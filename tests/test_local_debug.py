"""Owned-data privacy, bounded rotation and local export contract."""
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import zipfile

from local_debug import FILE_COUNT, MAX_EXPORT_BYTES, LocalDebugLog


class LocalDebugTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.log = LocalDebugLog(self.root / 'logs', version='0.4.9', max_bytes=1024)

    def read_export(self, config=None):
        output = self.log.export_zip(self.root / 'exports', config=config or {})
        with zipfile.ZipFile(output) as archive:
            self.assertEqual(set(archive.namelist()), {'manifest.json', 'events.jsonl'})
            return json.loads(archive.read('manifest.json')), archive.read('events.jsonl').decode()

    def test_default_off_has_no_files_or_persisted_opt_in(self):
        self.assertFalse(self.log.enabled)
        self.assertFalse(self.log.record('capture', capture_ms=1))
        self.assertFalse((self.root / 'logs').exists())
        self.log.set_enabled(True)
        self.assertFalse(LocalDebugLog(self.root / 'logs', version='0.4.9').enabled)
        self.log.set_enabled(False)
        before = self.log._path().read_bytes()
        self.log.record('capture', capture_ms=99)
        self.assertEqual(before, self.log._path().read_bytes())

    def test_allowlist_discards_private_text_and_nonfinite_values(self):
        self.log.set_enabled(True)
        secret = 'account-name TOKEN C:\\Users\\private\\secret.txt'
        self.log.record('capture', reason=secret, title=secret, path=secret, error=secret,
                        screenshot=secret, recognized_text=secret, backend=secret,
                        capture_ms=1.25, inference_ms=float('nan'), dpi=float('inf'),
                        generation=True, visible=True, width=1920, height=1080)
        manifest, events = self.read_export({'hero_auto': True, 'path': secret,
                                           'roi_percent': [15, 25, 70, 35], 'token': secret})
        self.assertNotIn(secret, events + json.dumps(manifest))
        value = json.loads(events.splitlines()[-1])
        self.assertEqual(value['capture_ms'], 1.25)
        self.assertEqual(value['width'], 1920)
        for key in ('reason', 'backend', 'inference_ms', 'dpi', 'generation'):
            self.assertNotIn(key, value)
        self.assertEqual(manifest['config'], {'hero_auto': True, 'roi_percent': [15, 25, 70, 35]})
        self.assertEqual(manifest['app_version'], '0.4.9')

    def test_identifiers_are_stable_only_for_same_launch_and_process_lifetime(self):
        first = self.log.identity(123, 456, 789)
        self.assertEqual(first, self.log.identity(123, 456, 789))
        self.assertNotEqual(first, self.log.identity(123, 456, 790))
        self.assertNotEqual(first, LocalDebugLog(self.root, version='0.4.9').identity(123, 456, 789))
        self.assertEqual(self.log.identity('private-name', 456), {})
        self.log.set_enabled(True)
        self.log.record('capture', **first)
        _, events = self.read_export()
        self.assertIn(first['window_id'], events)
        self.assertNotIn('"pid"', events)
        self.assertNotIn('"hwnd"', events)

    def test_rotation_and_repeated_export_are_bounded(self):
        self.log.set_enabled(True)
        for serial in range(200):
            self.log.record('capture', capture_ms=serial, serial=serial)
        logs = list((self.root / 'logs').iterdir())
        self.assertEqual(len(logs), FILE_COUNT)
        self.assertLessEqual(sum(path.stat().st_size for path in logs), FILE_COUNT * 1024)
        self.read_export()
        _, events = self.read_export()
        self.assertEqual(len(list((self.root / 'exports').iterdir())), 1)
        self.assertEqual(json.loads(events.splitlines()[-1])['serial'], 199)
        self.assertNotIn('"serial":0,', events)

    def test_export_revalidates_tampered_files_and_never_includes_neighbors(self):
        self.log.set_enabled(True)
        with self.log._path().open('a') as file:
            file.write(json.dumps({'event': 'capture', 'session': 'a' * 16,
                                   'path': 'PRIVATE_PATH', 'reason': 'RAW_EXCEPTION', 'capture_ms': 2}) + '\n')
            file.write('{bad json\n')
            file.write(json.dumps({'event': ['private']}) + '\n')
        (self.root / 'logs' / 'screenshot.png').write_bytes(b'PRIVATE_SCREENSHOT')
        (self.root / 'logs' / 'token.json').write_text('PRIVATE_TOKEN')
        _, events = self.read_export()
        self.assertNotIn('PRIVATE', events)
        self.assertNotIn('RAW_EXCEPTION', events)
        self.assertEqual(json.loads(events.splitlines()[-1])['capture_ms'], 2)

    def test_unknown_event_and_unsafe_version_are_not_exported(self):
        self.log.set_enabled(True)
        self.assertFalse(self.log.record('private-name', capture_ms=5))
        self.assertEqual(LocalDebugLog(self.root, version='C:/private/name').version, 'unknown')

    def test_io_failure_disables_logging_without_raw_error(self):
        with patch.object(Path, 'mkdir', side_effect=OSError('PRIVATE_PATH')):
            self.assertFalse(self.log.set_enabled(True))
        self.assertTrue(self.log.failed)
        self.assertFalse(self.log.enabled)

    def test_concurrent_records_are_valid_json_and_bounded(self):
        self.log.set_enabled(True)
        workers = [threading.Thread(target=lambda: [self.log.record('job', phase='completed', kind='ocr', generation=n) for n in range(40)]) for _ in range(4)]
        for worker in workers: worker.start()
        for worker in workers: worker.join()
        _, events = self.read_export()
        self.assertTrue(all(json.loads(line)['event'] == 'job' for line in events.splitlines()))
        self.assertLessEqual(sum(path.stat().st_size for path in (self.root / 'logs').iterdir()), 3 * 1024)

    def test_deeply_nested_corrupt_event_is_skipped_without_losing_valid_export(self):
        self.log=LocalDebugLog(self.root/'logs',version='0.4.9',max_bytes=16384)
        self.log.set_enabled(True)
        manifest,before=self.read_export()
        with self.log._path().open('a') as file:
            file.write('{"event":"capture","session":"aaaaaaaaaaaaaaaa","private":'+ '['*2000+'"PRIVATE_CONTENT"'+']'*2000+'}\n')
        original=json.loads
        def parse(value):
            if 'PRIVATE_CONTENT' in str(value):raise RecursionError('PRIVATE_PARSE_ERROR')
            return original(value)
        # Some OCR runtimes increase Python's recursion limit. Exercise the
        # decoder failure deterministically without depending on that limit.
        with patch('local_debug.json.loads',side_effect=parse):
            after_manifest,after=self.read_export()
        self.assertEqual(after_manifest,manifest)
        self.assertEqual(after,before)
        self.assertNotIn('PRIVATE_CONTENT',after)
        self.assertTrue((self.root/'exports'/'VGA-debug.zip').is_file())

    def test_huge_numeric_input_is_dropped_without_interrupting_logging(self):
        self.log.set_enabled(True)
        self.assertTrue(self.log.record('capture',capture_ms=10**1000,inference_ms=1))
        _,events=self.read_export()
        self.assertNotIn('capture_ms',json.loads(events.splitlines()[-1]))

    def test_export_budget_and_replace_failure_keep_previous_archive(self):
        self.log.set_enabled(True)
        self.read_export()
        target=self.root/'exports'/'VGA-debug.zip'
        before=target.read_bytes()
        self.assertLessEqual(len(before),MAX_EXPORT_BYTES)
        with patch.object(self.log,'_safe_events',return_value='x'*4000):
            with self.assertRaises(ValueError):self.read_export()
        self.assertEqual(target.read_bytes(),before)
        with patch('local_debug.EXPORT_OVERHEAD_BYTES',-4096):
            with self.assertRaises(ValueError):self.read_export()
        self.assertEqual(target.read_bytes(),before)
        with patch('local_debug.os.replace',side_effect=OSError('PRIVATE_PATH')):
            with self.assertRaises(OSError):self.read_export()
        self.assertEqual(target.read_bytes(),before)
        self.assertEqual([p.name for p in target.parent.iterdir()],['VGA-debug.zip'])

    def test_symlink_logs_are_rejected_without_reading_target(self):
        private = self.root / 'private'
        private.write_text('PRIVATE_CONTENT')
        self.log.directory.mkdir()
        try:self.log._path().symlink_to(private)
        except OSError as exc:
            if os.name=='nt' and getattr(exc,'winerror',None) in (1,50,1314):self.skipTest('Symlink creation is not available for this Windows account')
            raise
        self.assertFalse(self.log.set_enabled(True))
        with self.assertRaises(OSError): self.read_export()
        self.assertEqual(private.read_text(), 'PRIVATE_CONTENT')


if __name__ == '__main__':
    unittest.main()

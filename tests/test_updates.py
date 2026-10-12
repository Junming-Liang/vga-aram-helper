import copy
import hashlib
import json
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch, Mock

import updates
from update_network import UpdateError, json_bytes, runtime_state_dir


def executable(payload=b'test'):
    data = bytearray(128)
    data[:2] = b'MZ'
    data[60:64] = struct.pack('<I', 64)
    data[64:70] = b'PE\0\0\x64\x86'
    return bytes(data) + payload


def release_fixture():
    binary = executable()
    manifest = {'schema_version': 1, 'version': '0.4.0', 'platform': 'windows-x64',
                'url': updates.REPO_URL + '/releases/download/v0.4.0/vga-aram-helper-0.4.0-windows-x64.exe',
                'size': len(binary), 'sha256': hashlib.sha256(binary).hexdigest()}
    manifest_url = updates.REPO_URL + '/releases/download/v0.4.0/update-manifest.json'
    release = {'tag_name': 'v0.4.0', 'html_url': updates.REPO_URL + '/releases/tag/v0.4.0',
               'draft': False, 'prerelease': False, 'body': '测试发行说明',
               'assets': [{'name': 'update-manifest.json', 'browser_download_url': manifest_url},
                          {'name': 'vga-aram-helper-0.4.0-windows-x64.exe', 'browser_download_url': manifest['url'],
                           'size': len(binary), 'digest': 'sha256:' + manifest['sha256']}]}
    return binary, manifest, release, manifest_url


class UpdatesTests(unittest.TestCase):
    def setUp(self):
        self.binary, self.manifest, self.release, self.manifest_url = release_fixture()
        self.requested = []
        self.tmp = tempfile.TemporaryDirectory()
        # Windows tempfile may use an 8.3 path (RUNNER~1); production resolves
        # paths before comparing them. Keep the fixture canonical too so the
        # exact target assertions and replacement callback test the same path.
        self.root = Path(self.tmp.name).resolve()
        self.current = self.root / 'VGA-Aram-Helper.exe'
        self.current.write_bytes(executable(b'old'))

    def tearDown(self):
        self.tmp.cleanup()

    def fetch(self, url, *, max_bytes):
        self.requested.append(url)
        return json_bytes(self.release if url == updates.LATEST_API else self.manifest)

    def offered(self):
        return updates.check_for_update('0.3.0', fetcher=self.fetch)

    def downloader(self, manifest, destination):
        Path(destination).write_bytes(self.binary)

    def test_check_only_fetches_metadata_and_reports_unsigned(self):
        result = self.offered()
        self.assertEqual(result['state'], 'available')
        self.assertFalse(result['release']['signed'])
        self.assertEqual(self.requested, [updates.LATEST_API, self.manifest_url])
        self.assertEqual(len(list(self.root.iterdir())), 1)

    def test_current_does_not_fetch_manifest(self):
        result = updates.check_for_update('0.4.0', fetcher=self.fetch)
        self.assertEqual(result['state'], 'current')
        self.assertEqual(self.requested, [updates.LATEST_API])

    def test_no_downgrade_or_prerelease(self):
        self.assertEqual(updates.check_for_update('0.5.0', fetcher=self.fetch)['state'], 'current')
        self.release['prerelease'] = True
        self.assertEqual(self.offered()['state'], 'unavailable')

    def test_offline_is_honest_and_nonfatal(self):
        def fail(*args, **kwargs):
            raise OSError('offline')
        self.assertEqual(updates.check_for_update('0.3.0', fetcher=fail)['state'], 'unavailable')

    def test_requires_confirmation_before_download(self):
        with self.assertRaises(UpdateError):
            updates.prepare_update(self.offered()['release'], self.current, self.root, downloader=self.downloader)
        self.assertFalse((self.root / 'updates').exists())

    def test_preparation_preserves_executable_and_copies_trusted_updater(self):
        original = self.current.read_bytes()
        plan_path = updates.prepare_update(self.offered()['release'], self.current, self.root,
                                           confirmed=True, downloader=self.downloader)
        self.assertEqual(self.current.read_bytes(), original)
        self.assertEqual((plan_path.parent / 'updater.exe').read_bytes(), original)
        plan, job, target = updates._read_plan(plan_path)
        self.assertEqual(target, self.current)
        self.assertEqual(plan['manifest'], self.manifest)
        self.assertEqual((job / 'candidate.bin').read_bytes(), self.binary)

    def test_bad_download_removed_without_touching_current(self):
        original = self.current.read_bytes()
        def bad(manifest, dest):
            Path(dest).write_bytes(b'broken')
        with self.assertRaises(UpdateError):
            updates.prepare_update(self.offered()['release'], self.current, self.root, confirmed=True, downloader=bad)
        self.assertEqual(self.current.read_bytes(), original)
        self.assertFalse(list((self.root / 'updates').iterdir()))

    def test_other_repo_and_insecure_assets_rejected(self):
        for url in [self.manifest['url'].replace('Junming-Liang', 'Attacker'),
                    self.manifest['url'].replace('https:', 'http:'),
                    self.manifest['url'] + '?redirect=evil']:
            with self.subTest(url=url), self.assertRaises(UpdateError):
                updates.validate_manifest(dict(self.manifest, url=url))

    def test_wrong_architecture_not_allowed(self):
        with self.assertRaises(UpdateError):
            updates.validate_manifest(dict(self.manifest, platform='linux-x64'))
        bad = bytearray(self.binary)
        bad[68:70] = b'\x4c\x01'  # x86 instead of x64
        self.current.write_bytes(bad)
        manifest = dict(self.manifest, sha256=hashlib.sha256(bad).hexdigest())
        with self.assertRaises(UpdateError):
            updates._verify_exe(self.current, manifest)

    def test_api_checksum_disagreement_blocks_update(self):
        self.release['assets'][1]['digest'] = 'sha256:' + '0' * 64
        self.assertEqual(self.offered()['state'], 'unavailable')

    def test_relocated_or_wrong_release_page_rejected(self):
        self.release['html_url'] = 'https://github.com/attacker/repo/releases/tag/v0.4.0'
        self.assertEqual(self.offered()['state'], 'unavailable')

    def test_manifest_tag_and_size_validation(self):
        for change in ({'size': True}, {'size': 10**10}, {'sha256': '0'}, {'version': '../evil'}, {'schema_version': 2}):
            with self.subTest(change=change), self.assertRaises(UpdateError):
                updates.validate_manifest(dict(self.manifest, **change))
        with self.assertRaises(UpdateError):
            updates.validate_manifest(self.manifest, tag='v0.5.0')

    def test_source_mode_does_not_install_or_execute(self):
        self.assertEqual(updates.apply_update(self.root / 'missing'), 2)
        with self.assertRaises(UpdateError):
            updates.launch_update(self.root / 'missing')

    def test_target_lock_prevents_concurrent_installers(self):
        with updates._target_lock(self.current):
            with self.assertRaises(UpdateError):
                with updates._target_lock(self.current):
                    self.fail('Concurrent updater acquired the lock')
        with updates._target_lock(self.current):
            pass  # Released lock remains usable; file existence is not the lock.

    def test_busy_target_fails_without_replacing_files(self):
        path = self._prepared()
        original = self.current.read_bytes()
        with updates._target_lock(self.current), patch.object(updates, '_windows_frozen', return_value=True):
            self.assertEqual(updates.apply_update(path), 1)
        self.assertEqual(self.current.read_bytes(), original)
        self.assertIn('Another updater', json.loads((path.parent / 'result.json').read_text())['message'])

    def test_environment_can_isolate_state(self):
        with patch.dict(os.environ, {'VGA_STATE_DIR': str(self.root)}):
            self.assertEqual(runtime_state_dir(), self.root)

    def _prepared(self):
        return updates.prepare_update(self.offered()['release'], self.current, self.root,
                                      confirmed=True, downloader=self.downloader)

    def test_atomic_install_simulation_health_success(self):
        path = self._prepared()
        plan = json.loads(path.read_text())
        original = self.current.read_bytes()
        def spawn(command, **kwargs):
            self.assertEqual(kwargs['env']['PYINSTALLER_RESET_ENVIRONMENT'], '1')
            (path.parent / 'health.json').write_bytes(json_bytes({'token': plan['health_token'], 'version': '0.4.0'}))
            return Mock(poll=lambda: None)
        with patch.object(updates, '_windows_frozen', return_value=True), \
             patch.object(updates.sys, 'executable', str(path.parent / 'updater.exe')), \
             patch.object(updates, '_wait_for_parent'), \
             patch.object(updates.subprocess, 'Popen', side_effect=spawn):
            self.assertEqual(updates.apply_update(path), 0)
        self.assertEqual(self.current.read_bytes(), self.binary)
        self.assertEqual(self.current.with_name(self.current.name + '.previous').read_bytes(), original)
        self.assertEqual(json.loads((path.parent / 'result.json').read_text())['state'], 'installed')

    def test_atomic_install_simulation_rolls_back_crashed_app(self):
        path = self._prepared()
        original = self.current.read_bytes()
        with patch.object(updates, '_windows_frozen', return_value=True), \
             patch.object(updates.sys, 'executable', str(path.parent / 'updater.exe')), \
             patch.object(updates, '_wait_for_parent'), \
             patch.object(updates.subprocess, 'Popen', return_value=Mock(poll=lambda: 1)) as spawn:
            self.assertEqual(updates.apply_update(path), 1)
        self.assertEqual(self.current.read_bytes(), original)
        self.assertEqual(json.loads((path.parent / 'result.json').read_text())['state'], 'rolled_back')
        self.assertEqual(spawn.call_count, 2)

    def test_process_shutdown_errors_do_not_skip_rollback(self):
        path = self._prepared()
        original = self.current.read_bytes()
        child = Mock()
        child.poll.return_value = None
        child.wait.side_effect = OSError('wait failed')
        child.kill.side_effect = OSError('kill failed')
        with patch.object(updates, '_windows_frozen', return_value=True), \
             patch.object(updates.sys, 'executable', str(path.parent / 'updater.exe')), \
             patch.object(updates, '_wait_for_parent'), \
             patch.object(updates, '_healthy', side_effect=UpdateError('health failed')), \
             patch.object(updates.subprocess, 'Popen', return_value=child), \
             patch.object(updates.subprocess, 'run', side_effect=updates.subprocess.TimeoutExpired('taskkill', 20)):
            self.assertEqual(updates.apply_update(path), 1)
        self.assertEqual(self.current.read_bytes(), original)
        self.assertEqual(json.loads((path.parent / 'result.json').read_text())['state'], 'rolled_back')

    def test_backup_exists_before_target_replacement(self):
        path = self._prepared()
        original = self.current.read_bytes()
        replace = updates._replace_with_retry
        observed = []
        def inspect(source, target, **kwargs):
            if Path(target) == self.current:
                self.assertEqual(self.current.read_bytes(), original)
                self.assertEqual(self.current.with_name(self.current.name + '.previous').read_bytes(), original)
                observed.append(True)
                raise PermissionError('Target still busy')
            return replace(source, target, **kwargs)
        with patch.object(updates, '_windows_frozen', return_value=True), \
             patch.object(updates.sys, 'executable', str(path.parent / 'updater.exe')), \
             patch.object(updates, '_wait_for_parent'), \
             patch.object(updates, '_replace_with_retry', side_effect=inspect), \
             patch.object(updates.subprocess, 'Popen') as spawn:
            self.assertEqual(updates.apply_update(path), 1)
        self.assertTrue(observed)
        self.assertEqual(self.current.read_bytes(), original)
        spawn.assert_not_called()

    def test_health_marker_requires_matching_executable(self):
        path = self._prepared()
        marker = path.parent / 'health.json'
        self.current.write_bytes(self.binary)
        with patch.object(updates.sys, 'executable', str(self.current)), patch('app_version.__version__', '0.4.0'):
            updates.mark_update_healthy(marker)
        self.assertTrue(marker.exists())
        marker.unlink()
        with patch.object(updates.sys, 'executable', '/wrong/executable'), self.assertRaises(UpdateError):
            updates.mark_update_healthy(marker)
        self.assertFalse(marker.exists())

    def test_mislabeled_release_does_not_pass_health(self):
        path = self._prepared()
        self.current.write_bytes(self.binary)
        marker = path.parent / 'health.json'
        with patch.object(updates.sys, 'executable', str(self.current)), \
             patch('app_version.__version__', '0.3.0'), self.assertRaises(UpdateError):
            updates.mark_update_healthy(marker)
        self.assertFalse(marker.exists())

    def test_parent_still_running_prevents_mutation(self):
        path = self._prepared()
        original = self.current.read_bytes()
        with patch.object(updates, '_windows_frozen', return_value=True), \
             patch.object(updates.sys, 'executable', str(path.parent / 'updater.exe')), \
             patch.object(updates, '_wait_for_parent', side_effect=UpdateError('still running')):
            self.assertEqual(updates.apply_update(path), 1)
        self.assertEqual(self.current.read_bytes(), original)
        self.assertFalse(self.current.with_name(self.current.name + '.previous').exists())

    def test_plan_tampering_and_expiry(self):
        path = updates.prepare_update(self.offered()['release'], self.current, self.root,
                                      confirmed=True, downloader=self.downloader)
        plan = json.loads(path.read_text())
        for change in ({'target': str(self.root / 'unrelated.exe')}, {'parent_pid': -1}, {'created_at': 0},
                       {'health_token': 'bad'}, {'job': str(self.root)}):
            path.write_bytes(json_bytes(dict(plan, **change)))
            with self.subTest(change=change), self.assertRaises((UpdateError, OSError)):
                updates._read_plan(path)


if __name__ == '__main__':
    unittest.main()

"""Portable crossover protocol tests. Never invoke pip or native capture locally."""
import copy
import hashlib
import importlib.util
from importlib.metadata import PackagePath
import io
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import struct
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import probe_opencv_capture_crossover as crossover
from scripts import probe_opencv_parity as parity

spec = importlib.util.spec_from_file_location('crossover_parity_fixtures', ROOT / 'tests' / 'test_opencv_parity.py')
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)


def fake_wheel(folder, variant='A', changes=None):
    version = crossover.VERSIONS[variant]
    tag = 'cp37-abi3-win_amd64' if variant == 'A' else 'cp312-cp312-win_amd64'
    path = Path(folder) / ('opencv_python_headless-' + version + '-' + tag + '.whl')
    native = bytearray(2048)
    native[:2] = b'MZ'
    struct.pack_into('<I', native, 0x3c, 128)
    native[128:132] = b'PE\0\0'
    struct.pack_into('<H', native, 132, 0x8664)
    native[-1] = ord(variant)
    dist = 'opencv_python_headless-' + version + '.dist-info/'
    files = {'cv2/cv2.pyd': bytes(native), 'cv2/__init__.py': b'# fixture\n',
        'cv2/typing/__init__.py': b'# typing\n', 'cv2/py.typed': b'',
        'cv2/LICENSE.txt': b'license', 'cv2/LICENSE-3RD-PARTY.txt': b'licenses',
        dist + 'METADATA': ('Metadata-Version: 2.1\nName: opencv-python-headless\nVersion: ' + version + '\n').encode(),
        dist + 'WHEEL': ('Wheel-Version: 1.0\nRoot-Is-Purelib: false\nTag: ' + tag + '\n').encode(),
        dist + 'RECORD': b'fixture'}
    if changes:
        changes(files, dist)
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return path


def installed(wheel):
    return {'run': {'id': 'identity', 'pid': 500, 'created_unix': 10},
        'version': wheel['version'], 'cv_version': '5.0.0',
        'loaded_native': {'path': 'candidate/cv2.pyd', **wheel['native']},
        'package_inventory': copy.deepcopy(wheel['package_inventory']),
        'metadata_inventory': copy.deepcopy(wheel['metadata_inventory']),
        'dependencies': {name: 'pinned' for name in (*parity.DEPENDENCIES, 'PySide6-Essentials')},
        'cache_exclusion_rule': crossover.CACHE_RULE}


def completed_receipt(action='identity', label='initial', pid=500):
    return {'action': action, 'label': label, 'timeout_seconds': crossover.TIMEOUTS[action], 'pid': pid,
        'status': 'completed', 'returncode': 0, 'termination_attempts': [], 'child_exited': True,
        'owned_job_empty': True, 'job_closed': True, 'pipes_closed': True, 'reader_exited': True,
        'output_budget_exceeded': False, 'timed_out': False, 'errors': [],
        'log': {'path': 'fixed.txt', 'size': 0, 'sha256': hashlib.sha256(b'').hexdigest()}}


class CrossoverTests(unittest.TestCase):
    def test_official_and_custom_wheels_are_strictly_validated(self):
        with tempfile.TemporaryDirectory() as directory:
            for variant in ('A', 'B'):
                wheel = crossover.wheel_identity(fake_wheel(directory, variant), variant)
                self.assertEqual(wheel['version'], crossover.VERSIONS[variant])
                self.assertEqual(wheel['native']['size'], 2048)
                crossover.verify_installed(installed(wheel), wheel)

    def test_rejects_metadata_version_native_archive_path_and_budget(self):
        mutations = [
            lambda rows, dist: rows.__setitem__(dist + 'METADATA', b'Name: opencv-python-headless\nVersion: 1\n'),
            lambda rows, dist: rows.__setitem__('cv2/cv2.pyd', b'not-a-pe'),
            lambda rows, dist: rows.__setitem__('../escape', b'bad'),
            lambda rows, dist: rows.__setitem__('cv2/__pycache__/stale.pyc', b'bad'),
            lambda rows, dist: rows.__setitem__('outside/payload', b'bad'),
            lambda rows, dist: rows.__setitem__('CV2/__init__.py', b'case duplicate'),
            lambda rows, dist: rows.__setitem__(dist + 'WHEEL', b'Tag: cp312-cp312-linux_x86_64\nRoot-Is-Purelib: false\n'),
            lambda rows, dist: rows.__setitem__(dist + 'METADATA', b'Name: opencv-python-headless\nName: other\nVersion: 5.0.0.93\n'),
        ]
        with tempfile.TemporaryDirectory() as directory:
            for mutation in mutations:
                with self.subTest(mutation=mutation):
                    path = fake_wheel(directory, changes=mutation)
                    with self.assertRaises((RuntimeError, KeyError)):
                        crossover.wheel_identity(path, 'A')
            path = fake_wheel(directory)
            with patch.object(crossover, 'MAX_UNPACKED_BYTES', 100):
                with self.assertRaises(RuntimeError):
                    crossover.wheel_identity(path, 'A')

    def test_rejects_symlink_and_wrong_version_filename(self):
        with tempfile.TemporaryDirectory() as directory:
            path = fake_wheel(directory)
            linked = Path(directory) / 'link.whl'
            try:
                linked.symlink_to(path)
            except OSError:
                self.skipTest('Host cannot create test symlinks')
            with self.assertRaises(RuntimeError):
                crossover.wheel_identity(linked, 'A')
            path.rename(Path(directory) / 'opencv_python_headless-6.0.0-cp37-abi3-win_amd64.whl')
            with self.assertRaises(RuntimeError):
                crossover.wheel_identity(Path(directory) / 'opencv_python_headless-6.0.0-cp37-abi3-win_amd64.whl', 'A')

    def test_installed_inventory_rejects_stale_files_changed_metadata_and_native(self):
        with tempfile.TemporaryDirectory() as directory:
            wheel = crossover.wheel_identity(fake_wheel(directory), 'A')
            for kind in ('stale', 'missing', 'native', 'metadata', 'version', 'dependencies'):
                identity = installed(wheel)
                if kind == 'stale':
                    identity['package_inventory']['cv2/stale.py'] = {'size': 1, 'sha256': 'a' * 64}
                elif kind == 'missing':
                    del identity['package_inventory']['cv2/__init__.py']
                elif kind == 'native':
                    identity['loaded_native']['sha256'] = 'b' * 64
                elif kind == 'metadata':
                    next(iter(identity['metadata_inventory'].values()))['sha256'] = 'c' * 64
                elif kind == 'version':
                    identity['version'] = '5.0.0.93+other'
                else:
                    identity['dependencies']['Pillow'] = 'changed'
                with self.subTest(kind=kind), self.assertRaises(RuntimeError):
                    crossover.verify_installed(identity, wheel, dependencies=installed(wheel)['dependencies'])

    def test_only_explicit_pip_metadata_extras_are_allowed(self):
        with tempfile.TemporaryDirectory() as directory:
            wheel = crossover.wheel_identity(fake_wheel(directory), 'A')
            identity = installed(wheel)
            prefix = 'opencv_python_headless-' + wheel['version'] + '.dist-info/'
            identity['metadata_inventory'][prefix + 'INSTALLER'] = crossover.bytes_record(b'pip')
            identity['metadata_inventory'][prefix + 'RECORD'] = crossover.bytes_record(b'rewritten')
            crossover.verify_installed(identity, wheel)
            identity['metadata_inventory'][prefix + 'unexpected.py'] = crossover.bytes_record(b'stale')
            with self.assertRaises(RuntimeError):
                crossover.verify_installed(identity, wheel)

    def test_distribution_package_paths_preserve_posix_metadata_separator(self):
        name = 'opencv_python_headless-5.0.0.93.dist-info/METADATA'
        actual_package_path = PackagePath(name)
        self.assertIsInstance(actual_package_path, PurePosixPath)
        self.assertEqual(str(actual_package_path), name)
        self.assertTrue(str(actual_package_path).endswith('.dist-info/METADATA'))
        # Portable reproduction of the incorrect native-Windows-path fixture:
        # real importlib.metadata.PackagePath does not use this separator form.
        native_windows_path = PureWindowsPath(name)
        self.assertNotEqual(str(native_windows_path), str(actual_package_path))
        self.assertFalse(str(native_windows_path).endswith('.dist-info/METADATA'))

    def test_real_empty_requested_and_package_payload_are_valid_inventory(self):
        with tempfile.TemporaryDirectory() as directory:
            wheel_path = fake_wheel(directory)
            wheel = crossover.wheel_identity(wheel_path, 'A')
            site = Path(directory) / 'site-packages'
            with zipfile.ZipFile(wheel_path) as archive:
                archive.extractall(site)  # Locally generated test-only fixture.
                # Distribution.files returns PackagePath (PurePosixPath), including
                # on Windows. Native Path would turn METADATA's slash into '\\'.
                files = [PackagePath(name) for name in archive.namelist()]
                self.assertTrue(all(type(path) is PackagePath for path in files))
            metadata = site / ('opencv_python_headless-' + crossover.VERSIONS['A'] + '.dist-info')
            # pip._internal.operations.install.wheel._install_wheel creates
            # REQUESTED with `with open(requested_path, 'wb'): pass` for explicit installs.
            (metadata / 'REQUESTED').write_bytes(b'')
            (metadata / 'INSTALLER').write_bytes(b'pip\n')
            (metadata / 'RECORD').write_bytes(b'pip-rewritten-record')
            fake = SimpleNamespace(__file__=str(site / 'cv2' / '__init__.py'), __version__='5.0.0',
                _native=SimpleNamespace(__file__=str(site / 'cv2' / 'cv2.pyd')))
            distribution = Mock(metadata={'Name': 'opencv-python-headless'}, version=crossover.VERSIONS['A'], files=files)
            distribution.locate_file.side_effect = lambda path: site / path
            with patch.dict(sys.modules, {'cv2': fake}), patch.object(sys, 'prefix', directory), \
                    patch.object(crossover.importlib.metadata, 'distributions', return_value=[distribution]), \
                    patch.object(crossover.importlib.metadata, 'version', return_value='pinned'):
                identity = crossover.installed_identity()
                crossover.verify_installed(identity, wheel)
                self.assertEqual(identity['package_inventory']['cv2/py.typed'], crossover.bytes_record(b''))
                requested = metadata.name + '/REQUESTED'
                self.assertEqual(identity['metadata_inventory'][requested], crossover.bytes_record(b''))
                (site / 'cv2' / 'cv2.pyd').write_bytes(b'')
                with self.assertRaises(RuntimeError):
                    crossover.installed_identity()
            empty = Path(directory) / 'empty.json'
            empty.write_bytes(b'')
            with self.assertRaises(RuntimeError):
                crossover.read_json(empty)
            with self.assertRaises(RuntimeError):
                crossover.file_record(empty)
            with self.assertRaises(RuntimeError):
                crossover.wheel_identity(empty, 'A')

    def test_json_is_bounded_unique_finite_and_non_overwriting(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'proof.json'
            for raw in ('{"a":1,"a":2}', '{"a":NaN}'):
                path.write_text(raw)
                with self.assertRaises(ValueError):
                    crossover.read_json(path)
            with self.assertRaises(RuntimeError):
                crossover.write_json(path, {'a': 1})
            path.unlink()
            with patch.object(crossover, 'MAX_JSON_BYTES', 10):
                with self.assertRaises(RuntimeError):
                    crossover.write_json(path, {'large': 'x' * 20})

    def test_fixed_comparisons_include_reversal_and_same_variant_drift(self):
        baseline, candidate = fixtures.reports()
        blocks = []
        for index, label in enumerate(crossover.BLOCKS):
            report = copy.deepcopy(baseline if label[0] == 'A' else candidate)
            report['run'].update(id=label, process_nonce=label)
            fixtures.set_timing(report, 'capture_synthetic_window', (.12, .17, .125, .175)[index])
            blocks.append({'label': label, 'report': report})
        result = crossover.comparisons(blocks)
        self.assertEqual([row['kind'] for row in result], ['adjacent-forward', 'adjacent-reversal', 'adjacent-forward', 'official-drift', 'custom-drift'])
        self.assertLess(result[1]['performance']['capture_synthetic_window']['later_minus_earlier_seconds'], 0)
        self.assertNotIn('regression', result[0]['performance']['capture_synthetic_window'])
        self.assertNotIn('status', result[0])
        for bad in (blocks[:3], [blocks[0], blocks[2], blocks[1], blocks[3]], [blocks[0]] * 4):
            with self.assertRaises(RuntimeError):
                crossover.comparisons(bad)
        blocks[2]['report']['run']['process_nonce'] = blocks[0]['report']['run']['process_nonce']
        with self.assertRaises(RuntimeError):
            crossover.comparisons(blocks)

    def test_comparisons_reject_changed_helper_output_or_host(self):
        baseline, candidate = fixtures.reports()
        for kind in ('helper', 'output', 'host'):
            blocks = []
            for label in crossover.BLOCKS:
                report = copy.deepcopy(baseline if label[0] == 'A' else candidate)
                report['run'].update(id=label, process_nonce=label)
                blocks.append({'label': label, 'report': report})
            report = blocks[2]['report']
            if kind == 'helper':
                report['performance']['capture_synthetic_window']['capture_diagnostics']['identity_before_supplemental']['helpers']['one_shot']['binary']['sha256'] = 'f' * 64
            elif kind == 'output':
                report['api_results'][next(iter(report['api_results']))]['sha256'] = 'f' * 64
            else:
                report['host']['identity_sha256'] = 'f' * 64
            with self.subTest(kind=kind), self.assertRaises(RuntimeError):
                crossover.comparisons(blocks)

    def protocol_fixture(self, directory):
        baseline, candidate = fixtures.reports()
        for report in (baseline, candidate):
            for name in ('ocr_app_demo', 'hero_1080p'):
                report['performance'][name]['iterations_per_sample'] = 1
        wheels = {}
        for variant, report in (('A', baseline), ('B', candidate)):
            wheels[variant] = {'version': crossover.VERSIONS[variant],
                'wheel': {'path': variant + '.whl', 'size': 100, 'sha256': variant.lower() * 64},
                'native': {'size': report['native']['size'], 'sha256': report['native']['sha256']},
                'package_inventory': {}, 'metadata_inventory': {}, 'cache_exclusion_rule': crossover.CACHE_RULE}
        sources = {'commit': '1' * 40, 'files': {name: {'size': 100, 'sha256': '2' * 64} for name in parity.SOURCE_FILES}}
        identity = installed(wheels['A'])
        prepared = {'schema_version': 1, 'status': 'prepared', 'sources': sources,
            'official': wheels['A'], 'baseline_identity': identity,
            'baseline_identity_file': {'path': 'fixed', 'size': 1, 'sha256': 'a' * 64}}
        return wheels, sources, prepared, baseline, candidate

    def run_protocol(self, *, fail=None, unsafe=False, restoration_fail=False, malformed=False):
        context = tempfile.TemporaryDirectory()
        directory = Path(context.name)
        wheels, sources, prepared, baseline, candidate = self.protocol_fixture(directory)
        values = {str(directory / 'reports' / (crossover.PREFIX + 'prepared.json')): prepared}
        calls = []
        class FakeRunner:
            safe = True
            records = []
            def __call__(inner, action, label):
                calls.append((action, label))
                inner.records.append(completed_receipt(action, label))
                if (action, label) == fail or (restoration_fail and (action, label) == ('identity', 'restore')):
                    inner.safe = not unsafe
                    raise RuntimeError('original-failure' if label != 'restore' else 'restore-failure')
                if action == 'identity':
                    value = installed(wheels['A' if label[0] == 'A' else 'B'])
                    value['loaded_native']['path'] = ('baseline' if label[0] == 'A' else 'candidate') + '/cv2.pyd'
                    values[str(crossover.output_path(label + '-identity'))] = value
                if action == 'probe':
                    value = copy.deepcopy(baseline if label[0] == 'A' else candidate)
                    value['run'].update(id=label, process_nonce=label, pid=500)
                    values[str(crossover.output_path(label + '-probe'))] = {'run': {'pid': 500}} if malformed else value
                return inner.records[-1]
        saved = []
        fake = FakeRunner()
        fake.records = []
        with patch.object(crossover, 'ROOT', directory), patch.object(crossover, 'require_host'), \
                patch.object(crossover, 'source_binding', return_value=sources), \
                patch.object(crossover, 'expected_wheel', side_effect=lambda variant: variant), \
                patch.object(crossover, 'wheel_identity', side_effect=lambda path, variant: wheels[variant]), \
                patch.object(crossover, 'read_json', side_effect=lambda path: copy.deepcopy(values[str(path)])), \
                patch.object(crossover, 'file_record', return_value={'path': 'fixed', 'size': 1, 'sha256': 'a' * 64}), \
                patch.object(crossover, 'write_json', side_effect=lambda path, value: saved.append(copy.deepcopy(value))):
            result = crossover.run(fake)
        context.cleanup()
        return result, calls, saved

    def test_fixed_install_probe_order_and_unconditional_verified_B_restore(self):
        result, calls, saved = self.run_protocol()
        self.assertEqual(result['status'], 'completed', result['primary_error'])
        self.assertEqual([label for action, label in calls if action == 'install'], [*crossover.BLOCKS, 'restore'])
        self.assertEqual([label for action, label in calls if action == 'probe'], list(crossover.BLOCKS))
        self.assertEqual(calls[-3:], [('install', 'restore'), ('identity', 'restore'), ('check', 'restore')])
        self.assertEqual(result['restoration']['status'], 'verified')
        self.assertEqual(len(result['comparisons']), 5)
        self.assertEqual(len(saved), 1)
        self.assertNotIn('report', result['blocks'][0])
        self.assertEqual(len(result['blocks'][0]['capture']['samples_seconds']), 7)

    def test_failure_is_preserved_and_no_retry_or_later_block(self):
        result, calls, _ = self.run_protocol(fail=('probe', 'B1'))
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['primary_error']['message'], 'original-failure')
        self.assertEqual([label for action, label in calls if action == 'probe'], ['A1', 'B1'])
        self.assertEqual(result['restoration']['status'], 'verified')
        self.assertEqual([label for action, label in calls if action == 'install'], ['A1', 'B1', 'restore'])

    def test_unsafe_retirement_blocks_later_probes_and_restore(self):
        result, calls, _ = self.run_protocol(fail=('probe', 'A1'), unsafe=True)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['restoration']['status'], 'blocked')
        self.assertEqual(calls[-1], ('probe', 'A1'))
        self.assertNotIn(('install', 'restore'), calls)

    def test_restore_failure_is_separate_and_fails_successful_sequence(self):
        result, calls, _ = self.run_protocol(restoration_fail=True)
        self.assertEqual(result['status'], 'failed')
        self.assertIsNone(result['primary_error'])
        self.assertEqual(result['restoration']['status'], 'failed')
        result, calls, _ = self.run_protocol(fail=('probe', 'B1'), restoration_fail=True)
        self.assertEqual(result['primary_error']['message'], 'original-failure')
        self.assertEqual(result['restoration']['error']['message'], 'restore-failure')

    def test_probe_validation_rejects_sample_override(self):
        with tempfile.TemporaryDirectory() as directory:
            wheels, sources, prepared, baseline, candidate = self.protocol_fixture(directory)
            crossover.validate_block(baseline, wheels['A'], prepared)
            baseline['performance']['capture_synthetic_window']['warmups'] = 3
            with self.assertRaises(RuntimeError):
                crossover.validate_block(baseline, wheels['A'], prepared)

    def test_malformed_report_keeps_primary_failure_manifest_and_restore(self):
        result, calls, saved = self.run_protocol(malformed=True)
        self.assertEqual(result['status'], 'failed')
        self.assertIn('Full parity report validation failed', result['primary_error']['message'])
        self.assertEqual(result['restoration']['status'], 'verified')
        self.assertEqual(len(saved), 1)
        self.assertIsNone(result['blocks'][0]['capture'])

    def test_receipt_must_bind_report_to_the_launched_child(self):
        crossover.verify_receipt({'run': {'pid': 42}}, completed_receipt(pid=42))
        for receipt in ({'status': 'completed', 'pid': 43}, {'status': 'failed', 'pid': 42}, {'status': 'completed'}):
            with self.assertRaises(RuntimeError):
                crossover.verify_receipt({'run': {'pid': 42}}, receipt)

    def test_receipt_rejects_forged_success_and_float_report_pid(self):
        cases = [('returncode', 1), ('returncode', False), ('timed_out', True),
            ('output_budget_exceeded', True), ('errors', ['failure']), ('timeout_seconds', 600),
            ('termination_attempts', ['forced']), ('pipes_closed', 1), ('reader_exited', False)]
        for key, value in cases:
            receipt = completed_receipt(pid=42)
            receipt[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(RuntimeError):
                crossover.verify_receipt({'run': {'pid': 42}}, receipt)
        with self.assertRaises(RuntimeError):
            crossover.verify_receipt({'run': {'pid': 42.0}}, completed_receipt(pid=42))

    def runner_fixture(self, directory, *, live_reader=False, leaked=False, retirement_failure=False, output=b''):
        stdin, stdout = Mock(), Mock()
        stdin.closed = stdout.closed = False
        stdin.close.side_effect = lambda: setattr(stdin, 'closed', True)
        stdout.close.side_effect = lambda: setattr(stdout, 'closed', True)
        process = Mock(pid=42, returncode=0, stdin=stdin, stdout=stdout)
        process.poll.return_value = 0
        job = Mock()
        job.active.return_value = 0
        if leaked or retirement_failure:
            job.active.side_effect = [1, 0, 0]
        if retirement_failure:
            job.terminate.side_effect = RuntimeError('termination unavailable')
        reader = Mock()
        reader.is_alive.return_value = live_reader
        return stdin, stdout, process, job, reader

    def test_live_reader_failed_retirement_never_blocks_on_stdout_close(self):
        with tempfile.TemporaryDirectory() as directory:
            stdin, stdout, process, job, reader = self.runner_fixture(directory, live_reader=True, retirement_failure=True)
            with patch.object(crossover, 'ROOT', Path(directory)), patch.object(crossover, 'OwnedJob', return_value=job), \
                    patch.object(crossover.subprocess, 'Popen', return_value=process), \
                    patch.object(crossover.subprocess, 'CREATE_NO_WINDOW', 0, create=True), \
                    patch.object(crossover.threading, 'Thread', return_value=reader):
                runner = crossover.Runner()
                with self.assertRaises(crossover.CommandFailure):
                    runner('identity', 'initial')
                stdout.close.assert_not_called()
                self.assertFalse(runner.safe)
                self.assertFalse(runner.records[0]['reader_exited'])
                self.assertFalse(runner.records[0]['pipes_closed'])
                with self.assertRaises(RuntimeError):
                    runner('install', 'restore')
                self.assertEqual(len(runner.records), 1)

    def test_forced_job_cleanup_is_failure_even_when_all_processes_retire(self):
        with tempfile.TemporaryDirectory() as directory:
            stdin, stdout, process, job, reader = self.runner_fixture(directory, leaked=True)
            with patch.object(crossover, 'ROOT', Path(directory)), patch.object(crossover, 'OwnedJob', return_value=job), \
                    patch.object(crossover.subprocess, 'Popen', return_value=process), \
                    patch.object(crossover.subprocess, 'CREATE_NO_WINDOW', 0, create=True), \
                    patch.object(crossover.threading, 'Thread', return_value=reader):
                runner = crossover.Runner()
                with self.assertRaises(crossover.CommandFailure):
                    runner('probe', 'A1')
                self.assertTrue(runner.safe)
                self.assertEqual(runner.records[0]['termination_attempts'], ['remaining-owned-descendants'])
                self.assertEqual(runner.records[0]['pid'], 42)
                self.assertEqual(runner.records[0]['status'], 'failed')

    def test_normal_owned_command_records_complete_retirement_and_exact_pid(self):
        with tempfile.TemporaryDirectory() as directory:
            stdin, stdout, process, job, reader = self.runner_fixture(directory)
            with patch.object(crossover, 'ROOT', Path(directory)), patch.object(crossover, 'OwnedJob', return_value=job), \
                    patch.object(crossover.subprocess, 'Popen', return_value=process), \
                    patch.object(crossover.subprocess, 'CREATE_NO_WINDOW', 0, create=True), \
                    patch.object(crossover.threading, 'Thread', return_value=reader):
                runner = crossover.Runner()
                receipt = runner('identity', 'initial')
                self.assertTrue(runner.safe)
                self.assertEqual(receipt['pid'], 42)
                self.assertEqual(receipt['status'], 'completed')
                self.assertEqual(receipt['termination_attempts'], [])
                self.assertTrue(all(receipt[key] for key in ('child_exited', 'owned_job_empty', 'job_closed', 'pipes_closed', 'reader_exited')))
                stdin.write.assert_called_once_with(b'G')
                job.assign.assert_called_once_with(process)

    def test_stream_or_join_error_still_closes_job_and_forbids_replacement(self):
        for failure in ('close', 'join'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                stdin, stdout, process, job, reader = self.runner_fixture(directory)
                if failure == 'close':
                    stdout.close.side_effect = OSError('close failed')
                else:
                    reader.join.side_effect = RuntimeError('join failed')
                with patch.object(crossover, 'ROOT', Path(directory)), patch.object(crossover, 'OwnedJob', return_value=job), \
                        patch.object(crossover.subprocess, 'Popen', return_value=process), \
                        patch.object(crossover.subprocess, 'CREATE_NO_WINDOW', 0, create=True), \
                        patch.object(crossover.threading, 'Thread', return_value=reader):
                    runner = crossover.Runner()
                    with self.assertRaises(crossover.CommandFailure):
                        runner('identity', 'initial')
                    job.close.assert_called_once()
                    self.assertTrue(runner.records[0]['job_closed'])
                    self.assertFalse(runner.safe)
                    self.assertTrue(runner.records[0]['errors'])
                    self.assertIn('log', runner.records[0])

    def test_render_projection_preserves_every_performance_and_failure_field(self):
        baseline, candidate = fixtures.reports()
        baseline['failures'] = ['current failure']
        projected = crossover.report_projection(baseline)
        self.assertEqual(projected['performance'], baseline['performance'])
        self.assertEqual(projected['failures'], baseline['failures'])
        self.assertEqual(projected['run'], baseline['run'])
        self.assertEqual(projected['inputs'], baseline['inputs'])
        self.assertEqual(projected['api_results']['canonical_sha256'], parity.sha256(parity.canonical(baseline['api_results']).encode()))
        self.assertEqual(projected['opencv']['runtime'], baseline['opencv']['runtime'])
        self.assertNotEqual(projected['api_results'], baseline['api_results'])

    def test_failed_summary_preserves_malformed_raw_hash_and_prepare_error(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(crossover, 'ROOT', Path(directory)):
            path = crossover.output_path('prepared')
            crossover.write_json(path, {'schema_version': 1, 'status': 'failed', 'primary_error': {'message': 'prepare failed'}, 'commands': []})
            bad = crossover.output_path('A1-probe')
            bad.write_bytes(b'{bad-json')
            result = crossover.summarize()
            self.assertEqual(result['status'], 'failed')
            self.assertEqual(result['files']['prepared']['value']['primary_error']['message'], 'prepare failed')
            self.assertEqual(result['files']['A1-probe']['status'], 'invalid')
            self.assertEqual(result['files']['A1-probe']['raw_file']['sha256'], hashlib.sha256(b'{bad-json').hexdigest())
            self.assertEqual(result['files']['B2-probe']['status'], 'absent')

    def write_summary_fixture(self, directory):
        wheels, sources, prepared, baseline, candidate = self.protocol_fixture(directory)
        command = completed_receipt
        prepared['commands'] = [command('identity', 'prepare')]
        crossover.write_json(crossover.output_path('prepare-identity'), prepared['baseline_identity'])
        prepared['baseline_identity_file'] = crossover.file_record(crossover.output_path('prepare-identity'))
        crossover.write_json(crossover.output_path('prepared'), prepared)
        result = {'schema_version': 1, 'status': 'completed', 'fixed_order': list(crossover.BLOCKS),
            'excluded_from_adoption': True, 'primary_error': None, 'sources': sources,
            'prepared_file': crossover.file_record(crossover.output_path('prepared')), 'custom': wheels['B'],
            'commands': [command('identity', 'initial')], 'blocks': []}
        blocks = []
        for label in ('initial', *crossover.BLOCKS, 'restore'):
            identity = installed(wheels['A' if label.startswith('A') else 'B'])
            crossover.write_json(crossover.output_path(label + '-identity'), identity)
            if label in crossover.BLOCKS:
                report = copy.deepcopy(baseline if label[0] == 'A' else candidate)
                report['run'].update(id=label, process_nonce=label, pid=500)
                crossover.write_json(crossover.output_path(label + '-probe'), report)
                result['blocks'].append({'label': label, 'status': 'completed',
                    'report_file': crossover.file_record(crossover.output_path(label + '-probe')),
                    'installed_identity_file': crossover.file_record(crossover.output_path(label + '-identity'))})
                blocks.append({'label': label, 'report': report})
                result['commands'].extend([command(action, label) for action in ('install', 'identity', 'probe')])
        result['commands'].extend([command(action, 'restore') for action in ('install', 'identity', 'check')])
        result['initial_identity_file'] = crossover.file_record(crossover.output_path('initial-identity'))
        result['restoration'] = {'status': 'verified', 'identity_file': crossover.file_record(crossover.output_path('restore-identity'))}
        result['comparisons'] = crossover.comparisons(blocks)
        crossover.write_json(crossover.output_path('result'), result)
        return result

    def test_summary_revalidates_raw_reports_identities_order_and_retirement(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(crossover, 'ROOT', Path(directory)):
            self.write_summary_fixture(directory)
            summary = crossover.summarize()
            self.assertEqual(summary['status'], 'completed', summary['validation_errors'])
            self.assertLess(len(json.dumps(summary, ensure_ascii=True, indent=2).encode()), crossover.MAX_RENDER_BYTES)
            for label in crossover.BLOCKS:
                capture = summary['files'][label + '-probe']['value']['performance']['capture_synthetic_window']
                self.assertEqual(len(capture['samples_seconds']), 7)
                self.assertEqual(len(capture['capture_diagnostics']['authoritative_observations']), 27)
                self.assertEqual(len(capture['capture_diagnostics']['supplemental']['rows']), 6)
            path = crossover.output_path('A2-identity')
            value = json.loads(path.read_text())
            value['loaded_native']['sha256'] = 'e' * 64
            path.write_text(json.dumps(value))
            bad = crossover.summarize()
            self.assertEqual(bad['status'], 'failed')
            self.assertTrue(bad['validation_errors'])
            self.assertEqual(len(bad['files']['A2-probe']['value']['performance']['capture_synthetic_window']['samples_seconds']), 7)

    def test_summary_rejects_reordered_extra_commands_and_incomplete_block(self):
        for mutation in ('reorder', 'extra', 'block', 'prepare'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory, patch.object(crossover, 'ROOT', Path(directory)):
                self.write_summary_fixture(directory)
                path = crossover.output_path('prepared' if mutation == 'prepare' else 'result')
                value = json.loads(path.read_text())
                if mutation == 'reorder':
                    value['commands'][1], value['commands'][2] = value['commands'][2], value['commands'][1]
                elif mutation == 'extra':
                    value['commands'].append(completed_receipt('identity', 'initial'))
                elif mutation == 'block':
                    value['blocks'][2]['status'] = 'started'
                else:
                    value['commands'].append(completed_receipt('identity', 'prepare'))
                path.write_text(json.dumps(value))
                summary = crossover.summarize()
                self.assertEqual(summary['status'], 'failed')
                self.assertTrue(summary['validation_errors'])

    def test_failed_projection_keeps_nonduplicated_manifest_samples_and_identity(self):
        baseline, candidate = fixtures.reports()
        capture = baseline['performance']['capture_synthetic_window']
        identity = {'run': {'pid': 500}, 'loaded_native': {'sha256': 'a' * 64}}
        block = {'label': 'A1', 'capture': copy.deepcopy(capture), 'probe_run': baseline['run'],
                 'native': baseline['native'], 'runtime': baseline['opencv']['runtime'],
                 'imports': baseline['opencv']['imported_python_submodules']}
        comparison = {'earlier': 'A1', 'later': 'B1', 'performance': {'capture_synthetic_window': {
            'earlier_samples_seconds': capture['samples_seconds'], 'later_samples_seconds': capture['samples_seconds']}}}
        for state in ('absent', 'invalid', 'mismatch'):
            with self.subTest(state=state):
                raw_report = copy.deepcopy(baseline)
                raw_report['performance']['capture_synthetic_window']['samples_seconds'][0] = 0.99
                raw_report['run']['pid'] += 1
                raw_identity = {'run': {'pid': 501}}
                bundle = {'files': {
                    'prepared': {'status': 'read', 'value': {'baseline_identity': copy.deepcopy(identity)}},
                    'prepare-identity': {'status': state if state != 'mismatch' else 'read', 'value': raw_identity},
                    'result': {'status': 'read', 'value': {'blocks': [copy.deepcopy(block)], 'comparisons': [copy.deepcopy(comparison)]}},
                    'A1-probe': {'status': state if state != 'mismatch' else 'read', 'value': raw_report},
                    'B1-probe': {'status': 'read', 'value': candidate}}, 'status': 'failed'}
                projected = crossover.render_projection(bundle)
                kept = projected['files']['result']['value']['blocks'][0]
                self.assertEqual(kept['capture']['samples_seconds'], capture['samples_seconds'])
                self.assertEqual(kept['probe_run'], baseline['run'])
                self.assertEqual(projected['files']['prepared']['value']['baseline_identity'], identity)
                metric = projected['files']['result']['value']['comparisons'][0]['performance']['capture_synthetic_window']
                self.assertEqual(metric['earlier_samples_seconds'], capture['samples_seconds'])
                self.assertEqual(metric['later_samples_seconds'], capture['samples_seconds'])

    def test_projection_size_fails_visibly_without_truncating_fields(self):
        with patch.object(crossover, 'MAX_RENDER_BYTES', 1):
            with self.assertRaisesRegex(RuntimeError, 'rendered evidence exceeds'):
                crossover.render_projection({'files': {}, 'status': 'failed', 'error': 'complete error'})

    def test_start_gate_precedes_all_probe_and_install_work(self):
        with patch.object(sys, 'stdin', Mock(buffer=io.BytesIO(b''))), patch.object(crossover, 'require_host') as host, \
                patch.object(crossover.runpy, 'run_path') as run_path:
            with self.assertRaises(RuntimeError):
                crossover.child('probe', 'A1')
            host.assert_not_called()
            run_path.assert_not_called()

    def test_child_invokes_unchanged_full_probe_and_offline_exact_pip(self):
        with patch.object(sys, 'stdin', Mock(buffer=io.BytesIO(b'G'))), patch.object(crossover, 'require_host'), \
                patch.object(crossover.runpy, 'run_path') as run_path, patch.object(sys, 'argv', []):
            crossover.child('probe', 'A1')
            self.assertEqual(sys.argv[1:], ['generate', '--output', str(crossover.output_path('A1-probe')), '--samples', '7', '--warmups', '2'])
            run_path.assert_called_once_with(str(ROOT / 'scripts' / 'probe_opencv_parity.py'), run_name='__main__')
        with patch.object(sys, 'stdin', Mock(buffer=io.BytesIO(b'G'))), patch.object(crossover, 'require_host'), \
                patch.object(crossover, 'expected_wheel', return_value=Path('exact.whl')), \
                patch.object(crossover, 'wheel_identity'), patch.object(crossover.runpy, 'run_module') as module, patch.object(sys, 'argv', []):
            crossover.child('install', 'B1')
            self.assertEqual(sys.argv, ['pip', '--isolated', 'install', '--no-index', '--no-deps', '--no-cache-dir', '--force-reinstall', 'exact.whl'])
            module.assert_called_once_with('pip', run_name='__main__', alter_sys=True)

    def test_supervisor_does_not_import_native_packages(self):
        source = Path(crossover.__file__).read_text()
        import ast
        tree = ast.parse(source)
        top_imports = []
        for node in tree.body:
            if isinstance(node, ast.Import):
                top_imports.extend(alias.name.split('.')[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                top_imports.append(node.module.split('.')[0])
        self.assertFalse({'cv2', 'PIL', 'PySide6', 'numpy'} & set(top_imports))
        self.assertNotIn('setprofile', source)
        self.assertNotIn('CreateToolhelp32Snapshot', source)
        self.assertNotIn('NtQueryInformationProcess', source)

    def test_cli_has_no_path_version_sampling_or_threshold_overrides(self):
        for args in (['run', '--version', '1'], ['run', '--wheel', 'x'], ['run', '--samples', '8'], ['run', '--regression-ratio', '10']):
            with patch.object(sys, 'stderr', io.StringIO()), self.assertRaises(SystemExit) as error:
                crossover.main(args)
            self.assertEqual(error.exception.code, 2)


if __name__ == '__main__':
    unittest.main()

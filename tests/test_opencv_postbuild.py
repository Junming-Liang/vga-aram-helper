"""Portable postbuild protocol tests. Never invoke pip or native capture locally."""
import copy
import hashlib
import importlib.util
from importlib.metadata import PackagePath
from email.parser import Parser
import io
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import shutil
import struct
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import probe_opencv_postbuild as postbuild
from scripts import probe_opencv_parity as parity

spec = importlib.util.spec_from_file_location('postbuild_parity_fixtures', ROOT / 'tests' / 'test_opencv_parity.py')
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)


def fake_wheel(folder, variant='A', changes=None):
    version = postbuild.VERSIONS[variant]
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
        'version': wheel['version'], 'cv_version': '5.0.0', 'metadata_fields': copy.deepcopy(wheel['metadata_fields']),
        'loaded_native': {'path': 'candidate/cv2.pyd', **wheel['native']},
        'package_inventory': copy.deepcopy(wheel['package_inventory']),
        'metadata_inventory': copy.deepcopy(wheel['metadata_inventory']),
        'dependencies': {name: 'pinned' for name in (*parity.DEPENDENCIES, 'PySide6-Essentials')},
        'cache_exclusion_rule': postbuild.CACHE_RULE}


def completed_receipt(action='identity', label='initial', pid=500):
    return {'action': action, 'label': label, 'timeout_seconds': postbuild.TIMEOUTS[action], 'pid': pid,
        'status': 'completed', 'returncode': 0, 'termination_attempts': [], 'child_exited': True,
        'owned_job_empty': True, 'job_closed': True, 'pipes_closed': True, 'reader_exited': True,
        'output_budget_exceeded': False, 'timed_out': False, 'errors': [],
        'log': {'path': 'fixed.txt', 'size': 0, 'sha256': hashlib.sha256(b'').hexdigest()}}


class PostbuildTests(unittest.TestCase):
    def test_official_and_custom_wheels_are_strictly_validated(self):
        with tempfile.TemporaryDirectory() as directory:
            for variant in ('A', 'B'):
                wheel = postbuild.wheel_identity(fake_wheel(directory, variant), variant)
                self.assertEqual(wheel['version'], postbuild.VERSIONS[variant])
                self.assertEqual(wheel['native']['size'], 2048)
                postbuild.verify_installed(installed(wheel), wheel)

    def test_metadata_name_normalization_preserves_raw_fields_and_exact_hashes(self):
        names = ('opencv-python-headless', 'opencv_python_headless', 'OpenCV_Python_Headless',
                 'OPENCV-PYTHON-HEADLESS', 'opencv.python.headless', 'OpenCV-._Python__Headless')
        with tempfile.TemporaryDirectory() as directory:
            for name in names:
                with self.subTest(name=name):
                    def change(rows, dist):
                        rows[dist + 'METADATA'] = ('Name: ' + name + '\nVersion: ' + postbuild.VERSIONS['A'] + '\n').encode('ascii')
                    path = fake_wheel(directory, changes=change)
                    wheel = postbuild.wheel_identity(path, 'A')
                    self.assertEqual(wheel['metadata_fields'], {'raw_name': name, 'raw_version': postbuild.VERSIONS['A'],
                                                               'normalized_name': 'opencv-python-headless'})
                    postbuild.verify_installed(installed(wheel), wheel)
                    raw = ('Name: ' + name + '\nVersion: ' + postbuild.VERSIONS['A'] + '\n').encode('ascii')
                    metadata_name = 'opencv_python_headless-' + postbuild.VERSIONS['A'] + '.dist-info/METADATA'
                    self.assertEqual(wheel['metadata_inventory'][metadata_name], postbuild.bytes_record(raw))
            # Keep the unchanged builder's secondary custom-wheel checks intact.
            for name in ('opencv_python_headless', 'OpenCV-Python-Headless'):
                def change_custom(rows, dist):
                    rows[dist + 'METADATA'] = ('Name: ' + name + '\nVersion: ' + postbuild.VERSIONS['B'] + '\n').encode('ascii')
                wheel = postbuild.wheel_identity(fake_wheel(directory, 'B', change_custom), 'B')
                self.assertEqual(wheel['metadata_fields']['raw_name'], name)
                postbuild.verify_installed(installed(wheel), wheel)

    def test_metadata_rejects_invalid_ascii_names_duplicates_and_wrong_versions(self):
        names = ('', '-opencv-python-headless', 'opencv-python-headless.', 'opencv python headless',
                 'opencv/python/headless', 'opencv-python-headless\n', 'opencK-python-headless',
                 'opencv-python-headless\x00', 'opencv-python', 'opencv-python-headless-extra')
        for name in names:
            with self.subTest(name=name), self.assertRaises(RuntimeError):
                if '\n' in name:
                    postbuild.normalized_distribution_name(name)
                else:
                    postbuild.metadata_identity(Parser().parsestr('Name: ' + name + '\nVersion: 5.0.0.93\n'))
        invalid = ('Name: opencv-python-headless\nName: opencv_python_headless\nVersion: 5.0.0.93\n',
                   'Name: opencv-python-headless\nVersion: 5.0.0.93\nVersion: 5.0.0.93\n',
                   'Name: opencv-python-headless\nVersion: 5.0.0.93+wrong\n',
                   'Name: opencv-python-headless\nVersion: 5.0.0.93 \n',
                   'Name: opencv-python-headless\n', 'Version: 5.0.0.93\n')
        with tempfile.TemporaryDirectory() as directory:
            for text in invalid:
                with self.subTest(text=text):
                    with self.assertRaises(RuntimeError):
                        postbuild.metadata_identity(Parser().parsestr(text), expected_version=postbuild.VERSIONS['A'])
                    path = fake_wheel(directory, changes=lambda rows, dist: rows.__setitem__(dist + 'METADATA', text.encode()))
                    with self.assertRaises(RuntimeError):
                        postbuild.wheel_identity(path, 'A')

    def test_installed_distribution_name_rules_reject_conflicts_and_duplicate_headers(self):
        def distribution(name='OpenCV_Python_Headless', extra='', version='5.0.0.93'):
            return Mock(metadata=Parser().parsestr('Name: ' + name + '\nVersion: ' + version + '\n' + extra), version=version)
        for name in ('OpenCV_Python_Headless', 'opencv.python.headless', 'opencv--python__headless'):
            item = distribution(name)
            with patch.object(postbuild.importlib.metadata, 'distributions', return_value=[item]):
                selected, fields = postbuild.installed_opencv_distribution()
                self.assertIs(selected, item)
                self.assertEqual(fields['raw_name'], name)
        for items in ([distribution(), distribution()], [distribution(), distribution('opencv-python')],
                      [distribution(extra='Name: unrelated\n')], [distribution(extra='Version: 5.0.0.93\n')],
                      [distribution(version='5.0.0.93+wrong')], [distribution(name='opencv python headless')],
                      [distribution(name='unrelated', extra='Name: opencv-python-headless\n')]):
            with patch.object(postbuild.importlib.metadata, 'distributions', return_value=items), self.assertRaises(RuntimeError):
                postbuild.installed_opencv_distribution()

    def test_equivalent_names_do_not_relax_exact_installed_metadata_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            wheel = postbuild.wheel_identity(fake_wheel(directory), 'A')
            identity = installed(wheel)
            identity['metadata_fields']['raw_name'] = 'opencv_python_headless'
            with self.assertRaises(RuntimeError):
                postbuild.verify_installed(identity, wheel)
            identity = installed(wheel)
            key = 'opencv_python_headless-' + postbuild.VERSIONS['A'] + '.dist-info/METADATA'
            identity['metadata_inventory'][key] = postbuild.bytes_record(b'Name: opencv_python_headless\nVersion: 5.0.0.93\n')
            with self.assertRaises(RuntimeError):
                postbuild.verify_installed(identity, wheel)

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
                        postbuild.wheel_identity(path, 'A')
            path = fake_wheel(directory)
            with patch.object(postbuild, 'MAX_UNPACKED_BYTES', 100):
                with self.assertRaises(RuntimeError):
                    postbuild.wheel_identity(path, 'A')

    def test_rejects_symlink_and_wrong_version_filename(self):
        with tempfile.TemporaryDirectory() as directory:
            path = fake_wheel(directory)
            linked = Path(directory) / 'link.whl'
            try:
                linked.symlink_to(path)
            except OSError:
                self.skipTest('Host cannot create test symlinks')
            with self.assertRaises(RuntimeError):
                postbuild.wheel_identity(linked, 'A')
            path.rename(Path(directory) / 'opencv_python_headless-6.0.0-cp37-abi3-win_amd64.whl')
            with self.assertRaises(RuntimeError):
                postbuild.wheel_identity(Path(directory) / 'opencv_python_headless-6.0.0-cp37-abi3-win_amd64.whl', 'A')

    def test_installed_inventory_rejects_stale_files_changed_metadata_and_native(self):
        with tempfile.TemporaryDirectory() as directory:
            wheel = postbuild.wheel_identity(fake_wheel(directory), 'A')
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
                    postbuild.verify_installed(identity, wheel, dependencies=installed(wheel)['dependencies'])

    def test_only_explicit_pip_metadata_extras_are_allowed(self):
        with tempfile.TemporaryDirectory() as directory:
            wheel = postbuild.wheel_identity(fake_wheel(directory), 'A')
            identity = installed(wheel)
            prefix = 'opencv_python_headless-' + wheel['version'] + '.dist-info/'
            identity['metadata_inventory'][prefix + 'INSTALLER'] = postbuild.bytes_record(b'pip')
            identity['metadata_inventory'][prefix + 'RECORD'] = postbuild.bytes_record(b'rewritten')
            postbuild.verify_installed(identity, wheel)
            identity['metadata_inventory'][prefix + 'unexpected.py'] = postbuild.bytes_record(b'stale')
            with self.assertRaises(RuntimeError):
                postbuild.verify_installed(identity, wheel)

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
            wheel = postbuild.wheel_identity(wheel_path, 'A')
            site = Path(directory) / 'site-packages'
            with zipfile.ZipFile(wheel_path) as archive:
                archive.extractall(site)  # Locally generated test-only fixture.
                # Distribution.files returns PackagePath (PurePosixPath), including
                # on Windows. Native Path would turn METADATA's slash into '\\'.
                files = [PackagePath(name) for name in archive.namelist()]
                self.assertTrue(all(type(path) is PackagePath for path in files))
            metadata = site / ('opencv_python_headless-' + postbuild.VERSIONS['A'] + '.dist-info')
            # pip._internal.operations.install.wheel._install_wheel creates
            # REQUESTED with `with open(requested_path, 'wb'): pass` for explicit installs.
            (metadata / 'REQUESTED').write_bytes(b'')
            (metadata / 'INSTALLER').write_bytes(b'pip\n')
            (metadata / 'RECORD').write_bytes(b'pip-rewritten-record')
            fake = SimpleNamespace(__file__=str(site / 'cv2' / '__init__.py'), __version__='5.0.0',
                _native=SimpleNamespace(__file__=str(site / 'cv2' / 'cv2.pyd')))
            distribution = Mock(metadata=Parser().parsestr((metadata / 'METADATA').read_text()),
                                version=postbuild.VERSIONS['A'], files=files)
            distribution.locate_file.side_effect = lambda path: site / path
            with patch.dict(sys.modules, {'cv2': fake}), patch.object(sys, 'prefix', directory), \
                    patch.object(postbuild.importlib.metadata, 'distributions', return_value=[distribution]), \
                    patch.object(postbuild.importlib.metadata, 'version', return_value='pinned'):
                identity = postbuild.installed_identity()
                postbuild.verify_installed(identity, wheel)
                self.assertEqual(identity['package_inventory']['cv2/py.typed'], postbuild.bytes_record(b''))
                requested = metadata.name + '/REQUESTED'
                self.assertEqual(identity['metadata_inventory'][requested], postbuild.bytes_record(b''))
                (site / 'cv2' / 'cv2.pyd').write_bytes(b'')
                with self.assertRaises(RuntimeError):
                    postbuild.installed_identity()
            empty = Path(directory) / 'empty.json'
            empty.write_bytes(b'')
            with self.assertRaises(RuntimeError):
                postbuild.read_json(empty)
            with self.assertRaises(RuntimeError):
                postbuild.file_record(empty)
            with self.assertRaises(RuntimeError):
                postbuild.wheel_identity(empty, 'A')

    def test_json_is_bounded_unique_finite_and_non_overwriting(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'proof.json'
            for raw in ('{"a":1,"a":2}', '{"a":NaN}'):
                path.write_text(raw)
                with self.assertRaises(ValueError):
                    postbuild.read_json(path)
            with self.assertRaises(RuntimeError):
                postbuild.write_json(path, {'a': 1})
            path.unlink()
            with patch.object(postbuild, 'MAX_JSON_BYTES', 10):
                with self.assertRaises(RuntimeError):
                    postbuild.write_json(path, {'large': 'x' * 20})

    def test_one_fixed_forward_pair_preserves_every_original_sample(self):
        baseline, candidate = fixtures.reports()
        blocks = []
        for index, label in enumerate(postbuild.BLOCKS):
            report = copy.deepcopy(baseline if label[0] == 'A' else candidate)
            report['run'].update(id=label, process_nonce=label)
            fixtures.set_timing(report, 'capture_synthetic_window', (.12, .17)[index])
            blocks.append({'label': label, 'report': report})
        result = postbuild.comparisons(blocks)
        self.assertEqual([row['kind'] for row in result], ['adjacent-forward'])
        capture = result[0]['performance']['capture_synthetic_window']
        self.assertEqual(capture['earlier_samples_seconds'], [.12] * 7)
        self.assertEqual(capture['later_samples_seconds'], [.17] * 7)
        self.assertNotIn('regression', result[0]['performance']['capture_synthetic_window'])
        self.assertNotIn('status', result[0])
        for bad in (blocks[:1], list(reversed(blocks)), [blocks[0]] * 2, blocks * 2):
            with self.assertRaises(RuntimeError):
                postbuild.comparisons(bad)
        blocks[1]['report']['run']['process_nonce'] = blocks[0]['report']['run']['process_nonce']
        with self.assertRaises(RuntimeError):
            postbuild.comparisons(blocks)

    def test_comparisons_reject_changed_helper_output_or_host(self):
        baseline, candidate = fixtures.reports()
        for kind in ('helper', 'output', 'host'):
            blocks = []
            for label in postbuild.BLOCKS:
                report = copy.deepcopy(baseline if label[0] == 'A' else candidate)
                report['run'].update(id=label, process_nonce=label)
                blocks.append({'label': label, 'report': report})
            report = blocks[1]['report']
            if kind == 'helper':
                report['performance']['capture_synthetic_window']['capture_diagnostics']['identity_before_supplemental']['helpers']['one_shot']['binary']['sha256'] = 'f' * 64
            elif kind == 'output':
                report['api_results'][next(iter(report['api_results']))]['sha256'] = 'f' * 64
            else:
                report['host']['identity_sha256'] = 'f' * 64
            with self.subTest(kind=kind), self.assertRaises(RuntimeError):
                postbuild.comparisons(blocks)

    def protocol_fixture(self, directory):
        baseline, candidate = fixtures.reports()
        for report in (baseline, candidate):
            for name in ('ocr_app_demo', 'hero_1080p'):
                report['performance'][name]['iterations_per_sample'] = 1
        wheels = {}
        for variant, report in (('A', baseline), ('B', candidate)):
            wheels[variant] = {'version': postbuild.VERSIONS[variant],
                'metadata_fields': {'raw_name': 'opencv-python-headless', 'raw_version': postbuild.VERSIONS[variant],
                                    'normalized_name': 'opencv-python-headless'},
                'wheel': {'path': variant + '.whl', 'size': 100, 'sha256': variant.lower() * 64},
                'native': {'size': report['native']['size'], 'sha256': report['native']['sha256']},
                'package_inventory': {}, 'metadata_inventory': {}, 'cache_exclusion_rule': postbuild.CACHE_RULE}
        sources = {'commit': '1' * 40, 'files': {name: {'size': 100, 'sha256': '2' * 64} for name in parity.SOURCE_FILES}}
        identity = installed(wheels['A'])
        prepared = {'schema_version': 1, 'status': 'prepared', 'scope': postbuild.SCOPE, 'sources': sources,
            'official': wheels['A'], 'baseline_identity': identity,
            'baseline_identity_file': {'path': 'fixed', 'size': 1, 'sha256': 'a' * 64}}
        return wheels, sources, prepared, baseline, candidate

    def run_protocol(self, *, fail=None, unsafe=False, restoration_fail=False, malformed=False):
        context = tempfile.TemporaryDirectory()
        directory = Path(context.name)
        wheels, sources, prepared, baseline, candidate = self.protocol_fixture(directory)
        values = {str(directory / 'reports' / (postbuild.PREFIX + 'prepared.json')): prepared}
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
                    values[str(postbuild.output_path(label + '-identity'))] = value
                if action == 'probe':
                    value = copy.deepcopy(baseline if label[0] == 'A' else candidate)
                    value['run'].update(id=label, process_nonce=label, pid=500)
                    values[str(postbuild.output_path(label + '-probe'))] = {'run': {'pid': 500}} if malformed else value
                return inner.records[-1]
        saved = []
        fake = FakeRunner()
        fake.records = []
        with patch.object(postbuild, 'ROOT', directory), patch.object(postbuild, 'require_host'), \
                patch.object(postbuild, 'source_binding', return_value=sources), \
                patch.object(postbuild, 'expected_wheel', side_effect=lambda variant: variant), \
                patch.object(postbuild, 'wheel_identity', side_effect=lambda path, variant: wheels[variant]), \
                patch.object(postbuild, 'read_json', side_effect=lambda path: copy.deepcopy(values[str(path)])), \
                patch.object(postbuild, 'file_record', return_value={'path': 'fixed', 'size': 1, 'sha256': 'a' * 64}), \
                patch.object(postbuild, 'write_json', side_effect=lambda path, value: saved.append(copy.deepcopy(value))):
            result = postbuild.run(fake)
        context.cleanup()
        return result, calls, saved

    def test_fixed_install_probe_order_and_unconditional_verified_B_restore(self):
        result, calls, saved = self.run_protocol()
        self.assertEqual(result['status'], 'completed', result['primary_error'])
        self.assertEqual([label for action, label in calls if action == 'install'], [*postbuild.BLOCKS, 'restore'])
        self.assertEqual([label for action, label in calls if action == 'probe'], list(postbuild.BLOCKS))
        self.assertEqual(calls[-3:], [('install', 'restore'), ('identity', 'restore'), ('check', 'restore')])
        self.assertEqual(result['restoration']['status'], 'verified')
        self.assertEqual(len(result['comparisons']), 1)
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
            postbuild.validate_block(baseline, wheels['A'], prepared)
            baseline['performance']['capture_synthetic_window']['warmups'] = 3
            with self.assertRaises(RuntimeError):
                postbuild.validate_block(baseline, wheels['A'], prepared)

    def test_malformed_report_keeps_primary_failure_manifest_and_restore(self):
        result, calls, saved = self.run_protocol(malformed=True)
        self.assertEqual(result['status'], 'failed')
        self.assertIn('Full parity report validation failed', result['primary_error']['message'])
        self.assertEqual(result['restoration']['status'], 'verified')
        self.assertEqual(len(saved), 1)
        self.assertIsNone(result['blocks'][0]['capture'])

    def test_receipt_must_bind_report_to_the_launched_child(self):
        postbuild.verify_receipt({'run': {'pid': 42}}, completed_receipt(pid=42))
        for receipt in ({'status': 'completed', 'pid': 43}, {'status': 'failed', 'pid': 42}, {'status': 'completed'}):
            with self.assertRaises(RuntimeError):
                postbuild.verify_receipt({'run': {'pid': 42}}, receipt)

    def test_receipt_rejects_forged_success_and_float_report_pid(self):
        cases = [('returncode', 1), ('returncode', False), ('timed_out', True),
            ('output_budget_exceeded', True), ('errors', ['failure']), ('timeout_seconds', 600),
            ('termination_attempts', ['forced']), ('pipes_closed', 1), ('reader_exited', False)]
        for key, value in cases:
            receipt = completed_receipt(pid=42)
            receipt[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(RuntimeError):
                postbuild.verify_receipt({'run': {'pid': 42}}, receipt)
        with self.assertRaises(RuntimeError):
            postbuild.verify_receipt({'run': {'pid': 42.0}}, completed_receipt(pid=42))

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
            with patch.object(postbuild, 'ROOT', Path(directory)), patch.object(postbuild, 'OwnedJob', return_value=job), \
                    patch.object(postbuild.subprocess, 'Popen', return_value=process), \
                    patch.object(postbuild.subprocess, 'CREATE_NO_WINDOW', 0, create=True), \
                    patch.object(postbuild.threading, 'Thread', return_value=reader):
                runner = postbuild.Runner()
                with self.assertRaises(postbuild.CommandFailure):
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
            with patch.object(postbuild, 'ROOT', Path(directory)), patch.object(postbuild, 'OwnedJob', return_value=job), \
                    patch.object(postbuild.subprocess, 'Popen', return_value=process), \
                    patch.object(postbuild.subprocess, 'CREATE_NO_WINDOW', 0, create=True), \
                    patch.object(postbuild.threading, 'Thread', return_value=reader):
                runner = postbuild.Runner()
                with self.assertRaises(postbuild.CommandFailure):
                    runner('probe', 'A1')
                self.assertTrue(runner.safe)
                self.assertEqual(runner.records[0]['termination_attempts'], ['remaining-owned-descendants'])
                self.assertEqual(runner.records[0]['pid'], 42)
                self.assertEqual(runner.records[0]['status'], 'failed')

    def test_normal_owned_command_records_complete_retirement_and_exact_pid(self):
        with tempfile.TemporaryDirectory() as directory:
            stdin, stdout, process, job, reader = self.runner_fixture(directory)
            with patch.object(postbuild, 'ROOT', Path(directory)), patch.object(postbuild, 'OwnedJob', return_value=job), \
                    patch.object(postbuild.subprocess, 'Popen', return_value=process), \
                    patch.object(postbuild.subprocess, 'CREATE_NO_WINDOW', 0, create=True), \
                    patch.object(postbuild.threading, 'Thread', return_value=reader):
                runner = postbuild.Runner()
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
                with patch.object(postbuild, 'ROOT', Path(directory)), patch.object(postbuild, 'OwnedJob', return_value=job), \
                        patch.object(postbuild.subprocess, 'Popen', return_value=process), \
                        patch.object(postbuild.subprocess, 'CREATE_NO_WINDOW', 0, create=True), \
                        patch.object(postbuild.threading, 'Thread', return_value=reader):
                    runner = postbuild.Runner()
                    with self.assertRaises(postbuild.CommandFailure):
                        runner('identity', 'initial')
                    job.close.assert_called_once()
                    self.assertTrue(runner.records[0]['job_closed'])
                    self.assertFalse(runner.safe)
                    self.assertTrue(runner.records[0]['errors'])
                    self.assertIn('log', runner.records[0])

    def test_render_projection_preserves_every_performance_and_failure_field(self):
        baseline, candidate = fixtures.reports()
        baseline['failures'] = ['current failure']
        projected = postbuild.report_projection(baseline)
        self.assertEqual(projected['performance'], baseline['performance'])
        self.assertEqual(projected['failures'], baseline['failures'])
        self.assertEqual(projected['run'], baseline['run'])
        self.assertEqual(projected['inputs'], baseline['inputs'])
        self.assertEqual(projected['api_results']['canonical_sha256'], parity.sha256(parity.canonical(baseline['api_results']).encode()))
        self.assertEqual(projected['opencv']['runtime'], baseline['opencv']['runtime'])
        self.assertNotEqual(projected['api_results'], baseline['api_results'])

    def test_failed_summary_preserves_malformed_raw_hash_and_prepare_error(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(postbuild, 'ROOT', Path(directory)):
            path = postbuild.output_path('prepared')
            postbuild.write_json(path, {'schema_version': 1, 'status': 'failed', 'primary_error': {'message': 'prepare failed'}, 'commands': []})
            bad = postbuild.output_path('A1-probe')
            bad.write_bytes(b'{bad-json')
            result = postbuild.summarize()
            self.assertEqual(result['status'], 'failed')
            self.assertEqual(result['files']['prepared']['value']['primary_error']['message'], 'prepare failed')
            self.assertEqual(result['files']['A1-probe']['status'], 'invalid')
            self.assertEqual(result['files']['A1-probe']['raw_file']['sha256'], hashlib.sha256(b'{bad-json').hexdigest())
            self.assertEqual(result['files']['B1-probe']['status'], 'absent')

    def write_summary_fixture(self, directory, *, candidate_seconds=None):
        wheels, sources, prepared, baseline, candidate = self.protocol_fixture(directory)
        if candidate_seconds is not None:
            fixtures.set_timing(candidate, 'capture_synthetic_window', candidate_seconds)
        command = completed_receipt
        prepared['commands'] = [command('identity', 'prepare')]
        postbuild.write_json(postbuild.output_path('prepare-identity'), prepared['baseline_identity'])
        prepared['baseline_identity_file'] = postbuild.file_record(postbuild.output_path('prepare-identity'))
        postbuild.write_json(postbuild.output_path('prepared'), prepared)
        result = {'schema_version': 1, 'status': 'completed', 'scope': postbuild.SCOPE, 'fixed_order': list(postbuild.BLOCKS),
            'excluded_from_adoption': False, 'primary_error': None, 'sources': sources,
            'prepared_file': postbuild.file_record(postbuild.output_path('prepared')), 'custom': wheels['B'],
            'commands': [command('identity', 'initial')], 'blocks': []}
        build_path = Path(directory) / 'reports' / 'windows-opencv-build.json'
        postbuild.write_json(build_path, {'fixture': 'build provenance is validated by expected_wheel in production'})
        result['build_report_file'] = postbuild.file_record(build_path)
        blocks = []
        for label in ('initial', *postbuild.BLOCKS, 'restore'):
            identity = installed(wheels['A' if label.startswith('A') else 'B'])
            identity['loaded_native']['path'] = ('baseline' if label.startswith('A') else 'candidate') + '/cv2.pyd'
            postbuild.write_json(postbuild.output_path(label + '-identity'), identity)
            if label in postbuild.BLOCKS:
                report = copy.deepcopy(baseline if label[0] == 'A' else candidate)
                report['run'].update(id=label, process_nonce=label, pid=500)
                postbuild.write_json(postbuild.output_path(label + '-probe'), report)
                result['blocks'].append({'label': label, 'status': 'completed',
                    'report_file': postbuild.file_record(postbuild.output_path(label + '-probe')),
                    'installed_identity_file': postbuild.file_record(postbuild.output_path(label + '-identity'))})
                blocks.append({'label': label, 'report': report})
                result['commands'].extend([command(action, label) for action in ('install', 'identity', 'probe')])
        result['commands'].extend([command(action, 'restore') for action in ('install', 'identity', 'check')])
        result['initial_identity_file'] = postbuild.file_record(postbuild.output_path('initial-identity'))
        restored = postbuild.read_json(postbuild.output_path('restore-identity'))
        result['restoration'] = {'status': 'verified', 'identity_file': postbuild.file_record(postbuild.output_path('restore-identity')),
                                 'native': restored['loaded_native'], 'dependencies': restored['dependencies']}
        result['comparisons'] = postbuild.comparisons(blocks)
        postbuild.write_json(postbuild.output_path('result'), result)
        return result

    def test_summary_revalidates_raw_reports_identities_order_and_retirement(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(postbuild, 'ROOT', Path(directory)):
            self.write_summary_fixture(directory)
            summary = postbuild.summarize()
            self.assertEqual(summary['status'], 'completed', summary['validation_errors'])
            self.assertLess(len(json.dumps(summary, ensure_ascii=True, indent=2).encode()), postbuild.MAX_RENDER_BYTES)
            for label in postbuild.BLOCKS:
                capture = summary['files'][label + '-probe']['value']['performance']['capture_synthetic_window']
                self.assertEqual(len(capture['samples_seconds']), 7)
                self.assertEqual(len(capture['capture_diagnostics']['authoritative_observations']), 27)
                self.assertEqual(len(capture['capture_diagnostics']['supplemental']['rows']), 6)
            path = postbuild.output_path('B1-identity')
            value = json.loads(path.read_text())
            value['loaded_native']['sha256'] = 'e' * 64
            path.write_text(json.dumps(value))
            bad = postbuild.summarize()
            self.assertEqual(bad['status'], 'failed')
            self.assertTrue(bad['validation_errors'])
            self.assertEqual(len(bad['files']['B1-probe']['value']['performance']['capture_synthetic_window']['samples_seconds']), 7)

    def test_coherently_rehashed_float_preparation_pid_cannot_match_embedded_integer(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(postbuild, 'ROOT', Path(directory)):
            self.write_summary_fixture(directory)
            path = postbuild.output_path('prepare-identity')
            raw = postbuild.read_json(path); raw['run']['pid'] = float(raw['run']['pid'])
            path.write_text(json.dumps(raw), encoding='utf-8')
            prepared_path = postbuild.output_path('prepared')
            prepared = postbuild.read_json(prepared_path)
            prepared['baseline_identity_file'] = postbuild.file_record(path)
            prepared_path.write_text(json.dumps(prepared), encoding='utf-8')
            result_path = postbuild.output_path('result')
            result = postbuild.read_json(result_path)
            result['prepared_file'] = postbuild.file_record(prepared_path)
            result_path.write_text(json.dumps(result), encoding='utf-8')
            bundle = postbuild.validate_evidence()
            self.assertEqual(bundle['status'], 'failed')
            self.assertIn('baseline identity payload changed', str(bundle['validation_errors']))

    def test_source_and_recomputed_comparison_bindings_are_type_sensitive(self):
        for mutation in ('source', 'comparison'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory, patch.object(postbuild, 'ROOT', Path(directory)):
                self.write_summary_fixture(directory)
                path = postbuild.output_path('result'); value = postbuild.read_json(path)
                if mutation == 'source':
                    row = next(iter(value['sources']['files'].values()))
                    row['size'] = float(row['size'])
                else:
                    row = next(iter(value['comparisons'][0]['performance'].values()))
                    self.assertEqual(row['later_over_earlier'], 1.0)
                    row['later_over_earlier'] = 1
                path.write_text(json.dumps(value), encoding='utf-8')
                self.assertEqual(postbuild.validate_evidence()['status'], 'failed')

    def test_installed_native_and_metadata_inventory_records_are_type_sensitive(self):
        with tempfile.TemporaryDirectory() as directory:
            wheel = postbuild.wheel_identity(fake_wheel(directory), 'A')
            for mutation in ('native', 'metadata'):
                value = installed(wheel)
                row = value['loaded_native'] if mutation == 'native' else next(
                    row for name, row in value['metadata_inventory'].items() if name.endswith('/METADATA'))
                row['size'] = float(row['size'])
                with self.subTest(mutation=mutation), self.assertRaises(RuntimeError):
                    postbuild.verify_installed(value, wheel)

    def test_summary_rejects_reordered_extra_commands_and_incomplete_block(self):
        for mutation in ('reorder', 'extra', 'block', 'prepare'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory, patch.object(postbuild, 'ROOT', Path(directory)):
                self.write_summary_fixture(directory)
                path = postbuild.output_path('prepared' if mutation == 'prepare' else 'result')
                value = json.loads(path.read_text())
                if mutation == 'reorder':
                    value['commands'][1], value['commands'][2] = value['commands'][2], value['commands'][1]
                elif mutation == 'extra':
                    value['commands'].append(completed_receipt('identity', 'initial'))
                elif mutation == 'block':
                    value['blocks'][1]['status'] = 'started'
                else:
                    value['commands'].append(completed_receipt('identity', 'prepare'))
                path.write_text(json.dumps(value))
                summary = postbuild.summarize()
                self.assertEqual(summary['status'], 'failed')
                self.assertTrue(summary['validation_errors'])

    def export_fixture(self, directory):
        bundle = postbuild.validate_evidence()
        self.assertEqual(bundle['status'], 'completed', bundle['validation_errors'])
        prepared = bundle['files']['prepared']['value']
        custom = bundle['files']['result']['value']['custom']
        with patch.object(postbuild, 'require_host'), \
                patch.object(postbuild, 'source_binding', return_value=prepared['sources']), \
                patch.object(postbuild, 'expected_wheel', side_effect=lambda variant: variant), \
                patch.object(postbuild, 'wheel_identity', side_effect=lambda path, variant: prepared['official'] if variant == 'A' else custom):
            return postbuild.export()

    def test_exact_standard_exports_and_small_receipt_are_independently_revalidated(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(postbuild, 'ROOT', Path(directory)):
            result = self.write_summary_fixture(directory)
            self.assertEqual(len(result['commands']), 10)
            with patch.object(parity, 'compare_reports', wraps=parity.compare_reports) as compare:
                receipt = self.export_fixture(directory)
                self.assertEqual(compare.call_count, 1)
                self.assertEqual(compare.call_args.kwargs, {})
            self.assertEqual(receipt['status'], 'passed')
            self.assertLess(postbuild.output_path('export').stat().st_size, 10_000)
            for key, label in (('baseline', 'A1-probe'), ('candidate', 'B1-probe')):
                self.assertEqual((Path(directory) / 'reports' / postbuild.EXPORT_NAMES[key]).read_bytes(),
                                 postbuild.output_path(label).read_bytes())
            bundle, verified = postbuild.validate_export(Path(directory) / 'reports')
            self.assertEqual(verified, receipt)
            self.assertEqual(bundle['files']['result']['value']['restoration']['status'], 'verified')
            self.assertEqual(len(postbuild.EVIDENCE_NAMES), 10)

    def test_pure_validators_never_launch_install_capture_export_or_native_code(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(postbuild, 'ROOT', Path(directory)):
            self.write_summary_fixture(directory)
            self.export_fixture(directory)
            before = {p.name: p.read_bytes() for p in (Path(directory) / 'reports').iterdir()}
            with patch.object(postbuild, 'Runner', side_effect=AssertionError('runner')), \
                    patch.object(postbuild, 'export', side_effect=AssertionError('export')), \
                    patch.object(postbuild, 'require_host', side_effect=AssertionError('host')), \
                    patch.object(postbuild, 'source_binding', side_effect=AssertionError('checkout')), \
                    patch.object(postbuild, 'expected_wheel', side_effect=AssertionError('wheel')), \
                    patch.object(postbuild.subprocess, 'Popen', side_effect=AssertionError('process')), \
                    patch.object(postbuild.runpy, 'run_path', side_effect=AssertionError('native')):
                bundle, receipt = postbuild.validate_export()
            self.assertEqual(bundle['status'], 'completed')
            self.assertEqual(receipt['status'], 'passed')
            self.assertEqual(before, {p.name: p.read_bytes() for p in (Path(directory) / 'reports').iterdir()})

    def test_relative_and_relocated_fixed_evidence_preserves_original_receipt_paths(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as relocated, \
                patch.object(postbuild, 'ROOT', Path(directory)):
            self.write_summary_fixture(directory)
            original = self.export_fixture(directory)
            previous = Path.cwd()
            try:
                os.chdir(directory)
                bundle, receipt = postbuild.validate_export('reports')
                self.assertEqual(bundle['status'], 'completed')
                self.assertEqual(receipt, original)
            finally:
                os.chdir(previous)
            destination = Path(relocated) / 'reports'
            shutil.copytree(Path(directory) / 'reports', destination)
            # Remove the producer files, proving no recorded original path is read.
            shutil.rmtree(Path(directory) / 'reports')
            bundle, receipt = postbuild.validate_export(destination)
            self.assertEqual(bundle['status'], 'completed')
            self.assertEqual(receipt, original)

    def test_fixed_record_binding_rejects_wrong_name_shape_hash_size_and_types(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'windows-opencv-build.json'; path.write_bytes(b'{}\n')
            good = postbuild.file_record(path)
            for old_path in (str(path), 'D:\\a\\repository\\reports\\windows-opencv-build.json'):
                record = dict(good, path=old_path)
                self.assertEqual(postbuild.verify_record(record, path), good)
            cases = [('path', 'windows-opencv-build.json'), ('path', '/tmp/other.json'),
                     ('path', '/tmp/../windows-opencv-build.json'), ('path', '/tmp/windows-opencv-build.json/'),
                     ('path', 'D:\\a\\..\\windows-opencv-build.json'),
                     ('path', '/tmp/\x00/windows-opencv-build.json'), ('size', True), ('size', 3.0), ('size', 4),
                     ('sha256', 'e' * 64), ('sha256', 'x' * 64), ('sha256', 'A' * 64), ('sha256', 'a' * 63)]
            for key, value in cases:
                with self.subTest(key=key, value=value), self.assertRaises(RuntimeError):
                    postbuild.verify_record(dict(good, **{key: value}), path)
            target = Path(directory) / 'target'; target.write_bytes(path.read_bytes())
            path.unlink()
            try:
                path.symlink_to(target)
            except OSError:
                self.skipTest('Host cannot create test symlinks')
            with self.assertRaisesRegex(RuntimeError, 'Linked/reparse'):
                postbuild.verify_record(good, path)

    def test_selected_evidence_directory_symlink_is_rejected_before_resolution(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(postbuild, 'ROOT', Path(directory)):
            self.write_summary_fixture(directory)
            self.export_fixture(directory)
            link = Path(directory) / 'linked-reports'
            try:
                link.symlink_to(Path(directory) / 'reports', target_is_directory=True)
            except OSError:
                self.skipTest('Host cannot create test symlinks')
            for validator in (postbuild.validate_evidence, postbuild.validate_export):
                with self.subTest(validator=validator.__name__), self.assertRaisesRegex(RuntimeError, 'Linked/reparse directory'):
                    validator(link)

    def test_exports_require_unchanged_bound_sources_exact_wheels_and_build_proof(self):
        for mutation in ('source', 'wheel', 'build', 'late-source'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory, patch.object(postbuild, 'ROOT', Path(directory)):
                result = self.write_summary_fixture(directory)
                prepared = postbuild.read_json(postbuild.output_path('prepared'))
                source = copy.deepcopy(prepared['sources'])
                custom = copy.deepcopy(result['custom'])
                if mutation == 'source':
                    source['commit'] = 'e' * 40
                elif mutation == 'wheel':
                    custom['native']['sha256'] = 'e' * 64
                elif mutation == 'build':
                    path = Path(directory) / 'reports' / 'windows-opencv-build.json'
                    path.write_bytes(path.read_bytes() + b'\n')
                with patch.object(postbuild, 'require_host'), \
                        patch.object(postbuild, 'source_binding', side_effect=[source, {}] if mutation == 'late-source' else None, return_value=source), \
                        patch.object(postbuild, 'expected_wheel', side_effect=lambda variant: variant), \
                        patch.object(postbuild, 'wheel_identity', side_effect=lambda path, variant: prepared['official'] if variant == 'A' else custom), \
                        self.assertRaises(RuntimeError):
                    postbuild.export()
                self.assertFalse(postbuild.output_path('export').exists())
                with self.assertRaises((RuntimeError, FileNotFoundError)):
                    postbuild.validate_export()

    def test_host_requires_approved_manual_main_windows_runner(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(postbuild, 'ROOT', Path(directory)), \
                patch.object(postbuild.sys, 'platform', 'win32'), patch.object(postbuild.sys, 'version_info', (3, 12, 10)), \
                patch.object(postbuild.struct, 'calcsize', return_value=8):
            environment = {'GITHUB_ACTIONS': 'true', 'RUNNER_ENVIRONMENT': 'github-hosted',
                           'GITHUB_EVENT_NAME': 'workflow_dispatch', 'GITHUB_REPOSITORY': 'Junming-Liang/vga-aram-helper',
                           'GITHUB_REF': 'refs/heads/main', 'GITHUB_WORKSPACE': directory}
            with patch.dict(postbuild.os.environ, environment, clear=True):
                postbuild.require_host()
                for key, value in (('GITHUB_ACTIONS', 'false'), ('RUNNER_ENVIRONMENT', 'self-hosted'),
                                   ('GITHUB_EVENT_NAME', 'push'), ('GITHUB_REPOSITORY', 'other/repo'),
                                   ('GITHUB_REF', 'refs/heads/experiment/capture-opencv-crossover'),
                                   ('GITHUB_WORKSPACE', str(Path(directory).parent))):
                    with self.subTest(key=key), patch.dict(postbuild.os.environ, {key: value}), self.assertRaises(RuntimeError):
                        postbuild.require_host()

    def test_source_binding_exports_exact_fixed_inventory_and_commit(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(postbuild, 'ROOT', Path(directory)):
            for name in postbuild.SOURCE_FILES:
                path = Path(directory) / name; path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes((name + '\n').encode('utf-8'))
            with patch.object(postbuild.subprocess, 'check_output', return_value='1' * 40 + '\n'), \
                    patch.dict(postbuild.os.environ, {'GITHUB_SHA': '1' * 40}):
                binding = postbuild.source_binding()
                self.assertEqual(set(binding['files']), set(postbuild.SOURCE_FILES))
                self.assertEqual(binding['commit'], '1' * 40)
                self.assertIn('scripts/probe_opencv_postbuild.py', binding['files'])
                with patch.dict(postbuild.os.environ, {'GITHUB_SHA': '2' * 40}), self.assertRaises(RuntimeError):
                    postbuild.source_binding()

    def test_exports_never_overwrite_or_complete_preexisting_partial_outputs(self):
        for name in (*postbuild.EXPORT_NAMES.values(), postbuild.PREFIX + 'export.json'):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory, patch.object(postbuild, 'ROOT', Path(directory)):
                self.write_summary_fixture(directory)
                path = Path(directory) / 'reports' / name
                path.write_bytes(b'earlier evidence')
                before = {p.name: p.read_bytes() for p in path.parent.iterdir()}
                with self.assertRaisesRegex(RuntimeError, 'Refusing to replace'):
                    self.export_fixture(directory)
                self.assertEqual(before, {p.name: p.read_bytes() for p in path.parent.iterdir()})

    def test_standard_report_tamper_missing_file_and_partial_receipt_fail_closed(self):
        cases = ('baseline-bytes', 'candidate-bytes', 'parity', 'missing-candidate', 'missing-receipt',
                 'receipt-hash', 'receipt-extra', 'receipt-bool-version', 'receipt-false-role')
        for mutation in cases:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory, patch.object(postbuild, 'ROOT', Path(directory)):
                self.write_summary_fixture(directory)
                self.export_fixture(directory)
                reports = Path(directory) / 'reports'
                receipt_path = postbuild.output_path('export')
                if mutation.endswith('-bytes'):
                    path = reports / postbuild.EXPORT_NAMES[mutation.split('-')[0]]
                    path.write_bytes(path.read_bytes() + b'\n')
                elif mutation == 'parity':
                    path = reports / postbuild.EXPORT_NAMES['parity']
                    value = postbuild.read_json(path); value['status'] = 'failed'
                    path.write_text(json.dumps(value), encoding='utf-8')
                elif mutation == 'missing-candidate':
                    (reports / postbuild.EXPORT_NAMES['candidate']).unlink()
                elif mutation == 'missing-receipt':
                    receipt_path.unlink()
                else:
                    value = postbuild.read_json(receipt_path)
                    if mutation == 'receipt-hash':
                        value['exports']['baseline']['file']['sha256'] = 'e' * 64
                    elif mutation == 'receipt-extra':
                        value['selected_retry'] = True
                    elif mutation == 'receipt-bool-version':
                        value['schema_version'] = True
                    else:
                        value['excluded_from_adoption'] = True
                    receipt_path.write_text(json.dumps(value), encoding='utf-8')
                with self.assertRaises((RuntimeError, FileNotFoundError)):
                    postbuild.validate_export(reports)

    def test_export_requires_verified_restoration_and_exact_fixed_protocol_role(self):
        for mutation in ('restore', 'scope', 'excluded', 'order'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory, patch.object(postbuild, 'ROOT', Path(directory)):
                self.write_summary_fixture(directory)
                path = postbuild.output_path('result'); value = postbuild.read_json(path)
                if mutation == 'restore':
                    value['restoration']['status'] = 'failed'
                elif mutation == 'scope':
                    value['scope'] = 'supplemental experiment'
                elif mutation == 'excluded':
                    value['excluded_from_adoption'] = True
                else:
                    value['fixed_order'].reverse()
                path.write_text(json.dumps(value), encoding='utf-8')
                with patch.object(postbuild, 'require_host'), self.assertRaisesRegex(RuntimeError, 'Cannot export incomplete'):
                    postbuild.export()
                self.assertFalse(postbuild.output_path('export').exists())
                self.assertFalse((Path(directory) / 'reports' / postbuild.EXPORT_NAMES['baseline']).exists())

    def test_failed_default_parity_keeps_every_sample_but_cannot_validate_for_release(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(postbuild, 'ROOT', Path(directory)):
            self.write_summary_fixture(directory, candidate_seconds=.3)
            receipt = self.export_fixture(directory)
            self.assertEqual(receipt['status'], 'failed')
            report = postbuild.read_json(Path(directory) / 'reports' / postbuild.EXPORT_NAMES['parity'])
            self.assertEqual(report['performance_policy']['regression_ratio'], 1.5)
            self.assertEqual(report['performance']['capture_synthetic_window']['candidate_samples_seconds'], [.3] * 7)
            with self.assertRaisesRegex(RuntimeError, 'comparison did not pass'):
                postbuild.validate_export()

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
                projected = postbuild.render_projection(bundle)
                kept = projected['files']['result']['value']['blocks'][0]
                self.assertEqual(kept['capture']['samples_seconds'], capture['samples_seconds'])
                self.assertEqual(kept['probe_run'], baseline['run'])
                self.assertEqual(projected['files']['prepared']['value']['baseline_identity'], identity)
                metric = projected['files']['result']['value']['comparisons'][0]['performance']['capture_synthetic_window']
                self.assertEqual(metric['earlier_samples_seconds'], capture['samples_seconds'])
                self.assertEqual(metric['later_samples_seconds'], capture['samples_seconds'])

    def test_projection_size_fails_visibly_without_truncating_fields(self):
        with patch.object(postbuild, 'MAX_RENDER_BYTES', 1):
            with self.assertRaisesRegex(RuntimeError, 'rendered evidence exceeds'):
                postbuild.render_projection({'files': {}, 'status': 'failed', 'error': 'complete error'})

    def test_start_gate_precedes_all_probe_and_install_work(self):
        with patch.object(sys, 'stdin', Mock(buffer=io.BytesIO(b''))), patch.object(postbuild, 'require_host') as host, \
                patch.object(postbuild.runpy, 'run_path') as run_path:
            with self.assertRaises(RuntimeError):
                postbuild.child('probe', 'A1')
            host.assert_not_called()
            run_path.assert_not_called()

    def test_child_invokes_unchanged_full_probe_and_offline_exact_pip(self):
        with patch.object(sys, 'stdin', Mock(buffer=io.BytesIO(b'G'))), patch.object(postbuild, 'require_host'), \
                patch.object(postbuild.runpy, 'run_path') as run_path, patch.object(sys, 'argv', []):
            postbuild.child('probe', 'A1')
            self.assertEqual(sys.argv[1:], ['generate', '--output', str(postbuild.output_path('A1-probe')), '--samples', '7', '--warmups', '2'])
            run_path.assert_called_once_with(str(ROOT / 'scripts' / 'probe_opencv_parity.py'), run_name='__main__')
        with patch.object(sys, 'stdin', Mock(buffer=io.BytesIO(b'G'))), patch.object(postbuild, 'require_host'), \
                patch.object(postbuild, 'expected_wheel', return_value=Path('exact.whl')), \
                patch.object(postbuild, 'wheel_identity'), patch.object(postbuild.runpy, 'run_module') as module, patch.object(sys, 'argv', []):
            postbuild.child('install', 'B1')
            self.assertEqual(sys.argv, ['pip', '--isolated', 'install', '--no-index', '--no-deps', '--no-cache-dir', '--force-reinstall', 'exact.whl'])
            module.assert_called_once_with('pip', run_name='__main__', alter_sys=True)

    def test_supervisor_does_not_import_native_packages(self):
        source = Path(postbuild.__file__).read_text()
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
                postbuild.main(args)
            self.assertEqual(error.exception.code, 2)


if __name__ == '__main__':
    unittest.main()

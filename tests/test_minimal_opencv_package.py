"""Profile isolation and sealed-byte checks for custom OpenCV packaging."""
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
import warnings
import zipfile

from scripts import minimal_opencv_package as custom
from scripts import windows_package as package
from scripts import verify_release

ROOT = Path(__file__).resolve().parents[1]


class MinimalPackageTests(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(os.environ, {'VGA_EXPERIMENTAL_MINIMAL_OPENCV': '', 'VGA_RELEASE_PACKAGE_PROFILE': ''})
        environment.start()
        self.addCleanup(environment.stop)
        # Tiny byte fixtures isolate archive/isolation logic; the builder's
        # dedicated tests exercise the complete strict provenance contract.
        self.provenance_patch = patch.object(custom, 'validate_provenance', side_effect=lambda value: value)
        self.validated = self.provenance_patch.start()
        self.addCleanup(self.provenance_patch.stop)

    def test_strict_builder_validation_is_mandatory(self):
        self.validated.side_effect = RuntimeError('strict source pin failed')
        with self.assertRaisesRegex(RuntimeError, 'strict source pin'):
            custom.checked_proof(self.fixture()[1])

    @staticmethod
    def fixture(profile=package.EXPERIMENT_PROFILE):
        native, notice = b'custom native bytes', b'original upstream notice'
        proof = {'status': 'passed', 'version': custom.CUSTOM_VERSION,
                 'package_profile': profile, 'source_commit': 'a'*40,
                 'native': {'sha256': hashlib.sha256(native).hexdigest(), 'size': len(native)},
                 'licenses': [{'path': 'IPP/EULA.rtf', 'size': len(notice),
                               'sha256': hashlib.sha256(notice).hexdigest()}]}
        data = {'cv2/cv2.pyd': native, 'opencv_python_headless-5.0.0.93+vga1.dist-info/METADATA':
                b'Metadata-Version: 2.1\nVersion: 5.0.0.93+vga1\n',
                'licenses/opencv-minimal/IPP/EULA.rtf': notice,
                'licenses/opencv-minimal/BUILD-PROVENANCE.json': json.dumps(proof).encode()}
        class Archive:
            toc = data
            @staticmethod
            def extract(name): return data[name]
        return Archive(), proof, data

    @classmethod
    def build_fixture(cls, profile=package.ADOPTED_PROFILE):
        proof = None if profile == package.OFFICIAL_PROFILE else cls.fixture(profile)[1]
        return {'package_profile': profile, 'experimental': profile == package.EXPERIMENT_PROFILE,
                'source_commit': 'a'*40, 'opencv_custom_build': proof,
                'dependencies': [{'name': 'opencv-python-headless',
                                  'version': custom.OFFICIAL_VERSION if proof is None else custom.CUSTOM_VERSION}]}

    def test_complete_builder_contract_is_composed_without_stub(self):
        from scripts.build_minimal_opencv import validate_provenance
        from tests.test_minimal_opencv import valid_provenance_fixture
        proof = valid_provenance_fixture()
        with patch.object(custom, 'validate_provenance', wraps=validate_provenance):
            self.assertEqual(custom.checked_proof(proof), proof)
            proof['source']['sha256'] = '0' * 64
            with self.assertRaisesRegex(RuntimeError, 'pinned input'):
                custom.checked_proof(proof)

    def test_ordinary_build_requires_official_wheel(self):
        with patch.dict(os.environ, {'VGA_EXPERIMENTAL_MINIMAL_OPENCV': '0'}):
            self.assertIsNone(custom.check_build_mode(custom.OFFICIAL_VERSION))
            for version in (custom.CUSTOM_VERSION, '5.1.0.1', '5.0.0.93+unknown'):
                with self.assertRaisesRegex(RuntimeError, 'Ordinary builds'):
                    custom.check_build_mode(version)

    def test_experiment_requires_local_version_and_provenance(self):
        _, proof, _ = self.fixture()
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'VGA_EXPERIMENTAL_MINIMAL_OPENCV': '1'}):
            path = Path(folder) / 'proof.json'; path.write_text(json.dumps(proof))
            self.assertEqual(custom.check_build_mode(custom.CUSTOM_VERSION, path), proof)
            with self.assertRaisesRegex(RuntimeError, 'truthful'):
                custom.check_build_mode(custom.OFFICIAL_VERSION, path)
            proof['status'] = 'failed'; path.write_text(json.dumps(proof))
            with self.assertRaisesRegex(RuntimeError, 'provenance'):
                custom.check_build_mode(custom.CUSTOM_VERSION, path)

    def test_adopted_build_requires_explicit_profile_and_matching_proof(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'VGA_RELEASE_PACKAGE_PROFILE': package.ADOPTED_PROFILE}):
            _, proof, _ = self.fixture(package.ADOPTED_PROFILE)
            path = Path(folder) / 'proof.json'; path.write_text(json.dumps(proof))
            self.assertEqual(custom.check_build_mode(custom.CUSTOM_VERSION, path), proof)
            for version in (custom.OFFICIAL_VERSION, '5.0.0.93+unknown', '5.1.0.1'):
                with self.subTest(version=version), self.assertRaisesRegex(RuntimeError, 'truthful'):
                    custom.check_build_mode(version, path)
            for profile in (package.EXPERIMENT_PROFILE, package.OFFICIAL_PROFILE, None):
                proof['package_profile'] = profile; path.write_text(json.dumps(proof))
                with self.subTest(profile=profile), self.assertRaisesRegex(RuntimeError, 'profile'):
                    custom.check_build_mode(custom.CUSTOM_VERSION, path)

    def test_build_profile_is_explicit_pure_and_consistent(self):
        with patch.dict(os.environ, {'VGA_EXPERIMENTAL_MINIMAL_OPENCV': '1', 'VGA_RELEASE_PACKAGE_PROFILE': 'invalid'}):
            for profile in (package.OFFICIAL_PROFILE, *package.CUSTOM_PROFILES):
                self.assertEqual(custom.validate_build_profile(self.build_fixture(profile)), profile)
        for profile in (package.OFFICIAL_PROFILE, *package.CUSTOM_PROFILES):
            good = self.build_fixture(profile)
            for key, value in [('package_profile', None), ('package_profile', 'unknown'),
                               ('experimental', not good['experimental']), ('experimental', int(good['experimental'])),
                               ('dependencies', []), ('dependencies', good['dependencies']*2), ('dependencies', None)]:
                changed = copy.deepcopy(good); changed[key] = value
                with self.subTest(profile=profile, key=key), self.assertRaises(RuntimeError):
                    custom.validate_build_profile(changed)
            for version in ('5.1.0.1', '5.0.0.93+unknown', None):
                changed = copy.deepcopy(good); changed['dependencies'][0]['version'] = version
                with self.subTest(profile=profile, version=version), self.assertRaises(RuntimeError):
                    custom.validate_build_profile(changed)

    def test_experiment_cannot_be_relabelled_by_flags_environment_or_dependency(self):
        experiment = self.build_fixture(package.EXPERIMENT_PROFILE)
        with patch.dict(os.environ, {'VGA_EXPERIMENTAL_MINIMAL_OPENCV': '0'}):
            self.assertEqual(custom.validate_build_profile(experiment), package.EXPERIMENT_PROFILE)
            for change in ({'experimental': False}, {'package_profile': package.ADOPTED_PROFILE, 'experimental': False},
                           {'package_profile': package.OFFICIAL_PROFILE, 'experimental': False},
                           {'opencv_custom_build': None}, {'source_commit': 'b'*40}):
                with self.subTest(change=change), self.assertRaises(RuntimeError):
                    custom.validate_build_profile({**experiment, **change})
        official = self.build_fixture(package.OFFICIAL_PROFILE)
        official['opencv_custom_build'] = experiment['opencv_custom_build']
        with self.assertRaisesRegex(RuntimeError, 'cannot carry'):
            custom.validate_build_profile(official)

    def test_notice_paths_are_relative_unique_and_nonempty(self):
        _, proof, _ = self.fixture()
        for path in ('../EULA', '/EULA', 'IPP\\EULA', ''):
            changed = copy.deepcopy(proof); changed['licenses'][0]['path'] = path
            with self.assertRaisesRegex(RuntimeError, 'inventory'):
                custom.checked_proof(changed)
        proof['licenses'] *= 2
        with self.assertRaises(RuntimeError): custom.checked_proof(proof)

    def test_archive_rechecks_native_metadata_notice_and_provenance_bytes(self):
        for profile in package.CUSTOM_PROFILES:
            archive, proof, data = self.fixture(profile)
            custom.verify_custom_archive(archive, proof)
            for name in tuple(data):
                saved = data[name]; data[name] = b'changed'
                with self.subTest(profile=profile, name=name), self.assertRaises((RuntimeError, ValueError)):
                    custom.verify_custom_archive(archive, proof)
                data[name] = saved
            for name in ('PIL/_imagingft.cp312-win_amd64.pyd', 'PIL/_imagingcms.cp312-win_amd64.pyd'):
                data[name] = b'unused'
                with self.assertRaisesRegex(RuntimeError, 'Unused Pillow'):
                    custom.verify_custom_archive(archive, proof)
                del data[name]

    def test_both_profiles_require_same_parity_frozen_telemetry_icc_and_archive_evidence(self):
        from tests.test_opencv_parity import reports
        from scripts.probe_opencv_parity import compare_reports
        for profile in package.CUSTOM_PROFILES:
            archive, proof, data = self.fixture(profile)
            build = self.build_fixture(profile)
            baseline, candidate = reports()
            candidate['native'].update(sha256=proof['native']['sha256'], size=proof['native']['size'], zlib9_size=10)
            candidate['opencv']['binary'].update(sha256=proof['native']['sha256'], raw_bytes=proof['native']['size'], zlib9_bytes=10)
            # The synthetic package bytes also bind both supplemental loaded-module snapshots.
            for key in ('identity_before_supplemental', 'identity_after_supplemental'):
                candidate['performance']['capture_synthetic_window']['capture_diagnostics'][key]['loaded']['cv2_native'].update(
                    sha256=proof['native']['sha256'], size=proof['native']['size'])
            parity = compare_reports(baseline, candidate)
            self.assertEqual(parity['status'], 'passed')
            evidence = {'windows-opencv-build.json': proof, 'windows-opencv-baseline.json': baseline,
                        'windows-opencv-candidate.json': candidate, 'windows-opencv-parity.json': parity,
                        'windows-exe-self-test.json': {'ort_telemetry_opt_out': '1'},
                        'windows-exe-smoke.json': {'icc_image_formats': {
                            kind: ['星火共鸣（演示）', '晶盾回路（演示）', '风步微光（演示）'] for kind in ('PNG', 'JPEG', 'WEBP')}}}
            modules = {'PyInstaller': types.ModuleType('PyInstaller'),
                       'PyInstaller.archive': types.ModuleType('PyInstaller.archive'),
                       'PyInstaller.archive.readers': types.SimpleNamespace(CArchiveReader=lambda _: archive)}
            with tempfile.TemporaryDirectory() as directory, patch.dict(sys.modules, modules):
                def write(values):
                    for name, value in values.items():
                        (Path(directory)/name).write_text(json.dumps(value), encoding='utf-8')
                write(evidence)
                self.assertEqual(custom.verify_custom_evidence('unused.exe', directory, build), custom.EVIDENCE_NAMES)
                if profile == package.EXPERIMENT_PROFILE:
                    self.assertEqual(custom.verify_experiment_evidence('unused.exe', directory, build), custom.EVIDENCE_NAMES)
                else:
                    with self.assertRaisesRegex(RuntimeError, 'experimental package profile'):
                        custom.verify_experiment_evidence('unused.exe', directory, build)
                for name, key, value in [('windows-opencv-build.json', 'source_commit', 'b'*40),
                                         ('windows-opencv-build.json', 'package_profile', package.OFFICIAL_PROFILE),
                                         ('windows-opencv-parity.json', 'status', 'failed'),
                                         ('windows-exe-self-test.json', 'ort_telemetry_opt_out', '0'),
                                         ('windows-exe-smoke.json', 'icc_image_formats', {})]:
                    changed = copy.deepcopy(evidence); changed[name][key] = value; write(changed)
                    with self.subTest(profile=profile, name=name, key=key), self.assertRaises(RuntimeError):
                        custom.verify_custom_evidence('unused.exe', directory, build)
                    write(evidence)
                data['cv2/cv2.pyd'] = b'changed after acceptance'
                with self.assertRaisesRegex(RuntimeError, 'native bytes differ'):
                    custom.verify_custom_evidence('unused.exe', directory, build)

    def test_separate_license_zip_requires_exact_custom_notices_and_provenance(self):
        for profile in package.CUSTOM_PROFILES:
            _, proof, data = self.fixture(profile)
            files = {name.removeprefix('licenses/'): value for name, value in data.items() if name.startswith('licenses/')}
            files.update({'other-package/LICENSE': b'unrelated notice', 'opencv-minimal/': b'', 'opencv-minimal/IPP/': b''})
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory)/'third-party-licenses.zip'
                def write(values):
                    with zipfile.ZipFile(path, 'w') as archive:
                        for name, value in values.items():
                            archive.writestr(name, value)
                write(files)
                custom.verify_custom_notice_archive(path, proof)
                for name in ('opencv-minimal/IPP/EULA.rtf', 'opencv-minimal/BUILD-PROVENANCE.json'):
                    changed = dict(files); del changed[name]; write(changed)
                    with self.subTest(profile=profile, name=name), self.assertRaisesRegex(RuntimeError, 'incomplete'):
                        custom.verify_custom_notice_archive(path, proof)
                    changed[name] = b'{}' if name.endswith('.json') else b'changed'; write(changed)
                    with self.assertRaisesRegex(RuntimeError, 'differ'):
                        custom.verify_custom_notice_archive(path, proof)
                for name in ('opencv-minimal/EXTRA', 'opencv-minimal/extra/', 'OpenCV-Minimal/IPP/EULA.rtf',
                             'opencv-minimal/../EXTRA', 'opencv-minimal\\EXTRA'):
                    write({**files, name: b'extra'})
                    with self.subTest(name=name), self.assertRaises(RuntimeError):
                        custom.verify_custom_notice_archive(path, proof)
                write(files)
                with zipfile.ZipFile(path, 'a') as archive, warnings.catch_warnings():
                    warnings.simplefilter('ignore', UserWarning)
                    archive.writestr('opencv-minimal/IPP/EULA.rtf', files['opencv-minimal/IPP/EULA.rtf'])
                with self.assertRaisesRegex(RuntimeError, 'Duplicate'):
                    custom.verify_custom_notice_archive(path, proof)

    def test_source_zip_seals_probe_inputs_models_and_build_recipe(self):
        from model_inventory import EXPECTED_MODELS
        from scripts.probe_opencv_parity import SOURCE_FILES
        files = {name: (name + '\r\nraw source bytes\r\n').encode() for name in SOURCE_FILES}
        records = {'scripts/build_minimal_opencv.py': 'recipe',
                   'packaging/opencv-minimal-patch.py': 'patch',
                   'packaging/opencv-build-requirements.txt': 'build_requirements'}
        files.update({name: (name + '\r\n').encode() for name in records})
        build = self.build_fixture()
        proof = build['opencv_custom_build']
        for name, key in records.items():
            row = {'path': name, 'size': len(files[name]), 'sha256': custom.digest_bytes(files[name])}
            proof[key] = {'script': row} if key == 'patch' else row
        build['bundled_models'] = [{'name': name, 'sha256': digest, 'size': 100} for name, digest in EXPECTED_MODELS.items()]
        probes = {label: {'inputs': {name: custom.digest_bytes(files[name]) for name in SOURCE_FILES},
                          'models': copy.deepcopy(build['bundled_models'])} for label in ('baseline', 'candidate')}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'source.zip'
            def write_source(values):
                with zipfile.ZipFile(path, 'w') as archive:
                    for name, value in values.items():
                        archive.writestr(name, value)
            def write_probes(values):
                for label, value in values.items():
                    (Path(directory)/('windows-opencv-' + label + '.json')).write_text(json.dumps(value), encoding='utf-8')
            write_source(files); write_probes(probes)
            custom.verify_custom_source_archive(path, directory, build)
            for name in files:
                write_source({**files, name: files[name].replace(b'\r\n', b'\n')})
                with self.subTest(name=name), self.assertRaisesRegex(RuntimeError, 'differ'):
                    custom.verify_custom_source_archive(path, directory, build)
            write_source(files)
            for label in probes:
                for name in SOURCE_FILES:
                    changed = copy.deepcopy(probes); changed[label]['inputs'][name] = '0'*64; write_probes(changed)
                    with self.subTest(label=label, name=name), self.assertRaisesRegex(RuntimeError, 'parity source differs'):
                        custom.verify_custom_source_archive(path, directory, build)
                changed = copy.deepcopy(probes); changed[label]['models'][0]['size'] += 1; write_probes(changed)
                with self.assertRaisesRegex(RuntimeError, 'parity models differ'):
                    custom.verify_custom_source_archive(path, directory, build)
            write_probes(probes)
            for rows in ([], build['bundled_models']*2,
                         [{**row, 'sha256': '0'*64} for row in build['bundled_models']]):
                changed = copy.deepcopy(build); changed['bundled_models'] = rows
                with self.assertRaisesRegex(RuntimeError, 'pinned model inventory'):
                    custom.verify_custom_source_archive(path, directory, changed)
            for name in ('local_ocr.py', 'scripts/build_minimal_opencv.py'):
                changed = dict(files); del changed[name]; write_source(changed)
                with self.assertRaisesRegex(RuntimeError, 'source ZIP member'):
                    custom.verify_custom_source_archive(path, directory, build)
            write_source(files)
            with zipfile.ZipFile(path, 'a') as archive, warnings.catch_warnings():
                warnings.simplefilter('ignore', UserWarning)
                archive.writestr('local_ocr.py', files['local_ocr.py'])
            with self.assertRaisesRegex(RuntimeError, 'source ZIP member'):
                custom.verify_custom_source_archive(path, directory, build)

    def test_pillow_cuts_require_custom_profile_and_leave_image_and_qt_fonts(self):
        for profile in (package.OFFICIAL_PROFILE, *package.CUSTOM_PROFILES):
            with patch.dict(os.environ, {'VGA_EXPERIMENTAL_MINIMAL_OPENCV': '1' if profile == package.EXPERIMENT_PROFILE else '',
                                        'VGA_RELEASE_PACKAGE_PROFILE': package.ADOPTED_PROFILE if profile == package.ADOPTED_PROFILE else ''}):
                for name in ('PIL/_imagingft.cp312-win_amd64.pyd', 'PIL/_imagingcms.cp312-win_amd64.pyd'):
                    self.assertEqual(package.unused_binary_reason(name) is not None, profile in package.CUSTOM_PROFILES)
                for name in ('PIL/_imaging.cp312-win_amd64.pyd', 'PIL/_webp.cp312-win_amd64.pyd', 'Qt6Gui.dll', 'qsvg.dll'):
                    self.assertIsNone(package.unused_binary_reason(name))
        self.assertEqual(package.EXPERIMENT_EXCLUDED_IMPORTS, ('PIL._imagingft', 'PIL._imagingcms'))

    def test_publication_rejects_verified_experiment_even_without_env(self):
        with patch.dict(os.environ, {'VGA_EXPERIMENTAL_MINIMAL_OPENCV': '0'}), patch.object(verify_release, 'gh_api') as api:
            with self.assertRaisesRegex(RuntimeError, 'not approved for publication'):
                verify_release.publish({'experimental': True}, Path('unused'), {})
            api.assert_not_called()

    def test_isolated_workflow_has_all_gates_no_publication_or_large_upload(self):
        workflow = (ROOT / '.github/workflows/test-windows-minimal-opencv.yml').read_text()
        for value in ('contents: read', 'runs-on: windows-2022', 'persist-credentials: false',
                      "VGA_EXPERIMENTAL_MINIMAL_OPENCV: '1'", 'scripts/build_minimal_opencv.py',
                      'scripts/probe_opencv_parity.py generate', 'scripts/probe_opencv_parity.py compare',
                      'python scripts/build_windows.py', 'windows_exe_smoke.py', 'windows_native_smoke.py',
                      '--app-scale 1.5', '--app-scale 2', 'windows_selection_smoke.py', 'windows_ota_smoke.py',
                      'scripts/verify_release.py', '--evidence-only', 'retention-days: 1'):
            self.assertIn(value, workflow)
        for value in ('contents: write', '--publish', 'GH_TOKEN', 'secrets.', 'path: dist', 'self-hosted', 'schedule:'):
            self.assertNotIn(value, workflow)
        release_workflow = (ROOT / '.github/workflows/build-native-preview.yml').read_text()
        self.assertNotIn('VGA_EXPERIMENTAL_MINIMAL_OPENCV', release_workflow)
        self.assertIn("VGA_RELEASE_PACKAGE_PROFILE: 'minimal-opencv-v1'", release_workflow)
        for value in ('scripts/build_minimal_opencv.py', 'scripts/probe_opencv_parity.py generate',
                      'scripts/probe_opencv_parity.py compare', 'windows_exe_smoke.py', 'windows_native_smoke.py',
                      '--app-scale 1.5', '--app-scale 2', 'windows_selection_smoke.py', 'windows_ota_smoke.py',
                      'scripts/verify_release.py'):
            self.assertIn(value, release_workflow)


if __name__ == '__main__':
    unittest.main()

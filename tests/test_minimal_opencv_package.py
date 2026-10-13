"""Isolation and sealed-byte checks for the read-only custom OpenCV experiment."""
import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import minimal_opencv_package as custom
from scripts import windows_package as package
from scripts import verify_release

ROOT = Path(__file__).resolve().parents[1]


class MinimalPackageTests(unittest.TestCase):
    def setUp(self):
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
    def fixture():
        native, notice = b'custom native bytes', b'original upstream notice'
        proof = {'status': 'passed', 'version': custom.CUSTOM_VERSION,
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

    def test_notice_paths_are_relative_unique_and_nonempty(self):
        _, proof, _ = self.fixture()
        for path in ('../EULA', '/EULA', 'IPP\\EULA', ''):
            changed = copy.deepcopy(proof); changed['licenses'][0]['path'] = path
            with self.assertRaisesRegex(RuntimeError, 'inventory'):
                custom.checked_proof(changed)
        proof['licenses'] *= 2
        with self.assertRaises(RuntimeError): custom.checked_proof(proof)

    def test_archive_rechecks_native_metadata_notice_and_provenance_bytes(self):
        archive, proof, data = self.fixture()
        custom.verify_custom_archive(archive, proof)
        for name in tuple(data):
            saved = data[name]; data[name] = b'changed'
            with self.subTest(name=name), self.assertRaises((RuntimeError, ValueError)):
                custom.verify_custom_archive(archive, proof)
            data[name] = saved
        for name in ('PIL/_imagingft.cp312-win_amd64.pyd', 'PIL/_imagingcms.cp312-win_amd64.pyd'):
            data[name] = b'unused'
            with self.assertRaisesRegex(RuntimeError, 'Unused Pillow'):
                custom.verify_custom_archive(archive, proof)
            del data[name]

    def test_pillow_cuts_are_experiment_only_and_leave_image_and_qt_fonts(self):
        for flag in ('0', '1'):
            with patch.dict(os.environ, {'VGA_EXPERIMENTAL_MINIMAL_OPENCV': flag}):
                for name in ('PIL/_imagingft.cp312-win_amd64.pyd', 'PIL/_imagingcms.cp312-win_amd64.pyd'):
                    self.assertEqual(package.unused_binary_reason(name) is not None, flag == '1')
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
        self.assertNotIn('build_minimal_opencv', release_workflow)


if __name__ == '__main__':
    unittest.main()

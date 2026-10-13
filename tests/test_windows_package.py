"""Size-policy and safety guards; actual Windows execution is a separate CI gate."""
import copy
import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import windows_package as package
from scripts.check_package_candidate import validate_evidence, NAMES

ROOT = Path(__file__).resolve().parents[1]


class WindowsPackageTests(unittest.TestCase):
    def test_reviewed_binary_removals_are_narrow(self):
        for name in ('cv2/opencv_videoio_ffmpeg500_64.dll', 'onnxruntime/capi/onnxruntime.dll',
                     'libcrypto-3-x64.dll', 'libssl-3-x64.dll', 'PIL/_avif.cp312-win_amd64.pyd'):
            self.assertIsNotNone(package.unused_binary_reason(name))
        for name in ('libcrypto-3.dll', 'libssl-3.dll', 'onnxruntime_pybind11_state.pyd',
                     'onnxruntime_providers_shared.dll', 'cv2.pyd', '_imaging.pyd', '_webp.pyd',
                     'numpy.libs/openblas.dll', 'PySide6/MSVCP140.dll', 'vcruntime140.dll',
                     'opencv_videoio_custom.dll', 'Qt6Gui.dll', 'qschannelbackend.dll'):
            self.assertIsNone(package.unused_binary_reason(name), name)

    def test_trim_rejects_static_or_delay_import_of_removed_dll(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'original.dll'; source.write_bytes(b'fixture')
            entries = [('onnxruntime.dll', str(source), 'BINARY'), ('keep.dll', str(source), 'BINARY')]
            with self.assertRaisesRegex(RuntimeError, 'Refusing to remove'):
                package.trim_unused_binaries(entries, lambda _: ['onnxruntime.dll'])
            retained, report = package.trim_unused_binaries(entries, lambda _: ['kernel32.dll'])
            self.assertEqual(retained, entries[1:])
            self.assertEqual(report['removed_source_bytes'], 7)
            self.assertTrue(report['retained_pe_imports_checked'])

    @staticmethod
    def required_names():
        return ['assets/branding/vga.ico', 'assets/branding/vga-icon-512.png', 'rapidocr/config.yaml',
                'rapidocr/default_models.yaml', 'onnxruntime/capi/onnxruntime_pybind11_state.pyd',
                'onnxruntime/capi/onnxruntime_providers_shared.dll', '_ssl.pyd', 'libcrypto-3.dll', 'libssl-3.dll',
                'PySide6/plugins/tls/qcertonlybackend.dll', 'PySide6/plugins/tls/qschannelbackend.dll']

    def test_inventory_accepts_runtime_branding_and_rejects_missing(self):
        package.assert_slim_inventory(self.required_names())
        package.assert_slim_inventory([name.replace('/', '\\') for name in self.required_names()])
        for missing in self.required_names():
            with self.assertRaisesRegex(RuntimeError, 'missing'):
                package.assert_slim_inventory([name for name in self.required_names() if name != missing])

    def test_inventory_rejects_baggage_and_duplicate_sources(self):
        for name in ('assets/branding/vga-icon-source.png', 'rapidocr/main.py', 'onnxruntime/tools/test.py',
                     'onnxruntime/capi/onnxruntime.dll', 'PIL/_avif.cp312-win_amd64.pyd'):
            with self.assertRaisesRegex(RuntimeError, 'Unused or duplicate'):
                package.assert_slim_inventory(self.required_names() + [name])

    def measure_fixture(self, mutate=False, missing=False, maximum=125_000_000):
        raw = b'unchanged model fixture'
        class Archive:
            toc = {} if missing else {'rapidocr\\models\\fixture.onnx': (0, 5, len(raw), 1, 'x')}
            @staticmethod
            def extract(name): return b'changed' if mutate else raw
        with tempfile.TemporaryDirectory() as folder:
            exe = Path(folder) / 'app.exe'; exe.write_bytes(b'fixture-exe')
            with patch('model_inventory.EXPECTED_MODELS', {'fixture.onnx': hashlib.sha256(raw).hexdigest()}), \
                 patch.object(package, 'MAX_EXE_BYTES', maximum):
                return package.measure_archive(Archive(), exe)

    def test_measurement_reports_real_lengths_and_verified_model_bytes(self):
        result = self.measure_fixture()
        self.assertEqual(result['executable']['size'], 11)
        self.assertEqual(result['stored_payload_bytes'], 5)
        self.assertEqual(result['container_overhead_bytes'], 6)
        self.assertEqual(result['unchanged_models'][0]['size'], 23)
        self.assertEqual(result['saved_bytes'], package.BASELINE['size'] - 11)
        self.assertEqual(result['status'], 'passed')

    def test_model_changes_and_missing_assets_fail_before_size_claim(self):
        for options in ({'mutate': True}, {'missing': True}):
            with self.assertRaises(RuntimeError): self.measure_fixture(**options)

    def test_size_cap_marks_oversized_executable_failed(self):
        self.assertEqual(self.measure_fixture(maximum=10)['status'], 'failed')

    @staticmethod
    def evidence():
        sha = 'a' * 64
        size = {'status': 'passed', 'source_commit': 'b' * 40, 'executable': {'sha256': sha, 'size': 99}}
        smoke = {'status': 'passed', 'executable_sha256': sha,
                 'supported_image_formats': {name: NAMES for name in ('PNG', 'JPEG', 'WEBP', 'BMP')}}
        ota = {'status': 'passed', 'executable_sha256': sha, 'executable_bytes': 99,
               'release_source_commit': 'b' * 40, 'harness_source_commit': 'b' * 40,
               'all_owned_processes_exited': True,
               'cases': [{'case': name, 'status': 'passed', 'original_sha256': sha,
                          'target_sha256': sha, 'actual_file_identity_changed': True}
                         for name in ('success-concurrency', 'version-mismatch-rollback')]}
        return size, smoke, ota

    def test_candidate_evidence_matches_exact_bytes_source_and_formats(self):
        validate_evidence(*self.evidence(), 'b' * 40)
        for index, key, value in [(0, 'source_commit', 'c' * 40), (0, 'status', 'failed'),
                (1, 'executable_sha256', 'c' * 64), (1, 'supported_image_formats', {'PNG': NAMES}),
                (2, 'executable_bytes', 98), (2, 'release_source_commit', 'c' * 40),
                (2, 'all_owned_processes_exited', 1), (2, 'cases', [])]:
            evidence = copy.deepcopy(self.evidence()); evidence[index][key] = value
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                validate_evidence(*evidence, 'b' * 40)

    def test_candidate_evidence_rejects_mismatched_ota_case(self):
        for key, value in [('target_sha256', 'c' * 64), ('actual_file_identity_changed', False), ('status', 'failed')]:
            evidence = copy.deepcopy(self.evidence()); evidence[2]['cases'][0][key] = value
            with self.assertRaises(RuntimeError): validate_evidence(*evidence, 'b' * 40)

    def test_spec_preserves_models_and_standard_compression_without_collect_all(self):
        spec = (ROOT / 'packaging/VGA-Aram-Helper.spec').read_text(encoding='utf-8')
        for value in ('rapidocr.main', 'rapidocr.inference_engine.onnxruntime',
                      "collect_data_files('rapidocr', include_py_files=False)", 'verify_models()',
                      'replace_runtime_entries(a.binaries)', 'trim_unused_binaries(a.binaries)', 'upx=False'):
            self.assertIn(value, spec)
        self.assertNotIn('collect_all', spec)
        self.assertEqual(package.BRANDING_FILES, ('vga.ico', 'vga-icon-512.png'))
        self.assertIn('PIL.AvifImagePlugin', package.EXCLUDED_IMPORTS)
        self.assertIn('PIL._avif', package.EXCLUDED_IMPORTS)
        self.assertNotIn('numpy.random', package.EXCLUDED_IMPORTS)
        self.assertNotIn('numpy.linalg', package.EXCLUDED_IMPORTS)

    def test_dependencies_remain_at_measured_baseline_versions(self):
        constraints = (ROOT / 'packaging/windows-build-constraints.txt').read_text()
        for line in ('rapidocr==3.10.0', 'onnxruntime==1.31.0', 'numpy==2.5.4',
                     'opencv-python-headless==5.0.0.93', 'pillow==12.3.0', 'pyinstaller-hooks-contrib==2026.8'):
            self.assertIn(line, constraints)
        self.assertIn('-c packaging/windows-build-constraints.txt', (ROOT / 'requirements-build.txt').read_text())

    def test_workflow_is_read_only_free_runner_and_bounded_evidence(self):
        workflow = (ROOT / '.github/workflows/test-windows-package-size.yml').read_text()
        for value in ('workflow_dispatch:', 'contents: read', 'runs-on: windows-2022',
                      'persist-credentials: false', 'github.event.repository.private == false',
                      'python scripts/build_windows.py', 'python tests/windows_exe_smoke.py',
                      '--app-scale 1.5', '--app-scale 2', 'python tests/windows_selection_smoke.py',
                      'python tests/windows_ota_smoke.py', '--expected-sha256 $manifest.sha256',
                      '--expected-size $manifest.size', 'python scripts/check_package_candidate.py',
                      'python scripts/verify_release.py', '--evidence-only', 'retention-days: 1',
                      "steps.evidence_budget.outcome == 'success'"):
            self.assertIn(value, workflow)
        for value in ('contents: write', 'GH_TOKEN', 'secrets.', '--publish', 'path: dist', 'fetch_ota_fixture.py',
                      'pull_request:', 'schedule:', 'self-hosted'):
            self.assertNotIn(value, workflow)


if __name__ == '__main__':
    unittest.main()

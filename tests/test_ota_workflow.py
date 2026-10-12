"""Offline checks for a fixed owned fixture and a read-only OTA CI job."""
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import fetch_ota_fixture as fixture


class OtaWorkflowTests(unittest.TestCase):
    def test_owned_released_fixture_is_exactly_pinned(self):
        self.assertEqual(fixture.FIXTURE_SOURCE_COMMIT, '1ce516e967bbe153fa1dcf6e8289abf86185f04c')
        self.assertEqual(fixture.FIXTURE_MANIFEST['size'], 150155259)
        self.assertEqual(fixture.FIXTURE_MANIFEST['sha256'],
                         '40b8d2af8309278b9cf6a5eace8ca26d6a483f659578d441636b86369d66cf6e')
        self.assertEqual(fixture.validate_manifest(fixture.FIXTURE_MANIFEST, tag='v0.3.0'), fixture.FIXTURE_MANIFEST)

    def test_downloaded_fixture_is_verified_before_exclusive_output(self):
        data = bytearray(128)
        data[:2] = b'MZ'
        data[60:64] = (64).to_bytes(4, 'little')
        data[64:70] = b'PE\0\0\x64\x86'
        manifest = dict(fixture.FIXTURE_MANIFEST, size=len(data), sha256=hashlib.sha256(data).hexdigest())
        with tempfile.TemporaryDirectory() as folder, patch.object(fixture, 'FIXTURE_MANIFEST', manifest):
            output = Path(folder) / 'app.exe'
            result = fixture.fetch_fixture(output, downloader=lambda _manifest, path: path.write_bytes(data))
            self.assertEqual(output.read_bytes(), data)
            self.assertEqual(result['manifest'], manifest)
            with self.assertRaisesRegex(RuntimeError, 'refusing overwrite'):
                fixture.fetch_fixture(output, downloader=lambda *_: self.fail('Unexpected second download'))
            self.assertEqual(output.read_bytes(), data)

    def test_corrupt_fixture_leaves_no_executable(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'app.exe'
            with self.assertRaises(ValueError):
                fixture.fetch_fixture(output, downloader=lambda _manifest, path: path.write_bytes(b'MZcorrupt'))
            self.assertFalse(output.exists())
            self.assertEqual(list(Path(folder).iterdir()), [])

    def test_manual_read_only_workflow_has_no_large_artifact_or_secret(self):
        workflow = (fixture.ROOT / '.github/workflows/test-native-ota.yml').read_text()
        for text in ('workflow_dispatch:', 'contents: read', 'runs-on: windows-2022',
                     'persist-credentials: false', 'timeout-minutes: 18',
                     'python scripts/fetch_ota_fixture.py', '--evidence-only', 'retention-days: 1',
                     'path: reports/windows-ota-*'):
            self.assertIn(text, workflow)
        for text in ('contents: write', 'GH_TOKEN', 'secrets.', 'dist/release/*', 'gh release', 'delete-artifact'):
            self.assertNotIn(text, workflow)
        self.assertIn('Same-version local staging only', workflow)


if __name__ == '__main__':
    unittest.main()

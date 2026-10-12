"""Offline boundaries for the manual, read-only ordinary desktop test."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class GuiWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.workflow = (ROOT / '.github/workflows/test-windows-gui.yml').read_text(encoding='utf-8')

    def test_manual_standard_read_only_runner(self):
        for expected in ('workflow_dispatch:', 'contents: read', 'runs-on: windows-2022',
                         'timeout-minutes: 12', 'persist-credentials: false',
                         "github.repository == 'Junming-Liang/vga-aram-helper'",
                         "github.ref == 'refs/heads/main'", 'github.event.repository.private == false'):
            self.assertIn(expected, self.workflow)
        for forbidden in ('contents: write', 'secrets.', 'GH_TOKEN', 'schedule:', 'pull_request:',
                          'windows-latest', 'self-hosted', 'install-community', '--publish'):
            self.assertNotIn(forbidden, self.workflow)

    def test_existing_hash_pinned_exe_and_no_internal_smoke_substitute(self):
        self.assertIn('python scripts/fetch_ota_fixture.py', self.workflow)
        self.assertIn('python tests/windows_gui_walkthrough.py --exe build/ota-fixture/VGA-Aram-Helper.exe', self.workflow)
        for forbidden in ('--native-smoke-report', '--demo', '--headless', '--no-updates',
                          'native_qt_validation', 'pip install', 'build_windows.py'):
            self.assertNotIn(forbidden, self.workflow)

    def test_only_small_ephemeral_evidence_is_uploaded(self):
        self.assertIn('python scripts/check_artifact_budget.py --evidence-only', self.workflow)
        self.assertIn("steps.evidence_budget.outcome == 'success'", self.workflow)
        self.assertIn('path: reports/windows-gui-*', self.workflow)
        self.assertIn('retention-days: 1', self.workflow)
        self.assertNotIn('path: dist', self.workflow)
        self.assertNotIn('README', self.workflow)
        self.assertNotIn('git push', self.workflow)

    def test_summary_distinguishes_unsupported_and_excluded_pixels(self):
        self.assertIn('An input-desktop feasibility failure is not a passed GUI test.', self.workflow)
        self.assertIn('Capture-excluded overlay content must not be replaced by an offscreen rendering.', self.workflow)
        self.assertIn('windows-gui-walkthrough.json', self.workflow)


if __name__ == '__main__':
    unittest.main()

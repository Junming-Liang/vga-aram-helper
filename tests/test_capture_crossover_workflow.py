"""Static restrictions for the branch-only read-only crossover workflow."""
from pathlib import Path
import re
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / '.github/workflows/build-native-preview.yml'


class CrossoverWorkflowTests(unittest.TestCase):
    def test_only_exact_public_manual_branch_with_false_input_can_run(self):
        value = WORKFLOW.read_text(encoding='utf-8')
        for exact in ("github.event_name == 'workflow_dispatch'",
                      'github.event.repository.private == false',
                      "github.repository == 'Junming-Liang/vga-aram-helper'",
                      "github.ref == 'refs/heads/experiment/capture-opencv-crossover'",
                      'inputs.publish_preview == false', 'runs-on: windows-2022',
                      'timeout-minutes: 45', 'persist-credentials: false'):
            self.assertIn(exact, value)
        self.assertEqual(value.count('runs-on:'), 1)
        self.assertEqual(value.count('permissions:'), 1)
        self.assertIn('permissions:\n  contents: read\n', value)
        for forbidden in ('contents: write', 'GH_TOKEN', 'secrets.', '--publish',
                          'scripts/build_windows.py', 'verify_release.py',
                          'dist/', 'gh release', 'windows-latest', 'self-hosted', 'pull_request:'):
            self.assertNotIn(forbidden, value)

    def test_exact_dependency_wheels_and_original_helpers_are_used(self):
        value = WORKFLOW.read_text(encoding='utf-8')
        self.assertIn('--index-url https://pypi.org/simple --only-binary=:all: -r requirements-build.txt', value)
        self.assertIn('--only-binary=:all: --no-deps --dest build/opencv-crossover/official opencv-python-headless==5.0.0.93', value)
        self.assertEqual(value.count('python scripts/build_minimal_opencv.py'), 1)
        self.assertEqual(value.count('python scripts/build_wgc_capture.py'), 1)
        self.assertEqual(value.count('python scripts/build_wgc_session_capture.py'), 1)
        prepare = value.index('python scripts/probe_opencv_capture_crossover.py prepare')
        build = value.index('python scripts/build_minimal_opencv.py')
        run = value.index('python scripts/probe_opencv_capture_crossover.py run')
        self.assertLess(prepare, build)
        self.assertLess(build, run)
        self.assertNotIn('continue-on-error', value)
        self.assertNotIn('--regression-ratio', value)
        self.assertNotIn('--noise-floor-seconds', value)
        self.assertNotIn('--allow-non-windows', value)

    def test_summary_and_unchanged_budget_are_required_before_small_upload(self):
        value = WORKFLOW.read_text(encoding='utf-8')
        summary = value.index('python scripts/probe_opencv_capture_crossover.py summarize')
        budget = value.index('python scripts/check_artifact_budget.py --evidence-only')
        upload = value.index('uses: actions/upload-artifact@v4')
        self.assertLess(summary, budget)
        self.assertLess(budget, upload)
        self.assertEqual(value.count('if: ${{ always() }}'), 2)
        self.assertIn("if: ${{ always() && steps.evidence_budget.outcome == 'success' }}", value)
        self.assertIn('path: reports/windows-*', value)
        self.assertIn('retention-days: 1', value)
        self.assertIn('if-no-files-found: error', value)
        self.assertNotIn('path: build/', value)
        self.assertNotIn('path: reports/', value.replace('path: reports/windows-*', ''))

    def test_branch_source_files_have_exact_lf_attributes(self):
        names = ['scripts/probe_opencv_capture_crossover.py', '.github/workflows/build-native-preview.yml',
                 '.gitattributes', 'requirements-ocr.txt']
        result = subprocess.run(['git', 'check-attr', '-z', '--stdin', 'eol'], cwd=ROOT,
                                input=('\0'.join(names) + '\0').encode('utf-8'),
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        fields = result.stdout.decode('utf-8').split('\0')
        self.assertEqual(fields[-1], '')
        self.assertEqual([fields[i:i + 3] for i in range(0, len(fields) - 1, 3)],
                         [[name, 'eol', 'lf'] for name in names])


if __name__ == '__main__':
    unittest.main()

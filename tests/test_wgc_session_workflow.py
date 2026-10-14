"""Branch-only diagnostic safety contract; no CI or external action is executed."""
from pathlib import Path
import subprocess
import unittest

import yaml

from scripts.build_wgc_session_capture import SOURCE_FILES

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / '.github/workflows/build-native-preview.yml'
BRANCH = 'refs/heads/experiment/persistent-wgc-session'
GUARD = "${{ !inputs.publish_preview && github.event_name == 'workflow_dispatch' && github.event.repository.private == false && github.repository == 'Junming-Liang/vga-aram-helper' && github.ref == '" + BRANCH + "' }}"


class ExperimentWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.text = WORKFLOW.read_text(encoding='utf-8')
        # BaseLoader preserves GitHub's literal `on` key instead of YAML 1.1 bool coercion.
        self.workflow = yaml.load(self.text, Loader=yaml.BaseLoader)

    def test_manual_exact_public_branch_and_no_write_permissions(self):
        self.assertEqual(set(self.workflow['on']), {'workflow_dispatch'})
        self.assertEqual(self.workflow['on']['workflow_dispatch']['inputs']['publish_preview']['type'], 'boolean')
        self.assertEqual(self.workflow['on']['workflow_dispatch']['inputs']['publish_preview']['default'], 'false')
        self.assertEqual(self.workflow['permissions'], {})
        self.assertEqual(set(self.workflow['jobs']), {'persistent-capture-experiment'})
        job = self.workflow['jobs']['persistent-capture-experiment']
        self.assertEqual(job['if'], GUARD)
        self.assertEqual(job['runs-on'], 'windows-2022')
        self.assertEqual(job['permissions'], {'contents': 'read'})
        self.assertEqual(job['timeout-minutes'], '35')
        self.assertNotIn('secrets.', self.text)
        self.assertNotIn('GH_TOKEN', self.text)
        self.assertNotIn('continue-on-error', self.text)

    def test_exact_source_then_same_helper_frozen_and_bounded_evidence(self):
        steps = self.workflow['jobs']['persistent-capture-experiment']['steps']
        checkout = steps[0]
        self.assertEqual(checkout['uses'], 'actions/checkout@v4')
        self.assertEqual(checkout['with'], {'ref': '${{ github.sha }}', 'persist-credentials': 'false'})
        commands = [step['run'] for step in steps if 'run' in step]
        required = ['python scripts/build_wgc_session_capture.py',
                    'python tests/windows_wgc_session_capture.py',
                    'python scripts/build_wgc_session_capture.py --freeze-only',
                    'python tests/windows_wgc_session_capture.py --exe dist/wgc-session-diagnostic/WGC-Session-Diagnostic.exe']
        indexes = [commands.index(command) for command in required]
        self.assertEqual(indexes, sorted(indexes))
        self.assertNotIn('--freeze-diagnostic', self.text)
        self.assertNotIn('--publish', self.text)
        self.assertNotIn('verify_release.py', self.text)
        self.assertNotIn('python scripts/build_windows.py', self.text)
        summary = next(step for step in steps if step.get('run') == 'python tests/windows_wgc_session_capture.py --summarize')
        self.assertEqual(summary['if'], '${{ always() }}')
        budget = next(step for step in steps if step.get('id') == 'evidence_budget')
        self.assertEqual(budget['run'], 'python scripts/check_artifact_budget.py --evidence-only')
        upload = steps[-1]
        self.assertEqual(upload['uses'], 'actions/upload-artifact@v4')
        self.assertEqual(upload['if'], "${{ always() && steps.evidence_budget.outcome == 'success' }}")
        self.assertEqual(upload['with']['path'], 'reports/windows-wgc-session*.json')
        self.assertEqual(upload['with']['retention-days'], '1')

    def test_every_exact_manifest_input_has_lf_checkout_bytes(self):
        # Binary NUL input/output avoids Windows text-mode CRLF translation.
        result = subprocess.check_output(['git', 'check-attr', '-z', 'eol', '--stdin'], cwd=ROOT,
                                         input=b'\0'.join(name.encode('utf-8') for name in SOURCE_FILES) + b'\0')
        self.assertEqual(result.split(b'\0')[:-1],
                         [part for name in SOURCE_FILES for part in (name.encode('utf-8'), b'eol', b'lf')])


if __name__ == '__main__':
    unittest.main()

"""Offline safety contract, not real source/native/frozen Windows acceptance."""
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

from scripts.check_artifact_budget import check_budget

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / '.github/workflows/diagnose-native-source.yml'
NORMAL_WORKFLOW = ROOT / '.github/workflows/build-native-preview.yml'


def section(text, start, end):
    return text.split(start, 1)[1].split(end, 1)[0]


def evidence_code():
    text = WORKFLOW.read_text(encoding='utf-8')
    raw = section(text, "          @'\n", "          '@ | python -")
    return '\n'.join(line[10:] for line in raw.splitlines())


class NativeSourceDiagnosticWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.text = WORKFLOW.read_text(encoding='utf-8')
        self.configuration = '\n'.join(line for line in self.text.splitlines()
                                      if not line.lstrip().startswith('#'))
        self.steps = [block for block in re.split(
            r'^      - ', self.configuration.split('    steps:\n', 1)[1],
            flags=re.MULTILINE) if block.strip()]

    def test_manual_fixed_workflow_and_public_owned_main_only(self):
        self.assertEqual(section(self.configuration, '\non:\n', '\npermissions:').strip(),
                         'workflow_dispatch:')
        self.assertNotIn('inputs.', self.configuration)
        self.assertNotIn('inputs:', self.configuration)
        self.assertIn("    if: ${{ github.event_name == 'workflow_dispatch' && "
                      "github.event.repository.private == false && "
                      "github.repository == 'Junming-Liang/vga-aram-helper' && "
                      "github.ref == 'refs/heads/main' }}", self.configuration)
        self.assertEqual(re.findall(r'^  ([\w-]+):', section(
            self.configuration, '\njobs:\n', '    env:'), flags=re.MULTILINE),
                         ['source-diagnostic'])
        self.assertIn('    runs-on: windows-2022\n', self.configuration)
        self.assertIn('    timeout-minutes: 45\n', self.configuration)
        self.assertNotIn('self-hosted', self.configuration)
        self.assertNotIn('windows-latest', self.configuration)

    def test_read_only_permission_and_no_explicit_credentials(self):
        self.assertEqual(section(self.configuration, '\npermissions:\n', '\nconcurrency:').strip(),
                         'contents: read')
        self.assertEqual(self.configuration.count('permissions:'), 1)
        for forbidden in ('contents: write', 'actions: write', 'id-token:', 'write-all',
                          'GH_TOKEN', 'GITHUB_TOKEN', 'github.token', 'secrets.',
                          'ssh-key:', 'gh auth', 'create-github-app-token'):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, self.configuration)

    def test_exact_dispatch_checkout_never_reuses_artifacts(self):
        self.assertEqual(self.steps[0].strip(), '\n'.join((
            'uses: actions/checkout@v4', '        with:',
            '          ref: ${{ github.sha }}', '          persist-credentials: false')))
        self.assertEqual(self.configuration.count('actions/checkout@'), 1)
        self.assertIn('$head = (git rev-parse HEAD).Trim()', self.steps[3])
        self.assertIn('$head -cne $env:GITHUB_SHA', self.steps[3])
        self.assertIn('Get-ChildItem reports/windows-* -File', self.steps[3])
        self.assertIn('Existing Windows evidence cannot be reused', self.steps[3])
        self.assertIn('Diagnostic staging must be fresh.', self.steps[3])
        for forbidden in ('actions/download-artifact', 'actions/cache', 'fetch_ota_fixture',
                          'promote_verified_candidate', 'stage_verified_artifact'):
            self.assertNotIn(forbidden, self.configuration)

    def test_pinned_dependencies_and_existing_approved_helper_commands(self):
        self.assertIn('uses: actions/setup-python@v5', self.steps[1])
        self.assertIn("          python-version: '3.12'", self.steps[1])
        self.assertIn('          architecture: x64', self.steps[1])
        expected = 'python -m pip install --index-url https://pypi.org/simple --only-binary=:all: -r requirements-build.txt'
        self.assertIn(expected, self.steps[4])
        normal = NORMAL_WORKFLOW.read_text(encoding='utf-8')
        for index, command in ((5, './scripts/install-community-runtime.ps1 -AcceptCommunityLicense'),
                               (6, 'python scripts/build_wgc_capture.py'),
                               (7, 'python scripts/build_wgc_session_capture.py')):
            with self.subTest(command=command):
                self.assertIn('        run: ' + command, self.steps[index])
                self.assertIn(command, normal)
        self.assertNotIn('--extra-index-url', self.configuration)
        self.assertNotIn('--trusted-host', self.configuration)
        self.assertNotIn('--freeze-only', self.configuration)

    def test_three_source_scales_are_mandatory_in_failure_first_order(self):
        expected = ('python tests/windows_native_smoke.py --source --app-scale 1.5',
                    'python tests/windows_native_smoke.py --source',
                    'python tests/windows_native_smoke.py --source --app-scale 2')
        for step, command in zip(self.steps[8:11], expected):
            self.assertEqual(step.split('        run: ', 1)[1].strip(), command)
            self.assertIn('        timeout-minutes: 6', step)
        self.assertEqual(self.configuration.count('python tests/windows_native_smoke.py'), 3)
        # Implicit success() makes each source scale depend on every earlier gate.
        for step in self.steps[:11]:
            self.assertNotIn('        if:', step)
            self.assertNotIn('continue-on-error', step)
        self.assertNotIn('continue-on-error', self.configuration)
        self.assertNotIn('|| true', self.configuration)
        self.assertNotIn('exit 0', self.configuration)
        self.assertNotIn('QT_QPA_PLATFORM', self.configuration)

    def test_no_custom_opencv_packaging_or_release_path(self):
        for forbidden in ('python scripts/build_minimal_opencv.py', 'build_windows.py',
                          'verify_release.py', '--publish', 'publish_preview', 'gh release',
                          'gh api', 'git push', '--exe', 'dist/', 'PyInstaller',
                          'softprops/action-gh-release', 'actions/setup-node'):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, self.configuration)
        self.assertIn('Source-only diagnostic on owned synthetic Windows fixtures.', self.configuration)
        self.assertIn('Not frozen-EXE or release acceptance; no actual-game claim.', self.configuration)
        self.assertIn('Evidence staging does not turn a failed or skipped source check into a pass.', self.configuration)

    def test_failure_diagnostics_are_always_bounded_before_optional_upload(self):
        summary, budget, upload = self.steps[11:14]
        self.assertEqual(len(self.steps), 14)
        self.assertIn('        id: diagnostic_evidence', summary)
        self.assertIn('        if: ${{ always() }}', summary)
        self.assertIn('MAX_FILE_BYTES = 256 * 1024', summary)
        self.assertIn('MAX_TOTAL_BYTES = 2 * 1024 * 1024', summary)
        self.assertIn('MAX_PRINT_CHARS = 16000', summary)
        self.assertIn('        id: evidence_budget', budget)
        self.assertIn("        if: ${{ always() && steps.diagnostic_evidence.outcome == 'success' }}", budget)
        self.assertIn('python scripts/check_artifact_budget.py --evidence-only --output build/native-source-diagnostic-budget.json', budget)
        self.assertIn("        if: ${{ always() && steps.diagnostic_evidence.outcome == 'success' && steps.evidence_budget.outcome == 'success' }}", upload)
        self.assertIn('uses: actions/upload-artifact@v4', upload)
        self.assertIn('          path: build/native-source-diagnostic-evidence', upload)
        self.assertIn('          retention-days: 1', upload)
        self.assertIn('          if-no-files-found: error', upload)
        self.assertIn('${{ github.sha }}-${{ github.run_id }}-${{ github.run_attempt }}', upload)
        self.assertEqual(self.configuration.count('actions/upload-artifact@'), 1)
        self.assertNotIn('.png', summary)
        self.assertNotIn('.exe', summary)

    def test_workflow_audits_itself_before_installation(self):
        self.assertEqual(self.steps[2].split('        run: ', 1)[1].strip(),
                         "python -m unittest discover -s tests -p 'test_native_source_diagnostic_workflow.py' -v")
        for step in self.steps:
            if '        run:' in step:
                self.assertNotIn('${{', step.split('        run:', 1)[1])
        self.assertEqual(section(self.configuration, '\nconcurrency:\n', '\njobs:').strip(),
                         'group: vga-native-source-diagnostic\n  cancel-in-progress: false')


class BoundedSourceDiagnosticEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.reports = self.root / 'reports'
        self.reports.mkdir()
        self.stage = self.root / 'build/native-source-diagnostic-evidence'
        self.environment = {'GITHUB_SHA': 'a' * 40, 'GITHUB_RUN_ID': '12345',
                            'GITHUB_RUN_ATTEMPT': '1',
                            'GITHUB_STEP_SUMMARY': str(self.root / 'summary.txt')}
        self.output = io.StringIO()

    def run_evidence(self):
        previous = Path.cwd()
        try:
            os.chdir(self.root)
            with patch.dict(os.environ, self.environment, clear=True), redirect_stdout(self.output):
                exec(compile(evidence_code(), str(WORKFLOW), 'exec'), {})
        finally:
            os.chdir(previous)

    def test_current_owned_reports_keep_exact_bytes_without_extra_artifacts(self):
        name = 'windows-native-source-scale150-smoke.json'
        data = b'{"status":"failed","frozen":false,"unit_fixture":true}\n'
        (self.reports / name).write_bytes(data)
        (self.reports / 'windows-native-source-scale150-overlay.png').write_bytes(b'owned image stand-in')
        (self.reports / 'unrelated-secret.txt').write_bytes(b'never expose')
        (self.reports / 'windows-native-smoke.json').write_bytes(b'historical frozen output')
        self.run_evidence()
        self.assertEqual((self.stage / name).read_bytes(), data)
        names = {path.name for path in self.stage.iterdir()}
        self.assertEqual(names, {name, 'windows-native-source-diagnostic-inventory.json'})
        inventory = json.loads((self.stage / 'windows-native-source-diagnostic-inventory.json').read_text())
        self.assertEqual(inventory['source_sha'], self.environment['GITHUB_SHA'])
        self.assertEqual(inventory['run_id'], '12345')
        self.assertEqual(inventory['evidence_bytes'], len(data))
        self.assertNotIn('never expose', self.output.getvalue())
        self.assertNotIn('historical frozen output', self.output.getvalue())
        self.assertNotIn('owned image stand-in', self.output.getvalue())
        self.assertIn('"status":"failed"', self.output.getvalue())

    def test_missing_reports_remain_missing_not_successful(self):
        self.run_evidence()
        inventory = json.loads((self.stage / 'windows-native-source-diagnostic-inventory.json').read_text())
        self.assertEqual(inventory['files'], [])
        self.assertNotIn('status', inventory)
        self.assertIn('not produced', self.output.getvalue())
        self.assertIn('Not frozen-EXE or release acceptance', inventory['scope'])

    def test_oversized_log_prints_bounded_edges_but_blocks_artifact_staging(self):
        path = self.reports / 'windows-native-source-scale150-process.log'
        path.write_bytes(b'FIRST\n' + b'x' * (300 * 1024) + b'\nLAST')
        with self.assertRaisesRegex(SystemExit, 'per-file evidence cap'):
            self.run_evidence()
        self.assertFalse(self.stage.exists())
        output = self.output.getvalue()
        self.assertIn('FIRST', output)
        self.assertIn('LAST', output)
        self.assertIn('middle omitted', output)
        self.assertLess(len(output), 35000)

    def test_aggregate_cap_blocks_many_individually_bounded_files(self):
        prefixes = ('windows-native-source-scale150', 'windows-native-source', 'windows-native-source-scale200')
        for prefix in prefixes:
            for suffix in ('smoke.json', 'overlay.json', 'process.log'):
                (self.reports / (prefix + '-' + suffix)).write_bytes(b'x' * (240 * 1024))
        with self.assertRaisesRegex(SystemExit, 'Combined evidence exceeds 2 MiB'):
            self.run_evidence()
        self.assertFalse(self.stage.exists())

    def test_preexisting_staging_is_rejected_without_overwrite(self):
        self.stage.mkdir(parents=True)
        sentinel = self.stage / 'keep.txt'
        sentinel.write_text('preserve original')
        with self.assertRaises(FileExistsError):
            self.run_evidence()
        self.assertEqual(sentinel.read_text(), 'preserve original')

    def test_existing_budget_covers_exact_staged_files_and_metadata(self):
        for prefix in ('windows-native-source-scale150', 'windows-native-source', 'windows-native-source-scale200'):
            (self.reports / (prefix + '-process.log')).write_bytes(b'x' * 4096)
        self.run_evidence()
        calls = []
        def no_artifacts(url):
            calls.append(url)
            return {'total_count': 0, 'artifacts': []}
        result = check_budget(self.root, fetcher=no_artifacts, evidence_only=True,
                              output_path='build/native-source-diagnostic-budget.json')
        self.assertEqual(result['status'], 'passed')
        self.assertEqual(result['upload_scope'], 'evidence-only')
        actual = sum(path.stat().st_size for path in self.stage.iterdir())
        self.assertGreater(result['proposed_upper_estimate_bytes'], actual)
        self.assertEqual(calls, ['https://api.github.com/repos/Junming-Liang/vga-aram-helper/actions/artifacts?per_page=100&page=1'])


if __name__ == '__main__':
    unittest.main()

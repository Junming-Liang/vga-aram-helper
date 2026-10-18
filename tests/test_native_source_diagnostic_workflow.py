"""Offline workflow/binding contracts, never actual source/frozen Windows acceptance."""
from contextlib import redirect_stdout
import copy
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
import zipfile

from app_version import __version__
from scripts.check_artifact_budget import check_budget

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / '.github/workflows/diagnose-native-source.yml'
NORMAL_WORKFLOW = ROOT / '.github/workflows/build-native-preview.yml'


def section(text, start, end):
    return text.split(start, 1)[1].split(end, 1)[0]


def inline_code(index):
    blocks = re.findall(r"^          @'\n(.*?)^          '@", WORKFLOW.read_text(encoding='utf-8'), re.M | re.S)
    return '\n'.join(line[10:] if line else '' for line in blocks[index].splitlines())


def workflow_steps(text):
    return [block for block in re.split(r'^      - ', text.split('    steps:\n', 1)[1], flags=re.M)
            if block.strip()]


class NativeSourceDiagnosticWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.text = WORKFLOW.read_text(encoding='utf-8')
        self.configuration = '\n'.join(line for line in self.text.splitlines()
                                      if not line.lstrip().startswith('#'))
        self.steps = workflow_steps(self.configuration)

    def test_manual_fixed_workflow_and_public_owned_main_only(self):
        self.assertEqual(section(self.configuration, '\non:\n', '\npermissions:').strip(), 'workflow_dispatch:')
        self.assertNotIn('inputs.', self.configuration)
        self.assertNotIn('inputs:', self.configuration)
        self.assertIn("    if: ${{ github.event_name == 'workflow_dispatch' && "
                      "github.event.repository.private == false && "
                      "github.repository == 'Junming-Liang/vga-aram-helper' && "
                      "github.ref == 'refs/heads/main' }}", self.configuration)
        self.assertEqual(re.findall(r'^  ([\w-]+):', section(
            self.configuration, '\njobs:\n', '    env:'), flags=re.M), ['source-diagnostic'])
        self.assertIn('    runs-on: windows-2022\n', self.configuration)
        self.assertIn('    timeout-minutes: 60\n', self.configuration)
        self.assertNotIn('self-hosted', self.configuration)
        self.assertNotIn('windows-latest', self.configuration)

    def test_read_only_permission_and_no_explicit_credentials(self):
        self.assertEqual(section(self.configuration, '\npermissions:\n', '\nconcurrency:').strip(), 'contents: read')
        self.assertEqual(self.configuration.count('permissions:'), 1)
        for forbidden in ('contents: write', 'actions: write', 'id-token:', 'write-all',
                          'GH_TOKEN', 'GITHUB_TOKEN', 'github.token', 'secrets.',
                          'ssh-key:', 'gh auth', 'create-github-app-token'):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, self.configuration)

    def test_exact_dispatch_checkout_and_fresh_outputs(self):
        self.assertEqual(self.steps[0].strip(), '\n'.join((
            'uses: actions/checkout@v4', '        with:',
            '          ref: ${{ github.sha }}', '          persist-credentials: false')))
        self.assertEqual(self.configuration.count('actions/checkout@'), 1)
        self.assertIn('$head = (git rev-parse HEAD).Trim()', self.steps[3])
        self.assertIn('$head -cne $env:GITHUB_SHA', self.steps[3])
        self.assertIn('Get-ChildItem reports/windows-* -File', self.steps[3])
        for path in ('dist/VGA-Aram-Helper.exe', 'build/native-frozen150-second',
                     'build/native-source-diagnostic-evidence'):
            self.assertIn('Test-Path ' + path, self.steps[3])
        for forbidden in ('actions/download-artifact', 'actions/cache', 'fetch_ota_fixture',
                          'promote_verified_candidate', 'stage_verified_artifact'):
            self.assertNotIn(forbidden, self.configuration)

    def test_official_requirements_and_approved_helper_commands(self):
        self.assertIn('uses: actions/setup-python@v5', self.steps[1])
        self.assertIn("          python-version: '3.12'", self.steps[1])
        self.assertIn('          architecture: x64', self.steps[1])
        expected = 'python -m pip install --index-url https://pypi.org/simple --only-binary=:all: -r requirements-build.txt'
        self.assertIn(expected, self.steps[4])
        normal = NORMAL_WORKFLOW.read_text(encoding='utf-8')
        for index, command in ((5, './scripts/install-community-runtime.ps1 -AcceptCommunityLicense'),
                               (6, 'python scripts/build_wgc_capture.py'),
                               (7, 'python scripts/build_wgc_session_capture.py')):
            self.assertIn('        run: ' + command, self.steps[index])
            self.assertIn(command, normal)
        self.assertNotIn('--extra-index-url', self.configuration)
        self.assertNotIn('--trusted-host', self.configuration)
        self.assertNotIn('--freeze-only', self.configuration)

    def test_source_baseline_precedes_identical_normal_custom_build_pipeline(self):
        expected = ('python tests/windows_native_smoke.py --source --app-scale 1.5',
                    'python tests/windows_native_smoke.py --source',
                    'python tests/windows_native_smoke.py --source --app-scale 2')
        for step, command in zip(self.steps[8:11], expected):
            self.assertEqual(step.split('        run: ', 1)[1].strip(), command)
        normal_steps = workflow_steps(NORMAL_WORKFLOW.read_text(encoding='utf-8'))
        for step in self.steps[11:14]:
            title = step.splitlines()[0]
            normal = next(block for block in normal_steps if block.splitlines()[0] == title)
            self.assertEqual(step.strip(), normal.strip())
        self.assertEqual(self.steps[14].split('        run: ', 1)[1].strip(), 'python scripts/build_windows.py')
        self.assertEqual(self.configuration.count('run: python scripts/build_windows.py'), 1)
        self.assertIn("      VGA_RELEASE_PACKAGE_PROFILE: 'minimal-opencv-v1'", self.configuration)
        self.assertEqual(self.configuration.count("VGA_RELEASE_PACKAGE_PROFILE:"), 1)

    def test_four_fresh_frozen_processes_use_one_exe_and_stop_after_failure(self):
        cases = (
            ('frozen150-first', ' --app-scale 1.5'),
            ('frozen150-second', ' --app-scale 1.5 --report-dir build/native-frozen150-second/reports'),
            ('frozen100', ''), ('frozen200', ' --app-scale 2'))
        for step, (label, options) in zip(self.steps[16:20], cases):
            self.assertEqual(step.split('        run: |\n', 1)[1].strip(), '\n'.join((
                'python build/native-diagnostic-bindings.py before ' + label,
                '          if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }',
                '          python tests/windows_native_smoke.py --exe dist/VGA-Aram-Helper.exe' + options)))
            self.assertIn('        timeout-minutes: 6', step)
        self.assertEqual(self.steps[20].split('        run: ', 1)[1].strip(), 'python build/native-diagnostic-bindings.py verify')
        self.assertEqual(self.configuration.count('python tests/windows_native_smoke.py'), 7)
        for step in self.steps[:21]:
            self.assertNotIn('        if:', step)
        for forbidden in ('continue-on-error', '|| true', 'exit 0', 'QT_QPA_PLATFORM', '--skip', '--retry'):
            self.assertNotIn(forbidden, self.configuration)

    def test_no_release_publication_or_unrelated_acceptance_claim(self):
        for forbidden in ('verify_release.py', '--publish', 'publish_preview', 'gh release',
                          'gh api', 'git push', 'softprops/action-gh-release', 'actions/setup-node',
                          'windows_ota_smoke', 'windows_automatic_capture', 'windows_wgc_capture.py'):
            self.assertNotIn(forbidden, self.configuration)
        self.assertIn('Not complete release acceptance or proof of the original Run 80 cause.', self.configuration)
        self.assertIn('Evidence staging does not turn any failed or skipped check into a pass.', self.configuration)

    def test_always_bounded_text_evidence_and_exact_staging_budget(self):
        postbuild, summary, budget, upload = self.steps[21:25]
        self.assertEqual(len(self.steps), 25)
        self.assertIn('        if: ${{ always() }}', postbuild)
        self.assertIn('python scripts/probe_opencv_postbuild.py summarize', postbuild)
        self.assertIn('        id: diagnostic_evidence', summary)
        self.assertIn('        if: ${{ always() }}', summary)
        for cap in ('MAX_FILE_BYTES = 256 * 1024', 'MAX_TOTAL_BYTES = 2 * 1024 * 1024', 'MAX_PRINT_CHARS = 16000'):
            self.assertIn(cap, summary)
        self.assertIn("        if: ${{ always() && steps.diagnostic_evidence.outcome == 'success' }}", budget)
        self.assertIn("check_budget(Path('build/native-source-diagnostic-evidence'), evidence_only=True, output_path='../native-source-diagnostic-budget.json')", budget)
        self.assertIn("        if: ${{ always() && steps.diagnostic_evidence.outcome == 'success' && steps.evidence_budget.outcome == 'success' }}", upload)
        self.assertIn('uses: actions/upload-artifact@v4', upload)
        self.assertIn('          path: build/native-source-diagnostic-evidence/reports', upload)
        self.assertIn('          retention-days: 1', upload)
        self.assertIn('          if-no-files-found: error', upload)
        self.assertIn('${{ github.sha }}-${{ github.run_id }}-${{ github.run_attempt }}', upload)
        self.assertEqual(self.configuration.count('actions/upload-artifact@'), 1)
        self.assertNotIn('.png', summary)
        self.assertNotIn('.exe', summary)

    def test_stdlib_only_audit_precedes_install_and_no_shell_input_interpolation(self):
        self.assertEqual(self.steps[2].split('        run: ', 1)[1].strip(),
                         "python -m unittest discover -s tests -p 'test_native_source_diagnostic_workflow.py' -v")
        for step in self.steps:
            if '        run:' in step:
                self.assertNotIn('${{', step.split('        run:', 1)[1])
        self.assertEqual(section(self.configuration, '\nconcurrency:\n', '\njobs:').strip(),
                         'group: vga-native-source-diagnostic\n  cancel-in-progress: false')
        for index in (0, 1):
            compile(inline_code(index), str(WORKFLOW), 'exec')


class FreshExeBindingTests(unittest.TestCase):
    """Execute the workflow's real inline code; native build dependencies are stubs.

    Fixtures are deliberately synthetic bytes, never real Windows evidence.
    The existing build/export validators retain their independent test suites.
    """
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.sha = 'a' * 40
        self.environment = {'GITHUB_SHA': self.sha, 'GITHUB_REPOSITORY': 'Junming-Liang/vga-aram-helper',
                            'GITHUB_RUN_ID': '12345', 'GITHUB_RUN_ATTEMPT': '1',
                            'VGA_RELEASE_PACKAGE_PROFILE': 'minimal-opencv-v1'}
        self.envpatch = patch.dict(os.environ, self.environment, clear=True)
        self.envpatch.start()
        self.addCleanup(self.envpatch.stop)
        self.output = io.StringIO()
        self.stdout = redirect_stdout(self.output)
        self.stdout.__enter__()
        self.addCleanup(self.stdout.__exit__, None, None, None)
        self.ns = {'__name__': 'offline_diagnostic_binding_fixture'}
        oldpath = list(sys.path)
        exec(compile(inline_code(0), str(WORKFLOW), 'exec'), self.ns)
        sys.path[:] = oldpath
        self.ns['ROOT'] = self.root
        self.checkout_sha = self.sha
        self.export_status = 'completed'
        self.receipt_status = 'passed'
        builder = types.ModuleType('scripts.build_windows')
        builder.verify_source_checkout = lambda root, expected: self.checkout_sha
        postbuild = types.ModuleType('scripts.probe_opencv_postbuild')
        postbuild.SOURCE_FILES = ('scripts/config.py',)
        postbuild.EVIDENCE_NAMES = ('windows-opencv-proof.json',)
        postbuild.EXPORT_NAMES = {'parity': 'windows-opencv-parity.json'}
        postbuild.validate_export = lambda: ({'status': self.export_status}, {'status': self.receipt_status})
        duty = types.ModuleType('overlay_duty_contract')
        duty.SOURCE_FILES = ('native_ui.py',)
        self.modules = patch.dict(sys.modules, {'scripts.build_windows': builder,
                                  'scripts.probe_opencv_postbuild': postbuild, 'overlay_duty_contract': duty})
        self.modules.start()
        self.addCleanup(self.modules.stop)
        for name in (*self.ns['CONFIG_INPUTS'], 'native_ui.py', 'scripts/config.py'):
            self.put(name, b'owned synthetic source bytes\n')
        self.put('dist/VGA-Aram-Helper.exe', b'synthetic-exe-bytes-never-executed')
        self.named = 'dist/release/vga-aram-helper-' + __version__ + '-windows-x64.exe'
        self.archive = 'dist/release/vga-aram-helper-' + __version__ + '-source.zip'
        self.put(self.named, (self.root / 'dist/VGA-Aram-Helper.exe').read_bytes())
        with zipfile.ZipFile(self.root / self.archive, 'w') as source:
            source.writestr('unit-fixture.txt', 'synthetic archive')
            source.comment = self.sha.encode('ascii')
        self.manifest = dict(version=__version__, **self.ns['file_record']('dist/VGA-Aram-Helper.exe'))
        self.access = dict(source_commit=self.sha,
                           application_source=dict(filename=Path(self.archive).name, **self.ns['file_record'](self.archive)))
        self.build = dict(status='built-not-yet-smoke-tested', source_commit=self.sha,
                          version=__version__, package_profile='minimal-opencv-v1', experimental=False,
                          opencv_custom_build=dict(status='passed', source_commit=self.sha, package_profile='minimal-opencv-v1'),
                          manifest=self.manifest, source_access=self.access)
        self.write_json('dist/release/update-manifest.json', self.manifest)
        self.write_json('dist/release/source-access.json', self.access)
        self.write_json('reports/windows-build.json', self.build)
        for path in self.ns['fixed_bound_names'](__version__):
            if not (self.root / path).exists():
                self.put(path, b'unit-fixture build/env/proof bytes\n')
        self.identity = dict(source_sha=self.sha, version=__version__, source_files=self.ns['source_hashes'](),
                             exe=self.ns['file_record']('dist/VGA-Aram-Helper.exe'))
        for directory, prefix, scale in self.ns['SOURCE_CASES']:
            self.make_case(directory, prefix, scale, frozen=False)

    def put(self, path, data):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    def write_json(self, path, value):
        self.put(path, (json.dumps(value) + '\n').encode('utf-8'))

    def read_json(self, path):
        return json.loads((self.root / path).read_text())

    def make_case(self, directory, prefix, scale, *, frozen=True, **changes):
        native = prefix + '-overlay.json'
        self.write_json(directory + '/' + native, {'scope': 'unit fixture only', 'scale': scale})
        result = dict(status='passed', frozen=frozen, source_commit=self.sha, applicationVersion=__version__,
                      requested_app_scale=scale, process_exited=True,
                      source_files={name: self.identity['source_files'][name] for name in self.ns['duty_inputs']()},
                      manual_hero_switches=dict(required=8, attempted=8, completed=8),
                      executable_sha256=self.identity['exe']['sha256'] if frozen else None,
                      native_report=native, native_report_sha256=self.ns['file_record'](directory + '/' + native)['sha256'])
        if frozen:
            result['executable_size'] = self.identity['exe']['size']
        result.update(changes)
        path = directory + '/' + prefix + '-smoke.json'
        self.write_json(path, result)
        return path

    def record(self):
        self.identity = self.ns['record_identity']()
        return self.identity

    def frozen_case(self, index, **changes):
        _, directory, prefix, scale = self.ns['CASES'][index]
        return self.make_case(directory, prefix, scale, **changes)

    def test_valid_fresh_source_and_four_frozen_cases_bind_one_exe(self):
        identity = self.record()
        self.assertEqual(identity['source_sha'], self.sha)
        self.assertIn('capture_cadence.py', identity['source_files'])
        for index, case in enumerate(self.ns['CASES']):
            self.ns['before_case'](case[0])
            self.frozen_case(index)
        result = self.ns['verify_all']()
        self.assertEqual(result['status'], 'passed')
        self.assertEqual(result['frozen_manual_switches'], 32)
        self.assertEqual(result['source_manual_switches'], 24)
        self.assertEqual(result['exe'], identity['exe'])
        self.assertEqual(len({row['report'] for row in result['runs']}), 4)
        self.assertIn('Not complete release acceptance', result['scope'])
        self.assertEqual(result['identity_file'], self.ns['file_record'](self.ns['IDENTITY']))

    def test_wrong_dispatch_sha_and_checkout_are_rejected(self):
        for value in ('invalid', 'b' * 40):
            with self.subTest(sha=value), patch.dict(os.environ, {'GITHUB_SHA': value}):
                with self.assertRaisesRegex(RuntimeError, 'dispatch SHA'):
                    self.record()
        self.assertFalse((self.root / self.ns['IDENTITY']).exists())

    def test_wrong_repository_and_active_profile_are_rejected(self):
        for key, value in (('GITHUB_REPOSITORY', 'someone/else'), ('VGA_RELEASE_PACKAGE_PROFILE', ''),
                           ('VGA_RELEASE_PACKAGE_PROFILE', 'experimental-custom')):
            with self.subTest(key=key, value=value), patch.dict(os.environ, {key: value}):
                with self.assertRaisesRegex(RuntimeError, 'Wrong repository|Wrong active build profile'):
                    self.record()

    def test_wrong_build_source_version_profile_and_experimental_are_rejected(self):
        for key, value in (('source_commit', 'b' * 40), ('version', '0.4.14'),
                           ('package_profile', 'official'), ('experimental', True), ('status', 'failed')):
            with self.subTest(key=key):
                build = {**self.build, key: value}
                self.write_json('reports/windows-build.json', build)
                with self.assertRaisesRegex(RuntimeError, 'Build source/version/profile'):
                    self.record()

    def test_wrong_custom_profile_or_source_is_rejected(self):
        for key, value in (('status', 'failed'), ('source_commit', 'b' * 40), ('package_profile', 'official')):
            with self.subTest(key=key):
                build = copy.deepcopy(self.build)
                build['opencv_custom_build'][key] = value
                self.write_json('reports/windows-build.json', build)
                with self.assertRaisesRegex(RuntimeError, 'Custom OpenCV build proof'):
                    self.record()

    def test_incomplete_comparison_or_restoration_never_records_identity(self):
        self.export_status = 'failed'
        with self.assertRaisesRegex(RuntimeError, 'comparison/restoration'):
            self.record()
        self.export_status = 'completed'
        self.receipt_status = 'failed'
        with self.assertRaisesRegex(RuntimeError, 'comparison/restoration'):
            self.record()

    def test_exe_manifest_and_named_copy_changes_are_rejected(self):
        path = 'dist/VGA-Aram-Helper.exe'
        original = (self.root / path).read_bytes()
        self.put(path, b'x' * len(original))
        with self.assertRaisesRegex(RuntimeError, 'Fresh EXE differs'):
            self.record()
        self.put(path, original)
        self.put(self.named, b'y' * len(original))
        with self.assertRaisesRegex(RuntimeError, 'Named EXE copy differs'):
            self.record()

    def test_source_archive_wrong_comment_rejected_even_with_updated_receipts(self):
        with zipfile.ZipFile(self.root / self.archive, 'a') as source:
            source.comment = ('b' * 40).encode('ascii')
        self.access['application_source'].update(self.ns['file_record'](self.archive))
        self.write_json('dist/release/source-access.json', self.access)
        self.write_json('reports/windows-build.json', self.build)
        with self.assertRaisesRegex(RuntimeError, 'Source archive commit'):
            self.record()

    def test_exe_changed_between_processes_is_rejected(self):
        self.record()
        self.frozen_case(0)
        self.put('dist/VGA-Aram-Helper.exe', b'x' * self.identity['exe']['size'])
        with self.assertRaisesRegex(RuntimeError, 'Fresh EXE bytes changed'):
            self.ns['before_case']('frozen150-second')

    def test_source_config_build_environment_and_proof_changes_are_rejected(self):
        self.record()
        for name in ('capture_cadence.py', '.github/workflows/diagnose-native-source.yml',
                     'reports/windows-build.json', 'reports/windows-build-environment.txt',
                     'reports/windows-opencv-proof.json'):
            with self.subTest(name=name):
                original = (self.root / name).read_bytes()
                self.put(name, original + b'changed')
                with self.assertRaisesRegex(RuntimeError, 'bytes changed'):
                    self.ns['before_case']('frozen150-first')
                self.put(name, original)

    def test_prior_run_or_attempt_and_dispatch_change_are_rejected(self):
        self.record()
        for key, value in (('GITHUB_RUN_ID', 'old'), ('GITHUB_RUN_ATTEMPT', '2'), ('GITHUB_SHA', 'b' * 40)):
            with self.subTest(key=key), patch.dict(os.environ, {key: value}):
                with self.assertRaises(RuntimeError):
                    self.ns['before_case']('frozen150-first')

    def test_all_preexisting_target_outputs_are_rejected_without_overwrite(self):
        self.record()
        for suffix in ('smoke.json', 'overlay.json', 'overlay.png', 'process.log', 'last-launch-error.txt'):
            path = self.root / ('reports/windows-native-scale150-' + suffix)
            path.write_bytes(b'preserve existing bytes')
            with self.subTest(suffix=suffix), self.assertRaisesRegex(RuntimeError, 'output reuse rejected'):
                self.ns['before_case']('frozen150-first')
            self.assertEqual(path.read_bytes(), b'preserve existing bytes')
            path.unlink()

    def test_second_process_requires_successful_first_process_and_exact_report(self):
        self.record()
        with self.assertRaisesRegex(RuntimeError, 'Missing'):
            self.ns['before_case']('frozen150-second')
        mutations = ({'status': 'failed'}, {'source_commit': 'b' * 40}, {'executable_sha256': 'c' * 64},
                     {'executable_size': 1}, {'manual_hero_switches': dict(required=8, attempted=8, completed=7)},
                     {'process_exited': False}, {'requested_app_scale': True}, {'frozen': False},
                     {'native_report_sha256': 'd' * 64}, {'source_files': {}}, {'error': 'retained failure'})
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                self.frozen_case(0, **mutation)
                with self.assertRaises(RuntimeError):
                    self.ns['before_case']('frozen150-second')
        self.frozen_case(0)
        self.ns['before_case']('frozen150-second')

    def test_source_report_cannot_be_replaced_after_recording(self):
        self.record()
        directory, prefix, scale = self.ns['SOURCE_CASES'][0]
        self.make_case(directory, prefix, scale, frozen=False, fixture_changed=True)
        with self.assertRaisesRegex(RuntimeError, 'Source diagnostic evidence changed'):
            self.ns['before_case']('frozen150-first')

    def test_receipt_cannot_select_arbitrary_bound_inventory(self):
        self.record()
        receipt = self.read_json(self.ns['IDENTITY'])
        receipt['bound_files']['../../outside.txt'] = {'size': 1, 'sha256': 'x'}
        self.write_json(self.ns['IDENTITY'], receipt)
        with self.assertRaisesRegex(RuntimeError, 'Bound proof inventory changed'):
            self.ns['check_identity']()

    def test_final_check_rejects_missing_failed_or_changed_exe(self):
        self.record()
        for index in range(3):
            self.frozen_case(index)
        with self.assertRaisesRegex(RuntimeError, 'Missing'):
            self.ns['verify_all']()
        self.frozen_case(3, status='failed')
        with self.assertRaisesRegex(RuntimeError, 'Failed'):
            self.ns['verify_all']()
        self.frozen_case(3)
        self.put('dist/VGA-Aram-Helper.exe', b'x' * self.identity['exe']['size'])
        with self.assertRaisesRegex(RuntimeError, 'Fresh EXE bytes changed'):
            self.ns['verify_all']()
        self.assertFalse((self.root / self.ns['RESULT']).exists())

    def test_record_and_final_result_are_write_once(self):
        self.record()
        with self.assertRaises(FileExistsError):
            self.record()
        for index in range(4):
            self.frozen_case(index)
        self.ns['verify_all']()
        with self.assertRaises(FileExistsError):
            self.ns['verify_all']()


class BoundedSourceDiagnosticEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.reports = self.root / 'reports'
        self.reports.mkdir()
        self.stage = self.root / 'build/native-source-diagnostic-evidence/reports'
        self.environment = {'GITHUB_SHA': 'a' * 40, 'GITHUB_RUN_ID': '12345',
                            'GITHUB_RUN_ATTEMPT': '1', 'GITHUB_STEP_SUMMARY': str(self.root / 'summary.txt')}
        self.output = io.StringIO()

    def run_evidence(self):
        previous = Path.cwd()
        try:
            os.chdir(self.root)
            with patch.dict(os.environ, self.environment, clear=True), redirect_stdout(self.output):
                exec(compile(inline_code(1), str(WORKFLOW), 'exec'), {})
        finally:
            os.chdir(previous)

    def test_current_source_and_frozen_reports_keep_exact_bytes_without_binary_artifacts(self):
        name = 'windows-native-source-scale150-smoke.json'
        data = b'{"status":"failed","frozen":false,"unit_fixture":true}\n'
        (self.reports / name).write_bytes(data)
        (self.reports / 'windows-native-source-scale150-overlay.png').write_bytes(b'owned image stand-in')
        (self.reports / 'VGA-Aram-Helper.exe').write_bytes(b'owned exe stand-in')
        (self.reports / 'unrelated-secret.txt').write_bytes(b'never expose')
        frozen = 'windows-native-scale150-smoke.json'
        (self.reports / frozen).write_bytes(b'{"unit_fixture":"first frozen process"}')
        second = self.root / 'build/native-frozen150-second/reports'
        second.mkdir(parents=True)
        (second / frozen).write_bytes(b'{"unit_fixture":"second frozen process"}')
        self.run_evidence()
        self.assertEqual((self.stage / name).read_bytes(), data)
        self.assertEqual((self.stage / frozen).read_bytes(), (self.reports / frozen).read_bytes())
        self.assertEqual((self.stage / 'windows-native-frozen150-second-smoke.json').read_bytes(), (second / frozen).read_bytes())
        names = {path.name for path in self.stage.iterdir()}
        self.assertEqual(names, {name, frozen, 'windows-native-frozen150-second-smoke.json',
                                 'windows-native-source-diagnostic-inventory.json'})
        inventory = json.loads((self.stage / 'windows-native-source-diagnostic-inventory.json').read_text())
        self.assertEqual(inventory['source_sha'], self.environment['GITHUB_SHA'])
        self.assertEqual(inventory['run_id'], '12345')
        for text in ('never expose', 'owned image stand-in', 'owned exe stand-in'):
            self.assertNotIn(text, self.output.getvalue())
        self.assertIn('"status":"failed"', self.output.getvalue())

    def test_full_bounded_json_preserves_middle_failure_cause(self):
        value = {'head': 'x' * 20000, 'critical_failure': 'native-error-in-middle', 'tail': 'y' * 20000}
        (self.reports / 'windows-native-scale150-overlay.json').write_text(json.dumps(value))
        self.run_evidence()
        self.assertIn('native-error-in-middle', self.output.getvalue())
        self.assertNotIn('middle omitted', self.output.getvalue())

    def test_missing_reports_remain_missing_not_successful(self):
        self.run_evidence()
        inventory = json.loads((self.stage / 'windows-native-source-diagnostic-inventory.json').read_text())
        self.assertEqual(inventory['files'], [])
        self.assertNotIn('status', inventory)
        self.assertIn('not produced', self.output.getvalue())
        self.assertIn('not complete release acceptance', inventory['scope'])

    def test_oversized_log_prints_bounded_edges_but_blocks_artifact_staging(self):
        (self.reports / 'windows-native-source-scale150-process.log').write_bytes(b'FIRST\n' + b'x' * (300 * 1024) + b'\nLAST')
        with self.assertRaisesRegex(SystemExit, 'per-file evidence cap'):
            self.run_evidence()
        self.assertFalse(self.stage.exists())
        output = self.output.getvalue()
        self.assertIn('FIRST', output)
        self.assertIn('LAST', output)
        self.assertIn('middle omitted', output)
        self.assertLess(len(output), 37000)

    def test_aggregate_cap_blocks_many_individually_bounded_files(self):
        for prefix in ('windows-native-source-scale150', 'windows-native-source', 'windows-native-source-scale200'):
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

    def test_existing_budget_counts_exact_flat_staged_files_including_second_process(self):
        for prefix in ('windows-native-source-scale150', 'windows-native', 'windows-native-scale150', 'windows-native-scale200'):
            (self.reports / (prefix + '-process.log')).write_bytes(b'x' * 4096)
        second = self.root / 'build/native-frozen150-second/reports'
        second.mkdir(parents=True)
        (second / 'windows-native-scale150-process.log').write_bytes(b'y' * 240000)
        self.run_evidence()
        calls = []
        def no_artifacts(url):
            calls.append(url)
            return {'total_count': 0, 'artifacts': []}
        result = check_budget(self.stage.parent, fetcher=no_artifacts, evidence_only=True,
                              output_path='../native-source-diagnostic-budget.json')
        actual = sum(path.stat().st_size for path in self.stage.iterdir())
        self.assertEqual(result['status'], 'passed')
        self.assertEqual(result['upload_scope'], 'evidence-only')
        self.assertEqual(result['proposed_upper_estimate_bytes'], math.ceil(actual * 1.03) + 1_000_000)
        self.assertLessEqual(actual, 2 * 1024 * 1024)
        self.assertFalse((self.stage / 'native-source-diagnostic-budget.json').exists())
        self.assertEqual(calls, ['https://api.github.com/repos/Junming-Liang/vga-aram-helper/actions/artifacts?per_page=100&page=1'])


if __name__ == '__main__':
    unittest.main()

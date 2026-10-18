"""Offline contract for one fixed artifact's nonpublic draft recovery.

These tests intentionally use only the standard library, like other workflow
contracts in this repository. Runtime provenance, byte limits and draft-only
release operations are verified separately by the promoter's own tests.
"""
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / '.github/workflows/promote-verified-candidate.yml'
FIXED_INPUTS = {
    'run_id': ('CANDIDATE_RUN_ID', '39098790761'),
    'source_sha': ('CANDIDATE_SOURCE_SHA', '52b8720e2aa7f2b43afa5f1f73e884157f15deb6'),
    'run_attempt': ('CANDIDATE_RUN_ATTEMPT', '1'),
    'artifact_id': ('CANDIDATE_ARTIFACT_ID', '12125904800'),
    'artifact_sha256': (
        'CANDIDATE_ARTIFACT_SHA256',
        'ed3eb0d5aca6c909c8794d9513f103ba8ca6127a3cf48497a8548d9f84652b27',
    ),
}


def section(text, start, end):
    """Read a known top-level contract section without a YAML dependency."""
    return text.split(start, 1)[1].split(end, 1)[0]


class CandidatePromotionWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.workflow = WORKFLOW.read_text(encoding='utf-8')
        # Comments are not executable workflow configuration.
        self.configuration = '\n'.join(
            line for line in self.workflow.splitlines()
            if not line.lstrip().startswith('#')
        )
        self.steps = self.configuration.split('    steps:\n', 1)[1]
        self.step_blocks = [
            block for block in re.split(r'^      - ', self.steps, flags=re.MULTILINE)
            if block.strip()
        ]

    def test_manual_dispatch_is_the_only_trigger_and_inputs_are_exact(self):
        trigger = section(self.configuration, '\non:\n', '\npermissions:')
        self.assertEqual(re.findall(r'^  ([\w-]+):', trigger, flags=re.MULTILINE),
                         ['workflow_dispatch'])
        self.assertEqual(
            set(re.findall(r'^      (\w+):', trigger, flags=re.MULTILINE)),
            set(FIXED_INPUTS),
        )
        for name, (_, value) in FIXED_INPUTS.items():
            with self.subTest(input=name):
                match = re.search(
                    rf'^      {name}:\n(?P<fields>(?:^        .*(?:\n|$))+)',
                    trigger, flags=re.MULTILINE,
                )
                self.assertIsNotNone(match)
                fields = match.group('fields')
                self.assertIn('        required: true', fields)
                self.assertIn('        type: string', fields)
                self.assertIn(f"        default: '{value}'", fields)

    def test_only_public_owned_main_dispatch_can_run(self):
        jobs = section(self.configuration, '\njobs:\n', '    env:\n')
        self.assertEqual(re.findall(r'^  ([\w-]+):', jobs, flags=re.MULTILINE),
                         ['stage-verified-draft'])
        self.assertIn(
            "    if: ${{ github.event_name == 'workflow_dispatch' && "
            "github.event.repository.private == false && "
            "github.repository == 'Junming-Liang/vga-aram-helper' && "
            "github.ref == 'refs/heads/main' }}", jobs,
        )
        self.assertIn('    runs-on: windows-2022\n', jobs)
        self.assertNotIn('self-hosted', self.configuration)
        self.assertNotIn('windows-latest', self.configuration)

    def test_one_shared_release_lock_and_bounded_time(self):
        concurrency = section(self.configuration, '\nconcurrency:\n', '\njobs:')
        self.assertEqual(concurrency.strip(),
                         'group: vga-native-preview-v0.4.14\n  cancel-in-progress: false')
        self.assertEqual(self.configuration.count('concurrency:'), 1)
        self.assertNotIn('cancel-in-progress: true', self.configuration)
        self.assertIn('    timeout-minutes: 20\n', self.configuration)
        self.assertIn('        timeout-minutes: 1\n', self.step_blocks[0])
        self.assertIn('        timeout-minutes: 6\n', self.step_blocks[3])
        self.assertIn('        timeout-minutes: 12\n', self.step_blocks[4])

    def test_permissions_and_ephemeral_token_are_narrow(self):
        self.assertIn('\npermissions: {}\n', self.configuration)
        permissions = section(self.configuration, '    permissions:\n', '    env:\n')
        self.assertEqual(permissions, '      actions: read\n      contents: write\n')
        self.assertEqual(self.configuration.count('GH_TOKEN:'), 1)
        self.assertEqual(self.configuration.count('${{ github.token }}'), 1)
        self.assertNotIn('GH_TOKEN:', ''.join(self.step_blocks[:-1]))
        self.assertIn('          GH_TOKEN: ${{ github.token }}', self.step_blocks[-1])
        self.assertIn('          GH_HOST: github.com', self.step_blocks[-1])
        self.assertIn("          GH_PROMPT_DISABLED: '1'", self.step_blocks[-1])
        for forbidden in ('secrets.', 'id-token:', 'write-all', 'GH_ENTERPRISE_TOKEN',
                          'GITHUB_TOKEN:', 'gh auth', 'create-github-app-token',
                          'personal-access-token', 'ssh-key:', 'environment:'):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, self.configuration)

    def test_untrusted_inputs_are_env_only_and_rejected_before_checkout(self):
        guard = self.step_blocks[0]
        self.assertTrue(guard.startswith('name: Reject every input except the fixed verified candidate'))
        for name, (variable, value) in FIXED_INPUTS.items():
            with self.subTest(input=name):
                self.assertIn(f'      {variable}: ${{{{ inputs.{name} }}}}', self.configuration)
                self.assertIn(f"            {variable} = '{value}'", guard)
        self.assertIn('foreach ($key in $expected.Keys)', guard)
        self.assertIn('[Environment]::GetEnvironmentVariable($key) -cne $expected[$key]', guard)
        self.assertIn('throw "This recovery workflow accepts only the fixed verified candidate', guard)
        # Context interpolation inside a run script would bypass safe argument
        # passing, even when the normal default inputs happen to be harmless.
        for step in self.step_blocks:
            if '        run:' in step:
                run = step.split('        run:', 1)[1]
                self.assertNotIn('${{', run)
                self.assertNotIn('Invoke-Expression', run)
        self.assertIn('uses: actions/checkout@v4', self.step_blocks[1])
        self.assertIn('          ref: ${{ github.sha }}', self.step_blocks[1])
        self.assertIn('          persist-credentials: false', self.step_blocks[1])
        self.assertNotIn('inputs.', self.step_blocks[1])

    def test_only_pinned_official_binary_verifier_dependencies_are_installed(self):
        self.assertIn('uses: actions/setup-python@v5', self.step_blocks[2])
        self.assertIn("          python-version: '3.12'", self.step_blocks[2])
        self.assertIn('          architecture: x64', self.step_blocks[2])
        install = self.step_blocks[3]
        self.assertIn(
            'python -m pip --isolated install --index-url https://pypi.org/simple '
            '--only-binary=:all: -r requirements-build.txt', install,
        )
        self.assertIn('if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }', install)
        self.assertEqual(self.configuration.count('pip --isolated install'), 1)
        self.assertNotIn('--extra-index-url', self.configuration)
        self.assertNotIn('--trusted-host', self.configuration)

    def test_exact_promoter_cli_is_the_only_candidate_operation(self):
        self.assertEqual(len(self.step_blocks), 5)
        promoter = self.step_blocks[-1]
        expected = '\n'.join((
            ' >-',
            '          python scripts/promote_verified_candidate.py',
            '          --run-id "$env:CANDIDATE_RUN_ID"',
            '          --source-sha "$env:CANDIDATE_SOURCE_SHA"',
            '          --run-attempt "$env:CANDIDATE_RUN_ATTEMPT"',
            '          --artifact-id "$env:CANDIDATE_ARTIFACT_ID"',
            '          --artifact-sha256 "$env:CANDIDATE_ARTIFACT_SHA256"',
            '          --work-dir build/candidate-promotion',
        ))
        self.assertEqual(promoter.split('        run:', 1)[1].rstrip(), expected)
        for forbidden in ('--publish', 'gh release', 'gh api', 'git push',
                          'build_windows.py', 'build_minimal_opencv.py',
                          'build_wgc_capture.py', 'build_wgc_session_capture.py',
                          'install-community', 'msbuild', 'cmake', 'cl.exe',
                          'windows_exe_smoke.py', 'windows_native_smoke.py',
                          'windows_ota_smoke.py', 'VGA-Aram-Helper.exe',
                          'actions/upload-artifact', 'actions/download-artifact',
                          'softprops/action-gh-release', 'continue-on-error:',
                          'always()', 'workflow_run:', 'workflow_call:'):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, self.configuration)


if __name__ == '__main__':
    unittest.main()

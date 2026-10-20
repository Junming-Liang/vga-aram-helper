"""Offline draft boundary/CLI tests. All GitHub transport is mocked; no upload occurs."""
from contextlib import redirect_stderr, redirect_stdout
import copy
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts import verify_release as gate
from scripts.probe_opencv_parity import PERFORMANCE_CASES


class StageDraftTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.sha = 'a' * 40
        self.tag = 'v' + gate.PREVIEW_VERSION
        self.notes = self.root / 'release-notes.txt'
        self.notes.write_text('Owned offline fixture notes.', encoding='utf8')
        self.exe = self.root / f'vga-aram-helper-{gate.PREVIEW_VERSION}-windows-x64.exe'
        self.exe.write_bytes(b'MZ offline staging fixture')
        evidence = self.root / 'owned-evidence.zip'
        evidence.write_bytes(b'Owned offline evidence placeholder')
        assets = [dict(name=path.name, path=str(path), size=path.stat().st_size,
                       sha256=gate.digest(path)) for path in (self.exe, evidence)]
        timing = dict(baseline_samples_seconds=[.2] * 7, candidate_samples_seconds=[.2] * 7,
                      baseline_median_seconds=.2, candidate_median_seconds=.2,
                      ratio=1., delta_seconds=0., regression=False)
        adoption = gate.verify_adopted_performance(dict(status='passed', performance={
            name: copy.deepcopy(timing) for name in PERFORMANCE_CASES | {'capture_synthetic_window'}}))
        self.verified = dict(repository=gate.REPOSITORY, tag=self.tag, source_sha=self.sha,
            version=gate.PREVIEW_VERSION, run_id=12345, run_attempt=1, experimental=False,
            package_profile=gate.ADOPTED_PROFILE, opencv_build_profile=gate.ADOPTED_PROFILE,
            opencv_distribution_version=gate.CUSTOM_VERSION, opencv_adoption=adoption,
            opencv_postbuild=dict(status='passed', fixed_order=['A1', 'B1'], restoration='verified',
                                 source_commit=self.sha, export_sha256='e' * 64),
            evidence_sha256={'windows-opencv-postbuild-export.json': 'e' * 64},
            assets=assets, exe_size=assets[0]['size'], exe_sha256=assets[0]['sha256'])
        self.provenance = dict(repository=gate.REPOSITORY, source_sha=self.sha,
            run_id=12345, run_attempt=1, workflow=gate.PREVIEW_WORKFLOW,
            event='workflow_dispatch', branch='main')
        self.reference = dict(ref='refs/tags/' + self.tag, object=dict(sha=self.sha, type='commit'))
        self.draft = dict(id=456, tag_name=self.tag, target_commitish=self.sha, draft=True, prerelease=True,
            html_url=f'https://github.com/{gate.REPOSITORY}/releases/tag/{self.tag}',
            assets=[dict(name=asset['name'], size=asset['size'], state='uploaded',
                         digest='sha256:' + asset['sha256']) for asset in assets])

    def replies(self, draft=None, final_tag=None):
        return [None, [], self.reference, self.reference,
                [self.draft if draft is None else draft], self.reference if final_tag is None else final_tag]

    def stage(self):
        return gate.publish(self.verified, self.notes, self.provenance, draft_only=True)

    def assert_create_only(self, run):
        run.assert_called_once()
        command = run.call_args.args[0]
        self.assertEqual(command[:3], ['release', 'create', self.tag])
        for flag in ('--draft', '--prerelease', '--latest=false', '--verify-tag'):
            self.assertIn(flag, command)
        self.assertEqual(command[command.index('--target') + 1], self.sha)
        for forbidden in ('PATCH', 'draft=false', '--clobber', 'delete', 'edit'):
            self.assertNotIn(forbidden, command)

    def test_stage_returns_exact_verified_draft_without_publish_patch(self):
        with patch.object(gate, 'gh_api', side_effect=self.replies()) as api, \
                patch.object(gate, 'gh_run') as run:
            self.assertIs(self.stage(), self.draft)
        self.assert_create_only(run)
        self.assertEqual(api.call_count, 6)
        self.assertEqual(api.call_args_list[2].kwargs,
            {'fields': {'ref': 'refs/tags/' + self.tag, 'sha': self.sha}})
        self.assertEqual(api.call_args.args[0], f'repos/{gate.REPOSITORY}/git/ref/tags/{self.tag}')

    def test_default_publish_still_patches_exact_id_and_checks_final_state(self):
        final = dict(self.draft, draft=False)
        replies = self.replies() + [final, self.reference]
        with patch.object(gate, 'gh_api', side_effect=replies) as api, patch.object(gate, 'gh_run') as run:
            result = gate.publish(self.verified, self.notes, self.provenance)
        self.assertEqual(result, final['html_url'])
        self.assertEqual(run.call_count, 2)
        command = run.call_args.args[0]
        self.assertIn('PATCH', command)
        self.assertIn('draft=false', command)
        self.assertIn(f'repos/{gate.REPOSITORY}/releases/456', command)
        self.assertEqual(api.call_args_list[-2].args[0], f'repos/{gate.REPOSITORY}/releases/456')

    def test_stage_rechecks_profile_postbuild_timing_and_source_before_transport(self):
        mutations = (
            lambda v: v.update(experimental=True),
            lambda v: v.update(package_profile=gate.OFFICIAL_PROFILE),
            lambda v: v['opencv_postbuild'].update(restoration='failed'),
            lambda v: v['opencv_postbuild'].update(source_commit='b' * 40),
            lambda v: v['opencv_postbuild'].update(export_sha256='f' * 64),
            lambda v: v['opencv_adoption']['performance']['capture_synthetic_window'].update(candidate_median_seconds=.9),
            lambda v: v.update(source_sha='b' * 40),
            lambda v: v.update(version='99.0.0', tag='v99.0.0'),
            lambda v: v.update(exe_sha256='f' * 64),
            lambda v: v.update(run_attempt=2),
        )
        original = copy.deepcopy(self.verified)
        for index, mutate in enumerate(mutations):
            self.verified = copy.deepcopy(original)
            mutate(self.verified)
            with self.subTest(index=index), patch.object(gate, 'gh_api') as api, \
                    patch.object(gate, 'gh_run') as run, self.assertRaises(gate.VerificationError):
                self.stage()
            api.assert_not_called(); run.assert_not_called()

    def test_stage_rejects_missing_provenance_and_nonboolean_mode_before_transport(self):
        with patch.object(gate, 'gh_api') as api, patch.object(gate, 'gh_run') as run:
            with self.assertRaises(gate.VerificationError):
                gate.publish(self.verified, self.notes, {}, draft_only=True)
            for mode in ('true', 1, None):
                with self.subTest(mode=mode), self.assertRaises(gate.VerificationError):
                    gate.publish(self.verified, self.notes, self.provenance, draft_only=mode)
        api.assert_not_called(); run.assert_not_called()

    def test_stage_never_reuses_existing_tag_or_release(self):
        for replies in ([self.reference], [None, [self.draft]], [None, [dict(self.draft, draft=False)]]):
            with self.subTest(replies=replies), patch.object(gate, 'gh_api', side_effect=replies) as api, \
                    patch.object(gate, 'gh_run') as run, self.assertRaises(gate.VerificationError):
                self.stage()
            run.assert_not_called()
            self.assertTrue(all(not call.kwargs.get('fields') for call in api.call_args_list))

    def test_stage_rehashes_local_assets_before_any_write(self):
        self.exe.write_bytes(b'MZ changed after verification')
        with patch.object(gate, 'gh_api', side_effect=[None, []]) as api, \
                patch.object(gate, 'gh_run') as run, self.assertRaises(gate.VerificationError):
            self.stage()
        self.assertEqual(api.call_count, 2); run.assert_not_called()

    def test_stage_requires_exact_draft_target_id_and_uploaded_asset_hashes(self):
        mutations = (
            lambda d: d.update(draft=False), lambda d: d.update(prerelease=False),
            lambda d: d.update(tag_name='v99.0.0'), lambda d: d.update(target_commitish='b' * 40),
            lambda d: d.update(id=True), lambda d: d.update(id=0),
            lambda d: d['assets'].pop(), lambda d: d['assets'].append(copy.deepcopy(d['assets'][0])),
            lambda d: d['assets'][0].update(state='new'), lambda d: d['assets'][0].update(size=1),
            lambda d: d['assets'][0].update(digest='sha256:' + 'f' * 64),
        )
        for index, mutate in enumerate(mutations):
            draft = copy.deepcopy(self.draft); mutate(draft)
            with self.subTest(index=index), patch.object(gate, 'gh_api', side_effect=self.replies(draft)) as api, \
                    patch.object(gate, 'gh_run') as run, self.assertRaises(gate.VerificationError):
                self.stage()
            self.assert_create_only(run)

    def test_stage_rechecks_tag_after_upload_without_repair_on_drift(self):
        wrong = copy.deepcopy(self.reference); wrong['object']['sha'] = 'b' * 40
        with patch.object(gate, 'gh_api', side_effect=self.replies(final_tag=wrong)) as api, \
                patch.object(gate, 'gh_run') as run, self.assertRaises(gate.VerificationError):
            self.stage()
        self.assert_create_only(run); self.assertEqual(api.call_count, 6)

    def test_partial_creation_failures_never_retry_delete_or_publish(self):
        failures = (
            ([None, [], gate.VerificationError('Tag reservation failed')], None, 0),
            ([None, [], self.reference, self.reference], gate.VerificationError('Upload interrupted'), 1),
            ([None, [], self.reference, self.reference, []], None, 1),
            (self.replies()[:-1] + [gate.VerificationError('Final tag query failed')], None, 1),
        )
        for replies, error, writes in failures:
            with self.subTest(error=error, writes=writes), patch.object(gate, 'gh_api', side_effect=replies) as api, \
                    patch.object(gate, 'gh_run', side_effect=error) as run, self.assertRaises(gate.VerificationError):
                self.stage()
            self.assertEqual(run.call_count, writes)
            if writes: self.assert_create_only(run)
            self.assertEqual(api.call_count, len(replies))

    def cli(self, *flags):
        return ['verify_release.py', '--release-dir', str(self.root / 'release'),
                '--evidence-dir', str(self.root / 'evidence'), '--output-dir', str(self.root),
                '--repository', gate.REPOSITORY, '--source-sha', self.sha,
                '--run-id', '12345', '--run-attempt', '1', *flags]

    def cli_result(self):
        result = copy.deepcopy(self.verified)
        result.update({key: {} for key in ('artifact_budget', 'qt_binaries', 'native_scale_summary',
            'selection_summary', 'package_size', 'native_ota_summary', 'genuine_screenshot_summary',
            'champion_select_screenshot_summary')})
        return result

    def test_cli_stage_and_publish_are_mutually_exclusive_before_verification(self):
        with patch.object(sys, 'argv', self.cli('--stage-draft', '--publish')), \
                patch.object(gate, 'verify') as verify, patch.object(gate, 'publish') as publish, \
                redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
            gate.main()
        self.assertEqual(error.exception.code, 2)
        verify.assert_not_called(); publish.assert_not_called()

    def test_cli_stage_runs_same_full_verify_runner_and_provenance_gates(self):
        result = self.cli_result(); events = []
        with patch.object(sys, 'argv', self.cli('--stage-draft')), \
                patch.object(gate, 'verify', side_effect=lambda *a: events.append('verify') or result) as verify, \
                patch.object(gate, 'check_runner_context', side_effect=lambda *a: events.append('runner')) as runner, \
                patch.object(gate, 'verify_run_provenance', side_effect=lambda *a: events.append('provenance') or self.provenance) as provenance, \
                patch.object(gate, 'publish', side_effect=lambda *a, **k: events.append('stage') or self.draft) as publish, \
                redirect_stdout(io.StringIO()) as output:
            gate.main()
        self.assertEqual(events, ['verify', 'runner', 'provenance', 'stage'])
        verify.assert_called_once_with(self.root / 'release', self.root / 'evidence', gate.REPOSITORY,
            self.sha, self.root, 12345, 1)
        runner.assert_called_once_with(gate.REPOSITORY, self.sha, 12345, 1)
        provenance.assert_called_once_with(gate.REPOSITORY, self.sha, 12345, 1)
        publish.assert_called_once_with(result, self.notes, self.provenance, draft_only=True)
        self.assertIn('"status": "verified-draft"', output.getvalue())
        self.assertIn('"release_id": 456', output.getvalue())

    def test_cli_stage_stops_on_verification_runner_or_provenance_failure(self):
        for failure in ('verify', 'check_runner_context', 'verify_run_provenance'):
            with self.subTest(failure=failure), patch.object(sys, 'argv', self.cli('--stage-draft')), \
                    patch.object(gate, 'verify', return_value=self.cli_result()) as verify, \
                    patch.object(gate, 'check_runner_context') as runner, \
                    patch.object(gate, 'verify_run_provenance', return_value=self.provenance) as provenance, \
                    patch.object(gate, 'publish') as publish, redirect_stdout(io.StringIO()):
                {'verify': verify, 'check_runner_context': runner, 'verify_run_provenance': provenance}[failure].side_effect = gate.VerificationError('Blocked')
                with self.assertRaises(gate.VerificationError): gate.main()
                publish.assert_not_called()
                if failure == 'verify': runner.assert_not_called(); provenance.assert_not_called()
                if failure == 'check_runner_context': provenance.assert_not_called()

    def test_cli_existing_publish_and_verify_only_paths_remain_unchanged(self):
        result = self.cli_result()
        for flag in (None, '--publish'):
            with self.subTest(flag=flag), patch.object(sys, 'argv', self.cli(*([flag] if flag else []))), \
                    patch.object(gate, 'verify', return_value=result), \
                    patch.object(gate, 'check_runner_context') as runner, \
                    patch.object(gate, 'verify_run_provenance', return_value=self.provenance), \
                    patch.object(gate, 'publish', return_value='published-url') as publish, \
                    redirect_stdout(io.StringIO()):
                gate.main()
                if flag: publish.assert_called_once_with(result, self.notes, self.provenance)
                else: publish.assert_not_called(); runner.assert_not_called()


if __name__ == '__main__':
    unittest.main()

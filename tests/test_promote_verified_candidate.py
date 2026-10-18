"""Offline exact-artifact/private-draft tests, never real Windows acceptance.

The integration fixture uses the existing ReleaseFixture's explicitly synthetic
Windows reports and its documented native/archive stand-ins. The real release
verifier, receipt comparisons, staging, ZIP extraction and draft-asset checks run.
Every subprocess is intercepted, so no build, network call or release can occur.
Separate tests exercise the unmodified OpenCV provenance validator and the
original-checkout/credential-free subprocess boundary; the aggregate synthetic
fixture substitutes that boundary to retain its documented native stand-ins.
"""
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import warnings
import zipfile

from scripts import promote_verified_candidate as promotion
from scripts import stage_verified_artifact as staging
from scripts import probe_opencv_postbuild as postbuild
from scripts import build_minimal_opencv as opencv_builder
from scripts import minimal_opencv_package as opencv_package
from tests.test_minimal_opencv import valid_provenance_fixture
from tests import test_release_gate as fixtures


REQUIRED_STEPS = (
    'Python unit tests',
    'Re-run Python tests with the adopted native library',
    'Verify fresh native preview, source licenses and exact tested bytes',
    'Stage the exact verified candidate without publishing',
    'Preserve this exact verified candidate for one day',
)
PUBLISH_STEP = 'Create verified draft and publish its ID only as a non-latest prerelease'
PROMOTION_RUN_ID = 987654322
PROMOTION_SHA = 'c' * 40


def promotion_environment():
    return {'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': promotion.REPOSITORY,
            'GITHUB_REF': 'refs/heads/main', 'GITHUB_EVENT_NAME': 'workflow_dispatch',
            'GITHUB_WORKFLOW_REF': f'{promotion.REPOSITORY}/{promotion.WORKFLOW}@refs/heads/main',
            'GITHUB_RUN_ID': str(PROMOTION_RUN_ID), 'GITHUB_RUN_ATTEMPT': '1',
            'GITHUB_SHA': PROMOTION_SHA}


def good_promotion_record():
    run = good_remote_records()['run']
    run.update(id=PROMOTION_RUN_ID, run_attempt=1, head_sha=PROMOTION_SHA,
               status='in_progress', conclusion=None, path=promotion.WORKFLOW)
    return run


def good_remote_records():
    repository = {'id': 12345, 'full_name': promotion.REPOSITORY,
                  'private': False, 'fork': False}
    return {
        'run': {'id': promotion.RUN_ID, 'run_attempt': promotion.RUN_ATTEMPT,
                'status': 'completed', 'conclusion': 'success',
                'head_sha': promotion.SOURCE_SHA, 'head_branch': 'main',
                'event': 'workflow_dispatch', 'path': promotion.gate.PREVIEW_WORKFLOW,
                'repository': repository, 'head_repository': copy.deepcopy(repository)},
        'jobs': {'total_count': 1, 'jobs': [
            {'name': 'native-preview', 'status': 'completed', 'conclusion': 'success',
             'head_sha': promotion.SOURCE_SHA,
             'steps': [{'name': name, 'conclusion': 'success'} for name in REQUIRED_STEPS]
                      + [{'name': PUBLISH_STEP, 'conclusion': 'skipped'}]}]},
        'artifact': {'id': promotion.ARTIFACT_ID,
                     'name': 'verified-candidate-' + promotion.SOURCE_SHA,
                     'expired': False, 'size_in_bytes': promotion.ARTIFACT_SIZE,
                     'digest': 'sha256:' + promotion.ARTIFACT_SHA256,
                     'workflow_run': {'id': promotion.RUN_ID,
                                      'head_sha': promotion.SOURCE_SHA,
                                      'head_branch': 'main',
                                      'repository_id': repository['id'],
                                      'head_repository_id': repository['id']}}
    }


def record_api(records):
    endpoints = {
        f'repos/{promotion.REPOSITORY}/actions/runs/{promotion.RUN_ID}': 'run',
        f'repos/{promotion.REPOSITORY}/actions/runs/{promotion.RUN_ID}/attempts/{promotion.RUN_ATTEMPT}/jobs?per_page=100': 'jobs',
        f'repos/{promotion.REPOSITORY}/actions/artifacts/{promotion.ARTIFACT_ID}': 'artifact',
    }

    def read(endpoint, **kwargs):
        if kwargs or endpoint not in endpoints:
            raise AssertionError('Unexpected remote request: ' + endpoint)
        return copy.deepcopy(records[endpoints[endpoint]])
    return read


def expected_provenance():
    return {'repository': promotion.REPOSITORY, 'source_sha': promotion.SOURCE_SHA,
            'run_id': promotion.RUN_ID, 'run_attempt': promotion.RUN_ATTEMPT,
            'workflow': promotion.gate.PREVIEW_WORKFLOW,
            'event': 'workflow_dispatch', 'branch': 'main'}


class OfflineTestCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        guard = patch.object(subprocess, 'run', side_effect=AssertionError(
            'Tests must not run builds, GitHub, or any external command'))
        self.command_guard = guard.start()
        self.addCleanup(guard.stop)

    def start_patch(self, target, attribute, value):
        wrapper = patch.object(target, attribute, value)
        wrapper.start()
        self.addCleanup(wrapper.stop)


class PromotionIdentityTests(OfflineTestCase):
    def test_only_the_pinned_artifact_and_source_are_accepted(self):
        args = [promotion.RUN_ID, promotion.SOURCE_SHA, promotion.RUN_ATTEMPT,
                promotion.ARTIFACT_ID, promotion.ARTIFACT_SHA256]
        promotion.check_inputs(*args)
        for index, value in enumerate([promotion.RUN_ID + 1, 'b' * 40,
                                        promotion.RUN_ATTEMPT + 1,
                                        promotion.ARTIFACT_ID + 1, '0' * 64]):
            changed = args.copy()
            changed[index] = value
            with self.subTest(index=index), self.assertRaises(RuntimeError):
                promotion.check_inputs(*changed)
        for index in (0, 2, 3):
            changed = args.copy()
            changed[index] = float(changed[index])
            with self.subTest(noninteger=index), self.assertRaises(RuntimeError):
                promotion.check_inputs(*changed)
        args[2] = True
        with self.assertRaises(RuntimeError):
            promotion.check_inputs(*args)

    def test_exact_successful_original_manual_run_passes_get_only(self):
        records = good_remote_records()
        with patch.object(promotion.gate, 'gh_api', side_effect=record_api(records)) as api:
            self.assertEqual(promotion.remote_proof(), expected_provenance())
        self.assertEqual(api.call_count, 3)
        self.command_guard.assert_not_called()

    def test_wrong_run_source_attempt_status_event_branch_and_workflow_fail(self):
        mutations = [('id', promotion.RUN_ID + 1), ('run_attempt', 2),
                     ('head_sha', 'b' * 40), ('head_branch', 'other'),
                     ('status', 'in_progress'), ('conclusion', 'failure'),
                     ('conclusion', None), ('event', 'pull_request'),
                     ('path', '.github/workflows/other.yml')]
        for field, value in mutations:
            records = good_remote_records()
            records['run'][field] = value
            with self.subTest(field=field, value=value), \
                 patch.object(promotion.gate, 'gh_api', side_effect=record_api(records)), \
                 self.assertRaises(RuntimeError):
                promotion.remote_proof()

    def test_wrong_private_or_fork_repository_identity_fails(self):
        mutations = [('repository', 'full_name', 'other/repo'),
                     ('repository', 'private', True), ('repository', 'fork', True),
                     ('repository', 'id', 0), ('repository', 'id', True),
                     ('head_repository', 'full_name', 'fork/repo'),
                     ('head_repository', 'fork', True),
                     ('head_repository', 'id', 54321)]
        for container, field, value in mutations:
            records = good_remote_records()
            records['run'][container][field] = value
            with self.subTest(container=container, field=field), \
                 patch.object(promotion.gate, 'gh_api', side_effect=record_api(records)), \
                 self.assertRaises(RuntimeError):
                promotion.remote_proof()

    def test_artifact_identity_digest_expiry_size_and_owner_are_bound(self):
        mutations = [('id', promotion.ARTIFACT_ID + 1), ('name', 'other-artifact'),
                     ('expired', True), ('expired', None),
                     ('size_in_bytes', promotion.ARTIFACT_SIZE - 1),
                     ('digest', 'sha256:' + '0' * 64), ('digest', None)]
        for field, value in mutations:
            records = good_remote_records()
            records['artifact'][field] = value
            with self.subTest(field=field), \
                 patch.object(promotion.gate, 'gh_api', side_effect=record_api(records)), \
                 self.assertRaises(RuntimeError):
                promotion.remote_proof()
        for field, value in [('id', promotion.RUN_ID + 1), ('head_sha', 'b' * 40),
                             ('head_branch', 'other'), ('repository_id', 54321),
                             ('head_repository_id', 54321)]:
            records = good_remote_records()
            records['artifact']['workflow_run'][field] = value
            with self.subTest(owner_field=field), \
                 patch.object(promotion.gate, 'gh_api', side_effect=record_api(records)), \
                 self.assertRaises(RuntimeError):
                promotion.remote_proof()

    def test_json_numeric_identity_and_count_types_are_strict(self):
        mutations = [('run', 'id'), ('run', 'run_attempt'),
                     ('artifact', 'id'), ('artifact', 'size_in_bytes')]
        for container, field in mutations:
            records = good_remote_records()
            records[container][field] = float(records[container][field])
            with self.subTest(container=container, field=field), \
                 patch.object(promotion.gate, 'gh_api', side_effect=record_api(records)), \
                 self.assertRaises(RuntimeError):
                promotion.remote_proof()
        for container, field in [('head_repository', 'id')]:
            records = good_remote_records()
            records['run'][container][field] = float(records['run'][container][field])
            with self.subTest(repository=container), \
                 patch.object(promotion.gate, 'gh_api', side_effect=record_api(records)), \
                 self.assertRaises(RuntimeError):
                promotion.remote_proof()
        for field in ('id', 'repository_id', 'head_repository_id'):
            records = good_remote_records()
            records['artifact']['workflow_run'][field] = float(
                records['artifact']['workflow_run'][field])
            with self.subTest(owner=field), \
                 patch.object(promotion.gate, 'gh_api', side_effect=record_api(records)), \
                 self.assertRaises(RuntimeError):
                promotion.remote_proof()
        for container, field in [('run', 'run_attempt'), ('jobs', 'total_count')]:
            records = good_remote_records()
            records[container][field] = True
            with self.subTest(boolean=field), \
                 patch.object(promotion.gate, 'gh_api', side_effect=record_api(records)), \
                 self.assertRaises(RuntimeError):
                promotion.remote_proof()

    def test_original_job_inventory_and_required_successful_steps(self):
        records = good_remote_records()
        variants = []
        for field, value in [('name', 'other'), ('head_sha', 'b' * 40),
                             ('status', 'in_progress'), ('conclusion', 'failure')]:
            changed = copy.deepcopy(records)
            changed['jobs']['jobs'][0][field] = value
            variants.append(changed)
        for count, jobs in [(0, []), (2, records['jobs']['jobs'] * 2),
                            (2, records['jobs']['jobs'])]:
            changed = copy.deepcopy(records)
            changed['jobs'] = {'total_count': count, 'jobs': jobs}
            variants.append(changed)
        for name in REQUIRED_STEPS:
            for conclusion in (None, 'failure', 'skipped'):
                changed = copy.deepcopy(records)
                step = next(row for row in changed['jobs']['jobs'][0]['steps']
                            if row['name'] == name)
                step['conclusion'] = conclusion
                variants.append(changed)
            changed = copy.deepcopy(records)
            changed['jobs']['jobs'][0]['steps'] = [
                row for row in changed['jobs']['jobs'][0]['steps'] if row['name'] != name]
            variants.append(changed)
        for conclusion in (None, 'success', 'failure'):
            changed = copy.deepcopy(records)
            changed['jobs']['jobs'][0]['steps'][-1]['conclusion'] = conclusion
            variants.append(changed)
        for index, changed in enumerate(variants):
            with self.subTest(case=index), \
                 patch.object(promotion.gate, 'gh_api', side_effect=record_api(changed)), \
                 self.assertRaises(RuntimeError):
                promotion.remote_proof()

    def test_remote_errors_fail_closed_without_fallback(self):
        with patch.object(promotion.gate, 'gh_api', side_effect=RuntimeError('API unavailable')):
            with self.assertRaisesRegex(RuntimeError, 'API unavailable'):
                promotion.remote_proof()
        self.command_guard.assert_not_called()


class CurrentPromotionProofTests(OfflineTestCase):
    def call_proof(self, record=None, *, environment=None, checkout_sha=PROMOTION_SHA,
                   checkout_returncode=0):
        if record is None:
            record = good_promotion_record()
        environment = promotion_environment() if environment is None else environment

        def git(arguments, **kwargs):
            self.assertEqual(arguments, ['git', 'rev-parse', 'HEAD'])
            self.assertEqual(kwargs['timeout'], 30)
            return subprocess.CompletedProcess(arguments, checkout_returncode,
                                               stdout=checkout_sha + '\n', stderr='')
        with patch.dict(os.environ, environment, clear=True), \
             patch.object(promotion.gate, 'gh_api', return_value=record) as api, \
             patch.object(subprocess, 'run', side_effect=git):
            result = promotion.current_promotion_proof()
        api.assert_called_once_with(f'repos/{promotion.REPOSITORY}/actions/runs/{PROMOTION_RUN_ID}')
        return result

    def test_authenticated_active_promotion_and_checked_out_commit_are_bound(self):
        self.assertEqual(self.call_proof(), {'run_id': PROMOTION_RUN_ID,
                                           'run_attempt': 1, 'source_sha': PROMOTION_SHA})

    def test_invalid_environment_identity_fails_before_any_remote_read(self):
        for key, values in [('GITHUB_RUN_ID', ['', '0', '-1', '01', '1.0', 'true']),
                            ('GITHUB_RUN_ATTEMPT', ['', '0', '-1', '01', '1.0']),
                            ('GITHUB_SHA', ['', 'c' * 39, 'C' * 40, 'g' * 40])]:
            for value in values:
                environment = dict(promotion_environment(), **{key: value})
                with self.subTest(key=key, value=value), \
                     patch.dict(os.environ, environment, clear=True), \
                     patch.object(promotion.gate, 'gh_api') as api, \
                     self.assertRaisesRegex(RuntimeError, 'Invalid current promotion identity'):
                    promotion.current_promotion_proof()
                api.assert_not_called()
        self.command_guard.assert_not_called()

    def test_wrong_current_run_attempt_source_workflow_branch_or_status_fails(self):
        changes = [('id', PROMOTION_RUN_ID + 1), ('id', float(PROMOTION_RUN_ID)),
                   ('run_attempt', 2), ('run_attempt', True), ('head_sha', 'b' * 40),
                   ('status', 'completed'), ('conclusion', 'success'),
                   ('head_branch', 'other'), ('event', 'push'),
                   ('path', promotion.gate.PREVIEW_WORKFLOW)]
        for field, value in changes:
            record = dict(good_promotion_record(), **{field: value})
            with self.subTest(field=field, value=value), self.assertRaises(RuntimeError):
                self.call_proof(record)
        record = good_promotion_record()
        del record['conclusion']
        with self.assertRaises(RuntimeError):
            self.call_proof(record)

    def test_current_promotion_fork_or_repository_mismatch_fails(self):
        changes = [('repository', 'full_name', 'other/repo'), ('repository', 'private', True),
                   ('repository', 'fork', True), ('repository', 'id', True),
                   ('head_repository', 'full_name', 'fork/repo'),
                   ('head_repository', 'fork', True), ('head_repository', 'id', 999),
                   ('head_repository', 'id', 12345.0)]
        for container, field, value in changes:
            record = good_promotion_record()
            record[container][field] = value
            with self.subTest(container=container, field=field), self.assertRaises(RuntimeError):
                self.call_proof(record)

    def test_checkout_mismatch_or_git_error_fails_before_artifact_work(self):
        for sha, code in [('b' * 40, 0), (PROMOTION_SHA, 1)]:
            with self.subTest(sha=sha, returncode=code), \
                 self.assertRaisesRegex(RuntimeError, 'checkout differs'):
                self.call_proof(checkout_sha=sha, checkout_returncode=code)


class OriginalOpenCVProvenanceRegressionTests(OfflineTestCase):
    """Exercise the real validator that the larger release fixture substitutes."""
    def setUp(self):
        super().setUp()
        self.original_sha = 'a' * 40
        self.proof = valid_provenance_fixture(self.original_sha,
                                             profile=promotion.gate.ADOPTED_PROFILE)

    def fake_git_head(self, sha):
        def run(arguments, **kwargs):
            self.assertEqual(arguments, ['git', 'rev-parse', 'HEAD'])
            self.assertEqual(kwargs['cwd'], opencv_builder.ROOT)
            self.assertEqual(kwargs['timeout'], 30)
            return subprocess.CompletedProcess(arguments, 0, stdout=sha + '\n')
        return run

    def test_parent_promoter_sha_reproduces_real_original_provenance_failure(self):
        # The archived proof belongs to original HEAD, while the promotion
        # workflow legitimately executes a later commit. Its SHA must not leak.
        with patch.dict(os.environ, {'GITHUB_SHA': PROMOTION_SHA}, clear=True), \
             patch.object(subprocess, 'run', side_effect=self.fake_git_head(self.original_sha)) as git, \
             self.assertRaisesRegex(RuntimeError, 'Custom OpenCV source commit differs'):
            opencv_package.checked_proof(self.proof, profile=promotion.gate.ADOPTED_PROFILE)
        git.assert_not_called()

    def test_unmodified_validator_derives_original_commit_from_git_without_sha_override(self):
        with patch.dict(os.environ, {}, clear=True), \
             patch.object(subprocess, 'run', side_effect=self.fake_git_head(self.original_sha)) as git:
            self.assertEqual(opencv_package.checked_proof(
                self.proof, profile=promotion.gate.ADOPTED_PROFILE), self.proof)
        git.assert_called_once()

    def test_wrong_checkout_commit_still_fails_without_github_sha(self):
        with patch.dict(os.environ, {}, clear=True), \
             patch.object(subprocess, 'run', side_effect=self.fake_git_head(PROMOTION_SHA)), \
             self.assertRaisesRegex(RuntimeError, 'Custom OpenCV source commit differs'):
            opencv_package.checked_proof(self.proof, profile=promotion.gate.ADOPTED_PROFILE)

    def test_no_sha_override_does_not_weaken_other_original_provenance_checks(self):
        self.proof['source']['sha256'] = '0' * 64
        with patch.dict(os.environ, {}, clear=True), \
             patch.object(subprocess, 'run', side_effect=self.fake_git_head(self.original_sha)), \
             self.assertRaisesRegex(RuntimeError, 'pinned input'):
            opencv_package.checked_proof(self.proof, profile=promotion.gate.ADOPTED_PROFILE)


class OriginalCheckoutTests(OfflineTestCase):
    def setUp(self):
        super().setUp()
        self.checkout = self.root / 'original-source'
        self.checkout.mkdir()
        self.files = {'scripts/verify_release.py': b'# Synthetic original verifier fixture\n',
                      'scripts/build_minimal_opencv.py': b'# Synthetic pinned recipe fixture\n',
                      'README.md': b'Original fixture source bytes\n', '.gitattributes': b'* text=auto\n'}
        for name, data in self.files.items():
            path = self.checkout / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        (self.checkout / '.git').mkdir()
        (self.checkout / '.git' / 'config').write_text('Owned synthetic Git metadata')
        self.source_archive = self.root / 'source.zip'
        self.tree = b''.join(self.tree_row(name, data) for name, data in self.files.items())
        self.archive()
        self.git_commands = []

    @staticmethod
    def tree_row(name, data, *, mode='100644', kind='blob'):
        digest = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
        return f'{mode} {kind} {digest}\t{name}\0'.encode()

    def archive(self, files=None, comment=None):
        if files is None:
            files = list(self.files.items())
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', UserWarning)
            with zipfile.ZipFile(self.source_archive, 'w') as archive:
                archive.comment = promotion.SOURCE_SHA.encode() if comment is None else comment
                for name, data in files:
                    archive.writestr(name, data)

    def git(self, arguments, **kwargs):
        self.git_commands.append(list(arguments))
        self.assertEqual(arguments[:3], ['git', '-C', str(self.checkout.resolve())])
        self.assertEqual(kwargs['timeout'], 60)
        command = arguments[3:]
        if command == ['rev-parse', 'HEAD']:
            data = promotion.SOURCE_SHA.encode() + b'\n'
        elif command == ['rev-parse', '--show-toplevel']:
            data = str(self.checkout.resolve()).encode() + b'\n'
        elif command == ['ls-tree', '-r', '-z', '--full-tree', promotion.SOURCE_SHA]:
            data = self.tree
        else:
            raise AssertionError('Unexpected original-source command: ' + repr(arguments))
        return subprocess.CompletedProcess(arguments, 0, stdout=data, stderr=b'')

    def check(self, git=None):
        with patch.object(subprocess, 'run', side_effect=git or self.git):
            return promotion.check_original_source(self.checkout, self.source_archive)

    def test_exact_original_git_tree_checkout_and_source_archive_agree(self):
        with patch.dict(os.environ, {'GITHUB_SHA': PROMOTION_SHA}, clear=True):
            self.assertEqual(self.check(), self.checkout.resolve())
        self.assertEqual(len(self.git_commands), 3)
        self.assertNotEqual(PROMOTION_SHA, promotion.SOURCE_SHA)
        self.assertEqual((self.checkout / '.git' / 'config').read_text(), 'Owned synthetic Git metadata')

    def test_wrong_source_head_or_nonindependent_root_fails(self):
        for command, data, message in [(['rev-parse', 'HEAD'], PROMOTION_SHA.encode(), 'tested source commit'),
                                       (['rev-parse', '--show-toplevel'], str(self.root).encode(), 'independent Git root')]:
            def wrong(arguments, **kwargs):
                if arguments[3:] == command:
                    return subprocess.CompletedProcess(arguments, 0, stdout=data, stderr=b'')
                return self.git(arguments, **kwargs)
            with self.subTest(command=command), self.assertRaisesRegex(RuntimeError, message):
                self.check(wrong)

    def test_git_failure_stops_before_using_archive(self):
        with self.assertRaisesRegex(RuntimeError, 'Git identity check failed'):
            self.check(lambda args, **kwargs: subprocess.CompletedProcess(args, 1, stdout=b'', stderr=b'failed'))

    def test_extra_missing_and_modified_checkout_files_fail(self):
        extra = self.checkout / 'untracked.py'
        extra.write_bytes(b'No untracked imports')
        with self.assertRaisesRegex(RuntimeError, 'extra or missing'):
            self.check()
        extra.unlink()
        target = self.checkout / 'README.md'
        target.unlink()
        with self.assertRaisesRegex(RuntimeError, 'extra or missing'):
            self.check()
        target.write_bytes(b'Modified original source')
        with self.assertRaisesRegex(RuntimeError, 'checkout bytes differ'):
            self.check()

    def test_extra_bytecode_also_rejected_before_original_verifier_imports(self):
        cache = self.checkout / 'scripts' / '__pycache__'
        cache.mkdir()
        (cache / 'verify_release.cpython-312.pyc').write_bytes(b'untrusted cached code')
        with self.assertRaisesRegex(RuntimeError, 'extra or missing'):
            self.check()

    def test_checkout_file_and_directory_links_fail(self):
        target = self.checkout / 'README.md'
        target.unlink()
        outside = self.root / 'owned-file'
        outside.write_bytes(self.files['README.md'])
        try:
            target.symlink_to(outside)
        except (OSError, NotImplementedError):
            self.skipTest('Host does not permit owned symlink fixtures')
        with self.assertRaisesRegex(RuntimeError, 'contains a link'):
            self.check()
        target.unlink()
        target.write_bytes(self.files['README.md'])
        (self.checkout / 'linked-directory').symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(RuntimeError, 'contains a link'):
            self.check()

    def test_unsupported_tree_modes_duplicate_names_or_empty_tree_fail(self):
        original = self.tree
        bad = [b'', self.tree + self.tree.split(b'\0')[0] + b'\0',
               self.tree_row('README.md', self.files['README.md'], mode='120000'),
               self.tree_row('README.md', self.files['README.md'], mode='160000', kind='commit')]
        for index, tree in enumerate(bad):
            self.tree = tree
            with self.subTest(case=index), self.assertRaises(RuntimeError):
                self.check()
        self.tree = original

    def test_source_archive_commit_inventory_duplicate_and_traversal_fail(self):
        variants = [(list(self.files.items()), PROMOTION_SHA.encode()),
                    (list(self.files.items())[:-1], None),
                    (list(self.files.items()) + [('extra.py', b'unknown')], None),
                    (list(self.files.items()) + [('README.md', b'duplicate')], None),
                    (list(self.files.items())[:-1] + [('../escape', b'unsafe')], None)]
        for index, (files, comment) in enumerate(variants):
            self.archive(files, comment)
            with self.subTest(case=index), self.assertRaises(RuntimeError):
                self.check()

    def test_archive_and_checkout_cannot_collude_to_change_pinned_git_blob(self):
        changed = dict(self.files, **{'README.md': b'Changed in both places'})
        self.archive(list(changed.items()))
        (self.checkout / 'README.md').write_bytes(changed['README.md'])
        with self.assertRaisesRegex(RuntimeError, 'blob differs from tested Git tree'):
            self.check()

    def test_source_archive_symlink_encryption_and_expansion_budget_fail(self):
        link = zipfile.ZipInfo('README.md')
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        self.archive([(link if name == 'README.md' else name, data) for name, data in self.files.items()])
        with self.assertRaisesRegex(RuntimeError, 'Unsafe original source archive'):
            self.check()
        self.archive()
        data = bytearray(self.source_archive.read_bytes())
        central = data.index(b'PK\x01\x02')
        data[central + 8] |= 1
        self.source_archive.write_bytes(data)
        with self.assertRaisesRegex(RuntimeError, 'Unsafe original source archive'):
            self.check()
        self.archive()
        data = bytearray(self.source_archive.read_bytes())
        central = data.index(b'PK\x01\x02')
        data[central + 24:central + 28] = (256 * 1024 * 1024 + 1).to_bytes(4, 'little')
        self.source_archive.write_bytes(data)
        with self.assertRaisesRegex(RuntimeError, 'exceeds budget'):
            self.check()


class OriginalVerifierProcessTests(OfflineTestCase):
    def setUp(self):
        super().setUp()
        self.source = self.root / 'original-source'
        self.bundle = self.root / 'bundle'
        self.evidence = self.root / 'evidence'
        self.work = self.root / 'work'
        for path in (self.source, self.bundle, self.evidence, self.work):
            path.mkdir()
        self.parent_environment = {
            **promotion_environment(), 'PATH': '/owned/bin', 'PATHEXT': '.EXE;.CMD',
            'SystemRoot': 'C:\\Windows', 'TEMP': '/owned/tmp', 'HOME': '/owned/home',
            'GH_TOKEN': 'synthetic-must-not-leak', 'GITHUB_TOKEN': 'synthetic-must-not-leak',
            'ACTIONS_RUNTIME_TOKEN': 'synthetic-must-not-leak',
            'AWS_SECRET_ACCESS_KEY': 'synthetic-must-not-leak',
            'SOME_UNKNOWN_CREDENTIAL': 'synthetic-must-not-leak',
            'PYTHONPATH': '/untrusted/imports', 'PYTHONHOME': '/untrusted/python',
            'VGA_RELEASE_PACKAGE_PROFILE': 'untrusted', 'GIT_CONFIG_COUNT': '99'}

    def test_child_environment_is_a_credential_free_allowlist_without_sha_override(self):
        with patch.dict(os.environ, self.parent_environment, clear=True):
            environment = promotion.verifier_environment()
            self.assertEqual(os.environ['GITHUB_SHA'], PROMOTION_SHA)
            self.assertEqual(os.environ['GH_TOKEN'], 'synthetic-must-not-leak')
        self.assertEqual(environment, {'PATH': '/owned/bin', 'PATHEXT': '.EXE;.CMD',
                                      'SystemRoot': 'C:\\Windows', 'TEMP': '/owned/tmp',
                                      'HOME': '/owned/home', 'PYTHONUTF8': '1',
                                      'PYTHONDONTWRITEBYTECODE': '1', 'ORT_DISABLE_TELEMETRY': '1'})
        self.assertNotIn('synthetic-must-not-leak', environment.values())
        self.assertNotIn('GITHUB_SHA', environment)

    def test_child_runs_untouched_original_verifier_from_original_checkout_only(self):
        # Process stdout is not trusted as the receipt. The file is read only
        # after success; mocking its read here avoids inventing acceptance data.
        receipt = {'unit_fixture': 'subprocess receipt transport only'}
        def child(arguments, **kwargs):
            self.assertEqual(arguments[0], sys.executable)
            self.assertEqual(arguments[1], str(self.source / 'scripts' / 'verify_release.py'))
            self.assertEqual(kwargs['cwd'], self.source)
            self.assertEqual(kwargs['timeout'], 600)
            self.assertFalse(kwargs['check'])
            self.assertNotIn('GITHUB_SHA', kwargs['env'])
            self.assertNotIn('GH_TOKEN', kwargs['env'])
            self.assertNotIn('PYTHONPATH', kwargs['env'])
            self.assertNotIn('--publish', arguments)
            self.assertEqual(arguments[arguments.index('--source-sha') + 1], promotion.SOURCE_SHA)
            self.assertEqual(arguments[arguments.index('--run-id') + 1], str(promotion.RUN_ID))
            self.assertEqual(arguments[arguments.index('--run-attempt') + 1], str(promotion.RUN_ATTEMPT))
            for flag, path in [('--release-dir', self.bundle), ('--evidence-dir', self.evidence),
                               ('--output-dir', self.work / 'reverified')]:
                self.assertEqual(arguments[arguments.index(flag) + 1], str(path.resolve()))
            return subprocess.CompletedProcess(arguments, 0, stdout='synthetic stdout', stderr='synthetic stderr')
        with patch.dict(os.environ, self.parent_environment, clear=True), \
             patch.object(promotion, 'check_original_source', return_value=self.source) as source_check, \
             patch.object(subprocess, 'run', side_effect=child) as command, \
             patch.object(promotion.gate, 'read_json', return_value=receipt) as read:
            self.assertEqual(promotion.reverify_original(self.bundle, self.evidence, self.work, self.source), receipt)
            self.assertEqual(os.environ['GITHUB_SHA'], PROMOTION_SHA)
        source_check.assert_called_once_with(self.source, self.bundle / f'vga-aram-helper-{promotion.VERSION}-source.zip')
        command.assert_called_once()
        read.assert_called_once_with((self.work / 'reverified' / 'verified-release.json').resolve())
        self.assertEqual((self.work / 'original-verifier.log').read_text(), 'synthetic stdoutsynthetic stderr')

    def test_source_rejection_never_runs_original_python(self):
        with patch.object(promotion, 'check_original_source', side_effect=RuntimeError('wrong original source')), \
             patch.object(promotion.gate, 'read_json') as read, \
             self.assertRaisesRegex(RuntimeError, 'wrong original source'):
            promotion.reverify_original(self.bundle, self.evidence, self.work, self.source)
        self.command_guard.assert_not_called()
        read.assert_not_called()

    def test_child_failure_never_reads_or_reuses_a_receipt(self):
        output = self.work / 'reverified'
        output.mkdir()
        (output / 'verified-release.json').write_text('{"unit_fixture": "stale receipt"}')
        with patch.object(promotion, 'check_original_source', return_value=self.source), \
             patch.object(subprocess, 'run', return_value=subprocess.CompletedProcess([], 1, stdout='', stderr='original gate failed')), \
             patch.object(promotion.gate, 'read_json') as read, patch('sys.stderr', new_callable=io.StringIO), \
             self.assertRaisesRegex(RuntimeError, 'Unchanged original-source verifier rejected'):
            promotion.reverify_original(self.bundle, self.evidence, self.work, self.source)
        read.assert_not_called()
        self.assertEqual((output / 'verified-release.json').read_text(), '{"unit_fixture": "stale receipt"}')

    def test_missing_receipt_after_success_is_not_accepted(self):
        with patch.object(promotion, 'check_original_source', return_value=self.source), \
             patch.object(subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, stdout='', stderr='')), \
             self.assertRaisesRegex(RuntimeError, 'Missing or symlinked'):
            promotion.reverify_original(self.bundle, self.evidence, self.work, self.source)


class ArtifactDownloadTests(OfflineTestCase):
    def setUp(self):
        super().setUp()
        self.data = b'owned synthetic artifact bytes'
        self.start_patch(promotion, 'ARTIFACT_SIZE', len(self.data))
        self.start_patch(promotion, 'ARTIFACT_SHA256', hashlib.sha256(self.data).hexdigest())
        self.path = self.root / 'archive.zip'

    def fake_download(self, data, returncode=0):
        def run(arguments, **kwargs):
            self.assertEqual(arguments, ['gh', 'api', '--hostname', 'github.com',
                f'repos/{promotion.REPOSITORY}/actions/artifacts/{promotion.ARTIFACT_ID}/zip'])
            self.assertEqual(kwargs['timeout'], 600)
            self.assertFalse(kwargs['check'])
            kwargs['stdout'].write(data)
            return subprocess.CompletedProcess(arguments, returncode, stderr=b'')
        return run

    def test_exact_archive_download_is_hash_and_size_checked(self):
        with patch.object(subprocess, 'run', side_effect=self.fake_download(self.data)):
            promotion.download_artifact(self.path)
        self.assertEqual(self.path.read_bytes(), self.data)

    def test_wrong_hash_same_size_wrong_size_and_failed_download_fail(self):
        for index, (data, returncode) in enumerate([
                (b'X' * len(self.data), 0), (self.data + b'X', 0), (self.data, 1)]):
            with self.subTest(case=index), \
                 patch.object(subprocess, 'run', side_effect=self.fake_download(data, returncode)), \
                 self.assertRaises(RuntimeError):
                promotion.download_artifact(self.root / f'bad-{index}.zip')

    def test_preexisting_download_is_never_overwritten(self):
        self.path.write_bytes(b'preserve')
        with self.assertRaises(FileExistsError):
            promotion.download_artifact(self.path)
        self.assertEqual(self.path.read_bytes(), b'preserve')
        self.command_guard.assert_not_called()


class SafeArchiveTests(OfflineTestCase):
    def write_zip(self, entries, filename='artifact.zip'):
        path = self.root / filename
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', UserWarning)
            with zipfile.ZipFile(path, 'w') as archive:
                for name, data in entries:
                    archive.writestr(name, data)
        return path

    def test_exact_flat_inventory_extracts_original_bytes(self):
        entries = [('a.json', b'one'), ('b.txt', b'two')]
        archive = self.write_zip(entries)
        target = self.root / 'output'
        promotion.extract_flat(archive, target, {'a.json', 'b.txt'})
        self.assertEqual({p.name: p.read_bytes() for p in target.iterdir()}, dict(entries))

    def test_missing_extra_and_duplicate_inventory_fail_before_mkdir(self):
        variants = [[('a.json', b'one')], [('a.json', b'one'), ('b.txt', b'two'), ('extra', b'x')],
                    [('a.json', b'one'), ('a.json', b'two')],
                    [('a.json', b'one'), ('b.txt', b'two'), ('a.json', b'three')]]
        for index, entries in enumerate(variants):
            target = self.root / f'out-{index}'
            with self.subTest(case=index), self.assertRaises(RuntimeError):
                promotion.extract_flat(self.write_zip(entries), target, {'a.json', 'b.txt'})
            self.assertFalse(target.exists())

    def test_paths_symlinks_directories_and_windows_streams_are_rejected(self):
        for index, name in enumerate(['../escape', '/absolute', 'dir/file', r'dir\file',
                                       'a:stream', '.', '..', 'directory/']):
            target = self.root / f'out-{index}'
            with self.subTest(name=name), self.assertRaises(RuntimeError):
                promotion.extract_flat(self.write_zip([(name, b'owned')]), target, {name})
            self.assertFalse(target.exists())
        symlink = zipfile.ZipInfo('link')
        symlink.create_system = 3
        symlink.external_attr = (stat.S_IFLNK | 0o777) << 16
        with self.assertRaisesRegex(RuntimeError, 'Unsafe archive entry'):
            promotion.extract_flat(self.write_zip([(symlink, b'../escape')]),
                                   self.root / 'links', {'link'})
        self.assertFalse((self.root / 'links').exists())

    def test_expansion_budget_and_existing_target_are_fail_closed(self):
        archive = self.write_zip([('a', b'x' * 101), ('b', b'y')])
        with self.assertRaisesRegex(RuntimeError, 'exceeds budget'):
            promotion.extract_flat(archive, self.root / 'too-big', {'a', 'b'}, max_bytes=101)
        self.assertFalse((self.root / 'too-big').exists())
        target = self.root / 'existing'
        target.mkdir()
        (target / 'keep').write_bytes(b'preserve')
        with self.assertRaisesRegex(RuntimeError, 'already exists'):
            promotion.extract_flat(archive, target, {'a', 'b'})
        self.assertEqual((target / 'keep').read_bytes(), b'preserve')

    def test_encrypted_flag_is_rejected_before_extraction(self):
        archive = self.write_zip([('a', b'owned')])
        data = bytearray(archive.read_bytes())
        local = data.index(b'PK\x03\x04')
        central = data.index(b'PK\x01\x02')
        data[local + 6] |= 1
        data[central + 8] |= 1
        archive.write_bytes(data)
        with self.assertRaisesRegex(RuntimeError, 'Unsafe archive entry'):
            promotion.extract_flat(archive, self.root / 'encrypted', {'a'})
        self.assertFalse((self.root / 'encrypted').exists())


class FakeGitHub:
    """A strict subprocess boundary for GET-only proof and a private draft."""
    def __init__(self, receipt, archive_bytes=b''):
        self.receipt = receipt
        self.archive_bytes = archive_bytes
        self.records = good_remote_records()
        self.commands = []
        self.release = None
        self.tag = None
        self.after_create = None

    def __call__(self, arguments, **kwargs):
        self.commands.append(list(arguments))
        if arguments == ['git', 'rev-parse', 'HEAD']:
            return subprocess.CompletedProcess(arguments, 0, stdout=PROMOTION_SHA + '\n', stderr='')
        if arguments[:3] == ['gh', 'release', 'create']:
            if self.release is not None:
                raise AssertionError('A release already exists')
            self.release = {'id': 6789, 'tag_name': 'v' + promotion.VERSION,
                            'target_commitish': promotion.SOURCE_SHA,
                            'draft': True, 'prerelease': True,
                            'assets': [{'name': row['name'], 'size': row['size'],
                                        'state': 'uploaded', 'digest': 'sha256:' + row['sha256']}
                                       for row in self.receipt['assets']]}
            if self.after_create:
                self.after_create(self)
            return subprocess.CompletedProcess(arguments, 0, stdout='', stderr='')
        if arguments[:4] != ['gh', 'api', '--hostname', 'github.com']:
            raise AssertionError('Forbidden command: ' + repr(arguments))
        if '--method' in arguments or '--raw-field' in arguments:
            raise AssertionError('Only read-only API requests are permitted')
        endpoint = arguments[-1]
        prefix = f'repos/{promotion.REPOSITORY}/'
        if endpoint == prefix + f'actions/artifacts/{promotion.ARTIFACT_ID}/zip':
            kwargs['stdout'].write(self.archive_bytes)
            return subprocess.CompletedProcess(arguments, 0, stderr=b'')
        if endpoint == prefix + 'git/ref/tags/v' + promotion.VERSION:
            if self.tag is None:
                return subprocess.CompletedProcess(arguments, 1, stdout='', stderr='(HTTP 404)')
            value = self.tag
        elif endpoint == prefix + 'releases?per_page=100&page=1':
            value = [] if self.release is None else [self.release]
        elif endpoint == prefix + f'actions/runs/{PROMOTION_RUN_ID}':
            value = good_promotion_record()
        else:
            value = record_api(self.records)(endpoint)
        return subprocess.CompletedProcess(arguments, 0, stdout=json.dumps(value), stderr='')


class DraftCreationTests(OfflineTestCase):
    def setUp(self):
        super().setUp()
        assets = []
        for name in sorted(promotion.expected_names(promotion.VERSION)):
            path = self.root / name
            path.write_bytes(('synthetic asset: ' + name).encode())
            assets.append({'name': name, 'path': str(path), 'size': path.stat().st_size,
                           'sha256': promotion.gate.digest(path)})
        self.receipt = {'assets': assets}
        self.notes = self.root / 'release-notes.txt'
        self.notes.write_text('Synthetic private draft test. No Windows acceptance claim.')
        self.remote = FakeGitHub(self.receipt)

    def create(self):
        with patch.object(subprocess, 'run', side_effect=self.remote):
            return promotion.create_draft(self.receipt, self.notes)

    def test_only_one_draft_prerelease_command_uses_exact_original_assets(self):
        result = self.create()
        self.assertEqual(result['draft_id'], 6789)
        self.assertTrue(result['draft'])
        self.assertTrue(result['prerelease'])
        self.assertFalse(result['published'])
        self.assertEqual(result['asset_count'], 15)
        self.assertEqual(result['evidence_file_count'], 60)
        commands = [cmd for cmd in self.remote.commands if cmd[:3] == ['gh', 'release', 'create']]
        self.assertEqual(len(commands), 1)
        command = commands[0]
        for flag in ('--draft', '--prerelease', '--latest=false'):
            self.assertIn(flag, command)
        self.assertEqual(command[command.index('--target') + 1], promotion.SOURCE_SHA)
        self.assertEqual(command[command.index('--notes-file') + 1], str(self.notes))
        self.assertEqual(command[-15:], [row['path'] for row in self.receipt['assets']])
        for cmd in self.remote.commands:
            self.assertFalse(set(cmd) & {'PATCH', 'POST', '--clobber', 'edit', 'delete', 'publish', 'auth'})
            if cmd[1] == 'api':
                self.assertNotIn('--method', cmd)
                self.assertNotIn('/git/refs', cmd[-1])

    def test_tag_or_draft_conflict_prevents_any_creation_or_overwrite(self):
        for kind in ('tag', 'draft', 'published'):
            remote = FakeGitHub(self.receipt)
            if kind == 'tag':
                remote.tag = {'ref': 'refs/tags/v' + promotion.VERSION}
            else:
                remote.release = {'id': 55, 'tag_name': 'v' + promotion.VERSION,
                                  'draft': kind == 'draft'}
            with self.subTest(conflict=kind), patch.object(subprocess, 'run', side_effect=remote), \
                 self.assertRaisesRegex(RuntimeError, 'already exists'):
                promotion.create_draft(self.receipt, self.notes)
            self.assertFalse(any(cmd[:3] == ['gh', 'release', 'create'] for cmd in remote.commands))

    def test_every_asset_is_rehashed_immediately_before_creation(self):
        for row in self.receipt['assets']:
            path = Path(row['path'])
            original = path.read_bytes()
            path.write_bytes(b'X' * len(original))
            remote = FakeGitHub(self.receipt)
            with self.subTest(asset=row['name']), patch.object(subprocess, 'run', side_effect=remote), \
                 self.assertRaisesRegex(RuntimeError, 'changed after complete revalidation'):
                promotion.create_draft(self.receipt, self.notes)
            self.assertFalse(any(cmd[:3] == ['gh', 'release', 'create'] for cmd in remote.commands))
            path.write_bytes(original)

    def test_every_remote_asset_digest_is_mandatory_and_exact(self):
        for index, row in enumerate(self.receipt['assets']):
            for digest in (None, 'sha256:' + '0' * 64):
                remote = FakeGitHub(self.receipt)
                remote.after_create = lambda state, i=index, value=digest: state.release['assets'][i].update(digest=value)
                with self.subTest(asset=row['name'], digest=digest), \
                     patch.object(subprocess, 'run', side_effect=remote), \
                     self.assertRaisesRegex(RuntimeError, 'Remote asset SHA256'):
                    promotion.create_draft(self.receipt, self.notes)
                self.assertIsNotNone(remote.release)
                self.assertTrue(remote.release['draft'])
                self.assertFalse(any('delete' in command or 'PATCH' in command for command in remote.commands))

    def test_incomplete_duplicate_wrong_size_or_unuploaded_remote_assets_fail(self):
        alterations = [lambda s: s.release['assets'].pop(),
                       lambda s: s.release['assets'].append(copy.deepcopy(s.release['assets'][0])),
                       lambda s: s.release['assets'].__setitem__(1, copy.deepcopy(s.release['assets'][0])),
                       lambda s: s.release['assets'][0].update(size=1),
                       lambda s: s.release['assets'][0].update(state='new')]
        for index, alter in enumerate(alterations):
            remote = FakeGitHub(self.receipt)
            remote.after_create = alter
            with self.subTest(case=index), patch.object(subprocess, 'run', side_effect=remote), \
                 self.assertRaises(RuntimeError):
                promotion.create_draft(self.receipt, self.notes)
            self.assertTrue(remote.release['draft'])

    def test_unexpected_created_release_or_public_tag_fails_without_cleanup(self):
        alterations = [lambda s: s.release.update(draft=False),
                       lambda s: s.release.update(prerelease=False),
                       lambda s: s.release.update(tag_name='v0.0.0'),
                       lambda s: s.release.update(target_commitish='b' * 40),
                       lambda s: s.release.update(id=True),
                       lambda s: setattr(s, 'tag', {'ref': 'refs/tags/v' + promotion.VERSION})]
        for index, alter in enumerate(alterations):
            remote = FakeGitHub(self.receipt)
            remote.after_create = alter
            with self.subTest(case=index), patch.object(subprocess, 'run', side_effect=remote), \
                 self.assertRaises(RuntimeError):
                promotion.create_draft(self.receipt, self.notes)
            self.assertFalse(any('delete' in command or 'PATCH' in command for command in remote.commands))

    def test_failed_create_is_not_retried_or_cleaned_up(self):
        def failed(arguments, **kwargs):
            if arguments[:3] == ['gh', 'release', 'create']:
                self.remote.commands.append(list(arguments))
                return subprocess.CompletedProcess(arguments, 1, stdout='', stderr='upload failed')
            return self.remote(arguments, **kwargs)
        with patch.object(subprocess, 'run', side_effect=failed), \
             self.assertRaisesRegex(RuntimeError, 'GitHub command failed'):
            promotion.create_draft(self.receipt, self.notes)
        self.assertEqual(sum(cmd[:3] == ['gh', 'release', 'create'] for cmd in self.remote.commands), 1)
        self.assertFalse(any('delete' in cmd or 'edit' in cmd for cmd in self.remote.commands))


class SyntheticVerifierIntegrationTests(OfflineTestCase):
    def setUp(self):
        super().setUp()
        self.fixture = fixtures.ReleaseFixture(methodName='runTest')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.start_patch(promotion, 'gate', fixtures.gate)
        self.start_patch(promotion, 'VERSION', fixtures.VERSION)
        self.start_patch(promotion, 'SOURCE_SHA', fixtures.SHA)
        self.start_patch(promotion, 'RUN_ID', fixtures.RUN_ID)
        self.start_patch(promotion, 'RUN_ATTEMPT', fixtures.RUN_ATTEMPT)
        self.start_patch(promotion, 'EXE_SHA256', self.fixture.hash)
        self.start_patch(promotion, 'EXE_SIZE', self.fixture.exe.stat().st_size)
        # Stage the actual verifier output using its normal checkout layout.
        root = self.fixture.root
        (root / 'dist').mkdir()
        self.fixture.release.rename(root / 'dist' / 'release')
        self.fixture.release = root / 'dist' / 'release'
        self.fixture.exe = self.fixture.release / self.fixture.filename
        self.fixture.evidence.rename(root / 'reports')
        self.fixture.evidence = root / 'reports'
        self.fixture.output = root / 'build' / 'verified-preview'
        # The shared fixture substitutes native post-build validation and normally
        # retains only its export. Include the production ten-name inventory using
        # explicitly synthetic stand-ins, preserving that documented substitution.
        for name in postbuild.EVIDENCE_NAMES:
            if not (self.fixture.evidence / name).exists():
                self.fixture.write_json(self.fixture.evidence / name,
                                        {'unit_fixture': 'synthetic postbuild inventory'})
        self.start_patch(fixtures.gate, 'verify_postbuild_adoption',
                         lambda *args: (self.fixture.postbuild_summary, postbuild.EVIDENCE_NAMES))
        # Ensure regenerated ZIP metadata differs while all evidence bytes stay exact.
        for path in self.fixture.evidence.iterdir():
            os.utime(path, (946684800, 946684800))
        original = self.fixture.verify()
        self.assertEqual(len(original['evidence_sha256']), 60)
        self.bundle = root / 'build' / 'verified-artifact'
        staging.stage(self.fixture.output, self.bundle, fixtures.SHA,
                      fixtures.RUN_ID, fixtures.RUN_ATTEMPT, root=root)
        self.receipt = json.loads((self.bundle / 'verified-release.json').read_text())
        self.work = self.root / 'promotion'
        self.work.mkdir()
        self.provenance = expected_provenance()
        self.source_checkout = self.root / 'synthetic-original-source'
        self.source_checkout.mkdir()
        # This fixture must remain inside the process that owns its documented
        # native/archive stand-ins. Separate tests exercise the real boundary.
        def synthetic_reverify(bundle, evidence, work, source_checkout):
            self.assertEqual(source_checkout, self.source_checkout)
            return fixtures.gate.verify(bundle, evidence, promotion.REPOSITORY,
                                        promotion.SOURCE_SHA, work / 'reverified',
                                        promotion.RUN_ID, promotion.RUN_ATTEMPT)
        self.start_patch(promotion, 'reverify_original', synthetic_reverify)

    def save_receipt(self):
        (self.bundle / 'verified-release.json').write_text(json.dumps(self.receipt))

    def update_asset_hash(self, name):
        path = self.bundle / name
        row = next(row for row in self.receipt['assets'] if row['name'] == name)
        row.update(size=path.stat().st_size, sha256=promotion.gate.digest(path))
        self.save_receipt()

    def rewrite_evidence(self, name, update, *, rehash_evidence=False):
        archive_path = self.bundle / f'windows-test-evidence-{promotion.VERSION}.zip'
        with zipfile.ZipFile(archive_path) as archive:
            entries = {row.filename: archive.read(row) for row in archive.infolist()}
        entries[name] = update(entries[name])
        with zipfile.ZipFile(archive_path, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            for filename, data in entries.items():
                archive.writestr(filename, data)
        if rehash_evidence:
            self.receipt['evidence_sha256'][name] = hashlib.sha256(entries[name]).hexdigest()
        self.update_asset_hash(archive_path.name)

    def verify(self):
        return promotion.verify_bundle(self.bundle, self.work, self.provenance, self.source_checkout)

    def test_real_verifier_rechecks_synthetic_bundle_and_keeps_original_zip(self):
        original_bytes = {p.name: p.read_bytes() for p in self.bundle.iterdir()}
        with patch.object(fixtures.gate, 'verify', wraps=fixtures.gate.verify) as verify:
            receipt = self.verify()
        verify.assert_called_once_with(self.bundle, self.work / 'evidence', promotion.REPOSITORY,
                                       fixtures.SHA, self.work / 'reverified', fixtures.RUN_ID,
                                       fixtures.RUN_ATTEMPT)
        self.assertEqual({p.name: p.read_bytes() for p in self.bundle.iterdir()}, original_bytes)
        self.assertEqual(len(receipt['assets']), 15)
        self.assertTrue(all(Path(row['path']).parent == self.bundle for row in receipt['assets']))
        evidence_name = f'windows-test-evidence-{promotion.VERSION}.zip'
        original = next(row for row in receipt['assets'] if row['name'] == evidence_name)
        self.assertEqual(original['sha256'], hashlib.sha256(original_bytes[evidence_name]).hexdigest())
        self.assertNotEqual(promotion.gate.digest(self.work / 'reverified' / evidence_name), original['sha256'])
        self.assertEqual(len(list((self.work / 'evidence').iterdir())), 60)
        self.command_guard.assert_not_called()

    def test_original_asset_bytes_cannot_change_even_if_size_is_unchanged(self):
        for row in self.receipt['assets']:
            path = self.bundle / row['name']
            original = path.read_bytes()
            path.write_bytes(b'X' * len(original))
            with self.subTest(asset=row['name']), self.assertRaises(RuntimeError):
                self.verify()
            path.write_bytes(original)
        self.assertFalse((self.work / 'reverified').exists())

    def test_changed_evidence_bytes_fail_even_when_zip_asset_hash_is_updated(self):
        self.rewrite_evidence('windows-exe-smoke.json', lambda data: data + b' ')
        with self.assertRaisesRegex(RuntimeError, 'Evidence bytes changed'):
            self.verify()
        self.assertFalse((self.work / 'reverified').exists())

    def test_rehashed_invalid_windows_evidence_still_fails_real_original_gate(self):
        def invalidate(data):
            report = json.loads(data)
            report['status'] = 'failed'
            return json.dumps(report).encode()
        self.rewrite_evidence('windows-exe-smoke.json', invalidate, rehash_evidence=True)
        with patch.object(fixtures.gate, 'verify', wraps=fixtures.gate.verify) as verify:
            with self.assertRaises(RuntimeError):
                self.verify()
        verify.assert_called_once()
        self.assertFalse((self.work / 'reverified').exists())

    def test_changed_summary_and_original_notes_cannot_be_replaced(self):
        self.receipt['unapproved_summary'] = 'invented'
        self.save_receipt()
        with self.assertRaisesRegex(RuntimeError, 'Reverified proof differs'):
            self.verify()
        shutil.rmtree(self.work / 'evidence')
        shutil.rmtree(self.work / 'reverified')
        del self.receipt['unapproved_summary']
        self.save_receipt()
        (self.bundle / 'release-notes.txt').write_text('Changed notes')
        with self.assertRaisesRegex(RuntimeError, 'Release notes differ'):
            self.verify()

    def test_changed_identity_inventory_and_portable_paths_fail_before_reverification(self):
        original = copy.deepcopy(self.receipt)
        mutations = [lambda r: r.update(version='0.0.0'), lambda r: r.update(tag='v0.0.0'),
                     lambda r: r.update(source_sha='b' * 40), lambda r: r.update(run_id=1),
                     lambda r: r.update(run_attempt=2), lambda r: r.update(exe_sha256='0' * 64),
                     lambda r: r['assets'].pop(),
                     lambda r: r['assets'].__setitem__(1, copy.deepcopy(r['assets'][0])),
                     lambda r: r['assets'][0].update(path='../escape'),
                     lambda r: r['assets'][0].update(size=True),
                     lambda r: r['evidence_sha256'].pop(next(iter(r['evidence_sha256']))),
                     lambda r: r['evidence_sha256'].update(extra='0' * 64),
                     lambda r: r['evidence_sha256'].__setitem__(next(iter(r['evidence_sha256'])), 'bad')]
        for index, mutate in enumerate(mutations):
            self.receipt = copy.deepcopy(original)
            mutate(self.receipt)
            self.save_receipt()
            with self.subTest(case=index), patch.object(fixtures.gate, 'verify') as verify, \
                 self.assertRaises(RuntimeError):
                self.verify()
            verify.assert_not_called()
        self.assertFalse((self.work / 'evidence').exists())

    def test_end_to_end_main_revalidates_existing_artifact_then_creates_private_draft(self):
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            for path in self.bundle.iterdir():
                archive.write(path, arcname=path.name)
        data = output.getvalue()
        self.start_patch(promotion, 'ARTIFACT_SIZE', len(data))
        self.start_patch(promotion, 'ARTIFACT_SHA256', hashlib.sha256(data).hexdigest())
        remote = FakeGitHub(self.receipt, data)
        work = self.root / 'end-to-end'
        arguments = ['promote_verified_candidate.py', '--run-id', str(promotion.RUN_ID),
                     '--source-sha', promotion.SOURCE_SHA, '--run-attempt', str(promotion.RUN_ATTEMPT),
                     '--artifact-id', str(promotion.ARTIFACT_ID), '--artifact-sha256', promotion.ARTIFACT_SHA256,
                     '--work-dir', str(work), '--source-checkout', str(self.source_checkout)]
        environment = promotion_environment()
        with patch.object(sys, 'argv', arguments), patch.dict(os.environ, environment, clear=True), \
             patch.object(subprocess, 'run', side_effect=remote), patch('sys.stdout', new_callable=io.StringIO), \
             patch.object(fixtures.gate, 'verify', wraps=fixtures.gate.verify) as verify:
            promotion.main()
        verify.assert_called_once()
        result = json.loads((work / 'draft-verification.json').read_text())
        self.assertTrue(result['draft'])
        self.assertFalse(result['published'])
        self.assertEqual(result['asset_count'], 15)
        self.assertEqual(result['evidence_file_count'], 60)
        self.assertEqual((work / 'original-artifact.zip').read_bytes(), data)
        commands = [cmd for cmd in remote.commands if cmd[:3] == ['gh', 'release', 'create']]
        self.assertEqual(len(commands), 1)
        self.assertTrue(all(Path(path).parent == work / 'original' for path in commands[0][-15:]))
        self.assertFalse(any('reverified' in path for path in commands[0]))
        for row in self.receipt['assets']:
            self.assertEqual((work / 'original' / row['name']).read_bytes(),
                             (self.bundle / row['name']).read_bytes())
        run_endpoint = f'repos/{promotion.REPOSITORY}/actions/runs/{promotion.RUN_ID}'
        self.assertEqual(sum(cmd[-1] == run_endpoint for cmd in remote.commands), 2)
        self.assertIsNone(remote.tag)
        self.assertTrue(remote.release['draft'])


class PromotionMainSafetyTests(OfflineTestCase):
    def setUp(self):
        super().setUp()
        self.work = self.root / 'promotion'
        self.arguments = ['promote_verified_candidate.py', '--run-id', str(promotion.RUN_ID),
                          '--source-sha', promotion.SOURCE_SHA, '--run-attempt', str(promotion.RUN_ATTEMPT),
                          '--artifact-id', str(promotion.ARTIFACT_ID),
                          '--artifact-sha256', promotion.ARTIFACT_SHA256, '--work-dir', str(self.work),
                          '--source-checkout', str(self.root / 'original-source')]
        self.environment = promotion_environment()

    def test_wrong_execution_context_fails_before_network_or_writes(self):
        for key in ('GITHUB_ACTIONS', 'GITHUB_REPOSITORY', 'GITHUB_REF',
                    'GITHUB_EVENT_NAME', 'GITHUB_WORKFLOW_REF'):
            environment = dict(self.environment, **{key: 'wrong'})
            with self.subTest(key=key), patch.object(sys, 'argv', self.arguments), \
                 patch.dict(os.environ, environment, clear=True), \
                 self.assertRaisesRegex(RuntimeError, 'approved manual promotion context'):
                promotion.main()
        self.assertFalse(self.work.exists())
        self.command_guard.assert_not_called()

    def test_existing_work_directory_is_never_reused(self):
        self.work.mkdir()
        sentinel = self.work / 'keep'
        sentinel.write_bytes(b'preserve')
        with patch.object(sys, 'argv', self.arguments), \
             patch.dict(os.environ, self.environment, clear=True), \
             self.assertRaisesRegex(RuntimeError, 'directory already exists'):
            promotion.main()
        self.assertEqual(sentinel.read_bytes(), b'preserve')
        self.command_guard.assert_not_called()

    def test_failed_reverification_never_reaches_draft_creation(self):
        with patch.object(sys, 'argv', self.arguments), \
             patch.dict(os.environ, self.environment, clear=True), \
             patch.object(promotion, 'current_promotion_proof', return_value={}), \
             patch.object(promotion, 'remote_proof', return_value=expected_provenance()), \
             patch.object(promotion, 'download_artifact'), patch.object(promotion, 'extract_flat'), \
             patch.object(promotion, 'verify_bundle', side_effect=RuntimeError('gate failed')), \
             patch.object(promotion, 'create_draft') as create, \
             self.assertRaisesRegex(RuntimeError, 'gate failed'):
            promotion.main()
        create.assert_not_called()
        self.assertFalse((self.work / 'draft-verification.json').exists())

    def test_changed_promotion_run_before_creation_stops_without_mutation(self):
        with patch.object(sys, 'argv', self.arguments), \
             patch.dict(os.environ, self.environment, clear=True), \
             patch.object(promotion, 'current_promotion_proof', side_effect=[{'id': 1}, {'id': 2}]), \
             patch.object(promotion, 'remote_proof', return_value=expected_provenance()), \
             patch.object(promotion, 'download_artifact'), patch.object(promotion, 'extract_flat'), \
             patch.object(promotion, 'verify_bundle', return_value={}), \
             patch.object(promotion, 'create_draft') as create, \
             self.assertRaisesRegex(RuntimeError, 'Promotion provenance changed'):
            promotion.main()
        create.assert_not_called()
        self.assertFalse((self.work / 'draft-verification.json').exists())

    def test_changed_remote_proof_before_creation_stops_without_mutation(self):
        original = expected_provenance()
        changed = dict(original, source_sha='b' * 40)
        with patch.object(sys, 'argv', self.arguments), \
             patch.dict(os.environ, self.environment, clear=True), \
             patch.object(promotion, 'current_promotion_proof', return_value={}), \
             patch.object(promotion, 'remote_proof', side_effect=[original, changed]), \
             patch.object(promotion, 'download_artifact'), patch.object(promotion, 'extract_flat'), \
             patch.object(promotion, 'verify_bundle', return_value={}), \
             patch.object(promotion, 'create_draft') as create, \
             self.assertRaisesRegex(RuntimeError, 'provenance changed'):
            promotion.main()
        create.assert_not_called()
        self.assertFalse((self.work / 'draft-verification.json').exists())


if __name__ == '__main__':
    unittest.main()

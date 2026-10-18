"""One exact existing Windows artifact -> fully revalidated private draft only.

Never builds, runs candidate code, creates credentials, publishes, replaces a
release, or deletes partial results. gh alone uses the workflow's ephemeral token.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import verify_release as gate
from scripts.stage_verified_artifact import expected_names

REPOSITORY = gate.REPOSITORY
SOURCE_SHA = '52b8720e2aa7f2b43afa5f1f73e884157f15deb6'
RUN_ID = 39098790761
RUN_ATTEMPT = 1
ARTIFACT_ID = 12125904800
ARTIFACT_SHA256 = 'ed3eb0d5aca6c909c8794d9513f103ba8ca6127a3cf48497a8548d9f84652b27'
ARTIFACT_SIZE = 188584735
EXE_SHA256 = 'cbb177464da521dcc87f1309de03c6a38e7865f1c08abf68be4cad365baad4f5'
EXE_SIZE = 107100256
VERSION = '0.4.14'
WORKFLOW = '.github/workflows/promote-verified-candidate.yml'
MAX_EXPANDED = 250_000_000
require = gate.require


def check_inputs(run_id, source_sha, run_attempt, artifact_id, artifact_sha256):
    require((run_id, source_sha, run_attempt, artifact_id, artifact_sha256) ==
            (RUN_ID, SOURCE_SHA, RUN_ATTEMPT, ARTIFACT_ID, ARTIFACT_SHA256),
            'Only the explicitly verified run/artifact may be promoted')
    require(all(type(x) is int for x in (run_id, run_attempt, artifact_id)), 'Invalid numeric identity')


def remote_proof():
    run = gate.gh_api(f'repos/{REPOSITORY}/actions/runs/{RUN_ID}')
    require(isinstance(run, dict) and type(run.get('id')) is int and run.get('id') == RUN_ID
            and type(run.get('run_attempt')) is int and run.get('run_attempt') == RUN_ATTEMPT
            and run.get('status') == 'completed' and run.get('conclusion') == 'success'
            and run.get('head_sha') == SOURCE_SHA and run.get('head_branch') == 'main'
            and run.get('event') == 'workflow_dispatch' and run.get('path') == gate.PREVIEW_WORKFLOW,
            'Original Windows run provenance or successful attempt changed')
    repo, head = run.get('repository', {}), run.get('head_repository', {})
    require(repo.get('full_name') == REPOSITORY and repo.get('private') is False
            and repo.get('fork') is False and head.get('full_name') == REPOSITORY
            and head.get('fork') is False and type(repo.get('id')) is int and repo['id'] > 0
            and type(head.get('id')) is int and head.get('id') == repo['id'], 'Original run repository/fork mismatch')
    jobs = gate.gh_api(f'repos/{REPOSITORY}/actions/runs/{RUN_ID}/attempts/{RUN_ATTEMPT}/jobs?per_page=100')
    require(type(jobs.get('total_count')) is int and jobs.get('total_count') == 1 and len(jobs.get('jobs', [])) == 1, 'Unexpected original jobs')
    job = jobs['jobs'][0]
    require(job.get('name') == 'native-preview' and job.get('status') == 'completed'
            and job.get('conclusion') == 'success' and job.get('head_sha') == SOURCE_SHA,
            'Original Windows job is not the successful exact source')
    steps = {x.get('name'): x for x in job.get('steps', [])}
    for name in ('Python unit tests', 'Re-run Python tests with the adopted native library',
                 'Verify fresh native preview, source licenses and exact tested bytes',
                 'Stage the exact verified candidate without publishing',
                 'Preserve this exact verified candidate for one day'):
        require(steps.get(name, {}).get('conclusion') == 'success', 'Required original verification step missing')
    require(steps.get('Create verified draft and publish its ID only as a non-latest prerelease', {}).get('conclusion') == 'skipped',
            'Original run was not non-publishing validation')
    artifact = gate.gh_api(f'repos/{REPOSITORY}/actions/artifacts/{ARTIFACT_ID}')
    require(type(artifact.get('id')) is int and artifact.get('id') == ARTIFACT_ID and artifact.get('name') == 'verified-candidate-' + SOURCE_SHA
            and artifact.get('expired') is False and type(artifact.get('size_in_bytes')) is int
            and artifact.get('size_in_bytes') == ARTIFACT_SIZE
            and artifact.get('digest') == 'sha256:' + ARTIFACT_SHA256,
            'Original immutable artifact identity/digest/expiry mismatch')
    owner = artifact.get('workflow_run', {})
    require(all(type(owner.get(k)) is int for k in ('id', 'repository_id', 'head_repository_id'))
            and owner.get('id') == RUN_ID and owner.get('head_sha') == SOURCE_SHA
            and owner.get('head_branch') == 'main' and owner.get('repository_id') == repo['id']
            and owner.get('head_repository_id') == repo['id'], 'Artifact belongs to another run/source')
    return {'repository': REPOSITORY, 'run_id': RUN_ID, 'run_attempt': RUN_ATTEMPT,
            'source_sha': SOURCE_SHA, 'workflow': gate.PREVIEW_WORKFLOW,
            'event': 'workflow_dispatch', 'branch': 'main'}


def current_promotion_proof():
    # Environment pins the intended context; authenticated metadata pins the
    # actual executing workflow. Never read credential environment variables.
    run_id = os.environ.get('GITHUB_RUN_ID', '')
    attempt = os.environ.get('GITHUB_RUN_ATTEMPT', '')
    sha = os.environ.get('GITHUB_SHA', '')
    require(re.fullmatch('[1-9][0-9]*', run_id) and re.fullmatch('[1-9][0-9]*', attempt)
            and re.fullmatch('[0-9a-f]{40}', sha), 'Invalid current promotion identity')
    run = gate.gh_api(f'repos/{REPOSITORY}/actions/runs/{run_id}')
    require(type(run.get('id')) is int and run['id'] == int(run_id)
            and type(run.get('run_attempt')) is int and run['run_attempt'] == int(attempt)
            and run.get('head_sha') == sha and run.get('status') == 'in_progress'
            and 'conclusion' in run and run['conclusion'] is None
            and run.get('head_branch') == 'main' and run.get('event') == 'workflow_dispatch'
            and run.get('path') == WORKFLOW, 'Not the active approved promotion workflow')
    repo, head = run.get('repository', {}), run.get('head_repository', {})
    require(repo.get('full_name') == REPOSITORY and repo.get('private') is False
            and repo.get('fork') is False and head.get('full_name') == REPOSITORY
            and head.get('fork') is False and type(repo.get('id')) is int and repo['id'] > 0
            and type(head.get('id')) is int and head['id'] == repo['id'],
            'Promotion workflow repository/fork mismatch')
    checkout = subprocess.run(['git', 'rev-parse', 'HEAD'], capture_output=True, text=True,
                              check=False, timeout=30)
    require(checkout.returncode == 0 and checkout.stdout.strip() == sha,
            'Promotion validator checkout differs from executing workflow')
    return {'run_id': int(run_id), 'run_attempt': int(attempt), 'source_sha': sha}


def download_artifact(path):
    with path.open('xb') as output:
        result = subprocess.run(['gh', 'api', '--hostname', 'github.com',
            f'repos/{REPOSITORY}/actions/artifacts/{ARTIFACT_ID}/zip'],
            stdout=output, stderr=subprocess.PIPE, check=False, timeout=600)
    require(result.returncode == 0, 'Official artifact download failed; no draft created')
    require(path.stat().st_size == ARTIFACT_SIZE and gate.digest(path) == ARTIFACT_SHA256,
            'Downloaded archive differs from the verified Actions artifact')


def extract_flat(archive_path, destination, names, *, max_bytes=MAX_EXPANDED):
    require(not destination.exists(), 'Extraction directory already exists')
    with zipfile.ZipFile(archive_path) as archive:
        entries = archive.infolist()
        require(len(entries) == len(names) and {x.filename for x in entries} == set(names),
                'Unexpected archive inventory, duplicate, or path')
        require(sum(x.file_size for x in entries) <= max_bytes, 'Expanded archive exceeds budget')
        for row in entries:
            require(row.filename == Path(row.filename).name and '/' not in row.filename and '\\' not in row.filename
                    and ':' not in row.filename and row.filename not in ('.', '..') and not row.is_dir()
                    and not row.flag_bits & 1 and not stat.S_ISLNK(row.external_attr >> 16),
                    'Unsafe archive entry')
        destination.mkdir(parents=True)
        for row in entries:
            with archive.open(row) as source, (destination / row.filename).open('xb') as target:
                remaining = row.file_size
                while remaining:
                    block = source.read(min(1024 * 1024, remaining))
                    require(bool(block), 'Truncated archive entry')
                    target.write(block); remaining -= len(block)
                require(not source.read(1), 'Archive entry exceeded declared size')


def check_original_source(source_checkout, source_archive):
    source_checkout = Path(source_checkout).resolve()
    def git(*arguments):
        result = subprocess.run(['git', '-C', str(source_checkout), *arguments],
                                capture_output=True, check=False, timeout=60)
        require(result.returncode == 0, 'Original source Git identity check failed')
        return result.stdout
    require(git('rev-parse', 'HEAD').decode().strip() == SOURCE_SHA,
            'Original verifier checkout is not the tested source commit')
    require(Path(git('rev-parse', '--show-toplevel').decode().strip()).resolve() == source_checkout,
            'Original verifier checkout is not an independent Git root')
    rows = git('ls-tree', '-r', '-z', '--full-tree', SOURCE_SHA).split(b'\0')
    tree = {}
    for row in filter(None, rows):
        header, raw_name = row.split(b'\t', 1)
        mode, kind, blob = header.decode('ascii').split()
        name = raw_name.decode('utf8')
        require(mode in ('100644', '100755') and kind == 'blob' and name not in tree,
                'Unsupported original source tree entry')
        tree[name] = blob
    require(0 < len(tree) <= 10000, 'Invalid original source inventory')
    actual = set()
    for path in source_checkout.rglob('*'):
        relative = path.relative_to(source_checkout)
        if relative.parts[0] == '.git':
            continue
        require(not path.is_symlink(), 'Original verifier checkout contains a link')
        if path.is_file():
            actual.add(relative.as_posix())
    require(actual == set(tree), 'Original verifier checkout has extra or missing source files')
    with zipfile.ZipFile(source_archive) as archive:
        require(archive.comment == SOURCE_SHA.encode('ascii'), 'Original source archive commit changed')
        entries = archive.infolist()
        require(len({r.filename for r in entries}) == len(entries)
                and sum(r.file_size for r in entries) <= 256 * 1024 * 1024,
                'Original source archive duplicates or exceeds budget')
        files = [r for r in entries if not r.is_dir()]
        require({r.filename for r in files} == set(tree), 'Original source archive differs from Git inventory')
        for row in files:
            require(not stat.S_ISLNK(row.external_attr >> 16) and not row.flag_bits & 1,
                    'Unsafe original source archive entry')
            raw = archive.read(row)
            blob = hashlib.sha1(b'blob ' + str(len(raw)).encode('ascii') + b'\0' + raw).hexdigest()
            require(blob == tree[row.filename], 'Original source archive blob differs from tested Git tree')
            require((source_checkout / row.filename).read_bytes() == raw,
                    'Original verifier checkout bytes differ from original source archive')
    return source_checkout


def verifier_environment():
    # Child validates a separate original checkout, not the promoter commit.
    # With GITHUB_SHA absent the unchanged original validator reads its real
    # Git HEAD. Do not replace that value or pass any workflow credentials.
    allowed = {'PATH', 'PATHEXT', 'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'TEMP', 'TMP',
               'USERPROFILE', 'HOME', 'APPDATA', 'LOCALAPPDATA', 'PROGRAMFILES',
               'PROGRAMFILES(X86)', 'PROGRAMDATA'}
    env = {k: v for k, v in os.environ.items() if k.upper() in allowed}
    env.update(PYTHONUTF8='1', PYTHONDONTWRITEBYTECODE='1', ORT_DISABLE_TELEMETRY='1')
    return env


def reverify_original(bundle, evidence, work, source_checkout):
    source = check_original_source(source_checkout, bundle / f'vga-aram-helper-{VERSION}-source.zip')
    output = (work / 'reverified').resolve()
    command = [sys.executable, str(source / 'scripts' / 'verify_release.py'),
               '--release-dir', str(bundle.resolve()), '--evidence-dir', str(evidence.resolve()),
               '--output-dir', str(output), '--repository', REPOSITORY,
               '--source-sha', SOURCE_SHA, '--run-id', str(RUN_ID), '--run-attempt', str(RUN_ATTEMPT)]
    result = subprocess.run(command, cwd=source, env=verifier_environment(),
                            capture_output=True, text=True, check=False, timeout=600)
    (work / 'original-verifier.log').write_text(result.stdout + result.stderr, encoding='utf8')
    if result.returncode:
        print((result.stdout + result.stderr)[-6000:], file=sys.stderr)
        raise gate.VerificationError('Unchanged original-source verifier rejected the retained candidate')
    return gate.read_json(output / 'verified-release.json')


def verify_bundle(bundle, work, provenance, source_checkout):
    receipt = gate.read_json(bundle / 'verified-release.json')
    require(receipt.get('version') == VERSION and receipt.get('tag') == 'v' + VERSION,
            'Unexpected staged version')
    gate.check_preview_identity(receipt, provenance)
    require(receipt.get('exe_sha256') == EXE_SHA256 and receipt.get('exe_size') == EXE_SIZE,
            'Staged EXE differs from original tested bytes')
    assets = receipt.get('assets', [])
    require(len(assets) == 15 and {x.get('name') for x in assets} == expected_names(VERSION),
            'Staged asset inventory changed')
    for row in assets:
        require(row.get('path') == row['name'] and type(row.get('size')) is int and row['size'] > 0,
                'Staged receipt is not portable/exact')
        path = gate.checked_file(bundle / row['name'])
        require(path.stat().st_size == row['size'] and gate.digest(path) == row.get('sha256'),
                'Staged asset bytes changed')
    hashes = receipt.get('evidence_sha256', {})
    require(isinstance(hashes, dict) and len(hashes) == 60
            and all(isinstance(k, str) and isinstance(v, str) and re.fullmatch('[0-9a-f]{64}', v)
                    for k, v in hashes.items()), 'Incomplete original evidence inventory')
    evidence = work / 'evidence'
    extract_flat(bundle / f'windows-test-evidence-{VERSION}.zip', evidence, hashes, max_bytes=20_000_000)
    for name, digest in hashes.items():
        require(gate.digest(evidence / name) == digest, 'Evidence bytes changed')
    # Re-run ALL existing package/license/source/EXE/archive/60-evidence gates.
    # The temporary regenerated evidence ZIP is validation output, NEVER uploaded.
    fresh = reverify_original(bundle, evidence, work, source_checkout)
    require({k: v for k, v in fresh.items() if k != 'assets'} ==
            {k: v for k, v in receipt.items() if k != 'assets'}, 'Reverified proof differs from original receipt')
    original = {row['name']: row for row in assets}
    require({r['name'] for r in fresh['assets']} == set(original), 'Reverified asset inventory changed')
    for row in fresh['assets']:
        if row['name'] != f'windows-test-evidence-{VERSION}.zip':
            require(all(row[k] == original[row['name']][k] for k in ('size', 'sha256')),
                    'Reverified asset identity differs')
    require((work / 'reverified' / 'release-notes.txt').read_bytes() ==
            (bundle / 'release-notes.txt').read_bytes(), 'Release notes differ from original verified notes')
    receipt['assets'] = [{**row, 'path': str(bundle / row['name'])} for row in assets]
    return receipt


def create_draft(receipt, notes):
    tag = 'v' + VERSION
    require(gate.gh_api(f'repos/{REPOSITORY}/git/ref/tags/{tag}', allow_absent=True) is None,
            'Tag already exists; never overwrite')
    require(gate.find_release(REPOSITORY, tag) is None, 'Release/draft already exists; never reuse or overwrite')
    for row in receipt['assets']:
        require(Path(row['path']).stat().st_size == row['size'] and gate.digest(Path(row['path'])) == row['sha256'],
                'Asset changed after complete revalidation')
    # No tag reservation, PATCH, edit, clobber or publication. A failure leaves
    # any partial draft for inspection; subsequent runs refuse that conflict.
    gate.gh_run(['release', 'create', tag, '--repo', REPOSITORY, '--target', SOURCE_SHA,
                 '--draft', '--prerelease', '--latest=false', '--title',
                 'VGA Startup Recovery DIAGNOSTIC PREVIEW 0.4.14 / 诊断测试版',
                 '--notes-file', str(notes), *[row['path'] for row in receipt['assets']]])
    release = gate.find_release(REPOSITORY, tag)
    require(isinstance(release, dict) and release.get('draft') is True and release.get('prerelease') is True
            and release.get('tag_name') == tag and release.get('target_commitish') == SOURCE_SHA
            and type(release.get('id')) is int and release['id'] > 0, 'Unexpected created draft identity')
    gate.check_remote_assets(release, receipt['assets'])
    require(gate.gh_api(f'repos/{REPOSITORY}/git/ref/tags/{tag}', allow_absent=True) is None,
            'Unexpected public tag appeared; stop for inspection')
    return {'draft_id': release['id'], 'draft': True, 'prerelease': True, 'published': False,
            'source_sha': SOURCE_SHA, 'original_run_id': RUN_ID, 'artifact_id': ARTIFACT_ID,
            'artifact_sha256': ARTIFACT_SHA256, 'exe_sha256': EXE_SHA256,
            'exe_size': EXE_SIZE, 'asset_count': 15, 'evidence_file_count': 60}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-id', type=int, required=True)
    parser.add_argument('--source-sha', required=True)
    parser.add_argument('--run-attempt', type=int, required=True)
    parser.add_argument('--artifact-id', type=int, required=True)
    parser.add_argument('--artifact-sha256', required=True)
    parser.add_argument('--work-dir', type=Path, required=True)
    parser.add_argument('--source-checkout', type=Path, required=True)
    args = parser.parse_args()
    check_inputs(args.run_id, args.source_sha, args.run_attempt, args.artifact_id, args.artifact_sha256)
    context = {'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': REPOSITORY, 'GITHUB_REF': 'refs/heads/main',
               'GITHUB_EVENT_NAME': 'workflow_dispatch',
               'GITHUB_WORKFLOW_REF': f'{REPOSITORY}/{WORKFLOW}@refs/heads/main'}
    require(all(os.environ.get(k) == v for k, v in context.items()), 'Not the approved manual promotion context')
    require(not args.work_dir.exists(), 'Promotion directory already exists')
    promotion = current_promotion_proof()
    proof = remote_proof()
    args.work_dir.mkdir(parents=True)
    archive = args.work_dir / 'original-artifact.zip'
    download_artifact(archive)
    bundle = args.work_dir / 'original'
    extract_flat(archive, bundle, expected_names(VERSION) | {'verified-release.json', 'release-notes.txt'})
    receipt = verify_bundle(bundle, args.work_dir, proof, args.source_checkout)
    require(remote_proof() == proof, 'Original provenance changed before draft creation')
    require(current_promotion_proof() == promotion, 'Promotion provenance changed')
    result = create_draft(receipt, bundle / 'release-notes.txt')
    result['promotion'] = promotion
    (args.work_dir / 'draft-verification.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf8')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()

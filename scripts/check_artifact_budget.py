"""Read-only, fail-closed repository artifact budget gate before uploading."""
from __future__ import annotations
import argparse
import json
import math
import os
from pathlib import Path
from urllib.request import Request, urlopen

REPOSITORY = 'Junming-Liang/vga-aram-helper'
BUDGET_BYTES = 500_000_000
RESERVE_BYTES = 10_000_000


def fetch_json(url):
    request = Request(url, headers={'Accept': 'application/vnd.github+json', 'User-Agent': 'VGA-build-budget-check'})
    # Public repository metadata only; no credential is read or transmitted.
    with urlopen(request, timeout=20) as response:
        data = response.read(5 * 1024 * 1024 + 1)
    if len(data) > 5 * 1024 * 1024:
        raise RuntimeError('Artifact listing exceeded size limit')
    return json.loads(data)


def check_budget(root, repository=REPOSITORY, fetcher=fetch_json, *, evidence_only=False):
    if repository != REPOSITORY:
        raise RuntimeError('Unexpected repository for artifact budget')
    existing = 0
    listed = 0
    for page in range(1, 11):
        value = fetcher(f'https://api.github.com/repos/{REPOSITORY}/actions/artifacts?per_page=100&page={page}')
        artifacts = value.get('artifacts')
        if not isinstance(artifacts, list) or type(value.get('total_count')) is not int:
            raise RuntimeError('Invalid artifact inventory; refusing upload')
        for artifact in artifacts:
            size = artifact.get('size_in_bytes')
            if type(size) is not int or size < 0 or type(artifact.get('expired')) is not bool:
                raise RuntimeError('Invalid artifact size/state')
            if not artifact['expired']:
                existing += size
        listed += len(artifacts)
        if listed >= value['total_count']:
            break
        if not artifacts:
            raise RuntimeError('Incomplete artifact listing')
    else:
        raise RuntimeError('Artifact listing limit reached')
    root = Path(root)
    release = 0 if evidence_only else sum(path.stat().st_size for path in (root / 'dist' / 'release').glob('*') if path.is_file())
    evidence = sum(path.stat().st_size for path in (root / 'reports').glob('windows-*') if path.is_file())
    genuine_report = root / 'reports' / 'hero-recognition-genuine.json'
    if genuine_report.is_file():
        evidence += genuine_report.stat().st_size
    if not evidence_only and release <= 0:
        raise RuntimeError('Release artifact is missing')
    # Conservative archive headers/compression overhead plus room for evidence.
    proposed = math.ceil((release + evidence) * 1.03) + 1_000_000
    report = {'existing_repository_artifact_bytes': existing, 'proposed_upper_estimate_bytes': proposed,
              'projected_bytes': existing + proposed, 'project_budget_bytes': BUDGET_BYTES,
              'reserve_bytes': RESERVE_BYTES, 'upload_scope': 'evidence-only' if evidence_only else 'release-and-evidence',
              'scope': 'This repository only; not a claim about other account/repository storage usage.'}
    report['status'] = 'passed' if report['projected_bytes'] <= BUDGET_BYTES - RESERVE_BYTES else 'blocked'
    (root / 'reports').mkdir(exist_ok=True)
    (root / 'reports' / 'windows-artifact-budget.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    if report['status'] != 'passed':
        raise RuntimeError('Artifact budget would be exceeded; no new executable artifact may be uploaded')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--evidence-only', action='store_true', help='Use only when no EXE/source Actions artifact will be uploaded')
    args = parser.parse_args()
    print(json.dumps(check_budget(Path(__file__).resolve().parents[1], os.environ.get('GITHUB_REPOSITORY', REPOSITORY),
                                 evidence_only=args.evidence_only), indent=2))

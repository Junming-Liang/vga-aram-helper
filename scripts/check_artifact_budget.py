"""Read-only, fail-closed repository artifact budget gate before uploading."""
from __future__ import annotations
import argparse
import json
import math
import os
import re
from pathlib import Path
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError, URLError

REPOSITORY = 'Junming-Liang/vga-aram-helper'
BUDGET_BYTES = 500_000_000
RESERVE_BYTES = 10_000_000


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError('Artifact inventory redirect refused')


def fetch_json(url):
    # The existing job token is exposed only to this read-only budget step.
    # Exact URL validation happens before reading it; never forward to redirects.
    endpoint = f'https://api.github.com/repos/{REPOSITORY}/actions/artifacts?per_page=100&page='
    if not isinstance(url, str) or not re.fullmatch(re.escape(endpoint) + r'(?:[1-9]|10)', url):
        raise RuntimeError('Unexpected artifact inventory endpoint')
    headers = {'Accept': 'application/vnd.github+json', 'User-Agent': 'VGA-build-budget-check'}
    token = os.environ.get('VGA_ARTIFACT_READ_TOKEN', '')
    if token:
        if len(token) > 4096 or any(ord(char) < 33 or ord(char) > 126 for char in token):
            raise RuntimeError('Invalid artifact inventory authentication')
        headers['Authorization'] = 'Bearer ' + token
    request = Request(url, headers=headers, method='GET')
    try:
        with build_opener(NoRedirect()).open(request, timeout=20) as response:
            data = response.read(5 * 1024 * 1024 + 1)
    except HTTPError as exc:
        raise RuntimeError('Artifact inventory HTTP failure: ' + str(exc.code)) from None
    except (URLError, OSError):
        raise RuntimeError('Artifact inventory transport failure') from None
    if len(data) > 5 * 1024 * 1024:
        raise RuntimeError('Artifact listing exceeded size limit')
    return json.loads(data)


def check_budget(root, repository=REPOSITORY, fetcher=fetch_json, *, evidence_only=False, output_path=None):
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
    for report_name in ('hero-recognition-genuine.json', 'champion-select-genuine.json'):
        genuine_report = root / 'reports' / report_name
        if genuine_report.is_file():
            evidence += genuine_report.stat().st_size
    if not evidence_only and release <= 0:
        raise RuntimeError('Release artifact is missing')
    # Full candidate uploads contain the evidence ZIP and its separately exposed
    # original screenshot. Also count the existing small-evidence upload again:
    # the remote inventory may not yet reflect that upload. The 1 MB allowance
    # covers bounded staging receipts/notes; 3% remains for archive overhead.
    screenshot = root / 'reports' / 'windows-native-overlay.png'
    extra_screenshot = screenshot.stat().st_size if not evidence_only and screenshot.is_file() else 0
    counted_evidence = evidence if evidence_only else 2 * evidence
    proposed = math.ceil((release + counted_evidence + extra_screenshot) * 1.03) + 1_000_000
    report = {'existing_repository_artifact_bytes': existing, 'proposed_upper_estimate_bytes': proposed,
              'projected_bytes': existing + proposed, 'project_budget_bytes': BUDGET_BYTES,
              'reserve_bytes': RESERVE_BYTES, 'upload_scope': 'evidence-only' if evidence_only else 'release-and-evidence',
              'scope': 'This repository only; not a claim about other account/repository storage usage.'}
    report['status'] = 'passed' if report['projected_bytes'] <= BUDGET_BYTES - RESERVE_BYTES else 'blocked'
    output = Path(output_path) if output_path is not None else root / 'reports' / 'windows-artifact-budget.json'
    if output_path is not None and not output.is_absolute():
        output = root / output
    if output.is_symlink():
        raise RuntimeError('Artifact budget output cannot be a symlink')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    if report['status'] != 'passed':
        raise RuntimeError('Artifact budget would be exceeded; no new executable artifact may be uploaded')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--evidence-only', action='store_true', help='Estimate the small-evidence upload only; any EXE/source upload needs a separate full gate')
    parser.add_argument('--output', type=Path, help='Write a separate budget report without replacing already-verified evidence')
    args = parser.parse_args()
    print(json.dumps(check_budget(Path(__file__).resolve().parents[1], os.environ.get('GITHUB_REPOSITORY', REPOSITORY),
                                 evidence_only=args.evidence_only, output_path=args.output), indent=2))

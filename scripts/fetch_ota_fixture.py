"""Fetch the exact owned prerelease EXE for a separate read-only OTA test job.

This does not discover or promote a release. It uses the production HTTPS/PE/hash
download checks and a source-pinned public asset; no URL override is accepted.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from updates import _download_exe, _verify_exe, validate_manifest

FIXTURE_SOURCE_COMMIT = '1ce516e967bbe153fa1dcf6e8289abf86185f04c'
FIXTURE_MANIFEST = {
    'schema_version': 1, 'version': '0.3.0', 'platform': 'windows-x64',
    'url': 'https://github.com/Junming-Liang/vga-aram-helper/releases/download/v0.3.0/vga-aram-helper-0.3.0-windows-x64.exe',
    'sha256': '40b8d2af8309278b9cf6a5eace8ca26d6a483f659578d441636b86369d66cf6e',
    'size': 150155259,
}


def fetch_fixture(output, *, downloader=None):
    output = Path(output)
    if output.exists() or output.is_symlink():
        raise RuntimeError('OTA fixture output already exists; refusing overwrite')
    output = output.absolute()
    manifest = validate_manifest(FIXTURE_MANIFEST, tag='v0.3.0')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='ota-fixture-', dir=output.parent) as temporary:
        staged = Path(temporary) / 'candidate.bin'
        (downloader or _download_exe)(manifest, staged)
        _verify_exe(staged, manifest)
        # Hard-link creation is exclusive: never replace a concurrently created
        # destination. Both paths are on the same generated build volume.
        os.link(staged, output)
    return {'fixture_source_commit': FIXTURE_SOURCE_COMMIT, 'manifest': manifest,
            'scope': 'Exact published same-version test fixture; not stable-release discovery or a two-version upgrade.'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=ROOT / 'build' / 'ota-fixture' / 'VGA-Aram-Helper.exe')
    args = parser.parse_args()
    print(json.dumps(fetch_fixture(args.output), indent=2))


if __name__ == '__main__':
    main()

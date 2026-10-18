"""Retain only an already verified candidate; never build, publish or authenticate."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app_version import __version__
REPOSITORY = 'Junming-Liang/vga-aram-helper'
MAX_METADATA_BYTES = 1_000_000


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''): h.update(block)
    return h.hexdigest()


def expected_names(version):
    return {f'vga-aram-helper-{version}-windows-x64.exe', 'update-manifest.json', 'SHA256SUMS.txt',
            'third-party-licenses.zip', 'WINDOWS_EXECUTABLE.md', 'THIRD_PARTY_NOTICES.md',
            'LICENSE', 'source-access.json', f'vga-aram-helper-{version}-source.zip',
            f'windows-test-evidence-{version}.zip', 'windows-native-overlay.png',
            *(f'{part}-everywhere-src-6.11.2.tar.xz' for part in
              ('pyside-setup', 'qtbase', 'qtsvg', 'qtimageformats'))}


def owned_file(path, root):
    path = Path(path).absolute()
    try: relative = path.relative_to(root)
    except ValueError: raise RuntimeError('Candidate source lies outside checkout') from None
    cursor = root
    for component in relative.parts:
        if component in ('.', '..'): raise RuntimeError('Invalid candidate path')
        cursor /= component
        if cursor.is_symlink(): raise RuntimeError('Candidate symlink rejected')
    if not path.is_file(): raise RuntimeError('Candidate file missing')
    return path


def stage(verified_dir, output_dir, source_sha, run_id, run_attempt, *, root=ROOT):
    root = Path(root).resolve(); verified_dir = Path(verified_dir).absolute()
    output_dir = Path(output_dir).absolute()
    if not re.fullmatch(r'[0-9a-f]{40}', source_sha) or type(run_id) is not int or run_id <= 0 or type(run_attempt) is not int or run_attempt <= 0:
        raise RuntimeError('Invalid expected run identity')
    receipt = owned_file(verified_dir / 'verified-release.json', root)
    notes = owned_file(verified_dir / 'release-notes.txt', root)
    if receipt.stat().st_size + notes.stat().st_size > MAX_METADATA_BYTES:
        raise RuntimeError('Candidate metadata exceeds reserved budget')
    value = json.loads(receipt.read_text(encoding='utf8'))
    if not isinstance(value, dict) or any(value.get(k) != v for k, v in
            (('repository', REPOSITORY), ('version', __version__), ('tag', 'v' + __version__),
             ('source_sha', source_sha), ('run_id', run_id), ('run_attempt', run_attempt))):
        raise RuntimeError('Verified candidate identity mismatch')
    rows = value.get('assets')
    names = expected_names(__version__)
    if not isinstance(rows, list) or len(rows) != len(names) or {r.get('name') for r in rows if isinstance(r, dict)} != names:
        raise RuntimeError('Verified candidate asset inventory mismatch')
    validated = []
    for row in rows:
        name = row['name']; path = owned_file(row['path'], root)
        parent = (verified_dir if name.startswith('windows-test-evidence-') else
                  root / 'reports' if name == 'windows-native-overlay.png' else root / 'dist' / 'release')
        if path != parent / name or type(row.get('size')) is not int or row['size'] <= 0 or path.stat().st_size != row['size'] or digest(path) != row.get('sha256'):
            raise RuntimeError('Verified asset path, size or hash changed')
        if name == f'vga-aram-helper-{__version__}-windows-x64.exe' and (row['sha256'] != value.get('exe_sha256') or row['size'] != value.get('exe_size')):
            raise RuntimeError('Executable is not the exact tested asset')
        validated.append((row, path))
    # Never clobber a prior staged candidate or follow an output-directory link.
    try: relative = output_dir.relative_to(root)
    except ValueError: raise RuntimeError('Candidate output lies outside checkout') from None
    cursor = root
    for component in relative.parts:
        if component in ('.', '..'): raise RuntimeError('Invalid candidate output')
        cursor /= component
        if cursor.is_symlink(): raise RuntimeError('Candidate output symlink rejected')
    if output_dir.exists(): raise RuntimeError('Candidate output already exists')
    # Bound the bytes actually retained, including JSON escaping/formatting.
    value['assets'] = [{**row, 'path': row['name']} for row, _ in validated]
    serialized = (json.dumps(value, indent=2) + '\n').encode('utf8')
    with notes.open('rb') as f: notes_bytes = f.read(MAX_METADATA_BYTES + 1)
    if len(serialized) + len(notes_bytes) > MAX_METADATA_BYTES:
        raise RuntimeError('Serialized candidate metadata exceeds reserved budget')
    output_dir.mkdir(parents=True)
    for row, path in validated:
        target = output_dir / row['name']; shutil.copyfile(path, target)
        if target.stat().st_size != row['size'] or digest(target) != row['sha256']:
            raise RuntimeError('Staged copy differs from tested asset')
    # Portable receipt: all retained asset paths are basenames, no runner paths.
    (output_dir / 'verified-release.json').write_bytes(serialized)
    (output_dir / 'release-notes.txt').write_bytes(notes_bytes)
    if digest(output_dir / 'release-notes.txt') != hashlib.sha256(notes_bytes).hexdigest(): raise RuntimeError('Staged notes changed')
    return {'source_sha': source_sha, 'run_id': run_id, 'run_attempt': run_attempt,
            'version': __version__, 'exe_sha256': value['exe_sha256'], 'exe_size': value['exe_size'],
            'asset_count': len(rows), 'staged_bytes': sum(p.stat().st_size for p in output_dir.iterdir())}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--verified-dir', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--source-sha', required=True)
    parser.add_argument('--run-id', type=int, required=True)
    parser.add_argument('--run-attempt', type=int, required=True)
    a = parser.parse_args()
    print(json.dumps(stage(a.verified_dir, a.output_dir, a.source_sha, a.run_id, a.run_attempt), indent=2))


if __name__ == '__main__': main()

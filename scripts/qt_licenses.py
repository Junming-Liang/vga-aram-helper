"""Validate exact Qt notices and supply matching public source archives."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import shutil
import time
from urllib.parse import urlsplit
from urllib.request import urlopen

QT_VERSION = '6.11.2'
PROJECTS = {'pyside-setup', 'qtbase', 'qtsvg', 'qtimageformats'}


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def verify_bundle(source):
    source = Path(source).resolve()
    data = json.loads((source / 'PROVENANCE.json').read_text(encoding='utf-8'))
    if data.get('schema_version') != 1 or data.get('upstream_version') != QT_VERSION:
        raise RuntimeError('Qt notice provenance version mismatch')
    archives = data.get('archives', [])
    if {entry.get('project') for entry in archives} != PROJECTS or len(archives) != 4:
        raise RuntimeError('Qt source archive inventory is incomplete')
    for entry in archives:
        parsed = urlsplit(entry['url'])
        if (parsed.scheme != 'https' or parsed.netloc != 'download.qt.io' or parsed.query or parsed.fragment
                or not parsed.path.startswith('/official_releases/')
                or Path(parsed.path).name != entry['upstream_filename']
                or QT_VERSION not in entry['upstream_filename']
                or entry.get('sha256_verified_against_official_sidecar') is not True
                or not 0 < entry.get('size', 0) < 80_000_000):
            raise RuntimeError('Unexpected Qt source archive provenance')
    seen = set()
    for entry in data.get('files', []):
        relative = entry['path']
        path = (source / relative).resolve()
        if path == source or source not in path.parents or relative in seen:
            raise RuntimeError('Invalid or duplicate Qt license path')
        if not path.is_file() or path.stat().st_size != entry['size'] or digest(path) != entry['sha256']:
            raise RuntimeError('Qt license file missing or changed: ' + relative)
        seen.add(relative)
    required = {'pyside-setup/LICENSES/LGPL-3.0-only.txt', 'pyside-setup/LICENSES/GPL-3.0-only.txt'}
    if not required <= seen or len(seen) < 100:
        raise RuntimeError('Incomplete Qt license inventory')
    for name in ('NOTICE.txt', 'SOURCE_AND_RELINKING.txt', 'ATTRIBUTIONS.json'):
        if not (source / name).is_file():
            raise RuntimeError('Qt licensing entry point missing: ' + name)
    return data


def copy_bundle(source, destination):
    data = verify_bundle(source)
    target = Path(destination) / 'qt-licenses'
    shutil.copytree(source, target, dirs_exist_ok=True)
    files = [str(path.relative_to(destination)).replace('\\', '/')
             for path in sorted(target.rglob('*')) if path.is_file()]
    return data, files


def supply_sources(source, destination, opener=urlopen):
    """Download official nonexecutable sources only; bounded bytes, exact hash."""
    data = verify_bundle(source)
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + 240
    for entry in data['archives']:
        target = destination / entry['upstream_filename']
        temporary = target.with_suffix(target.suffix + '.partial')
        try:
            with opener(entry['url'], timeout=45) as response, temporary.open('wb') as output:
                remaining = entry['size']
                while remaining:
                    if time.monotonic() > deadline:
                        raise RuntimeError('Qt source download exceeded total time budget')
                    chunk = response.read(min(1024 * 1024, remaining))
                    if not chunk:
                        raise RuntimeError('Truncated Qt source archive')
                    output.write(chunk)
                    remaining -= len(chunk)
                if response.read(1):
                    raise RuntimeError('Qt source archive exceeded declared size')
            if digest(temporary) != entry['sha256']:
                raise RuntimeError('Qt source archive SHA-256 mismatch')
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
    return [{'filename': entry['upstream_filename'], 'size': entry['size'],
             'sha256': entry['sha256'], 'url': entry['url']} for entry in data['archives']]

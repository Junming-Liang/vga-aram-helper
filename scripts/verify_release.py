"""Verify fresh same-job native Windows evidence, then optionally publish a prerelease.

This helper never reads or prints credentials. gh alone consumes GH_TOKEN supplied
by the final workflow step. An existing tag/release is never updated or replaced.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import struct
import sys
import zlib
import zipfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.microsoft_runtime import verify_runtime_evidence, verify_notice_archive

REPOSITORY = 'Junming-Liang/vga-aram-helper'
PREVIEW_VERSION = '0.3.0'
PREVIEW_WORKFLOW = '.github/workflows/build-native-preview.yml'

BROWSER_CHECK = 'Actual EXE Chromium UI: hero + 3 slots, switch hero, recompute, clear round; screenshot saved'
COMPARE_CHECK = 'Frozen comparison API: same three slots produce different hero-specific priorities'
OCR_CHECK = 'Actual bundled ONNX inference: Chinese fixture 3/3; blank fixture 0; all model SHA256 match'
MODEL_HASHES = {
    'PP-OCRv6_det_small.onnx': '090f04abcd9d9a7498bc4ebf677e4cb9bdce1fe4197ddb7e529f1ef44e1ff94f',
    'PP-OCRv6_rec_small.onnx': '6f327246b50388f3c176ae304bd95767ea6dc0c9ae92153ef8cbe210b3c14884',
    'ch_ppocr_mobile_v2.0_cls_mobile.onnx': 'e47acedf663230f8863ff1ab0e64dd2d82b838fceb5957146dab185a89d6215c',
}
EVIDENCE_NAMES = ('windows-build.json', 'windows-exe-smoke.json', 'windows-exe-self-test.json',
                  'windows-exe-ui.png', 'windows-exe-self-test.log', 'windows-exe-server.log',
                  'windows-build-environment.txt', 'windows-native-smoke.json',
                  'windows-native-overlay.json', 'windows-native-overlay.png',
                  'windows-native-process.log', 'windows-artifact-budget.json')
QT_VERSION = '6.11.2'
PSL_SOURCE_URL = 'https://raw.githubusercontent.com/publicsuffix/list/e452c7058d6946bd76952b128c12f5ce87a5acb8/public_suffix_list.dat'
PSL_SOURCE_SHA256 = '5c75b7ea88e26f7940a888a34872345cb85c9484a4d0056c4063525d8c8aa184'
QT_RUNTIME_DLLS = {'qt6core.dll', 'qt6gui.dll', 'qt6widgets.dll', 'qwindows.dll'}
# Proprietary Microsoft release runtimes, reviewed separately from Qt LGPL
# sources. Only these observed dependency names are eligible; no debug/runtime
# prefix wildcard is permitted. Their notice and original bytes are checked too.
MICROSOFT_RUNTIME_DLLS = {'msvcp140.dll', 'msvcp140_1.dll', 'msvcp140_2.dll',
                          'vcruntime140.dll', 'vcruntime140_1.dll'}
RUNTIME_DLLS = {'python312.dll', 'vcruntime140.dll', 'vcruntime140_1.dll', 'msvcp140.dll'} | QT_RUNTIME_DLLS
QT_NOTICE_FILES = ('qt-licenses/NOTICE.txt', 'qt-licenses/SOURCE_AND_RELINKING.txt',
                   'qt-licenses/PROVENANCE.json',
                   'qt-licenses/qtbase/src/3rdparty/libpsl/PSL-LICENSE.txt',
                   'qt-licenses/qtbase/src/3rdparty/libpsl/src/LICENSE.chromium',
                   'qt-licenses/pyside-setup/LICENSES/LGPL-3.0-only.txt',
                   'qt-licenses/pyside-setup/LICENSES/GPL-3.0-only.txt')

QT_SOURCES = [{'filename': 'pyside-setup-everywhere-src-6.11.2.tar.xz',
  'size': 18053248,
  'sha256': 'cba47efbaad1bedd529725cbc14e21f156c7a19366f07b3edfbb076ffd7afdf8',
  'url': 'https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-6.11.2-src/pyside-setup-everywhere-src-6.11.2.tar.xz'},
 {'filename': 'qtbase-everywhere-src-6.11.2.tar.xz',
  'size': 50582668,
  'sha256': '5b2e00eccaf5a4d8c14134ffa0ea8dfd0a35ae1ffc7f8d87fa4305a1ed23cf22',
  'url': 'https://download.qt.io/official_releases/qt/6.11/6.11.2/submodules/qtbase-everywhere-src-6.11.2.tar.xz'},
 {'filename': 'qtsvg-everywhere-src-6.11.2.tar.xz',
  'size': 2341860,
  'sha256': 'd594337feca84c26fb67fe87b85e6a5c12fda404b611d905f9d138210c311876',
  'url': 'https://download.qt.io/official_releases/qt/6.11/6.11.2/submodules/qtsvg-everywhere-src-6.11.2.tar.xz'},
 {'filename': 'qtimageformats-everywhere-src-6.11.2.tar.xz',
  'size': 2050424,
  'sha256': 'cecd8900f34b6550076309bc94f62f828008b633a4239e0a08c86788f41001f8',
  'url': 'https://download.qt.io/official_releases/qt/6.11/6.11.2/submodules/qtimageformats-everywhere-src-6.11.2.tar.xz'}]
BASELINE_CHECKS = {
    'Standalone version command without Python/site-packages on PATH',
    'Embedded third-party license texts readable from EXE',
    'Frozen HTTP server: readiness, loopback UI/assets, CSP and synthetic data',
    'Frozen HTTP OCR API recognizes original demo fixture with bundled models',
    BROWSER_CHECK, COMPARE_CHECK, OCR_CHECK,
}


class VerificationError(RuntimeError):
    pass


def require(condition, message):
    if not condition:
        raise VerificationError(message)


def digest(path):
    with Path(path).open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def checked_file(path, allow_empty=False):
    path = Path(path)
    require(path.is_file() and not path.is_symlink(), f'Missing or symlinked release input: {path.name}')
    require((0 if allow_empty else 1) <= path.stat().st_size <= 512 * 1024 * 1024, f'Invalid release input size: {path.name}')
    return path


def read_json(path):
    checked_file(path)
    require(path.stat().st_size < 5 * 1024 * 1024, f'JSON exceeds size limit: {path.name}')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 'Duplicate JSON key')
            result[key] = value
        return result
    return json.loads(path.read_text(encoding='utf-8-sig'), object_pairs_hook=unique)


def evidence_file(folder, name):
    # upload-artifact can preserve reports/ when the warning-log path shares
    # the repository as common parent. Accept only these two exact layouts.
    candidates = [folder / name, folder / 'reports' / name]
    matches = [path for path in candidates if path.is_file()]
    require(len(matches) == 1, f'Missing or ambiguous evidence: {name}')
    return checked_file(matches[0], allow_empty=name.endswith('.log'))


def verify_png(path):
    """Verify a bounded non-interlaced 8-bit RGB/RGBA screenshot without Pillow."""
    require(path.stat().st_size <= 32 * 1024 * 1024, 'PNG screenshot exceeds size limit')
    data = path.read_bytes()
    require(data.startswith(b'\x89PNG\r\n\x1a\n'), 'Invalid PNG signature')
    offset, header, ended, idat_closed = 8, None, False, False
    compressed = bytearray()
    while offset < len(data):
        require(offset + 12 <= len(data), 'Truncated PNG chunk')
        size = struct.unpack('>I', data[offset:offset + 4])[0]
        kind = data[offset + 4:offset + 8]
        require(all(65 <= byte <= 90 or 97 <= byte <= 122 for byte in kind) and not kind[2] & 32,
                'Invalid PNG chunk type')
        require(offset + 12 + size <= len(data), 'Truncated PNG payload')
        payload = data[offset + 8:offset + 8 + size]
        crc = struct.unpack('>I', data[offset + 8 + size:offset + 12 + size])[0]
        require(zlib.crc32(kind + payload) & 0xffffffff == crc, 'PNG chunk CRC mismatch')
        if header is None:
            require(kind == b'IHDR' and size == 13, 'PNG must start with IHDR')
            header = struct.unpack('>IIBBBBB', payload)
            width, height, depth, color, compression, filtering, interlace = header
            require(1 <= width <= 8192 and 1 <= height <= 8192 and depth == 8 and
                    color in (2, 6) and compression == filtering == interlace == 0,
                    'Unsupported screenshot dimensions/PNG encoding')
            channels = 3 if color == 2 else 4
            expected = height * (1 + width * channels)
            require(expected <= 64 * 1024 * 1024, 'Decoded PNG exceeds size limit')
        elif kind == b'IDAT':
            require(not idat_closed, 'PNG IDAT chunks are not contiguous')
            compressed.extend(payload)
        elif kind == b'IEND':
            require(size == 0 and compressed, 'PNG image data/end missing')
            ended = True
            offset += 12
            break
        else:
            require(kind != b'IHDR' and (kind[0] & 32 or kind == b'PLTE'), 'Unknown or duplicate critical PNG chunk')
            if compressed:
                idat_closed = True
        offset += 12 + size
    require(ended and offset == len(data), 'Missing PNG end or trailing data')
    try:
        decoder = zlib.decompressobj()
        pixels = decoder.decompress(bytes(compressed), expected + 1)
    except zlib.error as error:
        raise VerificationError('Invalid PNG compressed pixels') from error
    require(len(pixels) == expected and decoder.eof and not decoder.unused_data and
            not decoder.unconsumed_tail, 'PNG pixel stream length mismatch')
    stride = 1 + width * channels
    require(all(pixels[row * stride] <= 4 for row in range(height)), 'Invalid PNG row filter')


def verify_budget(budget, release_dir, evidence):
    require(budget.get('status') == 'passed' and 'error' not in budget and
            budget.get('upload_scope') == 'evidence-only', 'Evidence-only artifact budget gate did not pass')
    keys = ('existing_repository_artifact_bytes', 'proposed_upper_estimate_bytes',
            'projected_bytes', 'project_budget_bytes', 'reserve_bytes')
    require(all(type(budget.get(key)) is int and budget[key] >= 0 for key in keys), 'Invalid artifact budget numbers')
    require(budget['project_budget_bytes'] == 500_000_000 and budget['reserve_bytes'] == 10_000_000,
            'Artifact budget/reserve differs from approved limit')
    require(budget['projected_bytes'] == budget['existing_repository_artifact_bytes'] + budget['proposed_upper_estimate_bytes'] and
            budget['projected_bytes'] <= budget['project_budget_bytes'] - budget['reserve_bytes'],
            'Artifact budget arithmetic or capacity check failed')
    # EXE/source files go directly to Releases, never duplicate Actions storage.
    measured = sum(path.stat().st_size for name, path in evidence.items() if name != 'windows-artifact-budget.json')
    require(budget['proposed_upper_estimate_bytes'] >= measured, 'Artifact budget underestimates uploaded evidence')


def verify_qt_licenses(archive, build):
    names = archive.namelist()
    require(len(names) == len(set(names)), 'Ambiguous duplicate entries in license archive')
    require(sum(row.file_size for row in archive.infolist()) <= 64 * 1024 * 1024, 'License archive expands beyond limit')
    require(archive.testzip() is None and names, 'Invalid license archive')
    for name in QT_NOTICE_FILES:
        require(name in names and archive.getinfo(name).file_size > 0, 'Missing Qt license/source notice: ' + name)
    archived = json.loads(archive.read('dependency-inventory.json')) if 'dependency-inventory.json' in names else None
    require(archived == build.get('dependencies') and isinstance(archived, list), 'License and build dependency inventories differ')
    for package in ('pyside6_essentials', 'shiboken6'):
        rows = [row for row in archived if str(row.get('name', '')).casefold().replace('-', '_') == package]
        require(len(rows) == 1 and rows[0].get('version') == QT_VERSION, 'Missing/wrong Qt dependency version: ' + package)
        paths = rows[0].get('license_files')
        require(isinstance(paths, list) and paths, 'Empty Qt dependency license inventory: ' + package)
        for path in paths:
            require(isinstance(path, str), 'Invalid license inventory path')
            name = path.replace('\\', '/')
            require(name in names and archive.getinfo(name).file_size > 0, 'Qt dependency license file is missing')
    provenance = json.loads(archive.read('qt-licenses/PROVENANCE.json'))
    require(provenance.get('schema_version') == 1 and provenance.get('upstream_version') == QT_VERSION,
            'Qt notice provenance/version mismatch')
    rows = provenance.get('files')
    require(isinstance(rows, list) and rows, 'Qt notice provenance has no files')
    seen = set()
    for row in rows:
        name = 'qt-licenses/' + row.get('path', '')
        require(name not in seen and name in names, 'Missing/duplicate Qt provenance file')
        seen.add(name)
        data = archive.read(name)
        require(len(data) == row.get('size') and hashlib.sha256(data).hexdigest() == row.get('sha256'),
                'Qt notice provenance checksum mismatch')
    sources = archive.read('qt-licenses/SOURCE_AND_RELINKING.txt').decode('utf-8')
    require('SOURCE' in sources.upper() and 'RELINK' in sources.upper() and
            'https://download.qt.io/official_releases/' in sources,
            'Qt corresponding-source/relinking access notice missing')
    require(PSL_SOURCE_URL in sources and PSL_SOURCE_SHA256 in sources,
            'Exact preferred-form MPL Public Suffix List source access is missing')


def verify_source_access(release_dir, build, source_sha, version):
    path = checked_file(release_dir / 'source-access.json')
    access = read_json(path)
    require(access == build.get('source_access') and access.get('source_commit') == source_sha,
            'Build/source-access identity mismatch')
    expected = {row['filename']: row for row in QT_SOURCES}
    sources = access.get('qt_sources')
    require(isinstance(sources, list) and len(sources) == len(expected) and
            {row.get('filename'): row for row in sources} == expected,
            'Qt corresponding-source inventory differs from pinned official archives')
    app = access.get('application_source')
    require(isinstance(app, dict) and app.get('filename') == f'vga-aram-helper-{version}-source.zip',
            'Application source archive name/version mismatch')
    assets = [path]
    for row in [app, *sources]:
        archive_path = checked_file(release_dir / row['filename'])
        require(type(row.get('size')) is int and archive_path.stat().st_size == row['size'] and
                digest(archive_path) == row.get('sha256'), 'Corresponding-source archive size/hash mismatch')
        assets.append(archive_path)
    with zipfile.ZipFile(assets[1]) as archive:
        require(archive.comment == source_sha.encode('ascii'), 'Application git archive commit differs from tested SHA')
        require(sum(row.file_size for row in archive.infolist()) <= 256 * 1024 * 1024 and
                len(archive.namelist()) <= 10000, 'Application source archive exceeds limits')
        require(archive.testzip() is None, 'Corrupt application source archive')
        require({'launcher.py', 'native_ui.py', 'native_smoke.py', 'requirements-build.txt',
                 'scripts/build_windows.py', 'packaging/VGA-Aram-Helper.spec'} <= set(archive.namelist()),
                'Application source archive lacks native packaging inputs')
    return assets


def verify_qt_runtime(binaries):
    """Reject any DLL/plugin outside the separately reviewed component inventory."""
    paths = {name.replace('\\', '/').casefold() for name in binaries}
    require(len(paths) == len(binaries), 'Duplicate Qt runtime paths')
    allowed_dlls = {'qt6core.dll', 'qt6gui.dll', 'qt6widgets.dll', 'qt6svg.dll', 'qt6network.dll', 'pyside6.abi3.dll'}
    allowed_bindings = {'qtcore.pyd', 'qtgui.pyd', 'qtwidgets.pyd', 'qtsvg.pyd', 'qtnetwork.pyd'}
    plugins = {
        'platforms': {'qwindows.dll', 'qminimal.dll', 'qoffscreen.dll', 'qdirect2d.dll'},
        'iconengines': {'qsvgicon.dll'},
        'styles': {'qmodernwindowsstyle.dll', 'qwindowsvistastyle.dll'},
        'tls': {'qcertonlybackend.dll', 'qschannelbackend.dll'},
        'networkinformation': {'qnetworklistmanager.dll'},
        'imageformats': {'qgif.dll', 'qico.dll', 'qjpeg.dll', 'qsvg.dll', 'qicns.dll',
                         'qtga.dll', 'qtiff.dll', 'qwbmp.dll', 'qwebp.dll', 'qdds.dll'},
    }
    for path in paths:
        require(not path.startswith('/') and '..' not in path.split('/'), 'Unsafe Qt archive path')
        if path.startswith('pyside6/'):
            relative = path.removeprefix('pyside6/')
        else:
            relative = path
        if path.startswith('pyside6/') and relative in MICROSOFT_RUNTIME_DLLS:
            continue
        if relative in allowed_dlls or relative in allowed_bindings:
            continue
        plugin_path = relative.removeprefix('qt/')
        parts = plugin_path.split('/')
        require(len(parts) == 3 and parts[0] == 'plugins' and
                parts[1] in plugins and parts[2] in plugins[parts[1]],
                'Qt runtime/plugin is outside reviewed source coverage: ' + path)
    require(QT_RUNTIME_DLLS <= {name.rsplit('/', 1)[-1] for name in paths},
            'Required Qt DLL/plugin absent from archive')
    return paths


def verify_run_provenance(repository, source_sha, run_id, run_attempt):
    """GET-only authenticated identity check for this still-running publishing job."""
    require(repository == REPOSITORY and re.fullmatch(r'[0-9a-f]{40}', source_sha) and
            type(run_id) is int and run_id > 0 and type(run_attempt) is int and run_attempt > 0, 'Invalid current workflow identity')
    run = gh_api(f'repos/{REPOSITORY}/actions/runs/{run_id}')
    require(type(run.get('id')) is int and run['id'] == run_id and type(run.get('run_attempt')) is int and
            run['run_attempt'] == run_attempt and run.get('status') == 'in_progress' and
            'conclusion' in run and run['conclusion'] is None and run.get('event') == 'workflow_dispatch' and
            run.get('head_branch') == 'main' and run.get('head_sha') == source_sha and
            run.get('path') == PREVIEW_WORKFLOW,
            'Current run is not the approved active main native-preview dispatch')
    repository_data, head_repository = run.get('repository', {}), run.get('head_repository', {})
    require(repository_data.get('full_name') == REPOSITORY and repository_data.get('private') is False and
            head_repository.get('full_name') == REPOSITORY and
            type(repository_data.get('id')) is int and repository_data['id'] > 0 and
            head_repository.get('id') == repository_data['id'], 'Current run repository/fork identity mismatch')
    return {'repository': REPOSITORY, 'run_id': run_id, 'run_attempt': run_attempt, 'source_sha': source_sha,
            'workflow': PREVIEW_WORKFLOW, 'event': 'workflow_dispatch', 'branch': 'main'}


def check_runner_context(repository, source_sha, run_id, run_attempt):
    """Read only nonsecret workflow context; never inspect credential variables."""
    expected = {'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': repository, 'GITHUB_SHA': source_sha,
                'GITHUB_RUN_ID': str(run_id), 'GITHUB_RUN_ATTEMPT': str(run_attempt), 'GITHUB_REF': 'refs/heads/main',
                'GITHUB_EVENT_NAME': 'workflow_dispatch',
                'GITHUB_WORKFLOW_REF': f'{REPOSITORY}/{PREVIEW_WORKFLOW}@refs/heads/main'}
    require(all(os.environ.get(key) == value for key, value in expected.items()),
            'Publication must run in this exact approved GitHub workflow context')


def check_preview_identity(verified, provenance):
    require(isinstance(provenance, dict) and provenance.get('repository') == REPOSITORY and
            provenance.get('workflow') == PREVIEW_WORKFLOW and provenance.get('event') == 'workflow_dispatch' and
            provenance.get('branch') == 'main' and type(provenance.get('run_id')) is int and provenance['run_id'] > 0 and
            type(provenance.get('run_attempt')) is int and provenance['run_attempt'] > 0,
            'Missing authenticated current-run provenance')
    require(verified.get('source_sha') == provenance.get('source_sha') and
            verified.get('run_id') == provenance['run_id'] and verified.get('run_attempt') == provenance['run_attempt'] and verified.get('version') == PREVIEW_VERSION and
            verified.get('tag') == 'v' + PREVIEW_VERSION and
            isinstance(verified.get('exe_sha256'), str) and re.fullmatch(r'[0-9a-f]{64}', verified['exe_sha256']) and
            type(verified.get('exe_size')) is int and verified['exe_size'] > 0,
            'Preview source/run/version/EXE identity differs from the fresh tested build')
    matches = [asset for asset in verified.get('assets', [])
               if asset.get('name') == f'vga-aram-helper-{PREVIEW_VERSION}-windows-x64.exe']
    require(len(matches) == 1 and matches[0].get('sha256') == verified['exe_sha256'] and
            matches[0].get('size') == verified['exe_size'], 'Preview EXE identity differs from verified release asset')


def verify(release_dir, evidence_dir, repository, source_sha, output_dir, run_id, run_attempt):
    require(repository == REPOSITORY, 'Repository is not the approved project')
    require(bool(re.fullmatch(r'[0-9a-f]{40}', source_sha)) and type(run_id) is int and run_id > 0 and type(run_attempt) is int and run_attempt > 0, 'Invalid source commit/run')
    release_dir, evidence_dir, output_dir = map(Path, (release_dir, evidence_dir, output_dir))
    manifest = read_json(release_dir / 'update-manifest.json')
    version = manifest.get('version')
    require(isinstance(version, str) and bool(re.fullmatch(r'(0|[1-9][0-9]{0,4})\.(0|[1-9][0-9]{0,4})\.(0|[1-9][0-9]{0,4})', version)), 'Invalid stable version')
    require(type(manifest.get('schema_version')) is int and manifest.get('schema_version') == 1 and manifest.get('platform') == 'windows-x64', 'Unsupported manifest')
    require(all(int(part) <= 65535 for part in version.split('.')), 'Version exceeds Windows resource limits')
    tag = 'v' + version
    filename = f'vga-aram-helper-{version}-windows-x64.exe'
    expected_url = f'https://github.com/{REPOSITORY}/releases/download/{tag}/{filename}'
    require(manifest.get('url') == expected_url, 'Manifest URL/repository/version mismatch')
    exe = checked_file(release_dir / filename)
    require(exe.stat().st_size == manifest.get('size') and type(manifest.get('size')) is int, 'EXE size mismatch')
    checksum = digest(exe)
    require(checksum == manifest.get('sha256'), 'EXE SHA256 mismatch')
    with exe.open('rb') as source:
        require(source.read(2) == b'MZ', 'Asset is not a Windows executable')
    sums = checked_file(release_dir / 'SHA256SUMS.txt').read_text(encoding='ascii').strip()
    require(sums == f'{checksum}  {filename}', 'SHA256SUMS does not match exactly')
    files = {name: evidence_file(evidence_dir, name) for name in EVIDENCE_NAMES}
    build = read_json(files['windows-build.json'])
    smoke = read_json(files['windows-exe-smoke.json'])
    selftest = read_json(files['windows-exe-self-test.json'])
    require(build.get('source_commit') == source_sha and build.get('version') == version, 'Build source/version mismatch')
    require(build.get('manifest') == manifest, 'Build and release manifests differ')
    require(build.get('status') == 'built-not-yet-smoke-tested', 'Unexpected build status')
    require({m.get('name'): m.get('sha256') for m in build.get('bundled_models', [])} == MODEL_HASHES, 'Build model identity mismatch')
    inventory = build.get('archive_inventory', {})
    require(inventory.get('model_assets') == 3 and set(inventory.get('required_runtime_dlls', [])) ==
            RUNTIME_DLLS,
            'Missing standalone runtime/archive evidence')
    qt_binaries = inventory.get('qt_binaries', [])
    require(isinstance(qt_binaries, list) and qt_binaries and all(isinstance(name, str) for name in qt_binaries),
            'Missing Qt binary archive inventory')
    require(len(qt_binaries) <= 100 and all(len(name) <= 240 for name in qt_binaries), 'Unexpectedly large Qt inventory')
    print(json.dumps({'qt_binaries_under_review': sorted(qt_binaries)}, indent=2), flush=True)
    qt_paths = verify_qt_runtime(qt_binaries)
    try:
        verify_runtime_evidence(inventory.get('microsoft_runtime', {}), qt_paths)
    except (RuntimeError, TypeError, AttributeError) as exc:
        raise VerificationError('Licensed Microsoft runtime evidence is missing or changed: ' + str(exc)) from exc
    require(smoke.get('status') == 'passed' and 'error' not in smoke and smoke.get('executable_sha256') == checksum, 'EXE smoke failed or tested different bytes')
    require(BASELINE_CHECKS.issubset(set(smoke.get('checks', []))), 'Required browser/comparison/OCR smoke evidence is missing')
    require(smoke.get('health', {}).get('applicationVersion') == version, 'HTTP smoke version mismatch')
    require(smoke.get('health', {}).get('ocr_enabled') is True and smoke.get('health', {}).get('status') == 'ok', 'HTTP OCR was not enabled')
    require(selftest.get('status') == 'passed' and 'error' not in selftest and selftest.get('frozen') is True, 'Self-test was not a passing frozen executable')
    require(selftest.get('applicationVersion') == version, 'OCR self-test version mismatch')
    require(selftest.get('recognized') == ['珠光护手', '炼狱导管', '双刀流'] and selftest.get('blank_candidates') == 0, 'OCR result mismatch')
    models = selftest.get('bundled_models', [])
    require(len(models) == 3 and {m.get('name'): m.get('sha256') for m in models} == MODEL_HASHES, 'Bundled model identity mismatch')
    verify_png(files['windows-exe-ui.png'])
    native_smoke = read_json(files['windows-native-smoke.json'])
    native = read_json(files['windows-native-overlay.json'])
    require(native_smoke.get('status') == 'passed' and 'error' not in native_smoke and
            native_smoke.get('executable_sha256') == checksum and native_smoke.get('applicationVersion') == version and
            native_smoke.get('process_exited') is True, 'Native smoke failed, did not exit, or tested different EXE/version')
    require(native_smoke.get('native_report') == 'windows-native-overlay.json' and
            native_smoke.get('native_screenshot') == 'windows-native-overlay.png', 'Native smoke references unexpected evidence')
    require(native.get('status') == 'passed' and 'error' not in native and native.get('backend') == 'qtwidgets' and
            native.get('frozen') is True and native.get('qt_platform') == 'windows' and
            native.get('applicationVersion') == version, 'Native evidence is not passing frozen QtWidgets on Windows')
    require(all(native.get(field) is True for field in
            ('native_window', 'window_closed', 'capture_passed', 'ocr_passed', 'click_through_passed',
             'source_tier_display_passed', 'source_tier_hero_specific', 'source_tier_missing_passed',
             'source_tier_screen_order_preserved', 'source_tier_no_winrate_display')),
            'Required native window/capture/OCR/click-through/close/source-tier proof missing')
    require(native.get('source_tier_rendered') == ['虚构源评级（演示）：T1', '虚构源评级（演示）：T2', '虚构源评级（演示）：T3'],
            'Actual native literal source-tier rendering evidence is missing or changed')
    require(isinstance(native.get('screenshot_method'), str) and native['screenshot_method'].strip(),
            'Native screenshot method missing')
    verify_png(files['windows-native-overlay.png'])
    budget = read_json(files['windows-artifact-budget.json'])
    verify_budget(budget, release_dir, files)
    assets = [exe, release_dir / 'update-manifest.json', release_dir / 'SHA256SUMS.txt']
    for name in ('third-party-licenses.zip', 'WINDOWS_EXECUTABLE.md', 'THIRD_PARTY_NOTICES.md', 'LICENSE'):
        assets.append(checked_file(release_dir / name))
    licenses = assets[3]
    with zipfile.ZipFile(licenses) as archive:
        verify_qt_licenses(archive, build)
        try:
            verify_notice_archive(archive, inventory['microsoft_runtime'])
        except (RuntimeError, KeyError, ValueError) as exc:
            raise VerificationError('Microsoft component notices/source proof missing or changed: ' + str(exc)) from exc
    assets.extend(verify_source_access(release_dir, build, source_sha, version))
    output_dir.mkdir(parents=True, exist_ok=True)
    require(not output_dir.is_symlink(), 'Output directory cannot be a symlink')
    evidence_zip = output_dir / f'windows-test-evidence-{version}.zip'
    require(not evidence_zip.is_symlink(), 'Evidence output cannot be a symlink')
    with zipfile.ZipFile(evidence_zip, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, path in files.items():
            archive.write(path, arcname=name)
    assets.append(evidence_zip)
    # Exact existing original mock screenshot, already fully PNG-validated above.
    assets.append(files['windows-native-overlay.png'])
    result = {'repository': REPOSITORY, 'source_sha': source_sha, 'run_id': run_id, 'run_attempt': run_attempt, 'version': version, 'tag': tag,
              'exe_sha256': checksum, 'exe_size': exe.stat().st_size, 'artifact_budget': budget, 'qt_binaries': sorted(qt_paths),
              'evidence_sha256': {name: digest(path) for name, path in files.items()}, 'assets': [{'name': path.name, 'path': str(path.resolve()),
                'size': path.stat().st_size, 'sha256': digest(path)} for path in assets]}
    (output_dir / 'verified-release.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    notes = (f'VGA native overlay PREVIEW {version} (pre-release).\n\n'
             'Native overlay PREVIEW displaying each offered choice’s literal source tier for the selected hero when available. '
             'Ungraded or unmatched live inputs remain '
             'neutral; no invented grade, synthetic upgrade or inferred ranking. This is not a claim of a finished '
             'Huya-equivalent product or real-game validation.\n\n'
             f'Tested source commit: {source_sha}\nEXE SHA256: {checksum}\n'
             f'Tested Windows run: https://github.com/{REPOSITORY}/actions/runs/{run_id}\n\n'
             'Machine-verified on a standard Windows runner against an ORIGINAL SYNTHETIC MOCK WINDOW only: '
             'frozen QtWidgets native windows, local capture/OCR, click-through, close/cleanup, hero-specific source-tier rendering '
             '(including missing-grade fallback, original slot order and no displayed win rate/rank), and baseline HTTP/browser tests. '
             'Screenshots and machine evidence are attached; this statement does not claim human visual inspection. '
             'No process-memory reads, game injection, Vanguard approval or real-game compatibility claim. '
             'Windows 10/11 clean machines, exclusive fullscreen, live-game OCR and native OTA swap/rollback remain unverified.\n'
             'Unsigned executable: SmartScreen may warn about an unknown publisher. No signing or antivirus certification claim.\n'
             'This is prerelease=true. The existing stable /releases/latest OTA endpoint does NOT discover this preview. '
             'Download manually if you choose to try it. The fixed v0.3.0 tag preserves the tested immutable manifest URL.\n\n'
             'MICROSOFT RUNTIME TERMS: READ BEFORE USE\n'
             'Using the bundled Microsoft Visual C++ runtime components requires agreement to their Microsoft end-user terms. '
             f'Read [the same-release complete terms and scope notice](https://github.com/{REPOSITORY}/releases/download/{tag}/third-party-licenses.zip), '
             'under microsoft-runtime/MICROSOFT_VISUAL_CPP_2015_2022_RUNTIME_TERMS.txt and MICROSOFT_RUNTIME_NOTICE.txt, before use. '
             'These conditions apply only to the five named Microsoft CRT DLLs, not the MIT application or LGPL Qt components. '
             'The publisher distribution basis is the approved Visual Studio Community 2022 installation/use and its Section 4; '
             'the runtime end-user terms themselves do not grant redistribution rights. The build record proves installed product, '
             'Microsoft signatures, x64 dependency inspection and unchanged source-to-EXE DLL hashes.\n\n'
             'QT / PYSIDE / SHIBOKEN: LGPLv3\n'
             'Applicable Qt, PySide6 and Shiboken6 6.11.2 shared libraries are offered under LGPLv3. '
             'Their notices and complete LGPL/GPL license texts are in third-party-licenses.zip, including '
             'qt-licenses/NOTICE.txt and qt-licenses/SOURCE_AND_RELINKING.txt. '
             'source-access.json identifies the matching four official source tar.xz archives and their SHA256 hashes, '
             'available alongside this binary in the SAME release, plus the same-commit application source ZIP '
             '(including specification, resources and build scripts). Corresponding sources remain available alongside the binary '
             'for as long as required by the applicable licenses.\n'
             'Recipients may modify the LGPL components, recombine/relink the application, and reverse-engineer/debug '
             'those modifications under the applicable license terms. No secret signing key is needed to run a modified build. '
             'This supplies a source/rebuild route under LGPLv3 section 4(d)(0); temporary one-file extraction is NOT claimed '
             'as a user-replaceable mechanism under section 4(d)(1).\n\n'
             'RECIPIENT REBUILD ROUTE (not represented as a tested modified-library rebuild)\n'
             'Use native Windows x64, MSVC 2022 x64 development tools, Python 3.12 x64, Git, CMake and Ninja. '
             'Extract the attached same-commit application source ZIP and the exact matching Qt/PySide/Shiboken sources. '
             'The packaging script uses git archive, so initialize the extracted application directory as your own local Git repository, '
             'commit its source/resources using your own Git identity, and commit later source changes before building. '
             'Follow the official Qt and Qt for Python instructions to build ABI-compatible modified 6.11.2 shared libraries:\n'
             'https://doc.qt.io/qt-6.11/windows-building.html\n'
             'https://doc.qt.io/qtforpython-6/building_from_source/index.html\n'
             'Prepare the remaining pinned requirements before replacing Qt. Install the modified ABI-compatible Qt/PySide/Shiboken '
             'libraries into that same Python packaging environment. Read and accept the Community terms before preparing licensed '
             'CRT inputs. The supplied install-community-runtime.ps1 -AcceptCommunityLicense route is limited to an ephemeral GitHub-hosted '
             'Windows runner; use your own source fork/workflow, or adapt that open-source preparation step under your own valid license '
             'for local tooling while retaining signature, dependency and source checks. From the application source root run:\n'
             'python scripts/build_windows.py\n'
             'Do not reinstall the official pinned Qt wheels after installing modified libraries. Retain the native resources/specification, '
             'record your modifications and their source, and run the supplied Windows/native acceptance tests on your rebuilt EXE. '
             'Version identity checks require ABI-compatible 6.11.2; adapt documented packaging checks if your intended modification changes '
             'that identity, preserving accurate notices/source availability.\n')
    links = [('Complete license and notice ZIP', 'third-party-licenses.zip'),
             ('Source inventory and SHA256 hashes', 'source-access.json'),
             ('Same-commit application source, specification and resources', f'vga-aram-helper-{version}-source.zip')]
    links += [('Corresponding source: ' + row['filename'], row['filename']) for row in QT_SOURCES]
    links += [('Original synthetic native overlay screenshot', 'windows-native-overlay.png')]
    notes += '\nSAME-RELEASE FILES AND CORRESPONDING SOURCES\n'
    notes += ''.join(f'- [{label}](https://github.com/{REPOSITORY}/releases/download/{tag}/{name})\n'
                     for label, name in links)
    (output_dir / 'release-notes.txt').write_text(notes, encoding='utf-8')
    return result


def gh_run(arguments):
    # The token is only supplied to the final workflow step. Never read it,
    # write it to disk, authenticate persistently, or include it in argv/output.
    command = subprocess.run(['gh', *arguments], capture_output=True, text=True,
                             check=False, timeout=300)
    if command.returncode:
        raise VerificationError('GitHub command failed; publication stopped without cleanup')
    return command.stdout


def gh_api(path, allow_absent=False, fields=None):
    arguments = ['gh', 'api', '--hostname', 'github.com',
                 '-H', 'Accept: application/vnd.github+json', path]
    if fields is not None:
        arguments += ['--method', 'POST']
        for key, value in fields.items():
            arguments += ['--raw-field', f'{key}={value}']
    command = subprocess.run(arguments, capture_output=True, text=True,
                             check=False, timeout=300)
    if command.returncode:
        if allow_absent and '(HTTP 404)' in command.stderr:
            return None
        # Fail closed on all authentication, validation and network errors.
        raise VerificationError('GitHub API check failed; publication stopped without cleanup')
    return json.loads(command.stdout)


def find_release(repo, tag):
    # The tag endpoint documents published releases only. Listing with this
    # job's write token also finds pre-existing drafts, so they cannot be reused.
    matches = []
    for page in range(1, 101):
        rows = gh_api(f'repos/{repo}/releases?per_page=100&page={page}')
        require(isinstance(rows, list), 'Invalid release listing')
        matches.extend(row for row in rows if row.get('tag_name') == tag)
        require(len(matches) <= 1, 'Ambiguous releases for version tag')
        if len(rows) < 100:
            return matches[0] if matches else None
    raise VerificationError('Release listing limit reached; refusing to guess absence')


def check_tag(reference, tag, sha):
    require(isinstance(reference, dict) and reference.get('ref') == 'refs/tags/' + tag and
            reference.get('object', {}).get('sha') == sha and
            reference.get('object', {}).get('type') == 'commit',
            'Tag does not point directly at the exact tested commit')


def check_remote_assets(release, assets):
    remote = release.get('assets', [])
    require(len(remote) == len(assets), 'Unexpected or incomplete release asset list')
    for asset in assets:
        matches = [item for item in remote if item.get('name') == asset['name']]
        require(len(matches) == 1, 'Missing or ambiguous uploaded asset')
        item = matches[0]
        require(item.get('state') == 'uploaded' and item.get('size') == asset['size'], 'Remote asset size/state mismatch')
        require(item.get('digest') == 'sha256:' + asset['sha256'], 'Remote asset SHA256 mismatch or unavailable')


def publish(verified, notes_file, provenance):
    check_preview_identity(verified, provenance)
    repo, tag, sha = verified['repository'], verified['tag'], verified['source_sha']
    require(repo == REPOSITORY and tag == 'v' + verified['version'] and
            re.fullmatch(r'v[0-9]{1,5}\.[0-9]{1,5}\.[0-9]{1,5}', tag) and
            re.fullmatch(r'[0-9a-f]{40}', sha), 'Publication identity mismatch')
    # No overwrite, clobber, update-ref, delete, reset, or automatic retries.
    require(gh_api(f'repos/{repo}/git/ref/tags/{tag}', allow_absent=True) is None, 'Tag already exists; never overwrite')
    require(find_release(repo, tag) is None, 'Release already exists; never overwrite')
    assets = verified['assets']
    for asset in assets:
        path = checked_file(asset['path'])
        require(path.stat().st_size == asset['size'] and digest(path) == asset['sha256'], 'Asset changed after verification')
    checked_file(notes_file)
    # Draft release creation may defer creation of its tag. Reserve the tag
    # atomically first: POST fails if another writer won, even for the same SHA.
    # A later failure intentionally leaves the tag/draft for manual inspection.
    reference = gh_api(f'repos/{repo}/git/refs', fields={'ref': 'refs/tags/' + tag, 'sha': sha})
    check_tag(reference, tag, sha)
    check_tag(gh_api(f'repos/{repo}/git/ref/tags/{tag}'), tag, sha)
    command = ['release', 'create', tag, '--repo', repo, '--target', sha, '--verify-tag', '--draft', '--prerelease', '--latest=false',
               '--title', f'VGA Native Overlay PREVIEW {verified["version"]}', '--notes-file', str(notes_file)]
    command += [asset['path'] for asset in assets]
    gh_run(command)
    # Creating/uploading while draft prevents OTA from seeing incomplete assets.
    release = find_release(repo, tag)
    require(isinstance(release, dict), 'Created draft release is missing')
    require(release.get('draft') is True and release.get('prerelease') is True and release.get('tag_name') == tag, 'Unexpected created release')
    require(release.get('target_commitish') == sha, 'Release target differs from tested source')
    require(type(release.get('id')) is int and release['id'] > 0, 'Created release has no stable identity')
    check_remote_assets(release, assets)
    check_tag(gh_api(f'repos/{repo}/git/ref/tags/{tag}'), tag, sha)
    # Publish only the specific verified draft, never resolve the mutable tag again.
    # gh --field converts false to a JSON boolean; no shell or token persistence.
    gh_run(['api', '--hostname', 'github.com', '--method', 'PATCH',
            '-H', 'Accept: application/vnd.github+json',
            f'repos/{repo}/releases/{release["id"]}', '--field', 'draft=false',
            '--field', 'prerelease=true', '--raw-field', 'make_latest=false'])
    final = gh_api(f'repos/{repo}/releases/{release["id"]}')
    check_tag(gh_api(f'repos/{repo}/git/ref/tags/{tag}'), tag, sha)
    require(final.get('draft') is False and final.get('prerelease') is True and final.get('id') == release['id'] and
            final.get('tag_name') == tag and final.get('target_commitish') == sha,
            'Published release identity verification failed')
    check_remote_assets(final, assets)
    expected_url = f'https://github.com/{repo}/releases/tag/{tag}'
    require(final.get('html_url') == expected_url, 'Unexpected release URL')
    return expected_url


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--release-dir', type=Path, required=True)
    parser.add_argument('--evidence-dir', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--repository', required=True)
    parser.add_argument('--source-sha', required=True)
    parser.add_argument('--run-id', type=int, required=True)
    parser.add_argument('--run-attempt', type=int, required=True)
    parser.add_argument('--publish', action='store_true')
    args = parser.parse_args()
    result = verify(args.release_dir, args.evidence_dir, args.repository, args.source_sha, args.output_dir, args.run_id, args.run_attempt)
    require(result['version'] == PREVIEW_VERSION, 'This manual preview approval covers v0.3.0 only')
    summary = {key: result[key] for key in ('repository', 'run_id', 'run_attempt', 'source_sha', 'version', 'tag',
                                          'exe_sha256', 'exe_size', 'artifact_budget', 'qt_binaries')}
    summary.update(prerelease=True, release_asset_count=len(result['assets']),
                   evidence_file_count=len(result['evidence_sha256']), evidence_sha256=result['evidence_sha256'])
    print(json.dumps(summary, indent=2), flush=True)
    if args.publish:
        check_runner_context(args.repository, args.source_sha, args.run_id, args.run_attempt)
        provenance = verify_run_provenance(args.repository, args.source_sha, args.run_id, args.run_attempt)
        print(publish(result, args.output_dir / 'release-notes.txt', provenance))


if __name__ == '__main__':
    main()

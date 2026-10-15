"""Build the persistent HWND WGC helper with existing Microsoft tools.

No downloads, package installation, game access or machine configuration changes.
The Windows SDK version and compiler/link flags are pinned below; signed Community
compiler/linker bytes and source inputs are recorded for each serviced build.
This is source correspondence, not a bit-reproducible toolchain claim.
"""
from __future__ import annotations
import argparse
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import microsoft_runtime
from scripts.build_minimal_opencv import clean_environment, community_toolchain

SDK_VERSION = '10.0.26100.0'
PROFILE = 'hwnd-wgc-session-v2'
PROTOCOL = 2
FILENAME = 'vga-wgc-session-capture.exe'
MANIFEST = 'wgc-session-capture-build.json'
OUTPUT = ROOT / 'build' / 'native'
SOURCE = ROOT / 'native' / 'wgc_session_capture.cpp'
COMPILE_FLAGS = ('/nologo', '/std:c++17', '/EHsc', '/O2', '/MT', '/W4', '/permissive-',
                 '/utf-8', '/DUNICODE', '/D_UNICODE', '/DNOMINMAX', '/DWIN32_LEAN_AND_MEAN')
LINK_FLAGS = ('/MACHINE:X64', '/SUBSYSTEM:CONSOLE', '/DYNAMICBASE', '/NXCOMPAT', '/HIGHENTROPYVA', '/INCREMENTAL:NO')
LIBRARIES = ('windowsapp.lib', 'd3d11.lib', 'dxgi.lib', 'dwmapi.lib', 'user32.lib')
ALLOWED_DLLS = {'kernel32.dll', 'kernelbase.dll', 'ntdll.dll', 'user32.dll', 'gdi32.dll',
                'advapi32.dll', 'ole32.dll', 'oleaut32.dll', 'combase.dll', 'd3d11.dll',
                'dxgi.dll', 'dwmapi.dll', 'runtimeobject.dll', 'shcore.dll', 'shell32.dll'}
SDK_HEADERS = ('cppwinrt/winrt/Windows.Graphics.Capture.h', 'cppwinrt/winrt/base.h',
               'um/windows.graphics.capture.interop.h', 'um/d3d11.h')
MAX_HELPER_BYTES = 4 * 1024 * 1024
SOURCE_FILES = ('native/wgc_session_capture.cpp', 'wgc_session_capture.py',
    'wgc_session_smoke.py', 'wgc_session_diagnostic.py', 'wgc_capture.py',
    'screen_capture.py', 'session_windows.py', 'app_version.py',
    'native_ui.py', 'automatic_windows.py', 'selection_session.py', 'persistent_capture_adapter.py',
    'scripts/build_wgc_session_capture.py', 'scripts/build_wgc_capture.py',
    'scripts/build_windows.py', 'scripts/build_minimal_opencv.py', 'scripts/windows_package.py',
    'scripts/microsoft_runtime.py', 'scripts/qt_licenses.py',
    'tests/windows_wgc_session_capture.py', 'tests/windows_exe_smoke.py',
    'launcher.py', 'packaging/VGA-Aram-Helper.spec',
    'packaging/WGC-Session-Diagnostic.spec', 'packaging/windows.manifest',
    'requirements-build.txt', 'packaging/windows-build-constraints.txt')


def record(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise RuntimeError('Expected a regular build input: ' + path.name)
    return {'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'size': path.stat().st_size}


def validate_manifest(value):
    if (not isinstance(value, dict) or type(value.get('schema_version')) is not int or value['schema_version'] != 1
            or type(value.get('protocol')) is not int or value['protocol'] != PROTOCOL
            or value.get('filename') != FILENAME or value.get('profile') != PROFILE
            or value.get('status') != 'passed' or 'error' in value):
        raise RuntimeError('WGC helper build identity is missing or changed')
    if type(value.get('size')) is not int or not 1024 <= value['size'] <= MAX_HELPER_BYTES:
        raise RuntimeError('WGC helper size is outside the native budget')
    for key in ('sha256', 'source_sha256', 'build_recipe_sha256'):
        if not isinstance(value.get(key), str) or not re.fullmatch('[0-9a-f]{64}', value[key]):
            raise RuntimeError('WGC helper input digest is invalid: ' + key)
    if (value.get('sdk_version') != SDK_VERSION or value.get('compile_flags') != list(COMPILE_FLAGS)
            or value.get('link_flags') != list(LINK_FLAGS) or value.get('libraries') != list(LIBRARIES)
            or value.get('machine') != 'x64' or value.get('crt') != 'static-release-/MT'):
        raise RuntimeError('WGC helper pinned build configuration changed')
    if not re.fullmatch('[0-9a-f]{40}', value.get('source_commit', '')):
        raise RuntimeError('WGC build is missing its exact source commit')
    inputs = value.get('source_files')
    if not isinstance(inputs, dict) or set(inputs) != set(SOURCE_FILES):
        raise RuntimeError('Session source/fixture inventory is incomplete')
    for row in inputs.values():
        if (not isinstance(row, dict) or set(row) != {'sha256', 'size'}
                or not isinstance(row.get('sha256'), str) or not re.fullmatch('[0-9a-f]{64}', row['sha256'])
                or type(row.get('size')) is not int or row['size'] <= 0):
            raise RuntimeError('Session source input digest is invalid')
    for name, key in (('native/wgc_session_capture.cpp', 'source_sha256'),
                      ('scripts/build_wgc_session_capture.py', 'build_recipe_sha256')):
        if inputs[name]['sha256'] != value[key]:
            raise RuntimeError('Session source inventory disagrees with manifest identity')
    toolchain = value.get('toolchain', {})
    if toolchain.get('product_id') != microsoft_runtime.PRODUCT_ID:
        raise RuntimeError('WGC build did not use the approved Community compiler')
    for name in ('compiler', 'linker'):
        tool = toolchain.get(name, {})
        if (not microsoft_runtime.signed_by_microsoft(tool)
                or not re.fullmatch('[0-9a-f]{64}', tool.get('sha256', ''))
                or type(tool.get('size')) is not int or tool['size'] <= 0):
            raise RuntimeError('WGC signed tool provenance is incomplete: ' + name)
    headers = value.get('sdk_headers', {})
    if set(headers) != set(SDK_HEADERS):
        raise RuntimeError('WGC SDK header inventory is incomplete')
    for row in headers.values():
        if (not re.fullmatch('[0-9a-f]{64}', row.get('sha256', ''))
                or type(row.get('size')) is not int or row['size'] <= 0):
            raise RuntimeError('WGC SDK header digest is missing')
    dependencies = value.get('dependencies')
    if (not isinstance(dependencies, list) or not dependencies or len(dependencies) > 100
            or len(set(dependencies)) != len(dependencies)
            or not all(allowed_dependency(name) for name in dependencies)):
        raise RuntimeError('WGC helper has an unreviewed runtime dependency')
    return value


def allowed_dependency(name):
    return isinstance(name, str) and (name in ALLOWED_DLLS or
        re.fullmatch(r'(?:api-ms-win-|ext-ms-win-)[a-z0-9-]+-l\d+-\d+-\d+\.dll', name) is not None)


def verify_built_helper(folder=OUTPUT, *, root=ROOT):
    folder, root = Path(folder), Path(root)
    manifest_path = folder / MANIFEST
    record(manifest_path)
    if manifest_path.stat().st_size > 64 * 1024:
        raise RuntimeError('WGC build manifest exceeded its budget')
    value = validate_manifest(json.loads(manifest_path.read_text(encoding='utf-8')))
    if record(folder / FILENAME) != {key: value[key] for key in ('sha256', 'size')}:
        raise RuntimeError('WGC helper bytes differ from their build manifest')
    for relative, key in (('native/wgc_session_capture.cpp', 'source_sha256'),
                          ('scripts/build_wgc_session_capture.py', 'build_recipe_sha256')):
        if record(root / relative)['sha256'] != value[key]:
            raise RuntimeError('WGC source/build recipe changed after compilation: ' + relative)
    for relative, expected in value['source_files'].items():
        if record(root / relative) != expected:
            raise RuntimeError('Session fixture/build input changed after compilation: ' + relative)
    return value


def verify_archive(archive, proof=None):
    proof = verify_built_helper() if proof is None else validate_manifest(proof)
    expected = {'native/' + FILENAME, 'native/' + MANIFEST}
    paths = {str(name).replace('\\', '/').lower(): name for name in archive.toc}
    if len(paths) != len(archive.toc):
        raise RuntimeError('Frozen archive contains ambiguous duplicate paths')
    if not expected <= paths.keys():
        raise RuntimeError('Frozen application is missing its WGC helper or integrity manifest')
    data = archive.extract(paths['native/' + FILENAME])
    if not isinstance(data, bytes) or len(data) != proof['size'] or hashlib.sha256(data).hexdigest() != proof['sha256']:
        raise RuntimeError('Frozen WGC helper bytes differ from the tested source build')
    raw_manifest = archive.extract(paths['native/' + MANIFEST])
    if not isinstance(raw_manifest, bytes) or not 0 < len(raw_manifest) <= 64 * 1024:
        raise RuntimeError('Frozen WGC integrity manifest is missing or oversized')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise RuntimeError('Frozen WGC integrity manifest has duplicate keys')
            result[key] = value
        return result
    manifest = json.loads(raw_manifest, object_pairs_hook=unique)
    if manifest != proof:
        raise RuntimeError('Frozen WGC integrity manifest differs from build evidence')
    return proof


def inspect_native(path):
    import pefile
    pe = pefile.PE(str(path), fast_load=True)
    try:
        if pe.FILE_HEADER.Machine != 0x8664 or pe.OPTIONAL_HEADER.Magic != 0x20b:
            raise RuntimeError('WGC helper is not a native x64 PE executable')
        pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY[name] for name in
            ('IMAGE_DIRECTORY_ENTRY_IMPORT', 'IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT')])
        dependencies = sorted({entry.dll.decode('ascii').lower() for key in
            ('DIRECTORY_ENTRY_IMPORT', 'DIRECTORY_ENTRY_DELAY_IMPORT') for entry in getattr(pe, key, ())})
        if not dependencies or not all(allowed_dependency(name) for name in dependencies):
            raise RuntimeError('WGC helper depends on a non-system runtime: ' + repr(dependencies))
        # ASLR, NX and high-entropy address space are required, no security setting changes.
        if pe.OPTIONAL_HEADER.DllCharacteristics & 0x160 != 0x160:
            raise RuntimeError('WGC helper is missing compiler hardening flags')
        return {'machine': 'x64', 'dependencies': dependencies}
    finally:
        pe.close()


def sdk_paths(root):
    root = Path(root)
    includes = [root / 'Include' / SDK_VERSION / name for name in ('ucrt', 'shared', 'um', 'winrt', 'cppwinrt')]
    libraries = [root / 'Lib' / SDK_VERSION / name / 'x64' for name in ('ucrt', 'um')]
    for path in includes + libraries:
        if not path.is_dir():
            raise RuntimeError('Installed pinned Windows SDK is unavailable: ' + str(path))
    return includes, libraries, {name: record(root / 'Include' / SDK_VERSION / name) for name in SDK_HEADERS}


def signed_tool(path, env):
    path = Path(path)
    proof = record(path)
    env = dict(env, VGA_CHECK_COMPILER=str(path))
    text = subprocess.check_output(['pwsh', '-NoProfile', '-NonInteractive', '-Command',
        '$f=Get-Item -LiteralPath $env:VGA_CHECK_COMPILER; $s=Get-AuthenticodeSignature -LiteralPath $f.FullName; '
        '@{signature_status=$s.Status.ToString();signer_subject=$s.SignerCertificate.Subject;'
        'file_version=$f.VersionInfo.FileVersion} | ConvertTo-Json -Compress'],
        env=env, timeout=60, text=True, encoding='utf-8')
    proof.update(json.loads(text))
    if not microsoft_runtime.signed_by_microsoft(proof):
        raise RuntimeError('WGC compiler/linker is not signed by Microsoft')
    return proof


def build():
    if sys.platform != 'win32' or struct.calcsize('P') != 8:
        raise RuntimeError('WGC helper must be compiled on native Windows x64')
    from scripts.build_windows import verify_source_checkout
    commit = verify_source_checkout(ROOT, os.environ.get('GITHUB_SHA'))
    runtime = microsoft_runtime.verify_source_files()
    toolchain = community_toolchain(runtime)
    compiler = Path(toolchain['compiler_path'])
    linker = Path(toolchain['linker_path'])
    vc = compiler.parents[3]
    program_files = {key.upper(): value for key, value in os.environ.items()}.get('PROGRAMFILES(X86)', '')
    if not Path(program_files).is_absolute():
        raise RuntimeError('Cannot locate the existing Windows SDK installation')
    sdk = Path(program_files) / 'Windows Kits' / '10'
    includes, libraries, headers = sdk_paths(sdk)
    env = clean_environment()
    env['INCLUDE'] = ';'.join(map(str, [vc / 'include', *includes]))
    env['LIB'] = ';'.join(map(str, [vc / 'lib/x64', *libraries]))
    env['PATH'] = str(compiler.parent) + ';' + env.get('PATH', '')
    toolchain['compiler'] = signed_tool(compiler, env)
    toolchain['linker'] = signed_tool(linker, env)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    # Never reuse a previous passing manifest if compilation fails.
    (OUTPUT / MANIFEST).unlink(missing_ok=True)
    destination = OUTPUT / FILENAME
    destination.unlink(missing_ok=True)
    command = [str(compiler), *COMPILE_FLAGS, str(SOURCE), '/Fo' + str(OUTPUT / 'wgc_session_capture.obj'),
               '/Fe' + str(destination), '/link', *LINK_FLAGS, *LIBRARIES]
    result = subprocess.run(command, cwd=OUTPUT, env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, timeout=180, check=False)
    if len(result.stdout) > 128 * 1024:
        raise RuntimeError('WGC compiler diagnostics exceeded their budget')
    (OUTPUT / 'wgc-session-build.log').write_bytes(result.stdout)
    if result.returncode:
        raise RuntimeError('WGC native build failed: ' + result.stdout.decode('utf-8', errors='replace')[-16000:])
    proof = {'schema_version': 1, 'protocol': PROTOCOL, 'filename': FILENAME, 'profile': PROFILE,
        'status': 'passed', 'source_commit': commit, **record(destination),
        'source_sha256': record(SOURCE)['sha256'], 'build_recipe_sha256': record(Path(__file__))['sha256'],
        'source_files': {name: record(ROOT / name) for name in SOURCE_FILES},
        'sdk_version': SDK_VERSION, 'sdk_headers': headers, 'toolchain': toolchain,
        'compile_flags': list(COMPILE_FLAGS), 'link_flags': list(LINK_FLAGS), 'libraries': list(LIBRARIES),
        'crt': 'static-release-/MT', **inspect_native(destination),
        'scope': 'Persistent HWND session helper. Build success is not native Windows capture or application acceptance.'}
    validate_manifest(proof)
    if verify_source_checkout(ROOT, commit) != commit:
        raise RuntimeError('WGC helper source changed during compilation')
    (OUTPUT / MANIFEST).write_text(json.dumps(proof, indent=2) + '\n', encoding='utf-8')
    verify_built_helper()
    return proof


def freeze_diagnostic():
    """Build only the standalone test diagnostic; never alter the production EXE."""
    if sys.platform != 'win32' or struct.calcsize('P') != 8:
        raise RuntimeError('Diagnostic must be frozen on native Windows x64')
    if sys.version_info[:2] != (3, 12):
        raise RuntimeError('Diagnostic requires the existing pinned Python 3.12 x64 environment')
    from scripts.build_windows import verify_source_checkout
    commit = verify_source_checkout(ROOT, os.environ.get('GITHUB_SHA'))
    proof = verify_built_helper()
    if proof['source_commit'] != commit:
        raise RuntimeError('Session helper must match the clean diagnostic source commit')
    for name, expected in {'pyinstaller': '6.22.3', 'PySide6-Essentials': '6.11.2',
                           'shiboken6': '6.11.2', 'pillow': '12.3.0', 'pefile': '2024.8.26'}.items():
        if metadata.version(name) != expected:
            raise RuntimeError('Existing pinned build package is missing/changed: ' + name)
    # Existing approved inputs only. No dependency installation or downloads.
    from scripts.qt_licenses import copy_bundle
    destination = ROOT / 'build' / 'wgc-session-diagnostic' / 'licenses'
    destination.mkdir(parents=True, exist_ok=True)
    copy_bundle(ROOT / 'packaging' / 'qt-licenses', destination)
    microsoft_runtime.copy_notices(destination)
    command = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean',
               '--distpath', str(ROOT / 'dist' / 'wgc-session-diagnostic'),
               '--workpath', str(ROOT / 'build' / 'wgc-session-diagnostic' / 'pyinstaller'),
               str(ROOT / 'packaging' / 'WGC-Session-Diagnostic.spec')]
    subprocess.run(command, cwd=ROOT, env=clean_environment(), check=True, timeout=600)
    executable = ROOT / 'dist' / 'wgc-session-diagnostic' / 'WGC-Session-Diagnostic.exe'
    from PyInstaller.archive.readers import CArchiveReader
    archive = CArchiveReader(str(executable))
    verify_archive(archive, proof)
    microsoft_runtime.verify_embedded_runtime(archive)
    if verify_source_checkout(ROOT, commit) != commit:
        raise RuntimeError('Diagnostic source changed while freezing')
    inventory = {str(name).replace('\\', '/').lower() for name in archive.toc}
    if any(any(part in name for part in ('onnxruntime', 'rapidocr', 'opencv', 'webengine')) for name in inventory):
        raise RuntimeError('Test-only diagnostic unexpectedly contains OCR or browser binaries')
    return {'source_commit': commit, 'filename': executable.name, **record(executable),
            'helper': proof, 'test_only': True, 'production_enabled': False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--freeze-diagnostic', action='store_true',
                        help='Also freeze the isolated Qt acceptance fixture using existing pinned packages')
    modes.add_argument('--freeze-only', action='store_true',
                       help='Freeze the standalone diagnostic without rebuilding the already-tested helper')
    args = parser.parse_args(argv)
    reports = ROOT / 'reports'
    reports.mkdir(exist_ok=True)
    report_name = 'windows-wgc-session-frozen-build.json' if args.freeze_only else 'windows-wgc-session-build.json'
    try:
        result = verify_built_helper() if args.freeze_only else build()
        if args.freeze_diagnostic or args.freeze_only:
            result = dict(result, diagnostic=freeze_diagnostic())
    except Exception as exc:
        result = {'schema_version': 1, 'status': 'failed', 'error': str(exc)[:20000], 'no_acceptance_claim': True}
        (reports / report_name).write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(result), flush=True)
        raise
    (reports / report_name).write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    main()

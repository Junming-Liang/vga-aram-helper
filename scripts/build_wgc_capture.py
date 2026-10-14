"""Build the original, HWND-only WGC helper with existing Microsoft tools.

No downloads, package installation, game access or machine configuration changes.
The Windows SDK version and compiler/link flags are pinned below; signed Community
compiler/linker bytes and source inputs are recorded for each serviced build.
This is source correspondence, not a bit-reproducible toolchain claim.
"""
from __future__ import annotations
import hashlib
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
PROFILE = 'hwnd-wgc-v1'
PROTOCOL = 1
FILENAME = 'vga-wgc-capture.exe'
MANIFEST = 'wgc-capture-build.json'
OUTPUT = ROOT / 'build' / 'native'
SOURCE = ROOT / 'native' / 'wgc_capture.cpp'
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
    if manifest_path.stat().st_size > 128 * 1024:
        raise RuntimeError('WGC build manifest exceeded its budget')
    value = validate_manifest(json.loads(manifest_path.read_text(encoding='utf-8')))
    if record(folder / FILENAME) != {key: value[key] for key in ('sha256', 'size')}:
        raise RuntimeError('WGC helper bytes differ from their build manifest')
    for relative, key in (('native/wgc_capture.cpp', 'source_sha256'),
                          ('scripts/build_wgc_capture.py', 'build_recipe_sha256')):
        if record(root / relative)['sha256'] != value[key]:
            raise RuntimeError('WGC source/build recipe changed after compilation: ' + relative)
    return value


def verify_archive(archive, proof=None):
    proof = verify_built_helper() if proof is None else validate_manifest(proof)
    expected = {'native/' + FILENAME, 'native/' + MANIFEST}
    paths = {str(name).replace('\\', '/').lower(): name for name in archive.toc}
    if not expected <= paths.keys():
        raise RuntimeError('Frozen application is missing its WGC helper or integrity manifest')
    data = archive.extract(paths['native/' + FILENAME])
    if not isinstance(data, bytes) or len(data) != proof['size'] or hashlib.sha256(data).hexdigest() != proof['sha256']:
        raise RuntimeError('Frozen WGC helper bytes differ from the tested source build')
    manifest = json.loads(archive.extract(paths['native/' + MANIFEST]))
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
    command = [str(compiler), *COMPILE_FLAGS, str(SOURCE), '/Fo' + str(OUTPUT / 'wgc_capture.obj'),
               '/Fe' + str(destination), '/link', *LINK_FLAGS, *LIBRARIES]
    result = subprocess.run(command, cwd=OUTPUT, env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, timeout=180, check=False)
    if len(result.stdout) > 128 * 1024:
        raise RuntimeError('WGC compiler diagnostics exceeded their budget')
    (OUTPUT / 'build.log').write_bytes(result.stdout)
    if result.returncode:
        raise RuntimeError('WGC native build failed: ' + result.stdout.decode('utf-8', errors='replace')[-16000:])
    proof = {'schema_version': 1, 'protocol': PROTOCOL, 'filename': FILENAME, 'profile': PROFILE,
        'status': 'passed', 'source_commit': commit, **record(destination),
        'source_sha256': record(SOURCE)['sha256'], 'build_recipe_sha256': record(Path(__file__))['sha256'],
        'sdk_version': SDK_VERSION, 'sdk_headers': headers, 'toolchain': toolchain,
        'compile_flags': list(COMPILE_FLAGS), 'link_flags': list(LINK_FLAGS), 'libraries': list(LIBRARIES),
        'crt': 'static-release-/MT', **inspect_native(destination),
        'scope': 'Original HWND-only helper. No Windows capture acceptance claimed by successful compilation.'}
    validate_manifest(proof)
    if verify_source_checkout(ROOT, commit) != commit:
        raise RuntimeError('WGC helper source changed during compilation')
    (OUTPUT / MANIFEST).write_text(json.dumps(proof, indent=2) + '\n', encoding='utf-8')
    verify_built_helper()
    return proof


def main():
    reports = ROOT / 'reports'
    reports.mkdir(exist_ok=True)
    try:
        result = build()
    except Exception as exc:
        result = {'schema_version': 1, 'status': 'failed', 'error': str(exc)[:20000], 'no_acceptance_claim': True}
        (reports / 'windows-wgc-build.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(result), flush=True)
        raise
    (reports / 'windows-wgc-build.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    main()

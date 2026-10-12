"""Preserve licensed, unmodified Microsoft release runtimes separately from Qt.

The installed Community toolchain supplies the actual bytes. The pinned Qt wheel
provenance records only the minimum compatible V14 runtime requirement.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path, PureWindowsPath
import re
import shutil

ROOT = Path(__file__).resolve().parents[1]
NOTICE_ROOT = ROOT / 'packaging' / 'microsoft-runtime'
RUNTIME_ROOT = ROOT / 'build' / 'microsoft-runtime'
PROVENANCE = json.loads((NOTICE_ROOT / 'WHEEL_BASELINE.json').read_text(encoding='utf-8'))
RUNTIME_DLLS = frozenset(row['filename'] for row in PROVENANCE['files'])
MINIMUM_VERSION = (14, 44, 35211, 0)
LICENSE_URL = 'https://visualstudio.microsoft.com/license-terms/vs2022-ga-community/'
PRODUCT_ID = 'Microsoft.VisualStudio.Product.Community'
NOTICE_HASHES = {
    'MICROSOFT_RUNTIME_NOTICE.txt': '77c9c3f71f4049c34808d0c0082075eebb562e76eccaf27cd4fbe820b20cffd3',
    'MICROSOFT_VISUAL_CPP_2015_2022_RUNTIME_TERMS.txt': '5d7d60ce25f23875bfb5abf5583d3caa9305ba61c01d7f8cbfc06f8b0d2bab22',
    'VISUAL_STUDIO_COMMUNITY_2022_LICENSE.txt': '0ff50aa7e32670b49af349ede7b464bed38cee0eb496767bd01c5f21223375a4',
}


def version_tuple(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d+\.\d+\.\d+\.\d+', value):
        raise RuntimeError('Invalid Microsoft runtime version')
    return tuple(map(int, value.split('.')))


def signed_by_microsoft(row):
    return (row.get('signature_status') == 'Valid' and
            re.search(r'(?:^|,\s*)O=Microsoft Corporation(?:,|$)', row.get('signer_subject', '')) is not None)


def allowed_dependency(name):
    return (name in RUNTIME_DLLS or name in {'kernel32.dll', 'kernelbase.dll', 'ntdll.dll', 'ucrtbase.dll'} or
            re.fullmatch(r'(?:api-ms-win-|ext-ms-win-)[a-z0-9-]+-l\d+-\d+-\d+\.dll', name) is not None)


def reject_unreviewed_runtime_names(names):
    for path in names:
        name = path.replace('\\', '/').rsplit('/', 1)[-1].casefold()
        if re.fullmatch(r'(?:msvcp|msvcr|vcruntime|concrt)[a-z0-9_]*\.dll', name) and name not in RUNTIME_DLLS:
            raise RuntimeError('Unexpected or debug Microsoft CRT anywhere in archive: ' + path)


def verify_provenance(proof):
    """Validate the output of the reviewed official Community setup/inspection step."""
    if (type(proof.get('schema_version')) is not int or proof['schema_version'] != 1 or
            proof.get('status') != 'passed' or 'error' in proof or proof.get('verified') is not True or
            proof.get('source') != 'Microsoft Visual Studio Community 2022' or proof.get('license_url') != LICENSE_URL):
        raise RuntimeError('Missing licensed Community runtime provenance')
    product = proof.get('product', {})
    base = PureWindowsPath(product.get('installation_path', ''))
    if (product.get('id') != PRODUCT_ID or not base.is_absolute() or '..' in base.parts or
            product.get('is_complete') is not True or product.get('is_launchable') is not True or
            product.get('is_reboot_required') is not False or
            version_tuple(product.get('installation_version'))[0] != 17):
        raise RuntimeError('Community installation is incomplete or has the wrong product/version')
    installer = proof.get('installer', {})
    if (installer.get('url') != 'https://aka.ms/vs/17/release/vs_community.exe' or
            not signed_by_microsoft(installer) or not re.fullmatch('[0-9a-f]{64}', installer.get('sha256', '')) or
            installer.get('community_license_accepted') is not True or
            type(installer.get('exit_code')) is not int or installer['exit_code'] != 0 or
            set(installer.get('requested_components', [])) != {'Microsoft.VisualStudio.Component.VC.Tools.x86.x64',
                                                              'Microsoft.VisualStudio.Component.VC.Redist.14.Latest'}):
        raise RuntimeError('Official signed Community installer evidence is missing')
    tool = proof.get('tool', {})
    tool_path = PureWindowsPath(tool.get('path', ''))
    if (not tool_path.is_relative_to(base) or tool_path.name.casefold() != 'dumpbin.exe' or
            not re.fullmatch(r'vc/tools/msvc/\d+\.\d+\.\d+/bin/hostx64/x64/dumpbin\.exe', tool_path.relative_to(base).as_posix().casefold()) or
            tool.get('used') != 'dumpbin /headers' or tool.get('dependency_check') != 'dumpbin /dependents' or
            not signed_by_microsoft(tool) or
            not re.fullmatch('[0-9a-f]{64}', tool.get('sha256', ''))):
        raise RuntimeError('Licensed Community inspection tool was not used')
    files = proof.get('files')
    if not isinstance(files, list) or len(files) != len(RUNTIME_DLLS) or {row.get('filename') for row in files} != RUNTIME_DLLS:
        raise RuntimeError('Unexpected Microsoft release runtime inventory')
    for row in files:
        source = PureWindowsPath(row.get('source_path', ''))
        try:
            relative = source.relative_to(base).as_posix().casefold()
        except ValueError as exc:
            raise RuntimeError('Microsoft runtime is outside the licensed Community installation') from exc
        if (not re.fullmatch(r'vc/redist/msvc/\d+\.\d+\.\d+/x64/microsoft\.vc143\.crt/' + re.escape(row['filename']), relative) or
                version_tuple(row.get('file_version')) < MINIMUM_VERSION or version_tuple(row.get('file_version'))[0] != 14 or
                row.get('machine') != 'x64' or not signed_by_microsoft(row) or
                type(row.get('size')) is not int or not 1024 <= row['size'] <= 20 * 1024 * 1024 or
                not re.fullmatch('[0-9a-f]{64}', row.get('sha256', ''))):
            raise RuntimeError('Invalid, debug, unsigned, old or unreviewed Microsoft runtime: ' + row['filename'])
        dependencies = row.get('dependencies')
        if (not isinstance(dependencies, list) or not dependencies or len(dependencies) > 100 or
                len(set(dependencies)) != len(dependencies) or not all(isinstance(name, str) and allowed_dependency(name) for name in dependencies)):
            raise RuntimeError('Microsoft runtime depends on an unreviewed or unbundled DLL: ' + row['filename'])
    return proof


def load_runtime_provenance(folder=RUNTIME_ROOT):
    return verify_provenance(json.loads((Path(folder) / 'provenance.json').read_text(encoding='utf-8-sig')))


def verify_source_files(folder=RUNTIME_ROOT):
    folder = Path(folder)
    proof = load_runtime_provenance(folder)
    for row in proof['files']:
        path = folder / row['filename']
        if path.is_symlink() or not path.is_file() or path.stat().st_size != row['size'] or hashlib.sha256(path.read_bytes()).hexdigest() != row['sha256']:
            raise RuntimeError('Serviced Microsoft runtime source bytes changed: ' + row['filename'])
    return proof


def replace_runtime_entries(entries, folder=RUNTIME_ROOT):
    """Replace every matching root/package copy with the same licensed source file."""
    verify_source_files(folder)
    reject_unreviewed_runtime_names([name for name, _source, _kind in entries])
    return [(name, str(Path(folder) / Path(name.replace('\\', '/')).name.casefold()), kind)
            if Path(name.replace('\\', '/')).name.casefold() in RUNTIME_DLLS else (name, source, kind)
            for name, source, kind in entries]


def verify_embedded_runtime(archive, proof=None):
    reject_unreviewed_runtime_names(archive.toc)
    proof = verify_provenance(proof) if proof is not None else verify_source_files()
    expected = {row['filename']: row for row in proof['files']}
    paths = {name.replace('\\', '/').casefold(): name for name in archive.toc
             if name.replace('\\', '/').rsplit('/', 1)[-1].casefold() in RUNTIME_DLLS}
    required = {'pyside6/' + name for name in RUNTIME_DLLS} | {'msvcp140.dll', 'vcruntime140.dll', 'vcruntime140_1.dll'}
    if not required <= paths.keys():
        raise RuntimeError('Required licensed Microsoft runtime archive paths are missing')
    rows = []
    for path, original in sorted(paths.items()):
        row = expected[path.rsplit('/', 1)[-1]]
        data = archive.extract(original)
        if not isinstance(data, bytes) or len(data) != row['size'] or hashlib.sha256(data).hexdigest() != row['sha256']:
            raise RuntimeError('Embedded Microsoft runtime bytes differ from licensed source: ' + path)
        rows.append({'path': path, 'size': row['size'], 'sha256': row['sha256']})
    return {'provenance': proof, 'embedded_files': rows}


def verify_runtime_evidence(bundle, qt_paths):
    proof = verify_provenance(bundle.get('provenance', {}))
    expected = {row['filename']: row for row in proof['files']}
    rows = bundle.get('embedded_files', [])
    required = {'pyside6/' + name for name in RUNTIME_DLLS} | {'msvcp140.dll', 'vcruntime140.dll', 'vcruntime140_1.dll'}
    paths = set()
    for row in rows:
        path = row.get('path', '')
        name = path.rsplit('/', 1)[-1]
        if (path in paths or path.startswith('/') or '\\' in path or '..' in path.split('/') or
                name not in expected or row.get('size') != expected[name]['size'] or row.get('sha256') != expected[name]['sha256']):
            raise RuntimeError('Microsoft archive/source correspondence changed')
        paths.add(path)
    if (not required <= paths or not {'pyside6/' + name for name in RUNTIME_DLLS} <= qt_paths or
            {path for path in qt_paths if path.rsplit('/', 1)[-1] in RUNTIME_DLLS} != {path for path in paths if path.startswith('pyside6/')}):
        raise RuntimeError('Microsoft archive runtime paths are missing or differ from inventory')
    return proof


def verify_notice_bytes(read_bytes):
    for name, expected in NOTICE_HASHES.items():
        if hashlib.sha256(read_bytes(name)).hexdigest() != expected:
            raise RuntimeError('Microsoft component terms/notice missing or changed: ' + name)


def copy_notices(destination, runtime_folder=RUNTIME_ROOT):
    verify_notice_bytes(lambda name: (NOTICE_ROOT / name).read_bytes())
    proof = verify_source_files(runtime_folder)
    destination = Path(destination) / 'microsoft-runtime'
    destination.mkdir(parents=True, exist_ok=True)
    for source in NOTICE_ROOT.iterdir():
        if source.is_file() and not source.is_symlink():
            shutil.copyfile(source, destination / source.name)
    (destination / 'BUILD-PROVENANCE.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return sorted('microsoft-runtime/' + path.name for path in destination.iterdir())


def verify_notice_archive(archive, bundle):
    verify_notice_bytes(lambda name: archive.read('microsoft-runtime/' + name))
    if json.loads(archive.read('microsoft-runtime/BUILD-PROVENANCE.json')) != bundle['provenance']:
        raise RuntimeError('Microsoft license/source provenance differs from build evidence')

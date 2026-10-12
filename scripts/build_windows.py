"""Build a redistributable Windows x64 EXE. Run in the pinned build virtualenv."""
from __future__ import annotations
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app_version import __version__
from model_inventory import verify_models


def sha256(path):
    with Path(path).open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def collect_licenses(destination):
    """Retain supplied wheel licenses/notices, including model notices, verbatim."""
    destination.mkdir(parents=True, exist_ok=True)
    inventory = []
    for distribution in sorted(metadata.distributions(), key=lambda item: item.metadata['Name'].casefold()):
        name = distribution.metadata['Name']
        found = []
        for entry in distribution.files or []:
            if not any(word in entry.name.casefold() for word in ('license', 'licence', 'notice', 'copying', 'copyright')):
                continue
            source = Path(distribution.locate_file(entry))
            if not source.is_file() or source.suffix.lower() in {'.py', '.pyc', '.pyd', '.dll'}:
                continue
            # Flatten wheel-relative names to avoid absolute or parent paths.
            target = destination / name / str(entry).replace('/', '__').replace('\\', '__').replace(':', '_')
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            found.append(str(target.relative_to(destination)))
        inventory.append({'name': name, 'version': distribution.version, 'license_files': found,
                          'license_expression': distribution.metadata.get('License-Expression')})
    python_license = Path(sys.base_prefix) / 'LICENSE.txt'
    if not python_license.is_file():
        raise RuntimeError('Python runtime LICENSE.txt missing; do not distribute without it')
    shutil.copyfile(python_license, destination / 'PYTHON-LICENSE.txt')
    shutil.copyfile(ROOT / 'LICENSE', destination / 'VGA-APP-LICENSE.txt')
    shutil.copyfile(ROOT / 'THIRD_PARTY_NOTICES.md', destination / 'THIRD_PARTY_NOTICES.md')
    (destination / 'dependency-inventory.json').write_text(json.dumps(inventory, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    required = ('rapidocr', 'onnxruntime', 'numpy', 'pillow', 'opencv-python-headless')
    for name in required:
        row = next((row for row in inventory if row['name'].casefold() == name), None)
        if not row or not row['license_files']:
            raise RuntimeError(f'Missing required bundled license: {name}')
    return inventory


def release_manifest(exe, version=__version__):
    filename = f'vga-aram-helper-{version}-windows-x64.exe'
    return {'schema_version': 1, 'version': version, 'platform': 'windows-x64',
            'url': f'https://github.com/Junming-Liang/vga-aram-helper/releases/download/v{version}/{filename}',
            'sha256': sha256(exe), 'size': Path(exe).stat().st_size}


def assert_archive_inventory(names):
    """Catch a superficially successful build that relies on CI-only runtimes."""
    normalized = {str(name).replace('\\', '/').lower() for name in names}
    basenames = {name.rsplit('/', 1)[-1] for name in normalized}
    required = {'python312.dll', 'vcruntime140.dll', 'vcruntime140_1.dll', 'msvcp140.dll'}
    missing = sorted(required - basenames)
    for name in ('PP-OCRv6_det_small.onnx', 'PP-OCRv6_rec_small.onnx', 'ch_ppocr_mobile_v2.0_cls_mobile.onnx'):
        if 'rapidocr/models/' + name.lower() not in normalized:
            missing.append('rapidocr/models/' + name)
    for name in ('static/index.html', 'fixtures/ocr-synthetic.png', 'fixtures/ocr-blank.png', 'assets/branding/vga.ico'):
        if name not in normalized:
            missing.append(name)
    if missing:
        raise RuntimeError('Standalone EXE is missing bundled resources/runtime DLLs: ' + ', '.join(missing))
    return {'entries': len(normalized), 'required_runtime_dlls': sorted(required),
            'model_assets': 3, 'icon': 'assets/branding/vga.ico'}


def write_version_resource(path, version):
    parts = tuple(int(piece) for piece in version.split('.'))
    if len(parts) != 3 or any(piece < 0 or piece > 65535 for piece in parts):
        raise ValueError('Windows product version must be three 16-bit integers')
    numeric = repr(parts + (0,))
    fields = {
        'CompanyName': 'VGA Aram Helper contributors',
        'FileDescription': 'VGA乱斗助手',
        'FileVersion': version,
        'InternalName': 'VGA-Aram-Helper',
        'OriginalFilename': 'VGA-Aram-Helper.exe',
        'ProductName': 'VGA乱斗助手',
        'ProductVersion': version,
    }
    strings = ', '.join(f'StringStruct({key!r}, {value!r})' for key, value in fields.items())
    source = f"VSVersionInfo(ffi=FixedFileInfo(filevers={numeric}, prodvers={numeric}, mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)), kids=[StringFileInfo([StringTable('040904B0', [{strings}])]), VarFileInfo([VarStruct('Translation', [1033, 1200])])])\n"
    Path(path).write_text(source, encoding='utf-8')


def main():
    if sys.platform != 'win32' or platform.machine().lower() not in {'amd64', 'x86_64'} or sys.maxsize <= 2**32:
        raise SystemExit('Build on native Windows x64 with 64-bit Python. PyInstaller is not a cross-compiler.')
    os.chdir(ROOT)
    models = verify_models()
    build = ROOT / 'build'
    build.mkdir(exist_ok=True)
    licenses = build / 'licenses'
    if licenses.exists():
        shutil.rmtree(licenses)
    inventory = collect_licenses(licenses)
    write_version_resource(build / 'version_info.txt', __version__)
    # Limit cleanup to generated packaging output. Never delete app data/cache.
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean',
                    '--distpath', str(ROOT / 'dist'), '--workpath', str(build / 'pyinstaller'),
                    str(ROOT / 'packaging' / 'VGA-Aram-Helper.spec')], check=True, cwd=ROOT)
    executable = ROOT / 'dist' / 'VGA-Aram-Helper.exe'
    if not executable.is_file() or executable.stat().st_size < 30_000_000:
        raise RuntimeError('Expected bundled executable missing or implausibly small')
    from PyInstaller.archive.readers import CArchiveReader
    bundled = assert_archive_inventory(CArchiveReader(str(executable)).toc)
    release = ROOT / 'dist' / 'release'
    release.mkdir(exist_ok=True)
    named = release / f'vga-aram-helper-{__version__}-windows-x64.exe'
    shutil.copyfile(executable, named)
    manifest = release_manifest(named)
    (release / 'update-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    (release / 'SHA256SUMS.txt').write_text(f"{manifest['sha256']}  {named.name}\n", encoding='ascii')
    shutil.make_archive(str(release / 'third-party-licenses'), 'zip', licenses)
    for document in ('WINDOWS_EXECUTABLE.md', 'THIRD_PARTY_NOTICES.md', 'LICENSE'):
        shutil.copyfile(ROOT / document, release / document)
    report = {'status': 'built-not-yet-smoke-tested', 'version': __version__, 'platform': platform.platform(),
              'python': platform.python_version(), 'source_commit': os.environ.get('GITHUB_SHA'),
              'manifest': manifest, 'bundled_models': models, 'archive_inventory': bundled, 'dependencies': inventory,
              'signature': 'Unsigned; no Authenticode or SmartScreen reputation claim.'}
    reports = ROOT / 'reports'
    reports.mkdir(exist_ok=True)
    (reports / 'windows-build.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    main()

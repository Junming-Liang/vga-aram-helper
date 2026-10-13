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
from scripts.qt_licenses import QT_VERSION, copy_bundle, supply_sources
from scripts.microsoft_runtime import verify_embedded_runtime, copy_notices
from scripts.windows_package import EXPERIMENT_PROFILE, assert_slim_inventory, measure_archive, package_profile
from scripts.minimal_opencv_package import (check_build_mode, copy_custom_licenses,
                                           validate_build_profile, verify_custom_archive)


def sha256(path):
    with Path(path).open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def verify_source_checkout(root, expected_commit=None):
    """Only a clean tracked checkout may claim an exact source correspondence."""
    root = Path(root)
    try:
        commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
        subprocess.run(['git', 'diff', 'HEAD', '--exit-code', '--quiet'], cwd=root, check=True)
        others = subprocess.check_output(['git', 'ls-files', '--others', '--exclude-standard', '-z'], cwd=root).decode('utf-8').split('\0')
        tracked = set(subprocess.check_output(['git', 'ls-files', '-z'], cwd=root).decode('utf-8').split('\0'))
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RuntimeError('Build requires a clean Git checkout; commit source changes before packaging') from exc
    if expected_commit and commit != expected_commit:
        raise RuntimeError('Checkout commit differs from the requested build commit')
    for name in filter(None, others):
        if not (name.startswith('reports/windows-') and '/' not in name[len('reports/'):]):
            raise RuntimeError('Untracked build input: ' + name)
    # Also catch ignored additions inside runtime/build input directories, which
    # git --exclude-standard intentionally omits. Generated outputs are outside
    # these trees. Bytecode caches never become source archive inputs.
    inputs = [path for path in root.iterdir() if path.is_file()]
    for folder in ('static', 'fixtures', 'assets', 'packaging', 'scripts', 'tests', '.github'):
        inputs.extend(path for path in (root / folder).rglob('*') if path.is_file()
                      and '__pycache__' not in path.parts and path.suffix != '.pyc')
    for path in inputs:
        relative = path.relative_to(root).as_posix()
        if path.is_symlink() or relative not in tracked:
            raise RuntimeError('Untracked or symbolic build input: ' + relative)
    return commit


def collect_licenses(destination):
    """Retain supplied wheel licenses/notices, including model notices, verbatim."""
    destination.mkdir(parents=True, exist_ok=True)
    for package in ('PySide6-Essentials', 'shiboken6'):
        if metadata.version(package) != QT_VERSION:
            raise RuntimeError('Qt dependency version changed; regenerate exact-version licenses')
    _, qt_license_files = copy_bundle(ROOT / 'packaging' / 'qt-licenses', destination)
    microsoft_license_files = copy_notices(destination)
    custom_license_files = copy_custom_licenses(destination)
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
        if name.casefold().replace('-', '_') in {'pyside6_essentials', 'shiboken6'}:
            found += qt_license_files
        if name.casefold().replace('-', '_') == 'opencv_python_headless':
            found += custom_license_files
        inventory.append({'name': name, 'version': distribution.version, 'license_files': found,
                          'license_expression': distribution.metadata.get('License-Expression')})
    python_license = Path(sys.base_prefix) / 'LICENSE.txt'
    if not python_license.is_file():
        raise RuntimeError('Python runtime LICENSE.txt missing; do not distribute without it')
    shutil.copyfile(python_license, destination / 'PYTHON-LICENSE.txt')
    shutil.copyfile(ROOT / 'LICENSE', destination / 'VGA-APP-LICENSE.txt')
    shutil.copyfile(ROOT / 'THIRD_PARTY_NOTICES.md', destination / 'THIRD_PARTY_NOTICES.md')
    inventory.append({'name': 'Microsoft Visual C++ Runtime', 'license_expression': 'LicenseRef-Microsoft-Visual-Cpp-Runtime',
                      'license_files': microsoft_license_files, 'version': 'See microsoft-runtime/BUILD-PROVENANCE.json'})
    (destination / 'dependency-inventory.json').write_text(json.dumps(inventory, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    required = ('rapidocr', 'onnxruntime', 'numpy', 'pillow', 'opencv-python-headless', 'pyside6_essentials', 'shiboken6')
    for name in required:
        row = next((row for row in inventory if row['name'].casefold().replace('-', '_') == name.replace('-', '_')), None)
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
    required = {'python312.dll', 'vcruntime140.dll', 'vcruntime140_1.dll', 'msvcp140.dll', 'qt6core.dll', 'qt6gui.dll', 'qt6widgets.dll', 'qwindows.dll'}
    missing = sorted(required - basenames)
    if any('webengine' in name for name in normalized):
        raise RuntimeError('Unexpected WebEngine/browser runtime in native QtWidgets package')
    if {'opengl32sw.dll', 'd3dcompiler_47.dll'} & basenames:
        raise RuntimeError('Unexpected optional OpenGL/shader runtime in raster QtWidgets package')
    if {'qopensslbackend.dll', 'qpdf.dll', 'qt6pdf.dll', 'qt6pdfwidgets.dll'} & basenames:
        raise RuntimeError('Unexpected optional Qt OpenSSL/PDF plugin in native package')
    if 'qtuiotouchplugin.dll' in basenames:
        raise RuntimeError('Unexpected optional TUIO network input plugin in native package')
    for name in ('PP-OCRv6_det_small.onnx', 'PP-OCRv6_rec_small.onnx', 'ch_ppocr_mobile_v2.0_cls_mobile.onnx'):
        if 'rapidocr/models/' + name.lower() not in normalized:
            missing.append('rapidocr/models/' + name)
    for name in ('static/index.html', 'fixtures/ocr-synthetic.png', 'fixtures/ocr-blank.png', 'assets/branding/vga.ico'):
        if name not in normalized:
            missing.append(name)
    if missing:
        raise RuntimeError('Standalone EXE is missing bundled resources/runtime DLLs: ' + ', '.join(missing))
    return {'entries': len(normalized), 'required_runtime_dlls': sorted(required),
            'qt_binaries': sorted(name for name in normalized if name.endswith(('.dll', '.pyd'))
                                  and ('pyside6/' in name or name.rsplit('/', 1)[-1].startswith('qt6'))),
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
    source_commit = verify_source_checkout(ROOT, os.environ.get('GITHUB_SHA'))
    profile = package_profile()
    custom_build = check_build_mode()
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
    archive = CArchiveReader(str(executable))
    bundled = assert_archive_inventory(archive.toc)
    if custom_build:
        verify_custom_archive(archive, custom_build)
    bundled['microsoft_runtime'] = verify_embedded_runtime(archive)
    assert_slim_inventory(archive.toc, profile=profile)
    size_report = measure_archive(archive, executable, profile=profile)
    size_report['source_commit'] = source_commit
    size_report['pruning'] = json.loads((build / 'windows-packaging-prune.json').read_text(encoding='utf-8'))
    reports = ROOT / 'reports'
    reports.mkdir(exist_ok=True)
    (reports / 'windows-package-size.json').write_text(json.dumps(size_report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'package_size': size_report}, indent=2), flush=True)
    if size_report['status'] != 'passed':
        raise RuntimeError('Windows package size regression: see reports/windows-package-size.json')
    print(json.dumps({'qt_binaries': bundled['qt_binaries']}, indent=2), flush=True)
    print(json.dumps({'licensed_microsoft_runtime': bundled['microsoft_runtime']}, indent=2), flush=True)
    release = ROOT / 'dist' / 'release'
    release.mkdir(exist_ok=True)
    named = release / f'vga-aram-helper-{__version__}-windows-x64.exe'
    shutil.copyfile(executable, named)
    manifest = release_manifest(named)
    (release / 'update-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    (release / 'SHA256SUMS.txt').write_text(f"{manifest['sha256']}  {named.name}\n", encoding='ascii')
    shutil.make_archive(str(release / 'third-party-licenses'), 'zip', licenses)
    qt_sources = supply_sources(ROOT / 'packaging' / 'qt-licenses', release)
    # Recheck after packaging so generated changes cannot silently alter inputs.
    if verify_source_checkout(ROOT, source_commit) != source_commit:
        raise RuntimeError('Source checkout changed during packaging')
    app_source = release / f'vga-aram-helper-{__version__}-source.zip'
    subprocess.run(['git', 'archive', '--format=zip', '--output', str(app_source), source_commit], cwd=ROOT, check=True)
    source_access = {'source_commit': source_commit, 'application_source': {'filename': app_source.name,
                     'sha256': sha256(app_source), 'size': app_source.stat().st_size}, 'qt_sources': qt_sources}
    (release / 'source-access.json').write_text(json.dumps(source_access, indent=2) + '\n', encoding='utf-8')
    for document in ('WINDOWS_EXECUTABLE.md', 'THIRD_PARTY_NOTICES.md', 'LICENSE'):
        shutil.copyfile(ROOT / document, release / document)
    report = {'status': 'built-not-yet-smoke-tested', 'version': __version__, 'platform': platform.platform(),
              'python': platform.python_version(), 'source_commit': source_commit,
              'manifest': manifest, 'bundled_models': models, 'archive_inventory': bundled, 'dependencies': inventory,
              'source_access': source_access, 'package_size': size_report,
              'package_profile': profile, 'experimental': profile == EXPERIMENT_PROFILE,
              'opencv_custom_build': custom_build,
              'signature': 'Unsigned; no Authenticode or SmartScreen reputation claim.'}
    validate_build_profile(report)
    reports = ROOT / 'reports'
    reports.mkdir(exist_ok=True)
    (reports / 'windows-build.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    main()

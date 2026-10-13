"""Build an explicitly opted-in, locally identified OpenCV Windows experiment.

Source/configuration pins make the procedure repeatable, not byte-reproducible
across serviced Community compilers or runner SDKs. Production adoption requires
separate exact-binary Windows parity and application acceptance gates.
"""
from __future__ import annotations
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import shutil
import stat
import struct
import subprocess
import sys
import tarfile
import time
import urllib.request
import zipfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts import microsoft_runtime

VERSION = '5.0.0.93+vga1'
SOURCE_FOLDER = 'opencv_python_headless-5.0.0.93'
OUTPUT = ROOT / 'build' / 'minimal-opencv'
PATCH = ROOT / 'packaging' / 'opencv-minimal-patch.py'
REQUIREMENTS = ROOT / 'packaging' / 'opencv-build-requirements.txt'
MODULES = {'core', 'flann', 'geometry', 'imgcodecs', 'imgproc', 'python3'}
DISPATCH = ['SSE4_1', 'SSE4_2', 'AVX', 'FP16', 'AVX2', 'AVX512_SKX']
ASSETS = {
    'source': {
        'url': 'https://files.pythonhosted.org/packages/1d/99/76b7c80252aa83c1af16393454aafd125a0287101afe8deb0a6821af0e30/opencv_python_headless-5.0.0.93.tar.gz',
        'sha256': 'b82f9831daab90b725c7c1ee1b36cb5732c367096ac76d119e64e14eb70d5f3c',
        'size': 81_817_738, 'filename': SOURCE_FOLDER + '.tar.gz',
    },
    'ipp': {
        'url': 'https://raw.githubusercontent.com/opencv/opencv_3rdparty/406d398c436d0465c8e53dd432d9ecd9301d5f4a/ippicv/ippicv_2026.0.0_win_intel64_20260327_general.zip',
        'sha256': 'cf1560b05cc67795852d4ec32ce58ceee466a8d996404af27dfaaea5f1da2760',
        'size': 26_382_666,
        'filename': 'ippicv_2026.0.0_win_intel64_20260327_general.zip',
        'cache': 'ippicv/73bc67cd5e4c8da706fa88fe84630231-ippicv_2026.0.0_win_intel64_20260327_general.zip',
    },
    'nasm': {
        'url': 'https://www.nasm.us/pub/nasm/releasebuilds/2.16.03/win64/nasm-2.16.03-win64.zip',
        'sha256': '3ee4782247bcb874378d02f7eab4e294a84d3d15f3f6ee2de2f47a46aa7226e6',
        'size': 513543, 'filename': 'nasm-2.16.03-win64.zip',
        'checksum_origin': 'Locally computed from exact official HTTPS vendor bytes; no publisher-signed checksum was available.',
    },
    'font': {
        'url': 'https://raw.githubusercontent.com/vpisarev/opencv_3rdparty/cc7d85179d69a704bee209aa37ce8a657f2f8b34/WenQuanYiMicroHei.ttf.gz',
        'sha256': '70c5634fe8326a20a18f4d634d08c510f2c05f6613d2d5aa3566f162cc02804f',
        'size': 2_104_595, 'filename': 'WenQuanYiMicroHei.ttf.gz',
        'cache': 'unifont/fb79cf5b4f4c89414f1233f14c2eb273-WenQuanYiMicroHei.ttf.gz',
    },
}
BUILD_DEPENDENCIES = {'pip': '25.0.1', 'cmake': '4.3.2', 'scikit-build': '0.18.1',
                      'setuptools': '69.5.1', 'wheel': '0.45.1', 'numpy': '2.0.2',
                      'packaging': '26.3', 'distro': '1.9.0'}
OPTIONS = {
    'BUILD_LIST': 'core,imgproc,imgcodecs,python3', 'PYTHON3_LIMITED_API': 'ON',
    # Mirror upstream Windows CI: generic ASM can select GCC and corrupt .lib naming.
    # Dedicated pinned ASM_NASM remains enabled for libjpeg-turbo SIMD.
    'CMAKE_ASM_COMPILER': '',
    'BUILD_SHARED_LIBS': 'OFF', 'BUILD_WITH_STATIC_CRT': 'ON',
    'BUILD_TESTS': 'OFF', 'BUILD_PERF_TESTS': 'OFF', 'BUILD_EXAMPLES': 'OFF',
    'BUILD_opencv_apps': 'OFF', 'BUILD_DOCS': 'OFF',
    'WITH_IPP': 'ON', 'BUILD_IPP_IW': 'ON', 'WITH_OPENCL': 'ON',
    'WITH_LAPACK': 'ON', 'BUILD_CLAPACK': 'ON', 'WITH_EIGEN': 'OFF',
    'WITH_UNIFONT': 'ON', 'WITH_ITT': 'ON', 'ENABLE_FAST_MATH': 'OFF',
    'OPENCV_ALGO_HINT_DEFAULT': 'ALGO_HINT_ACCURATE', 'CPU_BASELINE': 'SSE3',
    'CPU_DISPATCH': ','.join(DISPATCH),
    'WITH_JPEG': 'ON', 'BUILD_JPEG': 'ON', 'WITH_PNG': 'ON', 'BUILD_PNG': 'ON',
    'WITH_WEBP': 'ON', 'BUILD_WEBP': 'ON', 'BUILD_ZLIB': 'ON',
    **{key: 'OFF' for key in ('WITH_FFMPEG', 'WITH_GSTREAMER', 'WITH_V4L',
        'WITH_MSMF', 'WITH_DSHOW', 'WITH_OBSENSOR', 'WITH_AVIF', 'WITH_TIFF',
        'WITH_OPENJPEG', 'WITH_JASPER', 'WITH_OPENEXR', 'BUILD_OPENEXR',
        'WITH_IMGCODEC_GIF', 'WITH_IMGCODEC_HDR', 'WITH_IMGCODEC_SUNRASTER',
        'WITH_IMGCODEC_PXM', 'WITH_IMGCODEC_PFM')},
}
GENERATED_LICENSES = {'SoftFloat-COPYING.txt': {'size': 1732, 'sha256': '0c5b08365136da52639d777f1ebfc03988b0169d80655c90c59f1b3fa3e526a2'}, 'clapack-lapack_LICENSE': {'size': 2266, 'sha256': 'd56bd4441b999b80c88df04faf0d8b3d7d3b2bd781cf91242c4188e8a6d0f8be'}, 'dlpack-LICENSE': {'size': 11345, 'sha256': '3e8f6bc39276a586d60c8c5aaece2ff989262181cf2b3d2a128db58f97a9300c'}, 'flatbuffers-LICENSE.txt': {'size': 11358, 'sha256': 'cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30'}, 'fonts-Rubik_OFL.txt': {'size': 4383, 'sha256': '521fa3f83e0b1a4dc0163fff2d31445c6d38c103e47a19abc8f49b4f7b1818e4'}, 'ippicv-EULA.rtf': {'size': 68409, 'sha256': '37f11c79f36fb5e1b00aca31c1234a7435c2929d83e181ee802a349ca8571749'}, 'ippicv-readme.htm': {'size': 6894, 'sha256': '2fbc6125275ebb4fe17dcbfdf987e8cac1694a15fd5d73aa8861b69015ae6ccf'}, 'ippicv-third-party-programs.txt': {'size': 284, 'sha256': '75b8e68f815cefc85d58b644ce9e868f5194ffe79901fd697768dce42c3ca6ce'}, 'ippiw-EULA.rtf': {'size': 68409, 'sha256': '37f11c79f36fb5e1b00aca31c1234a7435c2929d83e181ee802a349ca8571749'}, 'ippiw-support.txt': {'size': 362, 'sha256': '47ad017f2b08d3944ae9f55305e1b125296185f63548130c7f145a62371e9f38'}, 'ippiw-third-party-programs.txt': {'size': 284, 'sha256': '75b8e68f815cefc85d58b644ce9e868f5194ffe79901fd697768dce42c3ca6ce'}, 'ittnotify-BSD-3-Clause.txt': {'size': 1485, 'sha256': 'cf48cdd9ed87c2031b68fb1b9f4cfb55d00dcf815b21a30bf8304aa1e5e6f76a'}, 'ittnotify-GPL-2.0-only.txt': {'size': 17599, 'sha256': 'cbe0f9505c5ca02ee34bfca453df31a98e31e6d56afcdf8ab0f87f4c94f1181b'}, 'libjpeg-turbo-LICENSE.md': {'size': 5620, 'sha256': '96f5b328adbb78eeaaec6980d73fd558cb1e4d62560ed615646bc3cf5e532430'}, 'libjpeg-turbo-README.ijg': {'size': 12799, 'sha256': '75815e3bf6484201a3c3d17a1bbf10f2e8e3237f84df10a2357ea896db2a81d6'}, 'libjpeg-turbo-README.md': {'size': 17784, 'sha256': 'c553459fc4ea1f69526f0edf0c8ff6c4002fda5b76094abefabdc3de1ee62c10'}, 'libpng-LICENSE': {'size': 5345, 'sha256': 'bdb0a645ea18c60507d0368379b1ac5474b92255fcc2d115e07486a7672ba526'}, 'libpng-README': {'size': 9485, 'sha256': '513658508b1c663bd2cfa814d4de84f0ef6d1bf7d7ff5e84c5f58fb3d3215774'}, 'opencl-headers-LICENSE.txt': {'size': 1309, 'sha256': 'cfaceadff07c2c9458283079cd0166872aa2d93d5c480f1f417be321aa7e0f4d'}, 'protobuf-LICENSE': {'size': 1732, 'sha256': '6e5e117324afd944dcf67f36cf329843bc1a92229a8cd9bb573d7a83130fea7d'}, 'protobuf-README.md': {'size': 134, 'sha256': 'aa924b1ceb243a25b4ff4a0360dc124a58d22633e9f6de02167d162b86968324'}, 'zlib-LICENSE': {'size': 1002, 'sha256': 'e32ff4e00d9d94930537635291da39e7e612703334bf6fde8c7f1686fe8a45a2'}}
FONT_NOTICE = '''WenQuanYi Micro Hei, unmodified font embedded by OpenCV 5.0.0.
Digitized data copyright © 2007, Google Corporation.
Copyright © 2008-2009 WenQuanYi Board of Trustees (http://wenq.org/) and Qianqian Fang
Licensed under the Apache License, Version 2.0.
The exact downloaded font's name-table records supply these notices.
See OPENCV-APACHE-LICENSE.txt and https://www.apache.org/licenses/LICENSE-2.0
'''


def digest(data):
    return hashlib.sha256(data).hexdigest()


def write_utf8(path, value):
    # Explicit bytes avoid Windows newline translation in hash-bound notices.
    Path(path).write_bytes(value.encode('utf-8'))


def file_record(path, relative_to=None):
    path = Path(path)
    ensure_regular(path)
    return {'path': path.relative_to(relative_to).as_posix() if relative_to else str(path),
            'size': path.stat().st_size, 'sha256': digest(path.read_bytes())}


def ensure_regular(path):
    path = Path(path)
    if not path.is_file():
        raise RuntimeError('Expected regular file: ' + str(path))
    for part in (path, *path.parents):
        attributes = getattr(part.lstat(), 'st_file_attributes', 0)
        if part.is_symlink() or attributes & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400):
            raise RuntimeError('Linked/reparse build input is not accepted: ' + str(part))
    return path


def verify_asset(path, asset):
    actual = file_record(path)
    if actual['size'] != asset['size'] or actual['sha256'] != asset['sha256']:
        raise RuntimeError('Pinned OpenCV asset bytes changed: ' + asset['filename'])
    return {**asset, 'path': str(path)}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError('Unexpected redirect for pinned OpenCV source asset')


def download_asset(asset, destination):
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise RuntimeError('Refusing to overwrite a build download')
    opener = urllib.request.build_opener(NoRedirect)
    with opener.open(asset['url'], timeout=90) as response, destination.open('xb') as out:
        if response.status != 200:
            raise RuntimeError('Unexpected OpenCV download status')
        size = 0
        while chunk := response.read(1024 * 1024):
            size += len(chunk)
            if size > asset['size']:
                raise RuntimeError('OpenCV asset exceeded its exact pinned size')
            out.write(chunk)
    return verify_asset(destination, asset)


def safe_member_name(name):
    if not isinstance(name, str) or not name or '\\' in name or ':' in name or '\x00' in name:
        raise RuntimeError('Unsafe source archive path')
    parts = name.rstrip('/').split('/')
    reserved = {'con', 'prn', 'aux', 'nul', *(f'com{i}' for i in range(1, 10)), *(f'lpt{i}' for i in range(1, 10))}
    if (PurePosixPath(name).is_absolute() or any(p in {'', '.', '..'} or p.endswith((' ', '.')) or
            p.split('.')[0].casefold() in reserved for p in parts)):
        raise RuntimeError('Unsafe source archive path: ' + name)
    return parts


def extract_nasm(archive, destination):
    """Copy only the approved compiler and notice from the exact vendor ZIP."""
    verify_asset(archive, ASSETS['nasm'])
    destination = Path(destination)
    if destination.exists():
        raise RuntimeError('NASM destination must be fresh')
    with zipfile.ZipFile(archive) as package:
        names = package.namelist()
        expected = {'nasm-2.16.03/LICENSE', 'nasm-2.16.03/nasm.exe', 'nasm-2.16.03/ndisasm.exe'}
        if len(names) != 3 or set(names) != expected:
            raise RuntimeError('Unexpected official NASM ZIP members')
        for item in package.infolist():
            safe_member_name(item.filename)
            mode = item.external_attr >> 16
            if stat.S_ISLNK(mode) or item.file_size > 5_000_000:
                raise RuntimeError('Linked or oversized NASM ZIP member')
        binary = package.read('nasm-2.16.03/nasm.exe')
        notice = package.read('nasm-2.16.03/LICENSE')
        if (len(binary) != 1_650_688 or digest(binary) != 'a93276636266516421cc9b422f47476c21f7a2949f1ae251556b2f1d33a3be04'
                or len(notice) != 1550 or digest(notice) != '7c22a2d3d099a1167c281e437f48340dfad88634630c97afee927e5705626f7a'):
            raise RuntimeError('NASM executable/license bytes changed')
        offset = struct.unpack_from('<I', binary, 0x3c)[0]
        if binary[:2] != b'MZ' or binary[offset:offset+4] != b'PE\0\0' or struct.unpack_from('<H', binary, offset+4)[0] != 0x8664:
            raise RuntimeError('NASM is not the pinned Windows x64 executable')
        destination.mkdir(parents=True)
        (destination/'nasm.exe').write_bytes(binary)
        (destination/'LICENSE').write_bytes(notice)
    return destination/'nasm.exe'


def extract_source(archive, destination):
    """Validate the complete member list before creating any output files."""
    destination = Path(destination)
    if destination.exists():
        raise RuntimeError('Source extraction destination must be fresh')
    with tarfile.open(archive, 'r:gz') as source:
        members = source.getmembers()
        if len(members) > 20_000 or sum(m.size for m in members) > 500_000_000:
            raise RuntimeError('Source archive exceeds bounded extraction limits')
        seen = set(); kinds = {}
        for member in members:
            parts = safe_member_name(member.name)
            key = '/'.join(parts).casefold()
            if parts[0] != SOURCE_FOLDER or key in seen or not (member.isfile() or member.isdir()):
                raise RuntimeError('Unexpected, duplicate or linked source archive member')
            if member.size < 0 or member.size > 100_000_000:
                raise RuntimeError('Source member exceeds its size limit')
            if len(parts) == 1 and not member.isdir():
                raise RuntimeError('Source root must be a directory')
            seen.add(key); kinds[key] = member.isdir()
        if not members:
            raise RuntimeError('Empty source archive')
        for key in kinds:
            if any(kinds.get('/'.join(key.split('/')[:i])) is False for i in range(1, len(key.split('/')))):
                raise RuntimeError('File/directory collision in source archive')
        destination.mkdir(parents=True)
        for member in members:
            target = destination.joinpath(*safe_member_name(member.name))
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with source.extractfile(member) as stream, target.open('xb') as out:
                    shutil.copyfileobj(stream, out)
    return destination / SOURCE_FOLDER


def load_patch():
    spec = importlib.util.spec_from_file_location('vga_opencv_minimal_patch', PATCH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def community_toolchain(proof):
    microsoft_runtime.verify_provenance(proof)
    root = PureWindowsPath(proof['product']['installation_path'])
    dumpbin = PureWindowsPath(proof['tool']['path'])
    tools_version = dumpbin.relative_to(root).parts[3]
    if proof['tool'].get('tools_version', tools_version) != tools_version:
        raise RuntimeError('Community toolset version/path disagree')
    return {'installation_path': root.as_posix(), 'tools_version': tools_version,
            'compiler_path': dumpbin.with_name('cl.exe').as_posix(),
            'linker_path': dumpbin.with_name('link.exe').as_posix(),
            'product_id': proof['product']['id'],
            'installation_version': proof['product']['installation_version']}


def parse_cmake_cache(text):
    """Parse CMake's quoted-key syntax without merging distinct MSVC flag keys."""
    result = {}; entries = {}
    cache_types = {'BOOL', 'FILEPATH', 'PATH', 'STRING', 'INTERNAL', 'STATIC', 'UNINITIALIZED'}
    for number, line in enumerate(text.splitlines(), 1):
        if not line or line.startswith(('#', '//')):
            continue
        # CMake cmState::ParseCacheEntry checks quoted keys before unquoted keys.
        # For example, "HAVE_CXX_ARCH:AVX2":INTERNAL=1 is one complete key.
        match = re.fullmatch(r'"([^"\r\n]+)":([^:=\r\n]+)=(.*)', line)
        if match is None:
            match = re.fullmatch(r'([^:="\r\n]+):([^:=\r\n]+)=(.*)', line)
        if match is None or match[2] not in cache_types:
            raise RuntimeError(f'Malformed CMake cache entry at line {number}')
        key, kind, value = match.groups()
        if key in result:
            prior_number, prior_kind = entries[key]
            raise RuntimeError(f'Duplicate CMake cache key {key[:160]!r}: '
                               f'{prior_kind} at line {prior_number}, {kind} at line {number}')
        # CMake uses single quotes to preserve trailing whitespace in values.
        value = value.rstrip('\r\t ')
        if len(value) >= 2 and value.startswith("'") and value.endswith("'"):
            value = value[1:-1]
        result[key] = value
        entries[key] = (number, kind)
    return result


def verify_cmake_cache(cache, toolchain):
    for key, expected in OPTIONS.items():
        actual = cache.get(key)
        if key == 'CPU_DISPATCH' and actual:
            actual = actual.replace(';', ',')
        if actual != expected:
            raise RuntimeError(f'OpenCV CMake setting differs: {key}={actual!r}')
    expected_paths = {'CMAKE_GENERATOR_INSTANCE': toolchain['installation_path'],
                      'CMAKE_C_COMPILER': toolchain['compiler_path'],
                      'CMAKE_CXX_COMPILER': toolchain['compiler_path'],
                      'CMAKE_LINKER': toolchain['linker_path']}
    for key, expected in expected_paths.items():
        if PureWindowsPath(cache.get(key, '')) != PureWindowsPath(expected):
            raise RuntimeError('OpenCV compiler is outside the approved Community instance: ' + key)
    generator = {'CMAKE_GENERATOR': 'Visual Studio 17 2022', 'CMAKE_GENERATOR_PLATFORM': 'x64',
                 'CMAKE_GENERATOR_TOOLSET': 'host=x64,version='+toolchain['tools_version']}
    if any(cache.get(key) != value for key, value in generator.items()):
        raise RuntimeError('Unexpected Windows CMake generator/toolset/platform')
    return {key: cache[key] for key in sorted(set(OPTIONS) | set(expected_paths) | set(generator))}


def verify_static_crt(projects):
    """Require explicit /MT-equivalent MSBuild properties in every named target."""
    for name, text in projects.items():
        root = ET.fromstring(text)
        groups = [node for node in root.iter() if node.tag.rsplit('}', 1)[-1] == 'ItemDefinitionGroup'
                  and re.search(r'==\s*[\'"]Release\|x64[\'"]', node.get('Condition', ''))]
        runtimes = [node.text for group in groups for node in group.iter()
                    if node.tag.rsplit('}', 1)[-1] == 'RuntimeLibrary']
        if not runtimes or set(runtimes) != {'MultiThreaded'}:
            raise RuntimeError('Release target is not explicit static /MT CRT: ' + name)
    if set(projects) != {'opencv_' + name for name in MODULES}:
        raise RuntimeError('Incomplete static CRT project checks')


def project_sdk_version(projects):
    versions = set()
    for name, text in projects.items():
        root = ET.fromstring(text)
        found = {node.text for node in root.iter()
                 if node.tag.rsplit('}', 1)[-1] == 'WindowsTargetPlatformVersion'}
        if len(found) != 1 or not re.fullmatch(r'10\.0\.\d+\.\d+', next(iter(found), '') or ''):
            raise RuntimeError('Missing explicit Windows SDK version in target: '+name)
        versions.update(found)
    if set(projects) != {'opencv_'+name for name in MODULES} or len(versions) != 1:
        raise RuntimeError('Windows SDK differs between OpenCV module projects')
    return next(iter(versions))


def verify_build_information(info):
    def require(pattern, message):
        if not re.search(pattern, info, re.MULTILINE):
            raise RuntimeError('Minimal OpenCV build feature mismatch: ' + message)
    require(r'^General configuration for OpenCV 5\.0\.0\s', 'native version')
    require(r'^\s+To be built:\s+' + r'([^\r\n]+)', 'modules')
    modules = re.search(r'^\s+To be built:\s+([^\r\n]+)', info, re.MULTILINE)[1].split()
    if set(modules) != MODULES:
        raise RuntimeError('Unexpected OpenCV modules: ' + ','.join(modules))
    for pattern, name in [
        (r'Algorithm Hint:\s+ALGO_HINT_ACCURATE', 'accurate hint'),
        (r'Baseline:\s+SSE SSE2 SSE3\s*$', 'SSE3 baseline'),
        (r'Dispatched code generation:\s+' + ' '.join(DISPATCH) + r'\s*$', 'CPU dispatch'),
        (r'Built as dynamic libs\?:\s+NO', 'static OpenCV'),
        (r'C\+\+ flags \(Release\):[^\r\n]*/fp:precise', 'precise arithmetic'),
        (r'Intel IPP:\s+2026\.0\.0', 'IPP'),
        (r'Custom HAL:\s+YES \(ipp', 'IPP HAL'),
        (r'OpenCL:\s+YES', 'OpenCL'), (r'Built-in Unicode font:\s+YES', 'Unicode font'),
        (r'Lapack:\s+YES \(Built-In libclapack\)', 'CLAPACK'),
        (r'Eigen:\s+NO', 'no alternate Eigen backend'),
        (r'Parallel framework:\s+Concurrency', 'Windows concurrency'),
        (r'Trace:\s+YES', 'trace/ITT'),
        (r'ZLib:\s+build \(ver 1\.3\.2\)', 'bundled zlib'),
        (r'JPEG:\s+build-libjpeg-turbo \(ver 3\.1\.2-70\)', 'bundled JPEG'),
        (r'JPEG:[\s\S]*?SIMD Support:\s+YES[^\r\n]*\r?\n\s+WEBP:', 'JPEG SIMD'),
        (r'PNG:\s+build \(ver 1\.6\.57\)', 'bundled PNG'),
        (r'WEBP:\s+build \(ver decoder: 0x0210, encoder: 0x0210, demux: 0x0107\)', 'bundled WebP'),
        (r'Limited API:\s+YES', 'Python limited API'),
    ]:
        require(pattern, name)
    if '/fp:fast' in info or re.search(r'FFMPEG:\s+YES', info):
        raise RuntimeError('Unexpected fast math or video support')
    return True


def validate_wheel(path):
    path = Path(path)
    if not re.fullmatch(r'opencv_python_headless-5\.0\.0\.93\+vga1-cp312-cp312-win_amd64\.whl', path.name):
        raise RuntimeError('Unexpected custom wheel identity/platform')
    with zipfile.ZipFile(path) as wheel:
        names = wheel.namelist()
        if len(names) != len(set(name.casefold() for name in names)):
            raise RuntimeError('Duplicate wheel member')
        for name in names:
            safe_member_name(name)
        metadata = [name for name in names if name.endswith('.dist-info/METADATA')]
        if len(metadata) != 1:
            raise RuntimeError('Missing unique custom wheel metadata')
        from email.parser import Parser
        fields = Parser().parsestr(wheel.read(metadata[0]).decode('utf-8'))
        if (fields.get('Name', '').replace('_', '-').lower() != 'opencv-python-headless'
                or fields.get('Version') != VERSION):
            raise RuntimeError('Custom wheel metadata version/name mismatch')
        native = [name for name in names if name.endswith('.pyd')]
        if native != ['cv2/cv2.pyd'] or any(name.endswith('.dll') for name in names):
            raise RuntimeError('Unexpected native custom wheel payload')
        data = wheel.read(native[0])
        if len(data) < 1024 or data[:2] != b'MZ':
            raise RuntimeError('Custom extension is not a Windows PE')
        pe_offset = struct.unpack_from('<I', data, 0x3c)[0]
        if pe_offset + 6 > len(data) or data[pe_offset:pe_offset+4] != b'PE\0\0' or struct.unpack_from('<H', data, pe_offset+4)[0] != 0x8664:
            raise RuntimeError('Custom extension is not x64')
        for required in ('cv2/typing/__init__.py', 'cv2/py.typed', 'cv2/LICENSE.txt', 'cv2/LICENSE-3RD-PARTY.txt'):
            if required not in names:
                raise RuntimeError('Custom wheel is missing required metadata/licensing: ' + required)
        return {'wheel': file_record(path), 'native': {'path': native[0], 'size': len(data), 'sha256': digest(data)}}


def collect_licenses(source, install, destination, inputs, nasm_license):
    source, install, destination = map(Path, (source, install, destination))
    generated = install / 'share' / 'licenses' / 'opencv5'
    files = sorted(path for path in generated.rglob('*') if path.is_file())
    names = {path.name.lower() for path in files}
    required = {'fonts-rubik_ofl.txt', 'libjpeg-turbo-license.md', 'libpng-license',
                'clapack-lapack_license', 'zlib-license'}
    if (not required <= names or not any('ippicv-eula' in name for name in names)
            or not any('ippicv-third-party-programs' in name for name in names)
            or len(files) > 100 or sum(p.stat().st_size for p in files) > 5_000_000):
        raise RuntimeError('Generated OpenCV license bundle is incomplete or excessive')
    destination.mkdir(parents=True, exist_ok=False)
    for path in files:
        ensure_regular(path)
        target = destination / 'generated' / path.relative_to(generated)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    for origin, name in [(source/'LICENSE.txt', 'WRAPPER-MIT-LICENSE.txt'),
                         (source/'LICENSE-3RD-PARTY.txt', 'UPSTREAM-LICENSE-3RD-PARTY.txt'),
                         (source/'opencv/LICENSE', 'OPENCV-APACHE-LICENSE.txt')]:
        shutil.copyfile(ensure_regular(origin), destination/name)
    shutil.copyfile(ensure_regular(nasm_license), destination/'NASM-BUILD-TOOL-LICENSE.txt')
    write_utf8((destination/'WENQUANYI-NOTICE.txt'), FONT_NOTICE)
    write_utf8((destination/'DOWNSTREAM-BUILD-NOTICE.txt'), downstream_notice())
    write_utf8((destination/'BUILD-INPUTS-PROVENANCE.json'), json.dumps(inputs, indent=2)+'\n')
    return [file_record(path, destination) for path in sorted(destination.rglob('*')) if path.is_file()]


def validate_requirements(text):
    pins = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        match = re.fullmatch(r'([A-Za-z0-9-]+)==([0-9.]+)', line)
        if not match or match[1] in pins:
            raise RuntimeError('Invalid or duplicate isolated build requirement')
        pins[match[1]] = match[2]
    if pins != BUILD_DEPENDENCIES:
        raise RuntimeError('Isolated build requirements differ from reviewed pins')
    return pins


def validate_pe_imports(imports, delay_imports):
    allowed = {'python3.dll', 'ole32.dll', 'kernel32.dll', 'oleaut32.dll'}
    for rows in (imports, delay_imports):
        if (not isinstance(rows, list) or any(not isinstance(name, str) for name in rows)
                or len(rows) != len(set(rows)) or not set(rows) <= allowed):
            raise RuntimeError('Unexpected OpenCV PE dependency; do not remove or silently bundle it')
    if not {'python3.dll', 'kernel32.dll'} <= set(imports):
        raise RuntimeError('Missing expected x64 Python OpenCV PE dependencies')


def inspect_native(path):
    import pefile
    pe = pefile.PE(str(path), fast_load=True)
    try:
        if pe.FILE_HEADER.Machine != 0x8664:
            raise RuntimeError('Installed OpenCV native machine is not x64')
        pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY[key] for key in
            ('IMAGE_DIRECTORY_ENTRY_IMPORT', 'IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT')])
        imports = sorted(entry.dll.decode('ascii').lower() for entry in getattr(pe, 'DIRECTORY_ENTRY_IMPORT', []))
        delay = sorted(entry.dll.decode('ascii').lower() for entry in getattr(pe, 'DIRECTORY_ENTRY_DELAY_IMPORT', []))
        validate_pe_imports(imports, delay)
        return {'machine': 'x64', 'imports': imports, 'delay_imports': delay}
    finally:
        pe.close()


def downstream_notice():
    return ('VGA experimental OpenCV '+VERSION+' is a downstream source build, not an official PyPI wheel.\n'
            'Only build-tool selection, wheel assembly, Python typing and package-version metadata were patched.\n'
            'No C++ image algorithm or OCR model source was changed.\n'
            'Exact upstream inputs and downstream patches are recorded in BUILD-INPUTS-PROVENANCE.json.\n')


def license_expectations(inputs):
    expected = {'generated/'+name: row for name, row in GENERATED_LICENSES.items()}
    expected.update({
        'WRAPPER-MIT-LICENSE.txt': {'size': 1070, 'sha256': '09d719058e782ac7bc71ba21c944e1136cde2bb957c0e888121f0218d6b5f02c'},
        'UPSTREAM-LICENSE-3RD-PARTY.txt': {'size': 179634, 'sha256': '2537f5653345db7231ff12f307bcfa4c89807d45ed1c4bb8ebfb6f26f61b160a'},
        'NASM-BUILD-TOOL-LICENSE.txt': {'size': 1550, 'sha256': '7c22a2d3d099a1167c281e437f48340dfad88634630c97afee927e5705626f7a'},
        'OPENCV-APACHE-LICENSE.txt': {'size': 11358, 'sha256': 'cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30'},
    })
    for name, value in [('WENQUANYI-NOTICE.txt', FONT_NOTICE),
                        ('DOWNSTREAM-BUILD-NOTICE.txt', downstream_notice()),
                        ('BUILD-INPUTS-PROVENANCE.json', json.dumps(inputs, indent=2)+'\n')]:
        raw = value.encode('utf-8'); expected[name] = {'size': len(raw), 'sha256': digest(raw)}
    return expected


def validate_provenance(proof, source_commit=None):
    """Recheck archived experiment evidence against this exact reviewed recipe."""
    try:
        return _validate_provenance(proof, source_commit)
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise RuntimeError('Malformed minimal OpenCV provenance') from exc


def _validate_provenance(proof, source_commit):
    if (not isinstance(proof, dict) or type(proof.get('schema_version')) is not int or proof['schema_version'] != 1
            or proof.get('status') != 'passed' or 'error' in proof or proof.get('version') != VERSION
            or proof.get('upstream_version') != '5.0.0.93'):
        raise RuntimeError('Missing successful custom OpenCV provenance')
    if source_commit is None:
        source_commit = os.environ.get('GITHUB_SHA') or run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, timeout=30).strip()
    if not re.fullmatch('[0-9a-f]{40}', source_commit) or proof.get('source_commit') != source_commit:
        raise RuntimeError('Custom OpenCV source commit differs')
    def check_record(row, *, minimum=1, maximum=200_000_000):
        if (not isinstance(row, dict) or not isinstance(row.get('path'), str) or not row['path']
                or type(row.get('size')) is not int or not minimum <= row['size'] <= maximum
                or not re.fullmatch('[0-9a-f]{64}', row.get('sha256', ''))):
            raise RuntimeError('Invalid custom OpenCV file identity')
    for name, path in [('recipe', Path(__file__)), ('build_requirements', REQUIREMENTS)]:
        check_record(proof[name]); actual = file_record(path)
        if any(proof[name][key] != actual[key] for key in ('size', 'sha256')):
            raise RuntimeError('Custom OpenCV local recipe/pin bytes differ: '+name)
    validate_requirements(REQUIREMENTS.read_text(encoding='utf-8'))
    if proof['build_dependencies'] != BUILD_DEPENDENCIES:
        raise RuntimeError('Custom OpenCV build dependency evidence differs')
    if set(proof['download_inputs']) != set(ASSETS) or proof['source'] != proof['download_inputs']['source']:
        raise RuntimeError('Incomplete custom OpenCV source inputs')
    for name, pin in ASSETS.items():
        row = proof['download_inputs'][name]
        if any(row.get(key) != value for key, value in pin.items()):
            raise RuntimeError('Custom OpenCV pinned input differs: '+name)
    if proof['upstream_git'] != {'opencv_python': 'b83046cda41133f1bf2e73e99dba16a1248f103a',
                                'opencv': '40738fb16ceddb5fb3fea747585f7ce6abb0605b'}:
        raise RuntimeError('Custom OpenCV upstream git identity differs')
    patch = proof['patch']; check_record(patch['script']); actual = file_record(PATCH)
    if any(patch['script'][key] != actual[key] for key in ('size', 'sha256')):
        raise RuntimeError('Custom OpenCV patch script bytes differ')
    expected_patch = [{'path': name, 'before_sha256': pair[0], 'after_sha256': pair[1]}
                      for name, pair in load_patch().FILE_HASHES.items()]
    if patch['files'] != expected_patch:
        raise RuntimeError('Custom OpenCV downstream source patch identities differ')
    expected_toolchain = community_toolchain(proof['community_runtime'])
    toolchain = proof['toolchain']
    if any(toolchain.get(key) != value for key, value in expected_toolchain.items()):
        raise RuntimeError('Custom OpenCV Community toolchain identity differs')
    for name in ('compiler', 'linker'):
        row = toolchain[name]; check_record(row, minimum=1024, maximum=30_000_000)
        if (PureWindowsPath(row['path']) != PureWindowsPath(toolchain[name+'_path'])
                or not microsoft_runtime.signed_by_microsoft(row) or not row.get('file_version')):
            raise RuntimeError('Custom OpenCV uses an unverified compiler/linker')
    check_record(toolchain['nasm'], minimum=1024, maximum=10_000_000)
    if (toolchain['nasm']['size'] != 1_650_688 or toolchain['nasm']['sha256'] != 'a93276636266516421cc9b422f47476c21f7a2949f1ae251556b2f1d33a3be04'
            or not re.match(r'^NASM version 2\.16\.03(?:\s|$)', toolchain.get('nasm_version', ''))):
        raise RuntimeError('Wrong pinned assembler identity')
    if not re.fullmatch(r'10\.0\.\d+\.\d+', toolchain.get('windows_sdk_version', '')):
        raise RuntimeError('Missing exact Windows SDK identity')
    if not re.fullmatch('[0-9a-f]{64}', proof['microsoft_runtime_provenance_sha256']):
        raise RuntimeError('Missing Community runtime proof hash')
    options = proof['cmake_options']
    expected_options = {**OPTIONS, 'CMAKE_GENERATOR_INSTANCE': toolchain['installation_path'],
                        'CMAKE_C_COMPILER': toolchain['compiler_path'], 'CMAKE_CXX_COMPILER': toolchain['compiler_path'],
                        'CMAKE_LINKER': toolchain['linker_path'],
                        'CMAKE_GENERATOR_TOOLSET': 'host=x64,version='+toolchain['tools_version'],
                        'CMAKE_GENERATOR_PLATFORM': 'x64',
                        'CMAKE_ASM_NASM_COMPILER': PureWindowsPath(toolchain['nasm']['path']).as_posix()}
    if options != expected_options:
        raise RuntimeError('Custom OpenCV CMake arguments differ')
    verify_cmake_cache(proof['verified_cmake_cache'], toolchain)
    info = proof['build_information']
    if len(info.encode('utf-8')) > 25_000 or digest(info.encode('utf-8')) != proof['build_info_sha256']:
        raise RuntimeError('Custom OpenCV build information hash differs')
    verify_build_information(info)
    if proof['static_crt'] != 'Release /MT (MultiThreaded) verified in all six module projects':
        raise RuntimeError('Custom OpenCV static CRT evidence is missing')
    check_record(proof['native'], minimum=1024)
    native_path = PureWindowsPath(proof['native']['path'])
    if not native_path.is_absolute() or '..' in native_path.parts or native_path.name != 'cv2.pyd' or proof['native']['machine'] != 'x64':
        raise RuntimeError('Custom OpenCV native identity is invalid')
    validate_pe_imports(proof['native']['imports'], proof['native']['delay_imports'])
    check_record(proof['wheel'], minimum=1024)
    if PureWindowsPath(proof['wheel']['path']).name != 'opencv_python_headless-'+VERSION+'-cp312-cp312-win_amd64.whl':
        raise RuntimeError('Custom OpenCV wheel identity is invalid')
    inputs = {key: value for key, value in proof.items() if key not in {'status', 'licenses', 'limitations'}}
    expected_licenses = license_expectations(inputs)
    licenses = proof['licenses']; seen = set()
    for row in licenses:
        check_record(row, maximum=500_000)
        safe_member_name(row['path'])
        if row['path'] in seen or row['path'] not in expected_licenses:
            raise RuntimeError('Unexpected or duplicate custom OpenCV license')
        if any(row[key] != expected_licenses[row['path']][key] for key in ('size', 'sha256')):
            raise RuntimeError('Custom OpenCV license/input-provenance bytes differ: '+row['path'])
        seen.add(row['path'])
    if seen != set(expected_licenses):
        raise RuntimeError('Custom OpenCV complete license set is missing')
    return proof


def sanitized_log_tail(path, limit=32768):
    """Bound new-build diagnostics; never dump environment or whole log files."""
    with Path(path).open('rb') as source:
        source.seek(0, 2)
        size = source.tell()
        source.seek(max(0, size-limit))
        raw = source.read(limit)
    text = raw.decode('utf-8', errors='replace').replace('\r\n', '\n')
    text = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', text)
    text = re.sub(r'[\x00-\x08\x0b-\x1f\x7f]', '', text)
    text = re.sub(r'(?i)(https?://)[^/\s@]+@', r'\1[redacted]@', text)
    text = re.sub(r'(?i)(authorization\s*:\s*(?:bearer|basic)\s+)\S+', r'\1[redacted]', text)
    text = re.sub(r'(?i)((?:[a-z0-9_]*(?:token|password|secret|credential|api_key)|signature)\s*[=:]\s*)[^\s&]+', r'\1[redacted]', text)
    # Prefix every line so third-party text cannot become an Actions command.
    output = '\n'.join('[opencv-build] '+line for line in text.splitlines())
    raw_output = output.encode('utf-8')
    if len(raw_output) > limit:
        prefix = '[opencv-build] '
        return prefix + raw_output[-(limit-len(prefix)):].decode('utf-8', errors='ignore')
    return output


def run(command, *, cwd=None, env=None, log=None, timeout=1200):
    if log:
        with Path(log).open('ab') as output:
            result = subprocess.run(command, cwd=cwd, env=env, stdout=output, stderr=subprocess.STDOUT, timeout=timeout)
        if result.returncode:
            print(sanitized_log_tail(log), flush=True)
            raise RuntimeError(f'Build command failed ({result.returncode}); see {Path(log).name}')
        return ''
    return subprocess.check_output(command, cwd=cwd, env=env, stderr=subprocess.STDOUT, timeout=timeout, text=True, encoding='utf-8')


def clean_environment():
    blocked = {'CC', 'CXX', 'CFLAGS', 'CXXFLAGS', 'LDFLAGS', 'CL', '_CL_', 'LINK', '_LINK_', 'PYTHONPATH', 'PYTHONHOME', 'CI_BUILD',
               'INCLUDE', 'LIB', 'LIBPATH', 'VCINSTALLDIR', 'VCTOOLSINSTALLDIR', 'VSINSTALLDIR',
               'VISUALSTUDIOVERSION', 'WINDOWSSDKDIR'}
    env = {key: value for key, value in os.environ.items() if key.upper() not in blocked
           and not key.upper().startswith(('CMAKE_', 'SKBUILD_', 'OPENCV_', 'ENABLE_'))}
    env.update(PYTHONUTF8='1', PIP_DISABLE_PIP_VERSION_CHECK='1', PIP_CONFIG_FILE=os.devnull)
    return env


def build():
    if (sys.platform != 'win32' or struct.calcsize('P') != 8 or sys.version_info[:2] != (3, 12)
            or os.environ.get('VGA_EXPERIMENTAL_MINIMAL_OPENCV') != '1'
            or os.environ.get('GITHUB_ACTIONS') != 'true' or os.environ.get('RUNNER_ENVIRONMENT') != 'github-hosted'):
        raise RuntimeError('Explicit experimental opt-in on a GitHub-hosted Python3.12 x64 Windows runner is required')
    if Path(os.environ.get('GITHUB_WORKSPACE', '')).resolve() != ROOT.resolve():
        raise RuntimeError('OpenCV experiment must use the workflow workspace')
    proof = microsoft_runtime.verify_source_files()
    toolchain = community_toolchain(proof)
    cl = ensure_regular(Path(toolchain['compiler_path']))
    linker = ensure_regular(Path(toolchain['linker_path']))
    source_commit = run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, timeout=30).strip()
    if not re.fullmatch('[0-9a-f]{40}', source_commit) or source_commit != os.environ.get('GITHUB_SHA'):
        raise RuntimeError('Workflow source commit and checkout HEAD differ')
    validate_requirements(REQUIREMENTS.read_text(encoding='utf-8'))
    if OUTPUT.exists():
        raise RuntimeError('Refusing to reuse an existing minimal OpenCV experiment')
    temporary = Path(os.environ.get('RUNNER_TEMP', ''))
    if not temporary.is_absolute() or not temporary.is_dir():
        raise RuntimeError('A valid ephemeral runner temporary directory is required')
    work = temporary / 'vga-opencv-vga1'
    work.mkdir(exist_ok=False)
    OUTPUT.mkdir(parents=True)
    logs = OUTPUT/'logs'; logs.mkdir()
    env = clean_environment()
    for key, executable in [('compiler', cl), ('linker', linker)]:
        env['VGA_CHECK_COMPILER'] = str(executable)
        signature = json.loads(run(['pwsh', '-NoProfile', '-NonInteractive', '-Command',
            '$f=Get-Item -LiteralPath $env:VGA_CHECK_COMPILER; $s=Get-AuthenticodeSignature -LiteralPath $f.FullName; '
            '@{signature_status=$s.Status.ToString();signer_subject=$s.SignerCertificate.Subject;'
            'file_version=$f.VersionInfo.FileVersion} | ConvertTo-Json -Compress'], env=env, timeout=60))
        if not microsoft_runtime.signed_by_microsoft(signature):
            raise RuntimeError('The exact Community tool is not signed by Microsoft: '+key)
        toolchain[key] = {**file_record(executable), **signature}
    downloads = work/'downloads'; assets = {}
    for name, asset in ASSETS.items():
        assets[name] = download_asset(asset, downloads/asset['filename'])
    nasm = extract_nasm(downloads/ASSETS['nasm']['filename'], work/'nasm')
    nasm_version = run([str(nasm), '-v'], env=env, timeout=30).strip()
    if not re.match(r'^NASM version 2\.16\.03(?:\s|$)', nasm_version):
        raise RuntimeError('Pinned NASM executable reported the wrong version')
    toolchain.update(nasm=file_record(nasm), nasm_version=nasm_version)
    source = extract_source(downloads/ASSETS['source']['filename'], work/'source')
    patches = load_patch().apply(source)
    for name in ('ipp', 'font'):
        target = source/'opencv/.cache'/ASSETS[name]['cache']
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(downloads/ASSETS[name]['filename'], target)
        verify_asset(target, ASSETS[name])
    build_env = work/'venv'
    run([sys.executable, '-m', 'venv', str(build_env)], env=env, timeout=120)
    python = build_env/'Scripts/python.exe'
    run([str(python), '-m', 'pip', '--isolated', 'install', '--index-url', 'https://pypi.org/simple',
         '--only-binary=:all:', '--no-deps', '-r', str(REQUIREMENTS)], env=env, log=logs/'tools.log')
    versions = json.loads(run([str(python), '-c', 'import importlib.metadata as m,json;print(json.dumps({n:m.version(n) for n in '+repr(list(BUILD_DEPENDENCIES))+'}))'], env=env))
    if versions != BUILD_DEPENDENCIES:
        raise RuntimeError('Isolated OpenCV build dependency versions differ')
    env.update(ENABLE_HEADLESS='1', CMAKE_BUILD_PARALLEL_LEVEL='2', CMAKE_GENERATOR='Visual Studio 17 2022')
    options = {**OPTIONS, 'CMAKE_GENERATOR_INSTANCE': toolchain['installation_path'],
               'CMAKE_C_COMPILER': toolchain['compiler_path'], 'CMAKE_CXX_COMPILER': toolchain['compiler_path'],
               'CMAKE_LINKER': toolchain['linker_path'],
               'CMAKE_GENERATOR_TOOLSET': 'host=x64,version='+toolchain['tools_version'],
                        'CMAKE_GENERATOR_PLATFORM': 'x64',
               'CMAKE_ASM_NASM_COMPILER': Path(nasm).as_posix()}
    # Classic skbuild splits CMAKE_ARGS twice, first without shell quoting.
    # The hash-pinned setup adapter receives intact argument strings via JSON.
    env['CMAKE_ARGS'] = '-DWITH_FFMPEG=OFF -DPYTHON3_LIMITED_API=ON'
    env['VGA_OPENCV_CMAKE_ARGS_JSON'] = json.dumps(['-D'+key+'='+value for key, value in options.items()])
    env['PATH'] = str(build_env/'Scripts')+os.pathsep+str(nasm.parent)+os.pathsep+env.get('PATH', '')
    wheels = work/'wheels'; wheels.mkdir()
    started = time.monotonic()
    run([str(python), '-m', 'pip', '--isolated', 'wheel', '.', '--no-build-isolation', '--no-deps',
         '-v', '--wheel-dir', str(wheels)], cwd=source, env=env, log=logs/'build.log', timeout=2400)
    duration = round(time.monotonic()-started, 3)
    candidates = list(wheels.glob('*.whl'))
    if len(candidates) != 1:
        raise RuntimeError('Expected exactly one custom wheel')
    wheel = candidates[0]; wheel_proof = validate_wheel(wheel)
    caches = list((source/'_skbuild').glob('*/cmake-build/CMakeCache.txt'))
    if len(caches) != 1:
        raise RuntimeError('Expected one source-build CMake cache')
    cmake_build = caches[0].parent
    cache = verify_cmake_cache(parse_cmake_cache(caches[0].read_text(encoding='utf-8')), toolchain)
    projects = {}
    for name in MODULES:
        files = list(cmake_build.rglob('opencv_'+name+'.vcxproj'))
        if len(files) != 1:
            raise RuntimeError('Missing unique MSBuild target: '+name)
        projects['opencv_'+name] = files[0].read_text(encoding='utf-8-sig')
    verify_static_crt(projects)
    toolchain['windows_sdk_version'] = project_sdk_version(projects)
    run([sys.executable, '-m', 'pip', '--isolated', 'install', '--no-index', '--no-deps', '--force-reinstall', str(wheel)],
        env=env, log=logs/'install.log', timeout=180)
    runtime = json.loads(run([sys.executable, '-c',
        'import cv2,cv2.typing,cv2.utils,cv2.version,importlib.metadata,json,pathlib;'
        'p=list(pathlib.Path(cv2.__file__).parent.glob("*.pyd"));'
        'print(json.dumps({"version":importlib.metadata.version("opencv-python-headless"),'
        '"wrapper_version":cv2.version.opencv_version,"native_version":cv2.__version__,"native_paths":[str(x) for x in p],'
        '"build_info":cv2.getBuildInformation()}))'], env=env, timeout=60))
    if runtime['version'] != VERSION or runtime['wrapper_version'] != VERSION or runtime['native_version'] != '5.0.0' or len(runtime['native_paths']) != 1:
        raise RuntimeError('Installed custom OpenCV identity differs')
    native = {**file_record(runtime['native_paths'][0]), **inspect_native(runtime['native_paths'][0])}
    reports = ROOT/'reports'; reports.mkdir(exist_ok=True)
    write_utf8((reports/'windows-opencv-build-info.txt'), runtime['build_info'])
    if any(native[key] != wheel_proof['native'][key] for key in ('size', 'sha256')):
        raise RuntimeError('Installed OpenCV native bytes differ from built wheel')
    verify_build_information(runtime['build_info'])
    run([sys.executable, '-m', 'pip', '--isolated', 'check'], env=env, log=logs/'pip-check.log', timeout=60)
    inputs = {'schema_version': 1, 'version': VERSION, 'upstream_version': '5.0.0.93',
              'source_commit': source_commit, 'recipe': file_record(Path(__file__)), 'community_runtime': proof,
              'source': assets['source'], 'download_inputs': assets,
              'upstream_git': {'opencv_python': 'b83046cda41133f1bf2e73e99dba16a1248f103a',
                               'opencv': '40738fb16ceddb5fb3fea747585f7ce6abb0605b'},
              'patch': {'script': file_record(PATCH), 'files': patches},
              'toolchain': toolchain, 'microsoft_runtime_provenance_sha256': file_record(microsoft_runtime.RUNTIME_ROOT/'provenance.json')['sha256'],
              'build_requirements': file_record(REQUIREMENTS), 'build_dependencies': versions,
              'cmake_options': options, 'verified_cmake_cache': cache, 'compile_seconds': duration,
              **wheel_proof, 'native': native,
              'static_crt': 'Release /MT (MultiThreaded) verified in all six module projects',
              'build_information': runtime['build_info'],
              'build_info_sha256': digest(runtime['build_info'].encode('utf-8'))}
    licenses = collect_licenses(source, cmake_build.parent/'cmake-install', OUTPUT/'licenses', inputs, nasm.parent/'LICENSE')
    result = {**inputs, 'status': 'passed', 'licenses': licenses,
              'limitations': ['Isolated source-build verification only; require separate baseline parity and actual Windows EXE acceptance.',
                              'Compiler/SDK servicing can change output bytes; this is not a bit-reproducible build claim.']}
    validate_provenance(result, source_commit=source_commit)
    write_utf8((OUTPUT/'provenance.json'), json.dumps(result, indent=2)+'\n')
    reports = ROOT/'reports'; reports.mkdir(exist_ok=True)
    write_utf8((reports/'windows-opencv-build.json'), json.dumps(result, indent=2)+'\n')
    write_utf8((reports/'windows-opencv-build-info.txt'), runtime['build_info'])
    write_utf8((reports/'windows-opencv-build-cmake.txt'), json.dumps(cache, indent=2)+'\n')
    return result


def main():
    try:
        result = build()
        print(json.dumps({'status': result['status'], 'version': result['version'], 'native': result['native']}))
    except Exception as exc:
        result = {'schema_version': 1, 'status': 'failed', 'version': VERSION,
                  'error': str(exc)[:2000], 'no_acceptance_claim': True}
        reports = ROOT/'reports'; reports.mkdir(exist_ok=True)
        write_utf8((reports/'windows-opencv-build.json'), json.dumps(result, indent=2)+'\n')
        log = OUTPUT/'logs/build.log'
        if log.is_file():
            write_utf8(reports/'windows-opencv-build-diagnostic.txt', sanitized_log_tail(log)+'\n')
        print(json.dumps(result), file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == '__main__':
    main()

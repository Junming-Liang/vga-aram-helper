"""Portable fail-closed build checks; never compile, install or contact a service."""
import ast
import copy
import hashlib
import importlib.util
import io
import json
import os
import re
import sys
import types
from pathlib import Path
import struct
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from scripts import build_minimal_opencv as build

BUILD_INFO = '''General configuration for OpenCV 5.0.0 =====================================
  Algorithm Hint: ALGO_HINT_ACCURATE
  Baseline: SSE SSE2 SSE3
  Dispatched code generation: SSE4_1 SSE4_2 AVX FP16 AVX2 AVX512_SKX
  Built as dynamic libs?: NO
  C++ flags (Release): /O2 /fp:precise /MT
  To be built: core flann geometry imgcodecs imgproc python3
  Built-in Unicode font: YES
  ZLib: build (ver 1.3.2)
  JPEG: build-libjpeg-turbo (ver 3.1.2-70)
    SIMD Support: YES
  WEBP: build (ver decoder: 0x0210, encoder: 0x0210, demux: 0x0107)
  PNG: build (ver 1.6.57)
  Parallel framework: Concurrency
  Trace: YES
  Intel IPP: 2026.0.0
  Custom HAL: YES (ipp (ver 0.0.1))
  OpenCL: YES
  Lapack: YES (Built-In libclapack)
  Eigen: NO
  Limited API: YES
'''


def provenance_fixture(source_commit=None):
    """Synthetic valid schema for companion packaging tests; no executable claim."""
    spec = importlib.util.spec_from_file_location('vga_runtime_fixture', build.ROOT/'tests/test_microsoft_runtime.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    runtime = module.runtime_fixture()
    toolchain = build.community_toolchain(runtime)
    signed = {'size': 10000, 'sha256': 'c'*64, 'signature_status': 'Valid',
              'signer_subject': runtime['tool']['signer_subject'], 'file_version': '19.44.35228.0'}
    for name in ('compiler', 'linker'):
        toolchain[name] = {'path': toolchain[name+'_path'], **signed}
    toolchain['nasm'] = {'path': 'C:/build/nasm/nasm.exe', 'size': 1650688,
                         'sha256': 'a93276636266516421cc9b422f47476c21f7a2949f1ae251556b2f1d33a3be04'}
    toolchain['windows_sdk_version'] = '10.0.22621.0'
    toolchain['nasm_version'] = 'NASM version 2.16.03 compiled on Apr 17 2024'
    options = {**build.OPTIONS, 'CMAKE_GENERATOR_INSTANCE': toolchain['installation_path'],
               'CMAKE_C_COMPILER': toolchain['compiler_path'], 'CMAKE_CXX_COMPILER': toolchain['compiler_path'],
               'CMAKE_LINKER': toolchain['linker_path'],
               'CMAKE_GENERATOR_TOOLSET': 'host=x64,version='+toolchain['tools_version'],
               'CMAKE_GENERATOR_PLATFORM': 'x64',
               'CMAKE_ASM_NASM_COMPILER': toolchain['nasm']['path']}
    cache = {**options, 'CMAKE_GENERATOR': 'Visual Studio 17 2022'}
    source_commit = source_commit or build.run(['git', 'rev-parse', 'HEAD'], cwd=build.ROOT, timeout=30).strip()
    assets = {name: {**value, 'path': 'C:/downloads/'+value['filename']} for name, value in build.ASSETS.items()}
    inputs = {'schema_version': 1, 'version': build.VERSION, 'upstream_version': '5.0.0.93',
              'source_commit': source_commit, 'recipe': build.file_record(Path(build.__file__)),
              'community_runtime': runtime, 'source': assets['source'], 'download_inputs': assets,
              'upstream_git': {'opencv_python': 'b83046cda41133f1bf2e73e99dba16a1248f103a',
                               'opencv': '40738fb16ceddb5fb3fea747585f7ce6abb0605b'},
              'patch': {'script': build.file_record(build.PATCH),
                        'files': [{'path': name, 'before_sha256': pair[0], 'after_sha256': pair[1]}
                                  for name, pair in build.load_patch().FILE_HASHES.items()]},
              'toolchain': toolchain, 'microsoft_runtime_provenance_sha256': 'd'*64,
              'build_requirements': build.file_record(build.REQUIREMENTS),
              'build_dependencies': dict(build.BUILD_DEPENDENCIES), 'cmake_options': options,
              'verified_cmake_cache': cache, 'compile_seconds': 10,
              'wheel': {'path': 'C:/build/opencv_python_headless-'+build.VERSION+'-cp312-cp312-win_amd64.whl',
                        'size': 20000, 'sha256': 'e'*64},
              'native': {'path': 'C:/app/Lib/site-packages/cv2/cv2.pyd', 'size': 40000, 'sha256': 'f'*64,
                         'machine': 'x64', 'imports': ['kernel32.dll', 'python3.dll'], 'delay_imports': []},
              'static_crt': 'Release /MT (MultiThreaded) verified in all six module projects',
              'build_information': BUILD_INFO, 'build_info_sha256': build.digest(BUILD_INFO.encode())}
    licenses = [{'path': name, **row} for name, row in sorted(build.license_expectations(inputs).items())]
    return {**inputs, 'status': 'passed', 'licenses': licenses, 'limitations': ['Synthetic test fixture only']}


# Stable public test helper for the companion frozen-package integration tests.
valid_provenance_fixture = provenance_fixture


class MinimalOpenCVTests(unittest.TestCase):
    def test_failure_diagnostic_is_bounded_sanitized_and_not_an_actions_command(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'build.log'
            path.write_bytes(b'old-prefix'*10000+b'\n::error::CMake Error: failed\n'
                b'https://person:password@example.invalid/path\nAuthorization: Bearer test-credential\n'
                b'API_TOKEN=abc123 SECRET=hidden password=hidden\n\x1b[31merror C1000: compiler failure\x1b[0m\n')
            tail=build.sanitized_log_tail(path, limit=512)
            self.assertNotIn('person:password',tail);self.assertNotIn('test-credential',tail)
            self.assertNotIn('abc123',tail);self.assertNotIn('hidden',tail);self.assertNotIn('\x1b',tail)
            self.assertIn('error C1000: compiler failure',tail)
            self.assertTrue(all(line.startswith('[opencv-build] ') for line in tail.splitlines()))
            self.assertLessEqual(len(tail.encode()),512)

    def test_frontend_adapter_has_one_generator_and_intact_arguments(self):
        options = provenance_fixture('a'*40)['cmake_options']
        args = ['-D'+key+'='+value for key, value in options.items()]
        class Platform:
            def __init__(self): self.default_generators = []
        class Generator:
            def __init__(self, name, **kwargs): self.name = name; self.__dict__.update(kwargs)
        abstract = types.SimpleNamespace(CMakePlatform=Platform, CMakeGenerator=Generator)
        namespace = {'os': os, 're': re, 'cmaker': types.SimpleNamespace(), '_vga_setup': lambda **kwargs: kwargs}
        with patch.dict(sys.modules, {'skbuild.platform_specifics.abstract': abstract}), patch.dict(os.environ, {'VGA_OPENCV_CMAKE_ARGS_JSON': json.dumps(args)}):
            exec(build.load_patch().FRONTEND_ADAPTER, namespace)
        generators = namespace['cmaker'].get_platform().default_generators
        self.assertEqual(len(generators), 1)
        self.assertEqual((generators[0].name, generators[0].arch, generators[0].toolset),
                         ('Visual Studio 17 2022', 'x64', options['CMAKE_GENERATOR_TOOLSET']))
        result = namespace['setup'](cmake_args=['-DWITH_FFMPEG=ON'])
        self.assertEqual(result['cmake_args'], ['-DWITH_FFMPEG=ON', *args])
        for raw in (None, '{', '{}', '[]', json.dumps(args+[args[0]]), json.dumps(['-T', 'v143']),
                    json.dumps(args+['-DUNREVIEWED_EMPTY=']),
                    json.dumps([arg for arg in args if not arg.startswith('-DCMAKE_ASM_COMPILER=')]),
                    json.dumps([arg.replace('-DCMAKE_ASM_COMPILER=', '-DCMAKE_ASM_COMPILER=C:/gcc.exe') for arg in args]),
                    json.dumps([arg for arg in args if not arg.startswith('-DCMAKE_C_COMPILER=')])):
            with self.subTest(raw=raw), patch.dict(sys.modules, {'skbuild.platform_specifics.abstract': abstract}), patch.dict(os.environ, {}, clear=True):
                if raw is not None: os.environ['VGA_OPENCV_CMAKE_ARGS_JSON'] = raw
                with self.assertRaises(RuntimeError): exec(build.load_patch().FRONTEND_ADAPTER, dict(namespace))

    def test_pinned_skbuild_discovery_and_configure_command_capture(self):
        # Run explicitly in the pinned isolated build venv. Ordinary app tests do
        # not require/install build tools and skip this extra integration check.
        try:
            import skbuild
            from skbuild import cmaker
        except ImportError:
            self.skipTest('Exact isolated scikit-build is not installed')
        if skbuild.__version__ != build.BUILD_DEPENDENCIES['scikit-build']:
            self.skipTest('Requires exact pinned scikit-build 0.18.1')
        options = provenance_fixture('a'*40)['cmake_options']
        args = ['-D'+key+'='+value for key, value in options.items()]
        namespace = {'os': os, 're': re, 'cmaker': cmaker, '_vga_setup': lambda **kwargs: kwargs}
        calls = []
        def capture(command, **kwargs):
            calls.append(command)
            return types.SimpleNamespace(returncode=0)
        old_directory = os.getcwd()
        with tempfile.TemporaryDirectory() as directory, patch.object(cmaker, 'get_platform'), patch.dict(os.environ, {
                'VGA_OPENCV_CMAKE_ARGS_JSON': json.dumps(args), 'CMAKE_ARGS': '-DWITH_FFMPEG=OFF -DPYTHON3_LIMITED_API=ON',
                'CMAKE_GENERATOR': 'Visual Studio 17 2022'}), patch.object(cmaker.subprocess, 'run', capture), \
                patch.object(cmaker.CMaker, 'check_for_bad_installs'), patch('sys.stdout', io.StringIO()):
            try:
                os.chdir(directory)
                exec(build.load_patch().FRONTEND_ADAPTER, namespace)
                maker = cmaker.CMaker.__new__(cmaker.CMaker)
                maker.platform = cmaker.get_platform(); maker.cmake_executable = 'cmake'; maker.cmake_version = '4.3.2'
                maker.configure(namespace['setup'](cmake_args=['-DWITH_FFMPEG=ON'])['cmake_args'])
            finally:
                os.chdir(old_directory)
        self.assertEqual(len(calls), 2, 'One real discovery path and one final configure, both intercepted')
        for command in calls:
            self.assertEqual(command.count('-T'), 1)
            self.assertEqual(command[command.index('-T')+1], options['CMAKE_GENERATOR_TOOLSET'])
            self.assertEqual(command[command.index('-A')+1], 'x64')
            for key in ('CMAKE_GENERATOR_INSTANCE', 'CMAKE_C_COMPILER', 'CMAKE_CXX_COMPILER', 'CMAKE_LINKER',
                        'CMAKE_GENERATOR_TOOLSET', 'CMAKE_GENERATOR_PLATFORM', 'CMAKE_ASM_COMPILER', 'CMAKE_ASM_NASM_COMPILER'):
                self.assertIn('-D'+key+'='+options[key], command)
            self.assertFalse(any(arg.startswith('"') for arg in command))
        self.assertEqual([arg for arg in calls[-1] if arg.startswith('-DWITH_FFMPEG=')][-1], '-DWITH_FFMPEG=OFF')

    def test_pinned_cmake_empty_asm_skips_probe_and_gnu_changes_library_names(self):
        try:
            import cmake
            import importlib.metadata
        except ImportError:
            self.skipTest('Pinned isolated CMake is not installed')
        if importlib.metadata.version('cmake') != build.BUILD_DEPENDENCIES['cmake']:
            self.skipTest('Requires exact pinned CMake 4.3.2')
        script = r'''
cmake_minimum_required(VERSION 4.3.2)
include(CheckLanguage)
function(execute_process)
  message(FATAL_ERROR "Empty generic ASM must not run a discovery subprocess")
endfunction()
set(CMAKE_ASM_COMPILER "")
set(CMAKE_ASM_NASM_COMPILER "C:/pinned/nasm.exe")
check_language(ASM)
if(NOT DEFINED CMAKE_ASM_COMPILER OR NOT CMAKE_ASM_COMPILER STREQUAL "")
  message(FATAL_ERROR "Generic ASM disable setting changed")
endif()
if(NOT CMAKE_ASM_NASM_COMPILER STREQUAL "C:/pinned/nasm.exe")
  message(FATAL_ERROR "Dedicated NASM changed")
endif()
set(CMAKE_SYSTEM_NAME Windows)
include(CMakeSystemSpecificInformation)
if(NOT CMAKE_STATIC_LIBRARY_PREFIX STREQUAL "" OR NOT CMAKE_STATIC_LIBRARY_SUFFIX STREQUAL ".lib")
  message(FATAL_ERROR "Expected Windows static library naming")
endif()
# Prove the contaminating platform file's effect without running its ld probe.
function(execute_process)
endfunction()
include(Platform/Windows-GNU)
if(NOT CMAKE_STATIC_LIBRARY_PREFIX STREQUAL "lib" OR NOT CMAKE_STATIC_LIBRARY_SUFFIX STREQUAL ".a")
  message(FATAL_ERROR "Expected GNU naming contamination")
endif()
message(STATUS "Empty ASM skips probe; NASM preserved; GNU changes .lib to lib.a")
'''
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'check.cmake'; path.write_text(script)
            output = build.run([str(Path(cmake.CMAKE_BIN_DIR)/('cmake.exe' if os.name == 'nt' else 'cmake')),
                                '-P', str(path)], timeout=30)
        self.assertIn('Empty ASM skips probe; NASM preserved; GNU changes .lib to lib.a', output)

    def test_wrapper_assembly_markers_match_selected_limited_api(self):
        # Upstream setup.py chooses python-3 versus python-3.12 using this marker,
        # independently of its CMake keyword argument list.
        tree = ast.parse(Path(build.__file__).read_text())
        markers = [node.value.value for node in ast.walk(tree)
                   if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)
                   and any(isinstance(target, ast.Subscript)
                           and isinstance(target.slice, ast.Constant)
                           and target.slice.value == 'CMAKE_ARGS' for target in node.targets)]
        self.assertEqual(markers, ['-DWITH_FFMPEG=OFF -DPYTHON3_LIMITED_API=ON'])
        self.assertEqual(markers[0].split(), ['-DWITH_FFMPEG=OFF', '-DPYTHON3_LIMITED_API=ON'])
        self.assertEqual(build.OPTIONS['PYTHON3_LIMITED_API'], 'ON')
        binary_regex = r'python/cv2/python-3*/cv2.*' if '-DPYTHON3_LIMITED_API=ON' in markers[0] else r'python/cv2/python-3.*/cv2.*'
        self.assertIsNotNone(re.fullmatch(binary_regex, 'python/cv2/python-3/cv2.pyd'))

    def test_generated_text_bytes_are_platform_stable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'notice.txt'
            build.write_utf8(path, 'first\nsecond ©\n')
            self.assertEqual(path.read_bytes(), 'first\nsecond ©\n'.encode('utf-8'))

    def test_nasm_zip_member_allowlist_is_narrow(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory)/'nasm.zip'
            with zipfile.ZipFile(archive, 'w') as package:
                package.writestr('../nasm.exe', b'not executed')
            with patch.object(build, 'verify_asset'), self.assertRaisesRegex(RuntimeError, 'ZIP members'):
                build.extract_nasm(archive, Path(directory)/'out')
            self.assertFalse((Path(directory)/'out').exists())

    def test_exact_source_and_reproducible_tool_pins(self):
        self.assertEqual(build.ASSETS['source']['sha256'], 'b82f9831daab90b725c7c1ee1b36cb5732c367096ac76d119e64e14eb70d5f3c')
        self.assertEqual(build.ASSETS['ipp']['sha256'], 'cf1560b05cc67795852d4ec32ce58ceee466a8d996404af27dfaaea5f1da2760')
        self.assertEqual(build.ASSETS['nasm']['size'], 513543)
        self.assertIn('no publisher-signed checksum', build.ASSETS['nasm']['checksum_origin'])
        self.assertEqual(build.validate_requirements(build.REQUIREMENTS.read_text()), build.BUILD_DEPENDENCIES)
        for text in ('cmake>=4', build.REQUIREMENTS.read_text()+'numpy==2.0.2\n', build.REQUIREMENTS.read_text().replace('2.0.2', '2.5.4')):
            with self.assertRaises(RuntimeError): build.validate_requirements(text)

    def test_hash_or_size_mismatch_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory)/'source'; file.write_bytes(b'approved')
            pin = {'filename': 'source', 'sha256': hashlib.sha256(b'approved').hexdigest(), 'size': 8}
            self.assertEqual(build.verify_asset(file, pin)['sha256'], pin['sha256'])
            for changed in ({**pin, 'size': 7}, {**pin, 'sha256': 'a'*64}):
                with self.assertRaises(RuntimeError): build.verify_asset(file, changed)

    @staticmethod
    def archive(path, members):
        with tarfile.open(path, 'w:gz') as out:
            for name, kind in members:
                member = tarfile.TarInfo(name)
                if kind == 'file': member.size = 1; out.addfile(member, io.BytesIO(b'x'))
                elif kind == 'dir': member.type = tarfile.DIRTYPE; out.addfile(member)
                elif kind == 'link': member.type = tarfile.SYMTYPE; member.linkname = '/tmp'; out.addfile(member)
                elif kind == 'hard': member.type = tarfile.LNKTYPE; member.linkname = '../bad'; out.addfile(member)
                elif kind == 'fifo': member.type = tarfile.FIFOTYPE; out.addfile(member)

    def test_safe_source_extraction_and_fresh_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory); archive = base/'source.tgz'; prefix = build.SOURCE_FOLDER
            self.archive(archive, [(prefix, 'dir'), (prefix+'/cv2/version.py', 'file')])
            result = build.extract_source(archive, base/'out')
            self.assertEqual((result/'cv2/version.py').read_bytes(), b'x')
            with self.assertRaises(RuntimeError): build.extract_source(archive, base/'out')

    def test_unsafe_archive_members_fail_before_writes(self):
        prefix = build.SOURCE_FOLDER
        cases = [[('../escape', 'file')], [('/absolute', 'file')], [(prefix+'/../escape', 'file')],
                 [(prefix+'/x\\y', 'file')], [(prefix+'/file:ads', 'file')], [(prefix+'/CON', 'file')],
                 [(prefix+'/x', 'link')], [(prefix+'/x', 'hard')], [(prefix+'/x', 'fifo')],
                 [(prefix+'/X', 'file'), (prefix+'/x', 'file')],
                 [(prefix+'/x', 'file'), (prefix+'/x/child', 'file')]]
        for members in cases:
            with self.subTest(members=members), tempfile.TemporaryDirectory() as directory:
                base = Path(directory); self.archive(base/'source.tgz', members)
                with self.assertRaises(RuntimeError): build.extract_source(base/'source.tgz', base/'out')
                self.assertFalse((base/'out').exists())

    def test_patch_preimages_and_whole_input_set_are_verified(self):
        module = build.load_patch()
        with self.assertRaises(RuntimeError): module.transform({})
        with self.assertRaisesRegex(RuntimeError, 'preimage'):
            module.transform({name: b'changed upstream source' for name in module.FILE_HASHES})
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            for name in module.FILE_HASHES:
                path = source/name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(b'unchanged')
            with self.assertRaises(RuntimeError): module.apply(source)
            self.assertTrue(all((source/name).read_bytes() == b'unchanged' for name in module.FILE_HASHES))

    def test_patch_duplicate_match_and_bad_postimage_fail(self):
        module = build.load_patch()
        originals = {
            'cv2/version.py': b'opencv_version = "5.0.0.93"',
            'setup.py': b'from skbuild import cmaker, setup\nif os.name == "nt"\n            else []',
            'opencv/modules/python/src2/typing_stubs_generation/api_refinement.py':
                b'from .ast_utils import (find_function_node, SymbolName,\n    for symbol_name, refine_symbol in NODES_TO_REFINE.items():\n        refine_symbol(root, symbol_name)',
            'opencv/modules/python/src2/typing_stubs_generation/generation.py':
                b'    for node in PREDEFINED_TYPES.values():\n        # if node does not have at least one required module skip it',
        }
        pins = {name: (build.digest(raw), '0'*64) for name, raw in originals.items()}
        with patch.object(module, 'FILE_HASHES', pins), self.assertRaisesRegex(RuntimeError, 'postimage'):
            module.transform(originals)
        originals['cv2/version.py'] *= 2
        pins = {name: (build.digest(raw), '0'*64) for name, raw in originals.items()}
        with patch.object(module, 'FILE_HASHES', pins), self.assertRaisesRegex(RuntimeError, 'exactly once'):
            module.transform(originals)

    def test_cache_parser_preserves_quoted_msvc_keys_and_metadata(self):
        cache = build.parse_cmake_cache('''// Windows flag probes contain colons in their names.
"HAVE_CXX_ARCH:AVX":INTERNAL=1
"HAVE_CXX_ARCH:AVX2":INTERNAL=1
"HAVE_CXX_ARCH:AVX512":INTERNAL=1
CMAKE_CXX_COMPILER:FILEPATH=C:/Program Files/Community/cl.exe
CPU_BASELINE:STRING=SSE3
CPU_BASELINE-STRINGS:INTERNAL=SSE3;SSE4_1
CPU_BASELINE-ADVANCED:INTERNAL=1
CMAKE_ASM_COMPILER:UNINITIALIZED=
"key:with=equals":STRING=first=second
TRAILING:STRING='keep space '
''')
        self.assertEqual([cache['HAVE_CXX_ARCH:'+value] for value in ('AVX', 'AVX2', 'AVX512')], ['1']*3)
        self.assertEqual(cache['CMAKE_CXX_COMPILER'], 'C:/Program Files/Community/cl.exe')
        self.assertEqual(cache['CPU_BASELINE'], 'SSE3')
        self.assertEqual(cache['CPU_BASELINE-STRINGS'], 'SSE3;SSE4_1')
        self.assertEqual(cache['CMAKE_ASM_COMPILER'], '')
        self.assertEqual(cache['key:with=equals'], 'first=second')
        self.assertEqual(cache['TRAILING'], 'keep space ')
        for text in ('X:BOOL=ON\nX:BOOL=OFF', 'X:BOOL=ON\n"X":BOOL=ON',
                     '"flag:value":INTERNAL=1\n"flag:value":STRING=1'):
            with self.subTest(text=text), self.assertRaisesRegex(RuntimeError, 'Duplicate CMake cache key.*line 1.*line 2'):
                build.parse_cmake_cache(text)
        for text in ('"unterminated:key:BOOL=ON', 'X:BOGUS=ON', 'X:BOOL'):
            with self.assertRaisesRegex(RuntimeError, 'Malformed CMake cache entry at line 1'):
                build.parse_cmake_cache(text)

    def test_pinned_cmake_generated_quoted_key_cache(self):
        try:
            import cmake
            import importlib.metadata
        except ImportError:
            self.skipTest('Pinned isolated CMake is not installed')
        if importlib.metadata.version('cmake') != build.BUILD_DEPENDENCIES['cmake']:
            self.skipTest('Requires exact pinned CMake 4.3.2')
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)/'source'; source.mkdir()
            (source/'CMakeLists.txt').write_text('''cmake_minimum_required(VERSION 4.3.2)
project(CacheFormat NONE)
set("HAVE_CXX_ARCH:AVX" 1 CACHE INTERNAL "MSVC flag probe")
set("HAVE_CXX_ARCH:AVX2" 1 CACHE INTERNAL "MSVC flag probe")
set(CPU_BASELINE SSE3 CACHE STRING "CPU baseline")
set_property(CACHE CPU_BASELINE PROPERTY STRINGS SSE3 SSE4_1)
mark_as_advanced(CPU_BASELINE)
''')
            output = Path(directory)/'build'
            build.run([str(Path(cmake.CMAKE_BIN_DIR)/('cmake.exe' if os.name == 'nt' else 'cmake')),
                       '-S', str(source), '-B', str(output)], timeout=30)
            text = (output/'CMakeCache.txt').read_text()
            self.assertIn('"HAVE_CXX_ARCH:AVX":INTERNAL=1', text)
            self.assertIn('"HAVE_CXX_ARCH:AVX2":INTERNAL=1', text)
            cache = build.parse_cmake_cache(text)
            self.assertEqual(cache['HAVE_CXX_ARCH:AVX'], '1')
            self.assertEqual(cache['HAVE_CXX_ARCH:AVX2'], '1')
            self.assertEqual(cache['CPU_BASELINE-ADVANCED'], '1')

    def test_cmake_flags_and_community_compiler_are_mandatory(self):
        proof = provenance_fixture('a'*40); cache = proof['verified_cmake_cache']; toolchain = proof['toolchain']
        build.verify_cmake_cache(cache, toolchain)
        for key, value in [('CPU_BASELINE', 'AVX2'), ('CPU_DISPATCH', ''), ('WITH_IPP', 'OFF'),
                           ('ENABLE_FAST_MATH', 'ON'), ('BUILD_WITH_STATIC_CRT', 'OFF'),
                           ('CMAKE_ASM_NASM_COMPILER', 'C:/unreviewed/nasm.exe'), ('CMAKE_ASM_COMPILER', 'C:/gcc.exe'), ('CMAKE_GENERATOR_TOOLSET', 'v143'), ('CMAKE_GENERATOR_PLATFORM', 'Win32'),
                           ('CMAKE_CXX_COMPILER', 'C:/Enterprise/cl.exe'), ('CMAKE_LINKER', 'C:/Enterprise/link.exe')]:
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                build.verify_cmake_cache({**cache, key: value}, toolchain)
        with self.assertRaises(RuntimeError): build.parse_cmake_cache('X:BOOL=ON\nX:BOOL=OFF')

    def test_static_crt_requires_all_release_module_projects(self):
        xml = '''<Project xmlns="http://schemas.microsoft.com/developer/msbuild/2003"><ItemDefinitionGroup Condition="'$(Configuration)|$(Platform)'=='Release|x64'"><ClCompile><RuntimeLibrary>MultiThreaded</RuntimeLibrary></ClCompile></ItemDefinitionGroup></Project>'''
        projects = {'opencv_'+name: xml for name in build.MODULES}
        build.verify_static_crt(projects)
        for change in ({**projects, 'opencv_python3': xml.replace('MultiThreaded', 'MultiThreadedDLL')},
                       {name: value for name, value in projects.items() if name != 'opencv_python3'},
                       {**projects, 'opencv_python3': xml.replace('Release|x64', 'Debug|x64')}):
            with self.assertRaises(RuntimeError): build.verify_static_crt(change)

    def test_sdk_version_is_explicit_and_consistent(self):
        xml = '<Project><PropertyGroup><WindowsTargetPlatformVersion>10.0.22621.0</WindowsTargetPlatformVersion></PropertyGroup></Project>'
        projects = {'opencv_'+name: xml for name in build.MODULES}
        self.assertEqual(build.project_sdk_version(projects), '10.0.22621.0')
        with self.assertRaises(RuntimeError):
            build.project_sdk_version({**projects, 'opencv_core': xml.replace('22621', '26100')})
        with self.assertRaises(RuntimeError):
            build.project_sdk_version({**projects, 'opencv_core': '<Project />'})

    def test_build_information_preserves_numerical_and_codec_features(self):
        self.assertTrue(build.verify_build_information(BUILD_INFO))
        for old, new in [('ALGO_HINT_ACCURATE', 'ALGO_HINT_APPROX'), ('SIMD Support: YES', 'SIMD Support: NO'),
                         ('/fp:precise', '/fp:fast'), ('OpenCL: YES', 'OpenCL: NO'),
                         ('core flann geometry imgcodecs imgproc python3', 'core imgproc python3'),
                         ('Intel IPP: 2026.0.0', 'Intel IPP: 2021.0.0')]:
            with self.subTest(old=old), self.assertRaises(RuntimeError):
                build.verify_build_information(BUILD_INFO.replace(old, new))

    def test_eigen_off_summary_omission_is_not_an_enabled_backend(self):
        absent = re.sub(r'^.*Eigen:.*\n', '', BUILD_INFO, flags=re.MULTILINE)
        self.assertTrue(build.verify_build_information(absent))
        for value in ('YES (ver 3.4.0)', 'UNKNOWN', '', 'NO\n    Eigen: NO'):
            with self.subTest(value=value), self.assertRaisesRegex(RuntimeError, 'no alternate Eigen backend'):
                build.verify_build_information(BUILD_INFO.replace('Eigen: NO', 'Eigen: '+value))

    def test_build_feature_audit_reports_all_mismatches_together(self):
        info = BUILD_INFO.replace('SIMD Support: YES', 'SIMD Support: NO').replace(
            'OpenCL: YES', 'OpenCL: NO').replace('/fp:precise', '/fp:fast')
        with self.assertRaises(RuntimeError) as caught:
            build.verify_build_information(info)
        for label in ('JPEG SIMD', 'OpenCL', 'precise arithmetic', 'unexpected fast math'):
            self.assertIn(label, str(caught.exception))
        with self.assertRaisesRegex(RuntimeError, 'native version.*modules.*accurate hint'):
            build.verify_build_information('')

    def test_native_measurement_is_available_without_an_acceptance_claim(self):
        proof = {'wheel': {'size': 1234, 'sha256': 'a'*64, 'path': 'private-path'},
                 'native': {'size': 6000, 'sha256': 'b'*64, 'zlib9_size': 2000}}
        report = build.native_size_measurement(proof)
        self.assertEqual(report['native_zlib9_saved_bytes'], 30_519_497-2000)
        self.assertEqual(report['status'], 'measurement_only')
        self.assertTrue(report['no_acceptance_claim'])
        self.assertTrue(report['not_exe_measurement'])
        self.assertNotIn('private-path', json.dumps(report))

    def test_generated_notices_use_windows_layout_and_exact_full_inventory(self):
        with tempfile.TemporaryDirectory() as directory:
            install = Path(directory)
            correct = install/'etc/licenses'; correct.mkdir(parents=True)
            linux = install/'share/licenses/opencv5'; linux.mkdir(parents=True)
            (correct/'one-LICENSE.txt').write_bytes(b'one')
            (correct/'two-LICENSE.txt').write_bytes(b'two')
            (linux/'do-not-use.txt').write_bytes(b'wrong platform')
            expected = {name+'-LICENSE.txt': {'size': 3, 'sha256': build.digest(name.encode())}
                        for name in ('one', 'two')}
            with patch.object(build, 'GENERATED_LICENSES', expected):
                generated, files, audit = build.generated_license_audit(install)
                self.assertEqual(generated, correct)
                self.assertEqual(len(files), 2)
                self.assertEqual(audit['status'], 'passed')
                (correct/'one-LICENSE.txt').write_bytes(b'bad')
                (correct/'two-LICENSE.txt').unlink()
                (correct/'extra.txt').write_bytes(b'extra')
                _, _, audit = build.generated_license_audit(install)
                self.assertEqual(audit['status'], 'failed')
                self.assertEqual(audit['missing'], ['two-LICENSE.txt'])
                self.assertEqual(audit['unexpected'], ['extra.txt'])
                self.assertEqual(audit['mismatched'], ['one-LICENSE.txt'])
                self.assertEqual(audit['missing_count'], 1)
                with self.assertRaisesRegex(RuntimeError, 'license audit failed'):
                    build.collect_licenses(install, install, install/'output', {}, install/'nasm')
                self.assertFalse((install/'output').exists())

    def test_unexpected_or_dynamic_crt_pe_imports_are_rejected(self):
        build.validate_pe_imports(['kernel32.dll', 'python3.dll', 'ole32.dll'], [])
        for imports, delayed in [(['kernel32.dll'], []), (['kernel32.dll', 'python3.dll'], ['vcruntime140.dll']),
                                 (['kernel32.dll', 'python3.dll', 'unexpected.dll'], [])]:
            with self.assertRaises(RuntimeError): build.validate_pe_imports(imports, delayed)

    @staticmethod
    def wheel(path, version=build.VERSION, machine=0x8664):
        native = bytearray(2048); native[:2] = b'MZ'; struct.pack_into('<I', native, 0x3c, 128)
        native[128:132] = b'PE\0\0'; struct.pack_into('<H', native, 132, machine)
        with zipfile.ZipFile(path, 'w') as out:
            out.writestr('cv2/cv2.pyd', native)
            out.writestr('opencv_python_headless-'+version+'.dist-info/METADATA', 'Name: opencv-python-headless\nVersion: '+version+'\n')
            for name in ('cv2/typing/__init__.py', 'cv2/py.typed', 'cv2/LICENSE.txt', 'cv2/LICENSE-3RD-PARTY.txt'):
                out.writestr(name, 'fixture')

    def test_wheel_identity_version_native_machine_and_typing(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/('opencv_python_headless-'+build.VERSION+'-cp312-cp312-win_amd64.whl')
            self.wheel(path); self.assertEqual(build.validate_wheel(path)['native']['size'], 2048)
            self.wheel(path, version='5.0.0.93')
            with self.assertRaises(RuntimeError): build.validate_wheel(path)
            self.wheel(path, machine=0x14c)
            with self.assertRaises(RuntimeError): build.validate_wheel(path)

    def test_provenance_validates_full_reviewed_recipe_and_licenses(self):
        proof = provenance_fixture('a'*40)
        self.assertIs(build.validate_provenance(proof, source_commit='a'*40), proof)
        paths = {row['path'] for row in proof['licenses']}
        self.assertIn('generated/ippicv-EULA.rtf', paths)
        self.assertIn('NASM-BUILD-TOOL-LICENSE.txt', paths)
        self.assertIn('BUILD-INPUTS-PROVENANCE.json', paths)
        cases = [('status', 'failed'), ('version', '5.0.0.93'), ('source_commit', 'b'*40), ('error', ''),
                 ('licenses', []), ('build_dependencies', {}), ('static_crt', '/MD')]
        for key, value in cases:
            changed = copy.deepcopy(proof); changed[key] = value
            with self.subTest(key=key), self.assertRaises(RuntimeError): build.validate_provenance(changed, source_commit='a'*40)
        for field in ('source', 'recipe', 'build_requirements'):
            changed = copy.deepcopy(proof); changed[field]['sha256'] = '0'*64
            with self.subTest(field=field), self.assertRaises(RuntimeError): build.validate_provenance(changed, source_commit='a'*40)
        mutations = [lambda p: p['download_inputs']['ipp'].update(sha256='0'*64),
                     lambda p: p['patch']['files'][0].update(after_sha256='0'*64),
                     lambda p: p['toolchain']['compiler'].update(path='C:/Enterprise/cl.exe'),
                     lambda p: p['toolchain']['linker'].update(signature_status='NotSigned'),
                     lambda p: p['native'].update(machine='x86'),
                     lambda p: p['native'].update(delay_imports=['msvcp140.dll']),
                     lambda p: p['licenses'][0].update(path='../outside'),
                     lambda p: p['licenses'][0].update(sha256='0'*64),
                     lambda p: p['cmake_options'].update(WITH_IPP='OFF')]
        for mutate in mutations:
            changed = copy.deepcopy(proof); mutate(changed)
            with self.assertRaises(RuntimeError): build.validate_provenance(changed, source_commit='a'*40)

    def test_environment_removes_inherited_toolchain_without_global_changes(self):
        inherited = {name: 'untrusted' for name in ['INCLUDE', 'LIB', 'LIBPATH', 'VCINSTALLDIR', 'VCToolsInstallDir',
            'VSINSTALLDIR', 'VisualStudioVersion', 'WindowsSdkDir', 'CMAKE_ARGS', 'CL', 'PYTHONPATH']}
        with patch.dict(os.environ, {**inherited, 'KEEP_ME': 'yes'}, clear=True):
            clean = build.clean_environment()
            self.assertFalse(set(inherited) & clean.keys()); self.assertEqual(clean['KEEP_ME'], 'yes')
            self.assertEqual(os.environ['LIB'], 'untrusted')


if __name__ == '__main__':
    unittest.main()

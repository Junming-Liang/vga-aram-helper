"""Supplemental post-build A1/B1/A2/B2 capture reversal; never an adoption gate.

Fixed commands: prepare (before custom build), run (after build), summarize.
All inputs/outputs and versions are fixed. Only run installs wheels, offline,
inside an ephemeral GitHub-hosted Windows job. No original parity code is changed.
The supervisor never imports cv2, Pillow, Qt, or another native Python package.
"""
from __future__ import annotations

import argparse
import copy
import ctypes
from ctypes import wintypes as W
from email.parser import Parser
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import runpy
import stat
import statistics
import struct
import subprocess
import sys
import threading
import time
import uuid
import zipfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts import build_minimal_opencv as builder
from scripts import probe_opencv_parity as parity

BLOCKS = ('A1', 'B1', 'A2', 'B2')
VERSIONS = {'A': parity.OFFICIAL_VERSION, 'B': parity.CUSTOM_VERSION}
PREFIX = 'windows-opencv-crossover-'
MAX_JSON_BYTES = 4 * 1024 * 1024
MAX_LOG_BYTES = 512 * 1024
MAX_RENDER_BYTES = 256 * 1024
MAX_WHEEL_BYTES = 100_000_000
MAX_UNPACKED_BYTES = 250_000_000
MAX_MEMBERS = 3000
TIMEOUTS = {'install': 180, 'identity': 90, 'probe': 600, 'check': 90}
RETIRE_TIMEOUT = 10.0
SCOPE = ('Fixed post-build A1/B1/A2/B2 supplemental reversal, all blocks retained; '
         'not adoption evidence, a speed threshold waiver, or proof of causality. '
         'Original two warmups and seven samples of three captures remain unchanged. '
         'No extra profiling hooks; existing full-probe import/runtime metadata only.')
CACHE_RULE = 'Only .pyc files immediately inside __pycache__ directories are excluded from installed cv2 inventory.'
METADATA_EXTRAS = {'RECORD', 'INSTALLER', 'REQUESTED', 'direct_url.json'}


def output_path(label):
    if not re.fullmatch(r'[a-zA-Z0-9-]+', label):
        raise RuntimeError('Invalid fixed output label')
    return ROOT / 'reports' / (PREFIX + label + '.json')


def regular(path, *, maximum=MAX_JSON_BYTES, allow_empty=False):
    path = Path(path)
    builder.ensure_regular(path)
    if not (0 if allow_empty else 1) <= path.stat().st_size <= maximum:
        raise RuntimeError('Input file exceeds its nonempty size budget')
    return path


def file_record(path, *, maximum=MAX_JSON_BYTES):
    path = regular(path, maximum=maximum)
    return {'path': str(path), 'size': path.stat().st_size,
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def bytes_record(data):
    return {'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}


def same(left, right):
    return parity.canonical(left) == parity.canonical(right)


def unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('Duplicate JSON field')
        value[key] = item
    return value


def read_json(path):
    value = json.loads(regular(path).read_text(encoding='utf-8'), object_pairs_hook=unique_object,
                       parse_constant=lambda value: (_ for _ in ()).throw(ValueError('Nonfinite JSON')))
    parity.canonical(value)
    return value


def write_json(path, value):
    raw = (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')
    if len(raw) > MAX_JSON_BYTES:
        raise RuntimeError('Report exceeds fixed output budget')
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    check_directory(path.parent)
    if path.exists() or path.is_symlink():
        raise RuntimeError('Refusing to replace earlier crossover evidence')
    with path.open('xb') as stream:
        stream.write(raw)


def check_directory(path):
    path = Path(path)
    if not path.is_dir():
        raise RuntimeError('Expected existing directory')
    for part in (path, *path.parents):
        if part.is_symlink() or getattr(part.lstat(), 'st_file_attributes', 0) & 0x400:
            raise RuntimeError('Linked/reparse directory is not accepted')
    return path


def source_binding():
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, timeout=30,
                                     text=True, encoding='utf-8').strip()
    if not re.fullmatch('[0-9a-f]{40}', commit) or commit != os.environ.get('GITHUB_SHA'):
        raise RuntimeError('Checkout and workflow source commit differ')
    names = set(parity.SOURCE_FILES) | {'scripts/probe_opencv_capture_crossover.py',
        'scripts/build_minimal_opencv.py', 'scripts/microsoft_runtime.py', 'scripts/windows_package.py',
        'packaging/opencv-minimal-patch.py', 'packaging/opencv-build-requirements.txt',
        'requirements-build.txt', 'requirements-ocr.txt', '.gitattributes',
        '.github/workflows/build-native-preview.yml'}
    return {'commit': commit, 'files': {name: bytes_record(regular(ROOT / name).read_bytes())
                                       for name in sorted(names)}}


def require_host():
    if (sys.platform != 'win32' or struct.calcsize('P') != 8 or sys.version_info[:2] != (3, 12)
            or os.environ.get('GITHUB_ACTIONS') != 'true'
            or os.environ.get('RUNNER_ENVIRONMENT') != 'github-hosted'
            or os.environ.get('GITHUB_REF') != 'refs/heads/experiment/capture-opencv-crossover'
            or Path(os.environ.get('GITHUB_WORKSPACE', '')).resolve() != ROOT):
        raise RuntimeError('Requires the isolated experiment branch on a GitHub-hosted Windows Python 3.12 x64 runner')
    check_directory(ROOT)


def expected_wheel(variant):
    if variant == 'A':
        folder = check_directory(ROOT / 'build' / 'opencv-crossover' / 'official')
        entries = list(folder.iterdir())
        if len(entries) != 1 or entries[0].suffix != '.whl':
            raise RuntimeError('Expected exactly one saved official wheel and no other files')
        return entries[0]
    if variant != 'B':
        raise RuntimeError('Unknown fixed wheel variant')
    proof = read_json(ROOT / 'reports' / 'windows-opencv-build.json')
    builder.validate_provenance(proof, source_commit=os.environ.get('GITHUB_SHA'))
    temporary = Path(os.environ.get('RUNNER_TEMP', ''))
    if not temporary.is_absolute():
        raise RuntimeError('Missing runner temporary root')
    check_directory(temporary)
    path = temporary / 'vga-opencv-vga1' / 'wheels' / ('opencv_python_headless-' + VERSIONS['B'] + '-cp312-cp312-win_amd64.whl')
    if Path(proof['wheel']['path']) != path:
        raise RuntimeError('Custom wheel is outside its fixed build location')
    actual = file_record(path, maximum=MAX_WHEEL_BYTES)
    if any(actual[key] != proof['wheel'][key] for key in ('size', 'sha256')):
        raise RuntimeError('Custom wheel differs from build provenance')
    return path


def normalized_distribution_name(name):
    # PyPA: https://packaging.python.org/en/latest/specifications/name-normalization/
    # Explicit ASCII ranges and fullmatch reject Unicode lookalikes/trailing newlines.
    if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?', name):
        raise RuntimeError('Distribution Name is not a valid ASCII project name')
    return re.sub(r'[-_.]+', '-', name).lower()


def metadata_identity(fields, *, expected_version=None):
    names, versions = fields.get_all('Name', []), fields.get_all('Version', [])
    if len(names) != 1 or len(versions) != 1:
        raise RuntimeError('Distribution METADATA requires exactly one Name and one Version')
    normalized = normalized_distribution_name(names[0])
    if (normalized != 'opencv-python-headless' or versions[0] not in VERSIONS.values()
            or (expected_version is not None and versions[0] != expected_version)):
        raise RuntimeError('Distribution METADATA name/exact version differs')
    return {'raw_name': names[0], 'raw_version': versions[0], 'normalized_name': normalized}


def installed_opencv_distribution():
    candidates = []
    opencv_names = {'opencv-python-headless', 'opencv-python', 'opencv-contrib-python', 'opencv-contrib-python-headless'}
    for distribution in importlib.metadata.distributions():
        fields = distribution.metadata
        recognized = False
        for name in fields.get_all('Name', []):
            try:
                recognized |= normalized_distribution_name(name) in opencv_names
            except RuntimeError:
                continue
        if recognized:
            candidates.append((distribution, fields))
    if len(candidates) != 1:
        raise RuntimeError('Installed OpenCV distributions are conflicting or duplicated')
    distribution, fields = candidates[0]
    identity = metadata_identity(fields)
    if distribution.version != identity['raw_version']:
        raise RuntimeError('Installed distribution Version disagrees with raw METADATA')
    return distribution, identity


def wheel_identity(path, variant):
    path = regular(path, maximum=MAX_WHEEL_BYTES)
    version = VERSIONS[variant]
    match = re.fullmatch(r'opencv_python_headless-' + re.escape(version)
                         + r'-(cp3(?:[7-9]|1[0-2]))-(abi3|cp312)-win_amd64\.whl', path.name)
    if not match:
        raise RuntimeError('Wheel filename/version/platform differs')
    python_tag, abi = match.groups()
    if ((abi == 'abi3' and not 37 <= int(python_tag[2:]) <= 312)
            or (abi != 'abi3' and (python_tag, abi) != ('cp312', 'cp312'))):
        raise RuntimeError('Wheel Python/ABI tag is incompatible with pinned Python 3.12')
    inventory, metadata = {}, {}
    with zipfile.ZipFile(path) as archive:
        rows = archive.infolist()
        names = [row.filename for row in rows]
        if (not 1 <= len(rows) <= MAX_MEMBERS or len(set(name.casefold() for name in names)) != len(names)
                or sum(row.file_size for row in rows) > MAX_UNPACKED_BYTES):
            raise RuntimeError('Wheel inventory is duplicate or exceeds budget')
        for row in rows:
            builder.safe_member_name(row.filename)
            mode = (row.external_attr >> 16) & 0xFFFF
            if stat.S_ISLNK(mode) or row.flag_bits & 1:
                raise RuntimeError('Linked/encrypted wheel member')
            if row.is_dir():
                continue
            if not 0 <= row.file_size <= 200_000_000:
                raise RuntimeError('Wheel member exceeds budget')
            if '__pycache__' in Path(row.filename).parts or row.filename.endswith(('.pyc', '.pyo')):
                raise RuntimeError('Generated cache files are not accepted in wheels')
            data = archive.read(row)
            if row.filename.startswith('cv2/'):
                inventory[row.filename] = bytes_record(data)
            elif '.dist-info/' in row.filename:
                metadata[row.filename] = bytes_record(data)
            else:
                raise RuntimeError('Unexpected wheel payload outside cv2/dist-info')
        metadata_names = [name for name in metadata if name.endswith('.dist-info/METADATA')]
        if len(metadata_names) != 1:
            raise RuntimeError('Missing unique wheel METADATA')
        directory = metadata_names[0].rsplit('/', 1)[0]
        if directory != 'opencv_python_headless-' + version + '.dist-info' or any(not name.startswith(directory + '/') for name in metadata):
            raise RuntimeError('Wheel distribution metadata directory differs')
        fields = Parser().parsestr(archive.read(metadata_names[0]).decode('utf-8'))
        fields_identity = metadata_identity(fields, expected_version=version)
        wheel_name = directory + '/WHEEL'
        wheel_fields = Parser().parsestr(archive.read(wheel_name).decode('utf-8'))
        if (wheel_fields.get_all('Tag') != [python_tag + '-' + abi + '-win_amd64']
                or wheel_fields.get('Root-Is-Purelib', '').lower() != 'false'
                or directory + '/RECORD' not in metadata):
            raise RuntimeError('Wheel native tag/RECORD metadata differs')
        native_names = [name for name in inventory if name.lower().endswith('.pyd')]
        if native_names != ['cv2/cv2.pyd']:
            raise RuntimeError('Unexpected native OpenCV extension inventory')
        data = archive.read(native_names[0])
        if len(data) < 1024 or data[:2] != b'MZ':
            raise RuntimeError('Wheel native extension is not a Windows PE')
        offset = struct.unpack_from('<I', data, 0x3c)[0]
        if offset + 6 > len(data) or data[offset:offset+4] != b'PE\0\0' or struct.unpack_from('<H', data, offset+4)[0] != 0x8664:
            raise RuntimeError('Wheel native extension is not x64')
    if variant == 'B':
        checked = builder.validate_wheel(path)
        if any(checked['native'][key] != inventory['cv2/cv2.pyd'][key] for key in ('size', 'sha256')):
            raise RuntimeError('Custom native validation disagrees')
    return {'version': version, 'metadata_fields': fields_identity,
            'wheel': file_record(path, maximum=MAX_WHEEL_BYTES),
            'native': inventory['cv2/cv2.pyd'], 'package_inventory': inventory,
            'metadata_inventory': metadata, 'cache_exclusion_rule': CACHE_RULE}


def installed_identity():
    """Only called in a separate gated identity child, never the supervisor/probe."""
    import cv2
    distribution, fields_identity = installed_opencv_distribution()
    files = list(distribution.files or [])
    metadata_paths = [file for file in files if str(file).endswith('.dist-info/METADATA')]
    if len(metadata_paths) != 1:
        raise RuntimeError('Installed distribution METADATA is not unique')
    native = Path(getattr(cv2, '_native', cv2).__file__)
    package = Path(cv2.__file__).parent
    site = Path(distribution.locate_file(''))
    if (package != site / 'cv2' or native != package / 'cv2.pyd'
            or not site.resolve().is_relative_to(Path(sys.prefix).resolve())):
        raise RuntimeError('Loaded OpenCV is outside the active interpreter distribution')
    check_directory(package)
    inventory = {}
    for path in package.rglob('*'):
        if path.is_dir():
            check_directory(path)
            continue
        regular(path, maximum=200_000_000, allow_empty=True)
        relative = path.relative_to(site).as_posix()
        if path.parent.name == '__pycache__' and path.suffix == '.pyc':
            continue
        inventory[relative] = bytes_record(path.read_bytes())
    metadata_dir = Path(distribution.locate_file(metadata_paths[0])).parent
    check_directory(metadata_dir)
    metadata = {}
    for path in metadata_dir.rglob('*'):
        if path.is_dir():
            check_directory(path)
            continue
        metadata[path.relative_to(site).as_posix()] = bytes_record(regular(path, allow_empty=True).read_bytes())
    return {'run': {'id': str(uuid.uuid4()), 'pid': os.getpid(), 'created_unix': time.time()},
            'version': distribution.version, 'cv_version': cv2.__version__, 'metadata_fields': fields_identity,
            'loaded_native': file_record(native, maximum=200_000_000),
            'package_inventory': inventory, 'metadata_inventory': metadata,
            'dependencies': {name: importlib.metadata.version(name) for name in (*parity.DEPENDENCIES, 'PySide6-Essentials')},
            'cache_exclusion_rule': CACHE_RULE}


def verify_installed(identity, wheel, *, dependencies=None):
    for value in (identity, wheel):
        fields = value.get('metadata_fields')
        if (not isinstance(fields, dict) or set(fields) != {'raw_name', 'raw_version', 'normalized_name'}
                or normalized_distribution_name(fields['raw_name']) != 'opencv-python-headless'
                or fields['normalized_name'] != 'opencv-python-headless' or fields['raw_version'] != value['version']
                or value['version'] not in VERSIONS.values()):
            raise RuntimeError('Recorded raw distribution metadata identity differs')
    if not same(identity['metadata_fields'], wheel['metadata_fields']):
        raise RuntimeError('Installed raw Name/Version fields differ from exact wheel')
    if (identity['version'] != wheel['version'] or identity['cv_version'] != '5.0.0'
            or identity['cache_exclusion_rule'] != CACHE_RULE
            or any(identity['loaded_native'][key] != wheel['native'][key] for key in ('size', 'sha256'))
            or not same(identity['package_inventory'], wheel['package_inventory'])):
        raise RuntimeError('Loaded OpenCV/version/full installed cv2 inventory differs from exact wheel')
    expected = wheel['metadata_inventory']
    actual = identity['metadata_inventory']
    prefix = 'opencv_python_headless-' + wheel['version'] + '.dist-info/'
    if any(name not in expected and name not in {prefix + extra for extra in METADATA_EXTRAS} for name in actual):
        raise RuntimeError('Unexpected installed distribution metadata payload')
    for name, record in expected.items():
        if name != prefix + 'RECORD' and actual.get(name) != record:
            raise RuntimeError('Installed distribution metadata differs from wheel')
    if dependencies is not None and identity['dependencies'] != dependencies:
        raise RuntimeError('Pinned dependency inventory changed')


class OwnedJob:
    """Bound only our gated child and descendants, never enumerate other processes."""
    def __init__(self):
        class Limits(ctypes.Structure):
            _fields_ = [('process_time', ctypes.c_int64), ('job_time', ctypes.c_int64), ('flags', W.DWORD),
                ('minimum', ctypes.c_size_t), ('maximum', ctypes.c_size_t), ('active', W.DWORD),
                ('affinity', ctypes.c_size_t), ('priority', W.DWORD), ('scheduling', W.DWORD)]
        class IO(ctypes.Structure):
            _fields_ = [(name, ctypes.c_uint64) for name in ('read_ops', 'write_ops', 'other_ops', 'read_bytes', 'write_bytes', 'other_bytes')]
        class Extended(ctypes.Structure):
            _fields_ = [('basic', Limits), ('io', IO), ('process_memory', ctypes.c_size_t),
                ('job_memory', ctypes.c_size_t), ('peak_process', ctypes.c_size_t), ('peak_job', ctypes.c_size_t)]
        class Accounting(ctypes.Structure):
            _fields_ = [('user', ctypes.c_int64), ('kernel', ctypes.c_int64), ('period_user', ctypes.c_int64),
                ('period_kernel', ctypes.c_int64), ('faults', W.DWORD), ('total', W.DWORD),
                ('active', W.DWORD), ('terminated', W.DWORD)]
        self.Accounting = Accounting
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        for name, arguments, result in (
            ('CreateJobObjectW', [ctypes.c_void_p, W.LPCWSTR], W.HANDLE),
            ('SetInformationJobObject', [W.HANDLE, ctypes.c_int, ctypes.c_void_p, W.DWORD], W.BOOL),
            ('AssignProcessToJobObject', [W.HANDLE, W.HANDLE], W.BOOL),
            ('QueryInformationJobObject', [W.HANDLE, ctypes.c_int, ctypes.c_void_p, W.DWORD, ctypes.c_void_p], W.BOOL),
            ('TerminateJobObject', [W.HANDLE, W.UINT], W.BOOL), ('CloseHandle', [W.HANDLE], W.BOOL)):
            function = getattr(self.kernel, name); function.argtypes = arguments; function.restype = result
        self.handle = self.kernel.CreateJobObjectW(None, None)
        if not self.handle:
            raise RuntimeError('Cannot establish owned process job')
        limits = Extended(); limits.basic.flags = 0x2000  # KILL_ON_JOB_CLOSE; no breakaway.
        if not self.kernel.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            self.close()
            raise RuntimeError('Cannot bound owned process lifetime')

    def assign(self, process):
        if not self.kernel.AssignProcessToJobObject(self.handle, int(process._handle)):
            raise RuntimeError('Cannot assign gated child to owned process job')

    def active(self):
        result = self.Accounting()
        if not self.kernel.QueryInformationJobObject(self.handle, 1, ctypes.byref(result), ctypes.sizeof(result), None):
            raise RuntimeError('Cannot verify owned job process retirement')
        return result.active

    def terminate(self):
        if not self.kernel.TerminateJobObject(self.handle, 1):
            raise RuntimeError('Cannot terminate owned job')

    def close(self):
        if self.handle:
            if not self.kernel.CloseHandle(self.handle):
                raise RuntimeError('Cannot close owned process job')
            self.handle = None


class CommandFailure(RuntimeError):
    def __init__(self, record):
        super().__init__('Owned command failed: ' + record['action'] + '/' + record['label'])
        self.record = record


class Runner:
    def __init__(self):
        self.safe = True
        self.records = []

    def __call__(self, action, label):
        if not self.safe:
            raise RuntimeError('Earlier child retirement is unconfirmed; refusing any later command')
        if action not in TIMEOUTS or label not in {'prepare', 'initial', 'restore', *BLOCKS}:
            raise RuntimeError('Unexpected fixed child command')
        log = ROOT / 'reports' / (PREFIX + label + '-' + action + '.txt')
        log.parent.mkdir(exist_ok=True)
        check_directory(log.parent)
        if log.exists() or log.is_symlink():
            raise RuntimeError('Refusing to replace earlier command log')
        record = {'action': action, 'label': label, 'timeout_seconds': TIMEOUTS[action],
            'status': 'failed', 'returncode': None, 'child_exited': False,
            'owned_job_empty': False, 'job_closed': False, 'pipes_closed': False,
            'output_budget_exceeded': False, 'timed_out': False, 'pid': None,
            'termination_attempts': [], 'reader_exited': False, 'errors': []}
        self.records.append(record)
        self.safe = False
        process = job = reader = None
        buffer = bytearray(); exceeded = threading.Event()
        assigned = False
        try:
            job = OwnedJob()
            environment = builder.clean_environment()
            environment.update(ORT_DISABLE_TELEMETRY='1', PYTHONDONTWRITEBYTECODE='1')
            command = [sys.executable, '-u', '-B', str(Path(__file__).resolve()), '_child', action, label]
            process = subprocess.Popen(command, cwd=ROOT, env=environment, stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
            record['pid'] = process.pid
            def consume():
                try:
                    while True:
                        data = process.stdout.read(8192)
                        if not data:
                            break
                        room = MAX_LOG_BYTES - len(buffer)
                        buffer.extend(data[:max(0, room)])
                        if len(data) > room:
                            exceeded.set()
                except BaseException:
                    exceeded.set()
            reader = threading.Thread(target=consume, name='owned-crossover-output', daemon=True)
            reader.start()
            job.assign(process); assigned = True
            process.stdin.write(b'G'); process.stdin.flush(); process.stdin.close()
            deadline = time.monotonic() + TIMEOUTS[action]
            while process.poll() is None and not exceeded.is_set() and time.monotonic() < deadline:
                time.sleep(.05)
            record['timed_out'] = process.poll() is None and not exceeded.is_set()
            record['output_budget_exceeded'] = exceeded.is_set()
        except BaseException as error:
            record['errors'].append(type(error).__name__)
        finally:
            try:
                if process is not None:
                    if process.poll() is None:
                        if assigned:
                            record['termination_attempts'].append('active-child-job')
                            job.terminate()
                        else:
                            record['termination_attempts'].append('unassigned-gated-child')
                            process.kill()  # Gated child has not started any work/descendants.
                    process.wait(timeout=RETIRE_TIMEOUT)
                    record['returncode'] = process.returncode
                    record['child_exited'] = True
                if job is not None:
                    if job.active():
                        record['termination_attempts'].append('remaining-owned-descendants')
                        job.terminate()
                    deadline = time.monotonic() + RETIRE_TIMEOUT
                    while job.active() and time.monotonic() < deadline:
                        time.sleep(.05)
                    record['owned_job_empty'] = job.active() == 0
            except BaseException as error:
                record['errors'].append('retirement:' + type(error).__name__)
            finally:
                try:
                    if reader is not None:
                        reader.join(RETIRE_TIMEOUT)
                    record['reader_exited'] = reader is None or not reader.is_alive()
                    record['output_budget_exceeded'] = exceeded.is_set()
                except BaseException as error:
                    record['errors'].append('reader-retirement:' + type(error).__name__)
                if process is not None:
                    # BufferedReader.close can block on a live reader's lock.
                    # Retain that stream and fail closed; never synchronously close it.
                    for pipe in (process.stdin, process.stdout if record['reader_exited'] else None):
                        try:
                            if pipe is not None and not pipe.closed:
                                pipe.close()
                        except BaseException as error:
                            record['errors'].append('pipe-close:' + type(error).__name__)
                    try:
                        record['pipes_closed'] = all(pipe is None or pipe.closed for pipe in (process.stdin, process.stdout))
                    except BaseException as error:
                        record['errors'].append('pipe-observation:' + type(error).__name__)
                try:
                    if job is not None:
                        job.close(); record['job_closed'] = True
                except BaseException as error:
                    record['errors'].append('job-close:' + type(error).__name__)
                self.safe = (record['child_exited'] and record['owned_job_empty'] and record['job_closed']
                    and record['pipes_closed'] and record['reader_exited']
                    and not any(value.startswith(('reader-', 'pipe-', 'retirement:', 'job-close:')) for value in record['errors']))
                try:
                    with log.open('xb') as stream:
                        stream.write(buffer)
                    record['log'] = {'path': str(log), **bytes_record(buffer)}
                except BaseException as error:
                    record['errors'].append('log-write:' + type(error).__name__)
        if (not self.safe or record['errors'] or record['termination_attempts'] or record['returncode'] != 0
                or record['timed_out'] or record['output_budget_exceeded']):
            raise CommandFailure(record)
        record['status'] = 'completed'
        return record


def child(action, label):
    # Every native import, pip operation and fixture waits for Job assignment.
    if sys.stdin.buffer.read(1) != b'G':
        raise RuntimeError('Missing owned supervisor start gate')
    require_host()
    variant = 'A' if label in {'prepare', 'A1', 'A2'} else 'B'
    if action == 'identity':
        write_json(output_path(label + '-identity'), installed_identity())
    elif action == 'install':
        path = expected_wheel(variant)
        verified = wheel_identity(path, variant)
        if variant == 'A' and verified != read_json(output_path('prepared'))['official']:
            raise RuntimeError('Official wheel changed before offline install')
        sys.argv = ['pip', '--isolated', 'install', '--no-index', '--no-deps', '--no-cache-dir', '--force-reinstall', str(path)]
        runpy.run_module('pip', run_name='__main__', alter_sys=True)
    elif action == 'check':
        sys.argv = ['pip', '--isolated', 'check']
        runpy.run_module('pip', run_name='__main__', alter_sys=True)
    elif action == 'probe' and label in BLOCKS:
        # Execute the unchanged standalone CLI, including its os._exit cleanup guard.
        sys.argv = [str(ROOT / 'scripts' / 'probe_opencv_parity.py'), 'generate',
                    '--output', str(output_path(label + '-probe')), '--samples', '7', '--warmups', '2']
        runpy.run_path(sys.argv[0], run_name='__main__')
    else:
        raise RuntimeError('Invalid child action')


def validate_receipt(receipt):
    expected = {'action', 'label', 'timeout_seconds', 'status', 'returncode', 'pid',
        'child_exited', 'owned_job_empty', 'job_closed', 'pipes_closed', 'reader_exited',
        'output_budget_exceeded', 'timed_out', 'termination_attempts', 'errors', 'log'}
    if not isinstance(receipt, dict) or set(receipt) != expected:
        raise RuntimeError('Owned command receipt schema differs')
    if (receipt['action'] not in TIMEOUTS or receipt['label'] not in {'prepare', 'initial', 'restore', *BLOCKS}
            or type(receipt['timeout_seconds']) is not int or receipt['timeout_seconds'] != TIMEOUTS[receipt['action']]
            or receipt['status'] != 'completed' or type(receipt['returncode']) is not int or receipt['returncode'] != 0
            or type(receipt['pid']) is not int or receipt['pid'] <= 0
            or receipt['timed_out'] is not False or receipt['output_budget_exceeded'] is not False
            or receipt['errors'] != [] or receipt['termination_attempts'] != []
            or any(receipt[key] is not True for key in ('child_exited', 'owned_job_empty', 'job_closed', 'pipes_closed', 'reader_exited'))):
        raise RuntimeError('Owned command did not complete with fully verified retirement')
    log = receipt['log']
    if (not isinstance(log, dict) or set(log) != {'path', 'size', 'sha256'} or not isinstance(log['path'], str)
            or type(log['size']) is not int or not 0 <= log['size'] <= MAX_LOG_BYTES
            or not isinstance(log['sha256'], str) or not re.fullmatch('[0-9a-f]{64}', log['sha256'])):
        raise RuntimeError('Owned command log identity is invalid')


def verify_receipt(report, receipt):
    validate_receipt(receipt)
    run = report.get('run') if isinstance(report, dict) else None
    if not isinstance(run, dict) or type(run.get('pid')) is not int or run['pid'] != receipt['pid']:
        raise RuntimeError('Report PID does not match the exact launched child receipt')


def prepare(runner=None):
    require_host()
    if output_path('prepared').exists():
        raise RuntimeError('Official baseline is already bound; refusing replacement')
    runner = runner or Runner()
    result = {'schema_version': 1, 'status': 'failed', 'scope': SCOPE,
              'primary_error': None, 'commands': runner.records}
    try:
        sources = source_binding()
        wheel = wheel_identity(expected_wheel('A'), 'A')
        result.update(sources=sources, official=wheel)
        receipt = runner('identity', 'prepare')
        identity = read_json(output_path('prepare-identity'))
        verify_receipt(identity, receipt)
        verify_installed(identity, wheel)
        if sources != source_binding():
            raise RuntimeError('Source bytes changed while preparing official baseline')
        result.update(status='prepared', baseline_identity=identity,
                      baseline_identity_file=file_record(output_path('prepare-identity')))
    except BaseException as error:
        result['primary_error'] = error_record(error)
    finally:
        write_json(output_path('prepared'), result)
    return result


def capture_identity(report):
    capture = report['performance']['capture_synthetic_window']
    identity = copy.deepcopy(capture['capture_diagnostics']['identity_before_supplemental'])
    del identity['loaded']['cv2_native']
    return {'identity': identity, 'fixture': capture['fixture'],
            'backend': capture['capture_diagnostics']['authoritative_observations'][0]['backend'],
            'output': capture['capture_diagnostics']['expected_output'],
            'output_sha256': capture['output_sha256']}


def validate_block(report, wheel, prepared):
    errors = parity.validate_report(report)
    if errors:
        raise RuntimeError('Full parity report validation failed: ' + '; '.join(errors))
    if (report['host']['system'] != 'Windows' or report['opencv']['cv_version'] != '5.0.0'
            or report['opencv']['distributions'] != {'opencv-python-headless': wheel['version']}
            or any(report['native'][key] != wheel['native'][key] for key in ('sha256', 'size'))):
        raise RuntimeError('Probe host/version/actual loaded native differs from wheel')
    dependencies = {name: prepared['baseline_identity']['dependencies'][name] for name in parity.DEPENDENCIES}
    if report['dependencies'] != dependencies:
        raise RuntimeError('Probe dependency versions changed')
    for name in parity.SOURCE_FILES:
        if report['inputs'][name] != prepared['sources']['files'][name]['sha256']:
            raise RuntimeError('Probe source fingerprint differs from bound source')
    for name, record in report['performance'].items():
        expected_iterations = 3 if name == 'capture_synthetic_window' else (1 if name in {'ocr_app_demo', 'hero_1080p'} else 10)
        if (len(record['samples_seconds']), record['warmups'], record['iterations_per_sample']) != (7, 2, expected_iterations):
            raise RuntimeError('Original fixed sampling configuration differs')
    identity = capture_identity(report)
    if (identity['backend'] != 'windows-graphics-capture'
            or any(row['status'] != 'verified' or row['source_commit'] != prepared['sources']['commit']
                   for row in identity['identity']['helpers'].values())):
        raise RuntimeError('Crossover requires verified WGC helpers and the WGC backend')


def comparisons(blocks):
    if [block['label'] for block in blocks] != list(BLOCKS):
        raise RuntimeError('All four fixed blocks are required; no dropped/reordered/retried blocks')
    reports = [block['report'] for block in blocks]
    if len({report['run']['id'] for report in reports}) != 4 or len({report['run']['process_nonce'] for report in reports}) != 4:
        raise RuntimeError('Every full probe must be a distinct fresh interpreter')
    reference = reports[0]
    for report in reports[1:]:
        for key in ('host', 'inputs', 'models', 'dependencies', 'api_results', 'ocr_results', 'hero_results', 'coverage'):
            if not same(reference[key], report[key]):
                raise RuntimeError('Full report identity/exact output differs: ' + key)
        if not same(capture_identity(reference), capture_identity(report)):
            raise RuntimeError('Capture backend/helper/source/Pillow/fixture/exact output differs')
        if reference['opencv']['runtime'] != report['opencv']['runtime']:
            raise RuntimeError('Full-probe runtime thread/IPP/OpenCL settings differ')
        for name in reference['performance']:
            if reference['performance'][name]['output_sha256'] != report['performance'][name]['output_sha256']:
                raise RuntimeError('Exact original benchmark output differs')
    result = []
    for left, right, kind in ((0, 1, 'adjacent-forward'), (1, 2, 'adjacent-reversal'),
                               (2, 3, 'adjacent-forward'), (0, 2, 'official-drift'), (1, 3, 'custom-drift')):
        before, after = reports[left], reports[right]
        metrics = {}
        for name in sorted(before['performance']):
            a, b = before['performance'][name], after['performance'][name]
            metrics[name] = {'earlier_samples_seconds': a['samples_seconds'], 'later_samples_seconds': b['samples_seconds'],
                'earlier_median_seconds': a['median_seconds'], 'later_median_seconds': b['median_seconds'],
                'later_over_earlier': b['median_seconds'] / a['median_seconds'],
                'later_minus_earlier_seconds': b['median_seconds'] - a['median_seconds']}
        result.append({'earlier': BLOCKS[left], 'later': BLOCKS[right], 'kind': kind, 'performance': metrics})
    return result


def error_record(error):
    return {'type': type(error).__name__, 'message': str(error)[:1000]}


def run(runner=None):
    require_host()
    if output_path('result').exists():
        raise RuntimeError('Crossover result already exists; refusing another sequence')
    runner = runner or Runner()
    result = {'schema_version': 1, 'status': 'failed', 'scope': SCOPE, 'excluded_from_adoption': True,
        'fixed_order': list(BLOCKS), 'blocks': [], 'comparisons': [], 'primary_error': None,
        'restoration': {'status': 'not-run'}, 'commands': runner.records}
    custom = prepared = None
    try:
        # Establish the exact recovery wheel before any attempt to install A.
        custom = wheel_identity(expected_wheel('B'), 'B')
        result['custom'] = custom
        result['build_report_file'] = file_record(ROOT / 'reports' / 'windows-opencv-build.json')
        prepared = read_json(output_path('prepared'))
        result['prepared_file'] = file_record(output_path('prepared'))
        if prepared.get('schema_version') != 1 or prepared.get('status') != 'prepared' or prepared['sources'] != source_binding():
            raise RuntimeError('Prepared official baseline/source binding differs')
        official = wheel_identity(expected_wheel('A'), 'A')
        if official != prepared['official'] or file_record(output_path('prepare-identity')) != prepared['baseline_identity_file']:
            raise RuntimeError('Saved official wheel/baseline identity changed')
        verify_installed(prepared['baseline_identity'], official)
        result['sources'] = prepared['sources']
        receipt = runner('identity', 'initial')
        initial = read_json(output_path('initial-identity'))
        verify_receipt(initial, receipt)
        verify_installed(initial, custom, dependencies=prepared['baseline_identity']['dependencies'])
        result['initial_identity_file'] = file_record(output_path('initial-identity'))
        for label in BLOCKS:
            wheel = official if label[0] == 'A' else custom
            block = {'label': label, 'variant': label[0], 'status': 'started', 'wheel': wheel['wheel']}
            result['blocks'].append(block)
            if source_binding() != prepared['sources'] or wheel_identity(expected_wheel(label[0]), label[0]) != wheel:
                raise RuntimeError('Bound sources/wheel changed before fixed block')
            runner('install', label)
            receipt = runner('identity', label)
            identity = read_json(output_path(label + '-identity'))
            verify_receipt(identity, receipt)
            block['installed_identity_file'] = file_record(output_path(label + '-identity'))
            verify_installed(identity, wheel, dependencies=prepared['baseline_identity']['dependencies'])
            try:
                receipt = runner('probe', label)
            finally:
                path = output_path(label + '-probe')
                if path.exists():
                    try:
                        block['report_file'] = file_record(path)
                    except Exception as error:
                        block['report_file_error'] = error_record(error)
            report = read_json(output_path(label + '-probe'))
            # Retain full raw reports separately; their hashes bind all original samples.
            block['report'] = report
            verify_receipt(report, receipt)
            validate_block(report, wheel, prepared)
            if report['native']['path'] != identity['loaded_native']['path']:
                raise RuntimeError('Probe loaded extension location differs from installed identity check')
            if source_binding() != prepared['sources']:
                raise RuntimeError('Bound sources changed during fixed block')
            block['status'] = 'completed'
        result['comparisons'] = comparisons(result['blocks'])
        result['status'] = 'completed'
    except BaseException as error:
        result['primary_error'] = error_record(error)
    finally:
        if custom is None:
            result['restoration'] = {'status': 'blocked', 'reason': 'No validated exact B recovery wheel; no wheel change was attempted'}
        elif not runner.safe:
            result['restoration'] = {'status': 'blocked', 'reason': 'Prior owned process retirement is unconfirmed; reinstall is unsafe'}
        else:
            try:
                if wheel_identity(expected_wheel('B'), 'B') != custom:
                    raise RuntimeError('Recovery B wheel changed')
                runner('install', 'restore')
                receipt = runner('identity', 'restore')
                restored = read_json(output_path('restore-identity'))
                verify_receipt(restored, receipt)
                verify_installed(restored, custom, dependencies=prepared['baseline_identity']['dependencies'] if prepared else None)
                runner('check', 'restore')
                result['restoration'] = {'status': 'verified', 'identity_file': file_record(output_path('restore-identity')),
                                        'native': restored['loaded_native'], 'dependencies': restored['dependencies']}
            except BaseException as error:
                result['restoration'] = {'status': 'failed', 'error': error_record(error)}
        if result['restoration']['status'] != 'verified':
            result['status'] = 'failed'
        # Never substitute these supplemental samples into original gate reports.
        # Avoid duplicating megabytes of full reports in the bounded manifest.
        for block in result['blocks']:
            report = block.pop('report', None)
            if report is not None:
                # Invalid/partial reports must not replace the original failure.
                if isinstance(report, dict):
                    block['capture'] = report.get('performance', {}).get('capture_synthetic_window') if isinstance(report.get('performance'), dict) else None
                    block['probe_run'] = report.get('run')
                    block['native'] = report.get('native')
                    opencv = report.get('opencv') if isinstance(report.get('opencv'), dict) else {}
                    block['runtime'] = opencv.get('runtime')
                    block['imports'] = opencv.get('imported_python_submodules')
                else:
                    block['invalid_report_type'] = type(report).__name__
        write_json(output_path('result'), result)
    return result


def inventory_projection(value):
    if not isinstance(value, dict):
        return {'invalid_inventory_type': type(value).__name__}
    return {'entries': len(value), 'canonical_sha256': parity.sha256(parity.canonical(value).encode('utf-8')),
            'aggregate_bytes': sum(row['size'] for row in value.values() if isinstance(row, dict) and type(row.get('size')) is int)}


def identity_projection(value):
    result = copy.deepcopy(value)
    if isinstance(result, dict):
        for key in ('package_inventory', 'metadata_inventory'):
            if key in result:
                result[key] = inventory_projection(result[key])
    return result


def report_projection(value):
    if not isinstance(value, dict):
        return value
    result = copy.deepcopy(value)
    for key in ('api_results', 'ocr_results', 'hero_results'):
        if key in result:
            result[key] = {'scope': 'Raw-file-bound exact-result dictionary summary; payload is not rendered',
                           'cases': len(result[key]) if isinstance(result[key], dict) else None,
                           'canonical_sha256': parity.sha256(parity.canonical(result[key]).encode('utf-8'))}
    cv = result.get('opencv')
    if isinstance(cv, dict) and isinstance(cv.get('build_information'), str):
        cv['build_information'] = bytes_record(cv['build_information'].encode('utf-8'))
    # All original performance records are preserved verbatim, especially capture.
    return result


def render_projection(bundle):
    result = copy.deepcopy(bundle)
    result['projection_scope'] = ('Full raw files are SHA256-bound and revalidated. API/OCR/hero exact-result dictionaries '
        'and installed package/metadata maps render canonical hashes/counts instead of repeated contents. '
        'Every timing sample, full capture record, loaded identity, source/input hash, comparison, failure and command retirement receipt is retained. '
        'Only type-sensitively identical parsed duplicate values become references.')
    def parsed(label):
        row = bundle['files'].get(label, {})
        return row.get('value') if row.get('status') == 'read' else None
    for label, row in result['files'].items():
        if row.get('status') != 'read':
            continue
        value = row['value']
        if label.endswith('-probe'):
            row['value'] = report_projection(value)
        elif label.endswith('-identity'):
            row['value'] = identity_projection(value)
        elif isinstance(value, dict):
            for key in ('official', 'custom'):
                if key in value:
                    value[key] = identity_projection(value[key])
            if 'baseline_identity' in value:
                original = parsed('prepare-identity')
                value['baseline_identity'] = ({'raw_file_reference': 'prepare-identity'}
                    if isinstance(original, dict) and same(original, value['baseline_identity'])
                    else identity_projection(value['baseline_identity']))
            # Failed or missing raw evidence is never replaced by a dangling reference.
            if label == 'result' and isinstance(value.get('comparisons'), list):
                for comparison in value['comparisons']:
                    if not isinstance(comparison, dict) or not isinstance(comparison.get('performance'), dict):
                        continue
                    matches = True
                    for side in ('earlier', 'later'):
                        report = parsed(str(comparison.get(side)) + '-probe')
                        performance = report.get('performance') if isinstance(report, dict) else None
                        for name, metric in comparison['performance'].items():
                            actual = performance.get(name) if isinstance(performance, dict) else None
                            if (not isinstance(metric, dict) or not isinstance(actual, dict)
                                    or 'samples_seconds' not in actual or side + '_samples_seconds' not in metric
                                    or not same(metric[side + '_samples_seconds'], actual['samples_seconds'])):
                                matches = False
                    if matches:
                        comparison['all_raw_samples_reference'] = {
                            side: str(comparison.get(side)) + '-probe.value.performance.[case].samples_seconds'
                            for side in ('earlier', 'later')}
                        for metric in comparison['performance'].values():
                            metric.pop('earlier_samples_seconds')
                            metric.pop('later_samples_seconds')
            blocks = value.get('blocks')
            if isinstance(blocks, list):
                for block in blocks:
                    if not isinstance(block, dict):
                        continue
                    report = parsed(str(block.get('label')) + '-probe')
                    if not isinstance(report, dict):
                        continue
                    cv = report.get('opencv') if isinstance(report.get('opencv'), dict) else {}
                    performance = report.get('performance') if isinstance(report.get('performance'), dict) else {}
                    equivalents = {'capture': performance.get('capture_synthetic_window'),
                        'probe_run': report.get('run'), 'native': report.get('native'),
                        'runtime': cv.get('runtime'), 'imports': cv.get('imported_python_submodules')}
                    for key, equivalent in equivalents.items():
                        if key in block and equivalent is not None and same(block[key], equivalent):
                            block.pop(key)
    if len(json.dumps(result, ensure_ascii=True, indent=2, allow_nan=False).encode('utf-8')) > MAX_RENDER_BYTES:
        raise RuntimeError('Complete relevant rendered evidence exceeds fixed 256 KiB budget')
    return result


def summarize():
    """Read-only bounded complete evidence, including partial/failed raw reports."""
    bundle = {'schema_version': 1, 'status': 'failed', 'scope': SCOPE,
              'excluded_from_adoption': True, 'validation_errors': [], 'files': {}}
    # Fixed inventory only. Never consume a path from untrusted report JSON.
    labels = ['prepared', 'result', 'prepare-identity', 'initial-identity', 'restore-identity']
    labels += [label + suffix for label in BLOCKS for suffix in ('-identity', '-probe')]
    for label in labels:
        path = output_path(label)
        if not path.exists():
            bundle['files'][label] = {'status': 'absent'}
            continue
        try:
            bundle['files'][label] = {'status': 'reading', 'raw_file': file_record(path)}
            bundle['files'][label].update(status='read', value=read_json(path))
        except Exception as error:
            bundle['files'].setdefault(label, {}).update(status='invalid', error=error_record(error))
            bundle['validation_errors'].append(label + ': invalid or over-budget evidence')
    try:
        prepared = bundle['files']['prepared']['value']
        result = bundle['files']['result']['value']
        if (result.get('schema_version') != 1 or result.get('excluded_from_adoption') is not True
                or result.get('fixed_order') != list(BLOCKS) or prepared.get('status') != 'prepared'):
            raise RuntimeError('Invalid or incomplete crossover preparation/protocol')
        if result.get('sources') != prepared.get('sources'):
            raise RuntimeError('Result source binding differs from preparation')
        if bundle['files']['prepared']['raw_file'] != result['prepared_file']:
            raise RuntimeError('Prepared proof raw hash changed')
        if bundle['files']['prepare-identity']['raw_file'] != prepared['baseline_identity_file']:
            raise RuntimeError('Official baseline identity raw hash changed')
        if bundle['files']['prepare-identity']['value'] != prepared['baseline_identity']:
            raise RuntimeError('Official baseline identity payload changed')
        verify_installed(prepared['baseline_identity'], prepared['official'])
        if result['status'] != 'completed' or result['restoration']['status'] != 'verified':
            raise RuntimeError('Fixed sequence or verified B restoration did not complete')
        if [row['label'] for row in result['blocks']] != list(BLOCKS):
            raise RuntimeError('Fixed block order differs')
        expected_commands = [('identity', 'initial')] + [(action, label) for label in BLOCKS
            for action in ('install', 'identity', 'probe')] + [('install', 'restore'), ('identity', 'restore'), ('check', 'restore')]
        if [(row['action'], row['label']) for row in result['commands']] != expected_commands:
            raise RuntimeError('Fixed child command sequence differs')
        blocks = []
        dependencies = prepared['baseline_identity']['dependencies']
        def receipt(action, label, records):
            matches = [item for item in records if item['action'] == action and item['label'] == label]
            if len(matches) != 1:
                raise RuntimeError('Missing/duplicate exact child receipt')
            item = matches[0]
            validate_receipt(item)
            return item
        if [(row['action'], row['label']) for row in prepared['commands']] != [('identity', 'prepare')]:
            raise RuntimeError('Preparation child command sequence differs')
        verify_receipt(prepared['baseline_identity'], receipt('identity', 'prepare', prepared['commands']))
        for label in ('initial', 'restore', *BLOCKS):
            identity = bundle['files'][label + '-identity']['value']
            wheel = prepared['official'] if label in {'A1', 'A2'} else result['custom']
            verify_installed(identity, wheel, dependencies=dependencies)
            verify_receipt(identity, receipt('identity', label, result['commands']))
        if bundle['files']['initial-identity']['raw_file'] != result['initial_identity_file']:
            raise RuntimeError('Initial B identity raw hash changed')
        if bundle['files']['restore-identity']['raw_file'] != result['restoration']['identity_file']:
            raise RuntimeError('Restored B identity raw hash changed')
        for label in (*BLOCKS, 'restore'):
            receipt('install', label, result['commands'])
        receipt('check', 'restore', result['commands'])
        for row in result['blocks']:
            if row.get('status') != 'completed':
                raise RuntimeError('Fixed block did not complete')
            label = row['label']
            if (bundle['files'][label + '-probe']['raw_file'] != row['report_file']
                    or bundle['files'][label + '-identity']['raw_file'] != row['installed_identity_file']):
                raise RuntimeError('Raw block report/identity hash changed')
            report = bundle['files'][label + '-probe']['value']
            validate_block(report, prepared['official'] if label[0] == 'A' else result['custom'], prepared)
            verify_receipt(report, receipt('probe', label, result['commands']))
            blocks.append({'label': label, 'report': report})
        if comparisons(blocks) != result['comparisons']:
            raise RuntimeError('Fixed-block arithmetic changed')
        if not bundle['validation_errors']:
            bundle['status'] = 'completed'
    except Exception as error:
        bundle['validation_errors'].append(error_record(error))
    # Project only after full raw validation. Failure evidence is projected too;
    # never discard a measured sample, failed block, error, or cleanup receipt.
    return render_projection(bundle)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='operation', required=True)
    for name in ('prepare', 'run', 'summarize'):
        commands.add_parser(name)
    internal = commands.add_parser('_child', help=argparse.SUPPRESS)
    internal.add_argument('action', choices=tuple(TIMEOUTS))
    internal.add_argument('label', choices=('prepare', 'initial', 'restore', *BLOCKS))
    args = parser.parse_args(argv)
    try:
        if args.operation == '_child':
            child(args.action, args.label)
            return 0
        if args.operation == 'prepare':
            result = prepare()
            summary = {'status': result['status'], 'official_native': result.get('official', {}).get('native'),
                       'primary_error': result['primary_error']}
        elif args.operation == 'run':
            result = run()
            summary = {'status': result['status'], 'primary_error': result['primary_error'], 'restoration': result['restoration']}
        else:
            summary = summarize()
        print(json.dumps(summary, ensure_ascii=True, indent=2, allow_nan=False), flush=True)
        return 1 if summary['status'] == 'failed' else 0
    except Exception as error:
        print(json.dumps({'status': 'failed', 'error': error_record(error)}), flush=True)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

"""Bounded, offline staging tests of the unchanged frozen Windows OTA transaction.

This is a same-binary reinstallation, NOT a genuine two-version upgrade. Local
fixture plans deliberately bypass discovery, download, UI consent and the
launch_update() handoff. Only the released EXE may write its health marker.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import ctypes
from ctypes import wintypes as W
import errno
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
from windows_exe_smoke import isolated_windows_environment, smoke_workspace
from windows_session_fixture import poll_owned_json

EXPECTED_SHA256 = '40b8d2af8309278b9cf6a5eace8ca26d6a483f659578d441636b86369d66cf6e'
EXPECTED_SIZE = 150155259
CONTROL_TITLE = 'VGA乱斗助手 · 原生控制台'
LIGHT_CONTROL_TITLE = 'VGA乱斗助手'
OVERLAY_TITLE = 'VGA乱斗助手 · 资料叠加'
MAX_JSON = 65536
MAX_EVIDENCE = 2 * 1024 * 1024


def control_title_for_version(version):
    # One exact title per known release, never a prefix or a fallback to another
    # window. Keep the pinned v0.3.0 walkthrough's legacy default unchanged.
    if version in ('0.3.0', '0.4.0', '0.4.1', '0.4.2', '0.4.3', '0.4.4', '0.4.5', '0.4.6'):
        return CONTROL_TITLE
    if version in ('0.4.7', '0.4.8'):
        return LIGHT_CONTROL_TITLE
    raise AssertionError('No exact native control title is bound to this application version')


def sha256(path):
    with Path(path).open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def read_json(path, limit=MAX_JSON):
    path = Path(path)
    if path.stat().st_size > limit:
        raise AssertionError('JSON evidence exceeds its size limit')
    with path.open('r', encoding='utf-8') as source:
        return json.load(source)


def write_json(path, value):
    path = Path(path)
    encoded = (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    if len(encoded) > MAX_JSON:
        raise AssertionError('JSON evidence exceeds its size limit')
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_bytes(encoded)
    temporary.replace(path)


def different_version(version):
    parts = version.split('.')
    if len(parts) not in (2, 3) or any(not x.isascii() or not x.isdecimal() or len(x) > 5 for x in parts):
        raise AssertionError('Unexpected released application version')
    numbers = [int(x) for x in parts] + [0] * (3 - len(parts))
    numbers[2] = (numbers[2] + 1) % 100000
    return '.'.join(map(str, numbers))


def prepare_fixture_plan(target, state_dir, name, parent_pid, version, digest):
    """Local fixture preparation only; never invokes download or forges health."""
    job = Path(state_dir) / 'updates' / ('update-' + name)
    job.mkdir(parents=True, exist_ok=False)
    for name in ('candidate.bin', 'updater.exe'):
        shutil.copyfile(target, job / name)
        if sha256(job / name) != digest:
            raise AssertionError('Fixture copy differs from the unchanged released EXE')
    filename = f'vga-aram-helper-{version}-windows-x64.exe'
    plan = {'schema_version': 1,
            'manifest': {'schema_version': 1, 'version': version, 'platform': 'windows-x64',
                         'url': f'https://github.com/Junming-Liang/vga-aram-helper/releases/download/v{version}/{filename}',
                         'sha256': digest, 'size': Path(target).stat().st_size},
            'target': str(Path(target).resolve()), 'job': str(job.resolve()), 'parent_pid': parent_pid,
            'original_sha256': digest, 'created_at': time.time(), 'health_token': secrets.token_hex(24)}
    path = job / 'plan.json'
    write_json(path, plan)
    return path, plan


@contextmanager
def rejecting_proxy():
    """Reject child HTTPS CONNECT requests locally; never forward/intercept TLS."""
    counts = {'rejected_requests': 0}

    class Handler(BaseHTTPRequestHandler):
        def reject(self):
            counts['rejected_requests'] += 1
            self.send_response(403)
            self.send_header('Content-Length', '0')
            self.send_header('Connection', 'close')
            self.end_headers()
            self.close_connection = True

        do_CONNECT = do_GET = do_POST = reject

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}', counts
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        if thread.is_alive():
            raise AssertionError('Rejecting proxy did not shut down')


def child_environment(environ, work, proxy):
    env = isolated_windows_environment(environ, work)
    for name in tuple(env):
        if name.startswith('_PYI_') or name in ('QT_QPA_PLATFORM', 'QT_PLUGIN_PATH', 'QT_QPA_PLATFORM_PLUGIN_PATH'):
            env.pop(name)
    temporary = Path(work) / 'temporary'
    temporary.mkdir(parents=True, exist_ok=True)
    env.update(TEMP=str(temporary), TMP=str(temporary), PYINSTALLER_RESET_ENVIRONMENT='1',
               HTTP_PROXY=proxy, HTTPS_PROXY=proxy, ALL_PROXY=proxy, NO_PROXY='127.0.0.1,localhost')
    return env


class Deadline:
    def __init__(self, seconds):
        self.end = time.monotonic() + seconds

    def until(self, seconds, other=None):
        return min(self.end, time.monotonic() + seconds, other if other is not None else self.end)

    @staticmethod
    def wait(predicate, end, description):
        while time.monotonic() < end:
            value = predicate()
            if value:
                return value
            time.sleep(.1)
        raise TimeoutError(description)


class NativeJob:
    """Private Windows job: suspended launches are assigned before any code runs.

    Descendants stay in the job after their updater parent exits. No process is
    selected by a broad executable name, and no unrelated process is terminated.
    """
    def __init__(self):
        if os.name != 'nt':
            raise RuntimeError('NativeJob requires Windows')
        self.k = ctypes.WinDLL('kernel32', use_last_error=True)
        self.u = ctypes.WinDLL('user32', use_last_error=True)
        self.handles = []
        self.callback_type = ctypes.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)

        class Startup(ctypes.Structure):
            _fields_ = [('cb', W.DWORD), ('reserved', W.LPWSTR), ('desktop', W.LPWSTR), ('title', W.LPWSTR),
                        ('x', W.DWORD), ('y', W.DWORD), ('xs', W.DWORD), ('ys', W.DWORD),
                        ('xc', W.DWORD), ('yc', W.DWORD), ('fill', W.DWORD), ('flags', W.DWORD),
                        ('show', W.WORD), ('reserved2_size', W.WORD), ('reserved2', ctypes.POINTER(ctypes.c_byte)),
                        ('stdin', W.HANDLE), ('stdout', W.HANDLE), ('stderr', W.HANDLE)]

        class ProcessInfo(ctypes.Structure):
            _fields_ = [('process', W.HANDLE), ('thread', W.HANDLE), ('pid', W.DWORD), ('tid', W.DWORD)]

        class BasicLimits(ctypes.Structure):
            _fields_ = [('process_time', ctypes.c_int64), ('job_time', ctypes.c_int64), ('flags', W.DWORD),
                        ('minimum', ctypes.c_size_t), ('maximum', ctypes.c_size_t), ('active_limit', W.DWORD),
                        ('affinity', ctypes.c_size_t), ('priority', W.DWORD), ('scheduling', W.DWORD)]

        class IO(ctypes.Structure):
            _fields_ = [(name, ctypes.c_uint64) for name in ('read_ops', 'write_ops', 'other_ops', 'read_bytes', 'write_bytes', 'other_bytes')]

        class Limits(ctypes.Structure):
            _fields_ = [('basic', BasicLimits), ('io', IO), ('process_memory', ctypes.c_size_t),
                        ('job_memory', ctypes.c_size_t), ('peak_process', ctypes.c_size_t), ('peak_job', ctypes.c_size_t)]

        self.Startup, self.ProcessInfo = Startup, ProcessInfo
        signatures = {
            'CreateJobObjectW': ([ctypes.c_void_p, W.LPCWSTR], W.HANDLE),
            'SetInformationJobObject': ([W.HANDLE, ctypes.c_int, ctypes.c_void_p, W.DWORD], W.BOOL),
            'QueryInformationJobObject': ([W.HANDLE, ctypes.c_int, ctypes.c_void_p, W.DWORD, ctypes.POINTER(W.DWORD)], W.BOOL),
            'AssignProcessToJobObject': ([W.HANDLE, W.HANDLE], W.BOOL),
            'TerminateJobObject': ([W.HANDLE, W.UINT], W.BOOL),
            'CloseHandle': ([W.HANDLE], W.BOOL),
            'CreateProcessW': ([W.LPCWSTR, W.LPWSTR, ctypes.c_void_p, ctypes.c_void_p, W.BOOL, W.DWORD,
                                ctypes.c_void_p, W.LPCWSTR, ctypes.POINTER(Startup), ctypes.POINTER(ProcessInfo)], W.BOOL),
            'ResumeThread': ([W.HANDLE], W.DWORD),
            'TerminateProcess': ([W.HANDLE, W.UINT], W.BOOL),
            'WaitForSingleObject': ([W.HANDLE, W.DWORD], W.DWORD),
            'GetExitCodeProcess': ([W.HANDLE, ctypes.POINTER(W.DWORD)], W.BOOL),
            'OpenProcess': ([W.DWORD, W.BOOL, W.DWORD], W.HANDLE),
            'QueryFullProcessImageNameW': ([W.HANDLE, W.DWORD, W.LPWSTR, ctypes.POINTER(W.DWORD)], W.BOOL),
        }
        for name, (args, result) in signatures.items():
            function = getattr(self.k, name)
            function.argtypes, function.restype = args, result
        self.u.EnumWindows.argtypes = (self.callback_type, W.LPARAM)
        self.u.EnumWindows.restype = W.BOOL
        self.u.GetWindowThreadProcessId.argtypes = (W.HWND, ctypes.POINTER(W.DWORD))
        self.u.GetWindowThreadProcessId.restype = W.DWORD
        self.u.GetWindowTextW.argtypes = (W.HWND, W.LPWSTR, ctypes.c_int)
        self.u.GetWindowTextW.restype = ctypes.c_int
        self.u.IsWindowVisible.argtypes = (W.HWND,)
        self.u.IsWindowVisible.restype = W.BOOL
        self.u.PostMessageW.argtypes = (W.HWND, W.UINT, W.WPARAM, W.LPARAM)
        self.u.PostMessageW.restype = W.BOOL
        self.u.GetWindowLongPtrW.argtypes = (W.HWND, ctypes.c_int)
        self.u.GetWindowLongPtrW.restype = ctypes.c_ssize_t
        self.job = self.k.CreateJobObjectW(None, None)
        if not self.job:
            raise ctypes.WinError(ctypes.get_last_error())
        limits = Limits()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self.k.SetInformationJobObject(self.job, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            self.k.CloseHandle(self.job)
            raise ctypes.WinError(ctypes.get_last_error())

    def spawn(self, executable, arguments, env, cwd):
        command = ctypes.create_unicode_buffer(subprocess.list2cmdline([str(executable), *map(str, arguments)]))
        block = ctypes.create_unicode_buffer('\0'.join(f'{key}={value}' for key, value in sorted(env.items())) + '\0\0')
        startup, info = self.Startup(), self.ProcessInfo()
        startup.cb = ctypes.sizeof(startup)
        # CREATE_SUSPENDED | CREATE_UNICODE_ENVIRONMENT; no inherited handles.
        if not self.k.CreateProcessW(str(executable), command, None, None, False, 0x4 | 0x400,
                                     ctypes.cast(block, ctypes.c_void_p), str(cwd), ctypes.byref(startup), ctypes.byref(info)):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            if not self.k.AssignProcessToJobObject(self.job, info.process):
                raise ctypes.WinError(ctypes.get_last_error())
            if self.k.ResumeThread(info.thread) == 0xFFFFFFFF:
                raise ctypes.WinError(ctypes.get_last_error())
        except BaseException:
            self.k.TerminateProcess(info.process, 98)
            self.k.WaitForSingleObject(info.process, 10000)
            self.k.CloseHandle(info.process)
            raise
        finally:
            self.k.CloseHandle(info.thread)
        self.handles.append(info.process)
        return {'handle': info.process, 'pid': info.pid}

    def poll(self, process):
        status = self.k.WaitForSingleObject(process['handle'], 0)
        if status == 258:
            return None
        if status != 0:
            raise ctypes.WinError(ctypes.get_last_error())
        code = W.DWORD()
        if not self.k.GetExitCodeProcess(process['handle'], ctypes.byref(code)):
            raise ctypes.WinError(ctypes.get_last_error())
        return int(code.value)

    def wait_exit(self, process, end):
        Deadline.wait(lambda: self.poll(process) is not None, end, 'Owned EXE did not exit before its deadline')
        return self.poll(process)

    def pids(self):
        capacity = 128
        buffer = ctypes.create_string_buffer(8 + capacity * ctypes.sizeof(ctypes.c_size_t))
        returned = W.DWORD()
        if not self.k.QueryInformationJobObject(self.job, 3, buffer, len(buffer), ctypes.byref(returned)):
            raise ctypes.WinError(ctypes.get_last_error())
        assigned, count = (W.DWORD * 2).from_buffer(buffer)
        if count > capacity or assigned > capacity:
            raise AssertionError('Unexpected process count in isolated test job')
        return set((ctypes.c_size_t * count).from_buffer(buffer, 8))

    def image(self, pid):
        handle = self.k.OpenProcess(0x1000, False, pid)  # query-limited only
        if not handle:
            return None  # A process can exit between enumeration and this query.
        try:
            buffer, size = ctypes.create_unicode_buffer(32768), W.DWORD(32768)
            if not self.k.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                return None
            return os.path.normcase(os.path.abspath(buffer.value))
        finally:
            self.k.CloseHandle(handle)

    def image_pids(self, executable):
        expected = os.path.normcase(os.path.abspath(executable))
        return {pid for pid in self.pids() if self.image(pid) == expected}

    def windows(self, executable, title=CONTROL_TITLE, visible=True):
        owned = self.image_pids(executable)
        found = []

        def visit(hwnd, _):
            pid = W.DWORD()
            self.u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value not in owned:
                return True
            text = ctypes.create_unicode_buffer(1024)
            self.u.GetWindowTextW(hwnd, text, len(text))
            if text.value == title and (not visible or self.u.IsWindowVisible(hwnd)):
                found.append({'hwnd': int(hwnd), 'pid': pid.value})
            return True

        callback = self.callback_type(visit)
        if not self.u.EnumWindows(callback, 0):
            raise ctypes.WinError(ctypes.get_last_error())
        return found

    def close_window(self, window):
        if not self.u.PostMessageW(window['hwnd'], 0x0010, 0, 0):  # WM_CLOSE
            raise ctypes.WinError(ctypes.get_last_error())

    def close_application(self, executable, deadline, title=CONTROL_TITLE):
        windows = self.windows(executable, title)
        if len(windows) != 1:
            raise AssertionError('Expected exactly one owned visible native control window')
        self.close_window(windows[0])
        Deadline.wait(lambda: not self.image_pids(executable), deadline, 'Native application did not close gracefully')

    def cleanup(self):
        try:
            if self.pids():
                if not self.k.TerminateJobObject(self.job, 99):
                    raise ctypes.WinError(ctypes.get_last_error())
                Deadline.wait(lambda: not self.pids(), time.monotonic() + 15, 'Owned process-job cleanup timed out')
        finally:
            for handle in self.handles:
                self.k.CloseHandle(handle)
            self.k.CloseHandle(self.job)


def lock_available(target):
    import msvcrt
    path = Path(str(target) + '.update.lock')
    if not path.exists():
        return True
    with path.open('r+b') as handle:
        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                raise
            return False
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return True


class TargetObserver:
    """Bounded observations, not a power-failure or mathematical atomicity proof."""
    def __init__(self, target):
        self.target = target
        self.stop = threading.Event()
        self.samples = 0
        self.identities = []
        self.errors = []
        self.thread = threading.Thread(target=self.run, daemon=True)

    def run(self):
        while not self.stop.is_set():
            try:
                stat = self.target.stat()
                value = [stat.st_ino, stat.st_size]
                if not self.identities or self.identities[-1] != value:
                    if len(self.identities) >= 16:
                        raise AssertionError('Too many target identity changes')
                    self.identities.append(value)
                self.samples += 1
            except Exception as exc:
                self.errors.append(type(exc).__name__)
                return
            self.stop.wait(.02)

    def finish(self):
        self.stop.set()
        self.thread.join(timeout=2)
        if self.thread.is_alive() or self.errors or not self.samples:
            raise AssertionError('Target continuity observation failed: ' + repr(self.errors))
        return {'samples': self.samples, 'identities_and_sizes': self.identities, 'missing_or_unreadable_samples': 0,
                'scope': 'Bounded file-stat observations; not a crash/power-failure atomicity guarantee.'}


def validate_old_ready(ready, version):
    if (ready.get('applicationVersion') != version or ready.get('frozen') is not True
            or ready.get('mode') != 'native-overlay' or type(ready.get('pid')) is not int or ready['pid'] <= 0):
        raise AssertionError('Old application did not provide genuine native frozen readiness')


def collect_logs(state, report_dir, name):
    evidence = []
    folder = Path(state) / 'logs'
    for path in sorted(folder.glob('*.txt'))[:8]:
        if path.stat().st_size > MAX_JSON:
            raise AssertionError('Native log exceeds 64 KiB evidence limit')
        destination = report_dir / ('windows-ota-' + name + '-' + path.name)
        shutil.copyfile(path, destination)
        evidence.append(destination.name)
    return evidence


def run_case(kind, original, root, report_dir, native, budget, proxy, version, digest, control_title):
    work = root / kind
    work.mkdir()
    target = work / 'VGA-Aram-Helper.exe'
    shutil.copyfile(original, target)
    env = child_environment(os.environ, work, proxy)
    state = Path(env['VGA_STATE_DIR'])
    report = {'case': kind, 'status': 'failed', 'candidate_kind': 'unmodified-same-binary',
              'expected_control_title': control_title, 'checks': []}
    observer = None
    try:
        ready_path = work / 'old-ready.json'
        old = native.spawn(target, ['--demo', '--no-updates', '--ready-file', ready_path], env, work)

        def old_ready():
            if native.poll(old) is not None:
                raise AssertionError('Old native EXE exited before readiness')
            return poll_owned_json(ready_path, read_json)

        ready = Deadline.wait(old_ready, budget.until(60), 'Old native application readiness timed out')
        validate_old_ready(ready, version)
        windows = native.windows(target, control_title)
        if len(windows) != 1 or windows[0]['pid'] != ready['pid']:
            raise AssertionError('Native ready PID does not own the visible control window')
        original_identity = target.stat().st_ino
        if not original_identity:
            raise AssertionError('Windows target file identity is unavailable')
        expected_version = version if kind == 'success-concurrency' else different_version(version)
        path, plan = prepare_fixture_plan(target, state, 'first', ready['pid'], expected_version, digest)
        second_path = None
        if kind == 'success-concurrency':
            second_path, _ = prepare_fixture_plan(target, state, 'second', ready['pid'], version, digest)
        observer = TargetObserver(target)
        observer.thread.start()
        started = time.monotonic()
        updater_deadline = budget.until(210)
        updater = native.spawn(path.parent / 'updater.exe', ['--apply-update', path], env, work)
        Deadline.wait(lambda: not lock_available(target), budget.until(20, updater_deadline), 'Real updater never acquired the target lock')
        backup = Path(str(target) + '.previous')
        if second_path:
            second = native.spawn(second_path.parent / 'updater.exe', ['--apply-update', second_path], env, work)
            if native.wait_exit(second, budget.until(45, started + 70)) != 1:
                raise AssertionError('Competing updater did not fail with code 1')
            second_result = read_json(second_path.parent / 'result.json')
            if second_result.get('state') != 'failed' or 'Another updater is already installing' not in second_result.get('message', ''):
                raise AssertionError('Competing updater did not report target-lock rejection')
            if list(second_path.parent.glob('health.json')):
                raise AssertionError('Rejected updater created a health marker')
            report['checks'].append('Independent frozen competing updater rejected by the Windows target lock')
        # The original real application is still running. No replacement, backup,
        # result or health marker may exist until its native window is closed.
        if (native.poll(old) is not None or ready['pid'] not in native.pids() or not native.u.IsWindowVisible(windows[0]['hwnd'])
                or native.poll(updater) is not None or sha256(target) != digest or target.stat().st_ino != original_identity or backup.exists()
                or (path.parent / 'health.json').exists() or (path.parent / 'result.json').exists()):
            raise AssertionError('Updater mutated the target or stopped while its real parent was alive')
        report['checks'].append('Real updater waited while the old native window and process remained alive; target unchanged')
        native.close_window(windows[0])
        if native.wait_exit(old, budget.until(20, updater_deadline)) != 0:
            raise AssertionError('Old native application did not exit cleanly after WM_CLOSE')
        Deadline.wait(lambda: ready['pid'] not in native.pids(), budget.until(5, updater_deadline), 'Old frozen worker survived WM_CLOSE')
        report['checks'].append('WM_CLOSE caused clean old-app bootloader and native-worker exit')
        code = native.wait_exit(updater, updater_deadline)
        updater_elapsed = time.monotonic() - started
        result = read_json(path.parent / 'result.json')
        if sha256(target) != digest or target.stat().st_size != original.stat().st_size:
            raise AssertionError('Installed/restored bytes differ from the unchanged source EXE')
        if target.stat().st_ino == original_identity:
            raise AssertionError('No actual target file replacement was observed')
        if kind == 'success-concurrency':
            if code != 0 or result != {'state': 'installed', 'version': version, 'backup': str(backup), 'signed': False}:
                raise AssertionError('Same-binary transaction did not report installation success')
            marker = read_json(path.parent / 'health.json', 1024)
            if marker != {'token': plan['health_token'], 'version': version}:
                raise AssertionError('Production native/OCR health token or running version did not match')
            if not backup.is_file() or sha256(backup) != digest:
                raise AssertionError('Successful transaction did not preserve the exact original backup')
            report['checks'].append('Actual replacement/relaunch passed production native Windows and bundled OCR health gates; token/version match')
            report['checks'].append('Successful .previous backup and target match the original released bytes')
        else:
            if code != 1 or result.get('state') != 'rolled_back' or (path.parent / 'health.json').exists():
                raise AssertionError('Wrong expected version did not roll back without a health marker')
            error_path = state / 'logs' / 'native-ready-error.txt'
            if not error_path.is_file() or error_path.stat().st_size > MAX_JSON:
                raise AssertionError('Version-health failure evidence is missing or oversized')
            if 'Running application version does not match the approved release' not in error_path.read_text(encoding='utf-8'):
                raise AssertionError('Rollback did not reach the intended production version-mismatch check')
            if backup.exists():
                raise AssertionError('Successful rollback should consume the .previous recovery copy')
            report['checks'].append('Actual native candidate rejected the mismatched expected version after OCR; no health marker')
            report['checks'].append('Updater restored exact original bytes from .previous and reported rolled_back')
        relaunched = Deadline.wait(lambda: native.windows(target, control_title), budget.until(30), 'Relaunched native control window was not visible')
        if len(relaunched) != 1 or relaunched[0]['pid'] == ready['pid']:
            raise AssertionError('Expected a new owned native application process')
        overlays = native.windows(target, OVERLAY_TITLE, visible=False)
        required = 0x00080000 | 0x08000000 | 0x80 | 0x8 | 0x20
        if len(overlays) != 1 or native.u.GetWindowLongPtrW(overlays[0]['hwnd'], -20) & required != required:
            raise AssertionError('Relaunched application lacks its real native safe-overlay styles')
        report['checks'].append('Relaunched/restored app owns a visible native control window and configured Win32 overlay')
        report['target_observation'] = observer.finish()
        observer = None
        if any(size != original.stat().st_size for _, size in report['target_observation']['identities_and_sizes']):
            raise AssertionError('Observed incomplete target file size')
        if not lock_available(target):
            raise AssertionError('Updater left the OS target lock held after exit')
        if list(work.glob(target.name + '.update-*.new')) or list(work.glob(target.name + '.update-*.backup')):
            raise AssertionError('Completed transaction left adjacent staging files')
        native.close_application(target, budget.until(25), title=control_title)
        Deadline.wait(lambda: not native.pids(), budget.until(10), 'Owned process descendants survived graceful shutdown')
        report['checks'].append('New native window closed cleanly; updater lock released; no surviving job descendants')
        report.update(status='passed', expected_version=expected_version, running_version=version,
                      updater_exit_code=code, updater_elapsed_seconds=round(updater_elapsed, 3),
                      original_sha256=digest, target_sha256=sha256(target), actual_file_identity_changed=True)
        return report
    except BaseException as exc:
        report['error'] = str(exc)[:2000]
        raise
    finally:
        if observer is not None:
            try:
                report['target_observation'] = observer.finish()
            except Exception as exc:
                report['observation_error'] = str(exc)[:1000]
        report['logs'] = collect_logs(state, report_dir, kind)
        write_json(report_dir / ('windows-ota-' + kind + '.json'), report)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exe', type=Path, required=True)
    parser.add_argument('--report-dir', type=Path, default=ROOT / 'reports')
    parser.add_argument('--expected-sha256', default=EXPECTED_SHA256)
    parser.add_argument('--expected-size', type=int, default=EXPECTED_SIZE)
    parser.add_argument('--release-source-sha', default=None)
    args = parser.parse_args()
    if os.name != 'nt' or ctypes.sizeof(ctypes.c_void_p) != 8:
        raise SystemExit('Requires actual x64 Windows, the frozen EXE and a native interactive desktop')
    original = args.exe.resolve(strict=True)
    reports = args.report_dir.resolve()
    reports.mkdir(parents=True, exist_ok=True)
    report = {'status': 'failed', 'scope': 'Local fixture-plan, unchanged same-binary frozen Windows OTA transactions',
              'harness_sha256': sha256(__file__), 'harness_source_commit': os.environ.get('GITHUB_SHA'),
              'release_source_commit': args.release_source_sha, 'cases': [],
              'limitations': ['Not a genuine two-version upgrade', 'No live GitHub discovery/download or UI confirmation test',
                              'Does not exercise launch_update() handoff', 'No signature/publisher-identity proof',
                              'No forced-hang child-tree kill, disk-full, permission-denied, power-failure or Windows 10/11 coverage',
                              'No real game, Vanguard, real-game capture or accuracy claim',
                              'Child-only rejecting proxy is not an OS-wide network audit']}
    started = time.monotonic()
    native = None
    try:
        if original.stat().st_size != args.expected_size or sha256(original) != args.expected_sha256:
            raise AssertionError('Input EXE does not match the pinned original bytes')
        report.update(executable_sha256=args.expected_sha256, executable_bytes=args.expected_size)
        # Nine minutes for work, with a separate bounded cleanup reserve below.
        budget = Deadline(540)
        with smoke_workspace() as work, rejecting_proxy() as (proxy, counts):
            # Windows TEMP may use an 8.3 alias; updater plans canonicalize paths.
            work = work.resolve()
            if shutil.disk_usage(work).free < 6 * 1024**3:
                raise AssertionError('At least 6 GiB free temporary disk space is required')
            native = NativeJob()
            try:
                env = child_environment(os.environ, work, proxy)
                version_path = work / 'version.json'
                version_process = native.spawn(original, ['--version-file', version_path], env, work)
                if native.wait_exit(version_process, budget.until(60)) != 0:
                    raise AssertionError('Original frozen EXE version probe failed')
                version_info = read_json(version_path)
                if version_info.get('frozen') is not True or not isinstance(version_info.get('applicationVersion'), str):
                    raise AssertionError('Input is not the expected frozen application')
                version = version_info['applicationVersion']
                different_version(version)  # Validate bounded numeric version syntax.
                report['applicationVersion'] = version
                control_title = control_title_for_version(version)
                report['expected_control_title'] = control_title
                for kind in ('success-concurrency', 'version-mismatch-rollback'):
                    case = run_case(kind, original, work, reports, native, budget, proxy, version, args.expected_sha256, control_title)
                    report['cases'].append(case)
                    # Cases are sequential; never retain both large fixture trees.
                    from windows_exe_smoke import remove_smoke_directory
                    remove_smoke_directory(work / kind, timeout=10)
                report['proxy_rejections'] = counts['rejected_requests']
                if not counts['rejected_requests']:
                    raise AssertionError('Candidate startup did not exercise the rejecting local proxy')
                report['all_owned_processes_exited'] = not native.pids()
            finally:
                native.cleanup()
                native = None
        if sum(path.stat().st_size for path in reports.glob('windows-ota-*') if path.is_file()) > MAX_EVIDENCE:
            raise AssertionError('OTA evidence exceeds the 2 MiB budget')
        report['status'] = 'passed'
    except BaseException as exc:
        report['error'] = str(exc)[:2000]
        raise
    finally:
        report['elapsed_seconds'] = round(time.monotonic() - started, 3)
        write_json(reports / 'windows-ota-smoke.json', report)
        print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()

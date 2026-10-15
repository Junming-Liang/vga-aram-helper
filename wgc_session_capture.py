"""DEFAULT-OFF persistent HWND WGC investigation, never a production fallback.

Only explicit WgcSessionCapture(experimental=True) opts into this separate
helper. capture() is a blocking WORKER API, never a Qt GUI-thread API. close()
and stop() revoke immediately and delegate all pipe/reap work to owned daemon
workers. Native guards are scheduled at 25 ms; that is not a measured teardown
latency guarantee. Parent deadlines operate independently of pipe/driver waits.

One immutable target/process/client geometry and one immutable owned-overlay
registration per instance. Strict-hidden CPU capture is the default. The explicit
allow_visible_overlay investigation permits only the exact registered excluded
opaque HWND, with fresh native guards around GPU/CPU copies and output. It is
not enabled by the production UI and is not Windows pixel-parity evidence.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes as W
from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import queue
import secrets
import struct
import subprocess
import threading
import time

from session_windows import process_metadata
from wgc_capture import (_CaptureJob, _integer, helper_directory, validate_request,
                         WgcError, WgcUnavailable, sanitize_native_diagnostic,
                         DIAGNOSTIC_PHASES, DIAGNOSTIC_CHECKS, MAX_DIAGNOSTIC_BYTES)

HELPER_NAME = 'vga-wgc-session-capture.exe'
MANIFEST_NAME = 'wgc-session-capture-build.json'
PROFILE = 'hwnd-wgc-session-v2'
PROTOCOL = 2
REQUEST_MAGIC = b'VGASREQ2'
RESPONSE_MAGIC = b'VGASRSP2'
IDLE_MAGIC = b'VGASIDL2'
REQUEST = struct.Struct('<8sIIQQiiiiII')
RESPONSE = struct.Struct('<8sIIQQIIIIqq')
IDLE = struct.Struct('<8sQQq')
assert (REQUEST.size, RESPONSE.size, IDLE.size) == (56, 64, 32)
FRAME_WAIT_MS = 800
PROCESS_TIMEOUT = 2.0
IDLE_LEASE = 4.0
WATCHDOG_INTERVAL = .025
REQUIRED_OVERLAY_STYLE = 0x00080000 | 0x08000000 | 0x80 | 0x8 | 0x20
SESSION_PHASES = DIAGNOSTIC_PHASES | {'validate-idle', 'validate-after-copy'}
SESSION_CHECKS = DIAGNOSTIC_CHECKS | {
    'parent-lifetime', 'overlay-support', 'overlay-owner', 'overlay-generation',
    'overlay-style', 'overlay-opacity', 'overlay-affinity', 'overlay-hidden', 'qpc-clock', 'pipe-write', 'pipe-read',
    'request-protocol', 'request-roi', 'idle-lease', 'frame-timestamp', 'capture-module-pin'}
SESSION_CLOCK_KEYS = frozenset(('qpc_counter', 'qpc_frequency', 'cutoff_100ns',
                              'frame_100ns', 'observed_now_100ns', 'previous_frame_100ns'))
SESSION_SHUTDOWN_STAGES = ('frame-arrived-revoke', 'item-closed-revoke', 'session-close',
                           'pool-close', 'local-release', 'apartment-uninit', 'process-return')
_SHUTDOWN_TOKENS = tuple(f'S{index}\n'.encode('ascii')
                         for index in range(1, len(SESSION_SHUTDOWN_STAGES) + 1))


def _invalid_reply():
    return WgcError('invalid-reply', '实验截图协议校验失败，已关闭本次会话。')


def encode_request(request_id, generation, pixel_roi, wait_ms=FRAME_WAIT_MS, *, stop=False):
    """The fixed request layout never carries window identity or retargeting."""
    if (not _integer(request_id, 1, 2**63 - 1)
            or not _integer(generation, 1, 2**63 - 1)
            or not _integer(wait_ms, 50, 1200)):
        raise ValueError('Invalid session request identity/deadline')
    try:
        left, top, width, height = pixel_roi
    except (TypeError, ValueError) as error:
        raise ValueError('Invalid session ROI') from error
    if not all(_integer(v, 0, 2**31 - 1) for v in (left, top, width, height)):
        raise ValueError('Invalid session ROI')
    if stop:
        if (left, top, width, height) != (0, 0, 0, 0):
            raise ValueError('Stop cannot authorize pixels')
    elif width < 16 or height < 16 or width * height > 16_000_000:
        raise ValueError('Invalid session ROI')
    return REQUEST.pack(REQUEST_MAGIC, 2 if stop else 1, REQUEST.size,
                        request_id, generation, left, top, width, height, wait_ms, 0)


def _validate_header(data, pixel_roi, request_id, generation):
    if len(data) != RESPONSE.size:
        raise _invalid_reply()
    values = RESPONSE.unpack(data)
    magic, status, phase, actual_id, actual_generation, width, height, size, reserved, cutoff, frame = values
    if ((magic, status, phase, actual_id, actual_generation, width, height, size, reserved)
            != (RESPONSE_MAGIC, 0, 1, request_id, generation, pixel_roi[2], pixel_roi[3],
                pixel_roi[2] * pixel_roi[3] * 4, 0)
            or not 0 < cutoff < frame):
        raise _invalid_reply()
    return size, cutoff, frame


def decode_response(data, pixel_roi, request_id, generation, *, previous_frame=0,
                    earliest_cutoff=None, latest_timestamp=None):
    """Never construct an image until exact pixels AND guarded-idle trailer match."""
    if len(data) < RESPONSE.size:
        raise _invalid_reply()
    size, cutoff, frame = _validate_header(data[:RESPONSE.size], pixel_roi, request_id, generation)
    if len(data) != RESPONSE.size + size + IDLE.size or frame <= previous_frame:
        raise _invalid_reply()
    magic, actual_id, actual_generation, entered = IDLE.unpack_from(data, RESPONSE.size + size)
    if (magic, actual_id, actual_generation) != (IDLE_MAGIC, request_id, generation) or entered < frame:
        raise _invalid_reply()
    if ((earliest_cutoff is not None and cutoff < earliest_cutoff)
            or (latest_timestamp is not None and entered > latest_timestamp)):
        raise _invalid_reply()
    from PIL import Image
    image = Image.frombytes('RGB', tuple(pixel_roi[2:]), bytes(data[RESPONSE.size:RESPONSE.size + size]), 'raw', 'BGRX')
    return image, {'request_cutoff_100ns': cutoff, 'frame_100ns': frame, 'idle_enter_100ns': entered,
                   'request_id': request_id, 'session_generation': generation}


def _decode_session_failure(data, returncode):
    if (type(data) not in (bytes, bytearray) or not 0 < len(data) <= MAX_DIAGNOSTIC_BYTES
            or type(returncode) is not int or not 10 <= returncode <= 14):
        return None
    try:
        def unique(pairs):
            value = {}
            for key, item in pairs:
                if key in value:
                    raise ValueError('Duplicate field')
                value[key] = item
            return value
        value = json.loads(data.decode('ascii'), object_pairs_hook=unique)
        if (type(value) is not dict or type(value.get('phase')) is not str
                or value['phase'] not in SESSION_PHASES or type(value.get('check')) is not str
                or value['check'] not in SESSION_CHECKS or value.get('code') != returncode):
            return None
        # Session-only optional failure evidence, never an input to capture gates.
        # Nonpositive frames short-circuit QPC, so their raw/now fields are zero.
        clock = None
        if 'clock' in value:
            clock = value.pop('clock')
            if (value['code'] != 12 or value['check'] != 'frame-timestamp'
                    or value['phase'] not in ('frame-wait', 'validate-idle')
                    or type(clock) is not dict or set(clock) != SESSION_CLOCK_KEYS
                    or any(type(number) is not int or not -(2**63) <= number <= 2**63 - 1
                           for number in clock.values())):
                return None
        # Strip only the validated session extension before reusing v1's strict
        # numeric/field allowlist; production v1 still rejects the extra field.
        clean = sanitize_native_diagnostic(dict(value, phase='startup', check='invariant'))
        if clean is not None:
            clean.update(phase=value['phase'], check=value['check'])
            if clock is not None:
                clean['clock'] = dict(clock)
        return clean
    except (ValueError, UnicodeError, TypeError, RecursionError):
        return None


def _decode_session_stderr(data, returncode):
    """Validate the complete bounded transcript before exposing either record."""
    if (type(data) not in (bytes, bytearray) or not 0 < len(data) <= MAX_DIAGNOSTIC_BYTES
            or type(returncode) is not int or not -(2**31) <= returncode <= 2**32 - 1
            or returncode == 0):
        return None
    data = bytes(data)
    count = offset = 0
    for token in _SHUTDOWN_TOKENS:
        if not data.startswith(token, offset):
            break
        count += 1
        offset += len(token)
    tail = data[offset:]
    failure = _decode_session_failure(tail, returncode) if tail else None
    # A truncated/unknown/repeated token or arbitrary tail invalidates everything,
    # including a valid earlier prefix. Optional JSON remains the exact old schema.
    if ((tail and failure is None) or (not count and failure is None)
            or (count and failure is not None and failure['phase'] != 'shutdown')):
        return None
    return count, failure


def decode_session_diagnostic(data, returncode):
    parsed = _decode_session_stderr(data, returncode)
    return parsed[1] if parsed is not None else None


def sanitize_session_shutdown_diagnostic(value, returncode):
    """The same strict allowlist is used by capture, reports and summaries."""
    keys = {'schema_version', 'exit_code', 'checkpoints', 'last_started_stage'}
    if (type(returncode) is not int or not -(2**31) <= returncode <= 2**32 - 1
            or returncode == 0 or type(value) is not dict or set(value) != keys
            or type(value['schema_version']) is not int or value['schema_version'] != 1
            or type(value['exit_code']) is not int or value['exit_code'] != returncode
            or type(value['checkpoints']) is not list
            or not 1 <= len(value['checkpoints']) <= len(SESSION_SHUTDOWN_STAGES)
            or any(type(index) is not int or index != expected
                   for expected, index in enumerate(value['checkpoints'], 1))
            or type(value['last_started_stage']) is not str
            or value['last_started_stage'] != SESSION_SHUTDOWN_STAGES[len(value['checkpoints']) - 1]):
        return None
    return dict(schema_version=1, exit_code=returncode, checkpoints=list(value['checkpoints']),
                last_started_stage=value['last_started_stage'])


def decode_session_shutdown_diagnostic(data, returncode):
    """Failure-only checkpoint evidence; never used for capture or exit decisions.

    Call after process exit and complete stderr collection. A checkpoint is
    written immediately before its operation, not evidence that it caused an
    exception or that the remaining teardown completed. Exit zero exposes none.
    """
    parsed = _decode_session_stderr(data, returncode)
    if parsed is None or not parsed[0]:
        return None
    count = parsed[0]
    return sanitize_session_shutdown_diagnostic(
        dict(schema_version=1, exit_code=returncode, checkpoints=list(range(1, count + 1)),
             last_started_stage=SESSION_SHUTDOWN_STAGES[count - 1]), returncode)


def completed_native_shutdown(data, returncode):
    """Exact completed-checkpoint evidence after exit and full stderr collection.

    This is separate from the failure-only decoder and changes no capture gate
    or process lifecycle. Callers must independently reject parent termination;
    a zero process exit alone does not prove voluntary native shutdown.
    """
    return (type(returncode) is int and returncode == 0
            and type(data) in (bytes, bytearray) and data == b''.join(_SHUTDOWN_TOKENS))


def _property_name(generation):
    return 'VGA.WGC.SessionV2.Overlay.' + str(generation)


def _window_api():
    user = ctypes.WinDLL('user32', use_last_error=True)
    for name, args, result in (
        ('IsWindow', [W.HWND], W.BOOL),
        ('GetWindowThreadProcessId', [W.HWND, ctypes.POINTER(W.DWORD)], W.DWORD),
        ('GetAncestor', [W.HWND, W.UINT], W.HWND),
        ('GetWindowLongPtrW', [W.HWND, ctypes.c_int], ctypes.c_ssize_t),
        ('GetWindowDisplayAffinity', [W.HWND, ctypes.POINTER(W.DWORD)], W.BOOL),
        ('SetPropW', [W.HWND, W.LPCWSTR, W.HANDLE], W.BOOL),
        ('GetPropW', [W.HWND, W.LPCWSTR], W.HANDLE),
        ('RemovePropW', [W.HWND, W.LPCWSTR], W.HANDLE),
    ):
        function = getattr(user, name); function.argtypes = args; function.restype = result
    return user


def _register_owned_overlay(hwnd, style, generation, parent_pid):
    """Only our own HWND is modified; its ephemeral property dies with the HWND."""
    user = _window_api()
    pid, affinity = W.DWORD(), W.DWORD()
    if (not user.IsWindow(hwnd) or user.GetAncestor(hwnd, 2) != hwnd
            or not user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid)) or pid.value != parent_pid
            or (int(user.GetWindowLongPtrW(hwnd, -20)) & 0xffffffff) != style
            or not user.GetWindowDisplayAffinity(hwnd, ctypes.byref(affinity)) or affinity.value != 0x11):
        raise WgcError('stale', '实验叠加窗口身份、样式或截图排除状态无效。')
    name = _property_name(generation)
    # Never overwrite a previous registration, even an equal token.
    if user.GetPropW(hwnd, name) or not user.SetPropW(hwnd, name, generation):
        raise WgcError('stale', '无法绑定实验叠加窗口的本次生命周期。')
    if user.GetPropW(hwnd, name) != generation:
        _remove_owned_overlay(hwnd, generation, parent_pid)
        raise WgcError('stale', '系统未确认实验叠加窗口的生命周期标记。')


def _remove_owned_overlay(hwnd, generation, parent_pid):
    try:
        user = _window_api(); pid = W.DWORD(); name = _property_name(generation)
        if (user.IsWindow(hwnd) and user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                and pid.value == parent_pid and user.GetPropW(hwnd, name) == generation):
            user.RemovePropW(hwnd, name)
    except (OSError, AttributeError):
        pass  # Destroyed HWND loses its properties automatically.


def _wipe(data):
    if isinstance(data, bytearray):
        # Bounded chunks avoid a second full-size retained pixel allocation.
        for start in range(0, len(data), 65536):
            size = min(65536, len(data) - start)
            data[start:start + size] = b'\0' * size
        data.clear()


def _read_exact(stream, length):
    data = bytearray()
    try:
        while len(data) < length:
            part = stream.read(min(65536, length - len(data)))
            if not part:
                raise _invalid_reply()
            data.extend(part)
        return data
    except BaseException:
        _wipe(data)
        raise


def _qpc_100ns():
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.QueryPerformanceCounter.argtypes = [ctypes.POINTER(ctypes.c_int64)]
    kernel.QueryPerformanceCounter.restype = W.BOOL
    kernel.QueryPerformanceFrequency.argtypes = [ctypes.POINTER(ctypes.c_int64)]
    kernel.QueryPerformanceFrequency.restype = W.BOOL
    ticks, frequency = ctypes.c_int64(), ctypes.c_int64()
    if (not kernel.QueryPerformanceCounter(ctypes.byref(ticks))
            or not kernel.QueryPerformanceFrequency(ctypes.byref(frequency))
            or ticks.value <= 0 or frequency.value <= 0):
        raise WgcError('backend-error', '无法核验实验截图时间戳。')
    return ticks.value * 10_000_000 // frequency.value


def _pipe_available(stream):
    import msvcrt
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.PeekNamedPipe.argtypes = [W.HANDLE, ctypes.c_void_p, W.DWORD,
                                    ctypes.c_void_p, ctypes.POINTER(W.DWORD), ctypes.c_void_p]
    kernel.PeekNamedPipe.restype = W.BOOL
    count = W.DWORD()
    if not kernel.PeekNamedPipe(msvcrt.get_osfhandle(stream.fileno()), None, 0, None, ctypes.byref(count), None):
        raise _invalid_reply()
    return count.value


@dataclass
class _Exchange:
    request: bytes
    roi: tuple
    request_id: int
    done: threading.Event = field(default_factory=threading.Event)
    data: bytearray | None = None
    error: BaseException | None = None


class _Transport:
    """All potentially blocking launch/pipe/cleanup operations stay off callers.

    A dedicated watchdog owns termination independently of the pipe worker.
    Even an idle native guard/Close hang has a parent 4 s lease. Refuse replacement
    until process exit, BOTH pipe workers and successful Job closure are confirmed.
    """
    def __init__(self, args, generation):
        self.args, self.generation = args, generation
        self.process = self.job = None
        self.revoked = threading.Event()
        self.ready_for_replacement = threading.Event()
        self.io_done = threading.Event()
        self.stderr_done = threading.Event()
        self.lock = threading.Lock()
        self.requests = queue.Queue(maxsize=1)
        self.request_deadline = time.monotonic() + PROCESS_TIMEOUT
        self.idle_deadline = time.monotonic() + IDLE_LEASE
        self.failure = None
        self.diagnostic = bytearray()
        # Sticky evidence only; never changes revoke, kill, reap or replacement.
        # None means the pre-termination poll failed, so graceful proof must
        # require exactly False. An observed-alive attempt always sets True.
        self.termination_requested_while_alive = False
        self.job_closed = False
        self.stderr_started = False
        self._active = None
        self.worker = threading.Thread(target=self._run, name='wgc-session-pipe', daemon=True)
        self.watchdog = threading.Thread(target=self._watch, name='wgc-session-lifetime', daemon=True)
        self.watchdog_ready = threading.Event()
        try:
            # The independent watchdog must actually be running before any
            # worker is allowed to create a process or release its start gate.
            self.watchdog.start()
            if not self.watchdog_ready.wait(.1):
                raise RuntimeError('Lifetime watchdog did not start')
            self.worker.start()
        except BaseException:
            self.revoke(WgcError('backend-error', '无法启动实验截图生命周期监控。'))
            if self.worker.ident is None:
                self.io_done.set(); self.stderr_done.set()
            raise WgcError('backend-error', '无法启动实验截图生命周期监控。') from None

    def submit(self, exchange):
        with self.lock:
            if self.revoked.is_set():
                raise self.failure or WgcError('stale', '实验截图会话已失效。')
            if self._active is not None:
                raise WgcError('busy', 'Only one session request may be outstanding')
            self.request_deadline = time.monotonic() + PROCESS_TIMEOUT
            self.idle_deadline = time.monotonic() + IDLE_LEASE
            self._active = exchange
            self.requests.put_nowait(exchange)

    def finish(self, exchange):
        with self.lock:
            if self.revoked.is_set() or self._active is not exchange:
                raise self.failure or WgcError('stale', '实验截图会话已失效。')
            if time.monotonic() >= self.request_deadline:
                raise WgcError('timeout', '实验截图超过独立的两秒时限。')
            self._active = None
            self.request_deadline = None

    def revoke(self, error=None):
        # No pipe close, wait, communicate, join or Job lock on this caller.
        if error is not None and self.failure is None:
            self.failure = error
        self.revoked.set()

    def _read_stderr(self):
        try:
            while True:
                part = self.process.stderr.read(256)
                if not part:
                    break
                remaining = MAX_DIAGNOSTIC_BYTES + 1 - len(self.diagnostic)
                if remaining > 0:
                    self.diagnostic.extend(part[:remaining])
                if len(self.diagnostic) > MAX_DIAGNOSTIC_BYTES:
                    self.revoke(_invalid_reply())
                    break
        except (OSError, ValueError):
            pass
        finally:
            self.stderr_done.set()

    def _native_error(self, fallback):
        process = self.process
        code = process.poll() if process is not None else None
        if code in (10, 11, 12, 13, 14):
            status = {10: 'unsupported', 11: 'timeout', 12: 'stale', 13: 'protected', 14: 'backend-error'}[code]
            error = (WgcUnavailable if code == 10 else WgcError)(status, '实验图形会话已停止，未返回本帧。')
            error.diagnostic = decode_session_diagnostic(self.diagnostic, code)
            return error
        return fallback if isinstance(fallback, WgcError) else WgcError('backend-error', '实验图形会话未正常完成。')

    def _run(self):
        exchange = None
        try:
            self.job = _CaptureJob()
            if self.revoked.is_set():
                return
            self.process = subprocess.Popen(self.args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, shell=False, bufsize=0,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            if self.revoked.is_set():
                return
            self.job.assign(self.process)
            if self.revoked.is_set():
                return
            stderr_thread = threading.Thread(target=self._read_stderr, name='wgc-session-stderr', daemon=True)
            stderr_thread.start()
            self.stderr_started = True
            # Nothing can capture until the exact child is inside its owned Job.
            self.process.stdin.write(b'C')
            while not self.revoked.is_set():
                try:
                    exchange = self.requests.get(timeout=WATCHDOG_INTERVAL)
                except queue.Empty:
                    if self.process.poll() is not None:
                        raise self._native_error(WgcError('stale', '实验图形会话已结束。'))
                    continue
                if self.revoked.is_set():
                    break
                view = memoryview(exchange.request)
                while view:
                    count = self.process.stdin.write(view)
                    if not count:
                        raise _invalid_reply()
                    view = view[count:]
                data = _read_exact(self.process.stdout, RESPONSE.size)
                try:
                    size, _, _ = _validate_header(data, exchange.roi, exchange.request_id, self.generation)
                    for length in (size, IDLE.size):
                        part = _read_exact(self.process.stdout, length)
                        data.extend(part); _wipe(part)
                    if _pipe_available(self.process.stdout):
                        raise _invalid_reply()
                    with self.lock:
                        if self.revoked.is_set():
                            raise self.failure or WgcError('cancelled', '实验截图已取消。')
                        exchange.data = data
                        data = None
                    exchange.done.set()
                finally:
                    _wipe(data)
                exchange = None
        except BaseException as error:
            if self.process is not None:
                try:
                    self.process.wait(timeout=.05)
                except subprocess.TimeoutExpired:
                    pass
                self.stderr_done.wait(.05)
            error = self.failure or self._native_error(error)
            self.revoke(error)
            if exchange is not None:
                exchange.error = error; exchange.done.set()
        finally:
            if not self.stderr_started:
                self.stderr_done.set()
            self.io_done.set()
            # Exit/error always retires this exact helper. A launch that finishes
            # after revocation is still killed before the start gate is released.
            self.revoke()

    def _terminate(self):
        # Only this watchdog touches close/kill/reap. Never any external PID.
        job, process = self.job, self.process
        if job is not None and not self.job_closed:
            if process is not None:
                try:
                    if process.poll() is None:
                        self.termination_requested_while_alive = True
                except OSError:
                    if self.termination_requested_while_alive is not True:
                        self.termination_requested_while_alive = None
            # Diagnostic sampling cannot prevent the existing close attempt.
            try:
                self.job_closed = bool(job.close())
            except OSError:
                pass
        if process is not None and process.poll() is None:
            try:
                self.termination_requested_while_alive = True
                process.kill()
            except OSError:
                pass

    def _watch(self):
        self.watchdog_ready.set()
        while not self.revoked.wait(WATCHDOG_INTERVAL):
            with self.lock:
                deadline = self.request_deadline if self.request_deadline is not None else self.idle_deadline
            if time.monotonic() >= deadline:
                self.revoke(WgcError('timeout', '实验图形会话的请求时限或空闲租期已到。'))
            elif self.process is not None and self.process.poll() is not None:
                self.revoke(self._native_error(WgcError('stale', '实验图形会话已结束。')))
        while True:
            self._terminate()
            process = self.process
            if (self.io_done.is_set() and self.stderr_done.is_set()
                    and (process is None or process.poll() is not None)
                    and (self.job is None or self.job_closed)):
                if process is not None:
                    for stream in (process.stdin, process.stdout, process.stderr):
                        if stream:
                            try:
                                stream.close()
                            except OSError:
                                pass
                with self.lock:
                    if self._active is not None:
                        _wipe(self._active.data); self._active.data = None
                        self._active.error = self.failure or WgcError('cancelled', '实验截图已取消。')
                        self._active.done.set()
                self.ready_for_replacement.set()
                return
            # Driver/OS termination can be delayed. Retain this sole ownership
            # record and keep replacement blocked; no unbounded caller wait.
            time.sleep(.1)


class WgcSessionCapture:
    def __init__(self, *, experimental=False, allow_visible_overlay=False):
        if experimental is not True:
            raise WgcError('experiment-disabled', '持续窗口捕获实验默认关闭。')
        if type(allow_visible_overlay) is not bool:
            raise TypeError('Visible overlay capability requires a boolean')
        self._allow_visible_overlay = allow_visible_overlay
        self._overlay_window_style = None
        directory = helper_directory()
        self.helper_path = directory / HELPER_NAME
        self.manifest_path = directory / MANIFEST_NAME
        self._state = threading.Lock()
        self._capture_lock = threading.Lock()
        self._closed = False
        self._binding = self._overlay = self._parent = self._transport = None
        self._overlay_generation = None
        self._request_id = self._last_frame = 0
        self.last_timing = None
        self._verify_helper()

    def _verify_helper(self):
        path, manifest = self.helper_path, self.manifest_path
        if not path.exists() and not manifest.exists():
            raise WgcUnavailable('missing-helper', '尚未构建默认关闭的持续捕获实验组件。')
        try:
            if (path.is_symlink() or manifest.is_symlink() or not path.is_file() or not manifest.is_file()
                    or manifest.stat().st_size > 64 * 1024):
                raise ValueError('Invalid session helper files')
            proof = json.loads(manifest.read_text(encoding='utf-8'))
            size = path.stat().st_size
            if (not 0 < size <= 4 * 1024 * 1024 or type(proof) is not dict
                    or type(proof.get('schema_version')) is not int or type(proof.get('protocol')) is not int
                    or type(proof.get('size')) is not int
                    or (proof.get('schema_version'), proof.get('protocol'), proof.get('profile'),
                        proof.get('filename'), proof.get('size'), proof.get('status'))
                    != (1, PROTOCOL, PROFILE, HELPER_NAME, size, 'passed')):
                raise ValueError('Invalid session helper identity')
            for key in ('sha256', 'source_sha256', 'build_recipe_sha256'):
                value = proof.get(key)
                if not isinstance(value, str) or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
                    raise ValueError('Invalid session provenance')
            if hashlib.sha256(path.read_bytes()).hexdigest() != proof['sha256']:
                raise ValueError('Session helper changed')
        except (OSError, ValueError, TypeError, AttributeError) as error:
            raise WgcError('untrusted-helper', '持续捕获实验组件校验失败。') from error

    def register_idle_overlay(self, hwnd, expected_extended_style, generation):
        if (not _integer(hwnd, 1, 2**63 - 1) or not _integer(generation, 1, 2**63 - 1)
                or not _integer(expected_extended_style, 0, 2**32 - 1)
                or expected_extended_style & REQUIRED_OVERLAY_STYLE != REQUIRED_OVERLAY_STYLE):
            raise WgcError('stale', '实验叠加窗口注册参数无效。')
        if os.name != 'nt':
            raise WgcUnavailable('unsupported', '持续窗口捕获实验仅支持 Windows。')
        parent_pid = os.getpid()
        parent = process_metadata(parent_pid)
        if not _integer(parent.created, 1, 2**63 - 1):
            raise WgcError('stale', '无法确认本进程生命周期。')
        with self._state:
            if self._closed or self._binding is not None or self._overlay is not None:
                raise WgcError('stale', '会话生命周期内不可更换叠加窗口注册。')
            # The caller's UI generation can restart at 1 in another instance.
            # Bind a fresh unpredictable registration token to the actual HWND;
            # destruction/reuse plus a repeated UI generation cannot revive it.
            token = secrets.randbits(63) or 1
            _register_owned_overlay(hwnd, expected_extended_style, token, parent_pid)
            try:
                if self._allow_visible_overlay:
                    # Capture the complete standard style as well as EXSTYLE;
                    # visibility/style changes retire this immutable enrollment.
                    user = _window_api()
                    ctypes.set_last_error(0)
                    self._overlay_window_style = int(user.GetWindowLongPtrW(hwnd, -16)) & 0xffffffff
                    if ctypes.get_last_error():
                        raise WgcError('stale', '无法核验叠加窗口的完整样式。')
            except BaseException:
                _remove_owned_overlay(hwnd, token, parent_pid)
                raise
            self._parent = (parent_pid, parent.created)
            self._overlay_generation = generation
            self._overlay = (hwnd, expected_extended_style, token)

    def capture(self, target, rect, pixel_roi, *, cancelled=None, expected_metadata=None):
        try:
            validate_request(target, rect, pixel_roi)
            cancelled = cancelled or (lambda: False)
            if not callable(cancelled):
                cancelled = cancelled.is_set
            if cancelled():
                raise WgcError('cancelled', '实验截图已取消。')
        except BaseException as error:
            # Invalid/pre-cancelled requests revoke an already-idle helper too.
            # Never leave its previous authorization alive until lease expiry.
            with self._state:
                if self._transport is not None:
                    self._transport.revoke(error if isinstance(error, WgcError) else None)
            raise
        if not self._capture_lock.acquire(blocking=False):
            raise WgcError('busy', '本实验只允许一个未完成的截图请求。')
        transport = None; exchange = None; data = None
        try:
            if os.name != 'nt':
                raise WgcUnavailable('unsupported', '持续窗口捕获实验仅支持 Windows。')
            metadata = process_metadata(target.pid)
            if (not _integer(metadata.created, 1, 2**63 - 1)
                    or expected_metadata is not None and metadata != expected_metadata):
                raise WgcError('stale', '原授权窗口进程已经变化。')
            binding = (target.hwnd, target.pid, metadata.created, rect.x, rect.y, rect.width, rect.height)
            parent_pid = os.getpid()
            parent = process_metadata(parent_pid)
            if not _integer(parent.created, 1, 2**63 - 1):
                raise WgcError('stale', '无法确认本进程生命周期。')
            with self._state:
                if self._closed:
                    raise WgcError('cancelled', '实验截图会话已关闭。')
                if self._binding is not None and binding != self._binding:
                    raise WgcError('stale', '持续捕获会话不可重定向或改变原窗口几何。')
                if self._parent is not None and self._parent != (parent_pid, parent.created):
                    raise WgcError('stale', '本进程生命周期已变化。')
                if self._allow_visible_overlay and (self._overlay is None
                        or not _integer(self._overlay_window_style, 0, 2**32 - 1)):
                    raise WgcError('stale', '可见叠加捕获必须先注册本次窗口生命周期。')
                self._binding, self._parent = binding, (parent_pid, parent.created)
                transport = self._transport
                if transport is not None and transport.revoked.is_set():
                    if not transport.ready_for_replacement.is_set():
                        raise WgcError('cleanup-pending', '上一次实验会话尚未确认关闭，暂不创建新会话。')
                    self._transport = transport = None
                if transport is None:
                    self._verify_helper()
                    generation = secrets.randbelow(2**63 - 1) + 1
                    mode = ('--session-v2-visible-owned-overlay' if self._allow_visible_overlay
                            else '--session-v2')
                    args = [str(self.helper_path), mode, *binding,
                            *self._parent, *(self._overlay or (0, 0, 0)), generation]
                    if self._allow_visible_overlay:
                        args.append(self._overlay_window_style)
                    transport = self._transport = _Transport([str(v) for v in args], generation)
                    self._last_frame = 0
                self._request_id += 1
                request_id = self._request_id
                exchange = _Exchange(encode_request(request_id, transport.generation, pixel_roi), tuple(pixel_roi), request_id)
                request_started = _qpc_100ns()
                transport.submit(exchange)
            while not exchange.done.wait(WATCHDOG_INTERVAL):
                if cancelled() or self._closed:
                    raise WgcError('cancelled', '实验截图已取消。')
                if transport.revoked.is_set():
                    raise transport.failure or WgcError('stale', '实验截图会话已失效。')
                if time.monotonic() >= transport.request_deadline:
                    raise WgcError('timeout', '实验截图超过独立的两秒时限。')
            if exchange.error is not None:
                raise exchange.error
            # Detach transport ownership before decoding; close can revoke it,
            # but the cleanup worker never races a wipe against this local buffer.
            with transport.lock:
                data, exchange.data = exchange.data, None
            if data is None:
                raise _invalid_reply()
            image, timing = decode_response(data, pixel_roi, request_id, transport.generation,
                                            previous_frame=self._last_frame,
                                            earliest_cutoff=request_started, latest_timestamp=_qpc_100ns())
            if process_metadata(target.pid) != metadata:
                raise WgcError('stale', '截图期间目标进程身份发生变化。')
            with self._state:
                if self._closed or cancelled() or self._transport is not transport:
                    raise WgcError('cancelled', '实验截图已取消。')
                transport.finish(exchange)
                self._last_frame = timing['frame_100ns']; self.last_timing = timing
                return image
        except (OSError, ValueError) as error:
            transport = transport or self._transport
            if transport is not None:
                transport.revoke(WgcError('backend-error', '无法验证或启动实验图形会话。'))
            raise WgcError('backend-error', '无法验证或启动实验图形会话。') from error
        except BaseException as error:
            transport = transport or self._transport
            if transport is not None:
                transport.revoke(error if isinstance(error, WgcError) else None)
            raise
        finally:
            _wipe(data)
            self._capture_lock.release()

    def close(self):
        with self._state:
            self._closed = True
            self.last_timing = None
            transport, overlay, parent = self._transport, self._overlay, self._parent
            if transport is not None:
                transport.revoke(WgcError('cancelled', '实验截图会话已关闭。'))
        if overlay is not None and parent is not None:
            _remove_owned_overlay(overlay[0], overlay[2], parent[0])

    stop = close

    @property
    def cleanup_pending(self):
        transport = self._transport
        return bool(transport is not None and transport.revoked.is_set()
                    and not transport.ready_for_replacement.is_set())

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

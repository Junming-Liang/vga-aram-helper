"""Bounded one-shot HWND WGC capture; no screen/monitor/title fallback.

The project-owned native helper gets only an exact verified HWND, process
creation time and physical client ROI. Windows owns a full-window GPU surface;
only the requested ROI is staged/read back and returned on an anonymous pipe.
An isolated process bounds even driver/session-shutdown hangs. Never run this
blocking worker API on Qt's GUI thread.
"""
from __future__ import annotations

import hashlib
import ctypes
from ctypes import wintypes as W
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import time

from session_windows import process_metadata

MAGIC = b'VGAWGC1\0'
HEADER = struct.Struct('<8sIIII')
PIXEL_BUDGET = 16_000_000
FRAME_WAIT_MS = 800
PROCESS_TIMEOUT = 2.0
HELPER_NAME = 'vga-wgc-capture.exe'
MANIFEST_NAME = 'wgc-capture-build.json'


class WgcError(RuntimeError):
    def __init__(self, status, message):
        self.status = status
        super().__init__(message)


class WgcUnavailable(WgcError):
    """Only a missing optional helper or unsupported OS permits the GDI path."""


class _CaptureJob:
    """Parent-owned lifetime for one Popen-owned helper, never another process.

    The anonymous handle is non-inheritable. Closing it, including on abrupt
    parent exit, tells Windows to terminate the helper. No breakaway is allowed.
    Native capture waits for stdin's start byte until assignment is complete.
    """
    def __init__(self):
        class Limits(ctypes.Structure):
            _fields_ = [('process_time', ctypes.c_int64), ('job_time', ctypes.c_int64),
                ('flags', W.DWORD), ('min_working_set', ctypes.c_size_t),
                ('max_working_set', ctypes.c_size_t), ('active_processes', W.DWORD),
                ('affinity', ctypes.c_size_t), ('priority', W.DWORD), ('scheduling', W.DWORD)]
        class IoCounters(ctypes.Structure):
            _fields_ = [(name, ctypes.c_uint64) for name in
                ('read_ops', 'write_ops', 'other_ops', 'read_bytes', 'write_bytes', 'other_bytes')]
        class ExtendedLimits(ctypes.Structure):
            _fields_ = [('basic', Limits), ('io', IoCounters),
                ('process_memory', ctypes.c_size_t), ('job_memory', ctypes.c_size_t),
                ('peak_process_memory', ctypes.c_size_t), ('peak_job_memory', ctypes.c_size_t)]
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        signatures = [('CreateJobObjectW', [ctypes.c_void_p, W.LPCWSTR], W.HANDLE),
            ('SetInformationJobObject', [W.HANDLE, ctypes.c_int, ctypes.c_void_p, W.DWORD], W.BOOL),
            ('AssignProcessToJobObject', [W.HANDLE, W.HANDLE], W.BOOL),
            ('CloseHandle', [W.HANDLE], W.BOOL)]
        for name, args, result in signatures:
            function = getattr(self.kernel, name); function.argtypes = args; function.restype = result
        self.handle = self.kernel.CreateJobObjectW(None, None)
        if not self.handle:
            raise OSError('Cannot establish owned capture lifetime')
        limits = ExtendedLimits()
        limits.basic.flags = 0x2000 | 0x8  # KILL_ON_JOB_CLOSE | ACTIVE_PROCESS
        limits.basic.active_processes = 1
        if not self.kernel.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            self.close()
            raise OSError('Cannot bound owned capture lifetime')

    def assign(self, process):
        if not self.kernel.AssignProcessToJobObject(self.handle, int(process._handle)):
            raise OSError('Cannot assign owned capture helper to its lifetime job')

    def close(self):
        if self.handle:
            if not self.kernel.CloseHandle(self.handle):
                return False
            self.handle = None
        return True


def helper_directory():
    if getattr(sys, 'frozen', False):
        return Path(sys._MEIPASS) / 'native'
    return Path(__file__).resolve().parent / 'build' / 'native'


def _integer(value, minimum, maximum):
    return isinstance(value, int) and not isinstance(value, bool) and minimum <= value <= maximum


def validate_request(target, rect, pixel_roi):
    try:
        left, top, width, height = pixel_roi
        values = (rect.x, rect.y, rect.width, rect.height, left, top, width, height)
        valid = (_integer(target.hwnd, 1, 2**63 - 1) and _integer(target.pid, 1, 2**32 - 1)
            and all(_integer(value, -(2**31), 2**31 - 1) for value in values)
            and rect.width >= 64 and rect.height >= 64 and rect.width * rect.height <= PIXEL_BUDGET
            and left >= 0 and top >= 0 and width >= 16 and height >= 16
            and left + width <= rect.width and top + height <= rect.height
            and rect.x + rect.width <= 2**31 - 1 and rect.y + rect.height <= 2**31 - 1)
    except (TypeError, ValueError, AttributeError):
        valid = False
    if not valid:
        raise WgcError('stale', '截图区域或窗口身份无效，已跳过本帧。')


def decode_frame(data, pixel_roi):
    """An exact-size protocol prevents headers from expanding the capture scope."""
    _, _, width, height = pixel_roi
    expected = width * height * 4
    if len(data) != HEADER.size + expected:
        raise WgcError('invalid-reply', '系统截图未返回完整的限定区域。')
    magic, protocol, actual_width, actual_height, payload_size = HEADER.unpack_from(data)
    if (magic, protocol, actual_width, actual_height, payload_size) != (MAGIC, 1, width, height, expected):
        raise WgcError('invalid-reply', '系统截图区域校验失败，已丢弃本帧。')
    from PIL import Image
    return Image.frombytes('RGB', (width, height), data[HEADER.size:], 'raw', 'BGRX')


class WgcCapture:
    def __init__(self):
        directory = helper_directory()
        self.helper_path = directory / HELPER_NAME
        self.manifest_path = directory / MANIFEST_NAME
        self._verify_helper()

    def _verify_helper(self):
        # There is intentionally no PATH lookup, environment override, downloaded
        # executable, dynamic package install or user-supplied helper path.
        path, manifest = self.helper_path, self.manifest_path
        if not path.exists() and not manifest.exists():
            raise WgcUnavailable('missing-helper', '当前源码环境未构建 Windows 图形捕获组件。')
        try:
            if path.is_symlink() or manifest.is_symlink() or not path.is_file() or not manifest.is_file():
                raise ValueError('Non-regular helper input')
            if manifest.stat().st_size > 64 * 1024:
                raise ValueError('Oversized capture manifest')
            proof = json.loads(manifest.read_text(encoding='utf-8'))
            size = path.stat().st_size
            if not 0 < size <= 4 * 1024 * 1024:
                raise ValueError('Unexpected helper size')
            if (proof.get('schema_version'), proof.get('protocol'), proof.get('filename'), proof.get('size')) != (1, 1, HELPER_NAME, size):
                raise ValueError('Capture helper protocol differs')
            for key in ('sha256', 'source_sha256', 'build_recipe_sha256'):
                value = proof.get(key)
                if not isinstance(value, str) or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
                    raise ValueError('Invalid capture provenance digest')
            if hashlib.sha256(path.read_bytes()).hexdigest() != proof['sha256']:
                raise ValueError('Capture helper content changed')
            self._digest = proof['sha256']
        except (OSError, ValueError, TypeError, AttributeError) as error:
            raise WgcError('untrusted-helper', 'Windows 图形捕获组件校验失败，请重新获取完整安装包。') from error

    def capture(self, target, rect, pixel_roi, *, cancelled=None, expected_metadata=None):
        validate_request(target, rect, pixel_roi)
        cancelled = cancelled or (lambda: False)
        if not callable(cancelled):
            cancelled = cancelled.is_set
        if cancelled():
            raise WgcError('cancelled', '截图已取消。')
        pending_job = getattr(self, '_pending_job', None)
        if pending_job is not None:
            if not pending_job.close():
                raise WgcError('cleanup-pending', '系统尚未确认上一截图任务已关闭，暂不启动新截图。')
            self._pending_job = None
        pending = getattr(self, '_pending_cleanup', None)
        if pending is not None:
            try:
                if pending.poll() is None:
                    raise subprocess.TimeoutExpired(str(self.helper_path), 0)
                pending.communicate(timeout=0)
            except subprocess.TimeoutExpired as error:
                # A driver may delay OS termination. Do not pile up helpers or
                # block on a pipe reader that still holds its stream lock.
                raise WgcError('cleanup-pending', '上一次图形捕获仍在由系统关闭，暂不启动新截图。') from error
            if pending.stdout:
                pending.stdout.close()
            self._pending_cleanup = None
        if os.name != 'nt':
            raise WgcUnavailable('unsupported', 'Windows 图形捕获仅支持 Windows。')
        self._verify_helper()
        try:
            metadata = process_metadata(target.pid)
        except (OSError, ValueError) as error:
            raise WgcError('stale', '截图窗口身份已变化，稍后重新连接。') from error
        if not _integer(metadata.created, 1, 2**63 - 1):
            raise WgcError('stale', '无法验证截图进程的创建时间。')
        if expected_metadata is not None and metadata != expected_metadata:
            raise WgcError('stale', '原授权窗口进程已经变化，本帧未进行截图。')
        args = [str(self.helper_path), '--capture-v1', target.hwnd, target.pid, metadata.created,
                rect.x, rect.y, rect.width, rect.height, *pixel_roi, FRAME_WAIT_MS]
        deadline = time.monotonic() + PROCESS_TIMEOUT
        process = None
        job = None
        communicated = False
        try:
            job = _CaptureJob()
            process = subprocess.Popen([str(value) for value in args], stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, shell=False,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            job.assign(process)
            # No WGC call can occur before the exact owned child is in the Job.
            # If we disappear before this write, EOF makes native startup exit.
            process.stdin.write(b'C')
            process.stdin.close()
            process.stdin = None
            while True:
                if cancelled():
                    raise WgcError('cancelled', '截图已取消。')
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise WgcError('timeout', '等待游戏图形画面超时，稍后自动重试。')
                try:
                    data, _ = process.communicate(timeout=min(.05, remaining))
                    communicated = True
                    break
                except subprocess.TimeoutExpired:
                    continue
            statuses = {10: ('unsupported', '此系统暂不支持 Windows 图形捕获。'),
                11: ('timeout', '等待游戏图形画面超时，稍后自动重试。'),
                12: ('stale', '截图期间窗口身份、位置或遮挡变化，已丢弃本帧。'),
                13: ('protected', '系统或目标窗口不允许捕获，已暂停本帧。'),
                14: ('backend-error', '系统图形捕获暂未提供可用画面，稍后自动重试。')}
            if process.returncode:
                status, message = statuses.get(process.returncode, ('backend-error', '系统图形捕获组件未正常完成。'))
                exception = WgcUnavailable if status == 'unsupported' else WgcError
                raise exception(status, message)
            if cancelled():
                raise WgcError('cancelled', '截图已取消。')
            try:
                if process_metadata(target.pid) != metadata:
                    raise WgcError('stale', '截图期间窗口进程身份变化，已丢弃本帧。')
            except (OSError, ValueError) as error:
                raise WgcError('stale', '截图窗口已退出，已丢弃本帧。') from error
            return decode_frame(data, pixel_roi)
        except OSError as error:
            raise WgcError('backend-error', '无法启动已验证的图形捕获组件。') from error
        finally:
            # Close the lifetime handle even if later pipe/process cleanup fails.
            # On cancellation/error this also asks Windows to terminate the sole
            # assigned child before our separately bounded reap attempt.
            job_closed = job is None or job.close()
            if not job_closed:
                self._pending_job = job
            # This helper never creates child processes. Kill only this exact
            # Popen-owned process, then reap it; never target an external PID.
            if process is not None:
                if not communicated:
                    if process.poll() is None:
                        try:
                            process.kill()
                        except OSError:
                            pass  # May have exited; verify completion below.
                    try:
                        process.communicate(timeout=.5)
                        communicated = True
                    except subprocess.TimeoutExpired:
                        # No indefinite GUI/app shutdown wait on a stuck driver.
                        # A Windows pipe reader can still own its stream lock;
                        # close() here could block. Retain this sole exact child
                        # and refuse new helpers until cleanup is confirmed.
                        self._pending_cleanup = process
                if communicated and process.stdout:
                    process.stdout.close()
            if not job_closed:
                raise WgcError('cleanup-pending', '系统尚未确认截图任务已关闭，已丢弃本帧。')

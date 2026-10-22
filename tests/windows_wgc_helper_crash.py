"""One owned-process crash observation, never product acceptance or live-game access.

Only this diagnostic launcher is instrumented. Production source, native helper
protocols, request/idle deadlines and the original formal gate stay unchanged.
Raw debugger text exists only in bounded memory. No dump or screenshot is saved.
"""
from __future__ import annotations

import argparse
import ctypes
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
RAW_LIMIT = 256 * 1024
FAST_FAIL = 0xC0000409
PRODUCT_FILES = (
    'native/wgc_capture.cpp', 'native/wgc_session_capture.cpp',
    'scripts/build_wgc_capture.py', 'scripts/build_wgc_session_capture.py',
    'wgc_session_capture.py', 'native_smoke.py', 'native_ui.py',
    'screen_capture.py', 'persistent_capture_adapter.py',
    'hero_recognition.py', 'card_badges.py', 'fixtures/auto-scene.png',
)
HELPER_FILES = ('build/native/vga-wgc-capture.exe', 'build/native/wgc-capture-build.json',
    'build/native/vga-wgc-session-capture.exe', 'build/native/wgc-session-capture-build.json')
REASONS = {'crash_recorded', 'not_reproduced', 'unsupported_host', 'invalid_tool_proof',
    'canary_failed', 'observer_not_ready', 'observer_overflow', 'observer_incomplete',
    'ownership_changed', 'owner_not_idle', 'lease_expired', 'native_probe_failed',
    'probe_timeout', 'cleanup_incomplete', 'source_changed', 'unexpected_failure',
    'duty_complete_no_screenshot'}


class DiagnosticError(RuntimeError):
    def __init__(self, reason):
        self.reason = reason if reason in REASONS else 'unexpected_failure'
        super().__init__(self.reason)


class DiagnosticComplete(DiagnosticError):
    """Uses the original failure-cleanup route, before its screenshot stage."""


def stop_after_duty_done(*args, **kwargs):
    raise DiagnosticComplete('duty_complete_no_screenshot')


def normalize_exit_status(code):
    if type(code) is not int or not -(2**31) <= code < 2**32:
        raise DiagnosticError('observer_incomplete')
    return code & 0xffffffff


def _nonce(nonce):
    if type(nonce) is not str or re.fullmatch('[0-9a-f]{16}', nonce) is None:
        raise DiagnosticError('observer_incomplete')
    return nonce


def build_cdb_commands(nonce):
    nonce = _nonce(nonce)
    # Only a second-chance fail-fast is inspected. gn leaves it unhandled.
    # k (not kb/kp) omits arguments; no dump, scripts, shell or symbol server.
    return (f'sxd -c2 ".echo VGA_EXCEPTION_{nonce};.exr -1;k 20;lm o;'
            f'.echo VGA_END_{nonce};gn" 0xc0000409\n'
            f'sx\n.echo VGA_READY_{nonce}\ng\n')


def _ready(text, nonce):
    lines = text.replace('\r', '').splitlines()
    marker = f'VGA_READY_{_nonce(nonce)}'
    if lines.count(marker) != 1:
        return False
    before = '\n'.join(lines[:lines.index(marker)]).lower()
    return bool(re.search(r'(?:c0000409|sbo\s*-\s*stack buffer overflow)[^\n]*second.chance', before))


def parse_cdb_text(text, nonce):
    """Convert exact exception/module output to a small address-free schema."""
    if type(text) is not str or len(text.encode('utf-8')) > RAW_LIMIT or '\x00' in text:
        raise DiagnosticError('observer_incomplete')
    nonce = _nonce(nonce)
    lines = text.replace('\r', '').splitlines()
    markers = [f'VGA_{kind}_{nonce}' for kind in ('READY', 'EXCEPTION', 'END')]
    if any(lines.count(item) != 1 for item in markers) or not _ready(text, nonce):
        raise DiagnosticError('observer_incomplete')
    positions = [lines.index(item) for item in markers]
    if positions != sorted(positions):
        raise DiagnosticError('observer_incomplete')
    body = lines[positions[1]+1:positions[2]]
    joined = '\n'.join(body)
    def scalar(pattern):
        found = re.findall(pattern, joined, re.M | re.I)
        if len(found) != 1:
            raise DiagnosticError('observer_incomplete')
        return int(found[0].replace('`', ''), 16)
    address = scalar(r'^\s*ExceptionAddress:\s*([0-9a-f`]+)')
    code = scalar(r'^\s*ExceptionCode:\s*([0-9a-f]+)')
    subtype = scalar(r'^\s*Parameter\[0\]:\s*([0-9a-f`]+)')
    count = re.findall(r'^\s*NumberParameters:\s*(\d+)\s*$', joined, re.M | re.I)
    if code != FAST_FAIL or subtype >= 2**32 or len(count) != 1 or not 1 <= int(count[0]) <= 15:
        raise DiagnosticError('observer_incomplete')
    modules = []
    for line in body:
        if line.strip().lower() == 'unloaded modules:':
            raise DiagnosticError('observer_incomplete')
        match = re.match(r'^\s*([0-9a-f]{8}`?[0-9a-f]{8})\s+([0-9a-f]{8}`?[0-9a-f]{8})\s+([A-Za-z0-9_.-]{1,80})\s+(?:\(|$)', line, re.I)
        if match:
            start, end = [int(value.replace('`', ''), 16) for value in match.group(1, 2)]
            if start >= end or any(start < other_end and end > other_start for other_start, other_end, _ in modules):
                raise DiagnosticError('observer_incomplete')
            modules.append((start, end, match[3]))
    def locate(value):
        found = [(name, value-start) for start, end, name in modules if start <= value < end]
        if len(found) != 1:
            raise DiagnosticError('observer_incomplete')
        return found[0]
    module, rva = locate(address)
    frames = []
    in_stack = False
    for line in body:
        if re.search(r'Child-SP\s+RetAddr\s+Call Site', line, re.I):
            in_stack = True
            continue
        if re.search(r'^\s*start\s+end\s+module name', line, re.I):
            in_stack = False
        if not in_stack:
            continue
        match = re.match(r'^\s*(?:[0-9a-f]{1,2}\s+)?([0-9a-f]{8}`?[0-9a-f]{8})\s+([0-9a-f]{8}`?[0-9a-f]{8})\s+\S', line, re.I)
        if not match:
            if line.strip():
                raise DiagnosticError('observer_incomplete')
            continue
        ret = int(match[2].replace('`', ''), 16)
        if not ret:
            break
        name, offset = locate(ret)
        frames.append(dict(return_module=name, return_rva=offset))
    if not 1 <= len(frames) <= 32:
        raise DiagnosticError('observer_incomplete')
    return dict(exception_code=code, fast_fail_subtype=subtype, exception_module=module,
                exception_rva=rva, frames=frames, complete=True)


def read_process_identity(process, job, expected_path):
    """Use the retained Popen HANDLE, never PID discovery, memory or injection."""
    if sys.platform != 'win32' or process.poll() is not None or not getattr(job, 'handle', None):
        raise DiagnosticError('ownership_changed')
    from ctypes import wintypes as W
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    specs = (
        ('GetProcessId', [W.HANDLE], W.DWORD),
        ('GetProcessTimes', [W.HANDLE, ctypes.POINTER(W.FILETIME), ctypes.POINTER(W.FILETIME), ctypes.POINTER(W.FILETIME), ctypes.POINTER(W.FILETIME)], W.BOOL),
        ('QueryFullProcessImageNameW', [W.HANDLE, W.DWORD, W.LPWSTR, ctypes.POINTER(W.DWORD)], W.BOOL),
        ('IsProcessInJob', [W.HANDLE, W.HANDLE, ctypes.POINTER(W.BOOL)], W.BOOL),
    )
    for name, args, result in specs:
        fn = getattr(kernel, name); fn.argtypes = args; fn.restype = result
    handle = int(process._handle)
    pid = int(kernel.GetProcessId(handle))
    times = [W.FILETIME() for _ in range(4)]
    length = W.DWORD(32768); path = ctypes.create_unicode_buffer(length.value)
    owned = W.BOOL()
    if (pid != process.pid or not kernel.GetProcessTimes(handle, *[ctypes.byref(t) for t in times])
            or not kernel.QueryFullProcessImageNameW(handle, 0, path, ctypes.byref(length))
            or not kernel.IsProcessInJob(handle, job.handle, ctypes.byref(owned)) or not owned.value):
        raise DiagnosticError('ownership_changed')
    expected = Path(expected_path).resolve()
    if Path(path.value).resolve() != expected or expected.is_symlink():
        raise DiagnosticError('ownership_changed')
    return dict(pid=pid, created=(times[0].dwHighDateTime << 32) | times[0].dwLowDateTime,
                path=str(expected), sha256=hashlib.sha256(expected.read_bytes()).hexdigest())


@dataclass(frozen=True)
class OwnerSnapshot:
    capture: object
    adapter: object
    owner: object
    session: object
    transport: object
    process: object
    job: object
    process_handle: int
    job_handle: int
    binding: tuple
    epoch: int
    receipt: dict
    identity: dict
    idle_deadline: float


def snapshot_owned_idle(capture, *, now=time.monotonic, identity_reader=read_process_identity):
    try:
        adapter = capture._persistent; owner = adapter._owner; epoch = adapter.epoch
        session = owner.session; transport = session._transport; process = transport.process
        if (adapter._closed or not adapter._enabled or adapter._allow_visible_overlay is not False
                or adapter._interactive_overlay or adapter._call_lock.locked() or adapter._prepared_visible_mode is not False or owner.binding[-1] is not False
                or owner.revoked.is_set() or not owner.setup_done.is_set() or not owner.call_done.is_set()
                or owner.close_done.is_set() or owner.cleanup_worker is not None
                or session._closed or session._allow_visible_overlay is not False
                or session._capture_lock.locked() or capture._capture_lock.locked()
                or transport.revoked.is_set() or transport.ready_for_replacement.is_set()
                or transport.io_done.is_set() or transport._active is not None
                or not transport.requests.empty() or transport.request_deadline is not None
                or transport.failure is not None or transport.job_closed or process.poll() is not None
                or getattr(capture._wgc, '_pending_cleanup', None) is not None
                or getattr(capture._wgc, '_pending_job', None) is not None):
            raise DiagnosticError('owner_not_idle')
        receipt = dict(capture.last_session_receipt or {})
        timing = dict(session.last_timing or {})
        timing_keys = {'request_cutoff_100ns', 'frame_100ns', 'idle_enter_100ns', 'request_id', 'session_generation'}
        if (set(timing) != timing_keys or any(type(v) is not int or not 0 < v < 2**63 for v in timing.values())
                or not timing['request_cutoff_100ns'] < timing['frame_100ns'] <= timing['idle_enter_100ns']
                or dict(adapter.last_receipt or {}) != receipt
                or not receipt or any(receipt.get(key) != value for key, value in timing.items())
                or receipt.get('request_id') != session._request_id
                or receipt.get('session_generation') != transport.generation
                or receipt.get('frame_100ns') != session._last_frame
                or receipt.get('overlay_registration_valid') is not True
                or receipt.get('overlay_affinity') != 0x11
                or receipt.get('overlay_hwnd') != adapter._overlay.hwnd
                or receipt.get('overlay_extended_style') != adapter._overlay.extended_style
                or session._overlay_generation != adapter._overlay.generation
                or session._overlay[:2] != (adapter._overlay.hwnd, adapter._overlay.extended_style)):
            raise DiagnosticError('ownership_changed')
        job = transport.job; process_handle = int(process._handle); job_handle = int(job.handle)
        binding = owner.binding; idle_deadline = transport.idle_deadline
        identity = identity_reader(process, job, session.helper_path)
        if (capture._persistent is not adapter or adapter._owner is not owner or owner.session is not session
                or session._transport is not transport or transport.process is not process or transport.job is not job
                or int(process._handle) != process_handle or job.handle != job_handle
                or adapter.epoch != epoch or owner.binding != binding or transport.idle_deadline != idle_deadline
                or dict(capture.last_session_receipt or {}) != receipt or dict(adapter.last_receipt or {}) != receipt
                or session.last_timing != timing or transport.revoked.is_set() or owner.revoked.is_set()
                or process.poll() is not None):
            raise DiagnosticError('ownership_changed')
        if receipt.get('helper_pid') != identity['pid'] or receipt.get('helper_created') != identity['created']:
            raise DiagnosticError('ownership_changed')
        snapshot = OwnerSnapshot(capture, adapter, owner, session, transport, process, transport.job,
            process_handle, job_handle, binding, epoch, receipt, identity, idle_deadline)
        attachment_timeout(snapshot, now=now)
        return snapshot
    except DiagnosticError:
        raise
    except (AttributeError, TypeError, ValueError, KeyError):
        raise DiagnosticError('owner_not_idle') from None


def attachment_timeout(snapshot, *, now=time.monotonic):
    remaining = snapshot.idle_deadline - now()
    if not 0 < remaining <= 4.01:
        raise DiagnosticError('lease_expired')
    return min(1.5, remaining)


def assert_same_owner(snapshot, capture, *, identity_reader=read_process_identity, now=time.monotonic):
    current = snapshot_owned_idle(capture, identity_reader=identity_reader, now=now)
    for name in ('capture', 'adapter', 'owner', 'session', 'transport', 'process', 'job'):
        if getattr(current, name) is not getattr(snapshot, name):
            raise DiagnosticError('ownership_changed')
    for name in ('process_handle', 'job_handle', 'binding', 'epoch', 'receipt', 'identity', 'idle_deadline'):
        if getattr(current, name) != getattr(snapshot, name):
            raise DiagnosticError('ownership_changed')


def _empty_observation():
    return dict(attempted=False, attached=False, entry_verified=False, request_verified=False,
                capture_returned=False, cleanup_complete=False, attachment_budget_us=None,
                attachment_elapsed_us=None, exit_code=None, crash=None)


def _validate_crash(value):
    if value is None:
        return
    if type(value) is not dict or set(value) != {'exception_code', 'fast_fail_subtype', 'exception_module', 'exception_rva', 'frames', 'complete'}:
        raise ValueError('Crash schema')
    if value['exception_code'] != FAST_FAIL or value['complete'] is not True:
        raise ValueError('Crash status')
    for key in ('fast_fail_subtype', 'exception_rva'):
        if type(value[key]) is not int or not 0 <= value[key] < 2**(32 if key == 'fast_fail_subtype' else 64):
            raise ValueError('Crash integer')
    def module(text):
        return type(text) is str and re.fullmatch(r'[A-Za-z0-9_.-]{1,80}', text) is not None
    if not module(value['exception_module']) or type(value['frames']) is not list or not 1 <= len(value['frames']) <= 32:
        raise ValueError('Crash frame list')
    for frame in value['frames']:
        if (type(frame) is not dict or set(frame) != {'return_module', 'return_rva'}
                or not module(frame['return_module']) or type(frame['return_rva']) is not int
                or not 0 <= frame['return_rva'] < 2**64):
            raise ValueError('Crash frame')


def validate_artifact(value):
    """Reject unknown fields. Never pass raw exception strings through."""
    expected = {'schema_version', 'status', 'reason', 'source_commit', 'product_hashes',
                'helper_hashes', 'tool', 'canary', 'probe', 'duty_completed', 'session_failure'}
    if type(value) is not dict or set(value) != expected or type(value['schema_version']) is not int or value['schema_version'] != 1:
        raise ValueError('Artifact schema')
    if value['status'] not in {'inconclusive', 'crash_recorded', 'not_reproduced'} or value['reason'] not in REASONS:
        raise ValueError('Artifact status')
    if type(value['source_commit']) is not str or re.fullmatch('[0-9a-f]{40}', value['source_commit']) is None:
        raise ValueError('Commit')
    if type(value['product_hashes']) is not dict or set(value['product_hashes']) != set(PRODUCT_FILES):
        raise ValueError('Input inventory')
    if any(type(v) is not str or re.fullmatch('[0-9a-f]{64}', v) is None for v in value['product_hashes'].values()):
        raise ValueError('Input hash')
    if (type(value['helper_hashes']) is not dict or set(value['helper_hashes']) != set(HELPER_FILES)
            or any(type(v) is not str or re.fullmatch('[0-9a-f]{64}', v) is None for v in value['helper_hashes'].values())):
        raise ValueError('Helper inventory')
    tool = value['tool']
    if (type(tool) is not dict or set(tool) != {'sha256', 'size', 'file_version'}
            or type(tool['sha256']) is not str or re.fullmatch('[0-9a-f]{64}', tool['sha256']) is None
            or type(tool['size']) is not int or not 1 <= tool['size'] <= 128 * 1024 * 1024
            or type(tool['file_version']) is not str or re.fullmatch(r'[0-9. ]{1,80}', tool['file_version']) is None):
        raise ValueError('Tool identity')
    for kind in ('canary', 'probe'):
        row = value[kind]
        if type(row) is not dict or set(row) != set(_empty_observation()):
            raise ValueError('Observation schema')
        if any(type(row[key]) is not bool for key in ('attempted', 'attached', 'entry_verified', 'request_verified', 'capture_returned', 'cleanup_complete')):
            raise ValueError('Observation flag')
        if row['exit_code'] is not None and (type(row['exit_code']) is not int or not 0 <= row['exit_code'] < 2**32):
            raise ValueError('Exit status')
        for key, maximum in (('attachment_budget_us', 1500000), ('attachment_elapsed_us', 180000000)):
            number = row[key]
            if number is not None and (type(number) is not int or not 0 <= number <= maximum):
                raise ValueError('Attachment timing')
        _validate_crash(row['crash'])
    if type(value['duty_completed']) is not bool:
        raise ValueError('Duty status')
    if value['session_failure'] is not None:
        from wgc_session_capture import sanitize_session_failure_evidence
        if sanitize_session_failure_evidence(value['session_failure']) != value['session_failure']:
            raise ValueError('Session evidence schema')
    if value['status'] != 'inconclusive':
        canary, probe = value['canary'], value['probe']
        if (not all(canary[key] and probe[key] for key in ('attempted', 'attached', 'entry_verified', 'request_verified', 'cleanup_complete'))
                or canary['exit_code'] != FAST_FAIL or canary['crash'] is None
                or canary['crash']['fast_fail_subtype'] != 7 or value['reason'] != value['status']):
            raise ValueError('Unproved diagnostic prerequisites')
        if any(row['attachment_budget_us'] is None or row['attachment_elapsed_us'] is None
                or not 0 <= row['attachment_elapsed_us'] <= row['attachment_budget_us'] <= 1500000
                for row in (canary, probe)):
            raise ValueError('Unproved attachment bound')
    if value['status'] == 'crash_recorded' and (value['probe']['crash'] is None or value['probe']['exit_code'] != FAST_FAIL):
        raise ValueError('Unproved crash')
    if value['status'] == 'not_reproduced' and (not value['duty_completed'] or not value['probe']['capture_returned'] or value['probe']['crash'] is not None
            or value['probe']['exit_code'] != 0 or value['session_failure'] is not None):
        raise ValueError('Unproved completed duty')
    if len(json.dumps(value).encode('utf-8')) > 64 * 1024:
        raise ValueError('Artifact budget')
    return value


class CdbObserver:
    """Own exactly one debugger and cap its pipe; never save raw output."""
    def __init__(self, cdb, process, folder):
        from wgc_capture import _CaptureJob
        self.nonce = secrets.token_hex(8); self.data = bytearray(); self.lock = threading.Lock()
        self.overflow = threading.Event(); self.done = threading.Event(); self.job = _CaptureJob()
        command_file = Path(folder) / ('commands-' + self.nonce + '.txt')
        command_file.write_text(build_cdb_commands(self.nonce), encoding='ascii')
        symbols = Path(folder) / 'empty-symbols'; symbols.mkdir(exist_ok=True)
        env = {key: value for key, value in os.environ.items()
               if key.upper() not in ('_NT_SYMBOL_PATH', '_NT_ALT_SYMBOL_PATH', '_NT_DEBUGGER_EXTENSION_PATH')}
        args = [str(cdb), '-G', '-pd', '-sins', '-noshell', '-nosqm', '-y', str(symbols),
                '-cf', str(command_file), '-p', str(process.pid)]
        try:
            self.process = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, cwd=folder, env=env, bufsize=0, creationflags=subprocess.CREATE_NO_WINDOW)
            self.job.assign(self.process)
        except BaseException:
            self.job.close()
            if getattr(self, 'process', None) is not None:
                self.process.kill(); self.process.wait(timeout=2)
            raise
        self.reader = threading.Thread(target=self._read, daemon=True); self.reader.start()

    def _read(self):
        try:
            while True:
                block = self.process.stdout.read(1024)
                if not block:
                    break
                with self.lock:
                    if len(self.data) + len(block) > RAW_LIMIT:
                        self.overflow.set(); break
                    self.data.extend(block)
        finally:
            self.done.set()

    def text(self):
        with self.lock:
            if self.overflow.is_set():
                raise DiagnosticError('observer_overflow')
            return bytes(self.data).decode('ascii', errors='replace')

    def ready(self, timeout):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.overflow.is_set():
                raise DiagnosticError('observer_overflow')
            if _ready(self.text(), self.nonce):
                return
            if self.done.is_set() or self.process.poll() is not None:
                break
            time.sleep(.005)
        raise DiagnosticError('observer_not_ready')

    def close(self):
        self.job.close()
        try:
            self.process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self.process.kill(); self.process.wait(timeout=2)
        self.reader.join(2)
        self.process.stdout.close()
        if self.reader.is_alive() or self.overflow.is_set() or self.job.handle is not None:
            raise DiagnosticError('cleanup_incomplete')


def _record(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise DiagnosticError('source_changed')
    return dict(sha256=hashlib.sha256(path.read_bytes()).hexdigest(), size=path.stat().st_size)


def _verify_proof(path):
    if Path(path).stat().st_size > RAW_LIMIT:
        raise DiagnosticError('invalid_tool_proof')
    proof = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    cdb = proof['cdb']
    required_helpers = set(HELPER_FILES)
    if (type(proof.get('schema_version')) is not int or proof['schema_version'] != 1
            or proof.get('status') != 'verified' or cdb.get('machine') != 'x64'
            or cdb.get('signature_status') != 'Valid'
            or re.search(r'(?:^|,\s*)O=Microsoft Corporation(?:,|$)', cdb.get('signer_subject', '')) is None
            or re.fullmatch(r'10\.\d+\.\d+\.\d+', cdb.get('file_version', '')) is None
            or not set(PRODUCT_FILES) <= set(proof.get('input_files', {}))
            or set(proof.get('helper_files', {})) != required_helpers
            or _record(cdb['path']) != {key: cdb[key] for key in ('sha256', 'size')}):
        raise DiagnosticError('invalid_tool_proof')
    for category in ('input_files', 'helper_files'):
        for name, record in proof[category].items():
            relative = Path(name)
            if relative.is_absolute() or '..' in relative.parts or _record(ROOT / relative) != record:
                raise DiagnosticError('source_changed')
    from scripts.build_wgc_capture import verify_built_helper as verify_one
    from scripts.build_wgc_session_capture import verify_built_helper as verify_session
    verify_one(); verify_session()
    return proof


def _compile_canary(folder):
    from scripts import microsoft_runtime
    from scripts.build_wgc_session_capture import community_toolchain, sdk_paths, clean_environment
    toolchain = community_toolchain(microsoft_runtime.verify_source_files())
    compiler = Path(toolchain['compiler_path']); vc = compiler.parents[3]
    sdk = Path(os.environ['ProgramFiles(x86)']) / 'Windows Kits' / '10'
    includes, libraries, _ = sdk_paths(sdk)
    env = clean_environment(); env['INCLUDE'] = ';'.join(map(str, [vc / 'include', *includes]))
    env['LIB'] = ';'.join(map(str, [vc / 'lib/x64', *libraries]))
    env['PATH'] = str(compiler.parent) + ';' + env.get('PATH', '')
    source = Path(folder) / 'owned_canary.cpp'; target = Path(folder) / 'owned_canary.exe'
    source.write_text('#include <intrin.h>\n#include <stdio.h>\nint main(){if(getchar()!=67)return 4;__fastfail(7);}\n', encoding='ascii')
    result = subprocess.run([str(compiler), '/nologo', '/O2', '/MT', str(source), '/Fe' + str(target),
        '/Fo' + str(Path(folder) / 'owned_canary.obj'), '/link', '/MACHINE:X64', '/SUBSYSTEM:CONSOLE'],
        cwd=folder, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
    if result.returncode != 0 or not target.is_file():
        raise DiagnosticError('canary_failed')
    return target


def run_canary(cdb, folder, row):
    from wgc_capture import _CaptureJob
    row['attempted'] = True
    target = _compile_canary(folder); job = _CaptureJob(); process = None; observer = None
    try:
        process = subprocess.Popen([str(target)], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, cwd=folder, creationflags=subprocess.CREATE_NO_WINDOW)
        job.assign(process); identity = read_process_identity(process, job, target)
        attach_start = time.monotonic(); attach_deadline = attach_start + 1.5
        row['attachment_budget_us'] = 1500000
        try:
            observer = CdbObserver(cdb, process, folder)
            remaining = attach_deadline - time.monotonic()
            if remaining <= 0:
                raise DiagnosticError('observer_not_ready')
            observer.ready(remaining)
        finally:
            row['attachment_elapsed_us'] = int((time.monotonic() - attach_start) * 1000000)
        if row['attachment_elapsed_us'] > row['attachment_budget_us']:
            raise DiagnosticError('observer_not_ready')
        if read_process_identity(process, job, target) != identity:
            raise DiagnosticError('ownership_changed')
        row['attached'] = True; row['entry_verified'] = True
        process.stdin.write(b'C'); process.stdin.flush(); row['request_verified'] = True
        row['exit_code'] = normalize_exit_status(process.wait(timeout=2))
        if not observer.done.wait(1):
            raise DiagnosticError('observer_incomplete')
        row['crash'] = parse_cdb_text(observer.text(), observer.nonce)
        if row['exit_code'] != FAST_FAIL or row['crash']['fast_fail_subtype'] != 7:
            raise DiagnosticError('canary_failed')
    finally:
        try:
            if observer is not None:
                observer.close()
        finally:
            job.close()
            if process is not None:
                process.wait(timeout=2)
                process.stdin.close()
            row['cleanup_complete'] = not job.handle and (process is None or process.poll() is not None)


def install_probe(smoke, cdb, folder, observation, result):
    """Wrap one known idle boundary, not the helper launcher or any product guard."""
    original_mode = smoke._start_overlay_duty_mode
    original_probe = smoke.start_overlay_duty_probe
    observers = []; retained = []; restore_capture = []
    def mode(control, **kwargs):
        if kwargs['mode_report']['mode'] != 'persistent':
            return original_mode(control, **kwargs)
        capture = control.capture; original_capture = capture.capture; armed = [False]
        restore_capture.append((capture, original_capture))
        def entry(*args, **kw):
            if not armed[0]:
                return original_capture(*args, **kw)
            if control.enable_visible_capture is not False:
                raise DiagnosticError('ownership_changed')
            snapshot = retained[0]
            assert_same_owner(snapshot, capture)
            armed[0] = False; observation['entry_verified'] = True
            try:
                value = original_capture(*args, **kw)
                observation['capture_returned'] = True
            finally:
                observation['request_verified'] = bool(
                    snapshot.session._transport is snapshot.transport
                    and snapshot.transport.process is snapshot.process
                    and snapshot.transport.generation == snapshot.receipt['session_generation']
                    and snapshot.session._request_id == snapshot.receipt['request_id'] + 1)
            receipt = dict(capture.last_session_receipt or {})
            if (not observation['request_verified'] or any(receipt.get(key) != snapshot.receipt[key]
                    for key in ('helper_pid', 'helper_created', 'session_generation'))
                    or receipt.get('request_id') != snapshot.receipt['request_id'] + 1):
                raise DiagnosticError('ownership_changed')
            return value
        capture.capture = entry
        original_paint = kwargs['paint_mock']
        def paint(*args, **kw):
            if kw.get('changed_title') is True:
                if observation['attempted']:
                    raise DiagnosticError('ownership_changed')
                observation['attempted'] = True
                if control.enable_visible_capture is not False or control.ocr_busy or control.capture_pending:
                    raise DiagnosticError('owner_not_idle')
                snapshot = snapshot_owned_idle(capture)
                from session_windows import process_metadata
                parent = process_metadata(os.getpid())
                if snapshot.session._parent != (os.getpid(), parent.created):
                    raise DiagnosticError('ownership_changed')
                helper = ROOT / 'build/native/vga-wgc-session-capture.exe'
                if (Path(snapshot.identity['path']).resolve() != helper.resolve()
                        or snapshot.identity['sha256'] != _record(helper)['sha256']):
                    raise DiagnosticError('ownership_changed')
                retained.append(snapshot)
                attach_start = time.monotonic(); budget = attachment_timeout(snapshot)
                attach_deadline = attach_start + budget
                observation['attachment_budget_us'] = int(budget * 1000000)
                try:
                    observer = CdbObserver(cdb, snapshot.process, folder); observers.append(observer)
                    remaining = min(attach_deadline - time.monotonic(), attachment_timeout(snapshot))
                    if remaining <= 0:
                        raise DiagnosticError('observer_not_ready')
                    observer.ready(remaining)
                finally:
                    observation['attachment_elapsed_us'] = int((time.monotonic() - attach_start) * 1000000)
                if observation['attachment_elapsed_us'] > observation['attachment_budget_us']:
                    raise DiagnosticError('observer_not_ready')
                assert_same_owner(snapshot, capture)
                observation['attached'] = True; armed[0] = True
            return original_paint(*args, **kw)
        kwargs['paint_mock'] = paint
        return original_mode(control, **kwargs)
    def probe(control, **kwargs):
        # Original done saves a PNG. Stop through its existing fail()/cleanup,
        # after both complete duty passes, never call or fake the screenshot.
        def complete():
            result['duty_completed'] = True
            stop_after_duty_done()
        kwargs['done'] = complete
        return original_probe(control, **kwargs)
    smoke._start_overlay_duty_mode = mode; smoke.start_overlay_duty_probe = probe
    def cleanup():
        smoke._start_overlay_duty_mode = original_mode; smoke.start_overlay_duty_probe = original_probe
        for capture, original in restore_capture:
            capture.capture = original
        for observer in observers:
            observer.done.wait(.2)
            observer.close()
            try:
                observation['crash'] = parse_cdb_text(observer.text(), observer.nonce)
            except DiagnosticError:
                pass
        if retained:
            process = retained[0].process
            if process.poll() is not None:
                observation['exit_code'] = normalize_exit_status(process.poll())
            observation['cleanup_complete'] = bool(process.poll() is not None and retained[0].transport.ready_for_replacement.is_set())
        else:
            observation['cleanup_complete'] = True
    return cleanup


def _child(args):
    import native_smoke
    import launcher
    result = dict(duty_completed=False, probe=_empty_observation())
    cleanup = install_probe(native_smoke, args.cdb, args.work, result['probe'], result)
    native_path = Path(args.work) / 'native.json'
    try:
        sys.argv = [str(ROOT / 'launcher.py'), '--no-updates', '--native-smoke-report', str(native_path)]
        launcher.entrypoint()
    finally:
        try:
            cleanup()
        except DiagnosticError as exc:
            result['reason'] = exc.reason
        if native_path.is_file() and native_path.stat().st_size <= RAW_LIMIT:
            native = json.loads(native_path.read_text(encoding='utf-8'))
            from wgc_session_capture import sanitize_session_failure_evidence
            failure = native.get('capture_failure_evidence', {}).get('final', {}).get('session_failure')
            result['session_failure'] = sanitize_session_failure_evidence(failure)
            if native.get('error_type') == 'DiagnosticError' and native.get('error') in REASONS:
                result['reason'] = native['error']
        Path(args.child_result).write_text(json.dumps(result), encoding='utf-8')
    return 1  # Deliberately not the formal gate, even when the duty completes.


def run_probe(cdb, folder, artifact):
    from tests.windows_native_smoke import native_environment
    artifact['probe']['attempted'] = False
    output = Path(folder) / 'child.json'
    command = [sys.executable, str(Path(__file__).resolve()), '--child', '--cdb', str(cdb),
               '--work', str(folder), '--child-result', str(output)]
    process = subprocess.Popen(command, cwd=folder, env=native_environment(os.environ, Path(folder), '1'),
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        process.wait(timeout=180)
    except subprocess.TimeoutExpired:
        process.kill(); process.wait(timeout=5)
        raise DiagnosticError('probe_timeout') from None
    if not output.is_file() or output.stat().st_size > 64 * 1024:
        raise DiagnosticError('native_probe_failed')
    result = json.loads(output.read_text(encoding='utf-8'))
    artifact['probe'] = result['probe']; artifact['duty_completed'] = result['duty_completed']
    artifact['session_failure'] = result.get('session_failure')
    if result.get('reason'):
        raise DiagnosticError(result['reason'])
    if not artifact['probe']['cleanup_complete']:
        raise DiagnosticError('cleanup_incomplete')
    if (artifact['probe']['crash'] is not None and artifact['probe']['exit_code'] == FAST_FAIL
            and artifact['probe']['request_verified']):
        artifact.update(status='crash_recorded', reason='crash_recorded')
    elif (artifact['duty_completed'] and artifact['probe']['entry_verified']
            and artifact['probe']['request_verified'] and artifact['probe']['capture_returned']
            and artifact['probe']['exit_code'] == 0 and artifact['session_failure'] is None):
        artifact.update(status='not_reproduced', reason='not_reproduced')
    else:
        raise DiagnosticError('observer_incomplete' if artifact['probe']['attached'] else 'native_probe_failed')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--debugger-proof', type=Path); parser.add_argument('--reports', type=Path)
    parser.add_argument('--child', action='store_true'); parser.add_argument('--cdb', type=Path)
    parser.add_argument('--work', type=Path); parser.add_argument('--child-result', type=Path)
    args = parser.parse_args(argv)
    if args.child:
        return _child(args)
    if sys.platform != 'win32' or not args.debugger_proof or not args.reports:
        raise DiagnosticError('unsupported_host')
    if args.reports.exists():
        raise DiagnosticError('source_changed')
    proof = _verify_proof(args.debugger_proof)
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    artifact = dict(schema_version=1, status='inconclusive', reason='unexpected_failure', source_commit=commit,
        product_hashes={name: _record(ROOT / name)['sha256'] for name in PRODUCT_FILES},
        helper_hashes={name: proof['helper_files'][name]['sha256'] for name in HELPER_FILES},
        tool={key: proof['cdb'][key] for key in ('sha256', 'size', 'file_version')},
        canary=_empty_observation(), probe=_empty_observation(), duty_completed=False, session_failure=None)
    try:
        with tempfile.TemporaryDirectory(prefix='vga-owned-crash-') as folder:
            run_canary(proof['cdb']['path'], folder, artifact['canary'])
            run_probe(proof['cdb']['path'], folder, artifact)
        _verify_proof(args.debugger_proof)
    except DiagnosticError as exc:
        artifact.update(status='inconclusive', reason=exc.reason)
    except Exception:
        artifact.update(status='inconclusive', reason='unexpected_failure')
    validate_artifact(artifact)
    destination = args.reports / 'reports' / 'windows-wgc-helper-crash.json'
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise DiagnosticError('source_changed')
    destination.write_text(json.dumps(artifact, sort_keys=True, indent=2) + '\n', encoding='utf-8')
    print('Owned helper diagnostic:', artifact['status'], artifact['reason'], '; not product acceptance')
    return 0 if artifact['status'] == 'not_reproduced' else 1


if __name__ == '__main__':
    raise SystemExit(main())

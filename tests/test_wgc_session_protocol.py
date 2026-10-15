"""Portable experiment tests only; fakes are NOT Windows/pixel/lifecycle proof."""
from contextlib import ExitStack
import ctypes
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from session_windows import ProcessMetadata
from screen_capture import ClientRect, WindowInfo
import wgc_session_capture as session
from wgc_capture import WgcError, WgcUnavailable, decode_native_diagnostic

ROOT = Path(__file__).resolve().parents[1]
ROI = (5, 7, 16, 16)
PIXELS = bytes([17, 23, 29, 255]) * (16 * 16)
CLOCK_KEYS = {'qpc_counter', 'qpc_frequency', 'cutoff_100ns', 'frame_100ns',
              'observed_now_100ns', 'previous_frame_100ns'}


def clock_diagnostic(**changes):
    value = dict(schema_version=1, code=12, phase='frame-wait', check='frame-timestamp',
                 hresult=0, style=0, extended_style=0, observed=[0]*4, expected=[0]*4,
                 window_rect=[0]*4, frame_rect=[0]*4,
                 clock=dict(qpc_counter=100, qpc_frequency=10000000, cutoff_100ns=98,
                            frame_100ns=101, observed_now_100ns=100, previous_frame_100ns=97))
    value.update(changes)
    return value


def diagnostic_bytes(value):
    return json.dumps(value, separators=(',', ':')).encode('ascii')


def shutdown_trace(count=7):
    return b''.join(f'S{index}\n'.encode('ascii') for index in range(1, count + 1))


def shutdown_failure(**changes):
    value = clock_diagnostic(code=14, phase='shutdown', check='hresult')
    value.pop('clock')
    value.update(changes)
    return value


def packet(request_id=1, generation=7, cutoff=100, frame=101, entered=102, **changes):
    fields = dict(magic=session.RESPONSE_MAGIC, status=0, phase=1, request_id=request_id,
                  generation=generation, width=16, height=16, length=len(PIXELS), reserved=0,
                  cutoff=cutoff, frame=frame)
    fields.update(changes)
    return bytearray(session.RESPONSE.pack(*fields.values()) + PIXELS +
                     session.IDLE.pack(session.IDLE_MAGIC, request_id, generation, entered))


class ProtocolTests(unittest.TestCase):
    def test_exact_little_endian_layout_sizes_and_roundtrip(self):
        self.assertEqual((session.REQUEST.size, session.RESPONSE.size, session.IDLE.size), (56, 64, 32))
        raw = session.encode_request(0x102, 0x304, ROI)
        self.assertEqual(raw[16:24], b'\x02\x01\0\0\0\0\0\0')
        self.assertEqual(session.REQUEST.unpack(raw),
                         (b'VGASREQ2', 1, 56, 0x102, 0x304, 5, 7, 16, 16, 800, 0))
        image, timing = session.decode_response(packet(), ROI, 1, 7)
        self.assertEqual(image.getpixel((0, 0)), (29, 23, 17))
        self.assertEqual(timing['idle_enter_100ns'], 102)

    def test_stop_never_authorizes_roi(self):
        self.assertEqual(session.REQUEST.unpack(session.encode_request(2, 7, (0, 0, 0, 0), stop=True))[1], 2)
        with self.assertRaises(ValueError):
            session.encode_request(2, 7, ROI, stop=True)

    def test_invalid_request_ids_generations_deadlines_and_roi(self):
        cases = [(0, 7, ROI, 800), (True, 7, ROI, 800), (1, 0, ROI, 800),
                 (1, 7, ROI, 49), (1, 7, ROI, 1201), (1, 7, (-1, 0, 16, 16), 800),
                 (1, 7, (0, 0, 15, 16), 800), (1, 7, (0, 0, 5000, 5000), 800),
                 (1, 7, (0, 0, 16.0, 16), 800), (1, 7, (0, 0, 16), 800)]
        for args in cases:
            with self.subTest(args=args), self.assertRaises(ValueError):
                session.encode_request(*args)

    def test_no_pixels_without_exact_idle_trailer(self):
        good = packet()
        for bad in (b'', good[:64], good[:-32], good[:-1], good + b'x'):
            with self.subTest(length=len(bad)), self.assertRaises(WgcError):
                session.decode_response(bad, ROI, 1, 7)
        for trailer in (session.IDLE.pack(b'WRONG123', 1, 7, 102),
                        session.IDLE.pack(session.IDLE_MAGIC, 2, 7, 102),
                        session.IDLE.pack(session.IDLE_MAGIC, 1, 8, 102),
                        session.IDLE.pack(session.IDLE_MAGIC, 1, 7, 100)):
            with self.assertRaises(WgcError):
                session.decode_response(good[:-32] + trailer, ROI, 1, 7)

    def test_rejects_wrong_header_scope_ids_status_and_reserved(self):
        for changes in ({'magic': b'WRONG123'}, {'status': 12}, {'phase': 2},
                        {'request_id': 2}, {'generation': 8}, {'width': 17}, {'height': 17},
                        {'length': 2**32 - 1}, {'reserved': 1}):
            with self.subTest(changes=changes), self.assertRaises(WgcError):
                session.decode_response(packet(**changes), ROI, 1, 7)

    def test_freshness_requires_strict_post_request_and_monotonic_time(self):
        for cutoff, frame, entered in ((0, 1, 2), (101, 101, 102), (102, 101, 103), (100, 101, 100)):
            with self.subTest(times=(cutoff, frame, entered)), self.assertRaises(WgcError):
                session.decode_response(packet(cutoff=cutoff, frame=frame, entered=entered), ROI, 1, 7)
        with self.assertRaises(WgcError):
            session.decode_response(packet(), ROI, 1, 7, previous_frame=101)
        with self.assertRaises(WgcError):
            session.decode_response(packet(), ROI, 1, 7, earliest_cutoff=101)
        with self.assertRaises(WgcError):
            session.decode_response(packet(), ROI, 1, 7, latest_timestamp=101)

    def test_wipe_clears_retained_buffer(self):
        data = bytearray(b'x' * 200000)
        session._wipe(data)
        self.assertEqual(data, bytearray())

    def test_default_off_before_any_helper_access(self):
        with patch.object(session.WgcSessionCapture, '_verify_helper') as verify:
            for flag in (False, None, 1, 'true'):
                with self.assertRaises(WgcError) as error:
                    session.WgcSessionCapture(experimental=flag)
                self.assertEqual(error.exception.status, 'experiment-disabled')
            verify.assert_not_called()

    def test_manifest_is_distinct_and_hash_verified(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            raw = b'owned experimental fixture helper'
            (directory / session.HELPER_NAME).write_bytes(raw)
            proof = dict(schema_version=1, protocol=2, profile=session.PROFILE, status='passed',
                         filename=session.HELPER_NAME, size=len(raw), sha256=hashlib.sha256(raw).hexdigest(),
                         source_sha256='a' * 64, build_recipe_sha256='b' * 64)
            manifest = directory / session.MANIFEST_NAME
            for changes in ({'protocol': 1}, {'profile': 'hwnd-wgc-v1'}, {'status': 'failed'},
                            {'sha256': '0' * 64}, {'schema_version': True}, {}):
                manifest.write_text(json.dumps(dict(proof, **changes)))
                with patch.object(session, 'helper_directory', return_value=directory):
                    if changes:
                        with self.assertRaises(WgcError):
                            session.WgcSessionCapture(experimental=True)
                    else:
                        session.WgcSessionCapture(experimental=True).close()

    def test_bounded_allowlisted_diagnostic_and_duplicate_fields(self):
        good = dict(schema_version=1, code=12, phase='validate-idle', check='overlay-generation',
                    hresult=0, style=0, extended_style=0, observed=[0]*4, expected=[0]*4,
                    window_rect=[0]*4, frame_rect=[0]*4)
        raw = json.dumps(good).encode('ascii')
        self.assertEqual(session.decode_session_diagnostic(raw, 12), good)
        for bad in (b'x' * 1025, raw[:-1] + b',"code":12}',
                    json.dumps(dict(good, path='private')).encode(),
                    json.dumps(dict(good, check='arbitrary-text')).encode()):
            self.assertIsNone(session.decode_session_diagnostic(bad, 12))
        self.assertIsNone(session.decode_session_diagnostic(raw, 13))

    def test_shutdown_checkpoints_preserve_exact_abnormal_exit_and_are_failure_only(self):
        stages = ('frame-arrived-revoke', 'item-closed-revoke', 'session-close', 'pool-close',
                  'local-release', 'apartment-uninit', 'process-return')
        self.assertEqual(session.SESSION_SHUTDOWN_STAGES, stages)
        for count, stage in enumerate(stages, 1):
            for code in (-(2**31), -1073741819, -9, 1, 10, 14, 3221225477, 2**32 - 1):
                expected = dict(schema_version=1, exit_code=code, checkpoints=list(range(1, count + 1)),
                                last_started_stage=stage)
                for raw in (shutdown_trace(count), bytearray(shutdown_trace(count))):
                    self.assertEqual(session.decode_session_shutdown_diagnostic(raw, code), expected)
                    self.assertIsNone(session.decode_session_diagnostic(raw, code))
                    self.assertIsNone(decode_native_diagnostic(bytes(raw), code))
            self.assertIsNone(session.decode_session_shutdown_diagnostic(shutdown_trace(count), 0))
        for code in (None, True, False, 1.0, 3221225477.0, '3221225477', -(2**31)-1, 2**32):
            self.assertIsNone(session.decode_session_shutdown_diagnostic(shutdown_trace(), code))

    def test_completed_native_shutdown_requires_exact_complete_raw_trace_and_integer_zero(self):
        for raw in (shutdown_trace(), bytearray(shutdown_trace())):
            self.assertIs(session.completed_native_shutdown(raw, 0), True)
            self.assertIsNone(session.decode_session_shutdown_diagnostic(raw, 0))
            self.assertIsNone(session.decode_session_diagnostic(raw, 0))
        for code in (None, True, False, 0.0, '0', 1, -9, 14, 3221225477):
            self.assertIs(session.completed_native_shutdown(shutdown_trace(), code), False)
        malformed = (None, 'S1\n', memoryview(shutdown_trace()), [83, 49, 10],
                     b'', b'S1\r\n' + shutdown_trace()[3:], shutdown_trace()[3:],
                     b'S1\nS1\n' + shutdown_trace()[3:], b'S2\nS1\n' + shutdown_trace()[6:],
                     b' ' + shutdown_trace(), shutdown_trace() + b' ', shutdown_trace() + b'\n',
                     shutdown_trace() + b'S8\n', shutdown_trace() + b'\xff',
                     shutdown_trace() + diagnostic_bytes(shutdown_failure()), b'x' * 1025)
        for raw in (*malformed, *(shutdown_trace(count) for count in range(7))):
            with self.subTest(raw=raw):
                self.assertIs(session.completed_native_shutdown(raw, 0), False)

    def test_module_pin_failure_is_bounded_session_only_diagnostic(self):
        failure = shutdown_failure(phase='session-create', check='capture-module-pin')
        raw = diagnostic_bytes(failure)
        self.assertEqual(session.decode_session_diagnostic(raw, 14), failure)
        self.assertIsNone(decode_native_diagnostic(raw, 14))
        self.assertIsNone(session.decode_session_shutdown_diagnostic(raw, 14))
        self.assertFalse(session.completed_native_shutdown(raw, 0))

    def test_shutdown_json_tail_retains_existing_failure_and_requires_shutdown(self):
        good = shutdown_failure()
        raw = diagnostic_bytes(good)
        self.assertEqual(session.decode_session_diagnostic(raw, 14), good)
        self.assertIsNone(session.decode_session_shutdown_diagnostic(raw, 14))
        for count in range(1, 8):
            transcript = shutdown_trace(count) + raw + b'\n'
            self.assertEqual(session.decode_session_diagnostic(transcript, 14), good)
            self.assertEqual(session.decode_session_shutdown_diagnostic(transcript, 14)['checkpoints'],
                             list(range(1, count + 1)))
            self.assertIsNone(decode_native_diagnostic(transcript, 14))
            for code in (0, 13, 3221225477):
                self.assertIsNone(session.decode_session_diagnostic(transcript, code))
                self.assertIsNone(session.decode_session_shutdown_diagnostic(transcript, code))
        for bad in (clock_diagnostic(), shutdown_failure(phase='startup'),
                    shutdown_failure(clock=clock_diagnostic()['clock'])):
            transcript = shutdown_trace(3) + diagnostic_bytes(bad)
            self.assertIsNone(session.decode_session_diagnostic(transcript, bad['code']))
            self.assertIsNone(session.decode_session_shutdown_diagnostic(transcript, bad['code']))

    def test_shutdown_whole_transcript_rejects_partial_reordered_duplicate_or_private_data(self):
        raw = diagnostic_bytes(shutdown_failure())
        malformed = (b'', b'S', b'S1', b'S1\r\n', b'S0\n', b'S2\n', b'S8\n', b'S1\nS1\n',
                     b'S1\nS3\n', b'S1\nS2', b'S1\nS2\nS1\n', shutdown_trace() + b'S8\n',
                     shutdown_trace() + b'S7\n', b' ' + shutdown_trace(), shutdown_trace() + b' ',
                     b'private\n' + shutdown_trace(), shutdown_trace() + b'private',
                     raw + shutdown_trace(), shutdown_trace() + raw + raw,
                     shutdown_trace() + raw[:-1], shutdown_trace() + b'\xff',
                     shutdown_trace() + raw[:-1] + b',"code":14}',
                     shutdown_trace() + diagnostic_bytes(shutdown_failure(path='private')))
        for data in malformed:
            for code in (14, 3221225477):
                with self.subTest(data=data, code=code):
                    self.assertIsNone(session.decode_session_diagnostic(data, code))
                    self.assertIsNone(session.decode_session_shutdown_diagnostic(data, code))
        for data in (None, 'S1\n', memoryview(shutdown_trace()), [83, 49, 10]):
            self.assertIsNone(session.decode_session_shutdown_diagnostic(data, 3221225477))

    def test_shutdown_combined_transcript_has_same_total_byte_cap(self):
        raw = shutdown_trace() + diagnostic_bytes(shutdown_failure())
        padded = raw + b' ' * (session.MAX_DIAGNOSTIC_BYTES - len(raw))
        self.assertEqual(session.decode_session_diagnostic(padded, 14), shutdown_failure())
        self.assertEqual(session.decode_session_shutdown_diagnostic(padded, 14)['checkpoints'], list(range(1, 8)))
        for data in (padded + b' ', shutdown_trace() + b'x' * 1024):
            self.assertIsNone(session.decode_session_diagnostic(data, 14))
            self.assertIsNone(session.decode_session_shutdown_diagnostic(data, 14))

    def test_shutdown_record_sanitizer_requires_exact_types_keys_prefix_stage_and_exit(self):
        code = 3221225477
        good = dict(schema_version=1, exit_code=code, checkpoints=[1, 2, 3, 4, 5, 6],
                    last_started_stage='apartment-uninit')
        clean = session.sanitize_session_shutdown_diagnostic(good, code)
        self.assertEqual(clean, good)
        self.assertIsNot(clean, good)
        self.assertIsNot(clean['checkpoints'], good['checkpoints'])
        for key in good:
            missing = dict(good); missing.pop(key)
            self.assertIsNone(session.sanitize_session_shutdown_diagnostic(missing, code))
        changes = ({'schema_version': True}, {'schema_version': 1.0}, {'schema_version': 2},
                   {'exit_code': True}, {'exit_code': float(code)}, {'exit_code': 14},
                   {'checkpoints': []}, {'checkpoints': [1, 3]}, {'checkpoints': [True]},
                   {'checkpoints': [1.0, 2, 3, 4, 5, 6]}, {'checkpoints': list(range(1, 9))},
                   {'checkpoints': (1, 2, 3, 4, 5, 6)}, {'checkpoints': None},
                   {'last_started_stage': 'pool-close'}, {'last_started_stage': 'private'},
                   {'last_started_stage': None}, {'raw_stderr': 'private'}, {'path': 'private'})
        for changed in changes:
            self.assertIsNone(session.sanitize_session_shutdown_diagnostic(dict(good, **changed), code))
        for bad in (None, [], 'private', True):
            self.assertIsNone(session.sanitize_session_shutdown_diagnostic(bad, code))
        for invalid in (0, True, False, 1.0, str(code), -(2**31)-1, 2**32, None):
            self.assertIsNone(session.sanitize_session_shutdown_diagnostic(dict(good, exit_code=invalid), invalid))

    def test_session_clock_is_optional_exact_and_never_accepted_by_v1(self):
        self.assertEqual(session.SESSION_CLOCK_KEYS, CLOCK_KEYS)
        for phase in ('frame-wait', 'validate-idle'):
            for with_clock in (False, True):
                good = clock_diagnostic(phase=phase)
                if not with_clock:
                    good.pop('clock')
                raw = diagnostic_bytes(good)
                self.assertEqual(session.decode_session_diagnostic(raw, 12), good)
                self.assertEqual(session.decode_session_diagnostic(bytearray(raw), 12), good)
        # Use otherwise valid v1 phase/check so the extension alone is rejected.
        old = clock_diagnostic(phase='startup', check='invariant')
        self.assertIsNone(decode_native_diagnostic(diagnostic_bytes(old), 12))
        old.pop('clock')
        self.assertEqual(decode_native_diagnostic(diagnostic_bytes(old), 12), old)

    def test_session_clock_requires_exact_keys_and_object(self):
        good = clock_diagnostic()
        for key in CLOCK_KEYS:
            bad = dict(good['clock']); bad.pop(key)
            with self.subTest(missing=key):
                self.assertIsNone(session.decode_session_diagnostic(diagnostic_bytes(dict(good, clock=bad)), 12))
        for bad in (None, [], 0, True, 'private', dict(good['clock'], extra=0),
                    dict(good['clock'], path='private')):
            with self.subTest(clock=bad):
                self.assertIsNone(session.decode_session_diagnostic(diagnostic_bytes(dict(good, clock=bad)), 12))
        for key in ('path', 'title', 'pixels', 'raw_stderr'):
            self.assertIsNone(session.decode_session_diagnostic(diagnostic_bytes(dict(good, **{key: 'private'})), 12))

    def test_session_clock_exact_signed_int64_values(self):
        good = clock_diagnostic()
        for key in CLOCK_KEYS:
            for number in (-(2**63), -1, 0, 2**63 - 1):
                value = dict(good, clock=dict(good['clock'], **{key: number}))
                with self.subTest(key=key, accepted=number):
                    self.assertEqual(session.decode_session_diagnostic(diagnostic_bytes(value), 12), value)
            for number in (True, False, 0.0, 1.0, -(2**63)-1, 2**63, '1', None, [], {},
                           float('nan'), float('inf'), -float('inf')):
                value = dict(good, clock=dict(good['clock'], **{key: number}))
                with self.subTest(key=key, rejected=number):
                    self.assertIsNone(session.decode_session_diagnostic(diagnostic_bytes(value), 12))

    def test_session_clock_only_matches_timestamp_failure_phase_check_and_code(self):
        for phase in sorted(session.SESSION_PHASES - {'frame-wait', 'validate-idle'}):
            self.assertIsNone(session.decode_session_diagnostic(diagnostic_bytes(clock_diagnostic(phase=phase)), 12))
        for check in sorted(session.SESSION_CHECKS - {'frame-timestamp'}):
            self.assertIsNone(session.decode_session_diagnostic(diagnostic_bytes(clock_diagnostic(check=check)), 12))
        for code in (0, 10, 11, 13, 14, 15, True, 12.0, '12', None):
            value = clock_diagnostic(code=code)
            self.assertIsNone(session.decode_session_diagnostic(diagnostic_bytes(value), code))
        raw = diagnostic_bytes(clock_diagnostic())
        for returncode in (0, 10, 11, 13, 14, -9, 12.0, True, '12', None):
            self.assertIsNone(session.decode_session_diagnostic(raw, returncode))

    def test_session_clock_duplicate_fields_and_malformed_json_never_exposed(self):
        raw = diagnostic_bytes(clock_diagnostic())
        for key in CLOCK_KEYS:
            token = ('"' + key + '":').encode()
            duplicate = raw.replace(token, token + b'0,' + token)
            self.assertIsNone(session.decode_session_diagnostic(duplicate, 12))
        for bad in (raw[:-1] + b',"clock":{}}', raw[:-1] + b',"code":12}',
                    raw + b'private stderr', raw + b'\n' + raw, raw[:-1], b'\xff',
                    b'null', b'[]', b'"private"', raw + b' ' * 1024):
            self.assertIsNone(session.decode_session_diagnostic(bad, 12))
        self.assertEqual(session.decode_session_diagnostic(raw + b' ' * (1024 - len(raw)), 12),
                         clock_diagnostic())
        self.assertIsNone(session.decode_session_diagnostic(raw + b' ' * (1025 - len(raw)), 12))

    def test_session_clock_does_not_bypass_geometry_sanitizer(self):
        for changes in ({'observed': [0, 0, 0, 2**32]}, {'expected': [True]*4},
                        {'window_rect': [0.0]*4}, {'frame_rect': [0]*3},
                        {'style': -1}, {'extended_style': 2**32}, {'hresult': True},
                        {'schema_version': True}, {'code': 12.0}):
            self.assertIsNone(session.decode_session_diagnostic(diagnostic_bytes(clock_diagnostic(**changes)), 12))

    def test_transport_retains_only_validated_session_clock(self):
        # Exercise only the decoder adapter; do not start real lifetime threads
        # against an intentionally incomplete process double.
        transport = object.__new__(session._Transport)
        transport.process = SimpleNamespace(poll=lambda: 12)
        good = clock_diagnostic()
        transport.diagnostic = bytearray(diagnostic_bytes(good))
        error = transport._native_error(RuntimeError('private stderr'))
        self.assertEqual(error.status, 'stale')
        self.assertEqual(error.diagnostic, good)
        transport.diagnostic.extend(b'private stderr')
        error = transport._native_error(RuntimeError('private stderr'))
        self.assertEqual(error.status, 'stale')
        self.assertIsNone(error.diagnostic)
        self.assertNotIn('private', str(error))


class Pipe:
    def __init__(self):
        self.condition = threading.Condition()
        self.data = bytearray()
        self.closed = False

    def feed(self, data):
        with self.condition:
            self.data.extend(data); self.condition.notify_all()

    def read(self, size):
        with self.condition:
            while not self.data and not self.closed:
                self.condition.wait()
            result = bytes(self.data[:size]); del self.data[:size]
            return result

    def close(self):
        with self.condition:
            self.closed = True; self.condition.notify_all()

    def available(self):
        with self.condition:
            return len(self.data)


class FakeProcess:
    def __init__(self, *, response=None, delayed_kill=False, blocked_write=False):
        self.stdout, self.stderr = Pipe(), Pipe()
        self.ended = threading.Event()
        self.stdin = SimpleNamespace(write=self.write, close=Mock())
        self.returncode = None
        self.response = response
        self.delayed_kill, self.blocked_write = delayed_kill, blocked_write
        self.writes = []; self.kills = 0; self.assigned = False
        self._handle = 987
        self.generation = 7

    def write(self, data):
        data = bytes(data)
        self.writes.append(data)
        if data == b'C':
            if not self.assigned:
                raise AssertionError('Capture start gate preceded Job assignment')
            return 1
        if self.blocked_write:
            self.ended.wait()
            raise OSError('Owned pipe terminated')
        magic, opcode, size, request_id, generation, *_ = session.REQUEST.unpack(data)
        self.generation = generation
        response = self.response(request_id, generation) if self.response else packet(request_id, generation, 100 + request_id*10, 101 + request_id*10, 102 + request_id*10)
        if response is not None:
            self.stdout.feed(response)
        return len(data)

    def poll(self):
        return self.returncode

    def kill(self):
        self.kills += 1
        if not self.delayed_kill:
            self.exit(-9)

    def exit(self, code=0):
        self.returncode = code
        self.ended.set(); self.stdout.close(); self.stderr.close()

    def wait(self, timeout=None):
        if not self.ended.wait(timeout):
            raise subprocess.TimeoutExpired('owned-helper', timeout)
        return self.returncode


class WrapperTests(unittest.TestCase):
    def setUp(self):
        self.target = WindowInfo(123, 77, 'owned fixture', 'owned')
        self.rect = ClientRect(-100, 20, 800, 600)
        self.target_metadata = ProcessMetadata('c:\\owned\\fixture.exe', 100000)
        self.parent_metadata = ProcessMetadata('c:\\owned\\parent.exe', 200000)
        self.stack = ExitStack(); self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(session.WgcSessionCapture, '_verify_helper'))
        self.capture = session.WgcSessionCapture(experimental=True)
        self.addCleanup(self.capture.close)
        self.stack.enter_context(patch.object(session.os, 'name', 'nt'))
        self.stack.enter_context(patch.object(session.os, 'getpid', return_value=99))
        self.stack.enter_context(patch.object(session, 'process_metadata', side_effect=lambda pid: self.parent_metadata if pid == 99 else self.target_metadata))
        self.stack.enter_context(patch.object(session, '_qpc_100ns', side_effect=lambda: 1 if not self.capture._transport or not self.capture._transport._active or not self.capture._transport._active.done.is_set() else 1000000))
        self.stack.enter_context(patch.object(session, '_pipe_available', side_effect=lambda stream: stream.available()))
        self.stack.enter_context(patch.object(session.secrets, 'randbelow', return_value=6))
        self.stack.enter_context(patch.object(session.secrets, 'randbits', return_value=555))
        self.stack.enter_context(patch.object(session, 'PROCESS_TIMEOUT', .15))
        self.stack.enter_context(patch.object(session, 'IDLE_LEASE', .4))
        self.stack.enter_context(patch.object(session, 'WATCHDOG_INTERVAL', .005))
        self.process = FakeProcess()
        self.job = Mock()
        self.job.close.return_value = True
        self.job.assign.side_effect = lambda process: setattr(process, 'assigned', True)
        self.spawn = self.stack.enter_context(patch.object(session.subprocess, 'Popen', side_effect=lambda *a, **kw: self.process))
        self.stack.enter_context(patch.object(session, '_CaptureJob', return_value=self.job))

    def wait_cleanup(self):
        self.capture.close()
        transport = self.capture._transport
        if transport:
            self.assertTrue(transport.ready_for_replacement.wait(2), 'owned fake cleanup timed out')

    def test_exact_immutable_startup_and_multiple_requests_reuse_one_helper(self):
        first = self.capture.capture(self.target, self.rect, ROI, expected_metadata=self.target_metadata)
        second = self.capture.capture(self.target, self.rect, ROI)
        self.assertEqual(first.getpixel((0, 0)), second.getpixel((0, 0)))
        self.assertEqual(self.spawn.call_count, 1)
        args = self.spawn.call_args.args[0]
        self.assertEqual(args[1:], ['--session-v2', '123', '77', '100000', '-100', '20', '800', '600',
                                  '99', '200000', '0', '0', '0', '7'])
        self.assertFalse(self.spawn.call_args.kwargs['shell'])
        self.assertEqual(self.process.writes[0], b'C')
        self.assertEqual([session.REQUEST.unpack(x)[3] for x in self.process.writes[1:]], [1, 2])
        self.assertEqual(self.capture.last_timing['request_id'], 2)
        self.assertIs(self.capture._transport.termination_requested_while_alive, False)
        self.wait_cleanup()
        self.assertIs(self.capture._transport.termination_requested_while_alive, True)

    def test_natural_exit_then_cleanup_never_records_parent_termination(self):
        self.capture.capture(self.target, self.rect, ROI)
        transport = self.capture._transport
        self.process.stderr.feed(shutdown_trace())
        self.process.exit(0)
        self.assertTrue(transport.ready_for_replacement.wait(2))
        self.assertIs(transport.termination_requested_while_alive, False)
        self.assertEqual(self.process.kills, 0)
        self.assertTrue(session.completed_native_shutdown(transport.diagnostic, self.process.returncode))
        self.job.close.assert_called_once()

    def test_job_termination_stays_recorded_even_when_child_has_full_trace_and_zero_exit(self):
        self.capture.capture(self.target, self.rect, ROI)
        transport = self.capture._transport
        self.process.stderr.feed(shutdown_trace())
        def terminate_job():
            self.assertIs(transport.termination_requested_while_alive, True)
            self.process.exit(0)
            return True
        self.job.close.side_effect = terminate_job
        self.wait_cleanup()
        self.assertEqual(self.process.kills, 0)
        self.assertIs(transport.termination_requested_while_alive, True)
        self.assertTrue(session.completed_native_shutdown(transport.diagnostic, 0))
        transport._terminate()
        self.assertIs(transport.termination_requested_while_alive, True)

    def test_termination_flag_records_attempts_without_changing_job_or_process_actions(self):
        # Execute the actual termination method with deterministic exact-child
        # doubles, without asynchronous workers racing these individual branches.
        for job_kind, process_kind, expected, kills in (
                ('none', 'none', False, 0), ('close', 'none', False, 0),
                ('close', 'exited', False, 0), ('none', 'alive', True, 1),
                ('closed', 'alive', True, 1), ('close', 'alive', True, 1),
                ('fails', 'alive', True, 1), ('raises', 'alive', True, 1),
                ('close', 'kill-raises', True, 1)):
            with self.subTest(job=job_kind, process=process_kind):
                transport = object.__new__(session._Transport)
                transport.job = None if job_kind == 'none' else Mock()
                transport.job_closed = job_kind == 'closed'
                transport.termination_requested_while_alive = False
                process = None if process_kind == 'none' else FakeProcess()
                transport.process = process
                if process_kind == 'exited':
                    process.exit(0)
                if transport.job is not None:
                    transport.job.close.return_value = job_kind != 'fails'
                    if job_kind == 'raises':
                        transport.job.close.side_effect = OSError('owned job failure')
                if process is not None:
                    original_kill = process.kill
                    def kill():
                        self.assertIs(transport.termination_requested_while_alive, True)
                        if process_kind == 'kill-raises':
                            raise OSError('owned process failure')
                        original_kill()
                    process.kill = Mock(side_effect=kill)
                transport._terminate()
                self.assertIs(transport.termination_requested_while_alive, expected)
                if process is not None:
                    self.assertEqual(process.kill.call_count, kills)
                if transport.job is not None:
                    self.assertEqual(transport.job.close.call_count, int(job_kind != 'closed'))
                self.assertIs(transport.job_closed, job_kind in ('closed', 'close'))

    def test_termination_observation_error_preserves_close_and_fails_closed(self):
        for initial, subsequent_poll, expected in (
                (False, 0, None), (None, 0, None), (True, 0, True),
                (False, None, True), (None, None, True), (True, None, True)):
            with self.subTest(initial=initial, subsequent_poll=subsequent_poll):
                transport = object.__new__(session._Transport)
                process = Mock()
                process.poll.side_effect = [OSError('observation failed'), subsequent_poll, 0]
                transport.process = process
                transport.job = Mock()
                transport.job.close.return_value = True
                transport.job_closed = False
                transport.termination_requested_while_alive = initial
                transport._terminate()
                transport.job.close.assert_called_once()
                self.assertTrue(transport.job_closed)
                self.assertIs(transport.termination_requested_while_alive, expected)
                self.assertEqual(process.kill.call_count, int(subsequent_poll is None))
                # A later observed-dead result must not erase unknown/True.
                transport._terminate()
                self.assertIs(transport.termination_requested_while_alive, expected)

        # A failure from the original post-close poll still propagates exactly
        # as before, after the existing close attempt has run. Metadata sampling
        # must not absorb or relocate that lifecycle error.
        transport = object.__new__(session._Transport)
        transport.process = Mock()
        transport.process.poll.side_effect = OSError('poll failed')
        transport.job = Mock()
        transport.job.close.return_value = True
        transport.job_closed = False
        transport.termination_requested_while_alive = False
        with self.assertRaises(OSError):
            transport._terminate()
        transport.job.close.assert_called_once()
        self.assertTrue(transport.job_closed)
        self.assertIsNone(transport.termination_requested_while_alive)

    def test_missing_trailer_and_blocked_pipe_have_independent_deadline(self):
        for blocked_write in (False, True):
            with self.subTest(blocked_write=blocked_write):
                self.process = FakeProcess(response=lambda *args: packet(*args)[:-1], blocked_write=blocked_write)
                with self.assertRaises(WgcError) as error:
                    self.capture.capture(self.target, self.rect, ROI)
                self.assertEqual(error.exception.status, 'timeout')
                self.assertTrue(self.capture._transport.ready_for_replacement.wait(2))
                self.assertGreater(self.process.kills, 0)

    def test_extra_reply_bytes_revoke_session(self):
        self.process = FakeProcess(response=lambda *args: packet(*args) + b'extra')
        with self.assertRaises(WgcError) as error:
            self.capture.capture(self.target, self.rect, ROI)
        self.assertEqual(error.exception.status, 'invalid-reply')
        self.wait_cleanup()

    def test_close_revokes_immediately_and_never_waits_on_calling_thread(self):
        self.process = FakeProcess(response=lambda *args: None, delayed_kill=True)
        outcome = []
        thread = threading.Thread(target=lambda: self._capture_error(outcome))
        thread.start()
        deadline = time.monotonic() + 1
        while self.capture._transport is None and time.monotonic() < deadline:
            time.sleep(.001)
        before = time.monotonic(); self.capture.close()
        self.assertLess(time.monotonic() - before, .1)
        thread.join(1); self.assertFalse(thread.is_alive())
        self.assertEqual(outcome, ['cancelled'])
        self.assertTrue(self.capture.cleanup_pending)
        self.process.exit()
        self.assertTrue(self.capture._transport.ready_for_replacement.wait(2))

    def test_stop_uses_the_same_immediate_close_cancellation_path(self):
        # close() above executes the real wrapper against fake process/Job I/O.
        # This binding is not evidence of Windows driver or Job teardown timing.
        self.assertIs(session.WgcSessionCapture.stop, session.WgcSessionCapture.close)

    def _capture_error(self, result):
        try:
            self.capture.capture(self.target, self.rect, ROI)
        except WgcError as error:
            result.append(error.status)

    def test_idle_parent_watchdog_kills_without_another_capture(self):
        self.capture.capture(self.target, self.rect, ROI)
        self.assertTrue(self.capture._transport.ready_for_replacement.wait(2))
        self.assertGreater(self.process.kills, 0)
        self.assertEqual(self.capture._transport.failure.status, 'timeout')

    def test_no_replacement_while_owned_process_cleanup_delayed(self):
        self.process = FakeProcess(response=lambda *args: None, delayed_kill=True)
        with self.assertRaises(WgcError):
            self.capture.capture(self.target, self.rect, ROI)
        with self.assertRaises(WgcError) as error:
            self.capture.capture(self.target, self.rect, ROI)
        self.assertEqual(error.exception.status, 'cleanup-pending')
        self.assertEqual(self.spawn.call_count, 1)
        self.process.exit(); self.wait_cleanup()

    def test_failed_job_close_blocks_replacement_even_after_child_exit(self):
        self.job.close.return_value = False
        self.capture.capture(self.target, self.rect, ROI)
        transport = self.capture._transport
        transport.revoke()
        time.sleep(.03)
        self.assertFalse(transport.ready_for_replacement.is_set())
        with self.assertRaises(WgcError) as error:
            self.capture.capture(self.target, self.rect, ROI)
        self.assertEqual(error.exception.status, 'cleanup-pending')
        self.job.close.return_value = True
        self.wait_cleanup()

    def test_assignment_failure_never_releases_start_gate(self):
        self.job.assign.side_effect = OSError('fixture job failure')
        with self.assertRaises(WgcError):
            self.capture.capture(self.target, self.rect, ROI)
        self.assertEqual(self.process.writes, [])
        self.wait_cleanup()

    def test_second_outstanding_request_rejected_without_replacement(self):
        self.process = FakeProcess(response=lambda *args: None)
        outcome = []; thread = threading.Thread(target=lambda: self._capture_error(outcome)); thread.start()
        deadline = time.monotonic() + 1
        while not self.process.writes and time.monotonic() < deadline:
            time.sleep(.001)
        with self.assertRaises(WgcError) as error:
            self.capture.capture(self.target, self.rect, ROI)
        self.assertEqual(error.exception.status, 'busy')
        self.capture.close(); thread.join(1); self.wait_cleanup()

    def test_target_or_geometry_change_cannot_retarget_instance(self):
        self.capture.capture(self.target, self.rect, ROI)
        for target, rect in ((WindowInfo(124, 77, 'owned', 'owned'), self.rect),
                             (self.target, ClientRect(-99, 20, 800, 600))):
            with self.assertRaises(WgcError) as error:
                self.capture.capture(target, rect, ROI)
            self.assertEqual(error.exception.status, 'stale')
        self.assertEqual(self.spawn.call_count, 1)
        self.assertTrue(self.capture._transport.revoked.is_set())
        self.wait_cleanup()

    def test_precancel_and_bad_expected_identity_never_launch(self):
        cancelled = threading.Event(); cancelled.set()
        with self.assertRaises(WgcError):
            self.capture.capture(self.target, self.rect, ROI, cancelled=cancelled)
        with self.assertRaises(WgcError):
            self.capture.capture(self.target, self.rect, ROI, expected_metadata=ProcessMetadata('other', 99))
        self.spawn.assert_not_called()

    def test_invalid_or_precancelled_call_revokes_existing_idle_helper(self):
        self.capture.capture(self.target, self.rect, ROI)
        transport = self.capture._transport
        cancelled = threading.Event(); cancelled.set()
        with self.assertRaises(WgcError) as error:
            self.capture.capture(self.target, self.rect, ROI, cancelled=cancelled)
        self.assertEqual(error.exception.status, 'cancelled')
        self.assertTrue(transport.revoked.is_set())
        self.wait_cleanup()

    def test_invalid_roi_revokes_existing_idle_helper(self):
        self.capture.capture(self.target, self.rect, ROI)
        transport = self.capture._transport
        with self.assertRaises(WgcError):
            self.capture.capture(self.target, self.rect, (-1, 0, 16, 16))
        self.assertTrue(transport.revoked.is_set())
        self.wait_cleanup()

    def test_watchdog_start_failure_never_launches_helper(self):
        original = threading.Thread.start
        def start(thread):
            if thread.name == 'wgc-session-lifetime':
                raise RuntimeError('fixture watchdog cannot start')
            return original(thread)
        with patch.object(threading.Thread, 'start', start), self.assertRaises(WgcError):
            self.capture.capture(self.target, self.rect, ROI)
        self.spawn.assert_not_called()

    def test_pipe_thread_start_failure_never_launches_helper(self):
        original = threading.Thread.start
        def start(thread):
            if thread.name == 'wgc-session-pipe':
                raise RuntimeError('fixture pipe thread cannot start')
            return original(thread)
        with patch.object(threading.Thread, 'start', start), self.assertRaises(WgcError):
            self.capture.capture(self.target, self.rect, ROI)
        self.spawn.assert_not_called()

    def test_stderr_start_failure_never_releases_gate_and_reaps(self):
        original = threading.Thread.start
        def start(thread):
            if thread.name == 'wgc-session-stderr':
                raise RuntimeError('fixture stderr thread cannot start')
            return original(thread)
        with patch.object(threading.Thread, 'start', start), self.assertRaises(WgcError):
            self.capture.capture(self.target, self.rect, ROI)
        self.assertEqual(self.process.writes, [])
        self.wait_cleanup()

    def test_registration_binds_parent_internally_and_is_immutable(self):
        with patch.object(session, '_register_owned_overlay') as register, patch.object(session, '_remove_owned_overlay'):
            self.capture.register_idle_overlay(456, session.REQUIRED_OVERLAY_STYLE, 987)
            register.assert_called_once_with(456, session.REQUIRED_OVERLAY_STYLE, 555, 99)
            for hwnd in (456, 457):
                with self.assertRaises(WgcError):
                    self.capture.register_idle_overlay(hwnd, session.REQUIRED_OVERLAY_STYLE, 988)
            self.capture.capture(self.target, self.rect, ROI)
            self.assertEqual(self.spawn.call_args.args[0][-4:], ['456', str(session.REQUIRED_OVERLAY_STYLE), '555', '7'])
            self.wait_cleanup()

    def test_same_ui_generation_in_new_instance_has_different_native_token(self):
        with patch.object(session, 'helper_directory', return_value=ROOT):
            second = session.WgcSessionCapture(experimental=True)
        with patch.object(session, '_register_owned_overlay') as register, \
             patch.object(session, '_remove_owned_overlay') as remove, \
             patch.object(session.secrets, 'randbits', side_effect=[111, 222]):
            self.capture.register_idle_overlay(456, session.REQUIRED_OVERLAY_STYLE, 1)
            # Model destruction/recreation with the same HWND value and UI generation.
            second.register_idle_overlay(456, session.REQUIRED_OVERLAY_STYLE, 1)
            self.assertEqual(register.call_args_list[0].args[2], 111)
            self.assertEqual(register.call_args_list[1].args[2], 222)
            self.capture.close(); second.close()
            self.assertEqual(remove.call_args_list[0].args, (456, 111, 99))
            self.assertEqual(remove.call_args_list[1].args, (456, 222, 99))

    def test_repeated_or_nonmonotonic_frame_rejected(self):
        self.process = FakeProcess(response=lambda *args: packet(*args))
        self.capture.capture(self.target, self.rect, ROI)
        with self.assertRaises(WgcError) as error:
            self.capture.capture(self.target, self.rect, ROI)
        self.assertEqual(error.exception.status, 'invalid-reply')
        self.wait_cleanup()


class WindowPropertyTests(unittest.TestCase):
    def api(self, *, owner=99, token=None):
        user = SimpleNamespace(IsWindow=Mock(return_value=True), GetAncestor=Mock(return_value=456),
            GetWindowLongPtrW=Mock(return_value=session.REQUIRED_OVERLAY_STYLE),
            SetPropW=Mock(return_value=True), GetPropW=Mock(return_value=token), RemovePropW=Mock())
        def get_pid(hwnd, output):
            ctypes.cast(output, ctypes.POINTER(ctypes.c_ulong)).contents.value = owner
            return 1
        def affinity(hwnd, output):
            ctypes.cast(output, ctypes.POINTER(ctypes.c_ulong)).contents.value = 0x11
            return 1
        user.GetWindowThreadProcessId = Mock(side_effect=get_pid)
        user.GetWindowDisplayAffinity = Mock(side_effect=affinity)
        return user

    def test_old_cleanup_never_removes_recreated_or_different_property(self):
        for owner, token in ((100, 987), (99, 988), (99, None)):
            user = self.api(owner=owner, token=token)
            with patch.object(session, '_window_api', return_value=user):
                session._remove_owned_overlay(456, 987, 99)
            user.RemovePropW.assert_not_called()
        user = self.api(owner=99, token=987)
        with patch.object(session, '_window_api', return_value=user):
            session._remove_owned_overlay(456, 987, 99)
        user.RemovePropW.assert_called_once_with(456, session._property_name(987))

    def test_registration_never_changes_foreign_window(self):
        user = self.api(owner=100)
        with patch.object(session, '_window_api', return_value=user), self.assertRaises(WgcError):
            session._register_owned_overlay(456, session.REQUIRED_OVERLAY_STYLE, 987, 99)
        user.SetPropW.assert_not_called()

    def test_registration_requires_full_style_and_exact_exclusion_affinity(self):
        for changed in ('style', 'affinity'):
            user = self.api()
            if changed == 'style':
                user.GetWindowLongPtrW.return_value = session.REQUIRED_OVERLAY_STYLE | 0x100
            else:
                def wrong(hwnd, output):
                    ctypes.cast(output, ctypes.POINTER(ctypes.c_ulong)).contents.value = 1
                    return 1
                user.GetWindowDisplayAffinity.side_effect = wrong
            with patch.object(session, '_window_api', return_value=user), self.assertRaises(WgcError):
                session._register_owned_overlay(456, session.REQUIRED_OVERLAY_STYLE, 987, 99)
            user.SetPropW.assert_not_called()


class NativeSourceParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.old = (ROOT / 'native/wgc_capture.cpp').read_text()
        cls.new = (ROOT / 'native/wgc_session_capture.cpp').read_text()

    def test_v1_target_geometry_and_protection_guard_parity(self):
        def target_body(text):
            start = text.index('    require(IsWindow(p.hwnd)')
            end = text.index('    ZOrder order{', start)
            return text[start:end]
        self.assertEqual(target_body(self.old), target_body(self.new))
        start, end = 'struct Geometry {', 'Input parse('
        self.assertEqual(self.old[self.old.index(start):self.old.index(end)],
                         self.new[self.new.index(start):self.new.index(end)])

    def test_native_struct_layout_and_immutable_startup(self):
        for name, size in (('Request', 56), ('Response', 64), ('Idle', 32)):
            self.assertIn(f'static_assert(sizeof({name}) == {size});', self.new)
        self.assertIn('argc == 15', self.new)
        self.assertIn('request.generation == p.generation', self.new)
        self.assertIn('request.id > last_id', self.new)
        self.assertIn('available == sizeof(Request)', self.new)

    def test_registered_overlay_hidden_at_every_strict_guard(self):
        validate = self.new[self.new.index('Geometry validate('):self.new.index('int64_t qpc_100ns(')]
        self.assertIn('validate_overlay(p);', validate)
        self.assertIn('if (!idle) require(!IsWindowVisible(p.overlay)', validate)
        self.assertIn('idle ? &p : nullptr', validate)
        # Explicit hidden check applies regardless of overlap, position or z-order.
        self.assertLess(validate.index('"overlay-hidden"'), validate.index('ZOrder order'))
        self.assertIn('scope.idle && hwnd == scope.idle->overlay', self.new)
        for check in ('overlay-owner', 'overlay-generation', 'overlay-style', 'overlay-affinity', 'overlay-support'):
            self.assertIn('"' + check + '"', self.new)
        self.assertIn('style == p.overlay_style', self.new)
        self.assertIn('affinity == 0x11', self.new)

    def test_no_readback_in_idle_and_strict_after_copy_before_idle_trailer(self):
        idle = self.new[self.new.index('while (true) {'):self.new.index('int64_t cutoff = qpc_100ns(true)')]
        self.assertNotIn('Map(', idle); self.assertNotIn('CopySubresourceRegion', idle)
        self.assertNotIn('pixels', idle)
        before = self.new[self.new.index('phase("validate-before-copy")'):self.new.index('phase("staging-copy")')]
        after = self.new[self.new.index('phase("validate-after-map")'):self.new.index('phase("copy-out")')]
        self.assertIn('validate(p, &geometry);', before)
        self.assertIn('validate(p, &geometry);', after)
        self.assertIn('frame_time > cutoff && frame_time > last_frame_time', self.new)
        self.assertIn('require(frame_time > 0, stale, "frame-timestamp");', self.new)
        self.assertIn('bool timestamp_ready = frame_time <= qpc_100ns(false, &diagnostic.clock);', self.new)
        self.assertIn('require(idle.entered >= frame_time, stale, "frame-timestamp");', self.new)
        self.assertIn('SecureZeroMemory(pixels.data(), pixels.size()); pixels.clear();', self.new)
        self.assertIn('~SensitivePixels()', self.new)

    def test_native_clock_uses_only_existing_samples_and_resets_on_phase_change(self):
        self.assertEqual(self.new.count('qpc_100ns('), 4)  # Definition, cutoff, each readiness check and idle.
        self.assertEqual(self.new.count('QueryPerformanceCounter('), 1)
        self.assertEqual(self.new.count('QueryPerformanceFrequency('), 1)
        self.assertEqual(self.new.count('frame_clock(cutoff, frame_time, previous_frame_time);'), 2)
        self.assertIn('int64_t previous_frame_time = last_frame_time;', self.new)
        phase = self.new[self.new.index('void phase('):self.new.index('void frame_clock(')]
        self.assertIn('diagnostic.clock = {};', phase)
        self.assertGreaterEqual(self.new.count('static_assert(qpc_ticks_100ns('), 8)

    def test_actual_cpp_system_module_pin_path_failure_and_before_capture_order(self):
        # Compile the actual pin function and its creation/start call sites.
        # Controlled OS stubs establish path, failure and lifetime ordering only;
        # they cannot prove which native module/thread caused the Windows crash.
        compiler = shutil.which('c++')
        if not compiler:
            self.skipTest('Portable C++ compiler absent; Windows module-lifetime evidence still required')
        pin = self.new[self.new.index('void pin_graphics_capture_module() {'):self.new.index('void run(Input const& p)')]
        failure = self.new[self.new.index('struct Failure {'):self.new.index('void report_failure(')]
        start = self.new.index('    auto pool = Direct3D11CaptureFramePool::CreateFreeThreaded(')
        create = self.new[start:self.new.index('    if (ApiInformation::IsPropertyPresent(', start)]
        start = self.new.index('    phase("session-start");')
        capture = self.new[start:self.new.index('    uint64_t last_id = 0;', start)]
        self.assertEqual(self.new.count('pin_graphics_capture_module();'), 1)
        self.assertIn('auto session = pool.CreateCaptureSession(item);', create)
        self.assertLess(create.index('pool.CreateCaptureSession(item)'), create.index('pin_graphics_capture_module();'))
        for forbidden in ('LoadLibrary(', 'LoadLibraryW(', 'LoadLibraryEx', 'FreeLibrary(',
                          'GetModuleHandleW(', 'GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS',
                          'GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT', 'Sleep(',
                          'ExitProcess(', 'TerminateProcess(', '__try', '__except'):
            self.assertNotIn(forbidden, pin)
        harness = r'''
#include <algorithm>
#include <cassert>
#include <cstdint>
#include <cwchar>
#include <string>
#include <vector>
using DWORD = uint32_t;
using UINT = uint32_t;
using HMODULE = void*;
constexpr UINT MAX_PATH = 260;
constexpr DWORD GET_MODULE_HANDLE_EX_FLAG_PIN = 1;
constexpr int stale = 12, failed = 14;
std::string scenario;
std::vector<std::string> calls;
std::wstring directory, exact_path;
bool factory_alive = false, item_alive = false, pool_alive = false,
     session_alive = false, pinned = false, started = false;
void before_capture() {
    assert(factory_alive && item_alive && pool_alive && session_alive && !started);
}
UINT GetSystemDirectoryW(wchar_t* out, UINT capacity) {
    before_capture(); calls.push_back("system-directory");
    assert(capacity == MAX_PATH);
    if (scenario == "directory-missing") return 0;
    if (scenario == "directory-truncated") return capacity;
    if (scenario == "directory-required") return capacity + 1;
    if (scenario == "directory-oversized") return UINT(-1);
    if (scenario == "directory-unterminated") {
        std::fill_n(out, capacity, L'x'); return capacity - 1;
    }
    assert(directory.size() < capacity);
    std::copy(directory.begin(), directory.end(), out);
    out[directory.size()] = L'\0';
    if (scenario == "directory-embedded-null") out[1] = L'\0';
    return UINT(directory.size());
}
bool GetModuleHandleExW(DWORD flags, wchar_t const* path, HMODULE* module) {
    before_capture(); calls.push_back("pin");
    assert(flags == GET_MODULE_HANDLE_EX_FLAG_PIN && std::wstring(path) == exact_path);
    assert(*module == nullptr);
    // No path search or module-load stub exists in this harness.
    if (scenario == "module-missing" || scenario == "pin-failed") return false;
    if (scenario != "pin-null-module") *module = reinterpret_cast<HMODULE>(1);
    pinned = *module != nullptr;
    return true;
}
''' + failure + pin + r'''
struct Factory {
    Factory() { factory_alive = true; calls.push_back("factory"); }
    ~Factory() { factory_alive = false; calls.push_back("factory-release"); }
};
struct Item {
    Item() { assert(factory_alive); item_alive = true; calls.push_back("item"); }
    ~Item() { item_alive = false; calls.push_back("item-release"); }
};
struct Session {
    Session() { assert(factory_alive && item_alive && pool_alive); session_alive = true; }
    ~Session() { session_alive = false; calls.push_back("session-release"); }
    void StartCapture() { before_capture(); assert(pinned); started = true; calls.push_back("start"); }
};
struct Pool {
    Pool() { assert(factory_alive && item_alive); pool_alive = true; calls.push_back("pool"); }
    ~Pool() { pool_alive = false; calls.push_back("pool-release"); }
    Session CreateCaptureSession(Item const&) { calls.push_back("session"); return {}; }
};
enum class DirectXPixelFormat { B8G8R8A8UIntNormalized };
struct Direct3D11CaptureFramePool {
    static Pool CreateFreeThreaded(int device, DirectXPixelFormat format, int count, int size) {
        assert(device == 11 && format == DirectXPixelFormat::B8G8R8A8UIntNormalized && count == 1 && size == 22);
        return {};
    }
};
void phase(char const* value) { assert(std::string(value) == "session-start"); }
void exercise_creation() {
    Factory factory; Item item;
    int runtime_device = 11, size = 22;
ACTUAL_CREATE
ACTUAL_START
}
int main() {
    for (char const* name : {"normal", "root", "longest-directory", "directory-missing",
            "directory-truncated", "directory-required", "directory-oversized",
            "directory-unterminated", "directory-embedded-null", "module-missing",
            "pin-failed", "pin-null-module"}) {
        scenario = name; calls.clear(); pinned = started = false;
        directory = scenario == "root" ? L"C:\\" : L"C:\\Windows\\System32";
        if (scenario == "longest-directory") directory = L"C:\\" + std::wstring(MAX_PATH - 4, L'x');
        exact_path = directory + (directory.back() == L'\\' ? L"" : L"\\") + L"GraphicsCapture.dll";
        bool expected_success = scenario == "normal" || scenario == "root" || scenario == "longest-directory";
        bool directory_failure = scenario.compare(0, 10, "directory-") == 0;
        bool rejected = false;
        try { exercise_creation(); }
        catch (Failure const& error) {
            rejected = true; assert(error.code == failed && std::string(error.check) == "capture-module-pin");
        }
        assert(rejected == !expected_success && started == expected_success);
        assert(!factory_alive && !item_alive && !pool_alive && !session_alive);
        std::vector<std::string> expected{"factory", "item", "pool", "session", "system-directory"};
        if (!directory_failure) expected.push_back("pin");
        if (expected_success) expected.push_back("start");
        for (char const* step : {"session-release", "pool-release", "item-release", "factory-release"})
            expected.push_back(step);
        assert(calls == expected);
    }
}
'''
        harness = harness.replace('ACTUAL_CREATE', create).replace('ACTUAL_START', capture)
        with tempfile.TemporaryDirectory() as directory:
            source, binary = Path(directory) / 'module_pin.cpp', Path(directory) / 'module_pin.exe'
            source.write_text(harness)
            built = subprocess.run([compiler, '-std=c++17', '-Wall', '-Wextra', str(source), '-o', str(binary)],
                                   capture_output=True, text=True, timeout=30)
            self.assertEqual(built.returncode, 0, built.stderr)
            ran = subprocess.run([str(binary)], capture_output=True, timeout=10)
            self.assertEqual(ran.returncode, 0, ran.stderr)

    def test_actual_cpp_shutdown_checkpoints_preserve_teardown_order_and_failure_exit(self):
        compiler = shutil.which('c++')
        if not compiler:
            self.skipTest('Portable C++ compiler absent; Windows shutdown evidence still required')
        checkpoint = self.new[self.new.index('enum class ShutdownStage :'):self.new.index('struct Handle {')]
        teardown = self.new[self.new.index('    phase("shutdown");'):self.new.index('\n}\n}\n\nint wmain(')]
        start = self.new.index('        run(p);')
        ending = self.new[start:self.new.index('        return 0;', start) + len('        return 0;')]
        for forbidden in ('Sleep(', 'SetUnhandledExceptionFilter', 'AddVectoredExceptionHandler',
                          '__try', '__except', 'ExitProcess(', 'TerminateProcess(', 'LoadLibrary'):
            self.assertNotIn(forbidden, checkpoint + teardown + ending)
        harness = r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#ifdef _WIN32
#include <fcntl.h>
#include <io.h>
#endif
using DWORD = uint32_t;
constexpr int STD_ERROR_HANDLE = -12;
int fail_at = 0, short_at = 0, writes = 0, operations = 0;
std::string written;
int GetStdHandle(int value) { assert(value == STD_ERROR_HANDLE); return value; }
bool WriteFile(int handle, void const* data, DWORD size, DWORD* count, void* overlapped) {
    assert(handle == STD_ERROR_HANDLE && size == 3 && overlapped == nullptr);
    assert(++writes <= 7);
    char const expected[]{'S', char('0' + writes), '\n'};
    assert(std::memcmp(data, expected, 3) == 0);
    *count = short_at == writes ? 1 : size;
    written.append(static_cast<char const*>(data), *count);
    return short_at != writes;
}
void phase(char const* value) { assert(std::strcmp(value, "shutdown") == 0); }
void operation(int index) {
    assert(writes == index && ++operations == index);
    if (fail_at == index) throw index;
}
struct LocalRelease {
    ~LocalRelease() noexcept(false) {
        // Early exception unwinding stays unchanged and emits no invented stage.
        if (!fail_at || fail_at >= 5) operation(5);
    }
};
struct Pool { void FrameArrived(int token) { assert(token == 11); operation(1); }
              void Close() { operation(4); } };
struct Item { void Closed(int token) { assert(token == 22); operation(2); } };
struct Session { void Close() { operation(3); } };
void uninit_apartment() { operation(6); }
''' + checkpoint + r'''
void run(int) {
    LocalRelease locals;
    Pool pool; Item item; Session session;
    int arrived = 11, closed = 22;
ACTUAL_TEARDOWN
}
int entry() {
    int p = 0;
ACTUAL_ENDING
}
int main(int argc, char** argv) {
#ifdef _WIN32
    assert(_setmode(_fileno(stdout), _O_BINARY) != -1);
#endif
    assert(argc == 3); fail_at = std::atoi(argv[1]); short_at = std::atoi(argv[2]);
    int result = 0;
    try { result = entry(); assert(fail_at == 0 && writes == 7 && operations == 6); }
    catch (int failure) {
        assert(failure == fail_at && writes == fail_at && operations == fail_at);
        result = 14;
    }
    assert(std::fwrite(written.data(), 1, written.size(), stdout) == written.size());
    return result;
}
'''
        harness = harness.replace('ACTUAL_TEARDOWN', teardown).replace('ACTUAL_ENDING', ending)
        with tempfile.TemporaryDirectory() as directory:
            source, binary = Path(directory) / 'shutdown.cpp', Path(directory) / 'shutdown.exe'
            source.write_text(harness)
            built = subprocess.run([compiler, '-std=c++17', '-Wall', '-Wextra', str(source), '-o', str(binary)],
                                   capture_output=True, text=True, timeout=30)
            self.assertEqual(built.returncode, 0, built.stderr)
            for failure in range(7):
                ran = subprocess.run([str(binary), str(failure), '0'], capture_output=True, timeout=10)
                self.assertEqual(ran.returncode, 14 if failure else 0, ran.stderr)
                self.assertEqual(ran.stdout, shutdown_trace(failure or 7))
                record = session.decode_session_shutdown_diagnostic(ran.stdout, ran.returncode)
                if failure:
                    self.assertEqual(record['checkpoints'], list(range(1, failure + 1)))
                    self.assertEqual(record['exit_code'], 14)
                    self.assertFalse(session.completed_native_shutdown(ran.stdout, ran.returncode))
                else:
                    self.assertIsNone(record)
                    self.assertTrue(session.completed_native_shutdown(ran.stdout, ran.returncode))
            for short in range(1, 8):
                ran = subprocess.run([str(binary), '0', str(short)], capture_output=True, timeout=10)
                self.assertEqual(ran.returncode, 0, ran.stderr)  # Write failure never changes native success.
                self.assertEqual(len(ran.stdout), 19)
                self.assertIsNone(session.decode_session_shutdown_diagnostic(ran.stdout, 3221225477))
                self.assertFalse(session.completed_native_shutdown(ran.stdout, ran.returncode))

    def test_actual_cpp_clock_sampling_arithmetic_and_worst_case_failure_size(self):
        # Execute the actual serializer, phase reset, QPC helper and predicates
        # with deterministic OS-call stubs. This is not Windows capture proof.
        compiler = shutil.which('c++')
        if not compiler:
            self.skipTest('Portable C++ compiler absent; native build still evaluates arithmetic static_asserts')
        metadata = self.new[self.new.index('struct ClockDiagnostic {'):self.new.index('struct SensitivePixels')]
        reporting = self.new[self.new.index('struct Failure {'):self.new.index('struct Handle {')]
        qpc = self.new[self.new.index('constexpr int64_t qpc_ticks_100ns('):self.new.index('void write_all(')]
        frame_guard = re.search(r'frame_clock\(cutoff, frame_time, previous_frame_time\);\s*'
                                r'require\(frame_time > 0[^;]+;\s*bool timestamp_ready[^;]+;', self.new).group()
        idle_guard = re.search(r'frame_clock\(cutoff, frame_time, previous_frame_time\);\s*'
                               r'Idle idle[^;]+;\s*require\(idle.entered[^;]+;', self.new).group()
        idle_start = self.new.index('struct Idle {')
        idle_struct = self.new[idle_start:self.new.index('};', idle_start) + 2]
        harness = r'''
#include <algorithm>
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <string>
#ifdef _WIN32
#include <fcntl.h>
#include <io.h>
#endif
constexpr int stale = 12, failed = 14, STD_ERROR_HANDLE = -12;
using DWORD = uint32_t;
struct LARGE_INTEGER { int64_t QuadPart; };
int counter_calls = 0, frequency_calls = 0;
int64_t ticks = 10000002, frequency = 10000000;
bool QueryPerformanceCounter(LARGE_INTEGER* out) { ++counter_calls; out->QuadPart = ticks; return true; }
bool QueryPerformanceFrequency(LARGE_INTEGER* out) { ++frequency_calls; out->QuadPart = frequency; return true; }
int GetStdHandle(int value) { return value; }
std::string written;
bool WriteFile(int, void const* data, DWORD size, DWORD* count, void*) {
    written.assign(static_cast<char const*>(data), size);
    *count = size;
    return std::fwrite(data, 1, size, stdout) == size;
}
''' + metadata + reporting + qpc + idle_struct + r'''
int main() {
#ifdef _WIN32
    // Match native WriteFile: CRT text-mode LF expansion would distort bounds.
    assert(_setmode(_fileno(stdout), _O_BINARY) != -1);
#endif
    int64_t cutoff = 10000000, frame_time = -1, previous_frame_time = 9999999;
    phase("frame-wait");
    try { FRAME_GUARD (void)timestamp_ready; assert(false); }
    catch (Failure const& error) {
        assert(error.code == stale && std::strcmp(error.check, "frame-timestamp") == 0);
        assert(counter_calls == 0 && frequency_calls == 0);
        assert(diagnostic.clock.qpc_counter == 0 && diagnostic.clock.qpc_frequency == 0 &&
               diagnostic.clock.observed_now_100ns == 0);
        report_failure(error.code, error.check);
    }
    phase("frame-wait");
    frame_time = 10000003;
    {   // A future timestamp is unready, not an immediate failure or success.
        FRAME_GUARD
        assert(!timestamp_ready);
        assert(counter_calls == 1 && frequency_calls == 1);
        assert(diagnostic.clock.qpc_counter == ticks && diagnostic.clock.qpc_frequency == frequency &&
               diagnostic.clock.observed_now_100ns == 10000002);
    }
    ticks = frame_time;
    { FRAME_GUARD assert(timestamp_ready); }
    assert(counter_calls == 2 && frequency_calls == 2);
    ticks = 10000002;
    phase("validate-idle");
    struct { uint64_t id; } request{1};
    struct { uint64_t generation; } p{7};
    try { IDLE_GUARD assert(false); }
    catch (Failure const& error) {
        assert(error.code == stale && std::strcmp(error.check, "frame-timestamp") == 0);
        assert(counter_calls == 3 && frequency_calls == 3);
        assert(diagnostic.clock.previous_frame_100ns == previous_frame_time);
        report_failure(error.code, error.check);
    }
    phase("validate-idle");
    assert(!diagnostic.clock.present && diagnostic.clock.qpc_counter == 0 &&
           diagnostic.clock.qpc_frequency == 0 && diagnostic.clock.cutoff_100ns == 0 &&
           diagnostic.clock.frame_100ns == 0 && diagnostic.clock.observed_now_100ns == 0 &&
           diagnostic.clock.previous_frame_100ns == 0);
    report_failure(stale, "frame-timestamp");
    diagnostic.clock = {true, INT64_MIN, INT64_MIN, INT64_MIN, INT64_MIN, INT64_MIN, INT64_MIN};
    diagnostic.style = diagnostic.extended_style = UINT32_MAX;
    for (auto rect : {diagnostic.observed, diagnostic.expected, diagnostic.window_rect, diagnostic.frame_rect})
        std::fill_n(rect, 4, -(int64_t(1) << 32));
    report_failure(stale, "frame-timestamp", UINT32_MAX);
    assert(written.size() == 637 && written.size() < 1024);
    for (auto rect : {diagnostic.observed, diagnostic.expected, diagnostic.window_rect, diagnostic.frame_rect})
        std::fill_n(rect, 4, INT64_MIN);
    report_failure(stale, "frame-timestamp", UINT32_MAX);
    assert(written.size() == 781 && written.size() < 1024);
    // Clock evidence is never attached to another check, phase or return code.
    report_failure(failed, "qpc-clock");
    report_failure(stale, "invariant");
    report_failure(failed, "frame-timestamp");
    diagnostic.phase = "startup";
    report_failure(stale, "frame-timestamp");
}
'''
        harness = harness.replace('FRAME_GUARD', frame_guard).replace('IDLE_GUARD', idle_guard)
        with tempfile.TemporaryDirectory() as directory:
            source, binary = Path(directory) / 'clock.cpp', Path(directory) / 'clock.exe'
            source.write_text(harness)
            built = subprocess.run([compiler, '-std=c++17', '-Wall', '-Wextra', str(source), '-o', str(binary)],
                                   capture_output=True, text=True, timeout=30)
            self.assertEqual(built.returncode, 0, built.stderr)
            ran = subprocess.run([str(binary)], capture_output=True, timeout=10)
            self.assertEqual(ran.returncode, 0, ran.stderr)
        rows = ran.stdout.splitlines(keepends=True)
        self.assertEqual(len(rows), 9)
        for row in rows:
            self.assertLess(len(row), 1024)
        records = [json.loads(row) for row in rows]
        self.assertEqual(records[0]['clock'], dict(qpc_counter=0, qpc_frequency=0, cutoff_100ns=10000000,
                         frame_100ns=-1, observed_now_100ns=0, previous_frame_100ns=9999999))
        self.assertEqual(records[1]['clock']['frame_100ns'], 10000003)
        self.assertEqual(records[1]['phase'], 'validate-idle')
        for index in (0, 1, 2, 3):
            self.assertEqual(session.decode_session_diagnostic(rows[index], 12), records[index])
        self.assertEqual(len(rows[3]), 637)  # All allowed numeric fields at longest-width bounds.
        self.assertEqual(len(rows[4]), 781)  # Even every native int64 slot at its longest width fits.
        self.assertEqual(len(rows[4]) + len(shutdown_trace()), 802)
        self.assertLessEqual(len(rows[4]) + len(shutdown_trace()), session.MAX_DIAGNOSTIC_BYTES)
        self.assertIsNone(session.decode_session_diagnostic(rows[4], 12))  # Geometry stays v1-bounded.
        for index in (2, 5, 6, 7, 8):
            self.assertNotIn('clock', records[index])

    def test_actual_cpp_readiness_loop_and_strict_guards(self):
        # Compile the production loop, validators and geometry/clock predicates.
        # Win32/WGC calls below are controlled stubs, not Windows pixel, Stop,
        # scheduler or cleanup evidence. The readback sentinel only proves that
        # the extracted loop's success barrier was (or was not) crossed.
        compiler = shutil.which('c++')
        if not compiler:
            self.skipTest('Portable C++ compiler absent; Windows readiness evidence still required')
        metadata = self.new[self.new.index('struct ClockDiagnostic {'):self.new.index('struct SensitivePixels')]
        failure = self.new[self.new.index('struct Failure {'):self.new.index('void report_failure(')]
        handles = self.new[self.new.index('struct Handle {'):self.new.index('// No ROI is supplied')]
        inputs = self.new[self.new.index('constexpr DWORD watchdog_ms'):self.new.index('#pragma pack(push, 1)')]
        geometry = self.new[self.new.index('struct Geometry {'):self.new.index('int64_t number(')]
        guards = self.new[self.new.index('uint64_t creation_time('):self.new.index('constexpr int64_t qpc_ticks_100ns(')]
        qpc = self.new[self.new.index('constexpr int64_t qpc_ticks_100ns('):self.new.index('void write_all(')]
        loop = self.new[self.new.index('        auto deadline = GetTickCount64() + request.wait_ms;'):
                        self.new.index('        phase("frame-size");')]
        self.assertIn('if (!frame) frame = pool.TryGetNextFrame();', loop)
        self.assertIn('require(frame_ready && GetTickCount64() < deadline, timed_out, "frame-deadline");', loop)
        for forbidden in ('Surface(', 'CreateTexture2D(', 'CopySubresourceRegion(', 'Map(',
                          'write_all(', 'lease =', 'cutoff =', 'last_frame_time ='):
            self.assertNotIn(forbidden, loop)
        harness = r"""
#include <algorithm>
#include <atomic>
#include <cassert>
#include <cstdint>
#include <cstring>
#include <memory>
#include <string>
#include <vector>
#define CALLBACK
using DWORD = uint32_t;
using BOOL = int;
using HANDLE = void*;
using HWND = void*;
using LPARAM = intptr_t;
struct RECT { int32_t left, top, right, bottom; };
struct POINT { int32_t x, y; };
struct FILETIME { uint32_t dwLowDateTime, dwHighDateTime; };
struct LARGE_INTEGER { int64_t QuadPart; };
struct MONITORINFO { DWORD cbSize; RECT rcMonitor; };
constexpr int stale = 12, timed_out = 11, protected_content = 13, failed = 14;
constexpr uint64_t pixel_budget = 16000000;
constexpr int FALSE = 0, TRUE = 1, WAIT_TIMEOUT = 258, PROCESS_QUERY_LIMITED_INFORMATION = 4096;
constexpr int GA_ROOT = 2, GWL_STYLE = -16, GWL_EXSTYLE = -20;
constexpr int DWMWA_CLOAKED = 14, DWMWA_EXTENDED_FRAME_BOUNDS = 9, MONITOR_DEFAULTTONULL = 0;
constexpr uint32_t WS_EX_LAYERED = 0x80000, WS_EX_NOACTIVATE = 0x8000000,
    WS_EX_TOOLWINDOW = 0x80, WS_EX_TOPMOST = 8, WS_EX_TRANSPARENT = 0x20;
HANDLE const INVALID_HANDLE_VALUE = reinterpret_cast<HANDLE>(intptr_t(-1));
HWND const target_hwnd = reinterpret_cast<HWND>(1), overlay_hwnd = reinterpret_cast<HWND>(2),
    occluder_hwnd = reinterpret_cast<HWND>(3);
HANDLE const parent_handle = reinterpret_cast<HANDLE>(4), event_handle = reinterpret_cast<HANDLE>(5);
std::string scenario;
uint64_t elapsed_ms = 0;
int waits = 0, validation_calls = 0, counter_calls = 0, frequency_calls = 0,
    frame_reads = 0, pool_calls = 0, content_calls = 0, frame_closes = 0,
    live_frames = 0, readback_entries = 0;
int64_t initial_now = 200;
std::vector<DWORD> waited;
std::vector<uint64_t> validated_at;
bool changed(char const* name) { return waits > 0 && scenario == name; }
bool SUCCEEDED(int result) { return result >= 0; }
bool CloseHandle(HANDLE) { return true; }
HANDLE CreateEventW(void*, BOOL, BOOL, void*) { return event_handle; }
DWORD WaitForSingleObject(HANDLE, DWORD);
uint64_t GetTickCount64() {
    if (scenario == "deadline-final" && counter_calls == 2) elapsed_ms = 60;
    return elapsed_ms;
}
bool QueryPerformanceCounter(LARGE_INTEGER* out) {
    ++counter_calls;
    out->QuadPart = initial_now + int64_t(elapsed_ms) * 10000;
    return true;
}
bool QueryPerformanceFrequency(LARGE_INTEGER* out) {
    ++frequency_calls; out->QuadPart = 10000000; return true;
}
HANDLE OpenProcess(DWORD access, BOOL, DWORD pid) {
    assert(access == PROCESS_QUERY_LIMITED_INFORMATION && pid == 77);
    return target_hwnd;
}
BOOL GetProcessTimes(HANDLE handle, FILETIME* created, FILETIME*, FILETIME*, FILETIME*) {
    created->dwHighDateTime = 0;
    created->dwLowDateTime = handle == parent_handle ? 200000 :
        (changed("process-created") ? 100001 : 100000);
    return TRUE;
}
struct ApiInformation {
    static bool IsApiContractPresent(wchar_t const*, int version) {
        assert(version == 10); return !changed("overlay-support");
    }
};
int DwmIsCompositionEnabled(BOOL* out) { *out = TRUE; return 0; }
BOOL IsWindow(HWND hwnd) {
    return !((hwnd == target_hwnd && changed("window-visible")) ||
             (hwnd == overlay_hwnd && changed("overlay-owner")));
}
BOOL IsWindowVisible(HWND hwnd) {
    if (hwnd == overlay_hwnd) return changed("overlay-hidden");
    if (hwnd == occluder_hwnd) return changed("occluder-overlap");
    return TRUE;
}
BOOL IsIconic(HWND hwnd) { return hwnd == target_hwnd && changed("minimized"); }
HWND GetAncestor(HWND hwnd, int flag) { assert(flag == GA_ROOT); return hwnd; }
HWND GetForegroundWindow() { return changed("foreground-root") ? overlay_hwnd : target_hwnd; }
DWORD GetWindowThreadProcessId(HWND hwnd, DWORD* out) {
    *out = hwnd == target_hwnd ? (changed("window-process") ? 78 : 77) : 99; return 1;
}
HANDLE GetPropW(HWND hwnd, wchar_t const* name) {
    assert(hwnd == overlay_hwnd && std::wstring(name) == L"VGA.WGC.SessionV2.Overlay.555");
    return reinterpret_cast<HANDLE>(changed("overlay-generation") ? 556 : 555);
}
intptr_t GetWindowLongPtrW(HWND hwnd, int field) {
    if (hwnd != overlay_hwnd || field != GWL_EXSTYLE) return 0;
    return WS_EX_LAYERED | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW | WS_EX_TOPMOST |
        (changed("overlay-style") ? 0 : WS_EX_TRANSPARENT);
}
BOOL GetWindowDisplayAffinity(HWND hwnd, DWORD* out) {
    *out = hwnd == overlay_hwnd ? (changed("overlay-affinity") ? 1 : 0x11) :
        (changed("display-affinity") ? 1 : 0); return TRUE;
}
BOOL GetClientRect(HWND, RECT* out) { *out = {0, 0, 320, 240}; return TRUE; }
BOOL ClientToScreen(HWND, POINT* out) {
    *out = {changed("client-geometry") ? 9 : 8, 31}; return TRUE;
}
int DwmGetWindowAttribute(HWND, int attribute, void* out, size_t) {
    if (attribute == DWMWA_CLOAKED) *static_cast<DWORD*>(out) = changed("window-uncloaked") ? 1 : 0;
    else { assert(attribute == DWMWA_EXTENDED_FRAME_BOUNDS); *static_cast<RECT*>(out) = {7, 0, 329, 272}; }
    return 0;
}
BOOL GetWindowRect(HWND hwnd, RECT* out) {
    *out = hwnd == target_hwnd ? RECT{0, 0, changed("geometry-stable") ? 337 : 336, 279} :
        RECT{20, 40, 50, 70}; return TRUE;
}
HANDLE MonitorFromRect(RECT*, int) { return target_hwnd; }
BOOL GetMonitorInfoW(HANDLE, MONITORINFO* out) {
    out->rcMonitor = {changed("client-on-monitor") ? 100 : 0, 0, 1000, 1000}; return TRUE;
}
BOOL EnumWindows(BOOL (*callback)(HWND, LPARAM), LPARAM argument) {
    if (callback(occluder_hwnd, argument)) callback(target_hwnd, argument); return TRUE;
}
""" + metadata + failure + handles + inputs + geometry + r"""
CaptureSignal* active_signal = nullptr;
struct ParentCancelled {};
DWORD WaitForSingleObject(HANDLE handle, DWORD duration) {
    if (handle == parent_handle) {
        assert(duration == 0);
        ++validation_calls; validated_at.push_back(elapsed_ms);
        if (changed("deadline-validation")) elapsed_ms = 60;
        return changed("parent-lifetime") ? 0 : WAIT_TIMEOUT;
    }
    assert(handle == event_handle && duration > 0 && duration <= watchdog_ms);
    assert(elapsed_ms < 60 && duration <= 60 - elapsed_ms);
    assert(readback_entries == 0 && live_frames <= 1);
    ++waits; waited.push_back(duration); elapsed_ms += duration;
    if (scenario == "closed") active_signal->closed.store(true);
    // Simulate the parent's out-of-process cancellation. The native capture
    // loop does not consume a pipelined Stop command, and this is not Job proof.
    if (scenario == "parent-cancel") throw ParentCancelled{};
    return WAIT_TIMEOUT;
}
""" + guards + qpc + r"""
struct Size { int Width, Height; };
struct Candidate { int64_t timestamp; Size content{322, 272}; };
struct FrameData {
    Candidate candidate;
    explicit FrameData(Candidate value) : candidate(value) { assert(++live_frames == 1); }
    ~FrameData() { --live_frames; }
};
struct Direct3D11CaptureFrame {
    std::shared_ptr<FrameData> data;
    Direct3D11CaptureFrame(std::nullptr_t) {}
    explicit Direct3D11CaptureFrame(Candidate candidate) : data(std::make_shared<FrameData>(candidate)) {}
    explicit operator bool() const { return bool(data); }
    struct Time { int64_t value; int64_t count() const { return value; } };
    Time SystemRelativeTime() const { ++frame_reads; return {data->candidate.timestamp}; }
    Size ContentSize() const {
        ++content_calls;
        if (scenario == "deadline-content" && content_calls == 2) elapsed_ms = 60;
        return data->candidate.content;
    }
    void Close() { assert(data); ++frame_closes; data.reset(); }
    Direct3D11CaptureFrame& operator=(std::nullptr_t) { data.reset(); return *this; }
};
struct Pool {
    std::vector<Candidate> queued;
    Direct3D11CaptureFrame TryGetNextFrame() {
        assert(live_frames == 0); ++pool_calls;
        if (queued.empty()) return Direct3D11CaptureFrame{nullptr};
        auto value = queued.front(); queued.erase(queued.begin());
        return Direct3D11CaptureFrame{value};
    }
};
int main(int argc, char** argv) {
    assert(argc == 2); scenario = argv[1];
    Input p{target_hwnd, 77, 100000, 8, 31, 320, 240, 99, 200000, overlay_hwnd,
            required_overlay_style, 555, 7, parent_handle};
    Geometry geometry{{7, 0, 329, 272}, {0, 0, 336, 279}, {8, 31}, {0, 0, 320, 240}};
    Size size{336, 279};
    auto signal = std::make_shared<CaptureSignal>(); active_signal = signal.get();
    struct { uint32_t wait_ms; } request{60};
    int64_t cutoff = 100, last_frame_time = 90, previous_frame_time = last_frame_time;
    Pool pool{{Candidate{250200}}}; // Strict equality with now at the second check.
    if (scenario == "ready-now") pool.queued = {Candidate{200}};
    if (scenario == "one-tick-future") pool.queued = {Candidate{201}};
    if (scenario == "two-waits") pool.queued = {Candidate{500200}};
    if (scenario == "persistent-future") pool.queued = {Candidate{1000000000}};
    if (scenario == "ready-at-deadline") pool.queued = {Candidate{600200}};
    if (scenario == "no-frame") pool.queued.clear();
    if (scenario == "zero") pool.queued = {Candidate{0}};
    if (scenario == "negative") pool.queued = {Candidate{-1}};
    if (scenario == "stale") pool.queued = {Candidate{100}, Candidate{500200}};
    if (scenario == "stale-only") pool.queued = {Candidate{100}};
    if (scenario == "duplicate") {
        last_frame_time = previous_frame_time = 300;
        pool.queued = {Candidate{300}, Candidate{500200}};
    }
    if (scenario == "duplicate-only") {
        last_frame_time = previous_frame_time = 300;
        pool.queued = {Candidate{300}};
    }
    if (scenario == "bad-content") pool.queued = {Candidate{250200, {321, 272}}, Candidate{500200}};
    if (scenario == "clipped-content") { size = {322, 272}; pool.queued = {Candidate{250200, {336, 279}}}; }
    if (scenario == "run32-values") {
        initial_now = 24076885278; cutoff = 24076721565;
        last_frame_time = previous_frame_time = 24071250000;
        pool.queued = {Candidate{24077031250}};
    }
    auto const original_cutoff = cutoff, original_previous = previous_frame_time;
    int failure_code = 0; std::string failure_check;
    try {
ACTUAL_LOOP
        ++readback_entries;
        assert(frame_ready && frame && elapsed_ms < 60);
        assert(frame_time > cutoff && frame_time > last_frame_time);
        assert(frame_time <= diagnostic.clock.observed_now_100ns);
        assert(same(capture_bounds, geometry.frame));
    } catch (Failure const& error) {
        failure_code = error.code; failure_check = error.check;
    } catch (ParentCancelled const&) { failure_check = "parent-cancel"; }
    assert(cutoff == original_cutoff && previous_frame_time == original_previous &&
           last_frame_time == original_previous);
    assert(live_frames == 0); // Retained candidate is released on every exit.
    assert(frequency_calls == counter_calls);
    assert(counter_calls == frame_reads - ((scenario == "zero" || scenario == "negative") ? 1 : 0));
    if (diagnostic.clock.present) {
        assert(diagnostic.clock.cutoff_100ns == original_cutoff);
        assert(diagnostic.clock.previous_frame_100ns == original_previous);
    }
    if (scenario == "ready-now") {
        assert(readback_entries == 1 && waits == 0 && validation_calls == 1 && counter_calls == 1);
    } else if (scenario == "future-ready" || scenario == "one-tick-future" || scenario == "run32-values") {
        assert(readback_entries == 1 && waits == 1 && validation_calls == 2 && counter_calls == 2);
        assert(pool_calls == 1 && frame_closes == 0);
    } else if (scenario == "two-waits") {
        assert(readback_entries == 1 && waits == 2 && validation_calls == 3 && counter_calls == 3);
        assert(pool_calls == 1 && frame_closes == 0);
    } else if (scenario == "persistent-future" || scenario == "ready-at-deadline" || scenario == "no-frame") {
        assert(readback_entries == 0 && failure_code == timed_out && failure_check == "frame-deadline");
        assert(elapsed_ms == 60 && waited == std::vector<DWORD>({25, 25, 10}));
        assert(validation_calls == 3 && validated_at == std::vector<uint64_t>({0, 25, 50}));
        assert(pool_calls == (scenario == "no-frame" ? 3 : 1));
        assert(counter_calls == (scenario == "no-frame" ? 0 : 3));
    } else if (scenario == "stale-only" || scenario == "duplicate-only") {
        assert(readback_entries == 0 && failure_code == timed_out && failure_check == "frame-deadline");
        assert(elapsed_ms == 60 && waited == std::vector<DWORD>({25, 25, 10}));
        assert(validation_calls == 3 && counter_calls == 1 && pool_calls == 3 && frame_closes == 1);
    } else if (scenario == "zero" || scenario == "negative") {
        assert(readback_entries == 0 && failure_code == stale && failure_check == "frame-timestamp");
        assert(counter_calls == 0 && waits == 0);
    } else if (scenario == "stale" || scenario == "duplicate" || scenario == "bad-content") {
        assert(readback_entries == 1 && waits == 2 && validation_calls == 3 && counter_calls == 3);
        assert(pool_calls == 2 && frame_closes == 1);
    } else if (scenario == "clipped-content") {
        assert(readback_entries == 0 && failure_code == stale && failure_check == "content-in-pool");
        assert(waits == 0 && pool_calls == 1);
    } else if (scenario == "deadline-validation" || scenario == "deadline-content" || scenario == "deadline-final") {
        assert(readback_entries == 0 && failure_code == timed_out && failure_check == "frame-deadline");
        assert(elapsed_ms == 60 && waits == 1 && pool_calls == 1 && counter_calls == 2);
    } else if (scenario == "closed" || scenario == "parent-cancel") {
        assert(readback_entries == 0 && waits == 1 && counter_calls == 1 && validation_calls == 1);
        assert(failure_check == (scenario == "closed" ? "item-open" : "parent-cancel"));
    } else {
        assert(readback_entries == 0 && waits == 1 && pool_calls == 1 && validation_calls == 2 && counter_calls == 1);
        assert(failure_code == (scenario == "display-affinity" ? protected_content : stale));
        assert(failure_check == (scenario == "minimized" ? "window-visible" : scenario));
    }
}
"""
        harness = harness.replace('ACTUAL_LOOP', loop)
        cases = ('ready-now', 'future-ready', 'one-tick-future', 'two-waits', 'run32-values',
                 'persistent-future', 'ready-at-deadline', 'no-frame', 'zero', 'negative',
                 'stale', 'stale-only', 'duplicate', 'duplicate-only', 'bad-content', 'clipped-content',
                 'deadline-validation', 'deadline-content', 'deadline-final', 'closed', 'parent-cancel',
                 'parent-lifetime', 'overlay-support', 'overlay-owner', 'overlay-generation', 'overlay-style',
                 'overlay-affinity', 'overlay-hidden', 'window-visible', 'minimized', 'foreground-root',
                 'window-process', 'process-created', 'window-uncloaked', 'display-affinity', 'client-geometry',
                 'geometry-stable', 'client-on-monitor', 'occluder-overlap')
        with tempfile.TemporaryDirectory() as directory:
            source, binary = Path(directory) / 'readiness.cpp', Path(directory) / 'readiness.exe'
            source.write_text(harness)
            built = subprocess.run([compiler, '-std=c++17', '-Wall', '-Wextra', str(source), '-o', str(binary)],
                                   capture_output=True, text=True, timeout=30)
            self.assertEqual(built.returncode, 0, built.stderr)
            for case in cases:
                with self.subTest(case=case):
                    ran = subprocess.run([str(binary), case], capture_output=True, timeout=10)
                    self.assertEqual(ran.returncode, 0, ran.stderr)
                    self.assertEqual(ran.stdout, b'')

    def test_no_monitor_item_injection_or_border_suppression(self):
        for forbidden in ('CreateForMonitor(', 'SetWindowsHookEx', 'ReadProcessMemory',
                          'WriteProcessMemory', 'IsBorderRequired(', 'RequestAccessAsync(',
                          'SetWindowDisplayAffinity('):
            self.assertNotIn(forbidden, self.new)
        self.assertIn('factory->CreateForWindow(p.hwnd', self.new)
        self.assertIn('PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE', self.new)
        self.assertIn('watchdog_ms = 25, idle_lease_ms = 4000', self.new)

    def test_production_does_not_import_experiment(self):
        for path in (ROOT / 'native_ui.py', ROOT / 'screen_capture.py', ROOT / 'wgc_capture.py'):
            self.assertNotIn('wgc_session_capture', path.read_text())


if __name__ == '__main__':
    unittest.main()

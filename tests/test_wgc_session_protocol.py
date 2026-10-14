"""Portable experiment tests only; fakes are NOT Windows/pixel/lifecycle proof."""
from contextlib import ExitStack
import ctypes
import hashlib
import json
from pathlib import Path
import re
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
from wgc_capture import WgcError, WgcUnavailable

ROOT = Path(__file__).resolve().parents[1]
ROI = (5, 7, 16, 16)
PIXELS = bytes([17, 23, 29, 255]) * (16 * 16)


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
        self.wait_cleanup()

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
        self.assertIn('frame_time <= qpc_100ns()', self.new)
        self.assertIn('SecureZeroMemory(pixels.data(), pixels.size()); pixels.clear();', self.new)
        self.assertIn('~SensitivePixels()', self.new)

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

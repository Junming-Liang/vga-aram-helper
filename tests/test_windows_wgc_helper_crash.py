"""Portable crash-diagnostic safety tests, NOT Windows capture acceptance.

The pipe regression drives the unchanged production Python transport. Remaining
tests exercise bounded launcher contracts with owned, synthetic objects only.
No test attaches a debugger, runs a native helper, or captures desktop pixels.
"""
from __future__ import annotations

from contextlib import redirect_stdout
import copy
import hashlib
import io
import json
from pathlib import Path
import queue
import re
import sys
import tempfile
import threading
import time
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from tests import test_wgc_session_failure_evidence as failure_fixtures
from tests import windows_native_smoke as gate
from persistent_capture_adapter import PersistentCaptureAdapter, OverlayRegistration, _SessionOwner
from screen_capture import Win32Capture, ClientRect, WindowInfo
from session_windows import ProcessMetadata
import wgc_session_capture as session


ROOT = Path(__file__).resolve().parents[1]


class OwnedStateFixture:
    """Real production state types, with no constructor that starts OS work."""

    def __init__(self, directory):
        self.now = time.monotonic()
        self.helper = Path(directory) / "owned-session-helper.exe"
        self.helper.write_bytes(b"synthetic test bytes, not executable")
        self.process = SimpleNamespace(pid=4321, _handle=9876, poll=Mock(return_value=None))
        self.job = SimpleNamespace(handle=5555)
        self.identity = dict(pid=4321, created=112233, path=str(self.helper.resolve()),
                             sha256=hashlib.sha256(self.helper.read_bytes()).hexdigest())
        self.identity_reader = Mock(side_effect=lambda process, job, expected_path:
                                    dict(self.identity))

        self.transport = session._Transport.__new__(session._Transport)
        self.transport.args = [str(self.helper), "--session-v2"]
        self.transport.generation = 123
        self.transport.process = self.process
        self.transport.job = self.job
        self.transport.revoked = threading.Event()
        self.transport.ready_for_replacement = threading.Event()
        self.transport.io_done = threading.Event()
        self.transport.stderr_done = threading.Event()
        self.transport.lock = threading.Lock()
        self.transport.requests = queue.Queue(maxsize=1)
        self.transport.request_deadline = None
        self.transport.idle_deadline = self.now + .7
        self.transport.failure = None
        self.transport._active = None
        self.transport.job_closed = False
        self.transport.termination_requested_while_alive = False

        self.session = session.WgcSessionCapture.__new__(session.WgcSessionCapture)
        self.session._allow_visible_overlay = False
        self.session.helper_path = self.helper
        self.session._state = threading.Lock()
        self.session._capture_lock = threading.Lock()
        self.session._closed = False
        self.session._transport = self.transport
        self.session._request_id = 7
        self.session._last_frame = 101
        self.session._overlay = (91, 0x80020, 456)
        self.session._overlay_generation = 89
        self.session._parent = (5678, 991122)
        self.session._binding = (34, 56, 7890, 0, 0, 960, 600)
        self.session.last_timing = dict(request_cutoff_100ns=100, frame_100ns=101,
                                        idle_enter_100ns=102, request_id=7,
                                        session_generation=123)
        self.adapter = PersistentCaptureAdapter(Mock(), allow_visible_overlay=False)
        self.adapter._overlay = OverlayRegistration(91, 0x80020, 89)
        self.target = WindowInfo(34, 56, "owned synthetic fixture", "OwnedFixtureClass")
        self.rect = ClientRect(0, 0, 960, 600)
        binding = (self.target.identity, ProcessMetadata("C:\\owned\\python.exe", 7890),
                   self.rect, self.adapter._overlay, False)
        self.owner = _SessionOwner(binding, session=self.session)
        self.owner.setup_done.set()
        self.owner.call_done.set()
        self.adapter._owner = self.owner
        self.adapter._persistent_required = True
        self.adapter._last_request_at = self.now - 3.3
        self.receipt = dict(self.session.last_timing, helper_pid=4321,
                            helper_created=112233, overlay_hwnd=91,
                            overlay_extended_style=0x80020, overlay_affinity=0x11,
                            overlay_registration_valid=True)
        self.adapter._last_receipt = dict(self.receipt)
        self.capture = Win32Capture.__new__(Win32Capture)
        self.capture._persistent = self.adapter
        self.capture._capture_lock = threading.Lock()
        self.capture._last_session_receipt = dict(self.receipt)
        self.capture._last_session_epoch = self.adapter.epoch
        self.capture._wgc = SimpleNamespace(_pending_cleanup=None, _pending_job=None)


class OriginalFailurePreservationTests(unittest.TestCase):
    fixture = failure_fixtures.ProtocolFailureEvidenceTests.fixture
    capture_error = failure_fixtures.ProtocolFailureEvidenceTests.capture_error

    def test_signed_and_unsigned_fastfail_remain_failed_without_decode_or_retry(self):
        # Popen on Windows returned the unsigned value in run 91. Neither
        # representation proves a subtype, native stack, or behavioral repair.
        for exit_code in (0xC0000409, 0xC0000409 - 2**32):
            with self.subTest(exit_code=exit_code):
                fixture = self.fixture()
                process = fixture.process
                process.response = lambda *args: process.exit(exit_code)
                with patch.object(session, "decode_response") as decode:
                    error = self.capture_error(fixture)
                    decode.assert_not_called()
                self.assertEqual(error.status, "invalid-reply")
                self.assertTrue(fixture.capture._transport.ready_for_replacement.wait(2))
                evidence = session.sanitize_session_failure_evidence(error.failure_evidence)
                expected = dict(
                    schema_version=1,
                    protocol_diagnostic=dict(
                        schema_version=1, reason="stdout_eof", stage="response_header",
                        expected_bytes=64, received_bytes=0),
                    process_exit_code=exit_code, stderr_bytes=0, cleanup_complete=True,
                    termination_requested_while_alive=False, native_diagnostic=None,
                    shutdown_diagnostic=None)
                self.assertEqual(evidence, expected)
                self.assertEqual(fixture.spawn.call_count, 1)
                self.assertEqual(process.kills, 0)
                self.assertEqual(len(process.writes), 2)  # startup + one request

                # Undo fixture's fake Windows globals before real host Paths.
                fixture.capture.close()
                fixture.doCleanups()
                snapshot = dict(capture_diagnostic={"capture_status": "invalid-reply"},
                                session_failure=evidence, cleanup_pending=False)
                report = dict(
                    status="failed", error="Owned helper abnormal exit",
                    capture_failure_evidence=dict(
                        initial=snapshot, final=snapshot, cleanup_wait_ms=0.,
                        cleanup_deadline_reached=False, revocation_requested=True))
                with tempfile.TemporaryDirectory() as folder:
                    path = Path(folder) / "owned-failure.json"
                    path.write_text(json.dumps(report), encoding="utf-8")
                    summary = gate.native_failure_summary(path)
                self.assertEqual(summary["status"], "failed")
                for stage in ("initial", "final"):
                    self.assertEqual(summary["capture_failure_evidence"][stage]
                                     ["session_failure"], expected)
                with self.assertRaises(RuntimeError):
                    gate.validate_report(report, "0.4.17", expected_frozen=False)


class DiagnosticApiTests(unittest.TestCase):
    def setUp(self):
        from tests import windows_wgc_helper_crash
        self.diag = windows_wgc_helper_crash

    def test_status_normalization_preserves_both_windows_representations(self):
        for value, expected in ((0, 0), (1, 1), (-1, 0xffffffff),
                                (0xC0000409, 0xC0000409),
                                (-1073740791, 0xC0000409),
                                (-2147483648, 0x80000000),
                                (0xffffffff, 0xffffffff)):
            with self.subTest(value=value):
                self.assertEqual(self.diag.normalize_exit_status(value), expected)
        for value in (None, True, False, 1., "3221226505", -2147483649,
                      0x100000000, float("nan"), float("inf")):
            with self.subTest(value=value), self.assertRaises(self.diag.DiagnosticError):
                self.diag.normalize_exit_status(value)

    def test_duty_done_always_stops_before_original_screenshot_callback(self):
        original_done = Mock(side_effect=AssertionError("Screenshot route was entered"))
        with self.assertRaises(self.diag.DiagnosticComplete) as raised:
            self.diag.stop_after_duty_done(original_done)
        self.assertEqual(raised.exception.reason, "duty_complete_no_screenshot")
        original_done.assert_not_called()

    def test_cdb_commands_are_fixed_second_chance_unhandled_no_dump_or_writes(self):
        nonce = "0123456789abcdef"
        commands = self.diag.build_cdb_commands(nonce)
        for required in ("sxd", "-c2", "c0000409", ".exr -1", "k 20", "lm o",
                         "gn", "sx", "VGA_READY_" + nonce,
                         "VGA_EXCEPTION_" + nonce, "VGA_END_" + nonce):
            self.assertIn(required, commands)
        for banned in (".dump", ".ecxr", ".logopen", ".shell", ".call", ".writemem",
                       ".load", ".symfix", "srv*", "http", "https", " gh", " eb ", " ed "):
            self.assertNotIn(banned, commands.casefold())
        for malicious in ("", "abc", "A" * 16, "a" * 17, "a" * 1024,
                          "a" * 15 + "\n", 'a";g;"' + "a" * 9):
            with self.subTest(nonce=malicious), self.assertRaises(self.diag.DiagnosticError):
                self.diag.build_cdb_commands(malicious)


class ExactOwnedIdleTests(unittest.TestCase):
    def setUp(self):
        from tests import windows_wgc_helper_crash
        self.diag = windows_wgc_helper_crash
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def make_fixture(self):
        return OwnedStateFixture(self.temp.name)

    def snapshot(self, fixture):
        return self.diag.snapshot_owned_idle(fixture.capture, now=lambda: fixture.now,
                                            identity_reader=fixture.identity_reader)

    def test_exact_current_guarded_idle_owner_is_retained_without_renewal(self):
        fixture = self.make_fixture()
        deadline = fixture.transport.idle_deadline
        receipt = copy.deepcopy(fixture.receipt)
        snapshot = self.snapshot(fixture)
        self.assertIs(snapshot.owner, fixture.owner)
        self.assertIs(snapshot.session, fixture.session)
        self.assertIs(snapshot.transport, fixture.transport)
        self.assertIs(snapshot.process, fixture.process)
        self.assertEqual(snapshot.receipt, receipt)
        self.assertEqual(snapshot.idle_deadline, deadline)
        self.assertEqual(fixture.transport.idle_deadline, deadline)
        self.assertIsNone(fixture.transport.request_deadline)
        self.assertIsNone(fixture.transport._active)
        self.assertFalse(fixture.transport.revoked.is_set())
        self.assertFalse(fixture.owner.revoked.is_set())
        self.diag.assert_same_owner(snapshot, fixture.capture,
                                    identity_reader=fixture.identity_reader)

    def test_attachment_budget_uses_remaining_original_submit_lease(self):
        fixture = self.make_fixture()
        snapshot = self.snapshot(fixture)
        self.assertAlmostEqual(self.diag.attachment_timeout(snapshot, now=lambda: fixture.now), .7)
        self.assertAlmostEqual(self.diag.attachment_timeout(snapshot, now=lambda: fixture.now + .5), .2)
        self.assertEqual(fixture.transport.idle_deadline, fixture.now + .7)
        for at in (fixture.now + .7, fixture.now + 1., float("nan"), float("inf")):
            with self.subTest(at=at), self.assertRaises(self.diag.DiagnosticError):
                self.diag.attachment_timeout(snapshot, now=lambda: at)
        fixture.transport.idle_deadline = fixture.now + 4.
        snapshot = self.snapshot(fixture)
        self.assertEqual(self.diag.attachment_timeout(snapshot, now=lambda: fixture.now), 1.5)

    def test_no_receipt_stale_receipt_or_nonidle_state_cannot_authorize_attach(self):
        mutations = {
            "absent_owner": lambda f: setattr(f.adapter, "_owner", None),
            "adapter_closed": lambda f: setattr(f.adapter, "_closed", True),
            "session_closed": lambda f: setattr(f.session, "_closed", True),
            "owner_revoked": lambda f: f.owner.revoked.set(),
            "transport_revoked": lambda f: f.transport.revoked.set(),
            "not_setup": lambda f: f.owner.setup_done.clear(),
            "capture_not_done": lambda f: f.owner.call_done.clear(),
            "active_exchange": lambda f: setattr(f.transport, "_active", object()),
            "request_deadline": lambda f: setattr(f.transport, "request_deadline", f.now + .5),
            "expired_lease": lambda f: setattr(f.transport, "idle_deadline", f.now),
            "no_receipt": lambda f: setattr(f.capture, "_last_session_receipt", None),
            "stale_epoch": lambda f: setattr(f.capture, "_last_session_epoch", -1),
            "stale_request": lambda f: setattr(f.session, "_request_id", 8),
            "stale_timing": lambda f: f.session.last_timing.update(frame_100ns=103),
            "wrong_generation": lambda f: setattr(f.transport, "generation", 124),
            "wrong_receipt_pid": lambda f: f.capture._last_session_receipt.update(helper_pid=1234),
            "wrong_receipt_created": lambda f: f.capture._last_session_receipt.update(helper_created=1234),
            "invalid_receipt_order": lambda f: f.capture._last_session_receipt.update(frame_100ns=1),
            "not_registered": lambda f: f.capture._last_session_receipt.update(overlay_registration_valid=False),
            "visible_capability": lambda f: setattr(f.adapter, "_allow_visible_overlay", True),
            "visible_prepared": lambda f: setattr(f.adapter, "_prepared_visible_mode", True),
            "visible_binding": lambda f: setattr(f.owner, "binding", f.owner.binding[:-1] + (True,)),
            "visible_session": lambda f: setattr(f.session, "_allow_visible_overlay", True),
            "absent_job": lambda f: setattr(f.transport, "job", None),
            "closed_job": lambda f: setattr(f.job, "handle", None),
            "process_exited": lambda f: setattr(f.process.poll, "return_value", 0),
            "prior_cleanup": lambda f: setattr(f.capture._wgc, "_pending_cleanup", object()),
            "prior_job": lambda f: setattr(f.capture._wgc, "_pending_job", object()),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                fixture = self.make_fixture()
                mutate(fixture)
                with self.assertRaises(self.diag.DiagnosticError):
                    self.snapshot(fixture)

    def test_identity_cannot_be_retargeted_after_qt_event_pump(self):
        mutations = {
            "owner": lambda f: setattr(f.adapter, "_owner", copy.copy(f.owner)),
            "session": lambda f: setattr(f.owner, "session", copy.copy(f.session)),
            "transport": lambda f: setattr(f.session, "_transport", copy.copy(f.transport)),
            "process": lambda f: setattr(f.transport, "process", copy.copy(f.process)),
            "job": lambda f: setattr(f.transport, "job", copy.copy(f.job)),
            "process_handle": lambda f: setattr(f.process, "_handle", 9999),
            "job_handle": lambda f: setattr(f.job, "handle", 9999),
            "pid": lambda f: f.identity.update(pid=4322),
            "creation": lambda f: f.identity.update(created=112234),
            "path": lambda f: f.identity.update(path=str(f.helper) + ".different"),
            "hash": lambda f: f.identity.update(sha256="0" * 64),
            "generation": lambda f: setattr(f.transport, "generation", 124),
            "mode": lambda f: setattr(f.adapter, "_prepared_visible_mode", True),
            "binding": lambda f: setattr(f.owner, "binding", f.owner.binding[:-1] + (True,)),
            "epoch": lambda f: setattr(f.adapter, "_epoch", 1),
            "request": lambda f: setattr(f.session, "_request_id", 8),
            "receipt": lambda f: f.capture._last_session_receipt.update(request_id=8),
            "idle_deadline": lambda f: setattr(f.transport, "idle_deadline", f.now + 4.),
            "revoked": lambda f: f.owner.revoked.set(),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                fixture = self.make_fixture()
                snapshot = self.snapshot(fixture)
                original_capture = Mock()
                app = SimpleNamespace(processEvents=lambda: mutate(fixture))
                app.processEvents()
                with self.assertRaises(self.diag.DiagnosticError):
                    self.diag.assert_same_owner(snapshot, fixture.capture,
                                                identity_reader=fixture.identity_reader)
                    original_capture()
                original_capture.assert_not_called()

    def test_mutation_during_identity_read_is_detected_without_owner_replacement(self):
        fixture = self.make_fixture()
        original = fixture.owner
        def race(process, job, expected_path):
            fixture.adapter._owner = copy.copy(original)
            return dict(fixture.identity)
        fixture.identity_reader.side_effect = race
        with self.assertRaises(self.diag.DiagnosticError):
            self.snapshot(fixture)
        # The probe observes replacement; it never writes its saved owner back.
        self.assertIsNot(fixture.adapter._owner, original)


class BoundedCdbParserTests(unittest.TestCase):
    NONCE = "0123456789abcdef"

    def setUp(self):
        from tests import windows_wgc_helper_crash
        self.diag = windows_wgc_helper_crash

    def transcript(self, frame_count=2, terminal=True):
        frames = [f"{index:02x} 00000000`0010{index * 16:04x} "
                  f"00000001`4000{0x320 + index * 16:04x} owned_helper+0x320"
                  for index in range(frame_count)]
        if terminal:
            frames.append(f"{frame_count:02x} 00000000`0010fff0 00000000`00000000 ntdll+0x123")
        return "\n".join([
            "Microsoft CDB owned fixture",
            "c0000409 - Security check failure - second-chance break",
            "VGA_READY_" + self.NONCE,
            "VGA_EXCEPTION_" + self.NONCE,
            "ExceptionAddress: 00000001`40000123 (owned_helper+0x123)",
            "ExceptionCode: c0000409 (Security check failure)",
            "ExceptionFlags: 00000001", "NumberParameters: 1",
            "Parameter[0]: 00000000`00000007",
            " # Child-SP          RetAddr               Call Site", *frames,
            "start             end                 module name",
            "00000001`40000000 00000001`40010000 owned_helper (no symbols)",
            "00000007`70000000 00000007`70010000 ntdll (no symbols)",
            "VGA_END_" + self.NONCE, ""])

    def parse(self, text):
        return self.diag.parse_cdb_text(text, self.NONCE)

    def test_complete_record_exports_only_relative_locations_and_validated_subtype(self):
        result = self.parse(self.transcript())
        self.assertEqual(result, dict(exception_code=0xC0000409, fast_fail_subtype=7,
            exception_module="owned_helper", exception_rva=0x123,
            frames=[dict(return_module="owned_helper", return_rva=0x320),
                    dict(return_module="owned_helper", return_rva=0x330)], complete=True))
        output = json.dumps(result)
        for private in ("00000001", "0010fff0", "ExceptionAddress", "Parameter", "Call Site"):
            self.assertNotIn(private, output)

    def test_documented_sbo_filter_alias_is_accepted_only_for_second_chance(self):
        text = self.transcript().replace("c0000409 - Security check failure", "sbo - Stack buffer overflow")
        self.assertEqual(self.parse(text)["exception_code"], 0xC0000409)
        with self.assertRaises(self.diag.DiagnosticError):
            self.parse(text.replace("second-chance break", "first-chance break"))

    def test_additional_exception_parameters_paths_and_argument_strings_never_escape(self):
        text = self.transcript().replace("NumberParameters: 1", "NumberParameters: 3")
        text = text.replace("Parameter[0]: 00000000`00000007",
                            "Parameter[0]: 00000000`00000007\n"
                            "Parameter[1]: 00000000`deadbeef\n"
                            "Parameter[2]: 00000000`cafebabe")
        text = "C:\\Users\\private-person\\secret.log\n" + text
        text = text.replace("owned_helper+0x320", "owned_helper+0x320 private_argument")
        output = json.dumps(self.parse(text))
        for private in ("private-person", "secret", "deadbeef", "cafebabe", "private_argument", "Parameter"):
            self.assertNotIn(private, output)

    def test_missing_duplicate_wrong_nonce_or_reordered_markers_fail_closed(self):
        original = self.transcript()
        ready = "VGA_READY_" + self.NONCE
        exception = "VGA_EXCEPTION_" + self.NONCE
        end = "VGA_END_" + self.NONCE
        malformed = [original.replace(marker, "") for marker in (ready, exception, end)]
        malformed += [original + marker + "\n" for marker in (ready, exception, end)]
        malformed += [original.replace(ready, "VGA_READY_ffffffffffffffff"),
                      original.replace(ready, "SWAP").replace(exception, ready).replace("SWAP", exception),
                      original.replace("second-chance break", "first-chance break")]
        for index, text in enumerate(malformed):
            with self.subTest(index=index), self.assertRaises(self.diag.DiagnosticError):
                self.parse(text)

    def test_no_stack_or_incomplete_stack_is_not_complete_evidence(self):
        original = self.transcript()
        variants = [self.transcript(frame_count=0),
                    original.replace("Child-SP", "missing-stack-header"),
                    original.replace("00000001`40000320", "00000009`90000320"),
                    original.replace("00000001`40000123", "00000009`90000123"),
                    original.split("VGA_END_", 1)[0],
                    original.replace("00 00000000`00100000 00000001`40000320 owned_helper+0x320",
                                     "00 malformed stack row")]
        for index, text in enumerate(variants):
            with self.subTest(index=index), self.assertRaises(self.diag.DiagnosticError):
                self.parse(text)

    def test_full_32_frame_bounded_stack_does_not_parse_module_table_as_frames(self):
        result = self.parse(self.transcript(frame_count=32, terminal=False))
        self.assertEqual(len(result["frames"]), 32)
        with self.assertRaises(self.diag.DiagnosticError):
            self.parse(self.transcript(frame_count=33))

    def test_nonfastfail_missing_or_out_of_range_subtype_and_ambiguous_modules_rejected(self):
        original = self.transcript()
        variants = [original.replace("ExceptionCode: c0000409", "ExceptionCode: c0000005"),
                    original.replace("Parameter[0]: 00000000`00000007", "Parameter[1]: 00000000`00000007"),
                    original.replace("Parameter[0]: 00000000`00000007", "Parameter[0]: 00000001`00000000"),
                    original.replace("NumberParameters: 1", "NumberParameters: 0"),
                    original.replace("NumberParameters: 1", "NumberParameters: 16"),
                    original.replace("00000007`70000000 00000007`70010000 ntdll",
                                     "00000001`40000001 00000001`40001000 ntdll"),
                    original.replace("owned_helper (no symbols)", "C:\\private\\helper.exe (no symbols)")]
        for index, text in enumerate(variants):
            with self.subTest(index=index), self.assertRaises(self.diag.DiagnosticError):
                self.parse(text)

    def test_unloaded_module_ranges_cannot_authorize_fault_or_return_addresses(self):
        original = self.transcript()
        for prefix in ("Unloaded modules:", "unloaded modules:"):
            text = original.replace("start             end                 module name",
                                    prefix + "\nstart             end                 module name")
            with self.subTest(prefix=prefix), self.assertRaises(self.diag.DiagnosticError):
                self.parse(text)

    def test_oversized_binary_and_malformed_inputs_do_not_escape_raw_text(self):
        for value in (b"private", None, "\0" + self.transcript(),
                      self.transcript() + "private" * self.diag.RAW_LIMIT):
            with self.subTest(kind=type(value).__name__), self.assertRaises(self.diag.DiagnosticError) as caught:
                self.parse(value)
            self.assertNotIn("private", str(caught.exception))


class StrictDiagnosticArtifactTests(unittest.TestCase):
    def setUp(self):
        from tests import windows_wgc_helper_crash
        self.diag = windows_wgc_helper_crash
        self.crash = dict(exception_code=0xC0000409, fast_fail_subtype=7,
                          exception_module="owned_helper", exception_rva=0x123,
                          frames=[dict(return_module="owned_helper", return_rva=0x320)], complete=True)
        successful = dict(attempted=True, attached=True, entry_verified=True,
                          request_verified=True, capture_returned=False,
                          attachment_budget_us=1500000, attachment_elapsed_us=50000,
                          cleanup_complete=True, exit_code=0xC0000409, crash=self.crash)
        self.valid = dict(schema_version=1, status="crash_recorded", reason="crash_recorded",
                          source_commit="a" * 40,
                          product_hashes={name: "b" * 64 for name in self.diag.PRODUCT_FILES},
                          helper_hashes={name: "d" * 64 for name in self.diag.HELPER_FILES},
                          tool=dict(sha256="c" * 64, size=12345, file_version="10.0.26100.1"),
                          canary=copy.deepcopy(successful), probe=copy.deepcopy(successful),
                          duty_completed=False, session_failure=None)

    def rejects(self, value):
        with self.assertRaises((ValueError, self.diag.DiagnosticError)):
            self.diag.validate_artifact(value)

    def test_exact_schema_roundtrip_and_failed_product_status_unchanged(self):
        self.assertEqual(self.diag.validate_artifact(copy.deepcopy(self.valid)), self.valid)
        self.assertNotIn("passed", json.dumps(self.valid))

    def test_unknown_private_fields_rejected_at_every_exported_level(self):
        for route in ((), ("tool",), ("canary",), ("probe",), ("probe", "crash"),
                      ("probe", "crash", "frames", 0)):
            value = copy.deepcopy(self.valid)
            target = value
            for key in route:
                target = target[key]
            target["private_path"] = "C:\\Users\\person\\secret.dmp"
            with self.subTest(route=route):
                self.rejects(value)

    def test_incomplete_identity_and_unbounded_or_address_fields_rejected(self):
        mutations = [lambda v: v["product_hashes"].pop(next(iter(v["product_hashes"]))),
                     lambda v: v["tool"].update(sha256="not a digest"),
                     lambda v: v["tool"].update(size=True),
                     lambda v: v["probe"]["crash"].update(exception_module="C:\\private\\helper.exe"),
                     lambda v: v["probe"]["crash"].update(fast_fail_subtype=2**32),
                     lambda v: v["probe"]["crash"].update(fast_fail_subtype=True),
                     lambda v: v["probe"]["crash"].update(frames=[]),
                     lambda v: v["probe"]["crash"].update(frames=[dict(return_module="x", return_rva=1)] * 33),
                     lambda v: v["probe"]["crash"].update(complete=False),
                     lambda v: v["probe"]["crash"]["frames"][0].update(return_rva=2**64),
                     lambda v: v.update(session_failure={"raw": "private"})]
        for index, mutate in enumerate(mutations):
            value = copy.deepcopy(self.valid)
            mutate(value)
            with self.subTest(index=index):
                self.rejects(value)

    def test_recorded_crash_requires_successful_canary_exact_entry_and_cleanup(self):
        for kind, key in (("canary", "attempted"), ("canary", "attached"),
                          ("canary", "entry_verified"), ("canary", "request_verified"),
                          ("canary", "cleanup_complete"),
                          ("probe", "attempted"), ("probe", "attached"),
                          ("probe", "entry_verified"), ("probe", "request_verified"),
                          ("probe", "cleanup_complete")):
            value = copy.deepcopy(self.valid)
            value[kind][key] = False
            with self.subTest(kind=kind, key=key):
                self.rejects(value)
        for kind in ("canary", "probe"):
            value = copy.deepcopy(self.valid)
            value[kind]["exit_code"] = 0
            with self.subTest(kind=kind):
                self.rejects(value)

    def test_not_reproduced_requires_completed_duty_and_clean_owned_observation(self):
        value = copy.deepcopy(self.valid)
        value.update(status="not_reproduced", reason="not_reproduced", duty_completed=True)
        value["probe"].update(crash=None, exit_code=0, capture_returned=True)
        self.diag.validate_artifact(value)
        for key in ("attempted", "attached", "entry_verified", "request_verified", "capture_returned", "cleanup_complete"):
            changed = copy.deepcopy(value)
            changed["probe"][key] = False
            with self.subTest(key=key):
                self.rejects(changed)
        changed = copy.deepcopy(value)
        changed["duty_completed"] = False
        self.rejects(changed)

    def test_helper_fixture_and_attachment_timing_are_bound_before_conclusive_status(self):
        self.assertIn("fixtures/auto-scene.png", self.valid["product_hashes"])
        for kind, key, replacement in (("canary", "attachment_budget_us", None),
                                       ("probe", "attachment_budget_us", 1500001),
                                       ("probe", "attachment_elapsed_us", 1500001),
                                       ("probe", "attachment_elapsed_us", True),
                                       ("probe", "attachment_elapsed_us", -1)):
            value = copy.deepcopy(self.valid)
            value[kind][key] = replacement
            with self.subTest(kind=kind, key=key, replacement=replacement):
                self.rejects(value)
        value = copy.deepcopy(self.valid)
        value["helper_hashes"].pop(next(iter(value["helper_hashes"])))
        self.rejects(value)


class ProbeHookIntegrationTests(unittest.TestCase):
    """Actual launcher hooks, synthetic scheduling, no debugger or Qt execution."""

    def setUp(self):
        from tests import windows_wgc_helper_crash
        self.diag = windows_wgc_helper_crash
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.fixture = OwnedStateFixture(self.temp.name)
        helper = Path(self.temp.name) / "build/native/vga-wgc-session-capture.exe"
        helper.parent.mkdir(parents=True)
        helper.write_bytes(self.fixture.helper.read_bytes())
        self.fixture.helper = self.fixture.session.helper_path = helper
        self.fixture.identity["path"] = str(helper.resolve())
        def original_capture(*args, **kwargs):
            fixture = self.fixture
            fixture.session._request_id += 1
            fixture.session.last_timing.update(
                request_id=fixture.session._request_id,
                request_cutoff_100ns=110, frame_100ns=111, idle_enter_100ns=112)
            fixture.session._last_frame = 111
            fixture.receipt.update(fixture.session.last_timing)
            fixture.capture._last_session_receipt = dict(fixture.receipt)
            fixture.adapter._last_receipt = dict(fixture.receipt)
            return "original capture value"
        self.fixture.capture.capture = Mock(side_effect=original_capture)
        self.control = SimpleNamespace(capture=self.fixture.capture,
                                       enable_visible_capture=False, ocr_busy=False, capture_pending=False)
        self.observation = self.diag._empty_observation()
        self.result = {"duty_completed": False}
        self.paint = Mock(return_value="original paint value")
        self.observer = SimpleNamespace(ready=Mock(), close=Mock(), text=Mock(return_value=""),
            nonce="0123456789abcdef",
            done=SimpleNamespace(wait=Mock(), is_set=Mock(return_value=False)))

    def install(self, original_mode, original_probe=None):
        self.smoke = SimpleNamespace(_start_overlay_duty_mode=original_mode,
                                     start_overlay_duty_probe=original_probe or Mock())
        cleanup = self.diag.install_probe(self.smoke, "owned-cdb.exe", self.temp.name,
                                          self.observation, self.result)
        self.addCleanup(cleanup)
        return cleanup

    def run_mode(self, event_pump=lambda: None):
        actual_snapshot = self.diag.snapshot_owned_idle
        fixture = self.fixture
        def read_owned(capture, **kwargs):
            return actual_snapshot(capture, now=lambda: fixture.now,
                                   identity_reader=fixture.identity_reader)
        with patch.object(self.diag, "snapshot_owned_idle", side_effect=read_owned), \
                patch.object(self.diag, "ROOT", Path(self.temp.name)), \
                patch("session_windows.process_metadata", return_value=SimpleNamespace(created=991122)), \
                patch.object(self.diag.os, "getpid", return_value=5678), \
                patch.object(self.diag, "CdbObserver", return_value=self.observer) as observer:
            value = self.smoke._start_overlay_duty_mode(self.control,
                mode_report={"mode": "persistent"}, paint_mock=self.paint,
                app=SimpleNamespace(processEvents=event_pump))
        return value, observer

    def test_exact_attach_paint_event_pump_capture_forwarded_once_unchanged(self):
        events = []
        def mode(control, **kwargs):
            events.append("paint")
            self.assertEqual(kwargs["paint_mock"](changed_title=True), "original paint value")
            kwargs["app"].processEvents()
            events.append("capture")
            return control.capture.capture("owned-target", allow_visible_overlay=False)
        original_capture = self.fixture.capture.capture
        self.install(mode)
        value, observer = self.run_mode(lambda: events.append("qt-events"))
        self.assertEqual(value, "original capture value")
        self.assertEqual(events, ["paint", "qt-events", "capture"])
        observer.assert_called_once_with("owned-cdb.exe", self.fixture.process, self.temp.name)
        self.observer.ready.assert_called_once()
        self.assertGreater(self.observer.ready.call_args.args[0], 0)
        self.assertLessEqual(self.observer.ready.call_args.args[0], .7 + .001)
        original_capture.assert_called_once_with("owned-target", allow_visible_overlay=False)
        self.paint.assert_called_once_with(changed_title=True)
        self.assertTrue(self.observation["entry_verified"])
        self.assertTrue(self.observation["request_verified"])
        self.assertTrue(self.observation["capture_returned"])

    def test_owner_replacement_in_real_hook_event_gap_prevents_original_capture(self):
        def mode(control, **kwargs):
            kwargs["paint_mock"](changed_title=True)
            kwargs["app"].processEvents()
            return control.capture.capture("owned-target")
        original_capture = self.fixture.capture.capture
        self.install(mode)
        with self.assertRaises(self.diag.DiagnosticError):
            self.run_mode(lambda: setattr(self.fixture.adapter, "_owner", copy.copy(self.fixture.owner)))
        original_capture.assert_not_called()
        self.assertFalse(self.observation["entry_verified"])

    def test_probe_refuses_second_changed_title_attach_without_retry(self):
        def mode(control, **kwargs):
            kwargs["paint_mock"](changed_title=True)
            kwargs["paint_mock"](changed_title=True)
        self.install(mode)
        with self.assertRaises(self.diag.DiagnosticError):
            self.run_mode()
        self.observer.ready.assert_called_once()
        self.paint.assert_called_once_with(changed_title=True)

    def test_attach_constructor_overhead_cannot_extend_remaining_budget(self):
        def mode(control, **kwargs):
            kwargs["paint_mock"](changed_title=True)
        self.install(mode)
        with patch.object(self.diag, "attachment_timeout", return_value=.7), \
                patch.object(self.diag.time, "monotonic", side_effect=[100., 101., 101.]), \
                self.assertRaises(self.diag.DiagnosticError):
            self.run_mode()
        self.observer.ready.assert_not_called()
        self.paint.assert_not_called()
        self.assertEqual(self.observation["attachment_budget_us"], 700000)
        self.assertEqual(self.observation["attachment_elapsed_us"], 1000000)

    def test_internal_transport_replacement_does_not_claim_observed_request(self):
        original_error = RuntimeError("original native failure")
        def failing_capture(*args, **kwargs):
            self.fixture.session._transport = copy.copy(self.fixture.transport)
            self.fixture.session._request_id += 1
            raise original_error
        self.fixture.capture.capture.side_effect = failing_capture
        def mode(control, **kwargs):
            kwargs["paint_mock"](changed_title=True)
            return control.capture.capture("owned-target")
        self.install(mode)
        with self.assertRaises(RuntimeError) as caught:
            self.run_mode()
        self.assertIs(caught.exception, original_error)
        self.assertTrue(self.observation["entry_verified"])
        self.assertFalse(self.observation["request_verified"])
        self.assertFalse(self.observation["capture_returned"])

    def test_original_capture_exception_is_preserved_with_exact_request_evidence(self):
        original_error = RuntimeError("original native failure")
        def failing_capture(*args, **kwargs):
            self.fixture.session._request_id += 1
            raise original_error
        self.fixture.capture.capture.side_effect = failing_capture
        def mode(control, **kwargs):
            kwargs["paint_mock"](changed_title=True)
            return control.capture.capture("owned-target")
        self.install(mode)
        with self.assertRaises(RuntimeError) as caught:
            self.run_mode()
        self.assertIs(caught.exception, original_error)
        self.assertTrue(self.observation["request_verified"])
        self.assertFalse(self.observation["capture_returned"])

    def test_one_shot_and_earlier_failure_are_not_replaced_by_targeted_probe(self):
        earlier = RuntimeError("existing failure")
        original_mode = Mock(side_effect=earlier)
        self.install(original_mode)
        with patch.object(self.diag, "CdbObserver") as observer, \
                self.assertRaises(RuntimeError) as caught:
            self.smoke._start_overlay_duty_mode(self.control,
                mode_report={"mode": "one-shot"}, paint_mock=self.paint)
        self.assertIs(caught.exception, earlier)
        observer.assert_not_called()
        self.paint.assert_not_called()
        self.assertFalse(self.observation["attempted"])

    def test_completion_callback_cannot_enter_screenshot_route_and_restores_hooks(self):
        original_mode = Mock()
        original_done = Mock(side_effect=AssertionError("Would persist screenshot"))
        original_probe = lambda control, **kwargs: kwargs["done"]()
        cleanup = self.install(original_mode, original_probe)
        with self.assertRaises(self.diag.DiagnosticComplete):
            self.smoke.start_overlay_duty_probe(self.control, done=original_done)
        original_done.assert_not_called()
        self.assertTrue(self.result["duty_completed"])
        self.assertEqual(list(Path(self.temp.name).glob("*.png")), [])
        cleanup()
        self.assertIs(self.smoke._start_overlay_duty_mode, original_mode)
        self.assertIs(self.smoke.start_overlay_duty_probe, original_probe)


class SingleRunOrchestrationTests(unittest.TestCase):
    def setUp(self):
        from tests import windows_wgc_helper_crash
        self.diag = windows_wgc_helper_crash
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.tool = dict(path=str(self.root / "cdb.exe"), sha256="a" * 64,
                         size=12345, file_version="10.0.26100.1")
        self.order = []
        self.crash = dict(exception_code=0xC0000409, fast_fail_subtype=7,
                          exception_module="owned_helper", exception_rva=1,
                          frames=[dict(return_module="owned_helper", return_rva=2)], complete=True)

    def canary(self, cdb, folder, row):
        self.order.append("canary")
        row.update(attempted=True, attached=True, entry_verified=True,
                   request_verified=True, capture_returned=False,
                   attachment_budget_us=1500000, attachment_elapsed_us=50000,
                   cleanup_complete=True, exit_code=0xC0000409, crash=self.crash)

    def invoke(self, canary, probe):
        verified = dict(cdb=self.tool,
                        helper_files={name: dict(sha256="d" * 64, size=1)
                                      for name in self.diag.HELPER_FILES})
        with patch.object(self.diag.sys, "platform", "win32"), \
                patch.object(self.diag, "_verify_proof", return_value=verified) as proof, \
                patch.object(self.diag, "_record", return_value={"sha256": "b" * 64, "size": 1}), \
                patch.object(self.diag.subprocess, "check_output", return_value="c" * 40), \
                patch.object(self.diag, "run_canary", side_effect=canary) as run_canary, \
                patch.object(self.diag, "run_probe", side_effect=probe) as run_probe, \
                redirect_stdout(io.StringIO()):
            code = self.diag.main(["--debugger-proof", str(self.root / "proof.json"),
                                   "--reports", str(self.root / "evidence")])
        result = json.loads((self.root / "evidence/reports/windows-wgc-helper-crash.json").read_text())
        return code, result, proof, run_canary, run_probe

    def test_one_successful_canary_then_one_probe_and_no_retry_when_not_reproduced(self):
        def probe(cdb, folder, artifact):
            self.order.append("probe")
            artifact["probe"].update(attempted=True, attached=True, entry_verified=True,
                                      request_verified=True, capture_returned=True,
                                      attachment_budget_us=700000, attachment_elapsed_us=50000,
                                      cleanup_complete=True, exit_code=0, crash=None)
            artifact.update(status="not_reproduced", reason="not_reproduced", duty_completed=True)
        code, result, proof, canary, probe = self.invoke(self.canary, probe)
        self.assertEqual(self.order, ["canary", "probe"])
        canary.assert_called_once()
        probe.assert_called_once()
        self.assertEqual(proof.call_count, 2)
        self.assertEqual(code, 0)
        self.assertEqual(result["status"], "not_reproduced")
        self.assertNotIn("passed", json.dumps(result))

    def test_canary_failure_stops_before_real_probe(self):
        def canary(cdb, folder, row):
            self.order.append("canary")
            row["attempted"] = True
            raise self.diag.DiagnosticError("canary_failed")
        code, result, proof, canary, probe = self.invoke(canary, Mock())
        self.assertEqual(code, 1)
        canary.assert_called_once()
        probe.assert_not_called()
        self.assertFalse(result["probe"]["attempted"])
        self.assertEqual(result["reason"], "canary_failed")

    def test_probe_failure_is_not_retried_or_reclassified_as_acceptance(self):
        def probe(cdb, folder, artifact):
            self.order.append("probe")
            artifact["probe"]["attempted"] = True
            raise self.diag.DiagnosticError("native_probe_failed")
        code, result, proof, canary, probe = self.invoke(self.canary, probe)
        self.assertEqual(code, 1)
        self.assertEqual(self.order, ["canary", "probe"])
        canary.assert_called_once()
        probe.assert_called_once()
        self.assertEqual(result["status"], "inconclusive")
        self.assertEqual(result["reason"], "native_probe_failed")

    def test_existing_output_stops_before_any_second_attempt(self):
        (self.root / "evidence").mkdir()
        with patch.object(self.diag.sys, "platform", "win32"), \
                patch.object(self.diag, "_verify_proof") as proof, \
                patch.object(self.diag, "run_canary") as canary, \
                patch.object(self.diag, "run_probe") as probe, \
                self.assertRaises(self.diag.DiagnosticError):
            self.diag.main(["--debugger-proof", str(self.root / "proof.json"),
                            "--reports", str(self.root / "evidence")])
        proof.assert_not_called()
        canary.assert_not_called()
        probe.assert_not_called()


class VerifiedDebuggerProofTests(unittest.TestCase):
    """Actual verifier on fake file bytes; signature claims are not OS-verified here."""

    def setUp(self):
        from tests import windows_wgc_helper_crash
        self.diag = windows_wgc_helper_crash
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "proof.json"
        cdb = self.root / "sdk/Debuggers/x64/cdb.exe"
        cdb.parent.mkdir(parents=True)
        cdb.write_bytes(b"MZ" + b"owned fake debugger" * 100)
        record = self.diag._record(cdb)
        self.proof = dict(schema_version=1, status="verified",
            cdb=dict(record, path=str(cdb), machine="x64", signature_status="Valid",
                     signer_subject="CN=Microsoft Windows, O=Microsoft Corporation, C=US",
                     file_version="10.0.26100.1"),
            installation=dict(performed=False, exit_code=None,
                              feature="OptionId.WindowsDesktopDebuggers", installer=None, license=None),
            input_files={}, helper_files={})
        helpers = ("build/native/vga-wgc-capture.exe", "build/native/wgc-capture-build.json",
                   "build/native/vga-wgc-session-capture.exe", "build/native/wgc-session-capture-build.json")
        for category, names in (("input_files", self.diag.PRODUCT_FILES), ("helper_files", helpers)):
            for name in names:
                path = self.root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"owned fixture " + name.encode())
                self.proof[category][name] = self.diag._record(path)

    def verify(self, proof):
        self.path.write_text(json.dumps(proof))
        with patch.object(self.diag, "ROOT", self.root), \
                patch("scripts.build_wgc_capture.verify_built_helper") as one, \
                patch("scripts.build_wgc_session_capture.verify_built_helper") as persistent:
            result = self.diag._verify_proof(self.path)
        return result, one, persistent

    def test_exact_verified_proof_rechecks_helpers_and_all_recorded_bytes(self):
        result, one, persistent = self.verify(self.proof)
        self.assertEqual(result, self.proof)
        one.assert_called_once()
        persistent.assert_called_once()

    def test_signature_architecture_version_and_schema_fail_closed(self):
        mutations = [lambda p: p.update(schema_version=True),
                     lambda p: p.update(schema_version=2),
                     lambda p: p.update(status="failed"),
                     lambda p: p["cdb"].update(machine="arm64"),
                     lambda p: p["cdb"].update(machine="x86"),
                     lambda p: p["cdb"].update(signature_status="NotSigned"),
                     lambda p: p["cdb"].update(signer_subject="CN=NotMicrosoft, O=Impostor Corporation"),
                     lambda p: p["cdb"].update(signer_subject="O=Microsoft Corporation Impostor"),
                     lambda p: p["cdb"].update(file_version="9.0.26100.1"),
                     lambda p: p["cdb"].update(file_version="private version string"),
                     lambda p: p["cdb"].update(sha256="0" * 64),
                     lambda p: p["cdb"].update(size=1)]
        for index, mutate in enumerate(mutations):
            value = copy.deepcopy(self.proof)
            mutate(value)
            with self.subTest(index=index), self.assertRaises(self.diag.DiagnosticError):
                self.verify(value)

    def test_missing_production_inputs_or_helper_inventory_rejected(self):
        for category in ("input_files", "helper_files"):
            value = copy.deepcopy(self.proof)
            value[category].pop(next(iter(value[category])))
            with self.subTest(category=category), self.assertRaises(self.diag.DiagnosticError):
                self.verify(value)
        value = copy.deepcopy(self.proof)
        value["helper_files"]["build/native/extra.exe"] = dict(sha256="1" * 64, size=1)
        with self.assertRaises(self.diag.DiagnosticError):
            self.verify(value)

    def test_source_and_helper_mutation_after_preparation_rejected(self):
        for category in ("input_files", "helper_files"):
            name = next(iter(self.proof[category]))
            path = self.root / name
            old = path.read_bytes()
            try:
                path.write_bytes(old + b" changed")
                with self.subTest(category=category), self.assertRaises(self.diag.DiagnosticError):
                    self.verify(self.proof)
            finally:
                path.write_bytes(old)

    def test_relative_path_escape_and_oversized_local_proof_rejected(self):
        value = copy.deepcopy(self.proof)
        value["input_files"]["../private.txt"] = dict(sha256="1" * 64, size=1)
        with self.assertRaises(self.diag.DiagnosticError):
            self.verify(value)
        self.path.write_bytes(b" " * (self.diag.RAW_LIMIT + 1))
        with self.assertRaises(self.diag.DiagnosticError):
            self.diag._verify_proof(self.path)


class OwnedDebuggerLaunchTests(unittest.TestCase):
    def setUp(self):
        from tests import windows_wgc_helper_crash
        self.diag = windows_wgc_helper_crash

    def test_debugger_exact_pid_no_shell_network_symbols_or_saved_raw_log(self):
        process = SimpleNamespace(pid=4321)
        debugger = SimpleNamespace(stdout=io.BytesIO(), pid=8765)
        job = SimpleNamespace(assign=Mock(), close=Mock(), handle=1234)
        with tempfile.TemporaryDirectory() as folder, \
                patch("wgc_capture._CaptureJob", return_value=job), \
                patch.object(self.diag.subprocess, "Popen", return_value=debugger) as spawn, \
                patch.object(self.diag.subprocess, "CREATE_NO_WINDOW", 0, create=True), \
                patch.object(self.diag.threading, "Thread") as thread, \
                patch.dict(self.diag.os.environ, {"_NT_SYMBOL_PATH": "srv*https://private.invalid",
                                                  "_NT_ALT_SYMBOL_PATH": "private",
                                                  "_NT_DEBUGGER_EXTENSION_PATH": "private"}):
            observer = self.diag.CdbObserver("verified-cdb.exe", process, folder)
            args = spawn.call_args.args[0]
            options = spawn.call_args.kwargs
            self.assertEqual(args[0], "verified-cdb.exe")
            self.assertEqual(args[args.index("-p") + 1], "4321")
            self.assertNotIn("-pn", args)
            self.assertFalse(options.get("shell", False))
            self.assertEqual(options["bufsize"], 0)
            for flag in ("-G", "-pd", "-sins", "-noshell", "-nosqm"):
                self.assertIn(flag, args)
            for key in ("_NT_SYMBOL_PATH", "_NT_ALT_SYMBOL_PATH", "_NT_DEBUGGER_EXTENSION_PATH"):
                self.assertNotIn(key, options["env"])
            self.assertEqual(Path(args[args.index("-y") + 1]).parent, Path(folder))
            files = [path for path in Path(folder).iterdir() if path.is_file()]
            self.assertEqual(len(files), 1)
            self.assertEqual(files[0].read_text(), self.diag.build_cdb_commands(observer.nonce))
            self.assertEqual(files[0].suffix, ".txt")
            self.assertNotIn(".dump", files[0].read_text())
            job.assign.assert_called_once_with(debugger)
            thread.return_value.start.assert_called_once()

    def test_raw_output_reader_stops_at_bound_without_saving_or_truncation_success(self):
        observer = self.diag.CdbObserver.__new__(self.diag.CdbObserver)
        observer.data = bytearray()
        observer.lock = threading.Lock()
        observer.overflow = threading.Event()
        observer.done = threading.Event()
        observer.process = SimpleNamespace(stdout=io.BytesIO(b"X" * (self.diag.RAW_LIMIT + 1024)))
        observer._read()
        self.assertTrue(observer.overflow.is_set())
        self.assertTrue(observer.done.is_set())
        self.assertLessEqual(len(observer.data), self.diag.RAW_LIMIT)
        with self.assertRaises(self.diag.DiagnosticError):
            observer.ready(.1)

    def test_complete_crash_block_cannot_survive_later_raw_output_overflow(self):
        observer = self.diag.CdbObserver.__new__(self.diag.CdbObserver)
        fixture = BoundedCdbParserTests()
        fixture.setUp()
        complete = fixture.transcript().encode("ascii")
        observer.data = bytearray()
        observer.lock = threading.Lock()
        observer.overflow = threading.Event()
        observer.done = threading.Event()
        observer.process = SimpleNamespace(stdout=io.BytesIO(complete + b"X" * self.diag.RAW_LIMIT))
        observer._read()
        self.assertTrue(observer.overflow.is_set())
        with self.assertRaises(self.diag.DiagnosticError):
            fixture.parse(observer.text())


class ReadOnlyDiagnosticWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.text = (ROOT / ".github/workflows/diagnose-wgc-helper.yml").read_text()
        self.configuration = "\n".join(line for line in self.text.splitlines()
                                       if not line.lstrip().startswith("#"))
        self.steps = [block for block in re.split(r"^      - ",
                      self.configuration.split("    steps:\n", 1)[1], flags=re.M)
                      if block.strip()]

    def test_only_first_manual_owned_main_dispatch_on_standard_windows(self):
        triggers = self.configuration.split("\non:\n", 1)[1].split("\npermissions:", 1)[0]
        self.assertEqual(triggers.strip(), "workflow_dispatch:")
        for required in ("github.event_name == 'workflow_dispatch'",
                         "github.event.repository.private == false",
                         "github.repository == 'Junming-Liang/vga-aram-helper'",
                         "github.ref == 'refs/heads/main'", "github.run_attempt == 1",
                         "    runs-on: windows-2022", "    timeout-minutes: 45"):
            self.assertIn(required, self.configuration)
        self.assertEqual(re.findall(r"^  ([\w-]+):", self.configuration.split("\njobs:\n", 1)[1], re.M),
                         ["owned-helper-crash"])
        for banned in ("matrix:", "workflow_run:", "schedule:", "push:",
                       "pull_request:", "self-hosted", "windows-latest", "continue-on-error:"):
            self.assertNotIn(banned, self.configuration)

    def test_readonly_tokens_and_exact_checkout(self):
        permissions = self.configuration.split("\npermissions:\n", 1)[1].split("\nconcurrency:", 1)[0]
        self.assertEqual(permissions.strip(), "contents: read\n  actions: read")
        self.assertEqual(self.configuration.count("permissions:"), 1)
        self.assertEqual(self.configuration.count("github.token"), 1)
        self.assertEqual(self.configuration.count("actions/checkout@"), 1)
        for required in ("ref: ${{ github.sha }}", "persist-credentials: false",
                         "$head -cne $env:GITHUB_SHA", "$env:GITHUB_RUN_ATTEMPT -cne '1'",
                         "git diff HEAD --exit-code --quiet"):
            self.assertIn(required, self.configuration)
        for banned in ("contents: write", "actions: write", "id-token:", "write-all",
                       "secrets.", "GH_TOKEN", "GITHUB_TOKEN", "ssh-key:", "gh auth",
                       "actions/download-artifact", "actions/cache", "git push", "gh release"):
            self.assertNotIn(banned, self.configuration)
        token_step = [step for step in self.steps if "github.token" in step]
        self.assertEqual(len(token_step), 1)
        self.assertIn("check_artifact_budget", token_step[0])
        self.assertIn("evidence_only=True", token_step[0])

    def test_one_harness_and_only_existing_two_helper_builds(self):
        harness = [step for step in self.steps
                   if "run: python tests/windows_wgc_helper_crash.py " in step]
        self.assertEqual(len(harness), 1)
        self.assertIn("--debugger-proof build/owned-crash/debugger.json", harness[0])
        self.assertIn("--reports build/owned-crash/evidence", harness[0])
        self.assertNotIn("        if:", harness[0])
        for script in ("build_wgc_capture.py", "build_wgc_session_capture.py"):
            self.assertEqual(self.configuration.count("run: python scripts/" + script), 1)
        self.assertEqual(self.configuration.count("run: ./scripts/prepare_windows_debugger.ps1"), 1)
        self.assertIn("-AcceptSdkLicense -InstallTimeoutMinutes 10", self.configuration)
        for banned in ("scripts/build_windows.py", "--freeze-only", "--app-scale 1.5",
                       "--app-scale 2", "windows_native_smoke.py", "retry", "rerun"):
            self.assertNotIn(banned, self.configuration)

    def test_upload_requires_validated_evidence_and_existing_budget(self):
        upload = [step for step in self.steps if "actions/upload-artifact@" in step]
        self.assertEqual(len(upload), 1)
        self.assertIn("steps.evidence.outcome == 'success'", upload[0])
        self.assertIn("steps.evidence_budget.outcome == 'success'", upload[0])
        self.assertIn("path: build/owned-crash/evidence/reports", upload[0])
        self.assertIn("retention-days: 1", upload[0])
        self.assertIn("if-no-files-found: error", upload[0])
        self.assertNotIn("continue-on-error", upload[0])


class WorkflowArtifactBoundaryTests(unittest.TestCase):
    """Execute the real inline allowlist, with only the schema validator stubbed."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.folder = self.root / "build/owned-crash/evidence/reports"
        self.folder.mkdir(parents=True)
        self.path = self.folder / "windows-wgc-helper-crash.json"
        self.path.write_text("{}", encoding="utf-8")
        text = (ROOT / ".github/workflows/diagnose-wgc-helper.yml").read_text()
        blocks = re.findall(r"^          @'\n(.*?)^          '@", text, re.M | re.S)
        self.assertEqual(len(blocks), 1)
        self.code = "\n".join(line[10:] if line else "" for line in blocks[0].splitlines())
        self.validator = Mock()

    def run_boundary(self):
        stub = ModuleType("windows_wgc_helper_crash")
        stub.validate_artifact = self.validator
        before = list(sys.path)
        try:
            with patch.object(Path, "cwd", return_value=self.root), \
                    patch.dict(sys.modules, {"windows_wgc_helper_crash": stub}), \
                    redirect_stdout(io.StringIO()):
                exec(compile(self.code, "workflow-inline-evidence", "exec"), {})
        finally:
            sys.path[:] = before

    def test_exact_json_reaches_validator_once(self):
        self.run_boundary()
        self.validator.assert_called_once_with({})

    def test_duplicate_and_nonfinite_json_rejected_before_schema_validation(self):
        for raw in ('{"key":0,"key":1}', '{"nested":{"key":0,"key":1}}',
                    '{"x":NaN}', '{"x":Infinity}', '{"x":-Infinity}',
                    '{"x":1e999}', '{"nested":[-1e999]}'):
            with self.subTest(raw=raw):
                self.path.write_text(raw)
                with self.assertRaises(RuntimeError):
                    self.run_boundary()
                self.validator.assert_not_called()

    def test_raw_logs_images_dumps_and_even_extra_text_are_not_uploadable(self):
        for name in ("raw-cdb.log", "screenshot.png", "helper.dmp", "helper.exe",
                     "windows-wgc-helper-crash.txt", "nested"):
            with self.subTest(name=name):
                extra = self.folder / name
                extra.write_text("private")
                try:
                    with self.assertRaises(RuntimeError):
                        self.run_boundary()
                finally:
                    extra.unlink()
        self.validator.assert_not_called()

    def test_byte_limit_and_missing_json_rejected(self):
        self.path.write_bytes(b" " * (1024 * 1024 + 1))
        with self.assertRaises(RuntimeError):
            self.run_boundary()
        self.path.unlink()
        with self.assertRaises(RuntimeError):
            self.run_boundary()
        self.validator.assert_not_called()

    @unittest.skipIf(sys.platform == "win32", "Unprivileged symlink creation is host dependent")
    def test_symlinked_file_is_not_followed(self):
        target = self.root / "secret.json"
        target.write_text("{}")
        self.path.unlink()
        self.path.symlink_to(target)
        with self.assertRaises(RuntimeError):
            self.run_boundary()
        self.validator.assert_not_called()


class DebuggerPreparationSourceContractTests(unittest.TestCase):
    """Static safety contracts; these do not execute or validate PowerShell."""

    def setUp(self):
        self.source = (ROOT / "scripts/prepare_windows_debugger.ps1").read_text()
        self.active = "\n".join(line for line in self.source.splitlines()
                                if not line.lstrip().startswith("#"))

    def test_signature_architecture_version_and_size_are_checked(self):
        for required in ("Get-AuthenticodeSignature", "'Valid'", "O=Microsoft Corporation",
                         "0x8664", "0x020b", "FileVersionInfo", "-Algorithm SHA256",
                         "ReparsePoint", "$record.size -ge 1024", "-RequireAmd64"):
            self.assertIn(required, self.active)

    def test_install_is_official_feature_only_once_bounded_and_no_reboot(self):
        self.assertEqual(len(re.findall(r"^\s+Invoke-OneInstaller \$installer \$work$",
                                       self.active, re.M)), 1)
        for required in ("$handler.AllowAutoRedirect = $false",
                         "$handler.UseDefaultCredentials = $false", "$uri.Scheme -eq 'https'",
                         "$allowedHosts -contains $uri.DnsSafeHost",
                         "OptionId.WindowsDesktopDebuggers", "'/features'", "'/norestart'",
                         "[ValidateRange(1, 10)]", "$process.WaitForExit($InstallTimeoutMinutes * 60 * 1000)",
                         "$process.ExitCode -ne 0", "Assert-NoPendingReboot",
                         "$licenseProof.sha256 -ceq $LicenseSha256",
                         "$licenseProof.size -eq $LicenseBytes"):
            self.assertIn(required, self.active)
        for banned in ("Restart-Computer", "Set-ItemProperty", "New-ItemProperty",
                       "bcdedit", "-SkipCertificateCheck", "Enable-PSRemoting",
                       "procdump", "AeDebug", "LocalDumps", "ExecutionPolicy"):
            self.assertNotIn(banned, self.active)

    def test_original_inputs_and_helpers_rechecked_before_verified_proof(self):
        for required in ("$Report.input_files = Get-CheckoutFiles $root",
                         "$Report.helper_files = Get-HelperFiles $root",
                         "$afterInputs = Get-CheckoutFiles $root",
                         "$afterHelpers = Get-HelperFiles $root",
                         "Tracked source bytes changed during debugger preparation.",
                         "Compiled helper bytes or manifests changed during debugger preparation.",
                         "$bytes.Length -le 256KB", "[IO.FileMode]::CreateNew"):
            self.assertIn(required, self.active)
        self.assertLess(self.active.index("$afterHelpers ="),
                        self.active.index("$Report.status = 'verified'"))


if __name__ == "__main__":
    unittest.main()

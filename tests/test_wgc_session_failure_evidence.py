"""Deterministic pipe faults and bounded diagnostics, not Windows capture proof."""
import io
import json
import threading
import unittest
from unittest.mock import patch

from tests import test_wgc_session_protocol as fixtures
from tests.test_wgc_session_protocol import (
    FakeProcess, packet, ROI, clock_diagnostic, diagnostic_bytes)
import wgc_session_capture as session
from wgc_capture import WgcError


class ProtocolFailureEvidenceTests(unittest.TestCase):
    def fixture(self):
        fixture = fixtures.WrapperTests(); fixture.setUp()
        def cleanup():
            fixture.capture.close()
            if fixture.capture._transport:
                fixture.process.exit(-9)
                self.assertTrue(fixture.capture._transport.ready_for_replacement.wait(2))
            fixture.doCleanups()
        self.addCleanup(cleanup)
        return fixture

    def capture_error(self, fixture):
        with self.assertRaises(WgcError) as raised:
            fixture.capture.capture(fixture.target, fixture.rect, ROI)
        return raised.exception

    def test_partial_reads_are_valid_and_eof_reports_only_stage_and_counts(self):
        class Fragmented(io.BytesIO):
            def read(self, size):return super().read(min(size, 3))
        self.assertEqual(session._read_exact(Fragmented(b'12345678'), 8), b'12345678')
        for stage, expected, actual in (('response_header', 64, 63),
                ('pixel_payload', 1024, 4), ('idle_trailer', 32, 31)):
            with self.subTest(stage=stage), self.assertRaises(WgcError) as raised:
                session._read_exact(Fragmented(b'X' * actual), expected, stage=stage)
            self.assertEqual(raised.exception.protocol_diagnostic,
                dict(schema_version=1, reason='stdout_eof', stage=stage,
                     expected_bytes=expected, received_bytes=actual))
            self.assertNotIn('XXX', json.dumps(raised.exception.protocol_diagnostic))

    def test_header_id_and_generation_mismatch_exposes_bits_never_values(self):
        data = packet(123456789, 987654321)
        with self.assertRaises(WgcError) as raised:
            session._validate_header(data[:session.RESPONSE.size], ROI, 1, 2)
        diagnostic = raised.exception.protocol_diagnostic
        self.assertEqual(diagnostic['reason'], 'header_mismatch')
        self.assertEqual(diagnostic['mismatch_mask'], (1 << 3) | (1 << 4))
        serialized = json.dumps(diagnostic)
        self.assertNotIn('123456789', serialized); self.assertNotIn('987654321', serialized)
        self.assertEqual(diagnostic['expected_width'], ROI[2])
        self.assertEqual(diagnostic['observed_payload_bytes'], ROI[2] * ROI[3] * 4)

    def test_fragmented_request_writes_are_completed_without_extra_request(self):
        fixture = self.fixture(); original = fixture.process.stdin.write
        pending = bytearray(); fragments = []
        def write(data):
            if bytes(data) == b'C':return original(data)
            count = min(3, len(data)); pending.extend(data[:count]); fragments.append(count)
            if len(pending) == session.REQUEST.size:
                original(pending); pending.clear()
            return count
        fixture.process.stdin.write = write
        image = fixture.capture.capture(fixture.target, fixture.rect, ROI)
        self.assertEqual(image.size, tuple(ROI[2:]))
        self.assertGreater(len(fragments), 1); self.assertEqual(sum(fragments), session.REQUEST.size)
        self.assertEqual(len(fixture.process.writes), 2)
        self.assertIsNone(fixture.capture.failure_evidence())

    def test_transport_fixed_branches_preserve_failure_and_allow_new_capture_only_after_cleanup(self):
        for fault, reason, stage in (
                ('magic', 'header_mismatch', 'response_header'),
                ('dimensions', 'header_mismatch', 'response_header'),
                ('header_eof', 'stdout_eof', 'response_header'),
                ('pixels_eof', 'stdout_eof', 'pixel_payload'),
                ('idle_eof', 'stdout_eof', 'idle_trailer'),
                ('trailing', 'stdout_trailing', 'after_response'),
                ('zero_write', 'stdin_write_zero', 'request')):
            with self.subTest(fault=fault):
                fixture = self.fixture(); process = fixture.process
                def response(request, generation):
                    data = packet(request, generation, 100+request*10, 101+request*10, 102+request*10)
                    if fault == 'magic':return b'PRIVATE!'+data[8:]
                    if fault == 'dimensions':
                        header = list(session.RESPONSE.unpack(data[:64])); header[5] += 1
                        return session.RESPONSE.pack(*header)+data[64:]
                    if fault == 'trailing':return data+b'PRIVATE_EXTRA'
                    if fault.endswith('_eof'):
                        length = {'header_eof':63, 'pixels_eof':68, 'idle_eof':len(data)-1}[fault]
                        process.stdout.feed(data[:length]); process.exit(0); return None
                    return data
                process.response = response
                if fault == 'zero_write':
                    write = process.stdin.write
                    process.stdin.write = lambda data:write(data) if bytes(data)==b'C' else 0
                error = self.capture_error(fixture)
                self.assertEqual(error.status, 'invalid-reply')
                self.assertEqual((error.protocol_diagnostic['reason'], error.protocol_diagnostic['stage']), (reason, stage))
                first_transport = fixture.capture._transport
                self.assertTrue(first_transport.ready_for_replacement.wait(2))
                evidence = session.sanitize_session_failure_evidence(error.failure_evidence)
                self.assertTrue(evidence['cleanup_complete'])
                self.assertNotIn('PRIVATE', json.dumps(evidence))
                fixture.process = FakeProcess()
                image = fixture.capture.capture(fixture.target, fixture.rect, ROI)
                self.assertEqual(image.size, tuple(ROI[2:]))
                self.assertEqual(fixture.spawn.call_count, 2)
                self.assertIsNot(fixture.capture._transport, first_transport)
                # Finish this nested fixture before restoring its global patches.
                fixture.capture.close(); self.assertTrue(fixture.capture._transport.ready_for_replacement.wait(2))
                fixture.doCleanups()

    def test_peek_failure_and_stderr_overflow_are_distinct_and_bounded(self):
        fixture = self.fixture()
        with patch.object(session, '_pipe_available', side_effect=session._invalid_reply('stdout_peek_failed', 'after_response')):
            error = self.capture_error(fixture)
        self.assertEqual(error.protocol_diagnostic['reason'], 'stdout_peek_failed')
        self.assertTrue(fixture.capture._transport.ready_for_replacement.wait(2))
        fixture.process = FakeProcess(response=lambda *args: None)
        fixture.process.stderr.feed(b'PRIVATE' * 200)
        error = self.capture_error(fixture)
        self.assertEqual(error.protocol_diagnostic['reason'], 'stderr_oversize')
        self.assertEqual(error.protocol_diagnostic['received_bytes'], session.MAX_DIAGNOSTIC_BYTES+1)
        self.assertTrue(fixture.capture._transport.ready_for_replacement.wait(2))
        self.assertEqual(error.failure_evidence['stderr_bytes'], session.MAX_DIAGNOSTIC_BYTES+1)
        self.assertNotIn('PRIVATE', json.dumps(error.failure_evidence))

    def test_native_crash_exit_is_preserved_without_claiming_native_guard(self):
        fixture = self.fixture()
        def crash(*args):fixture.process.exit(-1073741819)
        fixture.process.response = crash
        error = self.capture_error(fixture)
        self.assertEqual(error.status, 'invalid-reply')
        self.assertTrue(fixture.capture._transport.ready_for_replacement.wait(2))
        self.assertEqual(error.failure_evidence['process_exit_code'], -1073741819)
        self.assertEqual(error.failure_evidence['protocol_diagnostic']['reason'], 'stdout_eof')
        self.assertIsNone(error.failure_evidence['native_diagnostic'])

    def test_late_native_exit_updates_same_bounded_dict_without_reinterpreting_error(self):
        fixture = self.fixture(); process = FakeProcess(delayed_kill=True); fixture.process = process
        process.response = lambda *args: process.stdout.close()
        error = self.capture_error(fixture); retained = error.failure_evidence
        transport = fixture.capture._transport
        self.assertEqual(error.status, 'invalid-reply')
        self.assertFalse(retained['cleanup_complete']); self.assertIsNone(retained['native_diagnostic'])
        self.assertFalse(transport.ready_for_replacement.is_set())
        self.assertEqual(self.capture_error(fixture).status, 'cleanup-pending')
        self.assertEqual(fixture.spawn.call_count, 1)
        process.stderr.feed(diagnostic_bytes(clock_diagnostic())); process.exit(12)
        self.assertTrue(transport.ready_for_replacement.wait(2))
        self.assertIs(retained, error.failure_evidence)
        self.assertEqual(error.status, 'invalid-reply')
        self.assertEqual(retained['process_exit_code'], 12)
        self.assertEqual(retained['native_diagnostic'], clock_diagnostic())
        self.assertTrue(retained['cleanup_complete'])
        self.assertEqual(session.sanitize_failure_evidence(retained), fixture.capture.failure_evidence())
        fixture.process = FakeProcess()
        self.assertEqual(fixture.capture.capture(fixture.target, fixture.rect, ROI).size, tuple(ROI[2:]))
        self.assertEqual(fixture.spawn.call_count, 2)

    def test_native_status_translation_retains_original_protocol_location(self):
        fixture = self.fixture()
        def stop(*args):
            fixture.process.stderr.feed(diagnostic_bytes(clock_diagnostic())); fixture.process.exit(12)
        fixture.process.response = stop
        error = self.capture_error(fixture)
        self.assertEqual(error.status, 'stale')
        self.assertTrue(fixture.capture._transport.ready_for_replacement.wait(2))
        self.assertEqual(error.failure_evidence['protocol_diagnostic']['stage'], 'response_header')
        self.assertEqual(error.failure_evidence['native_diagnostic'], clock_diagnostic())

    def test_concurrent_reader_keeps_valid_snapshot_through_late_cleanup(self):
        fixture = self.fixture(); process = FakeProcess(delayed_kill=True); fixture.process = process
        process.response = lambda *args: process.stdout.close()
        error = self.capture_error(fixture); retained = error.failure_evidence
        transport = fixture.capture._transport; started = threading.Event(); stop = threading.Event()
        failures = []; observed = set()
        def read():
            try:
                while not stop.is_set():
                    evidence = session.sanitize_session_failure_evidence(retained)
                    if evidence is None:raise AssertionError('publication exposed invalid snapshot')
                    observed.add(evidence['cleanup_complete']); started.set()
            except BaseException as error:failures.append(error)
        reader = threading.Thread(target=read); reader.start()
        try:
            self.assertTrue(started.wait(2))
            process.stderr.feed(diagnostic_bytes(clock_diagnostic())); process.exit(12)
            self.assertTrue(transport.ready_for_replacement.wait(2))
            for _ in range(1000):transport._publish_failure_evidence(cleanup_complete=True)
        finally:
            stop.set(); reader.join(2)
        self.assertFalse(reader.is_alive()); self.assertEqual(failures, [])
        self.assertEqual(observed, {False, True}); self.assertIs(error.failure_evidence, retained)
        retained['raw_stderr'] = 'PRIVATE'
        transport._publish_failure_evidence(cleanup_complete=True)
        self.assertNotIn('raw_stderr', retained)

    def test_sanitizer_reads_detached_snapshot_before_later_validation(self):
        outer = dict(schema_version=1, protocol_diagnostic=None, process_exit_code=12, stderr_bytes=0,
            cleanup_complete=False, termination_requested_while_alive=False,
            native_diagnostic=None, shutdown_diagnostic=None)
        original = session.sanitize_protocol_diagnostic
        def interleaved(value):
            outer.clear()
            return original(value)
        with patch.object(session, 'sanitize_protocol_diagnostic', side_effect=interleaved):
            detached = session.sanitize_failure_evidence(outer)
        self.assertFalse(detached['cleanup_complete']); self.assertEqual(detached['process_exit_code'], 12)

    def test_delayed_nonterminal_publisher_cannot_erase_completed_cleanup(self):
        fixture = self.fixture(); process = FakeProcess(delayed_kill=True); fixture.process = process
        process.response = lambda *args: process.stdout.close()
        error = self.capture_error(fixture); retained = error.failure_evidence
        transport = fixture.capture._transport; collected = threading.Event(); resume = threading.Event()
        original = transport.failure_evidence; delayed = None
        def collect(*, cleanup_complete=None):
            evidence = original(cleanup_complete=cleanup_complete)
            if threading.current_thread() is delayed:
                collected.set()
                if not resume.wait(2):raise AssertionError('Delayed publisher was not released')
            return evidence
        with patch.object(transport, 'failure_evidence', side_effect=collect):
            delayed = threading.Thread(target=transport._publish_failure_evidence); delayed.start()
            try:
                self.assertTrue(collected.wait(2))
                process.stderr.feed(diagnostic_bytes(clock_diagnostic())); process.exit(12)
                self.assertTrue(transport.ready_for_replacement.wait(2))
                terminal = session.sanitize_session_failure_evidence(retained)
                self.assertTrue(terminal['cleanup_complete']); self.assertEqual(terminal['process_exit_code'], 12)
            finally:
                resume.set(); delayed.join(2)
        self.assertFalse(delayed.is_alive()); self.assertEqual(retained, terminal)
        self.assertIs(retained, error.failure_evidence)

    def test_nonterminal_revoke_does_not_wait_for_evidence_lock(self):
        fixture = self.fixture()
        fixture.capture.capture(fixture.target, fixture.rect, ROI)
        transport = fixture.capture._transport; returned = threading.Event()
        error = WgcError('cancelled', 'Owned diagnostic test')
        transport._evidence_lock.acquire()
        caller = threading.Thread(target=lambda:(transport.revoke(error), returned.set()))
        try:
            caller.start(); self.assertTrue(returned.wait(.5))
            self.assertIs(error.failure_evidence, transport._failure_evidence)
            self.assertIsNotNone(session.sanitize_session_failure_evidence(error.failure_evidence))
        finally:
            transport._evidence_lock.release(); caller.join(2)
        self.assertFalse(caller.is_alive())

    def test_sanitizers_reject_unknown_fields_raw_payloads_and_invalid_numbers(self):
        good = dict(schema_version=1, reason='stdout_eof', stage='pixel_payload', expected_bytes=1024, received_bytes=3)
        for change in ({'reason':'PRIVATE'}, {'stage':'PRIVATE'}, {'raw':'PRIVATE_PIXELS'},
                       {'request_id':123}, {'mismatch_mask':1024}, {'received_bytes':True}, {'expected_bytes':2**32}):
            self.assertIsNone(session.sanitize_protocol_diagnostic(dict(good, **change)))
        outer = dict(schema_version=1, protocol_diagnostic=good, process_exit_code=12, stderr_bytes=347,
            cleanup_complete=True, termination_requested_while_alive=False,
            native_diagnostic=clock_diagnostic(), shutdown_diagnostic=None)
        detached = session.sanitize_failure_evidence(outer)
        detached['native_diagnostic']['clock']['frame_100ns'] = 999
        self.assertEqual(outer['native_diagnostic']['clock']['frame_100ns'], 101)
        for change in ({'raw_stderr':'PRIVATE'}, {'process_exit_code':True}, {'stderr_bytes':1026},
                       {'native_diagnostic':{'raw':'PRIVATE'}}, {'shutdown_diagnostic':{'raw':'PRIVATE'}},
                       {'cleanup_complete':1}, {'protocol_diagnostic':dict(good, raw='PRIVATE')}):
            self.assertIsNone(session.sanitize_session_failure_evidence(dict(outer, **change)))


if __name__ == '__main__':unittest.main()

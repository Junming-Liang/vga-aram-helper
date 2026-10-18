"""Synthetic failure diagnostics and exact manual-switch scheduling contracts.

Portable Qt/OCR tests do not establish Windows helper or live-game acceptance.
"""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from tests import windows_native_smoke as gate
from tests import test_native_smoke_ocr_scope as scope


class ManualSwitchEvidenceTests(unittest.TestCase):
    def test_gate_requires_exact_eight_successful_captures(self):
        valid=dict(required=8,attempted=8,completed=8)
        gate.validate_manual_hero_switches(valid)
        for value in (None,{},dict(valid,completed=7),dict(valid,attempted=9),
                      dict(valid,required=True),dict(valid,completed=8.),dict(valid,extra=True)):
            with self.subTest(value=value),self.assertRaises(RuntimeError):
                gate.validate_manual_hero_switches(value)

    def test_summary_drops_unbounded_or_private_failure_fields(self):
        evidence=dict(initial=dict(capture_diagnostic=dict(capture_status='invalid-reply',raw='private'),
            session_failure={'raw':'private'},cleanup_pending=True,raw='private'),
            final=dict(capture_diagnostic=dict(capture_status='private'),session_failure=None,cleanup_pending=False),
            cleanup_wait_ms=100.,cleanup_deadline_reached=False,revocation_requested=True,raw='private')
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'failure.json'
            path.write_text(json.dumps(dict(status='failed',capture_failure_evidence=evidence,
                manual_hero_switches=dict(required=8,attempted=3,completed=2,raw='private'))))
            result=gate.native_failure_summary(path)
        self.assertEqual(result['manual_hero_switches'],dict(required=8,attempted=3,completed=2))
        self.assertEqual(result['capture_failure_evidence']['initial']['capture_diagnostic'],{'capture_status':'invalid-reply'})
        self.assertEqual(result['capture_failure_evidence']['final']['capture_diagnostic'],{})
        self.assertNotIn('private',json.dumps(result))
        self.assertLess(len(json.dumps(result)),4096)
        for bad in (True,-1,3_600_001,float('inf'),float('nan'),'private'):
            self.assertNotIn('cleanup_wait_ms',gate.sanitize_capture_failure_evidence(dict(evidence,cleanup_wait_ms=bad)))


@unittest.skipIf(scope.fixture.QtWidgets is None,'Optional Qt runtime unavailable')
class FailureCleanupObservationTests(unittest.TestCase):
    def test_terminal_failure_keeps_cadence_disabled_until_late_cleanup_finishes(self):
        import native_smoke
        from PySide6 import QtCore,QtWidgets,QtTest
        app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        timer=QtCore.QTimer();self.addCleanup(timer.stop);fired=[]
        timer.timeout.connect(lambda:fired.append(True))
        capture=SimpleNamespace(close=Mock(),capture=Mock(),cleanup_pending=True)
        restored=SimpleNamespace(close=Mock(),capture=Mock(),cleanup_pending=False,
            last_capture_diagnostic={'capture_status':'ok'})
        fake_app=SimpleNamespace(platformName=lambda:'offscreen',exit=Mock())
        original=lambda delay=None:timer.start(delay or 0)
        control=SimpleNamespace(current_version='owned',closed=False,monitor=timer,
            schedule_capture=original,capture=capture,close=Mock(),stop_monitor=Mock())
        control._smoke_duty_outer_cleanup=lambda:setattr(control,'capture',restored)
        with tempfile.TemporaryDirectory() as folder,patch.object(native_smoke.QtWidgets.QApplication,'instance',return_value=fake_app):
            path=Path(folder)/'failure.json'
            native_smoke.start_smoke(control,path,Path(folder)/'unused.png')
            control.stop_monitor.assert_called_once();fake_app.exit.assert_not_called()
            self.assertIs(control.capture,restored);capture.close.assert_called_once();restored.close.assert_not_called()
            control.schedule_capture(0);app.processEvents()
            self.assertFalse(timer.isActive());self.assertEqual(fired,[])
            capture.cleanup_pending=False;QtTest.QTest.qWait(40)
            fake_app.exit.assert_called_once_with(1);control.close.assert_called_once()
            self.assertIs(control.schedule_capture,original)
            report=json.loads(path.read_text());self.assertEqual(report['status'],'failed')
            self.assertEqual(report['capture_failure_evidence']['final']['capture_diagnostic'],{})
        capture.capture.assert_not_called()

    def test_failure_waits_for_late_cleanup_without_recapture_or_status_change(self):
        from native_smoke import _collect_failed_capture_cleanup
        report=dict(status='failed',error='original');queued=[];clock=[0.];done=Mock();save=Mock()
        capture=SimpleNamespace(close=Mock(),capture=Mock())
        before=dict(capture_diagnostic={'capture_status':'invalid-reply'},session_failure=None,cleanup_pending=True)
        after=dict(before,cleanup_pending=False)
        with patch('native_smoke._capture_failure_snapshot',side_effect=[before,before,after]):
            _collect_failed_capture_cleanup(SimpleNamespace(capture=capture),report,save,done,
                clock=lambda:clock[0],later=lambda delay,fn:queued.append((delay,fn)))
            self.assertEqual(queued[0][0],20);done.assert_not_called()
            clock[0]=.04;queued.pop(0)[1]()
        capture.close.assert_called_once();capture.capture.assert_not_called();done.assert_called_once()
        self.assertEqual(report['status'],'failed');self.assertEqual(report['error'],'original')
        self.assertTrue(report['capture_failure_evidence']['initial']['cleanup_pending'])
        self.assertFalse(report['capture_failure_evidence']['final']['cleanup_pending'])
        self.assertEqual(report['capture_failure_evidence']['cleanup_wait_ms'],40.)

    def test_unconfirmed_cleanup_stops_at_deadline_and_preserves_failure(self):
        from native_smoke import _collect_failed_capture_cleanup
        report=dict(status='failed');queued=[];clock=[0.];done=Mock()
        capture=SimpleNamespace(close=Mock(),capture=Mock())
        snapshot=dict(capture_diagnostic={},session_failure=None,cleanup_pending=True)
        with patch('native_smoke._capture_failure_snapshot',return_value=snapshot):
            _collect_failed_capture_cleanup(SimpleNamespace(capture=capture),report,lambda:None,done,
                clock=lambda:clock[0],later=lambda delay,fn:queued.append(fn))
            clock[0]=2.001;queued.pop(0)()
        done.assert_called_once();capture.capture.assert_not_called();self.assertEqual(queued,[])
        self.assertEqual(report['status'],'failed')
        self.assertTrue(report['capture_failure_evidence']['cleanup_deadline_reached'])
        self.assertTrue(report['capture_failure_evidence']['final']['cleanup_pending'])
        self.assertEqual(report['capture_failure_evidence']['cleanup_wait_ms'],2001.)


@unittest.skipUnless(scope.rounds.QtWidgets is not None and scope.rounds.OCR_AVAILABLE,
                     'Optional Qt/local OCR dependencies unavailable')
class RealOcrManualSwitchTests(unittest.TestCase):
    setUpClass=classmethod(scope.NativeSmokeLifecycleSequenceTests.setUpClass.__func__)
    setUp=scope.NativeSmokeLifecycleSequenceTests.setUp
    wait=scope.NativeSmokeLifecycleSequenceTests.wait
    dispose_window=scope.NativeSmokeLifecycleSequenceTests.dispose_window
    record_result=scope.NativeSmokeLifecycleSequenceTests.record_result
    record_error=scope.NativeSmokeLifecycleSequenceTests.record_error
    observe_current=scope.NativeSmokeLifecycleSequenceTests.observe_current

    def test_eight_exact_qt_manual_switches_each_accept_fresh_real_ocr(self):
        from native_smoke import _exercise_manual_hero_switches,_manual_smoke_cadence
        self.observe_current();self.observe_current();w=self.window;report={}
        restore=_manual_smoke_cadence(w);self.addCleanup(restore)
        before=w._completed_capture_serial
        with patch.object(w.hero_matcher,'recognize',side_effect=AssertionError('Manual capture used matcher')):
            _exercise_manual_hero_switches(w,self.observe_current,list(scope.rounds.NAMES[:3]),report)
        self.assertEqual(w._completed_capture_serial,before+8)
        self.assertEqual(report['manual_hero_switches'],dict(required=8,attempted=8,completed=8))
        self.assertFalse(w.monitor.isActive());self.assertEqual(self.errors,[])

    def test_failed_third_switch_is_not_retried_or_counted_as_success(self):
        from native_smoke import _exercise_manual_hero_switches,_manual_smoke_cadence
        from screen_capture import CapturePaused
        self.observe_current();self.observe_current();w=self.window;report={};calls=[]
        restore=_manual_smoke_cadence(w);self.addCleanup(restore)
        def acquire():
            calls.append(True)
            if len(calls)==3:
                w.overlay.hide();raise CapturePaused('Owned protocol failure')
            return self.observe_current()
        with self.assertRaisesRegex(CapturePaused,'Owned protocol failure'):
            _exercise_manual_hero_switches(w,acquire,list(scope.rounds.NAMES[:3]),report)
        self.assertEqual(len(calls),3)
        self.assertEqual(report['manual_hero_switches'],dict(required=8,attempted=3,completed=2))
        self.assertFalse(w.overlay.isVisible());self.assertFalse(w.monitor.isActive())
        # A later explicit observation can recover; the failed diagnostic loop
        # never makes this request or changes its recorded successful count.
        w.confirm();self.observe_current();self.assertTrue(w.overlay.isVisible())
        self.assertEqual(report['manual_hero_switches']['completed'],2)


if __name__=='__main__':unittest.main()

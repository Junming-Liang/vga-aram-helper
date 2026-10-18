"""Owned window-table/Qt routing regressions; not real-client compatibility.

Public Win32 enumeration/focus methods run against an owned table. Signature
and process metadata are injected, and jobs are intercepted before pixels or
APIs are read. No screenshot, credential, private API, or third-party code.
"""
import os
import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

from automatic_windows import AutomaticWindowPolicy
from screen_capture import Win32Capture, WindowInfo, ClientRect, CapturePaused
from session_windows import ProcessMetadata, SessionWindowPolicy
from tests import test_native_capture_worker as fixture

CLIENT=WindowInfo(101,201,'Owned client','RCLIENT')
GAME=WindowInfo(102,202,'Owned game','RiotWindowClass')


class OwnedWindowTable:
    windows=Win32Capture.windows
    discovery_snapshot=Win32Capture.discovery_snapshot
    foreground=Win32Capture.foreground

    def __init__(self,windows=(CLIENT,GAME)):
        self.rows=list(windows)
        self.hidden=set();self.minimized=set();self.foreground_hwnd=CLIENT.hwnd
        self.roots={};self.enum_cb=lambda callback:callback
        self.u=SimpleNamespace(
            IsWindowVisible=lambda hwnd:any(w.hwnd==hwnd for w in self.rows) and hwnd not in self.hidden,
            IsIconic=lambda hwnd:hwnd in self.minimized,
            EnumWindows=lambda callback,_:[callback(w.hwnd,0) for w in self.rows],
            GetForegroundWindow=lambda:self.foreground_hwnd,
            GetAncestor=lambda hwnd,flag:self.roots.get(hwnd,hwnd))

    def info(self,hwnd):
        return next(window for window in self.rows if window.hwnd==hwnd)

    def rect(self,target):
        if target not in self.rows or target.hwnd in self.hidden or target.hwnd in self.minimized:
            raise CapturePaused('Owned unavailable window')
        return ClientRect(0,0,900,600)


def metadata():
    return {201:ProcessMetadata(r'C:\Owned\LeagueClientUx.exe',100),
            202:ProcessMetadata(r'C:\Owned\Game\League of Legends.exe',200)}


class ForegroundPolicyTests(unittest.TestCase):
    def setUp(self):
        self.table=OwnedWindowTable();self.meta=metadata()
        self.policy=AutomaticWindowPolicy(resolver=self.meta.__getitem__,verifier=lambda path:True)

    def scan(self):return self.policy.discover(**self.table.discovery_snapshot())

    def bind(self):
        result=self.scan()
        self.assertTrue(self.policy.adopt(result,**self.table.discovery_snapshot()))
        return result.candidate

    def test_snapshot_separates_availability_without_losing_minimized_identity(self):
        self.table.minimized.add(GAME.hwnd)
        value=self.table.discovery_snapshot()
        self.assertEqual(set(value['windows']),{CLIENT,GAME})
        self.assertEqual(value['available_hwnds'],frozenset({CLIENT.hwnd}))
        self.assertEqual(value['foreground_hwnd'],CLIENT.hwnd)
        self.assertEqual(self.bind().window,CLIENT)

    def test_hidden_game_is_absent_and_blank_client_caption_still_works(self):
        self.table.hidden.add(GAME.hwnd)
        self.table.rows[0]=replace(CLIENT,title='')
        self.assertEqual(len(self.table.discovery_snapshot()['windows']),1)
        self.assertEqual(self.bind().window.identity,CLIENT.identity)

    def test_foreground_role_keeps_same_role_ambiguity_even_if_twin_minimized(self):
        twin=replace(CLIENT,hwnd=103)
        self.table.rows.append(twin);self.table.minimized.add(twin.hwnd)
        result=self.scan()
        self.assertIsNone(result.candidate)
        self.assertEqual(result.reason_code,'multiple_windows')
        self.assertEqual(dict(result.diagnostics)['eligible_client_count'],2)

    def test_minimized_other_installation_still_blocks_initial_binding(self):
        other=replace(GAME,hwnd=103,pid=203)
        self.meta[203]=ProcessMetadata(r'D:\Other\Game\League of Legends.exe',300)
        self.table.rows.append(other);self.table.minimized.add(other.hwnd)
        self.assertEqual(self.scan().reason_code,'multiple_installations')

    def test_foreground_cannot_bypass_signature_failure_or_fall_back(self):
        self.policy.verifier=lambda path:path.endswith('league of legends.exe')
        result=self.scan()
        self.assertIsNone(result.candidate)
        self.assertEqual(result.reason_code,'signature_unverified')
        self.assertEqual(result.confirmation.window,CLIENT)

    def test_foreground_changes_between_discovery_and_adoption_reject_old_role(self):
        result=self.scan();self.table.foreground_hwnd=GAME.hwnd
        self.assertFalse(self.policy.adopt(result,**self.table.discovery_snapshot()))
        self.assertEqual(self.bind().window,GAME)

    def test_new_minimized_twin_before_adoption_still_rejects_old_candidate(self):
        result=self.scan();twin=replace(CLIENT,hwnd=103)
        self.table.rows.append(twin);self.table.minimized.add(twin.hwnd)
        self.assertFalse(self.policy.adopt(result,**self.table.discovery_snapshot()))

    def test_pid_reuse_and_path_change_reject_old_candidate_despite_foreground(self):
        for changed in (ProcessMetadata(self.meta[201].path,101),
                        ProcessMetadata(r'C:\Owned\chrome.exe',100)):
            with self.subTest(changed=changed):
                self.meta=metadata();self.policy.resolver=self.meta.__getitem__
                result=self.scan();self.meta[201]=changed
                self.assertFalse(self.policy.adopt(result,**self.table.discovery_snapshot()))

    def test_no_foreground_preserves_bound_role_and_never_promotes_minimized_target(self):
        self.assertEqual(self.bind().window,CLIENT)
        for hwnd in (0,999):
            self.table.foreground_hwnd=hwnd
            self.assertEqual(self.bind().window,CLIENT)
        self.table.minimized.update({CLIENT.hwnd,GAME.hwnd})
        self.assertIsNone(self.scan().candidate)

    def test_all_minimized_reports_unavailable_instead_of_false_ambiguity(self):
        for windows in ((CLIENT,),(CLIENT,GAME)):
            with self.subTest(windows=windows):
                self.table.rows=list(windows);self.table.minimized={window.hwnd for window in windows}
                result=self.scan()
                self.assertIsNone(result.candidate);self.assertIsNone(result.confirmation)
                self.assertEqual(result.reason_code,'window_unavailable')
                self.assertEqual(dict(result.diagnostics)['preferred_count'],0)
                self.assertEqual(dict(result.diagnostics)['eligible_client_count'],1)

    def test_all_minimized_still_preserves_other_installation_rejection(self):
        other=replace(GAME,hwnd=103,pid=203)
        self.table.rows=[CLIENT,other];self.table.minimized={CLIENT.hwnd,other.hwnd}
        self.meta[203]=ProcessMetadata(r'D:\Other\Game\League of Legends.exe',300)
        result=self.scan()
        self.assertIsNone(result.candidate)
        self.assertEqual(result.reason_code,'multiple_installations')

    def test_foreground_child_uses_only_root_and_does_not_promote_child(self):
        self.table.foreground_hwnd=301;self.table.roots[301]=CLIENT.hwnd
        self.assertEqual(self.bind().window,CLIENT)
        self.assertTrue(self.table.foreground(CLIENT))

    def test_role_follow_optout_is_applied_before_foreground_preference(self):
        self.policy.follow_roles=False;self.assertEqual(self.bind().window,CLIENT)
        self.table.foreground_hwnd=GAME.hwnd
        self.assertEqual(self.bind().window,CLIENT)
        self.assertFalse(self.table.foreground(CLIENT))

    def test_unknown_foreground_caption_and_class_do_not_grant_permission(self):
        unknown=WindowInfo(103,203,'League of Legends','RCLIENT')
        self.meta[203]=ProcessMetadata(r'C:\Owned\chrome.exe',300)
        self.assertEqual(self.bind().window,CLIENT)
        self.table.rows.append(unknown);self.table.foreground_hwnd=unknown.hwnd
        self.assertEqual(self.bind().window,CLIENT)
        self.assertFalse(self.policy.permits(unknown,**self.table.discovery_snapshot()))

    def test_installation_confirmation_accepts_exact_choice_while_dialog_owns_focus(self):
        self.policy.verifier=lambda path:False
        candidate=self.scan().confirmation
        self.assertEqual(candidate.window,CLIENT)
        self.table.foreground_hwnd=999
        self.assertTrue(self.policy.confirm_installation(candidate,**self.table.discovery_snapshot()))
        self.assertIsNone(self.policy.bound)
        self.assertFalse(self.policy.permits(CLIENT,**self.table.discovery_snapshot()))
        # Consent does not carry a stale role into subsequent discovery.
        self.table.foreground_hwnd=GAME.hwnd
        self.assertEqual(self.bind().window,GAME)

    def test_dialog_focus_fallback_never_relaxes_identity_ambiguity_or_availability(self):
        for case in ('pid','path','minimized','duplicate','other-install','foreground-game','stop'):
            with self.subTest(case=case):
                self.setUp();self.policy.verifier=lambda path:False
                candidate=self.scan().confirmation;self.table.foreground_hwnd=999
                if case=='pid':self.meta[201]=replace(self.meta[201],created=101)
                elif case=='path':self.meta[201]=replace(self.meta[201],path=r'C:\Owned\chrome.exe')
                elif case=='minimized':self.table.minimized.add(CLIENT.hwnd)
                elif case=='duplicate':
                    self.table.rows.append(replace(CLIENT,hwnd=103));self.table.minimized.add(103)
                elif case=='other-install':
                    self.table.rows.append(replace(CLIENT,hwnd=103,pid=203))
                    self.meta[203]=ProcessMetadata(r'D:\Other\LeagueClientUx.exe',300)
                elif case=='foreground-game':self.table.foreground_hwnd=GAME.hwnd
                else:self.policy.stop()
                self.assertFalse(self.policy.confirm_installation(candidate,**self.table.discovery_snapshot()))
                self.assertIsNone(self.policy.confirmed_root)


@unittest.skipIf(fixture.QtWidgets is None,'Optional Qt runtime missing')
class NativeSelectionWindowRoutingTests(unittest.TestCase):
    setUpClass=classmethod(fixture.NativeCaptureWorkerTests.setUpClass.__func__)
    wait=fixture.NativeCaptureWorkerTests.wait
    dispose_window=fixture.NativeCaptureWorkerTests.dispose_window

    def setUp(self):
        fixture.NativeCaptureWorkerTests.setUp(self)
        from native_ui import ControlWindow
        w=self.window;w.stop_monitor()
        self.table=OwnedWindowTable();self.meta=metadata();self.jobs=[]
        self.verify=lambda path:True
        w.capture=self.table
        w.target_allowed=lambda:ControlWindow.target_allowed(w)
        w.capture_metadata=lambda:ControlWindow.capture_metadata(w)
        w.spawn=lambda kind,fn,generation=None:self.jobs.append((kind,fn,generation))

    def start_auto(self,*,follow=True):
        w=self.window
        w.client_follow.setChecked(follow)
        w.window_list.blockSignals(True)
        w.window_list.clear();w.window_list.addItem('Owned automatic',None)
        w.window_list.blockSignals(False)
        factory=lambda **kw:AutomaticWindowPolicy(resolver=self.meta.__getitem__,verifier=self.verify,**kw)
        with patch('automatic_windows.AutomaticWindowPolicy',side_effect=factory):w.start_monitor()
        w.monitor.stop()
        self.assertTrue(w.state.running)

    def scan(self):
        w=self.window
        if not self.jobs:w.queue_discovery(force=True)
        kind,fn,generation=self.jobs.pop(0)
        self.assertEqual(kind,'windows')
        result=fn();w.task_result(kind,result,generation)
        return result

    def assert_dispatch(self,expected):
        w=self.window;self.assertEqual(self.jobs,[])
        with patch('native_ui.QtCore.QTimer.singleShot',side_effect=lambda delay,fn:fn()), \
             patch('session_windows.process_metadata',side_effect=self.meta.__getitem__):w.capture_tick()
        self.assertEqual([job[0] for job in self.jobs],[expected])
        self.jobs.clear();w.ocr_busy=False;w.capture_pending=False;w._active_capture_generation=None

    def assert_focus_blocks_dispatch(self):
        delays=[];w=self.window
        with patch.object(w,'schedule_capture',side_effect=lambda delay=None:delays.append(delay)):w.capture_tick()
        self.assertEqual(self.jobs,[]);self.assertEqual(delays,[400])

    def start_manual(self,*,follow=False,target=CLIENT):
        w=self.window;w.client_follow.setChecked(follow)
        w.window_list.blockSignals(True)
        w.window_list.clear();w.window_list.addItem('Owned manual',target)
        w.window_list.blockSignals(False)
        factory=lambda client:SessionWindowPolicy(client,resolver=self.meta.__getitem__)
        with patch('session_windows.process_metadata',side_effect=self.meta.__getitem__), \
             patch('session_windows.SessionWindowPolicy',side_effect=factory):w.start_monitor()
        w.monitor.stop();self.assertTrue(w.state.running)
        self.assertEqual(w.target,target)

    def mark_active_display(self):
        import time
        w=self.window
        if w.selection_session:
            session=w.selection_session;now=time.monotonic()
            for when in (now-.2,now-.1):
                session.observe_client({'scene':'assigned-selection','assigned':True,'championId':'9001'},
                    CLIENT.identity,when,when,generation=session.generation)
            self.assertTrue(session.assigned)
        w.state.hero=next(iter(w.data['heroes']))
        w.state.confirmed=True;w.state.offered=tuple(w.data['augments'])[:3]
        w._accepted_frame={'owned_previous_frame':True};w._visible_previous=True
        w.overlay.show()
        self.assertTrue(w.overlay.isVisible())

    def assert_discovery_paused(self,binding,generation,session):
        w=self.window
        self.assertIsNone(w.target);self.assertIsNone(w.state.target)
        self.assertIsNone(w.selection_session);self.assertIsNone(w.client_target)
        self.assertIsNone(w.unverified_candidate);self.assertFalse(w.trust_button.isVisible())
        self.assertFalse(w.state.confirmed);self.assertFalse(w.state.offered)
        self.assertFalse(w.overlay.isVisible());self.assertIsNone(w._accepted_frame)
        self.assertGreater(w.state.generation,generation)
        self.assertEqual(w.automatic_policy.bound,binding)
        self.assertEqual(w.automatic_policy.root,binding.root)
        self.assertTrue(w.state.running)
        if session:self.assertFalse(session.active);self.assertFalse(session.assigned)

    def snapshot_failure(self,kind):
        if kind=='malformed':return patch.object(self.table,'discovery_snapshot',return_value=None)
        return patch.object(self.table,'discovery_snapshot',side_effect=RuntimeError('Owned failed snapshot'))

    def test_foreground_client_routes_selection_despite_background_or_minimized_game(self):
        for unavailable in ('background','minimized','hidden'):
            with self.subTest(unavailable=unavailable):
                self.table.hidden.clear();self.table.minimized.clear()
                if unavailable=='minimized':self.table.minimized.add(GAME.hwnd)
                if unavailable=='hidden':self.table.hidden.add(GAME.hwnd)
                self.start_auto();self.scan()
                self.assertEqual(self.window.target,CLIENT)
                self.assertTrue(self.window.client_phase())
                self.assert_dispatch('selection')

    def test_foreground_game_routes_game_ocr_and_return_to_client_clears_old_identity(self):
        self.start_auto();self.scan();w=self.window
        old_session=w.selection_session
        self.table.foreground_hwnd=GAME.hwnd;self.scan()
        self.assertEqual(w.target,GAME);self.assertFalse(w.client_phase())
        self.assertFalse(old_session.active)
        self.assert_dispatch('ocr')
        w.state.hero=next(iter(w.data['heroes']));w.state.confirmed=True
        self.table.foreground_hwnd=CLIENT.hwnd;self.scan()
        self.assertEqual(w.target,CLIENT);self.assertTrue(w.client_phase())
        self.assertFalse(w.state.hero);self.assertFalse(w.state.confirmed)
        self.assertIsNot(w.selection_session,old_session)
        self.assert_dispatch('selection')

    def test_two_client_windows_including_minimized_twin_remain_ambiguous(self):
        twin=replace(CLIENT,hwnd=103);self.table.rows.append(twin)
        for minimized in (False,True):
            with self.subTest(minimized=minimized):
                if minimized:self.table.minimized.add(twin.hwnd)
                self.start_auto();result=self.scan()
                self.assertEqual(result.reason_code,'multiple_windows')
                self.assertIsNone(self.window.target)
                self.assertFalse(self.window.state.confirmed)

    def test_other_installation_including_minimized_one_is_not_authorized(self):
        other=replace(GAME,hwnd=103,pid=203)
        self.meta[203]=ProcessMetadata(r'D:\Other\Game\League of Legends.exe',300)
        self.table.rows.append(other)
        for minimized in (False,True):
            with self.subTest(minimized=minimized):
                if minimized:self.table.minimized.add(other.hwnd)
                self.start_auto();result=self.scan()
                self.assertEqual(result.reason_code,'multiple_installations')
                self.assertIsNone(self.window.target)

    def test_no_eligible_foreground_keeps_binding_but_never_captures(self):
        self.start_auto();self.scan()
        for foreground in (0,999):
            with self.subTest(foreground=foreground):
                self.table.foreground_hwnd=foreground;self.scan()
                self.assertEqual(self.window.target,CLIENT)
                self.assert_focus_blocks_dispatch()
        self.table.foreground_hwnd=CLIENT.hwnd;self.scan()
        self.assert_dispatch('selection')

    def test_reconnected_client_replaces_scope_and_rejects_late_old_result(self):
        self.table.rows=[CLIENT];self.start_auto();self.scan();w=self.window
        old_generation=w.state.generation;old_session=w.selection_session
        replacement=replace(CLIENT,hwnd=103)
        self.table.rows=[replacement];self.table.foreground_hwnd=replacement.hwnd
        self.meta[201]=ProcessMetadata(self.meta[201].path,101)
        self.scan()
        self.assertEqual(w.target,replacement);self.assertTrue(w.client_phase())
        self.assertFalse(old_session.active)
        self.assertGreater(w.state.generation,old_generation)
        w.task_result('selection',{'scene':'assigned-selection','assigned':True,'championId':'9001'},old_generation)
        self.assertEqual(w.selection_session.candidate_frames,0)
        self.assertFalse(w.state.hero)
        self.assert_dispatch('selection')

    def test_focus_switch_after_worker_discovery_rejects_stale_adoption(self):
        self.start_auto();kind,fn,generation=self.jobs.pop(0)
        result=fn();self.table.foreground_hwnd=GAME.hwnd
        self.window.task_result(kind,result,generation)
        self.assertIsNone(self.window.target)
        self.scan();self.assertEqual(self.window.target,GAME)
        self.assert_dispatch('ocr')

    def test_foreground_change_revokes_old_role_before_next_discovery(self):
        self.start_auto();self.scan();w=self.window
        self.assertTrue(w.target_allowed())
        self.table.foreground_hwnd=GAME.hwnd
        self.assertFalse(w.target_allowed())
        self.assert_focus_blocks_dispatch()
        self.scan();self.assertEqual(w.target,GAME)

    def test_real_acceptance_and_watchdog_reject_client_frame_after_focus_switch(self):
        from native_ui import ControlWindow
        import time
        self.start_auto();self.scan();w=self.window
        w.captured_frame_current=lambda value:ControlWindow.captured_frame_current(w,value)
        w.check_target=lambda:ControlWindow.check_target(w)
        generation=w.state.generation
        value=dict(scene='assigned-selection',assigned=True,championId='9001',
            _capturedAt=time.monotonic(),_windowIdentity=CLIENT.identity,
            _captureRect=self.table.rect(CLIENT),_sessionGeneration=w.selection_session.generation)
        self.table.foreground_hwnd=GAME.hwnd
        w.task_result('selection',value,generation)
        self.assertGreater(w.state.generation,generation)
        self.assertEqual(w.selection_session.candidate_frames,0)
        self.assertFalse(w.state.hero);self.assertFalse(w.state.confirmed)
        self.assertFalse(w.overlay.isVisible())
        w.last_window_discovery=0.;w.check_target()
        self.assertTrue(all(job[0]=='windows' for job in self.jobs))
        self.scan();self.assertEqual(w.target,GAME)

    def test_focus_switch_between_adopt_and_capture_permission_queues_no_inference(self):
        self.start_auto();self.scan();w=self.window
        self.table.foreground_hwnd=GAME.hwnd
        generation=w.state.generation
        w.capture_hidden(generation)
        self.assertEqual(self.jobs,[])
        self.assertGreater(w.state.generation,generation)
        self.assertFalse(w.ocr_busy);self.assertFalse(w.capture_pending)

    def test_manual_client_follow_off_still_dispatches_selection_and_never_hands_off(self):
        self.start_manual(follow=False);w=self.window
        self.assertTrue(w.client_phase());self.assertIsNotNone(w.selection_session)
        self.assertFalse(w.lcu_toggle.isChecked())
        self.assert_dispatch('selection')
        session=w.selection_session
        for when in (100.,100.3):
            session.observe_client({'scene':'assigned-selection','assigned':True,'championId':'9001'},
                CLIENT.identity,when,when,generation=session.generation)
        self.table.foreground_hwnd=GAME.hwnd
        with patch.object(w.window_policy,'discover_game',side_effect=AssertionError('Follow disabled')), \
             patch('native_ui.time.monotonic',return_value=100.4):w.advance_session_window()
        self.assertEqual(w.target,CLIENT)
        self.assertIsNone(w.window_policy.game_identity)
        self.assert_focus_blocks_dispatch()

    def test_manual_client_follow_off_still_expires_selection_identity(self):
        self.start_manual(follow=False);w=self.window;session=w.selection_session
        for when in (100.,100.3):
            session.observe_client({'scene':'assigned-selection','assigned':True,'championId':'9001'},
                CLIENT.identity,when,when,generation=session.generation)
        w.state.hero=next(iter(w.data['heroes']))
        with patch.object(w.window_policy,'discover_game',side_effect=AssertionError('Follow disabled')), \
             patch('native_ui.time.monotonic',return_value=104.301):w.advance_session_window()
        self.assertEqual(session.stage,'client-expired')
        self.assertFalse(session.assigned);self.assertFalse(w.state.hero)
        self.assertEqual(w.target,CLIENT)

    def test_native_follow_off_phase_observer_uses_real_start_expiry_and_clean_restart(self):
        from native_ui import ControlWindow
        from selection_smoke import advance_follow_off_probe
        self.table.rows=[CLIENT];self.start_manual(follow=False);w=self.window
        w.captured_frame_current=lambda value:ControlWindow.captured_frame_current(w,value)
        w.check_target=lambda:ControlWindow.check_target(w)
        session=w.selection_session;policy=w.window_policy
        for when in (100.,100.3):
            with patch('native_ui.time.monotonic',return_value=when):
                w.task_result('selection',dict(scene='assigned-selection',assigned=True,championId='9001',
                    _capturedAt=when,_captureRect=self.table.rect(CLIENT),_windowIdentity=CLIENT.identity,
                    _sessionGeneration=session.generation),w.state.generation)
        w.overlay.show()
        report=dict(phase='capturing-client-follow-off',clientHwnd=CLIENT.hwnd,clientPid=CLIENT.pid)
        self.table.u.IsWindow=lambda hwnd:any(row.hwnd==hwnd for row in self.table.rows)
        with patch('selection_smoke.inspect_client_hero',return_value={'observation_count':session.candidate_frames}), \
             patch('selection_smoke.time.monotonic',return_value=100.4):
            self.assertTrue(advance_follow_off_probe(w,report))
            self.assertEqual(report['phase'],'await-follow-off-game')
            self.assertFalse(advance_follow_off_probe(w,report))  # No eligible game is no evidence.
            self.table.rows.append(GAME)
            self.meta[202]=replace(self.meta[202],created=policy.started_after+1)
            self.assertTrue(advance_follow_off_probe(w,report))
            self.assertEqual(report['phase'],'testing-follow-off-game')
            self.assertFalse(w.monitor.isActive())
            self.table.foreground_hwnd=GAME.hwnd
            self.assertFalse(advance_follow_off_probe(w,report))
            self.assertEqual(w.target,CLIENT);self.assertIsNone(policy.game_identity)
            self.assertFalse(policy.permits(GAME))
            self.assertNotIn('manual_client_follow_off_passed',report)
        with patch('selection_smoke.time.monotonic',return_value=104.3):
            self.assertFalse(advance_follow_off_probe(w,report))  # Exactly four seconds is not expiry.
        with patch('selection_smoke.time.monotonic',return_value=104.4):
            self.assertTrue(advance_follow_off_probe(w,report))
        self.assertEqual(report['phase'],'closing-follow-off-game')
        self.assertEqual(session.stage,'client-expired');self.assertFalse(session.assigned)
        self.assertFalse(w.state.hero);self.assertFalse(w.overlay.isVisible())
        self.assertFalse(advance_follow_off_probe(w,report))  # Still-live game blocks follow-on Start.
        self.table.rows=[CLIENT];self.table.foreground_hwnd=CLIENT.hwnd
        factory=lambda client:SessionWindowPolicy(client,resolver=self.meta.__getitem__)
        with patch('session_windows.process_metadata',side_effect=self.meta.__getitem__), \
             patch('session_windows.SessionWindowPolicy',side_effect=factory):
            self.assertTrue(advance_follow_off_probe(w,report))
        w.monitor.stop()
        self.assertEqual(report['phase'],'capturing-client');self.assertTrue(report['manual_client_follow_off_passed'])
        self.assertTrue(w.client_follow.isChecked());self.assertTrue(w.client_phase())
        self.assertIsNot(w.window_policy,policy);self.assertFalse(policy.active)
        self.assertGreater(w.window_policy.started_after,self.meta[202].created)
        self.assertFalse(session.active);self.assertIsNot(w.selection_session,session)

    def test_native_follow_off_probe_rejects_expired_initial_assignment_or_game_binding(self):
        from selection_smoke import advance_follow_off_probe
        self.start_manual(follow=False);w=self.window;session=w.selection_session;policy=w.window_policy
        self.meta[202]=replace(self.meta[202],created=policy.started_after+1)
        for when in (100.,100.3):
            session.observe_client(dict(scene='assigned-selection',assigned=True,championId='9001'),
                CLIENT.identity,when,when,generation=session.generation)
        w.overlay.show()
        report=dict(phase='capturing-client-follow-off',clientHwnd=CLIENT.hwnd,clientPid=CLIENT.pid)
        with patch('selection_smoke.inspect_client_hero',return_value={'observation_count':2}):
            advance_follow_off_probe(w,report);advance_follow_off_probe(w,report)
        self.table.foreground_hwnd=GAME.hwnd
        with patch('selection_smoke.time.monotonic',return_value=105.),self.assertRaises(AssertionError):
            advance_follow_off_probe(w,report)
        policy.game_identity=GAME.identity;policy.game_meta=self.meta[202]
        with self.assertRaises(AssertionError):advance_follow_off_probe(w,report)
        self.assertNotIn('manual_client_follow_off_passed',report)

    def test_manual_client_follow_on_keeps_selection_route(self):
        self.start_manual(follow=True)
        self.assertTrue(self.window.client_phase())
        self.assert_dispatch('selection')

    def test_manual_follow_on_hands_off_only_new_game_after_two_fresh_client_frames(self):
        import time
        self.start_manual(follow=True);w=self.window;session=w.selection_session
        now=time.monotonic()
        for when in (now-.2,now-.1):
            session.observe_client({'scene':'assigned-selection','assigned':True,'championId':'9001'},
                CLIENT.identity,when,when,generation=session.generation)
        self.table.foreground_hwnd=GAME.hwnd
        w.advance_session_window()
        self.assertEqual(w.target,CLIENT)  # Existing game predates Start.
        self.meta[202]=replace(self.meta[202],created=w.window_policy.started_after+1)
        w.last_window_discovery=0.;w.advance_session_window()
        self.assertEqual(w.target,GAME);self.assertFalse(w.client_phase())
        self.assertEqual(session.stage,'transition');self.assertEqual(session.carried,'9001')
        self.assertEqual(w.window_policy.game_identity,GAME.identity)
        self.assert_dispatch('ocr')

    def test_non_league_manual_target_with_client_class_is_not_reclassified(self):
        self.meta[201]=ProcessMetadata(r'C:\Owned\chrome.exe',100)
        for follow in (False,True):
            with self.subTest(follow=follow):
                self.start_manual(follow=follow)
                self.assertFalse(self.window.client_phase())
                self.assertIsNone(self.window.window_policy)
                self.assertIsNone(self.window.selection_session)
                self.assert_dispatch('ocr')

    def test_signature_and_stale_process_cannot_be_bypassed_by_foreground(self):
        self.verify=lambda path:False;self.start_auto();result=self.scan()
        self.assertEqual(result.reason_code,'signature_unverified')
        self.assertIsNone(self.window.target)
        self.verify=lambda path:True;self.start_auto()
        kind,fn,generation=self.jobs.pop(0);result=fn()
        self.meta[201]=ProcessMetadata(r'C:\Owned\chrome.exe',100)
        self.window.task_result(kind,result,generation)
        self.assertIsNone(self.window.target)

    def test_supported_snapshot_failure_never_falls_back_to_legacy_enumeration(self):
        w=self.window
        with patch.object(self.table,'discovery_snapshot',side_effect=CapturePaused('Owned snapshot unavailable')), \
             patch.object(self.table,'windows',side_effect=AssertionError('Unsafe legacy fallback')):
            with self.assertRaises(CapturePaused):w.discovery_snapshot()

    def test_supported_snapshot_missing_fields_or_malformed_data_fail_closed(self):
        valid=self.table.discovery_snapshot()
        for value in (None,{},dict(windows=[CLIENT]),{**valid,'foreground_hwnd':None},
                      {**valid,'foreground_hwnd':True},{**valid,'available_hwnds':{999}},
                      {**valid,'windows':[object()]}):
            with self.subTest(value=value), \
                 patch.object(self.table,'discovery_snapshot',return_value=value), \
                 patch.object(self.table,'windows',side_effect=AssertionError('Unsafe legacy fallback')):
                with self.assertRaises(CapturePaused):self.window.discovery_snapshot()

    def test_task_result_snapshot_failure_revokes_active_target_and_recovers_without_role_expansion(self):
        for failure in ('malformed','raising'):
            with self.subTest(failure=failure):
                self.start_auto(follow=False);self.scan();w=self.window
                self.mark_active_display();binding=w.automatic_policy.bound
                generation=w.state.generation;session=w.selection_session
                w.queue_discovery(force=True);kind,fn,scope=self.jobs.pop(0);result=fn()
                with self.snapshot_failure(failure), \
                     patch.object(self.table,'windows',side_effect=AssertionError('Unsafe legacy fallback')):
                    w.task_result(kind,result,scope)
                self.assertFalse(w.discovery_busy)
                self.assert_discovery_paused(binding,generation,session)
                self.table.foreground_hwnd=GAME.hwnd;self.scan()
                self.assertEqual(w.target,CLIENT)  # Preserve follow-off's original role.
                self.assert_focus_blocks_dispatch()
                self.table.foreground_hwnd=CLIENT.hwnd;self.scan()
                self.assert_dispatch('selection')

    def test_second_unchanged_binding_snapshot_failure_cannot_fall_through_to_readoption(self):
        for failure in (None,RuntimeError('Owned late snapshot failure')):
            with self.subTest(failure=failure):
                self.start_auto();self.scan();w=self.window;self.mark_active_display()
                binding=w.automatic_policy.bound;generation=w.state.generation;session=w.selection_session
                w.queue_discovery(force=True);kind,fn,scope=self.jobs.pop(0);result=fn()
                valid=self.table.discovery_snapshot()
                with patch.object(self.table,'discovery_snapshot',side_effect=[valid,failure]):
                    w.task_result(kind,result,scope)
                self.assert_discovery_paused(binding,generation,session)
                self.scan();self.assertEqual(w.target,CLIENT);self.assert_dispatch('selection')

    def test_confirmation_slot_snapshot_failure_revokes_active_target_without_granting_consent(self):
        for failure in ('malformed','raising'):
            with self.subTest(failure=failure):
                self.start_auto(follow=False);self.scan();w=self.window;self.mark_active_display()
                binding=w.automatic_policy.bound;generation=w.state.generation;session=w.selection_session
                w.unverified_candidate=binding;w.trust_button.show()
                with self.snapshot_failure(failure), \
                     patch.object(self.table,'windows',side_effect=AssertionError('Unsafe legacy fallback')), \
                     patch('native_ui.QtWidgets.QMessageBox.question',return_value=fixture.QtWidgets.QMessageBox.StandardButton.Yes):
                    w.confirm_game_installation()
                self.assertIsNone(w.automatic_policy.confirmed_root)
                self.assert_discovery_paused(binding,generation,session)
                self.table.foreground_hwnd=GAME.hwnd;self.scan()
                self.assertEqual(w.target,CLIENT);self.assert_focus_blocks_dispatch()
                self.table.foreground_hwnd=CLIENT.hwnd;self.scan();self.assert_dispatch('selection')

    def test_discovery_worker_error_revokes_active_display_and_recovers(self):
        self.start_auto();self.scan();w=self.window;self.mark_active_display()
        binding=w.automatic_policy.bound;generation=w.state.generation;session=w.selection_session
        w.discovery_busy=True
        w.task_error('windows','Owned worker snapshot failure',w.discovery_scope)
        self.assertFalse(w.discovery_busy)
        self.assert_discovery_paused(binding,generation,session)
        self.scan();self.assertEqual(w.target,CLIENT);self.assert_dispatch('selection')

    def test_permission_snapshot_failure_is_false_and_real_capture_callers_hide_old_display(self):
        from native_ui import ControlWindow
        for caller in ('check_target','capture_selection','capture_hidden','captured_frame_current'):
            for failure in ('malformed','raising'):
                with self.subTest(caller=caller,failure=failure):
                    self.start_auto();self.scan();w=self.window;self.mark_active_display()
                    generation=w.state.generation
                    with self.snapshot_failure(failure),patch.object(w,'queue_discovery'):
                        self.assertFalse(w.target_allowed())
                        if caller=='check_target':ControlWindow.check_target(w)
                        elif caller=='capture_selection':w.capture_selection()
                        elif caller=='capture_hidden':w.capture_hidden(generation)
                        else:
                            self.assertFalse(ControlWindow.captured_frame_current(w,
                                dict(_captureRect=self.table.rect(CLIENT),_windowIdentity=CLIENT.identity)))
                    self.assertFalse(w.state.confirmed);self.assertFalse(w.overlay.isVisible())
                    self.assertIsNone(w._accepted_frame);self.assertGreater(w.state.generation,generation)
                    self.assertEqual(self.jobs,[])
                    self.assertTrue(w.target_allowed())

    def test_second_result_permission_failure_never_escapes_selection_or_ocr_slots(self):
        from native_ui import ControlWindow
        import time
        for kind,target in (('selection',CLIENT),('ocr',GAME)):
            for failure in (None,RuntimeError('Owned late permission query failure')):
                with self.subTest(kind=kind,failure=failure):
                    self.table.foreground_hwnd=target.hwnd
                    self.start_auto();self.scan();w=self.window;self.mark_active_display()
                    w.captured_frame_current=lambda value:ControlWindow.captured_frame_current(w,value)
                    generation=w.state.generation;valid=self.table.discovery_snapshot()
                    value=dict(_captureRect=self.table.rect(target),_windowIdentity=target.identity,
                        _capturedAt=time.monotonic(),scene='assigned-selection',assigned=True,championId='9001')
                    with patch.object(self.table,'discovery_snapshot',side_effect=[valid,failure]) as query:
                        w.task_result(kind,value,generation)
                    self.assertEqual(query.call_count,2)
                    self.assertFalse(w.state.confirmed);self.assertFalse(w.overlay.isVisible())
                    self.assertGreater(w.state.generation,generation)
                    if w.selection_session:self.assertFalse(w.selection_session.assigned)
                    self.assertTrue(w.target_allowed())

    def test_query_failure_cause_survives_debug_export_without_private_payloads(self):
        import json
        from pathlib import Path
        import zipfile
        self.start_auto();self.scan();w=self.window
        self.mark_active_display()
        with patch.object(self.table,'discovery_snapshot',side_effect=RuntimeError('PRIVATE_PATH PRIVATE_TITLE PRIVATE_ERROR')):
            self.assertFalse(w.target_allowed())
            w.unverified_candidate=w.automatic_policy.bound
            with patch('native_ui.QtWidgets.QMessageBox.question',return_value=fixture.QtWidgets.QMessageBox.StandardButton.Yes):
                w.confirm_game_installation()
        path=w.debug_log.export_zip(Path(self.directory.name)/'exports',config={})
        with zipfile.ZipFile(path) as archive:
            text='\n'.join(archive.read(name).decode() for name in archive.namelist())
            manifest=json.loads(archive.read('manifest.json'))
            rows=[json.loads(line) for name in ('events.jsonl','critical.jsonl','context.jsonl')
                  for line in archive.read(name).splitlines()]
        self.assertNotIn('PRIVATE_',text)
        self.assertNotIn(CLIENT.title,text);self.assertNotIn(self.meta[201].path,text)
        self.assertTrue(any(row.get('event')=='window_binding' and row.get('binding_outcome')=='query_failed' for row in rows))
        self.assertGreater(manifest['summary']['binding_outcomes']['query_failed']['observations'],0)

    def test_unavailable_window_reason_survives_debug_export_and_recovers(self):
        import json
        from pathlib import Path
        import zipfile
        self.table.rows=[CLIENT];self.table.minimized.add(CLIENT.hwnd)
        self.start_auto();result=self.scan();w=self.window
        self.assertEqual(result.reason_code,'window_unavailable');self.assertIsNone(w.target)
        path=w.debug_log.export_zip(Path(self.directory.name)/'exports',config={})
        with zipfile.ZipFile(path) as archive:
            manifest=json.loads(archive.read('manifest.json'))
            rows=[json.loads(line) for name in ('events.jsonl','critical.jsonl','context.jsonl')
                  for line in archive.read(name).splitlines()]
        self.assertTrue(any(row.get('event')=='job' and row.get('reason')=='window_unavailable' for row in rows))
        self.assertGreater(manifest['summary']['reasons']['window_unavailable']['observations'],0)
        self.table.minimized.clear();self.scan()
        self.assertEqual(w.target,CLIENT);self.assert_dispatch('selection')

    def test_ordinary_focus_adoption_rejection_never_claims_query_failure(self):
        self.start_auto();self.scan();w=self.window
        w.queue_discovery(force=True);kind,fn,scope=self.jobs.pop(0);result=fn()
        self.table.foreground_hwnd=GAME.hwnd
        with patch.object(w,'debug_event') as event:w.task_result(kind,result,scope)
        outcomes=[call.kwargs.get('binding_outcome') for call in event.call_args_list if call.args==('window_binding',)]
        self.assertIn('adoption_rejected',outcomes)
        self.assertNotIn('query_failed',outcomes)

    def test_adapter_without_snapshot_preserves_legacy_identity_checked_policy(self):
        self.window.capture=SimpleNamespace(windows=lambda **kw:[CLIENT,GAME])
        snapshot=self.window.discovery_snapshot()
        self.assertEqual(snapshot,dict(windows=[CLIENT,GAME]))
        policy=AutomaticWindowPolicy(resolver=self.meta.__getitem__,verifier=lambda path:True)
        self.assertEqual(policy.discover(**snapshot).candidate.window,GAME)
        policy.verifier=lambda path:False
        self.assertIsNone(policy.discover(**snapshot).candidate)

    def test_real_confirmation_dialog_may_take_focus_but_cannot_bind_a_target(self):
        self.verify=lambda path:False;self.start_auto();self.scan();w=self.window
        self.assertEqual(w.unverified_candidate.window,CLIENT)
        def answer(*args):
            self.table.foreground_hwnd=999
            return fixture.QtWidgets.QMessageBox.StandardButton.Yes
        with patch('native_ui.QtWidgets.QMessageBox.question',side_effect=answer):w.confirm_game_installation()
        self.assertIsNotNone(w.automatic_policy.confirmed_root)
        self.assertIsNone(w.automatic_policy.bound);self.assertIsNone(w.target)
        self.table.foreground_hwnd=CLIENT.hwnd;self.scan()
        self.assertEqual(w.target,CLIENT)
        self.assert_dispatch('selection')


if __name__=='__main__':unittest.main()

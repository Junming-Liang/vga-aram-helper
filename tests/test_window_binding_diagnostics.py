"""Synthetic binding lifecycle tests; not evidence of real-client compatibility."""
import os
import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock
from automatic_windows import AutomaticWindowPolicy
from screen_capture import CapturePaused, CaptureUnavailable, Win32Capture, WindowInfo, ClientRect
from session_windows import ProcessMetadata

class BindingLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.window=WindowInfo(10,20,'League of Legends','RiotWindowClass')
        self.meta=ProcessMetadata(r'C:\Riot\Game\League of Legends.exe',100)
        self.policy=AutomaticWindowPolicy(resolver=lambda _:self.meta,verifier=lambda _:True)
    def test_title_changes_during_adopt_and_capture_are_not_identity_changes(self):
        discovery=self.policy.discover([self.window])
        for title in ('英雄联盟','League of Legends (TM) Client',''):
            with self.subTest(title=title):
                fresh=replace(self.window,title=title)
                self.assertTrue(self.policy.adopt(discovery,windows=[fresh]))
                self.assertTrue(self.policy.permits(self.window,windows=[fresh]))
                self.assertEqual(hash(discovery.candidate),hash(self.policy.inspect(fresh)))
    def test_confirmation_does_not_depend_on_caption(self):
        self.policy.verifier=lambda _:False
        discovery=self.policy.discover([self.window])
        self.assertTrue(self.policy.confirm_installation(discovery.confirmation,windows=[replace(self.window,title='英雄联盟')]))
    def test_title_invariance_never_relaxes_actual_identity(self):
        discovery=self.policy.discover([self.window]);self.policy.adopt(discovery,windows=[self.window])
        for fresh in (replace(self.window,hwnd=11),replace(self.window,pid=21),replace(self.window,class_name='OtherClass')):
            self.assertFalse(self.policy.adopt(discovery,windows=[fresh]))
            self.assertFalse(self.policy.permits(self.window,windows=[fresh]))
        self.meta=replace(self.meta,created=101)
        self.assertFalse(self.policy.adopt(discovery,windows=[self.window]))
        self.assertFalse(self.policy.permits(self.window,windows=[self.window]))
    def test_discovery_codes_separate_absence_identity_signature_and_success(self):
        self.assertEqual(self.policy.discover([]).reason_code,'window_not_found')
        self.assertEqual(self.policy.discover([self.window]).reason_code,'game_connected')
        self.assertEqual(self.policy.discover([self.window,replace(self.window,hwnd=11)]).reason_code,'multiple_windows')
        self.policy.verifier=lambda _:False
        self.assertEqual(self.policy.discover([self.window]).reason_code,'signature_unverified')
        self.meta=replace(self.meta,path=r'C:\Unrelated.exe')
        self.assertEqual(self.policy.discover([self.window]).reason_code,'window_identity_unverified')
        self.policy.stop();self.assertEqual(self.policy.discover([]).reason_code,'discovery_stopped')

class ClientGameTransitionTests(unittest.TestCase):
    def test_supported_client_classes_transition_to_game_and_back_across_recreation(self):
        for class_name in ('RCLIENT','Chrome_WidgetWin_1','CEFCLIENT'):
            with self.subTest(class_name=class_name):
                client=WindowInfo(1,10,'英雄联盟',class_name)
                game=WindowInfo(2,20,'League of Legends (TM) Client','RiotWindowClass')
                metadata={10:ProcessMetadata(r'C:\Riot\LeagueClientUx.exe',100),
                          20:ProcessMetadata(r'C:\Riot\Game\League of Legends.exe',200),
                          30:ProcessMetadata(r'C:\Riot\Game\League of Legends.exe',300)}
                policy=AutomaticWindowPolicy(resolver=metadata.__getitem__,verifier=lambda _:True)
                def bind(windows,role,expected):
                    result=policy.discover(windows)
                    self.assertEqual(result.candidate.role,role)
                    self.assertEqual(result.candidate.window.identity,expected.identity)
                    self.assertTrue(policy.adopt(result,windows=windows))
                    self.assertTrue(policy.permits(expected,windows=windows))
                bind([client],'client',client)
                bind([client,game],'game',game)
                self.assertFalse(policy.permits(client,windows=[client,game]))
                client=replace(client,title='')
                game=replace(game,title='英雄联盟')
                bind([game,client],'game',game)
                bind([client],'client',client)
                replacement=replace(game,hwnd=3,pid=30,title='')
                bind([client,replacement],'game',replacement)
                self.assertFalse(policy.permits(game,windows=[client,replacement]))
    def test_rclient_class_does_not_authorize_wrong_executable_or_signature(self):
        window=WindowInfo(1,10,'League of Legends','RCLIENT')
        policy=AutomaticWindowPolicy(resolver=lambda _:ProcessMetadata(r'C:\Other\browser.exe',100),verifier=lambda _:True)
        self.assertIsNone(policy.discover([window]).candidate)
        policy.resolver=lambda _:ProcessMetadata(r'C:\Riot\LeagueClientUx.exe',100)
        policy.verifier=lambda _:False
        result=policy.discover([window])
        self.assertIsNone(result.candidate);self.assertEqual(result.reason_code,'signature_unverified')

class CaptureEnumerationTests(unittest.TestCase):
    def test_automatic_optin_enumerates_untitled_but_never_own_or_hidden(self):
        capture=object.__new__(Win32Capture);capture.enum_cb=lambda fn:fn
        windows={1:WindowInfo(1,os.getpid()+100,'','RiotWindowClass'),
                 2:WindowInfo(2,os.getpid()+101,'visible','OtherClass'),
                 3:WindowInfo(3,os.getpid(),'','RiotWindowClass'),
                 4:WindowInfo(4,os.getpid()+102,'hidden','RiotWindowClass')}
        capture.info=lambda hwnd:windows[hwnd]
        capture.u=SimpleNamespace(IsWindowVisible=lambda hwnd:hwnd!=4,
            EnumWindows=lambda cb,_:[cb(hwnd,0) for hwnd in windows])
        self.assertEqual([w.hwnd for w in capture.windows()],[2])
        self.assertEqual([w.hwnd for w in capture.windows(include_untitled=True)],[1,2])

class CaptureReasonTests(unittest.TestCase):
    def test_default_reason_codes_remain_compatible(self):
        self.assertEqual(CapturePaused('localized text').reason_code,'capture_paused')
        self.assertEqual(CaptureUnavailable('localized text').reason_code,'capture_unavailable')
    def test_focus_rejection_has_distinct_code_without_pixel_access(self):
        capture=object.__new__(Win32Capture)
        capture.rect=Mock(return_value=ClientRect(0,0,800,600));capture.foreground=Mock(return_value=False)
        capture.u=SimpleNamespace()
        with self.assertRaises(CapturePaused) as caught:capture.validate(WindowInfo(1,2,'private caption','RiotWindowClass'))
        self.assertEqual(caught.exception.reason_code,'focus_rejected')
    def test_recreated_window_has_distinct_code(self):
        capture=object.__new__(Win32Capture);target=WindowInfo(1,2,'caption','RiotWindowClass')
        capture.info=Mock(return_value=replace(target,pid=3))
        with self.assertRaises(CapturePaused) as caught:capture.rect(target)
        self.assertEqual(caught.exception.reason_code,'window_identity_changed')

if __name__=='__main__':unittest.main()

"""Synthetic metadata/signature policy, never real-client compatibility evidence."""
import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from automatic_windows import AutomaticWindowPolicy,trusted_signature_result
from screen_capture import WindowInfo
from session_windows import ProcessMetadata

class AutomaticWindowTests(unittest.TestCase):
    def setUp(self):
        self.client=WindowInfo(1,10,'英雄联盟','Chrome_WidgetWin_1');self.game=WindowInfo(2,20,'League of Legends (TM) Client','RiotWindowClass')
        self.meta={10:ProcessMetadata(r'C:\Riot\LeagueClientUx.exe',100),20:ProcessMetadata(r'C:\Riot\Game\League of Legends.exe',200)}
        self.p=AutomaticWindowPolicy(resolver=lambda pid:self.meta[pid],verifier=lambda path:True)
    def bind(self,windows):
        result=self.p.discover(windows);self.assertTrue(self.p.adopt(result,windows=windows));return result.candidate
    def test_no_game_is_normal_wait_then_client_starts(self):
        self.assertIsNone(self.p.discover([]).candidate);self.assertEqual(self.bind([self.client]).role,'client')
    def test_already_running_game_needs_no_selected_hwnd_or_recent_creation(self):
        self.assertLess(self.meta[20].created,self.p.started_after);self.assertEqual(self.bind([self.client,self.game]).window,self.game)
    def test_game_can_start_without_client(self):self.assertEqual(self.bind([self.game]).window,self.game)
    def test_cn_client_subdirectory_is_same_installation(self):
        self.meta[10]=ProcessMetadata(r'C:\Riot\LeagueClient\LeagueClientUx.exe',100)
        self.bind([self.client]);self.assertEqual(self.bind([self.client,self.game]).window,self.game)
    def test_unrelated_ancestor_not_treated_as_installation(self):
        self.meta[10]=ProcessMetadata(r'C:\Riot\unrelated\LeagueClientUx.exe',100)
        self.bind([self.client]);self.assertIsNone(self.p.discover([self.game]).candidate)
    def test_client_to_game_and_back(self):
        self.bind([self.client]);self.bind([self.client,self.game]);self.assertTrue(self.p.permits(self.game,windows=[self.client,self.game]));self.bind([self.client]);self.assertFalse(self.p.permits(self.game))
    def test_client_restart_and_window_recreation_rebind_safely(self):
        self.bind([self.client]);self.meta[10]=ProcessMetadata(self.meta[10].path,999);self.assertFalse(self.p.permits(self.client))
        replacement=WindowInfo(9,10,self.client.title,self.client.class_name);self.bind([replacement]);self.assertTrue(self.p.permits(replacement));self.assertFalse(self.p.permits(self.client))
    def test_game_pid_reuse_rejects_old_result(self):
        result=self.p.discover([self.game]);self.meta[20]=ProcessMetadata(self.meta[20].path,999);self.assertFalse(self.p.adopt(result,windows=[self.game]))
    def test_wrong_process_class_or_filename_cannot_grant_capture(self):
        self.assertIsNone(self.p.discover([WindowInfo(1,10,'League of Legends','wrong')]).candidate)
        self.meta[10]=ProcessMetadata(r'C:\Riot\chrome.exe',100);self.assertIsNone(self.p.discover([self.client]).candidate)
    def test_unverified_publisher_abstains_and_explains(self):
        self.p.verifier=lambda path:False;result=self.p.discover([self.game]);self.assertIsNone(result.candidate);self.assertIn('校验',result.reason);self.assertIsNotNone(result.confirmation)
    def test_multiple_installations_do_not_bind(self):
        self.meta[10]=ProcessMetadata(r'D:\Other\LeagueClientUx.exe',100);self.assertIsNone(self.p.discover([self.game,self.client]).candidate)
    def test_pinned_installation_does_not_follow_other_install(self):
        self.bind([self.client]);self.meta[20]=ProcessMetadata(r'D:\Other\Game\League of Legends.exe',200);self.assertIsNone(self.p.discover([self.game]).candidate)
    def test_multiple_same_install_games_wait(self):
        twin=WindowInfo(3,20,self.game.title,self.game.class_name);self.assertIsNone(self.p.discover([self.game,twin]).candidate)
    def test_new_ambiguity_between_discover_and_adopt(self):
        result=self.p.discover([self.game]);twin=WindowInfo(3,20,self.game.title,self.game.class_name);self.assertFalse(self.p.adopt(result,windows=[self.game,twin]))
    def test_new_ambiguity_before_capture(self):
        self.bind([self.game]);twin=WindowInfo(3,20,self.game.title,self.game.class_name);self.assertFalse(self.p.permits(self.game,windows=[self.game,twin]))
    def test_stopped_scope_cannot_adopt_worker_result(self):
        result=self.p.discover([self.game]);self.p.stop();self.assertFalse(self.p.adopt(result,windows=[self.game]));self.assertFalse(self.p.permits(self.game))
    def test_follow_optout_honored_at_discover_adopt_and_capture(self):
        self.p.follow_roles=False;self.bind([self.client]);self.bind([self.client,self.game]);self.assertTrue(self.p.permits(self.client,windows=[self.client,self.game]));self.assertEqual(self.p.bound.role,'client')
    def test_explicit_installation_confirmation_is_session_only(self):
        self.p.verifier=lambda path:False;result=self.p.discover([self.game]);self.assertIsNone(result.candidate)
        self.assertTrue(self.p.confirm_installation(result.confirmation,windows=[self.game]));self.bind([self.game])
        self.p.stop();self.assertIsNone(self.p.confirmed_root);self.assertFalse(self.p.permits(self.game))
    def test_unverified_game_does_not_silently_fall_back_to_trusted_client(self):
        self.p.verifier=lambda path:path.endswith('leagueclientux.exe');result=self.p.discover([self.client,self.game]);self.assertIsNone(result.candidate);self.assertEqual(result.confirmation.window,self.game)
    def test_confirmation_stale_identity_and_ambiguity_rejected(self):
        self.p.verifier=lambda path:False;result=self.p.discover([self.game]);other=WindowInfo(9,20,self.game.title,self.game.class_name)
        self.assertFalse(self.p.confirm_installation(result.confirmation,windows=[self.game,other]))
        self.meta[20]=ProcessMetadata(self.meta[20].path,999);self.assertFalse(self.p.confirm_installation(result.confirmation,windows=[self.game]))

class SignatureIdentityTests(unittest.TestCase):
    def setUp(self):self.path=r'C:\Riot\LeagueClientUx.exe';self.value={'status':'Valid','publisher':'Riot Games, Inc.','original':'LeagueClientUx.exe','product':'League of Legends'}
    def test_verified_publisher_and_signed_product_identity(self):self.assertTrue(trusted_signature_result(self.value,self.path))
    def test_unsigned_expired_untrusted_chain_rejected(self):
        for status in ('NotSigned','HashMismatch','NotTrusted','UnknownError'):self.assertFalse(trusted_signature_result({**self.value,'status':status},self.path))
    def test_unrelated_tencent_signed_program_renamed_rejected(self):
        self.assertFalse(trusted_signature_result({**self.value,'publisher':'Tencent TechnologyShenzhen Company Limited','product':'QQ','original':'QQ.exe'},self.path))
    def test_wrong_original_or_product_or_publisher_rejected(self):
        for key,value in [('original','chrome.exe'),('product','Google Chrome'),('publisher','Unknown Co')]:self.assertFalse(trusted_signature_result({**self.value,key:value},self.path))
    def test_historical_cn_identity_spelling_supported(self):
        self.assertTrue(trusted_signature_result({'status':'Valid','publisher':'Tencent TechnologyShenzhen Company Limited','original':'League of Legends.exe','product':'League of Legends (TM) Client'},r'C:\Riot\Game\League of Legends.exe'))
if __name__=='__main__':unittest.main()

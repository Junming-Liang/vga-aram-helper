import sys,unittest
from pathlib import Path
from dataclasses import dataclass
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from session_windows import SessionWindowPolicy,ProcessMetadata,PROCESS_QUERY_LIMITED_INFORMATION,normalized_path
@dataclass
class Window:
 hwnd:int;pid:int;class_name:str
 @property
 def identity(self):return (self.hwnd,self.pid,self.class_name)
class WindowPolicyTests(unittest.TestCase):
 def setUp(self):
  self.client=Window(1,10,'Chrome_WidgetWin_1');self.game=Window(2,20,'RiotWindowClass');self.other=Window(3,30,'RiotWindowClass')
  self.meta={10:ProcessMetadata(r'C:\Riot Games\League of Legends\LeagueClientUx.exe',100),20:ProcessMetadata(r'C:\Riot Games\League of Legends\Game\League of Legends.exe',200),30:ProcessMetadata(r'C:\Other\Game\League of Legends.exe',300)}
  self.p=SessionWindowPolicy(self.client,resolver=lambda pid:self.meta[pid],started_after=150)
 def test_nested_client_directory_uses_explicit_installation_root(self):
  self.meta[10]=ProcessMetadata(r'C:\Riot Games\League of Legends\LeagueClient\LeagueClientUx.exe',100)
  policy=SessionWindowPolicy(self.client,resolver=lambda pid:self.meta[pid],started_after=150)
  candidate=policy.discover_game([self.game,self.other]);self.assertEqual(candidate[0],self.game)
  self.assertFalse(policy.adopt_game(candidate,windows=[self.game]))
  self.assertTrue(policy.adopt_game(candidate,windows=[self.game],confirmed_handoff=True))
  self.assertTrue(policy.permits(self.game));self.assertFalse(policy.permits(self.other))
 def test_unrecognized_client_subdirectory_does_not_authorize_parent_game(self):
  self.meta[10]=ProcessMetadata(r'C:\Riot Games\League of Legends\Other\LeagueClientUx.exe',100)
  policy=SessionWindowPolicy(self.client,resolver=lambda pid:self.meta[pid],started_after=150)
  self.assertIsNone(policy.discover_game([self.game,self.other]))
 def test_only_limited_metadata_right(self):self.assertEqual(PROCESS_QUERY_LIMITED_INFORMATION,0x1000);self.assertEqual(PROCESS_QUERY_LIMITED_INFORMATION&0x10,0)
 def test_only_selected_client_initially_permitted(self):self.assertTrue(self.p.permits(self.client));self.assertFalse(self.p.permits(self.game))
 def test_same_install_unique_loading_handoff(self):
  candidate=self.p.discover_game([self.game,self.other]);self.assertEqual(candidate[0],self.game);self.assertFalse(self.p.adopt_game(candidate,windows=[self.game]));self.assertTrue(self.p.adopt_game(candidate,windows=[self.game],confirmed_handoff=True));self.assertTrue(self.p.permits(self.game));self.assertFalse(self.p.permits(self.other))
 def test_preexisting_game_is_not_a_new_session(self):
  self.meta[20]=ProcessMetadata(self.meta[20].path,140);self.assertIsNone(self.p.discover_game([self.game]))
 def test_same_process_new_hwnd_does_not_substitute_discovered_window(self):
  candidate=self.p.discover_game([self.game]);second=Window(4,20,'RiotWindowClass');self.assertFalse(self.p.adopt_game(candidate,windows=[second],confirmed_handoff=True))
 def test_new_ambiguity_at_adoption_is_rejected(self):
  candidate=self.p.discover_game([self.game]);second=Window(4,20,'RiotWindowClass');self.assertFalse(self.p.adopt_game(candidate,windows=[self.game,second],confirmed_handoff=True))
 def test_spoofed_title_class_elsewhere_never_sufficient(self):self.assertIsNone(self.p.discover_game([self.other]))
 def test_ambiguous_candidates_pause(self):
  second=Window(4,20,'RiotWindowClass');self.assertIsNone(self.p.discover_game([self.game,second]))
 def test_pid_reuse_breaks_existing_consent(self):
  self.meta[10]=ProcessMetadata(self.meta[10].path,999);self.assertFalse(self.p.permits(self.client));self.assertIsNone(self.p.discover_game([self.game]))
 def test_game_metadata_rechecked_on_adoption(self):
  candidate=self.p.discover_game([self.game]);self.meta[20]=ProcessMetadata(self.meta[20].path,999);self.assertFalse(self.p.adopt_game(candidate,windows=[self.game],confirmed_handoff=True))
 def test_stop_revokes_every_window(self):self.p.stop();self.assertFalse(self.p.permits(self.client));self.assertIsNone(self.p.discover_game([self.game]))
 def test_invalid_or_relative_paths_rejected(self):
  for path in ['game.exe',r'C:\Riot\..\Other.exe','bad\0path']:
   with self.assertRaises(ValueError):normalized_path(path)
if __name__=='__main__':unittest.main()

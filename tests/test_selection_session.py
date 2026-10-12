import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from selection_session import SelectionSession
CLIENT = (1, 10, 'client')
GAME = (2, 20, 'game')

def assigned(hero='31'):
    return {'scene': 'assigned-selection', 'assigned': True, 'championId': hero}

class SessionTests(unittest.TestCase):

    def setUp(self):
        self.s = SelectionSession()
        self.s.start(CLIENT)

    def stable(self, hero='31', now=1):
        self.s.start(CLIENT)
        self.s.observe_client(assigned(hero), CLIENT, now, now, generation=self.s.generation)
        self.s.observe_client(assigned(hero), CLIENT, now + 1, now + 1, generation=self.s.generation)

    def test_two_observations_required(self):
        self.assertFalse(self.s.observe_client(assigned(), CLIENT, 1, 1, generation=self.s.generation))
        self.assertEqual(self.s.assigned, '')
        self.assertTrue(self.s.observe_client(assigned(), CLIENT, 2, 2, generation=self.s.generation))

    def test_initial_cards_never_assign(self):
        self.stable()
        self.s.observe_client({'scene': 'initial-cards', 'championId': '523', 'assigned': False}, CLIENT, 3, 3, generation=self.s.generation)
        self.assertEqual(self.s.assigned, '')

    def test_trade_change_clears_old_then_reaccepts(self):
        self.stable()
        self.assertFalse(self.s.observe_client(assigned('22'), CLIENT, 3, 3, generation=self.s.generation))
        self.assertEqual(self.s.assigned, '')
        self.assertTrue(self.s.observe_client(assigned('22'), CLIENT, 4, 4, generation=self.s.generation))

    def test_ambiguous_trade_and_cancel_clear(self):
        for scene in ['trade-pending', 'lobby', 'cancelled', 'unknown']:
            self.stable()
            self.s.observe_client({'scene': scene}, CLIENT, 3, 3, generation=self.s.generation)
            self.assertFalse(self.s.assigned or self.s.carried or self.s.verified)

    def test_no_window_authority_from_observation(self):
        self.stable()
        self.assertFalse(self.s.observe_client(assigned(), (9, 99, 'other'), 3, 3, generation=self.s.generation))
        self.assertEqual(self.s.assigned, '')

    def test_loading_needs_continuity_not_timer(self):
        self.stable()
        self.assertFalse(self.s.begin_handoff(GAME, 3, generation=self.s.generation))
        self.stable()
        self.assertFalse(self.s.begin_handoff(GAME, 10, new_game_window=True, generation=self.s.generation))

    def test_provisional_is_explicit_and_not_default_visible(self):
        self.stable()
        self.assertTrue(self.s.begin_handoff(GAME, 3, new_game_window=True, generation=self.s.generation))
        self.assertTrue(self.s.observe_game(GAME, 4, 4, game_scene=True, generation=self.s.generation))
        self.assertIsNone(self.s.visible_identity())
        self.assertFalse(self.s.visible_identity(allow_provisional=True)['verified'])

    def test_matching_hud_verifies_and_conflict_clears(self):
        self.stable()
        self.s.begin_handoff(GAME, 3, new_game_window=True, generation=self.s.generation)
        self.s.observe_game(GAME, 4, 4, game_scene=True, hud_hero='31', generation=self.s.generation)
        self.assertTrue(self.s.visible_identity()['verified'])
        self.assertFalse(self.s.observe_game(GAME, 5, 5, game_scene=True, hud_hero='22', generation=self.s.generation))
        self.assertIsNone(self.s.visible_identity(allow_provisional=True))

    def test_new_selection_cannot_reuse_previous_match(self):
        self.stable()
        self.s.begin_handoff(GAME, 3, new_game_window=True, generation=self.s.generation)
        self.s.observe_game(GAME, 4, 4, game_scene=True, hud_hero='31', generation=self.s.generation)
        self.assertFalse(self.s.observe_client(assigned(), CLIENT, 5, 5, generation=self.s.generation))
        self.assertIsNone(self.s.visible_identity(allow_provisional=True))
        self.assertIsNone(self.s.game)

    def test_capture_gaps_loading_timeout_stop_clear(self):
        self.stable()
        self.s.expire(7)
        self.assertEqual(self.s.assigned, '')
        self.stable()
        self.s.begin_handoff(GAME, 3, new_game_window=True, generation=self.s.generation)
        self.s.expire(124)
        self.assertEqual(self.s.carried, '')
        self.stable()
        self.s.stop()
        self.assertFalse(self.s.active)
        self.assertIsNone(self.s.client)

    def test_wrong_game_and_ended_match_clear(self):
        self.stable()
        self.s.begin_handoff(GAME, 3, new_game_window=True, generation=self.s.generation)
        self.assertFalse(self.s.observe_game((8, 80, 'other'), 4, 4, game_scene=True, generation=self.s.generation))
        self.stable()
        self.s.begin_handoff(GAME, 3, new_game_window=True, generation=self.s.generation)
        self.assertFalse(self.s.observe_game(GAME, 4, 4, game_scene=True, match_ended=True, generation=self.s.generation))
    def test_long_client_gap_does_not_count_as_two_frames(self):
        self.s.observe_client(assigned(),CLIENT,1,1,generation=self.s.generation)
        self.assertFalse(self.s.observe_client(assigned(),CLIENT,9,9,generation=self.s.generation))
        self.assertFalse(self.s.assigned)
        self.assertTrue(self.s.observe_client(assigned(),CLIENT,10,10,generation=self.s.generation))

    def test_long_game_gap_cannot_refresh_carried_identity(self):
        self.stable();self.s.begin_handoff(GAME,3,new_game_window=True,generation=self.s.generation)
        self.s.observe_game(GAME,4,4,game_scene=True,generation=self.s.generation)
        self.assertFalse(self.s.observe_game(GAME,10,10,game_scene=True,generation=self.s.generation))
        self.assertIsNone(self.s.visible_identity(allow_provisional=True))

    def test_duplicate_or_old_generation_frame_does_not_count(self):
        token=self.s.generation
        self.s.observe_client(assigned(),CLIENT,1,1,generation=token)
        self.assertFalse(self.s.observe_client(assigned(),CLIENT,2,2,generation=token))
        self.assertFalse(self.s.observe_client(assigned(),CLIENT,1,1,generation=self.s.generation))
        self.assertEqual(self.s.candidate_frames,1)

if __name__ == '__main__':
    unittest.main()

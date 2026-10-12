"""Pixel-only infrastructure tests. Never claim game/Vanguard compatibility."""
import copy
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from native_state import RecognitionState,display_cards
from screen_capture import bounded_roi,CaptureUnavailable,WindowInfo

class NativeStateTests(unittest.TestCase):
    def setUp(self):
        self.state=RecognitionState();self.state.select_hero('英雄甲');self.state.start((123,99,'Mock'))
    def test_stability_requires_two_matching_frames(self):
        self.assertFalse(self.state.observe(['甲','乙','丙']));self.assertTrue(self.state.observe(['甲','乙','丙']));self.assertFalse(self.state.confirmed)
    def test_manual_confirmation_required(self):
        for _ in range(4):self.state.observe(['甲','乙','丙'])
        self.assertFalse(self.state.confirmed);self.state.confirm(['甲','乙','丙'],['甲','乙','丙']);self.assertTrue(self.state.confirmed)
    def test_new_candidates_clear_old_overlay_state(self):
        self.state.confirm(['甲','乙','丙'],['甲','乙','丙']);self.state.observe(['丁','乙','丙']);self.assertFalse(self.state.confirmed);self.assertEqual(self.state.offered,())
    def test_scene_loss_clears_confirmation(self):
        self.state.confirm(['甲','乙','丙'],['甲','乙','丙']);self.state.observe([]);self.assertFalse(self.state.confirmed)
    def test_repeated_same_scene_keeps_manual_confirmation(self):
        self.state.confirm(['甲','乙','丙'],['甲','乙','丙']);self.state.observe(['甲','乙','丙']);self.assertTrue(self.state.confirmed)
    def test_stale_worker_result_is_discarded(self):
        token=self.state.generation;self.state.select_hero('英雄乙');self.assertFalse(self.state.observe(['甲','乙','丙'],generation=token));self.assertEqual(self.state.observed,())
    def test_manual_correction_is_preserved_until_observed_scene_changes(self):
        self.state.observe(['甲','错字候选','丙']);self.state.observe(['甲','错字候选','丙']);self.state.invalidate('手动编辑',clear_observed=False)
        self.state.confirm(['甲','乙','丙'],['甲','乙','丙']);self.state.observe(['甲','错字候选','丙']);self.assertTrue(self.state.confirmed);self.assertEqual(self.state.offered,('甲','乙','丙'))
        self.state.observe(['丁','乙','丙']);self.assertFalse(self.state.confirmed)
    def test_stop_invalidates_and_blocks_confirmation(self):
        self.state.stop()
        with self.assertRaises(ValueError):self.state.confirm(['甲','乙','丙'],['甲','乙','丙'])
    def test_unknown_hero_and_candidates_not_guessed(self):
        self.state.hero=''
        with self.assertRaises(ValueError):self.state.confirm(['甲','乙','丙'],['甲','乙','丙'])
        self.state.hero='英雄甲'
        for names in [('甲','甲','丙'),('甲','乙'),('甲','乙','未知')]:
            with self.assertRaises(ValueError):self.state.confirm(names,['甲','乙','丙'])
    def test_neutral_default_has_no_rates_or_ranking(self):
        data={'heroes':{'英雄甲':{}},'augments':{'甲':{'description':'原描述'}},'heroAugmentStats':{'英雄甲':[{'augmentName':'甲','tier':'T1','winRate':88.5,'numGames':500}]},'metadata':{}}
        cards=display_cards(data,'英雄甲',['甲'])
        self.assertEqual(cards[0]['description'],'原描述');self.assertIsNone(cards[0]['sourceTier']);self.assertIsNone(cards[0]['sourceRank'])
        self.assertNotIn('winRate',str(cards));self.assertNotIn('recommended',str(cards));self.assertNotIn('88.5',str(cards))
    def test_missing_description_and_relations_never_fabricate_synergy(self):
        result=display_cards({'metadata':{},'augments':{}},'英雄甲',['未知'])[0]
        self.assertEqual(result['description'],'描述未提供');self.assertEqual(result['notes'],[])
    def test_selected_window_identity_contains_no_game_memory(self):
        self.assertEqual(WindowInfo(123,456,'标题','Class').identity,(123,456,'Class'))

class RoiTests(unittest.TestCase):
    def test_only_selected_client_area(self):self.assertEqual(bounded_roi(1000,800,(.1,.2,.7,.5)),(100,160,700,400))
    def test_reject_outside_or_invalid_roi(self):
        for roi in [(-.1,0,1,1),(0,0,1.1,1),(.8,0,.3,1),(0,0,0,1),(0,0,.001,.001),(0,0,float('nan'),1)]:
            with self.subTest(roi=roi),self.assertRaises(CaptureUnavailable):bounded_roi(1000,800,roi)
    def test_full_target_not_full_desktop(self):self.assertEqual(bounded_roi(1080,600,(0,0,1,1)),(0,0,1080,600))

if __name__=='__main__':unittest.main()

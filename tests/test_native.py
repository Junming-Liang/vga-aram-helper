"""Pixel-only infrastructure tests. Never claim game/Vanguard compatibility."""
import copy
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from native_state import RecognitionState,display_cards,source_tier
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
    def test_literal_hero_tier_has_no_rates_or_ranking(self):
        data={'heroes':{'英雄甲':{}},'augments':{'甲':{'description':'原描述'}},'heroAugmentStats':{'英雄甲':[{'augmentName':'甲','tier':'T1','winRate':88.5,'numGames':500}]},'metadata':{}}
        cards=display_cards(data,'英雄甲',['甲'])
        self.assertEqual(cards[0]['description'],'原描述');self.assertEqual(cards[0]['sourceTier'],'T1');self.assertNotIn('sourceRank',cards[0])
        self.assertNotIn('winRate',str(cards));self.assertNotIn('recommended',str(cards));self.assertNotIn('88.5',str(cards))
    def test_source_tier_missing_null_unknown_never_maps_or_guesses(self):
        for value in [None,'','  ','None','unknown','T0','T5','T99','S','A','B','C',1,True,{},[]]:
            with self.subTest(value=value):self.assertIsNone(source_tier(value))
        for value in ['T1','T2','T3','T4']:self.assertEqual(source_tier(value),value)
        self.assertEqual(source_tier(' T2 '),'T2')
    def test_literal_hero_tier_changes_without_reordering_offered_cards(self):
        data={'metadata':{},'augments':{'甲':{'overallTier':'T1'},'乙':{},'丙':{}},'heroAugmentStats':{
            '英雄甲':[{'augmentName':'丙','tier':'T1'},{'augmentName':'乙','tier':'T2'},{'augmentName':'甲','tier':'T3'}],
            '英雄乙':[{'augmentName':'乙','tier':'T4'},{'augmentName':'甲','tier':'T1'},{'augmentName':'丙','tier':None}]}}
        before=display_cards(data,'英雄甲',['甲','乙','丙']);after=display_cards(data,'英雄乙',['甲','乙','丙'])
        self.assertEqual([x['name'] for x in before],['甲','乙','丙']);self.assertEqual([x['slot'] for x in before],[1,2,3])
        self.assertEqual([x['sourceTier'] for x in before],['T3','T2','T1']);self.assertEqual([x['sourceTier'] for x in after],['T1','T4',None])
        self.assertIsNone(display_cards(data,'缺少英雄记录',['甲'])[0]['sourceTier'])
    def test_global_tier_and_high_winrate_never_fill_missing_hero_tier(self):
        data={'metadata':{},'augments':{'甲':{'tier':'T1','overallTier':'T1','winRate':99}},'heroAugmentStats':{'英雄甲':[{'augmentName':'甲','tier':None,'winRate':99}]}}
        card=display_cards(data,'英雄甲',['甲'])[0]
        self.assertIsNone(card['sourceTier']);self.assertEqual(card['sourceTierLabel'],'虎牙公开源评级')
        self.assertNotIn('winRate',str(card));self.assertNotIn('99',str(card))

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

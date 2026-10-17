"""Synthetic route snapshots only; never real-client compatibility evidence."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from automatic_windows import selection_gate_snapshot,SELECTION_GATES,SELECTION_ROUTES,TARGET_ROLES


class SelectionRoutingTests(unittest.TestCase):
    def snapshot(self,**changes):
        values=dict(closed=False,running=True,ocr_busy=False,capture_pending=False,
            target_present=True,target_role='client',target_foreground=True,
            lcu_selection=False,hero_auto=True,pixel_fallback=False)
        return selection_gate_snapshot(**{**values,**changes})
    def test_lcu_off_keeps_pixel_selection_route(self):
        value=self.snapshot()
        self.assertEqual(value['selection_gate'],'client_pixels_ready')
        self.assertEqual(value['selection_route'],'selection_pixels')
        self.assertFalse(value['lcu_selection'])
    def test_lcu_requires_optin_auto_hero_and_no_pending_pixel_fallback(self):
        value=self.snapshot(lcu_selection=True)
        self.assertEqual(value['selection_gate'],'client_lcu_ready')
        self.assertEqual(value['selection_route'],'selection_lcu')
        for changes in ({'pixel_fallback':True},{'hero_auto':False}):
            value=self.snapshot(lcu_selection=True,**changes)
            self.assertEqual(value['selection_route'],'selection_pixels')
            self.assertTrue(value['lcu_selection'])
    def test_game_manual_and_missing_targets_are_distinct(self):
        self.assertEqual(self.snapshot(target_role='game')['selection_gate'],'game_pixels_ready')
        self.assertEqual(self.snapshot(target_role='manual')['selection_gate'],'manual_pixels_ready')
        missing=self.snapshot(target_role='none',target_present=False,target_foreground=None)
        self.assertEqual(missing['selection_gate'],'target_missing')
        self.assertEqual(missing['selection_route'],'blocked')
        self.assertNotIn('target_foreground',missing)
    def test_short_circuit_order_matches_capture_tick(self):
        for changes,expected in (({'closed':True,'ocr_busy':True},'closed'),
                ({'ocr_busy':True,'capture_pending':True},'inference_busy'),
                ({'capture_pending':True,'running':False},'capture_pending'),
                ({'running':False,'target_present':False},'stopped'),
                ({'target_present':False,'target_foreground':False},'target_missing'),
                ({'target_foreground':False},'foreground_rejected')):
            value=self.snapshot(**changes)
            self.assertEqual(value['selection_gate'],expected)
            self.assertEqual(value['selection_route'],'blocked')
    def test_unobserved_focus_is_not_assumed_permitted(self):
        value=self.snapshot(target_foreground=None)
        self.assertEqual(value['selection_gate'],'route_unknown')
        self.assertEqual(value['selection_route'],'unknown')
        self.assertNotIn('target_foreground',value)
    def test_unknown_role_cannot_leak_arbitrary_text(self):
        value=self.snapshot(target_role='private-player-title-path')
        self.assertEqual(value['target_role'],'unknown')
        self.assertEqual(value['selection_route'],'unknown')
        self.assertNotIn('private-player-title-path',repr(value))
        self.assertIn(value['selection_gate'],SELECTION_GATES)
        self.assertIn(value['selection_route'],SELECTION_ROUTES)
        self.assertIn(value['target_role'],TARGET_ROLES)
    def test_snapshots_do_not_remember_or_change_consent(self):
        self.assertEqual(self.snapshot(lcu_selection=True)['selection_route'],'selection_lcu')
        self.assertEqual(self.snapshot(lcu_selection=False)['selection_route'],'selection_pixels')
        self.assertEqual(self.snapshot(target_role='game',lcu_selection=True)['selection_route'],'game_pixels')


if __name__=='__main__':unittest.main()

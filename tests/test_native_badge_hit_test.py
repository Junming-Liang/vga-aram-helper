"""Portable adversarial native-point proof contract; no Windows claim."""
from types import SimpleNamespace
import unittest
try:
    from native_smoke import prove_badge_native_hits
except ImportError:
    prove_badge_native_hits=None


@unittest.skipIf(prove_badge_native_hits is None,'Optional Qt runtime is not installed')
class NativeBadgeHitTests(unittest.TestCase):
    def fixture(self, failure=None):
        state=dict(style=0x20,calls=[],restored=False)
        regions=((0,0,100,52),(150,0,100,52),(300,0,100,52))
        def configure(hwnd,transparent,**kwargs):
            state['calls'].append(('configure',hwnd,transparent))
            state['style']=0x20 if transparent or failure=='transparent' else 0
        def point(p):
            state['calls'].append(('hit',p.x,p.y,state['style']))
            inside=any(x<=p.x-10<x+w for x,y,w,h in regions)
            if failure=='center' and inside:return 9
            if failure=='gap' and not inside:return 7
            if failure=='exception':raise RuntimeError('Owned hit query failed')
            return 7 if inside else 9
        def restore():
            state['restored']=True
            state['calls'].append(('restore',))
            state['style']=0 if failure=='restore' else 0x20
        capture=SimpleNamespace(configure_overlay=configure,get_long=lambda *a:state['style'],
            u=SimpleNamespace(WindowFromPoint=point,GetAncestor=lambda hwnd,kind:hwnd))
        overlay=SimpleNamespace(winId=lambda:7,_badge_regions=regions,configure=restore)
        return capture,overlay,SimpleNamespace(left=10,top=20),state
    def test_centers_and_gaps_proved_with_native_transparency_off_then_restored(self):
        capture,overlay,rect,state=self.fixture()
        self.assertEqual(prove_badge_native_hits(capture,overlay,9,rect),
            dict(opaque_center_hits=3,target_gap_hits=2,normal_transparency_restored=True))
        hits=[row for row in state['calls'] if row[0]=='hit']
        self.assertEqual(len(hits),5);self.assertTrue(all(row[3]==0 for row in hits))
        self.assertEqual(state['calls'][0],('configure',7,False));self.assertEqual(state['calls'][-1],('restore',))
    def test_passthrough_wrong_centers_wrong_gaps_and_query_errors_fail_and_restore(self):
        for failure in ('transparent','center','gap','exception'):
            with self.subTest(failure=failure):
                capture,overlay,rect,state=self.fixture(failure)
                with self.assertRaises((AssertionError,RuntimeError)):prove_badge_native_hits(capture,overlay,9,rect)
                self.assertTrue(state['restored']);self.assertEqual(state['style'],0x20)
                if failure=='transparent':self.assertFalse(any(row[0]=='hit' for row in state['calls']))
    def test_failed_normal_style_restoration_fails_proof(self):
        capture,overlay,rect,state=self.fixture('restore')
        with self.assertRaisesRegex(AssertionError,'not restored'):prove_badge_native_hits(capture,overlay,9,rect)
        self.assertTrue(state['restored'])

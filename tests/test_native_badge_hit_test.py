"""Portable adversarial native-point proof contract; no Windows claim."""
from types import SimpleNamespace
import unittest
from contextlib import nullcontext
from unittest.mock import patch
import ctypes
import os
from ctypes import wintypes as W
try:
    from native_smoke import prove_badge_native_hits
except ImportError:
    prove_badge_native_hits=None


@unittest.skipIf(prove_badge_native_hits is None,'Optional Qt runtime is not installed')
class NativeBadgeHitTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch("native_smoke.owned_badge_hit_test_probe",return_value=nullcontext()))

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


@unittest.skipIf(prove_badge_native_hits is None,'Optional Qt runtime is not installed')
class NativeFilterLifetimeTests(unittest.TestCase):
    def fixture(self, failure=None):
        from native_smoke import owned_badge_hit_test_probe
        state=dict(filter=None,removed=False,queries=[])
        overlay=SimpleNamespace(winId=lambda:7)
        def owner(hwnd,p):p._obj.value=os.getpid()+(1 if failure=='foreign' else 0);return 1
        def send(hwnd,msg,w,l):
            result=-1
            if state['filter'] and failure!='not_applied':
                native=W.MSG();native.hWnd=hwnd;native.message=msg
                handled,value=state['filter'].nativeEventFilter(b'windows_generic_MSG',ctypes.addressof(native))
                if handled:result=value
            if state['removed'] and failure=='not_restored':result=1
            state['queries'].append(result);return result
        def install(f):state['filter']=f
        def remove(f):self.assertIs(state['filter'],f);state.update(filter=None,removed=True)
        app=SimpleNamespace(installNativeEventFilter=install,removeNativeEventFilter=remove)
        user=SimpleNamespace(GetWindowThreadProcessId=owner,SendMessageW=send)
        return owned_badge_hit_test_probe,overlay,app,user,state
    def test_only_exact_owned_hit_test_intercepted_and_restored(self):
        context,overlay,app,user,state=self.fixture()
        with context(overlay,W.POINT(20,30),app=app,user=user):
            for hwnd,msg in [(8,0x84),(7,0x21),(8,0x21)]:
                native=W.MSG();native.hWnd=hwnd;native.message=msg
                self.assertEqual(state['filter'].nativeEventFilter(b'windows_generic_MSG',ctypes.addressof(native)),(False,0))
        self.assertEqual(state['queries'],[-1,1,-1]);self.assertTrue(state['removed'])
    def test_failure_and_body_exception_always_remove_filter(self):
        for failure in ('not_applied','not_restored',None):
            context,overlay,app,user,state=self.fixture(failure)
            with self.subTest(failure=failure),self.assertRaises((AssertionError,RuntimeError)):
                with context(overlay,W.POINT(20,30),app=app,user=user):
                    if failure is None:raise RuntimeError('Owned diagnostic body failed')
            self.assertTrue(state['removed']);self.assertIsNone(state['filter'])
    def test_foreign_window_cannot_install_filter(self):
        context,overlay,app,user,state=self.fixture('foreign')
        with self.assertRaisesRegex(AssertionError,'not owned'):
            with context(overlay,W.POINT(20,30),app=app,user=user):pass
        self.assertIsNone(state['filter']);self.assertFalse(state['queries'])

"""Backend-failure and exact-bounds regressions using fake GDI, not live LoL."""
import io,sys,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from screen_capture import Win32Capture,WindowInfo,ClientRect,CapturePaused,CaptureUnavailable,intersects_rect
from ctypes import wintypes as W
from PIL import Image

class CaptureBackendTests(unittest.TestCase):
    def setUp(self):
        self.c=object.__new__(Win32Capture);self.target=WindowInfo(123,44,'fixture','RiotWindowClass');self.rect=ClientRect(-1000,60,800,600)
        self.c.validate=Mock(return_value=self.rect);self.c.validate_compositor=Mock(return_value=self.rect)
        self.c.u=SimpleNamespace(GetDC=Mock(side_effect=lambda hwnd:10 if hwnd else 20),ReleaseDC=Mock())
        self.blank=Image.new('RGB',(800,600),'black');self.picture=Image.new('RGB',(800,600),'black');self.picture.paste('red',(0,0,400,300))
    def test_blank_hwnd_frame_uses_only_target_sized_compositor_region(self):
        self.c._copy_pixels=Mock(side_effect=[self.blank,self.picture]);png,rect=self.c.capture(self.target)
        self.assertEqual(self.c._copy_pixels.call_args_list[1].args,(20,800,600,-1000,60));self.assertEqual(Image.open(io.BytesIO(png)).size,(800,600));self.assertEqual(self.c.last_backend,'bounded-compositor');self.assertEqual(self.c.validate_compositor.call_count,4)
    def test_gpu_pixel_copy_failure_uses_guarded_fallback(self):
        self.c._copy_pixels=Mock(side_effect=[CaptureUnavailable('BitBlt failed'),self.picture]);self.c.capture(self.target);self.assertEqual(self.c.last_backend,'bounded-compositor')
    def test_missing_hwnd_dc_uses_guarded_fallback(self):
        self.c.u.GetDC=Mock(side_effect=[0,20]);self.c._copy_pixels=Mock(return_value=self.picture);self.c.capture(self.target);self.assertEqual(self.c._copy_pixels.call_args.args,(20,800,600,-1000,60))
    def test_nonblank_hwnd_avoids_screen_dc(self):
        self.c._copy_pixels=Mock(return_value=self.picture);self.c.capture(self.target);self.c.u.GetDC.assert_called_once_with(123);self.assertEqual(self.c.last_backend,'window-dc')
    def test_focus_or_foreign_occlusion_never_starts_pixel_copy(self):
        self.c.validate_compositor.side_effect=CapturePaused('obscured');self.c._copy_pixels=Mock()
        with self.assertRaises(CapturePaused):self.c.capture(self.target)
        self.c._copy_pixels.assert_not_called();self.c.u.GetDC.assert_not_called()
    def test_foreign_window_appearing_after_copy_discards_frame(self):
        self.c._copy_pixels=Mock(side_effect=[self.blank,self.picture]);self.c.validate_compositor.side_effect=[self.rect,self.rect,self.rect,CapturePaused('occluded')]
        with self.assertRaises(CapturePaused):self.c.capture(self.target)
        self.assertEqual(self.c.u.ReleaseDC.call_count,2)
    def test_roi_uses_physical_offset_without_full_desktop_allocation(self):
        self.c._copy_pixels=Mock(side_effect=[self.blank,self.picture]);self.c.capture(self.target,(.25,.25,.5,.5));self.assertEqual(self.c._copy_pixels.call_args.args,(20,400,300,-800,210))
    def test_both_backends_blank_is_retryable_wait(self):
        self.c._copy_pixels=Mock(return_value=self.blank)
        with self.assertRaises(CapturePaused):self.c.capture(self.target)

class FullOcclusionTests(unittest.TestCase):
    def make_capture(self,blocker=None,geometry_ok=True,found=True):
        c=object.__new__(Win32Capture);target=WindowInfo(100,10,'fixture','RiotWindowClass');rect=ClientRect(0,0,800,600);c.validate=Mock(return_value=rect);c.enum_cb=lambda fn:fn
        def monitor(_,ptr):ptr._obj.monitor=W.RECT(0,0,1920,1080);return True
        def window_rect(hwnd,ptr):ptr._obj.left,ptr._obj.top,ptr._obj.right,ptr._obj.bottom=blocker or (900,0,950,50);return geometry_ok
        def enum(cb,_):
            for hwnd in ([99,100] if found else [99]):
                if not cb(hwnd,0):break
            return True
        c.u=SimpleNamespace(MonitorFromRect=lambda *_:1,GetMonitorInfoW=monitor,IsWindowVisible=lambda _:True,IsIconic=lambda _:False,GetWindowRect=window_rect,EnumWindows=enum)
        return c,target,rect
    def test_tiny_blocker_between_old_nine_points_rejected(self):
        c,target,rect=self.make_capture((1,1,8,8))
        with patch('ctypes.WinDLL',side_effect=OSError,create=True),self.assertRaises(CapturePaused):c.validate_compositor(target,rect)
    def test_unreadable_above_window_geometry_rejected(self):
        c,target,rect=self.make_capture(geometry_ok=False)
        with patch('ctypes.WinDLL',side_effect=OSError,create=True),self.assertRaises(CapturePaused):c.validate_compositor(target,rect)
    def test_disappeared_target_in_z_order_rejected(self):
        c,target,rect=self.make_capture(found=False)
        with patch('ctypes.WinDLL',side_effect=OSError,create=True),self.assertRaises(CapturePaused):c.validate_compositor(target,rect)
    def test_nonoverlapping_higher_window_allowed(self):
        c,target,rect=self.make_capture()
        with patch('ctypes.WinDLL',side_effect=OSError,create=True):self.assertEqual(c.validate_compositor(target,rect),rect)
    def test_offscreen_or_monitor_gap_rejected(self):
        c,target,rect=self.make_capture();c.u.MonitorFromRect=lambda *_:0
        with self.assertRaises(CapturePaused):c.validate_compositor(target,rect)
if __name__=='__main__':unittest.main()

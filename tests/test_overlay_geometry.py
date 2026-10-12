import sys,unittest,math
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from screen_capture import ClientRect
from overlay_geometry import layout_budget,placement
class OverlayGeometryTests(unittest.TestCase):
 def test_resolution_scale_and_negative_origin_matrix(self):
  for size in [(800,600),(1024,768),(1280,720),(1920,1080),(2560,1440),(3440,1440),(3840,2160),(5120,1440),(7680,2160)]:
   for scale in [1,1.25,1.5,1.75,2,2.5]:
    for origin in [(0,0),(-3840,0),(0,-2160),(-3840,-2160)]:
     with self.subTest(size=size,scale=scale,origin=origin):
      rect=ClientRect(*origin,*size);budget=layout_budget(rect,scale);x,y,w,h=placement(rect,budget,min(180,budget.logical_height))
      self.assertGreaterEqual(x,rect.x);self.assertGreaterEqual(y,rect.y);self.assertLessEqual(x+w,rect.x+rect.width);self.assertLessEqual(y+h,rect.y+rect.height)
 def test_nonsensical_scales_fail_closed(self):
  for scale in [None,True,0,-1,float('inf'),float('nan'),11]:
   with self.subTest(scale=scale),self.assertRaises(ValueError):layout_budget(ClientRect(0,0,1920,1080),scale)
 def test_tiny_client_reports_actual_budget(self):
  with self.assertRaisesRegex(ValueError,'160×120'):layout_budget(ClientRect(0,0,160,120),2)
 def test_invalid_client_values_fail(self):
  for r in [ClientRect(0,0,0,900),ClientRect(0,0,-1,100),ClientRect(0,0,True,100),ClientRect(float('nan'),0,1000,900)]:
   with self.assertRaises(ValueError):layout_budget(r,1)
 def test_unfittable_height_never_extends_outside_target(self):
  r=ClientRect(0,0,1280,720);b=layout_budget(r,1.5)
  for h in [0,-1,b.logical_height+1,True]:
   with self.assertRaises(ValueError):placement(r,b,h)
if __name__=='__main__':unittest.main()

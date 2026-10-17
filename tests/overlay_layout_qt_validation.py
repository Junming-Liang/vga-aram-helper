"""Real Qt layout/forced scale with simulated Win32 coordinates, NOT native DPI proof."""
import json,os,sys
from pathlib import Path
from types import SimpleNamespace
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from PySide6 import QtWidgets
from native_ui import Overlay
from native_state import display_cards
from badge_fixture import seed_badge_geometry
from native_smoke import inspect_smoke_layout
from screen_capture import ClientRect,CaptureUnavailable
from engine import load_data
app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
class Function:
 def __init__(self,fn):self.fn=fn
 def __call__(self,*args):return self.fn(*args)
class Adapter:
 def __init__(self):
  self.x=0;self.y=0;self.physical_width=0;self.physical_height=0;self.moves=[];self.dpr_override=None;self.change_at_final=None;self.fail_bounds=False
  self.u=SimpleNamespace(SetWindowPos=Function(self.move),GetWindowRect=Function(self.rect),GetDpiForWindow=Function(lambda hwnd:(_ for _ in ()).throw(AssertionError('Must not use game DPI'))))
 def ratio(self):return self.dpr_override or self.overlay.devicePixelRatioF()
 def move(self,hwnd,z,x,y,width,height,flags):
  self.x=x;self.y=y;self.moves.append((x,y,width,height,flags))
  if not flags&1:
   self.physical_width=width;self.physical_height=height
   if self.change_at_final:self.change_at_final()
   self.overlay.resize(round(width/self.ratio()),round(height/self.ratio()))
  app.processEvents();return True
 def rect(self,hwnd,pointer):
  actual=pointer._obj;actual.left=self.x;actual.top=self.y;actual.right=self.x+self.physical_width+(10000 if self.fail_bounds else 0);actual.bottom=self.y+self.physical_height;return True
 def configure_overlay(self,*args,**kwargs):return True
capture=Adapter();overlay=Overlay(capture);capture.overlay=overlay
records=load_data(ROOT/'fixtures/demo.json');names=['星火共鸣（演示）','晶盾回路（演示）','风步微光（演示）']
cards=display_cards(records,'星火术士（演示）',names)
for card in cards:card['description']='原创合成布局测试说明。'*10;card['notes']=['原创条件说明：需要人工根据游戏机制判断。'*3]
overlay.set_cards('星火术士（演示）',cards,'虚构日期','虚构版本','来自本局选人 · HUD未复核')
seed_badge_geometry(overlay)
checks=[];cases=[]
for width,height in [(800,600),(964,602),(1024,768),(1280,720),(1920,1080),(2560,1440),(3440,1440),(3840,2160),(5120,1440),(7680,2160)]:
 for x,y in [(0,0),(-width,0),(0,-height),(-width,-height)]:
  rect=ClientRect(x,y,width,height)
  try:overlay.show_at(rect,SimpleNamespace(hwnd=123))
  except CaptureUnavailable as exc:
   assert width==800 and overlay.devicePixelRatioF()>=2.5 and not overlay.isVisible(),(width,height,str(exc))
   cases.append({'client':[width,height],'origin':[x,y],'dpr':overlay.devicePixelRatioF(),'status':'explicit-safe-hide','reason':str(exc)});continue
  app.processEvents();assert overlay.isVisible();inspect_smoke_layout(overlay)
  for lab in overlay.findChildren(QtWidgets.QLabel):
   if not lab.isVisible():continue
   required=lab.heightForWidth(lab.width())
   assert required<0 or lab.height()+1>=required,(width,height,overlay.devicePixelRatioF(),lab.text(),lab.size(),required)
   assert lab.geometry().right()<lab.parentWidget().width() and lab.geometry().bottom()<lab.parentWidget().height()
  assert [row['name'] for row in overlay.cards]==names
  assert len(overlay.tier_labels)==3 and all(lab.isVisible() for lab in overlay.tier_labels)
  cases.append({'client':[width,height],'origin':[x,y],'dpr':overlay.devicePixelRatioF(),'compact':overlay._compact,'logicalOverlay':[overlay.width(),overlay.height()]})
checks.append('40 resolution/origin cases keep actual Qt labels readable and physically contained; order/three tiers/provenance remain visible')
original_handle=overlay.windowHandle;ratio=SimpleNamespace(devicePixelRatio=lambda:capture.ratio());overlay.windowHandle=lambda:ratio
capture.dpr_override=1.;changes=[1.5]
def change_once():
 if changes:capture.dpr_override=changes.pop()
capture.change_at_final=change_once;capture.moves=[];overlay._placed_key=None
overlay.show_at(ClientRect(-1280,0,1280,720),SimpleNamespace(hwnd=123));assert overlay.isVisible();assert sum(not (row[-1]&1) for row in capture.moves)==2;checks.append('Simulated DPI change between hidden probe and final placement triggers bounded re-fit')
capture.change_at_final=lambda:setattr(capture,'dpr_override',2. if capture.dpr_override==1.5 else 1.5);overlay._placed_key=None;capture.moves=[]
try:overlay.show_at(ClientRect(0,0,1280,720),SimpleNamespace(hwnd=123));raise AssertionError('Oscillating scale must fail')
except CaptureUnavailable:pass
assert not overlay.isVisible() and sum(not (row[-1]&1) for row in capture.moves)==3;checks.append('Repeated DPI oscillation fails closed after three attempts, with no visible stale overlay')
capture.change_at_final=None;capture.dpr_override=None;overlay.windowHandle=original_handle;capture.fail_bounds=True;overlay._placed_key=None
try:overlay.show_at(ClientRect(0,0,1280,720),SimpleNamespace(hwnd=123));raise AssertionError('Out of bounds must fail')
except CaptureUnavailable:pass
assert not overlay.isVisible();checks.append('Final native bounds disagreement hides overlay rather than relaxing containment')
overlay.close()
print(json.dumps({'status':'passed','qt_platform':app.platformName(),'forced_scale':os.environ.get('QT_SCALE_FACTOR','1'),'scope':'Real Qt widgets and layout at forced process scale; simulated Win32 positioning/monitor transitions only. No physical monitor DPI or real game claim.','checks':checks,'cases':cases},ensure_ascii=False,indent=2))

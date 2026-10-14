"""Qt control lifecycle for movement; synthetic capture metadata, no Windows proof."""
import json,os,sys,time,tempfile
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from PySide6 import QtWidgets,QtTest
from native_ui import ControlWindow
from engine import load_data
from screen_capture import WindowInfo,ClientRect,CaptureUnavailable
app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([]);checks=[]
with tempfile.TemporaryDirectory() as temp,patch('native_ui.Win32Capture',side_effect=CaptureUnavailable('Offscreen only')):
 w=ControlWindow(lambda:{'data':load_data(ROOT/'fixtures/demo.json'),'status':{}},state_dir=Path(temp),current_executable=Path('/unused'),current_version='test',frozen=False,enable_updates=False)
 for _ in range(40):
  app.processEvents();QtTest.QTest.qWait(10)
  if w.data:break
 w.watchdog.stop();w.monitor.stop();target=WindowInfo(1,10,'original mock','Synthetic')
 class Capture:
  current=target;bounds=ClientRect(20,20,1920,1080);focused=True
  def rect(self,requested):
   if requested.identity!=self.current.identity:raise CaptureUnavailable('Synthetic identity changed')
   return self.bounds
  def foreground(self,requested):return self.focused
 cap=Capture();w.capture=cap;w.target=target;w.hero_auto.setChecked(False);w.hero_box.setCurrentText('星火术士（演示）');names=['星火共鸣（演示）','晶盾回路（演示）','风步微光（演示）'];placements=[]
 def show(rect,target):placements.append(rect);w.overlay.show()
 w.overlay.show_at=show
 def fresh():
  w.target_allowed=lambda:True;w.state.start(target.identity);w.state.confirm(names,w.data['augments']);w.last_observation=time.monotonic();w.last_rect=cap.bounds;w.was_target_foreground=True
 fresh();token=w.state.generation;cap.bounds=ClientRect(-1920,0,1920,1080);w.check_target()
 assert w.state.confirmed and w.state.generation==token and w.state.hero=='星火术士（演示）' and list(w.state.offered)==names and placements[-1]==cap.bounds
 checks.append('Same-size negative-origin translation preserves still-fresh confirmed hero/offers and requests new bounded placement')
 w.last_observation=time.monotonic()-5;cap.bounds=ClientRect(-1900,0,1920,1080);w.check_target();assert not w.state.confirmed and not w.overlay.isVisible();checks.append('Translation cannot revive an expired observation')
 fresh();cap.bounds=ClientRect(-1900,0,1280,720);w.check_target();assert not w.state.confirmed and not w.overlay.isVisible();checks.append('Client size change still invalidates old candidates before new recognition')
 fresh();cap.current=WindowInfo(1,99,'same title','Synthetic');w.check_target();assert not w.state.confirmed and not w.overlay.isVisible();checks.append('Same geometry does not substitute for HWND/PID/class identity validation')
 cap.current=target;fresh();cap.focused=False;cap.bounds=ClientRect(0,0,1280,720);w.check_target();assert not w.state.confirmed and not w.overlay.isVisible();checks.append('Moved but unfocused target cannot reveal old cards')
 cap.focused=True;fresh();w.ocr_busy=True;w.ocr_started=time.monotonic()-9;w.ocr_timed_out=False;w.check_target();assert not w.state.confirmed and w.ocr_busy;checks.append('Existing inference timeout remains bounded and cannot revive moved cards')
 w.close();app.processEvents()
print(json.dumps({'status':'passed','scope':'Real Qt control with synthetic window metadata only; no game or Windows pixel evidence.','checks':checks},ensure_ascii=False,indent=2))

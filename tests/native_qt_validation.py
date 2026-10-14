"""Optional real QtWidgets offscreen checks; not Windows capture evidence."""
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from PySide6 import QtWidgets,QtCore,QtTest
from native_ui import ControlWindow
from engine import load_data
from screen_capture import CaptureUnavailable,ClientRect
import time,threading
from types import SimpleNamespace
app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([]);checks=[]
with patch('native_ui.Win32Capture',side_effect=CaptureUnavailable('Offscreen test: no actual capture')),patch('updates.check_for_update',return_value={'state':'current','message':'Synthetic update test'}):
    w=ControlWindow(lambda:{'data':load_data(ROOT/'fixtures/demo.json'),'status':{'state':'demo','message':'虚构演示'}},state_dir=Path('/unused'),current_executable=Path('/unused/test.exe'),current_version='test',frozen=False)
    w.captured_frame_current=lambda value:True # Explicit synthetic handler-only fixture.
    for _ in range(30):
        app.processEvents();QtTest.QTest.qWait(20)
        if w.data:break
    assert w.data is not None and w.isVisible();checks.append('Actual QtWidgets control created and synthetic data loaded')
    assert w.findChildren(QtWidgets.QScrollArea) and w.minimumSizeHint().height()<700;checks.append('Settings content scrolls instead of forcing an oversized control window')
    w.hero_box.setCurrentText('小星');assert w.state.hero=='星火术士（演示）';checks.append('Native hero alias resolves to one canonical hero');w.target_allowed=lambda:True;w.state.start((1,1,'synthetic'))
    names=['星火共鸣（演示）','晶盾回路（演示）','风步微光（演示）']
    for edit,name in zip(w.inputs,names):edit.setText(name)
    w.confirm();assert w.state.confirmed;assert len(w.overlay.cards)==3;checks.append('Manual hero+three confirmation creates three screen-ordered source-tier cards')
    labels=' '.join(widget.text() for widget in w.overlay.findChildren(QtWidgets.QLabel))
    assert all(name in labels for name in names);assert 'T1' in labels and '虚构演示' in w.overlay.footer.text() and w.overlay.tier_labels[0].accessibleName()=='虚构源评级（演示）：T1' and '源顺位' not in labels and '60.00%' not in labels and 'winRate' not in labels;checks.append('Native overlay shows literal hero-specific source tier without win rates or sorting')
    assert '来源日期' in labels and '数据包' in labels and '游戏资料' in labels;checks.append('Overlay identifies source date and package/game-data versions')
    assert [card['name'] for card in w.overlay.cards]==names and [card['sourceTier'] for card in w.overlay.cards]==['T1','T2','T3']
    w.hero_box.setCurrentText('磐石守卫（演示）');assert not w.state.confirmed and not w.overlay.isVisible();checks.append('Hero change hides stale overlay')
    w.target_allowed=lambda:True;w.state.start((1,1,'synthetic'));w.confirm();assert [card['name'] for card in w.overlay.cards]==names and [card['sourceTier'] for card in w.overlay.cards]==['T3','T1','T2'];checks.append('Hero change clears old view, then recomputes that hero’s literal tiers in the same screen order')
    rows=w.data['heroAugmentStats']['磐石守卫（演示）'];saved=rows[0]['tier'];rows[0]['tier']=None;w.confirm();labels=' '.join(widget.text() for widget in w.overlay.findChildren(QtWidgets.QLabel));assert '暂无评级' in labels;rows[0]['tier']=saved;checks.append('Missing hero source tier is visibly ungraded rather than inferred')
    w.show_page('correction');w.inputs[0].setFocus();QtTest.QTest.keyClicks(w.inputs[0],'x');assert not w.state.confirmed;checks.append('Actual Qt input editing invalidates confirmed candidates')
    class FakeCapture:
        def rect(self,target):return ClientRect(0,0,1000,700)
        def foreground(self,target):return True
        def capture(self,target,roi,**kwargs):raise OSError('Synthetic GDI/setup failure')
    w.capture=FakeCapture();w.target=SimpleNamespace(hwnd=1);w.last_rect=None
    w.target_allowed=lambda:True;w.state.start((1,1,'synthetic'));w.state.hero='星火术士（演示）';w.state.confirm(names,w.data['augments']);w.last_observation=time.monotonic()-5
    w.check_target();assert not w.state.confirmed and not w.overlay.isVisible();checks.append('Expired observation hides stale cards through production watchdog')
    w.state.confirm(names,w.data['augments']);w.last_observation=time.monotonic();w.ocr_busy=True;w.ocr_started=time.monotonic()-9;w.ocr_timed_out=False;token=w.state.generation
    w.check_target();assert not w.state.confirmed and w.ocr_busy;checks.append('Inference timeout hides cards while retaining one bounded active OCR job')
    w.task_result('ocr',{'candidates':[{'name':name,'match_method':'exact','ocr_confidence':1} for name in names]},token);assert not w.state.confirmed;checks.append('Late timed-out OCR result cannot revive an old scene')
    w.state.confirm(names,w.data['augments']);w.task_result('ocr',{'candidates':[{'name':name} for name in names],'_capturedAt':time.monotonic()-5},w.state.generation);assert not w.state.confirmed;checks.append('Freshly completed inference cannot revive an already old captured image')
    w.state.confirm(names,w.data['augments']);w.capture_hidden(w.state.generation);assert not w.state.confirmed and not w.ocr_busy;checks.append('Unexpected capture/setup exception fails closed')
    release=threading.Event();emitted=[];w.signals.result.connect(lambda *args:emitted.append(args));w.spawn('synthetic_close_race',lambda:release.wait(2))
    started=time.monotonic();w.close();elapsed=time.monotonic()-started;release.set()
    for _ in range(10):app.processEvents();QtTest.QTest.qWait(20)
    assert w.closed and not w.overlay.isVisible() and elapsed<.7 and not emitted and not w._workers;checks.append('Closure is bounded; late worker completes without emitting into torn-down Qt')
report={'status':'passed','backend':'qtwidgets','qt_platform':app.platformName(),'checks':checks,'scope':'Actual Qt offscreen widgets/input only. Windows GDI, focus, RegisterHotKey, click-through, LoL and Vanguard not tested here.'}
(ROOT/'reports/native-qt-offscreen.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8');print(json.dumps(report,ensure_ascii=False,indent=2))

"""Real Qt/OCR client flow, fake OS resolver explicitly not Windows evidence."""
import json,os,sys,time,tempfile
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from PySide6 import QtWidgets,QtTest
from engine import load_data
from native_ui import ControlWindow
from screen_capture import CaptureUnavailable,WindowInfo,ClientRect
from session_windows import SessionWindowPolicy,ProcessMetadata
from champion_select import ChampionSelectDetector
from hero_recognition import recognize_frame
from synthetic_vision import configure_data
from local_ocr import LocalOCR
app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([]);checks=[]
client=WindowInfo(1,10,'League of Legends','Chrome_WidgetWin_1');game=WindowInfo(2,20,'League of Legends (TM) Client','RiotWindowClass')
meta={10:ProcessMetadata(r'C:\Riot\LeagueClientUx.exe',100),20:ProcessMetadata(r'C:\Riot\Game\League of Legends.exe',200)}
class FakeCapture:
    focused=client
    def windows(self):return [client,game]
    def rect(self,target):return ClientRect(0,0,964,602)
    def foreground(self,target):return target==self.focused
with tempfile.TemporaryDirectory() as temp,patch('native_ui.Win32Capture',side_effect=CaptureUnavailable('Offscreen: no Windows capture')),patch('session_windows.process_metadata',side_effect=lambda pid:meta[pid]):
    w=ControlWindow(lambda:{'data':load_data(ROOT/'fixtures/demo.json'),'status':{}},state_dir=Path(temp),current_executable=Path('/unused.exe'),current_version='test',frozen=False,enable_updates=False)
    w.captured_frame_current=lambda value:True # Explicit synthetic handler-only fixture.
    for _ in range(40):
        app.processEvents();QtTest.QTest.qWait(10)
        if w.data:break
    w.watchdog.stop();configure_data(w.data);w.data['heroes']['星火术士（演示）']['alias'].append('星火术士');w.capture=FakeCapture();w.overlay.show_at=lambda *a:None
    w.window_list.addItem('synthetic client',client);w.window_list.setCurrentIndex(w.window_list.count()-1)
    policy=lambda target:SessionWindowPolicy(target,resolver=lambda pid:meta[pid],started_after=150)
    with patch('session_windows.SessionWindowPolicy',side_effect=policy):w.start_monitor()
    w.monitor.stop();assert w.state.running and w.window_policy.permits(client)
    w.client_follow.setChecked(False);assert not w.state.running and w.window_policy is None and w.selection_session is None;checks.append('Visible handoff opt-out immediately stops capture and revokes bound windows')
    w.client_follow.setChecked(True)
    w.target=WindowInfo(1,10,'英雄联盟','Chrome_WidgetWin_1')
    with patch('session_windows.SessionWindowPolicy',side_effect=policy):w.start_monitor()
    assert w.selection_session and w.window_policy.permits(client);checks.append('Explicit Chinese-titled client uses verified process metadata without requiring an English title')
    w.target=client
    with patch('session_windows.SessionWindowPolicy',side_effect=policy):w.start_monitor()
    with patch('session_windows.SessionWindowPolicy',side_effect=OSError('Synthetic metadata unavailable')):w.start_monitor()
    assert not w.state.running and not w.monitor.isActive() and w.window_policy is None;checks.append('Restart metadata failure cannot leave old unscoped monitor running')
    with patch('session_windows.SessionWindowPolicy',side_effect=policy):w.start_monitor()
    w.monitor.stop();ocr=LocalOCR();detector=ChampionSelectDetector({'9001':['星火术士']},ocr)
    recognized=detector.recognize((ROOT/'fixtures/champselect-synthetic.png').read_bytes());assert recognized['assigned'] and recognized['ownRow']['row']==5
    def deliver_selection(value):
        value={**value,'_capturedAt':time.monotonic(),'_sessionGeneration':w.selection_session.generation,'_windowIdentity':client.identity};w.task_result('selection',value,w.state.generation)
    deliver_selection(recognized);assert not w.selection_session.assigned
    deliver_selection(recognized);assert w.selection_session.assigned=='9001' and w.state.hero=='星火术士（演示）';checks.append('Real CPU OCR own gold row + central exact name enter production handler; two frames establish current assignment without hero selection')
    deliver_selection({**recognized,'scene':'unknown','assigned':False,'reason':'Synthetic ambiguous selection from the same OCR source'});assert not w.state.hero and not w.selection_session.assigned;checks.append('Unknown client scene clears the old assigned hero')
    deliver_selection(recognized);deliver_selection(recognized)
    w.capture.focused=game;w.last_window_discovery=0;w.check_target();assert w.target==game and w.window_list.currentData()==game and w.selection_session.stage=='transition';checks.append('Production handoff uses unique same-install new process policy and visibly changes selected window (fake metadata resolver in this offscreen check)')
    result=recognize_frame((ROOT/'fixtures/auto-scene.png').read_bytes(),(.15,.25,.7,.35),ocr,w.data['augments'],None)
    def deliver_game(value):
        value={**value,'_capturedAt':time.monotonic(),'_sessionGeneration':w.selection_session.generation,'_windowIdentity':game.identity};w.task_result('ocr',value,w.state.generation)
    deliver_game(result);assert not w.state.confirmed
    deliver_game(result);assert w.state.confirmed and w.hero_origin=='client-provisional';assert all(b.source=='HUD未复核' and '来自本局选人 · HUD未复核' in b.accessibleName() for b in w.overlay._badge_widgets);checks.append('Unknown portrait with real OCR three-card scene uses explicit this-session selection provenance and auto-confirms after stability')
    deliver_game({'candidates':[],'automatic_candidates':[],'hero_observation':{'confident':False}});assert not w.state.hero and not w.state.confirmed and w.selection_session.visible_identity(allow_provisional=True) is None;checks.append('Blank/lost game scene clears carried identity rather than treating previous state as fresh evidence')
    w.stop_monitor();w.window_list.addItem('synthetic client restart',client);w.window_list.setCurrentIndex(w.window_list.count()-1);w.capture.focused=client
    with patch('session_windows.SessionWindowPolicy',side_effect=policy):w.start_monitor()
    w.monitor.stop();deliver_selection(recognized);meta[10]=ProcessMetadata(meta[10].path,999);deliver_selection(recognized)
    assert not w.state.hero and not w.selection_session.assigned;checks.append('Process creation identity is rechecked at OCR result acceptance; PID reuse cannot apply stale client evidence')
    w.close();app.processEvents()
report={'status':'passed','scope':'Real Qt offscreen and CPU OCR original fixtures, synthetic OS metadata only. Actual Windows handoff is a separate EXE gate.','checks':checks}
(ROOT/'reports/native-selection-qt.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8');print(json.dumps(report,ensure_ascii=False,indent=2))

"""Production Qt controls/timers with synthetic metadata, not Windows evidence."""
import json,os,sys,tempfile,time,threading
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from PySide6 import QtWidgets,QtTest
from native_ui import ControlWindow
from engine import load_data
from automatic_windows import AutomaticWindowPolicy
from session_windows import ProcessMetadata
from screen_capture import CaptureUnavailable,ClientRect,WindowInfo
app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([]);checks=[]
client=WindowInfo(1,10,'英雄联盟','Chrome_WidgetWin_1');game=WindowInfo(2,20,'League of Legends (TM) Client','RiotWindowClass')
meta={10:ProcessMetadata(r'C:\Riot\LeagueClient\LeagueClientUx.exe',100),20:ProcessMetadata(r'C:\Riot\Game\League of Legends.exe',200)}
class Capture:
    visible=[]
    def windows(self, **kwargs):return list(self.visible)
    def foreground(self,target):return False
    def rect(self,target):return ClientRect(0,0,960,600)
def wait(predicate,why):
    end=time.monotonic()+5
    while time.monotonic()<end:
        app.processEvents();QtTest.QTest.qWait(10)
        if predicate():return
    raise AssertionError(why)
with tempfile.TemporaryDirectory() as directory,patch('native_ui.Win32Capture',side_effect=CaptureUnavailable('Offscreen only')):
    w=ControlWindow(lambda:{'data':load_data(ROOT/'fixtures/demo.json'),'status':{}},state_dir=Path(directory),current_executable=Path('/unused.exe'),current_version='test',frozen=False,enable_updates=False)
    wait(lambda:w.data is not None,'Data did not load');w.capture=Capture();w.refresh_windows();w.overlay.show_at=lambda *_:None
    assert not w.minimize_on_start.isChecked() # Current default keeps controls reachable.
    w.minimize_on_start.setChecked(True) # Exercise the explicitly opted-in minimize flow.
    create=lambda **kw:AutomaticWindowPolicy(resolver=lambda pid:meta[pid],verifier=lambda path:True,**kw)
    with patch('automatic_windows.AutomaticWindowPolicy',side_effect=create):w.start_monitor()
    wait(lambda:not w.discovery_busy,'Initial wait unfinished');assert w.window_list.currentIndex()==0 and w.window_list.currentData() is None and w.state.running and w.target is None and w.isMinimized()
    checks.append('Start with explicit minimize preference and no selected HWND waits for a later client')
    def scan():w.last_window_discovery=0;w.check_target();wait(lambda:not w.discovery_busy,'Discovery unfinished')
    w.capture.visible=[client];scan();assert w.target==client and w.selection_session and w.client_phase()
    checks.append('Chinese-layout client appears after Start and is connected without touching window selection')
    w.capture.visible=[client,game];scan();assert w.target==game and not w.client_phase() and w.selection_session is None
    checks.append('Already-running same-install game takes priority without a selection assignment; no stale hero carried')
    w.manual_editing=True;w.inputs[0].setText('old correction');w.state.hero='old hero';w.state.confirmed=True
    meta[20]=ProcessMetadata(meta[20].path,999);scan();assert w.target==game and not w.manual_editing and not w.inputs[0].text() and not w.state.hero and not w.state.confirmed
    checks.append('Reused HWND/PID with a new process creation time clears hero, cards, and manual edit state')
    w.capture.visible=[];scan();assert w.target is None and w.state.running and '等待' in w.status.text()
    replacement=WindowInfo(3,20,game.title,game.class_name);w.capture.visible=[replacement];scan();assert w.target==replacement
    checks.append('Close and recreated game window reconnect within the pinned installation')
    old_scope=w.discovery_scope;old_result=w.automatic_policy.discover([replacement]);w.stop_monitor();w.apply_discovery(old_result,old_scope);assert not w.state.running and w.automatic_policy is None
    checks.append('Stopped scope rejects a late discovery result')
    create_untrusted=lambda **kw:AutomaticWindowPolicy(resolver=lambda pid:meta[pid],verifier=lambda path:False,**kw)
    w.showNormal()
    with patch('automatic_windows.AutomaticWindowPolicy',side_effect=create_untrusted):w.start_monitor()
    wait(lambda:w.unverified_candidate is not None,'Missing signature failure');assert w.target is None and w.isMinimized() and not w.trust_button.isHidden()
    policy=w.automatic_policy
    with patch.object(QtWidgets.QMessageBox,'question',return_value=QtWidgets.QMessageBox.StandardButton.No):w.confirm_game_installation()
    assert policy.confirmed_root is None
    with patch.object(QtWidgets.QMessageBox,'question',return_value=QtWidgets.QMessageBox.StandardButton.Yes):w.confirm_game_installation()
    wait(lambda:w.target==replacement,'Explicit installation confirmation failed');assert policy.confirmed_root is not None and w.isMinimized()
    checks.append('Unverified identity exposes a clear per-session confirmation; No captures nothing, Yes trusts only this session/installation')
    w.stop_monitor();assert policy.confirmed_root is None
    started=threading.Event();release=threading.Event()
    def slow_verify(path):started.set();release.wait(2);return True
    slow=lambda **kw:AutomaticWindowPolicy(resolver=lambda pid:meta[pid],verifier=slow_verify,**kw)
    with patch('automatic_windows.AutomaticWindowPolicy',side_effect=slow):w.start_monitor()
    wait(started.is_set,'Slow verifier did not start')
    with patch('automatic_windows.AutomaticWindowPolicy',side_effect=create):
        for _ in range(4):w.start_monitor()
    assert sum(job.name=='vga-windows' and job.is_alive() for job in w._workers)<=1
    release.set();wait(lambda:not any(job.name=='vga-windows' for job in w._workers),'Old discovery worker did not exit');scan();assert w.target==replacement
    checks.append('Repeated Start during slow trust verification keeps one worker and discards old scopes')
    diagnostics={'schemaVersion':1,'failures':[{'asset':'Briar.png','error':{'winerror':5}}]}
    w._portraits_attempt+=1;w._portraits_busy=True # Owned synthetic public-asset worker lease.
    w.task_result('portraits',({}, {'message':'Synthetic local cache failure','cacheDiagnostics':diagnostics}),w._portraits_attempt)
    assert w.portrait_diagnostics==diagnostics and not w.cache_diagnostic_button.isHidden()
    checks.append('Cache failure exposes sanitized local-only diagnostic details even when no file can be saved')
    w.stop_monitor();w.close();app.processEvents()
report={'status':'passed','scope':'Actual Qt offscreen controls/timers, synthetic OS metadata and trust verifier. No Windows/LoL capture claim.','checks':checks}
(ROOT/'reports/native-discovery-qt.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8');print(json.dumps(report,ensure_ascii=False,indent=2))

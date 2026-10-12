"""Explicit Windows diagnostic using original, externally owned fixture processes.

No process launch or policy exemption. Normal launch never reads this input.
Only JSON evidence is written. No screenshots are persisted.
"""
from pathlib import Path
import json,os,sys,time
from ctypes import wintypes as W
from PySide6 import QtCore,QtWidgets


def atomic_report(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name(path.name+'.tmp')
    temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf8');temporary.replace(path)


def start_selection_smoke(control,input_path,report_path):
    app=QtWidgets.QApplication.instance();checks=[];started=time.monotonic()
    report={'schemaVersion':1,'status':'running','phase':'initializing','backend':'qtwidgets','qt_platform':app.platformName(),'frozen':bool(getattr(sys,'frozen',False)),'applicationVersion':control.current_version,'scope':'Original synthetic owned client/game processes only. Actual Windows metadata, capture and CPU OCR; no real LoL/Vanguard compatibility claim.','checks':checks}
    control._selection_smoke_timer=QtCore.QTimer(control);timer=control._selection_smoke_timer;timer.setInterval(150)
    def save():atomic_report(report_path,report)
    def fail(exc):
        timer.stop();report.update(status='failed',error=str(exc));save();control.close();app.exit(1)
    def guarded(fn):
        try:fn()
        except Exception as exc:fail(exc)
    def finish():
        expected=['星火共鸣','晶盾回路','风步微光']
        assert control.state.hero=='星火术士（演示）' and list(control.state.offered)==expected
        assert control.hero_auto.isChecked() and control.state.confirmation_mode=='automatic'
        assert control.hero_origin=='client-provisional'
        assert '来自本局选人' in control.overlay.heading.text() and 'HUD未复核' in control.overlay.heading.text()
        assert [row['sourceTier'] for row in control.overlay.cards]==['T1','T2','T3']
        assert control.selection_session.stage=='game-provisional'
        report.update(champion_select_session_carry_passed=True,recognizedHero=control.state.hero,recognized=expected,provenance=control.hero_origin,renderedHeading=control.overlay.heading.text(),gameHwnd=control.target.hwnd,gamePid=control.target.pid)
        checks.append('Production Start handler and timers capture own client, then adopt unique new same-install game; unknown HUD uses visibly provisional this-session identity and automatic three exact titles')
        policy=control.window_policy
        assert policy.permits(control.target) and policy.permits(control.client_target)
        assert not policy.permits(control.capture.info(int(control.winId())))
        report['champion_select_window_scope_passed']=True
        checks.append('Real OS path/creation identities authorize only bound client/new game; own assistant process is rejected')
        control.monitor.stop();control.watchdog.stop();timer.stop()
        token=control.selection_session.generation
        control.task_result('ocr',{'_capturedAt':time.monotonic(),'_sessionGeneration':token,'_windowIdentity':control.target.identity,'automatic_candidates':[],'candidates':[],'image_size':[964,602],'hero_observation':{'confident':False}},control.state.generation)
        assert not control.state.hero and not control.state.confirmed and not control.overlay.isVisible()
        assert control.selection_session.visible_identity(allow_provisional=True) is None
        report['champion_select_stale_clear_passed']=True
        checks.append('Production OCR-result handler clears carried hero/tiers on a synthetic unknown scene; this state injection is not a genuine game-end image test')
        from selection_session import SelectionSession
        state=SelectionSession();client=(1,10,'synthetic');state.start(client)
        for tick in (1.,2.):state.observe_client({'scene':'assigned-selection','championId':'9001','assigned':True},client,tick,tick,generation=state.generation)
        assert state.assigned=='9001'
        state.observe_client({'scene':'unknown'},client,3.,3.,generation=state.generation);assert not state.assigned
        report['champion_select_ambiguity_passed']=True
        checks.append('Pure synthetic session-state regression rejects ambiguous own assignment; not a real trade-dialog screenshot assertion')
        control.close();app.processEvents();assert not control.isVisible() and not control.overlay.isVisible()
        report.update(status='passed',phase='complete',window_closed=True,elapsed_seconds=round(time.monotonic()-started,3));save();app.exit(0)
    def poll():
        if time.monotonic()-started>110:raise RuntimeError('Selection handoff timeout: '+control.status.text())
        session=control.selection_session
        if report['phase']=='capturing-client' and session and session.stage=='assigned':
            assert session.assigned=='9001' and control.state.hero=='星火术士（演示）'
            assert control.hero_auto.isChecked() and not control.hero_box.isEnabled()
            report.update(phase='await-game-window',champion_select_own_row_passed=True,assignedHero=control.state.hero,clientGeneration=session.generation)
            checks.append('Real GDI client pixels + local OCR reach production own-row/center detector twice; no manual hero choice');save()
        if report['phase']=='await-game-window' and control.state.confirmed:finish()
    def prepare():
        if os.name!='nt' or app.platformName()!='windows' or not control.capture:raise RuntimeError('Requires real Windows Qt/capture backend')
        payload=Path(input_path).read_bytes()
        if len(payload)>4096:raise ValueError('Diagnostic fixture input too large')
        data=json.loads(payload)
        if data.get('schemaVersion')!=1 or data.get('scope')!='owned-synthetic-only':raise ValueError('Invalid diagnostic scope')
        target=control.capture.info(int(data['client']['hwnd']))
        if target.pid!=int(data['client']['pid']):raise ValueError('Fixture HWND/PID changed')
        from session_windows import process_metadata
        own=process_metadata(os.getpid());client=process_metadata(target.pid)
        assert own.created>0 and own.path and client.created>0
        report.update(metadata_query_passed=True,clientHwnd=target.hwnd,clientPid=target.pid,metadata_scope='Actual PROCESS_QUERY_LIMITED_INFORMATION path/creation + FILE_READ_ATTRIBUTES canonicalization, no process memory read')
        from synthetic_vision import configure_data
        configure_data(control.data);control.data['heroes']['星火术士（演示）']['alias'].append('星火术士')
        from local_ocr import LocalOCR
        control.ocr=LocalOCR();control.ocr.recognize((Path(__file__).resolve().parent/'fixtures/champselect-synthetic.png').read_bytes(),[])
        control.window_list.addItem('Original owned client fixture',target);control.window_list.setCurrentIndex(control.window_list.count()-1)
        control.hero_auto.setChecked(True);control.client_follow.setChecked(True);control.start_monitor()
        assert control.state.running and control.selection_session and control.window_policy
        assert control.window_policy.permits(target)
        control.hide();control.capture.u.SetForegroundWindow.argtypes=[W.HWND];control.capture.u.SetForegroundWindow.restype=W.BOOL;control.capture.u.SetForegroundWindow(target.hwnd)
        report['phase']='capturing-client';save();timer.timeout.connect(lambda:guarded(poll));timer.start()
    guarded(prepare)

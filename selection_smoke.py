"""Explicit Windows diagnostic using original, externally owned fixture processes.

No process launch or policy exemption. Normal launch never reads this input.
Only JSON evidence is written. No screenshots are persisted. Synthetic handler
negative checks are labelled separately from actual captured-pixel observations.
"""
from pathlib import Path
import ctypes
import hashlib
import json,math,os,sys,time,traceback
from ctypes import wintypes as W
from PySide6 import QtCore,QtWidgets


DEMO_HERO='星火术士（演示）'
FOCUS_SINK_CLASS='VGAOwnedFocusSink'
FOCUS_SINK_TITLE='VGA owned focus sink'
DEMO_REFERENCE={'hero':DEMO_HERO,'championId':'9001','sourceTier':'T5',
    'sourceTierLabel':'虚构英雄评级（演示）','sourceLabel':'虚构演示 · 不能用于对局',
    'sourceUrl':None,'sourceDataDate':'2026-01-02','sourceVersion':'0.1',
    'gamePatch':'0.2','wikiDataVersion':'synthetic-selection-v1','isDemo':True}


def atomic_report(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name(path.name+'.tmp')
    temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf8');temporary.replace(path)


def diagnostic_state(control,started,now=None):
    """Bounded owned-fixture state; no images, raw OCR lines or unrelated windows."""
    now=time.monotonic() if now is None else now
    session=control.selection_session
    value={'elapsed_seconds':round(max(0,now-started),3),'running':bool(control.state.running),
        'generation':control.state.generation,'hero':str(control.state.hero)[:80],
        'confirmed':bool(control.state.confirmed),'ocr_busy':bool(control.ocr_busy),
        'capture_pending':bool(control.capture_pending),'capture_serial':control._capture_serial,
        'monitor_active':bool(control.monitor.isActive()),'status':control.status.text()[:400],
        'capture_backend':str(getattr(control.capture,'last_backend','unknown'))[:64]}
    if session:
        age=now-session.last_client_frame if session.last_client_frame else None
        value['session']={'active':bool(session.active),'generation':session.generation,
            'stage':session.stage,'candidate_frames':session.candidate_frames,
            'candidate':session.candidate[:32],'assigned':session.assigned[:32],
            'last_client_frame_age_seconds':round(age,3) if age is not None else None,
            'reason':session.reason[:240]}
    return value


def inspect_client_hero(control):
    """Measure actual displayed native widgets; never render or save an image."""
    overlay=control.overlay;session=control.selection_session;u=control.capture.u
    assert session.stage=='assigned' and session.assigned=='9001' and session.candidate_frames>=2
    assert control.state.hero==DEMO_HERO and control.state.confirmed is False and control.state.offered==()
    assert overlay.reference==DEMO_REFERENCE and overlay.cards==[] and overlay.row.count()==1
    assert overlay.isVisible() and u.IsWindowVisible(int(overlay.winId()))
    assert control.capture.foreground(control.target)
    assert len(overlay._title_labels)==len(overlay.tier_labels)==1
    target=control.capture.rect(control.target);actual=W.RECT()
    assert u.GetWindowRect(int(overlay.winId()),ctypes.byref(actual))
    client={'x':target.x,'y':target.y,'width':target.width,'height':target.height}
    bounds={'x':actual.left,'y':actual.top,'width':actual.right-actual.left,'height':actual.bottom-actual.top}
    assert (bounds['width']>0 and bounds['height']>0 and bounds['x']>=client['x'] and bounds['y']>=client['y']
            and actual.right<=target.x+target.width and actual.bottom<=target.y+target.height
            and bounds['height']<=client['height']//2),'Hero reference escaped client/half-height budget'
    style=int(control.capture.get_long(int(overlay.winId()),-20))
    assert 0<=style<=2**32-1 and all(style&flag for flag in (0x80000,0x08000000,0x20,0x8,0x80)),hex(style)
    point=W.POINT(actual.left+bounds['width']//2,actual.top+min(10,bounds['height']//2))
    hit=int(u.GetAncestor(u.WindowFromPoint(point),2) or 0)
    assert hit==control.target.hwnd,'Hero-only overlay intercepted the owned client'
    labels={}
    for role,widget in (('hero',overlay._title_labels[0]),('tier',overlay.tier_labels[0]),
                        ('heading',overlay.heading),('metadata',overlay.metadata_label),('footer',overlay.footer)):
        assert widget.isVisible() and widget.isVisibleTo(overlay)
        pos=widget.mapTo(overlay,QtCore.QPoint(0,0));parent=widget.parentWidget()
        assert (widget.width()>0 and widget.height()>0 and pos.x()>=0 and pos.y()>=0
                and pos.x()+widget.width()<=overlay.width() and pos.y()+widget.height()<=overlay.height())
        assert (widget.x()>=0 and widget.y()>=0 and widget.x()+widget.width()<=parent.width()
                and widget.y()+widget.height()<=parent.height())
        required=widget.heightForWidth(widget.width());minimum=widget.minimumSizeHint().width()
        assert required<=widget.height()+1 and minimum<=widget.width()+1,('Clipped hero label',role,widget.text())
        labels[role]={'text':widget.text(),'accessible_name':widget.accessibleName(),'visible':True,
            'logical_rect':{'x':pos.x(),'y':pos.y(),'width':widget.width(),'height':widget.height()},
            'required_height_at_width':required,'minimum_width':minimum}
    assert labels['hero']['text']==DEMO_HERO
    assert labels['tier']['text']=='英雄整体强度：T5' and labels['tier']['accessible_name']=='虚构英雄评级（演示）：T5'
    assert labels['heading']['text']=='当前分配 · 仍可交换 · HUD未复核'
    assert labels['footer']['text']=='虚构演示 · 非 Riot 评级/批准'
    assert labels['metadata']['text']=='英雄评级快照 2026-01-02 · 英雄资料 0.1 · 游戏资料 0.2 · 数据包 synthetic-selection-v1'
    return {'reference':dict(overlay.reference),'assigned':session.assigned,'stage':session.stage,
        'observation_count':session.candidate_frames,'state_hero':control.state.hero,'confirmed':control.state.confirmed,
        'offered':list(control.state.offered),'augment_card_count':len(overlay.cards),'visible':True,
        'native_visible':True,'foreground_preserved':True,'click_through_hit_hwnd':hit,
        'overlay_hwnd':int(overlay.winId()),'window_style':style,'client_rect':client,'overlay_rect':bounds,
        'qt_dpr':float(overlay.windowHandle().devicePixelRatio()),
        'logical_size':{'width':overlay.width(),'height':overlay.height()},'labels':labels}


def start_selection_smoke(control,input_path,report_path):
    app=QtWidgets.QApplication.instance();checks=[];started=time.monotonic();safety={};last_saved=0.
    report={'schemaVersion':2,'status':'running','phase':'initializing','backend':'qtwidgets','qt_platform':app.platformName(),'frozen':bool(getattr(sys,'frozen',False)),'applicationVersion':control.current_version,'scope':'Original synthetic owned client/game processes only. Actual Windows metadata, capture and CPU OCR; no real LoL/Vanguard compatibility claim.','checks':checks,'client_hero_safety':safety}
    control._selection_smoke_timer=QtCore.QTimer(control);timer=control._selection_smoke_timer;timer.setInterval(20)
    def save():
        nonlocal last_saved
        last_saved=time.monotonic();report['diagnostic_state']=diagnostic_state(control,started,last_saved)
        atomic_report(report_path,report)
    def fail(exc):
        timer.stop();report.update(status='failed',error=str(exc) or type(exc).__name__,error_type=type(exc).__name__,error_traceback=traceback.format_exc(limit=5)[-4000:]);save();control.close();app.exit(1)
    def guarded(fn):
        try:fn()
        except Exception as exc:fail(exc)
    def hidden_unconfirmed():
        assert control.state.confirmed is False and control.state.offered==()
        assert not control.overlay.isVisible() and not control.capture.u.IsWindowVisible(int(control.overlay.winId()))
        assert not control.state.hero and control.client_strength_reference() is None
    def synthetic_negative(kind):
        # A production-handler policy regression only, never described as OCR of
        # a genuine unknown scene, swap dialog, or stale real screenshot.
        control.monitor.stop();now=time.monotonic()
        value={'scene':'assigned-selection','assigned':True,'championId':'9001',
               '_capturedAt':now,'_sessionGeneration':control.selection_session.generation,
               '_windowIdentity':control.target.identity}
        if kind=='unknown':value['scene']='unknown';value['assigned']=False
        elif kind=='swap':value['championId']='9002'
        elif kind=='stale':value['_capturedAt']=now-5
        control.task_result('selection',value,control.state.generation);hidden_unconfirmed()
        safety[kind+'_handler_hidden']=True;report['phase']='recovering-'+kind;save()
    def finish():
        expected=['星火共鸣','晶盾回路','风步微光']
        assert control.state.hero==DEMO_HERO and list(control.state.offered)==expected
        assert control.hero_auto.isChecked() and control.state.confirmation_mode=='automatic'
        assert control.hero_origin=='client-provisional'
        assert '来自本局选人' in control.overlay.heading.text() and 'HUD未复核' in control.overlay.heading.text()
        assert [row['sourceTier'] for row in control.overlay.cards]==['T1','T2','T3']
        assert control.overlay.reference is None and control.client_strength_reference() is None
        safety['handoff_reference_removed']=True
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
        assert all(safety.get(key) is True for key in ('before_second_observation_hidden','hidden_during_recapture',
            'unknown_handler_hidden','swap_handler_hidden','stale_handler_hidden','cleared_hero_hidden','foreground_loss_hidden','handoff_reference_removed'))
        report['client_hero_safety_passed']=True
        control.close();app.processEvents();assert not control.isVisible() and not control.overlay.isVisible()
        report.update(status='passed',phase='complete',window_closed=True,elapsed_seconds=round(time.monotonic()-started,3));save();app.exit(0)
    def poll():
        if time.monotonic()-last_saved>=1:save()
        if time.monotonic()-started>170:raise RuntimeError('Selection handoff timeout: '+control.status.text())
        session=control.selection_session;phase=report['phase']
        if phase=='capturing-client' and session and session.stage=='assigning':
            assert session.candidate_frames==1 and not session.assigned
            hidden_unconfirmed();safety['before_second_observation_hidden']=True
        if phase=='recapturing-client' and control.capture_pending:
            assert not control.overlay.isVisible() and not control.capture.u.IsWindowVisible(int(control.overlay.winId()))
            safety['hidden_during_recapture']=True;report['phase']='recapture-complete';return
        if phase=='testing-client-foreground-loss':
            foreground=int(control.capture.u.GetForegroundWindow() or 0);pid=W.DWORD()
            control.capture.u.GetWindowThreadProcessId(foreground,ctypes.byref(pid))
            if pid.value!=control.client_target.pid or foreground==control.client_target.hwnd:return
            sink=control.capture.info(foreground)
            if sink.class_name!=FOCUS_SINK_CLASS or sink.title!=FOCUS_SINK_TITLE:return
            actual=vars(control.capture.rect(control.client_target))
            assert actual==report['foreground_transition']['client_rect_before']
            assert control.capture.u.IsWindowVisible(control.client_target.hwnd)
            control.check_target();hidden_unconfirmed();safety['foreground_loss_hidden']=True
            report['foreground_recovery_start_count']=session.candidate_frames
            report['foreground_transition'].update(sink_hwnd=sink.hwnd,sink_pid=sink.pid,
                sink_class=sink.class_name,sink_title=sink.title,foreground_sink_hwnd=foreground,
                client_rect_during=actual,client_visible_during=True,overlay_hidden_after=True)
            report['phase']='requesting-client-focus-return';save();return
        if phase=='requesting-client-focus-return':
            transition=report['foreground_transition']
            if control.capture.u.IsWindow(transition['sink_hwnd']):return
            if int(control.capture.u.GetForegroundWindow() or 0)!=control.client_target.hwnd:return
            actual=vars(control.capture.rect(control.client_target))
            assert actual==transition['client_rect_before'] and control.capture.u.IsWindowVisible(control.client_target.hwnd)
            transition.update(sink_destroyed=True,client_foreground_returned=True,client_rect_returned=actual)
            report['phase']='recovering-foreground';control.schedule_capture(100);save();return
        if phase=='await-game-window' and control.state.confirmed:finish();return
        if not session or session.stage!='assigned' or not control.overlay.isVisible() or control.capture_pending or control.ocr_busy:return
        if phase=='capturing-client':
            assert control.hero_auto.isChecked() and not control.hero_box.isEnabled()
            assert safety.get('before_second_observation_hidden') is True
            report['client_hero_reference']=inspect_client_hero(control)
            report.update(champion_select_own_row_passed=True,assignedHero=control.state.hero,clientGeneration=session.generation,
                client_hero_reference_passed=True,client_hero_no_confirmation_passed=True,client_hero_geometry_passed=True,phase='recapturing-client')
            checks.append('Real client pixels + local OCR reach production own-row/center detector twice; native hero-only synthetic T5 reference is visible with exact source/date/patch/version, HUD未复核, no augment cards or confirmation')
            save()
        elif phase=='recapture-complete':synthetic_negative('unknown')
        elif phase=='recovering-unknown':synthetic_negative('swap')
        elif phase=='recovering-swap':synthetic_negative('stale')
        elif phase=='recovering-stale':
            control.monitor.stop();hero=control.state.hero;control.state.hero='';control.check_target();hidden_unconfirmed()
            assert session.stage=='assigned' and session.assigned=='9001';safety['cleared_hero_hidden']=True
            control.state.hero=hero
            control.check_target();inspect_client_hero(control)
            report['foreground_transition']={'client_rect_before':vars(control.capture.rect(control.client_target)),
                'overlay_hwnd':int(control.overlay.winId()),'overlay_visible_before':control.overlay.isVisible(),
                'overlay_native_visible_before':bool(control.capture.u.IsWindowVisible(int(control.overlay.winId())))}
            report['phase']='testing-client-foreground-loss';save()
        elif phase=='recovering-foreground':
            # Foreground loss clears state.hero but does not erase the current
            # assignment. Measure two NEW observations without falsely claiming
            # that the production session requires two before any re-display.
            count=session.candidate_frames-report['foreground_recovery_start_count']
            if count<2:return
            report['foreground_recovery_observations']=count
            inspect_client_hero(control)
            checks.append('Actual recapture hides the hero overlay; actual owned foreground loss clears visible hero state; fresh OCR restores the matching reference and two post-interruption observations are measured. Separately injected unknown/swap/stale/cleared-hero handler cases revoke it')
            report['phase']='await-game-window';save()
    def prepare():
        if os.name!='nt' or app.platformName()!='windows' or not control.capture:raise RuntimeError('Requires real Windows Qt/capture backend')
        scale=float(os.environ.get('QT_SCALE_FACTOR','1'))
        if not math.isfinite(scale) or scale not in (1,1.5,2):raise ValueError('Unsupported selection diagnostic app scale')
        report['requested_app_scale']=scale
        if report['frozen']:
            with Path(sys.executable).open('rb') as binary:
                report['executable_sha256']=hashlib.file_digest(binary,'sha256').hexdigest()
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
        configure_data(control.data);hero=control.data['heroes'][DEMO_HERO];hero['alias'].append('星火术士')
        assert control.data['metadata'].get('isDemo') is True
        # Explicitly fictional overall tier, distinct from existing T1/T2/T3
        # augment rows. These dates/patches identify test data, not live data.
        hero.update(overallTier='T5',sourceVersion='0.1')
        control.data['metadata'].update(sourceDataDate='2026-01-02',gamePatch='0.2',wikiDataVersion='synthetic-selection-v1')
        from local_ocr import LocalOCR
        report['phase']='warming-client-ocr';save()
        control.ocr=LocalOCR();control.ocr.recognize((Path(__file__).resolve().parent/'fixtures/champselect-synthetic.png').read_bytes(),[])
        control.window_list.addItem('Original owned client fixture',target);control.window_list.setCurrentIndex(control.window_list.count()-1)
        control.hero_auto.setChecked(True);control.client_follow.setChecked(True);control.start_monitor()
        assert control.state.running and control.selection_session and control.window_policy
        assert control.window_policy.permits(target)
        control.hide();control.capture.u.SetForegroundWindow.argtypes=[W.HWND];control.capture.u.SetForegroundWindow.restype=W.BOOL;control.capture.u.SetForegroundWindow(target.hwnd)
        report['phase']='capturing-client';save();timer.timeout.connect(lambda:guarded(poll));timer.start()
    save();guarded(prepare)

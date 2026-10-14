"""Actual Windows Qt/GDI/CPU-OCR smoke against our OWN synthetic mock window.

Only this explicit diagnostic saves an original synthetic screenshot. Normal
monitoring never writes image buffers to disk and never sends them to a service.
"""
from pathlib import Path
import ctypes
from ctypes import wintypes as W
import json
import hashlib
import math
import os
import sys
import threading
import time
import traceback
from PySide6 import QtCore,QtGui,QtWidgets
from native_state import display_cards


def smoke_dimensions(width,height):
    if any(not isinstance(v,int) or isinstance(v,bool) for v in (width,height)) or width<1000 or height<640:
        raise ValueError('Physical desktop work area cannot fit the fixed960x600 own-HUD mock with20px margins')
    return 960,600

def smoke_pixmap(portrait,cards_path,width,height,dpr,*,changed_roi=False):
    """Original fixed-physical diagnostic artwork, never a user screenshot."""
    from PIL import Image
    from synthetic_vision import frame,encoded
    if not math.isfinite(dpr) or dpr<=0:raise ValueError('Invalid artwork DPR')
    canvas=frame(portrait,width=width,height=height)
    cards=Image.open(cards_path).convert('RGB').resize((width,height),Image.Resampling.LANCZOS)
    canvas.paste(cards.crop((0,0,width,round(height*.8))),(0,0))
    if changed_roi:
        # Original non-text animation analogue: inside the candidate crop but
        # entirely above the .32h+ title band and outside the own-HUD input.
        left,top=round(width*.20),round(height*.27);canvas.paste((75,60,85),(left,top,left+12,top+12))
    pixmap=QtGui.QPixmap()
    if not pixmap.loadFromData(encoded(canvas)):raise RuntimeError('Original mock artwork could not be decoded')
    pixmap.setDevicePixelRatio(dpr)
    return pixmap


def shrink_smoke_mock(mock,image):
    """Release only the owned fixture's pixmap minimum before resize testing."""
    before=mock.size()
    image.clear();mock.layout().invalidate();mock.layout().activate()
    mock.resize(before.width()-20,before.height()-20)
    QtWidgets.QApplication.processEvents()
    assert mock.width()<before.width() and mock.height()<before.height(),'Owned diagnostic mock did not shrink'


def inspect_smoke_layout(overlay):
    """Diagnostic-only check of actual visible Qt layout, including text fit."""
    if not overlay.isVisible():raise AssertionError('Overlay is not visible')
    rows=[]
    for widget in overlay.findChildren(QtWidgets.QWidget):
        if not widget.isVisibleTo(overlay):continue
        parent=widget.parentWidget();pos=widget.mapTo(overlay,QtCore.QPoint(0,0))
        assert widget.width()>0 and widget.height()>0
        assert pos.x()>=0 and pos.y()>=0 and pos.x()+widget.width()<=overlay.width() and pos.y()+widget.height()<=overlay.height(),'Visible widget escapes overlay'
        if parent:
            assert widget.x()>=0 and widget.y()>=0 and widget.x()+widget.width()<=parent.width() and widget.y()+widget.height()<=parent.height(),'Visible widget escapes parent'
        row={'type':type(widget).__name__,'logical_rect':{'x':pos.x(),'y':pos.y(),'width':widget.width(),'height':widget.height()}}
        if isinstance(widget,QtWidgets.QLabel):
            required=widget.heightForWidth(widget.width());minimum=widget.minimumSizeHint().width()
            assert required<=widget.height()+1,('Label height clipped',widget.text(),required,widget.height())
            assert minimum<=widget.width()+1,('Label width clipped',widget.text(),minimum,widget.width())
            row.update(text=widget.text(),required_height_at_width=required,minimum_width=minimum)
        rows.append(row)
    assert len(overlay.cards)==3 and len(overlay.tier_labels)==3 and all(label.isVisibleTo(overlay) for label in overlay.tier_labels)
    assert overlay.metadata_label.isVisibleTo(overlay) is (not overlay._compact)
    assert '来源日期' in overlay.metadata_label.text() and '非 Riot' in overlay.footer.text()
    assert overlay.footer.isVisibleTo(overlay) and overlay.footer.text()==overlay._source_marker+' · 非 Riot 评级/批准'
    for i,card in enumerate(overlay.cards):
        labels=overlay.row.itemAt(i).widget().findChildren(QtWidgets.QLabel)
        assert labels[0].isVisibleTo(overlay) and labels[0].text()==card['name']
        assert labels[0].accessibleName()==f"选项 {card['slot']} · {card['name']}"
        assert overlay.tier_labels[i].text()==(card.get('sourceTier') or '暂无评级')
        assert overlay.tier_labels[i].accessibleName()==f"{card.get('sourceTierLabel','虎牙公开源评级')}：{card.get('sourceTier') or '暂无评级'}"
    return rows


class OverlayDutyTrace:
    """Diagnostic sampled HWND duty cycle; never a production speed claim.

    Native visibility is sampled at capture boundaries, phase dispatch and Qt
    timer ticks. Durations use the preceding sample, so the maximum sample gap
    is reported alongside them. The old hide-until-final policy is an explicit
    same-run counterfactual, not a measurement of another executable.
    """
    def __init__(self,name,*,clock=time.monotonic):
        self.name=name;self.clock=clock;self.started=clock();self.events={}
        self.samples=[];self.phases=[];self.helpers=[];self.holds={};self.hold_started={};self.hold_elapsed={}
        self.held_state_samples=0;self.qt_show_events_during_capture=0;self.capture_active=False;self.capture_count=0;self.capture_concurrency=0;self.max_capture_concurrency=0;self.finished=False;self.stopped=False;self.error=None
        self.lock=threading.Lock()
    def mark(self,name):
        with self.lock:self.events[name]=(self.clock()-self.started)*1000
    def sample(self,visible,*,capturing=False):
        with self.lock:self.samples.append(((self.clock()-self.started)*1000,bool(visible),bool(capturing)))
    def summary(self):
        total=self.events['final']
        points=sorted((min(stamp,total),shown,capturing) for stamp,shown,capturing in self.samples);hidden=visible=inference_visible=gap=0.;capture_samples=capture_visible=0
        for index,(stamp,shown,capturing) in enumerate(points):
            if capturing:capture_samples+=1;capture_visible+=int(shown)
            if index+1<len(points):
                elapsed=points[index+1][0]-stamp;gap=max(gap,elapsed)
                if shown:
                    visible+=elapsed
                    inference_visible+=max(0.,points[index+1][0]-max(stamp,self.events.get('capture_return',float('inf'))))
                else:hidden+=elapsed
        return {'name':self.name,'status':'passed','timings_ms':{key:round(value,3) for key,value in self.events.items()},
                'total_ms':round(total,3),'sampled_hidden_ms':round(hidden,3),'sampled_visible_ms':round(visible,3),
                'sampled_inference_visible_ms':round(inference_visible,3),'max_sample_gap_ms':round(gap,3),'native_visibility_samples':len(points),
                'capture_samples':capture_samples,'capture_visible_samples':capture_visible,
                'capture_count':self.capture_count,'max_capture_concurrency':self.max_capture_concurrency,'held_state_unchanged_samples':self.held_state_samples,
                'qt_show_events_during_capture':self.qt_show_events_during_capture,
                'sampled_visibility_transitions':[{'at_ms':round(stamp,3),'visible':shown} for index,(stamp,shown,_) in enumerate(points) if index==0 or shown!=points[index-1][1]],
                'artificial_holds_ms':{key:round(value,3) for key,value in self.hold_elapsed.items()},
                'old_hide_until_final_policy_counterfactual_ms':round(total,3),
                'comparison_scope':'Counterfactual whole-cycle hidden duration on this same instrumented run; not a measured baseline executable',
                'phases':self.phases}


def start_overlay_duty_probe(control,*,app,u,paint_mock,report,checks,save,run,done):
    """Actual owned-window acquisition and handlers, with explicit phase holds.

    Only diagnostics wrap production recognize_frame and Popen, forwarding
    all arguments and results unchanged. No recognition result is mocked.
    The concrete PortraitMatcher remains installed so its exact early HUD
    input signature is exercised before expensive matching and real OCR.
    """
    from hero_recognition import PortraitMatcher
    import hero_recognition
    import wgc_capture
    from session_windows import process_metadata
    overlay=control.overlay;hwnd=int(overlay.winId());capture_adapter=control.capture
    original_recognize=hero_recognition.recognize_frame;original_capture=capture_adapter.capture
    original_compositor=capture_adapter.validate_compositor;original_popen=wgc_capture.subprocess.Popen
    original_schedule=control.schedule_capture;active=[None];rows=[];main_thread=threading.get_ident()
    control.monitor.stop();control.schedule_capture=lambda delay=None:None
    control.hero_auto.setChecked(True);control.state.clear_hero();control.ocr_reuse.clear()
    control._accepted_frame=None;control.overlay.hide()
    report['overlay_duty_cycle']={'schema_version':1,'scope':'Original synthetic native Windows HWND + real capture/PortraitMatcher/OCR; controlled diagnostic holds, not live-game or user-machine latency',
        'artificial_hold_target_ms':350,'cases':rows}
    def snapshot():
        return {'last_observation':control.last_observation,'automatic_frames':control.state.automatic_frames,
                'hero_stable_frames':control.state.hero_stable_frames,'stable_frames':control.state.stable_frames,
                'generation':control.state.generation,'accepted_observed_at':control._accepted_frame['observed_at'] if control._accepted_frame else None}
    def native_visible():return bool(u.IsWindowVisible(hwnd))
    def helper_cleanup(trace):
        helper=getattr(capture_adapter,'_wgc',None)
        return all(process.poll() is not None for process in trace.helpers) and not getattr(helper,'_pending_cleanup',None) and not getattr(helper,'_pending_job',None)
    class VisibilityGuard(QtCore.QObject):
        def eventFilter(self,watched,event):
            trace=active[0]
            if trace is not None and trace.capture_active and event.type()==QtCore.QEvent.Type.Show:
                trace.qt_show_events_during_capture+=1;trace.error=AssertionError('Own overlay Show event during native capture/helper lifetime')
            return False
    visibility_guard=VisibilityGuard(overlay);overlay.installEventFilter(visibility_guard)
    def watched_popen(args,*arguments,**keywords):
        process=original_popen(args,*arguments,**keywords);trace=active[0]
        helper=getattr(capture_adapter,'_wgc',None)
        if trace is not None and helper is not None and args and str(args[0])==str(helper.helper_path):trace.helpers.append(process)
        return process
    def watched_compositor(*arguments,**keywords):
        value=original_compositor(*arguments,**keywords);trace=active[0]
        if trace is not None and threading.get_ident()==main_thread:trace.mark('gui_compositor_validated')
        return value
    def watched_capture(*arguments,**keywords):
        trace=active[0]
        if trace is None:return original_capture(*arguments,**keywords)
        trace.capture_active=True;trace.capture_count+=1;trace.capture_concurrency+=1;trace.max_capture_concurrency=max(trace.max_capture_concurrency,trace.capture_concurrency)
        trace.mark('capture_start');trace.sample(native_visible(),capturing=True)
        assert not native_visible(),'Own native overlay visible at pixel acquisition entry'
        try:
            value=original_capture(*arguments,**keywords)
            assert not native_visible(),'Own native overlay visible before capture/helper return'
            assert helper_cleanup(trace),'Capture helper has not fully exited/cleaned up'
            trace.sample(native_visible(),capturing=True);trace.mark('capture_return')
            trace.backend=capture_adapter.last_backend;return value
        finally:trace.capture_active=False;trace.capture_concurrency-=1
    def watched_recognize(*arguments,before_match=None,before_ocr=None,**keywords):
        trace=active[0]
        assert type(arguments[4]) is PortraitMatcher,'Duty probe must exercise the concrete production matcher'
        def phase(name,callback,*values):
            assert trace is not None and 'capture_return' in trace.events and helper_cleanup(trace),'Phase preceded completed native capture/helper cleanup'
            trace.mark(name+'_emitted')
            if trace.name in ('unchanged','changed_roi','changed_hud','unknown_hud','stop_late'):
                trace.holds[name]=threading.Event();trace.hold_started[name]=time.monotonic()
            callback(*values)
            if name in trace.holds:
                assert trace.holds[name].wait(4),'GUI did not release diagnostic phase hold'
                trace.hold_elapsed[name]=(time.monotonic()-trace.hold_started[name])*1000
        return original_recognize(*arguments,before_match=lambda *values:phase('before_match',before_match,*values),
            before_ocr=lambda *values:phase('before_ocr',before_ocr,*values),**keywords)
    def observed(kind,value,generation):
        trace=active[0]
        if trace is None or kind not in ('capture-proof','ocr'):return
        try:
            if kind=='capture-proof':
                name='before_ocr' if 'hero_observation' in value else 'before_match';trace.mark(name+'_applied')
                current_rect=capture_adapter.rect(control.target);accepted=trace.accepted or {}
                def rectangle(rect):return {key:getattr(rect,key) for key in ('x','y','width','height')}
                scope=value['_frameScope']
                current=(tuple(value['_windowIdentity'])==control.target.identity and capture_adapter.rect(control.target)==value['_captureRect']
                    and capture_adapter.foreground(control.target) and control.target_allowed())
                phase={'name':name,'emitted_ms':round(trace.events[name+'_emitted'],3),'applied_ms':round(trace.events[name+'_applied'],3),
                    'compositor_validated_ms':round(trace.events.get('gui_compositor_validated',-1),3),'restored':bool(control._restore_while_ocr),'qt_visible':overlay.isVisible(),'native_visible':native_visible(),
                    'state_unchanged':snapshot()==trace.before,'state_before':trace.before,'state_at_phase':snapshot(),
                    'current_identity_geometry_focus':bool(current),'helper_cleanup_complete':bool(helper_cleanup(trace)),
                    'window_identity':list(value['_windowIdentity']),'current_window_identity':list(control.target.identity),
                    'capture_rect':rectangle(value['_captureRect']),'current_rect':rectangle(current_rect),
                    'candidate_roi_sha256':value.get('_roiDigest'),'accepted_candidate_roi_sha256':accepted.get('digest'),
                    'hud_input_sha256':value.get('_hudInputDigest'),'accepted_hud_input_sha256':accepted.get('hud_digest'),
                    'scope_matches_accepted':scope==accepted.get('scope'),'roi':list(scope[3]),
                    'vocabulary_sha256':hashlib.sha256(json.dumps(scope[4],ensure_ascii=False).encode()).hexdigest(),
                    'source_metadata_sha256':hashlib.sha256(scope[5][1].encode()).hexdigest(),
                    'matcher_type':type(control.hero_matcher).__name__,'matcher_instance_matches_accepted':bool(accepted and scope[6][0] is accepted['scope'][6][0] is control.hero_matcher),
                    'matcher_configuration':[control.hero_matcher.minimum_score,control.hero_matcher.minimum_margin],
                    'capture_serial':value['_captureSerial'],'captured_at':value['_capturedAt'],
                    'compositor_checked_after_capture':trace.events.get('gui_compositor_validated',-1)>=trace.events['capture_return']}
                trace.phases.append(phase)
                assert helper_cleanup(trace) and current,'Native capture proof is no longer current'
                if trace.name in ('unchanged','stop_late'):
                    assert all(phase[key] for key in ('restored','qt_visible','native_visible','state_unchanged','compositor_checked_after_capture')),'Unchanged accepted capture was not safely restored before slow inference'
                elif trace.name in ('changed_roi','changed_hud','unknown_hud'):
                    assert not any(phase[key] for key in ('restored','qt_visible','native_visible')),'Changed/unknown own HUD restored old cards'
                    assert phase['state_unchanged'],'Intermediate proof must not refresh TTL or confirmation counters'
            else:
                trace.mark('final');trace.sample(native_visible());trace.finished=True
                trace.final_generation=generation;trace.final_value=value
        except Exception as exc:trace.error=AssertionError(trace.name+': '+str(exc));trace.finished=True
    def observed_error(kind,error,generation):
        trace=active[0]
        if trace is not None and kind=='ocr':trace.error=AssertionError('Production duty capture '+trace.name+' failed: '+error);trace.finished=True
    capture_adapter.capture=watched_capture;capture_adapter.validate_compositor=watched_compositor
    hero_recognition.recognize_frame=watched_recognize;wgc_capture.subprocess.Popen=watched_popen
    control.signals.result.connect(observed);control.signals.error.connect(observed_error)
    def cleanup():
        trace=active[0]
        if trace:
            for release in trace.holds.values():release.set()
        overlay.removeEventFilter(visibility_guard);visibility_guard.deleteLater()
        capture_adapter.capture=original_capture;capture_adapter.validate_compositor=original_compositor
        hero_recognition.recognize_frame=original_recognize;wgc_capture.subprocess.Popen=original_popen
        control.signals.result.disconnect(observed);control.signals.error.disconnect(observed_error)
        control.schedule_capture=original_schedule;control.monitor.stop();active[0]=None;control._smoke_duty_cleanup=None
    # Failures release only our diagnostic holds before ordinary shutdown.
    control._smoke_duty_cleanup=cleanup
    def begin(name,done):
        assert not control.ocr_busy and not control.capture_pending
        trace=OverlayDutyTrace(name);trace.before=snapshot();trace.accepted=control._accepted_frame;active[0]=trace
        report['overlay_duty_cycle']['active_case']={'name':name,'timings_ms':trace.events,'phases':trace.phases}
        trace.sample(native_visible());control.capture_tick();trace.sample(native_visible())
        deadline=time.monotonic()+8
        def poll():
            try:
                assert time.monotonic()<deadline,'Production duty capture exceeded its existing timeout'
                if trace.error:raise trace.error
                if trace.capture_active:assert not native_visible() and not overlay.isVisible(),'Own overlay visible during native pixel acquisition'
                if not trace.finished:
                    control.check_target();trace.sample(native_visible(),capturing=trace.capture_active)
                    for name,release in list(trace.holds.items()):
                        if release.is_set() or name+'_applied' not in trace.events:continue
                        assert snapshot()==trace.before,'TTL or confirmation counters changed during diagnostic inference hold'
                        trace.held_state_samples+=1
                        if time.monotonic()-trace.hold_started[name]<.35:continue
                        if trace.name=='stop_late' and name=='before_ocr':
                            trace.mark('stop');started=time.monotonic();control.stop_monitor();trace.stop_ms=(time.monotonic()-started)*1000;trace.stopped=True
                            assert not native_visible() and not overlay.isVisible() and not control.state.running and not control.state.confirmed
                            trace.sample(native_visible())
                        release.set()
                    QtCore.QTimer.singleShot(10,lambda:run(poll));return
                assert not control.ocr_busy and not control.capture_pending
                if trace.name in ('unchanged','changed_roi','changed_hud','unknown_hud','stop_late'):
                    value=trace.summary();value.update(capture_backend=trace.backend,helper_count=len(trace.helpers),helper_exit_codes=[process.poll() for process in trace.helpers],
                        helper_cleanup_complete_before_phase=all(phase['helper_cleanup_complete'] for phase in trace.phases),
                        final_confirmed=control.state.confirmed,final_running=control.state.running,final_qt_visible=overlay.isVisible(),final_native_visible=native_visible(),
                        final_state_generation=control.state.generation,final_result_generation=trace.final_generation,final_captured_at=trace.final_value['_capturedAt'],
                        final_last_observation=control.last_observation,final_candidate_names=[item['name'] for item in trace.final_value.get('automatic_candidates',[])],final_hero_observation={key:trace.final_value['hero_observation'].get(key) for key in ('hero','confident')})
                    assert value['capture_samples']>=2 and value['capture_visible_samples']==0 and value['qt_show_events_during_capture']==0
                    assert [phase['name'] for phase in value['phases']]==['before_match','before_ocr']
                    assert all(phase['state_unchanged'] for phase in value['phases'])
                    if trace.name=='unchanged':
                        assert control.state.confirmed and control.state.confirmation_mode=='automatic' and value['sampled_inference_visible_ms']>=500
                        assert trace.final_value['hero_observation']['hero']=='星火术士（演示）'
                    elif trace.name=='changed_roi':
                        value['fixture_change']='Original 12x12 non-text patch inside candidate ROI, above title band; synthetic animation analogue, not actual gameplay measurement'
                        assert control.state.confirmed and overlay.isVisible() and native_visible() and value['sampled_inference_visible_ms']==0
                        assert value['final_candidate_names']==['星火共鸣','晶盾回路','风步微光']
                        assert all(phase['candidate_roi_sha256']!=phase['accepted_candidate_roi_sha256'] and phase['hud_input_sha256']==phase['accepted_hud_input_sha256'] for phase in value['phases'])
                    elif trace.name in ('changed_hud','unknown_hud'):
                        assert not control.state.confirmed and not native_visible() and value['sampled_inference_visible_ms']==0
                        hero=trace.final_value['hero_observation']
                        assert (hero.get('hero')=='磐石守卫（演示）' and hero.get('confident') is True) if trace.name=='changed_hud' else hero.get('confident') is not True
                    else:
                        value.update(stop_return_ms=round(trace.stop_ms,3),late_final_discarded=bool(trace.stopped and trace.events['final']>trace.events['stop']
                            and trace.final_generation!=control.state.generation and not control.state.running and not control.state.confirmed and not native_visible() and control._accepted_frame is None))
                        assert value['late_final_discarded'] and trace.stop_ms<250
                    rows.append(value)
                active[0]=None;done()
            except Exception:
                cleanup();raise
        QtCore.QTimer.singleShot(10,lambda:run(poll))
    def assert_first_then(second):
        assert not control.state.confirmed and control.state.automatic_frames==1,'First actual fresh frame must not confirm'
        begin('independent_second',second)
    def established(next_step):
        assert control.state.confirmed and control.state.confirmation_mode=='automatic' and control.state.automatic_frames==2
        assert control._accepted_frame and control._accepted_frame['hud_digest'],'Actual automatic result did not establish exact HUD proof'
        next_step()
    def recover(next_step,*,restart=False,reset=False):
        if reset:control.invalidate_scene('Original diagnostic ROI reset; re-establish independent frame proof')
        paint_mock();app.processEvents();control.ocr_reuse.clear()
        if restart:
            control.manual_metadata=process_metadata(control.target.pid);control.manual_identity=control.target.identity;control.state.start(control.target.identity);control.state.clear_hero()
        begin('independent_first',lambda:assert_first_then(lambda:established(next_step)))
    def changed_roi():
        paint_mock(changed_roi=True);app.processEvents();begin('changed_roi',lambda:recover(changed,reset=True))
    def changed():
        paint_mock('9002');app.processEvents();begin('changed_hud',lambda:recover(unknown))
    def unknown():
        paint_mock(gray=True);app.processEvents();begin('unknown_hud',lambda:recover(stop_late))
    def stop_late():begin('stop_late',lambda:recover(finish,restart=True))
    def finish():
        assert [row['name'] for row in rows]==['unchanged','changed_roi','changed_hud','unknown_hud','stop_late']
        cleanup();report['overlay_duty_cycle'].pop('active_case',None);report['overlay_duty_cycle_passed']=True
        checks.append('Actual Windows capture stays hidden until helper exit; identical accepted ROI/HUD restores during two controlled 350 ms inference holds without refreshing TTL/counters; changed candidate ROI and changed/unknown HUD veto; Stop discards late actual OCR')
        save();QtCore.QTimer.singleShot(100,lambda:run(done))
    begin('independent_first',lambda:assert_first_then(lambda:established(lambda:begin('unchanged',changed_roi))))


def start_smoke(control,report_path,screenshot_path):
    app=QtWidgets.QApplication.instance();checks=[];root=Path(__file__).resolve().parent
    report={'status':'running','executable_sha256':hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest() if getattr(sys,'frozen',False) else None,'backend':'qtwidgets','qt_platform':app.platformName(),'frozen':bool(getattr(sys,'frozen',False)),'applicationVersion':control.current_version,'native_window':False,'window_closed':False,'capture_passed':False,'ocr_passed':False,'click_through_passed':False,'scope':'Original synthetic mock game only; not LoL/Vanguard, live-game accuracy or approval','checks':checks}
    control._smoke_objects=[]
    def save():
        report_path.parent.mkdir(parents=True,exist_ok=True);report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    def fail(exc):
        cleanup=getattr(control,'_smoke_duty_cleanup',None)
        if cleanup:
            control._smoke_duty_cleanup=None
            try:cleanup()
            except Exception:pass
        report.update(status='failed',error=str(exc)[:2000],error_type=type(exc).__name__,error_traceback=traceback.format_exc(limit=4)[-4000:]);save()
        for widget in control._smoke_objects:widget.close()
        control.close();app.exit(1)
    def run(fn):
        try:fn()
        except Exception as exc:fail(exc)
    if os.name!='nt' or app.platformName()!='windows':return fail(RuntimeError('Native Windows smoke requires the real Windows Qt platform, not offscreen/minimal.'))
    if not control.capture:return fail(RuntimeError('Win32 capture adapter unavailable'))
    control.watchdog.stop();control.monitor.stop()
    # SPI_GETWORKAREA only reads physical bounds; never change OS settings.
    u=control.capture.u;u.SystemParametersInfoW.argtypes=[W.UINT,W.UINT,W.LPVOID,W.UINT];u.SystemParametersInfoW.restype=W.BOOL
    available=W.RECT()
    if not u.SystemParametersInfoW(0x0030,0,ctypes.byref(available),0):return fail(RuntimeError('Physical work area unavailable'))
    work_area={'x':available.left,'y':available.top,'width':available.right-available.left,'height':available.bottom-available.top}
    mock_width,mock_height=smoke_dimensions(work_area['width'],work_area['height'])
    requested_scale=float(os.environ.get('QT_SCALE_FACTOR','1'))
    if not math.isfinite(requested_scale) or not .5<=requested_scale<=4:return fail(ValueError('Unsupported diagnostic app scale'))
    report.update(requested_app_scale=requested_scale,desktop_work_area_physical=work_area)
    mock=QtWidgets.QWidget(None,QtCore.Qt.WindowType.Window|QtCore.Qt.WindowType.FramelessWindowHint);mock.setWindowTitle('VGA original synthetic mock game');mock.winId()
    mock_dpr=float(mock.windowHandle().devicePixelRatio())
    if not math.isfinite(mock_dpr) or mock_dpr<=0:return fail(ValueError('Invalid native mock DPR'))
    mock.resize(round(mock_width/mock_dpr),round(mock_height/mock_dpr))
    def native_rect(hwnd):
        rect=W.RECT()
        if not u.GetWindowRect(hwnd,ctypes.byref(rect)):raise RuntimeError('Owned native window rectangle unavailable')
        return {'x':rect.left,'y':rect.top,'width':rect.right-rect.left,'height':rect.bottom-rect.top}
    def inside(outer,inner):
        return inner['width']>0 and inner['height']>0 and inner['x']>=outer['x'] and inner['y']>=outer['y'] and inner['x']+inner['width']<=outer['x']+outer['width'] and inner['y']+inner['height']<=outer['y']+outer['height']

    layout=QtWidgets.QVBoxLayout(mock);layout.setContentsMargins(0,0,0,0)
    image=QtWidgets.QLabel();image.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
    from synthetic_vision import portraits,configure_data
    from hero_recognition import PortraitMatcher,recognize_frame
    bank=portraits()
    configure_data(control.data)
    control.hero_matcher=PortraitMatcher(bank,control.data['heroes'])
    def paint_mock(key='9001',*,gray=False,changed_roi=False):
        portrait=bank[key].convert('L').convert('RGB') if gray else bank[key]
        image.setPixmap(smoke_pixmap(portrait,root/'fixtures/auto-scene.png',mock_width,mock_height,float(mock.windowHandle().devicePixelRatio()),changed_roi=changed_roi))
    paint_mock();layout.addWidget(image)
    control._smoke_objects.append(mock)
    def prepare():
        control.hide();mock.show()
        assert u.SetWindowPos(int(mock.winId()),None,work_area['x']+20,work_area['y']+20,mock_width,mock_height,0x0004|0x0040),'Could not place owned physical mock'
        app.processEvents();paint_mock();app.processEvents();mock.raise_();mock.activateWindow()
        actual=control.capture.rect(control.capture.info(int(mock.winId())))
        assert (actual.width,actual.height)==(mock_width,mock_height),('Mock physical dimensions changed',actual)
        assert inside(work_area,native_rect(int(mock.winId()))),'Owned mock must be fully inside physical work area'
        report.update(mock_qwindow_dpr=float(mock.windowHandle().devicePixelRatio()),mock_window_physical=native_rect(int(mock.winId())),physical_mock_geometry_passed=True)

        report['controlHwnd']=int(control.winId());report['mockHwnd']=int(mock.winId());report['overlayHwnd']=int(control.overlay.winId())
        report['native_window']=all(control.capture.u.IsWindow(h) for h in (report['controlHwnd'],report['mockHwnd'],report['overlayHwnd']))
        assert report['native_window'];checks.append('Real QtWidgets control, overlay and synthetic mock HWNDs exist')
        QtCore.QTimer.singleShot(700,lambda:run(capture))
    def capture():
        target=control.capture.info(int(mock.winId()));control.target=target
        from session_windows import process_metadata
        control.manual_metadata=process_metadata(target.pid);control.manual_identity=target.identity
        control.overlay.hide();captured_at=time.monotonic();bytes_,rect=control.capture.capture(target)
        report['capture_passed']=True;report['captureBytes']=len(bytes_);report['clientRect']={'x':rect.x,'y':rect.y,'width':rect.width,'height':rect.height}
        checks.append('Windows capture returned only selected mock client area into an in-memory PNG')
        from local_ocr import LocalOCR
        engine=LocalOCR();control.ocr=engine
        expected=['星火共鸣','晶盾回路','风步微光']
        control.hero_auto.setChecked(True);control.state.clear_hero();control.state.start(target.identity)
        assert control.state.hero=='' and control.hero_auto.isChecked()
        def observe_current():
            control.overlay.hide();assert not control.overlay.isVisible()
            assert not control.capture.u.IsWindowVisible(int(control.overlay.winId()))
            captured_at=time.monotonic();pixels,_=control.capture.capture(target)
            scoped=control.ocr_reuse.scoped(engine,(target.identity,(.15,.25,.7,.35),'game'),allow_reuse=control.state.confirmed and control.state.confirmation_mode=='automatic')
            value=recognize_frame(pixels,(.15,.25,.7,.35),scoped,control.data['augments'],control.hero_matcher)
            if time.monotonic()-captured_at>3:
                captured_at=time.monotonic();pixels,_=control.capture.capture(target);value=recognize_frame(pixels,(.15,.25,.7,.35),engine,control.data['augments'],control.hero_matcher)
            value['_capturedAt']=captured_at
            control.task_result('ocr',value,control.state.generation)
            return value
        result=observe_current();assert not control.state.confirmed
        result=observe_current();names=[item['name'] for item in result['automatic_candidates']]
        assert names==expected,('OCR names',names)
        assert control.state.hero=='星火术士（演示）' and control.state.confirmed and control.state.confirmation_mode=='automatic'
        assert control.hero_auto.isChecked() and not control.hero_box.isEnabled()
        report.update(automatic_hero_passed=True,automatic_choices_passed=True,auto_without_manual_hero_selection=True,own_overlay_hidden_capture_passed=True)
        report['ocr_passed']=True;report['recognized']=names;checks.append('Actual OS capture + original synthetic portrait matcher + OCR feed production handlers; two frames auto-confirm hero and three cards without hero selection or confirm click')
        independent_misses=control.ocr_reuse.misses;independent_frames=control.state.automatic_frames
        reused=observe_current()
        assert reused.get('ocr_reused') is True and control.ocr_reuse.misses==independent_misses
        assert control.state.confirmed and control.state.automatic_frames==independent_frames
        report['unchanged_frame_ocr_reuse_passed']=True
        checks.append('A third fresh owned-window capture reuses byte-identical title OCR only after two independent confirmations; reused OCR does not increase confirmation counters')
        report['targetForegroundBefore']=int(control.capture.u.GetForegroundWindow() or 0)
        unknown={**result,'hero_observation':{'hero':None,'confident':False,'reason':'Synthetic unknown portrait'},'_capturedAt':time.monotonic()}
        control.task_result('ocr',unknown,control.state.generation);assert not control.state.confirmed and control.state.hero=='' and not control.overlay.isVisible();report['auto_unknown_clears_passed']=True
        observe_current();observe_current();assert control.state.confirmed
        def change_hero(key,expected_hero):
            paint_mock(key);app.processEvents()
            first=observe_current()
            assert not control.state.confirmed and control.state.hero=='' and not control.overlay.isVisible(),'Changed hero must immediately revoke the old hero and overlay'
            reused=first.get('ocr_reused') is True
            independent=0 if reused else 1
            assert control.state.automatic_frames==independent,'A reused transition cannot count as independent OCR'
            observations=[{'reused':reused,'independent_frames':independent,'confirmed':False}]
            # Cache expiry can make the first transition already fresh. Either
            # way exactly two independent new-hero inferences are required;
            # a discarded unchanged-title hit never supplies confirmation.
            for expected_frames in range(independent+1,3):
                current=observe_current()
                assert current.get('ocr_reused') is not True,'Unconfirmed hero transition must run fresh OCR'
                assert control.state.automatic_frames==expected_frames,'Unexpected independent confirmation count'
                assert control.state.confirmed is (expected_frames==2),'Hero changed without two independent new observations'
                if not control.state.confirmed:assert not control.overlay.isVisible()
                observations.append({'reused':False,'independent_frames':expected_frames,'confirmed':control.state.confirmed})
            assert control.state.hero==expected_hero and control.state.confirmed,'New hero did not confirm after two independent observations'
            return observations
        report['hero_transition_observations']=[change_hero('9002','磐石守卫（演示）'),change_hero('9001','星火术士（演示）')]
        report['auto_hero_change_clears_passed']=True
        checks.append('Both hero transitions immediately hide old cards; a reused title is discarded and exactly two independent new-hero OCR results are required')
        assert [card['name'] for card in control.overlay.cards]==names
        assert [card['sourceTier'] for card in control.overlay.cards]==['T1','T2','T3']
        assert [widget.text() for widget in control.overlay.tier_labels]==['T1','T2','T3']
        assert [widget.accessibleName() for widget in control.overlay.tier_labels]==['虚构源评级（演示）：T1','虚构源评级（演示）：T2','虚构源评级（演示）：T3']
        assert '来源日期' in control.overlay.metadata_label.text() and '数据包' in control.overlay.metadata_label.text() and '游戏资料' in control.overlay.metadata_label.text()
        control.hero_box.setCurrentText('磐石守卫（演示）');assert not control.state.confirmed and not control.overlay.isVisible()
        control.confirm();assert [card['name'] for card in control.overlay.cards]==names and [card['sourceTier'] for card in control.overlay.cards]==['T3','T1','T2']
        report['source_tier_hero_specific']=True;report['auto_manual_fallback_passed']=not control.hero_auto.isChecked()
        tier_row=control.data['heroAugmentStats']['磐石守卫（演示）'][0];saved_tier=tier_row['tier']
        for missing in [None,'UNKNOWN']:
            tier_row['tier']=missing;control.confirm();assert control.overlay.tier_labels[1].text()=='暂无评级' and control.overlay.tier_labels[1].accessibleName()=='虚构源评级（演示）：暂无评级'
        tier_row['tier']=saved_tier;report['source_tier_missing_passed']=True
        control.hero_box.setCurrentText('星火术士（演示）');control.confirm()
        assert [card['name'] for card in control.overlay.cards]==names
        assert all('winRate' not in card and 'sourceRank' not in card and 'recommendedName' not in card for card in control.overlay.cards)
        rendered=' '.join(widget.text() for widget in control.overlay.tier_labels)
        assert all(value not in rendered for value in ['60.00%','55.00%','50.00%','胜率'])
        report.update(source_tier_display_passed=True,source_tier_screen_order_preserved=True,source_tier_no_winrate_display=True,
                      source_tier_rendered=[widget.text() for widget in control.overlay.tier_labels],
                      card_names_rendered=[widget.text() for widget in control.overlay._title_labels],
                      source_tier_accessible=[widget.accessibleName() for widget in control.overlay.tier_labels],
                      source_attribution_rendered=control.overlay.footer.text())
        before=(control.state.generation,control.state.confirmed,control.state.offered,control.overlay.isVisible())
        control.show_page('about');app.processEvents()
        assert control.source.isVisibleTo(control) and control.compatibility.isVisibleTo(control)
        assert all(text in control.source.text() for text in ('来源日期','数据包','游戏资料版本')) and '尚未验证' in control.compatibility.text()
        control.show_page('main');assert (control.state.generation,control.state.confirmed,control.state.offered,control.overlay.isVisible())==before
        report['source_details_reachable']=True
        checks.append('Actual native source-tier labels are hero-specific literals; null/unknown remain ungraded; screen order preserved with no win-rate/rank/best-choice fields')
        QtCore.QTimer.singleShot(50,lambda:run(verify_async_capture))
    def verify_async_capture():
        before=control.last_observation;deadline=time.monotonic()+8;busy_ticks=[]
        control.capture_tick()
        def poll():
            assert time.monotonic()<deadline,'Production asynchronous capture/OCR did not finish within its stale limit'
            if control.ocr_busy:
                busy_ticks.append(time.monotonic())
                control.check_target()
                assert not control.overlay.isVisible(),'Watchdog restored own overlay during capture/inference'
            if control.capture_pending or control.ocr_busy:
                QtCore.QTimer.singleShot(20,lambda:run(poll));return
            assert busy_ticks and control.last_observation>before and control.state.confirmed
            report['async_capture_ui_passed']=True
            checks.append('Actual frozen production capture worker completed while Qt timers ran; manual-mode watchdog kept own overlay hidden until the accepted fresh result')
            QtCore.QTimer.singleShot(50,lambda:run(verify_duty_cycle))
        QtCore.QTimer.singleShot(20,lambda:run(poll))
    def verify_duty_cycle():
        start_overlay_duty_probe(control,app=app,u=u,paint_mock=paint_mock,report=report,checks=checks,save=save,run=run,done=verify_overlay)
    def verify_overlay():
        names=report['recognized'];overlay=control.overlay;u=control.capture.u;hwnd=int(overlay.winId());style=int(control.capture.get_long(hwnd,-20))
        assert style&0x80000 and style&0x08000000 and style&0x20 and style&0x8,hex(style)
        assert int(u.GetForegroundWindow() or 0)==control.target.hwnd,'Overlay stole focus'
        assert overlay.isVisible();assert all(widget.isVisible() for widget in overlay.tier_labels)
        visible_text=' '.join(widget.text() for widget in overlay.findChildren(QtWidgets.QLabel) if widget.isVisible())
        assert '源顺位' not in visible_text and 'winRate' not in visible_text
        fixture_rates=[row.get('winRate') for rows in control.data.get('heroAugmentStats',{}).values() for row in rows]
        assert all(formatted not in visible_text for rate in fixture_rates if isinstance(rate,(int,float)) for formatted in (f'{rate:g}%',f'{rate:.2f}%',f'{rate}%'))
        checks.append('Overlay is layered/topmost/noactivate/transparent and does not steal foreground focus')
        report['overlayStyle']=hex(style);report['foregroundPreserved']=True
        report.update(overlay_qwindow_dpr=float(overlay.windowHandle().devicePixelRatio()),overlay_window_physical=native_rect(hwnd),overlay_compact=overlay._compact)
        assert inside(report['clientRect'],report['overlay_window_physical']),'Actual native overlay escaped fixed physical mock'
        report['overlay_layout_widgets']=inspect_smoke_layout(overlay);report['overlay_layout_passed']=True
        # Actual Win32 point hit test at a point inside the overlay; no game input.
        rect=W.RECT();u.GetWindowRect.argtypes=[W.HWND,ctypes.POINTER(W.RECT)];u.GetWindowRect.restype=W.BOOL;assert u.GetWindowRect(hwnd,ctypes.byref(rect))
        point=W.POINT(rect.left+(rect.right-rect.left)//2,rect.top+20)
        hit=int(u.GetAncestor(u.WindowFromPoint(point),2) or 0)
        assert hit==control.target.hwnd,('Transparent overlay intercepted point',hit,control.target.hwnd)
        control.toggle_clickthrough();style_off=int(control.capture.get_long(int(overlay.winId()),-20));assert not style_off&0x20
        control.toggle_clickthrough();style_on=int(control.capture.get_long(int(overlay.winId()),-20));assert style_on&0x20
        report['click_through_passed']=True;checks.append('Real OS point hit testing reaches the mock through overlay; click-through toggle changes WS_EX_TRANSPARENT')
        assert control.hotkey_registered,'Ctrl+Alt+O registration failed in test session';checks.append('RegisterHotKey succeeded without input hooks')
        # Compose ONLY our two rendered widgets; never save a user desktop screenshot.
        mock_pixels=mock.grab();mock_pixels.setDevicePixelRatio(1);overlay_pixels=overlay.grab();overlay_pixels.setDevicePixelRatio(1)
        canvas=QtGui.QPixmap(1100,780);canvas.fill(QtGui.QColor('#102029'));painter=QtGui.QPainter(canvas);painter.drawPixmap(0,0,mock_pixels);painter.drawPixmap(20,530,overlay_pixels.scaled(1060,230,QtCore.Qt.AspectRatioMode.KeepAspectRatio));painter.end()
        screenshot_path.parent.mkdir(parents=True,exist_ok=True);assert canvas.save(str(screenshot_path),'PNG')
        report['screenshot']=str(screenshot_path);report['screenshot_method']='Qt QWidget.grab of our synthetic mock and overlay only, composited locally; OS capture/OCR separately asserted'
        checks.append('Original synthetic native mock/overlay rendering saved, with no user desktop pixels')
        control.task_result('ocr',{'candidates':[],'_capturedAt':time.monotonic()},control.state.generation);assert not control.state.confirmed and not overlay.isVisible();checks.append('Production OCR result handler hides overlay on scene/candidate loss')
        old_generation=control.state.generation;control.hero_box.setCurrentText('磐石守卫（演示）');assert control.state.generation>old_generation;checks.append('Actual hero selection signal invalidates prior scene state')
        control.state.confirm(names,control.data['augments']);control.last_observation=__import__('time').monotonic();control.last_rect=control.capture.rect(control.target)
        mock.move(mock.x()+7,mock.y()+5);QtWidgets.QApplication.processEvents();control.check_target();assert control.state.confirmed and overlay.isVisible();overlay._verify_rect(control.capture.rect(control.target));checks.append('Real same-size mock translation preserves fresh confirmed identity/offers and repositions overlay inside the new physical client bounds')
        control.last_observation=time.monotonic()-5;control.check_target();assert not control.state.confirmed and not overlay.isVisible();checks.append('Expired observations cannot be revived by translating the target window')
        control.state.confirm(names,control.data['augments']);control.last_observation=time.monotonic()
        before_resize=control.capture.rect(control.target);shrink_smoke_mock(mock,image);after_resize=control.capture.rect(control.target)
        assert after_resize.width<before_resize.width and after_resize.height<before_resize.height,'Actual physical mock size did not shrink'
        assert inside(work_area,native_rect(int(mock.winId()))),'Resized own mock escaped physical work area'
        report['resize_physical_before']={'width':before_resize.width,'height':before_resize.height};report['resize_physical_after']={'width':after_resize.width,'height':after_resize.height}
        control.check_target();assert not control.state.confirmed and not overlay.isVisible();checks.append('Actual physical mock size changed after clearing its own artwork minimum; production watchdog hides old cards pending fresh recognition')
        control.state.confirm(names,control.data['augments']);mock.showMinimized();QtWidgets.QApplication.processEvents();control.check_target();assert not control.state.confirmed and not overlay.isVisible();checks.append('Real mock minimization hides old cards through production watchdog')
        control.close();mock.close();report['window_closed']=not control.isVisible() and not overlay.isVisible() and not mock.isVisible() and not control.hotkey_registered
        assert report['window_closed'];report['status']='passed';checks.append('Control, overlay and mock closed; timer monitoring and registered hotkey released');save();app.exit(0)
    QtCore.QTimer.singleShot(150,lambda:run(prepare))

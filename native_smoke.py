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
from types import SimpleNamespace
from PySide6 import QtCore,QtGui,QtWidgets
from native_state import display_cards


def smoke_dimensions(width,height):
    if any(not isinstance(v,int) or isinstance(v,bool) for v in (width,height)) or width<1000 or height<640:
        raise ValueError('Physical desktop work area cannot fit the fixed960x600 own-HUD mock with20px margins')
    return 960,600

def smoke_pixmap(portrait,cards_path,width,height,dpr,*,changed_roi=False,changed_title=False):
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
    if changed_title:
        # Swap two actual original title pixel blocks; OCR must independently
        # observe the changed order, no fabricated recognition payload.
        first=(round(width*180/960),round(height*235/600),round(width*295/960),round(height*290/600))
        second=(round(width*407/960),first[1],round(width*522/960),first[3])
        a,b=canvas.crop(first),canvas.crop(second);canvas.paste(b,first[:2]);canvas.paste(a,second[:2])
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
        assert pos.x()>=0 and pos.y()>=0 and pos.x()+widget.width()<=overlay.width() and pos.y()+widget.height()<=overlay.height(),('Visible widget escapes overlay',type(widget).__name__,pos.toTuple(),widget.size().toTuple(),overlay.size().toTuple(),overlay._badge_regions)
        if parent:
            assert widget.x()>=0 and widget.y()>=0 and widget.x()+widget.width()<=parent.width() and widget.y()+widget.height()<=parent.height(),'Visible widget escapes parent'
        row={'type':type(widget).__name__,'logical_rect':{'x':pos.x(),'y':pos.y(),'width':widget.width(),'height':widget.height()}}
        if isinstance(widget,QtWidgets.QLabel):
            required=widget.heightForWidth(widget.width());minimum=widget.minimumSizeHint().width()
            assert required<=widget.height()+1,('Label height clipped',widget.text(),required,widget.height())
            assert minimum<=widget.width()+1,('Label width clipped',widget.text(),minimum,widget.width())
            row.update(text=widget.text(),required_height_at_width=required,minimum_width=minimum)
        rows.append(row)
    from badge_contract import WIDTH, MIN_WIDTH, HEIGHT, HINT_FONT_SIZE, TIER_ROW_HEIGHT
    assert overlay.cards and not overlay.panel.isVisibleTo(overlay)
    anchors = overlay._badge_anchors
    assert anchors is not None
    expected = [card for card in overlay.cards if not card.get('pending')
                and anchors.names[card['slot']-1] == card['name']]
    shown = [badge for badge in overlay._badge_widgets if badge.isVisibleTo(overlay)]
    assert len(shown) == len(expected) == len(overlay._badge_regions)
    assert overlay.mask().rectCount() >= len(expected)
    for card in overlay.cards:
        badge = overlay._badge_widgets[card['slot']-1]
        assert badge.isVisibleTo(overlay) is (card in expected)
        if card not in expected: continue
        assert MIN_WIDTH <= badge.width() <= WIDTH and badge.height() == HEIGHT
        assert badge.tier == (card.get('sourceTier') or '暂无评级')
        identity=overlay._identity_provenance
        warning='HUD未复核' if '来自本局选人' in identity and 'HUD未复核' in identity else '本局已确认' if '头像未重新确认' in identity else ''
        source = warning or ('复核中' if overlay._rechecking else '演示评级' if card.get('sourceTierLabel') == '虚构源评级（演示）' else '源评级')
        assert badge.source == source
        hint=str(card.get('sourceHint') or '').strip()
        pending=bool(warning and overlay._rechecking)
        assert badge.hint == hint and badge.toolTip() == (identity+'\n' if warning else '')+('候选复核中\n' if pending else '')+hint
        assert badge.accessibleName() == f"选项 {card['slot']} · {card['name']} · {badge.tier} · {source}" + (' · '+identity if warning else '')+(' · 候选复核中' if pending else '')+(' · '+hint if hint else '')
        font,hint_rect=badge.hint_text_layout();metrics=QtGui.QFontMetrics(font)
        assert font.pixelSize()==HINT_FONT_SIZE and font.weight()==QtGui.QFont.Weight.Normal
        assert badge.display_hint == metrics.elidedText(('复核中 · ' if pending else '')+hint,QtCore.Qt.TextElideMode.ElideRight,hint_rect.width())
        assert metrics.horizontalAdvance(badge.display_hint) <= hint_rect.width()
        assert metrics.height() <= hint_rect.height() and badge.rect().contains(hint_rect)
        source_font,source_rect,tier_font,tier_rect,tier_lines=badge.top_text_layout()
        assert source_font.pixelSize()>=9 and badge.display_source in (source,{'HUD未复核':'HUD待核','本局已确认':'本局已核'}.get(source,source))
        assert badge.rect().contains(source_rect) and badge.rect().contains(tier_rect)
        assert tier_rect.right()+4<=source_rect.left()
        assert hint_rect.top()>=TIER_ROW_HEIGHT/2+max(QtGui.QFontMetrics(source_font).height(),QtGui.QFontMetrics(tier_font).height())/2
        assert not badge.findChildren(QtWidgets.QLabel), 'Names must stay in accessibility, not badge pixels'
    for i, (x,y,w,h) in enumerate(overlay._badge_regions):
        for xx,yy,ww,hh in overlay._badge_regions[i+1:]:
            assert x+w <= xx or xx+ww <= x or y+h <= yy or yy+hh <= y, 'Badge regions overlap'

    return rows


class OverlayDutyTrace:
    """Diagnostic sampled HWND duty cycle; never a production speed claim.

    Native visibility is sampled at capture boundaries, phase dispatch and Qt
    timer ticks. Durations use the preceding sample, so the maximum sample gap
    is reported alongside them. The old hide-until-final policy is an explicit
    same-run counterfactual, not a measurement of another executable.
    Inference ends when the final result enters the GUI handler; total elapsed
    and visibility still include that handler's application and final display.
    Diagnostic elapsed measurements share this high-resolution clock; product
    freshness timestamps and the existing timeout deadlines keep their clocks.
    """
    def __init__(self,name,*,clock=time.perf_counter):
        self.name=name;self.clock=clock;self.started=clock();self.events={}
        info=time.get_clock_info('perf_counter') if clock is time.perf_counter else None
        self.measurement_clock={'name':'perf_counter' if info else 'injected',
            'implementation':info.implementation if info else 'caller-supplied diagnostic clock',
            'monotonic':info.monotonic if info else None,'adjustable':info.adjustable if info else None,
            'resolution_seconds':info.resolution if info else None}
        self.initial_native_visible=None;self.initial_qt_visible=None
        self.samples=[];self.phases=[];self.helpers=[];self.holds={};self.hold_started={};self.hold_elapsed={}
        self.held_state_samples=0;self.qt_show_events_during_capture=0;self.capture_active=False;self.capture_count=0;self.capture_concurrency=0;self.max_capture_concurrency=0;self.finished=False;self.stopped=False;self.error=None
        self.lock=threading.Lock()
    def elapsed_ms(self):return (self.clock()-self.started)*1000
    def mark(self,name):
        with self.lock:self.events[name]=self.elapsed_ms()
    def sample(self,visible,*,capturing=False):
        with self.lock:self.samples.append((self.elapsed_ms(),bool(visible),bool(capturing)))
    def summary(self):
        total=self.events['final'];received=self.events.get('result_received',total)
        # Preserve actual acquisition order at equal timestamps. Sorting full
        # tuples orders False before True and can invent visibility changes;
        # clipping before sorting can also reverse distinct final samples.
        points=[(min(stamp,total),shown,capturing) for stamp,shown,capturing in sorted(self.samples,key=lambda point:point[0])];hidden=visible=inference_visible=gap=0.;capture_samples=capture_visible=0
        for index,(stamp,shown,capturing) in enumerate(points):
            if capturing:capture_samples+=1;capture_visible+=int(shown)
            if index+1<len(points):
                elapsed=points[index+1][0]-stamp;gap=max(gap,elapsed)
                if shown:
                    visible+=elapsed
                    inference_visible+=max(0.,min(points[index+1][0],received)-max(stamp,self.events.get('capture_return',float('inf'))))
                else:hidden+=elapsed
        return {'name':self.name,'status':'passed','timings_ms':{key:round(value,3) for key,value in self.events.items()},
                'measurement_clock':dict(self.measurement_clock),'initial_native_visible':self.initial_native_visible,'initial_qt_visible':self.initial_qt_visible,
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


class _DutyResultDispatch(QtCore.QObject):
    """Keep diagnostic result boundaries around the unchanged GUI handler.

    Separate queued observers can run after an intervening visibility timer.
    This GUI-affine receiver forwards every result exactly once. A disconnected
    receiver can still have queued calls, so restoration leaves it alive under
    the control and forwards those calls without running retired diagnostics.
    """
    def __init__(self,control,before,after,failed):
        super().__init__(control)
        self.signal=control.signals.result;self.handler=control.task_result
        self.before=before;self.after=after;self.failed=failed;self.installed=True
        self.signal.disconnect(self.handler);self.signal.connect(self.apply)
    @QtCore.Slot(str,object,int)
    def apply(self,kind,value,generation):
        if not self.installed:
            self.handler(kind,value,generation);return
        self.before(kind,value,generation)
        try:self.handler(kind,value,generation)
        except BaseException as exc:
            if self.installed:self.failed(kind,exc,generation)
            raise
        else:
            if self.installed:self.after(kind,value,generation)
    def restore(self):
        if not self.installed:return
        self.installed=False
        self.signal.disconnect(self.apply);self.signal.connect(self.handler)
        self.before=self.after=self.failed=None


from contextlib import contextmanager


@contextmanager
def owned_badge_hit_test_probe(overlay, point, *, app=None, user=None):
    """Temporarily answer one owned HWND's hit tests inside Qt diagnostics only.

    Normal badge nativeEvent returns HTTRANSPARENT independently of EXSTYLE.
    No other HWND/message is intercepted; no product state or cards are changed.
    """
    app=app or QtWidgets.QApplication.instance()
    if user is None:
        assert os.name=='nt' and app.platformName()=='windows'
        user=ctypes.WinDLL('user32',use_last_error=True)
        user.SendMessageW.argtypes=[W.HWND,W.UINT,W.WPARAM,W.LPARAM];user.SendMessageW.restype=ctypes.c_ssize_t
        user.GetWindowThreadProcessId.argtypes=[W.HWND,ctypes.POINTER(W.DWORD)];user.GetWindowThreadProcessId.restype=W.DWORD
    hwnd=int(overlay.winId())
    def query():
        assert int(overlay.winId())==hwnd,'Diagnostic changed owned HWND'
        pid=W.DWORD();assert user.GetWindowThreadProcessId(hwnd,ctypes.byref(pid)) and pid.value==os.getpid(),'Diagnostic HWND is not owned'
        return int(user.SendMessageW(hwnd,0x0084,0,(point.x&0xffff)|((point.y&0xffff)<<16)))
    class Probe(QtCore.QAbstractNativeEventFilter):
        def nativeEventFilter(self,event_type,message):
            msg=W.MSG.from_address(int(message))
            if int(msg.hWnd or 0)==hwnd and msg.message==0x0084:return True,1
            return False,0
    assert query()==-1,'Normal badge handler must be HTTRANSPARENT'
    probe=Probe();app.installNativeEventFilter(probe)
    try:
        assert query()==1,'Owned diagnostic hit-test override was not applied'
        yield
    finally:
        app.removeNativeEventFilter(probe)
        assert query()==-1,'Normal badge hit-test handler was not restored'


def prove_badge_native_hits(capture, overlay, target_hwnd, rect):
    """Owned diagnostic only: prove holes independently of whole-HWND passthrough."""
    hwnd=int(overlay.winId());regions=tuple(overlay._badge_regions)
    assert len(regions)==3
    centers=gaps=0
    try:
        capture.configure_overlay(hwnd,False,opaque=True)
        assert int(overlay.winId())==hwnd,'Diagnostic changed the owned overlay HWND'
        assert not int(capture.get_long(hwnd,-20))&0x20,'Native transparency remains enabled'
        def hit(x,y):
            return int(capture.u.GetAncestor(capture.u.WindowFromPoint(W.POINT(x,y)),2) or 0)
        x,y,width,height=regions[0]
        with owned_badge_hit_test_probe(overlay,W.POINT(rect.left+x+width//2,rect.top+y+height//2)):
            for x,y,width,height in regions:
                actual=hit(rect.left+x+width//2,rect.top+y+height//2)
                assert actual==hwnd,('Opaque badge center did not hit overlay',actual,hwnd)
                centers+=1
            for first,second in zip(regions,regions[1:]):
                actual=hit(rect.left+(first[0]+first[2]+second[0])//2,rect.top+first[1]+first[3]//2)
                assert actual==target_hwnd,('Native badge gap did not hit target',actual,target_hwnd)
                gaps+=1
    finally:
        overlay.configure()
        assert int(overlay.winId())==hwnd and int(capture.get_long(hwnd,-20))&0x20,'Normal badge transparency was not restored'
    return dict(opaque_center_hits=centers,target_gap_hits=gaps,normal_transparency_restored=True)


def _duty_session_observation(capture, receipt, *, hidden):
    """Independent live OS checks of the exact returned session receipt.

    The registration token stays local. It is never serialized in diagnostics.
    A receipt cannot establish its own helper identity or current HWND state.
    """
    from session_windows import process_metadata
    from wgc_session_capture import _window_api, _property_name
    owner=capture._persistent._owner;session=owner.session;transport=session._transport
    process=transport.process;registered=session._overlay
    assert not owner.revoked.is_set() and not transport.revoked.is_set()
    assert process is not None and process.poll() is None
    created=process_metadata(process.pid).created
    assert (process.pid,created,transport.generation)==tuple(receipt[key] for key in ('helper_pid','helper_created','session_generation'))
    assert process.poll() is None and session._transport is transport
    hwnd=receipt['overlay_hwnd'];affinity=W.DWORD()
    assert registered[:2]==(hwnd,receipt['overlay_extended_style'])
    valid=_window_api().GetPropW(hwnd,_property_name(registered[2]))==registered[2]
    actual_style=int(capture.get_long(hwnd,-20))&0xffffffff
    assert capture.u.GetWindowDisplayAffinity(hwnd,ctypes.byref(affinity))
    opaque=bool(capture._opaque_layered(hwnd));visible=bool(capture.u.IsWindowVisible(hwnd))
    assert valid and opaque and affinity.value==0x11 and actual_style==receipt['overlay_extended_style']
    if hidden:assert not visible,'Native overlay visible before full pixel acquisition return'
    assert not owner.revoked.is_set() and not transport.revoked.is_set() and process.poll() is None
    return owner,transport,dict(helper_pid=process.pid,helper_created=created,session_generation=transport.generation,
        helper_alive=True,overlay_hwnd=hwnd,overlay_extended_style=actual_style,overlay_affinity=int(affinity.value),
        overlay_registration_valid=bool(valid),overlay_opaque=opaque,native_visible=visible)


def _duty_one_shot_process_closed(process):
    """v1 closes then clears stdin; stdout/stderr remain owned closed streams."""
    return bool(process.poll() is not None
        and (process.stdin is None or process.stdin.closed)
        and all(getattr(process,name) is not None and getattr(process,name).closed for name in ('stdout','stderr')))


def _duty_process_created(process):
    """Read creation time through the retained exact process handle, even after exit."""
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.GetProcessTimes.argtypes=[W.HANDLE,*([ctypes.POINTER(W.FILETIME)]*4)]
    kernel.GetProcessTimes.restype=W.BOOL
    created,exited,kernel_time,user_time=(W.FILETIME() for _ in range(4))
    assert kernel.GetProcessTimes(int(process._handle),ctypes.byref(created),ctypes.byref(exited),
        ctypes.byref(kernel_time),ctypes.byref(user_time)),'Exact owned helper handle identity unavailable'
    return (int(created.dwHighDateTime)<<32)|int(created.dwLowDateTime)


def _duty_session_cleanup(capture, owner, transport, receipt, *, observed_ms):
    """Observe eventual cleanup independently of the nonblocking Stop return."""
    process=transport.process
    code=process.poll() if process is not None else None
    streams=[getattr(process,name,None) for name in ('stdin','stdout','stderr')]
    result=dict(helper_pid=receipt['helper_pid'],helper_created=receipt['helper_created'],
        session_generation=receipt['session_generation'],observed_ms=round(observed_ms,3),
        owner_revoked=owner.revoked.is_set(),transport_revoked=transport.revoked.is_set(),
        owner_close_done=owner.close_done.is_set(),capture_call_done=owner.call_done.is_set(),
        process_exit_code=code,process_exited=type(code) is int,
        pipes_closed=bool(all(stream is not None and stream.closed for stream in streams)),
        pipe_worker_done=transport.io_done.is_set(),stderr_worker_done=transport.stderr_done.is_set(),
        job_closed=bool(transport.job is not None and transport.job_closed and transport.job.handle is None),
        ready_for_replacement=transport.ready_for_replacement.is_set(),
        adapter_cleanup_complete=not capture.cleanup_pending)
    fields=('owner_revoked','transport_revoked','owner_close_done','capture_call_done','process_exited',
        'pipes_closed','pipe_worker_done','stderr_worker_done','job_closed','ready_for_replacement','adapter_cleanup_complete')
    if not all(result[key] is True for key in fields):return None
    created=_duty_process_created(process)
    assert (process.pid,created,transport.generation)==tuple(receipt[key] for key in ('helper_pid','helper_created','session_generation')), 'Stop cleanup belongs to a different helper'
    from wgc_session_capture import decode_session_shutdown_diagnostic
    result.update(helper_pid=process.pid,helper_created=created,session_generation=transport.generation,
        termination_requested_while_alive=transport.termination_requested_while_alive,
        shutdown_diagnostic=decode_session_shutdown_diagnostic(transport.diagnostic,code))
    return result


def start_overlay_duty_probe(control,*,app,u,paint_mock,report,checks,save,run,done):
    """Measure the full product pipeline twice against one exact owned scene."""
    from screen_capture import Win32Capture
    from session_windows import process_metadata
    original=control.capture;overlay=control.overlay;baseline=[None]
    assert type(original) is Win32Capture,'Duty persistent pass requires the actual default product adapter'
    assert original._persistent._enabled is True
    report['overlay_duty_cycle']={'schema_version':3,
        'scope':'Original synthetic native Windows HWND + real capture/PortraitMatcher/OCR; controlled diagnostic holds, not live-game or user-machine latency',
        'artificial_hold_target_ms':350,'active_mode':'initial-cleanup','mode':'persistent','adapter_constructor':'Win32Capture()',
        'baseline':{'mode':'one-shot','adapter_constructor':'Win32Capture(persistent_sessions=False)','cases':[]},'cases':[]}
    duty=report['overlay_duty_cycle'];control.monitor.stop();overlay.hide()
    def restore():
        if baseline[0] is not None:baseline[0].close()
        control.capture=original;overlay.capture=original
        original.retire_session();control._smoke_duty_outer_cleanup=None
    control._smoke_duty_outer_cleanup=restore
    def wait_cleanup(capture,next_step):
        deadline=time.monotonic()+8
        def poll():
            assert time.monotonic()<deadline,'Duty adapter cleanup exceeded the existing 8-second observation bound'
            helper=getattr(capture,'_wgc',None)
            if capture.cleanup_pending or getattr(helper,'_pending_cleanup',None) or getattr(helper,'_pending_job',None):
                QtCore.QTimer.singleShot(10,lambda:run(poll));return
            next_step()
        poll()
    def bind(capture):
        control.capture=capture;overlay.capture=capture;overlay.hide();overlay.configure()
        translucent=overlay.testAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground)
        opaque_paint=overlay.testAttribute(QtCore.Qt.WidgetAttribute.WA_OpaquePaintEvent)
        format=overlay.windowHandle().format();opacity=overlay.windowOpacity()
        badge_pixels=[]
        assert len(overlay._badge_regions)==3
        for badge in overlay._badge_widgets:
            image=badge.grab().toImage()
            badge_pixels.append([list(image.pixelColor(x,y).getRgb()) for x,y in ((0,0),(image.width()-1,0),(0,image.height()-1),(image.width()-1,image.height()-1))])
        assert not translucent and opaque_paint and opacity==1 and not format.hasAlpha() and format.alphaBufferSize() in (-1,0)
        assert badge_pixels==[[[11,20,30,255]]*4]*3,'Actual badge region contains unpainted/translucent edge pixels'
        rect=capture.rect(control.target);hwnd=int(overlay.winId());affinity=W.DWORD()
        assert capture.u.GetWindowDisplayAffinity(hwnd,ctypes.byref(affinity)) and affinity.value==0x11
        assert capture._opaque_layered(hwnd)
        scene=dict(window_identity=list(control.target.identity),target_created=process_metadata(control.target.pid).created,
            capture_rect={key:getattr(rect,key) for key in ('x','y','width','height')},overlay_hwnd=hwnd,
            overlay_extended_style=int(capture.get_long(hwnd,-20))&0xffffffff,overlay_affinity=int(affinity.value),overlay_opaque=True,
            qt_translucent_background=bool(translucent),qt_opaque_paint_event=bool(opaque_paint),qt_window_opacity=opacity,
            surface_has_alpha=bool(format.hasAlpha()),surface_alpha_buffer_size=format.alphaBufferSize(),badge_corner_rgba=badge_pixels,
            fixture_sha256=hashlib.sha256((Path(__file__).resolve().parent/'fixtures/auto-scene.png').read_bytes()).hexdigest())
        if 'scene_binding' not in duty:duty['scene_binding']=scene
        assert scene==duty['scene_binding'],'Mode swap changed the actual owned scene or opaque overlay'
        control.manual_metadata=process_metadata(control.target.pid);control.manual_identity=control.target.identity
        control.state.start(control.target.identity);control.state.clear_hero();control._accepted_frame=None;control.ocr_reuse.clear()
        paint_mock();app.processEvents()
    def start_baseline():
        duty['active_mode']='one-shot'
        baseline[0]=Win32Capture(persistent_sessions=False);bind(baseline[0])
        _start_overlay_duty_mode(control,app=app,u=u,paint_mock=paint_mock,mode_report=duty['baseline'],
            save=save,run=run,done=baseline_done)
    def baseline_done():
        duty['active_mode']='baseline-cleanup';baseline[0].close()
        def swapped():
            proof=duty['baseline']['cleanup'];assert proof['complete'] is True
            duty['baseline']['cleanup_before_persistent']=dict(proof)
            duty['active_mode']='persistent';bind(original)
            _start_overlay_duty_mode(control,app=app,u=u,paint_mock=paint_mock,mode_report=duty,
                save=save,run=run,done=finish)
        wait_cleanup(baseline[0],swapped)
    def finish():
        report['overlay_duty_cycle_passed']=True;duty.pop('active_mode',None);control._smoke_duty_outer_cleanup=None
        checks.append('Measured separate strict one-shot baseline and default persistent product passes on the exact same opaque own scene; both full five-case capture/PortraitMatcher/OCR proofs, with guarded-idle reuse and independently observed Stop cleanup in persistent mode')
        save();QtCore.QTimer.singleShot(100,lambda:run(done))
    original.retire_session();wait_cleanup(original,start_baseline)


def visible_badge_slots(overlay, native_visible, *, qt_visible=None):
    """Actual visible slots, not Qt child visibility relative to a hidden parent."""
    if qt_visible is None:qt_visible=overlay.isVisible()
    if qt_visible is not True or native_visible is not True:return []
    return [i+1 for i,badge in enumerate(overlay._badge_widgets) if badge.isVisibleTo(overlay)]


def _schedule_duty_mode_wait(control, active, single_shot, run, delay):
    """Honor production readiness scheduling, but never start a second capture."""
    trace=active[0]
    def eligible():
        return (not getattr(control,'closed',False) and trace is not None and active[0] is trace and not trace.finished
                and trace.error is None and trace.capture_count==0
                and getattr(control,'_mode_wait_started',None) is not None
                and not control.capture_pending and not control.ocr_busy)
    if not eligible():return
    def resume():
        if eligible():control.capture_tick()
    single_shot(delay if delay is not None else 50,lambda:run(resume))


def _start_overlay_duty_mode(control,*,app,u,paint_mock,mode_report,save,run,done):
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
    original_schedule=control.schedule_capture;active=[None];rows=mode_report['cases'];main_thread=threading.get_ident()
    mode=mode_report['mode'];assert mode in ('one-shot','persistent')
    all_helpers=[];all_jobs=[];reuse_captures=[]
    original_job=wgc_capture._CaptureJob
    control.monitor.stop();control.schedule_capture=lambda delay=None:_schedule_duty_mode_wait(control,active,QtCore.QTimer.singleShot,run,delay)
    control.hero_auto.setChecked(True);control.state.clear_hero();control.ocr_reuse.clear()
    control._accepted_frame=None;control.overlay.hide()
    mode_report['fresh_state']={'confirmed':control.state.confirmed,'automatic_frames':control.state.automatic_frames,
        'hero_stable_frames':control.state.hero_stable_frames,'stable_frames':control.state.stable_frames,
        'accepted_frame_present':control._accepted_frame is not None,'ocr_cache_cleared':control.ocr_reuse._entry is None}
    def snapshot():
        return {'last_observation':control.last_observation,'automatic_frames':control.state.automatic_frames,
                'hero_stable_frames':control.state.hero_stable_frames,'stable_frames':control.state.stable_frames,
                'generation':control.state.generation,'accepted_observed_at':control._accepted_frame['observed_at'] if control._accepted_frame else None}
    def native_visible():return bool(u.IsWindowVisible(hwnd))
    def helper_cleanup(trace):
        helper=getattr(capture_adapter,'_wgc',None)
        return all(_duty_one_shot_process_closed(process) for process in trace.helpers) and not getattr(helper,'_pending_cleanup',None) and not getattr(helper,'_pending_job',None)
    def acquisition_complete(trace):
        if mode=='one-shot':return helper_cleanup(trace)
        receipt=trace.session_capture['receipt']
        _duty_session_observation(capture_adapter,receipt,hidden=False)
        return dict(capture_adapter.last_session_receipt or {})==receipt
    def watched_job(*args,**kwargs):
        job=original_job(*args,**kwargs);all_jobs.append(job);return job
    class VisibilityGuard(QtCore.QObject):
        def eventFilter(self,watched,event):
            trace=active[0]
            if trace is not None and trace.capture_active and event.type()==QtCore.QEvent.Type.Show:
                trace.qt_show_events_during_capture+=1;trace.error=AssertionError('Own overlay Show event during native pixel acquisition')
            return False
    visibility_guard=VisibilityGuard(overlay);overlay.installEventFilter(visibility_guard)
    def watched_popen(args,*arguments,**keywords):
        process=original_popen(args,*arguments,**keywords);trace=active[0]
        helper=getattr(capture_adapter,'_wgc',None)
        if trace is not None and helper is not None and args and str(args[0])==str(helper.helper_path):
            trace.helpers.append(process);all_helpers.append(process)
        return process
    def watched_compositor(*arguments,**keywords):
        value=original_compositor(*arguments,**keywords);trace=active[0]
        if trace is not None and threading.get_ident()==main_thread:trace.mark('gui_compositor_validated')
        return value
    def watched_capture(*arguments,**keywords):
        trace=active[0]
        if trace is None:return original_capture(*arguments,**keywords)
        trace.capture_active=True;trace.capture_count+=1;trace.capture_concurrency+=1;trace.max_capture_concurrency=max(trace.max_capture_concurrency,trace.capture_concurrency)
        mode_report['active_case']['phase_state']='pixel-acquisition'
        trace.mark('capture_start');trace.sample(native_visible(),capturing=True)
        if mode=='persistent':
            from wgc_session_capture import _qpc_100ns
            capture_start_qpc=_qpc_100ns()
        assert not native_visible(),'Own native overlay visible at pixel acquisition entry'
        try:
            value=original_capture(*arguments,**keywords)
            assert not native_visible(),'Own native overlay visible before capture/helper return'
            trace.sample(native_visible(),capturing=True);trace.mark('capture_return')
            mode_report['active_case']['phase_state']='capture-return'
            if mode=='persistent':
                receipt=dict(capture_adapter.last_session_receipt or {})
                assert receipt,'Full capture return lacks its guarded-idle receipt'
                capture_return_qpc=_qpc_100ns()
                owner,transport,observation=_duty_session_observation(capture_adapter,receipt,hidden=True)
                trace.owner=owner;trace.transport=transport
                trace.session_capture=dict(receipt=receipt,capture_start_100ns=capture_start_qpc,
                    capture_return_100ns=capture_return_qpc,copied_after_capture_return=True,observation=observation)
                mode_report['active_case']['session_capture']=trace.session_capture
                if len(reuse_captures)<2:reuse_captures.append(trace.session_capture)
            else:assert helper_cleanup(trace),'One-shot helper has not fully exited/cleaned up'
            trace.backend=capture_adapter.last_backend;return value
        finally:trace.capture_active=False;trace.capture_concurrency-=1
    def watched_recognize(*arguments,before_match=None,before_ocr=None,**keywords):
        trace=active[0]
        assert type(arguments[4]) is PortraitMatcher,'Duty probe must exercise the concrete production matcher'
        def phase(name,callback,*values):
            assert trace is not None and 'capture_return' in trace.events and acquisition_complete(trace),'Phase preceded completed guarded capture return'
            trace.mark(name+'_emitted');mode_report['active_case']['phase_state']=name+'-emitted'
            if trace.name in ('unchanged','changed_roi','changed_title','changed_hud','unknown_hud','stop_late'):
                trace.holds[name]=threading.Event();trace.hold_started[name]=trace.clock()
            callback(*values)
            if name in trace.holds:
                assert trace.holds[name].wait(4),'GUI did not release diagnostic phase hold'
                trace.hold_elapsed[name]=(trace.clock()-trace.hold_started[name])*1000
        return original_recognize(*arguments,before_match=lambda *values:phase('before_match',before_match,*values),
            before_ocr=lambda *values:phase('before_ocr',before_ocr,*values),**keywords)
    def received(kind,value,generation):
        trace=active[0]
        if trace is not None and kind=='ocr':
            trace.mark('result_received');mode_report['active_case']['phase_state']='result-received'
    def observed(kind,value,generation):
        trace=active[0]
        if trace is None or kind not in ('capture-proof','title-proof','ocr'):return
        try:
            if kind=='title-proof':
                if trace.stopped:
                    assert not control.state.running and not control.state.confirmed and control._accepted_frame is None and not native_visible(), 'Late semantic proof revived stopped display'
                    return
                # The new independent semantic result can revoke counters while
                # an artificial HUD hold is active. It may never advance them.
                current=snapshot()
                revoked=dict(trace.before,automatic_frames=0,stable_frames=0,accepted_observed_at=None)
                assert current==trace.before or (trace.name in ('changed_title','changed_hud','unknown_hud') and current==revoked), 'Early title proof promoted state or renewed age'
                if trace.name=='changed_title':
                    assert current==revoked,'Changed ordered titles failed early semantic revocation'
                    trace.title_negative_applied=True
                return
            if kind=='capture-proof':
                name='before_ocr' if 'hero_observation' in value else 'before_match';trace.mark(name+'_applied');mode_report['active_case']['phase_state']=name+'-applied'
                current_rect=capture_adapter.rect(control.target);accepted=trace.accepted or {}
                def rectangle(rect):return {key:getattr(rect,key) for key in ('x','y','width','height')}
                scope=value['_frameScope']
                current=(tuple(value['_windowIdentity'])==control.target.identity and capture_adapter.rect(control.target)==value['_captureRect']
                    and capture_adapter.foreground(control.target) and control.target_allowed())
                phase={'name':name,'emitted_ms':round(trace.events[name+'_emitted'],3),'applied_ms':round(trace.events[name+'_applied'],3),
                    'compositor_validated_ms':round(trace.events.get('gui_compositor_validated',-1),3),'restored':bool(control._restore_while_ocr),'qt_visible':overlay.isVisible(),'native_visible':native_visible(),
                    'state_unchanged':snapshot()==trace.before,'state_before':trace.before,'state_at_phase':snapshot(),
                    'semantic_rejected_before_phase':bool(getattr(trace,'title_negative_applied',False)),
                    'current_identity_geometry_focus':bool(current),
                    ('helper_cleanup_complete' if mode=='one-shot' else 'session_guarded_idle_verified'):bool(acquisition_complete(trace)),
                    'window_identity':list(value['_windowIdentity']),'current_window_identity':list(control.target.identity),
                    'capture_rect':rectangle(value['_captureRect']),'current_rect':rectangle(current_rect),
                    'candidate_roi_sha256':value.get('_roiDigest'),'accepted_candidate_roi_sha256':accepted.get('digest'),
                    'hud_input_sha256':value.get('_hudInputDigest'),'accepted_hud_input_sha256':accepted.get('hud_digest'),
                    'card_geometry_unchanged':bool(accepted.get('card_geometry') is not None and value.get('_matchingCardGeometry') is accepted.get('card_geometry')),
                    'title_regions_unchanged':bool(accepted.get('title_proof') is not None and value.get('_matchingTitleProof') is accepted.get('title_proof')),
                    'scope_matches_accepted':scope==accepted.get('scope'),'roi':list(scope[3]),
                    'vocabulary_sha256':hashlib.sha256(json.dumps(scope[4],ensure_ascii=False).encode()).hexdigest(),
                    'source_metadata_sha256':hashlib.sha256(scope[5][1].encode()).hexdigest(),
                    'matcher_type':type(control.hero_matcher).__name__,'matcher_instance_matches_accepted':bool(accepted and scope[6][0] is accepted['scope'][6][0] is control.hero_matcher),
                    'matcher_configuration':[control.hero_matcher.minimum_score,control.hero_matcher.minimum_margin],
                    'capture_serial':value['_captureSerial'],'captured_at':value['_capturedAt'],
                    'compositor_checked_after_capture':trace.events.get('gui_compositor_validated',-1)>=trace.events['capture_return']}
                trace.phases.append(phase)
                assert acquisition_complete(trace) and current,'Native capture proof is no longer current'
                if trace.name in ('unchanged','changed_roi','stop_late'):
                    assert all(phase[key] for key in ('restored','qt_visible','native_visible','state_unchanged','compositor_checked_after_capture')),'Unchanged accepted capture was not safely restored before slow inference'
                elif trace.name in ('changed_title','changed_hud','unknown_hud'):
                    assert not any(phase[key] for key in ('restored','qt_visible','native_visible')),'Changed/unknown own HUD restored old cards'
                    expected_state=dict(trace.before,automatic_frames=0,stable_frames=0,accepted_observed_at=None) if (trace.name in ('changed_hud','unknown_hud') and name=='before_ocr') or phase['semantic_rejected_before_phase'] else trace.before
                    assert phase['state_at_phase']==expected_state,'Intermediate proof may only revoke unsafe evidence, never refresh TTL or promote counters'
            else:
                trace.mark('final');trace.sample(native_visible());trace.finished=True;mode_report['active_case']['phase_state']='final'
                trace.final_generation=generation;trace.final_value=value
        except Exception as exc:trace.error=AssertionError(trace.name+': '+str(exc));trace.finished=True
    def observed_error(kind,error,generation):
        trace=active[0]
        if trace is not None and kind=='ocr':trace.error=AssertionError('Production duty capture '+trace.name+' failed: '+error);trace.finished=True
    def handler_failed(kind,error,generation):
        trace=active[0]
        if trace is not None:
            trace.error=AssertionError('Production duty result handler '+kind+' failed: '+str(error));trace.finished=True
            mode_report['active_case']['phase_state']='handler-failed'
    capture_adapter.capture=watched_capture;capture_adapter.validate_compositor=watched_compositor
    hero_recognition.recognize_frame=watched_recognize;wgc_capture.subprocess.Popen=watched_popen
    if mode=='one-shot':wgc_capture._CaptureJob=watched_job
    result_dispatch=_DutyResultDispatch(control,received,observed,handler_failed)
    control.signals.error.connect(observed_error)
    def cleanup():
        trace=active[0]
        if trace:
            for release in trace.holds.values():release.set()
        overlay.removeEventFilter(visibility_guard);visibility_guard.deleteLater()
        capture_adapter.capture=original_capture;capture_adapter.validate_compositor=original_compositor
        hero_recognition.recognize_frame=original_recognize;wgc_capture.subprocess.Popen=original_popen;wgc_capture._CaptureJob=original_job
        result_dispatch.restore();control.signals.error.disconnect(observed_error)
        control.schedule_capture=original_schedule;control.monitor.stop();active[0]=None;control._smoke_duty_cleanup=None
    # Failures release only our diagnostic holds before ordinary shutdown.
    control._smoke_duty_cleanup=cleanup
    def begin(name,done):
        assert not control.ocr_busy and not control.capture_pending
        trace=OverlayDutyTrace(name);trace.before=snapshot();trace.accepted=control._accepted_frame;active[0]=trace
        trace.initial_native_visible=native_visible();trace.initial_qt_visible=overlay.isVisible()
        mode_report['active_case']={'mode':mode,'name':name,'phase_state':'waiting-for-capture','timings_ms':trace.events,'phases':trace.phases,
            'measurement_clock':dict(trace.measurement_clock),'initial_native_visible':trace.initial_native_visible,'initial_qt_visible':trace.initial_qt_visible}
        trace.sample(trace.initial_native_visible)
        if name in ('unchanged','changed_roi','changed_title','changed_hud','unknown_hud','stop_late'):
            assert trace.initial_native_visible and trace.initial_qt_visible,'Measured duty case must begin with the accepted overlay genuinely visible'
        control.capture_tick();trace.sample(native_visible())
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
                        held_phase=next(phase for phase in trace.phases if phase['name']==name)
                        expected=held_phase['state_at_phase']
                        if getattr(trace,'title_negative_applied',False):
                            expected=dict(trace.before,automatic_frames=0,stable_frames=0,accepted_observed_at=None)
                        assert snapshot()==expected,'TTL/counters changed without an applied semantic revocation'
                        trace.held_state_samples+=1
                        if trace.clock()-trace.hold_started[name]<.35:continue
                        if trace.name=='stop_late' and name=='before_ocr':
                            trace.mark('stop');started=trace.clock();control.stop_monitor();trace.stop_ms=(trace.clock()-started)*1000;trace.stopped=True
                            assert not native_visible() and not overlay.isVisible() and not control.state.running and not control.state.confirmed
                            trace.sample(native_visible())
                        release.set()
                    QtCore.QTimer.singleShot(10,lambda:run(poll));return
                assert not control.ocr_busy and not control.capture_pending,(trace.name,control.ocr_busy,control.capture_pending,trace.events)
                if trace.stopped and mode=='persistent':
                    mode_report['active_case']['phase_state']='stop-cleanup'
                    trace.stop_cleanup=_duty_session_cleanup(capture_adapter,trace.owner,trace.transport,trace.session_capture['receipt'],
                        observed_ms=trace.elapsed_ms())
                    if trace.stop_cleanup is None:
                        QtCore.QTimer.singleShot(10,lambda:run(poll));return
                    mode_report['active_case']['stop_cleanup']=trace.stop_cleanup
                    code=trace.stop_cleanup['process_exit_code']
                    assert code&0xffffffff!=0xc0000005,'Stop observed native access-violation crash'
                    assert code==0 or trace.stop_cleanup['termination_requested_while_alive'] is True,'Nonzero Stop exit lacks observed parent termination'
                if trace.name in ('unchanged','changed_roi','changed_title','changed_hud','unknown_hud','stop_late'):
                    final_qt_visible=overlay.isVisible();final_native_visible=native_visible()
                    value=trace.summary();value.update(mode=mode,capture_backend=trace.backend,
                        title_semantic_rejection_observed=bool(getattr(trace,'title_negative_applied',False)),
                        capture_duration_ms=round(trace.events['capture_return']-trace.events['capture_start'],3),
                        final_visible_slots=visible_badge_slots(overlay,final_native_visible,qt_visible=final_qt_visible),
                        final_confirmed=control.state.confirmed,final_running=control.state.running,final_qt_visible=final_qt_visible,final_native_visible=final_native_visible,
                        final_state_generation=control.state.generation,final_result_generation=trace.final_generation,final_captured_at=trace.final_value['_capturedAt'],
                        final_last_observation=control.last_observation,final_candidate_names=[item['name'] for item in trace.final_value.get('automatic_candidates',[])],final_hero_observation={key:trace.final_value['hero_observation'].get(key) for key in ('hero','confident')})
                    if mode=='one-shot':value.update(helper_count=len(trace.helpers),helper_exit_codes=[process.poll() for process in trace.helpers],
                        helper_cleanup_complete_before_phase=all(phase['helper_cleanup_complete'] for phase in trace.phases))
                    else:value.update(helper_count=1,session_capture=trace.session_capture)
                    # Preserve every computed operand even if an unchanged
                    # acceptance predicate below fails; only accepted rows pass.
                    mode_report['active_case'].update(value,status='pending-validation')
                    assert value['capture_samples']>=2 and value['capture_visible_samples']==0 and value['qt_show_events_during_capture']==0
                    assert [phase['name'] for phase in value['phases']]==['before_match','before_ocr']
                    for phase in value['phases']:
                        expected_state=dict(trace.before,automatic_frames=0,stable_frames=0,accepted_observed_at=None) if (trace.name in ('changed_hud','unknown_hud') and phase['name']=='before_ocr') or phase['semantic_rejected_before_phase'] else trace.before
                        assert phase['state_at_phase']==expected_state and phase['state_unchanged']==(expected_state==trace.before)
                    if trace.name=='unchanged':
                        assert control.state.confirmed and control.state.confirmation_mode=='automatic' and value['sampled_inference_visible_ms']>=500
                        assert trace.final_value['hero_observation']['hero']=='星火术士（演示）'
                    elif trace.name=='changed_roi':
                        value['fixture_change']='Original 12x12 non-text patch inside candidate ROI, above title band; synthetic animation analogue, not actual gameplay measurement'
                        assert control.state.confirmed and overlay.isVisible() and native_visible() and value['sampled_inference_visible_ms']>=500
                        assert all(phase['title_regions_unchanged'] for phase in value['phases'])
                        assert value['final_candidate_names']==['星火共鸣','晶盾回路','风步微光']
                        assert all(phase['candidate_roi_sha256']!=phase['accepted_candidate_roi_sha256'] and phase['hud_input_sha256']==phase['accepted_hud_input_sha256'] for phase in value['phases'])
                    elif trace.name=='changed_title':
                        assert value['title_semantic_rejection_observed'],'Changed titles lacked early semantic callback evidence'
                        assert not control.state.confirmed and native_visible() and value['sampled_inference_visible_ms']==0
                        assert value['final_visible_slots']==[3] and overlay._badge_widgets[2].tier=='T3'
                        assert value['final_candidate_names']==['晶盾回路','星火共鸣','风步微光']
                        assert all(not phase['title_regions_unchanged'] for phase in value['phases'])
                    elif trace.name in ('changed_hud','unknown_hud'):
                        assert not control.state.confirmed and not native_visible() and value['sampled_inference_visible_ms']==0
                        hero=trace.final_value['hero_observation']
                        assert (hero.get('hero')=='磐石守卫（演示）' and hero.get('confident') is True) if trace.name=='changed_hud' else hero.get('confident') is not True
                    else:
                        value.update(stop_return_ms=round(trace.stop_ms,3),late_final_discarded=bool(trace.stopped and trace.events['final']>trace.events['stop']
                            and trace.final_generation!=control.state.generation and not control.state.running and not control.state.confirmed and not native_visible() and control._accepted_frame is None))
                        assert value['late_final_discarded'] and trace.stop_ms<250
                        if mode=='persistent':value['stop_cleanup']=trace.stop_cleanup
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
        deadline=time.monotonic()+8
        def ready():
            assert time.monotonic()<deadline,'Retired capture cleanup exceeded the observation bound'
            if getattr(capture_adapter,'cleanup_pending',False):
                QtCore.QTimer.singleShot(10,lambda:run(ready));return
            begin('independent_first',lambda:assert_first_then(lambda:established(next_step)))
        ready()
    def changed_roi():
        paint_mock(changed_roi=True);app.processEvents();begin('changed_roi',lambda:recover(changed_title,reset=True))
    def changed_title():
        paint_mock(changed_title=True);app.processEvents();begin('changed_title',lambda:recover(changed,reset=True))
    def changed():
        paint_mock('9002');app.processEvents();begin('changed_hud',lambda:recover(unknown))
    def unknown():
        paint_mock(gray=True);app.processEvents();begin('unknown_hud',lambda:recover(stop_late))
    def stop_late():begin('stop_late',lambda:recover(finish,restart=True))
    def finish():
        assert [row['name'] for row in rows]==['unchanged','changed_roi','changed_title','changed_hud','unknown_hud','stop_late']
        if mode=='one-shot':
            mode_report['cleanup']=dict(helper_count=len(all_helpers),helpers_exited=all(process.poll() is not None for process in all_helpers),
                pipes_closed=all(_duty_one_shot_process_closed(process) for process in all_helpers),
                jobs_closed=bool(len(all_jobs)==len(all_helpers) and all(job.handle is None for job in all_jobs)),
                adapter_cleanup_complete=not getattr(capture_adapter,'cleanup_pending',False),complete=True)
            assert all(mode_report['cleanup'][key] is True for key in ('helpers_exited','pipes_closed','jobs_closed','adapter_cleanup_complete'))
        else:mode_report['reuse_captures']=reuse_captures
        cleanup();mode_report.pop('active_case',None)
        save();QtCore.QTimer.singleShot(100,lambda:run(done))
    begin('independent_first',lambda:assert_first_then(lambda:established(lambda:begin('unchanged',changed_roi))))


def _manual_smoke_cadence(control):
    """Keep this diagnostic's explicit captures in charge across Qt event pumps."""
    original_schedule=control.schedule_capture
    control.monitor.stop();control.schedule_capture=lambda delay=None:None
    def restore():
        control.monitor.stop();control.schedule_capture=original_schedule
    return restore



def _recognize_owned_ocr(control,target,pixels,engine,roi,*,allow_reuse=True):
    """Use the same active-mode matcher and cache scope as production capture."""
    from hero_recognition import recognize_frame
    matcher=control.hero_matcher if control.hero_auto.isChecked() else None
    scoped=control.ocr_reuse.scoped(engine,(target.identity,roi,'game'),
        allow_reuse=control.state.confirmed and control.state.confirmation_mode=='automatic') if allow_reuse else engine
    value=recognize_frame(pixels,roi,scoped,control.data['augments'],matcher)
    if not allow_reuse:value['ocr_reused']=False
    return value


def _dispatch_owned_ocr(control,target,value,capture_rect,captured_at,roi,*,hero_observation=None,candidates_missing=False):
    """Deliver one newly captured smoke observation with its current scope.

    Optional identity/candidate overrides are explicit handler-boundary negative
    fixtures, never production inference. They must share this new capture's
    serial/scope, rather than replaying an earlier completed OCR callback.
    """
    control._capture_serial+=1
    matcher=control.hero_matcher if control.hero_auto.isChecked() else None
    source=(id(control.data),json.dumps(control.data.get('metadata',{}),sort_keys=True,ensure_ascii=False))
    value=dict(value,_capturedAt=captured_at,_captureSerial=control._capture_serial,
        _windowIdentity=target.identity,_captureRect=capture_rect,
        _frameScope=(target.identity,control.capture_metadata(),capture_rect,roi,tuple(control.data['augments']),source,
            (matcher,matcher.proof_identity() if matcher else None)))
    if hero_observation is not None:value['hero_observation']=dict(hero_observation)
    if candidates_missing:
        value.update(candidates=[],automatic_candidates=[],partial_title_evidence=None,_cardGeometry=None)
    control.task_result('ocr',value,control.state.generation)
    return value


def _owned_hidden_capture(control, target, *, app, evidence, timeout=8.):
    """One diagnostic capture, after the production mode/cleanup barrier.

    This is a preflight, never a retry of capture. The owned fixture suppresses
    automatic cadence while Qt events drain; no pending owner is cleared here.
    Freshness starts after readiness, not before the preceding session closes.
    """
    started = time.monotonic()
    polls = 0
    control.overlay.hide()
    while True:
        if control.closed:
            raise RuntimeError('Owned capture stopped before readiness')
        if time.monotonic() - started >= timeout:
            raise RuntimeError('Owned capture cleanup/readiness exceeded bounded deadline')
        polls += 1
        ready = control.capture.prepare_capture_mode(False)
        settled = control.overlay.hidden_settle_ms() == 0
        if ready and settled:
            break
        app.processEvents()
        time.sleep(.005)
    assert not control.overlay.isVisible()
    assert not control.capture.u.IsWindowVisible(int(control.overlay.winId()))
    captured_at = time.monotonic()
    pixels, rect = control.capture.capture(target)
    evidence.append({'ready_before_capture': True, 'hidden_settled': True,
                     'polls': polls, 'wait_ms': round((captured_at-started)*1000, 3)})
    return pixels, rect, captured_at


def native_report_payload(report):
    # Six observed cases in both capture modes retain all evidence inside the
    # original bounded 128KiB diagnostic envelope. Omit formatting only.
    return json.dumps(report,ensure_ascii=False,separators=(',',':'))+'\n'


def _capture_failure_snapshot(control):
    """Bounded read-only evidence, never a capture or a cleanup operation."""
    from screen_capture import CAPTURE_DIAGNOSTIC_ENUMS
    from wgc_session_capture import sanitize_session_failure_evidence
    capture=getattr(control,'capture',None)
    diagnostic=getattr(capture,'last_capture_diagnostic',{})
    if not hasattr(diagnostic,'get'):diagnostic={}
    return dict(capture_diagnostic={key:diagnostic[key] for key,allowed in CAPTURE_DIAGNOSTIC_ENUMS.items()
                    if type(diagnostic.get(key)) is str and diagnostic[key] in allowed},
        session_failure=sanitize_session_failure_evidence(getattr(capture,'last_capture_failure_diagnostic',None)),
        cleanup_pending=bool(getattr(capture,'cleanup_pending',False)))


def _collect_failed_capture_cleanup(control,report,save,done,*,initial=None,clock=time.monotonic,later=QtCore.QTimer.singleShot):
    """Observe existing teardown for at most two seconds; the test stays failed."""
    started=clock()
    evidence=report['capture_failure_evidence']=dict(initial=initial or _capture_failure_snapshot(control))
    close=getattr(getattr(control,'capture',None),'close',None)
    evidence['revocation_requested']=False
    if close:
        try:close();evidence['revocation_requested']=True
        except Exception:pass  # Preserve the original failure, not cleanup text.
    save()
    def poll():
        snapshot=_capture_failure_snapshot(control);elapsed=max(0.,clock()-started)
        evidence.update(final=snapshot,cleanup_wait_ms=round(elapsed*1000,3),
            cleanup_deadline_reached=bool(snapshot['cleanup_pending'] and elapsed>=2.))
        if snapshot['cleanup_pending'] and elapsed<2.:
            later(20,poll);return
        save()
        done()
    poll()


def _exercise_manual_hero_switches(control,observe_current,names,report):
    """Repeat the actual manual-edit retirement path, with no capture retry."""
    evidence=report['manual_hero_switches']=dict(required=8,attempted=0,completed=0)
    for hero,tiers in [('磐石守卫（演示）',['T3','T1','T2']),('星火术士（演示）',['T1','T2','T3'])]*4:
        evidence['attempted']+=1
        control.hero_box.setCurrentText(hero)
        assert not control.state.confirmed and not control.overlay.isVisible()
        control.confirm();value=observe_current()
        assert control._completed_capture_serial==value['_captureSerial'],'Manual switch did not accept its new capture'
        assert value['_frameScope'][6]==(None,None),'Manual switch borrowed automatic matcher scope'
        assert control.state.hero==hero and control.state.confirmed and not control.hero_auto.isChecked()
        assert control.overlay.isVisible();inspect_smoke_layout(control.overlay)
        assert [card['name'] for card in control.overlay.cards]==names
        assert [card['sourceTier'] for card in control.overlay.cards]==tiers
        evidence['completed']+=1


def start_smoke(control,report_path,screenshot_path):
    app=QtWidgets.QApplication.instance();checks=[];root=Path(__file__).resolve().parent
    observed_frame={}
    report={'status':'running','executable_sha256':hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest() if getattr(sys,'frozen',False) else None,'backend':'qtwidgets','qt_platform':app.platformName(),'frozen':bool(getattr(sys,'frozen',False)),'applicationVersion':control.current_version,'native_window':False,'window_closed':False,'capture_passed':False,'ocr_passed':False,'click_through_passed':False,'scope':'Original synthetic mock game only; not LoL/Vanguard, live-game accuracy or approval','checks':checks}
    control._smoke_objects=[]
    report['owned_capture_preflights']=[]
    # Production result handlers schedule their next observation on completion.
    # This fixture owns every capture, including the real async and duty probes.
    restore_schedule=_manual_smoke_cadence(control)
    def save():
        report_path.parent.mkdir(parents=True,exist_ok=True);report_path.write_text(native_report_payload(report),encoding='utf8')
    def fail(exc):
        if report.get('status')=='failed':return
        # Duty cleanup can restore a different capture adapter. Both snapshots
        # and the drain below must retain the exact failing adapter instead.
        failed_capture=SimpleNamespace(capture=getattr(control,'capture',None))
        initial=_capture_failure_snapshot(failed_capture)
        report.update(status='failed',error=str(exc)[:2000],error_type=type(exc).__name__,error_traceback=traceback.format_exc(limit=4)[-4000:]);save()
        cleanup=getattr(control,'_smoke_duty_cleanup',None)
        if cleanup:
            control._smoke_duty_cleanup=None
            try:cleanup()
            except Exception:pass
        outer_cleanup=getattr(control,'_smoke_duty_outer_cleanup',None)
        if outer_cleanup:
            try:outer_cleanup()
            except Exception:pass
        # Keep all queued/late production callbacks quiescent while observing
        # teardown. Restore cadence only immediately before terminal closure.
        stop=getattr(control,'stop_monitor',None)
        if stop:stop()
        control.monitor.stop();control.schedule_capture=lambda delay=None:None
        def finish():
            restore_schedule()
            for widget in control._smoke_objects:widget.close()
            control.close();app.exit(1)
        _collect_failed_capture_cleanup(failed_capture,report,save,finish,initial=initial)
    def run(fn):
        if report.get('status')=='failed':return
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
    from hero_recognition import PortraitMatcher
    bank=portraits()
    configure_data(control.data)
    control.hero_matcher=PortraitMatcher(bank,control.data['heroes'])
    def paint_mock(key='9001',*,gray=False,changed_roi=False,changed_title=False):
        portrait=bank[key].convert('L').convert('RGB') if gray else bank[key]
        image.setPixmap(smoke_pixmap(portrait,root/'fixtures/auto-scene.png',mock_width,mock_height,float(mock.windowHandle().devicePixelRatio()),changed_roi=changed_roi,changed_title=changed_title))
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
        bytes_,rect,captured_at=_owned_hidden_capture(control,target,app=app,evidence=report['owned_capture_preflights'])
        report['capture_passed']=True;report['captureBytes']=len(bytes_);report['clientRect']={'x':rect.x,'y':rect.y,'width':rect.width,'height':rect.height}
        checks.append('Windows capture returned only selected mock client area into an in-memory PNG')
        from local_ocr import LocalOCR
        engine=LocalOCR();control.ocr=engine
        expected=['星火共鸣','晶盾回路','风步微光']
        control.hero_auto.setChecked(True);control.state.clear_hero();control.state.start(target.identity)
        assert control.state.hero=='' and control.hero_auto.isChecked()
        def observe_current(*,hero_observation=None,candidates_missing=False):
            control.overlay.hide();assert not control.overlay.isVisible()
            assert not control.capture.u.IsWindowVisible(int(control.overlay.winId()))
            pixels,capture_rect,captured_at=_owned_hidden_capture(control,target,app=app,evidence=report['owned_capture_preflights'])
            roi=tuple(spin.value()/100 for spin in control.roi)
            value=_recognize_owned_ocr(control,target,pixels,engine,roi)
            if time.monotonic()-captured_at>3:
                pixels,capture_rect,captured_at=_owned_hidden_capture(control,target,app=app,evidence=report['owned_capture_preflights'])
                value=_recognize_owned_ocr(control,target,pixels,engine,roi,allow_reuse=False)
            return _dispatch_owned_ocr(control,target,value,capture_rect,captured_at,roi,hero_observation=hero_observation,candidates_missing=candidates_missing)
        observed_frame['refresh']=observe_current
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
        # Deliberately withhold just the middle title from the dictionary, not
        # from the pixels. Real captured OCR must still prove three title rows;
        # the known outer cards remain in their true positions without guessing
        # a grade/name for the unsupported middle slot.
        middle=control.data['augments'].pop(expected[1]);control.ocr_reuse.clear()
        try:
            observe_current();assert not control.state.confirmed
            observe_current()
            assert control.current_partial_names()==(expected[0],'',expected[2]),control.current_partial_names()
            assert not control.state.confirmed and control.state.offered==()
            assert len(control.overlay.cards)==3
            assert control.overlay.cards[0]['sourceTier']=='T1' and control.overlay.cards[2]['sourceTier']=='T3'
            assert control.overlay.cards[1]['name']=='待识别' and control.overlay.cards[1]['sourceTier'] is None
            assert control.overlay.isVisible() and u.IsWindowVisible(int(control.overlay.winId()))
            from card_badges import native_region
            native_region(int(control.overlay.winId()),control.overlay._badge_regions,verify_only=True)
            assert len(control.overlay._badge_regions)==2 and not control.overlay._badge_widgets[1].isVisibleTo(control.overlay)
            report['partial_candidate_slots_passed']=True
            checks.append('Actual OS capture and local OCR retain known left/right grades after two independent frames while an unsupported middle title stays ungraded in its fixed slot')
        finally:
            control.data['augments'][expected[1]]=middle;control.ocr_reuse.clear()
        observe_current();observe_current()
        assert control.state.confirmed and control.state.offered==tuple(expected)
        report['partial_to_full_recovery_passed']=True
        report['targetForegroundBefore']=int(control.capture.u.GetForegroundWindow() or 0)
        unknown=observe_current(hero_observation={'hero':None,'confident':False,'reason':'Synthetic unknown portrait'})
        assert control._completed_capture_serial==unknown['_captureSerial'],'Unknown-hero boundary fixture did not reach the current result handler'
        assert not control.state.confirmed and control.state.hero=='' and not control.overlay.isVisible();report['auto_unknown_clears_passed']=True
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
        assert [widget.tier for widget in control.overlay.tier_labels]==['T1','T2','T3']
        assert [widget.accessibleName() for widget in control.overlay.tier_labels]==[f'选项 {i} · {name} · T{i} · 演示评级' for i,name in enumerate(names,1)]
        _exercise_manual_hero_switches(control,observe_current,names,report)
        checks.append('Eight alternating manual hero switches retire the old capture scope and each accept one fresh hidden capture with the exact hero-specific grades')
        report['source_tier_hero_specific']=True;report['auto_manual_fallback_passed']=not control.hero_auto.isChecked()
        control.hero_box.setCurrentText('磐石守卫（演示）');control.confirm();observe_current();assert control.overlay.isVisible();inspect_smoke_layout(control.overlay)
        tier_row=control.data['heroAugmentStats']['磐石守卫（演示）'][0];saved_tier=tier_row['tier']
        for missing in [None,'UNKNOWN']:
            tier_row['tier']=missing;control.confirm();observe_current();assert control.overlay.isVisible();inspect_smoke_layout(control.overlay);assert control.overlay._badge_widgets[1].tier=='暂无评级' and '暂无评级' in control.overlay._badge_widgets[1].accessibleName()
        tier_row['tier']=saved_tier;report['source_tier_missing_passed']=True
        control.hero_box.setCurrentText('星火术士（演示）');control.confirm();observe_current();assert control.overlay.isVisible();inspect_smoke_layout(control.overlay)
        assert [card['name'] for card in control.overlay.cards]==names
        assert all('winRate' not in card and 'sourceRank' not in card and 'recommendedName' not in card for card in control.overlay.cards)
        rendered=' '.join(widget.tier for widget in control.overlay.tier_labels)
        assert all(value not in rendered for value in ['60.00%','55.00%','50.00%','胜率'])
        report.update(source_tier_display_passed=True,source_tier_screen_order_preserved=True,source_tier_no_winrate_display=True,
                      source_tier_rendered=[widget.tier for widget in control.overlay.tier_labels],
                      card_names_accessible=[card['name'] for card in control.overlay.cards],
                      source_tier_accessible=[widget.accessibleName() for widget in control.overlay.tier_labels],
                      badge_source_markers=[widget.source for widget in control.overlay.tier_labels])
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
        readiness=SimpleNamespace(finished=False,error=None,capture_count=0);active=[readiness]
        previous_schedule=control.schedule_capture
        control.schedule_capture=lambda delay=None:_schedule_duty_mode_wait(control,active,QtCore.QTimer.singleShot,run,delay)
        control.capture_tick()
        def poll():
            assert time.monotonic()<deadline,'Production asynchronous capture/OCR did not finish within its stale limit'
            if control.capture_pending or control.ocr_busy:readiness.capture_count=1
            if control.ocr_busy:
                busy_ticks.append(time.monotonic())
                control.check_target()
                assert not control.overlay.isVisible(),'Watchdog restored own overlay during capture/inference'
            if control.capture_pending or control.ocr_busy or control._mode_wait_started is not None:
                QtCore.QTimer.singleShot(20,lambda:run(poll));return
            readiness.finished=True;active[0]=None;control.schedule_capture=previous_schedule
            assert busy_ticks and control.last_observation>before and control.state.confirmed
            report['async_capture_ui_passed']=True
            checks.append(('Actual frozen' if report['frozen'] else 'Actual source')+' production capture worker completed while Qt timers ran; manual-mode watchdog kept own overlay hidden until the accepted fresh result')
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
        from card_badges import native_region
        native_region(hwnd,overlay._badge_regions,verify_only=True)
        assert len(overlay._badge_regions)==3
        report['three_badge_regions_verified']=True
        report['badge_regions_physical']=[list(region) for region in overlay._badge_regions]
        # Actual Win32 point hit test at a point inside the overlay; no game input.
        rect=W.RECT();u.GetWindowRect.argtypes=[W.HWND,ctypes.POINTER(W.RECT)];u.GetWindowRect.restype=W.BOOL;assert u.GetWindowRect(hwnd,ctypes.byref(rect))
        point=W.POINT(rect.left+(rect.right-rect.left)//2,rect.top+20)
        hit=int(u.GetAncestor(u.WindowFromPoint(point),2) or 0)
        assert hit==control.target.hwnd,('Transparent overlay intercepted point',hit,control.target.hwnd)
        report['badge_native_hit_evidence']=prove_badge_native_hits(control.capture,overlay,control.target.hwnd,rect)
        report['badge_gap_hit_test_passed']=True
        dpr=float(overlay.windowHandle().devicePixelRatio())
        from badge_contract import WIDTH,HEIGHT,GAP,choose_width,align_physical_regions,top_gap
        client=control.capture.rect(control.target)
        report['badge_card_bounds_physical']=[]
        logical_width=choose_width([(x+cw/2)*client.width for x,y,cw,ch in overlay._badge_anchors.rects],dpr)
        for slot,(bx,by,bw,bh) in enumerate(overlay._badge_regions):
            x,y,cw,ch=overlay._badge_anchors.rects[slot]
            assert (bw,bh)==(math.ceil(logical_width*dpr),math.ceil(HEIGHT*dpr))
            report['badge_card_bounds_physical'].append([client.x+x*client.width,client.y+y*client.height,cw*client.width,ch*client.height])
            gap=client.y+y*client.height-(rect.top+by+bh)
            assert top_gap(dpr)<=gap<top_gap(dpr)+dpr+1.01
        bw,bh=math.ceil(logical_width*dpr),math.ceil(HEIGHT*dpr)
        physical=[(round(c[0]+c[2]/2-bw/2),math.floor(c[1]-top_gap(dpr)-bh),bw,bh) for c in report['badge_card_bounds_physical']]
        expected_bounds,expected_regions=align_physical_regions(physical,dpr,logical_width)
        assert tuple(report['overlay_window_physical'][k] for k in ('x','y','width','height'))==expected_bounds
        assert tuple(overlay._badge_regions)==expected_regions
        report['badge_above_cards_verified']=True
        # Renderer-only original hint; this is explicitly not source-combo or
        # live-game evidence. The ordinary demo data correctly abstains.
        from copy import deepcopy
        original_cards=deepcopy(overlay.cards);hint_cards=deepcopy(original_cards)
        original_regions=tuple(overlay._badge_regions)
        synthetic_hint='搭配：原创超长强化名称甲、原创超长强化名称乙'
        hint_cards[0]['sourceHint']=synthetic_hint
        overlay.set_cards(control.state.hero,hint_cards);overlay.show_at(client,control.target);app.processEvents()
        inspect_smoke_layout(overlay);native_region(hwnd,overlay._badge_regions,verify_only=True)
        badge=overlay._badge_widgets[0]
        assert tuple(overlay._badge_regions)==original_regions,'Hint must preserve exact native badge regions'
        assert badge.hint==synthetic_hint and badge.toolTip()==synthetic_hint and synthetic_hint in badge.accessibleName()
        assert badge.display_hint and badge.display_hint!=synthetic_hint and badge.tier==original_cards[0]['sourceTier']
        assert all(not b.hint for b in overlay._badge_widgets[1:])
        report['source_hint_renderer_passed']=True
        report['source_hint_render_scope']='Original synthetic sourceHint renderer only; not live-game or source-combo accuracy'
        report['source_hint_visible_text']=badge.display_hint
        overlay.set_cards(control.state.hero,original_cards);overlay.show_at(client,control.target);app.processEvents()
        inspect_smoke_layout(overlay);native_region(hwnd,overlay._badge_regions,verify_only=True)
        style_on=int(control.capture.get_long(int(overlay.winId()),-20));assert style_on&0x20
        report['click_through_passed']=True;checks.append('Real OS point hit testing proves opaque badge centers and target gaps with native transparency disabled, then restores normal click-through')
        assert control.hotkey_registered,'Ctrl+Alt+O registration failed in test session';checks.append('RegisterHotKey succeeded without input hooks')
        # Compose ONLY our two rendered widgets; never save a user desktop screenshot.
        mock_pixels=mock.grab();mock_pixels.setDevicePixelRatio(1);overlay_pixels=overlay.grab();overlay_pixels.setDevicePixelRatio(1)
        canvas=QtGui.QPixmap(1100,780);canvas.fill(QtGui.QColor('#102029'));painter=QtGui.QPainter(canvas);painter.drawPixmap(0,0,mock_pixels);painter.drawPixmap(20,530,overlay_pixels.scaled(1060,230,QtCore.Qt.AspectRatioMode.KeepAspectRatio));painter.end()
        screenshot_path.parent.mkdir(parents=True,exist_ok=True);assert canvas.save(str(screenshot_path),'PNG')
        report['screenshot']=str(screenshot_path);report['screenshot_method']='Qt QWidget.grab of our synthetic mock and overlay only, composited locally; OS capture/OCR separately asserted'
        checks.append('Original synthetic native mock/overlay rendering saved, with no user desktop pixels')
        missing=observed_frame['refresh'](candidates_missing=True)
        assert control._completed_capture_serial==missing['_captureSerial'],'Candidate-loss boundary fixture did not reach the current result handler'
        assert not control.state.confirmed and not overlay.isVisible();checks.append('Production OCR result handler hides overlay on explicit synthetic scene/candidate loss in a freshly captured current scope')
        old_generation=control.state.generation;control.hero_box.setCurrentText('磐石守卫（演示）');assert control.state.generation>old_generation;checks.append('Actual hero selection signal invalidates prior scene state')
        control.state.confirm(names,control.data['augments']);control.last_observation=__import__('time').monotonic();control.last_rect=control.capture.rect(control.target);observed_frame['refresh']();assert overlay.isVisible()
        mock.move(mock.x()+7,mock.y()+5);QtWidgets.QApplication.processEvents();control.check_target();assert control.state.confirmed and overlay.isVisible();overlay._verify_rect(control.capture.rect(control.target));checks.append('Real same-size mock translation preserves fresh confirmed identity/offers and repositions overlay inside the new physical client bounds')
        control.last_observation=time.monotonic()-5;control.check_target();assert not control.state.confirmed and not overlay.isVisible() and not u.IsWindowVisible(hwnd);report['badge_revocation_hidden_verified']=True;checks.append('Expired observations cannot be revived by translating the target window')
        control.state.confirm(names,control.data['augments']);control.last_observation=time.monotonic()
        before_resize=control.capture.rect(control.target);shrink_smoke_mock(mock,image);after_resize=control.capture.rect(control.target)
        assert after_resize.width<before_resize.width and after_resize.height<before_resize.height,'Actual physical mock size did not shrink'
        assert inside(work_area,native_rect(int(mock.winId()))),'Resized own mock escaped physical work area'
        report['resize_physical_before']={'width':before_resize.width,'height':before_resize.height};report['resize_physical_after']={'width':after_resize.width,'height':after_resize.height}
        control.check_target();assert not control.state.confirmed and not overlay.isVisible();checks.append('Actual physical mock size changed after clearing its own artwork minimum; production watchdog hides old cards pending fresh recognition')
        control.state.confirm(names,control.data['augments']);mock.showMinimized();QtWidgets.QApplication.processEvents();control.check_target();assert not control.state.confirmed and not overlay.isVisible();checks.append('Real mock minimization hides old cards through production watchdog')
        restore_schedule();control.close();mock.close();report['window_closed']=not control.isVisible() and not overlay.isVisible() and not mock.isVisible() and not control.hotkey_registered
        assert report['window_closed'];report['status']='passed';checks.append('Control, overlay and mock closed; timer monitoring and registered hotkey released');save();app.exit(0)
    QtCore.QTimer.singleShot(150,lambda:run(prepare))

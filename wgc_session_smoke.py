"""Explicit, DEFAULT-OFF native Windows owned-window session experiment.

No game, external HWND, screenshot input, trust override, or pixel files. This
fixture deliberately uses private inspection points only for evidence. Production
never imports it. Quiet pipes do not prove absence of GPU/CPU readback: report that
limit explicitly, along with actual retirement latency rather than a 50 ms claim.
"""
from __future__ import annotations
import ctypes
from ctypes import wintypes as W
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from unittest.mock import patch
from app_version import __version__

CHECK_FIELDS = (
    'owned_pixels_passed', 'same_helper_session_passed', 'fresh_requests_passed',
    'identical_roi_passed', 'static_frame_requests_passed', 'idle_no_unsolicited_pixels_passed', 'idle_overlay_passed',
    'visible_overlay_request_rejected', 'outside_overlay_request_rejected', 'other_same_process_occluder_rejected',
    'layered_same_process_occluder_rejected', 'focus_loss_rejected',
    'geometry_change_rejected', 'target_hide_rejected', 'target_destroy_rejected',
    'process_identity_rejected', 'hwnd_retarget_rejected', 'overlay_style_rejected',
    'overlay_affinity_rejected', 'overlay_registration_rejected', 'overlay_destroy_rejected',
    'native_roi_rejected', 'native_generation_rejected', 'native_duplicate_id_rejected',
    'native_pipeline_rejected', 'cancel_before_launch_passed', 'cancel_during_wait_passed',
    'stop_passed', 'native_stop_passed', 'pipe_eof_passed', 'idle_lease_passed',
    'request_deadline_passed', 'job_close_passed', 'suspended_job_close_passed', 'parent_death_passed',
    'helpers_exited_passed', 'pipe_readers_exited_passed', 'job_handles_closed_passed',
    'windows_closed_passed')
SCOPE = ('DEFAULT-OFF test-only persistent HWND WGC. Original self-owned Qt windows and '
         'synthetic pixels only; source/frozen parity at process-local Qt scales. No real '
         'game, exclusive fullscreen, Vanguard, OCR, or production integration claim.')
LIMITATIONS = {
    'idle_cpu_readback_runtime_proven': False,
    'idle_cpu_readback_evidence': 'Quiet stdout plus source control flow; no GPU/CPU readback instrumentation.',
    'gpu_framepool': 'Windows retains the full target-window GPU surface while idle. Only requested client ROI is staged/read into CPU memory by the reviewed source.',
    'watchdog_interval_ms': 25,
    'teardown_50ms_guaranteed': False,
    'dpi_scope': 'Process-local Qt scale, measured physical dimensions; no system display/DPI changes.',
    'production_enabled': False,
    'production_translucent_compatibility_proven': False,
    'parent_death_scope': 'Eventual exact helper cleanup; parent death also destroys the owned target. Separate suspended Job-close evidence isolates the kernel lifetime mechanism.',
    'focus_race': 'Guards run before and after each readback; a concurrent focus/identity change can overlap a GPU copy. Changed results are discarded. No atomic zero CPU activity after the exact focus-loss instant is claimed.',
}
OPAQUE_PROFILE = 'qt-opaque-redirected-v1'
TRANSLUCENT_PROFILE = 'qt-translucent-comparison-v1'
OVERLAY_REQUIRED_STYLE = 0x080800a8
QT_OVERLAY_FIELDS = ('qt_translucent_background','qt_opaque_paint_event',
                     'qt_surface_has_alpha','qt_surface_alpha_buffer_size','qt_opacity')
OVERLAY_PROFILE_ROLES = {'translucent-probe': TRANSLUCENT_PROFILE,
                         'registered-overlay': OPAQUE_PROFILE, 'lookalike-occluder': OPAQUE_PROFILE}
COLORS = ((226, 61, 82), (45, 188, 137), (68, 109, 231), (243, 196, 54))


def require(value, message):
    if not value:
        raise AssertionError(message)


def write_report(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


def pixel_error(image, rect, roi, colors=COLORS):
    from PIL import Image, ImageDraw, ImageChops, ImageStat
    expected = Image.new('RGB', (rect.width, rect.height))
    draw = ImageDraw.Draw(expected)
    x, y = rect.width // 2, rect.height // 2
    for bounds, color in zip(((0, 0, x-1, y-1), (x, 0, rect.width-1, y-1),
                              (0, y, x-1, rect.height-1), (x, y, rect.width-1, rect.height-1)), colors):
        draw.rectangle(bounds, fill=color)
    left, top, width, height = roi
    expected = expected.crop((left, top, left+width, top+height))
    require(image.size == expected.size, 'Exact client ROI dimensions differ')
    error = max(ImageStat.Stat(ImageChops.difference(image.convert('RGB'), expected)).mean)
    require(error <= 2, 'Native session pixels differ from owned synthetic target')
    return round(error, 4)


def qt_overlay_observation(widget):
    """Read the Qt window's actual reported surface format, without changing it."""
    from PySide6 import QtCore
    handle=widget.windowHandle()
    require(handle is not None,'Owned overlay has no Qt native window handle')
    surface=handle.format()
    return {'qt_translucent_background':bool(widget.testAttribute(QtCore.Qt.WA_TranslucentBackground)),
            'qt_opaque_paint_event':bool(widget.testAttribute(QtCore.Qt.WA_OpaquePaintEvent)),
            'qt_surface_has_alpha':bool(surface.hasAlpha()),
            'qt_surface_alpha_buffer_size':int(surface.alphaBufferSize()),
            'qt_opacity':float(widget.windowOpacity())}


def overlay_profile_matches(row,profile,stage):
    if (row['qt_opacity']!=1.0 or not -1<=row['qt_surface_alpha_buffer_size']<=64
            or row['qt_surface_has_alpha']!=(row['qt_surface_alpha_buffer_size']>0)):return False
    if profile==OPAQUE_PROFILE:
        return (not row['qt_translucent_background'] and row['qt_opaque_paint_event']
                and not row['qt_surface_has_alpha'] and row['qt_surface_alpha_buffer_size'] in (-1,0))
    if profile==TRANSLUCENT_PROFILE:
        return (row['qt_translucent_background'] and not row['qt_opaque_paint_event']
                and (stage=='created-hidden' or (row['qt_surface_has_alpha']
                     and row['qt_surface_alpha_buffer_size']>0)))
    return False


def overlay_observation(user,dwm,hwnd,expected_style,owner_pid,*,stage,attempt=False):
    """Bounded own-window metadata; preserve each WinError before other calls.

    Visibility is observed, not treated as an undocumented Windows prerequisite.
    No titles, paths, pixels, or external HWND details enter this record.
    """
    require(stage in ('created-hidden','realized-visible','verified-hidden'), 'Unknown overlay observation stage')
    exists=bool(user.IsWindow(hwnd));top_level=int(user.GetAncestor(hwnd,2)or 0)==hwnd
    pid=W.DWORD();ctypes.set_last_error(0)
    owner_thread=int(user.GetWindowThreadProcessId(hwnd,ctypes.byref(pid)))
    owner_error=ctypes.get_last_error()
    style=int(user.GetWindowLongPtrW(hwnd,-16))&0xffffffff
    extended_style=int(user.GetWindowLongPtrW(hwnd,-20))&0xffffffff
    composed=W.BOOL();hr=int(dwm.DwmIsCompositionEnabled(ctypes.byref(composed)))
    row={'stage':stage,'is_window':exists,'top_level':top_level,
         'visible':bool(user.IsWindowVisible(hwnd)),'owner_query_ok':bool(owner_thread),
         'owner_is_self':bool(owner_thread and pid.value==owner_pid),'owner_winerror':owner_error,
         'style':style,'extended_style':extended_style,'expected_extended_style':expected_style,
         'dwm_hresult':hr&0xffffffff,'dwm_composing':bool(hr>=0 and composed.value),
         'set_attempted':False,'set_ok':False,'set_winerror':0}
    # A diagnostic never modifies a foreign, replaced, structurally wrong, or
    # noncomposed window just to learn why it failed.
    if (attempt and exists and top_level and row['owner_is_self'] and row['dwm_composing']
            and extended_style==expected_style
            and extended_style&OVERLAY_REQUIRED_STYLE==OVERLAY_REQUIRED_STYLE
            and not extended_style&0x00200000 and style&0x80000000 and not style&0x40c40000):
        ctypes.set_last_error(0)
        success=bool(user.SetWindowDisplayAffinity(hwnd,0x11))
        error=ctypes.get_last_error()
        row.update(set_attempted=True,set_ok=success,set_winerror=error)
    affinity=W.DWORD();ctypes.set_last_error(0)
    success=bool(user.GetWindowDisplayAffinity(hwnd,ctypes.byref(affinity)))
    error=ctypes.get_last_error()
    row.update(affinity_query_ok=success,affinity_winerror=error,affinity=affinity.value)
    color=W.DWORD();alpha=W.BYTE();flags=W.DWORD();ctypes.set_last_error(0)
    success=bool(user.GetLayeredWindowAttributes(hwnd,ctypes.byref(color),ctypes.byref(alpha),ctypes.byref(flags)))
    error=ctypes.get_last_error()
    row.update(layered_attributes_query_ok=success,layered_attributes_winerror=error,
               layered_color_key=color.value,layered_alpha=alpha.value,layered_flags=flags.value)
    return row


def prepare_owned_overlay(widget,user,dwm,hwnd,expected_style,owner_pid,pump,result,*,label):
    """Compare separately constructed profiles; only the named probe may fail WDA.

    The opaque profile is preselected, never a success-dependent fallback. The
    hidden affinity call is evidence; one bounded retry follows first show/paint.
    Never substitute WDA_MONITOR, alter the original translucent renderer with
    SetLayeredWindowAttributes, or weaken the hidden-request contract.
    """
    require(label in OVERLAY_PROFILE_ROLES,'Unknown owned overlay role')
    profile=OVERLAY_PROFILE_ROLES[label]
    rows=result.setdefault('overlay_setup',[])
    require(len(rows)<=6 and not any(row['role']==label for row in rows),
            'Owned overlay setup observation budget exceeded or role repeated')
    def observe(stage,attempt=False):
        qt=qt_overlay_observation(widget);same=int(widget.winId())==hwnd
        row=overlay_observation(user,dwm,hwnd,expected_style,owner_pid,stage=stage,
                                attempt=attempt and same and overlay_profile_matches(qt,profile,stage))
        row.update(qt,role=label,profile=profile,hwnd_unchanged=same)
        rows.append(row)
        return row
    def identity(row):
        return (row['hwnd_unchanged'] and row['is_window'] and row['top_level']
                and row['owner_is_self'] and row['extended_style']==expected_style
                and row['extended_style']&OVERLAY_REQUIRED_STYLE==OVERLAY_REQUIRED_STYLE
                and not row['extended_style']&0x00200000
                and row['style']&0x80000000 and not row['style']&0x40c40000
                and (row['style']&~0x10000000)==(before['style']&~0x10000000))
    def rendering(row):
        valid=overlay_profile_matches(row,profile,row['stage'])
        if profile==OPAQUE_PROFILE:
            valid=valid and row['layered_attributes_query_ok'] and row['layered_color_key']==0 \
                  and row['layered_alpha']==255 and row['layered_flags']==2
        return valid
    before=observe('created-hidden',True)
    require(identity(before) and not before['visible'],'Owned overlay identity/styles invalid before first show')
    require(before['dwm_composing'],'Owned overlay requires DWM before first show')
    require(rendering(before),'Owned overlay rendering profile invalid before first show')
    try:
        widget.show();widget.update();pump(.12)
        shown=observe('realized-visible',True)
        require(identity(shown),'Owned overlay identity/styles changed during first show')
        require(shown['visible'] and shown['dwm_composing'],'Owned overlay was not realized visibly with DWM')
        require(rendering(shown),'Owned overlay rendering profile changed during first show')
    finally:
        widget.hide();pump(.04)
        hidden=observe('verified-hidden')
    require(identity(hidden) and not hidden['visible'] and hidden['dwm_composing'],
            'Owned overlay identity/styles invalid after hiding')
    require(rendering(hidden) and all(shown[key]==hidden[key] for key in QT_OVERLAY_FIELDS),
            'Owned overlay rendering profile changed while hidden')
    shown_excluded=shown['set_ok'] and shown['affinity_query_ok'] and shown['affinity']==0x11
    hidden_excluded=hidden['affinity_query_ok'] and hidden['affinity']==0x11
    if profile==OPAQUE_PROFILE:
        require(shown_excluded,'Owned overlay exact exclusion unavailable after realization; see overlay_setup diagnostics')
        require(hidden_excluded,'Owned overlay did not retain exact exclusion while hidden; see overlay_setup diagnostics')
    return {'profile':profile,**{key:shown[key]for key in QT_OVERLAY_FIELDS},
            **({'exclusion_available':bool(shown_excluded and hidden_excluded)}if profile==TRANSLUCENT_PROFILE else {})}


class Fixture:
    """Own all windows/processes; pump Qt while capture runs on a worker."""
    def __init__(self, result):
        require(os.name == 'nt' and ctypes.sizeof(ctypes.c_void_p) == 8,
                'Actual Windows x64 desktop is mandatory; Linux/offscreen is not evidence')
        version=sys.getwindowsversion()
        result['windows_version']={key:getattr(version,key)for key in ('major','minor','build')}
        result['overlay_setup']=[]
        import wgc_session_capture as session
        from screen_capture import Win32Capture
        from PySide6 import QtCore, QtGui, QtWidgets
        self.session, self.QtCore, self.QtGui, self.QtWidgets = session, QtCore, QtGui, QtWidgets
        self.result, self.sessions, self.windows = result, [], []
        self.end = time.monotonic() + 150
        self.capture = Win32Capture(); self.u = self.capture.u
        for name, args, result_type in (
            ('SetThreadDpiAwarenessContext', [ctypes.c_void_p], ctypes.c_void_p),
            ('SetForegroundWindow', [W.HWND], W.BOOL),
            ('ShowWindow', [W.HWND, ctypes.c_int], W.BOOL),
            ('SetWindowDisplayAffinity', [W.HWND, W.DWORD], W.BOOL),
            ('GetWindowDisplayAffinity', [W.HWND, ctypes.POINTER(W.DWORD)], W.BOOL),
            ('SetLayeredWindowAttributes', [W.HWND, W.DWORD, W.BYTE, W.DWORD], W.BOOL),
            ('GetLayeredWindowAttributes', [W.HWND, ctypes.POINTER(W.DWORD), ctypes.POINTER(W.BYTE), ctypes.POINTER(W.DWORD)], W.BOOL),
            ('GetWindowLongPtrW', [W.HWND, ctypes.c_int], ctypes.c_ssize_t),
            ('SetWindowLongPtrW', [W.HWND, ctypes.c_int, ctypes.c_ssize_t], ctypes.c_ssize_t),
            ('SetWindowPos', [W.HWND, W.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, W.UINT], W.BOOL),
            ('GetPropW', [W.HWND, W.LPCWSTR], W.HANDLE),
            ('RemovePropW', [W.HWND, W.LPCWSTR], W.HANDLE),
            ('IsWindowVisible', [W.HWND], W.BOOL), ('IsWindow', [W.HWND], W.BOOL)):
            function = getattr(self.u, name); function.argtypes = args; function.restype = result_type
        self.dwm=ctypes.WinDLL('dwmapi',use_last_error=True)
        self.dwm.DwmIsCompositionEnabled.argtypes=[ctypes.POINTER(W.BOOL)]
        self.dwm.DwmIsCompositionEnabled.restype=ctypes.c_long
        self.old_dpi = self.u.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
        require(self.old_dpi, 'Cannot establish PMv2 fixture observer coordinates')
        try:
            self.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
            require(self.app.platformName().lower() == 'windows', 'Actual Windows Qt platform required')
            result['qt_platform'] = self.app.platformName()
            self.initialize_windows(result)
        except BaseException:
            # No helper/session exists until construction returns. Do not leave
            # visible windows or changed thread DPI after any setup failure.
            try:
                for widget in self.windows:
                    try:
                        try:widget.close()
                        finally:widget.destroy()
                    except Exception:pass
                if hasattr(self,'app'):self.app.processEvents()
            finally:
                self.u.SetThreadDpiAwarenessContext(self.old_dpi)
            raise

    def initialize_windows(self,result):
        result['overlay_rendering']={'active_profile':OPAQUE_PROFILE,
            'selection':'preselected-before-probe','production_translucent_compatibility_proven':False}
        self.window = self.new_target()
        probe,probe_hwnd,probe_style=self.new_overlay(TRANSLUCENT_PROFILE)
        try:
            result['overlay_rendering']['translucent_probe']=prepare_owned_overlay(
                probe,self.u,self.dwm,probe_hwnd,probe_style,os.getpid(),self.pump,result,label='translucent-probe')
        finally:
            try:probe.close()
            finally:probe.destroy()
            self.app.processEvents()
            destroyed=not bool(self.u.IsWindow(probe_hwnd))
            if 'translucent_probe'in result['overlay_rendering']:
                result['overlay_rendering']['translucent_probe']['destroyed_before_registration']=bool(destroyed and not self.sessions)
            require(destroyed and not self.sessions,'Original translucent probe survived before registration')
            self.windows.remove(probe)
        self.overlay,self.overlay_hwnd,self.overlay_style=self.new_overlay(OPAQUE_PROFILE)
        result['overlay_rendering']['registered_overlay']=prepare_owned_overlay(
            self.overlay,self.u,self.dwm,self.overlay_hwnd,self.overlay_style,
            os.getpid(),self.pump,result,label='registered-overlay')
        self.overlay.hide(); self.focus(self.window)
        self.refresh_target()
        self.roi = (self.rect.width//4, self.rect.height//4, self.rect.width//2, self.rect.height//2)
        scale = float(os.environ.get('QT_SCALE_FACTOR', '1'))
        dpr = self.window.devicePixelRatioF()
        require(abs(scale-dpr) < .01 and (self.rect.width, self.rect.height) == (round(320*scale), round(240*scale)),
                'Requested Qt scale and physical client dimensions disagree')
        version = sys.getwindowsversion()
        result.update(requested_app_scale=scale, measured_qt_scale=dpr, client_rect=vars(self.rect),
                      roi=list(self.roi), windows_version={key: getattr(version, key) for key in ('major','minor','build')},
                      requests=[], transitions=[], negative_results={})
        # Animate only a corner OUTSIDE the tested ROI so fresh WGC frames keep
        # arriving even when the main quadrants deliberately remain unchanged.
        self.timer = self.QtCore.QTimer()
        self.timer.timeout.connect(self.tick)
        self.timer.start(25)


    def new_overlay(self,profile):
        require(profile in (OPAQUE_PROFILE,TRANSLUCENT_PROFILE),'Unknown owned overlay rendering profile')
        QtCore,QtGui,QtWidgets=self.QtCore,self.QtGui,self.QtWidgets
        class OpaqueOverlay(QtWidgets.QWidget):
            def paintEvent(self,event):
                painter=QtGui.QPainter(self)
                painter.fillRect(self.rect(),QtGui.QColor(90,70,210))
        widget_type=OpaqueOverlay if profile==OPAQUE_PROFILE else QtWidgets.QWidget
        widget=widget_type(None,QtCore.Qt.Tool|QtCore.Qt.FramelessWindowHint|
            QtCore.Qt.WindowStaysOnTopHint|QtCore.Qt.WindowDoesNotAcceptFocus|QtCore.Qt.WindowTransparentForInput)
        self.windows.append(widget)
        widget.setAttribute(QtCore.Qt.WA_ShowWithoutActivating)
        widget.setAttribute(QtCore.Qt.WA_TranslucentBackground,profile==TRANSLUCENT_PROFILE)
        widget.setAttribute(QtCore.Qt.WA_OpaquePaintEvent,profile==OPAQUE_PROFILE)
        widget.setWindowOpacity(1.0)
        if profile==TRANSLUCENT_PROFILE:
            widget.setStyleSheet('background-color: rgba(90, 70, 210, 180);')
        widget.resize(80,60);widget.move(100,100)
        hwnd=int(widget.winId())
        # Check ownership before configuring a native window, not just before WDA.
        pid=W.DWORD();owner_thread=self.u.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
        require(self.u.IsWindow(hwnd) and int(self.u.GetAncestor(hwnd,2)or 0)==hwnd
                and owner_thread and pid.value==os.getpid(),'Refuse to configure a non-owned root overlay')
        style=(int(self.u.GetWindowLongPtrW(hwnd,-20))&0xffffffff)|self.session.REQUIRED_OVERLAY_STYLE
        self.u.SetWindowLongPtrW(hwnd,-20,style)
        require((int(self.u.GetWindowLongPtrW(hwnd,-20))&0xffffffff)==style,
                'Cannot establish exact own overlay extended style')
        require(self.u.SetWindowPos(hwnd,ctypes.c_void_p(-1),0,0,0,0,0x13),
                'Cannot establish owned overlay topmost style')
        if profile==OPAQUE_PROFILE:
            qt=qt_overlay_observation(widget)
            require(overlay_profile_matches(qt,profile,'created-hidden'),
                    'Opaque fixture Qt rendering profile mismatch: '+json.dumps(qt,sort_keys=True))
            ctypes.set_last_error(0)
            success=bool(self.u.SetLayeredWindowAttributes(hwnd,0,255,2))
            error=ctypes.get_last_error()
            require(success,'Cannot establish opaque redirected layered attributes; WinError='+str(error))
        return widget,hwnd,style

    def new_target(self):
        QtCore, QtGui, QtWidgets = self.QtCore, self.QtGui, self.QtWidgets
        class Target(QtWidgets.QWidget):
            colors = COLORS
            heartbeat = 0
            def paintEvent(self, event):
                painter = QtGui.QPainter(self); x, y = self.width()//2, self.height()//2
                for box, color in zip(((0,0,x,y),(x,0,self.width()-x,y),
                                      (0,y,x,self.height()-y),(x,y,self.width()-x,self.height()-y)), self.colors):
                    painter.fillRect(QtCore.QRect(*box), QtGui.QColor(*color))
                painter.fillRect(QtCore.QRect(0,0,8,8), QtGui.QColor(self.heartbeat, 0, 0))
        window = Target(); window.resize(320,240); window.move(40,40)
        window.setWindowTitle('VGA isolated persistent WGC fixture')
        self.windows.append(window); window.show()
        return window

    def tick(self):
        if self.window is not None:
            self.window.heartbeat = (self.window.heartbeat + 31) % 256
            self.window.update()

    def pump(self, seconds=.08):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            require(time.monotonic() < self.end, 'Owned fixture exceeded its overall deadline')
            self.app.processEvents(); time.sleep(.003)

    def focus(self, window):
        window.showNormal(); window.raise_(); window.activateWindow()
        self.u.SetForegroundWindow(int(window.winId())); self.pump()
        require(int(self.u.GetAncestor(self.u.GetForegroundWindow(), 2) or 0) == int(window.winId()),
                'Cannot foreground owned target; do not alter other application windows')

    def refresh_target(self):
        self.target = self.capture.info(int(self.window.winId()))
        self.rect = self.capture.rect(self.target)
        require(self.target.pid == os.getpid(), 'Fixture may capture only its own target')

    def new_session(self, overlay=False):
        require(self.result['overlay_rendering']['translucent_probe']['destroyed_before_registration'],
                'Translucent compatibility probe must be destroyed before any session')
        self.overlay.hide(); self.pump(.02); self.focus(self.window)
        session = self.session.WgcSessionCapture(experimental=True)
        self.sessions.append(session)
        if overlay:
            session.register_idle_overlay(self.overlay_hwnd, self.overlay_style, len(self.sessions))
        return session

    def request(self, session, *, target=None, rect=None, roi=None, cancelled=None,
                expected_metadata=None, action=None):
        box = {}
        def worker():
            try:
                box['image'] = session.capture(target or self.target, rect or self.rect, roi or self.roi,
                    cancelled=cancelled, expected_metadata=expected_metadata)
            except BaseException as error:
                box['error'] = error
        thread = threading.Thread(target=worker, name='fixture-capture', daemon=True)
        started = time.monotonic(); thread.start(); acted = False
        while thread.is_alive() and time.monotonic()-started < 3.5:
            if action and not acted and time.monotonic()-started >= .08:
                action(); acted = True
            self.pump(.005)
        thread.join(timeout=0)
        require(not thread.is_alive(), 'Capture caller did not return within fixture bound')
        box['elapsed_ms'] = round((time.monotonic()-started)*1000, 3)
        return box

    def positive(self, session, *, record=True):
        require(not self.u.IsWindowVisible(self.overlay_hwnd), 'Own overlay must be hidden before each CPU request')
        box = self.request(session)
        if 'error' in box:
            raise box['error']
        error = pixel_error(box['image'], self.rect, self.roi, self.window.colors)
        timing = dict(session.last_timing)
        transport = session._transport
        require(transport.process is not None and transport.process.poll() is None, 'Positive helper already exited')
        row = dict(timing, helper_pid=transport.process.pid, helper_created=self.session.process_metadata(transport.process.pid).created,
                   roi=list(self.roi), mean_channel_error=error, elapsed_ms=box['elapsed_ms'])
        if record:
            self.result['requests'].append(row)
        return row

    def retirement(self, session, label, started=None, *, timeout=3.5):
        started = time.monotonic() if started is None else started
        transport = session._transport
        require(transport is not None, 'Retirement needs an exact owned helper transport')
        exit_at = revoked_at = None
        while time.monotonic()-started < timeout:
            now = time.monotonic()
            if transport.revoked.is_set() and revoked_at is None: revoked_at = now
            if transport.process is not None and transport.process.poll() is not None and exit_at is None: exit_at = now
            if transport.ready_for_replacement.is_set(): break
            self.pump(.003)
        require(transport.ready_for_replacement.is_set(), 'Owned helper/pipe/Job cleanup did not finish: '+label)
        require(transport.process is not None and transport.process.poll() is not None, 'Exact helper is still alive')
        transport.worker.join(timeout=.3); transport.watchdog.join(timeout=.3)
        require(not transport.worker.is_alive() and not transport.watchdog.is_alive() and transport.stderr_done.is_set()
                and transport.io_done.is_set() and transport.job_closed and transport.job.handle is None,
                'A helper, reader, watchdog or Job handle leaked')
        require(all(stream.closed for stream in (transport.process.stdin, transport.process.stdout, transport.process.stderr)),
                'Owned pipe handle leaked')
        row = {'case': label, 'helper_pid': transport.process.pid, 'exit_code': transport.process.returncode,
               'revoked_ms': round(((revoked_at or time.monotonic())-started)*1000,3),
               'process_exit_ms': round(((exit_at or time.monotonic())-started)*1000,3),
               'cleanup_ms': round((time.monotonic()-started)*1000,3), 'job_closed':True,
               'io_done':True, 'stderr_done':True, 'threads_exited':True, 'pipes_closed':True}
        row['observed_exit_within_50ms'] = row['process_exit_ms'] <= 50
        self.result['transitions'].append(row)
        return row

    def finish(self, session, label='close'):
        started = time.monotonic(); session.close()
        elapsed = (time.monotonic()-started)*1000
        require(elapsed < 250, 'close() unexpectedly blocked the GUI caller')
        if session._transport is not None:
            row = self.retirement(session, label, started); row['close_call_ms'] = round(elapsed,3)

    def negative(self, session, field, *, statuses=('stale', 'invalid-reply'), **kwargs):
        started = time.monotonic(); box = self.request(session, **kwargs)
        error = box.get('error')
        require(isinstance(error, self.session.WgcError) and error.status in statuses and 'image' not in box,
                'Request did not fail closed with expected status: '+field)
        self.result['negative_results'][field] = {'status':error.status, 'elapsed_ms':box['elapsed_ms']}
        if getattr(error, 'diagnostic', None):
            self.result['negative_results'][field]['diagnostic'] = error.diagnostic
        if session._transport is not None:
            self.retirement(session, field, started)
        session.close(); self.result[field] = True

    def mutate_idle(self, field, mutate, restore=lambda: None, *, overlay=False):
        session = self.new_session(overlay=overlay); self.positive(session, record=False)
        started = time.monotonic()
        try:
            mutate(); row = self.retirement(session, field, started)
            require(row['exit_code'] == 12, 'Native idle guard did not reject stale identity: '+field)
            self.result[field] = True
        finally:
            session.close(); restore(); self.pump(.04)

    def close(self):
        if hasattr(self, 'timer'): self.timer.stop()
        failures=[]
        for session in self.sessions:
            try:
                if session._transport and not session._transport.ready_for_replacement.is_set(): self.finish(session, 'finally-close')
                else: session.close()
            except Exception as error: failures.append(str(error))
        handles=[]
        for window in self.windows:
            try:
                handles.append(int(window.winId())); window.close(); window.destroy()
            except RuntimeError: pass
        self.app.processEvents()
        reader_names={'wgc-session-pipe','wgc-session-lifetime','wgc-session-stderr','fixture-capture'}
        require(not any(thread.name in reader_names and thread.is_alive()for thread in threading.enumerate()),
                'An owned pipe reader/watchdog/capture thread survived final cleanup')
        self.result['helper_process_count']=sum(session._transport is not None for session in self.sessions)
        windows_closed=all(not self.u.IsWindow(hwnd) for hwnd in handles)
        self.u.SetThreadDpiAwarenessContext(self.old_dpi)
        require(not failures, '; '.join(failures))
        require(windows_closed, 'An owned diagnostic window survived cleanup')
        self.result.update(helpers_exited_passed=True, pipe_readers_exited_passed=True,
                           job_handles_closed_passed=True, windows_closed_passed=True)


def execute(result):
    f = Fixture(result)
    try:
        session = f.new_session(overlay=True)
        proof = json.loads(session.manifest_path.read_text(encoding='utf-8'))
        result['overlay_observations']=[]
        result['helper'] = {'manifest':proof, 'sha256':hashlib.sha256(session.helper_path.read_bytes()).hexdigest(),
                            'size':session.helper_path.stat().st_size}
        for number in range(4):
            f.window.colors = COLORS if number % 2 == 0 else tuple(reversed(COLORS))
            f.window.update(); f.pump(.04)
            f.positive(session)
            transport = session._transport
            f.pump(.15)
            require(not transport.revoked.is_set() and f.session._pipe_available(transport.process.stdout) == 0,
                    'Idle helper emitted unsolicited pixels or exited')
            if number == 1:
                before=int(f.u.GetWindowLongPtrW(f.overlay_hwnd,-20))&0xffffffff
                f.overlay.show(); f.pump(.25)
                affinity=W.DWORD();user=f.session._window_api()
                affinity_ok=bool(user.GetWindowDisplayAffinity(f.overlay_hwnd,ctypes.byref(affinity)))
                result['overlay_observations'].append({'stage':'shown-idle','before_style':before,
                    'after_style':int(f.u.GetWindowLongPtrW(f.overlay_hwnd,-20))&0xffffffff,
                    'affinity_query_ok':affinity_ok,'affinity':affinity.value})
                require(f.u.IsWindowVisible(f.overlay_hwnd) and not transport.revoked.is_set()
                        and transport.process.poll() is None and f.session._pipe_available(transport.process.stdout) == 0,
                        'Exact registered excluded overlay did not remain GPU-only idle')
                result['idle_overlay_passed']=True
                f.overlay.hide(); f.pump(.04)
        rows=result['requests']
        require(len({(r['helper_pid'],r['helper_created'],r['session_generation']) for r in rows}) == 1,
                'Repeated captures replaced the helper/session')
        require(all(a['request_id'] < b['request_id'] and a['frame_100ns'] < b['request_cutoff_100ns'] < b['frame_100ns']
                    for a,b in zip(rows,rows[1:])), 'A request reused stale pixels/timestamps/IDs')
        result.update(owned_pixels_passed=True, same_helper_session_passed=True, fresh_requests_passed=True,
                      identical_roi_passed=all(r['roi']==list(f.roi) for r in rows), idle_no_unsolicited_pixels_passed=True)
        f.overlay.show(); f.pump(.04)
        f.negative(session,'visible_overlay_request_rejected')
        f.overlay.hide(); f.window.colors=COLORS
        session=f.new_session(overlay=True);f.positive(session,record=False)
        old_overlay_pos=f.overlay.pos()
        # Move only our overlay so it no longer intersects the client. Visible
        # registered overlays are still forbidden for every strict CPU request.
        f.overlay.move(f.window.x()+f.window.width()+60,f.window.y())
        f.overlay.show();f.pump(.04)
        f.negative(session,'outside_overlay_request_rejected')
        f.overlay.hide();f.overlay.move(old_overlay_pos)

        # Other SAME-PROCESS windows never inherit the exact-overlay exception.
        cover=f.QtWidgets.QWidget(None,f.QtCore.Qt.Tool|f.QtCore.Qt.FramelessWindowHint|f.QtCore.Qt.WindowStaysOnTopHint|
                                  f.QtCore.Qt.WindowDoesNotAcceptFocus)
        cover.setAttribute(f.QtCore.Qt.WA_ShowWithoutActivating)
        cover.resize(70,60); cover.move(120,120); f.windows.append(cover)
        f.mutate_idle('other_same_process_occluder_rejected',cover.show,cover.hide)
        lookalike,lookalike_hwnd,lookalike_style=f.new_overlay(OPAQUE_PROFILE)
        result['overlay_rendering']['lookalike_occluder']=prepare_owned_overlay(
            lookalike,f.u,f.dwm,lookalike_hwnd,lookalike_style,
            os.getpid(),f.pump,result,label='lookalike-occluder')
        f.mutate_idle('layered_same_process_occluder_rejected',lookalike.show,lookalike.hide,overlay=True)
        other=f.QtWidgets.QWidget(); other.resize(120,80); other.move(700,30); f.windows.append(other)
        f.mutate_idle('focus_loss_rejected',lambda:f.focus(other),lambda:(other.hide(),f.focus(f.window)))
        old=f.window.pos()
        f.mutate_idle('geometry_change_rejected',lambda:f.window.move(old.x()+20,old.y()),lambda:f.window.move(old))
        f.focus(f.window); f.refresh_target()
        f.mutate_idle('target_hide_rejected',f.window.hide,lambda:f.focus(f.window))
        f.mutate_idle('overlay_style_rejected',
            lambda:f.u.SetWindowLongPtrW(f.overlay_hwnd,-20,f.overlay_style&~0x20),
            lambda:f.u.SetWindowLongPtrW(f.overlay_hwnd,-20,f.overlay_style),overlay=True)
        f.mutate_idle('overlay_affinity_rejected',lambda:f.u.SetWindowDisplayAffinity(f.overlay_hwnd,0),
                      lambda:f.u.SetWindowDisplayAffinity(f.overlay_hwnd,0x11),overlay=True)
        session=f.new_session(overlay=True);f.positive(session,record=False)
        name=f.session._property_name(session._overlay[2]);started=time.monotonic()
        require(f.u.RemovePropW(f.overlay_hwnd,name),'Could not remove exact own overlay registration')
        f.retirement(session,'overlay_registration_rejected',started);session.close()
        result['overlay_registration_rejected']=True

        session=f.new_session();f.positive(session,record=False)
        metadata=f.session.process_metadata(f.target.pid)
        f.negative(session,'process_identity_rejected',expected_metadata=replace(metadata,created=metadata.created+1))
        session=f.new_session();f.positive(session,record=False)
        other_target=f.capture.info(int(other.winId()))
        f.negative(session,'hwnd_retarget_rejected',target=other_target)
        session=f.new_session()
        f.negative(session,'cancel_before_launch_passed',cancelled=lambda:True,statuses=('cancelled',))
        require(session._transport is None,'Pre-cancelled capture created a helper')

        # Malformed native requests are sent only to our exact owned helper.
        original=f.session.encode_request
        for field,mutator in (
            ('native_roi_rejected',lambda values:values.__setitem__(7,f.rect.width+1)),
            ('native_generation_rejected',lambda values:values.__setitem__(4,values[4]+1))):
            session=f.new_session()
            def bad_request(*args,_mutator=mutator,**kwargs):
                values=list(f.session.REQUEST.unpack(original(*args,**kwargs)));_mutator(values)
                return f.session.REQUEST.pack(*values)
            with patch.object(f.session,'encode_request',bad_request):
                f.negative(session,field,statuses=('stale','backend-error','invalid-reply'))
        session=f.new_session();f.positive(session,record=False);session._request_id-=1
        f.negative(session,'native_duplicate_id_rejected',statuses=('backend-error','invalid-reply'))
        session=f.new_session()
        with patch.object(f.session,'encode_request',lambda *a,**k:original(*a,**k)*2):
            f.negative(session,'native_pipeline_rejected',statuses=('backend-error','invalid-reply'))

        session=f.new_session();f.positive(session,record=False)
        started=time.monotonic();session.stop()
        stop_elapsed=(time.monotonic()-started)*1000
        require(stop_elapsed<250,'stop() unexpectedly blocked the GUI caller')
        row=f.retirement(session,'stop',started);row['close_call_ms']=round(stop_elapsed,3)
        result['stop_passed']=True
        for field,action in (
            ('native_stop_passed',lambda s:s._transport.process.stdin.write(original(
                s._request_id+1,s._transport.generation,(0,0,0,0),stop=True))),
            ('pipe_eof_passed',lambda s:s._transport.process.stdin.close()),
            ('job_close_passed',lambda s:s._transport.job.close())):
            session=f.new_session();f.positive(session,record=False);started=time.monotonic();action(session)
            row=f.retirement(session,field,started)
            if field in ('native_stop_passed','pipe_eof_passed'):
                require(row['exit_code']==0,'Native stop/EOF was not graceful')
            session.close();result[field]=True
        session=f.new_session();f.positive(session,record=False);started=time.monotonic()
        row=f.retirement(session,'idle_lease_passed',started,timeout=5.5)
        require(3000 <= row['process_exit_ms'] <= 5500,'Four-second idle lease was not bounded as expected')
        session.close();result['idle_lease_passed']=True

        # Suspension is a controlled test-only stalled helper; native capture
        # never starts. Independent parent cancellation/deadline must still reap it.
        popen=f.session.subprocess.Popen
        def suspended(*args,**kwargs):
            kwargs['creationflags']=kwargs.get('creationflags',0)|0x4
            return popen(*args,**kwargs)
        for field,cancel in (('cancel_during_wait_passed',True),('request_deadline_passed',False)):
            session=f.new_session();event=threading.Event()
            with patch.object(f.session.subprocess,'Popen',suspended):
                f.negative(session,field,cancelled=event,action=event.set if cancel else None,
                           statuses=('cancelled',) if cancel else ('timeout',))
        verify_suspended_job_close(f,result)
        # No repaints or off-ROI animation: this separately exercises truly
        # static-window freshness. A bounded timeout is fail-closed, but does
        # NOT pass this usability/enablement gate. Continue lifecycle checks so
        # a static-frame failure does not erase their evidence.
        result['static_requests']=[]
        static_session=f.new_session()
        f.timer.stop();f.window.update();f.pump(.05)
        try:
            for _ in range(3):
                result['static_requests'].append(f.positive(static_session,record=False))
                f.pump(.12)
            result['static_frame_requests_passed']=True
        except f.session.WgcError as error:
            result['static_frame_requests_passed']=False
            result['static_frame_failure']={'status':error.status,'message':str(error)[:300]}
        finally:
            f.finish(static_session,'static-close');f.timer.start(25)
        # Destroying the exact registered HWND cannot resurrect its token.
        session=f.new_session(overlay=True);f.positive(session,record=False);started=time.monotonic()
        f.overlay.destroy();f.retirement(session,'overlay_destroy_rejected',started);session.close()
        result['overlay_destroy_rejected']=True
        session=f.new_session();f.positive(session,record=False);started=time.monotonic()
        window=f.window;f.window=None;window.destroy()
        f.retirement(session,'target_destroy_rejected',started);session.close();result['target_destroy_rejected']=True
        verify_parent_death(f,result)
    finally:
        f.close()


def job_owner(report_path):
    """Internal isolated child mode: create its OWN target then await parent kill."""
    result={};f=None
    try:
        f=Fixture(result);s=f.new_session();f.positive(s,record=False)
        process=s._transport.process
        write_report(report_path,{'schema_version':1,'status':'ready','owner_pid':os.getpid(),
            'owner_created':f.session.process_metadata(os.getpid()).created,
            'helper_pid':process.pid,'helper_created':f.session.process_metadata(process.pid).created,
            'helper_sha256':hashlib.sha256(s.helper_path.read_bytes()).hexdigest()})
        # Keep lease alive only for this bounded diagnostic. Parent should kill
        # the exact owner well before its next lease expires.
        end=time.monotonic()+12
        while time.monotonic()<end:
            f.pump(.15)
            if s._transport.revoked.is_set(): break
            if time.monotonic()+2>s._transport.idle_deadline: f.positive(s,record=False)
        return 1
    finally:
        if f: f.close()


def verify_suspended_job_close(f,result):
    """Only kernel Job termination can stop this never-resumed own helper."""
    session=f.new_session();f.positive(session,record=False)
    args=list(session._transport.args);f.finish(session,'suspended-job-prepare')
    job=f.session._CaptureJob();process=None
    try:
        process=subprocess.Popen(args,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
            shell=False,bufsize=0,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)|0x4)
        job.assign(process)
        require(process.poll()is None,'Suspended exact helper exited before Job-close observation')
        kernel=job.kernel
        kernel.WaitForSingleObject.argtypes=[W.HANDLE,W.DWORD];kernel.WaitForSingleObject.restype=W.DWORD
        started=time.monotonic()
        require(job.close()and job.handle is None,'Owned Job handle did not close')
        wait=kernel.WaitForSingleObject(int(process._handle),3500)
        elapsed=round((time.monotonic()-started)*1000,3)
        require(wait==0,'Kernel Job close did not signal the never-resumed helper')
        code=process.wait(timeout=0)
        result['suspended_job_close_observation']={'wait_result':wait,'elapsed_ms':elapsed,
            'helper_pid':process.pid,'exit_code':code,'job_closed':True,'never_resumed':True,
            'start_gate_released':False}
        result['suspended_job_close_passed']=True
    finally:
        job.close()
        if process is not None:
            if process.poll()is None:process.kill()
            process.wait(timeout=5)
            for stream in (process.stdin,process.stdout,process.stderr):stream.close()


def verify_parent_death(f,result):
    import tempfile
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    for name,args,ret in (
        ('OpenProcess',[W.DWORD,W.BOOL,W.DWORD],W.HANDLE),
        ('WaitForSingleObject',[W.HANDLE,W.DWORD],W.DWORD),
        ('TerminateProcess',[W.HANDLE,W.UINT],W.BOOL),
        ('CloseHandle',[W.HANDLE],W.BOOL),
        ('GetProcessTimes',[W.HANDLE,ctypes.POINTER(W.FILETIME),ctypes.POINTER(W.FILETIME),ctypes.POINTER(W.FILETIME),ctypes.POINTER(W.FILETIME)],W.BOOL)):
        fn=getattr(kernel,name);fn.argtypes=args;fn.restype=ret
    class ProcessEntry(ctypes.Structure):
        _fields_=[('dwSize',W.DWORD),('cntUsage',W.DWORD),('th32ProcessID',W.DWORD),
                  ('th32DefaultHeapID',ctypes.c_size_t),('th32ModuleID',W.DWORD),('cntThreads',W.DWORD),
                  ('th32ParentProcessID',W.DWORD),('pcPriClassBase',W.LONG),('dwFlags',W.DWORD),
                  ('szExeFile',W.WCHAR*260)]
    kernel.CreateToolhelp32Snapshot.argtypes=[W.DWORD,W.DWORD];kernel.CreateToolhelp32Snapshot.restype=W.HANDLE
    for name in ('Process32FirstW','Process32NextW'):
        fn=getattr(kernel,name);fn.argtypes=[W.HANDLE,ctypes.POINTER(ProcessEntry)];fn.restype=W.BOOL
    def parent_pid(pid):
        snapshot=kernel.CreateToolhelp32Snapshot(2,0)
        require(snapshot not in (None,ctypes.c_void_p(-1).value),'Cannot inspect owned process ancestry')
        try:
            entry=ProcessEntry();entry.dwSize=ctypes.sizeof(entry)
            found=kernel.Process32FirstW(snapshot,ctypes.byref(entry))
            while found:
                if entry.th32ProcessID==pid:return int(entry.th32ParentProcessID)
                found=kernel.Process32NextW(snapshot,ctypes.byref(entry))
            raise AssertionError('Exact live owned process missing from ancestry snapshot')
        finally:kernel.CloseHandle(snapshot)
    with tempfile.TemporaryDirectory(prefix='vga-session-parent-') as directory:
        report=Path(directory)/'owner.json'
        command=([sys.executable] if getattr(sys,'frozen',False) else
                 [sys.executable,str(Path(__file__).with_name('wgc_session_diagnostic.py'))])
        env=dict(os.environ,PYINSTALLER_RESET_ENVIRONMENT='1')
        process=subprocess.Popen(command+['--job-owner-report',str(report)],env=env,
                                 stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        helper_handle=owner_handle=None
        owner_verified=False
        def created_from_handle(handle):
            values=[W.FILETIME()for _ in range(4)]
            require(kernel.GetProcessTimes(handle,*(ctypes.byref(item)for item in values)),
                    'Cannot bind exact process-handle creation time')
            return (int(values[0].dwHighDateTime)<<32)|int(values[0].dwLowDateTime)
        try:
            end=time.monotonic()+12
            while not report.is_file() and process.poll() is None and time.monotonic()<end: f.pump(.02)
            require(report.is_file() and report.stat().st_size<=4096,'Owned parent-death fixture did not become ready')
            owner=json.loads(report.read_text(encoding='utf-8'))
            require(owner.get('status')=='ready' and owner.get('helper_sha256')==result['helper']['sha256'],
                    'Parent-death fixture helper identity changed')
            # Onefile bootloader PID differs from the actual owner. Confirm its
            # image identity against this exact fixture before terminating it.
            owner_pid=owner.get('owner_pid');helper_pid=owner.get('helper_pid')
            require(type(owner_pid)is int and type(helper_pid)is int and owner_pid!=os.getpid(), 'Invalid owned process identities')
            own_meta=f.session.process_metadata(os.getpid());owner_meta=f.session.process_metadata(owner_pid)
            require(owner_meta.path==own_meta.path and owner_meta.created==owner.get('owner_created')
                    and owner_meta.created>=own_meta.created,
                    'Refuse to terminate a process outside this launched fixture identity')
            require(f.session.process_metadata(helper_pid).created==owner['helper_created'],'Helper PID reused')
            # Helper handle is SYNCHRONIZE + metadata only. Never terminate an
            # arbitrary process by a report PID. The owner is this launched child.
            helper_handle=kernel.OpenProcess(0x100000|0x1000,False,helper_pid)
            owner_handle=kernel.OpenProcess(0x1|0x1000|0x100000,False,owner_pid)
            require(helper_handle and owner_handle,'Cannot observe exact owned parent/child lifetime')
            require(created_from_handle(owner_handle)==owner['owner_created'],
                    'Owner PID changed before exact handle binding; refuse termination')
            require(created_from_handle(helper_handle)==owner['helper_created'],
                    'Helper PID changed before exact lifetime handle binding')
            bootloader_created=created_from_handle(int(process._handle))
            require(process.poll()is None and kernel.WaitForSingleObject(owner_handle,0)==258
                    and kernel.WaitForSingleObject(helper_handle,0)==258,
                    'Owned ancestry cannot be bound after a process exited')
            if getattr(sys,'frozen',False):
                require(owner_pid!=process.pid and parent_pid(owner_pid)==process.pid
                        and owner['owner_created']>=bootloader_created,
                        'Frozen owner is not the live child of this exact Popen bootloader')
            else:
                require(owner_pid==process.pid and owner['owner_created']==bootloader_created,
                        'Source owner differs from the exact Popen child')
            require(parent_pid(helper_pid)==owner_pid and owner['helper_created']>=owner['owner_created'],
                    'Helper is not the exact owner child')
            # Holding these live creation-bound handles prevents PID reuse from
            # changing the process objects selected for termination/observation.
            require(kernel.WaitForSingleObject(owner_handle,0)==258
                    and kernel.WaitForSingleObject(helper_handle,0)==258 and process.poll()is None,
                    'Owned ancestry changed before termination')
            owner_verified=True
            started=time.monotonic()
            require(kernel.TerminateProcess(owner_handle,77),'Could not terminate owned diagnostic parent')
            wait=kernel.WaitForSingleObject(helper_handle,3500)
            elapsed=round((time.monotonic()-started)*1000,3)
            require(wait==0,'Parent death did not signal exact helper process')
            process.wait(timeout=5)
            result['parent_death_observation']={'wait_result':wait,'elapsed_ms':elapsed,
                'owner_pid':owner_pid,'owner_created':owner['owner_created'],'helper_pid':helper_pid,'helper_created':owner['helper_created'],
                'exact_handle_observed':True,'helper_sha256':owner['helper_sha256'],
                'owner_ancestry_verified':True,'helper_ancestry_verified':True,
                'popen_pid':process.pid,'popen_created':bootloader_created,
                'scope':'parent-death-eventual-cleanup'}
            result['parent_death_passed']=True
        finally:
            try:
                if owner_verified and owner_handle:
                    kernel.TerminateProcess(owner_handle,77)
                if process.poll()is None:
                    # The launched onefile bootloader can own an extraction child.
                    # Bound cleanup to that exact Popen-owned process tree.
                    try:
                        subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True,timeout=20)
                    finally:
                        if process.poll()is None:process.kill()
                        process.wait(timeout=5)
            finally:
                if owner_handle: kernel.CloseHandle(owner_handle)
                if helper_handle: kernel.CloseHandle(helper_handle)


def run(report_path):
    result={'schema_version':1,'status':'failed','applicationVersion':__version__,
            'frozen':bool(getattr(sys,'frozen',False)),'scope':SCOPE,'limitations':dict(LIMITATIONS)}
    code=1
    try:
        execute(result)
        require(all(result.get(field)is True for field in CHECK_FIELDS),'Session evidence is incomplete')
        result['status']='passed';code=0
    except Exception as error:
        result.update(error_type=type(error).__name__,error=str(error)[:2000])
        diagnostic=getattr(error,'diagnostic',None)
        if diagnostic: result['native_diagnostic']=diagnostic
    finally:
        write_report(report_path,result)
    return code

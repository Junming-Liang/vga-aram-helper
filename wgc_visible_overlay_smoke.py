"""Explicit Windows ordinary-default product-overlay acceptance diagnostic.

Only original self-owned artwork is captured. This module is never imported by
normal startup. The external runner owns the one foreign-PID occluder in its
existing suspended-launch NativeJob; no arbitrary capture HWND is accepted.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes as W
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import threading
import time

from app_version import __version__
from wgc_session_smoke import Fixture, LIMITATIONS as SESSION_LIMITATIONS, require, write_report
from owned_diagnostic_json import poll_owned_json

SCALES = (1, 1.5, 2)
MAX_REPORT_BYTES = 256 * 1024
SAMPLE_FORMAT = '[offset_us, qt_visible*2+native_visible]'
SCOPE = ('Explicit ordinary-default real ControlWindow/Overlay and Win32Capture visible-owned-overlay '
         'diagnostic; original owned synthetic windows only. Not live-game, exclusive-fullscreen, '
         'Vanguard, general HWND exclusion, zero idle CPU readback, or general production compatibility proof.')
LIMITATIONS = dict(SESSION_LIMITATIONS, production_enabled=True)
NEGATIVES = ('same_pid_occluder', 'foreign_pid_occluder', 'wrong_hwnd', 'replaced_hwnd_token',
             'owner_change', 'token_change', 'extended_style_change', 'window_style_change',
             'affinity_change', 'opacity_change', 'protected_target', 'focus_loss',
             'geometry_loss', 'active_affinity_change', 'cancel', 'stop')
# Exact native idle-denial contract from native/wgc_session_capture.cpp. Target
# protection is protected_content (13); ordinary invalidation is stale (12).
# Product/in-flight lifecycle cases deliberately do not claim an idle exit code.
NATIVE_NEGATIVE_EXIT_CODES = {
    'same_pid_occluder': 12, 'foreign_pid_occluder': 12, 'replaced_hwnd_token': 12,
    'token_change': 12, 'extended_style_change': 12, 'window_style_change': 12,
    'affinity_change': 12, 'opacity_change': 12, 'protected_target': 13,
    'focus_loss': 12, 'geometry_loss': 12,
}
SOURCE_FILES = ('latest_capture_frame.py', 'wgc_visible_overlay_smoke.py', 'tests/windows_wgc_visible_overlay.py',
                'tests/test_wgc_visible_overlay_smoke.py', 'tests/test_card_badges.py', 'owned_diagnostic_json.py', 'launcher.py', 'native_ui.py',
                'native_smoke.py', 'screen_capture.py', 'persistent_capture_adapter.py',
                'card_badges.py', 'badge_contract.py', 'augment_card_geometry.py',
                'hero_identity_continuity.py', 'monitor_preferences.py', 'card_title_proof.py', 'source_combo_hints.py',
                'portrait_display.py', 'local_debug.py', 'selection_session.py',
                'wgc_session_capture.py', 'native/wgc_session_capture.cpp',
                'wgc_session_smoke.py', 'tests/windows_session_fixture.py',
                'tests/SessionWindowFixture.cs', 'tests/windows_ota_smoke.py')


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def report_payload(value):
    """Lossless compact JSON keeps all acquisition/sample evidence in the old cap."""
    payload=json.dumps(value,separators=(',',':'))+'\n'
    require(len(payload.encode('utf-8'))<=MAX_REPORT_BYTES,'Diagnostic report exceeded existing metadata budget')
    return payload


def read_live_json(path):
    """Strict bounded reader; only the shared poller handles transient OS errors."""
    path=Path(path)
    if path.is_symlink() or path.stat().st_size>8192:raise ValueError('Owned handshake exceeds metadata bound')
    def unique(pairs):
        result={}
        for key,value in pairs:
            if key in result:raise ValueError('Duplicate owned handshake key')
            result[key]=value
        return result
    def invalid(_):raise ValueError('Non-finite owned handshake constant')
    return json.loads(path.read_text(encoding='utf-8'),object_pairs_hook=unique,parse_constant=invalid)


def pixels(png):
    from PIL import Image
    return Image.open(io.BytesIO(png)).convert('RGB')


def compare_pixels(reference, captured):
    """Exact deterministic-state proof; no animated frames compared as equal."""
    import numpy as np
    before, after = (np.asarray(pixels(value)) for value in (reference, captured))
    require(before.shape == after.shape, 'Hidden/visible physical image dimensions differ')
    # Hash the canonical RGB8 pixels used by observed_capture. Widen only the
    # subtraction so signed channel deltas cannot wrap in the uint8 arrays.
    delta = np.abs(before.astype(np.int16) - after.astype(np.int16))
    magenta = lambda value: int(np.count_nonzero(np.all(value == (255, 0, 255), axis=2)))
    return dict(mean_channel_error=float(delta.mean()), max_channel_error=int(delta.max()),
                changed_pixels=int(np.count_nonzero(np.any(delta, axis=2))),
                hidden_magenta_pixels=magenta(before), visible_magenta_pixels=magenta(after),
                hidden_sha256=hashlib.sha256(before.tobytes()).hexdigest(),
                visible_sha256=hashlib.sha256(after.tobytes()).hexdigest())


def install_badge_sentinels(overlay):
    """Diagnostic-only child patches; preserve actual painter, mask and HWND.

    The legacy reference panel is hidden in card mode. Each patch stays inside
    one visible product badge and never creates a native/top-level window.
    """
    from PySide6 import QtCore, QtGui, QtWidgets
    from card_badges import native_region
    require(overlay.isVisible() and not overlay.panel.isVisible(), 'Product is not in visible badge mode')
    badges = overlay._badge_widgets
    require(len(badges) == 3 and len(overlay._badge_regions) == 3
            and all(badge.isVisible() for badge in badges), 'Three actual product badges are required')
    hwnd=int(overlay.winId());mask=overlay.mask()
    native_region(hwnd, overlay._badge_regions, verify_only=True)
    class SentinelPatch(QtWidgets.QWidget):
        def paintEvent(self, event):
            painter=QtGui.QPainter(self)
            painter.fillRect(self.rect(),QtGui.QColor(255,0,255))
            painter.end()
    patches = []
    for badge in badges:
        patch = SentinelPatch(badge)
        patch.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        patch.setAttribute(QtCore.Qt.WidgetAttribute.WA_OpaquePaintEvent)
        patch.setObjectName('owned-capture-sentinel')
        patch.setGeometry(12, badge.height()-18, badge.width()-24, 12)
        require(badge.rect().contains(patch.geometry()) and not patch.isWindow(), 'Sentinel escaped its badge')
        patch.show();patch.raise_();patches.append(patch)
    overlay._diagnostic_sentinels = patches
    require(int(overlay.winId())==hwnd and overlay.mask()==mask
            and all(not patch.testAttribute(QtCore.Qt.WidgetAttribute.WA_NativeWindow) for patch in patches),
            'Sentinel changed actual HWND or native ownership')
    native_region(hwnd, overlay._badge_regions, verify_only=True)
    return patches


def badge_sentinel_observation(overlay):
    from card_badges import native_region
    native_region(int(overlay.winId()), overlay._badge_regions, verify_only=True)
    require(all(patch.isVisible() and not patch.isWindow() for patch in overlay._diagnostic_sentinels),
            'Sentinel child visibility changed')
    counts=[]
    for badge in overlay._badge_widgets:
        image=badge.grab().toImage()
        counts.append(sum(image.pixelColor(x,y).getRgb()==(255,0,255,255)
                          for x in range(0,image.width(),8) for y in range(0,image.height(),8)))
    require(len(counts)==3 and all(count>0 for count in counts), 'A product badge lacks its visible sentinel')
    return dict(badge_magenta_grid_samples=counts, badge_native_region_verified=True)


def strict_timing(row):
    keys = ('helper_pid', 'helper_created', 'session_generation', 'request_id',
            'capture_start_100ns', 'request_cutoff_100ns', 'frame_100ns',
            'idle_enter_100ns', 'capture_return_100ns')
    return (all(type(row.get(key)) is int and 0 < row[key] < 2**63 for key in keys)
            and row['capture_start_100ns'] <= row['request_cutoff_100ns'] < row['frame_100ns']
            <= row['idle_enter_100ns'] <= row['capture_return_100ns'])


class ProductFixture(Fixture):
    """Reuse the reviewed fixture deadline, Qt pump, helper and Job retirement."""
    def __init__(self, result, report_path):
        self.report_path = Path(report_path)
        self.records = []
        self.owners = []
        self.active = None
        self.event_rows = []
        self.fallback_calls = []
        self.pending_action = None
        self.bridge_results = []
        self._cycle_serial = None
        super().__init__(result)

    def initialize_windows(self, result):
        from PySide6 import QtCore, QtGui, QtWidgets
        from native_ui import ControlWindow, Overlay
        from native_smoke import smoke_dimensions, smoke_pixmap
        from synthetic_vision import portraits, configure_data
        from hero_recognition import PortraitMatcher
        from local_ocr import LocalOCR
        from server import load_startup_data
        from session_windows import process_metadata
        from screen_capture import Win32Capture

        self.app.setQuitOnLastWindowClosed(False)
        state = Path(os.environ.get('VGA_STATE_DIR', self.report_path.parent / 'visible-state'))
        self.control = ControlWindow(lambda: load_startup_data(state / 'data', demo=True),
            state_dir=state, current_executable=sys.executable, current_version=__version__,
            frozen=bool(getattr(sys, 'frozen', False)), enable_updates=False)
        require(self.control.enable_visible_capture is True,
                'Ordinary ControlWindow construction did not enable guarded visible capture')
        self.windows.extend((self.control, self.control.overlay))
        self.use_explicit_capture_cadence()
        self.control.signals.result.connect(self.observe_product_result)
        self.wait(lambda: self.control.data is not None, 10, 'Synthetic product startup did not finish')
        self.control.hide()
        self.capture.close()
        self.capture = self.control.capture
        require(type(self.capture) is Win32Capture and type(self.control.overlay) is Overlay,
                'Diagnostic must use concrete product capture and Overlay classes')
        self.overlay = self.control.overlay
        self.overlay_hwnd = int(self.overlay.winId())
        self.overlay_style = int(self.capture.get_long(self.overlay_hwnd, -20)) & 0xffffffff
        self.overlay.hide(); self.overlay.configure()
        self.bank = portraits(); configure_data(self.control.data)
        self.control.hero_matcher = PortraitMatcher(self.bank, self.control.data['heroes'])
        self.control.ocr = LocalOCR()
        # Warm actual models before the cold capture/confirmation timeline.
        self.control.ocr.recognize((Path(__file__).parent / 'fixtures/ocr-blank.png').read_bytes(),
                                   tuple(self.control.data['augments']))
        self.u.SystemParametersInfoW.argtypes = [W.UINT, W.UINT, W.LPVOID, W.UINT]
        self.u.SystemParametersInfoW.restype = W.BOOL
        area = W.RECT()
        require(self.u.SystemParametersInfoW(0x30, 0, ctypes.byref(area), 0), 'Work area unavailable')
        width, height = smoke_dimensions(area.right-area.left, area.bottom-area.top)
        self.window = QtWidgets.QWidget(None, QtCore.Qt.Window | QtCore.Qt.FramelessWindowHint)
        self.windows.append(self.window)
        self.window.setWindowTitle('VGA owned visible-overlay deterministic target')
        self.window.winId()
        dpr = self.window.devicePixelRatioF()
        self.window.resize(round(width/dpr), round(height/dpr))
        layout = QtWidgets.QVBoxLayout(self.window); layout.setContentsMargins(0, 0, 0, 0)
        self.label = QtWidgets.QLabel(); layout.addWidget(self.label)
        self.window.show()
        require(self.u.SetWindowPos(int(self.window.winId()), None, area.left+20, area.top+20,
                                   width, height, 0x0004 | 0x0040), 'Cannot place owned physical target')
        self.artwork = [smoke_pixmap(self.bank['9001'], Path(__file__).parent / 'fixtures/auto-scene.png',
                                    width, height, dpr, changed_roi=changed) for changed in (False, True)]
        self.paint(0); self.focus(self.window); self.refresh_target()
        self.roi = (0, 0, self.rect.width, self.rect.height)
        require((self.rect.width, self.rect.height) == (960, 600), 'Physical fixture size changed')
        scale = float(os.environ.get('QT_SCALE_FACTOR', '1'))
        require(scale in SCALES and abs(scale-dpr) < .01, 'Requested/measured Qt scale differs')
        self.control.target = self.target
        self.control.manual_identity = self.target.identity
        self.control.manual_metadata = process_metadata(self.target.pid)
        self.control.state.start(self.target.identity); self.control.state.clear_hero()
        self.control.ocr_reuse.clear()
        result.update(requested_app_scale=scale, measured_qt_scale=dpr,
            client_rect=vars(self.rect), target_identity=list(self.target.identity),
            target_created=process_metadata(self.target.pid).created,
            overlay_hwnd=self.overlay_hwnd, control_hwnd=int(self.control.winId()),
            constructor='ControlWindow()', visible_capture_enabled=self.control.enable_visible_capture,
            pattern='Two deterministic paint states; static between explicit changes; no animation timer',
            transitions=[], negative_results={}, requests=self.records)
        parent = self
        class Events(QtCore.QObject):
            def eventFilter(self, obj, event):
                if event.type() in (QtCore.QEvent.Show, QtCore.QEvent.Hide):
                    require(len(parent.event_rows) < 512, 'Overlay event evidence exceeded bound')
                    parent.event_rows.append(dict(event='show' if event.type() == QtCore.QEvent.Show else 'hide',
                        at=time.perf_counter(), during_capture=parent.active is not None))
                return False
        self.events = Events(self.overlay); self.overlay.installEventFilter(self.events)
        self.title_check_events=[]
        original_title_check=self.overlay.set_title_checking
        def observe_title_check(value):
            before=self.overlay._titles_pending
            original_title_check(value)
            if before!=self.overlay._titles_pending:
                require(len(self.title_check_events)<256,'Title checking transition budget exceeded')
                self.title_check_events.append(bool(self.overlay._titles_pending))
        self.overlay.set_title_checking=observe_title_check
        self.real_capture = self.capture.capture
        self.capture.capture = self.observed_capture
        # Observe, rather than replace, actual legacy routes. A denial that
        # accidentally reaches either route is a test failure even if it raises.
        if self.capture._wgc is not None:
            self.real_v1 = self.capture._wgc.capture
            def v1(*args, **kwargs):
                self.fallback_calls.append('v1'); return self.real_v1(*args, **kwargs)
            self.capture._wgc.capture = v1
        self.real_gdi = self.capture._copy_pixels
        def gdi(*args, **kwargs):
            self.fallback_calls.append('gdi'); return self.real_gdi(*args, **kwargs)
        self.capture._copy_pixels = gdi

    def wait(self, predicate, seconds, message):
        until = min(self.end, time.monotonic()+seconds)
        while not predicate():
            require(time.monotonic() < until, message)
            self.pump(.003)

    def use_explicit_capture_cadence(self):
        """Step product cycles explicitly, including across queued Qt events.

        Result handlers may restart the monitor during processEvents(). Merely
        stopping it afterwards lets a due timeout capture the previous paint
        state before the fixture asks for its next independently observed frame.
        Keep the real capture method and its one-shot acquisition callbacks.
        """
        self.control.watchdog.stop(); self.control.monitor.stop()
        self.control.monitor.timeout.disconnect(self.control.capture_tick)

    def observe_product_result(self, kind, value, generation):
        """Copy bounded final bridge metadata without replacing its real handler."""
        if kind == 'ocr' and isinstance(value, dict):
            self.bridge_results.append(dict(generation=generation,
                serial=value.get('_captureSerial'), captured_at=value.get('_capturedAt'),
                window_identity=value.get('_windowIdentity')))

    def drain_product_capture(self, *, clear_latest=False):
        """Keep every completed acquisition, then discard only an idle pixel slot."""
        latest = self.control.latest_capture
        self.wait(lambda: not self.control.ocr_busy and not self.control.capture_pending
                  and not latest.busy, 8, 'Product primary/background acquisition did not drain')
        with latest._condition:
            require(latest._failure is None, 'Background acquisition failed before the fixture boundary')
        if clear_latest:latest.clear()
        with latest._condition:return latest._epoch

    def pump(self, seconds=.03):
        end = min(self.end, time.monotonic()+seconds)
        while time.monotonic() < end:
            require(time.monotonic() < self.end, 'Owned fixture exceeded existing 150-second deadline')
            self.app.processEvents()
            if hasattr(self, 'control'):
                self.control.monitor.stop(); self.control.watchdog.stop()
            row = self.active
            if row is not None:
                require(len(row['_samples']) < 2000, 'Capture visibility sample budget exceeded')
                row['_samples'].append((time.perf_counter(), bool(self.overlay.isVisible()),
                                       bool(self.u.IsWindowVisible(self.overlay_hwnd))))
                owner = self.capture._persistent._owner
                transport = getattr(getattr(owner, 'session', None), '_transport', None)
                exchange = getattr(transport, '_active', None)
                if self.pending_action is not None and exchange is not None and not exchange.done.is_set():
                    action, self.pending_action = self.pending_action, None
                    from wgc_session_capture import _qpc_100ns
                    row['mutation_100ns'] = _qpc_100ns()
                    row['pending_exchange_request_id'] = exchange.request_id
                    action()
            time.sleep(.001)

    def paint(self, state):
        self.label.setPixmap(self.artwork[state]); self.paint_state = state
        self.window.update(); self.pump(.03)

    def observed_capture(self, *args, **kwargs):
        from native_smoke import _duty_session_observation, _duty_process_created
        from wgc_session_capture import _qpc_100ns
        latest = self.control.latest_capture
        with latest._condition:
            producer = threading.current_thread() is latest._thread
            producer_epoch = latest._epoch
        require(self.active is None, 'Native acquisition lanes overlapped')
        row = dict(visible_request=kwargs.get('allow_visible_overlay', False), paint_state=self.paint_state,
                   capture_start_100ns=_qpc_100ns(), _samples=[], _started=time.perf_counter(),
                   capture_started_at=time.monotonic(), producer_epoch=producer_epoch,
                   acquisition_role='background' if producer else 'primary' if self._cycle_serial is not None else 'direct',
                   product_serial=self.control._capture_serial, product_generation=self.control.state.generation,
                   native_visible_before=bool(self.u.IsWindowVisible(self.overlay_hwnd)))
        owner_at_entry=self.capture._persistent._owner
        transport_at_entry=getattr(getattr(owner_at_entry,'session',None),'_transport',None)
        if transport_at_entry is not None and transport_at_entry.process is not None:
            row.update(helper_pid=transport_at_entry.process.pid,
                helper_created=_duty_process_created(transport_at_entry.process),
                session_generation=transport_at_entry.generation)
        self.active = row
        try:
            value = self.real_capture(*args, **kwargs)
            row['capture_return_100ns'] = _qpc_100ns()
            row['capture_returned_at'] = time.monotonic()
            row['_return_at'] = time.perf_counter()
            receipt = dict(self.capture.last_session_receipt or {})
            require(receipt, 'Actual product capture returned no persistent native receipt')
            owner, transport, observation = _duty_session_observation(self.capture, receipt,
                                                                     hidden=not row['visible_request'])
            owner_pid=W.DWORD()
            require(self.u.GetWindowThreadProcessId(self.overlay_hwnd,ctypes.byref(owner_pid))
                    and owner_pid.value==os.getpid(), 'Exact product overlay owner changed')
            if owner not in self.owners:
                self.owners.append(owner); self.sessions.append(owner.session)
            row.update(receipt, observation=observation, backend=self.capture.last_backend,
                       native_visible_after=bool(self.u.IsWindowVisible(self.overlay_hwnd)),
                       overlay_window_style=int(self.capture.get_long(self.overlay_hwnd, -16)) & 0xffffffff,
                       enrolled_window_style=owner.session._overlay_window_style,
                       parent_pid=os.getpid(), overlay_owner_pid=owner_pid.value, status='passed',
                       pixels_sha256=hashlib.sha256(pixels(value[0]).tobytes()).hexdigest())
            require(strict_timing(row), 'Native cutoff/frame/idle timestamps escaped actual acquisition')
            row['_png'] = value[0]
            return value
        except BaseException as error:
            row['capture_return_100ns']=_qpc_100ns();row['_return_at']=time.perf_counter()
            row.update(status='rejected', error_type=type(error).__name__, error=str(error)[:500])
            raise
        finally:
            self.active = None
            started=row.pop('_started');returned=row.pop('_return_at',time.perf_counter())
            row['elapsed_ms'] = round((returned-started)*1000, 3)
            samples = [item for item in row.pop('_samples') if item[0]<=returned]
            offsets=[[round((stamp-started)*1_000_000),int(qt)*2+int(native)] for stamp,qt,native in samples]
            duration=round((returned-started)*1_000_000)
            edges=[0,*[item[0] for item in offsets],duration]
            row['visibility'] = dict(samples=len(samples),
                qt_hidden_samples=sum(not item[1] for item in samples),
                native_hidden_samples=sum(not item[2] for item in samples),
                duration_us=duration,samples_us=offsets,sample_format=SAMPLE_FORMAT,
                max_sample_gap_ms=round(max((b-a for a,b in zip(edges,edges[1:])),default=0)/1000,3))
            self.records.append(row)

    def request_product(self, *, visible=False, cancelled=None, target=None, metadata=None):
        """Direct real product backend request; no request/guard/timestamp stubs."""
        box = {}
        def worker():
            try:
                box['result'] = self.capture.capture(target or self.target,
                    cancelled=cancelled, expected_metadata=metadata or self.control.manual_metadata,
                    **({'allow_visible_overlay': True} if visible else {}))
            except BaseException as error: box['error'] = error
        thread = threading.Thread(target=worker, name='fixture-capture', daemon=True)
        thread.start(); self.wait(lambda: not thread.is_alive(), 3.5, 'Capture exceeded existing caller bound')
        thread.join(0)
        if 'error' in box: raise box['error']
        return box['result'][0]

    def title_band_variation(self):
        """Mutate original non-text pixels INSIDE a verified title hash band.

        No recognition is injected: the normal OCR must independently recover
        the same titles. Pixel coordinates are physical, including at high DPR.
        """
        from PySide6 import QtGui
        from screen_capture import bounded_roi
        reference=self.control._accepted_frame
        proof=reference.get('title_proof') if reference else None
        require(proof is not None, 'Accepted title proof missing before variation')
        roi=tuple(spin.value()/100 for spin in self.control.roi)
        left,top,_,_=bounded_roi(self.rect.width,self.rect.height,roi)
        x0,y0,x1,y1=proof.regions[0]
        x,y=left+x0+2,top+(y0+y1)//2
        image=self.artwork[1].toImage()
        for dx in range(4):
            for dy in range(4):image.setPixelColor(x+dx,y+dy,QtGui.QColor(75,60,85))
        self.artwork[1]=QtGui.QPixmap.fromImage(image)
        self.artwork[1].setDevicePixelRatio(self.window.devicePixelRatioF())
        self.result['title_band_variation']={'patch':[x,y,4,4], 'pixel_proof_changed':False}
        return proof

    def product_cycle(self, name, *, visible, paint_state=None):
        """The real GUI route, actual matcher/OCR, and actual result handlers."""
        events = len(self.event_rows); title_events=len(self.title_check_events)
        epoch = self.drain_product_capture(clear_latest=True)
        if paint_state is not None:self.paint(paint_state)
        count = len(self.records); bridge_count = len(self.bridge_results); start = time.monotonic()
        expected_serial = self.control._capture_serial+1
        generation = self.control.state.generation
        self._cycle_serial = expected_serial
        self.control.capture_tick()
        # A planned mode switch may first return while the prior owner drains.
        while not any(row.get('acquisition_role') == 'primary' for row in self.records[count:]):
            require(time.monotonic()-start < 8, 'GUI planned drain did not lead to a new request')
            self.pump(.005)
            if (self.control._capture_serial < expected_serial
                    and not self.control.capture_pending and not self.control.ocr_busy):
                self.control.capture_tick()
        self.drain_product_capture()
        self._cycle_serial = None
        self.wait(lambda: len(self.bridge_results) > bridge_count, 8,
                  'Original OCR bridge metadata did not arrive')
        require(len(self.bridge_results) <= 64, 'Product bridge inventory exceeded its bound')
        rows = self.records[count:]
        primary = [row for row in rows if row.get('acquisition_role') == 'primary']
        require(len(primary) == 1 and len(self.records) <= 64
                and all(row.get('acquisition_role') in ('primary', 'background') for row in rows),
                'An explicit product cycle performed an unexpected primary acquisition')
        row = primary[0]
        require(row['status'] == 'passed' and row['visible_request'] is visible, 'Product selected wrong capture route')
        require(row['paint_state'] == self.paint_state,
                'Product cycle was associated with an acquisition from an earlier paint state')
        bridge = self.bridge_results[bridge_count:]
        require(len(bridge) == 1, 'Product cycle lacks exactly one original OCR bridge result')
        observed = bridge[0]
        captured_at = observed['captured_at']
        require(observed['serial'] == row['product_serial'] == self.control._capture_serial == expected_serial
                and observed['generation'] == row['product_generation'] == self.control.state.generation == generation
                and tuple(observed['window_identity'] or ()) == self.target.identity
                # The normal strict-hidden worker explicitly clears the slot
                # once more; the visible worker must keep this exact epoch.
                and row['producer_epoch'] == epoch + (0 if visible else 1)
                and type(captured_at) in (int, float)
                and start <= captured_at <= row['capture_started_at'] <= row['capture_returned_at'],
                'Original OCR frame did not belong to the explicit acquisition boundary')
        row['case'] = name
        row['product'] = dict(capture_serial=self.control._capture_serial,confirmed=self.control.state.confirmed,
            generation=generation, captured_at=captured_at, boundary_at=start,
            boundary_producer_epoch=epoch, producer_epoch=row['producer_epoch'], paint_state=self.paint_state,
            automatic_frames=self.control.state.automatic_frames, hero=self.control.state.hero,
            offered=list(self.control.state.offered), partial_names=list(self.control.current_partial_names()),
            tier_texts=[badge.tier for badge in self.overlay._badge_widgets], overlay_visible=self.overlay.isVisible(),
            hide_events=sum(item['event']=='hide' for item in self.event_rows[events:]),
            show_events=sum(item['event']=='show' for item in self.event_rows[events:]),
            title_check_transitions=self.title_check_events[title_events:], titles_pending=self.overlay._titles_pending)
        if visible:
            require(row['visibility']['samples'] > 0 and row['visibility']['qt_hidden_samples'] == 0
                    and row['visibility']['native_hidden_samples'] == 0 and row['native_visible_before']
                    and row['native_visible_after'], 'Overlay was hidden during actual acquisition')
            require(row['product']['hide_events'] == 0 and self.overlay.isVisible(),
                    'Product hid/reflowed its visible overlay during capture/inference/result')
            require(not row['product']['title_check_transitions'] and not row['product']['titles_pending'],
                    'Unchanged semantic titles alternated grades and neutral checking text')
        return row

    def partial_product_cycles(self):
        """Real OCR on original cards with one catalog name intentionally absent."""
        names=tuple(self.control.state.offered)
        require(len(names)==3,'Full accepted titles missing before partial case')
        omitted=self.control.data['augments'].pop(names[1])
        try:
            owner=self.capture._persistent._owner
            self.control.invalidate_scene('Owned synthetic partial catalog change')
            self.paint(0)
            first=self.product_cycle(None,visible=False)
            self.cleanup_owner(owner,'full-to-partial-hidden-drain')
            second=self.product_cycle(None,visible=False)
            expected=[names[0],'',names[2]]
            require(second['product']['partial_names']==expected and not second['product']['confirmed'],
                    'Two real partial OCR frames did not establish independent known slots')
            owner=self.capture._persistent._owner
            partial_reference=self.control._accepted_partial_frame
            require(partial_reference is not None,'Partial display lacks scoped accepted authority')
            third=self.product_cycle(None,visible=True,paint_state=1)
            self.cleanup_owner(owner,'partial-hidden-to-visible-drain')
            require(third['product']['partial_names']==expected and third['product']['tier_texts']==second['product']['tier_texts']
                    and third['product']['tier_texts'][1]=='', 'Partial animation lost known grades or rated the unknown slot')
            from native_smoke import visible_badge_slots
            from card_badges import native_region
            from PIL import Image
            x,y,w,h=self.result['title_band_variation']['patch']
            before=Image.open(io.BytesIO(second['_png'])).convert('RGB').crop((x,y,x+w,y+h))
            after=Image.open(io.BytesIO(third['_png'])).convert('RGB').crop((x,y,x+w,y+h))
            require(before.tobytes()!=after.tobytes(),'Partial title-band pixels did not actually change')
            slots=visible_badge_slots(self.overlay,bool(self.u.IsWindowVisible(self.overlay_hwnd)))
            require(slots==[1,3] and len(self.overlay._badge_regions)==2,'Partial native mask/slots differ')
            native_region(self.overlay_hwnd,self.overlay._badge_regions,verify_only=True)
            unknown=self.overlay._badge_widgets[1]
            require(not unknown.tier and not unknown.hint and not unknown.identity_provenance
                    and not unknown.accessibleDescription() and unknown.accessibleName()=='选项 2 · 正在核对当前候选',
                    'Unknown slot exposes stale grade/identity')
            self.result['partial_product']={'title_band_pixels_changed':True,'visible_slots':slots,
                'native_region_count':len(self.overlay._badge_regions),'native_mask_verified':True,'unknown_accessible_ungraded':True,
                'reference_serial':partial_reference['serial'],'request_indices':[self.records.index(row) for row in (first,second,third)],
                'expected_names':expected,'unknown_slot':2,'same_overlay_hwnd':int(self.overlay.winId())==self.overlay_hwnd}
        finally:
            self.control.data['augments'][names[1]]=omitted
        # Restore through independent real observations, never inject grades.
        owner=self.capture._persistent._owner
        self.control.invalidate_scene('Owned synthetic full catalog restored')
        self.product_cycle(None,visible=False)
        self.cleanup_owner(owner,'partial-to-full-hidden-drain')
        self.product_cycle(None,visible=False)
        require(self.control.state.confirmed,'Full real OCR did not recover after partial case')
        # Stop acceptance below requires an actual visible-enrollment request.
        owner=self.capture._persistent._owner
        self.product_cycle(None,visible=True)
        self.cleanup_owner(owner,'restored-full-to-visible-drain')

    def cleanup_owner(self, owner, label):
        from native_smoke import _duty_session_cleanup
        if owner is None or owner.session is None or owner.session._transport is None:return None
        transport = owner.session._transport
        process = transport.process
        from native_smoke import _duty_process_created
        receipt = dict(helper_pid=process.pid, helper_created=_duty_process_created(process),
                       session_generation=transport.generation)
        start = time.monotonic(); found = [None]
        def complete():
            found[0] = _duty_session_cleanup(self.capture, owner, transport, receipt,
                                            observed_ms=(time.monotonic()-start)*1000)
            return found[0] is not None
        self.wait(complete, 8, 'Exact owner/helper/pipe/Job cleanup exceeded existing 8-second bound')
        row = dict(found[0], case=label)
        self.result['transitions'].append(row)
        return row

    def prepare(self, visible, label):
        old = self.capture._persistent._owner; start = time.monotonic(); polls = 0
        while not self.capture.prepare_capture_mode(visible):
            polls += 1; require(time.monotonic()-start < 8, 'Planned mode cleanup exceeded existing bound')
            self.pump(.003)
        if old is not None and old.revoked.is_set():self.cleanup_owner(old, label)
        return dict(polls=polls, elapsed_ms=round((time.monotonic()-start)*1000, 3))

    def fresh_visible(self):
        old = self.capture._persistent._owner
        self.capture.retire_session()
        if old is not None:self.cleanup_owner(old, 'negative-case-reset')
        self.focus(self.window); self.overlay.show(); self.overlay.configure(); self.pump(.02)
        self.prepare(True, 'negative-case-enrollment')
        self.request_product(visible=True)
        return self.capture._persistent._owner

    def presentation_lifecycle(self):
        """Separate hide/show lifecycle case; never dilute visible pixel evidence."""
        from native_smoke import _duty_session_observation
        from wgc_session_capture import _qpc_100ns
        owner=self.capture._persistent._owner
        require(owner is not None and owner.binding[-1] is True and self.overlay.isVisible(),
                'Presentation lifecycle needs an already enrolled visible session')
        epoch=self.capture.session_epoch;baseline=self.records[-1]
        binding=tuple(baseline[key] for key in ('helper_pid','helper_created','session_generation'))
        fallbacks=len(self.fallback_calls)
        evidence=dict(baseline_request_index=len(self.records)-1,adapter_epoch=epoch,requests=[])
        self.result['presentation_lifecycle']=evidence
        for visible in (False,True,False,True):
            if visible:self.overlay.show()
            else:self.overlay.hide('owned-presentation-cycle')
            before=time.monotonic();self.pump(.1)
            dwell_ms=round((time.monotonic()-before)*1000,3)
            require(self.capture.prepare_capture_mode(True) and self.capture._persistent._owner is owner
                    and self.capture.session_epoch==epoch, 'Presentation-only change retired the adapter owner')
            require(self.overlay.isVisible() is visible and bool(self.u.IsWindowVisible(self.overlay_hwnd)) is visible,
                    'Owned presentation change did not reach the native HWND')
            box={}
            def worker():
                try:
                    start=_qpc_100ns();started=time.monotonic()
                    image,rect=self.real_capture(self.target,expected_metadata=self.control.manual_metadata,
                                                allow_visible_overlay=True)
                    returned=_qpc_100ns();elapsed=round((time.monotonic()-started)*1000,3)
                    receipt=dict(self.capture.last_session_receipt or {})
                    current,_,observation=_duty_session_observation(self.capture,receipt,hidden=not visible)
                    require(current is owner and rect==self.rect, 'Presentation cycle changed owner or target geometry')
                    box['row']=dict(receipt,capture_start_100ns=start,capture_return_100ns=returned,
                        elapsed_ms=elapsed,visible=visible,watchdog_dwell_ms=dwell_ms,observation=observation,
                        overlay_window_style=int(self.capture.get_long(self.overlay_hwnd,-16))&0xffffffff,
                        enrolled_window_style=owner.session._overlay_window_style,adapter_epoch=self.capture.session_epoch,
                        pixels_sha256=hashlib.sha256(pixels(image).tobytes()).hexdigest())
                except BaseException as error:box['error']=error
            thread=threading.Thread(target=worker,name='fixture-presentation-capture',daemon=True)
            thread.start();self.wait(lambda:not thread.is_alive(),3.5,'Presentation capture exceeded existing caller bound')
            thread.join(0)
            if 'error' in box:raise box['error']
            row=box['row'];evidence['requests'].append(row)
            require(strict_timing(row) and tuple(row[key] for key in ('helper_pid','helper_created','session_generation'))==binding
                    and self.capture._persistent._owner is owner and self.capture.session_epoch==epoch,
                    'Native presentation cycle replaced the enrolled helper')
            require(row['pixels_sha256']==baseline['pixels_sha256'] and len(self.fallback_calls)==fallbacks,
                    'Presentation cycle changed target pixels or reached a fallback')
        evidence['fallback_calls']=len(self.fallback_calls)-fallbacks

    def rejected_evidence(self,name,cleanup,*,mutation=None):
        row=self.records[-1]
        require(row['status']=='rejected' and all(row.get(key)==cleanup[key]
                for key in ('helper_pid','helper_created','session_generation')),
                'Rejected request is not bound to the exact retired owner: '+name)
        row['negative_case']=name
        if mutation is not None:row['mutation_100ns']=mutation
        return dict(request_index=len(self.records)-1,capture_start_100ns=row['capture_start_100ns'],
                    capture_return_100ns=row['capture_return_100ns'],
                    mutation_100ns=row.get('mutation_100ns'),request_id=row.get('pending_exchange_request_id'))

    def inflight_negative(self, name, action, restore=lambda:None, *, cancelled=None):
        owner=self.fresh_visible();count=len(self.records);fallbacks=len(self.fallback_calls)
        self.pending_action=action;error=None
        try:
            try:self.request_product(visible=True,cancelled=cancelled)
            except Exception as rejected:error=rejected
            require(self.pending_action is None, 'No real pending native exchange was observed: '+name)
            require(error is not None and len(self.records)==count+1 and self.records[-1]['status']=='rejected',
                    'In-flight invalidation returned pixels: '+name)
            self.capture.retire_session();cleanup=self.cleanup_owner(owner,name)
            require(len(self.fallback_calls)==fallbacks and self.capture.last_session_receipt is None,
                    'In-flight invalidation reached fallback or retained receipt')
            row=self.records[-1]
            self.result['negative_results'][name]=dict(status='rejected',actual_native_idle_rejection=False,
                actual_pending_native_exchange=True,evidence='actual mutation while native request remained pending',
                mutation_100ns=row['mutation_100ns'],request_id=row['pending_exchange_request_id'],
                capture_start_100ns=row['capture_start_100ns'],fallback_calls=0,
                native_exit_code=owner.session._transport.process.returncode,
                helper_pid=cleanup['helper_pid'],helper_created=cleanup['helper_created'],
                session_generation=cleanup['session_generation'])
            self.result['negative_results'][name].update(self.rejected_evidence(name,cleanup))
        finally:self.pending_action=None;restore()

    def stop_inflight(self):
        """Stop the actual GUI worker, then prove no restart or accepted result."""
        self.drain_product_capture(clear_latest=True)
        owner=self.capture._persistent._owner;count=len(self.records);fallbacks=len(self.fallback_calls)
        self.pending_action=self.control.stop_monitor
        try:
            self.control.capture_tick()
            self.wait(lambda:len(self.records)>count and not self.control.ocr_busy and not self.control.capture_pending,
                      8,'Actual product Stop did not drain its capture/inference worker')
            require(self.pending_action is None and len(self.records)==count+1,
                    'Stop did not occur during a real pending product capture')
            row=self.records[-1]
            require(row['visible_request'] and row['status']=='rejected' and not self.control.state.running
                    and not self.control.state.confirmed and self.control._accepted_frame is None
                    and not self.overlay.isVisible(), 'Late product result survived Stop')
            cleanup=self.cleanup_owner(owner,'stop')
            self.control.capture_tick();self.pump(.08)
            require(len(self.records)==count+1 and len(self.fallback_calls)==fallbacks,
                    'GUI capture restarted or fell back after Stop')
            self.result['negative_results']['stop']=dict(status='rejected',actual_native_idle_rejection=False,
                actual_pending_native_exchange=True,evidence='actual ControlWindow Stop during pending native request',
                mutation_100ns=row['mutation_100ns'],request_id=row['pending_exchange_request_id'],
                capture_start_100ns=row['capture_start_100ns'],fallback_calls=0,
                native_exit_code=owner.session._transport.process.returncode,
                helper_pid=cleanup['helper_pid'],helper_created=cleanup['helper_created'],
                session_generation=cleanup['session_generation'],
                late_result_discarded=True,gui_restart_after_stop=False)
            self.result['negative_results']['stop'].update(self.rejected_evidence('stop',cleanup))
        finally:self.pending_action=None
        from session_windows import process_metadata
        self.control.manual_identity=self.target.identity
        self.control.manual_metadata=process_metadata(self.target.pid)

    def negative(self, name, change, restore=lambda: None, *, native=True, request=None):
        owner = self.fresh_visible(); transport = owner.session._transport
        before = len(self.fallback_calls); start = time.monotonic()
        try:
            from wgc_session_capture import _qpc_100ns
            mutation=_qpc_100ns()
            change()
            native_revoked = False
            if native:
                self.wait(lambda: transport.revoked.is_set(), 3.5, 'Native idle guard did not revoke '+name)
                native_revoked = True
            rejected = None
            try:(request or (lambda: self.request_product(visible=True)))()
            except Exception as error: rejected = error
            require(rejected is not None, 'Unsafe request returned pixels: '+name)
            self.capture.retire_session()
            cleanup = self.cleanup_owner(owner, name)
            require(len(self.fallback_calls) == before, 'Visible failure reached v1/GDI: '+name)
            require(self.capture.last_session_receipt is None, 'Rejected capture retained a usable receipt')
            self.result['negative_results'][name] = dict(status='rejected',
                actual_native_idle_rejection=native_revoked, native_exit_code=transport.process.returncode,
                evidence='actual native mutation' if native else 'actual product request/lifecycle guard',
                error_type=type(rejected).__name__, elapsed_ms=round((time.monotonic()-start)*1000, 3),
                fallback_calls=0, helper_pid=cleanup['helper_pid'], helper_created=cleanup['helper_created'])
            self.result['negative_results'][name]['session_generation']=cleanup['session_generation']
            self.result['negative_results'][name].update(self.rejected_evidence(name,cleanup,mutation=mutation))
            if native:
                from wgc_session_capture import decode_session_diagnostic
                code=transport.process.returncode;expected=NATIVE_NEGATIVE_EXIT_CODES[name]
                self.result['negative_results'][name]['native_diagnostic']=decode_session_diagnostic(transport.diagnostic,code)
                require(type(code) is int and code == expected,
                        f'Native rejection exit differs for {name}: expected {expected}, observed {code!r}')
        finally:
            restore(); self.pump(.02)

    def close(self):
        self.capture.retire_session()
        owner = self.capture._persistent._owner
        if owner is not None:self.cleanup_owner(owner, 'final-product-stop')
        if hasattr(self, 'events'):self.overlay.removeEventFilter(self.events)
        self.control.close(); self.capture.close()
        # The base fixture verifies every exact owned helper and window, all
        # pipe/watchdog threads and Job handles, then restores thread DPI.
        super().close()


def execute(result, report_path):
    f = ProductFixture(result, report_path)
    try:
        helper = f.session.helper_directory()
        proof = json.loads((helper / f.session.MANIFEST_NAME).read_text(encoding='utf-8'))
        result['helper'] = dict(manifest=proof, sha256=sha256(helper / f.session.HELPER_NAME),
                                size=(helper / f.session.HELPER_NAME).stat().st_size)
        # Two independent actual observations through capture_tick, matcher,
        # OCR, and normal handlers. Never inject a recognition/confirmation.
        first = f.product_cycle('cold-hidden', visible=False)
        require(not first['product']['confirmed'], 'One frame unexpectedly confirmed product state')
        second = f.product_cycle('hidden-confirmation', visible=False)
        require(second['product']['confirmed'] and second['product']['automatic_frames'] == 2,
                'Two real OCR observations did not confirm')
        hidden_owner = f.capture._persistent._owner
        accepted_title_proof=f.title_band_variation()
        # Preserve the actual product renderer, but make its interior a strong
        # diagnostic contamination sentinel. No production renderer is replaced.
        install_badge_sentinels(f.overlay)
        f.overlay.update(); f.pump(.02)
        from wgc_session_smoke import qt_overlay_observation
        rendered=f.overlay.grab().toImage()
        magenta=sum(rendered.pixelColor(x,y).getRgb()==(255,0,255,255)
                    for x in range(0,rendered.width(),8) for y in range(0,rendered.height(),8))
        result['overlay_rendering']=dict(qt_overlay_observation(f.overlay),magenta_grid_samples=magenta,
                                         **badge_sentinel_observation(f.overlay))
        require(magenta>20 and result['overlay_rendering']['qt_opacity']==1
                and not result['overlay_rendering']['qt_translucent_background']
                and result['overlay_rendering']['qt_opaque_paint_event']
                and not result['overlay_rendering']['qt_surface_has_alpha'],
                'Actual product overlay is not the bright opaque renderer')
        # Reference A was acquired hidden, on exactly this deterministic state.
        references = {0: second['_png']};reference_rows={0:f.records.index(second)}
        ui1 = f.product_cycle('visible-product-1', visible=True)
        badge_sentinel_observation(f.overlay)
        require(hidden_owner.revoked.is_set(), 'Product capture_tick did not drain the hidden owner')
        f.cleanup_owner(hidden_owner,'hidden-to-visible-product-planned-drain')
        accepted_title_proof=f.control._accepted_frame['title_proof']
        ui2 = f.product_cycle('visible-product-2', visible=True, paint_state=1)
        from PIL import Image
        from screen_capture import bounded_roi
        from synthetic_vision import encoded
        with Image.open(io.BytesIO(ui2['_png'])) as captured:
            left,top,width,height=bounded_roi(captured.width,captured.height,tuple(spin.value()/100 for spin in f.control.roi))
            changed=not accepted_title_proof.matches(encoded(captured.crop((left,top,left+width,top+height))))
        require(changed,'Non-text title-band variation did not actually invalidate the exact pixel hash')
        result['title_band_variation']['pixel_proof_changed']=changed
        badge_sentinel_observation(f.overlay)
        require(ui1['paint_state'] == 0 and ui2['paint_state'] == 1
                and ui1['pixels_sha256'] != ui2['pixels_sha256'],
                'Second visible GUI cycle did not acquire changed target pixels')
        require(all(row['product']['hero'] == second['product']['hero']
                    and row['product']['offered'] == second['product']['offered'] for row in (ui1, ui2)),
                'Changed target pixels did not preserve the accepted hero and ordered candidate trio')
        identity = lambda row: tuple(row[key] for key in ('helper_pid','helper_created','session_generation'))
        require(identity(ui1) == identity(ui2) and identity(first) == identity(second)
                and identity(second) != identity(ui1), 'Cold/visible helper lifecycle or reuse differs')
        result['product_helper_reuse_passed'] = True
        f.partial_product_cycles()
        f.stop_inflight()
        # Acquire B hidden only after draining the visible immutable enrollment.
        f.overlay.hide(); f.prepare(False, 'visible-to-hidden-reference')
        f.paint(1); references[1] = f.request_product()
        reference_rows[1]=len(f.records)-1
        require(compare_pixels(references[0], references[1])['changed_pixels'] > 0,
                'The two deterministic target states are identical')
        f.overlay.show(); f.overlay.configure(); f.prepare(True, 'reference-to-visible')
        result['pixel_pairs'] = []
        # Move this exact actual product HWND across title and own-HUD regions.
        # All captures compare against a hidden reference of the SAME state.
        for state, placement in ((0, 'titles'), (1, 'hud'), (1, 'titles')):
            f.paint(state)
            x = f.rect.x + (f.rect.width//5 if placement == 'titles' else f.rect.width//4)
            y = f.rect.y + (round(f.rect.height*.37) if placement == 'titles' else round(f.rect.height*.88))
            require(f.u.SetWindowPos(f.overlay_hwnd, ctypes.c_void_p(-1), x, y, 0, 0, 0x0011),
                    'Cannot position exact owned product overlay')
            f.pump(.03)
            badge_sentinel_observation(f.overlay)
            captured = f.request_product(visible=True); row = f.records[-1]
            comparison = compare_pixels(references[state], captured)
            require(comparison['max_channel_error'] == 0 and comparison['changed_pixels'] == 0,
                    'Excluded product overlay altered captured target pixels')
            require(comparison['hidden_magenta_pixels'] == comparison['visible_magenta_pixels'],
                    'Bright overlay sentinel contaminated capture')
            require(row['visibility']['samples'] > 0 and not row['visibility']['qt_hidden_samples']
                    and not row['visibility']['native_hidden_samples'], 'Pixel-pair capture hid overlay')
            native_rect = W.RECT(); require(f.u.GetWindowRect(f.overlay_hwnd, ctypes.byref(native_rect)), 'Overlay rect unavailable')
            result['pixel_pairs'].append(dict(state=state, placement=placement,
                overlay_rect=[native_rect.left,native_rect.top,native_rect.right-native_rect.left,native_rect.bottom-native_rect.top],
                **comparison, request_index=len(f.records)-1, hidden_reference_index=reference_rows[state]))
        result['pixel_exclusion_passed'] = True
        f.presentation_lifecycle()
        run_negatives(f)
        # Explicit compatibility mode: a later hidden request may use v1 only
        # after the entire visible v2 ownership barrier has completed.
        owner = f.fresh_visible()
        f.capture.set_interactive_overlay(True); f.overlay.hide()
        if owner is not None:f.cleanup_owner(owner, 'visible-to-hidden-compatibility')
        f.prepare(False, 'hidden-compatibility-ready')
        count = len(f.fallback_calls)
        # The receipt observer deliberately applies only to persistent requests.
        f.capture.capture = f.real_capture
        png = f.request_product()
        require(png and len(f.fallback_calls) == count+1 and f.fallback_calls[-1] == 'v1',
                'Hidden compatibility request did not use the bounded v1 path')
        f.capture.capture = f.observed_capture
        result['hidden_compatibility_passed'] = True
    finally:
        try:f.close()
        finally:
            # Pixels and lifetime tokens never enter persisted evidence.
            for row in f.records:row.pop('_png', None)
            result['fallback_calls'] = list(f.fallback_calls)


def run_negatives(f):
    from screen_capture import WindowInfo
    from wgc_session_capture import _property_name
    QtCore, QtWidgets = f.QtCore, f.QtWidgets
    other = QtWidgets.QWidget(None, QtCore.Qt.Tool | QtCore.Qt.FramelessWindowHint |
                             QtCore.Qt.WindowDoesNotAcceptFocus | QtCore.Qt.WindowStaysOnTopHint)
    other.setAttribute(QtCore.Qt.WA_ShowWithoutActivating); other.resize(80, 80)
    other.move(round((f.rect.x+40)/f.window.devicePixelRatioF()), round((f.rect.y+40)/f.window.devicePixelRatioF()))
    f.windows.append(other)
    f.negative('same_pid_occluder', other.show, other.hide)
    style = int(f.capture.get_long(f.overlay_hwnd, -20)) & 0xffffffff
    window_style = int(f.capture.get_long(f.overlay_hwnd, -16)) & 0xffffffff
    for name, index, value, original in (
        ('extended_style_change', -20, style ^ 0x20, style),
        ('window_style_change', -16, window_style ^ 0x00800000, window_style)):
        f.negative(name, lambda i=index,v=value:f.capture.set_long(f.overlay_hwnd,i,v),
                   lambda i=index,v=original:f.capture.set_long(f.overlay_hwnd,i,v))
    f.negative('affinity_change', lambda:f.u.SetWindowDisplayAffinity(f.overlay_hwnd,0),
               lambda:f.u.SetWindowDisplayAffinity(f.overlay_hwnd,0x11))
    f.negative('opacity_change', lambda:f.u.SetLayeredWindowAttributes(f.overlay_hwnd,0,254,2),
               lambda:f.u.SetLayeredWindowAttributes(f.overlay_hwnd,0,255,2))
    f.negative('token_change', lambda:f.u.RemovePropW(f.overlay_hwnd,
               _property_name(f.capture._persistent._owner.session._overlay[2])))
    f.negative('protected_target', lambda:f.u.SetWindowDisplayAffinity(f.target.hwnd,0x11),
               lambda:f.u.SetWindowDisplayAffinity(f.target.hwnd,0))
    f.negative('focus_loss', lambda:f.focus(f.control), lambda:(f.control.hide(),f.focus(f.window)))
    point = f.window.pos()
    f.negative('geometry_loss', lambda:f.window.move(point.x()+5,point.y()), lambda:f.window.move(point))
    # Window ownership cannot be reassigned to a different PID with a legitimate
    # Win32 mutation. The wrong-owner enrollment below is a product guard test,
    # explicitly distinct from the actual native idle mutations above.
    from session_windows import ProcessMetadata
    actual_metadata = f.control.manual_metadata
    wrong_metadata = ProcessMetadata(actual_metadata.path, actual_metadata.created+1)
    f.negative('owner_change', lambda:None, native=False,
               request=lambda:f.request_product(visible=True,metadata=wrong_metadata))
    f.result['negative_results']['owner_change']['evidence'] = 'product guard injection: mismatched expected target process creation time'
    def wrong_handle():
        # Use the adapter's real enrollment-change API so the old property is
        # cleaned by its exact owner, even when the new enrollment is invalid.
        f.capture._persistent.set_overlay(int(other.winId()), style)
    def restore_handle():
        f.overlay.configure()
    f.negative('wrong_hwnd', wrong_handle, restore_handle, native=False)
    # Substitute an incorrect lifetime token on the actual owned HWND. Do not
    # force the OS to recycle a numeric handle or claim it did so.
    changed_name = [None]
    def replaced_token():
        token = f.capture._persistent._owner.session._overlay[2]
        name = changed_name[0] = _property_name(token)
        require(f.u.RemovePropW(f.overlay_hwnd,name), 'Could not remove owned registration property')
        f.u.SetPropW.argtypes=[W.HWND,W.LPCWSTR,W.HANDLE];f.u.SetPropW.restype=W.BOOL
        require(f.u.SetPropW(f.overlay_hwnd,name,token ^ 1 or 2), 'Could not replace owned registration token')
    f.negative('replaced_hwnd_token', replaced_token,
               lambda:f.u.RemovePropW(f.overlay_hwnd,changed_name[0]) if changed_name[0] else None)
    f.result['negative_results']['replaced_hwnd_token']['numeric_hwnd_reuse_forced'] = False
    f.result['negative_results']['replaced_hwnd_token']['evidence'] = 'actual stale lifetime-token substitution; numeric HWND reuse not forced'
    cancellation=threading.Event()
    f.inflight_negative('cancel',cancellation.set,cancelled=cancellation)
    f.inflight_negative('active_affinity_change',lambda:f.u.SetWindowDisplayAffinity(f.overlay_hwnd,0),
                        lambda:f.u.SetWindowDisplayAffinity(f.overlay_hwnd,0x11))
    # Restore only this fixture's authorization for the remaining owned checks.
    from session_windows import process_metadata
    f.control.manual_identity=f.target.identity;f.control.manual_metadata=process_metadata(f.target.pid)
    foreign_negative(f)


def foreign_negative(f):
    """Coordinate with the external runner; never mutate a borrowed HWND."""
    from session_windows import process_metadata
    request = f.report_path.with_suffix('.foreign-request.json')
    ready = f.report_path.with_suffix('.foreign-ready.json')
    release = f.report_path.with_suffix('.foreign-release.json')
    owner = f.fresh_visible()
    write_report(request, dict(pid=os.getpid(), created=process_metadata(os.getpid()).created,
        target_hwnd=f.target.hwnd, rect=vars(f.rect), status='ready'))
    found=[None]
    def published():
        found[0]=poll_owned_json(ready,read_live_json)
        return found[0] is not None
    f.wait(published, 10, 'External Job-owned foreign occluder was not supplied')
    proof = found[0]
    info = f.capture.info(proof['hwnd'])
    require(info.pid == proof['pid'] and info.pid != os.getpid()
            and process_metadata(info.pid).created == proof['created']
            and proof['job_verified'] is True and f.capture.foreground(f.target),
            'Foreign occluder exact ownership or target focus differs')
    before = len(f.fallback_calls); transport = owner.session._transport
    f.wait(transport.revoked.is_set, 3.5, 'Foreign occluder did not revoke actual native idle session')
    error = None
    try:f.request_product(visible=True)
    except Exception as rejected:error=rejected
    require(error is not None and len(f.fallback_calls)==before, 'Foreign occlusion did not fail closed')
    f.capture.retire_session();cleanup=f.cleanup_owner(owner,'foreign_pid_occluder')
    f.result['negative_results']['foreign_pid_occluder'] = dict(status='rejected',
        actual_native_idle_rejection=True, native_exit_code=transport.process.returncode, fallback_calls=0,
        helper_pid=cleanup['helper_pid'], helper_created=cleanup['helper_created'],
        session_generation=cleanup['session_generation'],
        foreign_pid=info.pid, foreign_created=proof['created'], foreign_hwnd=info.hwnd,
        foreign_fixture_sha256=proof['executable_sha256'], job_verified=True)
    f.result['negative_results']['foreign_pid_occluder'].update(f.rejected_evidence('foreign_pid_occluder',cleanup))
    from wgc_session_capture import decode_session_diagnostic
    code=transport.process.returncode;expected=NATIVE_NEGATIVE_EXIT_CODES['foreign_pid_occluder']
    f.result['negative_results']['foreign_pid_occluder']['native_diagnostic']=decode_session_diagnostic(transport.diagnostic,code)
    require(type(code) is int and code == expected,
            f'Native rejection exit differs for foreign_pid_occluder: expected {expected}, observed {code!r}')
    write_report(release, {'status':'release'})
    f.wait(lambda:not f.u.IsWindow(info.hwnd), 10, 'External owned foreign window survived cleanup')


def run(report_path):
    result = dict(status='failed', schema_version=1, applicationVersion=__version__,
        frozen=bool(getattr(sys,'frozen',False)), scope=SCOPE, limitations=dict(LIMITATIONS),
        executable_sha256=sha256(sys.executable) if getattr(sys,'frozen',False) else None)
    code = 1
    try:
        execute(result, report_path)
        require(set(result.get('negative_results',{})) == set(NEGATIVES), 'Negative evidence incomplete')
        result['status']='passed';code=0
    except Exception as error:
        result.update(error_type=type(error).__name__,error=str(error)[:2000])
    finally:
        payload=report_payload(result)
        path=Path(report_path);path.parent.mkdir(parents=True,exist_ok=True)
        temporary=path.with_name(path.name+'.tmp');temporary.write_text(payload,encoding='utf-8');temporary.replace(path)
    return code

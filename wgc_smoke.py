"""Explicit offline WGC acceptance using only this process's original Qt windows.

No HWND/path input or trust override is accepted. The diagnostic never accesses a
real game. Pixels are generated here and compared in memory; none are saved.
Controlled suspended owned-helper launches exercise the real Windows watchdog
and cancellation cleanup, separately from positive native WGC pixel capture.
"""
from __future__ import annotations
import ctypes
from ctypes import wintypes as W
from dataclasses import replace
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import threading
import time

from app_version import __version__

CHECK_FIELDS = ('owned_hwnd_pixels_passed', 'routed_wgc_backend_passed', 'roi_bounds_passed',
    'native_roi_bounds_passed', 'stale_identity_passed', 'resize_stale_passed', 'destroy_stale_passed', 'focus_loss_passed',
    'occlusion_passed', 'minimized_passed', 'protected_window_passed', 'cancel_before_launch_passed',
    'cancel_during_wait_passed', 'timeout_watchdog_passed', 'helpers_exited_passed', 'pipe_readers_exited_passed',
    'job_close_cleanup_passed', 'startgate_eof_passed', 'job_handles_closed_passed', 'windows_closed_passed')
SCOPE = ('Original self-owned Qt HWNDs and synthetic colored pixels only. Actual WGC capture, '
         'client ROI and native lifecycle validation; controlled suspended owned helper for '
         'watchdog/cancel tests. No real game, Vanguard, exclusive-fullscreen or OCR claim.')


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def pixel_error(image, rect, roi):
    from PIL import Image, ImageDraw, ImageChops, ImageStat
    colors = ((226, 61, 82), (45, 188, 137), (68, 109, 231), (243, 196, 54))
    expected = Image.new('RGB', (rect.width, rect.height))
    draw = ImageDraw.Draw(expected)
    x, y = rect.width // 2, rect.height // 2
    for bounds, color in zip(((0, 0, x-1, y-1), (x, 0, rect.width-1, y-1),
                              (0, y, x-1, rect.height-1), (x, y, rect.width-1, rect.height-1)), colors):
        draw.rectangle(bounds, fill=color)
    left, top, width, height = roi
    expected = expected.crop((left, top, left+width, top+height))
    require(image.size == expected.size, 'WGC did not return exactly the client ROI dimensions')
    error = max(ImageStat.Stat(ImageChops.difference(image.convert('RGB'), expected)).mean)
    require(error <= 2.0, f'Actual WGC pixels differ from the owned synthetic ROI: {error:.3f}')
    return round(error, 4)


def execute(result):
    require(os.name == 'nt', 'Native Windows is required; offscreen/Linux is not capture evidence')
    require(ctypes.sizeof(ctypes.c_void_p) == 8, 'WGC acceptance requires an x64 process')
    from screen_capture import Win32Capture, CaptureUnavailable
    from wgc_capture import WgcCapture, WgcError
    import wgc_capture
    capture = Win32Capture()
    u = capture.u
    for name, args, return_type in (
        ('SetThreadDpiAwarenessContext', [ctypes.c_void_p], ctypes.c_void_p),
        ('GetThreadDpiAwarenessContext', [], ctypes.c_void_p),
        ('AreDpiAwarenessContextsEqual', [ctypes.c_void_p, ctypes.c_void_p], W.BOOL),
        ('SetForegroundWindow', [W.HWND], W.BOOL), ('ShowWindow', [W.HWND, ctypes.c_int], W.BOOL),
        ('GetWindowDisplayAffinity', [W.HWND, ctypes.POINTER(W.DWORD)], W.BOOL),
        ('SetLayeredWindowAttributes', [W.HWND, W.DWORD, ctypes.c_ubyte, W.DWORD], W.BOOL)):
        fn = getattr(u, name); fn.argtypes = args; fn.restype = return_type
    old_dpi = u.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
    require(bool(old_dpi), 'Cannot establish local PMv2 observer coordinates')
    app = window = cover = None
    processes, jobs = [], []
    original_popen = wgc_capture.subprocess.Popen
    original_job = wgc_capture._CaptureJob
    class RecordingJob(original_job):
        def __init__(self):
            super().__init__()
            jobs.append(self)
    wgc_capture._CaptureJob = RecordingJob
    try:
        from PySide6 import QtCore, QtGui, QtWidgets
        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        require(app.platformName().lower() == 'windows', 'Actual Windows Qt platform is mandatory')
        result['qt_platform'] = app.platformName()
        class OwnedWindow(QtWidgets.QWidget):
            def paintEvent(self, event):
                painter = QtGui.QPainter(self)
                x, y = self.width() // 2, self.height() // 2
                for box, color in zip(((0,0,x,y),(x,0,self.width()-x,y),
                                       (0,y,x,self.height()-y),(x,y,self.width()-x,self.height()-y)),
                                      ((226,61,82),(45,188,137),(68,109,231),(243,196,54))):
                    painter.fillRect(QtCore.QRect(*box), QtGui.QColor(*color))
        window = OwnedWindow()
        window.setWindowTitle('VGA original WGC acceptance fixture')
        window.resize(320, 240)
        window.move(30, 30)
        window.show()
        deadline = time.monotonic() + 55
        def pump(seconds=.12):
            end = time.monotonic() + seconds
            while time.monotonic() < end:
                require(time.monotonic() < deadline, 'WGC diagnostic exhausted its deadline')
                app.processEvents(); time.sleep(.005)
        def focus(widget):
            widget.showNormal(); widget.raise_(); widget.activateWindow()
            u.SetForegroundWindow(int(widget.winId()))
            pump()
            require(int(u.GetAncestor(u.GetForegroundWindow(), 2) or 0) == int(widget.winId()),
                    'Could not foreground the owned acceptance window')
        focus(window)
        hwnd = int(window.winId())
        target = capture.info(hwnd)
        require(target.pid == os.getpid(), 'Diagnostic target is not owned by this process')
        rect = capture.rect(target)
        dpr = window.devicePixelRatioF()
        result.update(owned_pid=os.getpid(), owned_hwnd=hwnd, client_rect=vars(rect),
                      measured_qt_scale=dpr, requested_app_scale=float(os.environ.get('QT_SCALE_FACTOR', '1')))
        require(abs(dpr - result['requested_app_scale']) < .01, 'Requested/measured Qt scale differs')
        require((rect.width, rect.height) == (round(320*dpr), round(240*dpr)),
                'Owned client did not preserve requested physical DPI dimensions')
        # Exact fractions avoid fractional-pixel interpolation at all tested scales.
        roi = (rect.width // 4, rect.height // 4, rect.width // 2, rect.height // 2)
        backend = WgcCapture()
        helper = Path(backend.helper_path)
        manifest_path = helper.with_name('wgc-capture-build.json')
        proof = json.loads(manifest_path.read_text(encoding='utf-8'))
        result['helper'] = {'sha256': hashlib.sha256(helper.read_bytes()).hexdigest(),
                            'size': helper.stat().st_size, 'manifest': proof}
        require(proof['sha256'] == result['helper']['sha256'] and proof['size'] == result['helper']['size'],
                'Executing helper bytes differ from integrity manifest')
        require(helper.parent.name == 'native', 'Helper did not use its private native bundle directory')
        if getattr(sys, 'frozen', False):
            require(helper.is_relative_to(Path(sys._MEIPASS)), 'Frozen EXE used a helper outside its bundle')
        def recording_popen(args, *more, **kwargs):
            require(Path(args[0]).resolve() == helper.resolve(), 'Unexpected process launched by WGC diagnostic')
            process = original_popen(args, *more, **kwargs)
            processes.append(process)
            return process
        wgc_capture.subprocess.Popen = recording_popen
        def threaded(fn, on_wait=None):
            values, errors = [], []
            def work():
                try: values.append(fn())
                except BaseException as exc: errors.append(exc)
            thread = threading.Thread(target=work, name='owned-wgc-acceptance', daemon=True)
            thread.start()
            end = time.monotonic() + 6
            while thread.is_alive() and time.monotonic() < end:
                if on_wait is not None: on_wait()
                app.processEvents(); thread.join(.005)
            require(not thread.is_alive(), 'WGC operation escaped its hard deadline')
            if errors: raise errors[0]
            return values[0]
        image = threaded(lambda: backend.capture(target, rect, roi))
        result['roi'] = list(roi)
        result['mean_channel_error'] = pixel_error(image, rect, roi)
        result['owned_hwnd_pixels_passed'] = True
        encoded, routed_rect = threaded(lambda: capture.capture(target, (.25, .25, .5, .5)))
        with __import__('PIL.Image', fromlist=['Image']).open(io.BytesIO(encoded)) as image:
            result['routed_mean_channel_error'] = pixel_error(image, rect, roi)
        require(routed_rect == rect and capture.last_backend == 'windows-graphics-capture',
                'Normal capture routing silently used a different backend')
        result.update(last_backend=capture.last_backend, routed_wgc_backend_passed=True)
        def rejects(fn, field, statuses=None, on_wait=None):
            started = time.monotonic()
            try:
                threaded(fn, on_wait)
            except (WgcError, CaptureUnavailable, ValueError) as exc:
                status = getattr(exc, 'status', type(exc).__name__)
                if statuses is not None:
                    require(status in statuses, field + ': unexpected rejection ' + status)
                result.setdefault('negative_results', {})[field] = {
                    'status': status, 'elapsed_ms': round((time.monotonic()-started)*1000, 2)}
                result[field] = True
                return
            raise AssertionError(field + ': unsafe capture unexpectedly returned pixels')
        for invalid in ((-1,0,32,32),(0,-1,32,32),(rect.width-16,0,32,32),(0,rect.height-16,32,32),
                        (0,0,0,32),(0,0,32,0),(0,0,True,32)):
            rejects(lambda value=invalid: backend.capture(target, rect, value), 'roi_bounds_passed')
        from session_windows import process_metadata
        created = process_metadata(target.pid).created
        invalid_args = [str(helper), '--capture-v1', target.hwnd, target.pid, created,
                        rect.x, rect.y, rect.width, rect.height, rect.width-16, 0, 32, 32, 800]
        import subprocess
        native_reject = subprocess.run([str(value) for value in invalid_args], stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=3,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        require(native_reject.returncode == 14 and native_reject.stdout == b'',
                'Native helper did not reject out-of-client ROI before capture')
        result['native_roi_bounds_passed'] = True
        valid_args = [str(helper), '--capture-v1', target.hwnd, target.pid, created,
                      rect.x, rect.y, rect.width, rect.height, *roi, 800]
        # Before Job assignment, loss of the parent's pipe must stop native code
        # before any WGC call. Deliberately provide EOF and require zero pixels.
        eof_child = recording_popen([str(value) for value in valid_args], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        try:
            eof_child.stdin.close(); eof_child.stdin = None
            eof_pixels, _ = eof_child.communicate(timeout=3)
            require(eof_child.returncode == 14 and eof_pixels == b'', 'Native EOF start gate did not fail closed')
            result['startgate_eof_passed'] = True
        finally:
            if eof_child.poll() is None: eof_child.kill(); eof_child.communicate(timeout=3)
            if eof_child.stdout: eof_child.stdout.close()
        # Use only an owned suspended process for a PID/HWND mismatch. Never query
        # a guessed or unrelated PID, even for negative identity testing.
        other = recording_popen([str(helper)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0) | 4)
        other_job = wgc_capture._CaptureJob()
        try:
            other_job.assign(other)
            kernel = other_job.kernel
            kernel.IsProcessInJob.argtypes = [W.HANDLE, W.HANDLE, ctypes.POINTER(W.BOOL)]
            kernel.IsProcessInJob.restype = W.BOOL
            assigned = W.BOOL()
            require(kernel.IsProcessInJob(int(other._handle), other_job.handle, ctypes.byref(assigned)) and assigned.value,
                    'Suspended owned helper was not in the exact production lifetime Job')
            rejects(lambda: backend.capture(replace(target, pid=other.pid), rect, roi),
                    'stale_identity_passed', {'stale'})
            require(other.poll() is None, 'Suspended own helper exited before Job-close test')
            other_job.close()
            require(other.wait(timeout=3) != 0, 'Closing the production Job did not terminate its owned helper')
            result['job_close_cleanup_passed'] = True
            result['job_lifetime_scope'] = 'Production kill-on-close Job on suspended own helper; not an app-crash simulation'
        finally:
            other_job.close()
            if other.poll() is None: other.kill(); other.wait(timeout=3)
        def reject_after_snapshot(action, field):
            # Deterministic race after the production Python metadata/geometry
            # snapshot, before native helper creation. No post-copy claim.
            entered, release = threading.Event(), threading.Event()
            changed = []
            def gate(args, *more, **kwargs):
                entered.set()
                require(release.wait(2), 'Owned lifecycle gate timed out')
                return recording_popen(args, *more, **kwargs)
            def during():
                if entered.is_set() and not changed:
                    changed.append(True)
                    action(); pump(); release.set()
            wgc_capture.subprocess.Popen = gate
            try:
                rejects(lambda: backend.capture(target, rect, roi), field, {'stale'}, during)
                require(bool(changed), 'Lifecycle mutation did not happen after capture snapshot')
                result.setdefault('negative_timing', {})[field] = 'after-Python-snapshot-before-native-launch'
            finally:
                release.set(); wgc_capture.subprocess.Popen = recording_popen
        reject_after_snapshot(lambda: window.resize(336, 256), 'resize_stale_passed')
        window.resize(320, 240); pump(); focus(window)
        require(capture.rect(target) == rect, 'Owned geometry was not restored after resize')
        cover = QtWidgets.QWidget()
        cover.setWindowTitle('VGA original focus and occlusion fixture')
        cover.resize(80, 80); cover.move(window.x()+40, window.y()+40)
        focus(cover)
        rejects(lambda: backend.capture(target, rect, roi), 'focus_loss_passed', {'stale'})
        cover.hide(); focus(window)
        # A nonactivating owned topmost window blocks an unsampled tiny client area.
        cover.setWindowFlags(QtCore.Qt.Tool | QtCore.Qt.WindowStaysOnTopHint | QtCore.Qt.WindowDoesNotAcceptFocus)
        cover.setAttribute(QtCore.Qt.WA_ShowWithoutActivating)
        cover.resize(24, 24); cover.move(window.x()+20, window.y()+50); cover.show(); pump()
        require(capture.foreground(target), 'Occlusion test accidentally changed foreground')
        rejects(lambda: backend.capture(target, rect, roi), 'occlusion_passed', {'stale'})
        cover.hide(); focus(window)
        window.showMinimized(); pump()
        rejects(lambda: backend.capture(target, rect, roi), 'minimized_passed', {'stale'})
        focus(window)
        original_style = capture.get_long(hwnd, -20)
        capture.set_long(hwnd, -20, original_style | 0x00080000)  # WS_EX_LAYERED on our fixture only.
        require(capture.get_long(hwnd, -20) & 0x00080000, 'Owned fixture layered style was not applied')
        require(u.SetLayeredWindowAttributes(hwnd, 0, 255, 2), 'Owned layered fixture opacity setup failed')
        require(u.SetWindowDisplayAffinity(hwnd, 0x11), 'Owned window capture exclusion could not be set')
        try:
            affinity = W.DWORD()
            require(u.GetWindowDisplayAffinity(hwnd, ctypes.byref(affinity)) and affinity.value != 0,
                    'Owned capture exclusion was not applied')
            rejects(lambda: backend.capture(target, rect, roi), 'protected_window_passed', {'protected'})
        finally:
            require(u.SetWindowDisplayAffinity(hwnd, 0), 'Owned window capture exclusion could not be restored')
            capture.set_long(hwnd, -20, original_style)
        pump()
        before = len(processes)
        rejects(lambda: backend.capture(target, rect, roi, cancelled=lambda: True),
                'cancel_before_launch_passed', {'cancelled'})
        require(len(processes) == before, 'Pre-cancel launched a capture process')
        # CREATE_SUSPENDED starts only the verified owned helper. Its first instruction
        # cannot execute; the production wrapper must kill/reap it on timeout/cancel.
        # This is OS watchdog evidence, not an artificial successful WGC frame.
        def suspended_popen(args, *more, **kwargs):
            kwargs['creationflags'] = kwargs.get('creationflags', 0) | 0x00000004
            return recording_popen(args, *more, **kwargs)
        wgc_capture.subprocess.Popen = suspended_popen
        try:
            rejects(lambda: backend.capture(target, rect, roi), 'timeout_watchdog_passed', {'timeout'})
            cancel_at = time.monotonic() + .2
            rejects(lambda: backend.capture(target, rect, roi, cancelled=lambda: time.monotonic() >= cancel_at),
                    'cancel_during_wait_passed', {'cancelled'})
        finally:
            wgc_capture.subprocess.Popen = recording_popen
        def destroy_owned():
            window.close(); window.destroy()
            require(not u.IsWindow(hwnd), 'Owned HWND did not close')
        reject_after_snapshot(destroy_owned, 'destroy_stale_passed')
        result['helper_process_count'] = len(processes)
        require(processes and all(process.poll() is not None for process in processes), 'Owned WGC helper leaked')
        require(getattr(backend, '_pending_cleanup', None) is None
                and getattr(getattr(capture, '_wgc', None), '_pending_cleanup', None) is None,
                'WGC wrapper still has pending helper cleanup')
        result['helpers_exited_passed'] = True
        require(all(not thread.is_alive() for process in processes
                    for name in ('stdout_thread', 'stderr_thread', '_stdout_thread', '_stderr_thread')
                    if (thread := getattr(process, name, None)) is not None),
                'Owned helper pipe reader thread leaked')
        result['pipe_readers_exited_passed'] = True
        require(jobs and all(job.handle is None for job in jobs), 'Owned capture Job handle leaked')
        result['job_handles_closed_passed'] = True
    finally:
        wgc_capture.subprocess.Popen = original_popen
        wgc_capture._CaptureJob = original_job
        for job in jobs: job.close()
        leaked = [process for process in processes if process.poll() is None]
        for process in leaked:
            process.kill(); process.wait(timeout=5)
        for widget in (cover, window):
            if widget is not None:
                widget.close(); widget.destroy()
        if app is not None:
            app.processEvents()
        result['windows_closed_passed'] = all(widget is None or not widget.isVisible() for widget in (window, cover))
        u.SetThreadDpiAwarenessContext(old_dpi)
        require(not leaked, 'Cleanup found a live owned capture helper')


def run(report_path):
    result = {'schema_version': 1, 'status': 'failed', 'applicationVersion': __version__,
              'frozen': bool(getattr(sys, 'frozen', False)), 'scope': SCOPE}
    code = 1
    try:
        execute(result)
        require(all(result.get(field) is True for field in CHECK_FIELDS), 'WGC evidence is incomplete')
        result['status'] = 'passed'
        code = 0
    except Exception as exc:
        result.update(error_type=type(exc).__name__, error=str(exc)[:2000])
    finally:
        path = Path(report_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + '.tmp')
        temporary.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
        temporary.replace(path)
    return code

"""Narrow production owner for the separately validated, immutable WGC session.

One exact owned opaque overlay may be registered for GPU-only idle. CPU capture
remains strict-hidden by default. A separately opted-in investigation permits
only that exact excluded overlay while retaining every other authorization gate.
Retirement revokes synchronously; potentially blocking close/reap work is owned
by a daemon worker. No teardown latency or fullscreen compatibility is promised.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import threading
from types import MappingProxyType

from session_windows import process_metadata
from wgc_capture import WgcError, WgcUnavailable


def _new_session(*, allow_visible_overlay=False):
    from wgc_session_capture import WgcSessionCapture
    return WgcSessionCapture(experimental=True, allow_visible_overlay=allow_visible_overlay)


@dataclass(frozen=True)
class OverlayRegistration:
    hwnd: int
    extended_style: int
    generation: int


@dataclass
class _SessionOwner:
    binding: tuple
    session: object = None
    revoked: threading.Event = field(default_factory=threading.Event)
    setup_done: threading.Event = field(default_factory=threading.Event)
    call_done: threading.Event = field(default_factory=threading.Event)
    close_done: threading.Event = field(default_factory=threading.Event)
    cleanup_worker: object = None


class PersistentCaptureAdapter:
    """Short GUI lifecycle methods; capture and helper verification are worker-only.

    The single owner stays strongly referenced through construction, retirement,
    native process/pipe/Job cleanup AND the last in-flight capture call. Never
    replace it merely because close() returned or because its helper exited.
    """
    def __init__(self, overlay_check, *, session_factory=None, enabled=True, allow_visible_overlay=False):
        if type(allow_visible_overlay) is not bool:
            raise TypeError('Visible overlay capability requires a boolean')
        self._allow_visible_overlay = allow_visible_overlay
        self._overlay_check = overlay_check
        self._enabled = bool(enabled)
        self._interactive_overlay = False
        self._prepared_visible_mode = False
        self._last_receipt = None
        self._factory = session_factory or _new_session
        self._lock = threading.Lock()
        self._call_lock = threading.Lock()
        self._owner = None
        self._overlay = None
        self._generation = self._epoch = 0
        self._closed = False
        self._persistent_required = False
        self._unavailable = None

    @property
    def visible_capture_status(self):
        """Bounded routing reason only; never a grant or native exclusion proof."""
        with self._lock:
            if self._closed:return 'stopped'
            if not self._allow_visible_overlay:return 'disabled'
            if not self._enabled or self._unavailable is not None:return 'backend_unavailable'
            if self._interactive_overlay:return 'interactive'
            if self._overlay is None:return 'exclusion_unregistered'
            owner=self._owner
            if owner is not None and not self._complete(owner) and (owner.revoked.is_set() or self._native_revoked(owner)):
                return 'cleanup_pending'
            return 'eligible'

    @property
    def can_request_visible_overlay(self):
        """GUI-safe routing hint, NOT proof of exclusion or a capture permit.

        Each request must opt in again and independently pass every live guard.
        No helper construction, metadata query, wait or native call occurs here.
        """
        with self._lock:
            owner = self._owner
            return bool(self._allow_visible_overlay and self._enabled and not self._closed
                        and not self._interactive_overlay and self._overlay is not None
                        and self._unavailable is None
                        and (owner is None or self._complete(owner)
                             or not owner.revoked.is_set() and not self._native_revoked(owner)))

    def prepare_capture_mode(self, visible, *, overlay_window_style=None):
        """GUI-safe planned transition; never constructs, captures, or falls back.

        False means wait for cleanup; unavailable/closed modes raise WgcError.
        A caller may make a NEW explicit request only after True. The optional style is
        a routing snapshot, never authorization; native guards still prove it.
        """
        if type(visible) is not bool:
            raise TypeError('Visible overlay mode requires a boolean')
        if overlay_window_style is not None and (type(overlay_window_style) is not int
                or not 0 <= overlay_window_style < 2**32):
            raise TypeError('Overlay standard style requires an unsigned integer')
        with self._lock:
            if self._closed:
                raise WgcError('cancelled', '窗口截图已关闭。')
            owner = self._owner
            changed = self._prepared_visible_mode != visible
            if changed:
                self._prepared_visible_mode = visible
            mismatch = owner is not None and owner.binding[-1] != visible
            if owner is not None and visible and owner.session is not None:
                expected = getattr(owner.session, '_overlay_window_style', None)
                mismatch = mismatch or (overlay_window_style is not None and expected is not None
                                        and overlay_window_style != expected)
            invalid = owner is not None and self._native_revoked(owner)
            if changed or mismatch or invalid:
                self._epoch += 1
                self._last_receipt = None
                self._retire_locked()
            if owner is not None and owner.revoked.is_set():
                if not self._complete(owner):
                    return False
                self._owner = None
            if visible and (not self._allow_visible_overlay or not self._enabled
                    or self._interactive_overlay or self._overlay is None or self._unavailable is not None):
                raise WgcError('visible-overlay-unavailable', '可见叠加捕获未获授权或不可用；请隐藏叠加后再请求截图。')
            return True

    @property
    def last_receipt(self):
        with self._lock:
            return None if self._last_receipt is None else MappingProxyType(dict(self._last_receipt))

    @staticmethod
    def _receipt(session, overlay):
        """Optional bounded evidence; no pixels, paths or raw lifetime token.

        A failed diagnostic query never invents evidence or relaxes any gate.
        The exact Popen-owned helper must still be alive before and after its
        metadata query, so a reused numeric PID cannot enter this receipt.
        """
        try:
            timing = dict(session.last_timing or {})
            keys = {'request_cutoff_100ns', 'frame_100ns', 'idle_enter_100ns',
                    'request_id', 'session_generation'}
            if set(timing) != keys or any(type(v) is not int or not 0 < v < 2**63 for v in timing.values()):
                return None
            if not timing['request_cutoff_100ns'] < timing['frame_100ns'] <= timing['idle_enter_100ns']:
                return None
            transport = session._transport
            process = transport.process
            registered = session._overlay
            if (transport.revoked.is_set() or process is None or process.poll() is not None
                    or transport.generation != timing['session_generation']
                    or type(process.pid) is not int or not 0 < process.pid < 2**32
                    or len(registered) != 3 or registered[:2] != (overlay.hwnd, overlay.extended_style)
                    or type(registered[2]) is not int or not 0 < registered[2] < 2**63):
                return None
            helper = process_metadata(process.pid)
            if type(helper.created) is not int or not 0 < helper.created < 2**63:
                return None
            from wgc_session_capture import _window_api, _property_name
            user = _window_api()
            registration_valid = user.GetPropW(overlay.hwnd, _property_name(registered[2])) == registered[2]
            if (not registration_valid or process.poll() is not None or transport.revoked.is_set()
                    or session._transport is not transport):
                return None
            return dict(timing, helper_pid=process.pid, helper_created=helper.created,
                overlay_hwnd=overlay.hwnd, overlay_extended_style=overlay.extended_style,
                overlay_affinity=0x11, overlay_registration_valid=True)
        except (OSError, ValueError, TypeError, AttributeError):
            return None

    @property
    def epoch(self):
        with self._lock:
            return self._epoch

    def cancelled_since(self, epoch):
        with self._lock:
            return self._closed or epoch != self._epoch

    @property
    def overlay(self):
        with self._lock:
            return self._overlay

    @staticmethod
    def _native_revoked(owner):
        # Frozen wrapper's transport exposes the revocation Event. Its capture()
        # can otherwise replace a retired transport within the same instance;
        # production instead retires the entire immutable instance.
        transport = getattr(owner.session, '_transport', None)
        return bool(transport is not None and transport.revoked.is_set())

    @staticmethod
    def _complete(owner):
        return (owner.revoked.is_set() and owner.close_done.is_set()
                and owner.call_done.is_set()
                and (owner.session is None or not owner.session.cleanup_pending))

    @property
    def cleanup_pending(self):
        with self._lock:
            owner = self._owner
            return bool(owner is not None and (owner.revoked.is_set()
                        or self._native_revoked(owner)) and not self._complete(owner))

    def _cleanup(self, owner):
        # Construction/registration may still be underway on the capture worker.
        # Retain its placeholder until it publishes the exact session to close.
        owner.setup_done.wait()
        try:
            if owner.session is not None:
                owner.session.close()
        except BaseException:
            return  # Keep ownership and replacement blocked on unconfirmed close.
        owner.close_done.set()

    def _retire_locked(self):
        owner = self._owner
        if owner is None or owner.revoked.is_set():
            return
        owner.revoked.set()
        self._last_receipt = None
        worker = threading.Thread(target=self._cleanup, args=(owner,),
                                  name='wgc-adapter-retire', daemon=True)
        owner.cleanup_worker = worker
        try:
            worker.start()
        except RuntimeError:
            pass  # Revocation remains immediate; failed cleanup blocks replacement.

    def retire(self):
        """GUI-safe revocation, including captures still being constructed."""
        with self._lock:
            self._epoch += 1
            self._last_receipt = None
            self._retire_locked()

    def close(self):
        with self._lock:
            self._closed = True
            self._last_receipt = None
            self._epoch += 1
            self._overlay = None
            self._retire_locked()

    def set_interactive_overlay(self, enabled):
        """Explicit user mode only; never called by capability/error handling.

        Changing mode cancels the current request. Later strict-hide one-shot
        requests are allowed only after the complete v2 ownership barrier. The
        automatic failure policy remains sticky when returning to persistence.
        """
        if type(enabled) is not bool:
            raise TypeError('Interactive overlay mode requires a boolean')
        with self._lock:
            if self._closed or self._interactive_overlay == enabled:
                return
            self._interactive_overlay = enabled
            self._epoch += 1
            self._last_receipt = None
            self._retire_locked()
            # Both directions invalidate the old enrollment. A later persistent
            # request requires a fresh live opaque/style/affinity registration.
            self._overlay = None
            self._generation += 1

    def set_overlay(self, hwnd=None, extended_style=None):
        """Publish only a GUI-verified exact opaque/owned/style/0x11 snapshot."""
        with self._lock:
            if self._closed:
                return
            previous = self._overlay
            if (previous is None and hwnd is None) or (previous is not None
                    and (previous.hwnd, previous.extended_style) == (hwnd, extended_style)):
                return
            self._epoch += 1
            self._last_receipt = None
            self._retire_locked()
            self._generation += 1
            self._overlay = (None if hwnd is None else
                             OverlayRegistration(hwnd, extended_style, self._generation))

    def check_ready(self):
        """Never let either v1 or v2 start while v2 cleanup is unconfirmed."""
        with self._lock:
            if self._closed:
                raise WgcError('cancelled', '窗口截图已关闭。')
            owner = self._owner
            if owner is not None and self._native_revoked(owner):
                self._retire_locked()
            if owner is not None and owner.revoked.is_set():
                if not self._complete(owner):
                    raise WgcError('cleanup-pending', '上一次窗口捕获尚未确认关闭，暂不启动新截图。')
                self._owner = None

    def capture(self, target, rect, pixel_roi, *, cancelled, expected_metadata=None,
                allow_visible_overlay=False):
        """Return None ONLY for an eligible pre-use compatibility route.

        A denied/blank/stale/timed-out session never authorizes a one-shot retry.
        An initial native unsupported result retires first; a later call may use
        compatibility capture only after complete cleanup is observed.
        """
        if type(allow_visible_overlay) is not bool:
            raise TypeError('Visible overlay request requires a boolean')
        if not self._call_lock.acquire(blocking=False):
            raise WgcError('busy', '已有窗口截图请求尚未结束。')
        owner = None
        try:
            self.check_ready()
            with self._lock:
                self._last_receipt = None
                if allow_visible_overlay and (not self._allow_visible_overlay
                        or not self._enabled or self._interactive_overlay
                        or self._overlay is None or self._unavailable is not None):
                    raise WgcError('visible-overlay-unavailable', '可见叠加捕获未获授权或不可用；请隐藏叠加后再请求截图。')
                if not self._enabled or self._interactive_overlay:
                    return None
                overlay = self._overlay
                if overlay is None or self._unavailable:
                    if self._persistent_required:
                        raise WgcError('stale', '持续捕获所需的叠加排除条件已变化，已跳过本帧。')
                    return None
            if cancelled():
                raise WgcError('cancelled', '截图已取消。')
            if allow_visible_overlay:
                self._overlay_check(overlay, allow_visible_overlay=True)
            else:
                self._overlay_check(overlay)
            metadata = process_metadata(target.pid)
            if (type(metadata.created) is not int or metadata.created <= 0
                    or expected_metadata is not None and metadata != expected_metadata):
                raise WgcError('stale', '原授权窗口进程已经变化。')
            binding = (tuple(target.identity), metadata, rect, overlay, allow_visible_overlay)
            with self._lock:
                if self._closed or self._overlay != overlay:
                    raise WgcError('cancelled', '叠加注册已经变化，已跳过本帧。')
                owner = self._owner
                if owner is not None and owner.binding != binding:
                    self._retire_locked()
                    raise WgcError('stale', '窗口或进程身份、客户区位置或尺寸已变化，已关闭原捕获会话。')
                if owner is None:
                    owner = self._owner = _SessionOwner(binding)
                owner.call_done.clear()
            if owner.session is None:
                try:
                    session = (self._factory(allow_visible_overlay=True) if allow_visible_overlay
                               else self._factory())
                except WgcUnavailable as error:
                    was_cancelled = cancelled()
                    # The frozen constructor only verifies files; it cannot
                    # launch a helper. A missing optional pair permits v1/GDI
                    # only before any persistent request has become required.
                    with self._lock:
                        if (error.status not in ('missing-helper', 'unsupported')
                                or self._persistent_required or owner.revoked.is_set()
                                or self._closed or was_cancelled):
                            raise WgcError(error.status, str(error)) from error
                        self._unavailable = error.status
                        if not allow_visible_overlay:
                            self._owner = None
                    if allow_visible_overlay:
                        # Even a pre-launch capability failure ends this request.
                        # A later hidden request must pass the cleanup barrier.
                        raise WgcError(error.status, str(error)) from error
                    return None
                owner.session = session
                if owner.revoked.is_set() or cancelled():
                    raise WgcError('cancelled', '截图已取消。')
                session.register_idle_overlay(overlay.hwnd, overlay.extended_style, overlay.generation)
                owner.setup_done.set()
            if owner.revoked.is_set() or cancelled():
                raise WgcError('cancelled', '截图已取消。')
            with self._lock:
                previously_required = self._persistent_required
                self._persistent_required = True
            try:
                image = owner.session.capture(target, rect, pixel_roi,
                    cancelled=lambda: owner.revoked.is_set() or cancelled(),
                    expected_metadata=metadata)
            except WgcUnavailable as error:
                was_cancelled=cancelled()
                with self._lock:
                    if (error.status == 'unsupported' and not previously_required
                            and not owner.revoked.is_set() and not was_cancelled):
                        self._persistent_required = False
                        self._unavailable = error.status
                # No fallback in the failed request, even for unsupported. Its
                # exact helper must finish cleanup before the later v1 request.
                raise WgcError(error.status, str(error)) from error
            if image is None:
                raise WgcError('invalid-reply', '持续捕获未返回有效画面，已跳过本帧。')
            if allow_visible_overlay:
                self._overlay_check(overlay, allow_visible_overlay=True)
            else:
                self._overlay_check(overlay)
            if (owner.revoked.is_set() or cancelled()
                    or process_metadata(target.pid) != metadata):
                raise WgcError('stale', '截图期间授权或进程身份发生变化，已丢弃本帧。')
            receipt = self._receipt(owner.session, overlay)
            with self._lock:
                if owner.revoked.is_set() or self._closed or self._native_revoked(owner):
                    raise WgcError('cancelled', '截图会话已失效，已丢弃本帧。')
                self._last_receipt = receipt
            return image
        except BaseException as error:
            with self._lock:
                if owner is not None and self._unavailable is None:
                    self._persistent_required = True
                self._retire_locked()
            if isinstance(error, (OSError, ValueError)):
                raise WgcError('stale', '无法核验窗口捕获会话，已跳过本帧。') from error
            raise
        finally:
            if owner is not None:
                owner.setup_done.set()
                owner.call_done.set()
            self._call_lock.release()

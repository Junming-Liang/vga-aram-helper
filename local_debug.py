"""Opt-in, bounded local diagnostics. No network, screenshots or free-text logs.

Every value passes an allowlist on write AND export. Window/process identities
are per-launch salted aliases; raw HWNDs, PIDs, executable paths and titles are
never serialized. Enabling is intentionally not persisted between launches.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import re
import secrets
import tempfile
import threading
import time
import zipfile

MAX_BYTES = 256 * 1024
FILE_COUNT = 3
EXPORT_OVERHEAD_BYTES = 64 * 1024
MAX_EXPORT_BYTES = MAX_BYTES * FILE_COUNT + EXPORT_OVERHEAD_BYTES
_EVENTS = frozenset({'debug_enabled', 'debug_disabled', 'state', 'job', 'capture',
                     'recognition', 'overlay', 'expiry', 'invalidate', 'cancel', 'session', 'close'})
_ENUMS = {
    'kind': frozenset({'load', 'portraits', 'update', 'install', 'windows', 'ocr',
                       'selection', 'capture-proof', 'unknown'}),
    'phase': frozenset({'queued', 'started', 'completed', 'error', 'cancelled',
                        'discarded', 'requested', 'retired', 'acquired'}),
    'backend': frozenset({'windows-graphics-capture-session', 'windows-graphics-capture',
                          'bounded-compositor', 'window-dc', 'unknown'}),
    'state': frozenset({'error', 'waiting', 'idle', 'working', 'confirmed', 'provisional'}),
    'stage': frozenset({'idle', 'waiting', 'unassigned', 'assigning', 'assigned', 'transition', 'game-provisional',
                        'game-verified', 'client-expired', 'game-expired', 'unknown'}),
    'reason': frozenset({'enabled', 'disabled', 'start', 'stop', 'close', 'invalidate',
                         'capture_wait', 'capture_pending', 'capture_failed',
                         'capture_cancelled', 'capture_proof', 'unconfirmed',
                         'client_reference', 'confirmed', 'focus_lost', 'geometry_changed',
                         'target_unavailable', 'layout', 'layout_error', 'click_through',
                         'ttl_client', 'ttl_game', 'ocr_timeout', 'generation_changed',
                         'serial_changed', 'stopped', 'closed', 'worker_error',
                         'selection_changed', 'stale_frame', 'mode_wait', 'hero_unknown',
                         'candidate_missing', 'candidate_untrusted', 'candidate_layout',
                         'partial_confirmed', 'title_dictionary_miss', 'title_low_confidence',
                         'awaiting_confirmation', 'source_tier_missing', 'recognized',
                         'discovery_stopped', 'window_not_found', 'window_identity_unverified',
                         'multiple_installations', 'multiple_windows', 'signature_unverified',
                         'client_connected', 'game_connected', 'window_gone', 'window_identity_changed',
                         'window_hidden', 'client_rect_failed', 'client_rect_unsupported', 'focus_rejected',
                         'capture_protected', 'foreign_occlusion', 'monitor_bounds', 'blank_frame',
                         'capture_unavailable', 'capture_paused', 'unknown'}),
    'error_code': frozenset({'capture_paused', 'capture_unavailable', 'worker_error'}),
}
_BOOLS = frozenset({'running', 'confirmed', 'ocr_busy', 'capture_pending', 'visible',
                    'rechecking', 'click_through', 'visible_capture', 'cancelled',
                    'ocr_reused', 'hero_present', 'manual_editing', 'fresh'})
# session_generation is the small SelectionSession counter, never a native token.
_INTS = frozenset({'generation', 'session_generation', 'serial', 'width', 'height',
                   'stable_frames', 'automatic_frames', 'hero_stable_frames',
                   'hero_revision', 'candidate_revision', 'candidate_count'})
_FLOATS = frozenset({'capture_ms', 'inference_ms', 'queue_ms', 'prepare_ms', 'hud_ms', 'ocr_ms', 'dispatch_ms', 'elapsed_ms', 'age_ms', 'ttl_ms', 'dpi'})
_IDENTITIES = frozenset({'window_id', 'process_id'})
_CONFIG_BOOLS = frozenset({'hero_auto', 'client_follow', 'click_through',
                           'visible_capture', 'frozen', 'updates_enabled'})


def _number(value, limit):
    return type(value) in (int, float) and 0 <= value <= limit and math.isfinite(value)


def _fields(values):
    """Never coerce arbitrary values to strings; unknown fields disappear."""
    clean = {}
    for key, value in values.items():
        if key in _ENUMS and type(value) is str and value in _ENUMS[key]:
            clean[key] = value
        elif key in _BOOLS and type(value) is bool:
            clean[key] = value
        elif key in _INTS and type(value) is int and 0 <= value <= 2**53:
            clean[key] = value
        elif key in _FLOATS and _number(value, 86400000):
            clean[key] = round(value, 3)
        elif key in _IDENTITIES and type(value) is str and re.fullmatch(r'[0-9a-f]{16}', value):
            clean[key] = value
    return clean


def safe_config(config):
    clean = {key: value for key, value in config.items()
             if key in _CONFIG_BOOLS and type(value) is bool}
    roi = config.get('roi_percent')
    if type(roi) in (list, tuple) and len(roi) == 4 and all(type(v) is int and 0 <= v <= 100 for v in roi):
        clean['roi_percent'] = list(roi)
    return clean


class LocalDebugLog:
    def __init__(self, directory, *, version, max_bytes=MAX_BYTES):
        self.directory = Path(directory)
        self.version = version if type(version) is str and re.fullmatch(r'\d{1,3}\.\d{1,3}\.\d{1,3}(?:[-+][A-Za-z0-9.-]{1,32})?', version) else 'unknown'
        if type(max_bytes) is not int or not 512 <= max_bytes <= MAX_BYTES:
            raise ValueError('Invalid diagnostic size limit')
        self.max_bytes = max_bytes
        self.enabled = False
        self.failed = False
        self._lock = threading.RLock()
        self._salt = secrets.token_bytes(32)
        self._session = secrets.token_hex(8)
        self._started = time.monotonic()

    def _path(self, index=0):
        return self.directory / ('events.jsonl' if index == 0 else f'events.{index}.jsonl')

    @staticmethod
    def _owned_directory(path):
        if path.is_symlink():
            raise OSError('Diagnostic directory must not be a symlink')
        path.mkdir(parents=True, exist_ok=True)

    def identity(self, hwnd, pid, created=None):
        """Accept numeric identity only; no process metadata/path serialization."""
        if not all(type(v) is int and 0 < v < 2**64 for v in (hwnd, pid)):
            return {}
        if created is not None and not (type(created) is int and 0 <= created < 2**64):
            return {}
        process = f'{pid}:{created if created is not None else 0}'
        alias = lambda value: hmac.new(self._salt, value.encode('ascii'), hashlib.sha256).hexdigest()[:16]
        return {'window_id': alias(f'window:{hwnd}:{process}'),
                'process_id': alias(f'process:{process}')}

    def set_enabled(self, enabled):
        if type(enabled) is not bool:
            raise TypeError('Diagnostic toggle requires a boolean')
        with self._lock:
            if enabled == self.enabled:
                return self.enabled
            if not enabled:
                self.record('debug_disabled', reason='disabled')
                self.enabled = False
                return False
            self.enabled = True
            self.failed = False
            self.record('debug_enabled', reason='enabled')
            return self.enabled

    def record(self, event, **values):
        with self._lock:
            if not self.enabled or type(event) is not str or event not in _EVENTS:
                return False
            record = {'event': event, 'session': self._session,
                      'elapsed_ms': round(max(0, time.monotonic() - self._started) * 1000, 3),
                      **_fields(values)}
            encoded = (json.dumps(record, ensure_ascii=True, separators=(',', ':'), allow_nan=False) + '\n').encode('utf8')
            if len(encoded) > self.max_bytes:
                return False
            try:
                self._owned_directory(self.directory)
                paths = [self._path(index) for index in range(FILE_COUNT)]
                if any(path.is_symlink() for path in paths):
                    raise OSError('Diagnostic files must not be symlinks')
                if paths[0].exists() and paths[0].stat().st_size + len(encoded) > self.max_bytes:
                    paths[-1].unlink(missing_ok=True)
                    for index in range(FILE_COUNT - 2, -1, -1):
                        if paths[index].exists():
                            paths[index].replace(paths[index + 1])
                with paths[0].open('ab') as output:
                    output.write(encoded)
                return True
            except OSError:
                # Diagnostics must never interrupt capture or disclose raw errors.
                self.enabled = False
                self.failed = True
                return False

    def _safe_events(self):
        lines = []
        if self.directory.is_symlink():
            raise OSError('Diagnostic directory must not be a symlink')
        for index in reversed(range(FILE_COUNT)):
            path = self._path(index)
            if path.is_symlink():
                raise OSError('Diagnostic files must not be symlinks')
            if not path.exists():
                continue
            # A corrupted/replaced file cannot make export read unbounded data.
            with path.open('rb') as source:
                raw = source.read(self.max_bytes + 1)
            if len(raw) > self.max_bytes:
                continue
            for line in raw.splitlines():
                try:
                    value = json.loads(line)
                    if type(value) is not dict or value.get('event') not in _EVENTS:
                        continue
                    session = value.get('session')
                    if type(session) is not str or not re.fullmatch(r'[0-9a-f]{16}', session):
                        continue
                    clean = {'event': value['event'], 'session': session, **_fields(value)}
                    lines.append(json.dumps(clean, separators=(',', ':'), allow_nan=False) + '\n')
                except (ValueError, TypeError, UnicodeError, RecursionError):
                    continue
        return ''.join(lines)

    def export_zip(self, directory, *, config):
        """One local latest ZIP; never glob a directory, attach files or upload.

        Replaces only our fixed export filename atomically, bounding repeated
        button clicks to one archive. Old log files are privacy-filtered again.
        """
        directory = Path(directory)
        with self._lock:
            events = self._safe_events().encode('utf8')
            if len(events) > self.max_bytes * FILE_COUNT:
                raise ValueError('Diagnostic export exceeded event budget')
            manifest = {'schema': 1, 'app_version': self.version,
                        'config': safe_config(config),
                        'privacy': 'Local only; no screenshots, recognized text, titles, paths, raw errors or credentials.',
                        'log_limit_bytes': self.max_bytes * FILE_COUNT,
                        'identity_scope': 'Random per-launch aliases; raw HWND/PID excluded.'}
            self._owned_directory(directory)
            target = directory / 'VGA-debug.zip'
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(prefix='.vga-debug-', suffix='.tmp', dir=directory, delete=False) as file:
                    temporary = Path(file.name)
                with zipfile.ZipFile(temporary, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
                    archive.writestr('manifest.json', json.dumps(manifest, ensure_ascii=True, indent=2))
                    archive.writestr('events.jsonl', events)
                if temporary.stat().st_size > self.max_bytes * FILE_COUNT + EXPORT_OVERHEAD_BYTES:
                    raise ValueError('Diagnostic export exceeded ZIP budget')
                os.replace(temporary, target)
                return target
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)

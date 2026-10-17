"""Bounded local diagnostics (the UI selects the per-launch enabled state). No network, screenshots or free-text logs.

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
                     'recognition', 'overlay', 'expiry', 'invalidate', 'cancel', 'session', 'close', 'inference', 'sample_summary'})
_ENUMS = {
    'kind': frozenset({'load', 'portraits', 'update', 'install', 'windows', 'ocr',
                       'selection', 'capture-proof', 'unknown'}),
    'phase': frozenset({'queued', 'started', 'completed', 'error', 'cancelled',
                        'shown', 'hidden', 'rechecking', 'discarded', 'requested', 'retired', 'acquired', 'prepared', 'hud_started', 'hud_completed', 'ocr_started', 'ocr_completed', 'accepted'}),
    'capture_mode': frozenset({'eligible','disabled','backend_unavailable','interactive','exclusion_unregistered','cleanup_pending','stopped','unknown'}),
    'backend': frozenset({'windows-graphics-capture-session', 'windows-graphics-capture',
                          'bounded-compositor', 'window-dc', 'unknown'}),
    'state': frozenset({'error', 'waiting', 'idle', 'working', 'confirmed', 'provisional'}),
    'stage': frozenset({'idle', 'waiting', 'unassigned', 'assigning', 'assigned', 'transition', 'game-provisional',
                        'game-verified', 'client-expired', 'game-expired', 'unknown'}),
    'reason': frozenset({'enabled', 'disabled', 'start', 'stop', 'close', 'invalidate',
                         'capture_wait', 'capture_pending', 'capture_failed',
                         'capture_cancelled', 'capture_proof', 'unconfirmed',
                         'client_reference', 'confirmed', 'focus_lost', 'geometry_changed',
                         'card_geometry_changed', 'card_geometry_missing', 'cards_changed', 'invalid_slots', 'reference_changed',
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
                         'capture_unavailable', 'capture_paused', 'display_wait', 'geometry_unproven', 'title_changed', 'hero_conflict', 'no_previous', 'stale_previous', 'interactive', 'backend_unavailable', 'exclusion_unregistered', 'cleanup_pending', 'unknown'}),
    'error_code': frozenset({'capture_paused', 'capture_unavailable', 'worker_error'}),
}
# Mirror the fixed capture vocabulary without importing platform capture code.
_CAPTURE_ENUMS = {
    'capture_status': frozenset(('ok','pending','unknown','missing-helper','unsupported',
        'backend-error','cancelled','cleanup-pending','invalid-reply','stale','timeout',
        'untrusted-helper','busy','visible-overlay-unavailable','experiment-disabled',
        'protected','capture_paused','capture_unavailable','window_gone','window_identity_changed',
        'window_hidden','client_rect_failed','client_rect_unsupported','focus_rejected',
        'capture_protected','foreign_occlusion','geometry_changed','monitor_bounds','blank_frame')),
    'session_status': frozenset(('used','disabled','interactive','exclusion-unregistered',
        'missing-helper','unsupported','not-attempted','unknown')),
    'oneshot_status': frozenset(('used','missing-helper','unsupported','not-attempted','unknown')),
    'fallback_reason': frozenset(('none','session-disabled','session-interactive',
        'session-unregistered','session-missing-helper','session-unsupported',
        'oneshot-missing-helper','oneshot-unsupported','window-dc-unavailable',
        'window-dc-copy-failed','window-dc-blank','unknown')),
}
_ENUMS.update(_CAPTURE_ENUMS)
_ENUMS['inference_stage'] = frozenset({'prepare', 'hud_prepare', 'hud_match', 'hero_resolve', 'ocr', 'title_geometry', 'selection', 'total'})
_ENUMS['hero_source'] = frozenset({'hud', 'game-api', 'game-continuity', 'client-provisional', 'client-verified', 'manual', 'lcu-read-only', 'selection-pixels', 'unknown'})
_ENUMS['sampled_event'] = _EVENTS - {'sample_summary'}
_BOOLS = frozenset({'running', 'confirmed', 'ocr_busy', 'capture_pending', 'visible',
                    'rechecking', 'click_through', 'visible_capture', 'cancelled',
                    'ocr_cold_start', 'ocr_reused', 'hero_present', 'manual_editing', 'fresh', 'catalog_match', 'tier_present'})
# session_generation is the small SelectionSession counter, never a native token.
_INTS = frozenset({'generation', 'session_generation', 'serial', 'width', 'height',
                   'stable_frames', 'automatic_frames', 'hero_stable_frames',
                   'hero_revision', 'candidate_revision', 'candidate_count',
                   'sequence', 'game_generation', 'sample_count', 'first_serial', 'last_serial'})
_FLOATS = frozenset({'capture_ms', 'inference_ms', 'queue_ms', 'prepare_ms', 'hud_ms', 'ocr_ms', 'dispatch_ms', 'elapsed_ms', 'age_ms', 'ttl_ms', 'settle_ms', 'dpi'})
_TIMINGS = _FLOATS - {'dpi', 'elapsed_ms'}
_SUMMARY_FLOATS = frozenset(f'{key}_{suffix}' for key in _TIMINGS for suffix in ('min', 'max', 'mean'))
_FLOATS = _FLOATS | _SUMMARY_FLOATS | {'first_elapsed_ms', 'last_elapsed_ms'}
_IDENTITIES = frozenset({'window_id', 'process_id'})
_CONFIG_BOOLS = frozenset({'hero_auto', 'client_follow', 'click_through',
                           'visible_capture', 'frozen', 'updates_enabled', 'lcu_selection', 'live_identity'})


def _number(value, limit):
    return type(value) in (int, float) and 0 <= value <= limit and math.isfinite(value)


def _fields(values):
    """Never coerce arbitrary values to strings; unknown fields disappear."""
    clean = {}
    for key, value in values.items():
        if key in _ENUMS and type(value) is str and value in _ENUMS[key]:
            clean[key] = value
        elif key == 'slot' and type(value) is int and 0 <= value <= 2:
            clean[key] = value
        elif key in ('confidence', 'threshold') and _number(value, 1):
            clean[key] = round(value, 4)
        elif key in _BOOLS and type(value) is bool:
            clean[key] = value
        elif key in _INTS and type(value) is int and 0 <= value <= 2**53:
            clean[key] = value
        elif key in ('elapsed_ms', 'first_elapsed_ms', 'last_elapsed_ms') and _number(value, 2**53):
            clean[key] = round(value, 3)
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
        self._sequence = 0
        self._game_generation = 0
        self._catalogs = {'hero_name': frozenset(), 'augment_name': frozenset()}
        self._sample_key = None
        self._pending = None
        self._summary = {'events': {}, 'reasons': {}, 'inference_stages': {}, 'timings': {},
                         'capture_statuses': {}, 'session_statuses': {}, 'oneshot_statuses': {}, 'fallback_reasons': {}}
        self._visibility = None
        self._hidden_since = None
        self._hidden_total_ms = 0.0
        self._hidden_max_ms = 0.0
        self._hide_transitions = 0
        self._show_transitions = 0
        self._counts = {'dropped_events': 0, 'dropped_fields': 0,
                        'truncated_events': 0, 'rotations': 0, 'aggregated_samples': 0}

    @staticmethod
    def _add_metric(bucket, value):
        bucket['count'] = min(2**53, bucket.get('count', 0) + 1)
        bucket['total_ms'] = round(min(2**53, bucket.get('total_ms', 0) + value), 3)
        bucket['max_ms'] = max(bucket.get('max_ms', 0), value)

    def _observe(self, event, values):
        """Fixed enum-key budgets, counted once per original observation.

        Independent of successful disk writes/rotation and synthetic summaries.
        No catalog names, serials, arbitrary strings, or identities become keys.
        """
        if event == 'sample_summary':
            return
        now = self._elapsed()
        # A stage-start notification is not a measured zero-duration run.
        # Keep observation counts while excluding it from latency denominators.
        if event == 'inference' and values.get('phase') == 'started':
            values = {key: value for key, value in values.items() if key != 'inference_ms'}
        preferred = {'capture': ('capture_ms', 'inference_ms'),
                     'inference': ('inference_ms',),
                     'recognition': ('inference_ms', 'ocr_ms'),
                     'job': ('queue_ms', 'dispatch_ms')}.get(event, ('settle_ms',))
        duration = next((values[key] for key in preferred if key in values), None)
        dimensions = [('events', event)]
        if 'reason' in values:
            dimensions.append(('reasons', values['reason']))
        if 'inference_stage' in values:
            dimensions.append(('inference_stages', values['inference_stage']))
        for field, dimension in (('capture_status', 'capture_statuses'), ('session_status', 'session_statuses'),
                                 ('oneshot_status', 'oneshot_statuses'), ('fallback_reason', 'fallback_reasons')):
            if field in values:
                dimensions.append((dimension, values[field]))
        for dimension, key in dimensions:
            bucket = self._summary[dimension].setdefault(key, {'observations': 0, 'latency': {}})
            bucket['observations'] = min(2**53, bucket['observations'] + 1)
            if duration is not None:
                self._add_metric(bucket['latency'], duration)
        for key in (_TIMINGS - {'age_ms', 'ttl_ms'}) & values.keys():
            self._add_metric(self._summary['timings'].setdefault(key, {}), values[key])
        if event == 'overlay' and 'visible' in values and values.get('phase') != 'rechecking':
            visible = values['visible']
            if visible != self._visibility:
                if visible:
                    self._show_transitions = min(2**53, self._show_transitions + 1)
                    self._finish_hidden(now)
                else:
                    self._hide_transitions = min(2**53, self._hide_transitions + 1)
                    self._hidden_since = now
                self._visibility = visible
        if event == 'debug_disabled':
            self._finish_hidden(now)
            self._visibility = None

    def _finish_hidden(self, now):
        if self._hidden_since is not None:
            duration = max(0, now - self._hidden_since)
            self._hidden_total_ms = min(2**53, self._hidden_total_ms + duration)
            self._hidden_max_ms = max(self._hidden_max_ms, duration)
            self._hidden_since = None

    def _summary_snapshot(self):
        # JSON copy is bounded by enum dictionaries, not log/game length.
        result = json.loads(json.dumps(self._summary))
        open_ms = max(0, self._elapsed() - self._hidden_since) if self._hidden_since is not None else 0
        result['scope'] = 'current_launch_all_observations_including_coalesced_samples'
        result['overlay'] = {'observed_hide_transitions': self._hide_transitions,
                             'observed_show_transitions': self._show_transitions,
                             'hidden_total_ms': round(min(2**53, self._hidden_total_ms + open_ms), 3),
                             'hidden_max_ms': round(max(self._hidden_max_ms, open_ms), 3),
                             'open_hidden_ms': round(open_ms, 3)}
        return result

    def register_catalog(self, *, augment_names=(), hero_names=()):
        """Register trusted bundled vocabulary, NEVER OCR/user/account strings.

        Unknown names are omitted again at export. Registries are bounded and
        live only in memory; registering them does not enable diagnostics.
        """
        def names(values):
            result = set()
            for index, value in enumerate(values):
                if index >= 20000:
                    raise ValueError('Catalog exceeds diagnostic budget')
                if type(value) is str and 0 < len(value) <= 80 and all(ch.isprintable() for ch in value):
                    result.add(value)
            return frozenset(result)
        catalogs = {'hero_name': names(hero_names), 'augment_name': names(augment_names)}
        with self._lock:
            self.flush()
            self._catalogs = catalogs

    def _fields(self, values):
        clean = _fields(values)
        for key, names in self._catalogs.items():
            value = values.get(key)
            if type(value) is str and value in names:
                clean[key] = value
        return clean

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

    def _elapsed(self):
        return round(max(0, time.monotonic() - self._started) * 1000, 3)

    def begin_game(self):
        """Start a local numeric game scope, never accept a server/player ID."""
        with self._lock:
            self.flush()
            self._game_generation += 1
            self.record('session', phase='started')
            return self._game_generation

    def flush(self):
        """Write a pending repeated-sample summary; no background timer needed."""
        with self._lock:
            pending, self._pending = self._pending, None
            self._sample_key = None
            if pending is None:
                return True
            values = dict(pending['values'])
            values.update(sampled_event=pending['event'], sample_count=pending['count'],
                          first_elapsed_ms=pending['first'], last_elapsed_ms=pending['last'])
            if pending['serials']:
                values.update(first_serial=pending['serials'][0], last_serial=pending['serials'][1])
            for key, (low, high, total, count) in pending['timings'].items():
                values.update({key + '_min': low, key + '_max': high, key + '_mean': total / count})
            return self._write('sample_summary', values)

    def sample(self, event, **values):
        """Coalesce adjacent same-state observations, preserving every transition.

        First observation is immediate. A summary represents subsequent repeats
        only. Timing/serial changes do not change state; all other safe fields do.
        Emit after one second of repeated observations, or on record/flush/export.
        """
        with self._lock:
            if not self.enabled:
                return False
            if type(event) is not str or event not in _EVENTS or event == 'sample_summary':
                self._counts['dropped_events'] += 1
                return False
            clean = self._fields(values)
            self._counts['dropped_fields'] += len(values) - len(clean)
            # Context and timestamps are always generated, never caller supplied.
            for key in ('sequence', 'game_generation', 'elapsed_ms'):
                clean.pop(key, None)
            self._observe(event, clean)
            state = {key: value for key, value in clean.items() if key not in _TIMINGS and key != 'serial'}
            key = (event, tuple(sorted(state.items())))
            now = self._elapsed()
            if key != self._sample_key:
                self.flush()
                success = self._write(event, clean)
                if success:
                    self._sample_key = key
                return success
            if self._pending is None:
                self._pending = {'event': event, 'values': state, 'count': 0,
                                 'first': now, 'last': now, 'timings': {}, 'serials': []}
            pending = self._pending
            pending['count'] += 1
            pending['last'] = now
            if 'serial' in clean:
                pending['serials'] = [pending['serials'][0] if pending['serials'] else clean['serial'], clean['serial']]
            for name in _TIMINGS & clean.keys():
                value = clean[name]
                prior = pending['timings'].get(name, (value, value, 0, 0))
                pending['timings'][name] = (min(prior[0], value), max(prior[1], value), prior[2] + value, prior[3] + 1)
            self._counts['aggregated_samples'] += 1
            if now - pending['first'] >= 1000:
                return self.flush()
            return True

    def record(self, event, **values):
        with self._lock:
            if not self.enabled:
                return False
            self.flush()
            if type(event) is not str or event not in _EVENTS:
                self._counts['dropped_events'] += 1
                return False
            clean = self._fields(values)
            self._counts['dropped_fields'] += len(values) - len(clean)
            self._observe(event, clean)
            return self._write(event, clean)

    def _write(self, event, values):
        if not self.enabled:
            return False
        self._sequence += 1
        record = {**self._fields(values), 'event': event, 'session': self._session,
                  'elapsed_ms': self._elapsed(), 'sequence': self._sequence,
                  'game_generation': self._game_generation}
        encoded = (json.dumps(record, ensure_ascii=True, separators=(',', ':'), allow_nan=False) + '\n').encode('utf8')
        if len(encoded) > self.max_bytes:
            self._counts['dropped_events'] += 1
            return False
        try:
            self._owned_directory(self.directory)
            paths = [self._path(index) for index in range(FILE_COUNT)]
            if any(path.is_symlink() for path in paths):
                raise OSError('Diagnostic files must not be symlinks')
            if paths[0].exists() and paths[0].stat().st_size + len(encoded) > self.max_bytes:
                if paths[-1].exists():
                    with paths[-1].open('rb') as old:
                        self._counts['truncated_events'] += old.read(self.max_bytes).count(b'\n')
                paths[-1].unlink(missing_ok=True)
                self._counts['rotations'] += 1
                for index in range(FILE_COUNT - 2, -1, -1):
                    if paths[index].exists():
                        paths[index].replace(paths[index + 1])
            with paths[0].open('ab') as output:
                output.write(encoded)
            return True
        except OSError:
            # Diagnostics must never interrupt capture or disclose raw errors.
            self._counts['dropped_events'] += 1
            self._finish_hidden(self._elapsed())
            self._visibility = None
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
                    clean = {'event': value['event'], 'session': session, **self._fields(value)}
                    lines.append(json.dumps(clean, separators=(',', ':'), allow_nan=False) + '\n')
                except (ValueError, TypeError, UnicodeError, RecursionError):
                    continue
        return ''.join(lines)

    def export_zip(self, directory, *, config, recent_seconds=None, game_generation=None):
        """One local latest ZIP; never glob a directory, attach files or upload.

        Replaces only our fixed export filename atomically, bounding repeated
        button clicks to one archive. Old log files are privacy-filtered again.
        """
        directory = Path(directory)
        with self._lock:
            if recent_seconds is not None and not _number(recent_seconds, 86400):
                raise ValueError('Invalid recent window')
            if game_generation is not None and (type(game_generation) is not int or not 0 <= game_generation <= 2**53):
                raise ValueError('Invalid game scope')
            self.flush()
            event_text = self._safe_events()
            if recent_seconds is not None or game_generation is not None:
                cutoff = self._elapsed() - (recent_seconds or 0) * 1000
                selected = []
                for line in event_text.splitlines():
                    value = json.loads(line)
                    if value.get('session') != self._session:
                        continue
                    if recent_seconds is not None and value.get('elapsed_ms', -1) < cutoff:
                        continue
                    if game_generation is not None and value.get('game_generation') != game_generation:
                        continue
                    selected.append(line + '\n')
                event_text = ''.join(selected)
            events = event_text.encode('utf8')
            if len(events) > self.max_bytes * FILE_COUNT:
                raise ValueError('Diagnostic export exceeded event budget')
            manifest = {'schema': 2, 'app_version': self.version, 'diagnostic_profile': 'capture-stability-v1',
                        'session': self._session, 'counters': dict(self._counts),
                        'summary': self._summary_snapshot(),
                        'selection': {'recent_seconds': recent_seconds, 'game_generation': game_generation},
                        'config': safe_config(config),
                        'privacy': 'Local only; canonical catalog names only; no screenshots, raw OCR text, player identity, titles, paths, raw errors or credentials.',
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

"""Bounded local diagnostics (the UI selects the per-launch enabled state). No network, screenshots or free-text logs.

Every value passes an allowlist on write AND export. Window/process identities
are per-launch salted aliases; raw HWNDs, PIDs, executable paths and titles are
never serialized. Enabling is intentionally not persisted between launches.
"""
from __future__ import annotations

from collections import OrderedDict, deque
from concurrent.futures import CancelledError

import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import re
import secrets
import ssl
import tempfile
import threading
import time
import zipfile
from urllib.error import HTTPError, URLError

MAX_BYTES = 256 * 1024
FILE_COUNT = 3
EXPORT_OVERHEAD_BYTES = 64 * 1024
MAX_EXPORT_BYTES = MAX_BYTES * FILE_COUNT + EXPORT_OVERHEAD_BYTES
MAX_GAME_SUMMARIES = 4
GAME_SUMMARY_BYTES = 24 * 1024
_EVENTS = frozenset({'debug_enabled', 'debug_disabled', 'state', 'job', 'capture',
                     'recognition', 'overlay', 'expiry', 'invalidate', 'cancel', 'session', 'close', 'inference', 'sample_summary', 'config', 'selection_gate', 'identity', 'window_binding', 'card_observation', 'templates'})
_ENUMS = {
    'kind': frozenset({'load', 'portraits', 'update', 'install', 'windows', 'ocr',
                       'selection', 'capture-proof', 'title-proof', 'unknown'}),
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
                         'capture_unavailable', 'capture_paused', 'display_wait', 'geometry_unproven', 'title_changed', 'title_recheck', 'hero_conflict', 'no_previous', 'prior_frame_unproven', 'stale_previous', 'interactive', 'backend_unavailable', 'exclusion_unregistered', 'cleanup_pending', 'unknown'}),
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
_ENUMS['selection_gate'] = frozenset({'closed', 'stopped', 'inference_busy', 'capture_pending', 'target_missing', 'foreground_rejected', 'client_lcu_ready', 'client_pixels_ready', 'game_pixels_ready', 'manual_pixels_ready', 'route_unknown'})
_ENUMS['selection_route'] = frozenset({'blocked', 'selection_lcu', 'selection_pixels', 'game_pixels', 'manual_pixels', 'unknown'})
_ENUMS['target_role'] = frozenset({'none', 'client', 'game', 'manual', 'unknown'})
_ENUMS['template_outcome'] = frozenset({'loading', 'cached_ready', 'ready', 'unavailable', 'retry_wait'})
_ENUMS['binding_outcome'] = frozenset({'adopted', 'adoption_rejected', 'no_candidate', 'unchanged'})
_IDENTITY_ENUMS = {
    'api_outcome': frozenset({'disabled', 'cancelled', 'map_invalid', 'scope_unavailable',
        'tls_context_failed', 'tls_verification_failed', 'connection_failed', 'http_error',
        'response_invalid', 'payload_invalid', 'active_player_mismatch', 'champion_unmapped',
        'unstable', 'scope_changed', 'timeout', 'verified', 'unexpected_error'}),
    'hud_outcome': frozenset({'recognized', 'invalid_image', 'unsupported_layout', 'letterboxed',
        'templates_unavailable', 'incomplete_templates', 'score_low', 'margin_low',
        'death_grayscale', 'color_mismatch', 'champion_unmapped', 'unknown'}),
    'identity_outcome': frozenset({'api_verified', 'hud_verified', 'hud_abstained',
        'api_hud_conflict', 'source_unmapped'}),
    'map_outcome': frozenset({'not_requested', 'verified', 'verified_memory', 'manifest_unavailable',
        'manifest_invalid', 'roster_unavailable', 'hash_mismatch', 'roster_invalid'}),
}
_ENUMS.update(_IDENTITY_ENUMS)
_ENUMS['worker_error_category'] = frozenset({'capture_paused', 'capture_unavailable', 'cancelled',
    'timeout', 'connection_error', 'permission_error', 'file_missing', 'memory_error',
    'value_error', 'type_error', 'key_error', 'index_error', 'attribute_error', 'runtime_error',
    'os_error', 'unknown', 'tls_verification_failed', 'tls_error', 'http_error', 'network_error'})
_CAUSE_DIMENSIONS = ('reason', 'binding_outcome', 'worker_error_category', 'api_outcome', 'hud_outcome',
                     'identity_outcome', 'map_outcome', 'template_outcome')
_ENUMS['sampled_event'] = _EVENTS - {'sample_summary'}
_BOOLS = frozenset({'running', 'confirmed', 'ocr_busy', 'capture_pending', 'visible',
                    'card_geometry_proven', 'title_evidence_valid',
                    'rechecking', 'click_through', 'visible_capture', 'cancelled',
                    'ocr_cold_start', 'ocr_reused', 'hero_present', 'manual_editing', 'fresh', 'catalog_match', 'tier_present', 'lcu_selection', 'hero_auto', 'pixel_fallback', 'target_present', 'target_foreground', 'client_follow', 'frozen', 'updates_enabled', 'live_identity'})
# session_generation is the small SelectionSession counter, never a native token.
_INTS = frozenset({'generation', 'session_generation', 'serial', 'width', 'height',
                   'stable_frames', 'automatic_frames', 'hero_stable_frames',
                   'hero_revision', 'candidate_revision', 'candidate_count',
                   'sequence', 'game_generation', 'sample_count', 'first_serial', 'last_serial', 'occurrences', 'first_sequence', 'last_sequence', 'window_count', 'eligible_client_count', 'eligible_game_count', 'preferred_count', 'rejected_class_count', 'rejected_metadata_count', 'rejected_identity_count', 'rejected_installation_count', 'rejected_signature_count'})
_FLOATS = frozenset({'capture_ms', 'inference_ms', 'queue_ms', 'prepare_ms', 'hud_ms', 'ocr_ms', 'dispatch_ms', 'elapsed_ms', 'age_ms', 'ttl_ms', 'settle_ms', 'dpi'})
_TIMINGS = _FLOATS - {'dpi', 'elapsed_ms'}
_INTS = _INTS | frozenset(f'{key}_count' for key in _TIMINGS)
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
        elif key == 'roi_percent' and type(value) in (list, tuple) and len(value) == 4 and all(type(v) is int and 0 <= v <= 100 for v in value):
            clean[key] = list(value)
        elif key in _IDENTITIES and type(value) is str and re.fullmatch(r'[0-9a-f]{16}', value):
            clean[key] = value
    return clean


def classify_worker_error(error, *, error_code='worker_error'):
    """Fixed type-only category; bounded nested causes, never exception text."""
    if error_code in ('capture_paused', 'capture_unavailable'):
        return error_code
    current, seen = error, set()
    for depth in range(4):
        if id(current) in seen:
            break
        seen.add(id(current))
        for cls, category in ((HTTPError, 'http_error'),
                (ssl.SSLCertVerificationError, 'tls_verification_failed'),
                (ssl.SSLError, 'tls_error'), (TimeoutError, 'timeout'),
                (ConnectionError, 'connection_error')):
            if isinstance(current, cls):
                return category
        nested = current.reason if isinstance(current, URLError) else None
        if not isinstance(nested, BaseException):
            nested = getattr(current, '__cause__', None)
        if depth == 3 or not isinstance(nested, BaseException) or id(nested) in seen:
            break
        current = nested
    if isinstance(current, URLError):
        return 'network_error'
    for cls, category in ((CancelledError, 'cancelled'), (PermissionError, 'permission_error'),
            (FileNotFoundError, 'file_missing'), (MemoryError, 'memory_error'),
            (KeyError, 'key_error'), (IndexError, 'index_error'), (AttributeError, 'attribute_error'),
            (TypeError, 'type_error'), (ValueError, 'value_error'), (RuntimeError, 'runtime_error'),
            (OSError, 'os_error')):
        if isinstance(current, cls):
            return category
    return 'unknown'


def safe_config(config):
    clean = {key: value for key, value in config.items()
             if key in _CONFIG_BOOLS and type(value) is bool}
    roi = config.get('roi_percent')
    if type(roi) in (list, tuple) and len(roi) == 4 and all(type(v) is int and 0 <= v <= 100 for v in roi):
        clean['roi_percent'] = list(roi)
    return clean


class _ScopedDebugLog:
    """Internal worker handle retaining the diagnostic scope captured at queue time."""
    def __init__(self, log, scope):
        self._log, self._scope = log, scope

    @property
    def enabled(self):
        return self._log.enabled

    def identity(self, *args):
        return self._log.identity(*args)

    def record(self, event, **values):
        return self._log._record(event, values, game_scope=self._scope)

    def sample(self, event, **values):
        return self._log._sample(event, values, game_scope=self._scope)


class LocalDebugLog:
    def __init__(self, directory, *, version, max_bytes=MAX_BYTES):
        self.directory = Path(directory)
        self.version = version if type(version) is str and re.fullmatch(r'\d{1,3}\.\d{1,3}\.\d{1,3}(?:[-+][A-Za-z0-9.-]{1,32})?', version) else 'unknown'
        if type(max_bytes) is not int or not 512 <= max_bytes <= MAX_BYTES:
            raise ValueError('Invalid diagnostic size limit')
        self.max_bytes = max_bytes
        # The independent lanes share, rather than enlarge, the old 768 KiB budget.
        self._detail_limit = max_bytes // 2
        self._critical_limit = max_bytes
        self._context_limit = max_bytes // 2
        self.enabled = False
        self.failed = False
        self._lock = threading.RLock()
        self._salt = secrets.token_bytes(32)
        self._session = secrets.token_hex(8)
        self._started = time.monotonic()
        self._sequence = 0
        self._game_generation = 0
        self._catalogs = {'hero_name': frozenset(), 'augment_name': frozenset()}
        self._samples = OrderedDict()
        self._critical = OrderedDict()
        self._critical_bytes = 0
        self._critical_window_ms = 60000
        self._context = OrderedDict()
        self._context_bytes = 0
        self._buffer = deque()
        self._buffer_bytes = 0
        self._context_until = -1
        self._context_active = OrderedDict()
        self._context_causes = OrderedDict()
        self._lanes_dirty = False
        self._lanes_saved_at = -1000
        self._last_config = None
        self._export_validation = {}
        self._first_observed_ms = None
        self._last_observed_ms = None
        self._game_summaries = OrderedDict()
        self._game_summary_last_evicted = -1
        self._summary = {'events': {}, 'reasons': {}, 'inference_stages': {}, 'timings': {},
                         'capture_statuses': {}, 'session_statuses': {}, 'oneshot_statuses': {}, 'fallback_reasons': {},
                         'selection_gates': {}, 'selection_routes': {}, 'target_roles': {},
                         'worker_error_categories': {}, 'api_outcomes': {}, 'hud_outcomes': {},
                         'identity_outcomes': {}, 'map_outcomes': {}, 'binding_outcomes': {}}
        self._visibility = None
        self._hidden_since = None
        self._hidden_total_ms = 0.0
        self._hidden_max_ms = 0.0
        self._hide_transitions = 0
        self._show_transitions = 0
        self._counts = {'dropped_events': 0, 'dropped_fields': 0,
                        'truncated_events': 0, 'rotations': 0, 'aggregated_samples': 0,
                        'critical_observations': 0, 'critical_compactions': 0,
                        'critical_truncated_observations': 0, 'context_triggers': 0,
                        'context_truncated_events': 0, 'context_truncated_frames': 0, 'truncated_current_launch_records': 0, 'truncated_prior_launch_records': 0,
                        'game_summaries_evicted': 0, 'game_summary_observations_evicted': 0}

    @staticmethod
    def _add_metric(bucket, value):
        bucket['count'] = min(2**53, bucket.get('count', 0) + 1)
        bucket['total_ms'] = round(min(2**53, bucket.get('total_ms', 0) + value), 3)
        bucket['max_ms'] = max(bucket.get('max_ms', 0), value)

    def _observe(self, event, values, game_scope):
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
                                 ('oneshot_status', 'oneshot_statuses'), ('fallback_reason', 'fallback_reasons'),
                                 ('selection_gate', 'selection_gates'), ('selection_route', 'selection_routes'), ('target_role', 'target_roles'),
                                 ('worker_error_category', 'worker_error_categories'),
                                 ('api_outcome', 'api_outcomes'), ('hud_outcome', 'hud_outcomes'),
                                 ('identity_outcome', 'identity_outcomes'), ('map_outcome', 'map_outcomes'),
                                 ('binding_outcome', 'binding_outcomes')):
            if field in values:
                dimensions.append((dimension, values[field]))
        self._observe_game(event, values, now, game_scope)
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

    def _observe_game(self, event, values, now, scope):
        summary = self._game_summaries.get(scope)
        if summary is None:
            summary = {'game_generation': scope, 'observations': 0, 'worker_errors': 0,
                       'first_elapsed_ms': now, 'last_elapsed_ms': now,
                       'complete_observed_scope': scope > self._game_summary_last_evicted,
                       'events': {}, 'causes': {}, 'first_causes': {}, 'last_causes': {}}
            self._game_summaries[scope] = summary
            self._game_summaries = OrderedDict(sorted(self._game_summaries.items()))
        summary['observations'] = min(2**53, summary['observations'] + 1)
        summary['last_elapsed_ms'] = now
        summary['events'][event] = min(2**53, summary['events'].get(event, 0) + 1)
        if event == 'job' and values.get('phase') == 'error':
            summary['worker_errors'] = min(2**53, summary['worker_errors'] + 1)
        if 'reason' in values:
            summary.setdefault('first_reason', values['reason'])
            summary['last_reason'] = values['reason']
        for dimension in _CAUSE_DIMENSIONS:
            if dimension not in values:
                continue
            summary['first_causes'].setdefault(dimension, values[dimension])
            summary['last_causes'][dimension] = values[dimension]
            categories = summary['causes'].setdefault(dimension, {})
            bucket = categories.setdefault(values[dimension], {
                'observations': 0, 'first_elapsed_ms': now, 'last_elapsed_ms': now})
            bucket['observations'] = min(2**53, bucket['observations'] + 1)
            bucket['last_elapsed_ms'] = now
        # Entire oldest scopes are evicted, with explicit accounting. A late
        # old worker never displaces newer retained scopes by insertion order.
        while self._game_summaries and (len(self._game_summaries) > MAX_GAME_SUMMARIES or
                len(json.dumps(list(self._game_summaries.values()), separators=(',', ':')).encode('utf8')) > GAME_SUMMARY_BYTES):
            removed_scope, removed = self._game_summaries.popitem(last=False)
            self._game_summary_last_evicted = max(self._game_summary_last_evicted, removed_scope)
            self._counts['game_summaries_evicted'] += 1
            self._counts['game_summary_observations_evicted'] += removed['observations']

    def _game_summary_snapshot(self):
        return {'scope': 'current_launch; worker scope captured at queue time, other observations use active local scope'
                        ', local boundaries are monitor starts and verified new game-window bindings, never server match IDs',
                'max_scopes': MAX_GAME_SUMMARIES, 'max_payload_bytes': GAME_SUMMARY_BYTES,
                'evicted_scope_summaries': self._counts['game_summaries_evicted'],
                'evicted_observations': self._counts['game_summary_observations_evicted'],
                'games': json.loads(json.dumps(list(self._game_summaries.values())))}

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
            if self._last_config is not None:
                self.record('config', **self._last_config)
            return self._game_generation

    @staticmethod
    def _encode(record):
        return (json.dumps(record, ensure_ascii=True, separators=(',', ':'), allow_nan=False) + '\n').encode('utf8')

    def _new_record(self, event, values, game_scope=None):
        self._sequence += 1
        return {**self._fields(values), 'event': event, 'session': self._session,
                'elapsed_ms': self._elapsed(), 'sequence': self._sequence,
                'game_generation': self._game_generation if game_scope is None else game_scope}

    def _accept(self, event, values, game_scope=None):
        if not self.enabled:
            return None
        if type(event) is not str or event not in _EVENTS or event == 'sample_summary':
            self._counts['dropped_events'] += 1
            return None
        clean = self._fields(values)
        self._counts['dropped_fields'] += len(values) - len(clean)
        for key in ('sequence', 'game_generation', 'elapsed_ms', 'occurrences',
                    'first_sequence', 'last_sequence', 'first_elapsed_ms', 'last_elapsed_ms',
                    'first_serial', 'last_serial', 'sample_count', 'sampled_event'):
            clean.pop(key, None)
        scope = self._game_generation if game_scope is None else game_scope
        self._observe(event, clean, scope)
        record = self._new_record(event, clean, scope)
        now = record['elapsed_ms']
        if self._first_observed_ms is None:
            self._first_observed_ms = now
        self._last_observed_ms = now
        self._retain(record)
        return record

    def record_config(self, config):
        """Historical allowlisted settings, with no paths or caller timestamps."""
        with self._lock:
            self._last_config = safe_config(config)
            return self.record('config', **self._last_config)

    def _flush_sample(self, stream):
        sample = self._samples.get(stream)
        if not sample or sample['pending'] is None:
            return True
        pending, sample['pending'] = sample['pending'], None
        values = dict(pending['values'])
        values.update(sampled_event=pending['event'], sample_count=pending['count'],
                      first_elapsed_ms=pending['first'], last_elapsed_ms=pending['last'])
        if pending['serials']:
            values.update(first_serial=pending['serials'][0], last_serial=pending['serials'][1])
        for key, (low, high, total, count) in pending['timings'].items():
            values.update({key + '_min': low, key + '_max': high, key + '_mean': total / count, key + '_count': count})
        return self._write('sample_summary', values, game_scope=pending['game_scope'])

    def flush(self):
        """Flush independent streams and durable bounded history snapshots."""
        with self._lock:
            success = all([self._flush_sample(stream) for stream in tuple(self._samples)])
            return self._persist_lanes(force=True) and success

    def _sample_record(self, record, interval_ms):
        # Fixed stream dimensions prevent alternating inference phases or slots
        # from flushing unrelated streams. At most 64 streams can be pending.
        event = record['event']
        stream = tuple(record.get(key) for key in ('event', 'phase', 'kind', 'inference_stage', 'slot', 'game_generation'))
        clean = {key: value for key, value in record.items()
                 if key not in ('event', 'session', 'sequence', 'game_generation', 'elapsed_ms')}
        state = {key: value for key, value in clean.items() if key not in _TIMINGS and key != 'serial'}
        key = json.dumps(state, sort_keys=True, separators=(',', ':'))
        sample = self._samples.get(stream)
        if sample is None or sample['key'] != key:
            self._flush_sample(stream)
            if len(self._samples) >= 64 and stream not in self._samples:
                oldest = next(iter(self._samples))
                self._flush_sample(oldest)
                del self._samples[oldest]
            success = self._write(event, clean, record=record)
            self._samples[stream] = {'key': key, 'pending': None}
            return success
        self._samples.move_to_end(stream)
        now = record['elapsed_ms']
        if sample['pending'] is None:
            sample['pending'] = {'event': event, 'values': state, 'count': 0, 'game_scope': record['game_generation'],
                                 'first': now, 'last': now, 'timings': {}, 'serials': []}
        pending = sample['pending']
        pending['count'] += 1
        pending['last'] = now
        if 'serial' in clean:
            pending['serials'] = [pending['serials'][0] if pending['serials'] else clean['serial'], clean['serial']]
        for name in _TIMINGS & clean.keys():
            value = clean[name]
            prior = pending['timings'].get(name, (value, value, 0, 0))
            pending['timings'][name] = (min(prior[0], value), max(prior[1], value), prior[2] + value, prior[3] + 1)
        self._counts['aggregated_samples'] += 1
        if now - pending['first'] >= interval_ms:
            self._flush_sample(stream)
        return self._persist_lanes()

    def scoped(self):
        with self._lock:
            return _ScopedDebugLog(self, self._game_generation)

    def sample(self, event, **values):
        return self._sample(event, values)

    def _sample(self, event, values, game_scope=None):
        """Coalesce this stream without being interrupted by other records."""
        with self._lock:
            record = self._accept(event, values, game_scope)
            return self._sample_record(record, 1000) if record is not None else False

    def record(self, event, **values):
        return self._record(event, values)

    def _record(self, event, values, game_scope=None):
        with self._lock:
            if event in ('debug_disabled', 'session', 'close'):
                self.flush()
                self._samples.clear()
            record = self._accept(event, values, game_scope)
            if record is None:
                return False
            # Routine lifecycle observations still enter the exact incident
            # buffer and launch counters; only their disk tail is sampled.
            routine = (event == 'inference' and values.get('phase') in ('started', 'completed') or
                       event == 'capture' and values.get('phase') in ('started', 'acquired', 'completed', 'queued') or
                       event == 'job' and values.get('phase') in ('queued', 'started', 'completed'))
            return self._sample_record(record, 5000) if routine else self._write(event, values, record=record)

    @staticmethod
    def _is_critical(record):
        event = record['event']
        return (event in ('debug_enabled', 'debug_disabled', 'config', 'session', 'state',
                          'selection_gate', 'identity', 'window_binding', 'card_observation', 'templates', 'overlay', 'recognition', 'expiry', 'invalidate', 'cancel', 'close') or
                record.get('phase') in ('error', 'discarded') or
                event == 'capture' and (record.get('phase') == 'requested' or 'capture_mode' in record) or
                event == 'job' and record.get('kind') == 'windows')

    def _critical_key(self, record):
        # Counters/confidence/latencies vary within a stable state. Keep the
        # original representative and range statistics without making each
        # frame a new critical state. Identity aliases remain ordinary values.
        semantic = {key: value for key, value in record.items()
                    if key in _ENUMS or key in _BOOLS or key in _IDENTITIES or
                    key in ('event', 'session', 'game_generation', 'generation',
                            'session_generation', 'slot', 'hero_name', 'augment_name', 'roi_percent')}
        # Configuration and explicit game boundaries are exact chronological events.
        if record['event'] in ('config', 'session'):
            semantic['sequence'] = record['sequence']
        return (int(record['elapsed_ms'] // self._critical_window_ms),
                json.dumps(semantic, sort_keys=True, separators=(',', ':')))

    @staticmethod
    def _history_values(entry):
        record = dict(entry['record'])
        record.update(occurrences=entry['count'], first_elapsed_ms=entry['first'],
                      last_elapsed_ms=entry['last'], first_sequence=entry['first_sequence'],
                      last_sequence=entry['last_sequence'])
        if entry['serials']:
            record.update(first_serial=entry['serials'][0], last_serial=entry['serials'][1])
        for key, (low, high, total, count) in entry['timings'].items():
            record.update({key + '_min': low, key + '_max': high, key + '_mean': total / count, key + '_count': count})
        return record

    def _add_critical(self, record):
        self._counts['critical_observations'] += 1
        key = self._critical_key(record)
        entry = self._critical.get(key)
        if entry is None:
            entry = {'record': record, 'first': record['elapsed_ms'], 'last': record['elapsed_ms'],
                     'first_sequence': record['sequence'], 'last_sequence': record['sequence'],
                     'count': 0, 'serials': [], 'timings': {}, 'encoded': b''}
            self._critical[key] = entry
        self._critical_bytes -= len(entry['encoded'])
        entry['count'] += 1
        entry['last'] = record['elapsed_ms']
        entry['last_sequence'] = record['sequence']
        if 'serial' in record:
            entry['serials'] = [entry['serials'][0] if entry['serials'] else record['serial'], record['serial']]
        for name in _TIMINGS & record.keys():
            value = record[name]
            prior = entry['timings'].get(name, (value, value, 0, 0))
            entry['timings'][name] = (min(prior[0], value), max(prior[1], value), prior[2] + value, prior[3] + 1)
        entry['encoded'] = self._encode(self._history_values(entry))
        self._critical_bytes += len(entry['encoded'])
        while self._critical_bytes > self._critical_limit and self._critical_window_ms < 3600000:
            self._compact_critical()
        while self._critical_bytes > self._critical_limit:
            # An adversarial stream of unique states cannot fit indefinitely.
            # Preserve the beginning plus the latest evidence; report exact loss.
            keys = list(self._critical)
            victim = keys[min(max(0, len(keys) // 8), len(keys) - 1)]
            removed = self._critical.pop(victim)
            self._critical_bytes -= len(removed['encoded'])
            self._counts['critical_truncated_observations'] += removed['count']

    def _compact_critical(self):
        self._critical_window_ms = min(3600000, self._critical_window_ms * 2)
        self._counts['critical_compactions'] += 1
        combined = OrderedDict()
        for entry in self._critical.values():
            key = self._critical_key(entry['record'])
            previous = combined.get(key)
            if previous is None:
                combined[key] = entry
                continue
            previous['count'] += entry['count']
            previous['last'] = entry['last']
            previous['last_sequence'] = entry['last_sequence']
            if entry['serials']:
                previous['serials'] = [previous['serials'][0] if previous['serials'] else entry['serials'][0], entry['serials'][1]]
            for name, (low, high, total, count) in entry['timings'].items():
                prior = previous['timings'].get(name, (low, high, 0, 0))
                previous['timings'][name] = (min(low, prior[0]), max(high, prior[1]), total + prior[2], count + prior[3])
        self._critical = combined
        self._critical_bytes = 0
        for entry in combined.values():
            entry['encoded'] = self._encode(self._history_values(entry))
            self._critical_bytes += len(entry['encoded'])

    @staticmethod
    def _frame_key(record):
        return (record['session'], record['game_generation'], record.get('generation'),
                ('serial', record['serial']) if 'serial' in record else ('second', int(record['elapsed_ms'] // 1000)))

    def _add_context(self, record, encoded):
        frame = self._frame_key(record)
        group = self._context.setdefault(frame, OrderedDict())
        if record['sequence'] in group:
            return
        group[record['sequence']] = encoded
        self._context_bytes += len(encoded)
        while self._context_bytes > self._context_limit:
            keys = list(self._context)
            # Routine hide/show churn must not overwrite the most recent
            # distinct error's full frame. Pins are bounded, never permanent.
            pinned = set(self._context_causes.values())
            victim = next((key for key in keys[1:] if key not in pinned),
                          keys[1] if len(keys) > 1 else keys[0])
            removed = self._context.pop(victim)
            self._context_bytes -= sum(map(len, removed.values()))
            self._counts['context_truncated_events'] += len(removed)
            self._counts['context_truncated_frames'] += 1

    def _retain(self, record):
        encoded = self._encode(record)
        now = record['elapsed_ms']
        if self._is_critical(record):
            self._add_critical(record)
        self._buffer.append((record, encoded))
        self._buffer_bytes += len(encoded)
        while self._buffer and (self._buffer_bytes > min(65536, self._context_limit)):
            self._buffer_bytes -= len(self._buffer.popleft()[1])
        trigger = (record['event'] == 'overlay' and record.get('phase') in ('hidden', 'shown') or
                   record.get('phase') in ('error', 'discarded') or
                   record['event'] in ('expiry', 'invalidate', 'cancel') or
                   record['event'] == 'card_observation' and record.get('reason') in (
                       'candidate_missing', 'candidate_untrusted', 'candidate_layout',
                       'title_low_confidence', 'title_dictionary_miss') or
                   record['event'] == 'identity' and record.get('identity_outcome') in ('hud_abstained', 'api_hud_conflict', 'source_unmapped'))
        if trigger:
            self._counts['context_triggers'] += 1
            self._context_until = now + 5000
            frame = self._frame_key(record)
            cause = tuple(record.get(key) for key in ('event', 'phase', 'reason', 'error_code', 'capture_status',
                'worker_error_category', 'api_outcome', 'hud_outcome', 'identity_outcome', 'map_outcome', 'template_outcome'))
            self._context_causes[cause] = frame
            self._context_causes.move_to_end(cause)
            while len(self._context_causes) > 16:
                self._context_causes.popitem(last=False)
            self._context_active[frame] = True
            self._context_active.move_to_end(frame)
            while len(self._context_active) > 8:
                self._context_active.popitem(last=False)
            for buffered, data in self._buffer:
                if self._frame_key(buffered) == frame or now - buffered['elapsed_ms'] <= 2000:
                    self._add_context(buffered, data)
        elif now <= self._context_until or self._frame_key(record) in self._context_active:
            self._add_context(record, encoded)
        self._lanes_dirty = True

    def _fail(self):
        self._counts['dropped_events'] += 1
        self._finish_hidden(self._elapsed())
        self._visibility = None
        self.enabled = False
        self.failed = True
        return False

    def _persist_lanes(self, force=False):
        if not self._lanes_dirty or not self.enabled:
            return not self.failed
        now = self._elapsed()
        if not force and now - self._lanes_saved_at < 1000:
            return True
        try:
            self._owned_directory(self.directory)
            payloads = {'critical.jsonl': b''.join(entry['encoded'] for entry in self._critical.values()),
                        'context.jsonl': b''.join(data for group in self._context.values() for data in group.values())}
            for name, data in payloads.items():
                target = self.directory / name
                if target.is_symlink():
                    raise OSError('Diagnostic files must not be symlinks')
                # Owned, fixed files only. A partial crash write is skipped by
                # export's JSON/privacy validation; no extra unbounded files.
                with target.open('wb') as output:
                    output.write(data)
            self._lanes_dirty = False
            self._lanes_saved_at = now
            return True
        except OSError:
            return self._fail()

    def _write(self, event, values, *, record=None, game_scope=None):
        if not self.enabled:
            return False
        record = record if record is not None else self._new_record(event, values, game_scope)
        encoded = self._encode(record)
        if len(encoded) > self._detail_limit:
            self._counts['dropped_events'] += 1
            return False
        try:
            self._owned_directory(self.directory)
            paths = [self._path(index) for index in range(FILE_COUNT)]
            if any(path.is_symlink() for path in paths):
                raise OSError('Diagnostic files must not be symlinks')
            # A previous schema may have used larger per-file limits.
            for path in paths:
                if path.exists() and path.stat().st_size > self._detail_limit:
                    self._count_removed(path, self.max_bytes)
                    path.unlink()
            if paths[0].exists() and paths[0].stat().st_size + len(encoded) > self._detail_limit:
                if paths[-1].exists():
                    self._count_removed(paths[-1], self._detail_limit)
                paths[-1].unlink(missing_ok=True)
                self._counts['rotations'] += 1
                for index in range(FILE_COUNT - 2, -1, -1):
                    if paths[index].exists():
                        paths[index].replace(paths[index + 1])
            with paths[0].open('ab') as output:
                output.write(encoded)
            return self._persist_lanes(force=event in ('debug_disabled', 'close'))
        except OSError:
            return self._fail()

    def _safe_file(self, path, limit):
        lines = []
        if self.directory.is_symlink() or path.is_symlink():
            raise OSError('Diagnostic files must not be symlinks')
        if not path.exists():
            return ''
        with path.open('rb') as source:
            raw = source.read(limit + 1)
        if len(raw) > limit:
            self._export_validation['oversized_files'] = self._export_validation.get('oversized_files', 0) + 1
            return ''
        for line in raw.splitlines():
            try:
                value = json.loads(line)
                if type(value) is not dict or value.get('event') not in _EVENTS:
                    self._export_validation['invalid_records'] = self._export_validation.get('invalid_records', 0) + 1
                    continue
                session = value.get('session')
                if type(session) is not str or not re.fullmatch(r'[0-9a-f]{16}', session):
                    self._export_validation['invalid_records'] = self._export_validation.get('invalid_records', 0) + 1
                    continue
                clean = {'event': value['event'], 'session': session, **self._fields(value)}
                lines.append(self._encode(clean).decode('utf8'))
            except (ValueError, TypeError, UnicodeError, RecursionError):
                self._export_validation['invalid_records'] = self._export_validation.get('invalid_records', 0) + 1
                continue
        return ''.join(lines)

    def _safe_events(self):
        return ''.join(self._safe_file(self._path(index), self._detail_limit)
                       for index in reversed(range(FILE_COUNT)))

    def _count_removed(self, path, limit):
        with path.open('rb') as source:
            raw = source.read(limit)
        self._counts['truncated_events'] += raw.count(b'\n')
        for line in raw.splitlines():
            try:
                value = json.loads(line)
                if type(value) is dict and type(value.get('session')) is str:
                    key = 'truncated_current_launch_records' if value['session'] == self._session else 'truncated_prior_launch_records'
                    self._counts[key] += 1
            except (ValueError, TypeError, UnicodeError, RecursionError):
                pass

    def _select_text(self, value, recent_seconds, game_generation):
        selected = []
        cutoff = self._elapsed() - (recent_seconds or 0) * 1000
        for line in value.splitlines():
            record = json.loads(line)
            if recent_seconds is not None or game_generation is not None:
                if record.get('session') != self._session:
                    continue
                if recent_seconds is not None and record.get('last_elapsed_ms', record.get('elapsed_ms', -1)) < cutoff:
                    continue
                if game_generation is not None and record.get('game_generation') != game_generation:
                    continue
            selected.append(record)
        selected.sort(key=lambda row: (row['session'], row.get('elapsed_ms', 0), row.get('sequence', 0)))
        return b''.join(self._encode(record) for record in selected)

    def _coverage(self, data):
        records = [json.loads(line) for line in data.splitlines()]
        current = [row for row in records if row.get('session') == self._session]
        return {'retained_records': len(records), 'current_launch_records': len(current),
                'prior_launch_records': len(records) - len(current),
                'current_launch_represented_observations': sum(row.get('occurrences', row.get('sample_count', 1)) for row in current),
                'first_elapsed_ms': min((row.get('first_elapsed_ms', row.get('elapsed_ms', 0)) for row in current), default=None),
                'last_elapsed_ms': max((row.get('last_elapsed_ms', row.get('elapsed_ms', 0)) for row in current), default=None)}

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
            self._export_validation = {}
            event_text = self._safe_events()
            if len(event_text.encode('utf8')) > self._detail_limit * FILE_COUNT:
                raise ValueError('Diagnostic export exceeded event budget')
            lanes = {'events.jsonl': self._select_text(event_text, recent_seconds, game_generation),
                     'critical.jsonl': self._select_text(self._safe_file(self.directory / 'critical.jsonl', self._critical_limit), recent_seconds, game_generation),
                     'context.jsonl': self._select_text(self._safe_file(self.directory / 'context.jsonl', self._context_limit), recent_seconds, game_generation)}
            if sum(map(len, lanes.values())) > self.max_bytes * FILE_COUNT:
                raise ValueError('Diagnostic export exceeded combined budget')
            manifest = {'schema': 3, 'app_version': self.version, 'diagnostic_profile': 'capture-stability-v2',
                        'session': self._session, 'counters': dict(self._counts),
                        'summary': self._summary_snapshot(),
                        'game_summaries': self._game_summary_snapshot(),
                        'selection': {'recent_seconds': recent_seconds, 'game_generation': game_generation},
                        'config': safe_config(config),
                        'coverage': {'scope': 'current_launch_observations; retained lanes follow export selection',
                                     'first_observed_elapsed_ms': self._first_observed_ms,
                                     'last_observed_elapsed_ms': self._last_observed_ms,
                                     'export_validation': dict(self._export_validation),
                                     'critical_observation_loss': self._counts['critical_truncated_observations'],
                                     'critical_bucket_ms': self._critical_window_ms,
                                     'critical_order': 'noncontiguous_recurrences; first/last bounds are not adjacent transitions',
                                     'context_order': 'exact originals, may overlap other lanes; deduplicate by session/sequence',
                                     'lanes': {name: self._coverage(data) for name, data in lanes.items()}},
                        'lane_limit_bytes': {'events.jsonl': self._detail_limit * FILE_COUNT,
                                             'critical.jsonl': self._critical_limit, 'context.jsonl': self._context_limit},
                        'privacy': 'Local only; canonical catalog names only; no screenshots, raw OCR text, player identity, titles, paths, raw errors or credentials.',
                        'log_limit_bytes': self.max_bytes * FILE_COUNT,
                        'identity_scope': 'Random per-launch aliases; raw HWND/PID excluded.'}
            manifest_text = json.dumps(manifest, ensure_ascii=True, separators=(',', ':'))
            if len(manifest_text.encode('utf8')) > EXPORT_OVERHEAD_BYTES:
                raise ValueError('Diagnostic export exceeded manifest budget')
            self._owned_directory(directory)
            target = directory / 'VGA-debug.zip'
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(prefix='.vga-debug-', suffix='.tmp', dir=directory, delete=False) as file:
                    temporary = Path(file.name)
                with zipfile.ZipFile(temporary, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
                    archive.writestr('manifest.json', manifest_text)
                    for name, data in lanes.items():
                        archive.writestr(name, data)
                if temporary.stat().st_size > self.max_bytes * FILE_COUNT + EXPORT_OVERHEAD_BYTES:
                    raise ValueError('Diagnostic export exceeded ZIP budget')
                os.replace(temporary, target)
                return target
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)

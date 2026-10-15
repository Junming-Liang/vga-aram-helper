"""Bounded, supplemental owned-fixture capture diagnostics, never adoption timings.

Imported by the parity probe. No CLI, capture target discovery, images, installation,
backend override, production policy changes, or external communication.
"""
from __future__ import annotations

from contextlib import ExitStack
import copy
import hashlib
import importlib
import importlib.metadata
import json
import math
from pathlib import Path
import re
import threading
import time
from unittest.mock import patch

CONTEXTS = ('gui_blocked', 'worker_qt_pumped')
CALLS_PER_CONTEXT = 3
MAX_DIAGNOSTIC_BYTES = 65536
CALL_TIMEOUT = 6.0  # Cooperative cancellation; cannot interrupt native/PIL code.
DEADLINE_KIND = 'cooperative-cancellation; existing-external-job-final-bound'
CANCEL_GRACE = 3.0
PHASES = ('wgc_inclusive', 'helper_verify', 'frame_decode', 'png_encode')
BACKENDS = {'windows-graphics-capture', 'window-dc', 'bounded-compositor'}
SOURCE_FILES = ('screen_capture.py', 'wgc_capture.py', 'wgc_session_capture.py',
                'persistent_capture_adapter.py', 'session_windows.py',
                'native/wgc_capture.cpp', 'native/wgc_session_capture.cpp',
                'scripts/build_wgc_capture.py', 'scripts/build_wgc_session_capture.py',
                'scripts/probe_capture_phases.py', 'scripts/probe_opencv_parity.py')
SCOPE = ('Six fixed supplemental calls after authoritative capture timings; no speed '
         'median, adoption timing, or causal conclusion. helper_verify and frame_decode '
         'are nested inside wgc_inclusive; png_encode is outside it. outer_residual = '
         'total - wgc_inclusive - png_encode, including timer/wrapper overhead. '
         'Cancellation is cooperative; the existing external job deadline is the final bound.')


def bounded_json(value):
    text = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)
    if len(text.encode('utf-8')) > MAX_DIAGNOSTIC_BYTES:
        raise ValueError('Capture diagnostic exceeds its bounded text budget')
    return text


def file_record(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise RuntimeError('Non-regular diagnostic identity input')
    data = path.read_bytes()
    return {'sha256': hashlib.sha256(data).hexdigest(), 'size': len(data)}


def identity_snapshot(repo, bound_helper):
    """Outside all timers; bind helper manifests to actual source and helper bytes."""
    import cv2
    from PIL import Image, PngImagePlugin, _imaging
    root = Path(repo)
    native = getattr(cv2, '_native', cv2)
    if Path(native.__file__).suffix.lower() != '.pyd':
        raise RuntimeError('Capture diagnostics require the loaded Windows cv2 binary')
    loaded = {name: file_record(module.__file__) for name, module in
              (('cv2_native', native), ('pillow_native', _imaging),
               ('pillow_image', Image), ('pillow_png', PngImagePlugin))}
    sources = {name: file_record(root / name) for name in SOURCE_FILES}
    # Bind imported capture wrappers to the inspected checkout, not just files
    # with matching-looking names. The CLI itself may be loaded as __main__.
    for name in ('screen_capture', 'wgc_capture', 'wgc_session_capture',
                 'persistent_capture_adapter', 'session_windows'):
        module = importlib.import_module(name)
        if Path(module.__file__).resolve() != (root / (name + '.py')).resolve():
            raise RuntimeError('Loaded capture module is outside the bound checkout')
    helpers = {}
    for name, builder_name in (('one_shot', 'scripts.build_wgc_capture'),
                               ('session', 'scripts.build_wgc_session_capture')):
        builder = importlib.import_module(builder_name)
        folder = root / 'build' / 'native'
        binary, manifest = folder / builder.FILENAME, folder / builder.MANIFEST
        if not binary.exists() and not manifest.exists():
            helpers[name] = {'status': 'absent'}
            continue
        proof = builder.verify_built_helper(folder, root=root)
        helpers[name] = {'status': 'verified', 'binary': file_record(binary),
                         'manifest': file_record(manifest), 'protocol': proof['protocol'],
                         'source_commit': proof['source_commit'],
                         'source_sha256': proof['source_sha256'],
                         'build_recipe_sha256': proof['build_recipe_sha256']}
    if bound_helper is not None:
        if (helpers['one_shot']['status'] != 'verified'
                or bound_helper._digest != helpers['one_shot']['binary']['sha256']
                or Path(bound_helper.helper_path).resolve() != (root / 'build' / 'native' / 'vga-wgc-capture.exe').resolve()):
            raise RuntimeError('Bound capture helper differs from verified helper bytes')
    return {'loaded': loaded, 'sources': sources, 'helpers': helpers,
            'pillow_version': importlib.metadata.version('Pillow'),
            'bound_one_shot': bound_helper is not None}


def output_identity(value):
    raw, rect = value
    return {'image_sha256': hashlib.sha256(raw).hexdigest(), 'width': rect.width, 'height': rect.height}


def observation(capture):
    backend = getattr(capture, 'last_backend', None)
    helper = getattr(capture, '_wgc', None)
    try:
        pending = capture.cleanup_pending
    except Exception:
        pending = None
    return {'backend': backend, 'cleanup_pending': pending if type(pending) is bool else None,
            'one_shot_helper_sha256': getattr(helper, '_digest', None),
            'fallback_reason': 'unrecorded' if backend in {'window-dc', 'bounded-compositor'} else 'not-applicable'}


def error_record(error):
    # Never emit raw exception text, paths, process/window identifiers or stderr.
    result = {'type': type(error).__name__ if re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]{0,79}', type(error).__name__) else 'Exception'}
    status = getattr(error, 'status', None)
    if status in {'unsupported', 'missing-helper', 'untrusted-helper', 'cancelled',
                  'cleanup-pending', 'stale', 'protected', 'timeout', 'invalid-reply', 'backend-error'}:
        result['status'] = status
    return result


class PhaseTrace:
    """Scoped supplemental-only wrappers. Inclusive and child spans stay separate."""
    def __init__(self, capture):
        self.capture = capture
        self.seconds = {name: 0.0 for name in PHASES}
        self.calls = {name: 0 for name in PHASES}
        self.processes, self.jobs = [], []
        self.lock = threading.Lock()
        self.stack = ExitStack()

    def timed(self, name, function):
        def wrapped(*args, **kwargs):
            start = time.perf_counter()
            try:
                return function(*args, **kwargs)
            finally:
                elapsed = time.perf_counter() - start
                with self.lock:
                    self.seconds[name] += elapsed
                    self.calls[name] += 1
        return wrapped

    def __enter__(self):
        import wgc_capture
        from PIL import Image
        try:
            backend = getattr(self.capture, '_wgc', None)
            if backend is not None:
                self.stack.enter_context(patch.object(backend, 'capture', self.timed('wgc_inclusive', backend.capture)))
                self.stack.enter_context(patch.object(backend, '_verify_helper', self.timed('helper_verify', backend._verify_helper)))
            self.stack.enter_context(patch.object(wgc_capture, 'decode_frame', self.timed('frame_decode', wgc_capture.decode_frame)))
            self.stack.enter_context(patch.object(Image.Image, 'save', self.timed('png_encode', Image.Image.save)))
            popen, job = wgc_capture.subprocess.Popen, wgc_capture._CaptureJob
            def recording_popen(*args, **kwargs):
                value = popen(*args, **kwargs)
                self.processes.append(value)
                return value
            def recording_job(*args, **kwargs):
                value = job(*args, **kwargs)
                self.jobs.append(value)
                return value
            self.stack.enter_context(patch.object(wgc_capture.subprocess, 'Popen', recording_popen))
            self.stack.enter_context(patch.object(wgc_capture, '_CaptureJob', recording_job))
            return self
        except BaseException:
            self.stack.close()
            raise

    def __exit__(self, *exc):
        return self.stack.__exit__(*exc)

    def result(self):
        with self.lock:
            result = {'phase_seconds': dict(self.seconds), 'phase_calls': dict(self.calls)}
        result.update(helper_starts=len(self.processes),
                      helpers_exited=all(process.poll() is not None for process in self.processes),
                      helper_pipes_closed=all(getattr(process, name, None) is None or getattr(process, name).closed
                                              for process in self.processes for name in ('stdin', 'stdout', 'stderr')),
                      helper_jobs_closed=all(not job.handle for job in self.jobs))
        return result


def invoke(operation, *, context, pump, cancelled, timeout=CALL_TIMEOUT, grace=CANCEL_GRACE):
    """Only the caller/Qt thread pumps events. Timers exclude dispatch and pumping."""
    values, errors, threads = [], [], []
    caller = threading.get_ident()
    def work():
        threads.append(threading.get_ident() == caller)
        try:
            values.append(operation())
        except BaseException as error:
            errors.append(error)
    if context == 'gui_blocked':
        watchdog = threading.Timer(timeout, cancelled.set)
        watchdog.daemon = True
        watchdog.start()
        try:
            work()
        finally:
            watchdog.cancel()
        alive, pumps = False, 0
    else:
        worker = threading.Thread(target=work, name='owned-capture-phase-probe', daemon=True)
        worker.start()
        deadline, pumps = time.monotonic() + timeout, 0
        try:
            while worker.is_alive() and time.monotonic() < deadline:
                pump(); pumps += 1
                worker.join(.005)
        except BaseException:
            cancelled.set()
            worker.join(grace)
            raise
        if worker.is_alive():
            cancelled.set()
            deadline = time.monotonic() + grace
            while worker.is_alive() and time.monotonic() < deadline:
                pump(); pumps += 1
                worker.join(.005)
        alive = worker.is_alive()
    return {'value': values[0] if values else None, 'error': errors[0] if errors else None,
            'worker_exited': not alive, 'cancelled': cancelled.is_set(), 'qt_pumps': pumps,
            'capture_on_caller_thread': threads[0] if threads else None}


def same_value(left, right):
    return json.dumps(left, sort_keys=True, separators=(',', ':'), allow_nan=False) == json.dumps(right, sort_keys=True, separators=(',', ':'), allow_nan=False)


def valid_record(value):
    return (type(value) is dict and set(value) == {'sha256', 'size'}
            and type(value['sha256']) is str and re.fullmatch('[0-9a-f]{64}', value['sha256']) is not None
            and type(value['size']) is int and value['size'] > 0)


def supplemental_report(rows, *, failed, safe_to_close):
    return {'schema_version': 1, 'status': 'failed' if failed else 'passed', 'scope': SCOPE,
            'excluded_from_adoption': True, 'calls_per_context': CALLS_PER_CONTEXT,
            'call_timeout_seconds': CALL_TIMEOUT, 'cancellation_grace_seconds': CANCEL_GRACE,
            'deadline_kind': DEADLINE_KIND, 'safe_to_close_fixture': safe_to_close, 'rows': copy.deepcopy(rows)}


def skipped_supplemental(capture):
    rows = [{'context': context, 'index': index, 'status': 'not-run'}
            for context in CONTEXTS for index in range(CALLS_PER_CONTEXT)]
    return supplemental_report(rows, failed=True, safe_to_close=observation(capture)['cleanup_pending'] is False)


def run_supplemental(capture, target, expected, pump, *, tracer_factory=PhaseTrace, invoke_call=invoke):
    rows = [{'context': context, 'index': index, 'status': 'not-run'}
            for context in CONTEXTS for index in range(CALLS_PER_CONTEXT)]
    failed = False
    safe_to_close = True
    for row in rows:
        if failed:
            break
        cancelled = threading.Event()
        trace = tracer_factory(capture)
        timing = {}
        def operation():
            start = time.perf_counter()
            try:
                return capture.capture(target, cancelled=cancelled.is_set)
            finally:
                timing['total_seconds'] = time.perf_counter() - start
        try:
            with trace:
                run = invoke_call(operation, context=row['context'], pump=pump, cancelled=cancelled)
            row.update({**trace.result(), **timing, **observation(capture)},
                       worker_exited=run['worker_exited'], cancelled=run['cancelled'], qt_pumps=run['qt_pumps'],
                       capture_on_caller_thread=run['capture_on_caller_thread'])
            safe_to_close = (run['worker_exited'] and row['cleanup_pending'] is False
                             and row['helpers_exited'] and row['helper_pipes_closed'] and row['helper_jobs_closed'])
            if 'total_seconds' in row:
                row['outer_residual_seconds'] = row['total_seconds'] - row['phase_seconds']['wgc_inclusive'] - row['phase_seconds']['png_encode']
            if run['error'] is not None:
                row['error'] = error_record(run['error'])
            if run['value'] is not None:
                row['output'] = output_identity(run['value'])
                rect = run['value'][1]
                row['client_rect'] = [rect.x, rect.y, rect.width, rect.height]
            row['status'] = 'passed' if (run['error'] is None and not run['cancelled'] and run['worker_exited']
                and row.get('output') == expected and row['backend'] in BACKENDS and row['cleanup_pending'] is False
                and run['capture_on_caller_thread'] is (row['context'] == 'gui_blocked')
                and (row['context'] == 'gui_blocked' or run['qt_pumps'] > 0)
                and row['helpers_exited'] and row['helper_pipes_closed'] and row['helper_jobs_closed']) else 'failed'
        except Exception as error:
            cancelled.set()
            row.update(status='failed', error=error_record(error), **timing)
            safe_to_close = False
        failed = row['status'] != 'passed'
    return supplemental_report(rows, failed=failed, safe_to_close=safe_to_close)


def validate_diagnostics(value, record, *, inputs=None, native_sha256=None, pillow_version=None):
    """Validate observations, identity bindings, all fixed rows, and exact output."""
    errors = []
    try:
        if (value['status'] != 'passed' or type(value['schema_version']) is not int or value['schema_version'] != 1
                or type(value['errors']) is not list or value['errors']):
            errors.append('capture diagnostics failed')
        observations = value['authoritative_observations']
        expected_count = (record['warmups'] + len(record['samples_seconds'])) * record['iterations_per_sample']
        if (type(observations) is not list or len(observations) != expected_count
                or any(type(row) is not dict or set(row) != {'backend', 'cleanup_pending', 'one_shot_helper_sha256', 'fallback_reason'}
                       or row['backend'] not in BACKENDS or row['cleanup_pending'] is not False for row in observations)):
            errors.append('capture authoritative backend/cleanup evidence is incomplete')
        if len({(row['backend'], row['one_shot_helper_sha256'], row['fallback_reason']) for row in observations}) != 1:
            errors.append('capture authoritative backend changed')
        bounded_json(value)
        before, final = (value[name] for name in ('identity_before_supplemental', 'identity_after_supplemental'))
        if not before or not same_value(before, final):
            errors.append('capture diagnostic identity changed')
        for group in ('loaded', 'sources'):
            for proof in before[group].values():
                if not valid_record(proof):
                    errors.append('capture diagnostic file identity is invalid')
        if set(before['sources']) != set(SOURCE_FILES) or set(before['loaded']) != {'cv2_native', 'pillow_native', 'pillow_image', 'pillow_png'}:
            errors.append('capture diagnostic source/native inventory differs')
        if inputs is not None and any(inputs.get(name) != proof['sha256'] for name, proof in before['sources'].items()):
            errors.append('capture diagnostic source identity differs from probe inputs')
        if native_sha256 is not None and before['loaded']['cv2_native']['sha256'] != native_sha256:
            errors.append('capture diagnostic cv2 identity differs from loaded probe native')
        if pillow_version is not None and before['pillow_version'] != pillow_version:
            errors.append('capture diagnostic Pillow version differs')
        if type(before['bound_one_shot']) is not bool:
            errors.append('capture bound helper presence is not a boolean')
        if set(before['helpers']) != {'one_shot', 'session'}:
            errors.append('capture diagnostic helper inventory differs')
        for name, helper in before['helpers'].items():
            if helper['status'] == 'absent':
                if set(helper) != {'status'}:
                    errors.append('capture diagnostic missing helper identity is invalid')
                continue
            source = 'native/wgc_capture.cpp' if name == 'one_shot' else 'native/wgc_session_capture.cpp'
            recipe = 'scripts/build_wgc_capture.py' if name == 'one_shot' else 'scripts/build_wgc_session_capture.py'
            if (helper['status'] != 'verified' or type(helper['protocol']) is not int
                    or helper['protocol'] != (1 if name == 'one_shot' else 2)
                    or not re.fullmatch('[0-9a-f]{40}', helper['source_commit'])
                    or helper['source_sha256'] != before['sources'][source]['sha256']
                    or helper['build_recipe_sha256'] != before['sources'][recipe]['sha256']):
                errors.append('capture diagnostic helper source binding differs')
            for field in ('binary', 'manifest'):
                proof = helper[field]
                if not valid_record(proof):
                    errors.append('capture diagnostic helper identity is invalid')
        for row in observations:
            if row['backend'] == 'windows-graphics-capture':
                if (not before['bound_one_shot'] or before['helpers']['one_shot']['status'] != 'verified'
                        or row['one_shot_helper_sha256'] != before['helpers']['one_shot']['binary']['sha256']
                        or row['fallback_reason'] != 'not-applicable'):
                    errors.append('capture observed helper differs from verified helper')
            elif row['one_shot_helper_sha256'] is not None or row['fallback_reason'] != 'unrecorded':
                errors.append('capture GDI fallback provenance is invalid')
        expected = value['expected_output']
        rect = value['expected_client_rect']
        if (type(expected) is not dict or set(expected) != {'image_sha256', 'width', 'height'}
                or type(expected['image_sha256']) is not str or not re.fullmatch('[0-9a-f]{64}', expected['image_sha256'])
                or any(type(expected[key]) is not int or not 64 <= expected[key] <= 16_000_000 for key in ('width', 'height'))
                or expected['width'] * expected['height'] > 16_000_000
                or type(rect) is not list or len(rect) != 4
                or any(type(v) is not int or not -(2**31) <= v < 2**31 for v in rect)
                or rect[2:] != [expected['width'], expected['height']]):
            errors.append('capture expected output/physical geometry is invalid')
        if not same_value([expected['width'], expected['height']], [record['fixture']['width'], record['fixture']['height']]):
            errors.append('capture diagnostic output size differs from authoritative fixture')
        encoded = json.dumps(expected, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')
        if hashlib.sha256(encoded).hexdigest() != record['output_sha256']:
            errors.append('capture diagnostic output differs from authoritative fingerprint')
        detail = value['supplemental']
        if (detail['status'] != 'passed' or type(detail['schema_version']) is not int or detail['schema_version'] != 1 or detail['scope'] != SCOPE
                or detail['excluded_from_adoption'] is not True or type(detail['calls_per_context']) is not int
                or detail['calls_per_context'] != CALLS_PER_CONTEXT
                or type(detail['call_timeout_seconds']) is not float or detail['call_timeout_seconds'] != CALL_TIMEOUT
                or type(detail['cancellation_grace_seconds']) is not float or detail['cancellation_grace_seconds'] != CANCEL_GRACE
                or detail['deadline_kind'] != DEADLINE_KIND
                or detail['safe_to_close_fixture'] is not True):
            errors.append('capture supplemental diagnostic contract differs')
        rows = detail['rows']
        if (type(rows) is not list or any(type(row['index']) is not int for row in rows)
                or [(row['context'], row['index']) for row in rows] != [(c, i) for c in CONTEXTS for i in range(CALLS_PER_CONTEXT)]):
            errors.append('capture supplemental row inventory differs')
        for row in rows:
            if (row['status'] != 'passed' or not same_value(row['output'], expected) or row['backend'] != observations[-1]['backend']
                    or not same_value(row['client_rect'], value['expected_client_rect'])
                    or row['one_shot_helper_sha256'] != observations[-1]['one_shot_helper_sha256']
                    or row['fallback_reason'] != observations[-1]['fallback_reason']
                    or row['capture_on_caller_thread'] is not (row['context'] == 'gui_blocked')
                    or row['cleanup_pending'] is not False or row['worker_exited'] is not True or row['cancelled'] is not False
                    or any(row[field] is not True for field in ('helpers_exited', 'helper_pipes_closed', 'helper_jobs_closed'))):
                errors.append('capture supplemental output/backend/cleanup failed')
            if (set(row['phase_seconds']) != set(PHASES) or set(row['phase_calls']) != set(PHASES)
                    or any(type(t) not in (int, float) or not math.isfinite(t) or t < 0 for t in row['phase_seconds'].values())
                    or any(type(n) is not int or n < 0 for n in row['phase_calls'].values())
                    or type(row['total_seconds']) not in (int, float) or not math.isfinite(row['total_seconds']) or row['total_seconds'] <= 0):
                errors.append('capture supplemental phase timings are invalid')
            residual = row['total_seconds'] - row['phase_seconds']['wgc_inclusive'] - row['phase_seconds']['png_encode']
            if (residual < 0 or type(row['outer_residual_seconds']) not in (int, float)
                    or not math.isfinite(row['outer_residual_seconds'])
                    or not math.isclose(row['outer_residual_seconds'], residual, rel_tol=1e-12, abs_tol=1e-12)):
                errors.append('capture supplemental nested timing arithmetic differs')
            if sum(row['phase_seconds'][phase] for phase in ('helper_verify', 'frame_decode')) > row['phase_seconds']['wgc_inclusive']:
                errors.append('capture supplemental nested spans exceed parent')
            if (row['phase_calls']['png_encode'] != 1 or type(row['qt_pumps']) is not int or row['qt_pumps'] < 0
                    or type(row['helper_starts']) is not int or row['helper_starts'] < 0):
                errors.append('capture supplemental call/pump evidence differs')
            if row['context'] == 'gui_blocked' and row['qt_pumps'] != 0:
                errors.append('capture GUI-blocked context pumped Qt')
            if row['context'] == 'worker_qt_pumped' and row['qt_pumps'] <= 0:
                errors.append('capture worker context has no observed Qt pumping')
            if row['backend'] == 'windows-graphics-capture':
                if row['helper_starts'] != 1 or any(row['phase_calls'][phase] != 1 for phase in PHASES):
                    errors.append('capture supplemental one-shot helper count differs')
            elif row['helper_starts'] != 0 or any(row['phase_calls'][phase] != 0 for phase in PHASES[:-1]):
                errors.append('capture supplemental GDI unexpectedly invoked WGC')
    except (KeyError, TypeError, ValueError, AttributeError, IndexError):
        errors.append('capture diagnostic schema is incomplete')
    return errors

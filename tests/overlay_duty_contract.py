"""Pure validation of bounded, observed native capture/inference duty evidence.

No archived Python or report-provided code is imported. Synthetic fixture timings
include explicit diagnostic holds and are never advertised as production speed.
"""
from __future__ import annotations
import math
import re

SOURCE_FILES = ('frame_inference_worker.py', 'partial_candidates.py', 'lcu_selection.py', 'live_client_identity.py',
    'assets/riotgames.pem', 'public_payload.py', 'native_smoke.py', 'native_ui.py', 'portrait_display.py', 'local_debug.py', 'hero_recognition.py', 'hero_portraits.py',
    'local_ocr.py', 'ocr_privacy.py', 'model_inventory.py', 'frame_ocr_cache.py', 'native_state.py',
    'screen_capture.py', 'wgc_capture.py', 'persistent_capture_adapter.py', 'wgc_session_capture.py',
    'native/wgc_session_capture.cpp', 'native/wgc_capture.cpp', 'scripts/build_wgc_session_capture.py',
    'scripts/build_wgc_capture.py', 'session_windows.py', 'synthetic_vision.py', 'overlay_geometry.py',
    'hero_strength.py', 'engine.py', 'launcher.py', 'tests/windows_native_smoke.py',
    'tests/overlay_duty_contract.py', 'fixtures/auto-scene.png', 'fixtures/demo.json')
CASES = ('unchanged', 'changed_roi', 'changed_hud', 'unknown_hud', 'stop_late')
STATE_FIELDS = ('last_observation', 'automatic_frames', 'hero_stable_frames', 'stable_frames',
                'generation', 'accepted_observed_at')
SCOPE = ('Original synthetic native Windows HWND + real capture/PortraitMatcher/OCR; controlled '
         'diagnostic holds, not live-game or user-machine latency')
COMPARISON_SCOPE = ('Counterfactual whole-cycle hidden duration on this same instrumented run; '
                    'not a measured baseline executable')


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def number(value, label, *, minimum=0, maximum=8000):
    require(type(value) in (int, float) and math.isfinite(value) and minimum <= value <= maximum,
            'Invalid finite duty timing/measurement: ' + label)
    return value


def integer(value, label, *, minimum=0, maximum=10000):
    require(type(value) is int and minimum <= value <= maximum, 'Invalid duty integer: ' + label)
    return value


def state(value, label, *, allow_revoked=False):
    require(type(value) is dict and set(value) == set(STATE_FIELDS), 'Duty state snapshot fields differ: ' + label)
    number(value['last_observation'], label + '.last_observation', minimum=0, maximum=1e12)
    if not (allow_revoked and value['accepted_observed_at'] is None):
        number(value['accepted_observed_at'], label + '.accepted_observed_at', minimum=0, maximum=1e12)
    for key in ('automatic_frames', 'hero_stable_frames', 'stable_frames', 'generation'):
        integer(value[key], label + '.' + key, maximum=2**31-1)
    require((allow_revoked and value['accepted_observed_at'] is None) or (value['accepted_observed_at'] > 0 and value['accepted_observed_at'] == value['last_observation']),
            'Duty phase lacks previously accepted observation')
    return value


RECEIPT_FIELDS = ('request_cutoff_100ns', 'frame_100ns', 'idle_enter_100ns', 'request_id',
    'session_generation', 'helper_pid', 'helper_created', 'overlay_hwnd', 'overlay_extended_style',
    'overlay_affinity', 'overlay_registration_valid')
CLEANUP_FIELDS = ('owner_revoked', 'transport_revoked', 'owner_close_done', 'capture_call_done',
    'process_exited', 'pipes_closed', 'pipe_worker_done', 'stderr_worker_done', 'job_closed',
    'ready_for_replacement', 'adapter_cleanup_complete')


def session_capture(value, scene):
    require(type(value) is dict and set(value) == {'receipt', 'capture_start_100ns', 'capture_return_100ns',
        'copied_after_capture_return', 'observation'}, 'Duty guarded-idle capture evidence missing or forged')
    receipt = value['receipt']
    require(type(receipt) is dict and set(receipt) == set(RECEIPT_FIELDS), 'Duty guarded-idle receipt fields differ')
    for key in RECEIPT_FIELDS:
        if key == 'overlay_registration_valid':
            require(receipt[key] is True, 'Duty guarded-idle registration is invalid')
        else:
            integer(receipt[key], 'receipt.' + key, minimum=1, maximum=2**63-1)
    require(receipt['helper_pid'] < 2**32 and receipt['overlay_extended_style'] < 2**32,
            'Duty receipt identity/style out of range')
    start = integer(value['capture_start_100ns'], 'QPC capture start', minimum=1, maximum=2**63-1)
    end = integer(value['capture_return_100ns'], 'QPC capture return', minimum=1, maximum=2**63-1)
    require(start <= receipt['request_cutoff_100ns'] < receipt['frame_100ns'] <= receipt['idle_enter_100ns'] <= end
            and end-start <= 80_000_000, 'Duty receipt is stale or not inside this complete capture')
    require(value['copied_after_capture_return'] is True, 'Duty receipt was copied before complete capture return')
    observation = value['observation']
    observed_keys = ('helper_pid', 'helper_created', 'session_generation', 'overlay_hwnd',
                     'overlay_extended_style', 'overlay_affinity', 'overlay_registration_valid')
    require(type(observation) is dict and set(observation) == set(observed_keys) | {'helper_alive', 'overlay_opaque', 'native_visible'},
            'Duty independent OS session observation missing')
    for key in observed_keys:
        require(type(observation[key]) is type(receipt[key]) and observation[key] == receipt[key],
                'Duty independent helper/overlay identity differs: ' + key)
    require(observation['helper_alive'] is True and observation['overlay_opaque'] is True
            and observation['native_visible'] is False, 'Duty helper is not alive/guarded or native overlay was visible during acquisition')
    for key in ('overlay_hwnd', 'overlay_extended_style', 'overlay_affinity'):
        require(receipt[key] == scene[key], 'Duty receipt is bound to a different opaque product overlay')
    return receipt


def validate_overlay_duty(native, *, expected_fixture_sha256):
    require(type(native) is dict and native.get('overlay_duty_cycle_passed') is True,
            'Native overlay duty proof missing')
    report = native.get('overlay_duty_cycle')
    require(type(report) is dict and type(report.get('schema_version')) is int and report['schema_version'] == 2,
            'Overlay duty schema differs')
    require(report.get('scope') == SCOPE and type(report.get('artificial_hold_target_ms')) is int
            and report['artificial_hold_target_ms'] == 350, 'Duty diagnostic hold/scope disclosure differs')
    scene = report.get('scene_binding')
    scene_keys = {'window_identity', 'target_created', 'capture_rect', 'overlay_hwnd', 'overlay_extended_style',
                  'overlay_affinity', 'overlay_opaque', 'fixture_sha256', 'qt_translucent_background', 'qt_opaque_paint_event',
                  'qt_window_opacity', 'surface_has_alpha', 'surface_alpha_buffer_size', 'outer_corner_rgba'}
    require(type(scene) is dict and set(scene) == scene_keys, 'Duty exact shared scene binding missing')
    identity=scene['window_identity'];rect=scene['capture_rect']
    require(type(identity) is list and len(identity)==3
            and all(type(value) is int and 0<value<2**63 for value in identity[:2])
            and identity[1]<2**32 and type(identity[2]) is str and 0<len(identity[2])<=256,
            'Duty shared scene HWND/PID identity has invalid types')
    require(type(rect) is dict and set(rect)=={'x','y','width','height'}
            and all(type(value) is int for value in rect.values())
            and (rect['width'],rect['height'])==(960,600), 'Duty shared scene rectangle has invalid types')
    integer(scene['target_created'], 'target creation', minimum=1, maximum=2**63-1)
    integer(scene['overlay_hwnd'], 'overlay HWND', minimum=1, maximum=2**63-1)
    style = integer(scene['overlay_extended_style'], 'overlay style', minimum=1, maximum=2**32-1)
    require(style & 0x080800A8 == 0x080800A8 and scene['overlay_affinity'] == 17
            and type(scene['overlay_affinity']) is int and scene['overlay_opaque'] is True,
            'Duty scene is not the exact excluded opaque click-through product overlay')
    require(scene['qt_translucent_background'] is False and scene['qt_opaque_paint_event'] is True
            and type(scene['qt_window_opacity']) in (int,float) and scene['qt_window_opacity'] == 1
            and scene['surface_has_alpha'] is False and type(scene['surface_alpha_buffer_size']) is int
            and scene['surface_alpha_buffer_size'] in (-1,0) and scene['outer_corner_rgba'] == [[250,252,255,255]]*4
            and all(type(channel) is int for pixel in scene['outer_corner_rgba'] for channel in pixel),
            'Duty scene lacks the actual opaque Qt renderer/surface/corner evidence')
    require(type(scene['fixture_sha256']) is str and re.fullmatch(r'[0-9a-f]{64}', scene['fixture_sha256']),
            'Duty fixture digest missing')
    require(type(expected_fixture_sha256) is str and re.fullmatch(r'[0-9a-f]{64}',expected_fixture_sha256)
            and scene['fixture_sha256']==expected_fixture_sha256, 'Duty fixture differs from externally verified source bytes')
    baseline = report.get('baseline')
    require(type(baseline) is dict, 'Measured one-shot product baseline missing')
    baseline_summary = _validate_mode(baseline, 'one-shot', scene)
    cleanup_keys={'helper_count','helpers_exited','pipes_closed','jobs_closed','adapter_cleanup_complete','complete'}
    for label in ('cleanup','cleanup_before_persistent'):
        cleanup=baseline.get(label)
        require(type(cleanup) is dict and set(cleanup)==cleanup_keys,
                'Duty baseline was not completely cleaned before the persistent adapter swap')
        integer(cleanup['helper_count'], 'baseline helpers', minimum=15, maximum=15)
        for key in cleanup_keys-{'helper_count'}:
            require(cleanup[key] is True, 'Duty baseline cleanup proof missing: ' + label + '.' + key)
    require(baseline['cleanup']==baseline['cleanup_before_persistent'], 'Duty baseline swap cleanup changed')
    persistent_summary = _validate_mode(report, 'persistent', scene)
    reuse = report.get('reuse_captures')
    require(type(reuse) is list and len(reuse) == 2, 'Duty requires two sequential captures reusing one exact helper')
    receipts = [session_capture(value, scene) for value in reuse]
    first, second = receipts
    require(all(first[key] == second[key] for key in ('helper_pid','helper_created','session_generation')),
            'Duty sequential captures did not reuse the same helper identity/generation')
    require(first['request_id'] < second['request_id']
            and reuse[0]['capture_return_100ns'] < reuse[1]['capture_start_100ns']
            and all(first[key] < second[key] for key in ('request_cutoff_100ns','frame_100ns','idle_enter_100ns')),
            'Duty reused capture IDs/timestamps are stale or nonsequential')
    previous = reuse[-1]
    for base, row in zip(baseline['cases'], report['cases']):
        current = row['session_capture'];receipt = current['receipt'];old = previous['receipt']
        require(previous['capture_return_100ns'] < current['capture_start_100ns'], 'Duty case replayed a prior capture receipt')
        if all(old[key] == receipt[key] for key in ('helper_pid','helper_created','session_generation')):
            require(old['request_id'] < receipt['request_id'], 'Duty case request ID did not advance')
        previous = current
        for bp, pp in zip(base['phases'], row['phases']):
            for key in ('window_identity','capture_rect','roi','candidate_roi_sha256','accepted_candidate_roi_sha256',
                        'hud_input_sha256','accepted_hud_input_sha256','vocabulary_sha256','source_metadata_sha256','matcher_configuration'):
                require(bp[key] == pp[key], 'Duty modes used different actual scene/matcher inputs: ' + key)
    return {'schema_version':2, 'baseline':baseline_summary, 'persistent':persistent_summary, 'scene_binding':scene}


def _validate_mode(report, mode, scene):
    constructor = 'Win32Capture()' if mode == 'persistent' else 'Win32Capture(persistent_sessions=False)'
    require(report.get('mode') == mode and report.get('adapter_constructor') == constructor,
            'Duty product adapter mode or constructor differs')
    fresh = report.get('fresh_state')
    require(type(fresh) is dict and set(fresh) == {'confirmed','automatic_frames','hero_stable_frames',
            'stable_frames','accepted_frame_present','ocr_cache_cleared'}, 'Duty independent fresh confirmation proof missing')
    require(fresh['confirmed'] is False and fresh['accepted_frame_present'] is False and fresh['ocr_cache_cleared'] is True,
            'Duty modes reused accepted-frame or cached proof')
    for key in ('automatic_frames','hero_stable_frames','stable_frames'):
        require(type(fresh[key]) is int and fresh[key] == 0, 'Duty mode started with reused confirmation counters')
    rows = report.get('cases')
    require(type(rows) is list and len(rows) == len(CASES), 'Duty requires every observation case')
    summaries = []
    stable_binding = None
    for row, expected in zip(rows, CASES):
        require(type(row) is dict and row.get('name') == expected and row.get('status') == 'passed'
                and 'error' not in row and row.get('mode') == mode, 'Duty case order/status/mode differs')
        timings = row.get('timings_ms')
        keys = ('capture_start', 'capture_return', 'before_match_emitted', 'before_match_applied',
                'before_ocr_emitted', 'before_ocr_applied', 'gui_compositor_validated', 'result_received', 'final')
        required = set(keys) | ({'stop'} if expected == 'stop_late' else set())
        require(type(timings) is dict and set(timings) == required, 'Duty event inventory differs: ' + expected)
        for key, value in timings.items():
            number(value, expected + '.' + key)
        require(timings['capture_start'] < timings['capture_return'] <= timings['before_match_emitted']
                <= timings['before_match_applied'] <= timings['before_ocr_emitted']
                <= timings['before_ocr_applied'] < timings['result_received'] <= timings['final'], 'Duty phase/capture ordering differs')
        require(abs(number(row.get('capture_duration_ms'), 'capture duration') - (timings['capture_return']-timings['capture_start'])) <= .002,
                'Duty measured capture duration differs from capture boundaries')
        require(timings['capture_return'] <= timings['gui_compositor_validated'] <= timings['before_ocr_applied'],
                'Duty compositor validation preceded capture or followed phase')
        require(number(row.get('total_ms'), 'total') == timings['final']
                and number(row.get('old_hide_until_final_policy_counterfactual_ms'), 'counterfactual') == timings['final']
                and row.get('comparison_scope') == COMPARISON_SCOPE, 'Duty counterfactual misrepresented or duration differs')
        hidden = number(row.get('sampled_hidden_ms'), 'hidden')
        visible = number(row.get('sampled_visible_ms'), 'visible')
        inference = number(row.get('sampled_inference_visible_ms'), 'inference visible')
        gap = number(row.get('max_sample_gap_ms'), 'sampling gap', maximum=150)
        require(hidden + visible <= row['total_ms'] + .005 and hidden + visible > 0
                and row['total_ms'] - hidden - visible <= gap + .005 and inference <= visible + .005,
                'Duty sampled durations are incoherent')
        samples = integer(row.get('native_visibility_samples'), 'native visibility samples', minimum=4)
        held_samples = integer(row.get('held_state_unchanged_samples'), 'unchanged held-state samples', minimum=4)
        require(held_samples <= samples, 'Held-state samples exceed native visibility samples')
        transitions = row.get('sampled_visibility_transitions')
        pattern = [True, False] + ([True] if expected in ('unchanged', 'changed_roi', 'stop_late') else []) + ([False] if expected == 'stop_late' else [])
        require(type(transitions) is list and len(transitions) == len(pattern), 'Duty visibility transition count differs')
        for transition, wanted in zip(transitions, pattern):
            require(type(transition) is dict and set(transition) == {'at_ms', 'visible'} and transition['visible'] is wanted,
                    'Duty native visibility transition differs')
            number(transition['at_ms'], 'visibility transition', maximum=row['total_ms']+.05)
        times = [point['at_ms'] for point in transitions]
        require(all(left < right for left, right in zip(times, times[1:])) and times[1] <= timings['capture_start'],
                'Duty overlay was not hidden before acquisition or transition order differs')
        if expected in ('unchanged', 'stop_late'):
            require(timings['before_match_applied'] <= times[2] <= timings['before_match_applied']+gap+.05,
                    'Duty overlay restore timing differs from early phase')
        if expected == 'changed_roi':
            require(row.get('fixture_change') == 'Original 12x12 non-text patch inside candidate ROI, above title band; synthetic animation analogue, not actual gameplay measurement',
                    'Changed ROI fixture disclosure missing')
            require(timings['result_received'] <= times[2] <= timings['final']+.05,
                    'Changed candidate ROI showed prior cards before the final result')
        if expected == 'stop_late':
            require(timings['stop'] <= times[3] <= timings['stop']+row.get('stop_return_ms', 0)+gap+.05,
                    'Stop did not promptly hide the native overlay')
        calculated_hidden=calculated_visible=calculated_inference=0.
        for index, point in enumerate(transitions):
            end=times[index+1] if index+1<len(times) else max(row['total_ms'],times[-1])
            duration=end-point['at_ms']
            if point['visible']:
                calculated_visible+=duration
                calculated_inference+=max(0.,min(end,timings['result_received'])-max(point['at_ms'],timings['capture_return']))
            else:
                calculated_hidden+=duration
        require(abs(calculated_hidden-hidden) <= .05 and abs(calculated_visible-visible) <= .05
                and abs(calculated_inference-inference) <= .05, 'Duty durations disagree with observed transitions')
        capture_samples = integer(row.get('capture_samples'), 'capture samples', minimum=2)
        require(capture_samples <= samples and row.get('capture_visible_samples') == 0
                and type(row.get('capture_visible_samples')) is int, 'Own overlay visible while acquiring pixels')
        require(type(row.get('qt_show_events_during_capture')) is int and row['qt_show_events_during_capture'] == 0,
                'Qt overlay became visible during acquisition')
        require(integer(row.get('capture_count'), 'capture count', minimum=1) == 1
                and integer(row.get('max_capture_concurrency'), 'capture concurrency', minimum=1) == 1,
                'Duty capture count or no-overlap contract differs')
        holds = row.get('artificial_holds_ms')
        require(type(holds) is dict and set(holds) == {'before_match', 'before_ocr'}, 'Duty artificial hold inventory differs')
        for key in holds:
            number(holds[key], 'hold ' + key, minimum=350, maximum=4000)
        require(timings['before_ocr_emitted'] - timings['before_match_emitted'] + .005 >= holds['before_match']
                and timings['final'] - timings['before_ocr_emitted'] + .005 >= holds['before_ocr'],
                'Duty holds exceed observed phase intervals')
        expected_backend = 'windows-graphics-capture-session' if mode == 'persistent' else 'windows-graphics-capture'
        require(row.get('capture_backend') == expected_backend, 'Duty capture did not use the required real WGC mode')
        require(integer(row.get('helper_count'), 'helper count', minimum=1) == 1, 'Duty helper identity count differs')
        if mode == 'one-shot':
            require(type(row.get('helper_exit_codes')) is list and len(row['helper_exit_codes']) == 1
                    and type(row['helper_exit_codes'][0]) is int and row['helper_exit_codes'][0] == 0
                    and row.get('helper_cleanup_complete_before_phase') is True, 'Duty one-shot helper lifecycle evidence differs')
            require('session_capture' not in row, 'Duty baseline fabricated a persistent receipt')
        else:
            require('helper_exit_codes' not in row and 'helper_cleanup_complete_before_phase' not in row,
                    'Duty persistent mode misrepresented guarded idle as helper exit')
            session_capture(row.get('session_capture'), scene)
        phases = row.get('phases')
        require(type(phases) is list and len(phases) == 2, 'Duty requires both inference phases')
        for phase, name in zip(phases, ('before_match', 'before_ocr')):
            require(type(phase) is dict and phase.get('name') == name, 'Duty phase inventory differs')
            for key in ('emitted_ms', 'applied_ms', 'compositor_validated_ms'):
                number(phase.get(key), name + '.' + key)
            require(phase['emitted_ms'] == timings[name+'_emitted'] and phase['applied_ms'] == timings[name+'_applied']
                    and timings['capture_return'] <= phase['compositor_validated_ms'] <= phase['applied_ms'],
                    'Duty per-phase dispatch/compositor timing differs')
            for key in ('current_identity_geometry_focus',
                        'helper_cleanup_complete' if mode == 'one-shot' else 'session_guarded_idle_verified',
                        'compositor_checked_after_capture'):
                require(phase.get(key) is True, 'Duty phase safety evidence missing: ' + key)
            require(('helper_cleanup_complete' not in phase) if mode == 'persistent' else ('session_guarded_idle_verified' not in phase),
                    'Duty phase mixed helper-exit and guarded-idle modes')
            revoke = expected in ('changed_hud', 'unknown_hud') and name == 'before_ocr'
            before, during = state(phase.get('state_before'), 'before'), state(phase.get('state_at_phase'), 'during', allow_revoked=revoke)
            expected_during = dict(before, automatic_frames=0, stable_frames=0, accepted_observed_at=None) if revoke else before
            require(during == expected_during and before == phases[0]['state_before'],
                    'Intermediate duty proof must only revoke unsafe evidence, never renew TTL or promote counters')
            require(type(phase.get('state_unchanged')) is bool and phase['state_unchanged'] == (before == during),
                    'Duty state-unchanged flag disagrees with observed operands')
            for key in ('restored', 'qt_visible', 'native_visible'):
                require(phase.get(key) is (expected in ('unchanged', 'stop_late')),
                        'Duty phase restored changed/unknown HUD or hid unchanged HUD: ' + key)
            identity = phase.get('window_identity')
            current_identity = phase.get('current_window_identity')
            require(type(current_identity) is list and len(current_identity) == 3
                    and all(type(value) is int and value > 0 for value in current_identity[:2])
                    and type(current_identity[2]) is str and 0 < len(current_identity[2]) <= 256,
                    'Duty current window identity has invalid types')
            require(type(identity) is list and len(identity) == 3
                    and all(type(value) is int and value > 0 for value in identity[:2])
                    and type(identity[2]) is str and 0 < len(identity[2]) <= 256
                    and phase.get('current_window_identity') == identity,
                    'Duty current/native window identity differs')
            for field in ('capture_rect', 'current_rect'):
                rect = phase.get(field)
                require(type(rect) is dict and set(rect) == {'x', 'y', 'width', 'height'}
                        and all(type(value) is int for value in rect.values())
                        and (rect['width'], rect['height']) == (960, 600), 'Duty capture geometry differs')
            require(phase['capture_rect'] == phase['current_rect'] == scene['capture_rect']
                    and phase['window_identity'] == scene['window_identity'], 'Duty current capture scene binding changed')
            for key in ('candidate_roi_sha256', 'accepted_candidate_roi_sha256', 'hud_input_sha256',
                        'accepted_hud_input_sha256', 'vocabulary_sha256', 'source_metadata_sha256'):
                require(type(phase.get(key)) is str and re.fullmatch(r'[0-9a-f]{64}', phase[key]),
                        'Duty exact pixel/source binding missing: ' + key)
            require((phase['candidate_roi_sha256'] == phase['accepted_candidate_roi_sha256']) == (expected != 'changed_roi'),
                    'Duty candidate ROI changed from accepted cards')
            require((phase['hud_input_sha256'] == phase['accepted_hud_input_sha256'])
                    == (expected in ('unchanged', 'changed_roi', 'stop_late')), 'Duty HUD digest observation does not match case')
            require(phase.get('scope_matches_accepted') is True
                    and phase.get('matcher_instance_matches_accepted') is True
                    and phase.get('matcher_type') == 'PortraitMatcher', 'Duty scope/matcher identity changed')
            configuration = phase.get('matcher_configuration')
            require(type(configuration) is list and len(configuration) == 2
                    and all(type(value) in (int, float) and math.isfinite(value) for value in configuration)
                    and configuration == [.88, .07], 'Duty matcher confidence policy differs')
            roi = phase.get('roi')
            require(type(roi) is list and len(roi) == 4
                    and all(type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 1 for value in roi)
                    and roi[2] > 0 and roi[3] > 0 and roi[0]+roi[2] <= 1 and roi[1]+roi[3] <= 1,
                    'Duty candidate ROI scope invalid')
            integer(phase.get('capture_serial'), 'capture serial', minimum=1, maximum=2**31-1)
            captured = number(phase.get('captured_at'), 'captured time', maximum=1e12)
            age = captured - before['accepted_observed_at']
            require(0 < age <= 4, 'Duty observation is not independently newer or accepted reference is stale')
            if phase['restored']:
                require(age + (phase['applied_ms'] - timings['capture_start']) / 1000 <= 4,
                        'Duty restored an accepted reference past the 4-second freshness limit')
            binding = [identity, phase['capture_rect'], roi, phase['vocabulary_sha256'], phase['source_metadata_sha256'], configuration]
            if stable_binding is None:
                stable_binding = binding
            require(binding == stable_binding, 'Duty observation source/window/matcher scope changed')
            for key in ('capture_serial', 'captured_at', 'candidate_roi_sha256', 'accepted_candidate_roi_sha256',
                        'hud_input_sha256', 'accepted_hud_input_sha256'):
                require(phase[key] == phases[0][key], 'Duty phases do not describe the same capture: ' + key)
        final_captured = number(row.get('final_captured_at'), 'final capture time', maximum=1e12)
        last_observed = number(row.get('final_last_observation'), 'final observation time', maximum=1e12)
        result_generation = integer(row.get('final_result_generation'), 'result generation', maximum=2**31-1)
        state_generation = integer(row.get('final_state_generation'), 'state generation', maximum=2**31-1)
        require(final_captured == phases[0]['captured_at'] and result_generation == phases[0]['state_before']['generation'],
                'Duty final result was not the instrumented capture/generation')
        require(state_generation == result_generation if expected in ('unchanged', 'changed_roi') else state_generation > result_generation,
                'Duty final generation acceptance/revocation differs')
        if expected == 'stop_late':
            require(last_observed == phases[0]['state_before']['last_observation'], 'Late Stop result refreshed observation TTL')
        else:
            require(last_observed in (phases[0]['state_before']['last_observation'], final_captured),
                    'Duty final observation time does not match captured pixels')
        require(row.get('final_candidate_names') == ['星火共鸣', '晶盾回路', '风步微光'],
                'Duty actual final OCR candidate names changed or reordered')
        hero = row.get('final_hero_observation')
        require(type(hero) is dict and set(hero) == {'hero', 'confident'} and type(hero['confident']) is bool,
                'Duty final hero observation missing')
        if expected == 'unknown_hud':
            require(hero['confident'] is False and hero['hero'] in (None, ''), 'Unknown HUD manufactured a confident hero')
        else:
            require(hero['confident'] is True and hero['hero'] == ('磐石守卫（演示）' if expected == 'changed_hud' else '星火术士（演示）'),
                    'Duty concrete matcher returned the wrong hero')
        for key in ('final_confirmed', 'final_running', 'final_qt_visible', 'final_native_visible'):
            wanted = (expected in ('unchanged', 'changed_roi')) if key != 'final_running' else expected != 'stop_late'
            require(row.get(key) is wanted, 'Duty final state differs: ' + key)
        if expected == 'unchanged':
            require(inference >= 500, 'Unchanged overlay was not visible through controlled inference holds')
        elif expected in ('changed_roi', 'changed_hud', 'unknown_hud'):
            require(inference == 0, 'Changed/unknown HUD exposed prior cards during inference')
        else:
            require(inference >= 500 and timings['before_ocr_applied'] < timings['stop'] < timings['final']
                    and row.get('late_final_discarded') is True, 'Stop did not reject the late inference result')
            number(row.get('stop_return_ms'), 'Stop response', maximum=249.999)
            if mode == 'persistent':
                cleanup = row.get('stop_cleanup');receipt = row['session_capture']['receipt']
                require(type(cleanup) is dict and set(cleanup) == set(CLEANUP_FIELDS) | {'helper_pid','helper_created',
                    'session_generation','observed_ms','process_exit_code','termination_requested_while_alive','shutdown_diagnostic'}, 'Duty eventual Stop cleanup evidence missing')
                for key in CLEANUP_FIELDS:
                    require(cleanup[key] is True, 'Duty eventual Stop cleanup not independently observed: ' + key)
                for key in ('helper_pid','helper_created','session_generation'):
                    require(type(cleanup[key]) is int and cleanup[key] == receipt[key], 'Duty Stop cleaned a different helper')
                code=cleanup['process_exit_code'];termination=cleanup['termination_requested_while_alive']
                require(type(code) is int and -(2**31)<=code<2**32, 'Duty Stop process exit unobserved')
                require(type(termination) is bool or termination is None, 'Duty Stop parent termination tri-state missing')
                require(code & 0xffffffff != 0xc0000005, 'Duty Stop observed a native access-violation crash')
                require(code==0 or termination is True, 'Duty nonzero Stop exit lacks observed deliberate parent termination')
                diagnostic=cleanup['shutdown_diagnostic']
                if diagnostic is not None:
                    stages=('frame-arrived-revoke','item-closed-revoke','session-close','pool-close','local-release','apartment-uninit','process-return')
                    require(type(diagnostic) is dict and set(diagnostic)=={'schema_version','exit_code','checkpoints','last_started_stage'}
                        and type(diagnostic['schema_version']) is int and diagnostic['schema_version']==1
                        and type(diagnostic['exit_code']) is int and diagnostic['exit_code']==code and code!=0
                        and type(diagnostic['checkpoints']) is list and 1<=len(diagnostic['checkpoints'])<=len(stages)
                        and all(type(value) is int and value==index for index,value in enumerate(diagnostic['checkpoints'],1))
                        and diagnostic['last_started_stage']==stages[len(diagnostic['checkpoints'])-1],
                        'Duty Stop shutdown diagnostic is malformed or exit-mismatched')
                require(number(cleanup['observed_ms'], 'Stop cleanup observation') >= timings['stop'] + row['stop_return_ms'],
                        'Duty eventual cleanup observation preceded Stop return')
        summaries.append({key: row[key] for key in ('name', 'total_ms', 'sampled_hidden_ms',
            'sampled_visible_ms', 'sampled_inference_visible_ms', 'max_sample_gap_ms', 'timings_ms',
            'mode', 'capture_duration_ms', 'capture_backend', 'capture_count', 'max_capture_concurrency', 'helper_count',
            'held_state_unchanged_samples', 'sampled_visibility_transitions', 'qt_show_events_during_capture',
            'old_hide_until_final_policy_counterfactual_ms', 'comparison_scope',
            'artificial_holds_ms', 'final_confirmed', 'final_running')})
        if mode == 'one-shot':summaries[-1]['helper_exit_codes'] = row['helper_exit_codes']
        else:
            summaries[-1]['session_capture'] = row['session_capture']
            if expected == 'stop_late':summaries[-1]['stop_cleanup'] = row['stop_cleanup']
    return summaries

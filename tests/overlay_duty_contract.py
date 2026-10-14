"""Pure validation of bounded, observed native capture/inference duty evidence.

No archived Python or report-provided code is imported. Synthetic fixture timings
include explicit diagnostic holds and are never advertised as production speed.
"""
from __future__ import annotations
import math
import re

SOURCE_FILES = ('native_smoke.py', 'native_ui.py', 'hero_recognition.py', 'hero_portraits.py',
    'local_ocr.py', 'ocr_privacy.py', 'model_inventory.py', 'frame_ocr_cache.py', 'native_state.py',
    'screen_capture.py', 'wgc_capture.py', 'synthetic_vision.py', 'overlay_geometry.py',
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


def state(value, label):
    require(type(value) is dict and set(value) == set(STATE_FIELDS), 'Duty state snapshot fields differ: ' + label)
    for key in ('last_observation', 'accepted_observed_at'):
        number(value[key], label + '.' + key, minimum=0, maximum=1e12)
    for key in ('automatic_frames', 'hero_stable_frames', 'stable_frames', 'generation'):
        integer(value[key], label + '.' + key, maximum=2**31-1)
    require(value['accepted_observed_at'] > 0 and value['accepted_observed_at'] == value['last_observation'],
            'Duty phase lacks previously accepted observation')
    return value


def validate_overlay_duty(native):
    require(type(native) is dict and native.get('overlay_duty_cycle_passed') is True,
            'Native overlay duty proof missing')
    report = native.get('overlay_duty_cycle')
    require(type(report) is dict and type(report.get('schema_version')) is int and report['schema_version'] == 1,
            'Overlay duty schema differs')
    require(report.get('scope') == SCOPE and type(report.get('artificial_hold_target_ms')) is int
            and report['artificial_hold_target_ms'] == 350, 'Duty diagnostic hold/scope disclosure differs')
    rows = report.get('cases')
    require(type(rows) is list and len(rows) == len(CASES), 'Duty requires every observation case')
    summaries = []
    stable_binding = None
    for row, expected in zip(rows, CASES):
        require(type(row) is dict and row.get('name') == expected and row.get('status') == 'passed'
                and 'error' not in row, 'Duty case order/status differs')
        timings = row.get('timings_ms')
        keys = ('capture_start', 'capture_return', 'before_match_emitted', 'before_match_applied',
                'before_ocr_emitted', 'before_ocr_applied', 'gui_compositor_validated', 'final')
        required = set(keys) | ({'stop'} if expected == 'stop_late' else set())
        require(type(timings) is dict and set(timings) == required, 'Duty event inventory differs: ' + expected)
        for key, value in timings.items():
            number(value, expected + '.' + key)
        require(timings['capture_start'] < timings['capture_return'] <= timings['before_match_emitted']
                <= timings['before_match_applied'] <= timings['before_ocr_emitted']
                <= timings['before_ocr_applied'] < timings['final'], 'Duty phase/capture ordering differs')
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
            require(timings['final'] <= times[2] <= timings['final']+.05,
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
                calculated_inference+=max(0.,end-max(point['at_ms'],timings['capture_return']))
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
        require(row.get('capture_backend') == 'windows-graphics-capture', 'Duty capture did not use the real WGC helper')
        require(integer(row.get('helper_count'), 'helper count', minimum=1) == 1
                and type(row.get('helper_exit_codes')) is list and len(row['helper_exit_codes']) == 1
                and type(row['helper_exit_codes'][0]) is int and row['helper_exit_codes'][0] == 0
                and row.get('helper_cleanup_complete_before_phase') is True, 'Duty helper lifecycle evidence differs')
        phases = row.get('phases')
        require(type(phases) is list and len(phases) == 2, 'Duty requires both inference phases')
        for phase, name in zip(phases, ('before_match', 'before_ocr')):
            require(type(phase) is dict and phase.get('name') == name, 'Duty phase inventory differs')
            for key in ('emitted_ms', 'applied_ms', 'compositor_validated_ms'):
                number(phase.get(key), name + '.' + key)
            require(phase['emitted_ms'] == timings[name+'_emitted'] and phase['applied_ms'] == timings[name+'_applied']
                    and timings['capture_return'] <= phase['compositor_validated_ms'] <= phase['applied_ms'],
                    'Duty per-phase dispatch/compositor timing differs')
            for key in ('state_unchanged', 'current_identity_geometry_focus', 'helper_cleanup_complete',
                        'compositor_checked_after_capture'):
                require(phase.get(key) is True, 'Duty phase safety evidence missing: ' + key)
            before, during = state(phase.get('state_before'), 'before'), state(phase.get('state_at_phase'), 'during')
            require(before == during and before == phases[0]['state_before'],
                    'Intermediate duty proof renewed TTL or confirmation counters')
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
            require(phase['capture_rect'] == phase['current_rect'], 'Duty current capture rectangle changed')
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
        summaries.append({key: row[key] for key in ('name', 'total_ms', 'sampled_hidden_ms',
            'sampled_visible_ms', 'sampled_inference_visible_ms', 'max_sample_gap_ms', 'timings_ms',
            'capture_backend', 'capture_count', 'max_capture_concurrency', 'helper_count',
            'held_state_unchanged_samples', 'sampled_visibility_transitions', 'qt_show_events_during_capture',
            'old_hide_until_final_policy_counterfactual_ms', 'comparison_scope',
            'helper_exit_codes', 'artificial_holds_ms', 'final_confirmed', 'final_running')})
    return summaries

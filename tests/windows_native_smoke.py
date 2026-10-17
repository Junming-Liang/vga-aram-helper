"""Actual Windows QtWidgets EXE acceptance on an original mock game window."""
from __future__ import annotations
import argparse
from contextlib import ExitStack
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
from windows_exe_smoke import isolated_windows_environment, smoke_workspace, terminate_tree
from overlay_duty_contract import SOURCE_FILES, SCOPE as DUTY_SCOPE, validate_overlay_duty, validate_badge_regions


NATIVE_AUTOMATION_FIELDS = ('automatic_hero_passed', 'automatic_choices_passed', 'auto_without_manual_hero_selection', 'auto_unknown_clears_passed', 'auto_hero_change_clears_passed', 'auto_manual_fallback_passed', 'own_overlay_hidden_capture_passed', 'unchanged_frame_ocr_reuse_passed', 'partial_candidate_slots_passed', 'partial_to_full_recovery_passed', 'async_capture_ui_passed')

APP_SCALES = ('1', '1.5', '2')


def evidence_prefix(app_scale):
    value = float(app_scale)
    if value not in (1.0, 1.5, 2.0):
        raise ValueError('Unsupported explicit native test scale')
    return 'windows-native' if value == 1.0 else 'windows-native-scale' + str(round(value * 100))


def native_environment(environ, work, app_scale):
    evidence_prefix(app_scale)
    env = isolated_windows_environment(environ, work)
    for key in list(env):
        if key.startswith(('QT_', 'PYSIDE_')):
            env.pop(key)
    env['QT_SCALE_FACTOR'] = str(app_scale)
    return env


def validate_physical_geometry(result, app_scale):
    if result.get('physical_mock_geometry_passed') is not True or result.get('overlay_layout_passed') is not True:
        raise RuntimeError('Native physical mock geometry or visible text layout was not verified')
    for key in ('requested_app_scale', 'mock_qwindow_dpr', 'overlay_qwindow_dpr'):
        value = result.get(key)
        if type(value) not in (int, float) or not math.isfinite(value) or abs(value-float(app_scale)) > .01:
            raise RuntimeError('Native requested/measured Qt scale mismatch: ' + key)
    rects = {}
    for key in ('desktop_work_area_physical', 'mock_window_physical', 'clientRect', 'overlay_window_physical'):
        rect = result.get(key)
        if not isinstance(rect, dict) or set(rect) != {'x', 'y', 'width', 'height'} or any(type(v) is not int for v in rect.values()) or min(rect['width'], rect['height']) <= 0:
            raise RuntimeError('Native physical rectangle is invalid: ' + key)
        rects[key] = rect
    def contained(outer, inner):
        return (inner['x'] >= outer['x'] and inner['y'] >= outer['y'] and
                inner['x']+inner['width'] <= outer['x']+outer['width'] and
                inner['y']+inner['height'] <= outer['y']+outer['height'])
    client = rects['clientRect']
    if (client['width'], client['height']) != (960, 600):
        raise RuntimeError('Native mock client was not the fixed 960x600 physical fixture')
    for outer, inner in (('desktop_work_area_physical', 'mock_window_physical'),
                         ('mock_window_physical', 'clientRect'), ('clientRect', 'overlay_window_physical')):
        if not contained(rects[outer], rects[inner]):
            raise RuntimeError('Native physical containment failed: ' + inner)
    if rects['overlay_window_physical']['height']*2>client['height']:
        raise RuntimeError('Native overlay covers more than half the client height')
    if type(result.get('overlay_compact')) is not bool:
        raise RuntimeError('Native compact layout state is missing')


def validate_report(result, version, app_scale=1, *, executable_sha256=None, expected_fixture_sha256=None):
    if type(result) is not dict:
        raise RuntimeError('Native report must be an object')
    if result.get('status') != 'passed' or 'error' in result:
        raise RuntimeError('Native overlay self-test did not pass')
    if result.get('backend') != 'qtwidgets' or result.get('frozen') is not True:
        raise RuntimeError('Report is not a frozen native QtWidgets executable')
    if result.get('applicationVersion') != version:
        raise RuntimeError('Native executable version mismatch')
    for field in ('native_window', 'window_closed', 'capture_passed', 'ocr_passed', 'click_through_passed',
                  'source_hint_renderer_passed', 'three_badge_regions_verified', 'badge_gap_hit_test_passed', 'badge_above_cards_verified', 'badge_revocation_hidden_verified', 'source_tier_display_passed', 'source_tier_hero_specific', 'source_tier_missing_passed',
                  'source_tier_screen_order_preserved', 'source_tier_no_winrate_display'):
        if result.get(field) is not True:
            raise RuntimeError('Native evidence missing: ' + field)
    if str(result.get('qt_platform', '')).lower() != 'windows':
        raise RuntimeError('Native proof requires the real Windows Qt platform')
    if not result.get('screenshot_method'):
        raise RuntimeError('Native screenshot method was not recorded')
    for field in NATIVE_AUTOMATION_FIELDS:
        if result.get(field) is not True:
            raise RuntimeError('Automatic hero/candidate native proof missing: ' + field)
    if result.get('card_names_accessible') != ['星火共鸣','晶盾回路','风步微光']:
        raise RuntimeError('Native accessible card identities are incomplete or reordered')
    if result.get('source_tier_rendered') != ['T1','T2','T3']:
        raise RuntimeError('Native literal source-tier rendering evidence is incomplete')
    if result.get('source_tier_accessible') != [f'选项 {i} · {name} · T{i} · 演示评级' for i,name in enumerate(['星火共鸣','晶盾回路','风步微光'],1)]:
        raise RuntimeError('Native accessible source-tier evidence is incomplete')
    if result.get('badge_source_markers') != ['演示评级']*3 or result.get('source_details_reachable') is not True:
        raise RuntimeError('Native visible source and reachable source details are incomplete')
    if result.get('source_hint_render_scope') != 'Original synthetic sourceHint renderer only; not live-game or source-combo accuracy' or not isinstance(result.get('source_hint_visible_text'),str) or not result['source_hint_visible_text']:
        raise RuntimeError('Native owned source-hint renderer proof missing')
    validate_badge_regions(result)
    validate_physical_geometry(result, app_scale)
    if executable_sha256 is not None and result.get('executable_sha256') != executable_sha256:
        raise RuntimeError('Native report tested different executable bytes')
    validate_overlay_duty(result,expected_fixture_sha256=expected_fixture_sha256 or hashlib.sha256((ROOT/'fixtures/auto-scene.png').read_bytes()).hexdigest())


def native_failure_summary(path):
    """Bounded textual diagnostics from this run's OWN synthetic report only.

    This never exposes image bytes, arbitrary artifact entries or environment
    variables. It is informative only and cannot turn a failed test into a pass.
    """
    try:
        if not path.is_file():
            return {'report_present': False}
        if path.stat().st_size > 128 * 1024:
            return {'report_present': True, 'diagnostic_error': 'Native JSON exceeded 128 KiB'}
        value = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(value, dict):
            raise ValueError('Native JSON was not an object')
        result = {'report_present': True, 'native_report_sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
        for name, limit in (('status', 40), ('error_type', 120), ('error', 2000),
                            ('error_traceback', 4000), ('qt_platform', 80), ('applicationVersion', 40)):
            if isinstance(value.get(name), str):
                result[name] = value[name][:limit]
        if isinstance(value.get('checks'), list):
            result['last_completed_checks'] = [item[:500] for item in value['checks'][-8:] if isinstance(item, str)]
        for name in ('native_window', 'capture_passed', 'ocr_passed', 'physical_mock_geometry_passed',
                     'overlay_layout_passed', 'click_through_passed', 'window_closed'):
            if type(value.get(name)) is bool:
                result[name] = value[name]
        def detail(row):
            if type(row) is not dict:return {'invalid_row':True}
            output={}
            for key in ('mode','name','status','capture_backend','phase_state'):
                if type(row.get(key)) is str:output[key]=row[key][:80]
            for key in ('total_ms','capture_duration_ms','sampled_hidden_ms','sampled_visible_ms','sampled_inference_visible_ms',
                        'max_sample_gap_ms','native_visibility_samples','held_state_unchanged_samples',
                        'capture_samples','capture_visible_samples','capture_count','max_capture_concurrency',
                        'qt_show_events_during_capture','helper_count','stop_return_ms'):
                if type(row.get(key)) in (int,float) and math.isfinite(row[key]):output[key]=row[key]
            for key in ('initial_qt_visible','initial_native_visible','final_confirmed','final_running',
                        'final_qt_visible','final_native_visible','late_final_discarded'):
                if type(row.get(key)) is bool:output[key]=row[key]
            measurement=row.get('measurement_clock')
            if type(measurement) is dict:
                clock={}
                for key in ('name','implementation'):
                    if type(measurement.get(key)) is str:clock[key]=measurement[key][:120]
                for key in ('monotonic','adjustable'):
                    if type(measurement.get(key)) is bool:clock[key]=measurement[key]
                resolution=measurement.get('resolution_seconds')
                if type(resolution) in (int,float) and math.isfinite(resolution):clock['resolution_seconds']=resolution
                output['measurement_clock']=clock
            transitions=row.get('sampled_visibility_transitions')
            if type(transitions) is list:
                output['sampled_visibility_transitions']=[]
                for transition in transitions:
                    item={}
                    if type(transition) is dict:
                        stamp=transition.get('at_ms');shown=transition.get('visible')
                        if type(stamp) in (int,float) and math.isfinite(stamp):item['at_ms']=stamp
                        if type(shown) is bool:item['visible']=shown
                    output['sampled_visibility_transitions'].append(item or {'invalid_transition':True})
            timings=row.get('timings_ms')
            if type(timings) is dict:
                output['timings_ms']={key:timings[key] for key in ('capture_start','capture_return','before_match_emitted',
                    'before_match_applied','before_ocr_emitted','before_ocr_applied','gui_compositor_validated','stop','result_received','final')
                    if type(timings.get(key)) in (int,float) and math.isfinite(timings[key])}
            phases=row.get('phases')
            if type(phases) is list:
                output['phases']=[]
                for phase in phases:
                    if type(phase) is not dict:output['phases'].append({'invalid_phase':True});continue
                    item={}
                    if type(phase.get('name')) is str:item['name']=phase['name'][:80]
                    for key in ('emitted_ms','applied_ms','compositor_validated_ms','captured_at','capture_serial'):
                        if type(phase.get(key)) in (int,float) and math.isfinite(phase[key]):item[key]=phase[key]
                    for key in ('restored','qt_visible','native_visible','state_unchanged','current_identity_geometry_focus',
                                'helper_cleanup_complete','session_guarded_idle_verified','compositor_checked_after_capture'):
                        if type(phase.get(key)) is bool:item[key]=phase[key]
                    for key in ('state_before','state_at_phase'):
                        state=phase.get(key)
                        if type(state) is dict:item[key]={name:state[name] for name in ('last_observation','automatic_frames',
                            'hero_stable_frames','stable_frames','generation','accepted_observed_at')
                            if (name in state and state[name] is None) or (type(state.get(name)) in (int,float) and math.isfinite(state[name]))}
                    output['phases'].append(item)
            session=row.get('session_capture')
            if type(session) is dict:
                receipt=session.get('receipt')
                if type(receipt) is dict:
                    from overlay_duty_contract import RECEIPT_FIELDS
                    output['guarded_idle_receipt']={key:receipt[key] for key in RECEIPT_FIELDS if type(receipt.get(key)) in (int,bool)}
            cleanup=row.get('stop_cleanup')
            if type(cleanup) is dict:
                from overlay_duty_contract import CLEANUP_FIELDS
                output['stop_cleanup']={key:cleanup[key] for key in (*CLEANUP_FIELDS,'helper_pid','helper_created',
                    'session_generation','process_exit_code','observed_ms') if type(cleanup.get(key)) in (int,bool,float)
                    and (type(cleanup[key]) is not float or math.isfinite(cleanup[key]))}
                termination=cleanup.get('termination_requested_while_alive')
                if type(termination) is bool or termination is None:output['stop_cleanup']['termination_requested_while_alive']=termination
                from wgc_session_capture import sanitize_session_shutdown_diagnostic
                diagnostic=sanitize_session_shutdown_diagnostic(cleanup.get('shutdown_diagnostic'),cleanup.get('process_exit_code'))
                output['stop_cleanup']['shutdown_diagnostic']=diagnostic
            return output
        duty = value.get('overlay_duty_cycle')
        if type(duty) is dict:
            if type(duty.get('active_mode')) is str:result['duty_active_mode']=duty['active_mode'][:80]
            for prefix,mode in (('duty',duty),('duty_baseline',duty.get('baseline'))):
                if type(mode) is not dict:continue
                rows=mode.get('cases')
                if type(rows) is list:
                    result[prefix+'_case_count']=len(rows)
                    # The input itself is capped at 128 KiB. Preserve EVERY row;
                    # truncating to five would conceal malformed/additional work.
                    result[prefix+'_cases']=[detail(row) for row in rows]
                if type(mode.get('active_case')) is dict:result[prefix+'_active_case']=detail(mode['active_case'])
        return result
    except (OSError, ValueError, UnicodeError) as exc:
        return {'diagnostic_error': type(exc).__name__ + ': native JSON could not be read'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--exe', type=Path, required=True)
    parser.add_argument('--report-dir', type=Path, default=ROOT / 'reports')
    parser.add_argument('--app-scale', choices=APP_SCALES, default='1', help='Per-process Qt scale only; does not change Windows display settings')
    args = parser.parse_args()
    if os.name != 'nt':
        raise SystemExit('Requires the actual Windows executable and native Windows desktop')
    original = args.exe.resolve()
    reports = args.report_dir.resolve()
    reports.mkdir(parents=True, exist_ok=True)
    prefix = evidence_prefix(args.app_scale)
    report_path = reports / (prefix + '-overlay.json')
    result = {'status': 'failed', 'requested_app_scale': float(args.app_scale), 'executable_sha256': hashlib.sha256(original.read_bytes()).hexdigest(),
              'scope': 'Original synthetic mock window only; no real game, Vanguard or exclusive-fullscreen compatibility claim.'}
    try:
        with smoke_workspace() as work, ExitStack() as cleanup:
            result.update(executable_size=original.stat().st_size,
                source_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True, timeout=30).strip(),
                source_files={name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in SOURCE_FILES})
            exe = work / 'VGA-Aram-Helper.exe'
            shutil.copyfile(original, exe)
            if hashlib.sha256(exe.read_bytes()).hexdigest() != result['executable_sha256']:
                raise RuntimeError('Native executable copy changed bytes')
            env = native_environment(os.environ, work, args.app_scale)
            version_file = work / 'version.json'
            subprocess.run([str(exe), '--version-file', str(version_file)], env=env, cwd=work, timeout=90, check=True)
            version = json.loads(version_file.read_text(encoding='utf-8'))['applicationVersion']
            report_path = reports / (prefix + '-overlay.json')
            screenshot = report_path.with_suffix('.png')
            # These paths are this diagnostic's generated evidence, never app state.
            report_path.unlink(missing_ok=True)
            screenshot.unlink(missing_ok=True)
            with (reports / (prefix + '-process.log')).open('w', encoding='utf-8') as log:
                process = subprocess.Popen([str(exe), '--native-smoke-report', str(report_path)], env=env, cwd=work,
                                           stdout=log, stderr=subprocess.STDOUT)
                cleanup.callback(terminate_tree, process)
                try:
                    code = process.wait(timeout=180)
                finally:
                    logs = Path(env['VGA_STATE_DIR']) / 'logs'
                    if logs.is_dir():
                        for path in logs.glob('*.txt'):
                            shutil.copyfile(path, reports / (prefix + '-' + path.name))
                if code != 0:
                    result['native_failure'] = native_failure_summary(report_path)
                    raise RuntimeError(f'Native EXE exited with code {code}')
                native = json.loads(report_path.read_text(encoding='utf-8'))
                validate_report(native, version, float(args.app_scale), executable_sha256=result['executable_sha256'],
                    expected_fixture_sha256=result['source_files']['fixtures/auto-scene.png'])
                if not screenshot.is_file() or not screenshot.read_bytes().startswith(b'\x89PNG\r\n\x1a\n'):
                    raise RuntimeError('Native overlay PNG evidence is missing')
                result.update(applicationVersion=version, native_report=report_path.name,
                              native_screenshot=screenshot.name, process_exited=True,
                              native_report_sha256=hashlib.sha256(report_path.read_bytes()).hexdigest(),
                              native_screenshot_sha256=hashlib.sha256(screenshot.read_bytes()).hexdigest(),
                              overlay_duty_cycle=validate_overlay_duty(native,expected_fixture_sha256=result['source_files']['fixtures/auto-scene.png']), overlay_duty_scope=DUTY_SCOPE,
                              physical_geometry={key:native[key] for key in ('requested_app_scale','mock_qwindow_dpr',
                                  'overlay_qwindow_dpr','desktop_work_area_physical','mock_window_physical',
                                  'clientRect','overlay_window_physical','overlay_compact')})
        result['status'] = 'passed'
    except Exception as exc:
        result['error'] = repr(exc)
        raise
    finally:
        if result['status'] != 'passed':
            result['native_failure'] = native_failure_summary(report_path)
        (reports / (prefix + '-smoke.json')).write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()

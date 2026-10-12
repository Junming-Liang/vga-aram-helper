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
sys.path.insert(0, str(ROOT / 'tests'))
from windows_exe_smoke import isolated_windows_environment, smoke_workspace, terminate_tree


NATIVE_AUTOMATION_FIELDS = ('automatic_hero_passed', 'automatic_choices_passed', 'auto_without_manual_hero_selection', 'auto_unknown_clears_passed', 'auto_hero_change_clears_passed', 'auto_manual_fallback_passed', 'own_overlay_hidden_capture_passed')

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
    if type(result.get('overlay_compact')) is not bool:
        raise RuntimeError('Native compact layout state is missing')


def validate_report(result, version, app_scale=1):
    if result.get('status') != 'passed' or 'error' in result:
        raise RuntimeError('Native overlay self-test did not pass')
    if result.get('backend') != 'qtwidgets' or result.get('frozen') is not True:
        raise RuntimeError('Report is not a frozen native QtWidgets executable')
    if result.get('applicationVersion') != version:
        raise RuntimeError('Native executable version mismatch')
    for field in ('native_window', 'window_closed', 'capture_passed', 'ocr_passed', 'click_through_passed',
                  'source_tier_display_passed', 'source_tier_hero_specific', 'source_tier_missing_passed',
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
    if result.get('source_tier_rendered') != [f'虚构源评级（演示）：T{tier}' for tier in (1, 2, 3)]:
        raise RuntimeError('Native literal source-tier rendering evidence is incomplete')
    validate_physical_geometry(result, app_scale)


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
        result = {'report_present': True}
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
    result = {'status': 'failed', 'requested_app_scale': float(args.app_scale), 'executable_sha256': hashlib.sha256(original.read_bytes()).hexdigest(),
              'scope': 'Original synthetic mock window only; no real game, Vanguard or exclusive-fullscreen compatibility claim.'}
    try:
        with smoke_workspace() as work, ExitStack() as cleanup:
            exe = work / 'VGA-Aram-Helper.exe'
            shutil.copyfile(original, exe)
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
                validate_report(native, version, float(args.app_scale))
                if not screenshot.is_file() or not screenshot.read_bytes().startswith(b'\x89PNG\r\n\x1a\n'):
                    raise RuntimeError('Native overlay PNG evidence is missing')
                result.update(applicationVersion=version, native_report=report_path.name,
                              native_screenshot=screenshot.name, process_exited=True,
                              physical_geometry={key:native[key] for key in ('requested_app_scale','mock_qwindow_dpr',
                                  'overlay_qwindow_dpr','desktop_work_area_physical','mock_window_physical',
                                  'clientRect','overlay_window_physical','overlay_compact')})
        result['status'] = 'passed'
    except Exception as exc:
        result['error'] = repr(exc)
        raise
    finally:
        (reports / (prefix + '-smoke.json')).write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()

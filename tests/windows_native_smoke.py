"""Actual Windows QtWidgets EXE acceptance on an original mock game window."""
from __future__ import annotations
import argparse
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
from windows_exe_smoke import isolated_windows_environment, smoke_workspace, terminate_tree


NATIVE_AUTOMATION_FIELDS = ('automatic_hero_passed', 'automatic_choices_passed', 'auto_without_manual_hero_selection', 'auto_unknown_clears_passed', 'auto_hero_change_clears_passed', 'auto_manual_fallback_passed', 'own_overlay_hidden_capture_passed')

def validate_report(result, version):
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--exe', type=Path, required=True)
    parser.add_argument('--report-dir', type=Path, default=ROOT / 'reports')
    args = parser.parse_args()
    if os.name != 'nt':
        raise SystemExit('Requires the actual Windows executable and native Windows desktop')
    original = args.exe.resolve()
    reports = args.report_dir.resolve()
    reports.mkdir(parents=True, exist_ok=True)
    result = {'status': 'failed', 'executable_sha256': hashlib.sha256(original.read_bytes()).hexdigest(),
              'scope': 'Original synthetic mock window only; no real game, Vanguard or exclusive-fullscreen compatibility claim.'}
    try:
        with smoke_workspace() as work, ExitStack() as cleanup:
            exe = work / 'VGA-Aram-Helper.exe'
            shutil.copyfile(original, exe)
            env = isolated_windows_environment(os.environ, work)
            # Do not let an inherited test backend masquerade as a real window.
            env.pop('QT_QPA_PLATFORM', None)
            env.pop('QT_PLUGIN_PATH', None)
            version_file = work / 'version.json'
            subprocess.run([str(exe), '--version-file', str(version_file)], env=env, cwd=work, timeout=90, check=True)
            version = json.loads(version_file.read_text(encoding='utf-8'))['applicationVersion']
            report_path = reports / 'windows-native-overlay.json'
            screenshot = report_path.with_suffix('.png')
            with (reports / 'windows-native-process.log').open('w', encoding='utf-8') as log:
                process = subprocess.Popen([str(exe), '--native-smoke-report', str(report_path)], env=env, cwd=work,
                                           stdout=log, stderr=subprocess.STDOUT)
                cleanup.callback(terminate_tree, process)
                try:
                    code = process.wait(timeout=180)
                finally:
                    logs = Path(env['VGA_STATE_DIR']) / 'logs'
                    if logs.is_dir():
                        for path in logs.glob('*.txt'):
                            shutil.copyfile(path, reports / ('windows-native-' + path.name))
                if code != 0:
                    raise RuntimeError(f'Native EXE exited with code {code}')
                native = json.loads(report_path.read_text(encoding='utf-8'))
                validate_report(native, version)
                if not screenshot.is_file() or not screenshot.read_bytes().startswith(b'\x89PNG\r\n\x1a\n'):
                    raise RuntimeError('Native overlay PNG evidence is missing')
                result.update(applicationVersion=version, native_report=report_path.name,
                              native_screenshot=screenshot.name, process_exited=True)
        result['status'] = 'passed'
    except Exception as exc:
        result['error'] = repr(exc)
        raise
    finally:
        (reports / 'windows-native-smoke.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()

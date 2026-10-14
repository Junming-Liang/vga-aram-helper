"""Mandatory source/frozen HWND-only WGC acceptance on the actual Windows desktop.

Runs the same original owned-window diagnostic at three process-local Qt scales.
Unsupported WGC, fallback pixels, offscreen execution and missing evidence fail.
The frozen EXE runs from a clean directory with Python/compiler/package PATHs
removed, using only its own bundled helper. No display/system changes are made.
"""
from __future__ import annotations
import argparse
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
from app_version import __version__
from scripts.build_wgc_capture import validate_manifest, verify_built_helper
from wgc_smoke import CHECK_FIELDS, SCOPE
from windows_exe_smoke import isolated_windows_environment, smoke_workspace, terminate_tree

SCALES = (1, 1.5, 2)
SOURCE_FILES = ('native/wgc_capture.cpp', 'wgc_capture.py', 'screen_capture.py', 'wgc_smoke.py',
    'launcher.py', 'scripts/build_wgc_capture.py', 'scripts/build_windows.py',
    'packaging/VGA-Aram-Helper.spec', 'tests/windows_wgc_capture.py')
MAX_REPORT_BYTES = 128 * 1024


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate_report(value, *, frozen, scale, helper_build, version=__version__):
    if (not isinstance(value, dict) or value.get('status') != 'passed' or 'error' in value
            or type(value.get('schema_version')) is not int or value['schema_version'] != 1
            or value.get('frozen') is not frozen or value.get('applicationVersion') != version
            or value.get('qt_platform') != 'windows' or value.get('last_backend') != 'windows-graphics-capture'):
        raise RuntimeError('WGC diagnostic is not complete native Windows capture evidence')
    for field in CHECK_FIELDS:
        if value.get(field) is not True:
            raise RuntimeError('Mandatory native WGC check missing: ' + field)
    for field in ('requested_app_scale', 'measured_qt_scale'):
        number = value.get(field)
        if type(number) not in (int, float) or not math.isfinite(number) or abs(number-scale) > .01:
            raise RuntimeError('WGC diagnostic DPI evidence differs: ' + field)
    for field in ('mean_channel_error', 'routed_mean_channel_error'):
        number = value.get(field)
        if type(number) not in (int, float) or not math.isfinite(number) or not 0 <= number <= 2.0:
            raise RuntimeError('Native WGC pixel comparison is missing or failed')
    helper = value.get('helper', {})
    if (helper.get('sha256') != helper_build['sha256'] or helper.get('size') != helper_build['size']
            or helper.get('manifest') != helper_build):
        raise RuntimeError('WGC diagnostic ran different helper bytes or a different source build')
    validate_manifest(helper['manifest'])
    rect = value.get('client_rect')
    if (not isinstance(rect, dict) or set(rect) != {'x','y','width','height'}
            or any(type(number) is not int for number in rect.values())
            or (rect['width'], rect['height']) != (round(320*scale), round(240*scale))):
        raise RuntimeError('WGC diagnostic client physical geometry is invalid')
    expected_roi = [rect['width']//4, rect['height']//4, rect['width']//2, rect['height']//2]
    if value.get('roi') != expected_roi:
        raise RuntimeError('WGC diagnostic did not test the required bounded client ROI')
    if type(value.get('helper_process_count')) is not int or value['helper_process_count'] < 8:
        raise RuntimeError('WGC diagnostic helper lifecycle evidence is missing')
    negatives = value.get('negative_results', {})
    for field, status in (('timeout_watchdog_passed','timeout'), ('cancel_during_wait_passed','cancelled'),
                          ('cancel_before_launch_passed','cancelled'), ('protected_window_passed','protected')):
        row = negatives.get(field, {})
        elapsed = row.get('elapsed_ms')
        if (row.get('status') != status or type(elapsed) not in (int,float) or not math.isfinite(elapsed)
                or not 0 <= elapsed <= 5500):
            raise RuntimeError('WGC bounded negative evidence is invalid: ' + field)
    return value


def child_environment(environ, work, scale, *, frozen):
    env = isolated_windows_environment(environ, work) if frozen else dict(environ)
    for key in tuple(env):
        if key.upper().startswith(('QT_', 'PYSIDE_', '_PYI_')):
            env.pop(key)
    env.update(QT_SCALE_FACTOR=str(scale), QT_QPA_PLATFORM='windows',
               PYINSTALLER_RESET_ENVIRONMENT='1', VGA_STATE_DIR=str(work/'state'),
               LOCALAPPDATA=str(work/'local-appdata'))
    return env


def read_report(path):
    path = Path(path)
    if not path.is_file() or path.stat().st_size > MAX_REPORT_BYTES:
        raise RuntimeError('Mandatory bounded WGC report is missing')
    value = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value, dict):
        raise RuntimeError('WGC report must be an object')
    return value


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--exe', type=Path, help='Omit only for the separate source acceptance gate')
    parser.add_argument('--reports', '--report-dir', dest='reports', type=Path, default=ROOT/'reports')
    args = parser.parse_args(argv)
    if os.name != 'nt':
        raise SystemExit('Requires actual native Windows; Linux/offscreen cannot pass this acceptance')
    reports = args.reports.resolve(); reports.mkdir(parents=True, exist_ok=True)
    frozen = args.exe is not None
    prefix = 'windows-wgc-frozen' if frozen else 'windows-wgc-source'
    result = {'schema_version': 1, 'status': 'failed', 'frozen': frozen, 'scope': SCOPE,
              'scales': list(SCALES), 'runs': []}
    try:
        helper_build = verify_built_helper()
        source_commit = subprocess.check_output(['git','rev-parse','HEAD'], cwd=ROOT, text=True, timeout=30).strip()
        if helper_build.get('source_commit') != source_commit:
            raise RuntimeError('WGC helper was not built from this exact source commit')
        result.update(source_commit=source_commit, source_files={name:sha256(ROOT/name) for name in SOURCE_FILES},
                      helper_build=helper_build, applicationVersion=__version__)
        original = args.exe.resolve(strict=True) if frozen else None
        if original:
            result.update(executable_sha256=sha256(original), executable_size=original.stat().st_size)
        with smoke_workspace() as work:
            if frozen:
                executable = work/'VGA-Aram-Helper.exe'; shutil.copyfile(original, executable)
                require_same = sha256(executable) == result['executable_sha256']
                if not require_same:
                    raise RuntimeError('Isolated EXE bytes changed while copying')
            for scale in SCALES:
                report = reports / (prefix + '-scale' + str(round(scale*100)) + '.json')
                report.unlink(missing_ok=True)
                command = ([str(executable)] if frozen else [sys.executable, str(ROOT/'launcher.py')])
                command += ['--wgc-smoke-report', str(report)]
                process = subprocess.Popen(command, cwd=work, env=child_environment(os.environ, work, scale, frozen=frozen),
                                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                try:
                    returncode = process.wait(timeout=90)
                finally:
                    terminate_tree(process)
                detail = read_report(report)
                result['runs'].append({'app_scale':scale, 'report':report.name, 'detail':detail})
                if returncode:
                    raise RuntimeError('Actual WGC diagnostic failed: ' + str(detail.get('error', returncode))[:2000])
                validate_report(detail, frozen=frozen, scale=scale, helper_build=helper_build)
        # Passing evidence is recorded only after all owned processes and the
        # isolated copied executable/extraction directories have been cleaned up.
        result['status'] = 'passed'
        return 0
    except Exception as exc:
        result['error'] = str(exc)[:3000]
        raise
    finally:
        (reports/(prefix+'.json')).write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
        print(json.dumps(result, indent=2), flush=True)


if __name__ == '__main__':
    raise SystemExit(main())

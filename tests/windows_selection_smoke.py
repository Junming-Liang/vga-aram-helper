"""Real Windows client-to-new-game handoff using exclusively owned PNG windows.

Selection/carry and manual follow-off expiry use actual OS pixels and metadata.
Additional ambiguity/stale-handler cases are separate synthetic policy checks.
Neither is real game, Vanguard, or live-match compatibility evidence.
"""
from __future__ import annotations
import argparse
import ctypes
from ctypes import wintypes as W
import json
import math
import re
import subprocess
import os
from pathlib import Path
import shutil
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
from windows_exe_smoke import isolated_windows_environment, smoke_workspace
from windows_ota_smoke import Deadline, NativeJob, read_json, sha256, write_json
sys.path.insert(0, str(Path(__file__).resolve().parent))
from windows_session_fixture import CLASSES, TITLES, compile_fixture, fixture_argv, validate_ready, poll_owned_json
from windows_session_fixture import FOCUS_SINK_CLASS, FOCUS_SINK_TITLE, WM_FOCUS_OWNED_SINK, WM_RETURN_OWNED_CLIENT

CLIENT_PNG = ROOT / 'fixtures' / 'champselect-synthetic.png'
GAME_PNG = ROOT / 'fixtures' / 'auto-scene.png'
MAX_SECONDS = 240
JOB_CLEANUP_SECONDS = 15  # NativeJob.cleanup's existing bound, reserved inside MAX_SECONDS.
DIRECTORY_CLEANUP_SECONDS = 30  # smoke_workspace's existing post-job directory removal bound.
MAX_LOG_BYTES = 64 * 1024
MAX_TOTAL_LOG_BYTES = 256 * 1024
FIELDS = ('champion_select_own_row_passed', 'champion_select_ambiguity_passed',
          'champion_select_session_carry_passed', 'champion_select_stale_clear_passed',
          'champion_select_window_scope_passed', 'metadata_query_passed',
          'client_hero_reference_passed', 'client_hero_no_confirmation_passed',
          'client_hero_geometry_passed', 'client_hero_safety_passed',
          'manual_client_follow_off_passed')
SCALES = (1, 1.5, 2)
# These are the legacy scale100 mirrors checked by validate_aggregate. Keep
# optional evidence in its complete per-scale row instead of copying it again.
LEGACY_FIELDS = ('process_exited', 'owned_processes_exited', 'game_launched_after_selection_request',
    'native_report', 'native_report_sha256', 'fixture_source_sha256', 'completed_fields', 'client', 'game')
SAFETY_FIELDS = ('before_second_observation_hidden', 'hidden_during_recapture',
    'unknown_handler_hidden', 'swap_handler_hidden', 'stale_handler_hidden',
    'cleared_hero_hidden', 'foreground_loss_hidden', 'handoff_reference_removed')
SOURCE_FILES = ('badge_contract.py', 'source_combo_hints.py', 'hero_identity_continuity.py', 'monitor_preferences.py', 'card_title_proof.py', 'augment_card_geometry.py', 'card_badges.py', 'automatic_windows.py', 'native_ui.py', 'portrait_display.py', 'local_debug.py', 'native_state.py', 'screen_capture.py', 'overlay_geometry.py',
    'persistent_capture_adapter.py', 'wgc_session_capture.py', 'native/wgc_session_capture.cpp',
    'hero_strength.py', 'champion_select.py', 'selection_session.py', 'session_windows.py',
    'selection_smoke.py', 'synthetic_vision.py', 'launcher.py', 'tests/windows_selection_smoke.py',
    'owned_diagnostic_json.py', 'tests/windows_session_fixture.py', 'tests/SessionWindowFixture.cs',
    'fixtures/demo.json', 'fixtures/champselect-synthetic.png', 'fixtures/auto-scene.png')
EXPECTED_REFERENCE = {'hero': '星火术士（演示）', 'championId': '9001', 'sourceTier': 'T5',
    'sourceTierLabel': '虚构英雄评级（演示）', 'sourceLabel': '虚构演示 · 不能用于对局',
    'sourceUrl': None, 'sourceDataDate': '2026-01-02', 'sourceVersion': '0.1',
    'gamePatch': '0.2', 'wikiDataVersion': 'synthetic-selection-v1', 'isDemo': True}
EXPECTED_TEXT = {'hero': '星火术士（演示）', 'tier': '英雄整体强度：T5',
    'heading': '当前分配 · 仍可交换 · HUD未复核', 'footer': '虚构演示 · 非 Riot 评级/批准',
    'metadata': '英雄评级快照 2026-01-02 · 英雄资料 0.1 · 游戏资料 0.2 · 数据包 synthetic-selection-v1'}
SCOPE = ('Owned original synthetic windows only. Primary client-to-new-game carry uses actual '
         'Windows pixels and real executable metadata; manual follow-off also tests real TTL expiry. '
         'Additional ambiguity/stale-handler cases are separate synthetic policy checks. '
         'No real game, Vanguard, live-match accuracy or compatibility claim.')


def child_environment(environ, work, scale=1, *, frozen=True):
    env = isolated_windows_environment(environ, work) if frozen else {key.upper(): value for key, value in environ.items()}
    if type(scale) not in (int, float) or scale not in SCALES:
        raise ValueError("Unsupported selection app scale")
    for key in tuple(env):
        if key.startswith(('_PYI_', 'QT_', 'PYSIDE_', 'VGA_')):
            env.pop(key)
    temporary = Path(work) / 'temporary'
    temporary.mkdir()
    env.update(TEMP=str(temporary), TMP=str(temporary), VGA_STATE_DIR=str(Path(work) / 'state'),
               PYINSTALLER_RESET_ENVIRONMENT='1', QT_SCALE_FACTOR=str(scale))
    return env


def fixture_dimensions(work_width, work_height):
    """Both original scenes fit a 1024x768 runner without desktop settings edits."""
    if type(work_width) is not int or type(work_height) is not int:
        raise ValueError('Work-area dimensions must be integers')
    game_width = min(964, work_width - 60)
    game_height = min(602, work_height - 60)
    if game_height < 600 or game_width / game_height < 1.55:
        raise ValueError('Interactive desktop cannot fit the supported owned game fixture')
    return {'client': (game_width, game_height), 'game': (game_width, game_height)}


def declare_desktop(native):
    u = native.u
    declarations = {
        'GetClassNameW': ([W.HWND, W.LPWSTR, ctypes.c_int], ctypes.c_int),
        'GetClientRect': ([W.HWND, ctypes.POINTER(W.RECT)], W.BOOL),
        'GetForegroundWindow': ([], W.HWND),
        'SetForegroundWindow': ([W.HWND], W.BOOL),
        'ShowWindow': ([W.HWND, ctypes.c_int], W.BOOL),
        'SetWindowPos': ([W.HWND,W.HWND,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,W.UINT],W.BOOL),
        'IsWindow': ([W.HWND], W.BOOL),
        'SendMessageTimeoutW': ([W.HWND,W.UINT,W.WPARAM,W.LPARAM,W.UINT,W.UINT,ctypes.POINTER(ctypes.c_size_t)],ctypes.c_ssize_t),
        'ClientToScreen': ([W.HWND,ctypes.POINTER(W.POINT)],W.BOOL),
        'SystemParametersInfoW': ([W.UINT, W.UINT, ctypes.c_void_p, W.UINT], W.BOOL),
        'SetThreadDpiAwarenessContext': ([ctypes.c_void_p], ctypes.c_void_p),
        'GetThreadDpiAwarenessContext': ([], ctypes.c_void_p),
        'AreDpiAwarenessContextsEqual': ([ctypes.c_void_p, ctypes.c_void_p], W.BOOL),
    }
    for name, (args, result) in declarations.items():
        function = getattr(u, name)
        function.argtypes, function.restype = args, result
    # This observer thread only; restore in finally. No system display setting is modified.
    old_context = u.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
    if not old_context or not u.AreDpiAwarenessContextsEqual(u.GetThreadDpiAwarenessContext(), ctypes.c_void_p(-4)):
        raise RuntimeError('Owned-fixture observer thread could not establish PMv2 DPI awareness')
    return old_context


def assert_owned_window(native, process, executable, role, window, dimensions):
    if native.poll(process) is not None:
        raise AssertionError('Owned fixture exited before its requested close')
    windows = native.windows(executable, title=TITLES[role])
    if windows != [window] or window['pid'] != process['pid']:
        raise AssertionError('Fixture window/image/PID is not the exact owned process')
    cls = ctypes.create_unicode_buffer(256)
    if not native.u.GetClassNameW(window['hwnd'], cls, len(cls)) or cls.value != CLASSES[role]:
        raise AssertionError('Owned fixture Win32 class is not the expected class')
    rect = W.RECT()
    if not native.u.GetClientRect(window['hwnd'], ctypes.byref(rect)):
        raise AssertionError('Owned fixture client bounds are unavailable')
    if (rect.right - rect.left, rect.bottom - rect.top) != dimensions:
        raise AssertionError('Owned fixture client dimensions changed')


def foreground_owned(native, process, executable, role, window, dimensions):
    assert_owned_window(native, process, executable, role, window, dimensions)
    if int(native.u.GetForegroundWindow() or 0) != window['hwnd']:
        native.u.ShowWindow(window['hwnd'], 5)
        native.u.SetForegroundWindow(window['hwnd'])
    return int(native.u.GetForegroundWindow() or 0) == window['hwnd']


def owned_process_created(native,process):
    """Independent creation-time observation through the existing Job handle."""
    query=native.k.GetProcessTimes
    query.argtypes=[W.HANDLE,*([ctypes.POINTER(W.FILETIME)]*4)];query.restype=W.BOOL
    created,exited,kernel,user=(W.FILETIME() for _ in range(4))
    require(query(process['handle'],ctypes.byref(created),ctypes.byref(exited),ctypes.byref(kernel),ctypes.byref(user)),
            'Owned process creation time unavailable')
    return (int(created.dwHighDateTime)<<32)|int(created.dwLowDateTime)


def client_physical_rect(native,window):
    rect=W.RECT();point=W.POINT(0,0)
    require(native.u.GetClientRect(window['hwnd'],ctypes.byref(rect))
            and native.u.ClientToScreen(window['hwnd'],ctypes.byref(point)), 'Owned client geometry query failed')
    return {'x':point.x,'y':point.y,'width':rect.right-rect.left,'height':rect.bottom-rect.top}


def drive_focus_fixture(native,process,executable,window,dimensions,phase,result):
    """Only the exact Job-owned foreground fixture switches its own two HWNDs."""
    assert_owned_window(native,process,executable,'client',window,dimensions)
    evidence=result.setdefault('focus_fixture',{})
    before=client_physical_rect(native,window)
    if phase=='testing-client-foreground-loss':
        if evidence.get('sink'):return
        require(foreground_owned(native,process,executable,'client',window,dimensions),
                'Owned client must be foreground before its focus-sink request')
        response=ctypes.c_size_t()
        sent=bool(native.u.SendMessageTimeoutW(window['hwnd'],WM_FOCUS_OWNED_SINK,0,0,0x2,1000,ctypes.byref(response)))
        evidence.update(request_message=WM_FOCUS_OWNED_SINK,request_sent=sent,response_hwnd=response.value,
                        client_rect_before=before)
        require(sent and response.value>0,'Owned focus-sink request failed or timed out')
        sinks=native.windows(executable,title=FOCUS_SINK_TITLE)
        expected={'hwnd':response.value,'pid':process['pid']}
        require(sinks==[expected],'Focus sink is not the exact Job-owned fixture window')
        name=ctypes.create_unicode_buffer(256)
        require(native.u.GetClassNameW(response.value,name,len(name)) and name.value==FOCUS_SINK_CLASS,
                'Owned focus-sink class differs')
        require(int(native.u.GetForegroundWindow()or 0)==response.value,'Owned focus sink did not receive foreground')
        require(client_physical_rect(native,window)==before and native.u.IsWindowVisible(window['hwnd']),
                'Focus sink changed or hid original client geometry')
        evidence.update(sink=expected,sink_class=name.value,sink_title=FOCUS_SINK_TITLE,
                        client_rect_during=before,client_visible_during=True,foreground_sink_hwnd=response.value)
    elif phase=='requesting-client-focus-return':
        if evidence.get('sink_destroyed'):return
        sink=evidence.get('sink');require(type(sink)is dict,'Missing owned focus-sink identity')
        require(native.windows(executable,title=FOCUS_SINK_TITLE)==[sink]
                and int(native.u.GetForegroundWindow()or 0)==sink['hwnd'], 'Owned focus sink changed before return')
        response=ctypes.c_size_t()
        sent=bool(native.u.SendMessageTimeoutW(window['hwnd'],WM_RETURN_OWNED_CLIENT,0,0,0x2,1000,ctypes.byref(response)))
        evidence.update(return_message=WM_RETURN_OWNED_CLIENT,return_sent=sent,return_response_hwnd=response.value)
        require(sent and response.value==1,'Owned client return request failed or timed out')
        require(not native.u.IsWindow(sink['hwnd']) and int(native.u.GetForegroundWindow()or 0)==window['hwnd'],
                'Owned sink did not close and restore original client foreground')
        require(client_physical_rect(native,window)==evidence['client_rect_before']
                and native.u.IsWindowVisible(window['hwnd']),'Original client geometry changed on return')
        evidence.update(sink_destroyed=True,client_foreground_returned=True,client_rect_returned=before)


def wait_fixture(native, process, executable, role, ready_path, dimensions, budget):
    def ready():
        if native.poll(process) is not None:
            raise AssertionError('Owned fixture failed before readiness')
        value = poll_owned_json(ready_path, read_json)
        if value is None:
            return None
        window = validate_ready(value, role=role, pid=process['pid'], width=dimensions[0], height=dimensions[1])
        assert_owned_window(native, process, executable, role, window, dimensions)
        return window
    return Deadline.wait(ready, budget.until(20), 'Owned fixture readiness timed out')


def report_when(path, phase=None, *, terminal=False):
    try:
        value = poll_owned_json(path, read_json)
    except json.JSONDecodeError:
        return None  # The app may still be replacing/writing its bounded diagnostic report.
    if value is None:
        return None
    if not isinstance(value, dict):
        raise AssertionError('Selection handoff report is not a JSON object')
    if value.get('status') == 'failed' or 'error' in value:
        raise AssertionError('Selection handoff failed: ' + str(value.get('error', 'unknown error'))[:1800])
    if terminal:
        return value if value.get('status') == 'passed' else None
    return value if value.get('phase') == phase else None


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def rectangle(value, label):
    require(type(value) is dict and set(value) == {'x', 'y', 'width', 'height'}
            and all(type(number) is int and -(2**31) <= number < 2**31 for number in value.values())
            and value['width'] > 0 and value['height'] > 0
            and value['width'] * value['height'] <= 16_000_000, 'Invalid rectangle: ' + label)
    return value


def contains(outer, inner):
    return (inner['x'] >= outer['x'] and inner['y'] >= outer['y']
            and inner['x'] + inner['width'] <= outer['x'] + outer['width']
            and inner['y'] + inner['height'] <= outer['y'] + outer['height'])


def validate_focus_transition(value,client_hwnd,client_pid,client_rect,overlay_hwnd):
    require(type(value)is dict,'Actual owned focus-transition evidence missing')
    require(type(value.get('sink_hwnd'))is int and value['sink_hwnd']>0 and value['sink_hwnd']!=client_hwnd
            and type(value.get('sink_pid'))is int and value['sink_pid']==client_pid
            and value.get('sink_class')==FOCUS_SINK_CLASS and value.get('sink_title')==FOCUS_SINK_TITLE
            and type(value.get('foreground_sink_hwnd'))is int and value['foreground_sink_hwnd']==value['sink_hwnd'],
            'Focus loss must be observed on the exact same-process diagnostic sink')
    require(type(value.get('overlay_hwnd'))is int and value['overlay_hwnd']==overlay_hwnd,
            'Focus transition changed hero overlay identity')
    for field in ('overlay_visible_before','overlay_native_visible_before','client_visible_during',
                  'overlay_hidden_after','sink_destroyed','client_foreground_returned'):
        require(value.get(field)is True,'Actual focus transition missing: '+field)
    for field in ('client_rect_before','client_rect_during','client_rect_returned'):
        require(rectangle(value.get(field),field)==client_rect,'Focus transition changed original client geometry')
    return value


def validate_follow_off(value,client_hwnd,client_pid,game_created):
    require(type(value)is dict,'Manual follow-off evidence missing')
    for field in ('target_hwnd','game_hwnd','game_pid','game_created','started_after',
                  'follow_on_started_after','foreground_game_hwnd','observation_count'):
        require(type(value.get(field))is int and value[field]>0,'Manual follow-off integer missing: '+field)
    require(value['target_hwnd']==client_hwnd
            and value['game_hwnd']!=client_hwnd and value['game_pid']!=client_pid
            and value['foreground_game_hwnd']==value['game_hwnd'], 'Manual follow-off native identities differ')
    require(value.get('follow_enabled')is False and value.get('game_bound')is False,
            'Manual follow-off unexpectedly authorized following')
    require(value.get('expiry_hidden')is True,'Manual follow-off expiry display was not withdrawn')
    require(value.get('assigned')=='9001' and value['observation_count']>=2
            and value.get('expired_stage')=='client-expired','Manual follow-off selection/expiry state differs')
    fresh,expired=value.get('fresh_no_handoff_age_seconds'),value.get('expired_observation_age_seconds')
    require(type(fresh)in(int,float) and math.isfinite(fresh) and 0<=fresh<=4
            and type(expired)in(int,float) and math.isfinite(expired) and 4<expired<170,
            'Manual follow-off must test fresh no-handoff then real TTL expiry')
    require(type(game_created)is int and game_created>value['follow_on_started_after']>value['game_created']>value['started_after'],
            'Negative and final games must be created after their respective Start scopes')
    return value


def validate_report(value, version, *, frozen=True, scale=1, executable_sha256=None):
    require(type(value) is dict and value.get('status') == 'passed' and 'error' not in value,
            'Selection handoff did not pass')
    require(type(value.get('schemaVersion')) is int and value['schemaVersion'] == 2,
            'Selection native schema differs')
    for name, expected in (('backend', 'qtwidgets'), ('qt_platform', 'windows'), ('applicationVersion', version)):
        require(value.get(name) == expected, 'Selection handoff identity mismatch: ' + name)
    require(value.get('frozen') is frozen, 'Selection source/frozen identity differs')
    if frozen:
        require(type(value.get('executable_sha256')) is str
                and re.fullmatch(r'[0-9a-f]{64}', value['executable_sha256'])
                and (executable_sha256 is None or value['executable_sha256'] == executable_sha256),
                'Selection native executable bytes differ')
    else:
        require('executable_sha256' not in value, 'Source native report claims frozen EXE bytes')
    for name in FIELDS:
        require(value.get(name) is True, 'Selection handoff evidence missing: ' + name)
    requested = value.get('requested_app_scale')
    require(type(requested) in (int, float) and math.isfinite(requested) and requested == scale,
            'Selection requested app scale differs')
    require(value.get('window_closed') is True and value.get('phase') == 'complete',
            'Selection native window did not close')
    require(value.get('recognizedHero') == EXPECTED_REFERENCE['hero']
            and value.get('assignedHero') == EXPECTED_REFERENCE['hero']
            and value.get('recognized') == ['星火共鸣', '晶盾回路', '风步微光']
            and value.get('provenance') == 'client-provisional',
            'Selection handoff hero, augment order or provenance differs')
    badges=value.get('renderedBadgeProvenance')
    require(type(badges) is list and len(badges)==3, 'Three visible badge provenance rows missing')
    for index,(badge,name,tier) in enumerate(zip(badges,value['recognized'],('T1','T2','T3')),1):
        require(type(badge) is dict and type(badge.get('slot')) is int and badge.get('slot')==index and badge.get('visible') is True
                and badge.get('text')=='HUD未复核' and badge.get('paintedText') in ('HUD未复核','HUD待核')
                and badge.get('accessible')==f'选项 {index} · {name} · {tier} · HUD未复核 · 来自本局选人 · HUD未复核'
                and badge.get('tooltip')=='来自本局选人 · HUD未复核\n',
                'Visible badge provisional identity differs')
    for key in ('clientHwnd', 'clientPid', 'gameHwnd', 'gamePid', 'clientGeneration'):
        require(type(value.get(key)) is int and value[key] > 0, 'Selection identity missing: ' + key)
    require(value['clientHwnd'] != value['gameHwnd'] and value['clientPid'] != value['gamePid'],
            'Client and game identities must differ')
    validate_follow_off(value.get('manual_client_follow_off'),value['clientHwnd'],value['clientPid'],value.get('gameCreated'))
    detail = value.get('client_hero_reference')
    require(type(detail) is dict, 'Hero reference measurements missing')
    require(detail.get('reference') == EXPECTED_REFERENCE
            and type(detail['reference'].get('isDemo')) is bool,
            'Hero reference canonical tier/source/date/patch binding differs')
    require(detail.get('assigned') == '9001' and detail.get('stage') == 'assigned'
            and detail.get('state_hero') == EXPECTED_REFERENCE['hero']
            and type(detail.get('observation_count')) is int and detail['observation_count'] >= 2,
            'Hero reference requires two exact current client observations')
    require(detail.get('confirmed') is False and type(detail.get('offered')) is list and detail['offered'] == []
            and type(detail.get('augment_card_count')) is int and detail['augment_card_count'] == 0,
            'Hero-only reference fabricated augment confirmation')
    for key in ('visible', 'native_visible', 'foreground_preserved'):
        require(detail.get(key) is True, 'Actual visible hero reference missing: ' + key)
    require(type(detail.get('overlay_hwnd')) is int and detail['overlay_hwnd'] > 0
            and detail['overlay_hwnd'] not in (value['clientHwnd'], value['gameHwnd'])
            and type(detail.get('click_through_hit_hwnd')) is int
            and detail['click_through_hit_hwnd'] == value['clientHwnd'], 'Hero reference click-through identity differs')
    style = detail.get('window_style')
    require(type(style) is int and 0 <= style <= 2**32-1
            and all(style & flag for flag in (0x80000, 0x08000000, 0x20, 0x8, 0x80)),
            'Hero reference native overlay style differs')
    dpr = detail.get('qt_dpr')
    require(type(dpr) in (int, float) and math.isfinite(dpr) and abs(dpr-scale) <= .01,
            'Hero reference measured Qt scale differs')
    client = rectangle(detail.get('client_rect'), 'client')
    overlay = rectangle(detail.get('overlay_rect'), 'overlay')
    require((client['width'], client['height']) == (964, 602)
            and contains(client, overlay) and overlay['height'] <= client['height']//2,
            'Hero reference escaped original client/half-height bounds')
    logical = detail.get('logical_size')
    require(type(logical) is dict and set(logical) == {'width', 'height'}
            and all(type(number) is int and number > 0 for number in logical.values()),
            'Hero reference logical size missing')
    require(abs(overlay['width']-logical['width']*dpr) <= 2
            and abs(overlay['height']-logical['height']*dpr) <= 2, 'Hero native/logical bounds disagree')
    labels = detail.get('labels')
    require(type(labels) is dict and set(labels) == set(EXPECTED_TEXT), 'Hero visible label set differs')
    for role, expected in EXPECTED_TEXT.items():
        row = labels[role]
        require(type(row) is dict and row.get('text') == expected and row.get('visible') is True,
                'Hero displayed text missing or changed: ' + role)
        rect = rectangle(row.get('logical_rect'), role)
        require(contains(dict(x=0, y=0, **logical), rect), 'Hero label escaped overlay: ' + role)
        minimum, height = row.get('minimum_width'), row.get('required_height_at_width')
        require(type(minimum) is int and 0 <= minimum <= rect['width']+1
                and type(height) is int and -1 <= height <= rect['height']+1,
                'Hero label is clipped or lacks text measurements: ' + role)
        expected_accessible = ('当前分配英雄：' + EXPECTED_REFERENCE['hero'] if role == 'hero'
                               else '虚构英雄评级（演示）：T5' if role == 'tier' else '')
        require(row.get('accessible_name') == expected_accessible, 'Hero accessible text differs: ' + role)
    rects = [row['logical_rect'] for row in labels.values()]
    for index, left in enumerate(rects):
        for right in rects[index+1:]:
            require(not (left['x'] < right['x']+right['width'] and right['x'] < left['x']+left['width']
                         and left['y'] < right['y']+right['height'] and right['y'] < left['y']+left['height']),
                    'Visible hero labels overlap')
    require(type(value.get('foreground_recovery_start_count')) is int and value['foreground_recovery_start_count'] >= 2
            and type(value.get('foreground_recovery_observations')) is int and value['foreground_recovery_observations'] >= 2,
            'Two measured post-foreground client observations missing')
    safety = value.get('client_hero_safety')
    require(type(safety) is dict and all(safety.get(key) is True for key in SAFETY_FIELDS),
            'Hero reference revocation/recovery evidence missing')
    validate_focus_transition(value.get('foreground_transition'),value['clientHwnd'],value['clientPid'],client,detail['overlay_hwnd'])
    return value


def native_report_name(frozen, scale):
    prefix = 'windows-selection-handoff' if frozen else 'windows-selection-source-handoff'
    return prefix + ('' if scale == 1 else '-scale' + str(round(scale*100))) + '.json'


def validate_aggregate(value, version, *, frozen, source_commit=None, executable_sha256=None, executable_size=None):
    require(type(value) is dict and value.get('status') == 'passed' and 'error' not in value
            and type(value.get('schemaVersion')) is int and value['schemaVersion'] == 2
            and value.get('frozen') is frozen and value.get('applicationVersion') == version,
            'Selection aggregate identity/status differs')
    require(type(value.get('source_commit')) is str and re.fullmatch(r'[0-9a-f]{40}', value['source_commit'])
            and (source_commit is None or value['source_commit'] == source_commit), 'Selection source commit differs')
    files = value.get('source_files')
    require(type(files) is dict and set(files) == set(SOURCE_FILES)
            and all(type(digest) is str and re.fullmatch(r'[0-9a-f]{64}', digest) for digest in files.values()),
            'Selection source byte identities missing')
    if frozen:
        require(type(value.get('executable_sha256')) is str and re.fullmatch(r'[0-9a-f]{64}', value['executable_sha256'])
                and (executable_sha256 is None or value['executable_sha256'] == executable_sha256),
                'Selection tested different EXE bytes')
        require(type(value.get('executable_size')) is int and value['executable_size'] > 0
                and (executable_size is None or value['executable_size'] == executable_size),
                'Selection tested different EXE size')
    else:
        require('executable_sha256' not in value and 'executable_size' not in value,
                'Source selection evidence cannot claim frozen EXE bytes')
    scales = value.get('scales')
    require(type(scales) is list and len(scales) == 3 and all(type(s) in (int, float) for s in scales)
            and scales == list(SCALES), 'Selection aggregate scale set differs')
    runs = value.get('runs')
    require(type(runs) is list and len(runs) == 3, 'Selection aggregate requires all three runs')
    for row, scale in zip(runs, SCALES):
        require(type(row) is dict and type(row.get('app_scale')) in (int, float) and row['app_scale'] == scale
                and row.get('native_report') == native_report_name(frozen, scale), 'Selection scale/report identity differs')
        require(type(row.get('native_report_sha256')) is str
                and re.fullmatch(r'[0-9a-f]{64}', row['native_report_sha256']),
                'Selection native report byte hash missing')
        validate_report(row.get('detail'), version, frozen=frozen, scale=scale,
                        executable_sha256=value.get('executable_sha256'))
        require(row.get('applicationVersion') == version
                and row.get('fixture_source_sha256') == files['tests/SessionWindowFixture.cs'],
                'Selection run version/fixture source differs')
        if frozen:
            require(row.get('executable_sha256') == value['executable_sha256'], 'Selection run EXE bytes differ')
        for key in ('process_exited', 'owned_processes_exited', 'game_launched_after_selection_request'):
            require(row.get(key) is True, 'Selection owned lifecycle missing: ' + key)
        require(row.get('completed_fields') == list(FIELDS), 'Selection completed field list differs')
        for role in ('client', 'game'):
            observed = row.get(role)
            require(type(observed) is dict and observed.get('class_name') == CLASSES[role]
                    and type(observed.get('client_size')) is list and observed['client_size'] == [964, 602]
                    and all(type(number) is int for number in observed['client_size'])
                    and type(observed.get('hwnd')) is int and observed['hwnd'] == row['detail'][role+'Hwnd']
                    and type(observed.get('pid')) is int and observed['pid'] == row['detail'][role+'Pid'],
                    'Selection owned process/window evidence differs: ' + role)
        negative=row.get('follow_off_fixture');detail=row['detail']['manual_client_follow_off']
        require(type(negative)is dict and negative.get('class_name')==CLASSES['game']
                and negative.get('client_size')==[964,602] and all(type(size)is int for size in negative['client_size'])
                and all(type(negative.get(key))is int and negative[key]==detail[field]
                    for key,field in (('hwnd','game_hwnd'),('pid','game_pid'),('created','game_created'))),
                'Outer owned follow-off game differs from native observation')
        require(negative.get('launched_after_selection_request')is True and negative.get('process_exited')is True
                and negative.get('closed_before_follow_on')is True,'Follow-off game lifetime/cleanup evidence missing')
        observed=row.get('focus_fixture');transition=row['detail']['foreground_transition']
        require(type(observed)is dict and observed.get('sink')=={'hwnd':transition['sink_hwnd'],'pid':transition['sink_pid']}
                and all(type(observed['sink'].get(k))is int for k in ('hwnd','pid')),
                'Outer Job-owned focus sink differs from native observation')
        for key,expected in (('request_message',WM_FOCUS_OWNED_SINK),('response_hwnd',transition['sink_hwnd']),
                             ('return_message',WM_RETURN_OWNED_CLIENT),('return_response_hwnd',1)):
            require(type(observed.get(key))is int and observed[key]==expected,'Owned focus command evidence differs: '+key)
        for key in ('request_sent','return_sent','client_visible_during','sink_destroyed','client_foreground_returned'):
            require(observed.get(key)is True,'Owned focus command did not complete: '+key)
        for key in ('sink_class','sink_title','foreground_sink_hwnd'):
            require(type(observed.get(key))is type(transition[key]) and observed[key]==transition[key],
                    'Outer focus identity differs: '+key)
        for key in ('client_rect_before','client_rect_during','client_rect_returned'):
            require(rectangle(observed.get(key),key)==transition[key],'Outer focus geometry differs: '+key)
    for key in ('process_exited', 'owned_processes_exited', 'game_launched_after_selection_request'):
        require(value.get(key) is True, 'Legacy selection lifecycle missing: ' + key)
    for key in ('process_exited', 'owned_processes_exited', 'game_launched_after_selection_request',
                'native_report', 'native_report_sha256', 'fixture_source_sha256', 'completed_fields', 'client', 'game'):
        require(json.dumps(value.get(key), sort_keys=True) == json.dumps(runs[0].get(key), sort_keys=True), 'Legacy selection evidence differs from scale100: ' + key)
    return value


def collect_logs(work, reports, prefix='windows-selection-'):
    sources = list(sorted((Path(work) / 'state' / 'logs').glob('*.txt')))
    sources += list(sorted(Path(work).glob('*.error.txt')))
    if len(sources) > 12:
        raise AssertionError('Selection log count exceeds its evidence bound')
    total, names = 0, []
    for path in sources:
        size = path.stat().st_size
        total += size
        if size > MAX_LOG_BYTES or total > MAX_TOTAL_LOG_BYTES:
            raise AssertionError('Selection logs exceed their small-evidence bound')
        target = Path(reports) / (prefix + path.name)
        if target.name in names:
            raise AssertionError('Selection log names collide')
        shutil.copyfile(path, target)
        names.append(target.name)
    return names


def preserve_native_report(path,reports,result,*,completed=False):
    """Retain the exact owned diagnostic JSON on success OR failure for CI logs."""
    path=Path(path)
    result['native_report_present']=path.is_file()
    if not result['native_report_present']:
        require(not completed, 'Completed selection native report is missing')
        return
    if path.stat().st_size>MAX_LOG_BYTES:
        raise AssertionError('Selection handoff report exceeds 64 KiB')
    payload=path.read_bytes()
    if len(payload)>MAX_LOG_BYTES:
        raise AssertionError('Selection handoff report exceeds 64 KiB')
    value=json.loads(payload)
    if type(value) is not dict:
        raise AssertionError('Selection diagnostic report is not an object')
    target=Path(reports)/path.name
    target.write_bytes(payload)
    result['native_report_snapshot']=value
    result['native_report_snapshot_sha256']=sha256(target)
    if completed:
        # Only remove an already-observed duplicate after successful cleanup.
        # Canonical JSON is type-sensitive (unlike dict equality for True/1 or
        # 1/1.0); the hash also binds the original bytes, including whitespace.
        # Store the snapshot first so every mismatch keeps its full evidence.
        detail=result.get('detail')
        require(type(detail) is dict and detail.get('status')=='passed' and 'error' not in detail
                and result.get('process_exited') is True and result.get('owned_processes_exited') is True,
                'Completed selection run lacks successful native/lifecycle evidence')
        require(result.get('native_report')==path.name
                and result.get('native_report_sha256')==result['native_report_snapshot_sha256']
                and json.dumps(detail,sort_keys=True,allow_nan=False)==json.dumps(value,sort_keys=True,allow_nan=False),
                'Selection native report changed after validation')
        del result['native_report_snapshot']


def execute_run(original, reports, result, *, frozen=True, scale=1):
    # Reserve existing NativeJob failure-cleanup time inside the 240-second bound.
    budget = Deadline(MAX_SECONDS - JOB_CLEANUP_SECONDS)
    with smoke_workspace() as work:
        work = work.resolve()  # Canonicalize Windows short-name TEMP aliases before identity checks.
        target = work / 'VGA-Aram-Helper.exe' if frozen else Path(sys.executable).resolve()
        app_args = [] if frozen else [str(ROOT / 'launcher.py')]
        if frozen:
            shutil.copyfile(original, target)
            if sha256(target) != result['executable_sha256']:
                raise AssertionError('Target executable copy changed bytes')
        env = child_environment(os.environ, work, scale, frozen=frozen)
        artifact_prefix = ('windows-selection-' if frozen else 'windows-selection-source-') + 'scale' + str(round(scale*100)) + '-'
        fixture = compile_fixture(work / 'fixture-root', timeout=max(.1, min(45, budget.end - time.monotonic())))
        result['fixture_source_sha256'] = fixture['source_sha256']
        (reports / (artifact_prefix + 'compiler.log')).write_text(fixture['compiler_log'], encoding='utf-8')
        native = NativeJob()
        old_context = None
        try:
            old_context = declare_desktop(native)
            work_area = W.RECT()
            if not native.u.SystemParametersInfoW(0x0030, 0, ctypes.byref(work_area), 0):  # SPI_GETWORKAREA only
                raise RuntimeError('Interactive work-area bounds are unavailable')
            sizes = fixture_dimensions(work_area.right - work_area.left, work_area.bottom - work_area.top)
            x, y = max(0, work_area.left) + 20, max(0, work_area.top) + 20
            version_file = work / 'version.json'
            version_process = native.spawn(target, app_args + ['--version-file', str(version_file)], env, work)
            if native.wait_exit(version_process, budget.until(60)) != 0:
                raise AssertionError('Application version command failed')
            version_info = read_json(version_file)
            version = version_info.get('applicationVersion')
            if not isinstance(version, str) or not version or version_info.get('frozen') is not frozen:
                raise AssertionError('Application source/frozen version evidence is invalid')
            result['applicationVersion'] = version
            client_ready = work / 'client-ready.json'
            argv = fixture_argv(fixture['client_exe'], 'client', CLIENT_PNG, client_ready,
                                x=x, y=y, width=sizes['client'][0], height=sizes['client'][1])
            client = native.spawn(argv[0], argv[1:], env, work)
            client_window = wait_fixture(native, client, fixture['client_exe'], 'client', client_ready, sizes['client'], budget)
            input_path = work / 'selection-input.json'
            write_json(input_path, {'schemaVersion': 1, 'scope': 'owned-synthetic-only', 'client': client_window})
            handoff_path = work / native_report_name(frozen, scale)
            if handoff_path.exists():
                raise AssertionError('Selection handoff report must be fresh for this exact run')
            app = native.spawn(target, app_args + ['--selection-smoke-input', str(input_path),
                                        '--selection-smoke-report', str(handoff_path)], env, work)
            negative_game=None;negative_window=None

            def awaiting_game():
                nonlocal negative_game,negative_window
                if native.poll(app) is not None:
                    raise AssertionError('Application exited before its real game-window request')
                value = report_when(handoff_path, 'await-game-window')
                if value:
                    require(result.get('follow_off_fixture',{}).get('closed_before_follow_on')is True,
                            'Final game requested before negative-game cleanup')
                    return value
                current = poll_owned_json(handoff_path, read_json) or {}
                phase=current.get('phase')
                if phase=='await-follow-off-game' and negative_game is None:
                    require(foreground_owned(native,client,fixture['client_exe'],'client',client_window,sizes['client']),
                            'Owned client must be foreground before negative-game launch')
                    ready=work/'follow-off-game-ready.json'
                    argv=fixture_argv(fixture['game_exe'],'game',GAME_PNG,ready,x=x,y=y,
                        width=sizes['game'][0],height=sizes['game'][1],no_activate=True)
                    negative_game=native.spawn(argv[0],argv[1:],env,work)
                    negative_window=wait_fixture(native,negative_game,fixture['game_exe'],'game',ready,sizes['game'],budget)
                    # NOACTIVATE alone does not guarantee an unobscured client.
                    # Lower only this exact Job-owned game until the requested
                    # foreground test; do not change any external window.
                    assert_owned_window(native,negative_game,fixture['game_exe'],'game',negative_window,sizes['game'])
                    require(native.u.SetWindowPos(negative_window['hwnd'],W.HWND(1),0,0,0,0,0x0001|0x0002|0x0010),
                            'Could not place owned negative game behind the client')
                    require(int(native.u.GetForegroundWindow()or 0)==client_window['hwnd'],
                            'Nonactivating negative-game launch changed client foreground')
                    result['follow_off_fixture']=dict(negative_window,class_name=CLASSES['game'],
                        client_size=list(sizes['game']),created=owned_process_created(native,negative_game),
                        launched_after_selection_request=True,process_exited=False,closed_before_follow_on=False)
                if phase=='testing-follow-off-game':
                    require(negative_game is not None,'Follow-off game test lacks its owned process')
                    foreground_owned(native,negative_game,fixture['game_exe'],'game',negative_window,sizes['game'])
                elif phase=='closing-follow-off-game':
                    require(negative_game is not None,'Follow-off cleanup lacks its owned process')
                    if not result['follow_off_fixture']['process_exited']:
                        assert_owned_window(native,negative_game,fixture['game_exe'],'game',negative_window,sizes['game'])
                        native.close_window(negative_window)
                        require(native.wait_exit(negative_game,budget.until(10))==0,'Follow-off game did not exit cleanly')
                        result['follow_off_fixture'].update(process_exited=True,closed_before_follow_on=True)
                    foreground_owned(native,client,fixture['client_exe'],'client',client_window,sizes['client'])
                elif phase in ('testing-client-foreground-loss','requesting-client-focus-return'):
                    drive_focus_fixture(native,client,fixture['client_exe'],client_window,sizes['client'],current['phase'],result)
                else:
                    foreground_owned(native, client, fixture['client_exe'], 'client', client_window, sizes['client'])
                return None

            Deadline.wait(awaiting_game, budget.until(135), 'Application did not confirm selection before game launch')
            result['game_launched_after_selection_request'] = True
            result['client'] = dict(client_window, class_name=CLASSES['client'], client_size=list(sizes['client']))
            # The real game fixture process does not exist until the app's explicit session has started.
            game_ready = work / 'game-ready.json'
            argv = fixture_argv(fixture['game_exe'], 'game', GAME_PNG, game_ready,
                                x=x, y=y, width=sizes['game'][0], height=sizes['game'][1])
            game = native.spawn(argv[0], argv[1:], env, work)
            game_window = wait_fixture(native, game, fixture['game_exe'], 'game', game_ready, sizes['game'], budget)
            result['game'] = dict(game_window, class_name=CLASSES['game'], client_size=list(sizes['game']))
            Deadline.wait(lambda: foreground_owned(native, game, fixture['game_exe'], 'game', game_window, sizes['game']),
                          budget.until(10), 'Owned new game fixture could not become foreground')

            def completed():
                value = report_when(handoff_path, terminal=True)
                if value:
                    return value
                if native.poll(app) is not None:
                    raise AssertionError('Application exited without a passed handoff report')
                return None

            handoff = Deadline.wait(completed, budget.until(90), 'Real selection handoff did not finish before its deadline')
            validate_report(handoff, version, frozen=frozen, scale=scale)
            result['detail'] = handoff
            result['native_report_sha256'] = sha256(handoff_path)
            if native.wait_exit(app, budget.until(20)) != 0:
                raise AssertionError('Selection diagnostic executable did not exit with code zero')
            result['process_exited'] = True
            for role, process, window in (('game', game, game_window), ('client', client, client_window)):
                assert_owned_window(native, process, fixture[role + '_exe'], role, window, sizes[role])
                native.close_window(window)
            for process in (game, client):
                if native.wait_exit(process, budget.until(10)) != 0:
                    raise AssertionError('Owned fixture did not exit cleanly after WM_CLOSE')
            Deadline.wait(lambda: not native.pids(), budget.until(10), 'Private selection job still contains owned processes')
            result.update(owned_processes_exited=True, native_report=handoff_path.name,
                          completed_fields=list(FIELDS), cleanup='Both fixtures exited 0 after WM_CLOSE; private job empty')
        finally:
            try:
                native.cleanup()  # A cleanup error propagates; status cannot become passed.
            finally:
                if old_context:
                    if not native.u.SetThreadDpiAwarenessContext(old_context):
                        raise RuntimeError('Observer thread DPI context restoration failed')
                # Read only the current run's unique temporary report; preserve it as small evidence.
                current_handoff = work / native_report_name(frozen, scale)
                preserve_native_report(current_handoff,reports,result,completed=sys.exc_info()[0] is None)
                result['logs'] = collect_logs(work, reports, artifact_prefix)


def execute(original, reports, result):
    for scale in SCALES:
        row = {'app_scale': scale, 'process_exited': False, 'owned_processes_exited': False}
        if original:
            row['executable_sha256'] = result['executable_sha256']
        result['runs'].append(row)
        execute_run(original, reports, row, frozen=result['frozen'], scale=scale)
        if scale == 1:
            for key in (*LEGACY_FIELDS, 'applicationVersion'):
                result[key] = row[key]
        require(row['applicationVersion'] == result['applicationVersion'], 'Selection scale versions differ')


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--exe', type=Path, help='Omit only for separate actual Windows source acceptance')
    parser.add_argument('--report-dir', '--reports', type=Path, default=ROOT / 'reports')
    args = parser.parse_args(argv)
    if os.name != 'nt':
        raise SystemExit('Selection smoke requires actual native Windows and an interactive desktop')
    frozen = args.exe is not None
    original = args.exe.resolve(strict=True) if frozen else None
    if original and original.suffix.lower() != '.exe':
        raise SystemExit('Selection smoke requires a Windows .exe')
    reports = args.report_dir.resolve(); reports.mkdir(parents=True, exist_ok=True)
    result = {'schemaVersion': 2, 'status': 'failed', 'scope': SCOPE, 'frozen': frozen,
              'scales': list(SCALES), 'runs': [], 'process_exited': False, 'owned_processes_exited': False}
    try:
        sys.path.insert(0, str(ROOT))
        from app_version import __version__
        result.update(applicationVersion=__version__, source_commit=subprocess.check_output(
            ['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True, timeout=30).strip(),
            source_files={name: sha256(ROOT/name) for name in SOURCE_FILES})
        if frozen:
            result['executable_sha256'] = sha256(original)
            result['executable_size'] = original.stat().st_size
        execute(original, reports, result)
        result['status'] = 'passed'
        validate_aggregate(result, __version__, frozen=frozen)
    except Exception as error:
        result.update(status='failed', error=repr(error)[:2000])
        raise
    finally:
        write_json(reports / ('windows-selection-smoke.json' if frozen else 'windows-selection-source.json'), result)
        # Full bounded JSON stays in rendered CI logs for independently readable
        # label/geometry/source evidence even where artifact download is denied.
        print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()

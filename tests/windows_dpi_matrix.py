"""Source-level real-Windows/Qt regression harness; owned windows only.

This deliberately does not start ControlWindow, capture pixels, manipulate input,
change OS display settings, or test the packaged executable. See README.md.
"""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes as W
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
import traceback

SCALES = ('1', '1.25', '1.5', '2', '2.5')
CASES = (
    ('wide', 964, 602, 0, 'visible'),
    ('repeat', 964, 602, 0, 'visible'),
    ('moved', 964, 602, 5, 'visible'),
    ('medium', 860, 540, 0, 'visible'),
    ('narrow', 700, 420, 0, 'fit_or_hide'),
    ('too_small', 320, 180, 0, 'hidden'),
    ('recover', 964, 602, 0, 'visible'),
)
EXPECTED_CARD_NAMES = [f'原创候选{i}' for i in (1, 2, 3)]
EXPECTED_TIERS = [f'T{i}' for i in (1, 2, 3)]
EXPECTED_ACCESSIBLE_TIERS = [f'选项 {i} · 原创候选{i} · T{i} · 源评级' for i in (1,2,3)]
EXPECTED_SOURCE = ['源评级']*3
SCOPE = {
    'execution': 'Python source Overlay on actual Windows Qt platform',
    'scaling': 'Controlled per-process QT_SCALE_FACTOR simulation on unchanged OS desktop',
    'target': 'Original owned hit-testable nontext Win32 STATIC target in the same process',
    'pixels_captured': False,
    'input_simulated': False,
    'os_display_settings_changed': False,
    'frozen_executable_tested': False,
    'real_os_125_150_200_250_percent_monitors_tested': False,
    'real_game_or_vanguard_tested': False,
    'full_visible_4k_tested': False,
    'visual_font_quality_tested': False,
}


def rectangle(x, y, width, height):
    values = (x, y, width, height)
    if any(not isinstance(v, int) or isinstance(v, bool) for v in values):
        raise ValueError('Rectangle coordinates must be integers')
    if width <= 0 or height <= 0:
        raise ValueError('Rectangle must have positive area')
    return dict(x=x, y=y, width=width, height=height)


def contains(outer, inner, tolerance=0):
    return (inner['x'] >= outer['x'] - tolerance
            and inner['y'] >= outer['y'] - tolerance
            and inner['x'] + inner['width'] <= outer['x'] + outer['width'] + tolerance
            and inner['y'] + inner['height'] <= outer['y'] + outer['height'] + tolerance)


def expectation_for(case, scale):
    if case[0] == 'medium' and float(scale) > 2:
        return 'fit_or_hide'
    return case[4]


def translation_tolerance_px(delta, dpr):
    """A capped position-only allowance for a nonintegral Qt logical move.

    Integral logical displacements remain exact. This narrow allowance is at
    most ONE physical pixel, never a general layout or containment tolerance.
    """
    if not isinstance(dpr, (int, float)) or isinstance(dpr, bool) or not math.isfinite(dpr) or dpr <= 0:
        raise ValueError('Translation requires a finite positive effective DPR')
    logical_delta = delta / dpr
    return 0 if math.isclose(logical_delta, round(logical_delta), rel_tol=0, abs_tol=1e-9) else 1


def translation_matches(before, after):
    dpr = before.get('qt_window_dpr')
    if (not isinstance(dpr, (int, float)) or isinstance(dpr, bool)
            or not math.isfinite(dpr) or dpr <= 0 or after.get('qt_window_dpr') != dpr):
        return False
    a, b = before['overlay_window_physical'], after['overlay_window_physical']
    ta, tb = before['target_client_physical'], after['target_client_physical']
    if any(a[k] != b[k] or ta[k] != tb[k] for k in ('width', 'height')):
        return False
    for axis in ('x', 'y'):
        measured_target_delta = tb[axis] - ta[axis]
        # The fixture itself must have made the requested physical translation.
        if measured_target_delta != 5:
            return False
        if abs((b[axis] - a[axis]) - measured_target_delta) > translation_tolerance_px(measured_target_delta, dpr):
            return False
    return True


def case_issues(row):
    """Fail closed: hidden required cases, clipped children and stale UI fail."""
    issues = []
    visible = row['visible']
    error = row.get('error')
    expectation = row['expectation']
    if row.get('native_badge_regions_verified') is True and row.get('target_hit_test_baseline') is not True:
        issues.append('target_hit_test_baseline_missing')
    if expectation == 'visible' and (not visible or error):
        issues.append('required_visible_layout_missing')
    if expectation == 'hidden' and visible:
        issues.append('insufficient_space_left_overlay_visible')
    if expectation == 'hidden' and not error:
        issues.append('insufficient_space_not_explicitly_rejected')
    if not visible and not error:
        issues.append('silent_missing_overlay')
    if error and visible:
        issues.append('error_left_overlay_visible')
    if visible:
        if not contains(row['target_client_physical'], row['overlay_window_physical']):
            issues.append('native_overlay_outside_owned_client')
        if row['overlay_window_physical']['height']*2>row['target_client_physical']['height']:
            issues.append('native_overlay_exceeds_half_client_height')
        if not row['geometry_mapping_matches']:
            issues.append('qt_logical_to_native_physical_mismatch')
        if row['layout_issues']:
            issues.append('qt_child_or_text_layout_clipped')
        if row.get('native_badge_regions_verified') is not True or row.get('gap_hit_test_passed') is not True:
            issues.append('independent_native_badge_regions_not_verified')
        if row.get('badge_above_cards_verified') is not True:
            issues.append('badge_card_anchors_not_verified')
        if row['visible_card_count'] != 3 or row['visible_tier_count'] != 3:
            issues.append('three_card_content_missing')
        if row.get('visible_card_names') != EXPECTED_CARD_NAMES or row.get('visible_tier_text') != EXPECTED_TIERS:
            issues.append('original_card_order_or_tiers_changed')
        if row.get('visible_source_attribution') != EXPECTED_SOURCE or row.get('tier_accessible_names') != EXPECTED_ACCESSIBLE_TIERS:
            issues.append('source_attribution_or_accessible_tiers_changed')
    elif error and row.get('error_type') not in ('CaptureUnavailable', 'ValueError'):
        issues.append('unexpected_exception_instead_of_safe_rejection')
    return issues


def validate_matrix(report, expect):
    """Portable strict evidence gate; a historical regression is never a pass."""
    errors = []
    if report.get('scope') != SCOPE or report.get('os_name') != 'nt':
        errors.append('not_actual_windows_source_scope')
    children = report.get('children', [])
    if [c.get('qt_scale_factor') for c in children] != list(SCALES):
        errors.append('scale_matrix_incomplete')
    for child in children:
        prefix = child.get('qt_scale_factor', '?') + ':'
        if child.get('status') != 'completed' or child.get('process_exit_code') != 0:
            errors.append(prefix + 'child_incomplete')
            continue
        if child.get('qt_platform') != 'windows' or child.get('frozen') is not False:
            errors.append(prefix + 'not_real_windows_source_qt')
        if expect == 'candidate' and (child.get('badge_lifecycle_verified') is not True or child.get('badge_reference_transition_verified') is not True):
            errors.append(prefix + 'badge_lifecycle_not_verified')
        if not child.get('process_pmv2') or not child.get('owned_windows_destroyed'):
            errors.append(prefix + 'awareness_or_cleanup_not_verified')
        cases = child.get('cases', [])
        if [r.get('id') for r in cases] != [c[0] for c in CASES]:
            errors.append(prefix + 'cases_incomplete')
        for row in cases:
            fixture = next((c for c in CASES if c[0] == row.get('id')), None)
            if fixture is None or row.get('expectation') != expectation_for(fixture, child['qt_scale_factor']):
                errors.append(prefix + str(row.get('id')) + ':case_expectation_changed')
            if fixture is not None and (row['target_client_physical']['width'], row['target_client_physical']['height']) != fixture[1:3]:
                errors.append(prefix + row['id'] + ':physical_fixture_size_changed')
            if row.get('error_type') not in (None, 'CaptureUnavailable', 'ValueError'):
                errors.append(prefix + row['id'] + ':unexpected_overlay_exception')
            if row.get('target_native_visible') is not True:
                errors.append(prefix + row['id'] + ':owned_target_not_native_visible')
            if not row.get('target_fully_onscreen') or not row.get('same_process_owned_windows'):
                errors.append(prefix + row['id'] + ':ownership_or_visibility_invalid')
            if not row.get('target_pmv2') or not row.get('overlay_pmv2'):
                errors.append(prefix + row['id'] + ':window_awareness_invalid')
            dpr = row.get('qt_window_dpr')
            dpi = row.get('target_dpi')
            if not isinstance(dpr, (int, float)) or not math.isfinite(dpr) or not dpr > 0:
                errors.append(prefix + row['id'] + ':invalid_qt_dpr')
            elif not isinstance(dpi, int) or dpi <= 0 or abs(dpr - dpi / 96 * float(child['qt_scale_factor'])) > .03:
                errors.append(prefix + row['id'] + ':scale_did_not_take_effect')
            if expect == 'candidate':
                errors.extend(prefix + row['id'] + ':' + issue for issue in case_issues(row))
        if expect == 'candidate' and len(cases) >= 2:
            if cases[0].get('overlay_window_physical') != cases[1].get('overlay_window_physical'):
                errors.append(prefix + 'repeat_placement_drifted')
            if len(cases) >= 3 and all(r.get('visible') for r in cases[:3]):
                if not translation_matches(cases[0], cases[2]):
                    errors.append(prefix + 'pure_translation_changed_overlay_size_or_offset')
    if expect == 'historical':
        # Must observe a high-scale layout/geometry regression in a required-fit
        # case. The known tiny-window stale-UI failure alone is insufficient.
        measured_geometry_failures = {'native_overlay_outside_owned_client',
            'qt_logical_to_native_physical_mismatch', 'qt_child_or_text_layout_clipped'}
        regression = any(float(c.get('qt_scale_factor', 0)) >= 1.5
            and any(r.get('expectation') == 'visible' and r.get('visible')
                and r.get('target_qt_scale_mismatch') is True
                and measured_geometry_failures.intersection(case_issues(r))
                for r in c.get('cases', [])) for c in children)
        if not regression:
            errors.append('historical_high_scale_regression_not_observed')
    return errors


def clean_child_environment(environ, scale):
    # Normalize Windows environment key casing. Do not inherit a fake Qt backend
    # or an extra font/screen scale that could disguise the controlled matrix.
    env = {key.upper(): value for key, value in environ.items()}
    for key in ('QT_QPA_PLATFORM', 'QT_QPA_PLATFORM_PLUGIN_PATH', 'QT_PLUGIN_PATH',
                'QT_SCREEN_SCALE_FACTORS', 'QT_AUTO_SCREEN_SCALE_FACTOR',
                'QT_ENABLE_HIGHDPI_SCALING', 'QT_FONT_DPI', 'QT_USE_PHYSICAL_DPI',
                'QT_SCALE_FACTOR_ROUNDING_POLICY', 'PYTHONPATH', 'PYTHONHOME'):
        env.pop(key, None)
    env.update(QT_SCALE_FACTOR=scale, PYTHONUTF8='1', PYTHONDONTWRITEBYTECODE='1')
    return env


def source_metadata(implementation, support):
    files = [implementation] + [support / p for p in ('screen_capture.py', 'native_state.py', 'overlay_geometry.py', 'portrait_display.py', 'local_debug.py', 'card_badges.py', 'augment_card_geometry.py', 'badge_contract.py', 'native_smoke.py')]
    return [dict(path=str(p), sha256=hashlib.sha256(p.read_bytes()).hexdigest())
            for p in files if p.is_file()]


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


class OwnedWindows:
    """Real Win32 geometry. Every mutable handle belongs to this process."""
    def __init__(self):
        self.u = ctypes.WinDLL('user32', use_last_error=True)
        signatures = (
            ('SetProcessDpiAwarenessContext', [W.HANDLE], W.BOOL),
            ('GetThreadDpiAwarenessContext', [], W.HANDLE),
            ('GetWindowDpiAwarenessContext', [W.HWND], W.HANDLE),
            ('AreDpiAwarenessContextsEqual', [W.HANDLE, W.HANDLE], W.BOOL),
            ('GetDpiForWindow', [W.HWND], W.UINT),
            ('CreateWindowExW', [W.DWORD, W.LPCWSTR, W.LPCWSTR, W.DWORD, ctypes.c_int,
                ctypes.c_int, ctypes.c_int, ctypes.c_int, W.HWND, W.HMENU, W.HINSTANCE, W.LPVOID], W.HWND),
            ('DestroyWindow', [W.HWND], W.BOOL), ('IsWindow', [W.HWND], W.BOOL),
            ('IsWindowVisible', [W.HWND], W.BOOL),
            ('GetWindowThreadProcessId', [W.HWND, ctypes.POINTER(W.DWORD)], W.DWORD),
            ('GetWindowRect', [W.HWND, ctypes.POINTER(W.RECT)], W.BOOL),
            ('GetClientRect', [W.HWND, ctypes.POINTER(W.RECT)], W.BOOL),
            ('ClientToScreen', [W.HWND, ctypes.POINTER(W.POINT)], W.BOOL),
            ('SetWindowPos', [W.HWND, W.HWND, ctypes.c_int, ctypes.c_int,
                ctypes.c_int, ctypes.c_int, W.UINT], W.BOOL),
            ('SystemParametersInfoW', [W.UINT, W.UINT, W.LPVOID, W.UINT], W.BOOL),
            ('GetSystemMetrics', [ctypes.c_int], ctypes.c_int),
        )
        for name, args, result in signatures:
            fn = getattr(self.u, name)
            fn.argtypes, fn.restype = args, result
        self.pmv2 = W.HANDLE(-4)
        ctypes.set_last_error(0)
        self.process_awareness_set = bool(self.u.SetProcessDpiAwarenessContext(self.pmv2))
        self.process_awareness_set_error = ctypes.get_last_error()
        if not self.u.AreDpiAwarenessContextsEqual(self.u.GetThreadDpiAwarenessContext(), self.pmv2):
            raise RuntimeError('Could not establish PMv2 before QApplication')
        area = W.RECT()
        if not self.u.SystemParametersInfoW(0x0030, 0, ctypes.byref(area), 0):
            raise ctypes.WinError(ctypes.get_last_error())
        self.work_area = self.rect_value(area)
        self.desktop = rectangle(0, 0, self.u.GetSystemMetrics(0), self.u.GetSystemMetrics(1))
        self.target = None

    @staticmethod
    def rect_value(r):
        return rectangle(int(r.left), int(r.top), int(r.right-r.left), int(r.bottom-r.top))

    def pid(self, hwnd):
        result = W.DWORD()
        if not self.u.GetWindowThreadProcessId(hwnd, ctypes.byref(result)):
            raise ctypes.WinError(ctypes.get_last_error())
        return result.value

    def hit_diagnostic(self, hit, overlay, point, delegate):
        """Bounded own-window metadata only; no titles or foreign-process details."""
        hwnd=int(overlay.winId());target=int(self.target)
        self.u.GetAncestor.argtypes=[W.HWND,W.UINT];self.u.GetAncestor.restype=W.HWND
        self.u.GetWindow.argtypes=[W.HWND,W.UINT];self.u.GetWindow.restype=W.HWND
        self.u.GetClassNameW.argtypes=[W.HWND,W.LPWSTR,ctypes.c_int];self.u.GetClassNameW.restype=ctypes.c_int
        self.u.SendMessageW.argtypes=[W.HWND,W.UINT,W.WPARAM,W.LPARAM];self.u.SendMessageW.restype=ctypes.c_ssize_t
        def role(value):return 'overlay' if value==hwnd else 'target' if value==target else 'other' if value else 'none'
        def owned(value):
            if not value or self.pid(value)!=os.getpid():return {'owned':False}
            name=ctypes.create_unicode_buffer(128);self.u.GetClassNameW(value,name,128)
            packed=(point.x&0xffff)|((point.y&0xffff)<<16)
            return dict(owned=True,role=role(value),class_name=name.value,rect=self.window_rect(value),
                        style=int(delegate.get_long(value,-16)),extended_style=int(delegate.get_long(value,-20)),
                        visible=bool(self.u.IsWindowVisible(value)),hit_test=int(self.u.SendMessageW(value,0x84,0,packed)))
        chain=[];value=hwnd
        for _ in range(8):
            value=int(self.u.GetWindow(value,3) or 0)
            if not value:break
            chain.append(role(value))
        return dict(point=[point.x,point.y],hit_role=role(hit),hit_root_role=role(int(self.u.GetAncestor(hit,2) or 0)),
                    hit=owned(hit),overlay=owned(hwnd),target=owned(target),above_overlay=chain,
                    qt_window_flags=int(overlay.windowFlags()),badge_regions=[list(r) for r in overlay._badge_regions])

    def require_owned(self, hwnd):
        if self.pid(hwnd) != os.getpid():
            raise RuntimeError('Refusing access to a window outside this harness process')

    def window_rect(self, hwnd):
        self.require_owned(hwnd)
        r = W.RECT()
        if not self.u.GetWindowRect(hwnd, ctypes.byref(r)):
            raise ctypes.WinError(ctypes.get_last_error())
        return self.rect_value(r)

    def client_rect(self, hwnd):
        self.require_owned(hwnd)
        r, p = W.RECT(), W.POINT(0, 0)
        if not self.u.GetClientRect(hwnd, ctypes.byref(r)) or not self.u.ClientToScreen(hwnd, ctypes.byref(p)):
            raise ctypes.WinError(ctypes.get_last_error())
        return rectangle(int(p.x), int(p.y), int(r.right-r.left), int(r.bottom-r.top))

    def awareness(self, hwnd):
        self.require_owned(hwnd)
        context = self.u.GetWindowDpiAwarenessContext(hwnd)
        return dict(context_value=context, pmv2=bool(self.u.AreDpiAwarenessContextsEqual(context, self.pmv2)),
                    dpi=int(self.u.GetDpiForWindow(hwnd)))

    def position_target(self, width, height, offset):
        area = self.work_area
        wanted = rectangle(area['x'] + 10 + offset, area['y'] + 10 + offset, width, height)
        if not contains(area, wanted) or not contains(self.desktop, wanted):
            raise RuntimeError('Desktop work area is too small for the required fully-onscreen owned fixture')
        if self.target is None:
            # Borderless native STATIC fixture, shown without activating it.
            self.target = self.u.CreateWindowExW(0x08000080, 'STATIC', 'VGA original DPI fixture',
                0x80000104, wanted['x'], wanted['y'], width, height, None, None, None, None)
            if not self.target:
                raise ctypes.WinError(ctypes.get_last_error())
        self.require_owned(self.target)
        if not self.u.SetWindowPos(self.target, W.HWND(-1), wanted['x'], wanted['y'], width, height, 0x0010 | 0x0040):
            raise ctypes.WinError(ctypes.get_last_error())
        return self.client_rect(self.target)

    def close(self):
        if self.target and self.u.IsWindow(self.target):
            self.require_owned(self.target)
            if not self.u.DestroyWindow(self.target):
                raise ctypes.WinError(ctypes.get_last_error())
        return not self.target or not self.u.IsWindow(self.target)


def pump(app, QtCore, duration=.12):
    deadline = time.monotonic() + duration
    while time.monotonic() < deadline:
        app.processEvents()
        QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
        time.sleep(.005)


def inspect_layout(overlay, QtCore, QtWidgets):
    root_bounds = rectangle(0, 0, overlay.width(), overlay.height())
    issues, widgets = [], []
    for index, widget in enumerate(overlay.findChildren(QtWidgets.QWidget)):
        if not widget.isVisibleTo(overlay):
            continue
        pos = widget.mapTo(overlay, QtCore.QPoint(0, 0))
        bounds = dict(x=pos.x(), y=pos.y(), width=widget.width(), height=widget.height())
        key = f'{index}:{type(widget).__name__}:{widget.objectName()}'
        entry = dict(id=key, logical_rect=bounds,
            minimum_size_hint=dict(width=widget.minimumSizeHint().width(), height=widget.minimumSizeHint().height()))
        if bounds['width'] <= 0 or bounds['height'] <= 0 or not contains(root_bounds, bounds):
            issues.append(key + ':outside_overlay')
        parent = widget.parentWidget()
        if parent is not None:
            local = dict(x=widget.x(), y=widget.y(), width=widget.width(), height=widget.height())
            parent_rect = dict(x=0, y=0, width=parent.width(), height=parent.height())
            if not contains(parent_rect, local):
                issues.append(key + ':outside_parent')
        if isinstance(widget, QtWidgets.QLabel):
            need = widget.heightForWidth(widget.width())
            entry.update(text=widget.text(), required_height_at_width=need)
            if need > widget.height() + 1:
                issues.append(key + ':label_height_below_height_for_width')
            if widget.minimumSizeHint().width() > widget.width() + 1:
                issues.append(key + ':label_width_below_minimum')
        widgets.append(entry)
    return widgets, issues


def run_child(args):
    result = dict(status='failed', scope=SCOPE, qt_scale_factor=os.environ.get('QT_SCALE_FACTOR'),
                  frozen=bool(getattr(sys, 'frozen', False)), cases=[])
    native = app = overlay = None
    try:
        if os.name != 'nt':
            raise RuntimeError('Actual Windows is required; offscreen is not native evidence')
        native = OwnedWindows()  # PMv2 before importing or constructing Qt.
        from PySide6 import QtCore, QtWidgets
        app = QtWidgets.QApplication([])
        result.update(qt_platform=app.platformName(), qt_version=QtCore.qVersion(),
            process_pmv2=bool(native.u.AreDpiAwarenessContextsEqual(native.u.GetThreadDpiAwarenessContext(), native.pmv2)),
            process_awareness_set=native.process_awareness_set,
            process_awareness_set_error=native.process_awareness_set_error,
            desktop_physical=native.desktop, work_area_physical=native.work_area)
        if app.platformName() != 'windows' or result['frozen']:
            raise RuntimeError('Harness requires source Python with native Windows Qt platform')
        sys.path.insert(0, str(args.support_root))
        sys.path.insert(0, str(args.implementation_file.parent))
        spec = importlib.util.spec_from_file_location('vga_selected_overlay_implementation', args.implementation_file)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        from screen_capture import Win32Capture, WindowInfo, ClientRect
        delegate = Win32Capture()
        class OwnedCapture:
            # Only geometry/style methods are exposed; no capture, enumeration,
            # hotkey, game-window discovery, input, OCR, or network actions.
            u = native.u
            def configure_overlay(self, hwnd, click_through, *, opaque=False):
                native.require_owned(hwnd)
                return delegate.configure_overlay(hwnd, click_through, opaque=opaque)
        overlay = module.Overlay(OwnedCapture())
        overlay.set_cards('原创测试英雄', [dict(slot=i, name=f'原创候选{i}', sourceTier=f'T{i}',
            sourceTierLabel='原创测试评级', description='原创尺寸测试说明，验证三项文字是否完整显示。' * 3,
            notes=['原创条件提醒，仅用于布局检查。']) for i in (1, 2, 3)],
            source_date='2026-10-12', source_version='合成布局测试')
        from badge_fixture import seed_badge_geometry
        from card_badges import native_region
        from badge_contract import WIDTH, HEIGHT, GAP, choose_width, align_physical_regions, top_gap
        if args.expect == 'candidate':seed_badge_geometry(overlay)
        for case in CASES:
            ident, width, height, offset, _ = case
            expectation = expectation_for(case, result['qt_scale_factor'])
            overlay.hide('layout');pump(app,QtCore)
            target_rect = native.position_target(width, height, offset)
            native.u.WindowFromPoint.argtypes=[W.POINT];native.u.WindowFromPoint.restype=W.HWND
            baseline_point=W.POINT(target_rect['x']+width//2,target_rect['y']+height//2)
            baseline_hit=int(native.u.WindowFromPoint(baseline_point) or 0)
            assert baseline_hit==int(native.target), ('Owned target baseline hit differs',baseline_hit,int(native.target),target_rect)
            target = WindowInfo(int(native.target), os.getpid(), 'VGA original DPI fixture', 'Static')
            error = None
            try:
                overlay.show_at(ClientRect(**target_rect), target)
            except Exception as exc:
                error = exc
            pump(app, QtCore)
            hwnd = int(overlay.winId())
            own_rect = native.window_rect(hwnd)
            target_awareness, overlay_awareness = native.awareness(native.target), native.awareness(hwnd)
            dpr = float(overlay.windowHandle().devicePixelRatio())
            visible = bool(overlay.isVisible() and native.u.IsWindowVisible(hwnd))
            widgets, layout_issues = inspect_layout(overlay, QtCore, QtWidgets) if visible else ([], [])
            region_verified = gap_verified = anchors_verified = False
            if visible and args.expect == 'candidate':
                native_region(hwnd,overlay._badge_regions,verify_only=True)
                assert len(overlay._badge_regions)==3
                region_verified=True
                anchors_verified=True
                logical_width=choose_width([(x+cw/2)*width for x,y,cw,ch in overlay._badge_anchors.rects],dpr)
                for slot,(bx,by,bw,bh) in enumerate(overlay._badge_regions):
                    x,y,cw,ch=overlay._badge_anchors.rects[slot]
                    assert (bw,bh)==(math.ceil(logical_width*dpr),math.ceil(HEIGHT*dpr))
                    gap=target_rect['y']+y*height-(own_rect['y']+by+bh)
                    assert top_gap(dpr)<=gap<top_gap(dpr)+dpr+1.01
                bw,bh=math.ceil(logical_width*dpr),math.ceil(HEIGHT*dpr)
                physical=[(round(target_rect['x']+(x+cw/2)*width-bw/2),math.floor(target_rect['y']+y*height-top_gap(dpr)-bh),bw,bh) for x,y,cw,ch in overlay._badge_anchors.rects]
                expected_bounds,expected_regions=align_physical_regions(physical,dpr,logical_width)
                assert tuple(own_rect[k] for k in ('x','y','width','height'))==expected_bounds, ('Actual/expected badge bounds',own_rect,expected_bounds,dpr,overlay.size().toTuple())
                assert tuple(overlay._badge_regions)==expected_regions
                native.u.WindowFromPoint.argtypes=[W.POINT];native.u.WindowFromPoint.restype=W.HWND
                # Diagnostic-only direct backend override: production badges
                # intentionally force passthrough even if their UI flag is off.
                try:
                    delegate.configure_overlay(hwnd,False,opaque=True)
                    assert not (int(delegate.get_long(hwnd,-20)) & 0x20), 'Diagnostic overlay still clickthrough'
                    from native_smoke import owned_badge_hit_test_probe
                    bx,by,bw,bh=overlay._badge_regions[0]
                    probe_point=W.POINT(own_rect['x']+bx+bw//2,own_rect['y']+by+bh//2)
                    result['native_hit_before_probe']=native.hit_diagnostic(int(native.u.WindowFromPoint(probe_point) or 0),overlay,probe_point,delegate)
                    with owned_badge_hit_test_probe(overlay,probe_point):
                        for bx,by,bw,bh in overlay._badge_regions:
                            point=W.POINT(own_rect['x']+bx+bw//2,own_rect['y']+by+bh//2)
                            hit=int(native.u.WindowFromPoint(point) or 0)
                            result['last_native_hit_diagnostic']=native.hit_diagnostic(hit,overlay,point,delegate)
                            assert hit==hwnd, ('Badge center hit differs',hit,hwnd,point.x,point.y)
                        for first,second in zip(overlay._badge_regions,overlay._badge_regions[1:]):
                            px=own_rect['x']+(first[0]+first[2]+second[0])//2
                            py=own_rect['y']+first[1]+first[3]//2
                            hit=int(native.u.WindowFromPoint(W.POINT(px,py)) or 0)
                            assert hit==int(native.target), ('Badge gap hit differs',hit,int(native.target),px,py,own_rect)
                    gap_verified=True
                finally:
                    overlay.configure()
                    assert int(overlay.winId())==hwnd and int(delegate.get_long(hwnd,-20))&0x20, 'Normal badge passthrough not restored'
            row = dict(id=ident, expectation=expectation,target_hit_test_baseline=baseline_hit==int(native.target), target_client_physical=target_rect,
                target_window_physical=native.window_rect(native.target), overlay_window_physical=own_rect,
                target_native_visible=bool(native.u.IsWindowVisible(native.target)),
                target_fully_onscreen=contains(native.work_area, target_rect)
                    and contains(native.work_area, native.window_rect(native.target)),
                same_process_owned_windows=native.pid(native.target) == native.pid(hwnd) == os.getpid(),
                target_dpi=target_awareness['dpi'], overlay_dpi=overlay_awareness['dpi'],
                target_dpi_awareness_context=target_awareness['context_value'],
                overlay_dpi_awareness_context=overlay_awareness['context_value'],
                target_pmv2=target_awareness['pmv2'], overlay_pmv2=overlay_awareness['pmv2'],
                qt_window_dpr=dpr, qt_widget_dpr=float(overlay.devicePixelRatioF()),
                target_native_scale=target_awareness['dpi']/96,
                target_qt_scale_mismatch=abs(dpr-target_awareness['dpi']/96) > .03,
                native_physical_width_implied_logical=own_rect['width']/dpr,
                native_physical_height_implied_logical=own_rect['height']/dpr,
                qt_logical_size=dict(width=overlay.width(), height=overlay.height()),
                geometry_mapping_matches=abs(overlay.width()*dpr-own_rect['width']) <= 2
                    and abs(overlay.height()*dpr-own_rect['height']) <= 2,
                visible=visible, compact=getattr(overlay, '_compact', None),
                native_badge_regions_verified=region_verified, gap_hit_test_passed=gap_verified, badge_above_cards_verified=anchors_verified,
                badge_regions_physical=[list(r) for r in overlay._badge_regions] if visible and args.expect=='candidate' else [],
                visible_card_count=sum(bool(b.isVisibleTo(overlay)) for b in overlay._badge_widgets) if visible and args.expect=='candidate' else overlay.row.count() if visible else 0,
                visible_tier_count=sum(bool(w.isVisibleTo(overlay)) for w in overlay.tier_labels) if visible else 0,
                visible_card_names=[card['name'] for card in overlay.cards] if visible else [],
                visible_tier_text=[w.tier if args.expect=='candidate' else w.text() for w in overlay.tier_labels if w.isVisibleTo(overlay)] if visible else [],
                visible_source_attribution=[w.source for w in overlay.tier_labels] if visible and args.expect=='candidate' else overlay.footer.text() if visible else None,
                tier_accessible_names=[w.accessibleName() for w in overlay.tier_labels] if visible else [],
                widgets=widgets, layout_issues=layout_issues,
                error=str(error) if error else None, error_type=type(error).__name__ if error else None)
            row['candidate_issues'] = case_issues(row)
            result['cases'].append(row)
        if args.expect == 'candidate':
            # Exercise native regions after partial recognition, recovery and reflow.
            original=[dict(card) for card in overlay.cards]
            overlay.hide('capture_pending');pump(app,QtCore)
            assert not native.u.IsWindowVisible(int(overlay.winId()))
            partial=[dict(card) for card in original];partial[1]['pending']=True
            overlay.set_cards('原创测试英雄',partial);overlay.show_at(ClientRect(**target_rect),target);pump(app,QtCore)
            native_region(int(overlay.winId()),overlay._badge_regions,verify_only=True)
            assert len(overlay._badge_regions)==2 and not overlay._badge_widgets[1].isVisibleTo(overlay)
            assert overlay._badge_widgets[2].tier=='T3'
            overlay.set_cards('原创测试英雄',original);overlay.show_at(ClientRect(**target_rect),target);pump(app,QtCore)
            native_region(int(overlay.winId()),overlay._badge_regions,verify_only=True)
            assert len(overlay._badge_regions)==3
            reference=dict(hero='原创测试英雄',championId='9001',sourceTier='T2',sourceTierLabel='原创测试评级',isDemo=True,sourceUrl='',sourceDataDate='原创日期',sourceVersion='原创资料',gamePatch='原创版本',wikiDataVersion='原创包')
            original_hwnd=int(overlay.winId())
            overlay.set_hero_reference(reference);overlay.show_at(ClientRect(**target_rect),target);pump(app,QtCore)
            assert int(overlay.winId())==original_hwnd and overlay.isVisible() and overlay.panel.isVisibleTo(overlay)
            full=native.window_rect(original_hwnd)
            # Read the entire native region, not only a single input point.
            gdi=ctypes.WinDLL('gdi32',use_last_error=True)
            gdi.CreateRectRgn.argtypes=[ctypes.c_int]*4;gdi.CreateRectRgn.restype=W.HANDLE
            gdi.EqualRgn.argtypes=[W.HANDLE,W.HANDLE];gdi.EqualRgn.restype=W.BOOL
            gdi.DeleteObject.argtypes=[W.HANDLE];gdi.DeleteObject.restype=W.BOOL
            native.u.GetWindowRgn.argtypes=[W.HWND,W.HANDLE];native.u.GetWindowRgn.restype=ctypes.c_int
            actual=gdi.CreateRectRgn(0,0,0,0);expected=gdi.CreateRectRgn(0,0,full['width'],full['height'])
            assert actual and expected
            try:
                kind=native.u.GetWindowRgn(original_hwnd,actual)
                assert kind==0 or gdi.EqualRgn(actual,expected), 'Reference retained nonrectangular badge clipping'
            finally:gdi.DeleteObject(actual);gdi.DeleteObject(expected)
            overlay.click_through=False;overlay.configure()
            hit=native.u.WindowFromPoint(W.POINT(full['x']+full['width']//2,full['y']+full['height']//2))
            native.u.GetAncestor.argtypes=[W.HWND,W.UINT];native.u.GetAncestor.restype=W.HWND
            assert int(native.u.GetAncestor(hit,2) or 0)==original_hwnd, 'Old badge holes clipped reference panel'
            overlay.click_through=True;overlay.configure()
            overlay.set_cards('原创测试英雄',original);overlay.show_at(ClientRect(**target_rect),target);pump(app,QtCore)
            assert int(overlay.winId())==original_hwnd
            native_region(original_hwnd,overlay._badge_regions,verify_only=True);assert len(overlay._badge_regions)==3
            result['badge_reference_transition_verified']=True
            overlay.clear_candidate_geometry();pump(app,QtCore)
            assert not native.u.IsWindowVisible(int(overlay.winId()))
            overlay.show_at(ClientRect(**target_rect),target);pump(app,QtCore)
            assert not native.u.IsWindowVisible(int(overlay.winId()))
            result['badge_lifecycle_verified']=True
        result['status'] = 'completed'
    except Exception as exc:
        result.update(error=repr(exc), traceback=traceback.format_exc())
    finally:
        try:
            if overlay is not None:
                hwnd = int(overlay.winId())
                overlay.close()
                overlay.deleteLater()
                pump(app, QtCore)
                overlay_destroyed = not bool(native.u.IsWindow(hwnd))
            else:
                overlay_destroyed = True
            target_destroyed = native.close() if native is not None else True
            result['owned_windows_destroyed'] = overlay_destroyed and target_destroyed
            if not result['owned_windows_destroyed']:
                result['status'] = 'failed'
        except Exception as exc:
            result.update(status='failed', cleanup_error=repr(exc), owned_windows_destroyed=False)
        write_json(args.child_report, result)
    return 0 if result['status'] == 'completed' else 1


def run_matrix(args):
    args.report_dir.mkdir(parents=True, exist_ok=True)
    report = dict(schema_version=1, status='failed', expect=args.expect, scope=SCOPE,
        os_name=os.name, platform=platform.platform(), python=sys.version,
        source_metadata=source_metadata(args.implementation_file, args.support_root), children=[])
    try:
        if os.name != 'nt':
            raise RuntimeError('Windows runner required; no source Qt/Win32 execution was attempted')
        for scale in SCALES:
            child_report = args.report_dir / f'windows-dpi-{args.expect}-scale-{scale}.json'
            # A previous report must not be mistaken for this child run.
            child_report.unlink(missing_ok=True)
            command = [sys.executable, '-B', str(Path(__file__).resolve()),
                '--implementation-file', str(args.implementation_file), '--support-root', str(args.support_root),
                '--report-dir', str(args.report_dir), '--expect', args.expect, '--child-report', str(child_report)]
            process, timed_out = None, False
            with (args.report_dir / f'windows-dpi-{args.expect}-scale-{scale}.log').open('w', encoding='utf-8') as log:
                try:
                    process = subprocess.Popen(command, cwd=args.report_dir,
                        env=clean_child_environment(os.environ, scale), stdout=log, stderr=subprocess.STDOUT)
                    try:
                        process.wait(timeout=args.timeout)
                    except subprocess.TimeoutExpired:
                        timed_out = True
                finally:
                    # This source-only child starts no subprocesses. Terminate
                    # only the exact Popen-owned process using its held handle.
                    if process is not None and process.poll() is None:
                        process.terminate()
                        try:
                            process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait(timeout=5)
            child = json.loads(child_report.read_text(encoding='utf-8')) if child_report.exists() else dict(status='failed')
            child.update(qt_scale_factor=scale, process_exit_code=process.returncode, timed_out=timed_out)
            if timed_out:
                child['status'] = 'failed'
            report['children'].append(child)
        report['gate_errors'] = validate_matrix(report, args.expect)
        if not report['gate_errors']:
            report['status'] = 'candidate_passed' if args.expect == 'candidate' else 'historical_regression_observed'
    except Exception as exc:
        report['error'] = repr(exc)
    finally:
        write_json(args.report_dir / f'windows-dpi-{args.expect}-matrix.json', report)
        print(json.dumps({k: v for k, v in report.items() if k != 'children'}, ensure_ascii=False, indent=2))
    return 0 if report['status'] in ('candidate_passed', 'historical_regression_observed') else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--implementation-file', type=Path, required=True)
    parser.add_argument('--support-root', type=Path, help='Directory for native_state, screen_capture and candidate overlay_geometry')
    parser.add_argument('--report-dir', type=Path, required=True)
    parser.add_argument('--expect', choices=('candidate', 'historical'), required=True)
    parser.add_argument('--timeout', type=int, default=30, help='Per-process timeout in seconds (5-120)')
    parser.add_argument('--child-report', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    args.implementation_file = args.implementation_file.resolve(strict=True)
    args.support_root = (args.support_root or args.implementation_file.parent).resolve(strict=True)
    args.report_dir = args.report_dir.resolve()
    if not 5 <= args.timeout <= 120:
        parser.error('--timeout must be between 5 and 120 seconds')
    return run_child(args) if args.child_report else run_matrix(args)


if __name__ == '__main__':
    raise SystemExit(main())

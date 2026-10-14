"""Portable Win32 call-contract tests; not native Windows flicker evidence."""
import ctypes
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from screen_capture import CaptureUnavailable, Win32Capture


LAYERED = 0x00080000
NOACTIVATE = 0x08000000
TOOLWINDOW = 0x00000080
TOPMOST = 0x00000008
TRANSPARENT = 0x00000020
REQUIRED = LAYERED | NOACTIVATE | TOOLWINDOW | TOPMOST
POSITION_FLAGS = 0x0001 | 0x0002 | 0x0010
FRAMECHANGED = 0x0020


class FakeWin32:
    def __init__(self, styles):
        self.styles = dict(styles)
        self.calls = []
        self.last_error = 0
        self.read_count = 0
        self.read_failure = None
        self.write_failure = False
        self.position_failure = False
        self.after_position = None
        self.affinity_result = True

    def set_last_error(self, value):
        self.last_error = value

    def get_last_error(self):
        return self.last_error

    def get_long(self, hwnd, index):
        if index != -20:
            raise AssertionError('Only extended styles may be queried')
        self.calls.append(('read', hwnd, index))
        self.read_count += 1
        if self.read_count == self.read_failure:
            self.last_error = 5
            return 0
        return self.styles[hwnd]

    def set_long(self, hwnd, index, style):
        if index != -20:
            raise AssertionError('Only extended styles may be changed')
        self.calls.append(('write', hwnd, index, style))
        if self.write_failure:
            self.last_error = 5
            return 0
        previous = self.styles[hwnd]
        self.styles[hwnd] = style
        return previous

    def SetWindowPos(self, hwnd, after, x, y, width, height, flags):
        self.calls.append(('position', hwnd, after.value, x, y, width, height, flags))
        if self.position_failure:
            return False
        self.styles[hwnd] |= TOPMOST
        if self.after_position is not None:
            self.styles[hwnd] = self.after_position
        return True

    def SetWindowDisplayAffinity(self, hwnd, affinity):
        self.calls.append(('affinity', hwnd, affinity))
        return self.affinity_result

    def of_kind(self, kind):
        return [call for call in self.calls if call[0] == kind]


class OverlayStyleRefreshTests(unittest.TestCase):
    def fixture(self, styles=None):
        api = FakeWin32({101: REQUIRED | TRANSPARENT} if styles is None else styles)
        capture = object.__new__(Win32Capture)
        capture.u = api
        capture.get_long = api.get_long
        capture.set_long = api.set_long
        for name in ('set_last_error', 'get_last_error'):
            replacement = patch.object(ctypes, name, getattr(api, name), create=True)
            replacement.start()
            self.addCleanup(replacement.stop)
        return capture, api

    def assert_position(self, call, hwnd, changed):
        self.assertEqual(call, ('position', hwnd, ctypes.c_void_p(-1).value,
                               0, 0, 0, 0, POSITION_FLAGS | (FRAMECHANGED if changed else 0)))

    def test_unchanged_refresh_rechecks_styles_and_topmost_without_framechange(self):
        for click_through in (True, False):
            with self.subTest(click_through=click_through):
                style = REQUIRED | (TRANSPARENT if click_through else 0)
                capture, api = self.fixture({101: style})
                for _ in range(3):
                    self.assertTrue(capture.configure_overlay(101, click_through))
                self.assertEqual(api.of_kind('write'), [])
                self.assertEqual(api.of_kind('read'), [('read', 101, -20)] * 6)
                self.assertEqual(len(api.of_kind('position')), 3)
                for call in api.of_kind('position'):
                    self.assert_position(call, 101, False)
                self.assertEqual(api.of_kind('affinity'), [('affinity', 101, 0x11)] * 3)
                self.assertEqual([call[0] for call in api.calls],
                                 ['read', 'position', 'read', 'affinity'] * 3)

    def test_click_through_changes_only_rewrite_the_changed_style(self):
        capture, api = self.fixture()
        for click_through in (False, False, True, True):
            self.assertTrue(capture.configure_overlay(101, click_through))
        self.assertEqual(api.of_kind('write'),
                         [('write', 101, -20, REQUIRED),
                          ('write', 101, -20, REQUIRED | TRANSPARENT)])
        for call, changed in zip(api.of_kind('position'), (True, False, True, False)):
            self.assert_position(call, 101, changed)
        self.assertEqual(api.styles[101], REQUIRED | TRANSPARENT)

    def test_initial_configuration_preserves_unrelated_style_bits(self):
        extra = 0x00000100
        capture, api = self.fixture({101: extra})
        self.assertTrue(capture.configure_overlay(101))
        self.assertEqual(api.of_kind('write'),
                         [('write', 101, -20, extra | LAYERED | NOACTIVATE | TOOLWINDOW | TRANSPARENT)])
        self.assertEqual(api.styles[101], extra | REQUIRED | TRANSPARENT)
        self.assert_position(api.of_kind('position')[0], 101, True)

    def test_zero_previous_style_is_success_when_last_error_is_clear(self):
        capture, api = self.fixture({101: 0})
        api.last_error = 123  # A previous unrelated API error must not poison this call.
        self.assertTrue(capture.configure_overlay(101))
        self.assertEqual(api.styles[101], REQUIRED | TRANSPARENT)
        self.assert_position(api.of_kind('position')[0], 101, True)

    def test_lost_topmost_is_reasserted_without_unnecessary_style_write(self):
        capture, api = self.fixture({101: (REQUIRED | TRANSPARENT) & ~TOPMOST})
        self.assertTrue(capture.configure_overlay(101))
        self.assertEqual(api.of_kind('write'), [])
        self.assert_position(api.of_kind('position')[0], 101, False)
        self.assertEqual(api.styles[101], REQUIRED | TRANSPARENT)

    def test_live_style_drift_is_repaired_on_later_refresh(self):
        capture, api = self.fixture()
        self.assertTrue(capture.configure_overlay(101))
        api.styles[101] &= ~LAYERED
        self.assertTrue(capture.configure_overlay(101))
        self.assertEqual(api.of_kind('write'), [('write', 101, -20, REQUIRED | TRANSPARENT)])
        for call, changed in zip(api.of_kind('position'), (False, True)):
            self.assert_position(call, 101, changed)

    def test_recreated_hwnd_reads_and_configures_the_new_window(self):
        capture, api = self.fixture({101: REQUIRED | TRANSPARENT, 202: 0})
        self.assertTrue(capture.configure_overlay(101))
        self.assertTrue(capture.configure_overlay(202))
        self.assertEqual(api.of_kind('read'),
                         [('read', 101, -20)] * 2 + [('read', 202, -20)] * 2)
        self.assertEqual(api.of_kind('write'),
                         [('write', 202, -20, LAYERED | NOACTIVATE | TOOLWINDOW | TRANSPARENT)])
        self.assert_position(api.of_kind('position')[1], 202, True)
        self.assertEqual(api.of_kind('affinity'), [('affinity', 101, 0x11), ('affinity', 202, 0x11)])

    def test_reused_numeric_hwnd_does_not_reuse_cached_style_state(self):
        capture, api = self.fixture()
        self.assertTrue(capture.configure_overlay(101))
        api.styles[101] = 0
        self.assertTrue(capture.configure_overlay(101))
        self.assertEqual(len(api.of_kind('write')), 1)
        self.assert_position(api.of_kind('position')[1], 101, True)

    def test_failed_initial_style_read_stops_before_mutation(self):
        capture, api = self.fixture()
        api.read_failure = 1
        with self.assertRaises(CaptureUnavailable):
            capture.configure_overlay(101)
        self.assertEqual(api.calls, [('read', 101, -20)])

    def test_failed_style_write_stops_before_position_or_affinity(self):
        capture, api = self.fixture({101: 0})
        api.write_failure = True
        with self.assertRaises(CaptureUnavailable):
            capture.configure_overlay(101)
        self.assertEqual([call[0] for call in api.calls], ['read', 'write'])

    def test_failed_topmost_reassertion_stops_before_affinity(self):
        capture, api = self.fixture()
        api.position_failure = True
        with self.assertRaises(CaptureUnavailable):
            capture.configure_overlay(101)
        self.assertEqual([call[0] for call in api.calls], ['read', 'position'])
        self.assert_position(api.of_kind('position')[0], 101, False)

    def test_every_required_flag_is_verified_after_position(self):
        for bit in (LAYERED, NOACTIVATE, TOOLWINDOW, TOPMOST):
            with self.subTest(bit=bit):
                capture, api = self.fixture()
                api.after_position = (REQUIRED | TRANSPARENT) & ~bit
                with self.assertRaises(CaptureUnavailable):
                    capture.configure_overlay(101)
                self.assertEqual([call[0] for call in api.calls], ['read', 'position', 'read'])
                self.assertEqual(api.of_kind('affinity'), [])

    def test_click_through_readback_must_match_each_requested_state(self):
        for click_through in (True, False):
            with self.subTest(click_through=click_through):
                style = REQUIRED | (TRANSPARENT if click_through else 0)
                capture, api = self.fixture({101: style})
                api.after_position = style ^ TRANSPARENT
                with self.assertRaises(CaptureUnavailable):
                    capture.configure_overlay(101, click_through)
                self.assertEqual(api.of_kind('affinity'), [])

    def test_failed_final_style_read_does_not_authorize_affinity(self):
        capture, api = self.fixture()
        api.read_failure = 2
        with self.assertRaises(CaptureUnavailable):
            capture.configure_overlay(101)
        self.assertEqual([call[0] for call in api.calls], ['read', 'position', 'read'])

    def test_affinity_remains_best_effort_and_is_retried_on_each_refresh(self):
        capture, api = self.fixture()
        api.affinity_result = False
        self.assertFalse(capture.configure_overlay(101))
        api.affinity_result = True
        self.assertTrue(capture.configure_overlay(101))
        self.assertEqual(api.of_kind('write'), [])
        self.assertEqual(api.of_kind('affinity'), [('affinity', 101, 0x11)] * 2)


if __name__ == '__main__':
    unittest.main()

"""Reconstructed effective-placement regressions using real production Qt methods.

The original test file was lost with its temporary workspace. These six cases
restore its behavioral coverage, not its bytes. Win32 boundaries are owned
doubles; passing here is not Windows capture or live-game validation.

Keep the repository's optional-Qt collection convention. Acceptance runs must
install Qt and require zero skips; separate QT_SCALE_FACTOR processes exercise
actual Qt DPR values.
"""
import copy
import ctypes
from ctypes import wintypes as W
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from PySide6 import QtCore, QtGui, QtWidgets
    from shiboken6 import isValid
except ImportError:
    QtWidgets = None
if QtWidgets is not None:
    from card_badges import accepted_anchors, badge_placement
    from native_ui import Overlay
from screen_capture import ClientRect


class HideObserver(QtCore.QObject if QtWidgets is not None else object):
    def __init__(self, parent):
        super().__init__(parent)
        self.events = []

    def eventFilter(self, obj, event):
        if event.type() == QtCore.QEvent.Type.Hide:
            self.events.append(event.type())
        return False


class OwnedCapture:
    """Only the native boundary is doubled; placement/verification stay real."""
    def __init__(self):
        self.u = self
        self.bounds = (0, 0, 1, 1)
        self.positions = []
        self.reads = []
        self.configurations = []
        self.retirements = 0
        self.session = None

    def SetWindowPos(self, hwnd, after, x, y, width, height, flags):
        self.positions.append((hwnd, x, y, width, height, flags))
        if flags & 0x0001:  # SWP_NOSIZE, as in the production monitor probe.
            width, height = self.bounds[2:]
        self.bounds = (x, y, width, height)
        return 1

    def GetWindowRect(self, hwnd, pointer):
        self.reads.append(hwnd)
        actual = ctypes.cast(pointer, ctypes.POINTER(W.RECT)).contents
        x, y, width, height = self.bounds
        actual.left, actual.top = x, y
        actual.right, actual.bottom = x + width, y + height
        return 1

    def configure_overlay(self, hwnd, click_through, *, opaque=False):
        self.configurations.append((hwnd, click_through, opaque))

    def retire_session(self):
        self.retirements += 1
        self.session = None


@unittest.skipIf(QtWidgets is None, 'Optional Qt runtime is not installed')
class BadgeEffectivePlacementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.overlay = Overlay()
        self.addCleanup(self.dispose)
        self.candidates = [
            dict(name=f'候选{i + 1}', box=[[90 + i * 270, 230],
                 [180 + i * 270, 230], [180 + i * 270, 260],
                 [90 + i * 270, 260]]) for i in range(3)]
        self.geometry = SimpleNamespace(
            rects=((.05, .3, .25, .6), (.35, .3, .25, .6),
                   (.65, .3, .25, .6)), size=(900, 600), space='frame')
        self.cards = [dict(slot=i + 1, name=f'候选{i + 1}', sourceTier=f'T{i + 1}')
                      for i in range(3)]
        self.image_size = {'width': 900, 'height': 600}
        self.roi = (0, 0, 1, 1)
        self.rect = ClientRect(-1800, -1200, 1800, 1200)
        self.assertTrue(self.set_geometry(self.geometry))
        self.overlay.set_cards('英雄', self.cards)
        self.observer = HideObserver(self.overlay)
        self.overlay.installEventFilter(self.observer)

    def dispose(self):
        overlay = self.overlay
        overlay.capture = None
        overlay.close()
        overlay.deleteLater()
        QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
        self.app.processEvents()
        self.assertFalse(isValid(overlay))

    def set_geometry(self, geometry, candidates=None):
        return self.overlay.set_candidate_geometry(
            self.candidates if candidates is None else candidates,
            self.image_size, self.roi, geometry)

    def geometry_with(self, *, height=None, width=None, top=None):
        rects = []
        for x, y, w, h in self.geometry.rects:
            if width is not None:
                x, w = x + w / 2 - width / 2, width
            rects.append((x, y if top is None else top, w,
                          h if height is None else height))
        return SimpleNamespace(rects=tuple(rects), size=self.geometry.size,
                               space=self.geometry.space)

    def show(self):
        self.overlay.show_at(self.rect, None)
        self.app.processEvents()
        self.assertTrue(self.overlay.isVisible())

    def snapshot(self):
        o = self.overlay
        return (o._placed_key, o._badge_bounds, o._badge_regions,
                QtGui.QRegion(o.mask()), int(o.winId()),
                tuple(b.geometry().getRect() for b in o._badge_widgets))

    def assert_retained(self, before):
        self.assertTrue(self.overlay.isVisible())
        self.assertTrue(all(b.isVisible() for b in self.overlay._badge_widgets))
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.observer.events, [])

    def assert_same_placement(self, geometry):
        anchors = accepted_anchors(self.candidates, self.image_size, self.roi, geometry)
        self.assertEqual(anchors.names, tuple(card['name'] for card in self.cards))
        dpr = float(self.overlay.windowHandle().devicePixelRatio())
        self.assertEqual(badge_placement(self.rect, dpr, anchors, (0, 1, 2)),
                         (self.overlay._badge_bounds, self.overlay._badge_regions))

    def test_bottom_only_change_preserves_visible_physical_placement(self):
        self.show()
        before = self.snapshot()
        self.observer.events.clear()
        with patch.object(self.overlay, 'hide', wraps=self.overlay.hide) as hide, \
             patch.object(self.overlay, 'setMask', wraps=self.overlay.setMask) as mask:
            for height in (.599, .58, .6):
                geometry = self.geometry_with(height=height)
                self.assert_same_placement(geometry)
                self.assertTrue(self.set_geometry(geometry))
                self.assert_retained(before)  # No transient hide before show_at.
                self.show()
                self.assert_retained(before)
                self.assertEqual(self.overlay._badge_anchors.rects, geometry.rects)
            hide.assert_not_called()
            mask.assert_not_called()

    def test_width_change_with_same_center_preserves_visible_placement(self):
        self.show()
        before = self.snapshot()
        self.observer.events.clear()
        with patch.object(self.overlay, 'hide', wraps=self.overlay.hide) as hide, \
             patch.object(self.overlay, 'setMask', wraps=self.overlay.setMask) as mask:
            for width in (.23, .27, .25):
                geometry = self.geometry_with(width=width)
                self.assert_same_placement(geometry)
                self.assertTrue(self.set_geometry(geometry))
                self.assert_retained(before)
                self.show()
                self.assert_retained(before)
                self.assertEqual(self.overlay._badge_anchors.rects, geometry.rects)
            hide.assert_not_called()
            mask.assert_not_called()

    def test_real_card_top_movement_hides_before_replacement(self):
        self.show()
        before = (self.overlay._badge_bounds, self.overlay._badge_regions)
        geometry = self.geometry_with(top=.32)
        anchors = accepted_anchors(self.candidates, self.image_size, self.roi, geometry)
        self.assertEqual(anchors.names, tuple(card['name'] for card in self.cards))
        dpr = float(self.overlay.windowHandle().devicePixelRatio())
        after = badge_placement(self.rect, dpr, anchors, (0, 1, 2))
        self.assertNotEqual(after, before)
        with patch.object(self.overlay, 'hide', wraps=self.overlay.hide) as hide:
            self.assertTrue(self.set_geometry(geometry))
            hide.assert_called_once_with('card_geometry_changed')
        self.assertFalse(self.overlay.isVisible())
        self.assertIsNone(self.overlay._placed_key)
        self.show()
        self.assertEqual((self.overlay._badge_bounds, self.overlay._badge_regions), after)

    def test_missing_geometry_and_visible_slot_name_change_hide(self):
        for change in ('missing_geometry', 'visible_name'):
            with self.subTest(change=change):
                self.assertTrue(self.set_geometry(self.geometry))
                self.show()
                candidates = copy.deepcopy(self.candidates)
                geometry = self.geometry
                if change == 'missing_geometry':
                    geometry = None
                else:
                    candidates[0]['name'] = '另一个候选'
                with patch.object(self.overlay, 'hide', wraps=self.overlay.hide) as hide:
                    self.assertEqual(self.set_geometry(geometry, candidates), geometry is not None)
                    hide.assert_called_once_with('card_geometry_changed')
                self.assertFalse(self.overlay.isVisible())
                self.assertIsNone(self.overlay._placed_key)
                if geometry is None:
                    self.overlay.show_at(self.rect, None)
                    self.assertFalse(self.overlay.isVisible())

    def test_identical_native_placement_does_not_retire_live_session(self):
        capture = OwnedCapture()
        self.overlay.capture = capture
        installed = {}
        region_calls = []

        def native_boundary(hwnd, regions, *, verify_only=False):
            region_calls.append((hwnd, regions, verify_only))
            if verify_only:
                self.assertEqual(installed[hwnd], regions)
            else:
                installed[hwnd] = regions

        with patch('card_badges.native_region', side_effect=native_boundary):
            self.show()
            before = self.snapshot()
            hwnd = int(self.overlay.winId())
            self.assertEqual(capture.bounds, self.overlay._badge_bounds)
            self.assertEqual(region_calls, [(hwnd, self.overlay._badge_regions, False),
                                            (hwnd, self.overlay._badge_regions, True)])
            live_session = object()
            capture.session = live_session
            retires = capture.retirements
            capture.positions.clear()
            capture.reads.clear()
            capture.configurations.clear()
            region_calls.clear()
            self.observer.events.clear()
            for geometry in (self.geometry_with(height=.58),
                             self.geometry_with(width=.23), self.geometry):
                self.assert_same_placement(geometry)
                self.assertTrue(self.set_geometry(geometry))
                self.show()
                self.assertEqual(capture.retirements, retires)
                self.assertIs(capture.session, live_session)
                self.assert_retained(before)
            self.assertEqual(capture.positions, [])
            self.assertEqual(capture.configurations, [(hwnd, True, True)] * 3)
            self.assertEqual(capture.reads, [hwnd] * 6)  # Bounds AND client-budget proof.
            self.assertEqual(region_calls, [(hwnd, self.overlay._badge_regions, True)] * 3)

    def test_title_outside_new_geometry_hides_despite_identical_placement(self):
        self.show()
        geometry = copy.deepcopy(self.geometry)
        geometry.rects = ((.05, .3, .25, .1), *geometry.rects[1:])
        anchors = accepted_anchors(self.candidates, self.image_size, self.roi, geometry)
        self.assertEqual(anchors.names, (None, '候选2', '候选3'))
        dpr = float(self.overlay.windowHandle().devicePixelRatio())
        self.assertEqual(badge_placement(self.rect, dpr, anchors, (0, 1, 2)),
                         (self.overlay._badge_bounds, self.overlay._badge_regions))
        with patch.object(self.overlay, 'hide', wraps=self.overlay.hide) as hide:
            self.assertTrue(self.set_geometry(geometry))
            hide.assert_called_once_with('card_geometry_changed')
        self.assertFalse(self.overlay.isVisible())
        self.assertIsNone(self.overlay._placed_key)
        self.show()
        self.assertFalse(self.overlay._badge_widgets[0].isVisible())
        self.assertTrue(all(b.isVisible() for b in self.overlay._badge_widgets[1:]))
        self.assertEqual(len(self.overlay._badge_regions), 2)


if __name__ == '__main__':
    unittest.main()

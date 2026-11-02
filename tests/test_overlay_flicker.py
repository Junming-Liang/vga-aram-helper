"""Owned Qt display-lifecycle checks for the recognition box blinking report.

One strict-hidden pixel recheck withdraws the overlay, and the box must return as
soon as that frame's pixels are already in hand rather than after the whole local
inference. These are synthetic fixtures: no Windows capture, WGC session, real
League client or live game is exercised here.
"""
import unittest
from unittest.mock import patch

from tests import test_client_feedback as fixtures
from tests import test_semantic_title_recheck as semantic
from tests.test_badge_effective_placement import OwnedCapture


def hide_observer(overlay):
    from PySide6 import QtCore
    events = []

    class Observer(QtCore.QObject):
        def eventFilter(self, obj, event):
            if event.type() == QtCore.QEvent.Type.Hide:
                events.append(1)
            return False

    return events, Observer(overlay)


@unittest.skipIf(fixtures.QtWidgets is None, 'Optional Qt/PIL runtime is not installed')
class ClientStripRestoreTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.ClientDisplayTests.setUpClass.__func__)
    setUp = fixtures.ClientDisplayTests.setUp
    pump = fixtures.ClientDisplayTests.pump
    dispose = fixtures.ClientDisplayTests.dispose
    prepare_client = fixtures.ClientDisplayTests.prepare_client
    deliver = fixtures.ClientDisplayTests.deliver

    def start_strict_hidden_recheck(self, captured_at):
        w = self.window
        w._visible_previous = False
        w.monitor.stop()
        w.capture_pending = True
        w.ocr_busy = True
        w.ocr_started = captured_at - .1
        w._capture_serial += 1
        w.overlay.hide('capture_pending')
        self.assertFalse(w.overlay.isVisible())
        return dict(_capturedAt=captured_at, _captureSerial=w._capture_serial,
                    _windowIdentity=w.target.identity, _captureRect=self.proof['rect'])

    def test_unchanged_client_strip_returns_as_soon_as_pixels_are_acquired(self):
        self.window.lcu_toggle.setChecked(True)
        w = self.prepare_client()
        self.deliver(100., 100.1)
        self.deliver(101., 101.1)
        self.assertTrue(w.overlay.isVisible())
        revision = w.overlay._layout_revision
        observation = w.last_observation
        proof = self.start_strict_hidden_recheck(101.3)
        events, observer = hide_observer(w.overlay)
        with patch('native_ui.time.monotonic', return_value=101.4):
            w.task_result('capture-proof', proof, w.state.generation)
        self.assertTrue(w.overlay.isVisible())
        # Presentation only: inference is still running, no new observation and
        # no structural rebuild happened on the way back.
        self.assertTrue(w.ocr_busy)
        self.assertFalse(w.capture_pending)
        self.assertEqual(w.overlay._layout_revision, revision)
        self.assertEqual(w.last_observation, observation)
        self.assertEqual(events, [])

    def test_a_strip_whose_client_authority_aged_out_is_not_brought_back(self):
        self.window.lcu_toggle.setChecked(True)
        w = self.prepare_client()
        self.deliver(100., 100.1)
        self.deliver(101., 101.1)
        proof = self.start_strict_hidden_recheck(101.3)
        with patch('native_ui.time.monotonic', return_value=106.):
            w.task_result('capture-proof', proof, w.state.generation)
        self.assertFalse(w.client_strip_current())
        self.assertFalse(w._restore_while_ocr)
        self.assertFalse(w.overlay.isVisible())

    def test_card_badges_still_need_their_own_frame_proof_to_return(self):
        self.window.lcu_toggle.setChecked(True)
        w = self.prepare_client()
        self.deliver(100., 100.1)
        self.deliver(101., 101.1)
        # An accepted card display carries no client-authoritative strip, so the
        # pixel proof alone decides whether the old grades may be shown.
        w.overlay.reference = None
        w.overlay.cards = [dict(slot=1, name='候选', sourceTier='T1', sourceTierLabel='来源评级')]
        proof = self.start_strict_hidden_recheck(101.3)
        with patch('native_ui.time.monotonic', return_value=101.4):
            w.task_result('capture-proof', proof, w.state.generation)
        self.assertFalse(w._restore_while_ocr)
        self.assertFalse(w.overlay.isVisible())


@unittest.skipIf(fixtures.QtWidgets is None, 'Optional Qt/PIL runtime is not installed')
class NativeReassertTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = (fixtures.QtWidgets.QApplication.instance()
                   or fixtures.QtWidgets.QApplication([]))
        cls.app.setQuitOnLastWindowClosed(False)

    def overlay(self, capture):
        from native_ui import Overlay
        widget = Overlay(capture=capture)
        self.addCleanup(widget.deleteLater)
        return widget

    def test_configure_skips_the_native_reassert_while_enrollment_still_matches(self):
        calls = []

        class Stateful:
            def __init__(self, current):
                self.current = current

            def overlay_state_current(self, hwnd):
                return self.current

            def configure_overlay(self, *args, **kwargs):
                calls.append((args, kwargs))

        widget = self.overlay(Stateful(True))
        widget.configure()
        self.assertEqual(calls, [])
        widget.capture = Stateful(False)
        widget.configure()
        self.assertEqual(len(calls), 1)

    def test_a_stale_badge_placement_key_never_survives_leaving_the_badges(self):
        from types import SimpleNamespace
        from screen_capture import ClientRect
        capture = OwnedCapture()
        widget = self.overlay(capture)
        cards = [dict(slot=i + 1, name=f'候选{i + 1}', sourceTier=f'T{i + 1}',
                      sourceTierLabel='虎牙公开源评级') for i in range(3)]
        candidates = [dict(name=f'候选{i + 1}',
                           box=[[90 + i * 270, 230], [180 + i * 270, 230],
                                [180 + i * 270, 260], [90 + i * 270, 260]]) for i in range(3)]
        geometry = SimpleNamespace(rects=((.05, .3, .25, .6), (.35, .3, .25, .6), (.65, .3, .25, .6)),
                                   size=(900, 600), space='frame')
        widget.set_cards('阿萝拉', cards, '2026-09-07', '26.21', '自动识别')
        widget.set_candidate_geometry(candidates, {'width': 900, 'height': 600}, (0, 0, 1, 1), geometry)
        with patch('card_badges.native_region', return_value=True):
            widget.show_at(ClientRect(0, 0, 1600, 900), None)
        self.assertIsNotNone(widget._placed_key)
        widget._leave_badges()
        self.assertIsNone(widget._placed_key)
        self.assertIsNone(widget._expired_badge_placement)


@unittest.skipIf(fixtures.QtWidgets is None, 'Optional Qt/PIL runtime is not installed')
class BadgePlacementStabilityTests(unittest.TestCase):
    """A re-measure of the same three cards is not a new layout.

    Real HUD card edges wobble by a pixel or two between frames. Treating that
    as a relayout hides the box and retires the visible-capture session, so the
    next cycle must run strict-hidden and the player sees the box blink while
    the same candidates are still offered.
    """

    @classmethod
    def setUpClass(cls):
        cls.app = (fixtures.QtWidgets.QApplication.instance()
                   or fixtures.QtWidgets.QApplication([]))
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        from types import SimpleNamespace
        from native_ui import Overlay
        from screen_capture import ClientRect
        self.rect = ClientRect(0, 0, 1600, 900)
        self.candidates = [dict(name=f'候选{i + 1}',
                                box=[[90 + i * 270, 230], [180 + i * 270, 230],
                                     [180 + i * 270, 260], [90 + i * 270, 260]]) for i in range(3)]
        self.base = ((.05, .3, .25, .6), (.35, .3, .25, .6), (.65, .3, .25, .6))
        self.geometry = lambda rects: SimpleNamespace(rects=rects, size=(900, 600), space='frame')
        self.capture = OwnedCapture()
        self.widget = Overlay(capture=self.capture)
        self.addCleanup(self.widget.deleteLater)
        cards = [dict(slot=i + 1, name=f'候选{i + 1}', sourceTier=f'T{i + 1}',
                      sourceTierLabel='虎牙公开源评级') for i in range(3)]
        self.widget.set_cards('阿萝拉', cards, '2026-09-07', '26.21', '自动识别')
        self.assertTrue(self.widget.set_candidate_geometry(
            self.candidates, {'width': 900, 'height': 600}, (0, 0, 1, 1), self.geometry(self.base)))
        self.events, self.observer = hide_observer(self.widget)
        self.widget.installEventFilter(self.observer)
        with patch('card_badges.native_region', return_value=True):
            self.widget.show_at(self.rect, None)
        self.installed = (self.widget._badge_bounds, self.widget._badge_regions)
        self.assertIsNotNone(self.widget._placed_key)
        self.capture.positions.clear()
        self.capture.reads.clear()
        self.capture.configurations.clear()
        self.retires = self.capture.retirements

    def remeasure(self, rects):
        from card_badges import accepted_anchors, badge_placement
        anchors = accepted_anchors(self.candidates, {'width': 900, 'height': 600},
                                   (0, 0, 1, 1), self.geometry(rects))
        self.assertEqual(anchors.names, tuple(card['name'] for card in self.widget.cards))
        dpr = float(self.widget.windowHandle().devicePixelRatio())
        measured = badge_placement(self.rect, dpr, anchors, (0, 1, 2))
        with patch('card_badges.native_region', return_value=True) as region:
            self.assertTrue(self.widget.set_candidate_geometry(
                self.candidates, {'width': 900, 'height': 600}, (0, 0, 1, 1), self.geometry(rects)))
            self.widget.show_at(self.rect, None)
        return measured, region

    def test_a_few_pixel_remeasure_keeps_the_box_and_its_installed_regions(self):
        shifted = tuple((x, y + 3 / 900, w, h) for x, y, w, h in self.base)
        measured, region = self.remeasure(shifted)
        self.assertNotEqual(measured, self.installed)  # The tolerance is what retains it.
        self.assertEqual((self.widget._badge_bounds, self.widget._badge_regions), self.installed)
        self.assertEqual(self.widget._badge_regions, self.installed[1])
        self.assertTrue(self.widget.isVisible())
        self.assertEqual(self.events, [])
        self.assertEqual(self.capture.retirements, self.retires)
        self.assertEqual(self.capture.positions, [])
        # The fast path only ever reads back the region it already installed.
        self.assertTrue(all(call.kwargs.get('verify_only') for call in region.call_args_list))

    def test_a_real_card_move_still_hides_relays_out_and_revokes_the_session(self):
        moved = tuple((x, y + 30 / 900, w, h) for x, y, w, h in self.base)
        with patch('card_badges.native_region', return_value=True):
            self.assertTrue(self.widget.set_candidate_geometry(
                self.candidates, {'width': 900, 'height': 600}, (0, 0, 1, 1), self.geometry(moved)))
            self.assertIsNone(self.widget._placed_key)
            self.widget.show_at(self.rect, None)
        self.assertEqual(self.capture.retirements, self.retires + 1)
        self.assertTrue(self.capture.positions)
        self.assertTrue(self.events)  # A genuine move is allowed to blink once.
        self.assertTrue(self.widget.isVisible())
        self.assertNotEqual((self.widget._badge_bounds, self.widget._badge_regions), self.installed)

    def test_the_next_remeasure_never_accumulates_drift_past_the_tolerance(self):
        from card_badges import PLACEMENT_TOLERANCE
        cumulative = 0
        for _ in range(6):
            cumulative += 2 / 900
            shifted = tuple((x, y + cumulative, w, h) for x, y, w, h in self.base)
            measured, _ = self.remeasure(shifted)
            retained = (self.widget._badge_bounds, self.widget._badge_regions) == self.installed
            if retained:
                offset = abs(measured[0][1] - self.installed[0][1])
                self.assertLessEqual(offset, PLACEMENT_TOLERANCE)
            else:
                # A re-anchored layout restarts the budget instead of drifting.
                self.installed = (self.widget._badge_bounds, self.widget._badge_regions)
                self.capture.positions.clear()
                cumulative = 0
        self.assertTrue(self.widget.isVisible())


@unittest.skipIf(semantic.fixture.QtWidgets is None, 'Optional Qt/PIL runtime is not installed')
class CheckingHoldFlickerTests(unittest.TestCase):
    """An in-scope frame of animated artwork must not blank the recognition box.

    The strict-hidden route hides the overlay for its own capture. When the fresh
    pixels then could not be proven identical to the accepted observation, the box
    stayed hidden for the whole local inference and returned only with the next
    result — the blink the player reports next to the 复核中 label. A frame whose
    own border re-verification failed likewise revoked a healthy box outright.
    """

    setUpClass = classmethod(semantic.fixture.NativeCaptureWorkerTests.setUpClass.__func__)
    setUp = semantic.SemanticTitleRecheckTests.setUp
    wait = semantic.SemanticTitleRecheckTests.wait
    dispose_window = semantic.SemanticTitleRecheckTests.dispose_window
    accepted_proof_fixture = semantic.SemanticTitleRecheckTests.accepted_proof_fixture
    scene = semantic.SemanticTitleRecheckTests.scene
    phase = semantic.SemanticTitleRecheckTests.phase

    def installed(self, w):
        events, observer = hide_observer(w.overlay)
        w.overlay.installEventFilter(observer)
        self.addCleanup(w.overlay.removeEventFilter, observer)
        return events, int(w.overlay.winId()), w.overlay._placed_key, w.overlay.mask()

    def real_geometry(self, w, jitter=0.):
        from augment_card_geometry import CardGeometry
        rects = tuple((x, y + jitter, rw, rh) for x, y, rw, rh in w.overlay._badge_anchors.rects)
        return CardGeometry(rects, (900, 600), 'fresh-detection', (), 'frame')

    def test_strict_hidden_frame_holds_the_accepted_box_through_the_inference(self):
        value, hero, names = self.scene(); w = self.window
        w._visible_previous = False
        w.overlay.hide('capture_pending')
        self.assertFalse(w.overlay.isVisible())
        events, hwnd, key, mask = self.installed(w)
        observation, frames = w.last_observation, w.state.automatic_frames
        self.phase('capture-proof', dict(value, _roiDigest='animated-pixels',
                                         _matchingTitleProof=None,
                                         hero_observation=dict(hero=hero, confident=True)))
        self.assertFalse(w._restore_while_ocr)   # Pixel identity is still not proven.
        self.assertTrue(w.hold_while_ocr)
        self.assertTrue(w.overlay.isVisible())
        # The hold keeps the box in place without presenting any grade: this frame
        # has not earned one, and a grade here would be the stale data the player
        # cannot distinguish from a real current rating.
        self.assertTrue(w.overlay._titles_pending)
        self.assertEqual([badge.tier for badge in w.overlay._badge_widgets], ['', '', ''])
        self.assertEqual(w.overlay.heading.text(), '候选复核中')
        self.assertEqual(w.state.offered, names)  # Only the accepted observation.
        self.assertEqual((w.last_observation, w.state.automatic_frames), (observation, frames))
        self.assertEqual(events, [])
        self.assertEqual((int(w.overlay.winId()), w.overlay._placed_key, w.overlay.mask()), (hwnd, key, mask))

    def test_an_out_of_scope_frame_still_hides_rather_than_holding(self):
        value, hero, names = self.scene(); w = self.window
        w._visible_previous = False
        w.overlay.hide('capture_pending')
        scope = list(value['_frameScope']); scope[3] = 'changed scene scope'
        self.phase('capture-proof', dict(value, _frameScope=tuple(scope),
                                         hero_observation=dict(hero=hero, confident=True)))
        self.assertFalse(w.hold_while_ocr)
        self.assertFalse(w.overlay.isVisible())

    def test_unproven_edges_defer_to_the_title_phase_instead_of_revoking(self):
        value, hero, names = self.scene(); w = self.window
        self.assertTrue(w._visible_previous)
        events, hwnd, key, mask = self.installed(w)
        frames = w.state.automatic_frames
        self.phase('capture-proof', dict(value, _matchingCardGeometry=None,
                                         hero_observation=dict(hero=hero, confident=True)))
        self.assertTrue(w._geometry_deferred)
        self.assertIsNotNone(w._accepted_frame)
        self.assertTrue(w.overlay.isVisible())
        self.assertTrue(w.state.confirmed)
        self.assertEqual(w.state.offered, names)
        self.assertEqual(w.state.automatic_frames, frames)
        self.assertEqual(events, [])
        self.assertEqual((int(w.overlay.winId()), w.overlay._placed_key, w.overlay.mask()), (hwnd, key, mask))

    def test_fresh_full_detection_resolves_the_deferral_without_a_new_observation(self):
        value, hero, names = self.scene(); w = self.window
        accepted = self.real_geometry(w)
        w._accepted_frame['card_geometry'] = accepted
        observation = w.last_observation
        deferred = dict(value, _matchingCardGeometry=None, _cardGeometry=self.real_geometry(w),
                        hero_observation=dict(hero=hero, confident=True))
        self.phase('capture-proof', deferred)
        self.assertTrue(w._geometry_deferred)
        self.phase('title-proof', deferred)
        self.assertFalse(w._geometry_deferred)
        self.assertTrue(w.overlay.isVisible())
        self.assertTrue(w.state.confirmed)
        self.assertEqual(w.state.offered, names)
        self.assertEqual(w.last_observation, observation)

    def test_a_deferral_never_survives_contradicting_fresh_detection(self):
        value, hero, names = self.scene(); w = self.window
        w._accepted_frame['card_geometry'] = self.real_geometry(w)
        moved = dict(value, _matchingCardGeometry=None, _cardGeometry=None,
                     hero_observation=dict(hero=hero, confident=True))
        self.phase('capture-proof', moved)
        self.assertTrue(w._geometry_deferred)
        self.phase('title-proof', moved)
        self.assertFalse(w._geometry_deferred)
        self.assertFalse(w.overlay.isVisible())
        self.assertFalse(w.state.confirmed)
        self.assertIsNone(w._accepted_frame)

    def test_the_hold_dies_with_the_inference_and_with_the_next_capture(self):
        value, hero, names = self.scene(); w = self.window
        w._visible_previous = False
        w.overlay.hide('capture_pending')
        self.phase('capture-proof', dict(value, _roiDigest='animated-pixels',
                                         hero_observation=dict(hero=hero, confident=True)))
        self.assertTrue(w.hold_while_ocr)
        w.ocr_busy = False
        self.assertFalse(w.hold_while_ocr)
        w.ocr_busy = True
        self.assertTrue(w.hold_while_ocr)
        w._capture_serial += 1
        self.assertFalse(w.hold_while_ocr)
        w._capture_serial -= 1
        w._accepted_frame = None
        self.assertFalse(w.hold_while_ocr)


class GeometryEquivalenceTests(unittest.TestCase):
    """A few physical pixels between two measured layouts is not a new layout."""

    def geometry(self, jitter=0., index=0):
        from augment_card_geometry import CardGeometry
        rects = [[.05, .30, .25, .60], [.35, .30, .25, .60], [.65, .30, .25, .60]]
        rects[index][1] += jitter
        return CardGeometry(tuple(tuple(r) for r in rects), (900, 600), 'd', (), 'frame')

    def test_within_tolerance_and_beyond_it(self):
        from augment_card_geometry import GEOMETRY_TOLERANCE, geometry_equivalent
        base = self.geometry()
        self.assertTrue(geometry_equivalent(self.geometry(), base))
        self.assertTrue(geometry_equivalent(self.geometry(2 / 600), base))
        self.assertTrue(geometry_equivalent(self.geometry(GEOMETRY_TOLERANCE / 600), base))
        self.assertFalse(geometry_equivalent(self.geometry((GEOMETRY_TOLERANCE + 1) / 600), base))
        self.assertFalse(geometry_equivalent(self.geometry(30 / 600), base))
        # Every rectangle is compared, not merely the first or the envelope.
        self.assertFalse(geometry_equivalent(self.geometry(30 / 600, index=2), base))
        self.assertTrue(geometry_equivalent(self.geometry(2 / 600, index=2), base))

    def test_incompatible_shapes_and_spaces_are_never_equivalent(self):
        from dataclasses import replace
        from augment_card_geometry import CardGeometry, geometry_equivalent
        base = self.geometry()
        self.assertFalse(geometry_equivalent(None, base))
        self.assertFalse(geometry_equivalent(base, None))
        self.assertFalse(geometry_equivalent(base, replace(base, space='crop')))
        self.assertFalse(geometry_equivalent(base, replace(base, size=(1600, 900))))
        self.assertFalse(geometry_equivalent(base, replace(base, rects=base.rects[:2])))


if __name__ == '__main__':
    unittest.main()


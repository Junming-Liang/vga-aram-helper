"""Owned portrait refreshes never replace live-frame recognition authority.

Qt callbacks and the full synthetic OCR pipeline are real; Windows/game capture
and network are not exercised. Lifecycle tests use verified owned OS metadata.
"""
import copy
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tests import test_native_capture_worker as fixtures
from tests import test_animated_augment_rounds as animated


@unittest.skipIf(fixtures.QtWidgets is None, 'Optional Qt runtime is not installed')
class PortraitRefreshBoundaryTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.NativeCaptureWorkerTests.setUpClass.__func__)
    setUp = fixtures.NativeCaptureWorkerTests.setUp
    wait = fixtures.NativeCaptureWorkerTests.wait
    dispose_window = fixtures.NativeCaptureWorkerTests.dispose_window

    def bank(self, color=(40, 90, 130)):
        from PIL import Image
        return {str(i): Image.new('RGB', (64, 64), color) for i in range(1, 101)}

    def deliver(self, bank, state='fresh', **extra):
        w = self.window
        w._portraits_attempt += 1
        w._portraits_busy = True
        w.task_result('portraits', (bank, {'state': state, 'message': 'Owned bank', **extra}),
                      w._portraits_attempt)

    def install_then_defer(self):
        self.deliver(self.bank())
        old = self.window.hero_matcher
        revision = self.window.portrait_bank.revision
        self.deliver(self.bank((140, 90, 130)))
        self.assertIs(self.window.hero_matcher, old)
        self.assertEqual(self.window.portrait_bank.revision, revision + 1)
        self.assertIsNotNone(self.window._pending_portraits)
        return old

    def test_copied_equivalent_banks_preserve_identity_and_display_revision(self):
        w = self.window
        bank = self.bank()
        self.deliver(bank)
        matcher, token, revision = w.hero_matcher, w.hero_matcher.proof_identity(), w.portrait_bank.revision
        with patch('hero_recognition.PortraitMatcher') as constructor:
            for _ in range(4):
                self.deliver({key: image.copy() for key, image in reversed(list(bank.items()))})
        constructor.assert_not_called()
        self.assertIs(w.hero_matcher, matcher)
        self.assertEqual(w.hero_matcher.proof_identity(), token)
        self.assertEqual(w.portrait_bank.revision, revision)
        self.assertIsNone(w._pending_portraits)

    def test_first_bank_installs_immediately_while_monitoring(self):
        w = self.window
        self.assertTrue(w.state.running)
        self.assertIsNone(w.hero_matcher)
        self.deliver(self.bank())
        self.assertIsNotNone(w.hero_matcher)
        self.assertIsNone(w._pending_portraits)
        self.assertFalse(w._portraits_busy)

    def test_changed_bank_waits_through_focus_invalidation_then_applies_on_stop(self):
        w = self.window
        old = self.install_then_defer()
        pending = w._pending_portraits[3]
        revision = w.portrait_bank.revision
        w.invalidate_scene('Owned temporary focus loss', debug_reason='focus_lost')
        self.assertIs(w.hero_matcher, old)
        w.stop_monitor()
        self.assertIs(w.hero_matcher, pending)
        self.assertEqual(w.portrait_bank.revision, revision)
        self.assertIsNone(w._pending_portraits)
        self.assertFalse(w.state.running)
        self.assertFalse(w.state.confirmed)
        self.assertFalse(w.state.hero)
        self.assertFalse(w.overlay.isVisible())

    def test_catalog_name_change_is_not_content_equivalent(self):
        w = self.window
        bank = self.bank()
        hero = next(iter(w.data['heroes']))
        w.data['heroes'][hero]['championId'] = '1'
        self.deliver(bank)
        old = w.hero_matcher
        w.data['heroes']['Owned renamed hero'] = w.data['heroes'].pop(hero)
        self.deliver(copy.deepcopy(bank))
        self.assertIs(w.hero_matcher, old)
        self.assertIsNotNone(w._pending_portraits)
        w.stop_monitor()
        self.assertEqual(w.hero_matcher.names['1'], 'Owned renamed hero')

    def test_pending_bank_revalidates_current_catalog_at_boundary(self):
        w = self.window
        self.install_then_defer()
        hero = next(iter(w.data['heroes']))
        w.data['heroes'][hero]['championId'] = '1'
        w.stop_monitor()
        self.assertEqual(w.hero_matcher.names['1'], hero)
        self.assertIsNone(w._pending_portraits)

    def test_next_game_process_installs_pending_and_revokes_old_authority(self):
        from automatic_windows import AutomaticWindowPolicy
        from screen_capture import WindowInfo
        from session_windows import ProcessMetadata
        w = self.window
        game = WindowInfo(123, 456, 'Owned game', 'RiotWindowClass')
        metadata = {456: ProcessMetadata(r'C:\Owned\Game\League of Legends.exe', 100)}
        policy = AutomaticWindowPolicy(resolver=lambda pid: metadata[pid], verifier=lambda path: True)
        w.automatic_policy = policy
        w.capture = SimpleNamespace(windows=lambda **kwargs: [game], retire_session=lambda: None)
        w.apply_discovery(policy.discover([game]), w.discovery_scope)
        old = self.install_then_defer()
        pending = w._pending_portraits[3]
        generation = w.state.generation
        # Repeated discovery of the same process is not a model boundary.
        w.apply_discovery(policy.discover([game]), w.discovery_scope)
        self.assertIs(w.hero_matcher, old)
        self.assertEqual(w.state.generation, generation)
        w.state.hero = 'Owned previous hero'
        w.state.confirmed = True
        # Same HWND/PID, genuinely new process creation time is a new game.
        metadata[456] = ProcessMetadata(metadata[456].path, 200)
        w.apply_discovery(policy.discover([game]), w.discovery_scope)
        self.assertIs(w.hero_matcher, pending)
        self.assertIsNone(w._pending_portraits)
        self.assertGreater(w.state.generation, generation)
        self.assertFalse(w.state.hero)
        self.assertFalse(w.state.confirmed)
        self.assertFalse(w.overlay.isVisible())

    def test_real_client_to_game_rebinding_applies_even_when_game_process_is_unchanged(self):
        from automatic_windows import AutomaticWindowPolicy
        from screen_capture import WindowInfo
        from session_windows import ProcessMetadata
        w = self.window
        game = WindowInfo(123, 456, 'Owned game', 'RiotWindowClass')
        client = WindowInfo(789, 987, 'Owned client', 'Chrome_WidgetWin_1')
        metadata = {456: ProcessMetadata(r'C:\Owned\Game\League of Legends.exe', 100),
                    987: ProcessMetadata(r'C:\Owned\LeagueClient\LeagueClientUx.exe', 90)}
        visible = [game]
        policy = AutomaticWindowPolicy(resolver=lambda pid: metadata[pid], verifier=lambda path: True)
        w.automatic_policy = policy
        w.capture = SimpleNamespace(windows=lambda **kwargs: list(visible), retire_session=lambda: None)
        w.apply_discovery(policy.discover(visible), w.discovery_scope)
        self.deliver(self.bank())
        old = w.hero_matcher
        visible[:] = [client]
        w.apply_discovery(policy.discover(visible), w.discovery_scope)
        self.assertEqual(w.target, client)
        self.deliver(self.bank((140, 90, 130)))
        pending = w._pending_portraits[3]
        generation = w.state.generation
        w.apply_discovery(policy.discover(visible), w.discovery_scope)
        self.assertIs(w.hero_matcher, old)
        self.assertEqual(w.state.generation, generation)
        # The observed binding role changes back to this exact game process;
        # no timer or assumption about a new match grants the boundary.
        visible[:] = [game]
        w.apply_discovery(policy.discover(visible), w.discovery_scope)
        self.assertEqual(w.target, game)
        self.assertIs(w.hero_matcher, pending)
        self.assertIsNone(w._pending_portraits)
        self.assertGreater(w.state.generation, generation)
        self.assertFalse(w.state.confirmed)
        self.assertFalse(w.state.hero)

    def test_empty_and_stale_callbacks_cannot_replace_pending_viable_bank(self):
        w = self.window
        self.install_then_defer()
        pending = w._pending_portraits
        self.deliver({}, 'unavailable')
        w.task_result('portraits', (self.bank(), {'message': 'stale'}), w._portraits_attempt - 1)
        self.assertIs(w._pending_portraits, pending)
        w.stop_monitor()
        self.assertIs(w.hero_matcher, pending[3])

    def roster_value(self):
        return (tuple(('Owned'+str(i), str(i)) for i in range(1, 101)),
                {'state': 'verified-roster', 'version': '16.20.1',
                 'rosterSha256': 'a'*64, 'count': 100})

    def test_roster_signal_is_usable_before_slow_images_and_survives_failure(self):
        import hero_portraits
        w = self.window
        w.data['metadata']['isDemo'] = False
        entered, release = threading.Event(), threading.Event()
        self._release_events.append(release)
        value = self.roster_value()
        def load(*args, **kwargs):
            kwargs['roster_callback'](*value)
            entered.set()
            if not release.wait(3):
                raise RuntimeError('Owned image gate timed out')
            return {}, {'state': 'unavailable', 'message': 'Owned image failure'}
        with patch.object(hero_portraits, 'load_portraits', side_effect=load):
            w.request_portraits()
            self.wait(lambda: entered.is_set() and bool(w._verified_roster_map))
            self.assertTrue(w._portraits_busy)
            self.assertIsNone(w.hero_matcher)
            outcomes = []
            self.assertEqual(w.canonical_champion_map(diagnostic_callback=outcomes.append), dict(value[0]))
            self.assertEqual(outcomes, ['verified_roster'])
            self.assertFalse(w.state.hero)
            self.assertFalse(w.state.confirmed)
            release.set()
            self.wait(lambda: not w._portraits_busy and not w._workers)
        self.assertEqual(w.canonical_champion_map(), dict(value[0]))
        self.assertIsNone(w.hero_matcher)

    def test_roster_map_is_detached_and_bank_status_cannot_erase_it(self):
        w = self.window
        w._portraits_attempt = 1
        w._portraits_busy = True
        value = self.roster_value()
        w.task_result('portraits-roster', value, 1)
        value[1]['version'] = '99.99.99'
        self.assertEqual(w._verified_roster_source, ('16.20.1', 'a'*64))
        mapping = w.canonical_champion_map()
        mapping.clear()
        self.assertEqual(len(w.canonical_champion_map()), 100)
        for state in ('cached', 'current', 'fresh', 'memory-only'):
            self.deliver(self.bank(), state)
            self.assertEqual(w.canonical_champion_map(), dict(value[0]))

    def test_stale_terminal_cancelled_and_malformed_rosters_are_ignored(self):
        w = self.window
        w._portraits_attempt = 2
        w._portraits_busy = True
        value = self.roster_value()
        w.task_result('portraits-roster', value, 1)
        self.assertEqual(w.canonical_champion_map(), {})
        w._portraits_completed_attempt = 2
        w.task_result('portraits-roster', value, 2)
        self.assertEqual(w.canonical_champion_map(), {})
        w._portraits_completed_attempt = None
        w._cancel_workers.set()
        w.task_result('portraits-roster', value, 2)
        w._cancel_workers.clear()
        self.assertEqual(w.canonical_champion_map(), {})
        bad = [None, (value[0][:-1], value[1]), (value[0], {}),
               (value[0], dict(value[1], rosterSha256='bad')),
               ((('Owned0', '0'),)+value[0][1:], value[1]),
               ((value[0][0],)*100, value[1]),
               (list(value[0]), value[1])]
        for malformed in bad:
            with self.subTest(value=malformed):
                w.task_result('portraits-roster', malformed, 2)
                self.assertEqual(w.canonical_champion_map(), {})

    def test_diagnostics_distinguish_unchanged_deferred_and_installed_banks(self):
        w = self.window
        with patch.object(w.debug_log, 'record', wraps=w.debug_log.record) as record:
            self.deliver(self.bank())
            self.deliver(self.bank())
            self.deliver(self.bank((140, 90, 130)))
            w.stop_monitor()
        outcomes = [call.kwargs['template_outcome'] for call in record.call_args_list
                    if call.args == ('templates',) and 'template_outcome' in call.kwargs]
        self.assertEqual(outcomes, ['ready', 'unchanged', 'deferred', 'ready'])


class PortraitRefreshDiagnosticPrivacyTests(unittest.TestCase):
    def test_fixed_refresh_codes_are_private_and_rotation_remains_bounded(self):
        import json
        from pathlib import Path
        import tempfile
        import zipfile
        from local_debug import FILE_COUNT, LocalDebugLog
        from live_client_identity import MAP_OUTCOMES
        self.assertIn('verified_roster', MAP_OUTCOMES)
        secret = 'PRIVATE_PLAYER_TOKEN_LOCAL_PATH'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = LocalDebugLog(root/'logs', version='test', max_bytes=4096)
            log.set_enabled(True)
            codes = ('roster_ready', 'unchanged', 'deferred')
            for code in codes:
                log.record('templates', template_outcome=code, generation=1,
                           roster=secret, path=secret, rawChampionName=secret)
            log.record('identity', map_outcome='verified_roster', payload=secret)
            archive = log.export_zip(root/'exports', config={})
            with zipfile.ZipFile(archive) as exported:
                text = exported.read('events.jsonl').decode()
                self.assertNotIn(secret, text)
                rows = [json.loads(line) for line in text.splitlines()]
                self.assertEqual([row['template_outcome'] for row in rows if 'template_outcome' in row], list(codes))
                self.assertTrue(any(row.get('map_outcome') == 'verified_roster' for row in rows))
            for serial in range(400):
                log.record('templates', template_outcome=codes[serial % len(codes)],
                           generation=serial, roster=secret)
            self.assertLessEqual(sum(path.stat().st_size for path in (root/'logs').iterdir()),
                                 FILE_COUNT*4096)
            archive = log.export_zip(root/'exports', config={})
            with zipfile.ZipFile(archive) as exported:
                for name in exported.namelist():
                    self.assertNotIn(secret.encode(), exported.read(name))


@unittest.skipUnless(animated.QtWidgets is not None and animated.OCR_AVAILABLE,
                     'Optional Qt/local OCR dependencies are not installed')
class PortraitRefreshLiveFrameTests(unittest.TestCase):
    setUpClass = classmethod(animated.AnimatedAugmentRoundTests.setUpClass.__func__)
    setUp = animated.AnimatedAugmentRoundTests.setUp
    wait = animated.AnimatedAugmentRoundTests.wait
    dispose_window = animated.AnimatedAugmentRoundTests.dispose_window
    record_result = animated.AnimatedAugmentRoundTests.record_result
    record_error = animated.AnimatedAugmentRoundTests.record_error
    start_frame = animated.AnimatedAugmentRoundTests.start_frame
    finish_frame = animated.AnimatedAugmentRoundTests.finish_frame
    observe = animated.AnimatedAugmentRoundTests.observe
    assert_confirmed = animated.AnimatedAugmentRoundTests.assert_confirmed

    def exercise_inflight_refresh(self, changed):
        w = self.window
        w.hero_matcher = None
        w._portraits_attempt = 1
        w._portraits_busy = True
        w.task_result('portraits-cache', (self.scene.bank, {'state': 'cached', 'message': 'Owned cache'}), 1)
        self.observe((0, 1, 2), 0)
        self.observe((0, 1, 2), 1)
        self.assert_confirmed((0, 1, 2))
        w.capture.can_request_visible_overlay = True
        w.capture.visible_capture_status = 'eligible'
        w.capture.prepare_capture_mode = lambda visible: True
        ready, release = threading.Event(), threading.Event()
        self.releases.append(release)
        w.ocr.next_gate = (ready, release)
        old, token, generation = w.hero_matcher, w.hero_matcher.proof_identity(), w.state.generation
        previous = len(self.results)
        self.start_frame((0, 1, 2), 2)
        self.wait(lambda: ready.is_set() and not w.capture_pending)
        self.assertTrue(w.overlay.isVisible())
        with patch.object(w.overlay, 'hide', wraps=w.overlay.hide) as hide:
            for index in range(3):
                bank = {key: image.copy() for key, image in self.scene.bank.items()}
                if changed:
                    first = bank[next(iter(bank))]
                    first.putpixel((first.width // 2, first.height // 2), (index, 255, 0))
                w._portraits_attempt = index + 2
                w._portraits_busy = True
                w.task_result('portraits', (bank, {'state': 'fresh', 'message': 'Owned refresh'}), index + 2)
                self.assertIs(w.hero_matcher, old)
                self.assertEqual(w.hero_matcher.proof_identity(), token)
            release.set()
            self.finish_frame(previous)
            self.assert_confirmed((0, 1, 2))
            self.assertEqual(w.state.generation, generation)
            hide.assert_not_called()
        if changed:
            pending = w._pending_portraits[3]
            old_scope = self.results[-1]['_frameScope']
            w.stop_monitor()
            self.assertIs(w.hero_matcher, pending)
            self.assertFalse(w.partial_scope_current(old_scope))
            self.assertFalse(w.state.confirmed)
        else:
            self.assertIsNone(w._pending_portraits)

    def test_repeated_identical_copies_do_not_interrupt_live_ocr_or_display(self):
        self.exercise_inflight_refresh(False)

    def test_repeated_real_changes_defer_without_interrupting_live_ocr_or_display(self):
        self.exercise_inflight_refresh(True)

    def first_bank_during_api_display(self, *, expire=False):
        w = self.window
        w.hero_matcher = None
        w.automatic_policy = SimpleNamespace(bound=SimpleNamespace(role='game', metadata=None), stop=lambda: None)
        api = {'championId': '9001', 'confident': True, 'method': 'game-client-api'}
        reader = patch('live_client_identity.read_current_identity', return_value=api)
        read = reader.start()
        self.addCleanup(reader.stop)
        self.observe((0, 1, 2), 0)
        self.observe((0, 1, 2), 1)
        self.assert_confirmed((0, 1, 2))
        self.assertIsNone(w.hero_matcher)
        w.capture.can_request_visible_overlay = True
        w.capture.visible_capture_status = 'eligible'
        w.capture.prepare_capture_mode = lambda visible: True
        ready, release = threading.Event(), threading.Event()
        self.releases.append(release)
        w.ocr.next_gate = (ready, release)
        previous = len(self.results)
        generation = w.state.generation
        self.start_frame((0, 1, 2), 2)
        self.wait(lambda: ready.is_set() and not w.capture_pending)
        w._portraits_attempt = 1
        w._portraits_busy = True
        with patch.object(w.overlay, 'hide', wraps=w.overlay.hide) as hide:
            w.task_result('portraits', (self.scene.bank, {'state': 'fresh', 'message': 'First owned bank'}), 1)
            self.assertIsNone(w.hero_matcher)
            self.assertIsNotNone(w._pending_portraits)
            self.assertIsNone(w._portraits_retry_at)
            if expire:
                self.now += 4.01
                w.check_target()
                self.assertFalse(w.overlay.isVisible())
                self.assertIsNone(w.hero_matcher)
            release.set()
            if expire:
                self.wait(lambda: len(self.results) > previous and not w.ocr_busy and not w._workers)
            else:
                self.finish_frame(previous)
                self.assert_confirmed((0, 1, 2))
                self.assertEqual(w.state.generation, generation)
                hide.assert_not_called()
        read.return_value = None
        if not expire:
            # Keep the same three cards. API failure plus templates_unavailable
            # cannot borrow portrait/death continuity and must revoke identity.
            self.observe((0, 1, 2), 3)
        self.assertFalse(w.state.confirmed)
        self.assertFalse(w.overlay.isVisible())
        self.observe((0, 1, 2), 4)
        self.assertIsNotNone(w.hero_matcher)
        self.assertIsNone(w._pending_portraits)
        self.assertFalse(w.state.confirmed)
        self.observe((0, 1, 2), 5)
        self.assert_confirmed((0, 1, 2))

    def test_first_bank_preserves_api_display_then_recovers_after_api_unavailable(self):
        self.first_bank_during_api_display()

    def test_first_bank_becomes_usable_after_slow_frame_expiry_without_restart(self):
        self.first_bank_during_api_display(expire=True)

    def test_first_bank_waits_for_first_unconfirmed_api_frame_to_drain(self):
        w = self.window
        w.hero_matcher = None
        w.automatic_policy = SimpleNamespace(bound=SimpleNamespace(role='game', metadata=None), stop=lambda: None)
        api = {'championId': '9001', 'confident': True, 'method': 'game-client-api'}
        with patch('live_client_identity.read_current_identity', return_value=api) as read:
            ready, release = threading.Event(), threading.Event()
            self.releases.append(release)
            w.ocr.next_gate = (ready, release)
            generation = w.state.generation
            self.start_frame((0, 1, 2), 0)
            self.wait(lambda: ready.is_set() and not w.capture_pending)
            self.assertFalse(w.portrait_display_authority())
            w._portraits_attempt = 1
            w._portraits_busy = True
            w.task_result('portraits', (self.scene.bank, {'state': 'fresh', 'message': 'First owned bank'}), 1)
            self.assertIsNone(w.hero_matcher)
            self.assertIsNotNone(w._pending_portraits)
            self.assertEqual(w.state.generation, generation)
            release.set()
            self.finish_frame(0)
            self.assertEqual(w.state.hero_stable_frames, 1)
            self.assertEqual(w.state.automatic_frames, 1)
            self.assertFalse(w.state.confirmed)
            generation = w.state.generation
            read.return_value = None
            self.observe((0, 1, 2), 1)
            self.assertIsNotNone(w.hero_matcher)
            self.assertGreater(w.state.generation, generation)
            self.assertFalse(w.state.confirmed)
            self.observe((0, 1, 2), 2)
            self.assert_confirmed((0, 1, 2))

    def test_idle_first_bank_does_not_borrow_unconfirmed_api_frame_counters(self):
        w = self.window
        w.hero_matcher = None
        w.automatic_policy = SimpleNamespace(bound=SimpleNamespace(role='game', metadata=None), stop=lambda: None)
        api = {'championId': '9001', 'confident': True, 'method': 'game-client-api'}
        with patch('live_client_identity.read_current_identity', return_value=api) as read:
            self.observe((0, 1, 2), 0)
            self.assertFalse(w.portrait_display_authority())
            self.assertEqual(w.state.hero_stable_frames, 1)
            self.assertEqual(w.state.automatic_frames, 1)
            w._portraits_attempt = 1
            w._portraits_busy = True
            w.task_result('portraits', (self.scene.bank, {'state': 'fresh', 'message': 'First owned bank'}), 1)
            self.assertIsNotNone(w.hero_matcher)
            self.assertIsNone(w._pending_portraits)
            self.assertEqual(w.state.hero_stable_frames, 0)
            self.assertEqual(w.state.automatic_frames, 0)
            read.return_value = None
            self.observe((0, 1, 2), 1)
            self.assertFalse(w.state.confirmed)
            self.observe((0, 1, 2), 2)
            self.assert_confirmed((0, 1, 2))


if __name__ == '__main__':
    unittest.main()

import json
from pathlib import Path
import tempfile
import unittest

from tests import test_native_capture_worker as fixtures
from tests.test_local_offline import bundle


@unittest.skipIf(fixtures.QtWidgets is None, 'Qt unavailable')
class NativeOfflineUITests(unittest.TestCase):
    setUpClass = classmethod(fixtures.NativeCaptureWorkerTests.setUpClass.__func__)
    setUp = fixtures.NativeCaptureWorkerTests.setUp
    wait = fixtures.NativeCaptureWorkerTests.wait
    dispose_window = fixtures.NativeCaptureWorkerTests.dispose_window

    def test_auto_item_set_export_and_local_badge_data(self):
        from card_badges import TierBadge
        from local_offline import local_cards
        window = self.window
        data = bundle()['data']
        window.data = data
        window.state.running = True
        window.state.hero = '英雄'
        with tempfile.TemporaryDirectory() as folder:
            window.monitor_preferences['item_set_dir'] = folder
            window.auto_item_sets_toggle.setChecked(True)
            window.maybe_auto_export_item_sets()
            path = Path(folder) / '!!!vga-aram-0.json'
            self.assertTrue(path.is_file(), (window.hero_status.text(), window._item_set_signature))
            config = json.loads(path.read_text(encoding='utf-8'))
            self.assertEqual(config['championKey'], 'Hero')
            self.assertEqual(config['blocks'][0]['items'], [1001])
        card = local_cards(data, '英雄', ['甲'])[0]
        badge = TierBadge(None)
        try:
            badge.set_card(card)
            self.assertEqual(badge.tier, 'S')
            self.assertEqual(badge.source, '本地热度')
            self.assertIn('热度', badge.hint)
        finally:
            badge.deleteLater()


if __name__ == '__main__':
    unittest.main()

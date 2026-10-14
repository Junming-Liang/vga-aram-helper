"""Real Qt presentation checks using original data; not Windows capture proof."""
import gc
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
try:
    from PySide6 import QtCore, QtWidgets, QtTest
    from shiboken6 import isValid
except ImportError:
    QtWidgets = None


@unittest.skipIf(QtWidgets is None, 'Optional Qt runtime is not installed')
class NativeDesignTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        from engine import load_data
        from native_ui import ControlWindow
        from screen_capture import CaptureUnavailable
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        with patch('native_ui.Win32Capture', side_effect=CaptureUnavailable('Owned design fixture')):
            self.window = ControlWindow(
                lambda: {'data': load_data(Path(__file__).resolve().parents[1] / 'fixtures/demo.json')},
                state_dir=Path(self.directory.name), current_executable=Path('/unused.exe'),
                current_version='0.4.6', frozen=False, enable_updates=False)
        self.addCleanup(self.dispose)
        self.pump(lambda: self.window.data is not None)
        self.window.watchdog.stop(); self.window.monitor.stop()

    def pump(self, predicate=lambda: True):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            self.app.processEvents()
            if predicate():
                return
            time.sleep(.005)
        self.fail('Owned Qt fixture did not settle')

    def dispose(self):
        window = self.window
        overlay = window.overlay
        window.capture = None
        window.close()
        self.pump(lambda: not window._workers)
        overlay.deleteLater(); window.deleteLater()
        QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
        self.app.processEvents()
        self.assertFalse(isValid(window)); self.assertFalse(isValid(overlay))
        self.window = None
        gc.collect(); self.app.processEvents()

    def test_defaults_keep_auto_and_collapsed_advanced_without_hiding_trust(self):
        w = self.window
        self.assertTrue(w.hero_auto.isChecked())
        self.assertTrue(w.client_follow.isChecked())
        self.assertFalse(w.advanced_toggle.isChecked())
        self.assertFalse(w.advanced_panel.isVisible())
        self.assertFalse(w.hero_box.isEnabled())
        self.assertIn('尚未验证', w.compatibility.text())
        self.assertFalse(w.advanced_panel.isAncestorOf(w.trust_button))
        self.assertFalse(w.advanced_panel.isAncestorOf(w.cache_diagnostic_button))
        self.assertEqual([s.value() for s in w.roi], [15,25,70,35])
        self.assertEqual([e.accessibleName() for e in w.inputs], ['左侧候选','中间候选','右侧候选'])

    def test_manual_recovery_expands_the_actual_existing_hero_control(self):
        w = self.window
        w.hero_auto.setChecked(False)
        self.assertTrue(w.advanced_panel.isVisible())
        self.assertTrue(w.hero_box.isEnabled())
        w.advanced_toggle.setChecked(False)
        w.hero_box.setCurrentText(next(iter(w.data['heroes'])))
        self.assertTrue(w.advanced_toggle.isChecked())
        self.assertEqual(w.state.hero, w.hero_box.currentText())

    def test_badge_uses_state_not_arbitrary_success_or_error_words(self):
        w = self.window
        w.capture = object()
        w.status.setText('成功 已确认 失败 error ready')
        w.refresh_status_badge()
        self.assertEqual(w.status_chip.text(), '未开始')
        w.state.running = True
        w.refresh_status_badge()
        self.assertEqual(w.status_chip.text(), '等待连接')
        w.ocr_busy = True
        w.refresh_status_badge()
        self.assertEqual(w.status_chip.text(), '正在识别')
        w.ocr_busy = False
        w.state.confirmed = True
        w.refresh_status_badge()
        self.assertEqual(w.status_chip.property('state'), 'confirmed')

    def test_control_frame_and_fixed_actions_fit_actual_work_area(self):
        w = self.window
        w.fit_control_to_screen(); self.app.processEvents()
        self.assertTrue(w.screen().availableGeometry().contains(w.frameGeometry()),
                        (w.screen().availableGeometry(), w.frameGeometry()))
        for widget in (w.start_button, w.stop_button, w.toggle_button, w.status):
            bounds = QtCore.QRect(widget.mapTo(w, QtCore.QPoint()), widget.size())
            self.assertTrue(w.rect().contains(bounds), (widget.objectName(), bounds, w.rect()))
            self.assertTrue(widget.isVisibleTo(w))
        self.assertLessEqual(w.width(), 720)
        self.assertLessEqual(w.height(), 680)

    def test_candidate_keyboard_order_and_long_status_do_not_change_state(self):
        w = self.window
        w.inputs[0].setFocus(); self.app.processEvents()
        QtTest.QTest.keyClick(w.inputs[0], QtCore.Qt.Key.Key_Tab)
        self.assertIs(self.app.focusWidget(), w.inputs[1])
        QtTest.QTest.keyClick(w.inputs[1], QtCore.Qt.Key.Key_Tab)
        self.assertIs(self.app.focusWidget(), w.inputs[2])
        before = w.state.generation
        w.status.setText('窗口身份变化，已隐藏旧资料；请恢复游戏前台，等待两个独立画面重新核验。' * 2)
        self.app.processEvents()
        self.assertLessEqual(w.status.heightForWidth(w.status.width()), w.status.height()+1)
        self.assertEqual(w.state.generation, before)

    def test_overlay_remains_bounded_ordered_and_readable_at_three_budgets(self):
        from native_state import display_cards
        from native_smoke import inspect_smoke_layout
        from screen_capture import ClientRect
        w = self.window; hero = next(iter(w.data['heroes']))
        names = list(w.data['augments'])[:3]
        cards = display_cards(w.data, hero, names)
        cards[2]['sourceTier'] = None
        overlay = w.overlay
        overlay.set_cards(hero, cards, '2026-10-14', '数据包 演示 / 游戏资料 演示', '高置信自动识别')
        for scale in (1,1.5,2):
            with self.subTest(scale=scale):
                overlay.hide()
                x,y,width,height = overlay._fit_layout(ClientRect(-960,0,960,600), scale)
                self.assertGreaterEqual(x, -960); self.assertGreaterEqual(y, 0)
                self.assertLessEqual(x+width, 0); self.assertLessEqual(y+height, 600)
                self.assertLessEqual(overlay.width(), 820)
                overlay.show(); self.app.processEvents()
                inspect_smoke_layout(overlay)
                self.assertEqual([c['name'] for c in overlay.cards], names)
                self.assertIn('暂无评级', overlay.tier_labels[2].text())
                self.assertIn('来源日期', overlay.metadata_label.text())
                self.assertLessEqual(height, 300)
                self.assertIn('非 Riot', overlay.footer.text())
                self.assertTrue(overlay.click_through)
        self.assertTrue(overlay._compact)

    def test_dictionary_details_do_not_retain_current_hero_after_foreground_loss(self):
        from screen_capture import ClientRect, WindowInfo
        w = self.window
        before=(w.state.generation,w.state.confirmed,w.ocr_busy,w.capture_pending,w.overlay.isVisible())
        w.details_toggle.setChecked(True)
        self.assertEqual((w.state.generation,w.state.confirmed,w.ocr_busy,w.capture_pending,w.overlay.isVisible()),before)
        self.assertIn('名称未精确匹配', w.card_details.text())
        hero = next(iter(w.data['heroes'])); names = list(w.data['augments'])[:3]
        for edit,name in zip(w.inputs,names):edit.setText(name)
        w.state.start((1,1,'owned')); w.state.hero = hero
        w.state.confirm(names, w.data['augments']); w.refresh_card_details()
        self.assertIn('不代表识别或确认', w.card_details.text())
        for name in names:
            self.assertIn(name, w.card_details.text())
            self.assertIn(w.data['augments'][name]['description'], w.card_details.text())
        self.assertNotIn(hero, w.card_details.text())
        w.inputs[0].setText(names[0]+'未匹配');w.refresh_card_details()
        self.assertIn('1 · 名称未精确匹配词典',w.card_details.text())
        w.inputs[0].setText(names[0]);w.refresh_card_details()
        rect=ClientRect(0,0,1920,1080)
        class Capture:
            def rect(inner,target):return rect
            def foreground(inner,target):return False
        w.capture=Capture();w.target=WindowInfo(1,1,'owned','owned');w.target_allowed=lambda:True
        w.last_rect=rect;w.last_observation=time.monotonic();w.was_target_foreground=True
        w.check_target()
        self.assertFalse(w.state.confirmed);self.assertEqual(w.state.hero,'')
        self.assertFalse(w.overlay.isVisible())
        self.assertIn('不代表识别或确认',w.card_details.text())
        self.assertIn('未选择人工英雄',w.card_details.text())
        self.assertNotIn(hero,w.card_details.text())
        w.hero_auto.setChecked(False);w.hero_box.setCurrentText(hero);w.refresh_card_details()
        self.assertIn('人工选择英雄：'+hero,w.card_details.text())
        self.assertIn('虚构源评级（演示）：',w.card_details.text())
        self.assertFalse(w.state.confirmed)

    def test_dense_compact_keeps_full_long_fixture_text_at_250_percent_budget(self):
        from native_state import display_cards
        from native_smoke import inspect_smoke_layout
        from screen_capture import ClientRect
        w = self.window; hero = '星火术士（演示）'
        names = ['星火共鸣（演示）','晶盾回路（演示）','风步微光（演示）']
        cards = display_cards(w.data, hero, names)
        for card in cards:
            card['description'] = '原创合成布局测试说明。'*10
            card['notes'] = ['原创条件说明：需要人工根据游戏机制判断。'*3]
        overlay=w.overlay
        overlay.set_cards(hero,cards,'虚构日期','虚构版本','来自本局选人 · HUD未复核')
        _,_,_,height=overlay._fit_layout(ClientRect(0,0,964,602),2.5)
        overlay.show();self.app.processEvents();inspect_smoke_layout(overlay)
        # Installed font metrics may allow the ordinary compact branch; the
        # contract is full readable content within the same physical budget.
        self.assertLessEqual(height,301)
        self.assertIn('HUD未复核',overlay.heading.text())
        self.assertEqual([label.text() for label in overlay.tier_labels],
                         ['虚构源评级（演示）：T1','虚构源评级（演示）：T2','虚构源评级（演示）：T3'])

    def test_over_half_client_height_is_suppressed_without_clipping(self):
        from screen_capture import ClientRect, CaptureUnavailable
        overlay = self.window.overlay
        cards = [{'slot': i, 'name': '完整超长标题'*12, 'sourceTier': None,
                  'sourceTierLabel': '虎牙公开源评级', 'description':'完整描述',
                  'notes': []} for i in (1,2,3)]
        overlay.set_cards('未知英雄', cards)
        with self.assertRaisesRegex(CaptureUnavailable, '半屏高度'):
            overlay._fit_layout(ClientRect(0,0,960,600),2)
        self.assertFalse(overlay.isVisible())

    def test_long_chinese_names_and_unknown_ratings_are_not_elided(self):
        from native_smoke import inspect_smoke_layout
        from screen_capture import ClientRect
        cards = [{'slot': i, 'name': '超长中文海克斯标题用来核验自动换行'+str(i),
                  'description': '完整效果说明。'*15, 'notes': ['只用于原创界面回归'],
                  'sourceTier': None, 'sourceTierLabel':'虎牙公开源评级'} for i in (1,2,3)]
        overlay = self.window.overlay
        overlay.set_cards('当前英雄待人工复核',cards,'未知','数据包 未知 / 游戏资料 未知','人工确认')
        overlay._fit_layout(ClientRect(0,0,1920,1080),2);overlay.show();self.app.processEvents()
        inspect_smoke_layout(overlay)
        for i,card in enumerate(cards):
            labels=overlay.row.itemAt(i).widget().findChildren(QtWidgets.QLabel)
            self.assertIn(card['name'], labels[0].text())
            self.assertIn('暂无评级', overlay.tier_labels[i].text())


if __name__ == '__main__':
    unittest.main()

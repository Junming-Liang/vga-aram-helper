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
                current_version='0.4.7', frozen=False, enable_updates=False)
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

    def test_real_window_titles_match_exact_current_ota_contract(self):
        from app_version import __version__
        from windows_ota_smoke import control_title_for_version, OVERLAY_TITLE, CONTROL_TITLE
        self.assertEqual(self.window.windowTitle(), control_title_for_version(__version__))
        self.assertEqual(self.window.overlay.windowTitle(), OVERLAY_TITLE)
        self.assertEqual(CONTROL_TITLE, 'VGA乱斗助手 · 原生控制台')

    def test_installation_confirmation_obeys_explicit_minimize_preference(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        w=self.window
        self.assertFalse(w.minimize_on_start.isChecked())
        policy=SimpleNamespace(confirm_installation=Mock(return_value=True))
        candidate=SimpleNamespace(window=SimpleNamespace(title='Owned fixture'),metadata=SimpleNamespace(path='C:/Owned/Game/League of Legends.exe'))
        w.state.start((1,1,'owned'));w.automatic_policy=policy
        w.capture=SimpleNamespace(windows=lambda **kwargs:[])
        for enabled in (False,True):
            w.showNormal();w.minimize_on_start.setChecked(enabled);w.unverified_candidate=candidate
            with patch.object(QtWidgets.QMessageBox,'question',return_value=QtWidgets.QMessageBox.StandardButton.Yes),patch.object(w,'queue_discovery'):
                w.confirm_game_installation();self.app.processEvents()
            self.assertEqual(w.isMinimized(),enabled)
        w.automatic_policy=None

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
        for widget in (w.start_button, w.toggle_button, w.hero_title):
            bounds = QtCore.QRect(widget.mapTo(w, QtCore.QPoint()), widget.size())
            self.assertTrue(w.rect().contains(bounds), (widget.objectName(), bounds, w.rect()))
            self.assertTrue(widget.isVisibleTo(w))
        self.assertLessEqual(w.width(), 900)
        self.assertLessEqual(w.height(), 490)

    def test_candidate_keyboard_order_and_long_status_do_not_change_state(self):
        w = self.window
        w.show_page('correction');w.inputs[0].setFocus(); self.app.processEvents()
        QtTest.QTest.keyClick(w.inputs[0], QtCore.Qt.Key.Key_Tab)
        self.assertIs(self.app.focusWidget(), w.inputs[1])
        QtTest.QTest.keyClick(w.inputs[1], QtCore.Qt.Key.Key_Tab)
        self.assertIs(self.app.focusWidget(), w.inputs[2])
        before = w.state.generation
        w.status.setText('窗口身份变化，已隐藏旧资料；请恢复游戏前台，等待两个独立画面重新核验。' * 2)
        self.app.processEvents()
        self.assertLessEqual(w.status.heightForWidth(w.status.width()), w.status.height()+1)
        self.assertEqual(w.state.generation, before)

    def badge_fixture(self):
        from test_card_badges import fixture
        c,g,cards=fixture();overlay=self.window.overlay
        self.assertTrue(overlay.set_candidate_geometry(c,{'width':900,'height':600},(0,0,1,1),g))
        overlay.set_cards('原创英雄',cards)
        return overlay,c,g,cards

    def test_three_badges_have_fixed_size_grade_source_and_accessible_identity(self):
        from native_smoke import inspect_smoke_layout
        from screen_capture import ClientRect
        overlay,c,g,cards=self.badge_fixture()
        overlay.show_at(ClientRect(-960,0,960,600),None);self.app.processEvents()
        inspect_smoke_layout(overlay)
        self.assertEqual(overlay.mask().rectCount(),3)
        self.assertFalse(overlay.panel.isVisibleTo(overlay))
        self.assertEqual([b.tier for b in overlay._badge_widgets],['T1','T2','T3'])
        self.assertTrue(overlay.click_through)
        for card,badge in zip(cards,overlay._badge_widgets):
            from badge_contract import MIN_WIDTH,WIDTH,HEIGHT
            self.assertTrue(MIN_WIDTH<=badge.width()<=WIDTH);self.assertEqual(badge.height(),HEIGHT)
            self.assertIn(card['name'],badge.accessibleName())
            self.assertEqual(badge.findChildren(QtWidgets.QLabel),[])

    def test_source_hint_fits_visible_badge_and_retains_full_accessible_text(self):
        from native_smoke import inspect_smoke_layout
        from screen_capture import ClientRect
        overlay,c,g,cards=self.badge_fixture()
        cards[0]['sourceHint']='搭配：原创超长强化名称甲、原创超长强化名称乙'
        overlay.set_cards('原创英雄',cards);overlay.show_at(ClientRect(0,0,900,600),None);self.app.processEvents()
        inspect_smoke_layout(overlay)
        badge=overlay._badge_widgets[0]
        self.assertIn(cards[0]['sourceHint'],badge.accessibleName())
        self.assertEqual(badge.toolTip(),cards[0]['sourceHint'])
        self.assertTrue(badge.display_hint)
        self.assertFalse(overlay._badge_widgets[1].hint)

    def test_badges_keep_original_slots_and_hide_unknown_middle(self):
        from native_smoke import inspect_smoke_layout
        from screen_capture import ClientRect
        overlay,c,g,cards=self.badge_fixture();rect=ClientRect(0,0,900,600)
        overlay.show_at(rect,None);self.app.processEvents();right=overlay._badge_widgets[2].pos()
        cards[1]['pending']=True;cards[1]['name']='待识别';cards[1]['sourceTier']=None
        overlay.set_cards('原创英雄',cards);overlay.show_at(rect,None);self.app.processEvents()
        inspect_smoke_layout(overlay)
        self.assertEqual(overlay.mask().rectCount(),2)
        self.assertFalse(overlay._badge_widgets[1].isVisibleTo(overlay))
        self.assertEqual(overlay._badge_widgets[2].pos(),right)
        self.assertEqual(overlay._badge_widgets[2].tier,'T3')

    def test_long_names_remain_accessible_and_unknown_rating_is_explicit(self):
        from native_smoke import inspect_smoke_layout
        from screen_capture import ClientRect
        overlay,c,g,cards=self.badge_fixture()
        for card,candidate in zip(cards,c):
            card['name']='超长中文海克斯标题用来核验完整无省略'+str(card['slot']);candidate['name']=card['name'];card['sourceTier']=None
        overlay.set_candidate_geometry(c,{'width':900,'height':600},(0,0,1,1),g)
        overlay.set_cards('原创英雄',cards);overlay.show_at(ClientRect(0,0,900,600),None);self.app.processEvents()
        inspect_smoke_layout(overlay)
        for card,badge in zip(cards,overlay._badge_widgets):
            self.assertIn(card['name'],badge.accessibleName());self.assertEqual(badge.tier,'暂无评级')

    def test_badge_diagnostic_rejects_size_tier_source_and_identity_corruption(self):
        from native_smoke import inspect_smoke_layout
        from screen_capture import ClientRect
        overlay,c,g,cards=self.badge_fixture();overlay.show_at(ClientRect(0,0,900,600),None);self.app.processEvents()
        badge=overlay._badge_widgets[0]
        for field,bad in (('tier','T4'),('source',''),('accessibleName','T1')):
            original=badge.accessibleName() if field=='accessibleName' else getattr(badge,field)
            if field=='accessibleName':badge.setAccessibleName(bad)
            else:setattr(badge,field,bad)
            with self.subTest(field=field),self.assertRaises(AssertionError):inspect_smoke_layout(overlay)
            if field=='accessibleName':badge.setAccessibleName(original)
            else:setattr(badge,field,original)
        badge.setFixedSize(1,1)
        with self.assertRaises(AssertionError):inspect_smoke_layout(overlay)

    def test_badges_require_geometry_and_top_space_at_all_dpi_budgets(self):
        from card_badges import badge_placement,BadgeAnchors
        from screen_capture import ClientRect,CaptureUnavailable
        overlay,c,g,cards=self.badge_fixture()
        for dpr in (1,1.25,1.5,2,2.5):
            bounds,regions=badge_placement(ClientRect(-1800,-1200,1800,1200),dpr,overlay._badge_anchors,(0,1,2))
            self.assertEqual(len(regions),3)
            from badge_contract import GAP
            for slot,(x,y,w,h) in enumerate(regions):
                self.assertLessEqual(bounds[1]+y+h,-1200+overlay._badge_anchors.rects[slot][1]*1200-GAP*dpr)
            with self.assertRaises(CaptureUnavailable):badge_placement(ClientRect(0,0,320,180),dpr,overlay._badge_anchors,(0,1,2))
        overlay.clear_candidate_geometry();overlay.show_at(ClientRect(0,0,900,600),None)
        self.assertFalse(overlay.isVisible())

    def test_identical_payload_and_paint_only_tier_changes_reuse_placement(self):
        import copy
        from screen_capture import ClientRect
        overlay,c,g,cards=self.badge_fixture();overlay.show_at(ClientRect(0,0,900,600),None)
        badges=tuple(overlay._badge_widgets);revision=overlay._layout_revision
        overlay.set_cards('原创英雄',copy.deepcopy(cards))
        self.assertEqual(tuple(overlay._badge_widgets),badges);self.assertEqual(overlay._layout_revision,revision)
        overlay.set_rechecking(True);overlay.set_cards('原创英雄',copy.deepcopy(cards));self.assertFalse(overlay._rechecking)
        cards[0]['sourceTier']='T4';overlay.set_cards('原创英雄',cards)
        self.assertEqual(overlay._layout_revision,revision);self.assertTrue(overlay.isVisible())
        self.assertEqual(overlay._badge_widgets[0].tier,'T4')
        cards[0]['name']='different-card';overlay.set_cards('原创英雄',cards)
        self.assertGreater(overlay._layout_revision,revision);self.assertFalse(overlay.isVisible())

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

    def test_startup_failure_is_immediately_visible_on_main_without_guessing_text(self):
        w=self.window;w.data=None;w.startup_error=''
        w.task_error('load','Original fixture data error',0)
        self.assertEqual(w.pages.currentIndex(),0);self.assertFalse(w.start_button.isEnabled())
        self.assertEqual(w.status_chip.property('state'),'error');self.assertIn('资料加载失败',w.status_chip.text())
        w.show_page('about');self.assertTrue(w.source.isVisibleTo(w));self.assertIn('Original fixture data error',w.source.text())

    def test_narrow_settings_controls_remain_reachable_inside_viewport(self):
        w=self.window;w.setMinimumSize(0,0);w.resize(368,336);w.show_page('settings');self.app.processEvents()
        for widget in (w.window_list,w.refresh,w.client_follow,w.hero_box,*w.roi):
            w.scroll.ensureWidgetVisible(widget);self.app.processEvents()
            bounds=QtCore.QRect(widget.mapTo(w.scroll.viewport(),QtCore.QPoint()),widget.size())
            self.assertTrue(w.scroll.viewport().rect().contains(bounds),(widget.accessibleName(),bounds,w.scroll.viewport().rect()))
        self.assertEqual(w.roi_layout.getItemPosition(w.roi_layout.indexOf(w.roi_fields[-1]))[:2],(1,1))

    def test_main_is_read_only_and_typed_names_never_become_live_cards(self):
        w=self.window
        self.assertEqual(w.pages.currentIndex(),0)
        self.assertFalse(any(edit.isVisibleTo(w) for edit in w.inputs))
        self.assertFalse(w.source.isVisibleTo(w));self.assertFalse(w.roi[0].isVisibleTo(w))
        for edit,name in zip(w.inputs,list(w.data['augments'])[:3]):edit.setText(name)
        w.refresh_status_badge()
        self.assertEqual([v['name'].text() for v in w.candidate_views],['等待识别']*3)
        self.assertEqual([v['tier'].text() for v in w.candidate_views],['—']*3)
        self.assertFalse(w.state.confirmed)

    def test_main_confirmed_slots_are_literal_ordered_and_unknown_is_explicit(self):
        w=self.window;hero=next(iter(w.data['heroes']));names=list(w.data['augments'])[:3]
        w.data['heroAugmentStats'][hero][2]['tier']=None
        w.state.start((1,1,'owned'));w.state.hero=hero;w.state.confirm(names,w.data['augments']);w.refresh_status_badge()
        self.assertEqual([v['name'].text() for v in w.candidate_views],names)
        self.assertEqual([v['tier'].text() for v in w.candidate_views],['T1','T2','—'])
        self.assertIn('暂无评级',w.candidate_views[2]['detail'].text())
        self.assertIn('虚构源评级',w.candidate_views[0]['tier'].accessibleName())
        self.assertTrue(w.stop_button.isVisibleTo(w));self.assertTrue(w.stop_button.isEnabled())
        self.assertFalse(w.start_button.isVisibleTo(w))

    def test_main_clears_synchronously_on_stale_scene_edit_hero_change_and_stop(self):
        w=self.window;w.capture=object();hero=next(iter(w.data['heroes']));names=list(w.data['augments'])[:3]
        def confirmed():
            w.state.start((1,1,'owned'));w.state.hero=hero;w.state.confirm(names,w.data['augments']);w.refresh_status_badge()
            self.assertEqual(w.candidate_views[0]['name'].text(),names[0]);self.assertIn('资料已确认',w.status_chip.text())
        for change in (lambda:w.invalidate_scene('stale scene'),w.edit_changed,lambda:w.hero_changed(''),w.stop_monitor):
            confirmed();change()
            self.assertFalse(w.state.confirmed)
            self.assertNotIn('资料已确认',w.status_chip.text())
            self.assertNotEqual(w.status_chip.property('state'),'confirmed')
            self.assertEqual([v['name'].text() for v in w.candidate_views],['等待识别']*3)
            self.assertEqual([v['tier'].text() for v in w.candidate_views],['—']*3)
        self.assertEqual(w.hero_title.text(),'等待识别')

    def test_provisional_and_manual_identity_are_visible_in_main_provenance(self):
        w=self.window;w.capture=object();hero=next(iter(w.data['heroes']))
        w.state.start((1,1,'owned'));w.state.hero=hero;w.hero_origin='client-provisional';w.refresh_status_badge()
        self.assertIn('HUD未复核',w.status_chip.text());self.assertEqual(w.status_chip.property('state'),'provisional')
        w.hero_origin='client-verified';w.refresh_status_badge();self.assertIn('HUD复核',w.status_chip.text())
        w.hero_auto.blockSignals(True);w.hero_auto.setChecked(False);w.hero_auto.blockSignals(False);w.refresh_status_badge()
        self.assertIn('人工选择',w.status_chip.text());self.assertNotIn('连续确认',w.status_chip.text())

    def test_client_selection_handler_never_claims_hud_provenance(self):
        from screen_capture import WindowInfo
        from selection_session import SelectionSession
        w=self.window;hero=next(iter(w.data['heroes']));w.data['heroes'][hero]['championId']='9001'
        w.capture=object();w.target=WindowInfo(1,10,'owned client','Chrome_WidgetWin_1');w.state.start(w.target.identity)
        w.selection_session=SelectionSession();w.selection_session.start(w.target.identity)
        # Handler/presentation-only owned fixture; no OS authorization claim.
        w.target_allowed=lambda:True;w.captured_frame_current=lambda value:True
        def deliver(captured_at,scene='assigned-selection'):
            # Distinct observations must not depend on host clock resolution or
            # scheduler timing. Keep the real freshness and duplicate guards.
            value=dict(scene=scene,assigned=scene=='assigned-selection',championId='9001',_capturedAt=captured_at,_sessionGeneration=w.selection_session.generation,_windowIdentity=w.target.identity)
            with patch('native_ui.time.monotonic',return_value=captured_at+.01),patch.object(w,'check_target'):
                w.task_result('selection',value,w.state.generation)
        deliver(100.);self.assertEqual(w.hero_title.text(),'等待识别')
        self.assertEqual(w.selection_session.candidate_frames,1)
        deliver(100.);self.assertEqual(w.state.hero,'');self.assertEqual(w.hero_title.text(),'等待识别')
        self.assertEqual(w.selection_session.candidate_frames,1);self.assertEqual(w.selection_session.assigned,'')
        self.assertFalse(w.state.confirmed);self.assertNotIn('HUD 连续确认',w.status_chip.text())
        deliver(101.);self.assertEqual(w.state.hero,hero);self.assertEqual(w.hero_title.text(),hero)
        self.assertEqual(w.selection_session.candidate_frames,2)
        self.assertIn('仍可交换',w.status_chip.text());self.assertIn('HUD未复核',w.status_chip.text());self.assertNotIn('HUD 连续确认',w.status_chip.text())
        self.assertEqual(w.status_chip.property('state'),'provisional');self.assertFalse(w.state.confirmed)
        self.assertEqual([v['name'].text() for v in w.candidate_views],['等待识别']*3)
        deliver(102.,'unknown');self.assertEqual(w.hero_title.text(),'等待识别');self.assertNotIn('HUD 连续确认',w.status_chip.text())

    def test_client_hero_strength_is_separate_fresh_canonical_reference(self):
        from native_ui import ControlWindow
        from screen_capture import WindowInfo,ClientRect
        from selection_session import SelectionSession
        w=self.window;hero=next(iter(w.data['heroes']));w.data['heroes'][hero].update(championId='9001',overallTier='T5')
        w.target=WindowInfo(1,10,'owned client','Chrome_WidgetWin_1');w.state.start(w.target.identity)
        session=SelectionSession();session.start(w.target.identity);w.selection_session=session
        for stamp in (100.,101.):session.observe_client({'scene':'assigned-selection','assigned':True,'championId':'9001'},w.target.identity,stamp,stamp+.01,generation=session.generation)
        w.state.hero=hero;rect=ClientRect(10,10,1280,720)
        class Capture:
            def rect(inner,target):return rect
            def foreground(inner,target):return True
        w.capture=Capture();w.target_allowed=lambda:True
        with patch('native_ui.time.monotonic',return_value=101.1):
            reference=w.client_strength_reference();self.assertEqual(reference['sourceTier'],'T5')
            ControlWindow.check_target(w);w.refresh_status_badge()
            self.assertTrue(w.overlay.isVisible());self.assertEqual(w.overlay.cards,[]);self.assertFalse(w.state.confirmed);self.assertEqual(w.state.offered,())
            self.assertIn('HUD未复核',w.overlay.heading.text());self.assertIn('仍可交换',w.overlay.heading.text())
            self.assertIn('T5',w.hero_caption.text());self.assertIn('T5',w.overlay.tier_labels[0].text());self.assertIn('虚构',w.overlay.footer.text())
            session.assigned='9002';self.assertIsNone(w.client_strength_reference());ControlWindow.check_target(w);self.assertFalse(w.overlay.isVisible())
            session.assigned='9001';w.state.hero='';self.assertIsNone(w.client_strength_reference())
            w.state.hero=hero
        with patch('native_ui.time.monotonic',return_value=105.1):
            self.assertIsNone(w.client_strength_reference());ControlWindow.check_target(w);self.assertFalse(w.overlay.isVisible())
        w.stop_monitor();self.assertIsNone(w.client_strength_reference())

    def test_client_reference_never_reconstructs_revoked_identity_from_session(self):
        from native_ui import ControlWindow
        from screen_capture import WindowInfo,ClientRect
        from selection_session import SelectionSession
        w=self.window;hero=next(iter(w.data['heroes']));w.data['heroes'][hero].update(championId='9001',overallTier='T5')
        w.target=WindowInfo(1,10,'owned client','Chrome_WidgetWin_1');rect=ClientRect(10,10,1280,720)
        proof={'foreground':True,'allowed':True,'rect':rect}
        class Capture:
            def rect(inner,target):return proof['rect']
            def foreground(inner,target):return proof['foreground']
        w.capture=Capture();w.target_allowed=lambda:proof['allowed']
        def assign():
            w.state.start(w.target.identity);session=SelectionSession();session.start(w.target.identity);w.selection_session=session
            for stamp in (100.,101.):session.observe_client({'scene':'assigned-selection','assigned':True,'championId':'9001'},w.target.identity,stamp,stamp+.01,generation=session.generation)
            w.state.hero=hero;w.last_rect=rect;w.was_target_foreground=True
            proof.update(foreground=True,allowed=True,rect=rect)
            ControlWindow.check_target(w);self.assertTrue(w.overlay.isVisible());self.assertFalse(w.state.confirmed)
        with patch('native_ui.time.monotonic',return_value=101.1):
            assign();w.invalidate_scene('Owned inference revoked the observation')
            self.assertEqual(w.selection_session.assigned,'9001');self.assertFalse(w.state.hero)
            ControlWindow.check_target(w);self.assertIsNone(w.client_strength_reference());self.assertFalse(w.overlay.isVisible())
            for reason in ('permission','focus','resize'):
                with self.subTest(reason=reason):
                    assign()
                    if reason=='permission':proof['allowed']=False
                    elif reason=='focus':proof['foreground']=False
                    else:proof['rect']=ClientRect(10,10,1200,720)
                    ControlWindow.check_target(w)
                    self.assertFalse(w.overlay.isVisible());self.assertFalse(w.state.hero);self.assertFalse(w.state.confirmed)
                    self.assertIsNone(w.client_strength_reference())
                    self.assertEqual([v['name'].text() for v in w.candidate_views],['等待识别']*3)

    def test_history_keeps_one_literal_snapshot_without_reviving_live_or_selected_state(self):
        w=self.window;hero=next(iter(w.data['heroes']));names=list(w.data['augments'])[:3]
        w.state.start((1,10,'owned'));w.state.hero=hero
        for edit,name in zip(w.inputs,names):edit.setText(name)
        w.confirm();record=w.last_candidates;self.assertIsNotNone(record)
        self.assertEqual([card['name'] for card in record['cards']],names)
        old_text=w.history_view.text();w.invalidate_scene('owned choice cards disappeared')
        self.assertFalse(w.state.confirmed);self.assertEqual(w.state.offered,());self.assertFalse(w.overlay.isVisible())
        self.assertEqual([view['name'].text() for view in w.candidate_views],['等待识别']*3)
        self.assertIn('上次候选 · 最终选择未知',w.history_view.text())
        for name in names:self.assertIn(name,w.history_view.text())
        original=record['cards'][0]['sourceTier'];w.data['heroAugmentStats'][hero][0]['tier']='T4';w.refresh_history()
        self.assertEqual(record['cards'][0]['sourceTier'],original)
        generation=w.state.generation;w.show_page('correction');self.assertEqual(w.state.generation,generation);self.assertFalse(w.state.confirmed)
        w.stop_monitor();self.assertIsNone(w.last_candidates);self.assertIn('尚无本次监测记录',w.history_view.text())

    def test_history_clears_on_new_target_or_verified_hero(self):
        from screen_capture import WindowInfo
        w=self.window;heroes=list(w.data['heroes']);names=list(w.data['augments'])[:3]
        def record():
            w.state.start((1,10,'owned'));w.state.hero=heroes[0]
            for edit,name in zip(w.inputs,names):edit.setText(name)
            w.confirm();self.assertIsNotNone(w.last_candidates)
        record();w.target=WindowInfo(2,20,'new owned','owned');w.refresh_history();self.assertIsNone(w.last_candidates)
        w.target=None;record();w.state.hero=heroes[1];w.refresh_history();self.assertIsNone(w.last_candidates)

    def test_secondary_navigation_preserves_state_and_keeps_stop_reachable(self):
        w=self.window;hero=next(iter(w.data['heroes']));names=list(w.data['augments'])[:3]
        w.state.start((1,1,'owned'));w.state.hero=hero;w.state.confirm(names,w.data['augments']);w.refresh_status_badge()
        before=(w.state.generation,w.state.confirmed,w.state.offered,w.ocr_busy,w.capture_pending,w.overlay.isVisible())
        for page in ('settings','correction','about','main'):
            w.show_page(page);self.app.processEvents()
            self.assertEqual((w.state.generation,w.state.confirmed,w.state.offered,w.ocr_busy,w.capture_pending,w.overlay.isVisible()),before)
            action=w.stop_button if page=='main' else w.secondary_stop
            self.assertTrue(action.isVisibleTo(w));self.assertTrue(action.isEnabled())
        w.show_page('about');QtTest.QTest.mouseClick(w.secondary_stop,QtCore.Qt.MouseButton.LeftButton)
        self.assertFalse(w.state.running);self.assertFalse(w.state.confirmed)
        self.assertEqual([v['name'].text() for v in w.candidate_views],['等待识别']*3)

    def test_selection_diagnostic_snapshot_is_bounded_read_only_metadata(self):
        from selection_session import SelectionSession
        from selection_smoke import diagnostic_state
        import json
        w=self.window;w.state.start((1,10,'owned'));w.state.hero='示例'*100
        w.selection_session=SelectionSession();session=w.selection_session
        session.start((1,10,'owned'));session.candidate='9001';session.candidate_frames=1
        session.stage='assigning';session.last_client_frame=101.;session.reason='r'*1000
        w.status.setText('s'*1000)
        before=(w.state.generation,w.state.hero,w.state.confirmed,session.generation,session.candidate_frames)
        value=diagnostic_state(w,100.,now=102.)
        self.assertEqual(value['elapsed_seconds'],2.)
        self.assertEqual(value['session']['last_client_frame_age_seconds'],1.)
        self.assertEqual(value['session']['candidate_frames'],1)
        self.assertEqual(value['session']['stage'],'assigning')
        self.assertEqual(len(value['hero']),80);self.assertEqual(len(value['status']),400)
        self.assertEqual(len(value['session']['reason']),240)
        self.assertLess(len(json.dumps(value).encode()),4000)
        self.assertEqual(before,(w.state.generation,w.state.hero,w.state.confirmed,session.generation,session.candidate_frames))
        self.assertFalse(set(value)&{'image','screenshot','ocr_lines','window_title','path'})

    def test_accessible_switches_keep_real_checkbox_keyboard_and_single_signal(self):
        w=self.window
        self.assertIsInstance(w.hero_auto,QtWidgets.QCheckBox)
        self.assertIsInstance(w.toggle_button,QtWidgets.QCheckBox)
        w.hero_auto.setFocus();QtTest.QTest.keyClick(w.hero_auto,QtCore.Qt.Key.Key_Tab)
        self.assertIs(self.app.focusWidget(),w.toggle_button);self.assertTrue(w.toggle_button.keyboard_focus_visible())
        with patch.object(w.state,'clear_hero',wraps=w.state.clear_hero) as clear:
            w.hero_auto.setFocus();QtTest.QTest.keyClick(w.hero_auto,QtCore.Qt.Key.Key_Space)
            self.assertFalse(w.hero_auto.isChecked());self.assertEqual(clear.call_count,1)
        w.show_page('main');w.toggle_button.setFocus();before=w.overlay.click_through
        QtTest.QTest.keyClick(w.toggle_button,QtCore.Qt.Key.Key_Space)
        self.assertEqual(w.toggle_button.isChecked(),not before)
        self.assertEqual(w.overlay.click_through,not before)
        w.toggle_clickthrough();self.assertEqual(w.toggle_button.isChecked(),before)



if __name__ == '__main__':
    unittest.main()

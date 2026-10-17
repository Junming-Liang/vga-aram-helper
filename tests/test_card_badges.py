"""Owned badge geometry/Qt lifecycle contracts; Windows-only native proof is separate."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from types import SimpleNamespace
import unittest
try:
    from PySide6 import QtCore,QtWidgets
    from card_badges import BadgeAnchors,accepted_anchors,badge_placement,WIDTH,HEIGHT,GAP
    from badge_contract import choose_width,align_physical_regions,top_gap
except ImportError:
    QtWidgets=None
from screen_capture import ClientRect,CaptureUnavailable


def fixture():
    candidates=[dict(name=f'候选{i+1}',box=[[90+i*270,230],[180+i*270,230],[180+i*270,260],[90+i*270,260]]) for i in range(3)]
    geometry=SimpleNamespace(rects=((.05,.3,.25,.6),(.35,.3,.25,.6),(.65,.3,.25,.6)),size=(900,600),space='frame')
    cards=[dict(slot=i+1,name=f'候选{i+1}',sourceTier=f'T{i+1}',sourceTierLabel='虎牙公开源评级') for i in range(3)]
    return candidates,geometry,cards


@unittest.skipIf(QtWidgets is None,'Optional Qt runtime is not installed')
class BadgeGeometryTests(unittest.TestCase):
    def test_canonical_logical_hull_inverts_fractional_projection_without_double_ceil(self):
        import math
        from badge_contract import logical_hull_from_physical
        self.assertEqual(logical_hull_from_physical(779,65,1.25),(623,52))
        for dpr in (.5,.75,1,1.25,1.5,1.75,2,2.5,3,4):
            for logical_width in range(104,1600):
                physical=math.ceil(logical_width*dpr)
                recovered=logical_hull_from_physical(physical,math.ceil(52*dpr),dpr)
                self.assertEqual(math.ceil(recovered[0]*dpr),physical)
                self.assertGreaterEqual(recovered[0],logical_width)

    def test_fractional_native_hull_preserves_last_logical_child(self):
        bounds,regions=align_physical_regions(((0,0,302,104),(307,0,302,104),(615,0,302,104)),2,151)
        self.assertEqual(bounds,(0,0,918,104))
        self.assertEqual(regions,((0,0,302,104),(308,0,302,104),(616,0,302,104)))
        self.assertEqual(round(regions[-1][0]/2)+151,bounds[2]/2)
    def test_fractional_regions_and_children_fit_hull_for_every_width(self):
        import math
        for dpr in (1,1.25,1.5,1.75,2,2.5):
            for width in range(104,161):
                bw=math.ceil(width*dpr);bh=math.ceil(HEIGHT*dpr)
                for offset in range(bw+2,bw+12):
                    physical=((0,0,bw,bh),(offset,0,bw,bh),(2*offset+1,0,bw,bh))
                    bounds,regions=align_physical_regions(physical,dpr,width)
                    for x,y,w,h in regions:
                        self.assertLessEqual(x+w,bounds[2]);self.assertLessEqual(y+h,bounds[3])
                        self.assertLessEqual(round(x/dpr)+width,round(bounds[2]/dpr))
    def test_subunity_scale_keeps_physical_border_clearance(self):
        c,g,_=fixture();a=accepted_anchors(c,{'width':900,'height':600},(0,0,1,1),g)
        bounds,regions=badge_placement(ClientRect(0,0,900,600),.5,a,(0,1,2))
        self.assertEqual(top_gap(.5),8)
        self.assertGreaterEqual(.3*600-(bounds[1]+regions[0][1]+regions[0][3]),8)
    def test_card_edges_and_title_names_bind_slots(self):
        c,g,_=fixture();a=accepted_anchors(c,{'width':900,'height':600},(0,0,1,1),g)
        self.assertEqual(a.names,('候选1','候选2','候选3'));self.assertEqual(a.rects,g.rects)
        self.assertIsNone(accepted_anchors(c,{'width':900,'height':600},(0,0,1,1),None))
        c[1]['box']=c[0]['box'];a=accepted_anchors(c,{'width':900,'height':600},(0,0,1,1),g)
        self.assertEqual(a.names,(None,None,'候选3'))
    def test_full_frame_geometry_maps_crop_ocr_boxes(self):
        c,g,_=fixture();roi=(.05,.1,.9,.8)
        for item in c:item['box']=[[(x-45)/.9,(y-60)/.8] for x,y in item['box']]
        a=accepted_anchors(c,{'width':900,'height':600},roi,g)
        self.assertEqual(a.names,('候选1','候选2','候选3'));self.assertEqual(a.rects,g.rects)
    def test_dpi_origins_gap_and_physical_bounds(self):
        c,g,_=fixture();a=accepted_anchors(c,{'width':900,'height':600},(0,0,1,1),g)
        for dpr in (1,1.25,1.5,2,2.5):
            for x,y in ((0,0),(-1800,-1200),(300,-1200)):
                rect=ClientRect(x,y,1800,1200);bounds,regions=badge_placement(rect,dpr,a,(0,1,2))
                self.assertEqual(len(regions),3)
                for slot,(bx,by,bw,bh) in enumerate(regions):
                    self.assertEqual((bw,bh),(int(WIDTH*dpr+.999),int(HEIGHT*dpr+.999)))
                    self.assertAlmostEqual(bounds[0]+bx+bw/2,x+(a.rects[slot][0]+.125)*1800,delta=.5)
                    self.assertGreaterEqual(y+.3*1200-(bounds[1]+by+bh),GAP*dpr)
    def test_missing_top_space_fails_closed_not_clamped_onto_card(self):
        a=BadgeAnchors(('a','b','c'),((.05,.01,.25,.6),(.35,.01,.25,.6),(.65,.01,.25,.6)))
        with self.assertRaises(CaptureUnavailable):badge_placement(ClientRect(0,0,900,600),2,a,(0,1,2))


@unittest.skipIf(QtWidgets is None,'Optional Qt runtime is not installed')
class BadgeQtTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    def setUp(self):
        from native_ui import Overlay
        self.o=Overlay();self.c,self.g,self.cards=fixture()
        self.o.set_candidate_geometry(self.c,{'width':900,'height':600},(0,0,1,1),self.g)
        self.o.set_cards('英雄',self.cards);self.addCleanup(self.o.close)
    def show(self):self.o.show_at(ClientRect(0,0,900,600),None);self.app.processEvents()
    def test_three_disjoint_regions_not_a_joined_strip(self):
        self.show();self.assertTrue(self.o.isVisible());self.assertEqual(self.o.mask().rectCount(),3)
        self.assertFalse(self.o.panel.isVisible())
        self.assertTrue(all(b.isVisible() for b in self.o._badge_widgets))
        gap=(self.o._badge_widgets[0].x()+self.o._badge_widgets[0].width()+self.o._badge_widgets[1].x())//2
        self.assertFalse(self.o.mask().contains(QtCore.QPoint(gap,18)))
        width=choose_width((157.5,427.5,697.5),self.o.devicePixelRatioF())
        self.assertEqual([b.size().toTuple() for b in self.o._badge_widgets],[(width,HEIGHT)]*3)
        self.assertEqual([b.tier for b in self.o._badge_widgets],['T1','T2','T3'])
    def test_visible_capture_sentinel_uses_actual_badges_not_hidden_panel(self):
        from wgc_visible_overlay_smoke import install_badge_sentinels, badge_sentinel_observation
        self.show();hwnd=int(self.o.winId());mask=self.o.mask()
        patches=install_badge_sentinels(self.o);self.app.processEvents()
        proof=badge_sentinel_observation(self.o)
        self.assertEqual(len(patches),3);self.assertGreater(sum(proof['badge_magenta_grid_samples']),20)
        image=self.o.grab().toImage()
        count=sum(image.pixelColor(x,y).getRgb()==(255,0,255,255)
                  for x in range(0,image.width(),8) for y in range(0,image.height(),8))
        self.assertGreater(count,20)
        self.assertEqual(int(self.o.winId()),hwnd);self.assertEqual(self.o.mask(),mask)
        self.assertFalse(self.o.panel.isVisible())
        for patch,badge in zip(patches,self.o._badge_widgets):
            self.assertIs(patch.parentWidget(),badge);self.assertFalse(patch.isWindow())
            self.assertFalse(patch.testAttribute(QtCore.Qt.WidgetAttribute.WA_NativeWindow))
            self.assertTrue(badge.rect().contains(patch.geometry()))
        self.o.set_rechecking(True);self.o.hide();self.o.show();self.app.processEvents()
        self.assertGreater(sum(badge_sentinel_observation(self.o)['badge_magenta_grid_samples']),20)
        self.assertEqual(int(self.o.winId()),hwnd);self.assertEqual(self.o.mask(),mask)

    def test_identity_warning_is_visible_and_survives_candidate_rechecking(self):
        from PySide6 import QtGui
        for confirmation,marker in [('来自本局选人 · HUD未复核','HUD未复核'),
                ('本局此前确认英雄 + 本帧候选；头像未重新确认','本局已确认')]:
            self.cards[2]['sourceTier']=None
            self.o.set_cards('英雄',self.cards,confirmation=confirmation);self.show()
            for badge in self.o._badge_widgets:
                self.assertTrue(badge.isVisible());self.assertEqual(badge.source,marker)
                self.assertIn(confirmation,badge.accessibleName());self.assertIn(confirmation,badge.toolTip())
                badge.setFixedWidth(104)
                font,source_rect,tier_font,tier_rect,tier_lines=badge.top_text_layout()
                self.assertGreaterEqual(font.pixelSize(),9)
                self.assertLessEqual(QtGui.QFontMetrics(font).horizontalAdvance(badge.display_source),source_rect.width())
                self.assertLessEqual(tier_rect.right()+4,source_rect.left())
                self.assertTrue(badge.rect().contains(source_rect))
                for line in tier_lines:self.assertLessEqual(QtGui.QFontMetrics(tier_font).horizontalAdvance(line),tier_rect.width())
            self.o.set_rechecking(True);self.app.processEvents()
            for badge in self.o._badge_widgets:
                self.assertEqual(badge.source,marker);self.assertTrue(badge.display_hint.startswith('复核中'))
                self.assertIn('候选复核中',badge.accessibleName());self.assertIn(confirmation,badge.toolTip())

    def test_observed_windows_54px_warning_uses_measured_space_without_shrinking(self):
        from unittest.mock import patch
        from card_badges import TierBadge
        badge=TierBadge(None);self.addCleanup(badge.close);badge.setFixedWidth(104)
        badge.set_card(dict(slot=1,name='候选',sourceTier='T1'),identity_provenance='来自本局选人 · HUD未复核')
        class Metrics:
            def __init__(self,font):pass
            def horizontalAdvance(self,text):return 54 if text=='HUD未复核' else 30
        with patch('card_badges.QtGui.QFontMetrics',Metrics):
            font,source_rect,_,tier_rect,_=badge.top_text_layout()
        self.assertEqual(font.pixelSize(),9);self.assertEqual(source_rect.width(),54)
        self.assertEqual(source_rect.x(),46);self.assertLessEqual(tier_rect.right()+4,source_rect.left())
        self.assertTrue(badge.rect().contains(source_rect))

    def test_observed_box_font_metrics_choose_compact_warning_and_restore_full_on_resize(self):
        from unittest.mock import patch
        from card_badges import TierBadge
        badge=TierBadge(None);self.addCleanup(badge.close);badge.setFixedWidth(104)
        badge.set_card(dict(slot=1,name='候选',sourceTier='T1'),identity_provenance='来自本局选人 · HUD未复核')
        accessible=badge.accessibleName()
        class Metrics:
            def __init__(self,font):pass
            def horizontalAdvance(self,text):return {'HUD未复核':54,'HUD待核':45,'T1':40}[text]
        with patch('card_badges.QtGui.QFontMetrics',Metrics):
            font,rect,_,tier_rect,_=badge.top_text_layout()
        self.assertEqual(badge.display_source,'HUD待核');self.assertEqual(font.pixelSize(),9)
        self.assertLessEqual(tier_rect.right()+4,rect.left())
        self.assertEqual(badge.source,'HUD未复核');self.assertEqual(badge.accessibleName(),accessible)
        badge.setFixedWidth(160)
        with patch('card_badges.QtGui.QFontMetrics',Metrics):badge.top_text_layout()
        self.assertEqual(badge.display_source,'HUD未复核');self.assertEqual(badge.accessibleName(),accessible)

    def test_all_painted_top_labels_fit_supported_font_fallbacks(self):
        from card_badges import TierBadge
        from PySide6 import QtGui
        badge=TierBadge(None);self.addCleanup(badge.close);badge.setFixedWidth(104)
        for family in ('Segoe UI','Microsoft YaHei UI','Microsoft YaHei','Noto Sans CJK SC'):
            badge.setFont(QtGui.QFont(family))
            for tier in ('T1','T2','T3','T4',None):
                for source in ('源评级','演示评级','复核中','HUD未复核','本局已确认'):
                    badge.set_card(dict(slot=1,name='候选',sourceTier=tier));badge.source=source
                    font,source_rect,tier_font,tier_rect,lines=badge.top_text_layout()
                    with self.subTest(family=family,tier=tier,source=source):
                        self.assertGreaterEqual(font.pixelSize(),9)
                        self.assertTrue(badge.rect().contains(source_rect))
                        self.assertLessEqual(tier_rect.right()+4,source_rect.left())
                        self.assertLessEqual(QtGui.QFontMetrics(tier_font).height(),32//len(lines))
                        self.assertLessEqual(QtGui.QFontMetrics(font).height(),source_rect.height())
                        # Some dummy font engines expose a100000 origin in
                        # boundingRect. Prove actual unclipped paint ink instead.
                        image=QtGui.QImage(180,80,QtGui.QImage.Format.Format_ARGB32);image.fill(0)
                        painter=QtGui.QPainter(image);painter.setFont(font);painter.setPen(QtGui.QColor('white'))
                        painted=source_rect.translated(20,20)
                        painter.drawText(painted,QtCore.Qt.AlignmentFlag.AlignVCenter|QtCore.Qt.TextFlag.TextDontClip,badge.display_source);painter.end()
                        ink=[(x,y) for x in range(image.width()) for y in range(image.height()) if image.pixelColor(x,y).alpha()]
                        self.assertTrue(ink)
                        self.assertTrue(all(painted.contains(QtCore.QPoint(x,y)) for x,y in ink))
                        badge.hint='搭配：无限循环往复、纯粹主义者 - 术师';badge._pending_identity=True;badge._fit_hint()
                        hint_font,hint_rect=badge.hint_text_layout();metrics=QtGui.QFontMetrics(hint_font)
                        self.assertEqual(hint_font.pixelSize(),11);self.assertEqual(hint_font.weight(),QtGui.QFont.Weight.Normal)
                        self.assertTrue(badge.rect().contains(hint_rect))
                        self.assertLessEqual(metrics.horizontalAdvance(badge.display_hint),hint_rect.width())
                        self.assertLessEqual(metrics.height(),hint_rect.height())
                        self.assertGreaterEqual(hint_rect.top(),16+max(QtGui.QFontMetrics(font).height(),QtGui.QFontMetrics(tier_font).height())/2)


    def test_missing_tier_still_paints_provenance_at_minimum_width(self):
        from card_badges import TierBadge
        badge=TierBadge(None);self.addCleanup(badge.close);badge.setFixedWidth(104)
        badge.set_card(dict(slot=1,name='未知评级候选',sourceTier=None),identity_provenance='来自本局选人 · HUD未复核')
        self.assertEqual(badge.top_text_layout()[-1],('暂无',))
        self.assertIn('暂无评级',badge.accessibleName())
        badge.show();self.app.processEvents()
        before=badge.grab().toImage();badge.source='';badge.update();self.app.processEvents()
        after=badge.grab().toImage();dpr=before.devicePixelRatio()
        changed=sum(before.pixelColor(x,y)!=after.pixelColor(x,y)
                    for x in range(round(50*dpr),round(100*dpr)) for y in range(round(32*dpr)))
        self.assertGreater(changed,0)

    def test_post_show_native_rounding_is_corrected_exactly_or_rejected(self):
        bounds=[79,145,780,65];calls=[]
        def read(hwnd,ptr):
            r=ptr._obj;r.left,r.top=bounds[:2];r.right=r.left+bounds[2];r.bottom=r.top+bounds[3];return True
        def position(hwnd,z,x,y,w,h,flags):
            calls.append((x,y,w,h));bounds[:]=[x,y,w,h];return True
        self.o.capture=SimpleNamespace(u=SimpleNamespace(GetWindowRect=read,SetWindowPos=position))
        self.o._ensure_badge_bounds((79,145,779,65))
        self.assertEqual(calls,[(79,145,779,65)]);self.assertEqual(bounds,[79,145,779,65])
        self.o._ensure_badge_bounds((79,145,779,65));self.assertEqual(len(calls),1)
        bounds[2]=780;self.o.capture.u.SetWindowPos=lambda *args:False
        with self.assertRaises(CaptureUnavailable):self.o._ensure_badge_bounds((79,145,779,65))
        self.o.capture.u.SetWindowPos=lambda *args:True
        with self.assertRaises(CaptureUnavailable):self.o._ensure_badge_bounds((79,145,779,65))
        self.o.capture=None

    def test_failed_post_show_bounds_proof_hides_cached_badges(self):
        from unittest.mock import patch
        self.show();self.assertTrue(self.o.isVisible())
        with patch.object(self.o,'_ensure_badge_bounds',side_effect=CaptureUnavailable('owned bounds mismatch')):
            with self.assertRaises(CaptureUnavailable):self.show()
        self.assertFalse(self.o.isVisible());self.assertIsNone(self.o._placed_key)

    def test_source_hint_elision_retains_exact_accessible_text(self):
        full='搭配：无限循环往复、纯粹主义者 - 术师'
        self.cards[0]['sourceHint']=full;self.o.set_cards('英雄',self.cards);self.show()
        badge=self.o._badge_widgets[0]
        self.assertEqual(badge.hint,full);self.assertEqual(badge.toolTip(),full)
        self.assertIn(full,badge.accessibleName());self.assertNotEqual(badge.display_hint,full)
        self.assertTrue(badge.display_hint.endswith('…'))
        self.assertEqual(self.o._badge_widgets[1].hint,'');self.assertEqual(self.o._badge_widgets[1].display_hint,'')
    def test_short_source_hint_is_shown_without_change(self):
        self.cards[0]['sourceHint']='搭配：甲';self.o.set_cards('英雄',self.cards);self.show()
        self.assertEqual(self.o._badge_widgets[0].display_hint,'搭配：甲')
    def test_unknown_middle_slot_never_reuses_old_grade(self):
        self.show();self.cards[1]['pending']=True;self.o.set_cards('英雄',self.cards);self.show()
        self.assertEqual(self.o.mask().rectCount(),2);self.assertFalse(self.o._badge_widgets[1].isVisible())
        self.assertEqual(self.o._badge_widgets[2].pos().x(),round(540/self.o.devicePixelRatioF()))
    def test_changed_name_without_matching_geometry_is_hidden(self):
        self.show();self.cards[0]['name']='新的候选';self.o.set_cards('英雄',self.cards);self.show()
        self.assertFalse(self.o._badge_widgets[0].isVisible());self.assertEqual(self.o.mask().rectCount(),2)
    def test_geometry_revocation_hides_immediately_and_cannot_restore(self):
        self.show();self.o.clear_candidate_geometry();self.assertFalse(self.o.isVisible());self.show();self.assertFalse(self.o.isVisible())
    def test_stop_hide_and_close_cover_all_regions(self):
        self.show();self.o.hide('stop');self.assertFalse(self.o.isVisible());self.assertFalse(any(b.isVisible() for b in self.o._badge_widgets))
        self.show();self.o.close();self.assertFalse(self.o.isVisible())
    def test_rechecking_changes_badge_without_geometry_recreation(self):
        self.show();key=self.o._placed_key;region=self.o.mask();self.o.set_rechecking(True)
        self.assertEqual(self.o._placed_key,key);self.assertEqual(self.o.mask(),region)
        self.assertTrue(all(b.source=='复核中' for b in self.o._badge_widgets))
    def test_fresh_cards_reset_rechecking_without_rebuilding(self):
        self.show();self.o.set_rechecking(True);self.o.set_cards('英雄',self.cards)
        self.assertFalse(self.o._rechecking)

if __name__=='__main__':unittest.main()

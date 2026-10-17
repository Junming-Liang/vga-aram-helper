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

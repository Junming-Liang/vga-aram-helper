"""Owned synthetic pixels: border geometry, NOT real-game detection accuracy.

Public still validation is scripts/validate_card_geometry_public.py and its
checked-in metadata-only report. No gameplay screenshot is bundled. The
existing auto-scene fixture is explicitly original synthetic artwork. A live
scene/occlusion guard remains mandatory even when these border tests pass.
"""
import hashlib
import io
from pathlib import Path
import sys
import unittest

from PIL import Image, ImageDraw
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from augment_card_geometry import detect_card_geometry, detect_frame_card_geometry, refresh_frame_card_geometry

ROOT = Path(__file__).resolve().parents[1]


def encoded(image):
    out = io.BytesIO()
    image.save(out, format='PNG')
    return out.getvalue()


def titles(scale=1, offset=(0,0)):
    return [{'name': name, 'box': [(round((x+dx)*scale),round((y+dy)*scale))
                                 for x,y in [(left,302),(left+120,302),(left+120,333),(left,333)]]}
            for left,name in zip((255,557,859), ('a','b','c'))
            for dx,dy in [offset]]


class CardGeometryTests(unittest.TestCase):
    def setUp(self):
        with Image.open(ROOT/'fixtures/auto-scene.png') as source:
            self.image = source.convert('RGB')

    def detect(self, image=None, candidates=None):
        image = self.image if image is None else image
        return detect_card_geometry(encoded(image), candidates or titles(),
                                    {'width': image.width, 'height': image.height})

    def test_actual_fixture_borders_not_title_boxes_or_thirds(self):
        g = self.detect()
        self.assertIsNotNone(g)
        for rect,left in zip(g.rects,(196,498,800)):
            x,y,w,h = rect
            self.assertAlmostEqual(x*1280,left,delta=3)
            self.assertAlmostEqual(y*720,176,delta=3)
            self.assertAlmostEqual(w*1280,268,delta=3)
            self.assertAlmostEqual(h*720,325,delta=3)
        self.assertEqual(g.frame_digest,hashlib.sha256(encoded(self.image)).hexdigest())

    def test_resolutions_and_dpi_physical_pixels(self):
        for scale in (.5,.75,1,1.25,1.5,2):
            with self.subTest(scale=scale):
                frame=self.image.resize((round(1280*scale),round(720*scale)), Image.Resampling.BILINEAR)
                g=self.detect(frame,titles(scale))
                self.assertIsNotNone(g)
                self.assertAlmostEqual(g.rects[0][0],196/1280,delta=.006)
                self.assertAlmostEqual(g.rects[0][1],176/720,delta=.006)

    def test_nonuniform_card_centers_are_measured_from_pixels(self):
        frame=Image.new('RGB', self.image.size, (24,42,62))
        candidates=titles()
        for i,(old,new) in enumerate(zip((196,498,800),(70,445,830))):
            frame.paste(self.image.crop((old,176,old+268,501)),(new,176))
            candidates[i]['box']=[(x+new-old,y) for x,y in candidates[i]['box']]
        g=self.detect(frame,candidates)
        self.assertIsNotNone(g)
        for rect,left in zip(g.rects,(70,445,830)):
            self.assertAlmostEqual(rect[0]*1280,left,delta=3)

    def test_unknown_name_still_needs_all_three_observed_boxes(self):
        candidates=titles();candidates[1]['name']=''
        self.assertIsNotNone(self.detect(candidates=candidates))
        self.assertIsNone(detect_card_geometry(encoded(self.image),candidates[:2],{'width':1280,'height':720}))

    def test_title_crop_clipped_card_top_rejected_full_frame_wrapper_works(self):
        crop=self.image.crop((192,180,1088,432))
        anchors=titles(offset=(-192,-180))
        self.assertIsNone(self.detect(crop,anchors))
        g=detect_frame_card_geometry(encoded(self.image),anchors,{'width':896,'height':252},(.15,.25,.7,.35))
        self.assertIsNotNone(g)
        self.assertEqual(g.space,'frame')
        self.assertEqual(g.rects,self.detect().rects)
        self.assertIsNone(detect_frame_card_geometry(encoded(self.image),anchors,{'width':895,'height':252},(.15,.25,.7,.35)))

    def test_titles_without_borders_never_invent_screen_thirds(self):
        flat=Image.new('RGB',self.image.size,(24,42,62))
        for c in titles():
            l,t=c['box'][0];r,b=c['box'][2]
            flat.paste(self.image.crop((l,t,r,b)),(l,t))
        self.assertIsNone(self.detect(flat))

    def test_missing_one_card_foreign_occlusion_fails_closed(self):
        for box in ((180,150,480,510),(190,220,210,410),(200,170,450,195),(200,480,450,510)):
            with self.subTest(box=box):
                image=self.image.copy();ImageDraw.Draw(image).rectangle(box,fill=(77,77,77))
                self.assertIsNone(self.detect(image))

    def test_ambiguous_nested_panel_rejected(self):
        image=self.image.copy()
        ImageDraw.Draw(image).rectangle((220,200,440,470),outline=(0,0,0),width=2)
        self.assertIsNone(self.detect(image))

    def test_reprove_dynamic_border_and_do_not_reuse_stale_position(self):
        g=self.detect()
        image=self.image.copy()
        ImageDraw.Draw(image).ellipse((300,360,320,380),fill=(90,170,240))
        self.assertTrue(g.matches(encoded(image)))
        self.assertTrue(g.matches(encoded(image),_decoded_rgb=image))
        # Animated border color alone is safe when the same edges remain clear.
        ImageDraw.Draw(image).line((208,176,450,176),fill=(230,80,150),width=1)
        self.assertTrue(g.matches(encoded(image)))
        ImageDraw.Draw(image).rectangle((192,230,202,420),fill=(24,42,62))
        self.assertFalse(g.matches(encoded(image)))
        self.assertFalse(g.matches(encoded(image),_decoded_rgb=image))
        moved=Image.new('RGB',self.image.size,(24,42,62));moved.paste(self.image,(0,14))
        self.assertFalse(g.matches(encoded(moved)))

    def test_thick_ornamental_outline_bundle_uses_outer_border(self):
        image=self.image.copy()
        draw=ImageDraw.Draw(image)
        for x in (196,498,800):
            draw.rounded_rectangle((x+14,190,x+253,486),radius=8,outline=(20,50,60),width=3)
        g=self.detect(image)
        self.assertIsNotNone(g)
        self.assertAlmostEqual(g.rects[0][1]*720,176,delta=3)
        # Losing one outer frame cannot silently become an inner-panel anchor.
        for x in (196,498,800):
            draw.rectangle((x-6,220,x+18,450),fill=(24,42,62))
        self.assertIsNone(self.detect(image))

    def test_fresh_strip_reproof_binds_current_frame_and_falls_back_safely(self):
        roi=(.15,.25,.7,.35);size={'width':896,'height':252}
        anchors=titles(offset=(-192,-180));data=encoded(self.image)
        g=detect_frame_card_geometry(data,anchors,size,roi)
        image=self.image.copy();ImageDraw.Draw(image).ellipse((300,360,320,380),fill=(90,170,240))
        changed=encoded(image)
        fresh=refresh_frame_card_geometry(changed,g,anchors,size,roi)
        self.assertEqual(fresh.rects,g.rects)
        self.assertEqual(fresh.frame_digest,hashlib.sha256(changed).hexdigest())
        self.assertNotEqual(fresh.frame_digest,g.frame_digest)
        decoded=refresh_frame_card_geometry(changed,g,anchors,size,roi,_decoded_rgb=image)
        self.assertEqual(decoded,fresh)
        self.assertTrue(g.matches(changed,_decoded_rgb=image))
        self.assertFalse(g.matches(changed,_decoded_rgb=image.resize((640,360))))
        self.assertFalse(g.matches(changed,_decoded_rgb=image.convert('L')))
        self.assertIsNone(refresh_frame_card_geometry(changed,g,anchors,size,roi,_decoded_rgb=image.resize((640,360))))
        ImageDraw.Draw(image).rectangle((190,230,210,420),fill=(24,42,62))
        self.assertFalse(g.matches(encoded(image)))
        self.assertIsNone(refresh_frame_card_geometry(encoded(image),g,anchors,size,roi))
        blank=Image.new('RGB',self.image.size,(24,42,62))
        self.assertFalse(g.matches(encoded(blank)))
        self.assertIsNone(refresh_frame_card_geometry(encoded(blank),g,anchors,size,roi))
        moved=Image.new('RGB',self.image.size,(24,42,62));moved.paste(self.image,(0,14))
        self.assertFalse(g.matches(encoded(moved)))
        fresh=refresh_frame_card_geometry(encoded(moved),g,titles(offset=(-192,-166)),size,roi)
        self.assertIsNotNone(fresh)
        self.assertNotEqual(fresh.rects,g.rects)

    def test_untrusted_coordinates_and_bytes_reject(self):
        for data in (b'',b'not png'):
            self.assertIsNone(detect_card_geometry(data,titles(),{'width':1280,'height':720}))
        for value in (float('nan'),float('inf'),True,-1,99999):
            candidates=titles();candidates[1]['box'][0]=(value,302)
            self.assertIsNone(self.detect(candidates=candidates))
        self.assertIsNone(self.detect(candidates=list(reversed(titles()))))

if __name__=='__main__':
    unittest.main()

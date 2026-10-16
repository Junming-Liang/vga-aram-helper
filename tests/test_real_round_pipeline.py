"""Actual local OCR + synthetic HUD through Qt across rounds.

These are original generated pixels and an owned fake capture, not game footage
or Windows capture compatibility. Artificial delay is explicit and bounded.
"""
import importlib.util
import time
import unittest
from pathlib import Path

from tests import test_native_capture_worker as fixtures
QtWidgets=fixtures.QtWidgets

@unittest.skipIf(QtWidgets is None or importlib.util.find_spec('rapidocr') is None,
                 'Optional Qt and real local OCR runtime required')
class RealRoundPipelineTests(unittest.TestCase):
    setUpClass=classmethod(fixtures.NativeCaptureWorkerTests.setUpClass.__func__)
    setUp=fixtures.NativeCaptureWorkerTests.setUp
    wait=fixtures.NativeCaptureWorkerTests.wait
    dispose_window=fixtures.NativeCaptureWorkerTests.dispose_window

    def test_three_real_ocr_rounds_reroll_empty_and_recovery(self):
        from PIL import ImageDraw,ImageFont
        from hero_recognition import PortraitMatcher
        from local_ocr import LocalOCR
        from native_ui import ControlWindow
        from screen_capture import ClientRect
        from synthetic_vision import portraits,frame,encoded
        font_path=next((p for p in (Path('C:/Windows/Fonts/arial.ttf'),
            Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')) if p.is_file()),None)
        if font_path is None:self.skipTest('Owned text fixture needs a readable system font')
        w=self.window;w.debug_log.set_enabled(True);hero=next(iter(w.data['heroes']));names=('Fire Power','Ice Shield','Wind Step','Moon Beam')
        w.data['augments']={name:{'description':'Original procedural test card'} for name in names}
        w.data['heroes'][hero]['championId']='9001'
        w.data['heroAugmentStats']={hero:[{'augmentName':name,'tier':'T2'} for name in names]}
        bank=portraits();w.hero_matcher=PortraitMatcher(bank,w.data['heroes'])
        font=ImageFont.truetype(str(font_path),26)
        def image(titles):
            picture=frame(bank['9001']);draw=ImageDraw.Draw(picture)
            for x,name in zip((340,640,940),titles):draw.text((x,300),name,font=font,fill=(255,255,255),anchor='mm')
            return encoded(picture)
        class Capture:
            current=image(names[:3]);calls=0
            def capture(inner,*args,**kwargs):
                inner.calls+=1;time.sleep(.03);return inner.current,ClientRect(0,0,1280,720)
            def foreground(inner,target):return True
            def rect(inner,target):return ClientRect(0,0,1280,720)
        class DelayedOCR:
            def __init__(inner):inner.engine=LocalOCR();inner.calls=0
            def recognize(inner,*args):
                inner.calls+=1;time.sleep(.08);return inner.engine.recognize(*args)
        capture=Capture();w.capture=capture;w.ocr=DelayedOCR()
        w.captured_frame_current=lambda value:ControlWindow.captured_frame_current(w,value)
        def tick(titles):
            self.assertFalse(w.ocr_busy);capture.current=image(titles)
            w.capture_hidden(w.state.generation);self.wait(lambda:not w.ocr_busy,seconds=8)
            self.assertFalse(w.frame_inference_worker._busy)
        for titles in (names[:3],(names[3],names[1],names[2]),(names[2],names[0],names[1])):
            tick(titles);self.assertFalse(w.state.confirmed)
            tick(titles);self.assertTrue(w.state.confirmed,w.status.text());self.assertEqual(w.state.offered,titles)
        tick(())
        self.assertFalse(w.state.confirmed);self.assertFalse(w.overlay.isVisible())
        tick(names[:3]);self.assertFalse(w.state.confirmed)
        tick(names[:3]);self.assertTrue(w.state.confirmed)
        self.assertEqual(capture.calls,9)
        self.assertEqual(w.ocr.calls,9)  # No cached inference promoted a new round.
        import json
        events=[json.loads(line) for line in w.debug_log._path().read_text().splitlines()]
        completed=[row for row in events if row['event']=='capture' and row.get('phase')=='completed']
        self.assertEqual(len(completed),9)
        self.assertTrue(all(all(key in row for key in ('prepare_ms','hud_ms','ocr_ms')) for row in completed))
        self.assertTrue(any('queue_ms' in row for row in events));self.assertTrue(any('dispatch_ms' in row for row in events))
        text=w.debug_log._path().read_text()
        for name in names:self.assertNotIn(name,text)


if __name__=='__main__':unittest.main()

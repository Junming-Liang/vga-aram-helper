"""Real local HUD/OCR on owned pixels; not live-game or native capture evidence."""
from types import SimpleNamespace
import unittest
from tests import test_animated_augment_rounds as fixture

@unittest.skipUnless(fixture.QtWidgets is not None and fixture.OCR_AVAILABLE,'Qt/OCR unavailable')
class DeathFrameContinuityTests(unittest.TestCase):
    setUpClass=classmethod(fixture.AnimatedAugmentRoundTests.setUpClass.__func__)
    setUp=fixture.AnimatedAugmentRoundTests.setUp
    wait=fixture.AnimatedAugmentRoundTests.wait
    dispose_window=fixture.AnimatedAugmentRoundTests.dispose_window
    record_result=fixture.AnimatedAugmentRoundTests.record_result
    record_error=fixture.AnimatedAugmentRoundTests.record_error
    start_frame=fixture.AnimatedAugmentRoundTests.start_frame
    finish_frame=fixture.AnimatedAugmentRoundTests.finish_frame
    observe=fixture.AnimatedAugmentRoundTests.observe
    assert_confirmed=fixture.AnimatedAugmentRoundTests.assert_confirmed

    def test_grayscale_death_frames_keep_game_hero_and_fresh_titles_without_cache_cycle(self):
        from session_windows import ProcessMetadata
        w=self.window
        metadata=ProcessMetadata('C:/Owned/Game/League of Legends.exe',1234)
        w.capture_metadata=lambda:metadata
        w.automatic_policy=SimpleNamespace(bound=SimpleNamespace(role='game',metadata=metadata),stop=lambda:None)
        self.observe((0,1,2),0);self.observe((0,1,2),1)
        self.assert_confirmed((0,1,2));seed=w.hero_continuity.verified_at
        # Opaque countdown-like central glyphs over the desaturated own HUD.
        # This is original diagnostic artwork, not a real client screenshot.
        self.scene=fixture.AnimatedOriginalScene()
        original_image=self.scene.image
        def countdown(*args,**kwargs):
            from PIL import ImageDraw
            image=original_image(*args,**kwargs)
            if kwargs.get('gray'):
                draw=ImageDraw.Draw(image);draw.rectangle((432,665,459,689),fill=(38,38,38))
                draw.text((440,671),'42',fill=(220,50,50))
            return image
        self.scene.image=countdown
        self.now+=300
        for phase in (2,3,3,3):
            result=self.observe((0,1,2),phase,gray=True)
            self.assertFalse(result['hero_observation']['confident'])
            self.assertFalse(result.get('ocr_reused',False))
            self.assertEqual(w.state.hero,fixture.HERO)
        self.assert_confirmed((0,1,2));self.assertEqual(w.hero_origin,'game-continuity')
        self.assertEqual(w.hero_continuity.verified_at,seed)
        # A death portrait plus a non-card scene cannot show retained choices.
        self.observe(None,4,gray=True)
        self.assertFalse(w.state.confirmed);self.assertFalse(w.overlay.isVisible())
        self.assertEqual(w.hero_continuity.hero,fixture.HERO)

if __name__=='__main__':unittest.main()

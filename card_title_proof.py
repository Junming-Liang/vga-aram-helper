"""Exact local-title pixel evidence for short-lived redraw during fresh OCR.

This does not authorize a result, skip OCR, confirm candidates, or extend TTL.
The UI must additionally validate target, scene, generation, hero and freshness.
Only three previously verified OCR title bands are compared. Animated
particles elsewhere in the configured ROI are not evidence of changed titles.
No image pixels are retained; a single changed title pixel fails closed.
"""
from dataclasses import dataclass
import hashlib
import io
import math

from native_state import automatic_candidates


@dataclass(frozen=True)
class CardTitleProof:
    size: tuple
    names: tuple
    regions: tuple
    digests: tuple

    def matches(self, crop_bytes):
        """Compare newly acquired pixels, never a cached or perceptual image."""
        try:
            image = _decode(crop_bytes)
            return image.size == self.size and tuple(
                _digest(image, region) for region in self.regions) == self.digests
        except (OSError, ValueError, TypeError):
            return False


def _decode(crop_bytes):
    from PIL import Image
    with Image.open(io.BytesIO(crop_bytes)) as source:
        if source.width * source.height > 16_000_000:
            raise ValueError('Title crop exceeds the frame limit')
        source.load()
        return source.convert('RGB')


def _digest(image, region):
    return hashlib.sha256(image.crop(region).tobytes()).digest()


def make_title_proof(crop_bytes, candidates, image_size):
    """Build only from the accepted frame's exact high-confidence three titles.

    Use the full column width so an appended/prepended title character cannot
    evade the old OCR box. Half a glyph-height of vertical padding protects
    edges and nearby outline. Final OCR geometry remains an independent guard.
    """
    if not automatic_candidates(candidates, image_size):
        return None
    try:
        image = _decode(crop_bytes)
        if image.size != (image_size['width'], image_size['height']):
            return None
        regions = []
        for index, candidate in enumerate(candidates):
            _, ys = zip(*candidate['box'])
            padding = max(2, math.ceil((max(ys) - min(ys)) / 2))
            region = (math.floor(index * image.width / 3),
                      max(0, math.floor(min(ys)) - padding),
                      math.ceil((index + 1) * image.width / 3),
                      min(image.height, math.ceil(max(ys)) + padding))
            regions.append(region)
        return CardTitleProof(image.size, tuple(c['name'] for c in candidates),
                              tuple(regions), tuple(_digest(image, r) for r in regions))
    except (OSError, ValueError, TypeError, KeyError):
        return None

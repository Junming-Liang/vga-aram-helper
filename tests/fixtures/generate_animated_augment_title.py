"""Regenerate an original diagnostic card for the fourth existing demo title.

This is synthetic test artwork, not a game asset. The card background comes
from the project's original fixtures/auto-scene.png. The Chinese glyphs use
Noto Sans CJK Regular (SIL Open Font License). No font is bundled or loaded by
the regression tests; they consume the generated PNG directly.

Reproduction with the local generation font used for this fixture:
    python tests/fixtures/generate_animated_augment_title.py \
        /usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc
"""
import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('font', type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    with Image.open(root / 'fixtures/auto-scene.png') as original:
        card = original.convert('RGB').crop((196, 176, 464, 501))
    draw = ImageDraw.Draw(card)
    draw.rectangle((35, 110, 234, 179), fill=card.getpixel((20, 110)))
    font = ImageFont.truetype(str(args.font), 30, index=2)  # Simplified Chinese face.
    draw.text((60, 127), '旧日回声', font=font, fill=(20, 36, 32), anchor='lt')
    card.save(Path(__file__).with_name('animated-augment-new-title.png'))


if __name__ == '__main__':
    main()

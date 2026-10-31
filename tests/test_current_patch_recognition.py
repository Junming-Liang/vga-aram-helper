import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from local_ocr import candidate_matches
from patch_catalog import NEW_NAMES


def line(text):
    return [{'text': text, 'confidence': .99,
             'box': [[0, 0], [40, 0], [40, 12], [0, 12]]}]


class CatalogRecognitionTests(unittest.TestCase):
    def test_every_new_catalog_name_matches_ocr_variant(self):
        variants = {
            '小蜜蜂！！！': '小蜜蜂!!!',
            '没法力，没问题': '没法力,没问题',
            '鼓声暴起 低音轰鸣': '鼓声暴起低音轰鸣',
            '升级：风暴狂涌': '升级: 风暴狂涌',
        }
        vocabulary = sorted(NEW_NAMES)
        for name in vocabulary:
            text = variants.get(name, name)
            with self.subTest(name=name, text=text):
                result = candidate_matches(line(text), vocabulary, min_ocr_confidence=.93)
                self.assertEqual([row['name'] for row in result], [name])
                self.assertEqual(result[0]['match_method'], 'exact')

    def test_unknown_text_abstains(self):
        self.assertEqual(candidate_matches(line('完全不存在的海克斯'), sorted(NEW_NAMES),
                                           min_ocr_confidence=.93), [])


if __name__ == '__main__':
    unittest.main()

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import arammayhem_stats as stats

INDEX = {
    'patches': [{
        'patch': '26.21', 'statsDate': '2026-10-30',
        'files': {
            'augments': {'json': 'https://arammayhem.com/data/v1/26-21/augments.json'},
            'champions': {'json': 'https://arammayhem.com/data/v1/26-21/champions.json'},
        },
    }],
}
AUGMENTS = {
    'meta': {'patch': '26.21', 'statsDate': '2026-10-30'},
    'attribution': 'Data: arammayhem.com',
    'license': 'CC BY 4.0: free to use',
    'rows': [
        {'augmentId': 'bees', 'name': {'zh-CN': '小蜜蜂！！！'}, 'rarity': 'gold',
         'pickRate': 73.41, 'pickRateRank': 1, 'introducedPatch': '26.21',
         'retiredPatch': None, 'winRate': 99, 'url': 'https://arammayhem.com/augments/bees/'},
        {'augmentId': 'retired', 'name': {'zh-CN': '已退役'}, 'rarity': 'gold',
         'pickRate': 50.0, 'pickRateRank': 2, 'retiredPatch': '26.21'},
        {'augmentId': 'bad-rate', 'name': {'zh-CN': '坏数据'}, 'pickRate': None, 'pickRateRank': 3},
        {'augmentId': 'same-1', 'name': {'zh-CN': '同名'}, 'pickRate': 10.0, 'pickRateRank': 10},
        {'augmentId': 'same-2', 'name': {'zh-CN': '同名'}, 'pickRate': 11.0, 'pickRateRank': 11},
    ],
}
CHAMPIONS = {
    'meta': {'patch': '26.21', 'statsDate': '2026-10-30'},
    'attribution': 'Data: arammayhem.com',
    'license': 'CC BY 4.0: free to use',
    'rows': [
        {'championId': 'Teemo', 'name': {'zh-CN': '提莫'}, 'pickRate': 5.2,
         'pickRateRank': 88, 'winRate': 99},
        {'championId': 'Ashe', 'name': {'zh-CN': '寒冰射手'}, 'pickRate': 13.99,
         'pickRateRank': 1},
    ],
}


def fetcher(url):
    if url == stats.INDEX_URL:
        return INDEX
    if url.endswith('/augments.json'):
        return AUGMENTS
    if url.endswith('/champions.json'):
        return CHAMPIONS
    raise AssertionError(url)


class AramMayhemTests(unittest.TestCase):
    def cache(self):
        return stats.normalize_payload(AUGMENTS, CHAMPIONS, index_doc=INDEX,
                                       fetched_at='2026-10-31T00:00:00+00:00')

    def test_projection_keeps_pick_rate_only(self):
        cache = self.cache()
        meta = cache['metadata']
        self.assertEqual(meta['patch'], '26.21')
        self.assertEqual(meta['statsDate'], '2026-10-30')
        self.assertEqual(meta['license'], 'CC BY 4.0')
        self.assertIn('arammayhem.com', meta['attribution'])
        self.assertEqual(len(cache['augments']), 4)
        self.assertEqual(len(cache['champions']), 2)
        text = json.dumps(cache, ensure_ascii=False)
        for term in ('winRate', 'tier', 'winRateRank'):
            self.assertNotIn(term, text)
        self.assertEqual(cache['augments'][0]['pickRate'], 73.41)

    def test_augment_lookup_exact_variant_and_abstain(self):
        cache = self.cache()
        self.assertEqual(stats.lookup_augment(cache, '小蜜蜂！！！')['slug'], 'bees')
        self.assertEqual(stats.lookup_augment(cache, '小蜜蜂!!!')['slug'], 'bees')
        self.assertIsNone(stats.lookup_augment(cache, '同名'))
        self.assertIsNone(stats.lookup_augment(cache, '已退役'))
        self.assertIsNone(stats.lookup_augment(cache, '不存在'))

    def test_champion_lookup_uses_reviewed_aliases(self):
        cache = self.cache()
        self.assertEqual(stats.lookup_champion(cache, '迅捷斥候', ['提莫'])['championId'], 'Teemo')
        self.assertEqual(stats.lookup_champion(cache, '寒冰射手')['championId'], 'Ashe')
        self.assertIsNone(stats.lookup_champion(cache, '提莫', ['寒冰射手']))
        self.assertIsNone(stats.lookup_champion(cache, '不存在'))

    def test_sync_and_cached_round_trip(self):
        with tempfile.TemporaryDirectory() as folder:
            result = stats.sync(folder, fetcher=fetcher, fetched_at='2026-10-31T00:00:00+00:00')
            self.assertEqual(result['patch'], '26.21')
            self.assertEqual(result['augments'], 4)
            self.assertEqual(result['champions'], 2)
            cache = stats.load_cached(folder)
            self.assertIsNotNone(cache)
            self.assertEqual(stats.lookup_augment(cache, '小蜜蜂!!!')['slug'], 'bees')

    def test_missing_or_invalid_cache_returns_none(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertIsNone(stats.load_cached(folder))
            path = Path(folder) / stats.CACHE_NAME
            path.write_text('{"schemaVersion":1,"schemaVersion":2}', encoding='utf-8')
            self.assertIsNone(stats.load_cached(folder))
            path.write_text('not json', encoding='utf-8')
            self.assertIsNone(stats.load_cached(folder))

    def test_patch_mismatch_aborts_sync(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(stats.AramMayhemError):
                stats.sync(folder, fetcher=fetcher, target_patch='26.99')

    def test_untrusted_endpoints_rejected(self):
        for url in ('http://arammayhem.com/data/v1/index.json',
                    'https://evil.example/data/v1/index.json',
                    'https://arammayhem.com/other/index.json',
                    'https://user@arammayhem.com/data/v1/index.json'):
            with self.assertRaises(stats.AramMayhemError):
                stats._url(url)

    def test_combo_and_item_projection(self):
        combos = {'attribution': 'Data: arammayhem.com', 'license': 'CC BY 4.0',
                  'rows': [{'championName': {'zh-CN': '英雄'},
                            'augmentNames': [{'zh-CN': '甲'}, {'zh-CN': '乙'}],
                            'augmentIds': ['a', 'b'], 'types': ['god'],
                            'url': 'https://arammayhem.com/combo/x/', 'winRate': 99}]}
        items = {'attribution': 'Data: arammayhem.com', 'license': 'CC BY 4.0',
                 'rows': [{'gameItemId': 1001, 'name': {'zh-CN': '装备'},
                           'category': 'legendary', 'cost': 3000, 'pickRate': 99}]}
        combo_rows = stats.normalize_combos(combos)
        item_rows = stats.normalize_items(items)
        self.assertEqual(combo_rows[0]['champion'], '英雄')
        self.assertEqual(combo_rows[0]['augmentNames'], ['甲', '乙'])
        self.assertEqual(combo_rows[0]['types'], ['god'])
        self.assertEqual(item_rows[0]['gameItemId'], '1001')
        self.assertEqual(item_rows[0]['cost'], 3000)
        text = json.dumps([combo_rows, item_rows], ensure_ascii=False)
        for term in ('winRate', 'pickRate', 'tier'):
            self.assertNotIn(term, text)


if __name__ == '__main__':
    unittest.main()

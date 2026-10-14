"""Synthetic hero-source fixtures; no third-party dataset is redistributed."""
import copy
import unittest

from data_updates import WIKI_PAGE
from engine import normalize
from hero_strength import hero_source_tier, hero_strength_reference
from native_state import source_tier


def fixture():
    return {
        'metadata': {'isDemo': False, 'officialHeroStatistics': True,
                     'sourceUrl': WIKI_PAGE, 'sourceDataDate': '2026-09-07',
                     'wikiDataVersion': '395', 'gamePatch': '16.17',
                     'fetchedAt': '2026-10-12T06:52:18+00:00'},
        'heroes': {'测试英雄': {'championId': '9001', 'overallTier': 'T5', 'sourceVersion': '16.17',
                             'alias': ['测试别名'], 'winRate': 99.9}},
        'heroAugmentStats': {'测试英雄': [{'augmentName': '测试强化', 'tier': 'T1',
                                         'winRate': 99.9, 'numGames': 100000}]},
        'augments': {'测试强化': {'overallTier': 'T1', 'tier': 'T1', 'winRate': 99.9}},
    }


class HeroSourceTierTests(unittest.TestCase):
    def test_champion_vocabulary_includes_t5_without_changing_augment_vocabulary(self):
        for value in ['T1', 'T2', 'T3', 'T4', 'T5']:
            self.assertEqual(hero_source_tier(value), value)
        self.assertEqual(hero_source_tier(' T5 '), 'T5')
        self.assertIsNone(source_tier('T5'))

    def test_unrecognized_scales_and_malformed_values_abstain(self):
        for value in [None, '', ' ', 'None', 'T0', 'T6', 'T99', 't1', 'S', 'A',
                      '1', 1, True, {}, [], float('nan')]:
            with self.subTest(value=value):
                self.assertIsNone(hero_source_tier(value))


class HeroStrengthReferenceTests(unittest.TestCase):
    def test_exact_hero_tier_and_separate_source_metadata(self):
        data = fixture()
        result = hero_strength_reference(data, '测试英雄', champion_id='9001')
        self.assertEqual(result['hero'], '测试英雄')
        self.assertEqual(result['championId'], '9001')
        self.assertEqual(result['sourceTier'], 'T5')
        self.assertEqual(result['sourceTierLabel'], '虎牙公开源英雄评级')
        self.assertIn('资料快照', result['sourceLabel'])
        self.assertIn('非实时评级', result['sourceLabel'])
        self.assertEqual(result['sourceUrl'], WIKI_PAGE)
        self.assertEqual(result['sourceDataDate'], '2026-09-07')
        self.assertEqual(result['wikiDataVersion'], '395')
        self.assertEqual(result['gamePatch'], '16.17')
        self.assertEqual(result['sourceVersion'], '16.17')
        self.assertIs(result['isDemo'], False)
        for key in ['winRate', 'pickRate', 'numGames', 'rank', 'score', 'recommended',
                    'rawTier', 'fetchedAt']:
            self.assertNotIn(key, result)
        self.assertNotIn('99.9', str(result))

    def test_unknown_hero_aliases_and_id_mismatch_never_select_another_record(self):
        data = fixture()
        for hero in ['未知英雄', '测试别名', ' 测试英雄 ', '', None, 9001, {}]:
            with self.subTest(hero=hero):
                self.assertIsNone(hero_strength_reference(data, hero))
        for champion_id in ['9002', '09001', '', 'alias', 9001, True, [], {}]:
            with self.subTest(champion_id=champion_id):
                self.assertIsNone(hero_strength_reference(data, '测试英雄', champion_id=champion_id))

    def test_missing_or_unknown_tier_has_no_augment_or_rate_fallback(self):
        data = fixture()
        for value in [None, '', 'T0', 'T6', 'S', 1, True, {}, []]:
            with self.subTest(value=value):
                data['heroes']['测试英雄']['overallTier'] = value
                self.assertIsNone(hero_strength_reference(data, '测试英雄')['sourceTier'])
        del data['heroes']['测试英雄']['overallTier']
        self.assertIsNone(hero_strength_reference(data, '测试英雄')['sourceTier'])

    def test_unverified_source_is_fail_closed_without_hidden_raw_tier(self):
        for metadata in [{}, None, [], {'officialHeroStatistics': True},
                         {'sourceUrl': WIKI_PAGE},
                         {'officialHeroStatistics': 'true', 'sourceUrl': WIKI_PAGE},
                         {'officialHeroStatistics': True, 'sourceUrl': 'https://example.com/'},
                         {'officialHeroStatistics': True, 'sourceUrl': WIKI_PAGE + '&other=1'}]:
            with self.subTest(metadata=metadata):
                data = fixture()
                data['metadata'] = metadata
                result = hero_strength_reference(data, '测试英雄')
                self.assertIsNone(result['sourceTier'])
                self.assertEqual(result['sourceLabel'], '来源待核对')
                self.assertIsNone(result['sourceUrl'])
                self.assertNotIn('T5', str(result))

    def test_demo_tier_is_explicitly_fictional_even_if_public_marker_present(self):
        data = fixture()
        data['metadata']['isDemo'] = True
        result = hero_strength_reference(data, '测试英雄')
        self.assertEqual(result['sourceTier'], 'T5')
        self.assertIs(result['isDemo'], True)
        self.assertEqual(result['sourceTierLabel'], '虚构英雄评级（演示）')
        self.assertIn('不能用于对局', result['sourceLabel'])
        self.assertNotIn('虎牙', str(result))
        self.assertIsNone(result['sourceUrl'])

    def test_missing_metadata_is_not_replaced_by_fetch_date_or_row_patch(self):
        data = fixture()
        for field in ['sourceDataDate', 'wikiDataVersion', 'gamePatch']:
            del data['metadata'][field]
        data['heroes']['测试英雄']['sourceVersion'] = '16.17'
        result = hero_strength_reference(data, '测试英雄')
        self.assertEqual(result['sourceTier'], 'T5')
        for field in ['sourceDataDate', 'wikiDataVersion', 'gamePatch']:
            self.assertIsNone(result[field])
        self.assertEqual(result['sourceVersion'], '16.17')

    def test_row_version_is_separate_and_never_filled_from_metadata(self):
        data = fixture()
        data['heroes']['测试英雄']['sourceVersion'] = '16.16'
        result = hero_strength_reference(data, '测试英雄')
        self.assertEqual(result['sourceVersion'], '16.16')
        self.assertEqual(result['gamePatch'], '16.17')
        for value in [None, '', 'latest', '16.17<script>', True, {}]:
            with self.subTest(value=value):
                data['heroes']['测试英雄']['sourceVersion'] = value
                self.assertIsNone(hero_strength_reference(data, '测试英雄')['sourceVersion'])

    def test_invalid_snapshot_metadata_stays_missing(self):
        cases = {
            'sourceDataDate': ['2026-02-30', '2026-9-7', '<b>2026-09-07</b>', True, {}],
            'wikiDataVersion': ['', '.', '..', 'bad version', 395, True, {}],
            'gamePatch': ['latest', '16', '16.17<script>', 16.17, True, {}],
        }
        for field, values in cases.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    data = fixture()
                    data['metadata'][field] = value
                    self.assertIsNone(hero_strength_reference(data, '测试英雄')[field])

    def test_missing_canonical_id_cannot_satisfy_an_explicit_selection_id(self):
        for value in [None, '', 9001, True, [], 'not-an-id']:
            with self.subTest(value=value):
                data = fixture()
                data['heroes']['测试英雄']['championId'] = value
                self.assertIsNone(hero_strength_reference(data, '测试英雄', champion_id='9001'))
                self.assertIsNone(hero_strength_reference(data, '测试英雄')['championId'])

    def test_malformed_data_is_not_a_reference(self):
        for data in [None, [], {}, {'heroes': []}, {'heroes': {'测试英雄': None}}]:
            with self.subTest(data=data):
                self.assertIsNone(hero_strength_reference(data, '测试英雄'))

    def test_source_data_is_unchanged_and_output_does_not_alias_input(self):
        data = fixture()
        original = copy.deepcopy(data)
        result = hero_strength_reference(data, '测试英雄')
        result['sourceTier'] = 'T1'
        result['hero'] = 'other'
        self.assertEqual(data, original)

    def test_existing_wiki_adapter_preserves_hero_tier_separate_from_augment_tier(self):
        raw = {
            'metadata': {'sourceDataDate': '2026-09-07'},
            'wiki': {'version': '395', 'championDetail': [
                {'championId': '9001', 'championName': '测试英雄 测试别名',
                 'tier': 'T5', 'version': '16.17', 'winRate': '42%',
                 'augmentRecommendations': [
                     {'augmentId': '9002', 'augmentName': '测试强化', 'tier': 'T1',
                      'winRate': '99%', 'pickRate': '5%', 'numGames': 100}]}]},
        }
        data = normalize(raw)
        self.assertEqual(normalize(data), data)
        result = hero_strength_reference(data, '测试英雄', champion_id='9001')
        self.assertEqual(result['sourceTier'], 'T5')
        self.assertEqual(result['gamePatch'], '16.17')
        self.assertEqual(result['sourceVersion'], '16.17')
        self.assertEqual(data['heroAugmentStats']['测试英雄'][0]['tier'], 'T1')


if __name__ == '__main__':
    unittest.main()

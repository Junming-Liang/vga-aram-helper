import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine import equipment_builds
from hero_reference import equipment_reference, recommendation_rows
from patch_catalog import WIKI_URL


def current_data():
    return {
        'metadata': {'isDemo': False, 'officialHeroStatistics': True,
                     'sourceUrl': WIKI_URL, 'gamePatch': '26.21',
                     'sourceDataDate': '2026-10-25', 'wikiDataVersion': 'test'},
        'heroes': {'英雄': {
            'name': '英雄', 'championId': '17', 'sourceVersion': '26.21',
            'equipmentBuilds': [{
                'style': 'AP',
                'coreItems': [['残疫', '法师之靴']],
                'startingItems': [['短剑', '守护者法球']],
                'winRate': '52.4%', 'pickRate': '8.1%', 'games': 999,
            }],
        }},
        'augments': {
            '甲': {'name': '甲', 'augmentId': '101'},
            '乙': {'name': '乙', 'augmentId': '102'},
            '新': {'name': '新', 'augmentId': '999', 'catalogStatus': 'new'},
        },
        'heroAugmentStats': {'英雄': [
            {'augmentName': '甲', 'augmentId': '101', 'tier': 'T1'},
            {'augmentName': '新', 'augmentId': '999', 'tier': 'T1'},
            {'augmentName': '乙', 'augmentId': '102', 'tier': ''},
        ]},
        'heroSourceCombos': {'17': [['101', '102']]},
    }


class HeroReferenceTests(unittest.TestCase):
    def test_source_order_and_combo_hint(self):
        result = recommendation_rows(current_data(), '英雄')
        self.assertTrue(result['available'])
        self.assertEqual([row['name'] for row in result['rows']], ['甲', '乙'])
        self.assertEqual(result['rows'][0]['tier'], 'T1')
        self.assertEqual(result['rows'][0]['hint'], '搭配：乙')
        self.assertEqual(result['rows'][1]['tier'], '')

    def test_no_rate_or_sample_fields(self):
        result = recommendation_rows(current_data(), '英雄')
        text = json.dumps(result, ensure_ascii=False)
        for term in ('winRate', 'pickRate', 'numGames', 'games'):
            self.assertNotIn(term, text)
        for row in result['rows']:
            self.assertEqual(set(row), {'name', 'tier', 'hint'})

    def test_limit_keeps_source_order(self):
        result = recommendation_rows(current_data(), '英雄', limit=1)
        self.assertEqual([row['name'] for row in result['rows']], ['甲'])

    def test_equipment_names_only(self):
        result = equipment_reference(current_data(), '英雄')
        self.assertTrue(result['available'])
        self.assertEqual(result['builds'][0]['style'], 'AP')
        self.assertEqual(result['builds'][0]['coreItems'], [['残疫', '法师之靴']])
        self.assertEqual(result['builds'][0]['startingItems'], [['短剑', '守护者法球']])
        text = json.dumps(result, ensure_ascii=False)
        for term in ('winRate', 'pickRate', 'games', '样本'):
            self.assertNotIn(term, text)

    def test_outdated_snapshot_abstains(self):
        data = current_data()
        data['metadata'].update(gamePatch='16.17', sourceDataDate='2026-09-07')
        data['heroes']['英雄']['sourceVersion'] = '16.17'
        recommendation = recommendation_rows(data, '英雄')
        equipment = equipment_reference(data, '英雄')
        self.assertFalse(recommendation['available'])
        self.assertFalse(equipment['available'])
        self.assertIn('旧版', recommendation['reason'])
        self.assertIn('旧版', equipment['reason'])

    def test_unknown_hero_abstains(self):
        for hero in ('', '不存在', None, 1):
            self.assertFalse(recommendation_rows(current_data(), hero)['available'])
            self.assertFalse(equipment_reference(current_data(), hero)['available'])

    def test_demo_recommendation_but_no_equipment(self):
        data = {'metadata': {'isDemo': True},
                'heroes': {'演示英雄': {'name': '演示英雄'}},
                'augments': {'演示甲': {'name': '演示甲', 'augmentId': '1'}},
                'heroAugmentStats': {'演示英雄': [
                    {'augmentName': '演示甲', 'augmentId': '1', 'tier': 'T2'}]}}
        recommendation = recommendation_rows(data, '演示英雄')
        self.assertTrue(recommendation['available'])
        self.assertEqual(recommendation['rows'][0]['name'], '演示甲')
        self.assertFalse(equipment_reference(data, '演示英雄')['available'])

    def test_demo_fixture_shows_equipment(self):
        from engine import load_data
        data = load_data(Path(__file__).resolve().parents[1] / 'fixtures' / 'demo.json')
        equipment = equipment_reference(data, '星火术士（演示）')
        self.assertTrue(equipment['available'])
        self.assertEqual(len(equipment['builds']), 2)
        self.assertEqual(equipment['builds'][0]['style'], '演示法术流')
        self.assertNotIn('winRate', json.dumps(equipment, ensure_ascii=False))

    def test_engine_equipment_adapter_drops_rates(self):
        raw = [{
            'buildStyle': 'AD',
            'coreItems': [{'itemNames': ['无尽之刃', '疾射火炮'],
                           'itemIds': [3031, 3094],
                           'winRate': '55.0%', 'pickRate': '4.2%', 'games': 120}],
            'startingItemGroups': [['长剑', '生命药水']],
            'winRate': '54.0%', 'pickRate': '3.0%', 'games': 300,
        }]
        result = equipment_builds(raw)
        self.assertEqual(result, [{'style': 'AD',
                                   'coreItems': [['无尽之刃', '疾射火炮']],
                                   'startingItems': [['长剑', '生命药水']]}])
        self.assertNotIn('winRate', json.dumps(result, ensure_ascii=False))
        self.assertEqual(equipment_builds(result), result)

    def test_engine_equipment_adapter_ignores_malformed(self):
        raw = [None, 'x', {'buildStyle': 'X', 'coreItems': 'bad',
                           'startingItemGroups': [['A', 3, None], 'bad']},
               {'buildStyle': 5, 'coreItems': [{'itemNames': ['B']}]}]
        self.assertEqual(equipment_builds(raw),
                         [{'style': 'X', 'coreItems': [], 'startingItems': [['A']]},
                          {'style': '', 'coreItems': [['B']], 'startingItems': []}])
        self.assertEqual(equipment_builds(None), [])


if __name__ == '__main__':
    unittest.main()

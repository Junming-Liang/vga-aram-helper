import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hero_reference import equipment_reference
from local_offline import (augment_rows, champion_rows, heat_view, load_bundle,
                           local_cards)
from native_state import display_cards
from server import load_startup_data


def bundle():
    names = ['甲', '乙', '丙', '丁', '戊', '己', '庚', '辛', '壬', '癸']
    aram = {
        'metadata': {'patch': '26.21', 'statsDate': '2026-10-30',
                     'sourcePage': 'https://arammayhem.com/zh-cn/data/',
                     'attribution': 'Data: arammayhem.com', 'license': 'CC BY 4.0'},
        'augments': [
            {'name': name, 'slug': 's' + str(index), 'pickRate': 80.0 - index,
             'pickRateRank': index + 1, 'retiredPatch': None, 'winRate': 99}
            for index, name in enumerate(names)
        ],
        'champions': [{'name': '英雄', 'championId': 'Hero', 'pickRate': 10.0, 'pickRateRank': 1}],
        'combos': [
            {'champion': '别名', 'augmentNames': ['乙'], 'types': ['god']},
            {'champion': '英雄', 'augmentNames': ['戊'], 'types': ['trap']},
        ],
        'items': [{'gameItemId': '1001', 'name': '装备甲', 'category': 'legendary', 'cost': 3000},
                  {'gameItemId': '1002', 'name': '装备乙', 'category': 'legendary', 'cost': 800}],
    }
    data = {
        'metadata': {'isDemo': False, 'offlineLocal': True},
        'heroes': {'英雄': {'name': '英雄', 'alias': ['别名'],
                           'equipmentBuilds': [{'style': 'AP', 'coreItems': [['装备甲']],
                                                'startingItems': [['装备乙']]}]}},
        'augments': {name: {'name': name, 'description': '描述' + name} for name in names},
        'heroAugmentStats': {},
    }
    data['aram'] = aram
    return {'schemaVersion': 1, 'metadata': {'offlineLocal': True}, 'data': data, 'aram': aram}


class LocalOfflineTests(unittest.TestCase):
    def write(self, payload):
        folder = tempfile.TemporaryDirectory()
        path = Path(folder.name) / 'offline-data.json'
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
        return folder, path

    def test_local_cards_heat_tiers_and_combos(self):
        cards = local_cards(bundle()['data'], '英雄', ['甲', '乙', '戊', '丙', '癸', '不存在'])
        self.assertEqual([card['sourceTier'] for card in cards],
                         ['S', 'S', 'C', 'A', 'C', None])
        self.assertEqual(cards[0]['heatLabel'], '热度 80.00% · 全强化第 1')
        self.assertEqual(cards[1]['sourceHint'], '英雄组合：高协同')
        self.assertIn('陷阱', cards[2]['sourceHint'])
        self.assertTrue(cards[2]['notes'])
        self.assertEqual(cards[-1]['sourceTierLabel'], '本地未收录')
        text = json.dumps(cards, ensure_ascii=False)
        for term in ('winRate', '胜率'):
            self.assertNotIn(term, text)

    def test_pair_combo_god_synergy_boosts_both_cards(self):
        data = bundle()['data']
        data['aram']['combos'].append(
            {'champion': '英雄', 'augmentNames': ['甲', '丙'], 'types': ['god']})
        cards = local_cards(data, '英雄', ['甲', '丙', '癸'])
        self.assertEqual([card['sourceTier'] for card in cards], ['S', 'S', 'C'])
        self.assertIn('本轮组合', cards[0]['sourceHint'])
        self.assertIn('本轮组合', cards[1]['sourceHint'])
        self.assertNotIn('本轮组合', cards[2]['sourceHint'])

    def test_pair_combo_trap_drops_both_cards(self):
        data = bundle()['data']
        data['aram']['combos'].append(
            {'champion': '英雄', 'augmentNames': ['丙', '癸'], 'types': ['trap']})
        cards = local_cards(data, '英雄', ['丙', '癸'])
        self.assertEqual([card['sourceTier'] for card in cards], ['B', 'C'])
        self.assertIn('陷阱', cards[0]['sourceHint'])
        self.assertTrue(cards[0]['notes'])

    def test_hero_history_tier_is_used_when_unique(self):
        data = bundle()['data']
        data['heroAugmentStats'] = {'英雄': [
            {'augmentName': '丙', 'tier': 'T1'},
            {'augmentName': '丁', 'tier': 'T4'},
            {'augmentName': '戊', 'tier': 'T2'},
        ]}
        cards = local_cards(data, '英雄', ['丙', '丁', '癸'])
        self.assertEqual([card['sourceTier'] for card in cards], ['S', 'C', 'C'])
        self.assertEqual([card['sourceTierLabel'] for card in cards],
                         ['本地综合档位', '本地综合档位', '本地热度档位'])
        self.assertIn('英雄历史档位', cards[0]['sourceLabel'])
        self.assertIn('16.17', cards[0]['notes'][-1])
        self.assertNotIn('英雄历史档位', cards[2]['sourceLabel'])

    def test_ambiguous_history_tier_abstains(self):
        data = bundle()['data']
        data['heroAugmentStats'] = {'英雄': [
            {'augmentName': '丙', 'tier': 'T1'},
            {'augmentName': '丙', 'tier': 'T3'},
        ]}
        card = local_cards(data, '英雄', ['丙'])[0]
        self.assertEqual(card['sourceTierLabel'], '本地热度档位')

    def test_display_cards_branches_to_local(self):
        data = bundle()['data']
        cards = display_cards(data, '英雄', ['甲', '乙', '戊'])
        self.assertEqual([card['sourceTier'] for card in cards], ['S', 'S', 'C'])
        self.assertEqual(cards[0]['sourceBadge'], '本地热度')
        self.assertIsNotNone(heat_view(data))

    def test_offline_equipment_reference(self):
        data = bundle()['data']
        result = equipment_reference(data, '英雄')
        self.assertTrue(result['available'])
        self.assertEqual(result['status'], 'offline-local')
        self.assertIn('本地离线快照', result['note'])

    def test_load_bundle_and_offline_startup(self):
        folder, path = self.write(bundle())
        try:
            data = load_bundle(path)
            self.assertTrue(data['metadata']['offlineLocal'])
            startup = load_startup_data(None, offline_path=path)
            self.assertEqual(startup['status']['state'], 'offline')
            self.assertTrue(startup['data']['metadata']['offlineLocal'])
        finally:
            folder.cleanup()

    def test_load_bundle_strips_game_icon_tokens(self):
        payload = bundle()
        payload['data']['augments']['甲']['description'] = '获得%i:Augment%强化符文，+15%治疗。'
        folder, path = self.write(payload)
        try:
            self.assertEqual(load_bundle(path)['augments']['甲']['description'], '获得强化符文，+15%治疗。')
            startup = load_startup_data(None, offline_path=path)
            self.assertEqual(startup['data']['augments']['甲']['description'], '获得强化符文，+15%治疗。')
        finally:
            folder.cleanup()

    def test_champion_and_augment_source_rankings(self):
        aram = bundle()['aram']
        champions = champion_rows(aram, 5)
        self.assertEqual(champions[0], {'name': '英雄', 'pickRate': 10.0, 'rank': 1})
        augments = augment_rows(aram, 4)
        self.assertEqual([row['name'] for row in augments], ['甲', '乙', '丙', '丁'])
        self.assertEqual([row['rank'] for row in augments], [1, 2, 3, 4])
        self.assertEqual(champion_rows(aram, 0)[0]['name'], '英雄')
        self.assertEqual(len(champion_rows(aram, 999)), 1)
        text = json.dumps([champions, augments], ensure_ascii=False)
        for term in ('winRate', '胜率'):
            self.assertNotIn(term, text)

    def test_invalid_bundle_rejected(self):
        folder, path = self.write({'schemaVersion': 99, 'data': {}, 'aram': {}})
        try:
            with self.assertRaises(ValueError):
                load_bundle(path)
        finally:
            folder.cleanup()


if __name__ == '__main__':
    unittest.main()

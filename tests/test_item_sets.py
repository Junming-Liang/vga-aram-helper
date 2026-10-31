import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from item_sets import build_sets, export, item_index


def data():
    return {
        'heroes': {'英雄': {'name': '英雄', 'alias': ['别名'], 'equipmentBuilds': [
            {'style': 'AP', 'coreItems': [['装备甲', '装备乙', '未知装备']],
             'startingItems': [['装备乙']]},
            {'style': 'Tank', 'coreItems': [['未知装备']], 'startingItems': []},
        ]}},
        'aram': {
            'champions': [{'name': '别名', 'championId': 'Hero'}],
            'items': [
                {'name': '装备甲', 'gameItemId': '1001', 'cost': 3000},
                {'name': '装备乙', 'gameItemId': '1002', 'cost': 800},
                {'name': '重复', 'gameItemId': None, 'cost': 1},
            ],
        },
    }


class ItemSetTests(unittest.TestCase):
    def test_index_and_build_projection(self):
        exact, canonical = item_index(data())
        self.assertEqual(exact, {'装备甲': 1001, '装备乙': 1002})
        sets = build_sets(data(), '英雄')
        self.assertEqual(len(sets), 1)
        filename, config = sets[0]
        self.assertEqual(filename, '!!!vga-aram-0.json')
        self.assertEqual(config['championKey'], 'Hero')
        self.assertEqual(config['title'], 'AP')
        self.assertEqual(config['blocks'][0]['items'], [1001, 1002])
        self.assertTrue(config['priority'])
        self.assertEqual(config['sortrank'], 999999999)

    def test_export_replaces_only_prefix(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / '!!!vga-aram-9.json').write_text('{}', encoding='utf-8')
            (root / 'keep.json').write_text('{}', encoding='utf-8')
            paths = export(data(), '英雄', root)
            self.assertEqual([path.name for path in paths], ['!!!vga-aram-0.json'])
            self.assertFalse((root / '!!!vga-aram-9.json').exists())
            self.assertTrue((root / 'keep.json').exists())
            config = json.loads(paths[0].read_text(encoding='utf-8'))
            self.assertEqual(config['blocks'][0]['items'], [1001, 1002])

    def test_unknown_hero_or_empty_builds_abstain(self):
        with self.assertRaises(ValueError):
            build_sets(data(), '不存在')
        broken = data()
        broken['heroes']['英雄']['equipmentBuilds'] = [{'coreItems': [['未知']]}]
        with self.assertRaises(ValueError):
            build_sets(broken, '英雄')


if __name__ == '__main__':
    unittest.main()

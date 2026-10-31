import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gold_diff import compute, item_costs


DATA = {'aram': {'items': [
    {'gameItemId': '1001', 'cost': 3000},
    {'gameItemId': '1002', 'cost': 500},
    {'gameItemId': 'bad', 'cost': 100},
    {'gameItemId': '1003', 'cost': None},
    {'gameItemId': '1004', 'cost': True},
]}}


class GoldDiffTests(unittest.TestCase):
    def costs(self):
        return item_costs(DATA)

    def test_item_cost_projection(self):
        self.assertEqual(self.costs(), {1001: 3000, 1002: 500})

    def test_team_values_and_self_team(self):
        players = [
            {'team': 'ORDER', 'riotId': 'A#TAG', 'items': [{'itemID': 1001}, {'itemID': 9999}]},
            {'team': 'ORDER', 'summonerName': 'B', 'items': [{'itemID': 1002}]},
            {'team': 'CHAOS', 'riotId': 'C#TAG', 'items': [{'itemID': 1001}, {'itemID': 1001}]},
        ]
        result = compute(players, 'A#TAG', self.costs())
        self.assertEqual(result['blue'], 3500)
        self.assertEqual(result['red'], 6000)
        self.assertEqual(result['diff'], -2500)
        self.assertEqual(result['selfTeam'], 'ORDER')
        self.assertEqual((result['knownItems'], result['totalItems']), (4, 5))
        self.assertEqual(result['diffText'], '-2500')
        self.assertEqual(compute(players, 'B', self.costs())['selfTeam'], 'ORDER')
        self.assertEqual(compute(players, 'C#TAG', self.costs())['selfTeam'], 'CHAOS')
        self.assertEqual(compute(players, 'unknown', self.costs())['selfTeam'], 'ORDER')

    def test_large_values_are_compact(self):
        players = [{'team': 'ORDER', 'items': [{'itemID': 1001}] * 4},
                   {'team': 'CHAOS', 'items': []}]
        result = compute(players, '', {'x': 1} | {1001: 3000})
        self.assertEqual(result['blueText'], '12.0k')

    def test_invalid_inputs_abstain(self):
        for players in (None, [], [{'team': 'ORDER'}], [None], [{'team': 'ORDER'}] * 21):
            self.assertIsNone(compute(players, 'A', {1001: 3000}))
        self.assertIsNone(compute([{'team': 'ORDER', 'items': []}], 'A', None))

    def test_unknown_items_do_not_break_values(self):
        players = [{'team': 'ORDER', 'items': [{'itemID': 404}, {'itemID': 'bad'}, {}]},
                   {'team': 'CHAOS', 'items': []}]
        result = compute(players, 'A', self.costs())
        self.assertEqual(result['blue'], 0)
        self.assertEqual(result['totalItems'], 1)


if __name__ == '__main__':
    unittest.main()

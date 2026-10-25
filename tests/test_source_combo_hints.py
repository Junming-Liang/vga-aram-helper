import copy
import json
import unittest
from engine import normalize
from patch_catalog import WIKI_URL
from source_combo_hints import normalize_source_combos, source_combo_hint


def fixture():
    return {'metadata': {'officialHeroStatistics': True, 'isDemo': False,
                         'sourceDataDate': '2026-10-22', 'wikiDataVersion': 'synthetic-current',
                         'gamePatch': '16.21', 'sourceUrl': WIKI_URL},
            'heroes': {'英雄甲': {'championId': '1', 'sourceVersion': '16.21'}, '英雄乙': {'championId': '2', 'sourceVersion': '16.21'}},
            'augments': {name: {'augmentId': str(i)} for i, name in enumerate(['强化甲', '强化乙', '强化丙', '强化丁'], 11)},
            'heroSourceCombos': {'1': [['11', '12', '13']], '2': [['11', '14']]}}


class SourceComboHintTests(unittest.TestCase):
    def test_exact_hero_and_augment_identity(self):
        d = fixture()
        hint = source_combo_hint(d, '英雄甲', '强化甲')
        self.assertEqual(hint['text'], '搭配：强化乙、强化丙')
        self.assertEqual(hint['partnerIds'], ['12', '13'])
        self.assertEqual(source_combo_hint(d, '英雄乙', '强化甲')['text'], '搭配：强化丁')
        self.assertEqual(hint['sourceDate'], '2026-10-22')
        self.assertIn('非后续选择顺序', hint['sourceLabel'])

    def test_missing_is_not_invented(self):
        d = fixture()
        for hero, augment in [('英雄甲', '强化丁'), ('未知英雄', '强化甲'), ('英雄甲', '强化')]:
            self.assertIsNone(source_combo_hint(d, hero, augment))
        d.pop('heroSourceCombos')
        self.assertIsNone(source_combo_hint(d, '英雄甲', '强化甲'))

    def test_no_rates_rank_score_ai_or_assumed_history(self):
        d = fixture()
        d['heroSourceCombos']['1'] = [{'augments': ['11', '12'], 'tier': 'T1', 'winRate': '99%', 'rank': 1, 'championAiSummary': 'must pick'}]
        hint = source_combo_hint(d, '英雄甲', '强化甲')
        self.assertEqual(hint['text'], '搭配：强化乙')
        for term in ['winRate', 'pickRate', 'rank', 'tier', '99%', 'must pick']:
            self.assertNotIn(term, json.dumps(hint))

    def test_duplicate_catalog_ids_abstain(self):
        d = fixture(); d['augments']['同名别义'] = {'augmentId': '12'}
        self.assertIsNone(source_combo_hint(d, '英雄甲', '强化甲'))
        d = fixture(); d['heroes']['另一个英雄'] = {'championId': '1'}
        self.assertIsNone(source_combo_hint(d, '英雄甲', '强化甲'))

    def test_unknown_partner_and_deleted_abstain(self):
        for mutation in ['unknown', 'current-deleted', 'partner-deleted']:
            d = fixture()
            if mutation == 'unknown': d['heroSourceCombos']['1'] = [['11', '999']]
            elif mutation == 'current-deleted': d['augments']['强化甲']['isDeleted'] = True
            else: d['augments']['强化乙']['isDeleted'] = True
            self.assertIsNone(source_combo_hint(d, '英雄甲', '强化甲'))

    def test_demo_and_unverified_source_abstain(self):
        for metadata in [{'isDemo': True, 'officialHeroStatistics': True}, {}, {'officialHeroStatistics': 1}]:
            d = fixture(); d['metadata'] = metadata
            self.assertIsNone(source_combo_hint(d, '英雄甲', '强化甲'))

    def test_malformed_projection_abstains(self):
        for rows in [None, {}, [['11', '11']], [['11', 12]], [['11']], [['11', '12', '13', '14', '15', '16']], [['11', 'x']], ['11']]:
            d = fixture(); d['heroSourceCombos']['1'] = rows
            self.assertIsNone(source_combo_hint(d, '英雄甲', '强化甲'))

    def test_short_plain_text_no_partial_names(self):
        for name in ['x' * 25, 'bad\nname', '<script>bad</script>', 'bad\u2028name']:
            d = fixture(); d['augments'][name] = d['augments'].pop('强化乙')
            self.assertIsNone(source_combo_hint(d, '英雄甲', '强化甲'))

    def test_first_valid_source_example_not_inferred_score(self):
        d = fixture(); d['heroSourceCombos']['1'] = [['11', '999'], ['11', '14'], ['11', '12']]
        self.assertEqual(source_combo_hint(d, '英雄甲', '强化甲')['text'], '搭配：强化丁')

    def test_projection_is_narrow_and_idempotent(self):
        raw = {'wiki': {'championDetail': [{'championId': '1', 'topAugmentCombos': [
            {'augments': ['11', '12'], 'winRate': 99, 'tier': 'T1'}, {'augments': ['11', '12']}]}]}}
        projected = normalize_source_combos(raw)
        self.assertEqual(projected, {'1': [['11', '12']]})
        self.assertEqual(projected, normalize_source_combos({'heroSourceCombos': projected}))

    def test_duplicate_hero_source_rows_abstain(self):
        row = {'championId': '1', 'topAugmentCombos': [{'augments': ['11', '12']}]}
        self.assertEqual(normalize_source_combos({'wiki': {'championDetail': [row, row, row]}}), {})

    def test_normalize_preserves_only_combos_and_is_idempotent(self):
        d = fixture(); result = normalize(d)
        self.assertEqual(result['heroSourceCombos'], d['heroSourceCombos'])
        self.assertEqual(normalize(result), result)
        self.assertEqual(source_combo_hint(result, '英雄甲', '强化甲')['text'], '搭配：强化乙、强化丙')

    def test_raw_wiki_adapter_uses_stable_ids(self):
        raw = {'metadata': {'sourceDataDate': '2026-10-22', 'gamePatch': '16.21'},
               'wiki': {'version': 'synthetic-current', 'championDetail': [{'championId': '1', 'championName': '英雄甲 别名', 'version': '16.21',
                'topAugmentCombos': [{'augments': ['11', '12'], 'tier': '', 'winRate': '99%'}]}],
                'augmentDetail': [{'augmentId': '11', 'augmentName': '强化甲'}, {'augmentId': '12', 'augmentName': '强化乙'}]}}
        d = normalize(raw)
        self.assertEqual(source_combo_hint(d, '英雄甲', '强化甲')['text'], '搭配：强化乙')
        self.assertEqual(d, normalize(d))

    def test_malformed_wiki_details_abstain(self):
        for value in [None, {}, 'bad', 42]:
            self.assertEqual(normalize_source_combos({'wiki': {'championDetail': value}}), {})
        self.assertEqual(normalize_source_combos({'wiki': {}}), {})
        self.assertEqual(normalize_source_combos({'wiki': None}), {})

    def test_input_not_mutated(self):
        d = fixture(); before = copy.deepcopy(d)
        source_combo_hint(d, '英雄甲', '强化甲')
        self.assertEqual(d, before)


if __name__ == '__main__': unittest.main()

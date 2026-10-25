"""Reviewed announcement delta, not a complete third-party catalog fixture."""
import copy
import unittest
from collections import Counter
from engine import normalize
from patch_catalog import NEW_NAMES, RETIRED_NAMES, official_records, OFFICIAL_URL
from tests.test_current_patch import fixture


class OfficialCatalogTests(unittest.TestCase):
    def test_counts_rarities_and_official_spelling(self):
        records=official_records()
        self.assertEqual(len(records),35);self.assertEqual(len(RETIRED_NAMES),13)
        self.assertEqual(Counter(row['rarity'] for row in records.values()),{'silver':10,'gold':19,'prismatic':6})
        self.assertIn('由暴生急',RETIRED_NAMES);self.assertIn('魄罗蛮冲',RETIRED_NAMES)
        self.assertNotIn('由暴生极',RETIRED_NAMES);self.assertNotIn('魄罗奔袭',RETIRED_NAMES)
        self.assertIn('小蜜蜂！！！',NEW_NAMES);self.assertIn('鼓声暴起 低音轰鸣',NEW_NAMES)
        self.assertIn('没法力，没问题',NEW_NAMES);self.assertIn('升级：风暴狂涌',NEW_NAMES)

    def test_dictionary_new_retired_and_unverified_states(self):
        raw=fixture()
        raw['augments'].update({name:{'augmentId':str(9000+i)} for i,name in enumerate(RETIRED_NAMES)})
        data=normalize(raw)
        self.assertTrue(NEW_NAMES <= set(data['augments']))
        self.assertFalse(RETIRED_NAMES & set(data['augments']))
        self.assertEqual(set(data['retiredAugments']),RETIRED_NAMES)
        self.assertEqual(data['augments']['测试甲']['catalogStatus'],'carried_forward_unverified')
        self.assertEqual(data['metadata']['catalogCoverage'],'partial-official-delta')
        self.assertEqual(data['metadata']['catalogMode'],'ARAM: Mayhem')
        self.assertEqual(data['metadata']['catalogRegion'],'CN')

    def test_new_identity_provenance_has_no_fabricated_numeric_ids_or_grades(self):
        for row in official_records().values():
            self.assertEqual(row['augmentId'],'')
            self.assertTrue(row['catalogId'].startswith('tencent-cn:26.21:'))
            self.assertEqual(row['catalogSourceUrl'],OFFICIAL_URL)
            self.assertEqual(row['catalogSourceDate'],'2026-10-21')
            self.assertEqual(row['catalogConfidence'],'official-announcement')
            self.assertEqual(row['catalogStatus'],'new')
            for key in ('tier','overallTier','winRate','pickRate','numGames'):
                self.assertNotIn(key,row)

    def test_normalization_idempotent_no_mutation_and_old_audit_preserved(self):
        raw=fixture();original=copy.deepcopy(raw)
        data=normalize(raw)
        self.assertEqual(raw,original)
        self.assertEqual(normalize(data),data)
        self.assertEqual(data['heroAugmentStats']['英雄甲'],normalize(original)['heroAugmentStats']['英雄甲'])
        data['augments']['罪恶快感']['description']='mutated'
        self.assertIn('火箭',official_records()['罪恶快感']['description'])

    def test_conflicting_cn_en_mechanic_is_disclosed_not_silently_resolved(self):
        text=official_records()['没法力，没问题']['description']
        self.assertIn('法力回复',text);self.assertIn('法力值',text);self.assertIn('游戏内',text)


if __name__=='__main__':unittest.main()

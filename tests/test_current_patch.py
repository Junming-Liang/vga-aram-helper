"""Synthetic 4.0 applicability regressions; no live source data or network."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from core import compare_augments
from data_updates import refresh_official_data, WIKI_PAGE
from engine import normalize, recommend
from hero_strength import hero_strength_reference
from native_state import display_cards
from patch_catalog import (CURRENT_PATCH, NEW_NAMES, RETIRED_NAMES, OFFICIAL_URL,
                           WIKI_URL, official_records, statistics_status,
                           ratings_available, pair_rating_available)
from public_payload import public_data, public_comparison, public_recommendation
from source_combo_hints import source_combo_hint
from update_network import json_bytes


def fixture(patch='16.17', stamp='2026-09-07'):
    names = [('测试甲','11'), ('测试乙','12'), ('测试丙','13'), ('罪恶快感','1322'), ('炽燃利息','2128')]
    return {'metadata': {'isDemo':False, 'officialHeroStatistics':True, 'sourceUrl':WIKI_URL,
                         'wikiDataVersion':'synthetic', 'gamePatch':patch, 'sourceDataDate':stamp,
                         'fetchedAt':'2026-10-23T12:00:00+00:00'},
            'heroes': {'英雄甲':{'championId':'1','overallTier':'T5','sourceVersion':patch}},
            'augments': {name: {'augmentId':aid,'description':'旧机制标记','items':[{'name':'旧装备','core':True}],
                                'rarity':'gold','overallTier':'T1'} for name,aid in names},
            'heroAugmentStats': {'英雄甲':[{'augmentName':name,'augmentId':aid,'tier':'T1',
                                         'winRate':97.12345,'pickRate':41.56789,'numGames':9876543}
                                        for name,aid in names]},
            'heroSourceCombos': {'1':[['1322','11'],['11','12']]},
            'items':{'旧装备':{}},
            'relations':{'英雄甲':{'specialAugments':[{'name':'罪恶快感','reason':'旧联动标记','core':True}],
                                'trapAugments':[]}},
            'combinations':[{'name':'旧组合','augments':[{'name':'罪恶快感'}],
                             'combinations':[{'augments':[],'items':[{'name':'旧装备'}]}]}]}


def assert_public_safe(case, value):
    if isinstance(value, dict):
        for key, child in value.items():
            case.assertNotIn('rate', key.lower())
            case.assertNotIn(key, ('numGames','rank','officialRank','recommendedName','officialStats','rawTier'))
            assert_public_safe(case, child)
    elif isinstance(value, list):
        for child in value: assert_public_safe(case, child)
    case.assertNotIn('97.12345', json.dumps(value))
    case.assertNotIn('41.56789', json.dumps(value))


class CurrentPatchTests(unittest.TestCase):
    def test_fetched_today_old_source_stays_outdated(self):
        data = normalize(fixture())
        self.assertEqual(statistics_status(data)['ratingStatus'], 'outdated')
        self.assertEqual(data['metadata']['catalogPatch'], CURRENT_PATCH)
        self.assertEqual(data['metadata']['gamePatch'], '16.17')
        self.assertIsNone(hero_strength_reference(data,'英雄甲')['sourceTier'])
        self.assertTrue(all(c['sourceTier'] is None for c in display_cards(data,'英雄甲',['测试甲','测试乙','测试丙'])))
        self.assertIsNone(source_combo_hint(data,'英雄甲','测试甲'))
        result = compare_augments(data,'英雄甲',['测试甲','测试乙','测试丙'])
        self.assertIsNone(result['recommendedName'])
        self.assertEqual(recommend(data,'测试甲')['recommendations'], [])
        # Audit data is retained internally, never silently overwritten with a fake current tier.
        self.assertEqual(data['heroes']['英雄甲']['overallTier'], 'T5')
        self.assertEqual(data['heroAugmentStats']['英雄甲'][0]['tier'], 'T1')

    def test_only_explicit_current_aliases_are_eligible(self):
        for patch in ('16.21','26.21'):
            data = normalize(fixture(patch,'2026-10-22'))
            self.assertTrue(ratings_available(data,'英雄甲'))
            self.assertEqual(hero_strength_reference(data,'英雄甲')['sourceTier'],'T5')
            self.assertEqual(display_cards(data,'英雄甲',['测试甲'])[0]['sourceTier'],'T1')
        for patch in ('16.17','26.20','16.210','26.21.1','16.22','26.22','36.21','latest',None,True,{}):
            with self.subTest(patch=patch):
                data=fixture(); data['metadata']['gamePatch']=patch
                data['metadata']['sourceDataDate']='2026-10-22'
                self.assertFalse(ratings_available(data))

    def test_dates_provenance_and_forged_status_fail_closed(self):
        for stamp in (None,'','2026-09-07','2026-10-21','2026-02-30','2026-10-2','2099-01-01',True,{}):
            with self.subTest(stamp=stamp):
                data=fixture('16.21',stamp)
                data['metadata'].update(ratingStatus='current',dataFreshness='fresh')
                self.assertFalse(ratings_available(data))
        for url in (None,'https://example.test/',WIKI_URL+'&spoof=1'):
            data=fixture('16.21','2026-10-22');data['metadata']['sourceUrl']=url
            self.assertFalse(ratings_available(data))
        for version in ('16.17', None, '', '16.22', {}, []):
            data=fixture('16.21','2026-10-22');data['heroes']['英雄甲']['sourceVersion']=version
            self.assertFalse(ratings_available(data,'英雄甲'))
            self.assertEqual(hero_strength_reference(data,'英雄甲')['ratingStatus'],'unverified')
        del data['heroes']['英雄甲']['sourceVersion']
        self.assertFalse(ratings_available(data,'英雄甲'))

    def test_public_relations_do_not_bypass_conflicting_hero_patch(self):
        data=fixture('16.21','2026-10-22')
        data['relations']['英雄甲']['specialAugments']=[{'name':'测试甲','reason':'旧版 T1 联动'}]
        for version in ('16.17', None, '', {}, []):
            data['heroes']['英雄甲']['sourceVersion']=version
            payload=public_data(data)
            self.assertEqual(payload['relations'], {})
            self.assertIsNone(payload['heroes']['英雄甲']['overallTier'])
            self.assertNotIn('旧版 T1 联动', json.dumps(payload,ensure_ascii=False))
            self.assertTrue(all(row['tier'] is None for row in payload['heroAugmentStats']['英雄甲']))

    def test_pair_requires_stable_matching_id_not_display_name(self):
        data=normalize(fixture('16.21','2026-10-22'))
        row=data['heroAugmentStats']['英雄甲'][0]
        self.assertTrue(pair_rating_available(data,'英雄甲','测试甲',row))
        for aid in ('','12',None,11,{}):
            other=dict(row,augmentId=aid)
            self.assertFalse(pair_rating_available(data,'英雄甲','测试甲',other))
        del row['augmentId']
        self.assertIsNone(display_cards(data,'英雄甲',['测试甲'])[0]['sourceTier'])

    def test_same_name_new_effect_never_inherits_legacy_id_description_or_combo(self):
        for current in (False,True):
            data=normalize(fixture('16.21','2026-10-22') if current else fixture())
            self.assertEqual(normalize(data), data)
            record=data['augments']['罪恶快感']
            self.assertEqual(record['augmentId'],'')
            self.assertEqual(record['catalogId'],'tencent-cn:26.21:罪恶快感')
            self.assertIn('火箭',record['description'])
            self.assertNotIn('旧机制标记',record['description'])
            self.assertEqual(record['items'],[])
            card=display_cards(data,'英雄甲',['罪恶快感'])[0]
            self.assertIsNone(card['sourceTier']);self.assertEqual(card['notes'],[])
            self.assertNotIn('sourceHint',card)
            self.assertIsNone(source_combo_hint(data,'英雄甲','罪恶快感'))
            self.assertEqual(recommend(data,'罪恶快感')['recommendations'],[])
            payload=public_data(data)
            self.assertFalse(any(row['augmentName']=='罪恶快感' for row in payload['heroAugmentStats']['英雄甲']))
            self.assertNotIn('旧联动标记',json.dumps(payload,ensure_ascii=False))
            self.assertNotIn('旧组合',json.dumps(payload,ensure_ascii=False))

    def test_direct_unadapted_presentations_also_block_collision_and_retirement(self):
        data=fixture('16.21','2026-10-22')
        card=display_cards(data,'英雄甲',['罪恶快感'])[0]
        self.assertIn('火箭',card['description']);self.assertIsNone(card['sourceTier'])
        self.assertIsNone(display_cards(data,'英雄甲',['炽燃利息'])[0]['sourceTier'])
        with self.assertRaises(ValueError):compare_augments(data,'英雄甲',['炽燃利息','测试甲','测试乙'])
        with self.assertRaises(KeyError):recommend(data,'炽燃利息')

    def test_all_public_outlets_hide_statistics_and_old_tiers(self):
        data=normalize(fixture())
        outputs=[public_data(data), public_comparison(data,'英雄甲',['测试甲','测试乙','罪恶快感']),
                 public_recommendation(recommend(data,'测试甲')), hero_strength_reference(data,'英雄甲')]
        for value in outputs:
            assert_public_safe(self,value)
            self.assertNotIn('T1',json.dumps(value));self.assertNotIn('T5',json.dumps(value))
        self.assertEqual(outputs[0]['metadata']['ratingStatus'],'outdated')

    def test_legacy_tips_and_equipment_links_are_not_renewed_by_statistics_metadata(self):
        for patch, stamp in [('16.17','2026-09-07'), ('16.21','2026-10-22')]:
            data=fixture(patch,stamp)
            data['augments']['测试甲']['tips']='旧打法 T1'
            data['heroes']['英雄甲']['tips']='旧英雄打法 T1'
            data['relations']['英雄甲']['specialAugments']=[{'name':'测试甲','reason':'旧关系 T1'}]
            data=normalize(data)
            payload=public_data(data)
            self.assertNotIn('旧打法',json.dumps(payload,ensure_ascii=False))
            self.assertNotIn('旧英雄打法',json.dumps(payload,ensure_ascii=False))
            self.assertEqual(payload['augments']['测试甲']['items'],[])
            self.assertEqual(payload['relations'],{})
            self.assertEqual(payload['combinations'],[])
            self.assertEqual(display_cards(data,'英雄甲',['测试甲'])[0]['notes'],[])
            self.assertEqual(recommend(data,'测试甲')['recommendations'],[])

    def test_malformed_metadata_cannot_leak_hidden_statistics_in_new_card_fields(self):
        data=fixture();data['metadata']['sourceDataDate']={'winRate':97.12345}
        assert_public_safe(self,public_data(data))
        assert_public_safe(self,display_cards(data,'英雄甲',['测试甲']))

    def test_demo_remains_explicitly_fictional_and_unmodified_by_catalog(self):
        raw=fixture();raw['metadata']['isDemo']=True
        data=normalize(raw)
        self.assertNotIn('蓝色屏障',data['augments'])
        self.assertIn('炽燃利息',data['augments'])
        self.assertEqual(hero_strength_reference(data,'英雄甲')['sourceTier'],'T5')
        self.assertEqual(display_cards(data,'英雄甲',['测试甲'])[0]['sourceTier'],'T1')
        self.assertEqual(statistics_status(data)['ratingStatus'],'demo')

    def test_unknown_source_never_receives_official_catalog_identity(self):
        raw=fixture();raw['metadata']['sourceUrl']='https://example.test/'
        data=normalize(raw)
        self.assertNotIn('蓝色屏障',data['augments'])
        self.assertFalse(ratings_available(data))


class CurrentPatchTransportTests(unittest.TestCase):
    def test_fresh_and_cached_transport_do_not_relabel_old_statistics(self):
        # Reuse synthetic transport fixtures, not a live-source or recorded payload.
        from tests.test_data_updates import fixture as wire_fixture, BUNDLE, ROOT
        wire=wire_fixture()
        wire['champion-detail'][0]['date']='2026-09-07'
        def fetch(url, *, max_bytes):
            if url==WIKI_PAGE:return ('<script src="'+BUNDLE+'"></script>').encode()
            if url==BUNDLE:return b'var cfg={VITE_TOOL_ID:"test123"};'
            return json_bytes(wire[url.rsplit('/',1)[1].removesuffix('.json')])
        def version(*a, **kw):return {'version':'500','dataBaseUrl':ROOT.rsplit('/500/',1)[0]+'/'}
        with tempfile.TemporaryDirectory() as tmp:
            fresh=refresh_official_data(Path(tmp),fetcher=fetch,version_fetcher=version)
            self.assertEqual(fresh['status']['state'],'fresh')
            self.assertEqual(fresh['status']['ratingStatus'],'outdated')
            self.assertIn('不适用',fresh['status']['message'])
            original=(Path(tmp)/'current.json').read_bytes()
            def fail(*a,**k):raise OSError('synthetic offline')
            cached=refresh_official_data(Path(tmp),fetcher=fail,version_fetcher=version)
            self.assertEqual(cached['status']['state'],'cached')
            self.assertEqual(cached['status']['ratingStatus'],'outdated')
            self.assertEqual(cached['data'],fresh['data'])
            self.assertEqual((Path(tmp)/'current.json').read_bytes(),original)


if __name__=='__main__':unittest.main()

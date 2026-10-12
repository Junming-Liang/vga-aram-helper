"""Conservative automatic hero/title gates; no third-party images bundled."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from native_state import RecognitionState,automatic_candidates,display_description
from hero_portraits import parse_roster,load_portraits,BASE


def candidates():
    return [{'name':name,'recognized_text':name,'match_method':'exact','ocr_confidence':.99,
        'box':[[x-35,150],[x+35,150],[x+35,180],[x-35,180]]} for name,x in [('甲',150),('乙',450),('丙',750)]]

class AutomaticStateTests(unittest.TestCase):
    def test_unknown_hero_clears_prior_identity_and_cards(self):
        s=RecognitionState();s.start((1,2,'game'));self.assertFalse(s.observe_hero('本人甲'));self.assertTrue(s.observe_hero('本人甲'))
        s.confirm(['甲','乙','丙'],['甲','乙','丙'],automatic=True)
        self.assertFalse(s.observe_hero(None));self.assertEqual(s.hero,'');self.assertFalse(s.confirmed);self.assertEqual(s.offered,())
    def test_changed_hero_requires_two_observations(self):
        s=RecognitionState();s.start((1,2,'game'));s.observe_hero('甲');s.observe_hero('甲')
        self.assertFalse(s.observe_hero('乙'));self.assertEqual(s.hero,'');self.assertTrue(s.observe_hero('乙'));self.assertEqual(s.hero,'乙')
    def test_clear_hero_discards_stability(self):
        s=RecognitionState();s.start((1,2,'game'));s.observe_hero('甲');s.clear_hero();self.assertFalse(s.observe_hero('甲'))
    def test_unsafe_frame_never_counts_toward_two_safe_observations(self):
        s=RecognitionState();s.start((1,2,'game'));names=['甲','乙','丙']
        self.assertFalse(s.observe_automatic_candidates(names,False));self.assertFalse(s.observe_automatic_candidates(names,True));self.assertTrue(s.observe_automatic_candidates(names,True))
        self.assertFalse(s.observe_automatic_candidates(names,False));self.assertFalse(s.observe_automatic_candidates(names,True))
    def test_exact_unique_aligned_titles_pass(self):self.assertTrue(automatic_candidates(candidates(),{'width':900,'height':400}))
    def test_low_confidence_fuzzy_brackets_duplicate_wrong_geometry_fail(self):
        variants=[]
        for field,value in [('match_method','fuzzy-suggestion'),('ocr_confidence',.92),('ocr_confidence',float('nan')),('recognized_text','【甲】'),('box',None)]:
            items=candidates();items[0][field]=value;variants.append(items)
        items=candidates();items[2]['name']='甲';variants.append(items)
        items=candidates();items[1]['box']=[[410,220],[480,220],[480,250],[410,250]];variants.append(items)
        items=candidates();items[0]['box']=[[700,150],[750,150],[750,180],[700,180]];variants.append(items)
        variants.extend([[],candidates()[:2],candidates()+candidates()[:1]])
        for items in variants:
            with self.subTest(items=items):self.assertFalse(automatic_candidates(items,{'width':900,'height':400}))
    def test_invalid_dimensions_fail_closed(self):
        for size in [None,{}, {'width':True,'height':400},{'width':float('inf'),'height':400}]:self.assertFalse(automatic_candidates(candidates(),size))
    def test_source_tokens_do_not_invent_numbers(self):
        text=display_description('造成 %i:scaleCrit% ? 伤害并施加 %i:OnHit%')
        self.assertNotIn('%i:',text);self.assertIn('未展开',text);self.assertIn('?',text);self.assertNotIn('100',text)


def roster(version='16.20.1'):
    return json.dumps({'version':version,'data':{str(i):{'key':str(i),'id':'Hero'+str(i),'image':{'full':'Hero'+str(i)+'.png'}} for i in range(100)}}).encode()

class PortraitCacheTests(unittest.TestCase):
    def test_official_roster_rejects_paths_duplicates_and_incomplete(self):
        self.assertEqual(len(parse_roster(roster(),'16.20.1')),100)
        for change in ['path','duplicate','few','version']:
            raw=json.loads(roster())
            if change=='path':raw['data']['0']['image']['full']='../steal.png'
            elif change=='duplicate':raw['data']['0']['key']='1'
            elif change=='few':raw['data']={}
            else:raw['version']='invalid'
            with self.assertRaises(ValueError):parse_roster(json.dumps(raw),'16.20.1')
    @patch('hero_portraits.decode_portrait',side_effect=lambda payload:'decoded:'+payload.decode())
    def test_complete_cache_hashes_version_refresh_and_offline_fallback(self,_):
        calls=[]
        def fetch(url,**kwargs):
            calls.append(url);self.assertEqual(kwargs['hosts'],frozenset({'ddragon.leagueoflegends.com'}))
            if url.endswith('versions.json'):return b'["16.20.1"]'
            if url.endswith('champion.json'):return roster()
            return b'synthetic-icon'
        with tempfile.TemporaryDirectory() as temp:
            bank,status=load_portraits(temp,fetcher=fetch);self.assertEqual(len(bank),100);self.assertEqual(status['state'],'fresh')
            calls.clear();bank,status=load_portraits(temp,fetcher=fetch);self.assertEqual(status['state'],'current');self.assertEqual(len(calls),1)
            bank,status=load_portraits(temp,allow_download=False,fetcher=lambda *a,**k:self.fail('Offline called network'));self.assertEqual(len(bank),100)
            (Path(temp)/'16.20.1/Hero0.png').write_bytes(b'tampered')
            bank,status=load_portraits(temp,allow_download=False);self.assertFalse(bank);self.assertEqual(status['state'],'unavailable')
    def test_unavailable_network_and_no_cache_returns_unknown(self):
        with tempfile.TemporaryDirectory() as temp:
            bank,status=load_portraits(temp,fetcher=lambda *a,**k:(_ for _ in ()).throw(OSError('offline')))
            self.assertFalse(bank);self.assertEqual(status['state'],'unavailable')
    def test_cancel_stops_before_network(self):
        event=threading.Event();event.set()
        with tempfile.TemporaryDirectory() as temp:
            bank,status=load_portraits(temp,cancelled=event,fetcher=lambda *a,**k:self.fail('Cancelled fetched'))
            self.assertFalse(bank)

if __name__=='__main__':unittest.main()

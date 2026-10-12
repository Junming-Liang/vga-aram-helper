"""Original synthetic hero+three tests; no vendor dataset distributed."""
import copy
from http.client import HTTPConnection
import json
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core import compare_augments
from engine import normalize, percentage
from server import make_server,load_startup_data


def fixture():
    return normalize({'metadata':{'isDemo':True},'heroes':{'英雄甲':{},'英雄乙':{}},
      'augments':{'强化甲':{'winRate':40},'强化乙':{'winRate':99},'强化丙':{'winRate':80},'未收录配对':{'winRate':100}},
      'heroAugmentStats':{
       '英雄甲':[{'augmentName':n,'tier':t,'winRate':r,'pickRate':8,'numGames':150,'rateUnit':'percent'} for n,t,r in [('强化甲','T2',52),('强化乙','T1',65),('强化丙','T1',60)]],
       '英雄乙':[{'augmentName':n,'tier':'T2','winRate':55,'pickRate':2,'numGames':80,'rateUnit':'percent'} for n in ['强化丙','强化甲','强化乙']]}})

NAMES=['强化丙','强化乙','强化甲']
class ComparisonTests(unittest.TestCase):
    def setUp(self):self.d=fixture()
    def test_source_order_not_global_rate_tier_or_input(self):
        r=compare_augments(self.d,'英雄甲',NAMES)
        self.assertEqual([c['name'] for c in r['cards']],['强化甲','强化乙','强化丙'])
        self.assertEqual(r['recommendedName'],'强化甲')
        self.assertEqual(r['cards'][0]['pairWinRate'],52)
        self.assertEqual(r['cards'][0]['slot'],3)
        self.assertEqual(r['cards'][0]['tier'],'T2')
        self.assertFalse(r['cards'][0]['globalRateUsedForRanking'])
    def test_hero_switch_changes_three(self):
        self.assertEqual(compare_augments(self.d,'英雄乙',NAMES)['recommendedName'],'强化丙')
    def test_missing_pair_never_infers_global(self):
        r=compare_augments(self.d,'英雄甲',['强化乙','强化甲','未收录配对'])
        self.assertIsNone(r['recommendedName']);self.assertFalse(r['completeComparison'])
        self.assertEqual(r['missingOfficialStats'],['未收录配对'])
        self.assertIsNone(r['cards'][-1]['pairWinRate'])
    def test_missing_or_zero_sample_prevents_definitive_recommendation(self):
        for field,value in [('winRate',None),('numGames',0),('numGames',None)]:
            with self.subTest(field=field,value=value):
                d=copy.deepcopy(self.d);d['heroAugmentStats']['英雄甲'][1][field]=value
                r=compare_augments(d,'英雄甲',NAMES)
                self.assertIsNone(r['recommendedName']);self.assertFalse(r['completeComparison'])
                self.assertEqual(r['insufficientStatistics'],['强化乙'])
                self.assertEqual(r['cards'][0]['officialRank'],1)
    def test_real_zero_rate_is_not_missing_if_samples_exist(self):
        self.d['heroAugmentStats']['英雄甲'][0]['winRate']=0
        self.assertEqual(compare_augments(self.d,'英雄甲',NAMES)['cards'][0]['pairWinRate'],0)
    def test_trap_conflicts_preserved_with_primary_stat(self):
        self.d['relations']['英雄甲']={'specialAugments':[{'name':'强化甲','reason':'联动','core':False}], 'trapAugments':[{'name':'强化甲','reason':'不触发','core':False}]}
        r=compare_augments(self.d,'英雄甲',NAMES)
        self.assertIsNone(r['recommendedName']);self.assertEqual(r['cards'][0]['category'],'conflict')
        self.assertEqual(r['cards'][0]['officialRank'],1);self.assertEqual(len(r['cards'][0]['trapEvidence']),1)
    def test_conditions_visible_not_assumed(self):
        self.d['relations']['英雄甲']={'specialAugments':[{'name':'强化甲','reason':'需要搭配装备，强度不高。','core':True}]}
        r=compare_augments(self.d,'英雄甲',NAMES)
        self.assertEqual(r['cards'][0]['category'],'conditional');self.assertIn('强度不高',r['cards'][0]['cautionFlags'])
    def test_invalid_offered(self):
        for values in [None,[],['强化甲'],['强化甲','强化乙'],NAMES+['未收录配对'],['强化甲']*3,['强化甲','强化乙',None],['强化甲','强化乙','不存在'],'甲乙丙']:
            with self.subTest(values=values),self.assertRaises(ValueError):compare_augments(self.d,'英雄甲',values)
    def test_unknown_hero(self):
        with self.assertRaises(ValueError):compare_augments(self.d,'不明',NAMES)
    def test_no_pair_stats_fallback_clearly_identified(self):
        self.d['heroAugmentStats']={}
        self.d['relations']['英雄甲']={'specialAugments':[{'name':'强化甲','reason':'明确联动','core':True}], 'trapAugments':[{'name':'强化乙','reason':'陷阱'}]}
        r=compare_augments(self.d,'英雄甲',NAMES)
        self.assertEqual(r['policy'],'hero-evidence-v1');self.assertEqual(r['recommendedName'],'强化甲')
        self.assertTrue(all(c['pairWinRate'] is None for c in r['cards']))
    def test_zero_global_rate_is_unspecified(self):
        self.d['augments']['强化甲']['winRate']=0
        self.assertIsNone(compare_augments(self.d,'英雄甲',NAMES)['cards'][0]['globalReferenceWinRate'])

class WikiAdapterTests(unittest.TestCase):
    def raw(self):
        return {'wiki':{'version':'fictional-test','championDetail':[{'championId':'test-1','championName':'演示称号 演示本名','version':'demo','date':'2000-01-01','winRate':'51.23%', 'augmentRecommendations':[{'augmentName':'强化甲','augmentId':'a','tier':'T2','winRate':'','pickRate':'1.23%','numGames':0},{'augmentName':'强化乙','augmentId':'b','tier':'T1','winRate':'63.04%','pickRate':'2.34%','numGames':200}]}], 'augmentDetail':[{'augmentName':'强化甲','augmentId':'a','rarity':'棱彩','description':'<b>文字</b><script>alert(1)</script>','winRate':'70%'}], 'itemDetail':{'装备甲':{'description':'<b>效果</b>'}}},'metadata':{'wikiBaseUrl':'https://example.test/'}}
    def test_percent_units_blank_and_samples_preserved(self):
        d=normalize(self.raw());rows=d['heroAugmentStats']['演示称号']
        self.assertEqual(d['heroes']['演示称号']['winRate'],51.23)
        self.assertIsNone(rows[0]['winRate']);self.assertEqual(rows[0]['numGames'],0)
        self.assertEqual(rows[1]['winRate'],63.04);self.assertEqual(rows[1]['pickRate'],2.34)
    def test_alias_catalog_gaps_and_assets(self):
        d=normalize(self.raw())
        self.assertIn('演示本名',d['heroes']['演示称号']['alias']);self.assertIn('强化乙',d['augments'])
        self.assertEqual(d['augments']['强化甲']['description'],'文字');self.assertNotIn('Icon',str(d))
        self.assertEqual(d['augments']['强化甲']['rarity'],'prismatic')
    def test_idempotent(self):
        d=normalize(self.raw());self.assertEqual(normalize(d),d)
    def test_percentage_rejects_invalid(self):
        for value in ['',None,True,'NaN%','110%',float('nan'),-1]:self.assertIsNone(percentage(value))
        self.assertEqual(percentage('0%'),0)
    def test_no_fixture_when_live_source_unavailable(self):
        with patch('data_updates.refresh_official_data',return_value={'data':None,'status':{'state':'unavailable'}}):
            result=load_startup_data(Path('/unused'))
        self.assertEqual(result['data']['heroes'],{});self.assertFalse(result['data']['metadata']['isDemo'])

class ComparisonHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server=make_server(fixture(),0);cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
    @classmethod
    def tearDownClass(cls):cls.server.shutdown();cls.server.server_close();cls.thread.join()
    def request(self,path,payload=None,origin=None):
        conn=HTTPConnection('127.0.0.1',self.server.server_port,timeout=3)
        headers={'Content-Type':'application/json'}
        if origin:headers['Origin']=origin
        conn.request('POST' if payload is not None else 'GET',path,json.dumps(payload) if payload is not None else None,headers)
        r=conn.getresponse();body=r.read();conn.close();return r.status,body
    def test_compare_http(self):
        status,body=self.request('/api/compare',{'hero':'英雄甲','offered':NAMES})
        self.assertEqual(status,200);self.assertEqual(json.loads(body)['recommendedName'],'强化甲')
    def test_invalid_and_cross_origin(self):
        self.assertEqual(self.request('/api/compare',{'hero':'英雄甲','offered':[]})[0],400)
        self.assertEqual(self.request('/api/compare',{'hero':'英雄甲','offered':NAMES},'https://evil.example')[0],403)
    def test_new_assets_and_status(self):
        for path in ['/choices.js','/favicon.ico','/brand.png','/api/status']:
            self.assertEqual(self.request(path)[0],200)
    def test_non_exe_update_install_rejected(self):
        self.assertEqual(self.request('/api/updates/install',{'confirmed':True,'version':'9.0.0'})[0],409)

if __name__=='__main__':unittest.main()

class UpdateExitRegression(unittest.TestCase):
    def test_disconnected_browser_does_not_prevent_shutdown_after_update_spawn(self):
        import time
        from http.client import RemoteDisconnected
        context={'state_dir':Path('/unused'),'current_executable':Path('/unused/app.exe'),'current_version':'0.3.0','frozen':True}
        release={'version':'0.4.0','notes':'test'}
        with patch('updates.check_for_update',return_value={'state':'available','release':release}), patch('updates.prepare_update',return_value=Path('/unused/plan.json')), patch('updates.launch_update') as launch:
            server=make_server(fixture(),0,update_context=context)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            try:
                original=server.RequestHandlerClass.send_json
                def disconnected(handler,status,payload):
                    if payload.get('state')=='restarting':raise BrokenPipeError('Synthetic browser closed')
                    return original(handler,status,payload)
                # Wait only for the injected local checker, never the network.
                for _ in range(100):
                    conn=HTTPConnection('127.0.0.1',server.server_port,timeout=2);conn.request('GET','/api/updates');r=conn.getresponse();state=json.loads(r.read())['state'];conn.close()
                    if state=='available':break
                    time.sleep(.01)
                with patch.object(server.RequestHandlerClass,'send_json',disconnected):
                    conn=HTTPConnection('127.0.0.1',server.server_port,timeout=2)
                    conn.request('POST','/api/updates/install',json.dumps({'confirmed':True,'version':'0.4.0'}),{'Content-Type':'application/json'})
                    with self.assertRaises(RemoteDisconnected):conn.getresponse()
                    conn.close();thread.join(3)
                launch.assert_called_once();self.assertFalse(thread.is_alive())
            finally:
                server.shutdown();server.server_close();thread.join()

import copy
from http.client import HTTPConnection
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from engine import load_data, normalize, plain, recommend
from import_data import import_directory, PATTERNS
from server import make_server

A = '星火共鸣（演示）'
STAFF = '星尘法杖（演示）'
CHARM = '回响护符（演示）'
HEART = '山峦之心（演示）'
BOOTS = '晨风长靴（演示）'


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.data = load_data(ROOT / 'fixtures/demo.json')

    def test_direct_score_100_and_special_94(self):
        result = {x['name']: x for x in recommend(self.data, A)['recommendations']}
        self.assertEqual(result[STAFF]['score'], 100)
        self.assertEqual(result[CHARM]['score'], 94)

    def test_duplicate_max_not_sum_and_preserves_evidence_core(self):
        result = recommend(self.data, A)['recommendations']
        staff = next(x for x in result if x['name'] == STAFF)
        self.assertEqual(sum(x['name'] == STAFF for x in result), 1)
        self.assertEqual(staff['score'], 100)
        self.assertTrue(staff['core'])
        self.assertEqual(len(staff['evidence']), 2)

    def test_branch_core_and_both_bonuses(self):
        self.data['augments'][A]['specialItems'] = []
        result = {x['name']:x for x in recommend(self.data,A)['recommendations']}
        self.assertEqual(result[CHARM]['score'], 49)
        self.assertEqual(result[BOOTS]['score'], 33)

    def test_parent_match_includes_unmatched_branch(self):
        result = {x['name']:x for x in recommend(self.data,A)['recommendations']}
        self.assertEqual(result[HEART]['score'], 39)

    def test_branch_only_match(self):
        self.data['combinations'][0]['augments'] = []
        self.data['augments'][A]['specialItems'] = []
        result = {x['name']:x for x in recommend(self.data,A)['recommendations']}
        self.assertEqual(result[CHARM]['score'], 44)
        self.assertEqual(result[BOOTS]['score'], 28)
        self.assertNotIn(HEART,result)

    def test_parent_items_not_scored_without_branches(self):
        self.data['combinations'] = [{'name':'parent','augments':[{'name':A}], 'items':[{'name':HEART,'core':True}], 'combinations':[]}]
        result = recommend(self.data,A)['recommendations']
        self.assertNotIn(HEART,[x['name'] for x in result])

    def test_traps_separate_and_conflicts_marked(self):
        result = recommend(self.data,A)
        self.assertEqual(len(result['warnings']),2)
        self.assertTrue(all(x['score']==100 and x['warning'] for x in result['warnings']))
        self.assertTrue(next(x for x in result['recommendations'] if x['name']==CHARM)['warning'])
        self.assertNotIn('静默披风（演示）',[x['name'] for x in result['recommendations']])

    def test_missing_items_excluded_and_reported(self):
        result = recommend(self.data,A)
        self.assertEqual(result['missingItems'],['不存在的装备（演示）'])
        self.assertNotIn('不存在的装备（演示）',[x['name'] for x in result['recommendations']])

    def test_missing_win_rate_stays_none(self):
        self.assertIsNone(self.data['heroes']['晴空游侠（演示）']['winRate'])
        self.assertIsNone(self.data['augments']['风步微光（演示）']['winRate'])
        self.assertIsNone(recommend(self.data,A)['pairWinRate'])

    def test_unknown_augment_raises_keyerror(self):
        with self.assertRaises(KeyError):recommend(self.data,'unknown')

    def test_html_and_assets_are_removed(self):
        self.assertEqual(plain('<script>bad()</script><p>Hello<br>world</p>'), 'Hello\nworld')
        raw={'heroes':{'x':{'avatar':'https://example.com/x.png'}},'augments':{},'items':{}}
        self.assertNotIn('avatar',normalize(raw)['heroes']['x'])

    def test_repeated_evidence_is_deduplicated(self):
        self.data['augments'][A]['items'] *= 3
        result = next(x for x in recommend(self.data,A)['recommendations'] if x['name']==STAFF)
        self.assertEqual(len(result['evidence']),2)

    def test_normalize_idempotent(self):
        self.assertEqual(self.data,normalize(self.data))

    def test_non_finite_values_treated_as_missing(self):
        raw={'heroes':{'a':{'winRate':float('nan')},'b':{'winRate':True}},'augments':{},'items':{}}
        self.assertIsNone(normalize(raw)['heroes']['a']['winRate'])
        self.assertIsNone(normalize(raw)['heroes']['b']['winRate'])

    def test_bad_schema_fails_clearly(self):
        with self.assertRaises(ValueError):normalize({'heroes':[]})


class ImportTests(unittest.TestCase):
    def test_import_uses_whitelist_and_refuses_overwrite(self):
        raw=json.loads((ROOT/'fixtures/demo.json').read_text(encoding='utf-8'))
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder)
            for kind,pattern in PATTERNS.items():
                (folder/pattern.replace('*','synthetic')).write_text(json.dumps(raw[kind]))
            (folder/'changelogs-synthetic.json').write_text(json.dumps({'last_update':'2020-01-01','data':[{'date':'2026-07-17'}]}))
            out=folder/'out.json'
            counts=import_directory(folder,out)
            self.assertEqual(counts['heroes'],4)
            self.assertEqual(json.loads(out.read_text(encoding='utf-8'))['metadata']['latestChangelogDate'],'2026-07-17')
            self.assertEqual(json.loads(out.read_text(encoding='utf-8'))['metadata']['dataFreshness'],'unknown')
            with self.assertRaises(FileExistsError):import_directory(folder,out)

    def test_ambiguous_source_fails(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):import_directory(Path(folder),Path(folder)/'out.json')


class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server=make_server(load_data(ROOT/'fixtures/demo.json'),0)
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True)
        cls.thread.start()
    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close();cls.thread.join()
    def request(self,path,host=None):
        conn=HTTPConnection('127.0.0.1',self.server.server_port,timeout=5)
        conn.request('GET',path,headers={'Host':host} if host else {})
        result=conn.getresponse();body=result.read();conn.close()
        return result,body
    def test_ui_and_assets(self):
        for path in ['/','/app.js','/style.css']:
            response,body=self.request(path)
            self.assertEqual(response.status,200)
            self.assertGreater(len(body),100)
            self.assertEqual(response.getheader('X-Content-Type-Options'),'nosniff')
            self.assertIn("default-src 'self'",response.getheader('Content-Security-Policy'))
    def test_data_api(self):
        response,body=self.request('/api/data')
        self.assertEqual(response.status,200)
        self.assertTrue(json.loads(body)['metadata']['isDemo'])
    def test_recommend_api(self):
        response,body=self.request('/api/recommend?augment='+quote(A))
        self.assertEqual(response.status,200)
        self.assertEqual(json.loads(body)['recommendations'][0]['score'],100)
    def test_unknown_augment_and_traversal(self):
        for path in ['/api/recommend?augment=bad','/../engine.py','/fixtures/demo.json','/private-data.json']:
            self.assertEqual(self.request(path)[0].status,404)
    def test_host_rebinding_guard(self):
        self.assertEqual(self.request('/',host='attacker.example')[0].status,403)
    def test_application_name_and_metadata(self):
        response,body=self.request('/')
        self.assertIn('VGA乱斗助手',body.decode('utf-8'))
        self.assertNotIn('海克斯手册',body.decode('utf-8'))
        response,body=self.request('/health')
        self.assertEqual(json.loads(body)['applicationName'],'VGA乱斗助手')
        from app_version import __version__
        self.assertEqual(json.loads(body)['applicationVersion'],__version__)
    def test_localhost_binding(self):
        self.assertEqual(self.server.server_address[0],'127.0.0.1')


if __name__=='__main__':unittest.main(verbosity=2)

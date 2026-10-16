"""Grade-only legacy browser boundary; synthetic data, no live client."""
import copy,json,threading,unittest,urllib.request
from engine import normalize
from public_payload import public_data,public_comparison,public_recommendation
from server import make_server

def fixture():
    return normalize({'metadata':{'isDemo':True,'sourceDataDate':'2000-01-01','nestedSecret':{'winRate':98.765}},
      'heroes':{'Hero':{'overallTier':'T5','winRate':98.765}},
      'augments':{n:{'overallTier':'T2','winRate':98.765} for n in ['A','B','C']},'items':{},
      'heroAugmentStats':{'Hero':[{'augmentName':n,'tier':tier,'winRate':98.765,'pickRate':42.123,'numGames':99999} for n,tier in [('C','T1'),('B','T4'),('A','UNKNOWN')]]}})

class GradeOnlyPayloadTests(unittest.TestCase):
    def assert_safe(self,value):
        if isinstance(value,dict):
            for k,v in value.items():
                self.assertNotIn('rate',k.lower());self.assertNotIn(k,('officialStats','numGames','recommendedName','officialRank'));self.assert_safe(v)
        elif isinstance(value,list):
            for x in value:self.assert_safe(x)
        self.assertNotIn('98.765',json.dumps(value));self.assertNotIn('42.123',json.dumps(value))
    def test_data_projection_is_nested_allowlist_without_mutating_internal_data(self):
        d=fixture();original=copy.deepcopy(d);d['augments']['A']['futureStats']={'winRate':98.765}
        v=public_data(d);self.assert_safe(v);self.assertEqual(v['heroes']['Hero']['overallTier'],'T5');self.assertIsNone(v['heroAugmentStats']['Hero'][-1]['tier']);self.assertEqual(d['heroes'],original['heroes'])
    def test_comparison_preserves_slots_and_literal_pair_grades(self):
        v=public_comparison(fixture(),'Hero',['A','B','C']);self.assert_safe(v)
        self.assertEqual([c['name'] for c in v['cards']],['A','B','C']);self.assertEqual([c['sourceTier'] for c in v['cards']],[None,'T4','T1'])
    def test_existing_validation_remains(self):
        for hero,names in [('unknown',['A','B','C']),('Hero',['A','A','C']),('Hero',['A','B'])]:
            with self.assertRaises(ValueError):public_comparison(fixture(),hero,names)
    def test_recommendation_allowlist_filters_nested_future_fields(self):
        v=public_recommendation({'pairWinRate':98.765,'recommendations':[{'name':'X','score':10,'winRate':98.765,'evidence':[{'score':10,'source':'fixture','winRate':98.765}]}]});self.assert_safe(v)
    def test_real_loopback_http_routes_apply_projection(self):
        server=make_server(fixture(),port=0);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            root='http://127.0.0.1:'+str(server.server_port)
            opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
            for path,body in [('/api/data',None),('/api/compare',{'hero':'Hero','offered':['A','B','C']}),('/api/recommend?augment=A',None)]:
                req=urllib.request.Request(root+path,data=json.dumps(body).encode() if body else None,headers={'Content-Type':'application/json'})
                with opener.open(req,timeout=3) as response:self.assert_safe(json.load(response))
        finally:server.shutdown();server.server_close();thread.join(3)

if __name__=='__main__':unittest.main()

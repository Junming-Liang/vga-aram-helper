import sys, unittest, threading, ssl
from pathlib import Path
from unittest.mock import patch, Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from lcu_selection import *

def inputs():
    return 'ChampSelect', {'gameData': {'queue': {'id': 2400}}}, {'localPlayerCellId': 2, 'myTeam': [{'cellId': 2, 'championId': 31, 'summonerName':'PRIVATE'}, {'cellId':3,'championId':99}], 'benchChampions':[{'championId':1}]}

class LCUTests(unittest.TestCase):
    def test_exact_own_and_bench(self):
        x=selection_observation(*inputs());self.assertEqual(x['championId'],'31');self.assertEqual(x['benchChampionIds'],('1',));self.assertNotIn('PRIVATE',str(x))
    def test_ordinary_aram_is_not_mayhem(self):
        a,b,c=inputs();b['gameData']['queue']['id']=450;self.assertFalse(selection_observation(a,b,c)['assigned'])
    def test_unassigned_not_hover(self):
        a,b,c=inputs();c['myTeam'][0].update(championId=0,championPickIntent=22);x=selection_observation(a,b,c);self.assertFalse(x['assigned']);self.assertIsNone(x['championId'])
    def test_no_or_ambiguous_self(self):
        for rows in [[],[{'cellId':2,'championId':31}]*2]:
            a,b,c=inputs();c['myTeam']=rows;self.assertFalse(selection_observation(a,b,c)['assigned'])
    def test_bad_types(self):
        for bad in [True,'31',-1,0,1e5,None]:
            a,b,c=inputs();c['myTeam'][0]['championId']=bad;self.assertFalse(selection_observation(a,b,c)['assigned'])
    def test_wrong_phase(self):
        a,b,c=inputs();self.assertEqual(selection_observation('InProgress',b,c)['scene'],'unknown')
    def test_credentials_hidden_and_strict(self):
        self.assertEqual(parse_lockfile(b'LeagueClient:12:12345:synthetic+/token=:https').port,12345)
        x=parse_lockfile(b'LeagueClient:12:12345:synthetic_token:https');self.assertNotIn('synthetic_token',repr(x))
        for raw in [b'',b'LeagueClient:12:443:x:http',b'RiotClient:12:443:abcdefgh:https',b'LeagueClient:12:65536:abcdefgh:https',b'x'*1025]:
            with self.assertRaises(LCUUnavailable):parse_lockfile(raw)
    def test_stable_swap_expiry_scope(self):
        x=selection_observation(*inputs());s=SelectionSnapshot();s.observe(x,'scope',10.,10.1);self.assertIsNone(s.current('scope',10.2));s.observe(x,'scope',11.,11.1);self.assertIsNotNone(s.current('scope',11.2));self.assertIsNone(s.current('other',11.2));self.assertIsNone(s.current('scope',15.1));x['benchChampionIds']=('2',);s.observe(x,'scope',12.,12.1);self.assertIsNone(s.current('scope',12.2))
    def test_unknown_revokes(self):
        x=selection_observation(*inputs());s=SelectionSnapshot();s.observe(x,'scope',10.,10.1);s.observe(x,'scope',11.,11.1);s.observe({},'scope',12.,12.1);self.assertIsNone(s.current('scope',12.2))
    def test_literal_source_tier_only(self):
        from data_updates import WIKI_PAGE
        d={'metadata':{'officialHeroStatistics':True,'sourceUrl':WIKI_PAGE},'heroes':{'Cho':{'championId':'31','overallTier':'T3'}}};x=selection_observation(*inputs());r=selection_reference(d,x);self.assertEqual(r['selectionRows'][0][1][0]['sourceTier'],'T3');self.assertEqual(r['selectionRows'][1][1],[])
    def reader(self):
        from session_windows import ProcessMetadata
        return LocalSelectionReader(ProcessMetadata(r'C:\League\LeagueClientUx.exe',1),resolver=lambda pid:ProcessMetadata(r'c:\league\leagueclient.exe',2),clock=lambda:1.)
    def test_transport_exact_get_loopback_no_redirect(self):
        reader=self.reader(); response=Mock(status=302);connection=Mock();connection.getresponse.return_value=response
        with patch('lcu_selection.http.client.HTTPSConnection',return_value=connection) as ctor:
            with self.assertRaises(LCUUnavailable):reader._get(Credentials(12,1234,'synthetic_token'),'/lol-champ-select/v1/session',Mock(),2.,threading.Event())
        self.assertEqual(ctor.call_args.args,('127.0.0.1',1234));self.assertEqual(connection.request.call_args.args,('GET','/lol-champ-select/v1/session'));connection.close.assert_called_once()
    def test_non_allowlist_no_connection(self):
        with patch('lcu_selection.http.client.HTTPSConnection') as ctor:
            with self.assertRaises(LCUUnavailable):self.reader()._get(Credentials(12,1234,'synthetic_token'),'/lol-item-sets/v1/item-sets',Mock(),2.,threading.Event())
            ctor.assert_not_called()
    def test_vendor_ca_verifies_by_default(self):
        c=ssl.create_default_context(cafile=str(Path(__file__).resolve().parents[1]/'assets/riotgames.pem'));self.assertTrue(c.check_hostname);self.assertEqual(c.verify_mode,ssl.CERT_REQUIRED)


class LCUReadBoundaryTests(unittest.TestCase):
    reader=LCUTests.reader
    def read_with(self, values, *, resolver=None, raw_after=None, get_error=None, cancelled=None):
        import io
        reader=self.reader()
        if resolver:reader.resolver=resolver
        raw=b'LeagueClient:12:12345:synthetic_token:https'
        streams=[io.BytesIO(raw),io.BytesIO(raw if raw_after is None else raw_after)]
        with patch('lcu_selection.Path.open',side_effect=streams),patch.object(reader,'_get',side_effect=get_error or values):
            return reader.read(cancelled=cancelled or threading.Event())
    def test_success_minimizes(self):
        a,b,c=inputs();result=self.read_with([a,b,c,a]);self.assertEqual(result['championId'],'31');self.assertNotIn('PRIVATE',str(result))
    def test_phase_transition_abstains(self):
        a,b,c=inputs();self.assertFalse(self.read_with([a,b,c,'InProgress'])['assigned'])
    def test_tls_error_is_sanitized(self):
        with self.assertRaises(LCUUnavailable) as error:self.read_with([],get_error=ssl.SSLCertVerificationError('synthetic_token PRIVATE'))
        self.assertEqual(str(error.exception),'local_client_unavailable')
    def test_lockfile_rotation_rejected(self):
        a,b,c=inputs()
        with self.assertRaises(LCUUnavailable):self.read_with([a,b,c,a],raw_after=b'LeagueClient:12:12345:different_token:https')
    def test_metadata_rotation_rejected(self):
        from session_windows import ProcessMetadata
        a,b,c=inputs();values=iter([ProcessMetadata(r'c:\league\leagueclient.exe',1),ProcessMetadata(r'c:\league\leagueclient.exe',2)])
        with self.assertRaises(LCUUnavailable):self.read_with([a,b,c,a],resolver=lambda pid:next(values))
    def test_cancelled_has_no_read(self):
        event=threading.Event();event.set()
        with patch('lcu_selection.Path.open') as opened:
            with self.assertRaises(LCUUnavailable):self.reader().read(cancelled=event)
        opened.assert_not_called()
    def test_bounded_payload_and_trickle(self):
        for oversized in (True,False):
            reader=self.reader();response=Mock(status=200);connection=Mock();connection.getresponse.return_value=response
            if oversized:response.read1.side_effect=[b'x'*16384]*33
            else:
                ticks=iter([1.,1.1,1.2,3.]);reader.clock=lambda:next(ticks);response.read1.side_effect=[b'a',b'b',b'c']
            with patch('lcu_selection.http.client.HTTPSConnection',return_value=connection):
                with self.assertRaises(LCUUnavailable):reader._get(Credentials(12,1234,'synthetic_token'),'/lol-champ-select/v1/session',Mock(),2.,threading.Event())
            connection.close.assert_called_once()

class LCURestartTests(unittest.TestCase):
    def test_client_restart_resets_snapshot_stability(self):
        value=selection_observation(*inputs());value['_lcuInstance']=(12,100,0)
        state=SelectionSnapshot();state.observe(value,'window',10.,10.1)
        value['_lcuInstance']=(12,200,0);state.observe(value,'window',11.,11.1)
        self.assertIsNone(state.current('window',11.2));state.observe(value,'window',12.,12.1)
        self.assertIsNotNone(state.current('window',12.2))

if __name__=='__main__':unittest.main()

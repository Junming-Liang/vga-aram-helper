import json
import ssl
import threading
import unittest
from unittest.mock import patch
import live_client_identity as live

MAP = {'Annie': '1', 'MonkeyKing': '62'}
NAME = 'Mock Player#TEST'
def row(slug='Annie', name=NAME):
    return {'riotId': name, 'rawChampionName': live.PREFIX + slug,
            'championName': '任意本地化名称', 'isDead': True, 'skinID': 99}

class PayloadTests(unittest.TestCase):
    def test_exact_canonical_mapping_ignores_skin_death_localization(self):
        self.assertEqual(live.identity_from_payload(NAME, [row()], MAP), '1')
        self.assertEqual(live.identity_from_payload(NAME, [row('MonkeyKing')], MAP), '62')
    def test_unknown_ambiguous_and_legacy_names_rejected(self):
        for players in ([row(),row()], [], [row('Unknown')], [None],
                        [{'summonerName': NAME, 'rawChampionName': live.PREFIX+'Annie'}],
                        [dict(row(), rawChampionName='Annie')],
                        [dict(row(), riotIdGameName='Other', riotIdTagLine='TEST')]):
            self.assertIsNone(live.identity_from_payload(NAME, players, MAP))
    def test_exact_no_fuzzy_matching(self):
        self.assertIsNone(live.identity_from_payload(NAME.lower(), [row()], MAP))
        self.assertIsNone(live.identity_from_payload(NAME, [row('annie')], MAP))
        self.assertIsNone(live.identity_from_payload(NAME, [row()], {'Annie': True}))
        self.assertIsNone(live.identity_from_payload(NAME, [row()], {'Annie':'1','Other':'1'}))

class ReaderTests(unittest.TestCase):
    def call(self, **kw):
        defaults = dict(enabled=True, cancelled=threading.Event(), scope_probe=lambda: (8, 'created-at'))
        defaults.update(kw)
        return live.read_current_identity(MAP, **defaults)
    def test_off_does_not_touch_network_scope_or_ca(self):
        with patch.object(live.ssl, 'create_default_context') as ctx, patch.object(live, '_get') as get:
            self.assertIsNone(self.call(enabled=False, scope_probe=lambda: self.fail()))
            ctx.assert_not_called(); get.assert_not_called()
    def test_fresh_minimal_output_no_retention(self):
        with patch.object(live.ssl, 'create_default_context', return_value=ssl.create_default_context()), patch.object(live, '_get', side_effect=[NAME,[row()],NAME,[row()]]):
            self.assertEqual(self.call(), {'championId':'1','confident':True,'method':'game-client-api'})
    def test_mismatch_restart_failure_and_timeout_invalidate(self):
        cases = ([NAME,[row()], 'Other#TEST',[row(name='Other#TEST')]],
                 [NAME,[row()],NAME,[row('MonkeyKing')]],
                 [NAME,[row()],NAME,[row(),row()]], OSError('private payload'))
        for values in cases:
            with patch.object(live.ssl, 'create_default_context', return_value=ssl.create_default_context()), patch.object(live, '_get', side_effect=values):
                self.assertIsNone(self.call())
        for scopes in ([None], [(1,2),(1,3)]):
            with patch.object(live.ssl, 'create_default_context', return_value=ssl.create_default_context()), patch.object(live, '_get', side_effect=[NAME,[row()],NAME,[row()]]):
                self.assertIsNone(self.call(scope_probe=unittest.mock.Mock(side_effect=scopes)))
    def test_no_cache_after_success(self):
        with patch.object(live.ssl, 'create_default_context', return_value=ssl.create_default_context()), patch.object(live, '_get', side_effect=[NAME,[row()],NAME,[row()],OSError('failure')]):
            self.assertIsNotNone(self.call()); self.assertIsNone(self.call())
    def test_insecure_context_and_cancellation_rejected(self):
        with patch.object(live.ssl, 'create_default_context', return_value=ssl._create_unverified_context()), patch.object(live, '_get') as get:
            self.assertIsNone(self.call()); get.assert_not_called()
        stop=threading.Event();stop.set()
        with patch.object(live, '_get') as get:
            self.assertIsNone(self.call(cancelled=stop));get.assert_not_called()

class Response:
    def __init__(self, body, status=200, headers=None):
        self.body=body;self.status=status;self.headers=headers or {}
    def getheader(self,k,d=None): return self.headers.get(k,d)
    def read1(self,n):
        chunk=self.body[:n];self.body=self.body[n:];return chunk
class Connection:
    sock=None
    def __init__(self,response):self.response=response;self.calls=[];self.closed=False
    def request(self,*args,**kwargs):self.calls.append((args,kwargs))
    def getresponse(self):return self.response
    def close(self):self.closed=True

class TransportTests(unittest.TestCase):
    def get(self, response, path='/liveclientdata/activeplayername', clock=lambda:0):
        connection=Connection(response)
        with patch.object(live.http.client,'HTTPSConnection',return_value=connection) as factory:
            value=live._get(path,ssl.create_default_context(),1,threading.Event(),clock)
            self.assertEqual(factory.call_args.args, ('127.0.0.1',2999))
            self.assertEqual(connection.calls,[(('GET',path),{'headers':{'Accept':'application/json'}})])
            self.assertTrue(connection.closed)
            return value
    def test_direct_endpoint(self):self.assertEqual(self.get(Response(json.dumps(NAME).encode())),NAME)
    def test_no_redirect_errors_oversize_compression_malformed(self):
        for response in (Response(b'"name"',302),Response(b'',500),Response(b'x'*(live.MAX_RESPONSE+1)),
                         Response(b'{}',headers={'Content-Length':str(live.MAX_RESPONSE+1)}),
                         Response(b'{}',headers={'Content-Encoding':'gzip'}),Response(b'{'),
                         Response(b'{"riotId":"one","riotId":"two"}'),Response(b'NaN')):
            with self.assertRaises(Exception):self.get(response)
    def test_allowlist_and_deadline(self):
        for path in ('https://evil.test/', '/liveclientdata/playerlist?name=x', '/allgamedata'):
            with self.assertRaises(ValueError):self.get(Response(b'{}'),path)
        with self.assertRaises(ValueError):self.get(Response(b'{}'),clock=lambda:2)


class CompatibilityTests(unittest.TestCase):
    def test_documented_legacy_name_exact_and_unique(self):
        from live_client_identity import identity_from_payload
        row={'summonerName':'Riot Tuxedo','rawChampionName':'game_character_displayname_Ahri'}
        self.assertEqual(identity_from_payload('Riot Tuxedo',[row],{'Ahri':'103'}),'103')
        self.assertIsNone(identity_from_payload('Riot Tuxedo',[row,row],{'Ahri':'103'}))
        self.assertIsNone(identity_from_payload('Riot Tuxedo',[{**row,'riotIdGameName':'different'}],{'Ahri':'103'}))
    def test_source_ids_must_be_unique(self):
        from live_client_identity import source_hero_names,reconcile_identity
        names=source_hero_names({'heroes':{'first':{'championId':'103'},'second':{'championId':'103'},'unique':{'championId':'31'}}})
        self.assertEqual(names,{'31':'unique'})
        self.assertFalse(reconcile_identity({'confident':False},{'championId':'103','confident':True},names)['confident'])
    def test_reconcile_fresh_identity_and_conflicts(self):
        from live_client_identity import reconcile_identity
        api={'championId':'103','confident':True,'method':'game-client-api'}
        self.assertEqual(reconcile_identity({'confident':False},api,{'103':'Ahri'})['hero'],'Ahri')
        self.assertFalse(reconcile_identity({'confident':True,'championId':'31'},api,{'103':'Ahri'})['confident'])
        self.assertEqual(reconcile_identity({'confident':True,'championId':'103'},api,{'103':'Ahri'})['method'],'game-client-api')
        hud={'confident':False,'reason':'unknown'};self.assertEqual(reconcile_identity(hud,None,{}),hud)

class LegacyConflictTests(unittest.TestCase):
    def test_present_modern_identity_must_corroborate_legacy_name(self):
        base={'summonerName':'Bob','rawChampionName':live.PREFIX+'Ahri'}
        for value in ('Alice#TAG','Bob','Bob#','Bob#TAG#extra',None,5):
            with self.subTest(value=value):
                self.assertIsNone(live.identity_from_payload('Bob',[dict(base,riotId=value)],{'Ahri':'103'}))
        self.assertEqual(live.identity_from_payload('Bob',[dict(base,riotId='Bob#TAG')],{'Ahri':'103'}),'103')
        self.assertIsNone(live.identity_from_payload('Bob',[dict(base,riotId='Bob#TAG',riotIdTagLine='other')],{'Ahri':'103'}))
        self.assertIsNone(live.identity_from_payload('Bob',[dict(base,riotIdTagLine='TAG')],{'Ahri':'103'}))

if __name__ == '__main__': unittest.main()

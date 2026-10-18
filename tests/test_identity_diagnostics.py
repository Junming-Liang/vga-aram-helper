"""Fixed causes only; owned payloads/pixels and no actual client/network."""
import http.client
import json
import ssl
import threading
import unittest
from unittest.mock import Mock,patch
import live_client_identity as live
from tests.test_live_client_identity import Connection,Response

MAP={'OwnedOne':'1','OwnedTwo':'2'}
NAME='PRIVATE_SYNTHETIC_PLAYER#OWNED'
def player(slug='OwnedOne',name=NAME):
    return {'riotId':name,'rawChampionName':live.PREFIX+slug,'private':'PRIVATE_PAYLOAD'}
def batch(slug='OwnedOne',name=NAME):return [name,[player(slug,name)],name,[player(slug,name)]]


class IdentityDiagnosticTests(unittest.TestCase):
    def call(self,values=None,**options):
        self.codes=[]
        args=dict(enabled=True,cancelled=threading.Event(),scope_probe=lambda:(1,10),diagnostic_callback=self.codes.append)
        args.update(options)
        with patch.object(live.ssl,'create_default_context',return_value=ssl.create_default_context()),patch.object(live,'_get',side_effect=batch() if values is None else values):
            value=live.read_current_identity(MAP,**args)
        self.assertEqual(len(self.codes),1);self.assertIn(self.codes[0],live.API_OUTCOMES)
        self.assertNotIn('PRIVATE',repr(self.codes))
        return value

    def test_schema_player_mapping_and_two_read_failures_have_distinct_codes(self):
        cases=(([None,[player()]],'payload_invalid'),([NAME,[]],'payload_invalid'),
               ([NAME,[player(name='different')]],'active_player_mismatch'),
               ([NAME,[player(),player()]],'active_player_mismatch'),
               ([NAME,[dict(player(),riotIdGameName='other',riotIdTagLine='OWNED')]],'active_player_mismatch'),
               ([NAME,[dict(player(),rawChampionName='PRIVATE_raw')]],'payload_invalid'),
               ([NAME,[player('Unknown')]],'champion_unmapped'),
               (batch()[:2]+batch('OwnedTwo')[2:],'unstable'),
               (batch()[:2]+batch(name='OTHER#OWNED')[2:],'unstable'))
        for values,code in cases:
            with self.subTest(code=code):self.assertIsNone(self.call(values));self.assertEqual(self.codes,[code])

    def test_disabled_cancelled_and_bad_map_do_not_touch_network_scope_or_ca(self):
        stop=threading.Event();stop.set()
        for enabled,mapping,cancelled,code in ((False,MAP,threading.Event(),'disabled'),
                (True,{},threading.Event(),'map_invalid'),(True,MAP,stop,'cancelled')):
            codes=[]
            with patch.object(live,'_get') as get,patch.object(live.ssl,'create_default_context') as ctx:
                result=live.read_current_identity(mapping,enabled=enabled,cancelled=cancelled,
                    scope_probe=lambda:self.fail('Unexpected scope probe'),diagnostic_callback=codes.append)
            self.assertIsNone(result);self.assertEqual(codes,[code]);get.assert_not_called();ctx.assert_not_called()

    def test_transport_exception_codes_do_not_parse_exception_messages(self):
        for error,code in ((ssl.SSLCertVerificationError('PRIVATE_TLS'),'tls_verification_failed'),
                (TimeoutError('PRIVATE_timeout'),'timeout'),(ConnectionRefusedError('PRIVATE_address'),'connection_failed'),
                (http.client.RemoteDisconnected('PRIVATE_body'),'connection_failed'),(RuntimeError('PRIVATE_internal'),'unexpected_error')):
            with self.subTest(code=code):self.assertIsNone(self.call(error));self.assertEqual(self.codes,[code])

    def test_scope_restart_timeout_and_context_failures(self):
        for probe,code in ((lambda:None,'scope_unavailable'),(Mock(side_effect=OSError('PRIVATE_scope')),'scope_unavailable'),
                           (Mock(side_effect=[(1,10),(1,11)]),'scope_changed')):
            self.assertIsNone(self.call(scope_probe=probe));self.assertEqual(self.codes,[code])
        self.assertIsNone(self.call(clock=Mock(side_effect=[10.,11.8])));self.assertEqual(self.codes,['timeout'])
        for context in (OSError('PRIVATE_CA'),ssl._create_unverified_context()):
            codes=[]
            with patch.object(live.ssl,'create_default_context',**({'side_effect':context} if isinstance(context,Exception) else {'return_value':context})),patch.object(live,'_get') as get:
                result=live.read_current_identity(MAP,enabled=True,cancelled=threading.Event(),scope_probe=lambda:(1,10),diagnostic_callback=codes.append)
            self.assertIsNone(result);self.assertEqual(codes,['tls_context_failed']);get.assert_not_called()

    def test_http_parser_limit_codes_from_actual_get_and_close(self):
        cases=((Response(b'',302),'http_error'),(Response(b'',503),'http_error'),
               (Response(b'{}',headers={'Content-Encoding':'gzip'}),'response_invalid'),
               (Response(b'{}',headers={'Content-Length':str(live.MAX_RESPONSE+1)}),'response_invalid'),
               (Response(b'{"x":1,"x":2}'),'response_invalid'),(Response(b'NaN'),'response_invalid'),
               (Response(b'\xff'),'response_invalid'),(Response(b'{'),'response_invalid'))
        for response,code in cases:
            connection=Connection(response);codes=[]
            with patch.object(live.http.client,'HTTPSConnection',return_value=connection),patch.object(live.ssl,'create_default_context',return_value=ssl.create_default_context()):
                result=live.read_current_identity(MAP,enabled=True,cancelled=threading.Event(),scope_probe=lambda:(1,10),diagnostic_callback=codes.append)
            self.assertIsNone(result);self.assertEqual(codes,[code]);self.assertTrue(connection.closed)

    def test_fresh_games_and_callback_failures_never_reuse_identity(self):
        self.assertEqual(self.call()['championId'],'1');self.assertEqual(self.codes,['verified'])
        self.assertIsNone(self.call(ConnectionRefusedError('PRIVATE_new_game')))
        self.assertEqual(self.call(batch('OwnedTwo'),scope_probe=lambda:(1,11))['championId'],'2')
        with patch.object(live.ssl,'create_default_context',return_value=ssl.create_default_context()),patch.object(live,'_get',side_effect=batch()):
            result=live.read_current_identity(MAP,enabled=True,cancelled=threading.Event(),scope_probe=lambda:(1,10),
                diagnostic_callback=Mock(side_effect=RuntimeError('PRIVATE_diagnostic')))
        self.assertEqual(result,{'championId':'1','confident':True,'method':'game-client-api'})

    def test_reconciliation_codes_preserve_decisions_and_malformed_fallback(self):
        api={'championId':'1','confident':True,'method':'game-client-api'}
        cases=(({'confident':False},None,{'1':'Owned'},'hud_abstained',False),
               ({'confident':True,'championId':'1'},None,{'1':'Owned'},'hud_verified',True),
               ({'confident':False},api,{'1':'Owned'},'api_verified',True),
               ({'confident':True,'championId':'2'},api,{'1':'Owned'},'api_hud_conflict',False),
               ({'confident':False},api,{},'source_unmapped',False))
        for hud,value,names,code,confident in cases:
            codes=[];result=live.reconcile_identity(hud,value,names,diagnostic_callback=codes.append)
            self.assertEqual(codes,[code]);self.assertIs(result['confident'],confident)
            if value is None:self.assertIs(result,hud)
        for hud in (None,[],'PRIVATE_invalid'):
            codes=[];self.assertIs(live.reconcile_identity(hud,None,{},diagnostic_callback=codes.append),hud)
            self.assertEqual(codes,['hud_abstained'])


try:
    import cv2
    import numpy as np
    from PIL import Image
except ImportError:cv2=None

@unittest.skipIf(cv2 is None,'Optional OpenCV unavailable')
class HUDDiagnosticTests(unittest.TestCase):
    def test_existing_hud_gates_keep_thresholds_and_fixed_codes(self):
        from dataclasses import replace
        from hero_recognition import PortraitMatcher,hud_identity_outcome,HUD_OUTCOMES
        from synthetic_vision import portraits,frame,encoded
        bank=portraits();heroes={'Owned '+k:{'championId':k} for k in bank};matcher=PortraitMatcher(bank,heroes)
        good=encoded(frame(bank['9001']));prepared=matcher._prepare_array(np.asarray(frame(bank['9001'])))
        cases=((matcher.recognize(good),'recognized'),(matcher.recognize(None),'invalid_image'),
               (matcher.recognize(encoded(Image.new('RGB',(900,1200),(40,50,60)))),'unsupported_layout'),
               (matcher.recognize(encoded(Image.new('RGB',(1280,720)))),'letterboxed'),
               (PortraitMatcher({},{}).recognize(good),'templates_unavailable'),
               (PortraitMatcher({'9001':bank['9001']},heroes).recognize(good),'incomplete_templates'),
               (matcher.recognize(encoded(Image.new('RGB',(1280,720),(24,42,62)))),'score_low'),
               (PortraitMatcher({'9001':bank['9001'],'9002':bank['9001']},heroes).recognize(good),'margin_low'),
               (matcher.recognize(encoded(frame(bank['9001'],gray=True))),'death_grayscale'),
               (matcher._recognize_prepared(replace(prepared,rgb=255-prepared.rgb)),'color_mismatch'),
               (PortraitMatcher(bank,{}).recognize(good),'champion_unmapped'))
        for result,code in cases:
            with self.subTest(code=code):
                self.assertEqual(hud_identity_outcome(result),code);self.assertIn(code,HUD_OUTCOMES)
                self.assertIs(result['confident'],code=='recognized')
        self.assertEqual((matcher.minimum_score,matcher.minimum_margin),(.88,.07))
        self.assertEqual(hud_identity_outcome({'hudOutcome':'PRIVATE_payload','reason':'PRIVATE_text'}),'unknown')

if __name__=='__main__':unittest.main()

"""Production resolver + real local-API transport, with owned HTTP/Qt fakes."""
import hashlib
import json
import ssl
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile
from tests import test_native_capture_worker as fixtures
from tests.test_identity_diagnostics import NAME,player
from tests.test_live_client_identity import Connection,Response


def write_roster(cache):
    cache.mkdir(parents=True,exist_ok=True)
    raw=json.dumps({'version':'16.20.1','data':{str(i):{'key':str(i),'id':'Owned'+str(i),
        'image':{'full':'Owned'+str(i)+'.png'}} for i in range(1,101)}}).encode()
    path=cache/'roster-16.20.1.json';path.write_bytes(raw)
    (cache/'manifest.json').write_text(json.dumps({'version':'16.20.1','rosterSha256':hashlib.sha256(raw).hexdigest()}))
    return path


def connections(slug='Owned1'):
    return [Connection(Response(json.dumps(p).encode())) for p in (NAME,[player(slug)],NAME,[player(slug)])]


@unittest.skipIf(fixtures.QtWidgets is None,'Qt unavailable')
class NativeIdentityDiagnosticTests(unittest.TestCase):
    setUpClass=classmethod(fixtures.NativeCaptureWorkerTests.setUpClass.__func__)
    setUp=fixtures.NativeCaptureWorkerTests.setUp
    wait=fixtures.NativeCaptureWorkerTests.wait
    dispose_window=fixtures.NativeCaptureWorkerTests.dispose_window

    def prepare(self):
        from screen_capture import ClientRect
        from session_windows import ProcessMetadata
        w=self.window;self.meta=ProcessMetadata('C:/PRIVATE/League of Legends.exe',12345)
        self.hero=next(iter(w.data['heroes']));w.data['heroes'][self.hero]['championId']='1'
        w.automatic_policy=SimpleNamespace(bound=SimpleNamespace(role='game',metadata=self.meta),stop=lambda:None)
        w.capture_metadata=lambda:self.meta
        class Capture:
            last_backend='window-dc'
            def capture(inner,*args,**kwargs):return b'PRIVATE_SYNTHETIC_IMAGE',ClientRect(0,0,1280,720)
        w.capture=Capture();write_roster(w.state_dir/'hero-portraits')
        self.raw={'hero':None,'championId':None,'confident':False,'method':'own-hud-portrait',
                  'hudOutcome':'score_low','abstentionKind':'portrait-unavailable'}
        self.resolved=[];return w

    def events(self):
        archive=self.window.debug_log.export_zip(self.window.state_dir/'test-export',config={})
        with zipfile.ZipFile(archive) as log:
            text='\n'.join(log.read(n).decode() for n in log.namelist())
            rows=[json.loads(line) for line in log.read('events.jsonl').splitlines()]
            rows.extend(json.loads(line) for line in log.read('context.jsonl').splitlines())
        self.assertNotIn('PRIVATE_',text);self.assertNotIn(NAME,text)
        return sorted({r['sequence']:r for r in rows}.values(),key=lambda r:r['sequence'])

    def identity(self):return [r for r in self.events() if r['event']=='identity'][-1]

    def run_frame(self,*,http=None,hud=None,fail_ocr=False,metadata=None):
        w=self.window;raw=dict(self.raw if hud is None else hud)
        def recognize(image,roi,ocr,vocabulary,matcher,*,before_match,before_ocr,resolve_hero=None,**kwargs):
            before_match(None,b'PRIVATE_SYNTHETIC_CROP')
            resolved=resolve_hero(raw) if resolve_hero else raw;self.resolved.append(resolved)
            before_ocr(resolved,b'PRIVATE_SYNTHETIC_CROP')
            if fail_ocr:raise RuntimeError('PRIVATE_later_ocr_failure')
            return {'hero_observation':resolved,'automatic_candidates':[],'candidates':[]}
        with patch('hero_recognition.recognize_frame',side_effect=recognize), \
                patch('session_windows.process_metadata',return_value=self.meta if metadata is None else metadata) as probe, \
                patch('live_client_identity.ssl.create_default_context',return_value=ssl.create_default_context()) as tls, \
                patch('live_client_identity.http.client.HTTPSConnection',side_effect=connections() if http is None else http) as factory:
            w.capture_hidden(w.state.generation);self.wait(lambda:not w.ocr_busy and not w._workers)
        return factory,probe,tls

    def test_actual_four_request_reader_is_logged_before_later_ocr_failure(self):
        w=self.prepare();owned=connections();factory,probe,_=self.run_frame(http=owned,fail_ocr=True)
        self.assertEqual(factory.call_count,4);self.assertEqual(probe.call_count,2)
        self.assertTrue(all(c.closed for c in owned))
        self.assertEqual([c.calls[0][0] for c in owned],[('GET','/liveclientdata/activeplayername'),('GET','/liveclientdata/playerlist')]*2)
        for call in factory.call_args_list:
            self.assertEqual(call.args,('127.0.0.1',2999))
            self.assertEqual(call.kwargs['context'].verify_mode,ssl.CERT_REQUIRED);self.assertTrue(call.kwargs['context'].check_hostname)
        row=self.identity()
        self.assertEqual(tuple(row[k] for k in ('api_outcome','map_outcome','hud_outcome','identity_outcome')),
                         ('verified','verified','score_low','api_verified'))
        self.assertEqual(self.resolved[-1]['hero'],self.hero)
        errors=[r for r in self.events() if r.get('phase')=='error']
        self.assertTrue(any(r['sequence']>row['sequence'] and r.get('serial')==row['serial'] for r in errors))
        self.assertFalse(w.state.confirmed)

    def test_failure_hud_fallback_conflict_and_unmapped_source_remain_separate(self):
        w=self.prepare();hud={'hero':self.hero,'championId':'1','confident':True,'method':'own-hud-portrait','hudOutcome':'recognized'}
        self.run_frame(http=ConnectionRefusedError('PRIVATE_transport'),hud=hud)
        row=self.identity();self.assertEqual((row['api_outcome'],row['identity_outcome']),('connection_failed','hud_verified'))
        self.assertEqual(self.resolved[-1],hud)
        self.run_frame(hud={**hud,'championId':'2'})
        self.assertEqual(self.identity()['identity_outcome'],'api_hud_conflict');self.assertFalse(self.resolved[-1]['confident'])
        w.data['heroes'][self.hero]['championId']='3';self.run_frame()
        self.assertEqual(self.identity()['identity_outcome'],'source_unmapped');self.assertFalse(self.resolved[-1]['confident'])

    def test_disabled_manual_and_unverified_paths_never_touch_api_scope_or_ca(self):
        w=self.prepare()
        for mode in ('disabled','manual','unverified'):
            with self.subTest(mode=mode):
                if mode=='disabled':w.live_identity_toggle.setChecked(False)
                elif mode=='manual':w.live_identity_toggle.setChecked(True);w.hero_auto.setChecked(False)
                else:w.hero_auto.setChecked(True);w.automatic_policy=None
                w.state.start(w.target.identity);factory,probe,tls=self.run_frame()
                factory.assert_not_called();probe.assert_not_called();tls.assert_not_called()
                row=self.identity();self.assertEqual((row['api_outcome'],row['map_outcome']),('disabled','not_requested'))

    def test_two_game_transport_failure_and_new_identity_cannot_carry_previous_seed(self):
        from session_windows import ProcessMetadata
        w=self.prepare();second=list(w.data['heroes'])[1];w.data['heroes'][second]['championId']='2'
        self.run_frame();self.run_frame()
        self.assertEqual(w.state.hero,self.hero);self.assertEqual(w.hero_continuity.hero,self.hero)
        seed=w.hero_continuity.verified_at;old=self.identity()
        self.meta=ProcessMetadata(self.meta.path,self.meta.created+1);w.automatic_policy.bound.metadata=self.meta
        w.debug_log.begin_game();self.run_frame(http=ConnectionRefusedError('PRIVATE_second_game'))
        row=self.identity();self.assertGreater(row['game_generation'],old['game_generation'])
        self.assertEqual(row['api_outcome'],'connection_failed')
        self.assertFalse(w.state.hero);self.assertFalse(w.hero_continuity.hero);self.assertIsNone(w.hero_continuity.verified_at)
        self.run_frame(http=connections('Owned2'));self.assertFalse(w.state.hero)
        self.run_frame(http=connections('Owned2'));self.assertEqual(w.state.hero,second)
        self.assertGreater(w.hero_continuity.verified_at,seed);self.assertFalse(w.state.confirmed)

    def test_process_creation_mismatch_blocks_requests_and_records_scope_loss(self):
        from session_windows import ProcessMetadata
        self.prepare();factory,_,_=self.run_frame(metadata=ProcessMetadata(self.meta.path,self.meta.created+1))
        factory.assert_not_called();self.assertEqual(self.identity()['api_outcome'],'scope_unavailable')
        self.assertFalse(self.resolved[-1]['confident'])

    def test_map_outcomes_and_malformed_roster_allow_safe_hud_fallback(self):
        w=self.prepare();cache=w.state_dir/'hero-portraits';path=cache/'roster-16.20.1.json'
        def read(code):
            codes=[];value=w.canonical_champion_map(diagnostic_callback=codes.append)
            self.assertEqual(codes,[code]);return value
        self.assertEqual(len(read('verified')),100)
        (cache/'manifest.json').unlink();self.assertEqual(read('manifest_unavailable'),{})
        for raw in (b'\xff',b'{',b'null',b'[]',b'{"version":"../../PRIVATE"}'):
            (cache/'manifest.json').write_bytes(raw);self.assertEqual(read('manifest_invalid'),{})
        write_roster(cache);saved=path.read_bytes();path.unlink();self.assertEqual(read('roster_unavailable'),{})
        path.write_bytes(saved+b' ');self.assertEqual(read('hash_mismatch'),{})
        raw=b'{"version":"16.20.1","data":{}}';path.write_bytes(raw)
        (cache/'manifest.json').write_text(json.dumps({'version':'16.20.1','rosterSha256':hashlib.sha256(raw).hexdigest()}))
        self.assertEqual(read('roster_invalid'),{})
        # Invalid reference data disables API mapping, not independent HUD/OCR.
        raw=json.dumps({'version':'16.20.1','data':{'x':{'key':'1','id':'Owned1','image':[]}}}).encode();path.write_bytes(raw)
        (cache/'manifest.json').write_text(json.dumps({'version':'16.20.1','rosterSha256':hashlib.sha256(raw).hexdigest()}))
        codes=[]
        self.assertEqual(w.canonical_champion_map(diagnostic_callback=codes.append),{})
        self.assertEqual(codes,['roster_invalid'])
        expected_generation=w.state.generation;expected_serial=w._capture_serial+1
        factory,probe,tls=self.run_frame()
        factory.assert_not_called();probe.assert_not_called();tls.assert_not_called()
        row=self.identity();self.assertEqual(row['map_outcome'],'roster_invalid')
        self.assertEqual((row['generation'],row['serial']),(expected_generation,expected_serial))
        self.assertEqual((row['api_outcome'],row['hud_outcome'],row['identity_outcome']),('map_invalid','score_low','hud_abstained'))
        self.assertTrue(self.resolved)
        self.assertFalse(w.ocr_busy);self.assertFalse(w.state.confirmed)
        (cache/'manifest.json').write_text('[]');factory,probe,_=self.run_frame()
        factory.assert_not_called();probe.assert_not_called()
        row=self.identity();self.assertEqual((row['map_outcome'],row['api_outcome']),('manifest_invalid','map_invalid'))

if __name__=='__main__':unittest.main()

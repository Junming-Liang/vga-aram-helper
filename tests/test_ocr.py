"""Standard-library tests for matching and localhost OCR request boundaries."""
import base64
from http.client import HTTPConnection
import json
from pathlib import Path
import sys
import threading
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from local_ocr import candidate_matches,normalized_name
from engine import load_data
from server import make_server

class MatchingTests(unittest.TestCase):
    def line(self,text,score=.95,x=0):return {'text':text,'confidence':score,'box':[[x,0],[x+10,0],[x+10,10],[x,10]]}
    def test_normalization(self):self.assertEqual(normalized_name(' ＡＢ 珠光·护手！ '),'ab珠光护手')
    def test_exact_never_automatically_selects(self):
        result=candidate_matches([self.line('珠光护手')],['珠光护手'])
        self.assertEqual(result[0]['match_method'],'exact');self.assertTrue(result[0]['requires_confirmation'])
    def test_blank_returns_empty(self):self.assertEqual(candidate_matches([self.line('')],['珠光护手']),[])
    def test_unrelated_returns_empty(self):self.assertEqual(candidate_matches([self.line('设置音量游戏开始')],['珠光护手','双刀流']),[])
    def test_low_confidence_returns_empty(self):self.assertEqual(candidate_matches([self.line('珠光护手',.3)],['珠光护手']),[])
    def test_nan_confidence_returns_empty(self):self.assertEqual(candidate_matches([self.line('珠光护手',float('nan'))],['珠光护手']),[])
    def test_infinite_confidence_returns_empty(self):self.assertEqual(candidate_matches([self.line('珠光护手',float('inf'))],['珠光护手']),[])
    def test_fuzzy_requires_clear_margin(self):
        self.assertEqual(candidate_matches([self.line('星火共鸣演式')],['星火共鸣演示','星火共鸣演事']),[])
    def test_single_fuzzy_suggestion(self):
        result=candidate_matches([self.line('星火共鸣演式')],['星火共鸣演示'])
        self.assertEqual(result[0]['match_method'],'fuzzy-suggestion');self.assertTrue(result[0]['requires_confirmation'])
    def test_deduplicates_best_confidence(self):
        result=candidate_matches([self.line('珠光护手',.8),self.line('珠光护手',.99)],['珠光护手'])
        self.assertEqual(len(result),1);self.assertEqual(result[0]['ocr_confidence'],.99)
    def test_keeps_left_to_right_order(self):
        result=candidate_matches([self.line('珠光护手',x=300),self.line('双刀流',x=100)],['珠光护手','双刀流'])
        self.assertEqual([x['name'] for x in result],['双刀流','珠光护手'])
    def test_long_paragraph_not_a_title(self):
        self.assertEqual(candidate_matches([self.line('这是一大段无关说明文字珠光护手后面还跟着非常多的正文说明文字')],['珠光护手']),[])
    def test_model_inventory_fails_before_missing_models_load(self):
        from model_inventory import verify_models
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(RuntimeError):verify_models(folder)

class FakeOCR:
    def recognize(self,image,names):
        if len(image)>8*1024*1024:raise ValueError('图片超过限制')
        if image!=b'test-image':raise ValueError('非法测试图片')
        return {'candidates':[],'network_transmission':False,'image_saved':False}

class OCRHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server=make_server(load_data(ROOT/'fixtures/demo.json'),0,enable_ocr=True,ocr_engine=FakeOCR())
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
    @classmethod
    def tearDownClass(cls):cls.server.shutdown();cls.server.server_close();cls.thread.join()
    def post(self,payload,path='/api/ocr',headers=None):
        connection=HTTPConnection('127.0.0.1',self.server.server_port,timeout=5)
        h={'Content-Type':'application/json'};h.update(headers or {})
        connection.request('POST',path,body=json.dumps(payload),headers=h)
        response=connection.getresponse();body=json.loads(response.read());connection.close();return response.status,body
    def test_valid_local_request(self):self.assertEqual(self.post({'image_base64':base64.b64encode(b'test-image').decode()})[0],200)
    def test_foreign_origin_denied(self):self.assertEqual(self.post({},headers={'Origin':'https://evil.example'})[0],403)
    def test_local_origin_allowed(self):self.assertEqual(self.post({'image_base64':base64.b64encode(b'test-image').decode()},headers={'Origin':f'http://127.0.0.1:{self.server.server_port}'})[0],200)
    def test_foreign_host_denied(self):self.assertEqual(self.post({},headers={'Host':'evil.example'})[0],403)
    def test_non_json_denied(self):self.assertEqual(self.post({},headers={'Content-Type':'text/plain'})[0],415)
    def test_missing_image_denied(self):self.assertEqual(self.post({})[0],400)
    def test_invalid_base64_denied(self):self.assertEqual(self.post({'image_base64':'not base64!'})[0],400)
    def test_invalid_image_denied(self):self.assertEqual(self.post({'image_base64':'eA=='})[0],400)
    def test_unknown_route(self):self.assertEqual(self.post({},path='/api/anything')[0],404)
    def test_oversized_declared_length(self):self.assertEqual(self.post({},headers={'Content-Length':str(13*1024*1024)})[0],413)

if __name__=='__main__':unittest.main(verbosity=2)

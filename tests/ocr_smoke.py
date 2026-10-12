"""Actual offline OCR of original synthetic test images. Optional dependencies."""
import hashlib
import base64
from http.client import HTTPConnection
import threading
import importlib.metadata
import json
from pathlib import Path
import platform
import sys
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from local_ocr import LocalOCR

expected=['珠光护手','炼狱导管','双刀流']
engine=LocalOCR()
start=time.perf_counter()
result=engine.recognize((ROOT/'fixtures/ocr-synthetic.png').read_bytes(),expected)
first_seconds=time.perf_counter()-start
actual=[x['name'] for x in result['candidates']]
assert actual==expected,(expected,actual,result['ocr_lines'])
start=time.perf_counter()
blank=engine.recognize((ROOT/'fixtures/ocr-blank.png').read_bytes(),expected)
assert blank['candidates']==[],blank
blank_seconds=time.perf_counter()-start
# Repeat warm path, preserving left-to-right order and requiring manual review.
start=time.perf_counter()
warm=engine.recognize((ROOT/'fixtures/ocr-synthetic.png').read_bytes(),expected)
assert [x['name'] for x in warm['candidates']]==expected
assert all(x['requires_confirmation'] for x in warm['candidates'])
warm_seconds=time.perf_counter()-start
from engine import load_data
from server import make_server
server=make_server(load_data(ROOT/'fixtures/demo.json'),0,enable_ocr=True,ocr_engine=engine)
thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
try:
    connection=HTTPConnection('127.0.0.1',server.server_port,timeout=30)
    payload={'image_base64':base64.b64encode((ROOT/'fixtures/ocr-app-demo.png').read_bytes()).decode()}
    connection.request('POST','/api/ocr',body=json.dumps(payload),headers={'Content-Type':'application/json'})
    response=connection.getresponse();api=json.loads(response.read());connection.close()
    assert response.status==200,api
    app_names=['星火共鸣（演示）','晶盾回路（演示）','风步微光（演示）']
    assert [x['name'] for x in api['candidates']]==app_names,api
finally:
    server.shutdown();server.server_close();thread.join()
report={'result':'passed','localhost_ocr_api':'passed with default synthetic app dictionary and original test image','app_names_recognized':app_names,'environment':platform.platform(),'fixture':'Original synthetic image, not real gameplay',
        'names_expected':expected,'names_recognized':actual,'matched_on_fixture':'3/3 (not an accuracy estimate)',
        'blank_candidates':0,'first_call_seconds':round(first_seconds,3),'warm_call_seconds':round(warm_seconds,3),'blank_call_seconds':round(blank_seconds,3),
        'network_controls':'Bundled local model files are hash-checked and passed explicitly; ONNX telemetry disabled. No process-global socket patch; no cloud vision API. Native OS egress was not independently measured.',
        'versions':{x:importlib.metadata.version(x) for x in ['rapidocr','onnxruntime','numpy','Pillow']},
        'fixture_sha256':hashlib.sha256((ROOT/'fixtures/ocr-synthetic.png').read_bytes()).hexdigest(),
        'candidates':result['candidates'],'not_tested':['real user game screenshot accuracy','hero recognition','live capture','overlay','Windows execution']}
(ROOT/'reports').mkdir(exist_ok=True)
(ROOT/'reports/ocr-validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(report,ensure_ascii=False,indent=2))

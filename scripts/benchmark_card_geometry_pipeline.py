"""Released versus candidate whole-frame local inference on an explicit public still.

Includes actual OCR/HUD, ROI encoding, native-equivalent early title+geometry
reproof, and final title-proof creation. Excludes Windows capture, Qt dispatch,
local-client network calls and game timing. No images copied or downloaded.
"""
import argparse
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import platform
import statistics
import sys
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

def sha(data):return hashlib.sha256(data).hexdigest()
def summary(values):return {'samples_ms':values,'median_ms':statistics.median(values),'min_ms':min(values),'max_ms':max(values)}
def semantic(value):
    if isinstance(value,dict):
        return {k:semantic(v) for k,v in value.items() if not k.startswith('_') and k not in ('elapsed_seconds','partial_title_evidence','abstentionKind')}
    if isinstance(value,(list,tuple)):return [semantic(v) for v in value]
    return value

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('baseline','templates','data','image','output'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--samples',type=int,default=9)
    a=p.parse_args()
    if not 7<=a.samples<=31:p.error('--samples must be7..31')
    import cv2
    from PIL import Image
    from engine import normalize
    import hero_recognition as candidate
    from local_ocr import LocalOCR
    from frame_inference_worker import FrameInferenceWorker
    from card_title_proof import make_title_proof
    from augment_card_geometry import detect_frame_card_geometry
    from screen_capture import bounded_roi
    paths=[a.baseline,ROOT/'hero_recognition.py',ROOT/'augment_card_geometry.py',ROOT/'card_title_proof.py',ROOT/'local_ocr.py',ROOT/'frame_inference_worker.py']
    hashes={p.name:sha(p.read_bytes()) for p in paths}
    spec=importlib.util.spec_from_file_location('released_geometry_baseline',a.baseline)
    baseline=importlib.util.module_from_spec(spec);sys.modules[spec.name]=baseline;spec.loader.exec_module(baseline)
    roster=json.loads((a.templates/'champion.en_US.json').read_text())
    bank={row['key']:Image.open(a.templates/'square'/row['image']['full']).convert('RGB') for row in roster['data'].values()}
    heroes={r['name']:{'championId':r['key']} for r in roster['data'].values()}
    raw=json.loads(a.data.read_text());vocabulary=tuple(normalize(raw.get('data',raw))['augments'])
    matchers={'baseline':baseline.PortraitMatcher(bank,heroes),'full':candidate.PortraitMatcher(bank,heroes),'fresh':candidate.PortraitMatcher(bank,heroes)}
    payload=a.image.read_bytes();roi=(.15,.25,.7,.35);worker=FrameInferenceWorker();ocr=LocalOCR()
    previous=candidate.recognize_frame(payload,roi,ocr,vocabulary,matchers['fresh'],inference_worker=worker)
    geometry=previous['_cardGeometry']
    if geometry is None:raise AssertionError('Public modal actual card geometry missing')
    image=Image.open(io.BytesIO(payload)).convert('RGB');l,t,w,h=bounded_roi(*image.size,roi)
    out=io.BytesIO();image.crop((l,t,l+w,t+h)).save(out,format='PNG');crop=out.getvalue()
    proof=make_title_proof(crop,previous['automatic_candidates'],previous['image_size'])
    if proof is None:raise AssertionError('Public modal title proof missing')
    expected=semantic(previous)
    def run(arm):
        started=time.perf_counter();phases={};current=[];decoded=[]
        def before_match(signature,crop):
            proof_start=time.perf_counter();current[:]=[crop]
            if arm!='baseline':
                if not proof.matches(crop) or not geometry.matches(payload,_decoded_rgb=decoded[0]):raise AssertionError('Fresh native-equivalent proof failed')
            sha(crop)
            phases['early_reproof_ms']=(time.perf_counter()-proof_start)*1000
            phases['before_match_ms']=(time.perf_counter()-started)*1000
        def before_ocr(hero,crop):
            sha(crop);phases['before_ocr_ms']=(time.perf_counter()-started)*1000
        module=baseline if arm=='baseline' else candidate
        options={'prior_card_geometry':geometry if arm=='fresh' else None,'prepared_frame':lambda rgb:decoded.append(rgb)} if arm!='baseline' else {}
        result=module.recognize_frame(payload,roi,ocr,vocabulary,matchers[arm],before_match=before_match,before_ocr=before_ocr,inference_worker=worker,**options)
        if arm!='baseline':
            if make_title_proof(current[0],result['automatic_candidates'],result['image_size']) is None:raise AssertionError('Final title proof missing')
            if result.get('_cardGeometry') is None:raise AssertionError('Final card geometry missing')
        phases['total_ms']=(time.perf_counter()-started)*1000
        if semantic(result)!=expected:raise AssertionError('Hero/OCR/title semantics changed for '+arm)
        return phases
    arms=('baseline','full','fresh')
    for _ in range(2):
        for arm in arms:run(arm)
    timing={arm:{k:[] for k in ('total_ms','early_reproof_ms','before_match_ms','before_ocr_ms')} for arm in arms}
    orders=[]
    for i in range(a.samples):
        order=arms[i%3:]+arms[:i%3]
        if i%2:order=tuple(reversed(order))
        orders.append(order)
        for arm in order:
            phases=run(arm)
            for k,v in phases.items():timing[arm][k].append(round(v,3))
    if any(sha(p.read_bytes())!=hashes[p.name] for p in paths):raise RuntimeError('Implementation changed; rerun')
    worker.close()
    report={'schema_version':1,'status':'passed','scope':__doc__.strip(),'baseline_commit':'9a45c8d','implementation_sha256':hashes,'driver_sha256':sha(Path(__file__).read_bytes()),
            'source_url':'https://raw.githubusercontent.com/Nyx0ra/lol-aram-mayhem-hextech-helper/main/docs/demo.png','image_sha256':sha(payload),'image_size':image.size,
            'environment':{'platform':platform.platform(),'python':platform.python_version(),'opencv':cv2.__version__,'opencv_threads':cv2.getNumThreads()},
            'vocabulary_count':len(vocabulary),'vocabulary_sha256':sha(json.dumps(vocabulary,ensure_ascii=False).encode()),'template_count':len(bank),
            'warmups_per_arm':2,'samples_per_arm':a.samples,'interleaved_arm_order':orders,'semantic_parity':True,
            'hero':expected['hero_observation'],'automatic_titles':expected['automatic_candidates'],
            'timing_ms':{arm:{k:summary(v) for k,v in values.items()} for arm,values in timing.items()},
            'exclusions':['Windows capture','Qt signal dispatch/render','live-client HTTP identity','actual gameplay animation','general accuracy claims'],
            'note':'Candidate early and final edge proofs use the exact same-call decoded RGB supplied by prepared_frame, as native code does. Baseline uses released parallel HUD/OCR without new badge proofs; full uses fresh early proofs plus full rectangle search; fresh uses fresh early proofs plus fresh bounded edge reproof. Each arm runs actual independent OCR; no OCR result cache.'}
    a.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({arm:report['timing_ms'][arm]['total_ms'] for arm in arms},indent=2))
if __name__=='__main__':main()

"""Bounded exact-matching benchmark, optionally with one pinned public screenshot.

No downloads and no images copied to the repository. Supply the previously
inspected screenshot and authorized vocabulary explicitly. Report timings are
local measurements, not gameplay accuracy or Windows performance estimates.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import io
import json
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import time
import types

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import local_ocr
from app_version import __version__

SOURCE='https://raw.githubusercontent.com/Nyx0ra/lol-aram-mayhem-hextech-helper/main/docs/demo.png'
EXPECTED_SHA='62ea23e33139ad27159548ef84e2d619293da90b46f92360f1ae003c6301bed0'
EXPECTED=['心灵净化','暴击律动','虚幻武器']
CROP=(620,520,1935,635)


def line(text,x=0):
    return {'text':text,'confidence':.99,'box':[[x,0],[x+80,0],[x+80,30],[x,30]]}


def timing(fn,repeat=7,iterations=100):
    fn()  # Exclude initial index construction; this is the repeated-frame path.
    values=[]
    for _ in range(repeat):
        started=time.perf_counter()
        for _ in range(iterations):fn()
        values.append((time.perf_counter()-started)*1000/iterations)
    return {'median_ms':round(statistics.median(values),6),
            'min_ms':round(min(values),6),'max_ms':round(max(values),6),
            'batches':repeat,'iterations_per_batch':iterations}


def compare_matching(baseline,lines,names,iterations=100):
    before=baseline.candidate_matches(lines,names)
    after=local_ocr.candidate_matches(lines,names)
    old=timing(lambda:baseline.candidate_matches(lines,names),iterations=iterations)
    new=timing(lambda:local_ocr.candidate_matches(lines,names),iterations=iterations)
    return {'output_equal':before==after,'line_count':len(lines),'baseline':old,'candidate':new,
            'baseline_over_candidate_ratio':round(old['median_ms']/max(new['median_ms'],.000001),2)}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline-revision',default='0417bd3')
    parser.add_argument('--vocabulary',type=Path,required=True)
    parser.add_argument('--vocabulary-source-url',required=True)
    parser.add_argument('--public-image',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    revision=subprocess.check_output(['git','rev-parse',args.baseline_revision+'^{commit}'],cwd=ROOT,text=True).strip()
    source=subprocess.check_output(['git','show',revision+':local_ocr.py'],cwd=ROOT)
    baseline=types.ModuleType('local_ocr_baseline');baseline.__file__=str(ROOT/'local_ocr.py')
    exec(compile(source,baseline.__file__,'exec'),baseline.__dict__)
    vocabulary_raw=args.vocabulary.read_bytes();vocabulary=json.loads(vocabulary_raw)
    if not isinstance(vocabulary,(dict,list)) or not all(isinstance(name,str) for name in vocabulary):
        raise ValueError('Vocabulary must be a map/list of names')
    names=list(vocabulary)
    if not all(name in names for name in EXPECTED):raise ValueError('Expected public titles missing from vocabulary')
    changes=[]
    for name in names:
        old=baseline.candidate_matches([line(name)],names)
        new=local_ocr.candidate_matches([line(name)],names)
        if old!=new:
            changes.append({'input':name,'baseline':[{'name':v['name'],'method':v['match_method']} for v in old],
                            'candidate':[{'name':v['name'],'method':v['match_method']} for v in new]})
        if len(new)!=1 or new[0]['name']!=name or new[0]['match_method']!='exact':
            raise AssertionError('Literal dictionary title did not resolve uniquely: '+name)
    report={'result':'passed','applicationVersion':__version__,'recorded_at_executor_clock':datetime.now(timezone.utc).isoformat(),
            'baseline_commit':revision,'baseline_local_ocr_sha256':hashlib.sha256(source).hexdigest(),
            'candidate_local_ocr_sha256':hashlib.sha256((ROOT/'local_ocr.py').read_bytes()).hexdigest(),
            'environment':platform.platform(),'python':platform.python_version(),
            'vocabulary_count':len(names),'vocabulary_sha256':hashlib.sha256(vocabulary_raw).hexdigest(),
            'vocabulary_source_url':args.vocabulary_source_url,
            'vocabulary_scope':'Historical public reference snapshot; not current live-game coverage',
            'literal_dictionary_checks':{'count':len(names),'candidate_exact_count':len(names),'intentional_changes':changes},
            'exact_three_titles_matching':compare_matching(baseline,[line(name,i*400) for i,name in enumerate(EXPECTED)],names),
            'design_reference':{'url':'https://github.com/Nyx0ra/lol-aram-mayhem-hextech-helper/blob/main/main.py',
                                'license':'MIT','use':'Exact-before-fuzzy lookup idea; independently implemented, no copied source'},
            'limits':['Matcher timings exclude OCR inference, image decoding and screen capture',
                      'Only bounded local measurements; no aggregate accuracy claim',
                      'No live Windows execution or real user-session validation',
                      'No model, preprocessing, confidence threshold or automatic-confirmation changes',
                      'Three alternating warm samples do not establish an end-to-end latency improvement']}
    if args.public_image:
        from PIL import Image
        raw=args.public_image.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=EXPECTED_SHA:raise ValueError('Sample changed; inspect before testing')
        with Image.open(io.BytesIO(raw)) as image:
            if image.size!=(2560,1440):raise ValueError('Unexpected sample geometry')
            crop=image.crop(CROP);out=io.BytesIO();crop.save(out,format='PNG')
        images={'full_image':raw,'title_only_crop':out.getvalue()}
        engines={'baseline':baseline.LocalOCR(),'candidate':local_ocr.LocalOCR()}
        results={};samples={key:{kind:[] for kind in images} for key in engines}
        # Initialize both engines before warm timing; import order makes cold
        # startup incomparable, so this benchmark deliberately does not report it.
        for engine in engines.values():engine.recognize(images['title_only_crop'],names)
        for iteration in range(3):
            order=('baseline','candidate') if iteration%2==0 else ('candidate','baseline')
            for key in order:
                for kind,payload in images.items():
                    started=time.perf_counter();result=engines[key].recognize(payload,names)
                    samples[key][kind].append((time.perf_counter()-started)*1000)
                    results[(key,kind)]=result
        inference={}
        for kind in images:
            before=results[('baseline',kind)];after=results[('candidate',kind)]
            if before['ocr_lines']!=after['ocr_lines'] or before['candidates']!=after['candidates']:
                raise AssertionError('Public sample OCR output changed: '+kind)
            if [item['name'] for item in after['candidates']]!=EXPECTED:
                raise AssertionError('Unexpected public sample title candidates')
            inference[kind]={'ocr_lines_equal':True,'candidates_equal':True,
                             'names':[item['name'] for item in after['candidates']],
                             'warm_wall_time_ms':{key:{'median':round(statistics.median(values[kind]),3),
                                                      'samples':[round(value,3) for value in values[kind]]}
                                                  for key,values in samples.items()}}
        lines=results[('candidate','full_image')]['ocr_lines']
        title_lines=[entry for entry in lines if entry.get('box') and 520<=min(p[1] for p in entry['box'])<=610]
        real_titles=local_ocr.candidate_matches(title_lines,names)
        if [item['name'] for item in real_titles]!=EXPECTED:raise AssertionError('Actual title row mismatch')
        report['public_sample']={'source_url':SOURCE,'sample_sha256':EXPECTED_SHA,'sample_count':1,
            'image_included':False,'crop_xyxy':list(CROP),'crop_excludes_helper_overlays':True,
            'source_context':'One public screenshot with third-party helper overlays; not a clean gameplay accuracy corpus',
            'gold_labels':'Manually inspected actual card title row, not colored helper overlay labels',
            'expected_names':EXPECTED,'actual_title_row_candidates':real_titles,'inference':inference,
            'full_image_matching':compare_matching(baseline,lines,names,iterations=20),
            'actual_title_row_matching':compare_matching(baseline,title_lines,names)}
        report['versions']={name:importlib.metadata.version(name) for name in ['rapidocr','onnxruntime','numpy','Pillow']}
        report['limits'].append('Only one static public screenshot; output parity is not an accuracy estimate')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':main()

"""Optional bounded check of ONE public screenshot; no download/redistribution.

Pass the previously downloaded image explicitly. Its checksum is pinned so the
hand-checked labels/crop are not silently reused for a different image.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import sys
import time
from PIL import Image
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from local_ocr import LocalOCR,candidate_matches
SOURCE='https://raw.githubusercontent.com/Nyx0ra/lol-aram-mayhem-hextech-helper/main/docs/demo.png'
EXPECTED_SHA='62ea23e33139ad27159548ef84e2d619293da90b46f92360f1ae003c6301bed0'
EXPECTED=['心灵净化','暴击律动','虚幻武器']
CROP=(620,520,1935,635)  # Manually inspected original pixel coordinates, excludes helper overlay text.
parser=argparse.ArgumentParser();parser.add_argument('image',type=Path);parser.add_argument('--vocabulary',type=Path,help='Optional authorized source JSON map/list of augment names');parser.add_argument('--vocabulary-source-url',default='');parser.add_argument('--output',type=Path,default=ROOT/'reports/public-sample-validation.json');args=parser.parse_args()
vocabulary=json.loads(args.vocabulary.read_text(encoding='utf-8')) if args.vocabulary else EXPECTED
assert isinstance(vocabulary,(dict,list))
vocabulary_sha=hashlib.sha256(args.vocabulary.read_bytes()).hexdigest() if args.vocabulary else None
raw=args.image.read_bytes();assert hashlib.sha256(raw).hexdigest()==EXPECTED_SHA,'Sample changed; inspect before testing'
engine=LocalOCR();start=time.perf_counter();full=engine.recognize(raw,vocabulary);full_elapsed=time.perf_counter()-start
with Image.open(io.BytesIO(raw)) as image:
    assert image.size==(2560,1440)
    crop=image.crop(CROP);stream=io.BytesIO();crop.save(stream,format='PNG')
start=time.perf_counter();titles=engine.recognize(stream.getvalue(),vocabulary);crop_elapsed=time.perf_counter()-start
full_names=[x['name'] for x in full['candidates']];crop_names=[x['name'] for x in titles['candidates']]
# Also prove title text is present in the full-image OCR, independently of duplicate overlays.
real_title_lines=[line for line in full['ocr_lines'] if line.get('box') and 520<=min(p[1] for p in line['box'])<=610]
full_title_names=[x['name'] for x in candidate_matches(real_title_lines,vocabulary)]
report={'result':'passed' if full_names==crop_names==full_title_names==EXPECTED else 'incomplete',
    'source_url':SOURCE,'sample_sha256':EXPECTED_SHA,'sample_count':1,'sample_image_included_in_package':False,'vocabulary_count':len(vocabulary),'vocabulary_sha256':vocabulary_sha,
    'vocabulary_source_url':args.vocabulary_source_url or None,
    'vocabulary_freshness':'Separately supplied public snapshot; retrieval time does not establish current live-game coverage',
    'source_context':'Public repository screenshot with third-party helper overlays; not a user session and not a clean accuracy benchmark',
    'gold_labels':'Manually read from actual card title row before evaluating OCR','expected_names':EXPECTED,
    'full_image_candidates':full_names,'full_image_actual_title_row_matches':full_title_names,'title_only_crop_candidates':crop_names,
    'crop_xyxy':list(CROP),'crop_excludes_helper_overlays':True,'full_image_seconds':round(full_elapsed,3),'title_crop_warm_seconds':round(crop_elapsed,3),
    'caution':'Full-image duplicate names may be sourced from helper overlay labels because deduplication favors OCR confidence. This is not a validated card-localization method.',
    'limits':['One static public sample only','Vocabulary is '+str(len(vocabulary))+' entries from the supplied reference; dataset coverage/currentness not guaranteed','No aggregate accuracy estimate','No live capture, hero recognition, overlay or Windows validation','No current-version guarantee'],
    'full_image_match_details':[{'name':x['name'],'raw_text':x['recognized_text'],'method':x['match_method'],'similarity':x['name_similarity'],'ocr_confidence':x['ocr_confidence']} for x in full['candidates']],
    'actual_title_row_match_details':[{'name':x['name'],'raw_text':x['recognized_text'],'method':x['match_method'],'similarity':x['name_similarity'],'ocr_confidence':x['ocr_confidence']} for x in candidate_matches(real_title_lines,vocabulary)],
    'title_crop_match_details':[{'name':x['name'],'raw_text':x['recognized_text'],'method':x['match_method'],'similarity':x['name_similarity'],'ocr_confidence':x['ocr_confidence']} for x in titles['candidates']],
    'title_crop_confidences':{x['name']:x['ocr_confidence'] for x in titles['candidates']}}
args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(report,ensure_ascii=False,indent=2));assert report['result']=='passed',report

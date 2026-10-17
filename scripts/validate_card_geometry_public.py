"""Validate caller-supplied public stills, never redistribute screenshot pixels.

The positive is the already-reviewed Samira modal from the publisher's public
repository. This tests geometry only, not OCR, game identity, live animation,
foreground/occlusion, or Windows. Resized positives are explicitly transformed.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import sys
import time
import statistics
from PIL import Image, ImageDraw
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from augment_card_geometry import detect_card_geometry, detect_frame_card_geometry, refresh_frame_card_geometry

SOURCE='https://raw.githubusercontent.com/Nyx0ra/lol-aram-mayhem-hextech-helper/main/docs/demo.png'
SHA='62ea23e33139ad27159548ef84e2d619293da90b46f92360f1ae003c6301bed0'

def encode(image):
    out=io.BytesIO();image.save(out,format='PNG');return out.getvalue()

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--positive',type=Path,required=True)
    p.add_argument('--negative',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    data=a.positive.read_bytes()
    if hashlib.sha256(data).hexdigest()!=SHA:raise ValueError('Expected reviewed public Samira modal SHA')
    image=Image.open(io.BytesIO(data)).convert('RGB')
    raw=json.loads((ROOT/'reports/hero-recognition-genuine.json').read_text())['genuine_selection_frame']['automatic_titles']
    boxes=[[(x+384,y+360) for x,y in c['box']] for c in raw]
    cases=[]
    for scale in (.4,.5,.625,.75,1,1.25,1.5):
        frame=image.resize((round(image.width*scale),round(image.height*scale)),Image.Resampling.BILINEAR)
        candidates=[{'box':[(x*scale,y*scale) for x,y in b]} for b in boxes]
        g=detect_card_geometry(encode(frame),candidates,{'width':frame.width,'height':frame.height})
        # Independent visual annotation of visible OUTER card frames; permit
        # 0.5% frame-coordinate anti-alias/rounding tolerance at transformed sizes.
        expected=((594/2560,240/1440,425/2560,703/1440),
                  (1067/2560,240/1440,425/2560,703/1440),
                  (1540/2560,240/1440,425/2560,703/1440))
        correct=g is not None and all(abs(x-y)<.008 for r,e in zip(g.rects,expected) for x,y in zip(r,e))
        cases.append({'case':'public_modal' if scale==1 else 'public_modal_resized', 'scale':scale,'size':frame.size,
                      'rects':g.rects if g else None,'pass':correct,'source_url':SOURCE})
    candidates=[{'box':b} for b in boxes]
    for label,box in [('left_border_occlusion',(580,380,630,800)),('top_border_occlusion',(650,220,970,280)),
                      ('card_removed',(570,220,1040,970))]:
        changed=image.copy();ImageDraw.Draw(changed).rectangle(box,fill=(42,42,42))
        g=detect_card_geometry(encode(changed),candidates,{'width':2560,'height':1440})
        cases.append({'case':label,'transformed':True,'pass':g is None})
    changed=image.copy()
    for dx in (0,473,946):
        ImageDraw.Draw(changed).rectangle((580+dx,380,630+dx,800),fill=(42,42,42))
    g=detect_card_geometry(encode(changed),candidates,{'width':2560,'height':1440})
    cases.append({'case':'all_three_outer_borders_occluded','transformed':True,'pass':g is None})
    crop_size={'width':1792,'height':504};roi=(.15,.25,.7,.35)
    previous=detect_frame_card_geometry(data,raw,crop_size,roi)
    timings={'full_detection_ms':[],'fresh_strip_reproof_ms':[],'same_call_decoded_reproof_ms':[]}
    for _ in range(5):
        start=time.perf_counter();full=detect_frame_card_geometry(data,raw,crop_size,roi)
        timings['full_detection_ms'].append(round((time.perf_counter()-start)*1000,3))
        start=time.perf_counter();fresh=refresh_frame_card_geometry(data,previous,raw,crop_size,roi)
        timings['fresh_strip_reproof_ms'].append(round((time.perf_counter()-start)*1000,3))
        start=time.perf_counter();decoded=refresh_frame_card_geometry(data,previous,raw,crop_size,roi,_decoded_rgb=image)
        timings['same_call_decoded_reproof_ms'].append(round((time.perf_counter()-start)*1000,3))
        if full is None or fresh is None or full.rects!=fresh.rects or decoded!=fresh:raise AssertionError('Fresh geometry parity failed')
    fast_negative=refresh_frame_card_geometry(encode(changed),previous,raw,crop_size,roi)
    cases.append({'case':'fresh_reproof_rejects_all_three_occlusions','transformed':True,'pass':fast_negative is None})
    timings['full_detection_median_ms']=statistics.median(timings['full_detection_ms'])
    timings['fresh_strip_reproof_median_ms']=statistics.median(timings['fresh_strip_reproof_ms'])
    timings['same_call_decoded_reproof_median_ms']=statistics.median(timings['same_call_decoded_reproof_ms'])
    negative=Image.open(a.negative).convert('RGB')
    sx,sy=negative.width/image.width,negative.height/image.height
    c=[{'box':[(x*sx,y*sy) for x,y in b]} for b in boxes]
    g=detect_card_geometry(encode(negative),c,{'width':negative.width,'height':negative.height})
    cases.append({'case':'public_non_modal_scoreboard','image_sha256':hashlib.sha256(a.negative.read_bytes()).hexdigest(),
                  'size':negative.size,'pass':g is None,
                  'source_url':'https://turbo-uploads.s3.eu-north-1.amazonaws.com/i_just_played_an_all_prismatics_aram_mayhem_fa9d4de2a0.webp'})
    report={'schema_version':1,'scope':'One genuine public modal still plus explicitly resized/occluded variants and one genuine scoreboard negative. Geometry only; not Windows live-game, multi-round accuracy or interior-occlusion proof. Screenshots not redistributed.',
            'source_image_sha256':SHA,'implementation_sha256':hashlib.sha256((ROOT/'augment_card_geometry.py').read_bytes()).hexdigest(),
            'status':'passed' if all(c['pass'] for c in cases) else 'failed','cases':cases,'geometry_only_timing':timings}
    a.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False))
    return 0 if report['status']=='passed' else 1
if __name__=='__main__':raise SystemExit(main())

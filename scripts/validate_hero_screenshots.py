"""Evaluate caller-supplied permitted screenshots; report facts without copying images."""
import argparse,hashlib,json,platform,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from PIL import Image
from hero_recognition import PortraitMatcher,recognize_frame
from native_state import automatic_candidates
from local_ocr import LocalOCR
from app_version import __version__


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--templates',type=Path,required=True);parser.add_argument('--fixtures',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);parser.add_argument('--data',type=Path)
    args=parser.parse_args();roster=json.loads((args.templates/'champion.en_US.json').read_text());bank={row['key']:Image.open(args.templates/'square'/row['image']['full']).convert('RGB') for row in roster['data'].values()};heroes={row['name']:{'championId':row['key']} for row in roster['data'].values()}
    matcher=PortraitMatcher(bank,heroes);records=json.loads(args.fixtures.read_text());cases=[]
    for row in records:
        if not row.get('path'):continue
        path=Path(row['path']);payload=path.read_bytes();gold=str(row.get('canonical_champion_id',''));start=time.monotonic();observed=matcher.recognize(payload)
        negative=row.get('test_role','').startswith('negative')
        correct=(not observed['confident']) if negative else observed['championId']==gold
        cases.append({'source_url':row.get('image_url'),'source_page':row.get('source_page'),'image_sha256':hashlib.sha256(payload).hexdigest(),'image_dimensions':list(Image.open(path).size),'condition':row.get('context'),'gold_hero_id':gold or None,'gold_hero':row.get('visible_champion'),'gold_confidence':row.get('gold_confidence'),'expected_outcome':'abstain' if negative else 'recognize_own_hero','observed':observed,'case_pass':correct,'safety_pass':not observed['confident'] or observed['championId']==gold,'kind':'genuine_public_screenshot','transformation':None,'elapsed_seconds':round(time.monotonic()-start,3),'image_redistributed':False})
    positives=[c for c in cases if c['expected_outcome']=='recognize_own_hero'];negatives=[c for c in cases if c['expected_outcome']=='abstain']
    report={'schema_version':1,'applicationVersion':__version__,'status':'passed' if all(c['case_pass'] for c in cases) else 'partial_with_abstentions','scope':'Local Linux screenshot evaluation of a small selected public sample. Not Windows live-game capture, aggregate game accuracy, all skins, Riot approval or Vanguard compatibility. Genuine images are not redistributed.','platform':platform.system(),'implementation_sha256':{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in ['hero_recognition.py','hero_portraits.py']},'templates':{'source_url':'https://ddragon.leagueoflegends.com/api/versions.json','version':roster['version'],'count':len(bank),'roster_sha256':hashlib.sha256((args.templates/'champion.en_US.json').read_bytes()).hexdigest(),'asset_source':'Riot Data Dragon base-square portraits; local cache only'},'summary':{'positive_cases':len(positives),'positive_recognized':sum(c['case_pass'] for c in positives),'positive_abstained':sum(not c['observed']['confident'] for c in positives),'wrong_hero_predictions':sum(not c['safety_pass'] for c in cases),'negative_cases':len(negatives),'negative_abstained':sum(c['case_pass'] for c in negatives)},'cases':cases}
    if args.data:
        from engine import normalize
        raw=json.loads(args.data.read_text());data=normalize(raw.get('data',raw));samira=next((r for r in records if str(r.get('canonical_champion_id'))=='360' and r.get('path')),None)
        if samira:
            result=recognize_frame(Path(samira['path']).read_bytes(),(.15,.25,.7,.35),LocalOCR(),data['augments'],PortraitMatcher(bank,data['heroes']))
            report['genuine_selection_frame']={'source_url':samira['image_url'],'hero':result['hero_observation'],'automatic_titles':result['automatic_candidates'],'passes_title_geometry':automatic_candidates(result['automatic_candidates'],result['image_size']),'scope':'One still-frame pipeline observation, not temporal/video or native Windows proof; unrelated preexisting overlay labels excluded by title-band and literal-text gates.'}
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps(report['summary'],ensure_ascii=False));print(report['status'])
if __name__=='__main__':main()

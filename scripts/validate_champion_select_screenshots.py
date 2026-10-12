"""Small caller-supplied screenshot evaluation; never redistributes the frames."""
import argparse,hashlib,json,platform,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from app_version import __version__
from champion_select import ChampionSelectDetector
from local_ocr import LocalOCR
from PIL import Image

def main():
    p=argparse.ArgumentParser();p.add_argument('--rosters',type=Path,required=True);p.add_argument('--fixtures',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    aliases={}
    for locale in ('en_US','zh_CN'):
        roster=json.loads((a.rosters/f'champion.{locale}.json').read_text(encoding='utf8'))
        for row in roster['data'].values():aliases.setdefault(str(row['key']),[]).extend([row['name'],row['title']])
    records=json.loads(a.fixtures.read_text(encoding='utf8'))['items'];detector=ChampionSelectDetector(aliases,LocalOCR());cases=[]
    for row in records:
        if not row.get('path'):continue
        image=Path(row['path']);payload=image.read_bytes();digest=hashlib.sha256(payload).hexdigest()
        if row.get('sha256')!=digest:raise ValueError('Fixture hash changed: '+image.name)
        gold=str(row['champion_id']) if row.get('champion_id') else None;negative=row['expected']=='abstain';start=time.monotonic();observed=detector.recognize(payload)
        correct=not observed['assigned'] if negative else observed['assigned'] and observed['championId']==gold
        cases.append({'source_url':row['image_url'],'source_page':row.get('source_page'),'image_sha256':digest,'image_dimensions':list(Image.open(image).size),'gold_hero_id':gold,'expected_outcome':'abstain' if negative else 'recognize_current_assignment','observed':observed,'case_pass':correct,'safety_pass':not observed['assigned'] or observed['championId']==gold,'kind':'genuine_public_screenshot','condition':row['context'],'limitations':row.get('limitation') or row.get('license'),'transformation':None,'image_redistributed':False,'elapsed_seconds':round(time.monotonic()-start,3)})
    positive=[c for c in cases if c['expected_outcome']!='abstain'];negative=[c for c in cases if c['expected_outcome']=='abstain']
    report={'schema_version':1,'applicationVersion':__version__,'status':'passed' if all(c['case_pass'] for c in cases) else 'partial_with_abstentions','scope':'Small local Linux still-image evaluation only: one July2025 Traditional Chinese post-choice client modified by a third-party plugin, plus three June2025 prerelease initial-card images representing two distinct scenes (one scene has resized/original variants). Not current stock-client, live trade/cancel sequence, native Windows, or Riot/Vanguard compatibility proof. Images are not redistributed.','platform':platform.system(),'implementation_sha256':{'champion_select.py':hashlib.sha256((ROOT/'champion_select.py').read_bytes()).hexdigest()},'summary':{'positive_cases':len(positive),'positive_recognized':sum(c['case_pass'] for c in positive),'negative_cases':len(negative),'negative_abstained':sum(c['case_pass'] for c in negative),'distinct_negative_scenes':len({c['source_page'] for c in negative}),'wrong_hero_predictions':sum(not c['safety_pass'] for c in cases)},'cases':cases}
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8');print(json.dumps(report['summary']))
if __name__=='__main__':main()

"""Developer-only, read a separately acquired official snapshot without bundling it.
Run: python tests/official_snapshot_validation.py --source-dir /path/to/wiki-json
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from engine import normalize
from core import compare_augments
parser=argparse.ArgumentParser();parser.add_argument('--source-dir',type=Path,required=True);parser.add_argument('--output',type=Path)
args=parser.parse_args()
files={'championDetail':'champion-detail','augmentDetail':'augment-detail','championList':'champion-list','augmentList':'augment-list','itemDetail':'item-detail'}
wiki={};hashes={}
for key,name in files.items():
    body=(args.source_dir/f'wiki-data-{name}.json').read_bytes();wiki[key]=json.loads(body);hashes[name]=hashlib.sha256(body).hexdigest()
wiki['version']='395'
data=normalize({'wiki':wiki,'metadata':{'wikiBaseUrl':'https://fileserver.cdn.huya.com/game_tools/1-p81hl812-395/395/','sourceDataDate':'2026-09-07'}})
assert len(data['heroes'])==172 and len(data['augments'])==209 and len(data['items'])==180
assert normalize(data)==data
r=compare_augments(data,'战争之影',['扳机炼狱','终极唤醒','掷骰狂人'])
assert [x['officialRank'] for x in r['cards']]==[1,4,17]
assert [x['pairWinRate'] for x in r['cards']]==[65.02,63.48,57.89]
assert [x['numGames'] for x in r['cards']]==[9014,31941,12638]
assert r['recommendedName']=='掷骰狂人'
annie=compare_augments(data,'黑暗之女',['扳机炼狱','终极唤醒','掷骰狂人'])
ultimate=next(row for row in annie['cards'] if row['name']=='终极唤醒')
assert ultimate['pairWinRate']==50.36 and ultimate['officialRank']==32
missing=compare_augments(data,'战争之影',['炼狱导管','终极唤醒','掷骰狂人'])
assert missing['missingOfficialStats']==['炼狱导管'] and missing['recommendedName'] is None
raw_rows=[x for h in wiki['championDetail'] for x in h['augmentRecommendations']]
normalized_rows=[x for rows in data['heroAugmentStats'].values() for x in rows]
blank_count=sum(x.get('winRate')=='' and x.get('numGames')==0 for x in raw_rows)
assert blank_count==1582 and len(raw_rows)==21288
assert sum(x['winRate'] is None and x['numGames']==0 for x in normalized_rows)==blank_count
report={'result':'passed','scope':'One separately downloaded official version395 snapshot; no live-game outcome accuracy claimed','sourceDataDate':'2026-09-07','gamePatch':data['metadata']['gamePatch'],'counts':{'heroes':len(data['heroes']),'augments':len(data['augments']),'items':len(data['items']),'heroAugmentRows':len(raw_rows),'blankWinRateZeroSamples':blank_count},'sha256':hashes,'hecarimThree':[{'name':x['name'],'sourceRank':x['officialRank'],'tier':x['tier'],'winRate':x['pairWinRate'],'pickRate':x['pickRate'],'numGames':x['numGames']} for x in r['cards']],'heroSwitch':{'hero':'黑暗之女','augment':'终极唤醒','sourceRank':ultimate['officialRank'],'winRate':ultimate['pairWinRate']},'missingPairVerified':'战争之影 + 炼狱导管 remains unrecorded; no invented pair stats','normalizationIdempotent':True}
text=json.dumps(report,ensure_ascii=False,indent=2)+'\n';print(text)
if args.output:args.output.write_text(text,encoding='utf8')

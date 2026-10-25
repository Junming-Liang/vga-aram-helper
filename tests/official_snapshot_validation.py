"""Developer-only, read a separately acquired official snapshot without bundling it.
Run: python tests/official_snapshot_validation.py --source-dir /path/to/wiki-json
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from engine import normalize, adapt_official_wiki
from patch_catalog import NEW_NAMES, RETIRED_NAMES, statistics_status
from public_payload import public_data, public_comparison
from core import compare_augments
parser=argparse.ArgumentParser();parser.add_argument('--source-dir',type=Path,required=True);parser.add_argument('--output',type=Path)
args=parser.parse_args()
files={'championDetail':'champion-detail','augmentDetail':'augment-detail','championList':'champion-list','augmentList':'augment-list','itemDetail':'item-detail'}
wiki={};hashes={}
for key,name in files.items():
    body=(args.source_dir/f'wiki-data-{name}.json').read_bytes();wiki[key]=json.loads(body);hashes[name]=hashlib.sha256(body).hexdigest()
wiki['version']='395'
raw={'wiki':wiki,'metadata':{'wikiBaseUrl':'https://fileserver.cdn.huya.com/game_tools/1-p81hl812-395/395/','sourceDataDate':'2026-09-07'}}
# This is an immutable historical-bundle audit, not current recommendation truth.
audit=adapt_official_wiki(raw)
assert len(audit['heroes'])==172 and len(audit['augments'])==209 and len(audit['items'])==180
data=normalize(raw)
assert set(data['augments']) == (set(audit['augments'])-RETIRED_NAMES)|NEW_NAMES
assert len(data['heroes'])==172 and len(data['items'])==180
assert normalize(data)==data
assert statistics_status(data)['ratingStatus']=='outdated'
assert data['metadata']['catalogCoverage']=='partial-official-delta'
assert data['augments']['罪恶快感']['augmentId']==''
assert '火箭' in data['augments']['罪恶快感']['description']
# Retain historical numeric assertions internally, without publishing them.
def historical(hero, name):
    return next((index,row) for index,row in enumerate(data['heroAugmentStats'][hero],1) if row['augmentName']==name)
old=[historical('战争之影',name) for name in ('扳机炼狱','终极唤醒','掷骰狂人')]
assert [index for index,row in old]==[1,4,17]
assert [row['winRate'] for index,row in old]==[65.02,63.48,57.89]
assert [row['numGames'] for index,row in old]==[9014,31941,12638]
index,ultimate=historical('黑暗之女','终极唤醒')
assert ultimate['winRate']==50.36 and index==32
raw_rows=[x for h in wiki['championDetail'] for x in h['augmentRecommendations']]
normalized_rows=[x for rows in data['heroAugmentStats'].values() for x in rows]
blank_count=sum(x.get('winRate')=='' and x.get('numGames')==0 for x in raw_rows)
assert blank_count==1582 and len(raw_rows)==21288
assert sum(x['winRate'] is None and x['numGames']==0 for x in normalized_rows)==blank_count
names=['扳机炼狱','终极唤醒','炼狱导管']
result=compare_augments(data,'战争之影',names)
assert result['recommendedName'] is None and all(card['sourceTier'] is None for card in result['cards'])
assert [card['name'] for card in result['cards']]==names
try:
    compare_augments(data,'战争之影',['扳机炼狱','终极唤醒','掷骰狂人'])
except ValueError:
    pass
else:
    raise AssertionError('Retired augment entered current comparison')
def public_safe(value):
    if isinstance(value,dict):
        assert not set(value)&{'winRate','pickRate','numGames','rank','officialRank','recommendedName','officialStats'}
        for key,child in value.items():
            if key in ('tier','sourceTier','overallTier'):assert child is None
            public_safe(child)
    elif isinstance(value,list):
        for child in value:public_safe(child)
public_safe(public_data(data));public_safe(public_comparison(data,'战争之影',names))
report={'result':'passed','scope':'Historical Huya 395 import audit plus current-patch abstention; not current statistics or full 4.0 catalog validation',
        'sourceDataDate':'2026-09-07','gamePatch':data['metadata']['gamePatch'],
        'counts':{'historicalHeroes':172,'historicalAugments':209,'historicalItems':180,'historicalHeroAugmentRows':len(raw_rows),
                  'currentPartialCatalogEntries':len(data['augments']),'officialAdditions':len(NEW_NAMES),'officialRetirements':len(RETIRED_NAMES)},
        'sha256':hashes,'historicalRowsVerifiedInternally':True,'oldRatingsWithheld':True,
        'retiredCandidateRejected':True,'sameNameIdentityIsolated':True,'publicStatisticsAbsent':True,
        'normalizationIdempotent':True,'catalogCoverage':'partial-official-delta'}
text=json.dumps(report,ensure_ascii=False,indent=2)+'\n';print(text)
if args.output:args.output.write_text(text,encoding='utf8')

"""Explicit browser/API projections. Internal source statistics never cross here."""
from copy import deepcopy
from native_state import display_cards, source_tier

METADATA = frozenset(('isDemo','title','source','sourceUrl','sourceDataDate','wikiDataVersion','gamePatch','officialHeroStatistics','latestChangelogDate','importedAt','licenseNote','dataFreshness','applicationName','applicationVersion'))
RECORD = frozenset(('name','description','alias','position','tips','championId','augmentId','sourceVersion','version','isSkillEnhancement','rarity','isDeleted','limit','types','total'))

def pick(record, fields):
    return {key:deepcopy(record[key]) for key in fields if key in record}

def links(rows):
    return [pick(row, ('name','reason','core')) for row in rows if isinstance(row,dict)]

def public_data(data):
    result={'metadata':pick(data.get('metadata',{}),METADATA)}
    for kind in ('heroes','augments','items'):
        result[kind]={}
        for name,row in data.get(kind,{}).items():
            item=pick(row,RECORD)
            allowed=('T1','T2','T3','T4','T5') if kind=='heroes' else ('T1','T2','T3','T4')
            item['overallTier']=row.get('overallTier') if row.get('overallTier') in allowed else None
            for field in ('items','specialItems','trapItems'):
                if field in row:item[field]=links(row[field])
            for field in ('changes','bugFixes'):
                item[field]=[pick(x,('version','text')) for x in row.get(field,[]) if isinstance(x,dict)]
            result[kind][name]=item
    result['relations']={name:{key:links(row.get(key,[])) for key in ('specialAugments','trapAugments')} for name,row in data.get('relations',{}).items()}
    def group(row):
        item=pick(row,('name','description','tips','last_update','heros'))
        item.update({key:links(row.get(key,[])) for key in ('augments','items')})
        return item
    result['combinations']=[dict(group(row),combinations=[group(x) for x in row.get('combinations',[])]) for row in data.get('combinations',[])]
    result['heroAugmentStats']={name:[dict(pick(row,('augmentName','augmentId','rarity','sourceUrl')),tier=source_tier(row.get('tier'))) for row in rows] for name,rows in data.get('heroAugmentStats',{}).items()}
    return result

def public_comparison(data, hero, offered):
    # Retain established validation, but never publish ranking/statistics output.
    from core import compare_augments
    compare_augments(data,hero,offered)
    return {'hero':hero,'offered':list(offered),'cards':display_cards(data,hero,[x.strip() for x in offered]),
            'policy':'literal-source-grades-v1','decision':'保留三个候选原位置，仅展示原始评级；缺失资料不推测。',
            'policyExplanation':'公开源评级快照，不是实时预测或 Riot 批准。','warnings':[]}

def public_recommendation(value):
    result=pick(value,('augment','missingItems','scoreMeaning'))
    for field in ('recommendations','warnings'):
        result[field]=[]
        for row in value.get(field,[]):
            item=pick(row,('name','score','core','warning'))
            item['evidence']=[pick(x,('score','source','reason')) for x in row.get('evidence',[])]
            result[field].append(item)
    return result

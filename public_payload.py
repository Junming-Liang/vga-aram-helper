"""Explicit browser/API projections. Internal source statistics never cross here."""
from copy import deepcopy
from native_state import display_cards, source_tier
from hero_strength import hero_strength_reference
from patch_catalog import (active_augment, ratings_available, pair_rating_available,
                           statistics_status, apply_official_catalog)

METADATA = frozenset(('isDemo','title','source','sourceUrl','sourceDataDate','wikiDataVersion','gamePatch','officialHeroStatistics','latestChangelogDate','importedAt','licenseNote','dataFreshness','applicationName','applicationVersion','catalogPatch','catalogRegion','catalogMode','catalogCoverage','catalogSourceUrl','catalogSourceDate','catalogCheckedDate','catalogConfidence'))
RECORD = frozenset(('name','description','alias','position','tips','championId','augmentId','sourceVersion','version','isSkillEnhancement','rarity','isDeleted','limit','types','total','catalogId','catalogStatus','catalogPatch','catalogSourceUrl','catalogSourceDate','catalogConfidence'))

def pick(record, fields):
    return {key:deepcopy(record[key]) for key in fields if key in record}

def links(rows):
    return [pick(row, ('name','reason','core')) for row in rows if isinstance(row,dict)]

def public_data(data):
    data = apply_official_catalog(data)
    result={'metadata':{key: value for key, value in pick(data.get('metadata',{}),METADATA).items()
                        if value is None or isinstance(value, (str, bool, int, float))}}
    result['metadata'].update(statistics_status(data))
    is_demo = data.get('metadata', {}).get('isDemo') is True
    for kind in ('heroes','augments','items'):
        result[kind]={}
        for name,row in data.get(kind,{}).items():
            if kind == 'augments':
                row = active_augment(data, name)
                if row is None:continue
            item=pick(row,RECORD)
            # Legacy prose/links have no independently reviewed current-patch
            # provenance. A fresh statistics marker cannot re-authorize them.
            if not is_demo:item.pop('tips', None)
            allowed=('T1','T2','T3','T4','T5') if kind=='heroes' else ('T1','T2','T3','T4')
            reference = hero_strength_reference(data, name) if kind == 'heroes' else None
            item['overallTier'] = (reference['sourceTier'] if reference else
                row.get('overallTier') if data.get('metadata', {}).get('isDemo') is True and row.get('overallTier') in allowed else None)
            for field in ('items','specialItems','trapItems'):
                if field in row:item[field]=links(row[field]) if is_demo else []
            for field in ('changes','bugFixes'):
                item[field]=[pick(x,('version','text')) for x in row.get(field,[]) if isinstance(x,dict)]
            result[kind][name]=item
    result['relations']={name:{key:links(row.get(key,[])) for key in ('specialAugments','trapAugments')} for name,row in data.get('relations',{}).items() if is_demo and ratings_available(data, name)}
    def group(row):
        item=pick(row,('name','description','tips','last_update','heros'))
        item.update({key:links(row.get(key,[])) for key in ('augments','items')})
        return item
    result['combinations']=[dict(group(row),combinations=[group(x) for x in row.get('combinations',[])]) for row in data.get('combinations',[])]
    result['heroAugmentStats'] = {name: [dict(pick(row, ('augmentName','augmentId','rarity','sourceUrl')),
        tier=source_tier(row.get('tier')) if pair_rating_available(data, name, row.get('augmentName'), row) else None)
        for row in rows if active_augment(data, row.get('augmentName')) is not None
        and active_augment(data, row.get('augmentName')).get('catalogStatus') != 'new']
        for name, rows in data.get('heroAugmentStats', {}).items()}
    if not is_demo:
        result['relations'] = {}
        result['combinations'] = []
    result['retiredAugments'] = {name: pick(row, ('name','catalogStatus','catalogPatch','catalogSourceUrl'))
                               for name, row in data.get('retiredAugments', {}).items() if isinstance(row, dict)}
    return result

def public_comparison(data, hero, offered):
    # Retain established validation, but never publish ranking/statistics output.
    from core import compare_augments
    compare_augments(data,hero,offered)
    return {'hero':hero,'offered':list(offered),'cards':display_cards(data,hero,[x.strip() for x in offered]),
            'policy':'literal-source-grades-v1','decision':('保留三个候选原位置，仅展示原始评级；缺失资料不推测。'
                if ratings_available(data, hero) else statistics_status(data, hero)['ratingMessage']),
            'policyExplanation':'公开源评级快照，不是实时预测或 Riot 批准。',
            'warnings':[] if ratings_available(data, hero) else [statistics_status(data, hero)['ratingMessage']]}

def public_recommendation(value):
    result=pick(value,('augment','missingItems','scoreMeaning'))
    for field in ('recommendations','warnings'):
        result[field]=[]
        for row in value.get(field,[]):
            item=pick(row,('name','score','core','warning'))
            item['evidence']=[pick(x,('score','source','reason')) for x in row.get('evidence',[])]
            result[field].append(item)
    return result

"""Hero + three offered augments from verified official hero-specific tables.

Primary order follows the published table, without recreating remote AI.
Legacy relations are supplemental; global winRate never ranks hero pairs.
"""
from __future__ import annotations
import re
from engine import plain

CONDITION_TERMS=('如果','需要','需配合','配合','前提','只有','搭配','拿到','有了','出了','出装','慎选','斟酌','但是','不过','注意','才能')
CAUTION_TERMS=('不推荐','不建议','强度不高','不要','别拿','没用','无效','不适合','不能触发','无法触发','吃不到','触发不了','不生效','会吞','吞掉')
POLICY='hero-evidence-v1'


def _notes(records,name):
    out=[]
    for record in records:
        if isinstance(record,dict) and record.get('name')==name:
            note={'reason':plain(record.get('reason')),'core':record.get('core') is True}
            if note not in out:out.append(note)
    return out


def compare_augments(data, hero_name, offered):
    if not isinstance(hero_name,str) or hero_name not in data.get('heroes',{}):
        raise ValueError('请先选择资料中存在的英雄。')
    if not isinstance(offered,list) or len(offered)!=3 or not all(isinstance(x,str) and x.strip() for x in offered):
        raise ValueError('需要恰好 3 个已确认的海克斯名称。')
    offered=[name.strip() for name in offered]
    if len(set(offered))!=3:raise ValueError('三个候选不能重复，请核对识别结果或手动修改。')
    missing=[name for name in offered if name not in data.get('augments',{})]
    if missing:raise ValueError('以下名称不在当前资料中：'+'、'.join(missing))
    from patch_catalog import active_augment, ratings_available, pair_rating_available, statistics_status
    inactive = [name for name in offered if active_augment(data, name) is None]
    if inactive:
        raise ValueError('以下名称已移除或不适用于当前目录：' + '、'.join(inactive))
    if not ratings_available(data, hero_name):
        from native_state import display_cards
        status = statistics_status(data, hero_name)
        return {'hero': hero_name, 'offered': offered,
                'cards': display_cards(data, hero_name, offered), 'groups': [],
                'recommendedName': None, 'pairWinRatesAvailable': False,
                'decision': status['ratingMessage'], 'policy': 'current-patch-abstention-v1',
                'policyExplanation': '旧版或来源不明的评级与关系不作为当前版本推荐。',
                'warnings': [status['ratingMessage']], 'source': data.get('metadata', {})}
    hero=data['heroes'][hero_name]
    relation=(data.get('relations',{}).get(hero_name,{})
              if data.get('metadata', {}).get('isDemo') is True else {})
    entries=[]
    for index,name in enumerate(offered):
        augment=active_augment(data, name)
        special=_notes(relation.get('specialAugments',[]),name)
        traps=_notes(relation.get('trapAugments',[]),name)
        if augment.get('catalogStatus') == 'new':
            special, traps = [], []
        reason_text=' '.join(x['reason'] for x in special)
        condition_flags=[term for term in CONDITION_TERMS if term in reason_text]
        caution_flags=[term for term in CAUTION_TERMS if term in reason_text]
        deleted=augment.get('isDeleted') is True
        core=any(note['core'] for note in special)
        if deleted:
            category,label,group='source-deleted','资料标记已移除，需核对版本',4
        elif special and traps:
            category,label,group='conflict','英雄资料有正反冲突',3
        elif traps:
            category,label,group='trap','英雄专属陷阱提醒',3
        elif special and (condition_flags or caution_flags):
            category,label,group='conditional','有英雄依据，条件待核对',2
        elif special and core:
            category,label,group='core-synergy','英雄资料标记核心联动',0
        elif special:
            category,label,group='synergy','有英雄专项联动说明',1
        else:
            category,label,group='unknown','暂无英雄专项记录',2
        global_rate=augment.get('winRate')
        # Some source entries use zero; sampling semantics are not established.
        displayed_rate=global_rate if isinstance(global_rate,(int,float)) and not isinstance(global_rate,bool) and 0<global_rate<=100 else None
        tags=set(hero.get('position',[]))
        entries.append({'name':name,'slot':index+1,'category':category,'label':label,'priorityGroup':group,
                        'sourceCore':core,'positiveEvidence':special,'trapEvidence':traps,
                        'conditionFlags':condition_flags,'cautionFlags':caution_flags,'sourceDeleted':deleted,
                        'matchingTags':[tag for tag in augment.get('limit',[]) if tag in tags],
                        'sourceLimitTags':augment.get('limit',[]),'pairWinRate':None,
                        'globalReferenceWinRate':displayed_rate,'globalRateUsedForRanking':False,
                        'globalRateNote':'海克斯全局参考值；样本/日期未提供，不参与本次英雄排序。' if displayed_rate is not None else '未提供可靠的全局参考值；源值0不当作已验证0%胜率。',
                        'version':augment.get('version',[]),'changes':augment.get('changes',[]),'bugFixes':augment.get('bugFixes',[]),
                        'isSkillEnhancement':augment.get('isSkillEnhancement',False)})
    # Stable input-order tie handling: never imply an arbitrary global-rate tie-break.
    entries.sort(key=lambda card:(card['priorityGroup'],card['slot']))
    # Newer official wiki statistics are the primary ranking source when available.
    stats_by_name={}
    stats_rows=data.get('heroAugmentStats',{}).get(hero_name,[])
    for source_index,row in enumerate(stats_rows):
        if not isinstance(row,dict):continue
        name=row.get('augmentName') or row.get('name')
        if not isinstance(name,str) or name in stats_by_name:continue
        if not pair_rating_available(data, hero_name, name, row):continue
        stats_by_name[name]={**row,'sourceRank':source_index+1}
    if stats_rows:
        for entry in entries:
            official=stats_by_name.get(entry['name'])
            entry['officialStats']=official
            entry['officialRank']=official['sourceRank'] if official else None
            entry['pairWinRate']=official.get('winRate') if official else None
            entry['pickRate']=official.get('pickRate') if official else None
            entry['numGames']=official.get('numGames') if official else None
            entry['tier']=official.get('tier') if official else None
        entries.sort(key=lambda entry:(entry['officialRank'] is None,entry['officialRank'] or 0,entry['slot']))
        known=[entry for entry in entries if entry['officialStats'] is not None]
        missing_names=[entry['name'] for entry in entries if entry['officialStats'] is None]
        insufficient=[entry['name'] for entry in known if entry['pairWinRate'] is None or entry['numGames'] is None or entry['numGames']<=0]
        first=known[0] if known else None
        conflict=bool(first and (first['trapEvidence'] or first['sourceDeleted']))
        recommended=first['name'] if first and not missing_names and not insufficient and not conflict else None
        if recommended:
            decision='按官方英雄专属推荐列表的顺序，优先考虑 '+recommended+'。评级和统计见下方，玩法条件仍需核对。'
        elif first and missing_names:
            decision='已收录选项中 '+first['name']+' 的官方顺位最高，但 '+ '、'.join(missing_names)+' 缺少该英雄统计，无法完成三项比较。'
        elif insufficient:
            decision='官方源顺位已展示，但 '+ '、'.join(insufficient)+' 缺少有效胜率或样本，统计不足，暂不给出唯一推荐。'
        elif conflict:
            decision='官方排序首项与另一来源的陷阱/移除记录冲突，请先核对版本和说明，暂不自动给出唯一选择。'
        else:
            decision='三个选项均未出现在该英雄的官方推荐记录中，暂不推测排名。'
        if data.get('metadata',{}).get('isDemo'):
            decision='【虚构演示，不可用于对局】'+decision.replace('官方','演示')
        return {'hero':hero_name,'offered':offered,'cards':entries,'groups':[],
                'recommendedName':recommended,'bestRecordedName':first['name'] if first else None,
                'missingOfficialStats':missing_names,'insufficientStatistics':insufficient,'completeComparison':not missing_names and not insufficient,
                'decision':decision,'policy':'official-hero-source-order-v1',
                'pairWinRatesAvailable':any(entry['pairWinRate'] is not None for entry in entries),
                'policyExplanation':'优先使用官方 champion-detail 中该英雄 augmentRecommendations 的源顺序；同时展示源 tier、英雄配对 winRate、pickRate 和 numGames。未收录的候选不假装低分，全局胜率不参与排序。',
                'warnings':['这是官方公开资料快照的排序，不是复现虎牙云端AI模型，也不保证适用于当前对局。','旧版联动/陷阱说明单独保留；与统计冲突时明确提醒。'],
                'source':data.get('metadata',{})}
    for entry in entries:
        entry.update(officialStats=None,officialRank=None,pickRate=None,numGames=None,tier=None)
    groups=[]
    for entry in entries:
        if not groups or groups[-1]['priorityGroup']!=entry['priorityGroup']:
            groups.append({'priorityGroup':entry['priorityGroup'],'names':[]})
        groups[-1]['names'].append(entry['name'])
    top=groups[0]
    recommended=top['names'][0] if top['priorityGroup']<2 and len(top['names'])==1 else None
    if recommended:
        decision='按当前英雄专项资料，可优先考虑 '+recommended+'；请同时核对下方原始理由与版本。'
    elif top['priorityGroup']<2:
        decision='这些候选有同档英雄专项依据，资料不足以分出唯一最优；并列展示。'
    elif top['priorityGroup']==2:
        decision='没有足够明确的依据给出唯一推荐。请核对条件，或根据当前玩法选择；未收录不代表弱。'
    else:
        decision='三项均有陷阱、冲突或版本风险，当前资料无法给出可靠推荐。'
    return {'hero':hero_name,'offered':offered,'cards':entries,'groups':groups,'recommendedName':recommended,
            'decision':decision,'policy':POLICY,'pairWinRatesAvailable':False,
            'policyExplanation':'本地证据序：无警告的源核心联动、英雄专项联动、条件待核对/未收录、陷阱或冲突、源已移除。同档并列；不使用全局胜率排序。不是虎牙云端AI评级。',
            'warnings':['当前已加载的数据中未取得该英雄的官方推荐统计；这里只能展示联动/陷阱依据，不能代替官方评分。',
                        '条件/负面词提醒只是提示阅读原文，不能证明条件已满足，也不自动推断游戏机制。'],
            'source':data.get('metadata',{})}

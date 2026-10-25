"""Reviewed CN Mayhem 26.21 delta and fail-closed statistics applicability.

Announcement identities are NOT numeric game/Huya IDs. This is a partial delta,
not a reconstructed full pool. No network calls, performance tiers or estimates.
"""
from copy import deepcopy
from datetime import date
import re

CURRENT_PATCH = '26.21'
PATCH_ALIASES = frozenset({'26.21', '16.21'})
RELEASE_DATE = '2026-10-22'
CHECKED_DATE = '2026-10-23'
OFFICIAL_URL = 'https://lol.qq.com/gicp/news/410/37099805.html'
WIKI_URL = 'https://gametool.huya.com/league-of-legends/wiki/index.html?embed=1'

# Original short mechanism summaries of the CN announcement, not client text.
# No numeric game IDs or statistical grades were published in that announcement.
_NEW = (
    ('蓝色屏障', 'silver', '施法时按法力消耗获得护盾。'),
    ('灵魂乐流', 'silver', '指定技能可提供叠加的攻击速度。'),
    ('水果化', 'silver', '参与击杀产生可恢复生命与法力的水果。'),
    ('溺水之赠礼', 'silver', '装备提供的额外生命值转为穿甲。'),
    ('远射天资', 'silver', '在最大射程附近攻击可造成额外伤害。'),
    ('巫妖大脑', 'silver', '根据额外生命值获得法术强度。'),
    ('孤勇者', 'silver', '附近有敌方英雄时获得双抗和攻击速度。'),
    ('没法力，没问题', 'silver', '法力相关装备属性转为法术强度。国服公告写法力回复，英文公告写法力值；具体属性以游戏内说明为准。'),
    ('音之屏障', 'silver', '获得护盾时提高移动速度。'),
    ('终极循环往复', 'silver', '获得终极技能急速。'),
    ('奥术公理', 'gold', '参与击杀返还终极技能冷却时间。'),
    ('装甲冲击', 'gold', '施法后强化普攻，伤害与护甲相关。'),
    ('小蜜蜂！！！', 'gold', '蜂巢爆炸造成伤害和减速，并触发攻击特效。'),
    ('黄铜爆音', 'gold', '获得可蓄力吹响号角并击退敌人的召唤师技能。'),
    ('深红钴蓝闪光', 'gold', '指定技能留下标记，消耗标记可造成伤害并返还冷却。'),
    ('翻倍时间', 'gold', '短时间内命中不同技能可积累法力与伤害。'),
    ('迷人蝴蝶', 'gold', '治疗或护盾积累蝴蝶，蝴蝶可伤害敌人。'),
    ('罪恶快感', 'gold', '获得骑乘爆炸火箭的召唤师技能。不是旧版同名的参与击杀加速强化。'),
    ('王冠之重', 'gold', '提高攻击、法强和攻速，但降低移速；击杀参与和死亡影响收益。'),
    ('珠光手镯', 'gold', '终极技能可以暴击。'),
    ('反冲', 'gold', '指定技能施放时让自身向后位移。'),
    ('拯救', 'gold', '低生命值时击退敌人并治疗友军。'),
    ('吸元秘术', 'gold', '周期性强化攻击，造成伤害并恢复生命。'),
    ('屹立不倒', 'gold', '损失生命值可提高攻击、法强与生命偷取。'),
    ('将他们放倒倒倒', 'gold', '连续命中后触发额外伤害与治疗。'),
    ('鼓声暴起 低音轰鸣', 'gold', '技能后的普攻提供额外伤害和移动速度。'),
    ('嗡嗡怪兽', 'gold', '装备提供的攻击力转为攻击速度。'),
    ('升级：风暴狂涌', 'gold', '强化风暴狂涌的范围效果和后续标记。'),
    ('命运之武器', 'gold', '第一件传说装备可随击杀参与成长。'),
    ('大腕', 'prismatic', '将攻击速度转为暴击伤害。'),
    ('弹跳蜜蜂', 'prismatic', '施法后普攻可以弹跳，完成任务后得到强化。'),
    ('一起抱抱', 'prismatic', '指定治疗或护盾可影响附近友军。'),
    ('热舞怪兽', 'prismatic', '终极技能提供额外生命值与减速区域，随击杀参与增强。'),
    ('伤不过三', 'prismatic', '第三次攻击触发爆发伤害和攻击速度。'),
    ('死之舞', 'prismatic', '暂时无法被击杀，期间必须参与击杀才能避免死亡。'),
)
NEW_NAMES = frozenset(name for name, _, _ in _NEW)
RETIRED = (
    ('炽燃利息', '2128'), ('由暴生急', '2024'), ('暴击飞弹', '1356'),
    ('位面转移', '2063'), ('空投熊', '2031'), ('飞身踢', '2006'),
    ('连拨击锤', '1220'), ('藏身草丛', '2042'), ('掷骰狂人', '2095'),
    ('我们的治疗', '2082'), ('魄罗蛮冲', '2046'), ('心灵净化', '1345'), ('大招工具人', '2118'),
)
RETIRED_NAMES = frozenset(name for name, _ in RETIRED)


def official_records():
    """Fresh independent records: no accidental legacy-name merge or numeric ID."""
    return {name: {'name': name, 'rarity': rarity, 'description': description,
                   'augmentId': '', 'catalogId': 'tencent-cn:26.21:' + name,
                   'catalogStatus': 'new', 'catalogPatch': CURRENT_PATCH,
                   'catalogSourceUrl': OFFICIAL_URL, 'catalogSourceDate': '2026-10-21',
                   'catalogConfidence': 'official-announcement', 'isDeleted': False,
                   'version': [CURRENT_PATCH], 'alias': [], 'items': [],
                   'specialItems': [], 'trapItems': []}
            for name, rarity, description in _NEW}


def _meta(data):
    meta = data.get('metadata') if isinstance(data, dict) else None
    return meta if isinstance(meta, dict) else {}


def is_public_source(data):
    meta = _meta(data)
    return (meta.get('isDemo') is not True and meta.get('officialHeroStatistics') is True
            and meta.get('sourceUrl') == WIKI_URL)


def _valid_date(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def statistics_status(data, hero=None):
    """Recompute from source facts; fetchedAt/cached booleans cannot grant a tier."""
    meta = _meta(data)
    patch = meta.get('gamePatch')
    patch = patch if isinstance(patch, str) and re.fullmatch(r'\d{1,3}\.\d{1,3}(?:\.\d{1,3})?', patch) else None
    stamp = _valid_date(meta.get('sourceDataDate'))
    heroes = data.get('heroes') if isinstance(data, dict) else None
    record = heroes.get(hero) if isinstance(heroes, dict) and hero is not None else None
    if meta.get('isDemo') is True:
        status, message = 'demo', '虚构演示，不能用于对局。'
    elif not is_public_source(data):
        status, message = 'unverified', '来源待核对，当前版本评级暂不展示。'
    elif patch not in PATCH_ALIASES:
        # Only independently reviewed aliases are accepted; no major-offset math.
        status = 'outdated' if patch in {'16.17', '26.17', '16.18', '26.18', '16.19', '26.19', '16.20', '26.20'} else 'unverified'
        message = ('旧版 ' + patch + ' 评级不适用于国服 ' + CURRENT_PATCH + '；等待新版统计。'
                   if status == 'outdated' else '统计版本待核对，当前版本评级暂不展示。')
    elif stamp is None or stamp < date.fromisoformat(RELEASE_DATE) or stamp > date.today():
        status, message = 'unverified', '统计日期缺失或与国服版本不符，当前版本评级暂不展示。'
    elif hero is not None and (not isinstance(record, dict)
            or not isinstance(record.get('sourceVersion'), str)
            or record['sourceVersion'] not in PATCH_ALIASES):
        status, message = 'unverified', '英雄行版本缺失或不匹配，当前版本评级暂不展示。'
    else:
        status, message = 'current', '版本和日期匹配的公开源快照；统计地区与区间仍未核实。'
    return {'ratingStatus': status, 'ratingMessage': message,
            'targetGamePatch': CURRENT_PATCH, 'statisticsPatch': patch,
            'statisticsDate': stamp.isoformat() if stamp else None,
            'statisticsRegion': 'unverified',
            'ratingConfidence': 'source-snapshot' if status == 'current' else 'unverified'}


def ratings_available(data, hero=None):
    return statistics_status(data, hero)['ratingStatus'] in ('demo', 'current')


def active_augment(data, name):
    """Presentation defense also works for direct callers bypassing normalize."""
    item = data.get('augments', {}).get(name)
    if not isinstance(item, dict):
        return None
    if is_public_source(data):
        if name in RETIRED_NAMES:
            return None
        if name in NEW_NAMES:
            return official_records()[name]
    return None if item.get('isDeleted') is True else item


def pair_rating_available(data, hero, name, row):
    if not ratings_available(data, hero):
        return False
    item = active_augment(data, name)
    if item is None or not isinstance(row, dict):
        return False
    if _meta(data).get('isDemo') is True:
        return True
    if item.get('catalogStatus') == 'new' or name in NEW_NAMES:
        return False  # Announcement IDs have no reviewed statistics crosswalk yet.
    aid = item.get('augmentId')
    return (isinstance(aid, str) and re.fullmatch(r'[0-9]{1,12}', aid) is not None
            and row.get('augmentId') == aid)


def apply_official_catalog(data):
    """Overlay only reviewed Huya Mayhem imports; never alter fictional datasets.

    Cached raw source remains intact. Historical ratings remain internal audit
    data, but retired/colliding name relationships cannot enter active outputs.
    """
    if not is_public_source(data):
        return data
    result = deepcopy(data)
    meta = result['metadata']
    meta.update(catalogPatch=CURRENT_PATCH, catalogRegion='CN', catalogMode='ARAM: Mayhem',
                catalogCoverage='partial-official-delta', catalogSourceUrl=OFFICIAL_URL,
                catalogSourceDate='2026-10-21', catalogCheckedDate=CHECKED_DATE,
                catalogConfidence='official-announcement', **statistics_status(data))
    augments = result.setdefault('augments', {})
    for name in RETIRED_NAMES:
        augments.pop(name, None)
    for item in augments.values():
        if isinstance(item, dict):
            item.setdefault('catalogStatus', 'carried_forward_unverified')
    augments.update(official_records())
    result['retiredAugments'] = {name: {'name': name, 'catalogStatus': 'retired',
        'catalogPatch': CURRENT_PATCH, 'catalogSourceUrl': OFFICIAL_URL,
        'legacySourceId': aid, 'legacySourceNamespace': 'huya-wiki-395'} for name, aid in RETIRED}
    blocked = NEW_NAMES | RETIRED_NAMES
    for relation in result.get('relations', {}).values():
        if isinstance(relation, dict):
            for key in ('specialAugments', 'trapAugments'):
                relation[key] = [row for row in relation.get(key, []) if isinstance(row, dict) and row.get('name') not in blocked]
    # Legacy bundles are optional references. A bundle containing an old identity
    # must not become a recommendation for a new same-name mechanic.
    def safe_group(group):
        return isinstance(group, dict) and not any(
            (row if isinstance(row, str) else row.get('name') if isinstance(row, dict) else None) in blocked
            for row in group.get('augments', []))
    groups = []
    for group in result.get('combinations', []):
        if safe_group(group):
            group['combinations'] = [branch for branch in group.get('combinations', []) if safe_group(branch)]
            groups.append(group)
    result['combinations'] = groups
    return result

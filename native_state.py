"""UI-independent conservative state for manually confirmed screenshot candidates."""
from dataclasses import dataclass,field
import math
import re
import unicodedata

@dataclass
class RecognitionState:
    hero: str = ''
    running: bool = False
    target: tuple | None = None
    generation: int = 0
    offered: tuple = ()
    observed: tuple = ()
    stable_frames: int = 0
    confirmed: bool = False
    confirmed_observation: tuple = ()
    reason: str = '尚未开始'
    hero_observed: str = ''
    hero_stable_frames: int = 0
    confirmation_mode: str = 'manual'
    automatic_observed: tuple = ()
    automatic_frames: int = 0

    def invalidate(self, reason, *, clear_observed=True):
        self.generation+=1;self.confirmed=False;self.confirmed_observation=();self.offered=();self.reason=reason
        if clear_observed:self.observed=();self.stable_frames=0;self.automatic_observed=();self.automatic_frames=0
        return self.generation
    def select_hero(self, hero):
        if hero!=self.hero:self.hero=hero;self.invalidate('英雄已变化，请重新确认三个候选')
    def start(self,target):
        self.target=tuple(target);self.running=True;self.invalidate('监测已开始，等待目标窗口位于前台')
    def stop(self):
        self.running=False;self.invalidate('监测已停止')
    def observe(self,names, *, generation=None):
        if not self.running or (generation is not None and generation!=self.generation):return False
        names=tuple(names)
        if self.confirmed and names==self.confirmed_observation:return True
        if len(names)!=3 or len(set(names))!=3:
            self.invalidate('未稳定识别到三个不同候选，旧叠加已隐藏');return False
        if names!=self.observed:
            self.invalidate('候选变化，等待连续两次一致识别');self.observed=names;self.stable_frames=1;return False
        self.stable_frames+=1
        if self.stable_frames>=2 and not self.confirmed:self.reason='识别稳定，请核对英雄及三个名称后确认'
        return self.stable_frames>=2
    def observe_hero(self, hero):
        """Accept only the caller's high-confidence own-HUD identity. Unknown clears."""
        hero=hero if isinstance(hero,str) else ''
        if not self.running:return False
        if not hero:
            self.hero='';self.hero_observed='';self.hero_stable_frames=0
            self.invalidate('本人 HUD 英雄尚不确定，旧英雄与评级已清除')
            return False
        if hero!=self.hero_observed:
            self.hero='';self.hero_observed=hero;self.hero_stable_frames=1
            self.invalidate('发现新的 HUD 英雄，等待连续两帧一致')
            return False
        self.hero_stable_frames+=1
        if self.hero_stable_frames>=2:self.hero=hero
        return bool(self.hero)
    def clear_hero(self):
        self.hero='';self.hero_observed='';self.hero_stable_frames=0
        self.invalidate('等待重新识别本人 HUD 英雄')
    def observe_automatic_candidates(self,names,safe):
        names=tuple(names)
        if not self.running or not safe:
            self.automatic_observed=();self.automatic_frames=0;return False
        self.automatic_frames=self.automatic_frames+1 if names==self.automatic_observed else 1
        self.automatic_observed=names
        return self.automatic_frames>=2
    def confirm(self,names,vocabulary, *, automatic=False):
        names=tuple(str(x).strip() for x in names)
        if not self.running:raise ValueError('请先选择目标窗口并开始监测。')
        if not self.hero:raise ValueError('尚未可靠识别本人英雄；可等待下一帧或人工纠正。')
        if len(names)!=3 or len(set(names))!=3 or any(not x or x not in vocabulary for x in names):raise ValueError('请确认三个不同且词典中存在的海克斯名称。')
        self.generation+=1;self.confirmed_observation=self.observed or names;self.offered=names;self.observed=self.confirmed_observation;self.stable_frames=2;self.confirmed=True;self.confirmation_mode='automatic' if automatic else 'manual';self.reason='三个候选已连续高置信识别，使用已确定的本人英雄自动显示资料' if automatic else '名称已手动确认，显示英雄相关资料'
        return self.generation


# Observed literal vocabulary in the verified public hero-specific table.
# Unknown/new schemes stay ungraded until their source meaning is verified.
SOURCE_TIERS=frozenset({'T1','T2','T3','T4'})


def source_tier(value):
    return value.strip() if isinstance(value,str) and value.strip() in SOURCE_TIERS else None


def display_cards(data, hero, offered):
    """Keep screen order; only expose source grades applicable to this patch.

    Transport freshness is not statistical applicability. Announcement identities
    cannot inherit a same-name historical row, description or combo.
    """
    from patch_catalog import (active_augment, pair_rating_available,
                               statistics_status)
    from source_combo_hints import source_combo_hint
    status = statistics_status(data, hero)
    is_demo = data.get('metadata', {}).get('isDemo') is True
    rows = {}
    for row in data.get('heroAugmentStats', {}).get(hero, []):
        if isinstance(row, dict) and isinstance(row.get('augmentName'), str):
            rows.setdefault(row['augmentName'], row)
    relation = data.get('relations', {}).get(hero, {})
    cards = []
    for slot, name in enumerate(offered, 1):
        row = rows.get(name, {})
        item = active_augment(data, name)
        available = pair_rating_available(data, hero, name, row)
        new = item is not None and item.get('catalogStatus') == 'new'
        notes = [record.get('reason', '') for key in ('specialAugments', 'trapAugments')
                 for record in relation.get(key, []) if isinstance(record, dict)
                 and record.get('name') == name] if is_demo and not new and item else []
        label = ('虚构源评级（演示）' if is_demo else '新版评级待核实' if new else
                 '旧版评级不适用' if status['ratingStatus'] == 'outdated' else
                 '虎牙公开源评级' if available else '评级待核实')
        cards.append({'name': name, 'slot': slot,
            'description': display_description(item.get('description', '描述未提供')) if item else '描述未提供',
            'sourceTier': source_tier(row.get('tier')) if available else None, 'notes': notes,
            'sourceTierLabel': label,
            'sourceLabel': '虚构演示' if is_demo else
                ('国服 26.21 官方新增目录；无已核实的新版评级。' if new else status['ratingMessage']) + ' 非 Riot 评级/批准。',
            'ratingStatus': 'unverified' if new or item is None else status['ratingStatus'],
            'catalogStatus': item.get('catalogStatus', 'unverified') if item else 'retired_or_unknown',
            'sourceDataDate': status['statisticsDate'],
            'gamePatch': status['statisticsPatch'], 'targetGamePatch': status['targetGamePatch'],
            'catalogSourceUrl': item.get('catalogSourceUrl') if new else None,
            'catalogSourceDate': item.get('catalogSourceDate') if new else None,
            'catalogConfidence': item.get('catalogConfidence') if new else 'unverified'})
        hint = source_combo_hint(data, hero, name) if not is_demo and item and not new else None
        if hint:
            cards[-1]['sourceHint'] = hint['text']
            cards[-1]['sourceHintProvenance'] = hint
    return cards


def automatic_candidates(candidates, image_size):
    """Exact unique titles, high OCR confidence, aligned in three screen columns.

    This is a conservative scene heuristic, never a guarantee of game context.
    Confidence measures OCR quality, not game win rate. Invalid boxes abstain.
    """
    if not isinstance(candidates,list) or len(candidates)!=3:return False
    if not isinstance(image_size,dict):return False
    width=image_size.get('width');height=image_size.get('height')
    if not all(isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) and v>=64 for v in (width,height)):return False
    names=[];centers=[]
    for item in candidates:
        if not isinstance(item,dict) or item.get('match_method')!='exact':return False
        conf=item.get('ocr_confidence')
        if not isinstance(conf,(int,float)) or isinstance(conf,bool) or not math.isfinite(conf) or not .93<=conf<=1:return False
        name=item.get('name')
        if not isinstance(name,str) or not name or name in names:return False
        if ''.join(unicodedata.normalize('NFKC',str(item.get('recognized_text',''))).split())!=''.join(unicodedata.normalize('NFKC',name).split()):return False
        names.append(name);box=item.get('box')
        if not isinstance(box,list) or len(box)!=4:return False
        if any(not isinstance(p,(list,tuple)) or len(p)!=2 or any(not isinstance(v,(int,float)) or isinstance(v,bool) or not math.isfinite(v) for v in p) for p in box):return False
        xs=[p[0] for p in box];ys=[p[1] for p in box]
        if min(xs)<0 or max(xs)>width or min(ys)<0 or max(ys)>height:return False
        x=(min(xs)+max(xs))/2/width;y=(min(ys)+max(ys))/2/height
        if not .015<=(max(ys)-min(ys))/height<=.20 or not .02<=(max(xs)-min(xs))/width<=.28:return False
        centers.append((x,y))
    if not all(i/3+.02<=x<=(i+1)/3-.02 for i,(x,y) in enumerate(centers)):return False
    if not all(.08<=y<=.82 for x,y in centers):return False
    if max(y for x,y in centers)-min(y for x,y in centers)>.06:return False
    return True


def display_description(text):
    """Remove unresolved source display tokens without fabricating effect values."""
    text=str(text)
    cleaned,count=re.subn(r'%i:[^%\r\n]{1,80}%', '[来源图标]', text)
    if count or re.search(r'\{\{[^}]+\}\}|@[^@\s]+@',text):
        return cleaned+'（来源含未展开标记，具体数值以游戏内说明为准）'
    return cleaned

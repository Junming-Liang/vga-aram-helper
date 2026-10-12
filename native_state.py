"""UI-independent conservative state for manually confirmed screenshot candidates."""
from dataclasses import dataclass,field

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

    def invalidate(self, reason, *, clear_observed=True):
        self.generation+=1;self.confirmed=False;self.confirmed_observation=();self.offered=();self.reason=reason
        if clear_observed:self.observed=();self.stable_frames=0
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
    def confirm(self,names,vocabulary):
        names=tuple(str(x).strip() for x in names)
        if not self.running:raise ValueError('请先选择目标窗口并开始监测。')
        if not self.hero:raise ValueError('请先手动选择英雄；软件不会猜测英雄。')
        if len(names)!=3 or len(set(names))!=3 or any(not x or x not in vocabulary for x in names):raise ValueError('请确认三个不同且词典中存在的海克斯名称。')
        self.generation+=1;self.confirmed_observation=self.observed or names;self.offered=names;self.observed=self.confirmed_observation;self.stable_frames=2;self.confirmed=True;self.reason='名称已手动确认，显示英雄相关资料'
        return self.generation


def display_cards(data, hero, offered, *, include_source_ranks=False):
    """Neutral names/effects by default. Source ranks gated pending policy review.

    Never exposes win rates or a unique-best recommendation.
    """
    rows={row['augmentName']:(index+1,row) for index,row in enumerate(data.get('heroAugmentStats',{}).get(hero,[]))}
    relation=data.get('relations',{}).get(hero,{})
    cards=[]
    for slot,name in enumerate(offered,1):
        rank,row=rows.get(name,(None,{}));item=data.get('augments',{}).get(name,{})
        notes=[record.get('reason','') for key in ('specialAugments','trapAugments') for record in relation.get(key,[]) if record.get('name')==name]
        cards.append({'name':name,'slot':slot,'description':item.get('description','描述未提供'),
            'sourceTier':(row.get('tier') or '未收录') if include_source_ranks else None,'sourceRank':rank if include_source_ranks else None,'notes':notes,
            'sourceLabel':'虚构演示' if data.get('metadata',{}).get('isDemo') else '第三方源资料；非 Riot 评级/批准'})
    return cards

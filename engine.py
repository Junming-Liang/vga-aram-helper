"""Original data adapter and deterministic reference recommendation rules.

No target application code is loaded or executed. Scores rank source links; they
are neither win rates nor estimates of live-game performance.
"""
from __future__ import annotations

from copy import deepcopy
from html import unescape
from html.parser import HTMLParser
import json
import math
import re
from pathlib import Path


class PlainText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1
        if tag in {"br", "li", "p", "div"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def plain(value):
    if not isinstance(value, str):
        return ""
    parser = PlainText()
    parser.feed(value)
    return unescape("".join(parser.parts)).strip()


def names(value):
    return [v for v in value if isinstance(v, str)] if isinstance(value, list) else []


def number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else None


def links(value):
    result = []
    if not isinstance(value, list):
        return result
    for item in value:
        if isinstance(item, str):
            result.append({"name": item, "reason": "", "core": False})
        elif isinstance(item, dict) and isinstance(item.get("name"), str):
            result.append({"name": item["name"], "reason": plain(item.get("reason")), "core": item.get("core") is True})
    return result



def percentage(value):
    if isinstance(value,str) and re.fullmatch(r"\s*\d+(?:\.\d+)?%\s*",value):
        result=float(value.strip().rstrip('%'))
        return result if 0<=result<=100 else None
    return number(value) if isinstance(value,(int,float)) and 0<=value<=100 else None


def adapt_official_wiki(raw):
    """New official hero-specific statistics; use text/numbers, never vendor assets."""
    wiki=raw.get('wiki')
    if not isinstance(wiki,dict) or not isinstance(wiki.get('championDetail'),list):return raw
    output=deepcopy(raw)
    old_heroes=output.get('heroes',{})
    old_augments=output.get('augments',{})
    output['heroes']={};output['augments']={};output['items']={};output['heroAugmentStats']={}
    metadata=output.setdefault('metadata',{})
    metadata.update(isDemo=False,officialHeroStatistics=True,wikiDataVersion=str(wiki.get('version','')))
    metadata.setdefault('sourceUrl','https://gametool.huya.com/league-of-legends/wiki/index.html?embed=1')
    base=metadata.get('wikiBaseUrl','')
    rarity_map={'棱彩':'prismatic','黄金':'gold','白银':'silver','prismatic':'prismatic','gold':'gold','silver':'silver'}
    for row in wiki.get('augmentDetail',[]):
        if not isinstance(row,dict) or not isinstance(row.get('augmentName'),str):continue
        name=row['augmentName'];legacy=old_augments.get(name,{})
        output['augments'][name]={**legacy,'name':name,'augmentId':str(row.get('augmentId','')),
            'description':row.get('description',''),'rarity':rarity_map.get(row.get('rarity'),'unknown'),
            'winRate':percentage(row.get('winRate')),'version':[str(row['version'])] if row.get('version') else [],
            'isDeleted':False,'officialTier':row.get('tier',''),'officialPickRate':percentage(row.get('pickRate'))}
    for row in wiki['championDetail']:
        if not isinstance(row,dict) or not isinstance(row.get('championName'),str):continue
        full=row['championName'];name,_,alias=full.partition(' ')
        if name in output['heroes']:name=full
        legacy=old_heroes.get(name,{})
        aliases=list(dict.fromkeys([x for x in [alias,full,*legacy.get('alias',[]),*(['人马'] if str(row.get('championId'))=='120' else [])] if isinstance(x,str) and x]))
        output['heroes'][name]={**legacy,'name':name,'alias':aliases,'championId':str(row.get('championId','')),
            'winRate':percentage(row.get('winRate')),'overallPickRate':percentage(row.get('pickRate')),
            'overallTier':row.get('tier',''),'sourceVersion':str(row.get('version',''))}
        if row.get('version'):metadata.setdefault('gamePatch',str(row['version']))
        stats=[]
        for item in row.get('augmentRecommendations',[]):
            if not isinstance(item,dict) or not isinstance(item.get('augmentName'),str):continue
            augment_name=item['augmentName']
            # Keep offered names present in actual hero stats even if detail catalog has a gap.
            if augment_name not in output['augments']:
                output['augments'][augment_name]={'name':augment_name,'augmentId':str(item.get('augmentId','')),
                    'rarity':rarity_map.get(item.get('rarity'),'unknown'),'description':'官方英雄表存在此海克斯，完整描述暂缺。'}
            stats.append({'augmentName':augment_name,'augmentId':str(item.get('augmentId','')),
                'rarity':rarity_map.get(item.get('rarity'),'unknown'),'tier':str(item.get('tier','')),
                'winRate':percentage(item.get('winRate')),'pickRate':percentage(item.get('pickRate')),
                'numGames':number(item.get('numGames')),'rateUnit':'percent',
                'sourceUrl':base+'champion-detail.json' if base else metadata['sourceUrl']})
        output['heroAugmentStats'][name]=stats
    for name,row in wiki.get('itemDetail',{}).items():
        if isinstance(row,dict):output['items'][name]={'name':name,'description':row.get('description',''),'itemId':str(row.get('itemId',''))}
    return output

def normalize(raw):
    """Whitelist text fields; discard remote images, executable markup and extras."""
    raw = adapt_official_wiki(raw)
    from source_combo_hints import normalize_source_combos
    source_combos = normalize_source_combos(raw)
    data = {"metadata": deepcopy(raw.get("metadata", {})), "heroes": {}, "augments": {}, "items": {}, "relations": {}, "combinations": [], "heroAugmentStats": {}}
    data['heroSourceCombos'] = source_combos
    for kind in ["heroes", "augments", "items"]:
        source = raw.get(kind, {})
        if not isinstance(source, dict):
            raise ValueError(f"{kind} must be a JSON object")
        for name, record in source.items():
            if not isinstance(name, str) or not isinstance(record, dict):
                raise ValueError(f"Invalid {kind} record")
            item = {"name": name, "description": plain(record.get("description")), "alias": names(record.get("alias")),
                    "position": names(record.get("position")), "winRate": number(record.get("winRate")),
                    "tips": plain(record.get("tips")), "championId": str(record.get("championId","")), "augmentId": str(record.get("augmentId","")), "sourceVersion":str(record.get("sourceVersion","")), "overallTier":str(record.get("overallTier","")), "overallPickRate":number(record.get("overallPickRate")), "version": names(record.get("version")),
                    "isSkillEnhancement": record.get("isSkillEnhancement") is True,
                    "changes": [{"version":str(x.get("version","")),"text":plain(x.get("text",x.get("changesHtml","")))} for x in record.get("changes",[]) if isinstance(x,dict)],
                    "bugFixes": [{"version":str(x.get("version","")),"text":plain(x.get("text",x.get("changesHtml","")))} for x in record.get("bugFixes",[]) if isinstance(x,dict)]}
            if kind == "augments":
                item.update(rarity=record.get("rarity") if record.get("rarity") in ["gold", "silver", "prismatic"] else "unknown",
                            isDeleted=record.get("isDeleted") is True, limit=names(record.get("limit")))
                for field in ["items", "specialItems", "trapItems"]:
                    item[field] = links(record.get(field))
            if kind == "items":
                item.update(types=names(record.get("types")), total=str(record.get("total", "")))
            data[kind][name] = item
    relations = raw.get("relations", {})
    if not isinstance(relations, dict):
        raise ValueError("relations must be a JSON object")
    for name, relation in relations.items():
        if isinstance(relation, dict):
            data["relations"][name] = {field: links(relation.get(field)) for field in ["specialAugments", "trapAugments"]}
    def combination(record):
        return {"name": str(record.get("name", "未命名方案")), "description": plain(record.get("description")),
                "tips": plain(record.get("tips")), "last_update": str(record.get("last_update", "")),
                "heros": names(record.get("heros")), "augments": links(record.get("augments")), "items": links(record.get("items"))}
    groups = raw.get("combinations", [])
    if not isinstance(groups, list):
        raise ValueError("combinations must be a JSON array")
    for group in groups:
        if isinstance(group, dict):
            adapted = combination(group)
            adapted["combinations"] = [combination(branch) for branch in group.get("combinations", []) if isinstance(branch, dict)]
            data["combinations"].append(adapted)
    # Official champion-specific statistics are adapted by the verified source updater.
    # Do not derive pair rates from the global augment catalog.
    official=raw.get('heroAugmentStats',{})
    if isinstance(official,dict):
        for hero,rows in official.items():
            if not isinstance(hero,str) or not isinstance(rows,list):continue
            data['heroAugmentStats'][hero]=[]
            for row in rows:
                if not isinstance(row,dict):continue
                name=row.get('augmentName') or row.get('name')
                if not isinstance(name,str):continue
                data['heroAugmentStats'][hero].append({
                    'augmentName':name,'augmentId':str(row.get('augmentId','')),
                    'rarity':str(row.get('rarity','')),'tier':str(row.get('tier','')),
                    'winRate':number(row.get('winRate')),'pickRate':number(row.get('pickRate')),
                    'numGames':number(row.get('numGames')),
                    'rateUnit':str(row.get('rateUnit','unknown')),
                    'sourceUrl':str(row.get('sourceUrl',''))})
    return data


def load_data(path):
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("Dataset must be a JSON object")
    return normalize(raw)


def recommend(data, augment_name):
    """Keep all candidates; browser applies zh-CN collation and the top-8 cut.

    Duplicate evidence contributes the maximum score, never a sum. Traps stay
    separate and also mark an otherwise recommended item as a conflict.
    """
    augment = data["augments"].get(augment_name)
    if augment is None:
        raise KeyError(augment_name)
    recommended, warnings = {}, {}
    missing = set()
    def add(target, link, score, source, warning=False):
        name = link["name"]
        if name not in data["items"]:
            missing.add(name)
            return
        entry = target.setdefault(name, {"name": name, "score": score, "core": False, "warning": False, "evidence": []})
        entry["score"] = max(entry["score"], score)
        entry["core"] |= link.get("core", False)
        entry["warning"] |= warning
        evidence = {"score": score, "source": source, "reason": link.get("reason", "")}
        if evidence not in entry["evidence"]:
            entry["evidence"].append(evidence)
    for link in augment["items"]:
        add(recommended, link, 100, "海克斯直接装备列表")
    for link in augment["specialItems"]:
        add(recommended, link, 94, "海克斯特殊联动")
    for link in augment["trapItems"]:
        add(warnings, link, 100, "海克斯陷阱装备", True)
    for group in data["combinations"]:
        parent_match = any(link["name"] == augment_name for link in group["augments"])
        branches = group["combinations"]
        for branch in branches:
            branch_match = any(link["name"] == augment_name for link in branch["augments"])
            if not (parent_match or branch_match):
                continue
            for link in branch["items"]:
                score = (34 if link["core"] else 18) + (10 if branch_match else 0) + (5 if parent_match else 0)
                label = group["name"] if branch is group else group["name"] + " / " + branch["name"]
                add(recommended, link, score, "组合方案：" + label)
    for name in warnings.keys() & recommended.keys():
        recommended[name]["warning"] = True
    return {"augment": augment_name, "recommendations": sorted(recommended.values(), key=lambda x: (-x["score"], x["name"])),
            "warnings": sorted(warnings.values(), key=lambda x: x["name"]), "missingItems": sorted(missing),
            "pairWinRate": None, "scoreMeaning": "公开资料关联规则分，不是胜率；与所选英雄无关。"}

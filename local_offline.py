"""Fully local offline cards for the bundled 26.21 dataset.

The local tier is a documented heat tier: current arammayhem pick-rate rank
percentile plus hero-specific combo hints (god/trap). It is not a Huya remote
AI score, win rate or strength rating, and it never uses a win rate.
"""
from __future__ import annotations

import json
from pathlib import Path

from arammayhem_stats import AramMayhemError, _strict_json, canonical_name, lookup_augment, lookup_champion
from engine import plain

TIERS = ('S', 'A', 'B', 'C')
SCHEMA_VERSION = 1


def load_bundle(path):
    """Load a validated local bundle and mark its dataset as offline-local."""
    raw = _strict_json(Path(path).read_bytes())
    if not isinstance(raw, dict) or raw.get('schemaVersion') != SCHEMA_VERSION:
        raise ValueError('Unsupported offline data bundle')
    data, aram = raw.get('data'), raw.get('aram')
    if not isinstance(data, dict) or not isinstance(aram, dict):
        raise ValueError('Offline bundle is missing data or aram payload')
    for key in ('heroes', 'augments', 'heroAugmentStats'):
        if not isinstance(data.get(key), dict):
            raise ValueError('Offline bundle is missing ' + key)
    for key in ('augments', 'champions', 'combos', 'items'):
        if not isinstance(aram.get(key), list):
            raise ValueError('Offline bundle is missing aram ' + key)
    metadata = data.setdefault('metadata', {})
    if not isinstance(metadata, dict):
        raise ValueError('Offline bundle has invalid metadata')
    metadata['offlineLocal'] = True
    metadata['offlineBundle'] = str(Path(path).resolve())
    data['aram'] = aram
    return data


def _tier(rank, total):
    if not isinstance(rank, int) or isinstance(rank, bool) or rank < 1 or total < 1:
        return None
    position = (rank - 1) / max(1, total - 1)
    return 'S' if position <= .10 else 'A' if position <= .30 else 'B' if position <= .60 else 'C'


def _move(tier, steps):
    try:
        index = TIERS.index(tier)
    except ValueError:
        return tier
    return TIERS[max(0, min(len(TIERS) - 1, index + steps))]


def _hero_keys(data, hero):
    record = data.get('heroes', {}).get(hero)
    values = [hero]
    if isinstance(record, dict):
        values += [value for value in record.get('alias', []) if isinstance(value, str)]
    return {canonical_name(value) for value in values if isinstance(value, str) and value.strip()}


def _combos_for(aram, hero_keys, augment_name):
    key = canonical_name(augment_name)
    matches = []
    for combo in aram.get('combos', []):
        if not isinstance(combo, dict):
            continue
        if canonical_name(combo.get('champion', '')) not in hero_keys:
            continue
        names = combo.get('augmentNames')
        if not isinstance(names, list):
            continue
        if key in {canonical_name(name) for name in names if isinstance(name, str)}:
            matches.append(combo)
    return matches


def _combo_hint(combos, augment_name):
    if not combos:
        return '', []
    types = {value for combo in combos for value in combo.get('types', [])
             if isinstance(value, str)}
    labels = []
    if 'trap' in types:
        labels.append('英雄组合：陷阱')
    if 'god' in types:
        labels.append('英雄组合：高协同')
    if not labels:
        labels.append('英雄专属组合')
    partners = []
    key = canonical_name(augment_name)
    for combo in combos:
        for name in combo.get('augmentNames', []):
            if isinstance(name, str) and canonical_name(name) != key and name not in partners:
                partners.append(name)
    if partners:
        labels.append('搭配：' + '、'.join(partners[:2]))
    notes = ['本地英雄组合将该强化标记为陷阱，请结合机制判断。'] if 'trap' in types else []
    return ' · '.join(labels), notes


def local_cards(data, hero, offered):
    """Return three fixed-slot cards; missing/ambiguous local rows abstain."""
    aram = data.get('aram') if isinstance(data, dict) else None
    if not isinstance(aram, dict) or not isinstance(offered, (list, tuple)):
        return []
    hero_keys = _hero_keys(data, hero)
    rows = [row for row in aram.get('augments', [])
            if isinstance(row, dict) and not row.get('retiredPatch')
            and isinstance(row.get('pickRateRank'), int) and not isinstance(row.get('pickRateRank'), bool)]
    total = len(rows)
    meta = aram.get('metadata') if isinstance(aram.get('metadata'), dict) else {}
    cards = []
    for slot, name in enumerate(offered, 1):
        item = data.get('augments', {}).get(name) if isinstance(name, str) else None
        description = plain(item.get('description')) if isinstance(item, dict) and isinstance(item.get('description'), str) else '描述未提供'
        augment = lookup_augment(aram, name) if isinstance(name, str) else None
        if augment is None:
            cards.append({'name': name, 'slot': slot, 'description': description,
                          'sourceTier': None, 'sourceTierLabel': '本地未收录',
                          'sourceLabel': '本地离线数据未收录该强化；不代表强度',
                          'ratingStatus': 'local-unmatched', 'catalogStatus': 'local',
                          'notes': [], 'sourceHint': '', 'heatLabel': '',
                          'sourceBadge': '本地', 'offlineLocal': True,
                          'sourceDataDate': meta.get('statsDate'), 'gamePatch': meta.get('patch'),
                          'targetGamePatch': meta.get('patch')})
            continue
        tier = _tier(augment.get('pickRateRank'), total)
        combos = _combos_for(aram, hero_keys, name)
        combos_types = {value for combo in combos for value in combo.get('types', []) if isinstance(value, str)}
        if 'trap' in combos_types:
            tier = _move(tier, 1)
        elif 'god' in combos_types:
            tier = _move(tier, -1)
        hint, notes = _combo_hint(combos, name)
        pick_rate = augment.get('pickRate')
        cards.append({
            'name': name, 'slot': slot, 'description': description,
            'sourceTier': tier, 'sourceTierLabel': '本地热度档位',
            'sourceLabel': '本地 26.21 热度 · aram mayhem CC BY 4.0 · 非虎牙 AI 强度',
            'ratingStatus': 'local-heat', 'catalogStatus': 'local',
            'notes': notes, 'sourceHint': hint,
            'heatLabel': (f"热度 {pick_rate:.2f}% · 全强化第 {augment.get('pickRateRank')}"
                          if isinstance(pick_rate, (int, float)) else ''),
            'pickRate': pick_rate, 'heatRank': augment.get('pickRateRank'),
            'sourceBadge': '本地', 'offlineLocal': True,
            'sourceDataDate': meta.get('statsDate'), 'gamePatch': meta.get('patch'),
            'targetGamePatch': meta.get('patch'),
        })
    return cards


def heat_view(data):
    """Return an arammayhem-shaped cache from the offline bundle for UI lookups."""
    aram = data.get('aram') if isinstance(data, dict) else None
    return aram if isinstance(aram, dict) and isinstance(aram.get('augments'), list) else None

"""Hero-level reference rows from the verified public source.

Source order only: never sort by tier, pick rate or sample size. Ratings,
pick rates, sample counts and equipment rates never enter these projections.
Applicability follows the same patch/date gate as augment ratings.
"""
from __future__ import annotations

from patch_catalog import (active_augment, pair_rating_available,
                           ratings_available, statistics_status)
from native_state import source_tier
from source_combo_hints import source_combo_hint

DEFAULT_ROW_LIMIT = 8
DEFAULT_BUILD_LIMIT = 6


def _limit(value, fallback):
    if isinstance(value, bool) or not isinstance(value, int):
        return fallback
    return max(1, min(value, 20))


def _hero(data, hero):
    if not isinstance(data, dict) or not isinstance(hero, str):
        return None
    heroes = data.get('heroes')
    if not isinstance(heroes, dict):
        return None
    record = heroes.get(hero)
    return record if isinstance(record, dict) else None


def _unavailable(reason, status=None):
    status = status if isinstance(status, dict) else {}
    return {'available': False, 'rows': [], 'reason': reason,
            'status': status.get('ratingStatus', 'unverified'),
            'sourceDataDate': status.get('statisticsDate'),
            'gamePatch': status.get('statisticsPatch')}


def recommendation_rows(data, hero, limit=DEFAULT_ROW_LIMIT):
    """Hero-specific source rows, preserving source order and known identity."""
    limit = _limit(limit, DEFAULT_ROW_LIMIT)
    if _hero(data, hero) is None:
        return _unavailable('请选择并确认英雄')
    if isinstance(data.get('metadata'), dict) and data['metadata'].get('offlineLocal') is True:
        meta = data['metadata']
        return {'available': False, 'rows': [],
                'reason': '本地离线模式：请查看三个候选的本地热度档位；此处不展示旧版统计。',
                'status': 'offline-local', 'sourceDataDate': meta.get('sourceDataDate'),
                'gamePatch': meta.get('gamePatch')}
    status = statistics_status(data, hero)
    if not ratings_available(data, hero):
        return _unavailable(status['ratingMessage'], status)
    rows, seen = [], set()
    for row in data.get('heroAugmentStats', {}).get(hero, []):
        if not isinstance(row, dict):
            continue
        name = row.get('augmentName')
        if not isinstance(name, str) or name in seen:
            continue
        item = active_augment(data, name)
        if item is None or not pair_rating_available(data, hero, name, row):
            continue
        hint = source_combo_hint(data, hero, name)
        rows.append({'name': name, 'tier': source_tier(row.get('tier')) or '',
                     'hint': hint['text'] if hint else ''})
        seen.add(name)
        if len(rows) >= limit:
            break
    if not rows:
        return _unavailable('公开源没有可用的英雄专属海克斯顺序', status)
    return {'available': True, 'rows': rows, 'reason': '',
            'status': status['ratingStatus'],
            'sourceDataDate': status['statisticsDate'],
            'gamePatch': status['statisticsPatch']}


def _project_builds(builds, limit):
    if not isinstance(builds, list) or not builds:
        return []
    result = []
    for build in builds[:limit]:
        if not isinstance(build, dict):
            continue
        style = build.get('style') if isinstance(build.get('style'), str) else ''
        core = []
        for row in build.get('coreItems', []) if isinstance(build.get('coreItems'), list) else []:
            if not isinstance(row, list):
                continue
            names = [name for name in row[:8] if isinstance(name, str) and name]
            if names:
                core.append(names)
        starting = []
        for group in build.get('startingItems', []) if isinstance(build.get('startingItems'), list) else []:
            if not isinstance(group, list):
                continue
            names = [name for name in group[:8] if isinstance(name, str) and name]
            if names:
                starting.append(names)
        if core or starting:
            result.append({'style': style[:40], 'coreItems': core, 'startingItems': starting})
    return result


def equipment_reference(data, hero, limit=DEFAULT_BUILD_LIMIT):
    """Public item names only; the source's rates/sample counts are discarded."""
    limit = _limit(limit, DEFAULT_BUILD_LIMIT)
    record = _hero(data, hero)
    if record is None:
        return _unavailable('请选择并确认英雄')
    if isinstance(data.get('metadata'), dict) and data['metadata'].get('offlineLocal') is True:
        result = _project_builds(record.get('equipmentBuilds'), limit)
        if not result:
            return _unavailable('本地离线包未提供该英雄的出装资料')
        meta = data['metadata']
        return {'available': True, 'builds': result, 'reason': '',
                'status': 'offline-local',
                'sourceDataDate': meta.get('sourceDataDate'),
                'gamePatch': meta.get('gamePatch'),
                'note': '本地离线快照（16.17 / 2026-09-07）；仅装备名称，可能已过期。'}
    status = statistics_status(data, hero)
    if not ratings_available(data, hero):
        return _unavailable(status['ratingMessage'], status)
    result = _project_builds(record.get('equipmentBuilds'), limit)
    if not result:
        return _unavailable('公开源未提供该英雄的出装资料', status)
    return {'available': True, 'builds': result, 'reason': '',
            'status': status['ratingStatus'],
            'sourceDataDate': status['statisticsDate'],
            'gamePatch': status['statisticsPatch']}

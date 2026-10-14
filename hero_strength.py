"""Literal champion-level source ratings, independent of augment ratings.

This module only reads the already loaded dataset. It performs no recognition,
network requests, ranking, rate conversion, or inference from augment records.
The caller remains responsible for current selection and capture permission.
"""
from __future__ import annotations

from datetime import date
import re

from data_updates import WIKI_PAGE


# The reviewed champion-level public table uses T1 through T5. Augment-level
# ratings have their own, intentionally narrower vocabulary in native_state.
HERO_SOURCE_TIERS = frozenset({'T1', 'T2', 'T3', 'T4', 'T5'})


def hero_source_tier(value):
    """Accept only a literal known champion tier; never convert another scale."""
    return value.strip() if isinstance(value, str) and value.strip() in HERO_SOURCE_TIERS else None


def _token(value, pattern):
    return value if isinstance(value, str) and re.fullmatch(pattern, value) else None


def _source_date(value):
    if not _token(value, r'\d{4}-\d{2}-\d{2}'):
        return None
    try:
        date.fromisoformat(value)
    except ValueError:
        return None
    return value


def hero_strength_reference(data, hero, *, champion_id=None):
    """Return an exact known hero's small, presentation-ready reference record.

    Unknown heroes and an optional canonical-ID mismatch return None. A known
    hero with missing/unrecognized tier returns sourceTier=None. Only explicit
    fictional demo data or the existing canonical public-source provenance may
    expose a tier. Missing provenance never leaks the raw tier as a fallback.

    Metadata stays absent when it is absent or malformed; fetchedAt is never a
    substitute for a source date. Returned values are independent primitives.
    """
    if not isinstance(data, dict) or not isinstance(hero, str) or not hero:
        return None
    heroes = data.get('heroes')
    if not isinstance(heroes, dict) or not isinstance(heroes.get(hero), dict):
        return None
    record = heroes[hero]
    canonical_id = _token(record.get('championId'), r'[0-9]{1,10}')
    if champion_id is not None and (
            not _token(champion_id, r'[0-9]{1,10}') or champion_id != canonical_id):
        return None
    metadata = data.get('metadata')
    metadata = metadata if isinstance(metadata, dict) else {}
    is_demo = metadata.get('isDemo') is True
    is_public = (not is_demo and metadata.get('officialHeroStatistics') is True
                 and metadata.get('sourceUrl') == WIKI_PAGE)
    tier = hero_source_tier(record.get('overallTier')) if is_demo or is_public else None
    source_version = _token(metadata.get('wikiDataVersion'), r'[A-Za-z0-9_.-]{1,64}')
    if source_version in ('.', '..'):
        source_version = None
    return {
        'hero': hero,
        'championId': canonical_id,
        'sourceTier': tier,
        'sourceTierLabel': ('虚构英雄评级（演示）' if is_demo else
                            '虎牙公开源英雄评级' if is_public else '英雄评级 · 来源待核对'),
        'sourceLabel': ('虚构演示 · 不能用于对局' if is_demo else
                        '虎牙公开源资料快照 · 非实时评级 · 非 Riot 评级/批准' if is_public else
                        '来源待核对'),
        'sourceUrl': WIKI_PAGE if is_public else None,
        'sourceDataDate': _source_date(metadata.get('sourceDataDate')),
        'wikiDataVersion': source_version,
        'gamePatch': _token(metadata.get('gamePatch'), r'[0-9]{1,3}\.[0-9]{1,3}(?:\.[0-9]{1,3})?'),
        'sourceVersion': _token(record.get('sourceVersion'), r'[0-9]{1,3}\.[0-9]{1,3}(?:\.[0-9]{1,3})?'),
        'isDemo': is_demo,
    }

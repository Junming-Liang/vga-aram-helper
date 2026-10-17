"""Short source-template hints, never a next-pick model or inferred ranking."""
from __future__ import annotations
import re

_ID = re.compile(r'[0-9]{1,12}\Z')


def _id(value):
    return value if isinstance(value, str) and _ID.fullmatch(value) else None


def normalize_source_combos(raw):
    """Keep only stable IDs. Re-normalization preserves this narrow projection."""
    result = {}
    wiki = raw.get('wiki')
    if isinstance(wiki, dict):
        details = wiki.get('championDetail')
        if not isinstance(details, list):
            return {}
        source = [(row.get('championId'), row.get('topAugmentCombos'))
                  for row in details if isinstance(row, dict)]
    else:
        projection = raw.get('heroSourceCombos', {})
        source = list(projection.items()) if isinstance(projection, dict) else []
    seen = set()
    for hero_id, rows in source:
        if not _id(hero_id):
            continue
        if hero_id in seen:
            result.pop(hero_id, None)
            continue
        seen.add(hero_id)
        if not isinstance(rows, list) or len(rows) > 100:
            continue
        valid = []
        for row in rows:
            ids = row.get('augments') if isinstance(row, dict) else row
            if (not isinstance(ids, list) or not 2 <= len(ids) <= 5
                    or any(not _id(x) for x in ids) or len(set(ids)) != len(ids)):
                continue
            if ids not in valid:
                valid.append(list(ids))
        if valid:
            result[hero_id] = valid
    return result


def source_combo_hint(data, hero, augment):
    """Return one short matching source example, or no hint if unverifiable.

    Original source order selects an example only, never an inferred score.
    No selected-augment history is accepted or assumed. No equipment inference.
    """
    meta = data.get('metadata', {})
    if meta.get('isDemo') or meta.get('officialHeroStatistics') is not True:
        return None
    heroes, augments = data.get('heroes', {}), data.get('augments', {})
    h, a = heroes.get(hero), augments.get(augment)
    if not isinstance(h, dict) or not isinstance(a, dict):
        return None
    hid, aid = _id(h.get('championId')), _id(a.get('augmentId'))
    if not hid or not aid or a.get('isDeleted') is True:
        return None
    if sum(isinstance(x, dict) and x.get('championId') == hid for x in heroes.values()) != 1:
        return None
    names, ambiguous = {}, set()
    for name, row in augments.items():
        if not isinstance(row, dict):
            continue
        key = _id(row.get('augmentId'))
        if not key:
            continue
        if key in names:
            ambiguous.add(key)
        names[key] = name
    rows = normalize_source_combos({'heroSourceCombos': data.get('heroSourceCombos', {})}).get(hid, [])
    for ids in rows:
        if aid not in ids or any(x in ambiguous or x not in names for x in ids):
            continue
        partners = [names[x] for x in ids if x != aid]
        if any(not isinstance(x, str) or not 1 <= len(x) <= 24 or
               any(ord(c) < 32 or c in '<>\u2028\u2029' for c in x) or
               augments[x].get('isDeleted') is True for x in partners):
            continue
        # Do not truncate names into misleading partial labels.
        text = '搭配：' + '、'.join(partners)
        if len(text) > 48:
            continue
        return {'text': text, 'kind': 'hero-source-combo-example',
                'sourceLabel': '虎牙公开组合示例，非后续选择顺序',
                'sourceDate': meta.get('sourceDataDate'),
                'sourceVersion': meta.get('wikiDataVersion'),
                'championId': hid, 'augmentId': aid, 'partnerIds': [x for x in ids if x != aid]}
    return None

"""Build local League recommended-item-set JSON from the offline bundle.

No game directory is modified automatically. The caller chooses an export
directory; only files with the local prefix are replaced there.
"""
from __future__ import annotations

import json
from pathlib import Path

from arammayhem_stats import canonical_name, lookup_champion
from update_network import atomic_write

FILE_PREFIX = '!!!vga-aram-'
BASE_SORTRANK = 999999999
MAX_BUILDS = 6
MAX_ITEMS = 12


def item_index(data):
    """Localized item name -> numeric game item ID from the bundled item list."""
    rows = data.get('aram', {}).get('items') if isinstance(data, dict) else None
    index, canonical = {}, {}
    if not isinstance(rows, list):
        return index, canonical
    for row in rows:
        if not isinstance(row, dict):
            continue
        name, game_id = row.get('name'), row.get('gameItemId')
        if not isinstance(name, str) or not name.strip():
            continue
        if not isinstance(game_id, str) or not game_id.isdigit():
            continue
        value = int(game_id)
        index.setdefault(name.strip(), []).append(value)
        canonical.setdefault(canonical_name(name), []).append(value)
    return ({name: values[0] for name, values in index.items() if len(set(values)) == 1},
            {name: values[0] for name, values in canonical.items() if len(set(values)) == 1})


def _resolve(names, exact, canonical):
    result = []
    for name in names[:MAX_ITEMS] if isinstance(names, list) else []:
        if not isinstance(name, str) or not name.strip():
            continue
        value = exact.get(name.strip())
        if value is None:
            value = canonical.get(canonical_name(name))
        if value is not None and value not in result:
            result.append(value)
    return result


def build_sets(data, hero, limit=MAX_BUILDS):
    record = data.get('heroes', {}).get(hero) if isinstance(data.get('heroes'), dict) else None
    aram = data.get('aram') if isinstance(data, dict) else None
    if not isinstance(record, dict) or not isinstance(aram, dict):
        raise ValueError('没有可用的离线英雄与物品资料')
    champion = lookup_champion(aram, hero, record.get('alias', []))
    if not champion or not isinstance(champion.get('championId'), str):
        raise ValueError('未能匹配该英雄的游戏键')
    exact, canonical = item_index(data)
    if not exact:
        raise ValueError('离线包没有可用的装备 ID')
    sets = []
    for index, build in enumerate(record.get('equipmentBuilds', [])[:limit]):
        if not isinstance(build, dict):
            continue
        core = build.get('coreItems')
        names = core[0] if isinstance(core, list) and core and isinstance(core[0], list) else []
        items = _resolve(names, exact, canonical)
        if not items:
            continue
        title = build.get('style') if isinstance(build.get('style'), str) and build.get('style') else '推荐出装'
        config = {
            'title': title[:40], 'championKey': champion['championId'],
            'map': 'any', 'mode': 'any', 'type': 'custom',
            'priority': index == 0, 'sortrank': BASE_SORTRANK - index,
            'blocks': [{'recMath': False, 'minSummonerLevel': -1, 'maxSummonerLevel': -1,
                        'showIfSummonerSpell': '', 'hideIfSummonerSpell': '',
                        'type': '核心出装', 'items': items}],
        }
        sets.append((f'{FILE_PREFIX}{index}.json', config))
    if not sets:
        raise ValueError('没有可解析的装备名称')
    return sets


def export(data, hero, directory):
    folder = Path(directory)
    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    for filename, config in build_sets(data, hero):
        path = folder / filename
        atomic_write(path, json.dumps(config, ensure_ascii=False, allow_nan=False,
                                      separators=(',', ':')).encode('utf-8'))
        paths.append(path)
    for stale in folder.glob(FILE_PREFIX + '*.json'):
        if stale.name not in {path.name for path in paths}:
            try:
                stale.unlink()
            except OSError:
                pass
    return paths

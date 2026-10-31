#!/usr/bin/env python3
"""Build a self-contained, offline 26.21 dataset from local public snapshots.

Inputs are local JSON files; this tool performs no network access.
- Huya wiki snapshot: names, descriptions, hero-specific historical stats and
  equipment builds. Its old tiers are not used for the local heat rating.
- arammayhem 26.21: CC BY 4.0 pick rates/ranks, hero combos and item costs.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from arammayhem_stats import (ATTRIBUTION, LICENSE_NAME, LICENSE_URL, SOURCE_PAGE,
                              normalize_combos, normalize_items, normalize_payload)
from engine import normalize
from update_network import atomic_write


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def main():
    parser = argparse.ArgumentParser(description='生成不联网的本地离线数据包')
    parser.add_argument('--huya-dir', type=Path, required=True)
    parser.add_argument('--arammayhem-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--huya-version', default='395')
    args = parser.parse_args()

    wiki = {
        'version': args.huya_version,
        'championDetail': read(args.huya_dir / 'champion-detail.json'),
        'augmentDetail': read(args.huya_dir / 'augment-detail.json'),
        'itemDetail': read(args.huya_dir / 'item-detail.json'),
    }
    data = normalize({'wiki': wiki})
    aram_augments = read(args.arammayhem_dir / 'augments.json')
    aram_champions = read(args.arammayhem_dir / 'champions.json')
    aram_cache = normalize_payload(aram_augments, aram_champions,
                                   fetched_at=datetime.now(timezone.utc).isoformat())
    aram = {
        'metadata': aram_cache['metadata'],
        'augments': aram_cache['augments'],
        'champions': aram_cache['champions'],
        'combos': normalize_combos(read(args.arammayhem_dir / 'combos.json')),
        'items': normalize_items(read(args.arammayhem_dir / 'items.json')),
    }
    metadata = data.setdefault('metadata', {})
    metadata['offlineLocal'] = True
    metadata['offlinePatch'] = aram['metadata']['patch']
    metadata['offlineStatsDate'] = aram['metadata']['statsDate']
    bundle = {
        'schemaVersion': 1,
        'metadata': {
            'offlineLocal': True,
            'patch': aram['metadata']['patch'],
            'statsDate': aram['metadata']['statsDate'],
            'createdAt': datetime.now(timezone.utc).isoformat(),
            'ratingModel': 'local heat tier: arammayhem pick-rate rank percentile + god/trap hero combos',
            'sources': [
                {'name': 'arammayhem.com', 'url': SOURCE_PAGE, 'license': LICENSE_NAME,
                 'licenseUrl': LICENSE_URL, 'attribution': ATTRIBUTION,
                 'files': ['augments', 'champions', 'combos', 'items'],
                 'note': 'pick rates/ranks only; no win rates, tiers or win-rate rankings'},
                {'name': 'Huya public wiki snapshot', 'version': str(wiki['version']),
                 'gamePatch': metadata.get('gamePatch'),
                 'sourceDataDate': metadata.get('sourceDataDate'),
                 'note': 'names, descriptions, historical hero stats and equipment builds; old tiers are not used for local ratings'},
            ],
        },
        'data': data,
        'aram': aram,
    }
    payload = json.dumps(bundle, ensure_ascii=False, allow_nan=False,
                         separators=(',', ':')).encode('utf-8')
    atomic_write(args.output, payload)
    print(json.dumps({
        'output': str(args.output), 'bytes': len(payload),
        'patch': bundle['metadata']['patch'], 'statsDate': bundle['metadata']['statsDate'],
        'heroes': len(data.get('heroes', {})), 'augments': len(data.get('augments', {})),
        'aramAugments': len(aram['augments']), 'aramChampions': len(aram['champions']),
        'combos': len(aram['combos']), 'items': len(aram['items']),
    }, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()

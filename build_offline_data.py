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
import tempfile

from arammayhem_stats import (ATTRIBUTION, LICENSE_NAME, LICENSE_URL, SOURCE_PAGE,
                              fetch_current_docs, normalize_combos, normalize_items,
                              normalize_payload)
from engine import normalize
from update_network import atomic_write


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def load_sources(args):
    if args.fetch:
        from data_updates import refresh_official_data
        with tempfile.TemporaryDirectory(prefix='vga-offline-') as cache:
            result = refresh_official_data(Path(cache))
        raw = result.get('data') if isinstance(result, dict) else None
        wiki = raw.get('wiki') if isinstance(raw, dict) else None
        if not isinstance(wiki, dict):
            raise SystemExit('无法从官方 wiki 取得原始快照')
        docs = fetch_current_docs()
        return wiki, docs
    wiki = {
        'version': args.huya_version,
        'championDetail': read(args.huya_dir / 'champion-detail.json'),
        'augmentDetail': read(args.huya_dir / 'augment-detail.json'),
        'itemDetail': read(args.huya_dir / 'item-detail.json'),
    }
    docs = {
        'index': None,
        'augments': read(args.arammayhem_dir / 'augments.json'),
        'champions': read(args.arammayhem_dir / 'champions.json'),
        'combos': read(args.arammayhem_dir / 'combos.json'),
        'items': read(args.arammayhem_dir / 'items.json'),
    }
    return wiki, docs


def main():
    parser = argparse.ArgumentParser(description='生成不联网的本地离线数据包')
    parser.add_argument('--fetch', action='store_true',
                        help='构建时从公开源抓取（仅 CI 构建用；运行时仍完全离线）')
    parser.add_argument('--huya-dir', type=Path)
    parser.add_argument('--arammayhem-dir', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--huya-version', default='395')
    args = parser.parse_args()
    if not args.fetch and (args.huya_dir is None or args.arammayhem_dir is None):
        parser.error('未使用 --fetch 时必须提供 --huya-dir 与 --arammayhem-dir')

    wiki, docs = load_sources(args)
    data = normalize({'wiki': wiki})
    aram_cache = normalize_payload(docs['augments'], docs['champions'],
                                   index_doc=docs.get('index'),
                                   fetched_at=datetime.now(timezone.utc).isoformat())
    aram = {
        'metadata': aram_cache['metadata'],
        'augments': aram_cache['augments'],
        'champions': aram_cache['champions'],
        'combos': normalize_combos(docs['combos']),
        'items': normalize_items(docs['items']),
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

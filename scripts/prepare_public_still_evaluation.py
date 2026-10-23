"""Reacquire the already reviewed public samples in a caller-owned scratch folder.

Images are hash checked and never included in reports or release assets.
"""
import concurrent.futures
import hashlib
import json
from pathlib import Path
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
cache = Path(sys.argv[1]).resolve()
cache.mkdir(parents=True, exist_ok=True)


def acquire(url, path, checksum=None):
    if not url.startswith('https://'):
        raise ValueError('HTTPS public source required')
    if not path.exists():
        request = urllib.request.Request(url, headers={'User-Agent': 'VGA-public-still-evaluation'})
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = response.read(20_000_001)
        if len(payload) > 20_000_000:
            raise ValueError('Public fixture too large')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    payload = path.read_bytes()
    if checksum and hashlib.sha256(payload).hexdigest() != checksum:
        raise ValueError('Original public fixture changed: ' + url)


hero = json.loads((ROOT/'reports/hero-recognition-genuine.json').read_text())
client = json.loads((ROOT/'reports/champion-select-genuine.json').read_text())
version = hero['templates']['version']
for locale in ('en_US', 'zh_CN'):
    acquire(f'https://ddragon.leagueoflegends.com/cdn/{version}/data/{locale}/champion.json',
            cache/f'champion.{locale}.json',
            hero['templates']['roster_sha256'] if locale == 'en_US' else None)
roster = json.loads((cache/'champion.en_US.json').read_text())


def portrait(row):
    name = row['image']['full']
    acquire(f'https://ddragon.leagueoflegends.com/cdn/{version}/img/champion/{name}', cache/'square'/name)


with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
    list(pool.map(portrait, roster['data'].values()))
heroes = []
clients = []
for index, row in enumerate(hero['cases']):
    path = cache/f'hero-{index}.png'
    acquire(row['source_url'], path, row['image_sha256'])
    heroes.append(dict(path=str(path), image_url=row['source_url'], source_page=row['source_page'],
        canonical_champion_id=row['gold_hero_id'], visible_champion=row.get('gold_hero'),
        gold_confidence=row.get('gold_confidence'), context=row['condition'],
        test_role='negative' if row['expected_outcome']=='abstain' else 'positive'))
for index, row in enumerate(client['cases']):
    path = cache/f'client-{index}.png'
    acquire(row['source_url'], path, row['image_sha256'])
    clients.append(dict(path=str(path), image_url=row['source_url'], source_page=row['source_page'],
        sha256=row['image_sha256'], champion_id=row['gold_hero_id'],
        expected='abstain' if row['expected_outcome']=='abstain' else 'recognize',
        context=row['condition'], limitation=row.get('limitations')))
(cache/'hero.json').write_text(json.dumps(heroes))
(cache/'client.json').write_text(json.dumps({'items': clients}))
zh = json.loads((cache/'champion.zh_CN.json').read_text())
# Only vocabulary is needed for this single-frame OCR check; no tier data is invented.
vocabulary = {'heroes': {r['name']: {'championId': r['key']} for r in zh['data'].values()},
              'augments': {r['name']: {} for r in hero['genuine_selection_frame']['automatic_titles']}}
(cache/'vocabulary.json').write_text(json.dumps(vocabulary, ensure_ascii=False))
print('Original public samples and official portraits ready; no images redistributed')

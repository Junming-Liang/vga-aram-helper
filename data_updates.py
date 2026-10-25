"""Discover official Huya JSON each launch, validate, then commit one coherent cache.

Remote JavaScript is only searched for literal asset URLs; it is never executed.
No bundled/demo data is substituted for missing official data.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
from pathlib import Path
import re
import threading
import time
from urllib.parse import urljoin, urlsplit
from urllib.error import HTTPError, URLError

from update_network import (HUYA_HOSTS, UpdateError, atomic_write, fetch_bytes, json_bytes,
                            runtime_state_dir, strict_json, validate_url)

OFFICIAL_PAGE = 'https://gametool.huya.com/lolhex'
MAX_PAGE_BYTES = 2 * 1024 * 1024
MAX_SCRIPT_BYTES = 8 * 1024 * 1024
MAX_JSON_BYTES = 16 * 1024 * 1024
MAX_CACHE_BYTES = 48 * 1024 * 1024
SOURCE_NAMES = ('heroIndex', 'augments', 'items', 'relations', 'combinations', 'changelogs',
                'equipment-categories')
APP_KEYS = {'heroIndex': 'heroes', 'equipment-categories': 'equipmentCategories'}
_LOCK = threading.RLock()


def _now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


class _Scripts(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []

    def handle_starttag(self, tag, attrs):
        if tag == 'script':
            source = dict(attrs).get('src')
            if source:
                self.urls.append(source)


def discover_sources(html: str, bundles: list[tuple[str, str]]) -> list[dict]:
    """Find complete, same-bundle sets; never combine assets from different builds."""
    sources = []
    for bundle_url, text in bundles:
        validate_url(bundle_url, HUYA_HOSTS)
        digest = hashlib.sha256(text.encode()).hexdigest()
        # These exact literal roots are the site's own prioritized data branches.
        roots = list(dict.fromkeys(re.findall(r'[\"\'](/data/[A-Za-z0-9_.-]{1,64}/converted)[\"\']', text)))
        for root in roots[:3]:
            sources.append({'version': root.split('/')[2], 'mode': 'versioned', 'bundleUrl': bundle_url,
                            'bundleSha256': digest,
                            'urls': {name: urljoin(OFFICIAL_PAGE, root + '/' + name + '.json') for name in SOURCE_NAMES}})
        found = {}
        for literal in re.findall(r'[\"\']([^\"\'\s<>]{1,2048}\.json)[\"\']', text):
            url = urljoin(bundle_url, literal)
            basename = urlsplit(url).path.rsplit('/', 1)[-1]
            match = re.fullmatch(r'(heroIndex|augments|items|relations|combinations|changelogs|equipment-categories)-[A-Za-z0-9_-]+\.json', basename)
            if not match:
                continue
            validate_url(url, HUYA_HOSTS)
            if not urlsplit(url).path.startswith('/gametool/league-of-legends/work/assets/'):
                continue
            found[match.group(1)] = url
        if set(found) == set(SOURCE_NAMES):
            sources.append({'version': 'assets-' + digest[:16], 'mode': 'hashed-assets',
                            'bundleUrl': bundle_url, 'bundleSha256': digest, 'urls': found})
    return sources


def _bounded_tree(value, depth=0):
    if depth > 24:
        raise UpdateError('Data nesting exceeds the safe limit')
    if isinstance(value, dict):
        if len(value) > 10000:
            raise UpdateError('Too many data fields')
        for key, child in value.items():
            if not isinstance(key, str) or len(key) > 1024:
                raise UpdateError('Invalid data field name')
            _bounded_tree(child, depth + 1)
    elif isinstance(value, list):
        if len(value) > 20000:
            raise UpdateError('Too many data entries')
        for child in value:
            _bounded_tree(child, depth + 1)
    elif isinstance(value, str) and len(value) > 128000:
        raise UpdateError('Data text exceeds the safe limit')


def validate_dataset(data: dict) -> dict:
    if not isinstance(data, dict):
        raise UpdateError('Expected a dataset object')
    _bounded_tree(data)
    if 'wiki' in data:
        validate_wiki(data['wiki'])
        return data
    for name in ('heroes', 'augments', 'items', 'relations'):
        entries = data.get(name)
        if not isinstance(entries, dict) or not entries or len(entries) > 6000:
            raise UpdateError('Missing or invalid ' + name)
        for title, record in entries.items():
            if not isinstance(title, str) or not 1 <= len(title) <= 160 or not isinstance(record, dict):
                raise UpdateError('Invalid ' + name + ' record')
            for field in ('alias', 'position', 'limit', 'types'):
                if field in record and (not isinstance(record[field], list)
                                        or any(not isinstance(x, str) for x in record[field])):
                    raise UpdateError('Invalid ' + field)
            for field in ('items', 'specialItems', 'trapItems', 'specialAugments', 'trapAugments'):
                if field in record:
                    _validate_links(record[field])
    combinations = data.get('combinations')
    if not isinstance(combinations, list) or len(combinations) > 5000:
        raise UpdateError('Invalid combinations')
    for group in combinations:
        _validate_combination(group)
    logs = data.get('changelogs')
    if not isinstance(logs, dict) or not isinstance(logs.get('data'), list):
        raise UpdateError('Invalid changelog data')
    for entry in logs['data']:
        if not isinstance(entry, dict) or not isinstance(entry.get('date'), str):
            raise UpdateError('Invalid changelog entry')
    categories = data.get('equipmentCategories')
    if not isinstance(categories, list) or any(not isinstance(x, dict) for x in categories):
        raise UpdateError('Invalid equipment categories')
    return data


def _validate_links(value):
    if not isinstance(value, list):
        raise UpdateError('Expected a list of links')
    for item in value:
        if not isinstance(item, str) and not (isinstance(item, dict) and isinstance(item.get('name'), str)):
            raise UpdateError('Invalid relation link')


def _validate_combination(group, depth=0):
    if depth > 6 or not isinstance(group, dict) or not isinstance(group.get('name'), str):
        raise UpdateError('Invalid combination')
    for field in ('items', 'augments'):
        if field in group:
            _validate_links(group[field])
    children = group.get('combinations', [])
    if not isinstance(children, list):
        raise UpdateError('Invalid nested combinations')
    for child in children:
        _validate_combination(child, depth + 1)


def _read_cache(path):
    if not path.is_file() or path.stat().st_size > MAX_CACHE_BYTES:
        raise UpdateError('No valid cached data')
    envelope = strict_json(path.read_bytes())
    if not isinstance(envelope, dict) or envelope.get('schema_version') != 1:
        raise UpdateError('Invalid cache format')
    data = validate_dataset(envelope.get('data'))
    if hashlib.sha256(json_bytes(data)).hexdigest() != envelope.get('sha256'):
        raise UpdateError('Cached data checksum mismatch')
    if not isinstance(envelope.get('status'), dict):
        raise UpdateError('Invalid cache provenance')
    return envelope


def load_cached_data(cache_dir: Path) -> dict | None:
    for filename in ('current.json', 'previous.json'):
        try:
            return _read_cache(Path(cache_dir) / filename)
        except (OSError, ValueError, TypeError, RecursionError):
            continue
    return None


def _commit(cache_dir: Path, envelope):
    cache_dir.mkdir(parents=True, exist_ok=True)
    try:
        old = _read_cache(cache_dir / 'current.json')
    except (OSError, ValueError, TypeError, RecursionError):
        old = None
    if old is not None:
        atomic_write(cache_dir / 'previous.json', json_bytes(old))
    atomic_write(cache_dir / 'current.json', json_bytes(envelope))


def refresh_official_data(cache_dir: Path, *, fetcher=None, version_fetcher=None) -> dict:
    """Return {data: raw app dictionary | None, status: source and freshness facts}.

    Called once at each startup (preferably off the UI thread). An update failure
    returns a validated last-good cache; never synthetic recommendations.
    An injectable fetcher(url, max_bytes=...) supports deterministic offline tests.
    """
    with _LOCK:
        return _refresh_wiki(Path(cache_dir), fetcher, version_fetcher)


def _refresh(cache_dir, fetcher):
    checked = _now()
    deadline = time.monotonic() + 40
    if fetcher is None:
        def fetcher(url, *, max_bytes):
            return fetch_bytes(url, max_bytes=max_bytes, deadline=deadline)
    def fetch(url, limit):
        validate_url(url, HUYA_HOSTS)
        payload = fetcher(url, max_bytes=limit)
        if not isinstance(payload, bytes) or len(payload) > limit:
            raise UpdateError('Invalid or oversized response')
        return payload
    try:
        page = fetch(OFFICIAL_PAGE, MAX_PAGE_BYTES).decode('utf-8')
        parser = _Scripts()
        parser.feed(page)
        bundle_urls = []
        for source in parser.urls:
            url = urljoin(OFFICIAL_PAGE, source)
            try:
                validate_url(url, HUYA_HOSTS)
            except ValueError:
                continue
            path = urlsplit(url).path
            if path.startswith('/gametool/league-of-legends/work/assets/') and path.endswith('.js'):
                bundle_urls.append(url)
        bundle_urls.sort(key=lambda u: not urlsplit(u).path.rsplit('/', 1)[-1].startswith('index-'))
        candidates = []
        for bundle_url in list(dict.fromkeys(bundle_urls))[:6]:
            bundle = fetch(bundle_url, MAX_SCRIPT_BYTES).decode('utf-8')
            candidates = discover_sources(page, [(bundle_url, bundle)])
            if any(source['mode'] == 'hashed-assets' for source in candidates):
                break
        if not candidates:
            raise UpdateError('Official source discovery needs an app update')
        failures = []
        for candidate in candidates[:5]:
            try:
                data, artifacts = {}, {}
                for name in SOURCE_NAMES:
                    payload = fetch(candidate['urls'][name], MAX_JSON_BYTES)
                    data[APP_KEYS.get(name, name)] = strict_json(payload)
                    artifacts[name] = {'url': candidate['urls'][name],
                                       'sha256': hashlib.sha256(payload).hexdigest(), 'bytes': len(payload)}
                validate_dataset(data)
                dates = [x['date'] for x in data['changelogs']['data']
                         if re.fullmatch(r'\d{4}-\d{2}-\d{2}', x.get('date', ''))]
                fetched = _now()
                data['metadata'] = {'source': '虎牙公开海克斯大乱斗图鉴', 'sourceUrl': OFFICIAL_PAGE,
                                    'sourceVersion': candidate['version'], 'fetchedAt': fetched,
                                    'latestChangelogDate': max(dates, default=None), 'demo': False}
                checksum = hashlib.sha256(json_bytes(data)).hexdigest()
                status = {'state': 'fresh', 'checkedAt': checked, 'fetchedAt': fetched,
                          'sourceUrls': [OFFICIAL_PAGE, candidate['bundleUrl']] + list(candidate['urls'].values()),
                          'latestChangelogDate': max(dates, default=None), 'version': candidate['version'],
                          'sha256': checksum, 'usingCached': False, 'sourceMode': candidate['mode'],
                          'bundleSha256': candidate['bundleSha256'], 'artifacts': artifacts,
                          'message': '本次启动已校验虎牙公开数据。抓取时间不代表官方数据更新时间。'}
                envelope = {'schema_version': 1, 'sha256': checksum, 'data': data, 'status': status}
                _commit(cache_dir, envelope)
                return {'data': data, 'status': status}
            except (OSError, ValueError, TypeError, TimeoutError, RecursionError) as exc:
                failures.append(type(exc).__name__)
        raise UpdateError('No complete valid official dataset was available')
    except (OSError, ValueError, TypeError, TimeoutError, RecursionError):
        cached = load_cached_data(cache_dir)
        if cached is not None:
            status = dict(cached['status'], state='cached', checkedAt=checked, usingCached=True,
                          message='本次联网更新未完成，继续使用上次已校验的官方数据；请查看数据日期。')
            return {'data': cached['data'], 'status': status}
        return {'data': None, 'status': {'state': 'unavailable', 'checkedAt': checked, 'fetchedAt': None,
                'sourceUrls': [OFFICIAL_PAGE], 'latestChangelogDate': None, 'version': None, 'sha256': None,
                'usingCached': False, 'message': '无法取得官方数据，且没有可用缓存。请联网后重试；不会用演示数据生成推荐。'}}

# The modern official wiki is the primary source. The older atlas discovery above
# is kept as a tested format adapter, never silently substituted for wiki results.
WIKI_PAGE = 'https://gametool.huya.com/league-of-legends/wiki/index.html?embed=1'
WIKI_FILES = {'champion-list': 'championList', 'augment-list': 'augmentList',
              'champion-detail': 'championDetail', 'augment-detail': 'augmentDetail',
              'item-detail': 'itemDetail'}
MAX_WIKI_TOTAL_BYTES = 32 * 1024 * 1024


def _rate(value):
    if value in ('', None):
        return
    if not isinstance(value, str) or not re.fullmatch(r'\d{1,3}(?:\.\d{1,6})?%', value):
        raise UpdateError('Invalid wiki percentage')
    if not 0 <= float(value[:-1]) <= 100:
        raise UpdateError('Wiki percentage out of range')


def _wiki_records(wiki, key, id_key, name_key):
    records = wiki.get(key)
    if not isinstance(records, list) or not 1 <= len(records) <= 6000:
        raise UpdateError('Missing wiki ' + key)
    ids = set()
    for record in records:
        if (not isinstance(record, dict) or not isinstance(record.get(id_key), str)
                or not re.fullmatch(r'[A-Za-z0-9_.-]{1,64}', record[id_key])
                or not isinstance(record.get(name_key), str) or not 1 <= len(record[name_key]) <= 160):
            raise UpdateError('Invalid wiki ' + key + ' record')
        if record[id_key] in ids:
            raise UpdateError('Duplicate wiki record ID')
        ids.add(record[id_key])
        _rate(record.get('winRate'))
        _rate(record.get('pickRate'))
    return ids


def validate_wiki(wiki):
    if not isinstance(wiki, dict) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,64}', str(wiki.get('version', ''))):
        raise UpdateError('Invalid wiki data version')
    champions = _wiki_records(wiki, 'championList', 'championId', 'championName')
    augments = _wiki_records(wiki, 'augmentList', 'augmentId', 'augmentName')
    if champions != _wiki_records(wiki, 'championDetail', 'championId', 'championName'):
        raise UpdateError('Wiki champion files are not a coherent set')
    if augments != _wiki_records(wiki, 'augmentDetail', 'augmentId', 'augmentName'):
        raise UpdateError('Wiki augment files are not a coherent set')
    items = wiki.get('itemDetail')
    if not isinstance(items, dict) or not 1 <= len(items) <= 6000:
        raise UpdateError('Missing wiki items')
    for name, record in items.items():
        if (not isinstance(name, str) or not name or not isinstance(record, dict)
                or not isinstance(record.get('name'), str) or not isinstance(record.get('itemId'), str)):
            raise UpdateError('Invalid wiki item')
    patches = set()
    for hero in wiki['championDetail']:
        patch = hero.get('version')
        if not isinstance(patch, str) or not re.fullmatch(r'\d{1,3}\.\d{1,3}(?:\.\d{1,3})?', patch):
            raise UpdateError('Invalid game patch')
        patches.add(patch)
        recs = hero.get('augmentRecommendations')
        if not isinstance(recs, list) or len(recs) > 6000:
            raise UpdateError('Missing hero-specific wiki recommendations')
        seen = set()
        for entry in recs:
            if (not isinstance(entry, dict) or entry.get('augmentId') not in augments
                    or not isinstance(entry.get('augmentName'), str)
                    or not isinstance(entry.get('tier'), str)):
                raise UpdateError('Invalid hero-specific wiki recommendation')
            if entry['augmentId'] in seen:
                raise UpdateError('Duplicate hero recommendation')
            seen.add(entry['augmentId'])
            _rate(entry.get('winRate'))
            _rate(entry.get('pickRate'))
            count = entry.get('numGames')
            if type(count) is not int or count < 0 or count > 10**12:
                raise UpdateError('Invalid wiki sample count')
    if len(patches) != 1:
        raise UpdateError('Mixed game patches in wiki data')
    return wiki


def _wiki_failure(cache_dir, checked, *, error_code=None, failed_stage=None):
    cached = load_cached_data(cache_dir)
    if cached is not None and 'wiki' in cached['data']:
        status = dict(cached['status'], state='cached', checkedAt=checked, usingCached=True,
                      errorCode=error_code, failedStage=failed_stage,
                      message='本次联网更新未完成，继续使用上次已校验的虎牙海斗 wiki 数据；请留意版本与抓取时间。')
        from patch_catalog import statistics_status
        applicability = statistics_status({'metadata': dict(cached['data'].get('metadata', {}), officialHeroStatistics=True)})
        status.update(applicability)
        status['message'] += ' ' + applicability['ratingMessage']
        return {'data': cached['data'], 'status': status}
    return {'data': None, 'status': {'state': 'unavailable', 'checkedAt': checked, 'fetchedAt': None,
            'sourceUrls': [WIKI_PAGE], 'latestChangelogDate': None, 'version': None, 'sha256': None,
            'usingCached': False, 'errorCode': error_code, 'failedStage': failed_stage,
            'message': '无法取得虎牙海斗 wiki 数据，且没有可用缓存。请联网后重试；不会用演示数据生成推荐。'}}


def _discover_wiki_config(fetch):
    page_bytes = bundle_bytes = None
    bundle_url = None
    try:
        page_bytes = fetch(WIKI_PAGE, MAX_PAGE_BYTES)
        parser = _Scripts()
        parser.feed(page_bytes.decode('utf-8'))
        bundles = []
        for source in parser.urls:
            url = urljoin(WIKI_PAGE, source)
            try:
                validate_url(url, HUYA_HOSTS)
            except ValueError:
                continue
            path = urlsplit(url).path
            if (path.startswith('/gametool/league-of-legends/wiki/assets/')
                    and re.fullmatch(r'index-[A-Za-z0-9_-]+\.js', path.rsplit('/', 1)[-1])
                    and '/index-legacy-' not in path):
                bundles.append(url)
        if not bundles:
            raise UpdateError('Official wiki bundle not found')
        bundle_url = bundles[0]
        bundle_bytes = fetch(bundle_url, MAX_SCRIPT_BYTES)
        text = bundle_bytes.decode('utf-8')
        ids = set(re.findall(r'\bVITE_TOOL_ID\s*:\s*[\"\']([A-Za-z0-9_-]{1,64})[\"\']', text))
        if len(ids) != 1:
            raise UpdateError('Official wiki tool configuration needs an app update')
        tool_id = ids.pop()
        return tool_id, page_bytes, bundle_url, bundle_bytes, 'fresh-page-config'
    except HTTPError as exc:
        if exc.code not in (500, 502, 503, 504):
            raise
    except (TimeoutError, URLError):
        pass
    # Public service ID independently audited from the official current page.
    # This is an identity, never a pinned data release. The live anonymous RPC
    # still selects today's server-advertised version and verifies that identity.
    return 'p81hl812', page_bytes, bundle_url, bundle_bytes, 'verified-public-tool-id-fallback'


def _refresh_wiki(cache_dir, fetcher, version_fetcher):
    checked, deadline = _now(), time.monotonic() + 50
    if fetcher is None:
        def fetcher(url, *, max_bytes):
            return fetch_bytes(url, max_bytes=max_bytes, deadline=deadline)
    if version_fetcher is None:
        from huya_rpc import fetch_wiki_version
        version_fetcher = fetch_wiki_version
    def fetch(url, limit):
        validate_url(url, HUYA_HOSTS)
        payload = fetcher(url, max_bytes=limit)
        if not isinstance(payload, bytes) or len(payload) > limit:
            raise UpdateError('Invalid or oversized response')
        return payload
    stage = 'discovery'
    try:
        tool_id, page_bytes, bundle_url, bundle_bytes, discovery = _discover_wiki_config(fetch)
        stage = 'version-service'
        version_info = version_fetcher(tool_id, timeout=8, deadline=deadline)
        if not isinstance(version_info, dict):
            raise UpdateError('Invalid wiki version response')
        version = version_info.get('version')
        if (not isinstance(version, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,64}', version)
                or version in ('.', '..')):
            raise UpdateError('Invalid wiki release version')
        base = version_info.get('dataBaseUrl')
        validate_url(base, frozenset({'fileserver.cdn.huya.com'}))
        parsed = urlsplit(base)
        if (parsed.query or not parsed.path.startswith('/game_tools/')
                or '..' in parsed.path or '%' in parsed.path or '\\' in parsed.path):
            raise UpdateError('Unexpected wiki data root')
        root = base.rstrip('/') + '/' + version + '/'
        wiki, artifacts, total = {'version': version}, {}, 0
        for source, appkey in WIKI_FILES.items():
            stage = 'download-' + source
            url = root + source + '.json'
            payload = fetch(url, MAX_JSON_BYTES)
            total += len(payload)
            if total > MAX_WIKI_TOTAL_BYTES:
                raise UpdateError('Wiki dataset exceeds total size limit')
            wiki[appkey] = strict_json(payload)
            artifacts[source] = {'url': url, 'sha256': hashlib.sha256(payload).hexdigest(), 'bytes': len(payload)}
        stage = 'schema-validation'
        _bounded_tree(wiki)
        validate_wiki(wiki)
        fetched = _now()
        patch = wiki['championDetail'][0]['version']
        dates = [row.get('date') for row in wiki['championDetail']
                 if isinstance(row.get('date'), str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', row['date'])]
        source_date = dates[0] if len(dates) == len(wiki['championDetail']) and len(set(dates)) == 1 else None
        metadata = {'source': '虎牙海斗 wiki 公开数据', 'sourceUrl': WIKI_PAGE,
                    'officialHeroStatistics': True,
                    'wikiDataVersion': version, 'gamePatch': patch, 'wikiBaseUrl': root,
                    'isDemo': False, 'demo': False, 'dataFreshness': 'fetched', 'fetchedAt': fetched,
                    'sourceUpdatedAt': None, 'sourceDataDate': source_date, 'latestChangelogDate': None}
        data = {'wiki': wiki, 'metadata': metadata, 'heroes': {}, 'augments': {}, 'items': {},
                'relations': {}, 'combinations': []}
        checksum = hashlib.sha256(json_bytes(data)).hexdigest()
        status = {'state': 'fresh', 'checkedAt': checked, 'fetchedAt': fetched, 'latestChangelogDate': None,
                  'sourceUpdatedAt': None, 'sourceDataDate': source_date, 'version': version, 'gamePatch': patch, 'sha256': checksum,
                  'usingCached': False, 'sourceMode': 'official-wiki', 'wikiBaseUrl': root,
                  'discoveryMethod': discovery,
                  'sourceUrls': [u for u in [WIKI_PAGE, bundle_url, 'https://cdnws.api.huya.com/'] if u] + [a['url'] for a in artifacts.values()],
                  'pageSha256': hashlib.sha256(page_bytes).hexdigest() if page_bytes else None,
                  'bundleSha256': hashlib.sha256(bundle_bytes).hexdigest() if bundle_bytes else None, 'artifacts': artifacts,
                  'versionResponseSha256': version_info.get('responseSha256'),
                  'message': '本次启动已校验虎牙海斗 wiki 数据。数据版本与游戏补丁分别展示；抓取时间不代表官方更新时间。'}
        from patch_catalog import statistics_status
        applicability = statistics_status(data)
        status.update(applicability)
        status['message'] += ' ' + applicability['ratingMessage']
        envelope = {'schema_version': 1, 'sha256': checksum, 'data': data, 'status': status}
        stage = 'cache-commit'
        _commit(cache_dir, envelope)
        return {'data': data, 'status': status}
    except (OSError, ValueError, TypeError, TimeoutError, RecursionError, KeyError) as exc:
        return _wiki_failure(cache_dir, checked, error_code=type(exc).__name__, failed_stage=stage)

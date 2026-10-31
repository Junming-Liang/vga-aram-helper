"""Optional current-patch pick-rate reference from arammayhem.com.

The dataset is CC BY 4.0 and contains pick rates and pick-rate ranks only.
It explicitly excludes win rates, tiers and win-rate-based rankings. A pick
rate is selection heat, not a strength rating. Name matching is presentation
only; no Huya tier, numeric augment ID or win-rate crosswalk is invented.
"""
from __future__ import annotations

import gzip
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
import re
import urllib.parse
import urllib.request

from update_network import atomic_write
from patch_catalog import CURRENT_PATCH

INDEX_URL = 'https://arammayhem.com/data/v1/index.json'
SOURCE_PAGE = 'https://arammayhem.com/zh-cn/data/'
ATTRIBUTION = 'Data: arammayhem.com'
LICENSE_NAME = 'CC BY 4.0'
LICENSE_URL = 'https://creativecommons.org/licenses/by/4.0/'
CACHE_NAME = 'arammayhem.json'
SCHEMA_VERSION = 1
MAX_INDEX_BYTES = 64 * 1024
MAX_DATA_BYTES = 1024 * 1024
MAX_CACHE_BYTES = 2 * 1024 * 1024
TIMEOUT_SECONDS = 8


class AramMayhemError(ValueError):
    """An unavailable, invalid or unlicensed current-patch response."""


def _url(value):
    parsed = urllib.parse.urlsplit(value)
    if (parsed.scheme != 'https' or parsed.hostname != 'arammayhem.com'
            or parsed.username or parsed.password or parsed.port not in (None, 443)
            or parsed.fragment or not parsed.path.startswith('/data/v1/')):
        raise AramMayhemError('Untrusted arammayhem endpoint')
    return value


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    max_redirections = 2

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise AramMayhemError('Duplicate JSON field')
        result[key] = value
    return result


def _strict_json(raw):
    try:
        return json.loads(raw.decode('utf-8'), object_pairs_hook=_pairs,
                          parse_constant=lambda value: (_ for _ in ()).throw(
                              AramMayhemError('Non-finite JSON value')))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise AramMayhemError('Invalid JSON response') from exc


def _fetch(url, *, max_bytes=MAX_DATA_BYTES):
    _url(url)
    request = urllib.request.Request(url, headers={
        'Accept': 'application/json',
        'Accept-Encoding': 'identity',
        'User-Agent': 'VGA-Aram-Helper',
    })
    opener = urllib.request.build_opener(_SafeRedirect())
    with opener.open(request, timeout=TIMEOUT_SECONDS) as response:
        _url(response.geturl())
        if response.status != 200:
            raise AramMayhemError('Unexpected HTTP status')
        length = response.headers.get('Content-Length')
        if length and (not length.isdigit() or int(length) > max_bytes):
            raise AramMayhemError('Invalid response length')
        chunks, total = [], 0
        while True:
            chunk = response.read(min(65536, max_bytes + 1 - total))
            total += len(chunk)
            if total > max_bytes:
                raise AramMayhemError('Response too large')
            if not chunk:
                break
            chunks.append(chunk)
    raw = b''.join(chunks)
    if raw.startswith(b'\x1f\x8b'):
        try:
            raw = gzip.decompress(raw)
        except (OSError, EOFError) as exc:
            raise AramMayhemError('Invalid compressed response') from exc
        if len(raw) > max_bytes:
            raise AramMayhemError('Response too large')
    return _strict_json(raw)


def _text(value, limit):
    if isinstance(value, str):
        value = value.strip()
        return value[:limit] if value else None
    return None


def _name(value):
    if not isinstance(value, dict):
        return None
    for key in ('zh-CN', 'zh-TW', 'en'):
        name = _text(value.get(key), 80)
        if name:
            return name
    return None


def _percent(value):
    return (value if isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and 0 <= value <= 100 else None)


def _rank(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 100000 else None


def _canonical(value):
    import unicodedata
    return ''.join(char for char in unicodedata.normalize('NFKC', str(value)).casefold()
                   if char.isalnum())


def _patch_entry(index, target):
    if not isinstance(index, dict):
        raise AramMayhemError('Invalid index')
    patches = index.get('patches')
    if not isinstance(patches, list):
        raise AramMayhemError('Missing patch index')
    for entry in patches:
        if isinstance(entry, dict) and entry.get('patch') == target:
            return entry
    raise AramMayhemError('Current patch is not published')


def _file_url(entry, kind):
    files = entry.get('files') if isinstance(entry, dict) else None
    record = files.get(kind) if isinstance(files, dict) else None
    value = record.get('json') if isinstance(record, dict) else None
    return _url(value) if isinstance(value, str) else _url('')


def _rows(doc, kind, *, limit):
    if not isinstance(doc, dict):
        raise AramMayhemError('Invalid ' + kind + ' payload')
    rows = doc.get('rows')
    if not isinstance(rows, list) or not 1 <= len(rows) <= limit:
        raise AramMayhemError('Invalid ' + kind + ' rows')
    return rows


def _document_meta(doc, kind):
    meta = doc.get('meta') if isinstance(doc, dict) else None
    if not isinstance(meta, dict):
        raise AramMayhemError('Missing ' + kind + ' metadata')
    patch = _text(meta.get('patch'), 20)
    stats_date = _text(meta.get('statsDate'), 20)
    if not patch or not re.fullmatch(r'\d{1,3}\.\d{1,3}(?:\.\d{1,3})?', patch):
        raise AramMayhemError('Invalid patch')
    if not stats_date or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', stats_date):
        raise AramMayhemError('Invalid statistics date')
    return patch, stats_date


def _attribution(*docs):
    for doc in docs:
        value = doc.get('attribution') if isinstance(doc, dict) else None
        if isinstance(value, str) and 'arammayhem.com' in value:
            return value[:120]
        license_value = doc.get('license') if isinstance(doc, dict) else None
        if isinstance(license_value, str) and 'CC BY 4.0' in license_value:
            return ATTRIBUTION
    raise AramMayhemError('Missing CC BY attribution')


def normalize_payload(augments_doc, champions_doc, *, index_doc=None, fetched_at=None):
    """Project localized names plus pick rates; discard every other field."""
    patch, stats_date = _document_meta(augments_doc, 'augments')
    champion_patch, champion_date = _document_meta(champions_doc, 'champions')
    if (patch, stats_date) != (champion_patch, champion_date):
        raise AramMayhemError('Inconsistent patch snapshots')
    attribution = _attribution(augments_doc, champions_doc, index_doc)
    augments = []
    for row in _rows(augments_doc, 'augments', limit=1000):
        if not isinstance(row, dict):
            continue
        name = _name(row.get('name'))
        slug = _text(row.get('augmentId'), 64)
        pick_rate = _percent(row.get('pickRate'))
        rank = _rank(row.get('pickRateRank'))
        if not name or not slug or pick_rate is None or rank is None:
            continue
        retired = _text(row.get('retiredPatch'), 20)
        augments.append({
            'name': name, 'slug': slug,
            'rarity': _text(row.get('rarity'), 20),
            'pickRate': pick_rate, 'pickRateRank': rank,
            'introducedPatch': _text(row.get('introducedPatch'), 20),
            'retiredPatch': retired,
            'url': _text(row.get('url'), 300),
        })
    champions = []
    for row in _rows(champions_doc, 'champions', limit=1000):
        if not isinstance(row, dict):
            continue
        name = _name(row.get('name'))
        champion_id = _text(row.get('championId'), 64)
        pick_rate = _percent(row.get('pickRate'))
        rank = _rank(row.get('pickRateRank'))
        if not name or not champion_id or pick_rate is None or rank is None:
            continue
        champions.append({
            'name': name, 'championId': champion_id,
            'pickRate': pick_rate, 'pickRateRank': rank,
            'url': _text(row.get('url'), 300),
        })
    if not augments or not champions:
        raise AramMayhemError('No usable rows')
    fetched_at = fetched_at or datetime.now(timezone.utc).isoformat()
    return {
        'schemaVersion': SCHEMA_VERSION,
        'metadata': {
            'source': 'arammayhem.com', 'sourcePage': SOURCE_PAGE,
            'attribution': attribution, 'license': LICENSE_NAME,
            'licenseUrl': LICENSE_URL, 'patch': patch, 'statsDate': stats_date,
            'fetchedAt': fetched_at,
        },
        'augments': augments[:1000], 'champions': champions[:1000],
    }


def sync(state_dir, *, fetcher=None, target_patch=None, fetched_at=None):
    """Fetch the current patch, normalize it and atomically cache the result."""
    fetcher = fetcher or (lambda url: _fetch(url, max_bytes=(
        MAX_INDEX_BYTES if url == INDEX_URL else MAX_DATA_BYTES)))
    target = target_patch or CURRENT_PATCH
    index = fetcher(INDEX_URL)
    entry = _patch_entry(index, target)
    augments_doc = fetcher(_file_url(entry, 'augments'))
    champions_doc = fetcher(_file_url(entry, 'champions'))
    cache = normalize_payload(augments_doc, champions_doc, index_doc=index,
                              fetched_at=fetched_at)
    if cache['metadata']['patch'] != target:
        raise AramMayhemError('Patch mismatch')
    path = Path(state_dir) / CACHE_NAME
    atomic_write(path, json.dumps(cache, ensure_ascii=False, allow_nan=False,
                                  separators=(',', ':')).encode('utf-8'))
    return {'cache': str(path), 'patch': cache['metadata']['patch'],
            'statsDate': cache['metadata']['statsDate'],
            'augments': len(cache['augments']), 'champions': len(cache['champions']),
            'attribution': cache['metadata']['attribution'],
            'license': cache['metadata']['license']}


def load_cached(state_dir):
    """Return a validated cache snapshot or None; never fetch during UI reads."""
    path = Path(state_dir) / CACHE_NAME
    try:
        if path.stat().st_size > MAX_CACHE_BYTES:
            return None
        cache = _strict_json(path.read_bytes())
    except (OSError, AramMayhemError):
        return None
    if not isinstance(cache, dict) or cache.get('schemaVersion') != SCHEMA_VERSION:
        return None
    meta = cache.get('metadata')
    if not isinstance(meta, dict) or not isinstance(cache.get('augments'), list) \
            or not isinstance(cache.get('champions'), list):
        return None
    if not isinstance(meta.get('patch'), str) or not re.fullmatch(r'\d{1,3}\.\d{1,3}(?:\.\d{1,3})?', meta['patch']):
        return None
    if not isinstance(meta.get('statsDate'), str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', meta['statsDate']):
        return None
    if not isinstance(meta.get('attribution'), str) or 'arammayhem.com' not in meta['attribution']:
        return None
    return cache


def _active_augments(cache):
    rows = cache.get('augments') if isinstance(cache, dict) else None
    return [row for row in rows if isinstance(row, dict) and not row.get('retiredPatch')] \
        if isinstance(rows, list) else []


def lookup_augment(cache, name):
    """Unique exact or canonical name match; ambiguity abstains."""
    if not isinstance(name, str) or not name.strip():
        return None
    rows = _active_augments(cache)
    exact = [row for row in rows if row.get('name') == name.strip()]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        return None
    key = _canonical(name)
    if not key:
        return None
    matches = [row for row in rows if isinstance(row.get('name'), str) and _canonical(row['name']) == key]
    return matches[0] if len(matches) == 1 else None


def lookup_champion(cache, hero, aliases=()):
    """Match the local hero name or its reviewed aliases to one champion row."""
    rows = cache.get('champions') if isinstance(cache, dict) else None
    rows = [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []
    candidates = [hero] + list(aliases) if isinstance(aliases, (list, tuple)) else [hero]
    candidates = [value.strip() for value in candidates if isinstance(value, str) and value.strip()]
    for canonical in (False, True):
        matches = []
        for value in candidates:
            key = _canonical(value) if canonical else value
            if not key:
                continue
            for row in rows:
                name = row.get('name')
                if not isinstance(name, str):
                    continue
                if (_canonical(name) if canonical else name) == key and row not in matches:
                    matches.append(row)
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            return None
    return None

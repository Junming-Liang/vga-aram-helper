"""Fresh, opt-in current-self identity from the official Game Client API.

Schema/source: https://developer.riotgames.com/docs/lol#game-client-api
Only documented activeplayername/playerlist endpoints are used. No credentials,
player identifiers, roster payloads, or errors leave this module. No cache exists.
The caller owns consent, verified process scope, mode gating and UI invalidation.
"""
from pathlib import Path
import http.client
import json
import re
import ssl
import time

PATHS = frozenset(('/liveclientdata/activeplayername', '/liveclientdata/playerlist'))
MAX_RESPONSE = 256 * 1024
BATCH_TIMEOUT = 1.8
PREFIX = 'game_character_displayname_'


def _valid_map(mapping):
    return (isinstance(mapping, dict) and 0 < len(mapping) <= 512
            and all(isinstance(k, str) and re.fullmatch(r'[A-Za-z0-9]{1,60}', k)
                    and isinstance(v, str) and re.fullmatch(r'[1-9][0-9]{0,5}', v)
                    for k, v in mapping.items())
            and len(set(mapping.values())) == len(mapping))


def identity_from_payload(active_name, players, canonical_name_to_id):
    """Return only an ID; match exact Riot ID, never fuzzy/localized names.

    canonical_name_to_id must originate from validated official Data Dragon
    champion id/key records. rawChampionName is a localization token, whose
    exact canonical suffix can match that trusted table. No fallback guesses.
    """
    if (not _valid_map(canonical_name_to_id) or not isinstance(active_name, str)
            or not 1 <= len(active_name) <= 256
            or not isinstance(players, list) or not 1 <= len(players) <= 20
            or any(not isinstance(row, dict) for row in players)):
        return None
    modern = '#' in active_name
    own = [row for row in players if row.get('riotId' if modern else 'summonerName') == active_name]
    if len(own) != 1:
        return None
    row = own[0]
    # Optional component fields must corroborate rather than conflict.
    if not modern and 'riotIdGameName' in row and row['riotIdGameName'] != active_name:
        return None
    if not modern and 'riotId' in row:
        riot_id = row['riotId']
        if (not isinstance(riot_id, str) or riot_id.count('#') != 1
                or not riot_id.split('#', 1)[1]
                or riot_id.split('#', 1)[0] != active_name):
            return None
        if 'riotIdTagLine' in row and row['riotIdTagLine'] != riot_id.split('#', 1)[1]:
            return None
    elif not modern and 'riotIdTagLine' in row:
        return None
    if modern and ('riotIdGameName' in row or 'riotIdTagLine' in row):
        name, tag = row.get('riotIdGameName'), row.get('riotIdTagLine')
        if not isinstance(name, str) or not isinstance(tag, str) or name + '#' + tag != active_name:
            return None
    raw = row.get('rawChampionName')
    if not isinstance(raw, str) or not raw.startswith(PREFIX):
        return None
    return canonical_name_to_id.get(raw[len(PREFIX):])


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('invalid_json')
        result[key] = value
    return result


def _get(path, context, deadline, cancelled, clock):
    if path not in PATHS or cancelled.is_set() or clock() >= deadline:
        raise ValueError('unavailable')
    # http.client uses a direct literal address and ignores proxy environment.
    # It never follows redirects. No authorization header or user-derived URL.
    connection = http.client.HTTPSConnection('127.0.0.1', 2999,
        timeout=min(.45, deadline - clock()), context=context)
    try:
        connection.request('GET', path, headers={'Accept': 'application/json'})
        response = connection.getresponse()
        if response.status != 200 or response.getheader('Content-Encoding', 'identity') != 'identity':
            raise ValueError('unavailable')
        length = response.getheader('Content-Length')
        if length is not None and (not length.isdecimal() or int(length) > MAX_RESPONSE):
            raise ValueError('unavailable')
        chunks = []; size = 0
        while True:
            remaining = deadline - clock()
            if remaining <= 0 or cancelled.is_set():
                raise ValueError('unavailable')
            if connection.sock:
                connection.sock.settimeout(min(.45, remaining))
            chunk = response.read1(min(16384, MAX_RESPONSE + 1 - size))
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_RESPONSE:
                raise ValueError('unavailable')
            chunks.append(chunk)
        if clock() >= deadline or cancelled.is_set():
            raise ValueError('unavailable')
        return json.loads(b''.join(chunks), object_pairs_hook=_unique_object,
                          parse_constant=lambda _: (_ for _ in ()).throw(ValueError('invalid_json')))
    finally:
        connection.close()


def read_current_identity(canonical_name_to_id, *, enabled=False, cancelled,
                          scope_probe, ca_file=None, clock=time.monotonic):
    """Return fresh minimal observation or None for every failure/mismatch.

    scope_probe returns the verified current game process/window generation,
    or None on loss. It must detect process restarts (PID alone is insufficient).
    Caller must recheck scope before applying an async result and clear previous
    evidence on failure, consent loss, restart, mode loss or conflicting HUD.
    The returned observation is for this poll only: never reuse across matches.
    """
    if enabled is not True:
        return None
    try:
        if cancelled.is_set() or not _valid_map(canonical_name_to_id):
            return None
        scope = scope_probe()
        if scope is None:
            return None
        context = ssl.create_default_context(cafile=str(ca_file or
            Path(__file__).resolve().parent / 'assets' / 'riotgames.pem'))
        if context.verify_mode != ssl.CERT_REQUIRED or not context.check_hostname:
            return None
        deadline = clock() + BATCH_TIMEOUT
        first_name = _get('/liveclientdata/activeplayername', context, deadline, cancelled, clock)
        first = identity_from_payload(first_name,
            _get('/liveclientdata/playerlist', context, deadline, cancelled, clock), canonical_name_to_id)
        if first is None:
            return None
        second_name = _get('/liveclientdata/activeplayername', context, deadline, cancelled, clock)
        second = identity_from_payload(second_name,
            _get('/liveclientdata/playerlist', context, deadline, cancelled, clock), canonical_name_to_id)
        if (first_name != second_name or first != second or scope_probe() != scope
                or cancelled.is_set() or clock() >= deadline):
            return None
        return {'championId': first, 'confident': True, 'method': 'game-client-api'}
    except Exception:
        # Never expose exception text, which could contain names or raw payload.
        return None


def source_hero_names(data):
    """Canonical IDs with exactly one source hero; duplicate IDs abstain."""
    heroes=data.get('heroes',{}) if isinstance(data,dict) else {}
    if not isinstance(heroes,dict):return {}
    result={};ambiguous=set()
    for name,row in heroes.items():
        if not isinstance(name,str) or not name or not isinstance(row,dict):continue
        cid=row.get('championId')
        if not isinstance(cid,str) or not re.fullmatch(r'[1-9][0-9]{0,5}',cid):continue
        if cid in result:ambiguous.add(cid)
        else:result[cid]=name
    return {cid:name for cid,name in result.items() if cid not in ambiguous}


def reconcile_identity(hud,api,hero_names):
    """Fresh API cannot override a confident conflicting HUD or unknown source."""
    if not api:return hud
    cid=api.get('championId');name=hero_names.get(cid)
    unknown={'hero':None,'championId':None,'confident':False,'method':'game-client-api'}
    if api.get('confident') is not True or not name:
        return {**unknown,'reason':'本机英雄尚无已核验资料'}
    if hud.get('confident') is True and hud.get('championId')!=cid:
        return {**unknown,'reason':'本机接口与当前 HUD 英雄不一致，已隐藏资料'}
    return {**api,'hero':name,'reason':'本机游戏接口连续核验本人英雄'}

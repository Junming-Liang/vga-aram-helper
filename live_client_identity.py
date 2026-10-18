"""Fresh, opt-in current-self identity from the official Game Client API.

Schema/source: https://developer.riotgames.com/docs/lol#game-client-api
Only documented activeplayername/playerlist endpoints are used. No credentials,
player identifiers, roster payloads, or exception text leave this module. Only
fixed outcome codes may describe a failure. No cache exists.
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


API_OUTCOMES = frozenset({'disabled', 'cancelled', 'map_invalid', 'scope_unavailable',
    'tls_context_failed', 'tls_verification_failed', 'connection_failed', 'http_error',
    'response_invalid', 'payload_invalid', 'active_player_mismatch', 'champion_unmapped',
    'unstable', 'scope_changed', 'timeout', 'verified', 'unexpected_error'})
MAP_OUTCOMES = frozenset({'not_requested', 'verified', 'verified_memory', 'verified_roster', 'manifest_unavailable',
    'manifest_invalid', 'roster_unavailable', 'hash_mismatch', 'roster_invalid'})
IDENTITY_OUTCOMES = frozenset({'api_verified', 'hud_verified', 'hud_abstained',
    'api_hud_conflict', 'source_unmapped'})


def report_outcome(callback, outcome, allowed):
    """Diagnostics accept fixed codes only and cannot affect identity decisions."""
    if callback is not None and type(outcome) is str and outcome in allowed:
        try:callback(outcome)
        except Exception:pass


class _ReadFailure(ValueError):
    def __init__(self, outcome):
        self.outcome = outcome if outcome in API_OUTCOMES else 'unexpected_error'
        super().__init__(self.outcome)


def _valid_map(mapping):
    return (isinstance(mapping, dict) and 0 < len(mapping) <= 512
            and all(isinstance(k, str) and re.fullmatch(r'[A-Za-z0-9]{1,60}', k)
                    and isinstance(v, str) and re.fullmatch(r'[1-9][0-9]{0,5}', v)
                    for k, v in mapping.items())
            and len(set(mapping.values())) == len(mapping))


def identity_from_payload(active_name, players, canonical_name_to_id, *, diagnostic_callback=None):
    """Return only an ID; match exact Riot ID, never fuzzy/localized names.

    canonical_name_to_id must originate from validated official Data Dragon
    champion id/key records. rawChampionName is a localization token, whose
    exact canonical suffix can match that trusted table. No fallback guesses.
    """
    def finish(outcome, champion_id=None):
        report_outcome(diagnostic_callback, outcome, API_OUTCOMES)
        return champion_id
    if not _valid_map(canonical_name_to_id):return finish('map_invalid')
    if (not isinstance(active_name, str)
            or not 1 <= len(active_name) <= 256
            or not isinstance(players, list) or not 1 <= len(players) <= 20
            or any(not isinstance(row, dict) for row in players)):
        return finish('payload_invalid')
    modern = '#' in active_name
    own = [row for row in players if row.get('riotId' if modern else 'summonerName') == active_name]
    if len(own) != 1:
        return finish('active_player_mismatch')
    row = own[0]
    # Optional component fields must corroborate rather than conflict.
    if not modern and 'riotIdGameName' in row and row['riotIdGameName'] != active_name:
        return finish('active_player_mismatch')
    if not modern and 'riotId' in row:
        riot_id = row['riotId']
        if (not isinstance(riot_id, str) or riot_id.count('#') != 1
                or not riot_id.split('#', 1)[1]
                or riot_id.split('#', 1)[0] != active_name):
            return finish('active_player_mismatch')
        if 'riotIdTagLine' in row and row['riotIdTagLine'] != riot_id.split('#', 1)[1]:
            return finish('active_player_mismatch')
    elif not modern and 'riotIdTagLine' in row:
        return finish('active_player_mismatch')
    if modern and ('riotIdGameName' in row or 'riotIdTagLine' in row):
        name, tag = row.get('riotIdGameName'), row.get('riotIdTagLine')
        if not isinstance(name, str) or not isinstance(tag, str) or name + '#' + tag != active_name:
            return finish('active_player_mismatch')
    raw = row.get('rawChampionName')
    if not isinstance(raw, str) or not raw.startswith(PREFIX):
        return finish('payload_invalid')
    champion_id = canonical_name_to_id.get(raw[len(PREFIX):])
    return finish('verified' if champion_id else 'champion_unmapped', champion_id)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('invalid_json')
        result[key] = value
    return result


def _get(path, context, deadline, cancelled, clock):
    if path not in PATHS:raise _ReadFailure('response_invalid')
    if cancelled.is_set():raise _ReadFailure('cancelled')
    if clock() >= deadline:raise _ReadFailure('timeout')
    # http.client uses a direct literal address and ignores proxy environment.
    # It never follows redirects. No authorization header or user-derived URL.
    connection = http.client.HTTPSConnection('127.0.0.1', 2999,
        timeout=min(.45, deadline - clock()), context=context)
    try:
        connection.request('GET', path, headers={'Accept': 'application/json'})
        response = connection.getresponse()
        if response.status != 200:raise _ReadFailure('http_error')
        if response.getheader('Content-Encoding', 'identity') != 'identity':
            raise _ReadFailure('response_invalid')
        length = response.getheader('Content-Length')
        if length is not None and (not length.isdecimal() or int(length) > MAX_RESPONSE):
            raise _ReadFailure('response_invalid')
        chunks = []; size = 0
        while True:
            remaining = deadline - clock()
            if remaining <= 0:raise _ReadFailure('timeout')
            if cancelled.is_set():raise _ReadFailure('cancelled')
            if connection.sock:
                connection.sock.settimeout(min(.45, remaining))
            chunk = response.read1(min(16384, MAX_RESPONSE + 1 - size))
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_RESPONSE:
                raise _ReadFailure('response_invalid')
            chunks.append(chunk)
        if clock() >= deadline:raise _ReadFailure('timeout')
        if cancelled.is_set():raise _ReadFailure('cancelled')
        try:
            return json.loads(b''.join(chunks), object_pairs_hook=_unique_object,
                parse_constant=lambda _: (_ for _ in ()).throw(ValueError('invalid_json')))
        except (ValueError, UnicodeError):raise _ReadFailure('response_invalid') from None
    finally:
        connection.close()


def read_current_identity(canonical_name_to_id, *, enabled=False, cancelled,
                          scope_probe, ca_file=None, clock=time.monotonic,
                          diagnostic_callback=None):
    """Fresh minimal observation or None; optional diagnostics are fixed codes.

    scope_probe verifies the current process/window generation, including process
    creation time. Caller rechecks async scope and clears evidence on failure,
    consent/mode loss or conflict. No observation is cached across matches.
    """
    def finish(outcome, observation=None):
        report_outcome(diagnostic_callback, outcome, API_OUTCOMES)
        return observation
    if enabled is not True:return finish('disabled')
    stage = 'unexpected_error'
    try:
        if cancelled.is_set():return finish('cancelled')
        if not _valid_map(canonical_name_to_id):return finish('map_invalid')
        stage = 'scope_unavailable'
        scope = scope_probe()
        if scope is None:return finish('scope_unavailable')
        stage = 'tls_context_failed'
        context = ssl.create_default_context(cafile=str(ca_file or
            Path(__file__).resolve().parent / 'assets' / 'riotgames.pem'))
        if context.verify_mode != ssl.CERT_REQUIRED or not context.check_hostname:
            return finish('tls_context_failed')
        stage = 'unexpected_error'
        deadline = clock() + BATCH_TIMEOUT
        payload_outcomes = []
        first_name = _get('/liveclientdata/activeplayername', context, deadline, cancelled, clock)
        first = identity_from_payload(first_name,
            _get('/liveclientdata/playerlist', context, deadline, cancelled, clock), canonical_name_to_id,
            diagnostic_callback=payload_outcomes.append)
        if first is None:return finish(payload_outcomes[-1])
        second_name = _get('/liveclientdata/activeplayername', context, deadline, cancelled, clock)
        second = identity_from_payload(second_name,
            _get('/liveclientdata/playerlist', context, deadline, cancelled, clock), canonical_name_to_id,
            diagnostic_callback=payload_outcomes.append)
        if first_name != second_name or first != second:
            return finish(payload_outcomes[-1] if second is None else 'unstable')
        stage = 'scope_unavailable'
        if scope_probe() != scope:return finish('scope_changed')
        stage = 'unexpected_error'
        if cancelled.is_set():return finish('cancelled')
        if clock() >= deadline:return finish('timeout')
        return finish('verified', {'championId': first, 'confident': True, 'method': 'game-client-api'})
    except _ReadFailure as exc:return finish(exc.outcome)
    except ssl.SSLCertVerificationError:
        return finish(stage if stage != 'unexpected_error' else 'tls_verification_failed')
    except TimeoutError:return finish(stage if stage != 'unexpected_error' else 'timeout')
    except (OSError, http.client.HTTPException):
        return finish(stage if stage != 'unexpected_error' else 'connection_failed')
    except Exception:
        # Never inspect or retain exception messages or payloads in diagnostics.
        return finish(stage)


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


def reconcile_identity(hud,api,hero_names,*,diagnostic_callback=None):
    """Fresh API cannot override a confident conflicting HUD or unknown source."""
    def finish(outcome, observation):
        report_outcome(diagnostic_callback, outcome, IDENTITY_OUTCOMES)
        return observation
    if not api:
        return finish('hud_verified' if isinstance(hud,dict) and hud.get('confident') is True else 'hud_abstained', hud)
    cid=api.get('championId');name=hero_names.get(cid)
    unknown={'hero':None,'championId':None,'confident':False,'method':'game-client-api'}
    if api.get('confident') is not True or not name:
        return finish('source_unmapped', {**unknown,'reason':'本机英雄尚无已核验资料'})
    if hud.get('confident') is True and hud.get('championId')!=cid:
        return finish('api_hud_conflict', {**unknown,'reason':'本机接口与当前 HUD 英雄不一致，已隐藏资料'})
    return finish('api_verified', {**api,'hero':name,'reason':'本机游戏接口连续核验本人英雄'})

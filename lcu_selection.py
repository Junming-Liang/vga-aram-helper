"""Opt-in, session-only, GET-only local League selection reader.

Original implementation. No game memory, command-line scraping, remote requests,
client writes, token persistence, account identifiers, or raw error logging.
Caller must grant explicit consent and bind a verified client installation.
"""
from dataclasses import dataclass, field
from pathlib import Path, PureWindowsPath
import base64
import http.client
import json
import re
import ssl
import time

PATHS = frozenset(('/lol-gameflow/v1/gameflow-phase', '/lol-gameflow/v1/session',
                   '/lol-champ-select/v1/session'))
MAX_RESPONSE = 512 * 1024

class LCUUnavailable(Exception):
    """Fixed, non-sensitive public error; never include credentials or payload."""

@dataclass(frozen=True)
class Credentials:
    pid: int
    port: int
    token: str = field(repr=False)

def parse_lockfile(payload):
    if not isinstance(payload, bytes) or not 0 < len(payload) <= 1024:
        raise LCUUnavailable('local_client_unavailable')
    try:
        name, pid, port, token, protocol = payload.decode('ascii').strip().split(':')
        if name != 'LeagueClient' or protocol != 'https' or not pid.isdecimal() or not port.isdecimal():
            raise ValueError()
        if not 1 <= int(pid) <= 2**32-1 or not 1 <= int(port) <= 65535 or not re.fullmatch(r'[A-Za-z0-9_+/=-]{8,256}', token):
            raise ValueError()
        return Credentials(int(pid), int(port), token)
    except (ValueError, UnicodeError):
        raise LCUUnavailable('local_client_unavailable') from None

def champion_id(value):
    return str(value) if type(value) is int and 0 < value <= 100000 else None

def selection_observation(phase, flow, session):
    """Minimize input to IDs only; never retain player names/PUUIDs/chat."""
    unknown = {'scene': 'unknown', 'championId': None, 'assigned': False,
               'reason': '本地客户端当前不在已核验的海克斯大乱斗选人阶段', 'method': 'lcu-read-only'}
    if phase != 'ChampSelect' or not isinstance(flow, dict) or not isinstance(session, dict):
        return unknown
    # Fail closed for other modes. Queue 2400 is ARAM: Mayhem, not ordinary ARAM.
    queue = flow.get('gameData', {}).get('queue', {}) if isinstance(flow.get('gameData'), dict) else {}
    if not isinstance(queue, dict) or type(queue.get('id')) is not int or queue['id'] != 2400:
        return unknown
    local = session.get('localPlayerCellId')
    team = session.get('myTeam'); bench = session.get('benchChampions', [])
    if type(local) is not int or not 0 <= local < 10 or not isinstance(team, list) or not 1 <= len(team) <= 5 or not isinstance(bench, list) or len(bench) > 20:
        return unknown
    own = [p for p in team if isinstance(p, dict) and type(p.get('cellId')) is int and p['cellId'] == local]
    if len(own) != 1:
        return unknown
    selected = champion_id(own[0].get('championId'))
    allies = tuple(dict.fromkeys(cid for p in team if isinstance(p, dict) and (cid := champion_id(p.get('championId')))))
    available = tuple(dict.fromkeys(cid for p in bench if isinstance(p, dict) and (cid := champion_id(p.get('championId')))))
    return {'scene': 'assigned-selection' if selected else 'initial-cards',
            'championId': selected, 'assigned': bool(selected), 'teamChampionIds': allies,
            'benchChampionIds': available, 'reason': '本地客户端只读选人资料；仍可交换',
            'method': 'lcu-read-only', 'requiresTemporalStability': True}

def tier_references(data, ids):
    from hero_strength import hero_strength_reference
    heroes = data.get('heroes', {}) if isinstance(data, dict) else {}
    result = []
    for cid in ids:
        matches = [name for name, row in heroes.items() if isinstance(row, dict) and row.get('championId') == cid]
        if len(matches) == 1:
            ref = hero_strength_reference(data, matches[0], champion_id=cid)
            if ref: result.append(ref)
    return result

class LocalSelectionReader:
    """Create only for an explicitly opted-in, verified client session.

    HTTPS uses the vendor's documented root CA, normal hostname validation,
    direct literal loopback (no proxies), no redirects, bounded payload/time.
    Metadata is checked before and after each request batch. Tokens exist only
    as local values during read(), and are never returned or stored on self.
    """
    def __init__(self, client_metadata, *, resolver, ca_file=None, clock=time.monotonic):
        from session_windows import normalized_path
        path = PureWindowsPath(normalized_path(client_metadata.path))
        if path.name not in ('leagueclient.exe', 'leagueclientux.exe'):
            raise LCUUnavailable('client_identity_changed')
        self.root = path.parent
        self.resolver = resolver
        self.clock = clock
        self.ca_file = Path(ca_file) if ca_file else Path(__file__).resolve().parent / 'assets' / 'riotgames.pem'

    def _metadata(self, credentials):
        from session_windows import normalized_path
        metadata = self.resolver(credentials.pid)
        if normalized_path(metadata.path) != str(self.root / 'leagueclient.exe'):
            raise LCUUnavailable('client_identity_changed')
        return metadata

    def _get(self, credentials, path, context, deadline, cancelled):
        if path not in PATHS or cancelled.is_set():
            raise LCUUnavailable('local_request_cancelled')
        remaining = deadline - self.clock()
        if remaining <= 0:
            raise LCUUnavailable('local_client_timeout')
        connection = http.client.HTTPSConnection('127.0.0.1', credentials.port,
                       timeout=min(.6, remaining), context=context)
        try:
            authorization = base64.b64encode(('riot:' + credentials.token).encode('ascii')).decode('ascii')
            connection.request('GET', path, headers={'Authorization': 'Basic ' + authorization, 'Accept': 'application/json'})
            response = connection.getresponse()
            if response.status != 200:
                raise LCUUnavailable('local_client_unavailable')
            chunks=[];size=0
            while True:
                remaining=deadline-self.clock()
                if remaining<=0 or cancelled.is_set():raise LCUUnavailable('local_client_timeout')
                if connection.sock:connection.sock.settimeout(min(.6,remaining))
                chunk=response.read1(min(16384,MAX_RESPONSE+1-size))
                if not chunk:break
                chunks.append(chunk);size+=len(chunk)
                if size>MAX_RESPONSE:raise LCUUnavailable('local_client_timeout')
            if self.clock()>deadline:raise LCUUnavailable('local_client_timeout')
            return json.loads(b''.join(chunks))
        finally:
            connection.close()

    def read(self, *, cancelled):
        try:
            if cancelled.is_set(): raise LCUUnavailable('local_request_cancelled')
            lockfile = Path(str(self.root / 'lockfile'))
            with lockfile.open('rb') as handle: raw = handle.read(1025)
            credentials = parse_lockfile(raw)
            metadata = self._metadata(credentials)
            context = ssl.create_default_context(cafile=str(self.ca_file))
            deadline = self.clock() + 1.8
            phase = self._get(credentials, '/lol-gameflow/v1/gameflow-phase', context, deadline, cancelled)
            if phase != 'ChampSelect':
                return selection_observation(phase, None, None)
            flow = self._get(credentials, '/lol-gameflow/v1/session', context, deadline, cancelled)
            session = self._get(credentials, '/lol-champ-select/v1/session', context, deadline, cancelled)
            phase_after = self._get(credentials, '/lol-gameflow/v1/gameflow-phase', context, deadline, cancelled)
            if phase_after != phase:return selection_observation(phase_after,None,None)
            if metadata != self._metadata(credentials) or cancelled.is_set():
                raise LCUUnavailable('client_identity_changed')
            with lockfile.open('rb') as handle: current = handle.read(1025)
            if current != raw: raise LCUUnavailable('client_identity_changed')
            result=selection_observation(phase, flow, session)
            game_data=flow.get('gameData',{}) if isinstance(flow,dict) else {}
            game_id=game_data.get('gameId') if isinstance(game_data,dict) else None
            if type(game_id) is not int or game_id<0:game_id=None
            result['_lcuInstance']=(credentials.pid,metadata.created,game_id)
            return result
        except LCUUnavailable:
            raise
        except Exception:
            raise LCUUnavailable('local_client_unavailable') from None

class SelectionSnapshot:
    """Two fresh equal snapshots; scope, mode, swap and expiry hide immediately."""
    def __init__(self): self.clear()
    def clear(self):
        self.scope = None; self.signature = None; self.count = 0; self.observed_at = 0.; self.value = None
    def observe(self, value, scope, captured_at, now):
        if not isinstance(value, dict) or value.get('method') != 'lcu-read-only' or value.get('scene') not in ('assigned-selection', 'initial-cards') or not 0 <= now-captured_at <= 4:
            self.clear(); return
        signature = (value.get('_lcuInstance'), value.get('championId'), tuple(value.get('teamChampionIds', ())), tuple(value.get('benchChampionIds', ())))
        if scope != self.scope or signature != self.signature or not 0 < captured_at-self.observed_at <= 4:
            self.clear()
        self.scope = scope; self.signature = signature; self.count += 1; self.observed_at = captured_at
        self.value = dict(value) if self.count >= 2 else None
    def current(self, scope, now):
        return self.value if scope == self.scope and 0 <= now-self.observed_at <= 4 else None

def selection_reference(data, value):
    if not value: return None
    teams = tier_references(data, value.get('teamChampionIds', ()))
    benches = tier_references(data, value.get('benchChampionIds', ()))
    if not teams and not benches: return None
    base = dict((teams or benches)[0])
    base.update(hero='选人英雄一览', championId=None, sourceTier=None,
                selectionRows=[('队伍', teams), ('备选席', benches)], ownChampionId=value.get('championId'))
    return base

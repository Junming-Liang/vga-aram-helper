"""Local item-value difference from the documented Game Client API.

Only the documented localhost 2999 endpoints are read; no credentials, remote
service, item memory or network beyond loopback. Values use bundled item costs
and are purchased-item value, not raw gold.
"""
from __future__ import annotations

import math

from live_client_identity import fetch_live_json

MAX_PLAYERS = 20


def item_costs(data):
    """Map numeric game item IDs to bundled costs; ignore unknown/malformed rows."""
    rows = data.get('aram', {}).get('items') if isinstance(data, dict) else None
    costs = {}
    if not isinstance(rows, list):
        return costs
    for row in rows:
        if not isinstance(row, dict):
            continue
        game_id, cost = row.get('gameItemId'), row.get('cost')
        if isinstance(game_id, str) and game_id.isdigit() and isinstance(cost, int) \
                and not isinstance(cost, bool) and 0 <= cost <= 100000:
            costs[int(game_id)] = cost
    return costs


def _value(player, costs):
    items = player.get('items')
    if not isinstance(items, list):
        return 0, 0, 0
    value = known = total = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        item_id = item.get('itemID', item.get('itemId'))
        if not isinstance(item_id, int) or isinstance(item_id, bool) or item_id <= 0:
            continue
        total += 1
        cost = costs.get(item_id)
        if cost is not None:
            value += cost
            known += 1
    return value, known, total


def _format(value):
    if value >= 10000:
        return f'{value / 1000:.1f}k'
    return str(int(value))


def _format_diff(value):
    if value == 0:
        return '0'
    return ('+' if value > 0 else '-') + _format(abs(value))


def compute(players, active_name, costs):
    """Return team purchased-item values and self-team orientation."""
    if not isinstance(players, list) or not 2 <= len(players) <= MAX_PLAYERS \
            or not isinstance(costs, dict):
        return None
    blue = red = known = total = 0
    self_team = 'ORDER'
    for player in players:
        if not isinstance(player, dict):
            return None
        team = player.get('team')
        if team not in ('ORDER', 'CHAOS'):
            continue
        value, player_known, player_total = _value(player, costs)
        if team == 'ORDER':
            blue += value
        else:
            red += value
        known += player_known
        total += player_total
        if isinstance(active_name, str) and active_name:
            if player.get('riotId') == active_name or player.get('summonerName') == active_name:
                self_team = team
    diff = blue - red
    return {
        'blue': blue, 'red': red, 'diff': diff, 'selfTeam': self_team,
        'blueText': _format(blue), 'redText': _format(red),
        'diffText': _format_diff(diff),
        'knownItems': known, 'totalItems': total,
    }


def observe(data, *, timeout=1.2):
    """Read the local player list and return the current item-value summary."""
    costs = item_costs(data)
    if not costs:
        return None
    active = fetch_live_json('/liveclientdata/activeplayername', timeout=timeout)
    players = fetch_live_json('/liveclientdata/playerlist', timeout=timeout)
    return compute(players, active, costs)

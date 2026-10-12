"""Small HTTPS transport for public updates; no credentials or executable parsing."""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import time
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

HUYA_HOSTS = frozenset({'gametool.huya.com', 'huyafedltc.msstatic.com', 'fileserver.cdn.huya.com'})
GITHUB_HOSTS = frozenset({'api.github.com', 'github.com', 'release-assets.githubusercontent.com',
                          'objects.githubusercontent.com'})


class UpdateError(ValueError):
    """An update is unusable; the installed app/data must remain unchanged."""


def validate_url(url: str, hosts: frozenset[str]) -> str:
    if not isinstance(url, str) or len(url) > 8192 or any(ord(c) < 32 for c in url):
        raise UpdateError('Invalid update URL')
    try:
        parsed = urlsplit(url)
        if (parsed.scheme != 'https' or parsed.hostname not in hosts or parsed.username is not None
                or parsed.password is not None or parsed.port not in (None, 443) or parsed.fragment):
            raise UpdateError('Update URL is outside the HTTPS allowlist')
    except ValueError as exc:
        raise UpdateError('Invalid update URL') from exc
    return url


class SafeRedirects(HTTPRedirectHandler):
    max_redirections = 5
    max_repeats = 2

    def __init__(self, hosts):
        super().__init__()
        self.hosts = hosts

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_url(newurl, self.hosts)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_bytes(url: str, *, max_bytes: int, hosts=HUYA_HOSTS, timeout: float = 8,
                deadline: float | None = None) -> bytes:
    """Bounded, verified-TLS GET. Validate every redirect before following it."""
    validate_url(url, hosts)
    if deadline is not None:
        timeout = min(timeout, max(0.1, deadline - time.monotonic()))
        if time.monotonic() >= deadline:
            raise UpdateError('Update check timed out')
    req = Request(url, headers={'User-Agent': 'VGA-Aram-Helper/0.3 (public-data-updater)',
                                'Accept': 'application/json,text/html,application/javascript,*/*',
                                'Accept-Encoding': 'identity', 'Cache-Control': 'no-cache'})
    opener = build_opener(SafeRedirects(hosts), HTTPSHandler())
    with opener.open(req, timeout=timeout) as response:
        validate_url(response.geturl(), hosts)
        length = response.headers.get('Content-Length')
        if length is not None and (not length.isdecimal() or int(length) > max_bytes):
            raise UpdateError('Update response exceeds the size limit')
        chunks, total = [], 0
        while True:
            if deadline is not None and time.monotonic() > deadline:
                raise UpdateError('Update check timed out')
            chunk = response.read(min(65536, max_bytes + 1 - total))
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise UpdateError('Update response exceeds the size limit')
            chunks.append(chunk)
    return b''.join(chunks)


def strict_json(payload: bytes | str):
    def no_constant(_):
        raise UpdateError('Non-finite JSON values are not allowed')

    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise UpdateError('Duplicate JSON key')
            result[key] = value
        return result

    try:
        return json.loads(payload, parse_constant=no_constant, object_pairs_hook=unique_pairs)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise UpdateError('Invalid JSON update') from exc


def json_bytes(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True,
                      separators=(',', ':')).encode('utf-8')


def atomic_write(path: Path, payload: bytes):
    """Write and fsync next to the destination before atomic replacement."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name + '-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def runtime_state_dir() -> Path:
    if os.environ.get('VGA_STATE_DIR'):
        return Path(os.environ['VGA_STATE_DIR']).expanduser().resolve()
    if os.name == 'nt':
        return Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData' / 'Local')) / 'VGAAramHelper'
    return Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local' / 'share')) / 'VGAAramHelper'

"""Read Huya's public, anonymous wiki version metadata.

The official wiki invokes webLiveUI.getGameToolVersion using JCE/WUP. This
independent, minimal implementation performs that read only. It does not execute
remote JavaScript, use an account, copy cookies, or read stored credentials.
"""
from __future__ import annotations

import base64
import math
import hashlib
import re
import struct
import time
import urllib.parse
import urllib.request
import zlib

RPC_HOST = "cdnws.api.huya.com"
MAX_WIRE_BYTES = 256 * 1024
MAX_DECODED_BYTES = 1024 * 1024
MAX_CONTAINER_ITEMS = 4096
MAX_DEPTH = 16
MAX_FIELDS = 20000


class HuyaVersionError(ValueError):
    """An unavailable or invalid public version response."""


def _head(tag, kind):
    return bytes([(tag << 4) | kind]) if tag < 15 else bytes([240 | kind, tag])


def _integer(tag, value):
    if value == 0:
        return _head(tag, 12)
    for kind, fmt, minimum, maximum in (
        (0, "b", -128, 127), (1, "h", -32768, 32767),
        (2, "i", -(2 ** 31), 2 ** 31 - 1), (3, "q", -(2 ** 63), 2 ** 63 - 1),
    ):
        if minimum <= value <= maximum:
            return _head(tag, kind) + struct.pack(">" + fmt, value)
    raise HuyaVersionError("Integer outside JCE range")


def _string(tag, value):
    data = value.encode("utf-8")
    if len(data) < 256:
        return _head(tag, 6) + bytes([len(data)]) + data
    return _head(tag, 7) + struct.pack(">I", len(data)) + data


def _bytes(tag, value):
    return _head(tag, 13) + _head(0, 0) + _integer(0, len(value)) + value


def _struct(tag, value):
    return _head(tag, 10) + value + _head(0, 11)


def _map(tag, pairs):
    return _head(tag, 8) + _integer(0, len(pairs)) + b"".join(k + v for k, v in pairs)


class _Reader:
    """Strict, bounded decoder for the JCE types used by the public response."""
    def __init__(self, data):
        if not isinstance(data, bytes) or len(data) > MAX_DECODED_BYTES:
            raise HuyaVersionError("Invalid JCE input size")
        self.data, self.offset, self.fields = data, 0, 0

    def take(self, size):
        if size < 0 or size > MAX_DECODED_BYTES or self.offset + size > len(self.data):
            raise HuyaVersionError("Truncated or oversized JCE field")
        value = self.data[self.offset:self.offset + size]
        self.offset += size
        return value

    def count(self, depth, maximum=MAX_CONTAINER_ITEMS):
        tag, value, kind = self.field(depth)
        if tag != 0 or kind not in (0, 1, 2, 3, 12) or not isinstance(value, int) or not 0 <= value <= maximum:
            raise HuyaVersionError("Invalid JCE container count")
        return value

    def field(self, depth=0):
        self.fields += 1
        if depth > MAX_DEPTH or self.fields > MAX_FIELDS:
            raise HuyaVersionError("JCE nesting or field limit exceeded")
        first = self.take(1)[0]
        tag, kind = first >> 4, first & 15
        if tag == 15:
            tag = self.take(1)[0]
        if kind <= 5:
            fmt = ("b", "h", "i", "q", "f", "d")[kind]
            value = struct.unpack(">" + fmt, self.take(struct.calcsize(fmt)))[0]
            if isinstance(value, float) and not math.isfinite(value):
                raise HuyaVersionError("Non-finite JCE number")
        elif kind in (6, 7):
            size = self.take(1)[0] if kind == 6 else struct.unpack(">I", self.take(4))[0]
            value = self.take(size).decode("utf-8", errors="strict")
        elif kind == 8:
            value = {}
            for _ in range(self.count(depth + 1)):
                key_tag, key, _ = self.field(depth + 1)
                val_tag, item, _ = self.field(depth + 1)
                if key_tag != 0 or val_tag != 1 or not isinstance(key, (str, int)) or key in value:
                    raise HuyaVersionError("Invalid or duplicate JCE map key")
                value[key] = item
        elif kind == 9:
            value = []
            for _ in range(self.count(depth + 1)):
                child_tag, child, _ = self.field(depth + 1)
                if child_tag != 0:
                    raise HuyaVersionError("Invalid JCE list element")
                value.append(child)
        elif kind == 10:
            value = self.all(depth + 1, end_required=True)
        elif kind in (11, 12):
            value = 0
        elif kind == 13:
            if self.take(1) != b"\x00":
                raise HuyaVersionError("Unsupported JCE byte-list type")
            value = self.take(self.count(depth + 1, MAX_DECODED_BYTES))
        else:
            raise HuyaVersionError("Unsupported JCE field type")
        return tag, value, kind

    def all(self, depth=0, end_required=False):
        values = {}
        while self.offset < len(self.data):
            tag, value, kind = self.field(depth)
            if kind == 11:
                if not end_required or tag != 0:
                    raise HuyaVersionError("Unexpected JCE structure end")
                return values
            if tag in values:
                raise HuyaVersionError("Duplicate JCE field")
            values[tag] = value
        if end_required:
            raise HuyaVersionError("Missing JCE structure end")
        return values


def _validate_rpc_url(url):
    parsed = urllib.parse.urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname != RPC_HOST or parsed.username
            or parsed.password or parsed.port not in (None, 443) or parsed.fragment):
        raise HuyaVersionError("Untrusted public version endpoint")
    return url


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    max_redirections = 3
    max_repeats = 2

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _validate_rpc_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _remaining(timeout, deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("Public wiki version deadline exceeded")
    return min(timeout, remaining)


def _decode_response(wire, tool_id):
    if not isinstance(wire, bytes) or len(wire) > MAX_WIRE_BYTES:
        raise HuyaVersionError("Public wiki response too large")
    if wire.startswith(b"\x1f\x8b"):
        decompressor = zlib.decompressobj(16 + zlib.MAX_WBITS)
        body = decompressor.decompress(wire, MAX_DECODED_BYTES + 1)
        if (len(body) > MAX_DECODED_BYTES or decompressor.unconsumed_tail
                or not decompressor.eof or decompressor.unused_data):
            raise HuyaVersionError("Invalid or oversized compressed response")
    else:
        body = wire
    if len(body) < 5 or len(body) > MAX_DECODED_BYTES or struct.unpack(">I", body[:4])[0] != len(body):
        raise HuyaVersionError("Invalid WUP packet length")
    envelope = _Reader(body[4:]).all()
    if envelope.get(1) != 3 or envelope.get(5) != "webLiveUI" or envelope.get(6) != "getGameToolVersion":
        raise HuyaVersionError("Unexpected WUP response")
    attributes = _Reader(envelope.get(7)).all().get(0)
    if not isinstance(attributes, dict) or not isinstance(attributes.get("tRsp"), bytes):
        raise HuyaVersionError("Missing public wiki response payload")
    if "" in attributes and _Reader(attributes[""]).all().get(0) != 0:
        raise HuyaVersionError("Public wiki transport reported an error")
    result = _Reader(attributes["tRsp"]).all().get(0)
    if not isinstance(result, dict) or not isinstance(result.get(0), dict) or result[0].get(0) != 200:
        raise HuyaVersionError("Public wiki version service reported an error")
    if not isinstance(result.get(1), dict) or result[1].get(0) != tool_id:
        raise HuyaVersionError("Public wiki tool identity mismatch")
    version_info = result.get(2)
    if not isinstance(version_info, dict):
        raise HuyaVersionError("Missing public wiki version metadata")
    version, base = version_info.get(0), version_info.get(1)
    if not isinstance(version, str) or not re.fullmatch(r"[A-Za-z0-9._-]{1,80}", version) or version in (".", ".."):
        raise HuyaVersionError("Invalid public wiki version identifier")
    if not isinstance(base, str) or len(base) > 2048:
        raise HuyaVersionError("Invalid public wiki data URL")
    parsed = urllib.parse.urlsplit(base)
    if (parsed.scheme != "https" or parsed.hostname != "fileserver.cdn.huya.com"
            or parsed.username or parsed.password or parsed.port not in (None, 443)
            or parsed.query or parsed.fragment or not parsed.path.startswith("/game_tools/")
            or "%" in parsed.path or "\\" in parsed.path or ".." in parsed.path.split("/")):
        raise HuyaVersionError("Untrusted public wiki data URL")
    return {"version": version, "dataBaseUrl": base}


def fetch_wiki_version(tool_id, *, timeout=8, deadline=None):
    """Return current public wiki {'version', 'dataBaseUrl'} without authentication.

    deadline, when supplied, is an absolute time.monotonic() deadline. Both the
    request and response are bounded; network or validation errors propagate.
    """
    if not isinstance(tool_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", tool_id):
        raise HuyaVersionError("Invalid public tool identifier")
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
        raise HuyaVersionError("Invalid request timeout")
    if deadline is None:
        deadline = time.monotonic() + timeout
    if isinstance(deadline, bool) or not isinstance(deadline, (int, float)) or not math.isfinite(deadline):
        raise HuyaVersionError("Invalid request deadline")
    ua = "webh5&1.0.0&huya"
    anonymous = (_integer(0, 0) + _string(1, "") + _string(2, "") + _string(3, ua)
                 + _string(4, "") + _integer(5, 0) + _string(6, "") + _string(7, ""))
    request_data = _struct(0, _struct(0, anonymous) + _string(1, tool_id) + _string(2, ""))
    attributes = _map(0, [(_string(0, "tReq"), _bytes(1, request_data))])
    packet = (_integer(1, 3) + _integer(2, 0) + _integer(3, 0) + _integer(4, 1)
              + _string(5, "webLiveUI") + _string(6, "getGameToolVersion")
              + _bytes(7, attributes) + _integer(8, min(60000, max(1, int(timeout * 1000))))
              + _map(9, []) + _map(10, []))
    packet = struct.pack(">I", len(packet) + 4) + packet
    base = (_integer(0, 0) + _string(1, "") + _string(2, ua)
            + b"".join(_string(i, "") for i in (3, 4, 5)) + _integer(6, 0)
            + b"".join(_string(i, "") for i in (7, 8, 9)) + _map(10, []))
    query = urllib.parse.urlencode({"baseinfo": base64.b64encode(base).decode("ascii"), "timestamp": str(int(time.time() * 1000))})
    url = _validate_rpc_url("https://" + RPC_HOST + "/?" + query)
    request = urllib.request.Request(url, packet, method="POST", headers={
        "Content-Type": "application/octet-stream", "Accept-Encoding": "gzip",
        "Origin": "https://gametool.huya.com",
        "Referer": "https://gametool.huya.com/league-of-legends/wiki/index.html?embed=1",
    })
    opener = urllib.request.build_opener(_SafeRedirect())
    with opener.open(request, timeout=_remaining(timeout, deadline)) as response:
        _validate_rpc_url(response.geturl())
        if response.status != 200:
            raise HuyaVersionError("Unexpected public wiki HTTP status")
        length = response.headers.get("Content-Length")
        if length and (not length.isdigit() or int(length) > MAX_WIRE_BYTES):
            raise HuyaVersionError("Invalid public wiki response length")
        chunks, total = [], 0
        while True:
            _remaining(timeout, deadline)
            chunk = response.read(min(65536, MAX_WIRE_BYTES + 1 - total))
            total += len(chunk)
            if total > MAX_WIRE_BYTES:
                raise HuyaVersionError("Public wiki response too large")
            if not chunk:
                break
            chunks.append(chunk)
        _remaining(timeout, deadline)
    wire = b"".join(chunks)
    result = _decode_response(wire, tool_id)
    result.update({"sourceUrl": "https://" + RPC_HOST + "/", "responseSha256": hashlib.sha256(wire).hexdigest()})
    return result

"""Independent synthetic protocol tests; no official dataset or network required."""
import gzip
import io
import pathlib
import struct
import sys
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import huya_rpc as h


def response(tool="p81hl812", version="395", base="https://fileserver.cdn.huya.com/game_tools/test/", status=200, transport=0):
    result = h._struct(0,
        h._struct(0, h._integer(0, status) + h._string(1, "success"))
        + h._struct(1, h._string(0, tool))
        + h._struct(2, h._string(0, version) + h._string(1, base)))
    attrs = h._map(0, [(h._string(0, ""), h._bytes(1, h._integer(0, transport))),
                       (h._string(0, "tRsp"), h._bytes(1, result))])
    packet = (h._integer(1, 3) + h._integer(2, 0) + h._integer(3, 0) + h._integer(4, 1)
              + h._string(5, "webLiveUI") + h._string(6, "getGameToolVersion")
              + h._bytes(7, attrs) + h._integer(8, 0) + h._map(9, []) + h._map(10, []))
    return struct.pack(">I", len(packet) + 4) + packet


class FakeResponse(io.BytesIO):
    status = 200
    headers = {}
    def geturl(self):
        return "https://cdnws.api.huya.com/"


class HuyaRpcTests(unittest.TestCase):
    def test_plain_and_gzip_response(self):
        plain = response()
        for wire in (plain, gzip.compress(plain)):
            self.assertEqual(h._decode_response(wire, "p81hl812"), {
                "version": "395", "dataBaseUrl": "https://fileserver.cdn.huya.com/game_tools/test/"})

    def test_corrupt_or_truncated_packet(self):
        for wire in (b"", b"\x00\x00\x00\x05\xff", response()[:-1], gzip.compress(response())[:20]):
            with self.subTest(wire=wire[:10]):
                with self.assertRaises((ValueError, UnicodeDecodeError)):
                    h._decode_response(wire, "p81hl812")

    def test_remote_error_identity_and_urls(self):
        invalid = [dict(status=403), dict(transport=-1), dict(tool="wrong"),
                   dict(version="../x"), dict(base="http://fileserver.cdn.huya.com/game_tools/test/"),
                   dict(base="https://fileserver.cdn.huya.com.evil.test/game_tools/"),
                   dict(base="https://u@fileserver.cdn.huya.com/game_tools/"),
                   dict(base="https://fileserver.cdn.huya.com/game_tools/%2e%2e/"),
                   dict(base="https://fileserver.cdn.huya.com/game_tools/test/?token=x")]
        for kwargs in invalid:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                h._decode_response(response(**kwargs), "p81hl812")

    def test_response_size_and_gzip_bomb(self):
        for wire in (b"x" * (h.MAX_WIRE_BYTES + 1), gzip.compress(b"x" * (h.MAX_DECODED_BYTES + 1))):
            with self.assertRaises(ValueError):
                h._decode_response(wire, "p81hl812")

    def test_duplicate_truncated_and_deep_fields(self):
        deep = h._integer(0, 1)
        for _ in range(h.MAX_DEPTH + 2):
            deep = h._struct(0, deep)
        for data in (deep, h._integer(0, 1) * 2, h._head(0, 10),
                     h._head(0, 8) + h._integer(0, h.MAX_CONTAINER_ITEMS + 1),
                     h._head(0, 7) + struct.pack(">I", h.MAX_DECODED_BYTES + 1)):
            with self.assertRaises(ValueError):
                h._Reader(data).all()

    def test_endpoint_and_redirect_allowlist(self):
        self.assertEqual(h._validate_rpc_url("https://cdnws.api.huya.com/"), "https://cdnws.api.huya.com/")
        for url in ("http://cdnws.api.huya.com/", "https://cdnws.api.huya.com.evil.test/",
                    "https://u@cdnws.api.huya.com/", "https://cdnws.api.huya.com:444/"):
            with self.assertRaises(ValueError):
                h._validate_rpc_url(url)
        with self.assertRaises(ValueError):
            h._SafeRedirect().redirect_request(None, None, 302, "", {}, "https://evil.test/")

    def test_invalid_arguments_and_expired_deadline(self):
        for tool in ("", "../x", "a" * 65, None):
            with self.assertRaises(ValueError):
                h.fetch_wiki_version(tool)
        for timeout in (0, -1, True, float("inf"), float("nan")):
            with self.assertRaises(ValueError):
                h.fetch_wiki_version("p81hl812", timeout=timeout)
        with self.assertRaises(TimeoutError):
            h.fetch_wiki_version("p81hl812", deadline=time.monotonic() - 1)

    def test_request_is_anonymous_and_read_only(self):
        captured = {}
        wire = gzip.compress(response())
        class Opener:
            def open(self, req, timeout):
                captured.update(request=req, timeout=timeout)
                return FakeResponse(wire)
        with patch.object(h.urllib.request, "build_opener", return_value=Opener()):
            result = h.fetch_wiki_version("p81hl812", timeout=5)
        req = captured["request"]
        self.assertEqual(req.get_method(), "POST")
        self.assertNotIn("Cookie", req.headers)
        self.assertNotIn("Authorization", req.headers)
        env = h._Reader(req.data[4:]).all()
        self.assertEqual((env[5], env[6]), ("webLiveUI", "getGameToolVersion"))
        attrs = h._Reader(env[7]).all()[0]
        payload = h._Reader(attrs["tReq"]).all()[0]
        self.assertEqual(payload[1], "p81hl812")
        self.assertEqual(payload[2], "")
        self.assertEqual(payload[0][0], 0)
        for field in (1, 2, 4, 6, 7):
            self.assertEqual(payload[0][field], "")
        self.assertEqual(result["version"], "395")
        self.assertEqual(len(result["responseSha256"]), 64)
        self.assertEqual(result["sourceUrl"], "https://cdnws.api.huya.com/")

    def test_oversized_content_length(self):
        class HugeResponse(FakeResponse):
            headers = {"Content-Length": str(h.MAX_WIRE_BYTES + 1)}
        class Opener:
            def open(self, req, timeout):
                return HugeResponse(b"")
        with patch.object(h.urllib.request, "build_opener", return_value=Opener()), self.assertRaises(ValueError):
            h.fetch_wiki_version("p81hl812")


if __name__ == "__main__":
    unittest.main()

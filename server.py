#!/usr/bin/env python3
"""Read-only localhost helper. Python 3.10+, standard library only."""
import argparse
import base64
import binascii
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from engine import load_data, recommend

APP_NAME = "VGA乱斗助手"
APP_VERSION = "0.2"
ROOT = Path(__file__).resolve().parent
STATIC = {"/": ("index.html", "text/html; charset=utf-8"), "/app.js": ("app.js", "text/javascript; charset=utf-8"),
          "/style.css": ("style.css", "text/css; charset=utf-8"), "/ocr-ui.js": ("ocr-ui.js", "text/javascript; charset=utf-8")}


def make_server(data, port=8765, enable_ocr=False, ocr_engine=None):
    if enable_ocr and ocr_engine is None:
        from local_ocr import LocalOCR
        ocr_engine=LocalOCR()
    class Handler(BaseHTTPRequestHandler):
        def send_bytes(self, status, body, content_type):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)

        def send_json(self, status, value):
            self.send_bytes(status, json.dumps(value, ensure_ascii=False, allow_nan=False).encode(), "application/json; charset=utf-8")

        def do_GET(self):
            host = self.headers.get("Host", "").partition(":")[0]
            if host not in {"127.0.0.1", "localhost"}:
                return self.send_json(403, {"error": "仅允许 localhost 访问"})
            request = urlsplit(self.path)
            if request.path == "/api/data":
                return self.send_json(200, data)
            if request.path == "/api/recommend":
                name = parse_qs(request.query).get("augment", [""])[0]
                try:
                    return self.send_json(200, recommend(data, name))
                except KeyError:
                    return self.send_json(404, {"error": "未找到海克斯"})
            if request.path == "/health":
                return self.send_json(200, {"applicationName": APP_NAME, "applicationVersion": APP_VERSION, "status": "ok", "mode": "manual-reference", "externalRequests": False, "ocr_enabled": enable_ocr})
            if request.path in STATIC:
                filename, content_type = STATIC[request.path]
                return self.send_bytes(200, (ROOT / "static" / filename).read_bytes(), content_type)
            self.send_json(404, {"error": "未找到页面"})

        def do_POST(self):
            host=self.headers.get("Host", "").partition(":")[0]
            if host not in {"127.0.0.1", "localhost"}:
                return self.send_json(403, {"error":"仅允许 localhost 访问"})
            origin=self.headers.get("Origin")
            allowed={f"http://127.0.0.1:{self.server.server_port}",f"http://localhost:{self.server.server_port}"}
            if origin is not None and origin not in allowed:
                return self.send_json(403,{"error":"拒绝跨站截图请求"})
            if urlsplit(self.path).path!="/api/ocr":
                return self.send_json(404,{"error":"未找到页面"})
            if not enable_ocr:
                return self.send_json(503,{"error":"OCR 尚未启用；请安装可选依赖并以 --enable-ocr 启动。"})
            if self.headers.get("Content-Type","").split(";")[0]!="application/json":
                return self.send_json(415,{"error":"仅接受 JSON 图片请求"})
            try:
                length=int(self.headers.get("Content-Length","0"))
                if length<=0 or length>12*1024*1024:
                    return self.send_json(413,{"error":"请求大小无效，图片上限 8 MiB。"})
                self.connection.settimeout(15)
                payload=json.loads(self.rfile.read(length))
                if not isinstance(payload,dict) or not isinstance(payload.get("image_base64"),str):
                    raise ValueError("缺少图片数据")
                image_bytes=base64.b64decode(payload["image_base64"],validate=True)
                result=ocr_engine.recognize(image_bytes,data["augments"].keys())
                return self.send_json(200,result)
            except (ValueError,binascii.Error) as exc:
                return self.send_json(400,{"error":str(exc)})
            except RuntimeError as exc:
                return self.send_json(503,{"error":str(exc)})
            except (OSError,TimeoutError):
                return self.send_json(400,{"error":"无法完整读取图片请求。"})
            except Exception:
                return self.send_json(500,{"error":"本地 OCR 运行失败，请在终端运行截图命令检查。"})

        def log_message(self, fmt, *args):
            pass
    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def main():
    parser = argparse.ArgumentParser(description="VGA乱斗助手：独立本地参考原型")
    parser.add_argument("--data", type=Path, default=ROOT / "fixtures" / "demo.json", help="自有或获授权的规范化 JSON 数据；默认使用虚构演示")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--enable-ocr", action="store_true", help="启用可选本地截图 OCR；不上传图片")
    args = parser.parse_args()
    try:
        data = load_data(args.data)
        server = make_server(data, args.port, enable_ocr=args.enable_ocr)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"启动失败：{exc}\n")
    print(f"VGA乱斗助手已启动：http://127.0.0.1:{server.server_port}\n数据：{args.data}\n仅本机访问；按 Ctrl+C 退出。", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

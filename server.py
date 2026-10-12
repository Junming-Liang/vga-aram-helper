#!/usr/bin/env python3
"""Loopback API for official hero comparisons, local OCR and update controls."""
import argparse
import base64
import binascii
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
from urllib.parse import parse_qs, urlsplit
from engine import load_data, normalize, recommend
from core import compare_augments
from app_version import __version__ as APP_VERSION

APP_NAME='VGA乱斗助手'
ROOT=Path(__file__).resolve().parent
STATIC={'/':('static/index.html','text/html; charset=utf-8'),'/app.js':('static/app.js','text/javascript; charset=utf-8'),
        '/choices.js':('static/choices.js','text/javascript; charset=utf-8'),'/style.css':('static/style.css','text/css; charset=utf-8'),
        '/ocr-ui.js':('static/ocr-ui.js','text/javascript; charset=utf-8'),'/favicon.ico':('assets/branding/vga.ico','image/x-icon'),
        '/brand.png':('assets/branding/vga-icon-512.png','image/png')}


def load_startup_data(cache_dir, demo=False):
    if demo:
        return {'data':load_data(ROOT/'fixtures/demo.json'),'status':{'state':'demo','message':'明确启用的虚构演示模式，不用于真实对局。','usingCached':False}}
    from data_updates import refresh_official_data
    result=refresh_official_data(Path(cache_dir))
    raw=result.get('data')
    status=result.get('status',{})
    if raw is None:
        raw={'metadata':{'isDemo':False,'title':'官方数据不可用','dataFreshness':'unavailable'},'heroes':{},'augments':{},'items':{}}
    data=normalize(raw)
    data['metadata']['updateStatus']=status
    data['metadata']['applicationName']=APP_NAME
    data['metadata']['applicationVersion']=APP_VERSION
    return {'data':data,'status':status}


def make_server(data, port=8765, enable_ocr=False, ocr_engine=None, data_status=None, update_context=None):
    if enable_ocr and ocr_engine is None:
        from local_ocr import LocalOCR
        ocr_engine=LocalOCR()
    data_status=data_status or {'state':'demo' if data.get('metadata',{}).get('isDemo') else 'local','message':'显式本地数据；未自动验证版本。','usingCached':False}
    software={'state':'checking' if update_context else 'disabled','message':'正在检查软件版本。' if update_context else '此启动方式未启用软件 OTA。'}
    lock=threading.Lock()
    def public_software():
        with lock:
            value={key:software.get(key) for key in ['state','message']}
            release=software.get('release')
            if isinstance(release,dict):
                value['release']={key:release.get(key) for key in ['version','notes','url']}
            value['canInstall']=bool(update_context and update_context.get('frozen') and software.get('state')=='available')
            return value
    class Handler(BaseHTTPRequestHandler):
        def send_bytes(self,status,body,content_type):
            self.send_response(status)
            for key,value in {'Content-Type':content_type,'Content-Length':str(len(body)),'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','X-Frame-Options':'DENY','Referrer-Policy':'no-referrer','Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"}.items():self.send_header(key,value)
            self.end_headers();self.wfile.write(body)
        def send_json(self,status,value):self.send_bytes(status,json.dumps(value,ensure_ascii=False,allow_nan=False).encode(),'application/json; charset=utf-8')
        def valid_host(self):return self.headers.get('Host','').partition(':')[0] in {'127.0.0.1','localhost'}
        def do_GET(self):
            if not self.valid_host():return self.send_json(403,{'error':'仅允许 localhost 访问'})
            request=urlsplit(self.path)
            if request.path=='/api/data':return self.send_json(200,data)
            if request.path=='/api/status':return self.send_json(200,{'data':data_status,'software':public_software(),'applicationVersion':APP_VERSION})
            if request.path=='/api/updates':return self.send_json(200,public_software())
            if request.path=='/api/recommend':
                name=parse_qs(request.query).get('augment',[''])[0]
                try:return self.send_json(200,recommend(data,name))
                except KeyError:return self.send_json(404,{'error':'未找到海克斯'})
            if request.path=='/health':return self.send_json(200,{'applicationName':APP_NAME,'applicationVersion':APP_VERSION,'status':'ok','mode':'hero-three-augment-comparison','ocr_enabled':enable_ocr,'dataState':data_status.get('state'),'softwareUpdateState':public_software()['state']})
            if request.path in STATIC:
                filename,kind=STATIC[request.path]
                try:return self.send_bytes(200,(ROOT/filename).read_bytes(),kind)
                except OSError:return self.send_json(404,{'error':'资源缺失'})
            return self.send_json(404,{'error':'未找到页面'})
        def do_POST(self):
            if not self.valid_host():return self.send_json(403,{'error':'仅允许 localhost 访问'})
            origin=self.headers.get('Origin')
            if origin is not None and origin not in {f'http://127.0.0.1:{self.server.server_port}',f'http://localhost:{self.server.server_port}'}:
                return self.send_json(403,{'error':'拒绝跨站请求'})
            path=urlsplit(self.path).path
            if path not in {'/api/ocr','/api/compare','/api/updates/install'}:return self.send_json(404,{'error':'未找到页面'})
            if path=='/api/ocr' and not enable_ocr:return self.send_json(503,{'error':'此构建未启用 OCR。请使用包含模型的正式 Windows EXE，或开发环境安装可选依赖。'})
            if self.headers.get('Content-Type','').split(';')[0]!='application/json':return self.send_json(415,{'error':'仅接受 JSON 请求'})
            try:
                length=int(self.headers.get('Content-Length','0'))
                maximum=12*1024*1024 if path=='/api/ocr' else 64*1024
                if length<=0 or length>maximum:return self.send_json(413,{'error':'请求大小无效；图片上限 8 MiB，普通请求上限 64 KiB。'})
                self.connection.settimeout(20)
                payload=json.loads(self.rfile.read(length))
                if not isinstance(payload,dict):raise ValueError('请求应为 JSON 对象。')
                if path=='/api/compare':return self.send_json(200,compare_augments(data,payload.get('hero'),payload.get('offered')))
                if path=='/api/ocr':
                    if not isinstance(payload.get('image_base64'),str):raise ValueError('缺少图片数据')
                    image_bytes=base64.b64decode(payload['image_base64'],validate=True)
                    return self.send_json(200,ocr_engine.recognize(image_bytes,data['augments'].keys()))
                if not update_context or not update_context.get('frozen'):return self.send_json(409,{'error':'只有正式 Windows EXE 支持应用内安装更新。'})
                if payload.get('confirmed') is not True:return self.send_json(400,{'error':'需先确认安装版本及重启。'})
                with lock:
                    release=software.get('release')
                    if software.get('state')!='available' or not isinstance(release,dict) or payload.get('version')!=release.get('version'):
                        return self.send_json(409,{'error':'版本已变化，请重新查看更新信息。'})
                    software.update(state='preparing',message='正在校验并准备软件更新。')
                try:
                    from updates import prepare_update,launch_update
                    plan=prepare_update(release,Path(update_context['current_executable']),Path(update_context['state_dir']),confirmed=True)
                    launch_update(plan)
                except Exception as exc:
                    with lock:software.update(state='available',message='准备更新失败，原程序保持不变：'+str(exc))
                    return self.send_json(503,{'error':public_software()['message']})
                try:
                    self.send_json(200,{'state':'restarting','message':'更新已校验，程序即将关闭并由更新器重启。'})
                except OSError:
                    pass  # Closing the browser cannot cancel an already spawned updater.
                finally:
                    threading.Thread(target=self.server.shutdown,daemon=True).start()
            except (ValueError,binascii.Error) as exc:return self.send_json(400,{'error':str(exc)})
            except RuntimeError as exc:return self.send_json(503,{'error':str(exc)})
            except (OSError,TimeoutError):return self.send_json(400,{'error':'无法完整读取请求。'})
            except Exception:return self.send_json(500,{'error':'处理失败，请查看本地日志。'})
        def log_message(self,fmt,*args):pass
    server=ThreadingHTTPServer(('127.0.0.1',port),Handler)
    if update_context:
        def check():
            try:
                from updates import check_for_update
                result=check_for_update(update_context.get('current_version',APP_VERSION))
            except Exception as exc:result={'state':'unavailable','message':'软件更新检查失败：'+str(exc)}
            with lock:software.clear();software.update(result)
        threading.Thread(target=check,name='vga-software-update-check',daemon=True).start()
    return server


def main():
    parser=argparse.ArgumentParser(description='VGA乱斗助手：英雄 + 三个海克斯比较')
    parser.add_argument('--data',type=Path,help='显式本地开发数据；不替代正式启动时的官方刷新')
    parser.add_argument('--demo',action='store_true',help='仅使用虚构演示数据')
    parser.add_argument('--port',type=int,default=8765)
    parser.add_argument('--enable-ocr',action='store_true')
    args=parser.parse_args()
    try:
        if args.data:startup={'data':load_data(args.data),'status':{'state':'local','message':'显式本地数据模式','usingCached':False}}
        else:
            from updates import runtime_state_dir
            startup=load_startup_data(runtime_state_dir()/'data',demo=args.demo)
        server=make_server(startup['data'],args.port,enable_ocr=args.enable_ocr,data_status=startup['status'])
    except (OSError,ValueError,RuntimeError) as exc:parser.exit(1,f'启动失败：{exc}\n')
    print(f'{APP_NAME} {APP_VERSION} 已启动：http://127.0.0.1:{server.server_port}\n仅本机访问；按 Ctrl+C 退出。',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()

if __name__=='__main__':main()

"""Verified-TLS public Riot Data Dragon portrait cache; no screenshot upload.

Assets remain Riot-owned and are downloaded to the user's local cache, not
redistributed with this source package. A complete roster is required so a
partial dictionary cannot create misleading runner-up confidence margins.
"""
from __future__ import annotations
import hashlib
import io
import os
from pathlib import Path
import re
import tempfile
import threading
import time
import weakref
from concurrent.futures import ThreadPoolExecutor
from update_network import fetch_bytes, strict_json, json_bytes, UpdateError

HOSTS=frozenset({'ddragon.leagueoflegends.com'})
BASE='https://ddragon.leagueoflegends.com'
VERSION_URL=BASE+'/api/versions.json'
MAX_PORTRAITS=400
# Only writers of the exact same resolved path contend. Hash stripes can make
# an unrelated image's slow fsync exhaust another image's bounded lock wait.
# Weak entries disappear after their last active/waiting writer drops its
# strong reference, so old versions/paths do not accumulate in a running app.
_CACHE_LOCKS=weakref.WeakValueDictionary()
_CACHE_REGISTRY_LOCK=threading.Lock()
_CACHE_RETRY_DELAYS=(0.05,0.15,0.3)
_CACHE_LOCK_TIMEOUT=0.5


def _cache_lock(path):
    key=os.path.normcase(str(Path(path).resolve()))
    with _CACHE_REGISTRY_LOCK:
        lock=_CACHE_LOCKS.get(key)
        if lock is None:
            lock=threading.Lock();_CACHE_LOCKS[key]=lock
        return lock


def _check_active(cancelled,deadline):
    if cancelled.is_set():raise UpdateError('Portrait loading cancelled')
    if time.monotonic()>=deadline:raise UpdateError('Portrait loading timed out')


def _write_cache(path,payload,*,cancelled,deadline):
    """Best-effort persistence; callers may use verified images without a cache.

    Never delete/modify an existing destination to bypass a sharing lock. Only
    Windows access/sharing/lock errors from replacement get a short retry; disk
    space, directory permissions and other failures return to the caller.
    """
    path=Path(path)
    from portrait_cache_diagnostics import capture_failure,error_codes
    lock=_cache_lock(path)
    lock_deadline=min(deadline,time.monotonic()+_CACHE_LOCK_TIMEOUT)
    while True:
        _check_active(cancelled,deadline)
        remaining=lock_deadline-time.monotonic()
        if remaining<=0:
            error=OSError('Portrait cache is busy')
            error.cache_diagnostic=capture_failure(path,None,'acquire-lock',error,
                                                  temp_created=False,temp_flushed=False,temp_closed=False)
            raise error
        if lock.acquire(timeout=min(0.05,remaining)):break
    temporary=None;stage='inspect-existing';diagnostic=None
    temp_created=False;temp_flushed=False;temp_closed=False
    def record(error):
        nonlocal diagnostic
        if diagnostic is None:
            diagnostic=capture_failure(path,temporary,stage,error,temp_created=temp_created,
                                       temp_flushed=temp_flushed,temp_closed=temp_closed)
        diagnostic['attemptErrors'].append({'stage':stage,**error_codes(error)})
        return diagnostic
    try:
        _check_active(cancelled,deadline)
        # Concurrent loads, interrupted downloads and another app instance may
        # already have written these exact verified bytes. Do not replace them.
        try:
            with path.open('rb') as handle:
                if handle.read(len(payload)+1)==payload:return
        except OSError:pass
        stage='create-directory'
        path.parent.mkdir(parents=True,exist_ok=True)
        stage='create-temp'
        fd,temporary=tempfile.mkstemp(prefix='.'+path.name+'-',dir=path.parent)
        temp_created=True;stage='write-temp'
        handle=None
        try:
            with os.fdopen(fd,'wb') as handle:
                handle.write(payload);stage='flush-temp';handle.flush();os.fsync(handle.fileno());temp_flushed=True
        finally:temp_closed=handle is not None and handle.closed
        stage='replace'
        # The temp handle MUST be closed before replacement on Windows.
        for attempt in range(len(_CACHE_RETRY_DELAYS)+1):
            _check_active(cancelled,deadline)
            try:
                os.replace(temporary,path)
                if diagnostic is not None:diagnostic['outcome']='recovered-after-retry'
                return diagnostic
            except OSError as exc:
                record(exc)
                if getattr(exc,'winerror',None) not in (5,32,33) or attempt==len(_CACHE_RETRY_DELAYS):raise
                cancelled.wait(min(_CACHE_RETRY_DELAYS[attempt],max(0,deadline-time.monotonic())))
    except OSError as exc:
        if diagnostic is None:record(exc)
        exc.cache_diagnostic=diagnostic
        raise
    finally:
        try:
            if temporary is not None:
                try:os.unlink(temporary)
                except FileNotFoundError:pass
                except OSError as exc:
                    if diagnostic is not None:diagnostic['cleanupError']=error_codes(exc)
                    # Never mask the write result or touch unrelated files.
        finally:lock.release()


def decode_portrait(payload):
    from PIL import Image
    if not isinstance(payload,bytes) or not 0<len(payload)<=1024*1024:raise ValueError('Invalid portrait bytes')
    with Image.open(io.BytesIO(payload)) as image:
        if image.format!='PNG' or image.width!=image.height or not 64<=image.width<=512:raise ValueError('Invalid portrait image')
        image.load();return image.convert('RGB').copy()


def parse_roster(payload,version):
    source=strict_json(payload)
    if not isinstance(source,dict) or source.get('version')!=version or not isinstance(source.get('data'),dict):raise ValueError('Invalid official portrait roster')
    records=[];ids=set()
    for row in source['data'].values():
        if not isinstance(row,dict):raise ValueError('Invalid champion')
        key=row.get('key');slug=row.get('id');name=row.get('image',{}).get('full')
        if not isinstance(key,str) or not re.fullmatch(r'[0-9]{1,6}',key) or key in ids or not isinstance(slug,str) or not re.fullmatch(r'[A-Za-z0-9]{1,60}',slug) or name!=slug+'.png':raise ValueError('Invalid champion portrait ID')
        ids.add(key);records.append({'championId':key,'asset':name,'url':f'{BASE}/cdn/{version}/img/champion/{name}'})
    if not 100<=len(records)<=MAX_PORTRAITS:raise ValueError('Incomplete official roster')
    return records


def load_portraits(cache_dir, *, allow_download=True, fetcher=None, cancelled=None):
    """Return complete decoded bank + provenance/status; no dependency installs."""
    cache=Path(cache_dir);fetcher=fetcher or fetch_bytes;deadline=time.monotonic()+150
    cancelled=cancelled or threading.Event()
    cache_diagnostics=[];diagnostic_lock=threading.Lock()
    def diagnostic_status(status):
        if not cache_diagnostics:return status
        from portrait_cache_diagnostics import report,save_report
        details=report(cache_diagnostics)
        saved=save_report(cache,details)
        return {**status,'cacheDiagnostics':details,'cacheDiagnosticSaved':saved,
                'message':status['message']+'；可点击“头像缓存诊断”查看本地错误详情。'}
    def fetch(url,limit):
        _check_active(cancelled,deadline)
        return fetcher(url,max_bytes=limit,hosts=HOSTS,timeout=8,deadline=deadline)
    def cached():
        raw=(cache/'manifest.json').read_bytes()
        if len(raw)>256*1024:raise ValueError('Portrait manifest too large')
        manifest=strict_json(raw);version=manifest.get('version')
        if not isinstance(version,str) or not re.fullmatch(r'\d{1,3}\.\d{1,3}\.\d{1,3}',version):raise ValueError('Invalid cached version')
        roster=(cache/f'roster-{version}.json').read_bytes()
        if hashlib.sha256(roster).hexdigest()!=manifest.get('rosterSha256'):raise ValueError('Invalid cached roster hash')
        records=parse_roster(roster,version);hashes=manifest.get('hashes',{})
        bank={}
        for record in records:
            payload=(cache/version/record['asset']).read_bytes()
            if hashlib.sha256(payload).hexdigest()!=hashes.get(record['asset']):raise ValueError('Invalid cached portrait hash')
            bank[record['championId']]=decode_portrait(payload)
        return bank,{'state':'cached','version':version,'source':VERSION_URL,'count':len(bank),'message':f'本人头像模板 {version}（完整本地缓存，{len(bank)} 英雄）'}
    try:bank,status=cached()
    except (OSError,ValueError,KeyError,TypeError):bank=None;status=None
    if not allow_download:
        return (bank,status) if bank is not None else ({},{'state':'unavailable','message':'完整头像模板缓存不可用，自动英雄识别暂停；可人工纠正。'})
    try:
        versions=strict_json(fetch(VERSION_URL,64*1024))
        if not isinstance(versions,list) or not versions or not isinstance(versions[0],str) or not re.fullmatch(r'\d{1,3}\.\d{1,3}\.\d{1,3}',versions[0]):raise ValueError('Invalid official version list')
        version=versions[0]
        if bank is not None and status['version']==version:return bank,{**status,'state':'current','message':status['message']+'；已检查官方版本'}
        roster_url=f'{BASE}/cdn/{version}/data/en_US/champion.json';roster=fetch(roster_url,2*1024*1024);records=parse_roster(roster,version)
        cache_failed=threading.Event()
        def persist(path,payload):
            _check_active(cancelled,deadline)
            if cache_failed.is_set():return
            diagnostic=None
            try:diagnostic=_write_cache(path,payload,cancelled=cancelled,deadline=deadline)
            except OSError as exc:
                cache_failed.set();diagnostic=getattr(exc,'cache_diagnostic',None)
            if diagnostic is not None:
                from portrait_cache_diagnostics import retain_failure
                with diagnostic_lock:
                    retain_failure(cache_diagnostics,diagnostic)
        def download(record):
            payload=fetch(record['url'],1024*1024);image=decode_portrait(payload)
            persist(cache/version/record['asset'],payload)
            return record,hashlib.sha256(payload).hexdigest(),image
        with ThreadPoolExecutor(max_workers=6,thread_name_prefix='vga-public-portrait') as pool:results=list(pool.map(download,records))
        fresh_bank={};hashes={}
        for record,sha,image in results:fresh_bank[record['championId']]=image;hashes[record['asset']]=sha
        manifest={'version':version,'rosterUrl':roster_url,'rosterSha256':hashlib.sha256(roster).hexdigest(),'hashes':hashes,'source':VERSION_URL,'fetchedAt':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'rights':'Riot-owned Data Dragon assets; local recognition cache only; no game screenshots transmitted.'}
        persist(cache/f'roster-{version}.json',roster);persist(cache/'manifest.json',json_bytes(manifest))
        _check_active(cancelled,deadline)
        message=f'本人头像模板 {version}（Riot Data Dragon，{len(fresh_bank)} 英雄）'
        if cache_failed.is_set():
            message+='；本地缓存写入失败，本次仍可自动识别，下次启动可能需重新下载。请关闭其他助手实例后重试，并检查缓存目录是否可写。'
        return fresh_bank,diagnostic_status({'state':'memory-only' if cache_failed.is_set() else 'fresh','version':version,'source':VERSION_URL,'count':len(fresh_bank),'message':message})
    except Exception as exc:
        if bank is not None and not cancelled.is_set():return bank,diagnostic_status({**status,'message':status['message']+'；网络更新失败，头像版本可能较旧'})
        return {},diagnostic_status({'state':'unavailable','message':'自动英雄模板不可用：'+str(exc)+'；不会猜测英雄，可人工纠正。'})

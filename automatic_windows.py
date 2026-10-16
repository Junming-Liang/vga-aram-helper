"""Opt-in discovery of a unique, publisher-verified League installation.

Reads only public window/process/file metadata. Never reads process memory.
Discovery grants no pixel access until the GUI adopts and revalidates its result.
"""
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
import base64
import ctypes
from ctypes import wintypes as W
import uuid
import json
import os
import subprocess
import time

from session_windows import ProcessMetadata, normalized_path, process_metadata

CLIENT_CLASSES=frozenset({'RCLIENT','Chrome_WidgetWin_1','CEFCLIENT'})
PUBLISHERS=frozenset({'riot games, inc.','riot games, inc','riot games inc.',
    'tencent technology (shenzhen) company limited','tencent technology(shenzhen) company limited',
    'tencent technology (shenzhen) company ltd.','tencent technologyshenzhen company limited'})


def verify_authenticode_offline(path):
    """WinVerifyTrust with no UI and no network retrieval (Microsoft SDK flags)."""
    class GUID(ctypes.Structure):
        _fields_=[('data',ctypes.c_ubyte*16)]
    class FILE(ctypes.Structure):
        _fields_=[('size',W.DWORD),('path',W.LPCWSTR),('handle',W.HANDLE),('subject',ctypes.c_void_p)]
    class TRUST(ctypes.Structure):
        _fields_=[('size',W.DWORD),('policy',ctypes.c_void_p),('sip',ctypes.c_void_p),('ui',W.DWORD),('revocation',W.DWORD),('choice',W.DWORD),('file',ctypes.POINTER(FILE)),('action',W.DWORD),('state',W.HANDLE),('url',W.LPCWSTR),('flags',W.DWORD),('context',W.DWORD),('settings',ctypes.c_void_p)]
    action=GUID((ctypes.c_ubyte*16).from_buffer_copy(uuid.UUID('00AAC56B-CD44-11D0-8CC2-00C04FC295EE').bytes_le))
    file=FILE(ctypes.sizeof(FILE),str(path),None,None)
    trust=TRUST();trust.size=ctypes.sizeof(TRUST);trust.ui=2;trust.choice=1;trust.file=ctypes.pointer(file);trust.action=1
    # CACHE_ONLY_URL_RETRIEVAL + REVOCATION_CHECK_NONE + DISABLE_MD2_MD4.
    # Trust uses the installed local chain; this does not assert fresh revocation.
    trust.flags=0x1000|0x10|0x2000
    dll=ctypes.WinDLL('wintrust',use_last_error=True);fn=dll.WinVerifyTrust
    fn.argtypes=[W.HWND,ctypes.POINTER(GUID),ctypes.POINTER(TRUST)];fn.restype=ctypes.c_long
    try:return fn(W.HWND(-1),ctypes.byref(action),ctypes.byref(trust))==0
    finally:
        trust.action=2;fn(W.HWND(-1),ctypes.byref(action),ctypes.byref(trust))


class PublisherVerifier:
    """Windows verifies the Authenticode chain; cache only unchanged local files.

    Runs on the discovery worker, never on the GUI thread. No shell expansion or
    path interpolation into PowerShell source. A failed check is retried later.
    """
    def __init__(self):self.cache={}
    def __call__(self,path):
        if os.name!='nt':return False
        try:
            stat=Path(path).stat();key=(normalized_path(path),stat.st_size,stat.st_mtime_ns,stat.st_ino)
            saved=self.cache.get(key)
            if saved and (saved[0] or time.monotonic()-saved[1]<30):return saved[0]
            if not verify_authenticode_offline(path):
                self.cache[key]=(False,time.monotonic());return False
            script="[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new(); $c=[System.Security.Cryptography.X509Certificates.X509Certificate2]::new([System.Security.Cryptography.X509Certificates.X509Certificate]::CreateFromSignedFile($env:VGA_VERIFY_IMAGE_PATH)); $n=$c.GetNameInfo([System.Security.Cryptography.X509Certificates.X509NameType]::SimpleName,$false); $v=[System.Diagnostics.FileVersionInfo]::GetVersionInfo($env:VGA_VERIFY_IMAGE_PATH); @{status='Valid';publisher=$n;original=$v.OriginalFilename;product=$v.ProductName}|ConvertTo-Json -Compress"
            command=base64.b64encode(script.encode('utf-16-le')).decode('ascii')
            executable=Path(os.environ.get('SystemRoot',r'C:\Windows'))/'System32/WindowsPowerShell/v1.0/powershell.exe'
            result=subprocess.run([str(executable),'-NoLogo','-NoProfile','-NonInteractive','-EncodedCommand',command],
                env={**os.environ,'VGA_VERIFY_IMAGE_PATH':str(path)},capture_output=True,timeout=12,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),check=False)
            value=json.loads(result.stdout.decode('utf-8-sig').strip()) if result.returncode==0 else {}
            valid=trusted_signature_result(value,path)
            after=Path(path).stat()
            valid=valid and (after.st_size,after.st_mtime_ns,after.st_ino)==key[1:]
            self.cache[key]=(valid,time.monotonic());return valid
        except (OSError,ValueError,subprocess.SubprocessError):
            if 'key' in locals():self.cache[key]=(False,time.monotonic())
            return False


def trusted_signature_result(value,path):
    """Publisher alone cannot authorize a renamed, unrelated signed Tencent app."""
    if not isinstance(value,dict):return False
    return (value.get('status')=='Valid'
        and str(value.get('publisher','')).strip().casefold() in PUBLISHERS
        and str(value.get('original','')).strip().casefold()==PureWindowsPath(path).name.casefold()
        and str(value.get('product','')).strip().casefold() in ('league of legends','league of legends (tm) client'))


@dataclass(frozen=True,eq=False)
class Candidate:
    window:object
    metadata:ProcessMetadata
    root:str
    role:str
    @property
    def binding_identity(self):
        # A localized or changing caption is presentation, never authorization.
        return (tuple(self.window.identity),self.metadata,self.root,self.role)
    def __eq__(self,other):
        if not isinstance(other,Candidate):return NotImplemented
        return self.binding_identity==other.binding_identity
    def __hash__(self):return hash(self.binding_identity)


@dataclass(frozen=True)
class Discovery:
    candidate:Candidate|None
    reason:str
    confirmation:Candidate|None=None
    reason_code:str="unknown"


class AutomaticWindowPolicy:
    """One explicit Start, one installation. Restarts do not carry hero evidence."""
    def __init__(self,*,resolver=process_metadata,verifier=None,follow_roles=True):
        self.resolver=resolver;self.verifier=verifier or PublisherVerifier()
        self.root=None;self.bound=None;self.active=True;self.follow_roles=follow_roles;self.confirmed_root=None
        self.started_after=int(time.time()*10_000_000)+116444736000000000
    def stop(self):self.active=False;self.bound=None;self.confirmed_root=None
    def inspect(self,window,*,verify=True):
        if window.class_name not in CLIENT_CLASSES|{'RiotWindowClass'}:return None
        try:
            meta=self.resolver(window.pid);path=PureWindowsPath(normalized_path(meta.path))
            if not isinstance(meta.created,int) or meta.created<=0:return None
            if path.name in ('leagueclientux.exe','leagueclient.exe') and window.class_name in CLIENT_CLASSES:
                role='client';root=path.parent.parent if path.parent.name=='leagueclient' else path.parent
            elif path.name=='league of legends.exe' and path.parent.name=='game' and window.class_name=='RiotWindowClass':
                role='game';root=path.parent.parent
            else:return None
            if self.root is not None and str(root)!=self.root:return None
            if verify and not self.verifier(str(path)):return None
            return Candidate(window,ProcessMetadata(str(path),meta.created),str(root),role)
        except (OSError,ValueError,KeyError):return None
    def preferred(self,candidates):
        if not self.follow_roles and self.bound:candidates=[item for item in candidates if item.role==self.bound.role]
        games=[item for item in candidates if item.role=='game']
        return games or [item for item in candidates if item.role=='client']
    def discover(self,windows):
        if not self.active:return Discovery(None,'监测已停止。',reason_code='discovery_stopped')
        recognized=[item for window in windows if (item:=self.inspect(window,verify=False)) is not None]
        if not recognized:
            reason='检测到游戏窗口，但暂时无法核验其基本进程身份；不会截图，稍后自动重试。' if any(window.class_name=='RiotWindowClass' for window in windows) else '等待英雄联盟窗口；游戏启动、恢复或重开后会自动连接。'
            return Discovery(None,reason,reason_code='window_identity_unverified' if any(window.class_name=='RiotWindowClass' for window in windows) else 'window_not_found')
        if len({item.root for item in recognized})!=1:return Discovery(None,'发现多个英雄联盟安装目录，等待只保留一个客户端或游戏。',reason_code='multiple_installations')
        preferred=self.preferred(recognized)
        if len(preferred)!=1:return Discovery(None,'发现多个同类英雄联盟窗口，暂不截图；关闭多余窗口后自动恢复。',reason_code='multiple_windows')
        candidate=preferred[0]
        if not self.active:return Discovery(None,'监测已停止。',reason_code='discovery_stopped')
        if candidate.root!=self.confirmed_root and not self.verifier(candidate.metadata.path):
            name=PureWindowsPath(candidate.metadata.path).name
            return Discovery(None,'已找到 '+name+'（'+candidate.window.class_name+'），但签名/游戏文件身份未通过本机校验；可确认自己的安装目录后继续。',candidate,reason_code='signature_unverified')
        return Discovery(candidate,'已自动连接'+('游戏窗口。' if candidate.role=='game' else '客户端，等待选人或进入游戏。'),reason_code='game_connected' if candidate.role=='game' else 'client_connected')
    def confirm_installation(self,candidate,*,windows):
        """Only the GUI's explicit, per-session installation confirmation calls this."""
        if not self.active or not candidate:return False
        fresh=[item for window in windows if (item:=self.inspect(window,verify=False)) is not None]
        if len({item.root for item in fresh})!=1 or self.preferred(fresh)!=[candidate]:return False
        self.root=candidate.root;self.confirmed_root=candidate.root;return True
    def adopt(self,discovery,*,windows):
        candidate=discovery.candidate
        if not self.active or candidate is None:return False
        # A late result cannot authorize a window after a new ambiguity appeared.
        # Only metadata is read here; expensive trust checks stay on the worker.
        fresh=[item for window in windows if (item:=self.inspect(window,verify=False)) is not None]
        if len({item.root for item in fresh})!=1:return False
        preferred=self.preferred(fresh)
        if len(preferred)!=1 or preferred[0]!=candidate:return False
        try:
            meta=self.resolver(candidate.window.pid)
            if ProcessMetadata(normalized_path(meta.path),meta.created)!=candidate.metadata:return False
        except (OSError,ValueError,KeyError):return False
        if self.root is not None and candidate.root!=self.root:return False
        self.root=candidate.root;self.bound=candidate;return True
    def permits(self,window,*,windows=None):
        if not self.active or not self.bound or tuple(window.identity)!=tuple(self.bound.window.identity):return False
        if windows is not None:
            fresh=[item for item_window in windows if (item:=self.inspect(item_window,verify=False)) is not None]
            preferred=self.preferred(fresh)
            if len(preferred)!=1 or preferred[0]!=self.bound:return False
        try:
            meta=self.resolver(window.pid)
            return ProcessMetadata(normalized_path(meta.path),meta.created)==self.bound.metadata
        except (OSError,ValueError,KeyError):return False

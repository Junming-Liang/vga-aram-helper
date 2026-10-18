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
CLIENT_EXECUTABLES=frozenset({'leagueclientux.exe','leagueclient.exe'})
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
    # Counts only. Metadata eligibility is distinct from publisher verification;
    # the preferred candidate still passes the unchanged signature gate below.
    diagnostics:tuple[tuple[str,int],...]=()


DISCOVERY_COUNT_FIELDS=('window_count','eligible_client_count','eligible_game_count',
    'preferred_count','rejected_class_count','rejected_metadata_count',
    'rejected_identity_count','rejected_installation_count','rejected_signature_count')


TARGET_ROLES=frozenset({'none','client','game','manual','unknown'})
SELECTION_GATES=frozenset({'closed','stopped','inference_busy','capture_pending',
    'target_missing','foreground_rejected','client_lcu_ready','client_pixels_ready',
    'game_pixels_ready','manual_pixels_ready','route_unknown'})
SELECTION_ROUTES=frozenset({'blocked','selection_lcu','selection_pixels',
    'game_pixels','manual_pixels','unknown'})


def selection_gate_snapshot(*,closed,running,ocr_busy,capture_pending,
        target_present,target_role,target_foreground=None,lcu_selection=False,
        hero_auto=False,pixel_fallback=False):
    """Mirror capture_tick's existing short-circuit gates with fixed enums.

    Diagnostic-only: this never grants capture permission or starts work.
    A ready route is intent, not proof of a completed capture or inference.
    Foreground may be None when a prior guard short-circuited, so diagnostics
    never need an additional OS query. LCU off still leaves the client pixel
    route available. Its opt-in is observed, never changed or persisted.
    """
    role=target_role if type(target_role) is str and target_role in TARGET_ROLES else 'unknown'
    values={'target_role':role,'target_present':bool(target_present),
        'lcu_selection':bool(lcu_selection),'hero_auto':bool(hero_auto),
        'pixel_fallback':bool(pixel_fallback)}
    if type(target_foreground) is bool:values['target_foreground']=target_foreground
    route='blocked'
    if closed:gate='closed'
    elif ocr_busy:gate='inference_busy'
    elif capture_pending:gate='capture_pending'
    elif not running:gate='stopped'
    elif not target_present:gate='target_missing'
    elif target_foreground is False:gate='foreground_rejected'
    elif target_foreground is not True:gate='route_unknown';route='unknown'
    elif role=='client':
        if lcu_selection and hero_auto and not pixel_fallback:
            gate='client_lcu_ready';route='selection_lcu'
        else:gate='client_pixels_ready';route='selection_pixels'
    elif role=='game':gate='game_pixels_ready';route='game_pixels'
    elif role=='manual':gate='manual_pixels_ready';route='manual_pixels'
    else:gate='route_unknown';route='unknown'
    return {**values,'selection_gate':gate,'selection_route':route}


class AutomaticWindowPolicy:
    """One explicit Start, one installation. Restarts do not carry hero evidence."""
    def __init__(self,*,resolver=process_metadata,verifier=None,follow_roles=True):
        self.resolver=resolver;self.verifier=verifier or PublisherVerifier()
        self.root=None;self.bound=None;self.active=True;self.follow_roles=follow_roles;self.confirmed_root=None
        self.started_after=int(time.time()*10_000_000)+116444736000000000
    def stop(self):self.active=False;self.bound=None;self.confirmed_root=None
    def inspect(self,window,*,verify=True):
        return self._inspect(window,verify=verify)[0]
    def _inspect(self,window,*,verify=True):
        """Return the existing eligibility decision and a fixed rejection code.

        Diagnostic codes carry no title, executable path or native identity and
        cannot authorize a candidate. Keep metadata/signature calls unchanged.
        """
        if window.class_name not in CLIENT_CLASSES|{'RiotWindowClass'}:return None,'rejected_class_count'
        try:
            meta=self.resolver(window.pid);path=PureWindowsPath(normalized_path(meta.path))
            if not isinstance(meta.created,int) or meta.created<=0:return None,'rejected_metadata_count'
            if path.name in CLIENT_EXECUTABLES and window.class_name in CLIENT_CLASSES:
                role='client';root=path.parent.parent if path.parent.name=='leagueclient' else path.parent
            elif path.name=='league of legends.exe' and path.parent.name=='game' and window.class_name=='RiotWindowClass':
                role='game';root=path.parent.parent
            else:return None,'rejected_identity_count'
            if self.root is not None and str(root)!=self.root:return None,'rejected_installation_count'
            if verify and not self.verifier(str(path)):return None,'rejected_signature_count'
            return Candidate(window,ProcessMetadata(str(path),meta.created),str(root),role),None
        except (OSError,ValueError,KeyError):return None,'rejected_metadata_count'
    def preferred(self,candidates,*,foreground_hwnd=None,available_hwnds=None,confirmation_candidate=None):
        if not self.follow_roles and self.bound:candidates=[item for item in candidates if item.role==self.bound.role]
        available=[item for item in candidates if available_hwnds is None or item.window.hwnd in available_hwnds]
        # Foreground selects a ROLE only among metadata-eligible windows. It
        # never authorizes an arbitrary caption/process or breaks same-role
        # ambiguity. Trust and installation checks still run before adoption.
        if foreground_hwnd is not None:
            foreground=[item for item in available if item.window.hwnd==foreground_hwnd]
            if foreground:
                return [item for item in candidates if item.role==foreground[0].role]
            # Opening our controls or another app must not switch an existing
            # binding from client to a background game. Capture still requires
            # the exact target to be foreground. None preserves legacy callers
            # that cannot supply a foreground snapshot; zero means no focus.
            for previous in (confirmation_candidate,self.bound):
                if previous in available:
                    return [item for item in candidates if item.role==previous.role]
        games=[item for item in available if item.role=='game']
        ready=games or [item for item in available if item.role=='client']
        # Availability chooses a role, never removes a second window from that
        # role's ambiguity evidence. The full set also checks installations.
        return [item for item in candidates if item.role==ready[0].role] if ready else []
    def discover(self,windows,*,foreground_hwnd=None,available_hwnds=None):
        counts={name:0 for name in DISCOVERY_COUNT_FIELDS}
        def result(candidate,reason,confirmation=None,*,reason_code):
            return Discovery(candidate,reason,confirmation,reason_code,tuple(counts.items()))
        if not self.active:return result(None,'监测已停止。',reason_code='discovery_stopped')
        windows=tuple(windows);counts['window_count']=len(windows);recognized=[]
        for window in windows:
            item,rejection=self._inspect(window,verify=False)
            if item is None:counts[rejection]+=1
            else:
                recognized.append(item)
                counts['eligible_client_count' if item.role=='client' else 'eligible_game_count']+=1
        if not recognized:
            reason='检测到游戏窗口，但暂时无法核验其基本进程身份；不会截图，稍后自动重试。' if any(window.class_name=='RiotWindowClass' for window in windows) else '等待英雄联盟窗口；游戏启动、恢复或重开后会自动连接。'
            return result(None,reason,reason_code='window_identity_unverified' if any(window.class_name=='RiotWindowClass' for window in windows) else 'window_not_found')
        if len({item.root for item in recognized})!=1:return result(None,'发现多个英雄联盟安装目录，等待只保留一个客户端或游戏。',reason_code='multiple_installations')
        preferred=self.preferred(recognized,foreground_hwnd=foreground_hwnd,available_hwnds=available_hwnds)
        counts['preferred_count']=len(preferred)
        if not preferred:return result(None,'已找到英雄联盟窗口，但当前没有可采集窗口；恢复窗口后自动连接。',reason_code='window_unavailable')
        if len(preferred)!=1:return result(None,'发现多个同类英雄联盟窗口，暂不截图；关闭多余窗口后自动恢复。',reason_code='multiple_windows')
        candidate=preferred[0]
        if not self.active:return result(None,'监测已停止。',reason_code='discovery_stopped')
        if candidate.root!=self.confirmed_root and not self.verifier(candidate.metadata.path):
            counts['rejected_signature_count']+=1
            name=PureWindowsPath(candidate.metadata.path).name
            return result(None,'已找到 '+name+'（'+candidate.window.class_name+'），但签名/游戏文件身份未通过本机校验；可确认自己的安装目录后继续。',candidate,reason_code='signature_unverified')
        return result(candidate,'已自动连接'+('游戏窗口。' if candidate.role=='game' else '客户端，等待选人或进入游戏。'),reason_code='game_connected' if candidate.role=='game' else 'client_connected')
    def confirm_installation(self,candidate,*,windows,foreground_hwnd=None,available_hwnds=None):
        """Only the GUI's explicit, per-session installation confirmation calls this."""
        if not self.active or not candidate:return False
        fresh=[item for window in windows if (item:=self.inspect(window,verify=False)) is not None]
        if len({item.root for item in fresh})!=1 or self.preferred(fresh,foreground_hwnd=foreground_hwnd,available_hwnds=available_hwnds,confirmation_candidate=candidate)!=[candidate]:return False
        self.root=candidate.root;self.confirmed_root=candidate.root
        # The dialog may temporarily own focus. This confirms the installation
        # only; no target binding or pending role preference is retained.
        return True
    def adopt(self,discovery,*,windows,foreground_hwnd=None,available_hwnds=None):
        candidate=discovery.candidate
        if not self.active or candidate is None:return False
        # A late result cannot authorize a window after a new ambiguity appeared.
        # Only metadata is read here; expensive trust checks stay on the worker.
        fresh=[item for window in windows if (item:=self.inspect(window,verify=False)) is not None]
        if len({item.root for item in fresh})!=1:return False
        preferred=self.preferred(fresh,foreground_hwnd=foreground_hwnd,available_hwnds=available_hwnds)
        if len(preferred)!=1 or preferred[0]!=candidate:return False
        try:
            meta=self.resolver(candidate.window.pid)
            if ProcessMetadata(normalized_path(meta.path),meta.created)!=candidate.metadata:return False
        except (OSError,ValueError,KeyError):return False
        if self.root is not None and candidate.root!=self.root:return False
        self.root=candidate.root;self.bound=candidate;return True
    def permits(self,window,*,windows=None,foreground_hwnd=None,available_hwnds=None):
        if not self.active or not self.bound or tuple(window.identity)!=tuple(self.bound.window.identity):return False
        if windows is not None:
            fresh=[item for item_window in windows if (item:=self.inspect(item_window,verify=False)) is not None]
            preferred=self.preferred(fresh,foreground_hwnd=foreground_hwnd,available_hwnds=available_hwnds)
            if len(preferred)!=1 or preferred[0]!=self.bound:return False
        try:
            meta=self.resolver(window.pid)
            return ProcessMetadata(normalized_path(meta.path),meta.created)==self.bound.metadata
        except (OSError,ValueError,KeyError):return False

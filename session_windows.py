"""Ordinary Windows process *metadata* for explicitly started client/game scope.

The only process right requested is PROCESS_QUERY_LIMITED_INFORMATION (0x1000).
No VM_READ, ReadProcessMemory, injection, LCU, hooks, tokens or private APIs.
An approved client window anchors the installation; title alone never grants
capture permission to a game window. No capture occurs in this module.
"""
from dataclasses import dataclass
from pathlib import PureWindowsPath
import ctypes
from ctypes import wintypes as W
import os
import re
import time

PROCESS_QUERY_LIMITED_INFORMATION=0x1000

@dataclass(frozen=True)
class ProcessMetadata:
    path:str
    created:int


def process_metadata(pid):
    if os.name!='nt':raise OSError('Windows metadata queries unavailable')
    if not isinstance(pid,int) or isinstance(pid,bool) or pid<=0:raise ValueError('Invalid PID')
    k=ctypes.WinDLL('kernel32',use_last_error=True)
    k.OpenProcess.argtypes=[W.DWORD,W.BOOL,W.DWORD];k.OpenProcess.restype=W.HANDLE
    k.QueryFullProcessImageNameW.argtypes=[W.HANDLE,W.DWORD,W.LPWSTR,ctypes.POINTER(W.DWORD)];k.QueryFullProcessImageNameW.restype=W.BOOL
    k.GetProcessTimes.argtypes=[W.HANDLE,ctypes.POINTER(W.FILETIME),ctypes.POINTER(W.FILETIME),ctypes.POINTER(W.FILETIME),ctypes.POINTER(W.FILETIME)];k.GetProcessTimes.restype=W.BOOL
    k.CloseHandle.argtypes=[W.HANDLE];k.CloseHandle.restype=W.BOOL
    handle=k.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION,False,pid)
    if not handle:raise OSError('Cannot query the selected process metadata')
    try:
        size=W.DWORD(32768);buffer=ctypes.create_unicode_buffer(size.value)
        if not k.QueryFullProcessImageNameW(handle,0,buffer,ctypes.byref(size)):raise OSError('Process image path unavailable')
        created,exit_time,kernel,user=(W.FILETIME() for _ in range(4))
        if not k.GetProcessTimes(handle,ctypes.byref(created),ctypes.byref(exit_time),ctypes.byref(kernel),ctypes.byref(user)):raise OSError('Process creation time unavailable')
        return ProcessMetadata(final_image_path(buffer.value),(int(created.dwHighDateTime)<<32)|int(created.dwLowDateTime))
    finally:k.CloseHandle(handle)



def final_image_path(path):
    """Resolve junctions/symlinks through a metadata-only file handle."""
    if os.name!='nt':raise OSError('Windows final-path query unavailable')
    k=ctypes.WinDLL('kernel32',use_last_error=True)
    k.CreateFileW.argtypes=[W.LPCWSTR,W.DWORD,W.DWORD,ctypes.c_void_p,W.DWORD,W.DWORD,W.HANDLE];k.CreateFileW.restype=W.HANDLE
    k.GetFinalPathNameByHandleW.argtypes=[W.HANDLE,W.LPWSTR,W.DWORD,W.DWORD];k.GetFinalPathNameByHandleW.restype=W.DWORD
    k.CloseHandle.argtypes=[W.HANDLE];k.CloseHandle.restype=W.BOOL
    handle=k.CreateFileW(path,0x80,0x7,None,3,0,None) # FILE_READ_ATTRIBUTES only; share all; OPEN_EXISTING
    if handle in (None,ctypes.c_void_p(-1).value):raise OSError('Cannot canonicalize process executable path')
    try:
        buffer=ctypes.create_unicode_buffer(32768);size=k.GetFinalPathNameByHandleW(handle,buffer,len(buffer),0)
        if not 0<size<len(buffer):raise OSError('Final executable path unavailable')
        value=buffer.value
        if value.startswith('\\\\?\\'):value=value[4:]
        return normalized_path(value)
    finally:k.CloseHandle(handle)


def normalized_path(value):
    if not isinstance(value,str) or not value or '\x00' in value:raise ValueError('Invalid process image path')
    p=PureWindowsPath(value)
    if not p.is_absolute() or not re.fullmatch(r'[a-zA-Z]:',p.drive) or '..' in p.parts:raise ValueError('Expected absolute OS-reported image path')
    return str(p).casefold()


class SessionWindowPolicy:
    """Instantiate only after explicit Start for listed client+same-install game."""
    def __init__(self,client, *, resolver=process_metadata,started_after=None):
        self.started_after=started_after if started_after is not None else int(time.time()*10_000_000)+116444736000000000
        self.resolver=resolver;meta=resolver(client.pid);path=PureWindowsPath(normalized_path(meta.path))
        if path.name not in ('leagueclientux.exe','leagueclient.exe'):raise ValueError('Selected window is not a supported League client executable')
        self.client_identity=tuple(client.identity);self.client_meta=ProcessMetadata(str(path),meta.created);self.root=path.parent.parent if path.parent.name=='leagueclient' else path.parent
        self.game_identity=None;self.game_meta=None;self.active=True
    def stop(self):self.active=False;self.game_identity=None;self.game_meta=None
    def _matches(self,window,saved_identity,saved_meta):
        if not self.active or tuple(window.identity)!=saved_identity:return False
        try:
            meta=self.resolver(window.pid)
            return normalized_path(meta.path)==saved_meta.path and meta.created==saved_meta.created
        except (OSError,ValueError):return False
    def permits(self,window):
        return self._matches(window,self.client_identity,self.client_meta) or (self.game_identity is not None and self._matches(window,self.game_identity,self.game_meta))
    def discover_game(self,windows):
        """Return a single same-install candidate; caller still validates scene.

        A client process must remain the originally consented instance. A
        different/restarted client invalidates discovery, rather than widening
        permission by process name.
        """
        if not self.active:return None
        try:
            current=self.resolver(self.client_identity[1])
            if normalized_path(current.path)!=self.client_meta.path or current.created!=self.client_meta.created:return None
        except (OSError,ValueError):return None
        expected=str(self.root/'game'/'league of legends.exe');matches=[]
        for window in windows:
            if window.class_name!='RiotWindowClass':continue
            try:meta=self.resolver(window.pid)
            except (OSError,ValueError):continue
            if normalized_path(meta.path)==expected and meta.created>self.started_after:matches.append((window,ProcessMetadata(expected,meta.created)))
        if len(matches)!=1:return None
        return matches[0]
    def adopt_game(self,candidate, *, windows,confirmed_handoff=False):
        if not self.active or not confirmed_handoff or not isinstance(candidate,tuple) or len(candidate)!=2:return False
        window,meta=candidate
        # Revalidate instead of trusting an old discovery result/PID reuse.
        fresh=self.discover_game(windows)
        if fresh is None or fresh[1]!=meta or tuple(fresh[0].identity)!=tuple(window.identity):return False
        self.game_identity=tuple(window.identity);self.game_meta=meta;return True

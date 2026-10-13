"""Bounded local evidence for cache failures; never record paths or image bytes."""
from __future__ import annotations

import os
from pathlib import Path
import re
import stat
import threading
import time

from app_version import __version__
from update_network import atomic_write, json_bytes

REPORT_NAME='portrait-cache-diagnostic.json'
MAX_FAILURES=6


def error_codes(error):
    """Do not serialize exception messages: Windows adds private absolute paths."""
    return {name:value for name in ('errno','winerror')
            if isinstance(value:=getattr(error,name,None),int)}


def file_snapshot(path):
    try:
        details=Path(path).lstat()
        attributes=getattr(details,'st_file_attributes',None)
        return {'exists':True,'regularFile':stat.S_ISREG(details.st_mode),'metadataFollowsLinks':False,
                'sizeBytes':details.st_size,
                'windowsReadOnly':bool(attributes&1) if attributes is not None else None,
                'windowsReparsePoint':bool(attributes&0x400) if attributes is not None else None}
    except OSError as error:
        return {'exists':False if isinstance(error,FileNotFoundError) else None,
                'statError':error_codes(error)}


def sharing_probe(path):
    """Try a DELETE-access handle, but NEVER mark/delete/write/change the file.

    OPEN_EXISTING plus sharing read/write/delete distinguishes an existing
    handle's sharing denial from access denial at this instant. A successful
    probe cannot exclude an earlier short-lived lock, read-only attributes, or
    a parent-directory permission problem. No process enumeration is performed.
    """
    if os.name!='nt':return {'state':'not-windows'}
    try:return _windows_sharing_probe(path)
    except (OSError,AttributeError) as error:return {'state':'probe-unavailable',**error_codes(error)}


def _windows_sharing_probe(path):
    import ctypes
    from ctypes import wintypes
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateFileW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,
                                wintypes.LPVOID,wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE]
    kernel.CreateFileW.restype=wintypes.HANDLE
    kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    kernel.CloseHandle.restype=wintypes.BOOL
    # DELETE access; FILE_SHARE_READ|WRITE|DELETE; OPEN_EXISTING. No delete flag.
    handle=kernel.CreateFileW(str(path),0x00010000,0x1|0x2|0x4,None,3,0,None)
    if handle==wintypes.HANDLE(-1).value:
        return {'state':'denied','winerror':ctypes.get_last_error()}
    if not kernel.CloseHandle(handle):
        return {'state':'opened','closeWinerror':ctypes.get_last_error()}
    return {'state':'opened'}


def capture_failure(path,temporary,stage,error,*,temp_created,temp_flushed,temp_closed):
    """Only fixed fields and allowlisted public asset/version identifiers leave here."""
    path=Path(path)
    name=path.name
    if not re.fullmatch(r'(?:[A-Za-z0-9]{1,60}\.png|manifest\.json|roster-\d{1,3}\.\d{1,3}\.\d{1,3}\.json)',name):name='other-cache-file'
    version=path.parent.name if re.fullmatch(r'\d{1,3}\.\d{1,3}\.\d{1,3}',path.parent.name) else None
    result={'asset':name,'version':version,'stage':stage,'error':error_codes(error),
            'processId':os.getpid(),'threadId':threading.get_native_id(),
            'tempCreated':temp_created,'tempFlushed':temp_flushed,'tempClosed':temp_closed,
            'sourceAndDestinationSameParent':temporary is not None and
                os.path.normcase(os.path.abspath(Path(temporary).parent))==os.path.normcase(os.path.abspath(path.parent)),
            'destination':file_snapshot(path),'attemptErrors':[],'outcome':'failed'}
    if temporary is not None:
        result['source']=file_snapshot(temporary)
    if stage=='replace':
        result['destinationDeleteAccess']=sharing_probe(path)
        if temporary is not None:result['sourceDeleteAccess']=sharing_probe(temporary)
    return result


def report(failures):
    return {'schemaVersion':1,'applicationVersion':__version__,
            'recordedAt':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
            'scope':'Local portrait-cache filesystem evidence only. No screenshots, file contents, full paths, usernames or process lists. Probes describe the instant sampled; they do not identify the historical cause or locking process.',
            'failures':failures[:MAX_FAILURES]}


def retain_failure(failures,diagnostic):
    """The bounded report must not hide a persistent error behind recovered ones."""
    if len(failures)<MAX_FAILURES:failures.append(diagnostic)
    elif diagnostic.get('outcome')=='failed':
        for index,earlier in enumerate(failures):
            if earlier.get('outcome')=='recovered-after-retry':
                failures[index]=diagnostic
                break


def save_report(cache,details):
    """One small latest report; persistence failure must not break recognition."""
    try:
        payload=json_bytes(details)
        if len(payload)>32*1024:return False
        atomic_write(Path(cache).parent/'logs'/REPORT_NAME,payload)
        return True
    except (OSError,ValueError):return False

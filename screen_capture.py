"""Ordinary Windows window metadata + bounded client-area pixel capture.

No process-memory reading, DLL injection, input hooks, game API or input
simulation. Only explicitly authorized visible foreground window pixels are copied.
WGC uses project-owned, bounded HWND helpers, with metadata-only process queries
and ROI-only GPU readback. The persistent path requires an exact owned opaque
overlay exclusion; unsupported systems retain the strict one-shot/GDI path.
The compositor fallback allocates only the verified client rectangle, never a
whole-desktop image; every intersecting higher window makes it abstain.
"""
from __future__ import annotations
import ctypes
from ctypes import wintypes as W
from dataclasses import dataclass
import io
import os
import subprocess
import threading

class CaptureUnavailable(RuntimeError):pass
class CapturePaused(CaptureUnavailable):
    """Expected lifecycle/focus condition; retry automatically, not a setup error."""
    pass

@dataclass(frozen=True)
class WindowInfo:
    hwnd:int
    pid:int
    title:str
    class_name:str
    @property
    def identity(self):return (self.hwnd,self.pid,self.class_name)

@dataclass(frozen=True)
class ClientRect:
    x:int;y:int;width:int;height:int

class Win32Capture:
    def __init__(self,*,persistent_sessions=True,allow_visible_overlay=False):
        if os.name!='nt':raise CaptureUnavailable('窗口像素监测目前仅支持 Windows 10/11。')
        self.u=ctypes.WinDLL('user32',use_last_error=True);self.g=ctypes.WinDLL('gdi32',use_last_error=True)
        self._declare()
        from persistent_capture_adapter import PersistentCaptureAdapter
        self._persistent=PersistentCaptureAdapter(self._check_session_overlay,enabled=persistent_sessions,
                                                   allow_visible_overlay=allow_visible_overlay)
        self._last_session_receipt=None
        self._last_session_epoch=None
        self._capture_lock=threading.Lock()
        self._overlay_hwnd=None
        self._wgc=None;self._wgc_error=None
        from wgc_capture import WgcCapture,WgcError,WgcUnavailable
        try:self._wgc=WgcCapture()
        except WgcUnavailable:pass
        except WgcError as exc:self._wgc_error=exc
    def _declare(self):
        def sig(dll,name,args,restype):
            fn=getattr(dll,name);fn.argtypes=args;fn.restype=restype
        for name,args,result in [
            ('IsWindow',[W.HWND],W.BOOL),('IsWindowVisible',[W.HWND],W.BOOL),('IsIconic',[W.HWND],W.BOOL),
            ('GetWindowTextLengthW',[W.HWND],ctypes.c_int),('GetWindowTextW',[W.HWND,W.LPWSTR,ctypes.c_int],ctypes.c_int),
            ('GetClassNameW',[W.HWND,W.LPWSTR,ctypes.c_int],ctypes.c_int),('GetWindowThreadProcessId',[W.HWND,ctypes.POINTER(W.DWORD)],W.DWORD),
            ('GetWindowRect',[W.HWND,ctypes.POINTER(W.RECT)],W.BOOL),('GetClientRect',[W.HWND,ctypes.POINTER(W.RECT)],W.BOOL),('ClientToScreen',[W.HWND,ctypes.POINTER(W.POINT)],W.BOOL),
            ('MonitorFromRect',[ctypes.POINTER(W.RECT),W.DWORD],W.HANDLE),('GetMonitorInfoW',[W.HANDLE,ctypes.c_void_p],W.BOOL),
            ('GetForegroundWindow',[],W.HWND),('GetAncestor',[W.HWND,W.UINT],W.HWND),('GetDC',[W.HWND],W.HDC),('ReleaseDC',[W.HWND,W.HDC],ctypes.c_int),
            ('WindowFromPoint',[W.POINT],W.HWND),('SetWindowDisplayAffinity',[W.HWND,W.DWORD],W.BOOL),
            ('GetWindowDisplayAffinity',[W.HWND,ctypes.POINTER(W.DWORD)],W.BOOL),
            ('SetLayeredWindowAttributes',[W.HWND,W.DWORD,W.BYTE,W.DWORD],W.BOOL),
            ('GetLayeredWindowAttributes',[W.HWND,ctypes.POINTER(W.DWORD),ctypes.POINTER(W.BYTE),ctypes.POINTER(W.DWORD)],W.BOOL),
            ('RegisterHotKey',[W.HWND,ctypes.c_int,W.UINT,W.UINT],W.BOOL),('UnregisterHotKey',[W.HWND,ctypes.c_int],W.BOOL),
            ('SetWindowPos',[W.HWND,W.HWND,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,W.UINT],W.BOOL)]:sig(self.u,name,args,result)
        try:
            self.dwm=ctypes.WinDLL('dwmapi',use_last_error=True);self._cloaked_fn=self.dwm.DwmGetWindowAttribute
            self._cloaked_fn.argtypes=[W.HWND,W.DWORD,ctypes.c_void_p,W.DWORD];self._cloaked_fn.restype=ctypes.c_long
        except OSError:self._cloaked_fn=None
        self.enum_cb=ctypes.WINFUNCTYPE(W.BOOL,W.HWND,W.LPARAM)
        sig(self.u,'EnumWindows',[self.enum_cb,W.LPARAM],W.BOOL)
        ptr=ctypes.c_ssize_t
        self.get_long=getattr(self.u,'GetWindowLongPtrW',self.u.GetWindowLongW);self.get_long.argtypes=[W.HWND,ctypes.c_int];self.get_long.restype=ptr
        self.set_long=getattr(self.u,'SetWindowLongPtrW',self.u.SetWindowLongW);self.set_long.argtypes=[W.HWND,ctypes.c_int,ptr];self.set_long.restype=ptr
        for name,args,result in [('CreateCompatibleDC',[W.HDC],W.HDC),('CreateCompatibleBitmap',[W.HDC,ctypes.c_int,ctypes.c_int],W.HBITMAP),('SelectObject',[W.HDC,W.HANDLE],W.HANDLE),('DeleteObject',[W.HANDLE],W.BOOL),('DeleteDC',[W.HDC],W.BOOL),('BitBlt',[W.HDC,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,W.HDC,ctypes.c_int,ctypes.c_int,W.DWORD],W.BOOL),('GetDIBits',[W.HDC,W.HBITMAP,W.UINT,W.UINT,ctypes.c_void_p,ctypes.c_void_p,W.UINT],ctypes.c_int)]:sig(self.g,name,args,result)
    def info(self,hwnd):
        if not self.u.IsWindow(hwnd):raise CapturePaused('等待英雄联盟窗口重新启动。')
        count=self.u.GetWindowTextLengthW(hwnd);title=ctypes.create_unicode_buffer(count+1);self.u.GetWindowTextW(hwnd,title,count+1)
        cls=ctypes.create_unicode_buffer(256);self.u.GetClassNameW(hwnd,cls,256);pid=W.DWORD();self.u.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
        return WindowInfo(int(hwnd),int(pid.value),title.value,cls.value)
    def windows(self,include_own=False):
        result=[]
        def each(hwnd,_):
            if self.u.IsWindowVisible(hwnd):
                try:
                    item=self.info(hwnd)
                    if item.title and (include_own or item.pid!=os.getpid()):result.append(item)
                except CaptureUnavailable:pass
            return True
        cb=self.enum_cb(each);self.u.EnumWindows(cb,0);return sorted(result,key=lambda x:x.title.casefold())
    def rect(self,target):
        current=self.info(target.hwnd)
        if current.identity!=target.identity:raise CapturePaused('窗口已重建，等待重新连接。')
        if not self.u.IsWindowVisible(target.hwnd) or self.u.IsIconic(target.hwnd):raise CapturePaused('游戏已隐藏或最小化；恢复窗口后自动继续。')
        rect=W.RECT();point=W.POINT(0,0)
        if not self.u.GetClientRect(target.hwnd,ctypes.byref(rect)) or not self.u.ClientToScreen(target.hwnd,ctypes.byref(point)):raise CaptureUnavailable('无法读取目标窗口客户区。')
        width,height=rect.right-rect.left,rect.bottom-rect.top
        if min(width,height)<64:raise CaptureUnavailable(f'目标客户区尺寸不支持：{width}×{height} 像素，宽和高需至少64像素。')
        if width*height>16_000_000:raise CaptureUnavailable(f'目标客户区尺寸不支持：{width}×{height} 像素，超过当前1600万像素预算。')
        return ClientRect(point.x,point.y,width,height)
    def foreground(self,target):return int(self.u.GetAncestor(self.u.GetForegroundWindow(),2) or 0)==target.hwnd
    def validate(self,target,*,check_occlusion=True):
        rect=self.rect(target)
        if not self.foreground(target):raise CapturePaused('等待切回英雄联盟；旧资料已隐藏。')
        affinity=W.DWORD();query=getattr(self.u,'GetWindowDisplayAffinity',None)
        if query and query(target.hwnd,ctypes.byref(affinity)) and affinity.value:
            raise CapturePaused('目标窗口已设置画面保护，本帧不进行截图。')
        if check_occlusion:
            for fx in (.1,.5,.9):
                for fy in (.1,.5,.9):
                    hit=self.u.WindowFromPoint(W.POINT(rect.x+int(rect.width*fx),rect.y+int(rect.height*fy)))
                    if int(self.u.GetAncestor(hit,2) or 0)!=target.hwnd:raise CapturePaused('游戏被其他窗口遮挡；移开后会自动继续。')
        return rect
    def validate_compositor(self,target,expected,*,allow_visible_overlay=False):
        """Prove the ENTIRE client rectangle is visible, not nine sample points.

        EnumWindows walks top-level z order. Unknown/failed geometry is denied.
        DWM-cloaked windows may be ignored only after a successful OS query.
        """
        overlay=None
        if allow_visible_overlay:
            adapter=getattr(self,'_persistent',None)
            overlay=adapter.overlay if adapter is not None else None
            if overlay is None or not adapter.can_request_visible_overlay:
                raise CapturePaused('可见叠加捕获条件已变化，已跳过本帧。')
            self._check_session_overlay(overlay,allow_visible_overlay=True)
        else:
            self._check_overlay_hidden()
        rect=self.validate(target,check_occlusion=False) if allow_visible_overlay else self.validate(target)
        if rect!=expected:raise CapturePaused('窗口正在移动，等待画面稳定。')
        bounds=W.RECT(rect.x,rect.y,rect.x+rect.width,rect.y+rect.height)
        class MI(ctypes.Structure):
            _fields_=[('size',W.DWORD),('monitor',W.RECT),('work',W.RECT),('flags',W.DWORD)]
        monitor=self.u.MonitorFromRect(ctypes.byref(bounds),0);info=MI();info.size=ctypes.sizeof(info)
        if not monitor or not self.u.GetMonitorInfoW(monitor,ctypes.byref(info)) or not contains_rect(info.monitor,bounds):
            raise CapturePaused('游戏客户区需完整位于一个显示器内；移动后自动继续。')
        found=False;blocked=False
        def each(hwnd,_):
            nonlocal found,blocked
            if int(hwnd)==target.hwnd:found=True;return False
            if not self.u.IsWindowVisible(hwnd) or self.u.IsIconic(hwnd):return True
            fn=getattr(self,'_cloaked_fn',None)
            if fn:
                cloaked=W.DWORD()
                if fn(hwnd,14,ctypes.byref(cloaked),ctypes.sizeof(cloaked))==0 and cloaked.value:return True
            other=W.RECT()
            if not self.u.GetWindowRect(hwnd,ctypes.byref(other)):
                blocked=True;return False
            if intersects_rect(bounds,other):
                if overlay is not None and int(hwnd)==overlay.hwnd:
                    try:self._check_session_overlay(overlay,allow_visible_overlay=True)
                    except Exception:blocked=True;return False
                    return True
                blocked=True;return False
            return True
        callback=self.enum_cb(each);self.u.EnumWindows(callback,0)
        if blocked or not found:raise CapturePaused('游戏上方仍有其他窗口；移开后会自动继续。')
        return rect
    def _copy_pixels(self,source,width,height,left,top):
        dc=bitmap=old=None
        try:
            dc=self.g.CreateCompatibleDC(source);bitmap=self.g.CreateCompatibleBitmap(source,width,height)
            if not dc or not bitmap:raise CaptureUnavailable('系统截图缓冲区创建失败。')
            old=self.g.SelectObject(dc,bitmap)
            if not self.g.BitBlt(dc,0,0,width,height,source,left,top,0x00CC0020):raise CaptureUnavailable('系统窗口像素复制失败。')
            class BI(ctypes.Structure):
                _fields_=[('size',W.DWORD),('width',W.LONG),('height',W.LONG),('planes',W.WORD),('bits',W.WORD),('compression',W.DWORD),('sizeImage',W.DWORD),('xppm',W.LONG),('yppm',W.LONG),('colors',W.DWORD),('important',W.DWORD)]
            header=BI(ctypes.sizeof(BI),width,-height,1,32,0,width*height*4,0,0,0,0)
            buf=ctypes.create_string_buffer(width*height*4)
            self.g.SelectObject(dc,old);old=None
            if self.g.GetDIBits(dc,bitmap,0,height,buf,ctypes.byref(header),0)!=height:raise CaptureUnavailable('系统未返回完整窗口像素。')
            from PIL import Image
            return Image.frombytes('RGB',(width,height),buf.raw,'raw','BGRX')
        finally:
            if old and dc:self.g.SelectObject(dc,old)
            if bitmap:self.g.DeleteObject(bitmap)
            if dc:self.g.DeleteDC(dc)
    def retire_session(self):
        """GUI-safe: revoke now; the adapter owns asynchronous close/cleanup."""
        self._last_session_receipt=None
        adapter=getattr(self,'_persistent',None)
        if adapter is not None:adapter.retire()
    def set_interactive_overlay(self,enabled):
        """Explicit UI mode, separate from all automatic fallback decisions."""
        if type(enabled) is not bool:raise TypeError('Interactive overlay mode requires a boolean')
        self._last_session_receipt=None
        adapter=getattr(self,'_persistent',None)
        if adapter is not None:adapter.set_interactive_overlay(enabled)
    def close(self):
        """GUI-safe permanent revocation; never waits for a native helper."""
        self._last_session_receipt=None
        adapter=getattr(self,'_persistent',None)
        if adapter is not None:adapter.close()
    @property
    def last_session_receipt(self):
        from types import MappingProxyType
        value=getattr(self,'_last_session_receipt',None)
        adapter=getattr(self,'_persistent',None)
        epoch=getattr(self,'_last_session_epoch',None)
        if adapter is not None and adapter.cancelled_since(epoch):return None
        return None if value is None else MappingProxyType(dict(value))
    def prepare_capture_mode(self,visible):
        """Plan a mode/style transition on the GUI thread before a NEW request.

        Returns False only while the old v2 owner drains. An unavailable route
        raises CapturePaused. No acquisition or backend retry happens here. Preserve old
        UI evidence only within its original TTL; readiness never refreshes it.
        """
        if type(visible) is not bool:raise TypeError('Visible overlay mode requires a boolean')
        adapter=getattr(self,'_persistent',None)
        if adapter is None:
            if visible:raise CapturePaused('可见叠加捕获未获授权或不可用。')
            return True
        style=None
        if visible:
            overlay=adapter.overlay
            if overlay is None:
                self.retire_session()
                raise CapturePaused('可见叠加窗口尚未完成排除注册。')
            try:
                ctypes.set_last_error(0)
                style=int(self.get_long(overlay.hwnd,-16))&0xffffffff
                if ctypes.get_last_error():raise OSError('Overlay style unavailable')
            except (OSError,AttributeError,ValueError,TypeError) as exc:
                self.retire_session()
                raise CapturePaused('无法核验可见叠加窗口的完整样式。') from exc
        from wgc_capture import WgcError
        try:ready=adapter.prepare_capture_mode(visible,overlay_window_style=style)
        except WgcError as exc:
            self._last_session_receipt=None
            raise CapturePaused(str(exc)) from exc
        if not ready:self._last_session_receipt=None
        # Legacy one-shot cleanup is drained by the next capture worker before
        # any helper acquisition. Waiting on its pending flags here would stop
        # that worker from ever running; no native wait belongs on the GUI.
        return ready
    @property
    def can_request_visible_overlay(self):
        """GUI-safe eligibility only; callers still explicitly opt in per capture.

        Keep any old candidates visibly rechecking with their original 4 s TTL.
        This hint never refreshes evidence or proves WGC pixel exclusion.
        """
        adapter=getattr(self,'_persistent',None)
        return bool(adapter is not None and adapter.can_request_visible_overlay
                    and not self.cleanup_pending)
    @property
    def cleanup_pending(self):
        adapter=getattr(self,'_persistent',None)
        backend=getattr(self,'_wgc',None)
        return bool((adapter is not None and adapter.cleanup_pending)
                    or getattr(backend,'_pending_cleanup',None) is not None
                    or getattr(backend,'_pending_job',None) is not None)
    def _check_overlay_hidden(self):
        hwnd=getattr(self,'_overlay_hwnd',None)
        if hwnd is not None and self.u.IsWindowVisible(hwnd):
            raise CapturePaused('自己的叠加尚未隐藏，已跳过本帧以避免识别反馈。')
    def _drain_one_shot_cleanup(self):
        """Worker-only old-v1 cleanup barrier before considering a v2 helper."""
        backend=getattr(self,'_wgc',None)
        if backend is None:return
        job=getattr(backend,'_pending_job',None)
        if job is not None:
            if not job.close():raise CapturePaused('上一次截图任务尚未确认关闭，暂不启动新截图。')
            backend._pending_job=None
        process=getattr(backend,'_pending_cleanup',None)
        if process is not None:
            try:
                if process.poll() is None:raise subprocess.TimeoutExpired('owned capture helper',0)
                process.communicate(timeout=0)
            except subprocess.TimeoutExpired as exc:
                raise CapturePaused('上一次截图任务仍在关闭，暂不启动新截图。') from exc
            for name in ('stdout','stderr'):
                stream=getattr(process,name,None)
                if stream:stream.close()
            backend._pending_cleanup=None
    def capture(self,target,roi=(0.,0.,1.,1.),*,cancelled=None,expected_metadata=None,allow_visible_overlay=False):
        """Worker-only capture. Every exit rechecks revocation, including PNG work."""
        from wgc_capture import WgcError
        adapter=getattr(self,'_persistent',None)
        epoch=adapter.epoch if adapter is not None else None
        external=(cancelled if callable(cancelled) else cancelled.is_set) if cancelled is not None else lambda:False
        is_cancelled=lambda:external() or (adapter is not None and adapter.cancelled_since(epoch))
        lock=getattr(self,'_capture_lock',None)
        if lock is not None and not lock.acquire(blocking=False):raise CapturePaused('已有窗口截图请求尚未结束。')
        try:
            self._last_session_receipt=None
            if adapter is not None:adapter.check_ready()
            if type(allow_visible_overlay) is not bool:raise TypeError('Visible overlay request requires a boolean')
            options={'allow_visible_overlay':True} if allow_visible_overlay else {}
            result=self._capture(target,roi,cancelled=is_cancelled,expected_metadata=expected_metadata,**options)
            if is_cancelled():raise CapturePaused('截图已取消。')
            if adapter is not None and self.last_backend=='windows-graphics-capture-session':
                self._last_session_receipt=adapter.last_receipt
                self._last_session_epoch=epoch
            if is_cancelled():raise CapturePaused('截图已取消。')
            return result
        except BaseException as exc:
            self.retire_session()
            if isinstance(exc,WgcError):raise CapturePaused(str(exc)) from exc
            raise
        finally:
            if lock is not None:lock.release()
    def _capture(self,target,roi=(0.,0.,1.,1.),*,cancelled=None,expected_metadata=None,allow_visible_overlay=False):
        """Capture on a worker; WGC denial/blank frames never trigger GDI."""
        is_cancelled=(cancelled if callable(cancelled) else cancelled.is_set) if cancelled is not None else lambda:False
        def check_binding():
            if expected_metadata is not None:
                from session_windows import process_metadata
                try:current=process_metadata(target.pid)
                except (OSError,ValueError) as exc:raise CapturePaused('截图窗口进程身份无法验证，已跳过本帧。') from exc
                if current!=expected_metadata:raise CapturePaused('原授权窗口进程已经变化，本帧未进行截图。')
        if is_cancelled():raise CapturePaused('截图已取消。')
        check_binding()
        adapter=getattr(self,'_persistent',None)
        if allow_visible_overlay:
            if not self.can_request_visible_overlay:
                raise CapturePaused('可见叠加捕获未获授权或不可用；请隐藏叠加后再请求截图。')
            rect=self.validate(target,check_occlusion=False)
            self.validate_compositor(target,rect,allow_visible_overlay=True)
        else:
            self._check_overlay_hidden()
            rect=self.validate(target);self.validate_compositor(target,rect)
        left,top,width,height=bounded_roi(rect.width,rect.height,roi)
        if getattr(self,'_wgc_error',None):raise CapturePaused(str(self._wgc_error))
        adapter=getattr(self,'_persistent',None)
        if adapter is not None:
            self._drain_one_shot_cleanup()
            options={'allow_visible_overlay':True} if allow_visible_overlay else {}
            image=adapter.capture(target,rect,(left,top,width,height),cancelled=is_cancelled,expected_metadata=expected_metadata,**options)
            if image is not None:
                if allow_visible_overlay:self.validate_compositor(target,rect,allow_visible_overlay=True)
                else:self._check_overlay_hidden();self.validate_compositor(target,rect)
                check_binding()
                if is_cancelled():raise CapturePaused('截图已取消。')
                if image.size!=(width,height):raise CapturePaused('系统截图区域校验失败，已丢弃本帧。')
                if blank_image(image):raise CapturePaused('图形画面为空或受保护；已跳过本帧，稍后自动重试。')
                self.last_backend='windows-graphics-capture-session';self._blank_frames=(None,0)
                out=io.BytesIO();image.save(out,format='PNG');return out.getvalue(),rect
            if allow_visible_overlay:
                raise CapturePaused('可见叠加捕获未返回画面，已跳过本帧。')
            adapter.check_ready() # No v1/GDI while a v2 close/cleanup is pending.
        if allow_visible_overlay:raise CapturePaused('可见叠加请求仅允许持续窗口捕获。')
        if getattr(self,'_wgc',None) is not None:
            from wgc_capture import WgcError,WgcUnavailable
            try:
                image=self._wgc.capture(target,rect,(left,top,width,height),cancelled=is_cancelled,expected_metadata=expected_metadata)
                self.validate_compositor(target,rect)
                check_binding()
                if is_cancelled():raise CapturePaused('截图已取消。')
                if image.size!=(width,height):raise CapturePaused('系统截图区域校验失败，已丢弃本帧。')
                if blank_image(image):raise CapturePaused('图形画面为空或受保护；已跳过本帧，稍后自动重试。')
                self.last_backend='windows-graphics-capture';self._blank_frames=(None,0)
                out=io.BytesIO();image.save(out,format='PNG');return out.getvalue(),rect
            except WgcUnavailable:self._wgc=None # Unsupported API only; exact GDI bounds remain below.
            except WgcError as exc:raise CapturePaused(str(exc)) from exc
        if is_cancelled():raise CapturePaused('截图已取消。')
        check_binding()
        source=self.u.GetDC(target.hwnd)
        image=None
        if source:
            try:image=self._copy_pixels(source,width,height,left,top)
            except CaptureUnavailable:pass # Pixel backend failure only; authorization is never bypassed.
            finally:self.u.ReleaseDC(target.hwnd,source)
        self.validate_compositor(target,rect)
        check_binding()
        if image is None or blank_image(image):
            self.validate_compositor(target,rect)
            check_binding()
            source=self.u.GetDC(None)
            if not source:raise CaptureUnavailable('系统未提供可见窗口画面。')
            try:image=self._copy_pixels(source,width,height,rect.x+left,rect.y+top)
            finally:self.u.ReleaseDC(None,source)
            self.validate_compositor(target,rect)
            check_binding()
            self.last_backend='bounded-compositor'
        else:self.last_backend='window-dc'
        if blank_image(image):
            key=tuple(target.identity);previous,count=getattr(self,'_blank_frames',(None,0));count=count+1 if previous==key else 1;self._blank_frames=(key,count)
            raise CapturePaused('游戏画面持续为空；仍会重试，独占全屏可尝试无边框模式。' if count>=5 else '等待游戏画面；当前帧为空白，稍后自动重试。')
        self._blank_frames=(None,0)
        if is_cancelled():raise CapturePaused('截图已取消。')
        out=io.BytesIO();image.save(out,format='PNG');return out.getvalue(),rect
    def _owned_overlay(self,hwnd):
        pid=W.DWORD()
        if (not self.u.IsWindow(hwnd) or int(self.u.GetAncestor(hwnd,2) or 0)!=hwnd
                or not self.u.GetWindowThreadProcessId(hwnd,ctypes.byref(pid)) or pid.value!=os.getpid()):
            raise CaptureUnavailable('叠加必须是本程序自己的顶层窗口。')
    def _opaque_layered(self,hwnd):
        color=W.DWORD();alpha=W.BYTE();flags=W.DWORD()
        return bool(self.u.GetLayeredWindowAttributes(hwnd,ctypes.byref(color),ctypes.byref(alpha),ctypes.byref(flags))
                    and (color.value,alpha.value,flags.value)==(0,255,2))
    def _check_session_overlay(self,overlay,*,allow_visible_overlay=False):
        from wgc_capture import WgcError
        try:
            self._owned_overlay(overlay.hwnd)
            ctypes.set_last_error(0)
            style=int(self.get_long(overlay.hwnd,-20))&0xffffffff
            affinity=W.DWORD()
            if (ctypes.get_last_error() or style!=overlay.extended_style or not self._opaque_layered(overlay.hwnd)
                    or not self.u.GetWindowDisplayAffinity(overlay.hwnd,ctypes.byref(affinity)) or affinity.value!=0x11
                    or not allow_visible_overlay and self.u.IsWindowVisible(overlay.hwnd)):
                raise CaptureUnavailable('叠加窗口身份、样式、排除状态或隐藏状态已变化。')
        except (CaptureUnavailable,OSError,AttributeError) as exc:
            raise WgcError('stale',str(exc)) from exc
    def configure_overlay(self,hwnd,click_through=True,*,opaque=False):
        """GUI registration only. No helper construction, file I/O or pipe waits.

        opaque=True is a caller contract that Qt's translucent backing was
        disabled before HWND creation. Win32 independently proves the redirected
        opaque layered profile. Existing callers still hide this HWND for capture;
        visible capture requires both an explicit capability and request opt-in.
        """
        adapter=getattr(self,'_persistent',None)
        def invalidate():
            if adapter is not None:adapter.set_overlay()
        try:
            if opaque:self._owned_overlay(hwnd) # Verify before any HWND mutation.
            previous=getattr(self,'_overlay_hwnd',None)
            if previous is not None and previous!=hwnd:invalidate()
            self._overlay_hwnd=hwnd
            ctypes.set_last_error(0)
            current=int(self.get_long(hwnd,-20))&0xffffffff
            if not current and ctypes.get_last_error():raise CaptureUnavailable('无法读取叠加窗口样式，叠加已停用。')
            style=current|0x00080000|0x08000000|0x00000080
            style=(style|0x20) if click_through else (style&~0x20)
            expected=style|0x8
            registered=adapter.overlay if adapter is not None else None
            if registered is not None and (registered.hwnd!=hwnd or registered.extended_style!=current):invalidate()
            flags=0x0001|0x0002|0x0010
            if style!=current:
                invalidate() # Revoke before mutation, even if the OS repairs it.
                ctypes.set_last_error(0)
                previous=self.set_long(hwnd,-20,style)
                if not previous and ctypes.get_last_error():raise CaptureUnavailable('无法设置安全叠加窗口样式，叠加已停用。')
                flags|=0x0020
            if current!=expected:invalidate()
            if not self.u.SetWindowPos(hwnd,W.HWND(-1),0,0,0,0,flags):raise CaptureUnavailable('无法设置非激活置顶叠加，叠加已停用。')
            ctypes.set_last_error(0)
            actual=int(self.get_long(hwnd,-20))&0xffffffff
            if ctypes.get_last_error() or actual!=expected:raise CaptureUnavailable('系统未确认完整的安全叠加样式，叠加已停用。')
            if opaque:
                if not self._opaque_layered(hwnd):
                    invalidate()
                    if not self.u.SetLayeredWindowAttributes(hwnd,0,255,2) or not self._opaque_layered(hwnd):
                        raise CaptureUnavailable('系统未确认不透明叠加窗口，叠加已停用。')
                affinity=W.DWORD()
                exact=bool(self.u.GetWindowDisplayAffinity(hwnd,ctypes.byref(affinity)) and affinity.value==0x11)
                if not exact:
                    invalidate()
                    exact=bool(self.u.SetWindowDisplayAffinity(hwnd,0x11)
                               and self.u.GetWindowDisplayAffinity(hwnd,ctypes.byref(affinity)) and affinity.value==0x11)
                # Recheck all live identity/style/opacity state after API writes.
                self._owned_overlay(hwnd)
                ctypes.set_last_error(0)
                if (int(self.get_long(hwnd,-20))&0xffffffff)!=actual or ctypes.get_last_error() or not self._opaque_layered(hwnd):
                    raise CaptureUnavailable('叠加窗口配置期间状态已变化，叠加已停用。')
                exact=bool(exact and self.u.GetWindowDisplayAffinity(hwnd,ctypes.byref(affinity)) and affinity.value==0x11)
                if adapter is not None:
                    if exact and click_through:adapter.set_overlay(hwnd,actual)
                    else:invalidate()
                return exact
            invalidate() # Legacy translucent UI never gets an idle exemption.
            return bool(self.u.SetWindowDisplayAffinity(hwnd,0x11))
        except BaseException:
            invalidate()
            raise
    def hotkey(self,hwnd,ident=0x5647):return bool(self.u.RegisterHotKey(hwnd,ident,0x4000|0x0002|0x0001,0x4F)) # Ctrl+Alt+O
    def release_hotkey(self,hwnd,ident=0x5647):self.u.UnregisterHotKey(hwnd,ident)


def bounded_roi(width,height,roi):
    if len(roi)!=4 or any(not isinstance(v,(int,float)) or not 0<=v<=1 for v in roi):raise CaptureUnavailable('截图区域必须位于目标窗口内。')
    x,y,w,h=roi
    if w<=0 or h<=0 or x+w>1.00001 or y+h>1.00001:raise CaptureUnavailable('截图区域超出目标窗口。')
    left,top=round(width*x),round(height*y);right,bottom=min(width,round(width*(x+w))),min(height,round(height*(y+h)))
    if right-left<16 or bottom-top<16:raise CaptureUnavailable('截图区域太小。')
    return left,top,right-left,bottom-top


def intersects_rect(a,b):
    return a.left<b.right and b.left<a.right and a.top<b.bottom and b.top<a.bottom


def contains_rect(outer,inner):
    return inner.right>inner.left and inner.bottom>inner.top and outer.left<=inner.left and outer.top<=inner.top and inner.right<=outer.right and inner.bottom<=outer.bottom


def blank_image(image):
    from PIL import ImageStat
    return max(ImageStat.Stat(image.resize((32,32))).stddev)<1

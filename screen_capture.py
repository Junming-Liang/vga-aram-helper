"""Ordinary Windows window metadata + GDI client-area pixel capture.

No process opening/memory reading, DLL injection, input hooks, game API or input
simulation. Only explicitly selected visible foreground window pixels are copied.
"""
from __future__ import annotations
import ctypes
from ctypes import wintypes as W
from dataclasses import dataclass
import io
import os

class CaptureUnavailable(RuntimeError):pass

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
    def __init__(self):
        if os.name!='nt':raise CaptureUnavailable('窗口像素监测目前仅支持 Windows 10/11。')
        self.u=ctypes.WinDLL('user32',use_last_error=True);self.g=ctypes.WinDLL('gdi32',use_last_error=True)
        self._declare()
    def _declare(self):
        def sig(dll,name,args,restype):
            fn=getattr(dll,name);fn.argtypes=args;fn.restype=restype
        for name,args,result in [
            ('IsWindow',[W.HWND],W.BOOL),('IsWindowVisible',[W.HWND],W.BOOL),('IsIconic',[W.HWND],W.BOOL),
            ('GetWindowTextLengthW',[W.HWND],ctypes.c_int),('GetWindowTextW',[W.HWND,W.LPWSTR,ctypes.c_int],ctypes.c_int),
            ('GetClassNameW',[W.HWND,W.LPWSTR,ctypes.c_int],ctypes.c_int),('GetWindowThreadProcessId',[W.HWND,ctypes.POINTER(W.DWORD)],W.DWORD),
            ('GetWindowRect',[W.HWND,ctypes.POINTER(W.RECT)],W.BOOL),('GetClientRect',[W.HWND,ctypes.POINTER(W.RECT)],W.BOOL),('ClientToScreen',[W.HWND,ctypes.POINTER(W.POINT)],W.BOOL),
            ('GetForegroundWindow',[],W.HWND),('GetAncestor',[W.HWND,W.UINT],W.HWND),('GetDC',[W.HWND],W.HDC),('ReleaseDC',[W.HWND,W.HDC],ctypes.c_int),
            ('WindowFromPoint',[W.POINT],W.HWND),('SetWindowDisplayAffinity',[W.HWND,W.DWORD],W.BOOL),
            ('RegisterHotKey',[W.HWND,ctypes.c_int,W.UINT,W.UINT],W.BOOL),('UnregisterHotKey',[W.HWND,ctypes.c_int],W.BOOL),
            ('SetWindowPos',[W.HWND,W.HWND,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,W.UINT],W.BOOL)]:sig(self.u,name,args,result)
        self.enum_cb=ctypes.WINFUNCTYPE(W.BOOL,W.HWND,W.LPARAM)
        sig(self.u,'EnumWindows',[self.enum_cb,W.LPARAM],W.BOOL)
        ptr=ctypes.c_ssize_t
        self.get_long=getattr(self.u,'GetWindowLongPtrW',self.u.GetWindowLongW);self.get_long.argtypes=[W.HWND,ctypes.c_int];self.get_long.restype=ptr
        self.set_long=getattr(self.u,'SetWindowLongPtrW',self.u.SetWindowLongW);self.set_long.argtypes=[W.HWND,ctypes.c_int,ptr];self.set_long.restype=ptr
        for name,args,result in [('CreateCompatibleDC',[W.HDC],W.HDC),('CreateCompatibleBitmap',[W.HDC,ctypes.c_int,ctypes.c_int],W.HBITMAP),('SelectObject',[W.HDC,W.HANDLE],W.HANDLE),('DeleteObject',[W.HANDLE],W.BOOL),('DeleteDC',[W.HDC],W.BOOL),('BitBlt',[W.HDC,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,W.HDC,ctypes.c_int,ctypes.c_int,W.DWORD],W.BOOL),('GetDIBits',[W.HDC,W.HBITMAP,W.UINT,W.UINT,ctypes.c_void_p,ctypes.c_void_p,W.UINT],ctypes.c_int)]:sig(self.g,name,args,result)
    def info(self,hwnd):
        if not self.u.IsWindow(hwnd):raise CaptureUnavailable('目标窗口已关闭。')
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
        if current.identity!=target.identity:raise CaptureUnavailable('目标窗口身份变化，请重新选择。')
        if not self.u.IsWindowVisible(target.hwnd) or self.u.IsIconic(target.hwnd):raise CaptureUnavailable('目标窗口隐藏或最小化，监测暂停。')
        rect=W.RECT();point=W.POINT(0,0)
        if not self.u.GetClientRect(target.hwnd,ctypes.byref(rect)) or not self.u.ClientToScreen(target.hwnd,ctypes.byref(point)):raise CaptureUnavailable('无法读取目标窗口客户区。')
        width,height=rect.right-rect.left,rect.bottom-rect.top
        if min(width,height)<64 or width*height>16_000_000:raise CaptureUnavailable('目标客户区尺寸不支持。')
        return ClientRect(point.x,point.y,width,height)
    def foreground(self,target):return int(self.u.GetAncestor(self.u.GetForegroundWindow(),2) or 0)==target.hwnd
    def validate(self,target,*,check_occlusion=True):
        rect=self.rect(target)
        if not self.foreground(target):raise CaptureUnavailable('目标不在前台；暂停捕获并隐藏旧资料。')
        if check_occlusion:
            for fx in (.1,.5,.9):
                for fy in (.1,.5,.9):
                    hit=self.u.WindowFromPoint(W.POINT(rect.x+int(rect.width*fx),rect.y+int(rect.height*fy)))
                    if int(self.u.GetAncestor(hit,2) or 0)!=target.hwnd:raise CaptureUnavailable('目标窗口被其他窗口遮挡，请移开遮挡后重试。')
        return rect
    def capture(self,target,roi=(0.,0.,1.,1.)):
        """GetDC(selected HWND), not a full-desktop screenshot; no image persistence."""
        rect=self.validate(target)
        left,top,width,height=bounded_roi(rect.width,rect.height,roi)
        source=self.u.GetDC(target.hwnd)
        if not source:raise CaptureUnavailable('系统未提供目标窗口画面。')
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
            # GetDIBits requires the bitmap deselected from the memory DC.
            self.g.SelectObject(dc,old);old=None
            if self.g.GetDIBits(dc,bitmap,0,height,buf,ctypes.byref(header),0)!=height:raise CaptureUnavailable('系统未返回完整窗口像素。')
            if self.validate(target)!=rect:raise CaptureUnavailable('目标窗口在截图期间移动，已丢弃本帧。')
            from PIL import Image,ImageStat
            image=Image.frombytes('RGB',(width,height),buf.raw,'raw','BGRX')
            if max(ImageStat.Stat(image.resize((32,32))).stddev)<1:raise CaptureUnavailable('窗口画面近乎空白；独占全屏/受保护画面可能不支持，请用无边框或窗口模式。')
            out=io.BytesIO();image.save(out,format='PNG');return out.getvalue(),rect
        finally:
            if old and dc:self.g.SelectObject(dc,old)
            if bitmap:self.g.DeleteObject(bitmap)
            if dc:self.g.DeleteDC(dc)
            self.u.ReleaseDC(target.hwnd,source)
    def configure_overlay(self,hwnd,click_through=True):
        style=int(self.get_long(hwnd,-20))|0x00080000|0x08000000|0x00000080 # LAYERED,NOACTIVATE,TOOLWINDOW
        style=(style|0x20) if click_through else (style&~0x20)
        ctypes.set_last_error(0)
        previous=self.set_long(hwnd,-20,style)
        if not previous and ctypes.get_last_error():raise CaptureUnavailable('无法设置安全叠加窗口样式，叠加已停用。')
        if not self.u.SetWindowPos(hwnd,W.HWND(-1),0,0,0,0,0x0001|0x0002|0x0010|0x0020):raise CaptureUnavailable('无法设置非激活置顶叠加，叠加已停用。')
        actual=int(self.get_long(hwnd,-20));required=0x00080000|0x08000000|0x80|0x8
        if actual&required!=required or bool(actual&0x20)!=bool(click_through):raise CaptureUnavailable('系统未确认鼠标穿透/非激活样式，叠加已停用。')
        # Exclusion is best effort; the UI ALWAYS hides this window before capture.
        return bool(self.u.SetWindowDisplayAffinity(hwnd,0x11))
    def hotkey(self,hwnd,ident=0x5647):return bool(self.u.RegisterHotKey(hwnd,ident,0x4000|0x0002|0x0001,0x4F)) # Ctrl+Alt+O
    def release_hotkey(self,hwnd,ident=0x5647):self.u.UnregisterHotKey(hwnd,ident)


def bounded_roi(width,height,roi):
    if len(roi)!=4 or any(not isinstance(v,(int,float)) or not 0<=v<=1 for v in roi):raise CaptureUnavailable('截图区域必须位于目标窗口内。')
    x,y,w,h=roi
    if w<=0 or h<=0 or x+w>1.00001 or y+h>1.00001:raise CaptureUnavailable('截图区域超出目标窗口。')
    left,top=round(width*x),round(height*y);right,bottom=min(width,round(width*(x+w))),min(height,round(height*(y+h)))
    if right-left<16 or bottom-top<16:raise CaptureUnavailable('截图区域太小。')
    return left,top,right-left,bottom-top

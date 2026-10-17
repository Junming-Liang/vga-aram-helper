"""Native Windows owned-window region and mouse-gap proof, no game interaction.

Run in a native Windows Qt process (not offscreen). This is NOT WGC exclusion
proof; the existing owned visible-overlay capture harness must also pass.
"""
import ctypes
from ctypes import wintypes as W
import json
import os
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
if os.name!='nt':raise SystemExit('This proof requires native Windows')
from PySide6 import QtCore,QtWidgets
from native_ui import Overlay
from screen_capture import Win32Capture,ClientRect
from card_badges import native_region
from types import SimpleNamespace

def fixture():
    candidates=[dict(name=f"候选{i+1}",box=[[90+i*270,150],[180+i*270,150],[180+i*270,180],[90+i*270,180]]) for i in range(3)]
    geometry=SimpleNamespace(rects=((.05,.2,.25,.6),(.35,.2,.25,.6),(.65,.2,.25,.6)),size=(900,600),space="frame")
    cards=[dict(slot=i+1,name=f"候选{i+1}",sourceTier=f"T{i+1}",sourceTierLabel="虎牙公开源评级") for i in range(3)]
    return candidates,geometry,cards

app=QtWidgets.QApplication([])
if app.platformName()!='windows':raise SystemExit('Requires native windows Qt platform')
# One owned synthetic target with no hooks, injection, or game process access.
target=QtWidgets.QWidget();target.setWindowTitle('VGA owned badge-region fixture');target.resize(900,600);target.show();app.processEvents()
capture=Win32Capture(persistent_sessions=False)
overlay=Overlay(capture);overlay.winId();overlay.configure()
c,g,cards=fixture();overlay.set_candidate_geometry(c,{'width':900,'height':600},(0,0,1,1),g);overlay.set_cards('原创测试英雄',cards)
rectw=W.RECT();capture.u.GetWindowRect(int(target.winId()),ctypes.byref(rectw))
# Client origin is mapped physically, including title-bar nonclient offset.
point=W.POINT(0,0);capture.u.ClientToScreen(int(target.winId()),ctypes.byref(point));client=W.RECT();capture.u.GetClientRect(int(target.winId()),ctypes.byref(client))
rect=ClientRect(point.x,point.y,client.right,client.bottom)
try:
    overlay.show_at(rect,None);app.processEvents();assert overlay.isVisible()
    native_region(int(overlay.winId()),overlay._badge_regions,verify_only=True)
    assert len(overlay._badge_regions)==3
    user=ctypes.WinDLL('user32',use_last_error=True);user.WindowFromPoint.argtypes=[W.POINT];user.WindowFromPoint.restype=W.HWND
    actual=W.RECT();capture.u.GetWindowRect(int(overlay.winId()),ctypes.byref(actual))
    first,second=overlay._badge_regions[:2];gap=actual.left+(first[0]+first[2]+second[0])//2
    assert user.WindowFromPoint(W.POINT(gap,actual.top+10))!=int(overlay.winId()),'Gap must not hit the overlay'
    hwnd=int(overlay.winId());overlay.hide('capture_pending');app.processEvents()
    assert not capture.u.IsWindowVisible(hwnd);capture._check_overlay_hidden()
    cards[1]['pending']=True;overlay.set_cards('原创测试英雄',cards);overlay.show_at(rect,None);app.processEvents()
    native_region(hwnd,overlay._badge_regions,verify_only=True);assert len(overlay._badge_regions)==2
    overlay.clear_candidate_geometry();app.processEvents();assert not capture.u.IsWindowVisible(hwnd)
    overlay.close();app.processEvents();assert not capture.u.IsWindowVisible(hwnd)
    print(json.dumps({'status':'passed','platform':app.platformName(),'dpr':overlay.devicePixelRatioF(),'checks':['exact physical region equals three disjoint badge rectangles','gap does not hit overlay HWND','capture hide covers every region','partial slot removes old middle grade and region','geometry revocation and close hide all regions'],'scope':'Owned native Windows widgets only; not WGC or game compatibility proof'},ensure_ascii=False))
finally:
    overlay.close();target.close();capture.retire_session()

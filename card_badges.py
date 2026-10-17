"""Three independent opaque badge regions on one exact-owned Qt HWND.

No new overlay exemption: the native window region is a bounded union of the
visible badges. Pixels and input between badges belong to the game. Placement
requires separately proven card borders; OCR title boxes alone never suffice.
"""
from __future__ import annotations
from dataclasses import dataclass
import ctypes
from ctypes import wintypes as W
import math
import os
from PySide6 import QtCore, QtGui, QtWidgets
from screen_capture import CaptureUnavailable

from badge_contract import WIDTH, MIN_WIDTH, HEIGHT, GAP, TIER_ROW_HEIGHT, HINT_FONT_SIZE, choose_width, align_physical_regions, top_gap, logical_hull_from_physical
COLORS = {'T1':'#F2CE86','T2':'#79D9EF','T3':'#B2BED2','T4':'#AEB6C2'}


def _finite(value):
    return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)


@dataclass(frozen=True)
class BadgeAnchors:
    names: tuple
    rects: tuple


def accepted_anchors(candidates, image_size, roi, geometry):
    """Bind each proven card to its actual OCR title and original physical slot."""
    if geometry is None:return None
    try:
        size=(image_size['width'],image_size['height'])
        if len(geometry.rects)!=3:return None
        frame_space=getattr(geometry,'space','crop')=='frame'
        if not frame_space and tuple(geometry.size)!=size:return None
        if len(roi)!=4 or not all(_finite(v) for v in roi):return None
        rx,ry,rw,rh=roi
        if min(rx,ry)<0 or min(rw,rh)<=0 or rx+rw>1 or ry+rh>1:return None
        names=[];rects=[];previous=-1.
        for bounds in geometry.rects:
            if len(bounds)!=4 or not all(_finite(v) for v in bounds):return None
            x,y,w,h=bounds
            if min(x,y)<0 or min(w,h)<=0 or x+w>1.000001 or y+h>1.000001 or x<previous:return None
            previous=x+w
            matches=[]
            for candidate in candidates:
                box=candidate.get('box')
                if not box or len(box)!=4:continue
                xs=[p[0]/size[0] for p in box];ys=[p[1]/size[1] for p in box]
                if frame_space:xs=[rx+v*rw for v in xs];ys=[ry+v*rh for v in ys]
                if x<=min(xs)<=max(xs)<=x+w and y<=min(ys)<=max(ys)<=y+h:
                    matches.append(candidate.get('name'))
            names.append(matches[0] if len(matches)==1 and isinstance(matches[0],str) else None)
            rects.append((x,y,w,h) if frame_space else (rx+x*rw,ry+y*rh,w*rw,h*rh))
        return BadgeAnchors(tuple(names),tuple(rects))
    except (AttributeError,KeyError,TypeError,ValueError,ZeroDivisionError,IndexError):return None


def badge_placement(rect,dpr,anchors,slots):
    """Return physical window bounds and logical rectangles; never clamp to cards."""
    if not _finite(dpr) or not .5<=dpr<=10:raise CaptureUnavailable('叠加缩放无效。')
    if anchors is None or len(anchors.rects)!=3:raise CaptureUnavailable('尚未确认强化卡边界，评级已隐藏。')
    centers=[(x+w/2)*rect.width for x,y,w,h in anchors.rects]
    try:logical_width=choose_width(centers,dpr)
    except ValueError:raise CaptureUnavailable('强化卡间距不足，评级已隐藏。')
    physical=[]
    for slot in slots:
        x,y,w,h=anchors.rects[slot]
        width=math.ceil(logical_width*dpr);height=math.ceil(HEIGHT*dpr)
        left=round(rect.x+(x+w/2)*rect.width-width/2)
        top=math.floor(rect.y+y*rect.height-top_gap(dpr)-height)
        if left<rect.x or top<rect.y or left+width>rect.x+rect.width or top+height>rect.y+rect.height:
            raise CaptureUnavailable('强化卡上方空间不足，评级已隐藏。')
        physical.append((left,top,width,height))
    if not physical:return None
    left=min(p[0] for p in physical);top=min(p[1] for p in physical)
    # QWidget child positions live on an integer logical grid. Snap the native
    # region to that same grid, then ceil the hull in logical units before its
    # physical conversion. Otherwise a 917px hull at 2x becomes a 458-DIP parent
    # while its right child needs 459 DIP, clipping the last badge.
    bounds,regions=align_physical_regions(physical,dpr,logical_width)
    left,top,hull_width,hull_height=bounds;right=left+hull_width;bottom=top+hull_height
    if left<rect.x or top<rect.y or right>rect.x+rect.width or bottom>rect.y+rect.height:
        raise CaptureUnavailable('强化卡评级缩放范围越过客户区，已隐藏。')
    if bottom-top>rect.height//2:raise CaptureUnavailable('强化卡定位不一致，评级已隐藏。')
    for i,a in enumerate(regions):
        for b in regions[i+1:]:
            if a[0]<b[0]+b[2] and b[0]<a[0]+a[2] and a[1]<b[1]+b[3] and b[1]<a[1]+a[3]:
                raise CaptureUnavailable('强化卡评级区域重叠，已隐藏。')
    return (left,top,right-left,bottom-top),regions


def native_region(hwnd,regions,*,verify_only=False):
    """Install and read back the exact disjoint opaque physical HWND region.

    SetWindowRgn takes ownership only on success. EqualRgn verifies the actual
    shape, not merely its bounding rectangle; no arbitrary HWND is registered.
    """
    if os.name!='nt' or QtGui.QGuiApplication.platformName()!='windows':return
    user=ctypes.WinDLL('user32',use_last_error=True);gdi=ctypes.WinDLL('gdi32',use_last_error=True)
    gdi.CreateRectRgn.argtypes=[ctypes.c_int]*4;gdi.CreateRectRgn.restype=W.HANDLE
    gdi.CombineRgn.argtypes=[W.HANDLE,W.HANDLE,W.HANDLE,ctypes.c_int];gdi.CombineRgn.restype=ctypes.c_int
    gdi.DeleteObject.argtypes=[W.HANDLE];gdi.DeleteObject.restype=W.BOOL
    gdi.EqualRgn.argtypes=[W.HANDLE,W.HANDLE];gdi.EqualRgn.restype=W.BOOL
    user.SetWindowRgn.argtypes=[W.HWND,W.HANDLE,W.BOOL];user.SetWindowRgn.restype=ctypes.c_int
    user.GetWindowRgn.argtypes=[W.HWND,W.HANDLE];user.GetWindowRgn.restype=ctypes.c_int
    expected=actual=installed=None
    try:
        expected=gdi.CreateRectRgn(0,0,0,0);actual=gdi.CreateRectRgn(0,0,0,0);installed=gdi.CreateRectRgn(0,0,0,0)
        if not expected or not actual or not installed:raise CaptureUnavailable('无法建立评级窗口区域。')
        for x,y,w,h in regions:
            part=gdi.CreateRectRgn(x,y,x+w,y+h)
            if not part:raise CaptureUnavailable('无法建立评级区域。')
            try:
                if not gdi.CombineRgn(expected,expected,part,2):raise CaptureUnavailable('无法合并评级区域。')
            finally:gdi.DeleteObject(part)
        if not gdi.CombineRgn(installed,expected,expected,5):raise CaptureUnavailable('无法复制评级区域。')
        if not verify_only:
            if not user.SetWindowRgn(hwnd,installed,True):raise CaptureUnavailable('无法设置评级窗口区域。')
            installed=None
        if user.GetWindowRgn(hwnd,actual)<=0 or not gdi.EqualRgn(expected,actual):raise CaptureUnavailable('系统未确认独立评级区域，已隐藏。')
    finally:
        for handle in (expected,actual,installed):
            if handle:gdi.DeleteObject(handle)


def clear_native_region(hwnd):
    """Remove our native region on the same HWND before a full reference panel.

    GetWindowRgn returns ERROR (0) when no region is assigned. Prove HWND is
    still valid separately, so an invalid window cannot masquerade as removal.
    """
    if os.name!='nt' or QtGui.QGuiApplication.platformName()!='windows':return
    user=ctypes.WinDLL('user32',use_last_error=True);gdi=ctypes.WinDLL('gdi32',use_last_error=True)
    user.SetWindowRgn.argtypes=[W.HWND,W.HANDLE,W.BOOL];user.SetWindowRgn.restype=ctypes.c_int
    user.GetWindowRgn.argtypes=[W.HWND,W.HANDLE];user.GetWindowRgn.restype=ctypes.c_int
    user.IsWindow.argtypes=[W.HWND];user.IsWindow.restype=W.BOOL
    gdi.CreateRectRgn.argtypes=[ctypes.c_int]*4;gdi.CreateRectRgn.restype=W.HANDLE
    gdi.DeleteObject.argtypes=[W.HANDLE];gdi.DeleteObject.restype=W.BOOL
    actual=gdi.CreateRectRgn(0,0,0,0)
    if not actual:raise CaptureUnavailable('无法核验资料窗口区域。')
    try:
        if not user.IsWindow(hwnd) or not user.SetWindowRgn(hwnd,None,True):raise CaptureUnavailable('无法清除旧评级窗口区域。')
        if not user.IsWindow(hwnd) or user.GetWindowRgn(hwnd,actual)!=0:raise CaptureUnavailable('旧评级窗口区域仍存在，已隐藏。')
    finally:gdi.DeleteObject(actual)


class TierBadge(QtWidgets.QWidget):
    def __init__(self,parent):
        super().__init__(parent)
        self.setFixedSize(WIDTH,HEIGHT);self.tier='';self.source='源评级';self.hint='';self.display_hint='';self.accent='#C1C8D2'
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    def set_card(self,card,rechecking=False,identity_provenance=""):
        self.tier=str(card.get('sourceTier') or '暂无评级');self.accent=COLORS.get(self.tier,'#C1C8D2')
        self.identity_provenance=identity_provenance
        warning='HUD未复核' if '来自本局选人' in identity_provenance and 'HUD未复核' in identity_provenance else '本局已确认' if '头像未重新确认' in identity_provenance else ''
        self._pending_identity=bool(warning and rechecking)
        self.source=warning or ('复核中' if rechecking else '演示评级' if card.get('sourceTierLabel')=='虚构源评级（演示）' else '源评级')
        hint=card.get('sourceHint')
        self.hint=hint.strip() if isinstance(hint,str) else ''
        self._fit_hint()
        self.setToolTip((identity_provenance+'\n' if warning else '')+('候选复核中\n' if warning and rechecking else '')+self.hint)
        self.setAccessibleName(f"选项 {card['slot']} · {card['name']} · {self.tier} · {self.source}"+(f' · {identity_provenance}' if warning else '')+(' · 候选复核中' if warning and rechecking else '')+(f' · {self.hint}' if self.hint else ''))
        self.update()
    def set_title_checking(self,slot):
        # No stale grade, source hint, hero provenance or identity is exposed
        # visually or through accessibility while title meaning is unproven.
        self.tier='';self.source='复核中';self.hint='';self.display_hint=''
        self.accent='#C1C8D2';self.identity_provenance='';self._pending_identity=False
        self.setToolTip('正在核对当前候选');self.setAccessibleDescription('')
        self.setAccessibleName(f'选项 {slot} · 正在核对当前候选')
        self.update()
    def _fit_hint(self):
        font=self.font();font.setPixelSize(HINT_FONT_SIZE);font.setWeight(QtGui.QFont.Weight.Normal)
        self.display_hint=QtGui.QFontMetrics(font).elidedText(('复核中 · ' if getattr(self,'_pending_identity',False) else '')+self.hint,QtCore.Qt.TextElideMode.ElideRight,self.width()-24)
    def resizeEvent(self,event):
        self._fit_hint();super().resizeEvent(event)
    def hint_text_layout(self):
        font=QtGui.QFont(self.font());font.setPixelSize(HINT_FONT_SIZE);font.setWeight(QtGui.QFont.Weight.Normal)
        height=QtGui.QFontMetrics(font).height()
        return font,QtCore.QRect(12,HEIGHT-3-height,self.width()-24,height)

    def top_text_layout(self):
        """Measure the exact paint fonts; never shrink identity warnings.

        The fixed 50px source column clipped Windows CJK fallback glyphs.
        Reclaim unused tier space instead; missing tier uses the compact 暂无 label.
        """
        source_font=QtGui.QFont(self.font());source_font.setPixelSize(9 if self.source in ('HUD未复核','本局已确认') else 10)
        source_font.setWeight(QtGui.QFont.Weight.Normal)
        source_width=QtGui.QFontMetrics(source_font).horizontalAdvance(self.source)
        source_rect=QtCore.QRect(self.width()-4-source_width,0,source_width,TIER_ROW_HEIGHT)
        tier_font=QtGui.QFont(self.font());tier_font.setPixelSize(10 if self.tier=='暂无评级' else 20)
        tier_font.setWeight(QtGui.QFont.Weight.DemiBold)
        tier_lines=('暂无',) if self.tier=='暂无评级' else (self.tier,)
        tier_width=max(QtGui.QFontMetrics(tier_font).horizontalAdvance(line) for line in tier_lines)
        tier_rect=QtCore.QRect(8,0,tier_width,TIER_ROW_HEIGHT)
        self.display_source=self.source
        if tier_rect.right()+4>source_rect.left():
            self.display_source={'HUD未复核':'HUD待核','本局已确认':'本局已核'}.get(self.source,self.source)
            source_width=QtGui.QFontMetrics(source_font).horizontalAdvance(self.display_source)
            source_rect=QtCore.QRect(self.width()-4-source_width,0,source_width,TIER_ROW_HEIGHT)
        return source_font,source_rect,tier_font,tier_rect,tier_lines

    def paintEvent(self,event):
        # Decorative chamfers are drawn INSIDE an opaque rectangular region.
        # No alpha/glow/shadow can change the capture or input contract.
        width=self.width()
        p=QtGui.QPainter(self);p.fillRect(self.rect(),QtGui.QColor('#0B141E'))
        p.setPen(QtGui.QPen(QtGui.QColor('#46647A'),1))
        p.drawPolygon(QtGui.QPolygon([QtCore.QPoint(x,y) for x,y in ((1,7),(7,1),(width-8,1),(width-1,8),(width-1,HEIGHT-7),(width-7,HEIGHT-1),(8,HEIGHT-1),(1,HEIGHT-8))]))
        p.setPen(QtGui.QPen(QtGui.QColor(self.accent),2));p.drawLine(8,1,34,1);p.drawLine(width-26,HEIGHT-1,width-8,HEIGHT-1)
        source_font,source_rect,font,tier_rect,tier_lines=self.top_text_layout()
        p.setFont(font);p.setPen(QtGui.QColor(self.accent))
        p.drawText(tier_rect,QtCore.Qt.AlignmentFlag.AlignVCenter,tier_lines[0])
        p.setFont(source_font);p.setPen(QtGui.QColor('#AFC3D0'))
        p.drawText(source_rect,QtCore.Qt.AlignmentFlag.AlignVCenter,self.display_source)
        if self.display_hint:
            hint_font,hint_rect=self.hint_text_layout();p.setFont(hint_font);p.setPen(QtGui.QColor('#D0DEE8'))
            p.drawText(hint_rect,QtCore.Qt.AlignmentFlag.AlignVCenter,self.display_hint)
        p.end()


class BadgeOverlayMixin:
    """Controller-compatible badge renderer; legacy hero reference stays separate."""
    def _init_badges(self):
        self._titles_pending=False;self._badge_anchors=None;self._badge_regions=();self._badge_widgets=[TierBadge(self) for _ in range(3)]
        for badge in self._badge_widgets:badge.hide()
    def set_title_checking(self,value):
        value=bool(value)
        if self._titles_pending==value:return
        self._titles_pending=value
        self._refresh_badges()
        self.heading.setText('候选复核中' if value else self._previous_heading if self._rechecking else self._compact_heading if self._compact else self._full_heading)
        self.overlay_debug(phase='rechecking',visible=self.isVisible(),rechecking=value,reason='title_recheck')
    def clear_candidate_geometry(self):
        if self.cards:self.hide('card_geometry_missing')
        self._badge_anchors=None;self._placed_key=None
    def set_candidate_geometry(self,candidates,image_size,roi,card_geometry):
        anchors=accepted_anchors(candidates,image_size,roi,card_geometry)
        if anchors!=self._badge_anchors:
            # A newly recognized but still unconfirmed hidden slot cannot
            # move or rename any visible badge. Keep those exact regions.
            active=[card['slot']-1 for card in self.cards if not card.get('pending')]
            unchanged=bool(anchors is not None and self._badge_anchors is not None
                and anchors.rects==self._badge_anchors.rects
                and all(anchors.names[i]==self._badge_anchors.names[i] for i in active))
            if not unchanged:
                if self.cards:self.hide('card_geometry_changed')
                self._placed_key=None
            self._badge_anchors=anchors
        return anchors is not None
    def _set_badge_cards(self,hero,cards,source_date,source_version,confirmation):
        # Slot identity comes from the controller, never tier order or list sort.
        slots={card.get('slot'):dict(card) for card in cards if isinstance(card,dict)}
        if len(slots)!=len(cards) or any(type(slot) is not int or slot not in (1,2,3) for slot in slots):
            self.hide('invalid_slots');self.cards=[];return
        signature=(hero,repr(cards),source_date,source_version,confirmation)
        if getattr(self,'_card_signature',None)==signature and self.reference is None:
            self.set_rechecking(False);self.set_title_checking(False);return
        ordered=[slots[s] for s in sorted(slots)]
        # Identity provenance (fresh portrait versus carried in-game identity),
        # source text and tiers only repaint the fixed-size children. Rebuilding
        # the HWND region for those changes hides the overlay every OCR cycle
        # and revokes the otherwise unchanged native capture enrollment.
        def identities(items):
            return tuple((card['slot'],card['name'],bool(card.get('pending'))) for card in items)
        previous=getattr(self,'_card_signature',None)
        repaint_only=bool(self.reference is None and previous is not None
                          and previous[0]==hero and identities(self.cards)==identities(ordered))
        if not repaint_only:
            self.hide('cards_changed');self._placed_key=None;self._layout_revision+=1
            self.panel.hide();self.setMinimumSize(0,0)
        self._card_signature=signature;self.cards=ordered
        self.reference=None;self._rechecking=False;self._titles_pending=False
        self._identity_provenance=confirmation
        self._full_heading=self._compact_heading=f'{hero} · {confirmation}';self._previous_heading=f'{hero} · 上次候选复核中'
        self.tier_labels=[]
        for slot,badge in enumerate(self._badge_widgets,1):
            if not repaint_only:badge.hide()
            card=slots.get(slot)
            if card and not card.get('pending'):
                badge.set_card(card,identity_provenance=confirmation);self.tier_labels.append(badge)
            else:badge.set_title_checking(slot)
    def _leave_badges(self):
        self.hide('reference_changed')
        for badge in self._badge_widgets:badge.hide()
        self.clearMask();clear_native_region(int(self.winId()));self._badge_regions=();self.panel.show()
    def _refresh_badges(self):
        for card in self.cards:
            badge=self._badge_widgets[card['slot']-1]
            if self._titles_pending or card.get('pending'):badge.set_title_checking(card['slot'])
            else:badge.set_card(card,self._rechecking,self._identity_provenance)
    def _ensure_badge_bounds(self,bounds):
        if not self.capture:return
        hwnd=int(self.winId())
        def actual_bounds():
            actual=W.RECT()
            if not self.capture.u.GetWindowRect(hwnd,ctypes.byref(actual)):
                raise CaptureUnavailable('无法复核评级实际位置。')
            return actual.left,actual.top,actual.right-actual.left,actual.bottom-actual.top
        if actual_bounds()!=bounds:
            if not self.capture.u.SetWindowPos(hwnd,W.HWND(-1),*bounds,0x0010):
                raise CaptureUnavailable('无法校正评级缩放位置。')
            if actual_bounds()!=bounds:raise CaptureUnavailable('评级实际缩放位置不一致，已隐藏。')

    def _show_badges_at(self,rect,target):
        self._show_reason='partial_confirmed' if any(card.get('pending') for card in self.cards) else 'confirmed'
        try:
            anchors=self._badge_anchors
            slots=[card['slot']-1 for card in self.cards if not card.get('pending') and anchors is not None and anchors.names[card['slot']-1]==card['name']]
            if not slots:self.hide('card_geometry_missing');return
            # Only the names with actual native regions affect placement.
            # An invisible unknown slot has no name/grade/capture exemption.
            anchors=BadgeAnchors(tuple(name if i in slots else None for i,name in enumerate(anchors.names)),anchors.rects)
            hwnd=int(self.winId());dpr=float(self.windowHandle().devicePixelRatio())
            key=(rect,self._layout_revision,dpr,anchors,tuple(slots))
            if self._placed_key==key:
                self.show();self.configure();self._ensure_badge_bounds(self._badge_bounds);native_region(hwnd,self._badge_regions,verify_only=True)
                if self.capture:self._verify_rect(rect)
                if float(self.windowHandle().devicePixelRatio())==dpr:return
            self.hide('layout')
            retire=getattr(self.capture,'retire_session',None)
            if retire:retire()
            if self.capture:
                if not self.capture.u.SetWindowPos(hwnd,W.HWND(-1),rect.x+rect.width//2,rect.y+rect.height//2,0,0,0x0001|0x0010):
                    raise CaptureUnavailable('无法定位评级所属显示器。')
                dpr=float(self.windowHandle().devicePixelRatio())
            for _ in range(3):
                bounds,regions=badge_placement(rect,dpr,anchors,slots)
                x,y,width,height=bounds
                self.resize(*logical_hull_from_physical(width,height,dpr))
                if self.capture:
                    if not self.capture.u.SetWindowPos(hwnd,W.HWND(-1),x,y,width,height,0x0010):raise CaptureUnavailable('无法定位独立评级。')
                else:self.move(round(x/dpr),round(y/dpr))
                final_dpr=float(self.windowHandle().devicePixelRatio())
                if final_dpr!=dpr:dpr=final_dpr;continue
                region=QtGui.QRegion()
                for badge in self._badge_widgets:badge.hide()
                for slot,(bx,by,bw,bh) in zip(slots,regions):
                    logical=QtCore.QRect(round(bx/dpr),round(by/dpr),round(bw/dpr),HEIGHT)
                    region=region.united(QtGui.QRegion(logical));badge=self._badge_widgets[slot];badge.setFixedSize(logical.size());badge.move(logical.topLeft());badge.show()
                self.setMask(region)
                native_region(hwnd,regions)
                self._badge_regions=regions;self._badge_bounds=bounds
                self.show();self.configure();self._ensure_badge_bounds(bounds);native_region(hwnd,regions,verify_only=True)
                if self.capture:self._verify_rect(rect)
                final_dpr=float(self.windowHandle().devicePixelRatio())
                if final_dpr==dpr:
                    self._placed_key=(rect,self._layout_revision,dpr,anchors,tuple(slots));return
                self.hide('layout');dpr=final_dpr
            raise CaptureUnavailable('评级跨显示器缩放持续变化，等待稳定。')
        except Exception:
            self._placed_key=None;self.hide('layout_error');raise

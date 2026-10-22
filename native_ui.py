"""Native QtWidgets controls and a nonactivating Windows pixel-only overlay.

No browser engine. Screenshot buffers stay in memory. Session handoff queries
only OS process path/creation metadata, never game process memory.
"""
from __future__ import annotations
import ctypes
import hashlib
from ctypes import wintypes as W
import json
import math
import os
from pathlib import Path,PureWindowsPath
import threading
import traceback
import time
from PySide6 import QtCore,QtGui,QtWidgets
from native_state import RecognitionState,display_cards,automatic_candidates
from frame_ocr_cache import FrameOCRCache
from hero_identity_continuity import HeroIdentityContinuity
from monitor_preferences import load_preferences,save_preferences
from partial_candidates import EMPTY_SLOTS,PartialCandidateState
from local_debug import LocalDebugLog,classify_worker_error
from portrait_display import PortraitDisplayBank,cached_roster_fingerprint
from latest_capture_frame import LatestCaptureFrame,CapturedFrame
from screen_capture import Win32Capture,CaptureUnavailable,CapturePaused

ROOT=Path(__file__).resolve().parent
APP_NAME='VGA乱斗助手'
STYLE="""
QWidget { color:#101828; font-family:"Segoe UI","Microsoft YaHei UI","Microsoft YaHei","Noto Sans CJK SC"; font-size:13px; }
ControlWindow,QDialog,QMessageBox { background:#FFFFFF; }
QWidget#scroll-content,QWidget#dashboard,QScrollArea,QScrollArea > QWidget > QWidget { background:#FFFFFF; border:0; }
QLabel { background:transparent; border:0; }
QLabel#muted,QLabel#field-label { color:#687385; font-size:12px; }
QLabel#hero-title { font-size:30px; font-weight:600; }
QLabel#section-title { font-size:18px; font-weight:600; }
QLabel#status-chip { color:#687385; font-size:13px; }
QLabel#status-chip[state="confirmed"] { color:#24745D; }
QLabel#status-chip[state="waiting"] { color:#687385; }
QLabel#status-chip[state="working"] { color:#0067ED; }
QLabel#status-chip[state="provisional"] { color:#8D6600; }
QLabel#status-chip[state="error"] { color:#B42318; }
QFrame#section { background:#FFFFFF; border:1px solid #E4E9F0; border-radius:10px; }
QFrame#candidate-card { background:#FFFFFF; border:1px solid #E4E9F0; border-radius:12px; }
QLabel#candidate-name { font-size:18px; font-weight:600; }
QLabel#slot-mark { color:#8390A4; font-size:24px; font-weight:500; }
QLabel#tier-pill { color:#536075; background:#F0F3F7; border-radius:7px; padding:4px 10px; font-weight:600; }
QLabel#tier-pill[known="true"] { color:#0067ED; background:#EAF3FF; }
QFrame#divider { background:#E6EAF0; max-height:1px; border:0; }
QLineEdit,QComboBox,QSpinBox { background:#FFFFFF; border:1px solid #D9E0E9; border-radius:6px; padding:5px 8px; min-height:20px; selection-background-color:#DCEBFF; }
QLineEdit:focus,QComboBox:focus,QSpinBox:focus { border:2px solid #0067ED; padding:4px 7px; }
QComboBox QAbstractItemView { background:#FFFFFF; color:#101828; selection-background-color:#EAF3FF; border:1px solid #D9E0E9; }
QPushButton,QToolButton { background:transparent; border:1px solid #D9E0E9; border-radius:7px; padding:7px 12px; min-height:20px; }
QPushButton:hover,QToolButton:hover { background:#EDF3FC; border-color:#B7C9E2; }
QPushButton:focus,QToolButton:focus { border:2px solid #0067ED; padding:6px 11px; }
QPushButton#primary-action { background:#0067ED; color:#FFFFFF; border-color:#0067ED; font-size:14px; font-weight:600; }
QPushButton#primary-action:hover { background:#005BD3; }
QPushButton#primary-action:disabled { color:#8798AE; background:#E8EDF5; border-color:#E8EDF5; }
QPushButton:disabled,QToolButton:disabled,QLineEdit:disabled,QComboBox:disabled { color:#8390A4; background:#EDF1F6; border-color:#E3E8EF; }
QToolButton#utility { border:0; color:#687385; padding:4px 8px; }
QToolButton#utility:focus { border:2px solid #0067ED; padding:2px 6px; }
QCheckBox { spacing:8px; padding:3px 0; color:#536075; }
QCheckBox::indicator { width:16px; height:16px; }
QCheckBox:focus { outline:1px solid #0067ED; }
QScrollBar:vertical { background:#FFFFFF; width:8px; margin:0; }
QScrollBar::handle:vertical { background:#CDD6E3; border-radius:4px; min-height:24px; }
QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical { height:0; }
QToolTip { background:#FFFFFF; color:#101828; border:1px solid #D9E0E9; padding:5px; }
"""

def label(text='',muted=False):
    widget=QtWidgets.QLabel(text);widget.setTextFormat(QtCore.Qt.TextFormat.PlainText);widget.setWordWrap(True)
    if muted:widget.setObjectName('muted')
    return widget

class Switch(QtWidgets.QCheckBox):
    def sizeHint(self):
        return QtCore.QSize(42+self.fontMetrics().horizontalAdvance(self.text())+8,30)
    def minimumSizeHint(self):return self.sizeHint()
    def hitButton(self,pos):return self.rect().contains(pos)
    def keyboard_focus_visible(self):
        return self.hasFocus() and self.window().testAttribute(QtCore.Qt.WidgetAttribute.WA_KeyboardFocusChange)
    def paintEvent(self,event):
        painter=QtGui.QPainter(self);painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        track=QtCore.QRectF(1,(self.height()-20)/2,34,20)
        painter.setPen(QtCore.Qt.PenStyle.NoPen);painter.setBrush(QtGui.QColor('#0067ED' if self.isChecked() else '#C9D1DD'));painter.drawRoundedRect(track,10,10)
        painter.setBrush(QtGui.QColor('#FFFFFF'));painter.drawEllipse(QtCore.QRectF(18 if self.isChecked() else 4,track.y()+3,14,14))
        painter.setPen(QtGui.QColor('#536075' if self.isEnabled() else '#8390A4'));painter.drawText(QtCore.QRect(44,0,self.width()-44,self.height()),QtCore.Qt.AlignmentFlag.AlignVCenter,self.text())
        if self.keyboard_focus_visible():
            painter.setBrush(QtCore.Qt.BrushStyle.NoBrush);painter.setPen(QtGui.QPen(QtGui.QColor('#0067ED'),1));painter.drawRoundedRect(self.rect().adjusted(0,0,-1,-1),5,5)
        painter.end()

class TaskSignals(QtCore.QObject):
    result=QtCore.Signal(str,object,int)
    error=QtCore.Signal(str,str,int)

from card_badges import BadgeOverlayMixin

class Overlay(BadgeOverlayMixin,QtWidgets.QWidget):
    def __init__(self,capture=None,portrait_bank=None,hero_id_lookup=None,debug_log=None,*,before_capture_retirement=None):
        super().__init__(None,QtCore.Qt.WindowType.Tool|QtCore.Qt.WindowType.FramelessWindowHint|QtCore.Qt.WindowType.WindowStaysOnTopHint|QtCore.Qt.WindowType.WindowDoesNotAcceptFocus)
        self.capture=capture;self.click_through=True;self.cards=[];self.reference=None;self._layout_revision=0;self._placed_key=None;self._detail_labels=[];self._compact=False;self._rechecking=False
        self.portrait_bank=portrait_bank or PortraitDisplayBank();self.hero_id_lookup=hero_id_lookup;self._portrait_revision=None;self.hero_portrait=None
        self._last_hidden_at=None;self.debug_log=debug_log;self._hide_reason='unknown';self._show_reason='unknown'
        self._before_capture_retirement=before_capture_retirement
        self._capture_retirement_pending=False
        # The validated redirected Windows renderer has no per-pixel alpha.
        # Set this before winId()/show; changing it later can recreate the HWND.
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground,False)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_OpaquePaintEvent,True)
        self.setWindowOpacity(1.0)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setWindowTitle(APP_NAME+' · 资料叠加');self.setStyleSheet(STYLE+'\nOverlay{background:#FAFCFF;}')
        self.setWindowFlag(QtCore.Qt.WindowType.WindowTransparentForInput,True)
        layout=QtWidgets.QVBoxLayout(self);layout.setContentsMargins(0,0,0,0)
        self.panel=QtWidgets.QFrame();self.panel.setObjectName('overlay-panel');self.panel.setStyleSheet('#overlay-panel{background:#FAFCFF;border:1px solid #D9E0E9;border-radius:10px} #overlay-panel QLabel{background:transparent;border:0} QLabel#overlay-heading{font-size:13px;font-weight:600} QLabel#source-tier-label{color:#536075;font-size:12px;font-weight:600}')
        layout.addWidget(self.panel);inner=QtWidgets.QVBoxLayout(self.panel);inner.setContentsMargins(10,10,10,10);inner.setSpacing(8)
        self.heading=label('');self.heading.setObjectName('overlay-heading');self.footer=label('仅窗口像素 · Ctrl+Alt+O · 非 Riot 评级/批准',True);summary=QtWidgets.QHBoxLayout();self.summary_layout=summary;summary.addWidget(self.heading,1);summary.addWidget(self.footer,1);self.metadata_label=label('',True);inner.addWidget(self.metadata_label);self.row=QtWidgets.QHBoxLayout();self.row.setSpacing(8);inner.addLayout(self.row);inner.addLayout(summary)
        self.resize(820,76);self._init_badges()
    def paintEvent(self,event):
        # WA_OpaquePaintEvent requires every pixel, including the rounded
        # child's outer corners, to be painted on every resize/exposure.
        painter=QtGui.QPainter(self);painter.fillRect(self.rect(),QtGui.QColor('#0B141E' if self.cards else '#FAFCFF'));painter.end()
        super().paintEvent(event)
    def hide(self,reason='unknown'):
        self._hide_reason=reason
        super().hide()
        self._hide_reason='unknown'
    def overlay_debug(self,**fields):
        if self.debug_log:self.debug_log.record('overlay',**(self.debug_context() if hasattr(self,'debug_context') else {}),**fields)
    def showEvent(self,event):
        self.overlay_debug(phase='shown',visible=True,reason=self._show_reason,rechecking=self._rechecking,dpi=float(self.devicePixelRatioF())*96)
        super().showEvent(event)
    def hideEvent(self,event):
        self._last_hidden_at=time.monotonic()
        self.overlay_debug(phase='hidden',visible=False,reason=self._hide_reason,rechecking=self._rechecking)
        super().hideEvent(event)
    def hidden_settle_ms(self):
        # A hidden flag alone is not a DWM settling interval. Hides from Stop,
        # expiry and other transitions share the same actual transition clock.
        if self._last_hidden_at is None:return 0
        return max(0,math.ceil(60-(time.monotonic()-self._last_hidden_at)*1000))
    def set_cards(self,hero,cards,source_date='未知',source_version='未知',confirmation='人工确认'):
        return self._set_badge_cards(hero,cards,source_date,source_version,confirmation)
    def set_hero_reference(self,reference):
        if reference.get('selectionRows') is not None:return self.set_selection_reference(reference)
        if self.cards:self._leave_badges()
        portrait_id=self.hero_id_lookup(reference['hero']) if self.hero_id_lookup else None
        if portrait_id!=reference.get('championId'):portrait_id=None
        portrait_revision=(self.portrait_bank.revision,portrait_id)
        if self.reference==reference and self._portrait_revision==portrait_revision:return
        if self.reference==reference and self.hero_portrait is not None:
            # A verified image-cache update changes only these fixed-size
            # decorative pixels, never assignment authority or placement.
            self._portrait_revision=portrait_revision
            portrait=self.portrait_bank.pixmap(portrait_id,40,float(self.devicePixelRatioF()))
            self.hero_portrait.setPixmap(portrait if portrait is not None else ControlWindow.neutral_portrait(40))
            self.hero_portrait.setAccessibleName(reference['hero']+' · 官方基础头像' if portrait is not None else '通用身份占位图，不是英雄画像')
            return
        self._portrait_revision=portrait_revision
        self.cards=[];self.reference=dict(reference);self._rechecking=False;self._titles_pending=False;self.tier_labels=[];self._pill_labels=[];self._detail_labels=[];self._card_layouts=[];self._title_labels=[];self._layout_revision+=1;self._placed_key=None
        while self.row.count():
            item=self.row.takeAt(0);widget=item.widget()
            if widget:widget.hide();widget.deleteLater()
        self._previous_heading='上次分配 · 复核中 · HUD未复核'
        self._full_heading=self._compact_heading='当前分配 · 仍可交换 · HUD未复核'
        self.heading.setStyleSheet('font-size:12px;font-weight:600;color:#8D6600')
        self._source_marker='虚构演示' if reference['isDemo'] else '虎牙公开源' if reference['sourceUrl'] else '来源待核对'
        self.metadata_label.setText(f"英雄评级快照 {reference['sourceDataDate'] or '日期未知'} · 英雄资料 {reference['sourceVersion'] or '未知'} · 游戏资料 {reference['gamePatch'] or '未知'} · 数据包 {reference['wikiDataVersion'] or '未知'}")
        frame=QtWidgets.QFrame();box=QtWidgets.QHBoxLayout(frame);box.setContentsMargins(8,4,8,4);box.setSpacing(12);self._card_layouts.append(box)
        self.hero_portrait=label();self.hero_portrait.setFixedSize(40,40)
        portrait=self.portrait_bank.pixmap(portrait_id,40,float(self.devicePixelRatioF()))
        self.hero_portrait.setPixmap(portrait if portrait is not None else ControlWindow.neutral_portrait(40))
        self.hero_portrait.setAccessibleName(reference['hero']+' · 官方基础头像' if portrait is not None else '通用身份占位图，不是英雄画像');box.addWidget(self.hero_portrait)
        title=label(reference['hero']);title.setAccessibleName('当前分配英雄：'+reference['hero']);self._title_labels.append(title);box.addWidget(title,1)
        tier=label('英雄整体强度：'+(reference['sourceTier'] or '暂无评级'));tier.setAccessibleName(reference['sourceTierLabel']+'：'+(reference['sourceTier'] or '暂无评级'));self.tier_labels.append(tier);box.addWidget(tier);self.row.addWidget(frame)
        self._set_compact(True);self.adjustSize();self.resize(820,max(52,self.height()))
    def set_selection_reference(self,reference):
        if self.reference==reference:return
        if self.cards:self._leave_badges()
        self.cards=[];self.reference=dict(reference);self._rechecking=False;self._titles_pending=False;self.tier_labels=[];self._pill_labels=[];self._detail_labels=[];self._card_layouts=[];self._title_labels=[];self._layout_revision+=1;self._placed_key=None
        while self.row.count():
            item=self.row.takeAt(0);widget=item.widget()
            if widget:widget.hide();widget.deleteLater()
        self._previous_heading='本机客户端选人 · 上次资料复核中'
        self._full_heading=self._compact_heading='本机客户端只读选人 · 仍可交换'
        self.heading.setStyleSheet('font-size:12px;font-weight:600;color:#536075')
        self._source_marker='虎牙公开源' if reference.get('sourceUrl') else '来源待核对'
        self.metadata_label.setText('英雄评级快照 '+(reference.get('sourceDataDate') or '日期未知')+' · 非实时评级')
        frame=QtWidgets.QFrame();box=QtWidgets.QVBoxLayout(frame);self._card_layouts.append(box)
        for group,rows in reference['selectionRows']:
            values=[('本人：' if row['championId']==reference.get('ownChampionId') and group=='队伍' else '')+row['hero']+' '+(row['sourceTier'] or '暂无评级') for row in rows]
            text=label(group+'：'+('  ·  '.join(values) if values else '暂无可确认英雄'));text.setWordWrap(True);text.setAccessibleName(text.text());box.addWidget(text);self.tier_labels.append(text)
        self.row.addWidget(frame,1)
        self._set_compact(True);self.adjustSize();self.resize(820,max(52,self.height()))
    def configure(self):
        if self.capture:self.capture.configure_overlay(int(self.winId()),self.click_through or bool(self.cards),opaque=True)
    def retire_capture_session(self):
        # A replacement layout must wait for the producer to drain. Closing
        # its session while a frame is in flight would turn our own retirement
        # into a failure of the newly confirmed display. Never clear a pending
        # real failure: the controller consumes it before retrying placement.
        self._capture_retirement_pending=True
        if self._before_capture_retirement and not self._before_capture_retirement():return False
        retire=getattr(self.capture,'retire_session',None)
        if retire:retire()
        self._capture_retirement_pending=False
        return True
    def set_rechecking(self,value):
        value=bool(value)
        if self._rechecking==value:return
        self._rechecking=value
        if self.cards:self._refresh_badges()
        self.overlay_debug(phase='rechecking',visible=self.isVisible(),rechecking=value,reason='capture_proof')
        # The shorter status text does not change cards, source or geometry.
        # Invalidating placement here would hide/move the HWND every cycle.
        if self.cards or self.reference:self.heading.setText('候选复核中' if self._titles_pending else self._previous_heading if value else self._compact_heading if self._compact else self._full_heading)
    def set_click_through(self,value):
        mode=getattr(self.capture,'set_interactive_overlay',None)
        if mode:mode(not bool(value)) # Explicit user-selected strict-hide compatibility route.
        else:
            retire=getattr(self.capture,'retire_session',None)
            if retire:retire()
        # Revoke the old HWND/style token before Qt can change it. Automatic
        # affinity/identity failures never select the compatibility mode above.
        self.click_through=bool(value);self.hide('click_through');self._placed_key=None;self._layout_revision+=1
        self.setWindowFlag(QtCore.Qt.WindowType.WindowTransparentForInput,self.click_through or bool(self.cards))
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.configure()
    def _set_compact(self,compact,*,dense=False):
        self._compact=compact;self._dense=bool(dense)
        self.summary_layout.setDirection(QtWidgets.QBoxLayout.Direction.TopToBottom if dense else QtWidgets.QBoxLayout.Direction.LeftToRight)
        for pill in self._pill_labels:pill.setVisible(not dense)
        self.heading.setText(self._previous_heading if self._rechecking else self._compact_heading if compact else self._full_heading)
        for widget in self._detail_labels:widget.setVisible(not compact)
        self.metadata_label.setVisible(bool(self.reference) or not compact)
        self.panel.layout().setContentsMargins(*((1,1,1,1) if dense else (3,3,3,3) if compact else (10,10,10,10)));self.panel.layout().setSpacing(0 if dense else 2 if compact else 8);self.row.setSpacing(4 if compact else 8)
        for box in self._card_layouts:box.setContentsMargins(*((6,0,6,0) if dense else (6,3,6,3) if compact else (10,8,10,8)));box.setSpacing(1 if dense else 2 if compact else 5)
        for title in self._title_labels:title.setStyleSheet('font-size:'+('13' if compact else '14')+'px;font-weight:600')
        self.footer.setText(self._source_marker+' · 非 Riot 评级/批准')
        for layout in reversed(self.findChildren(QtWidgets.QLayout)):layout.invalidate();layout.activate()
        self.layout().invalidate();self.layout().activate()
    def _fit_layout(self,rect,dpr):
        from overlay_geometry import layout_budget,placement
        budget=layout_budget(rect,dpr)
        # Preserve the earlier100-DIP readable-layout + half-client eligibility
        # budget, even though the new strip itself can be shorter.
        if rect.height < math.ceil(200*dpr):
            raise CaptureUnavailable('目标客户区不足200逻辑像素高度，无法保留足够游戏空间，已隐藏。')
        for compact,dense in ((True,False),(True,True)):
            self._set_compact(compact,dense=dense)
            width=budget.logical_width
            self.resize(width,max(52,min(self.height(),budget.logical_height)))
            self.layout().activate()
            hint=self.layout().totalHeightForWidth(width)
            height=max(self.minimumSizeHint().height(),hint if hint>=0 else self.sizeHint().height(),52)
            # Keep every name and literal tier legible within the same hard
            # client/half-height budget; dense padding never shrinks the font.
            if self.minimumSizeHint().width()<=width and height<=min(budget.logical_height,math.floor(rect.height*.5/dpr)):
                self.resize(width,height);self.layout().activate()
                return placement(rect,budget,height)
        raise CaptureUnavailable(f'客户区 {rect.width}×{rect.height} 像素 / 叠加缩放 {dpr:g} 倍：紧凑资料卡无法清晰放入半屏高度，已隐藏；可在控制台按名称查阅资料。')
    def _verify_rect(self,rect):
        actual=W.RECT()
        if not self.capture.u.GetWindowRect(int(self.winId()),ctypes.byref(actual)) or actual.right<=actual.left or actual.bottom<=actual.top or actual.left<rect.x or actual.top<rect.y or actual.right>rect.x+rect.width or actual.bottom>rect.y+rect.height or actual.bottom-actual.top>rect.height//2:
            raise CaptureUnavailable(f'叠加实际范围超出客户区或半屏高度 {rect.width}×{rect.height}，已隐藏。')
    def show_at(self,rect,target):
        if not self.cards and not self.reference:return
        if self.cards:return self._show_badges_at(rect,target)
        self._show_reason='client_reference' if self.reference else 'confirmed'
        try:
            if not self.capture:
                self.show();self.move(rect.x+20,rect.y+max(20,rect.height-self.height()-20));return
            hwnd=int(self.winId());dpr=float(self.windowHandle().devicePixelRatio())
            key=(rect,self._layout_revision,dpr)
            if self._placed_key==key:
                self.show();self.configure();self._verify_rect(rect)
                if float(self.windowHandle().devicePixelRatio())==dpr:return
            # Move hidden own HWND toward the target monitor. The game's DPI
            # may be96 even when Qt is150/200%; never use it to size Qt widgets.
            self.hide('layout')
            anchor_x=rect.x+rect.width//2-round(self.width()*dpr/2)
            anchor_y=rect.y+rect.height//2-round(self.height()*dpr/2)
            if not self.capture.u.SetWindowPos(hwnd,W.HWND(-1),anchor_x,anchor_y,0,0,0x0001|0x0010):raise CaptureUnavailable('无法定位叠加所属显示器，已隐藏。')
            dpr=float(self.windowHandle().devicePixelRatio())
            for _ in range(3):
                x,y,width,height=self._fit_layout(rect,dpr)
                if not self.capture.u.SetWindowPos(hwnd,W.HWND(-1),x,y,width,height,0x0010):raise CaptureUnavailable('无法把叠加放在目标窗口内，已隐藏。')
                final_dpr=float(self.windowHandle().devicePixelRatio())
                if final_dpr!=dpr:dpr=final_dpr;continue
                self.show();self.configure();self._verify_rect(rect)
                final_dpr=float(self.windowHandle().devicePixelRatio())
                if final_dpr==dpr:
                    self._placed_key=(rect,self._layout_revision,dpr);return
                self.hide('layout');dpr=final_dpr
            raise CaptureUnavailable('叠加跨显示器缩放持续变化，暂时隐藏，等待稳定布局。')
        except Exception:
            self._placed_key=None;self.hide('layout_error');raise
    def nativeEvent(self,event_type,message):
        if os.name=='nt':
            msg=W.MSG.from_address(int(message))
            if msg.message==0x0084 and (self.click_through or self.cards):return True,-1 # HTTRANSPARENT, no hooks
            if msg.message==0x0021:return True,3 # MA_NOACTIVATE
        return super().nativeEvent(event_type,message)

class ControlWindow(QtWidgets.QWidget):
    def __init__(self,startup_loader,*,state_dir,current_executable,current_version,frozen,on_ready=None,smoke_report=None,smoke_screenshot=None,enable_updates=True,selection_smoke_input=None,enable_visible_capture=True):
        super().__init__();self.state=RecognitionState();self.hero_continuity=HeroIdentityContinuity();self.data=None;self.startup_error='';self.target=None;self.capture=None;self.last_rect=None;self.was_target_foreground=False;self.ocr_busy=False;self.manual_editing=False;self.capture_pending=False;self.last_observation=0.;self.ocr_started=0.;self.ocr_timed_out=False;self.closed=False;self.on_ready=on_ready
        self._worker_lock=threading.Lock();self._cancel_workers=threading.Event();self._workers=set();self.latest_capture=LatestCaptureFrame();self._prefetch_last_attempt=0.;self.ocr_reuse=FrameOCRCache();self._capture_cancel=threading.Event();self.manual_metadata=None;self.manual_identity=None
        from lcu_selection import SelectionSnapshot
        self.lcu_snapshot=SelectionSnapshot();self.last_selection_source=None;self._lcu_pixel_fallback=False;self._lcu_error=''
        from selection_retry import SelectionRetry
        self.selection_retry=SelectionRetry();self._selection_capture_state='waiting'
        self._capture_serial=0;self._completed_capture_serial=None;self._active_capture_generation=None;self._geometry_frame=None;self._accepted_frame=None;self._semantic_title_frame=None;self._current_capture_proof=None;self._restore_while_ocr=False;self.last_timings=None;self.last_candidates=None
        self.partial_candidates=PartialCandidateState();self._partial_revision=0;self._partial_hero='';self._partial_scope=None;self._partial_displayed=False
        self._accepted_partial_frame=None;self._semantic_partial_frame=None
        if type(enable_visible_capture) is not bool:raise TypeError('Visible capture requires an explicit boolean')
        # Ordinary capture retains all per-request guards and strict-hidden fallback.
        self.enable_visible_capture=enable_visible_capture;self._visible_previous=False;self._mode_wait_started=None
        from frame_inference_worker import FrameInferenceWorker
        self.frame_inference_worker=FrameInferenceWorker()
        self.enable_updates=enable_updates;self.hero_matcher=None;self.selection_session=None;self.window_policy=None;self.client_target=None;self.selection_detector=None;self.hero_origin='hud';self.selection_smoke_input=selection_smoke_input;self.last_window_discovery=0.;self.automatic_policy=None;self.discovery_busy=False;self.discovery_scope=0
        self.current_version=current_version;self.current_executable=Path(current_executable);self.state_dir=Path(state_dir);self.frozen=frozen;self.release=None;self.smoke_report=smoke_report;self.smoke_screenshot=smoke_screenshot;self.hotkey_registered=False
        self.debug_log=LocalDebugLog(self.state_dir/'local-debug',version=current_version);self._debug_snapshot=None;self._debug_hero=None;self._debug_candidates=None;self._debug_hero_revision=0;self._debug_candidate_revision=0;self._debug_game_window=None
        self._portraits_busy=False;self._portraits_attempt=0;self._portraits_completed_attempt=None;self._portraits_failures=0;self._portraits_retry_at=None;self._portraits_bank=None;self._portrait_memory_map=()
        self._portrait_model_key=None;self._pending_portraits=None;self._portrait_display_key=None
        self._verified_roster_map=();self._verified_roster_source=None
        self.portrait_bank=PortraitDisplayBank();self._hero_portrait_key=None;self._selection_roster_fingerprint=cached_roster_fingerprint(self.state_dir/'hero-portraits')
        self.signals=TaskSignals(self);self.signals.result.connect(self.task_result);self.signals.error.connect(self.task_error)
        self.setWindowTitle(APP_NAME);self.setWindowIcon(QtGui.QIcon(str(ROOT/'assets/branding/vga.ico')));self.setStyleSheet(STYLE);self.resize(900,490)
        outer=QtWidgets.QVBoxLayout(self);outer.setContentsMargins(28,12,28,14);outer.setSpacing(12)
        utilities=QtWidgets.QHBoxLayout();utilities.setSpacing(4)
        icon=label();icon.setPixmap(QtGui.QIcon(str(ROOT/'assets/branding/vga-icon-512.png')).pixmap(QtCore.QSize(28,28),self.devicePixelRatioF()));icon.setFixedSize(28,28);utilities.addWidget(icon)
        brand=label(APP_NAME);self.brand_label=brand;brand.setStyleSheet('font-size:14px;font-weight:600');utilities.addWidget(brand);utilities.addStretch()
        self.back_button=QtWidgets.QToolButton();self.back_button.setText('返回');self.back_button.setObjectName('utility');self.back_button.hide();utilities.addWidget(self.back_button)
        self.correction_button=QtWidgets.QToolButton();self.correction_button.setText('核对资料');self.correction_button.setObjectName('utility');utilities.addWidget(self.correction_button)
        self.advanced_toggle=QtWidgets.QToolButton();self.advanced_toggle.setText('设置');self.advanced_toggle.setObjectName('utility');self.advanced_toggle.setCheckable(True);self.advanced_toggle.setAccessibleName('打开监测设置');utilities.addWidget(self.advanced_toggle)
        self.about_button=QtWidgets.QToolButton();self.about_button.setText('关于');self.about_button.setObjectName('utility');utilities.addWidget(self.about_button);self.secondary_stop=QtWidgets.QPushButton('停止监测');self.secondary_stop.hide();self.secondary_stop.clicked.connect(self.stop_monitor);utilities.addWidget(self.secondary_stop);outer.addLayout(utilities)
        self.pages=QtWidgets.QStackedWidget();self.pages.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding,QtWidgets.QSizePolicy.Policy.Ignored);outer.addWidget(self.pages,1)
        self.dashboard=QtWidgets.QWidget();self.dashboard.setObjectName('dashboard');self.dashboard_scroll=QtWidgets.QScrollArea();self.dashboard_scroll.setWidgetResizable(True);self.dashboard_scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame);self.dashboard_scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff);self.dashboard_scroll.setWidget(self.dashboard);self.pages.addWidget(self.dashboard_scroll)
        main=QtWidgets.QVBoxLayout(self.dashboard);self.main_layout=main;main.setContentsMargins(0,4,0,0);main.setSpacing(16)
        hero_row=QtWidgets.QHBoxLayout();self.hero_row=hero_row;hero_row.setSpacing(24)
        self.hero_avatar=label();self.hero_avatar.setFixedSize(108,108);self.hero_avatar.setPixmap(self.neutral_portrait(108));self.hero_avatar.setAccessibleName('通用身份占位图，不是英雄画像');hero_row.addWidget(self.hero_avatar)
        identity=QtWidgets.QVBoxLayout();identity.setSpacing(5);self.hero_caption=label('本局英雄',True);identity.addWidget(self.hero_caption);self.hero_title=label('等待识别');self.hero_title.setObjectName('hero-title');identity.addWidget(self.hero_title)
        self.status_chip=label('资料待就绪');self.status_chip.setObjectName('status-chip');identity.addWidget(self.status_chip);self.hero_provenance=label('',True);identity.addWidget(self.hero_provenance);hero_row.addLayout(identity,1)
        self.start_button=QtWidgets.QPushButton('开始监测');self.start_button.setObjectName('primary-action');self.stop_button=QtWidgets.QPushButton('停止监测');self.stop_button.setObjectName('primary-action')
        self.monitor_actions=QtWidgets.QStackedWidget();self.monitor_actions.setFixedWidth(152);self.monitor_actions.setFixedHeight(46);self.monitor_actions.addWidget(self.start_button);self.monitor_actions.addWidget(self.stop_button);hero_row.addWidget(self.monitor_actions)
        main.addSpacing(4);main.addLayout(hero_row);main.addSpacing(4)
        main.addWidget(label('非 Riot 官方或背书产品；完整声明见“关于”。',True))
        self.selection_optin=QtWidgets.QFrame();selection_optin_layout=QtWidgets.QVBoxLayout(self.selection_optin);selection_optin_layout.setContentsMargins(0,0,0,0)
        selection_optin_layout.addWidget(label('选人截图尚不稳定时，可开启本机只读识别，显示当前英雄、队伍与备选席评级；仅本次启动有效。',True))
        self.selection_optin_button=QtWidgets.QPushButton('开启本机选人识别');self.selection_optin_button.clicked.connect(self.enable_client_selection);selection_optin_layout.addWidget(self.selection_optin_button)
        main.addWidget(self.selection_optin);self.selection_optin.hide()
        self.trust_button=QtWidgets.QPushButton('确认自己的游戏安装目录…');self.trust_button.hide();self.trust_button.clicked.connect(self.confirm_game_installation);main.addWidget(self.trust_button);self.unverified_candidate=None
        divider=QtWidgets.QFrame();divider.setObjectName('divider');divider.setFixedHeight(1);main.addWidget(divider)
        section_row=QtWidgets.QHBoxLayout();heading=label('候选强化');heading.setObjectName('section-title');section_row.addWidget(heading);section_row.addStretch();self.candidate_caption=label('等待三个候选稳定确认',True);section_row.addWidget(self.candidate_caption);main.addLayout(section_row)
        self.candidate_row=QtWidgets.QHBoxLayout();self.candidate_row.setSpacing(16);self.candidate_views=[]
        for index in range(1,4):
            frame=QtWidgets.QFrame();frame.setObjectName('candidate-card');box=QtWidgets.QVBoxLayout(frame);box.setContentsMargins(20,18,20,18);box.setSpacing(10)
            top=QtWidgets.QHBoxLayout();mark=label();mark.setPixmap(self.neutral_augment(32));mark.setFixedSize(32,32);mark.setAccessibleName(f'画面选项 {index} · 通用强化符号，不表示具体机制');top.addWidget(mark);position=label(('左侧','中间','右侧')[index-1],True);top.addWidget(position);top.addStretch();tier=label('—');tier.setObjectName('tier-pill');top.addWidget(tier,0,QtCore.Qt.AlignmentFlag.AlignTop);box.addLayout(top);box.addSpacing(10)
            name=label('等待识别');name.setObjectName('candidate-name');name.setAccessibleName(f'选项 {index} 名称');box.addWidget(name);detail=label('识别稳定后显示资料',True);box.addWidget(detail);box.addStretch(1);frame.setMinimumHeight(154);self.candidate_row.addWidget(frame,1);self.candidate_views.append(dict(frame=frame,name=name,tier=tier,detail=detail))
        main.addLayout(self.candidate_row);main.addStretch(1)
        self.scroll=QtWidgets.QScrollArea();self.scroll.setWidgetResizable(True);self.scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame);self.scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff);self.pages.addWidget(self.scroll)
        container=QtWidgets.QWidget();container.setObjectName('scroll-content');self.scroll.setWidget(container);secondary=QtWidgets.QVBoxLayout(container);secondary.setContentsMargins(0,4,4,4);secondary.setSpacing(12)
        self.secondary_title=label('核对与资料');self.secondary_title.setObjectName('section-title');secondary.addWidget(self.secondary_title)
        self.correction_panel=QtWidgets.QFrame();self.correction_panel.setObjectName('section');candidate_box=QtWidgets.QVBoxLayout(self.correction_panel);candidate_box.setContentsMargins(16,16,16,16);candidate_box.setSpacing(10);secondary.addWidget(self.correction_panel)
        candidate_box.addWidget(label('按画面左、中、右核对。输入名称不会自动确认，也不会替代当前监测结果。',True));fields=QtWidgets.QHBoxLayout();fields.setSpacing(8);self.inputs=[]
        for name in ('左侧','中间','右侧'):
            column=QtWidgets.QVBoxLayout();caption=label(name,True);edit=QtWidgets.QLineEdit();edit.setAccessibleName(name+'候选');edit.setPlaceholderText('等待识别');caption.setBuddy(edit);edit.textEdited.connect(self.edit_changed);self.inputs.append(edit);column.addWidget(caption);column.addWidget(edit);fields.addLayout(column,1)
        candidate_box.addLayout(fields);self.confirm_button=QtWidgets.QPushButton('人工纠正并确认三项');self.confirm_button.clicked.connect(self.confirm);candidate_box.addWidget(self.confirm_button)
        self.details_toggle=QtWidgets.QToolButton();self.details_toggle.setText('查阅输入名称的完整资料');self.details_toggle.setCheckable(True);self.details_toggle.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonTextBesideIcon);self.details_toggle.setArrowType(QtCore.Qt.ArrowType.RightArrow);candidate_box.addWidget(self.details_toggle)
        self.card_details=label('',True);self.card_details.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse|QtCore.Qt.TextInteractionFlag.TextSelectableByKeyboard);self.card_details.setAccessibleName('输入名称的词典资料');self.card_details.hide();candidate_box.addWidget(self.card_details);self.details_toggle.toggled.connect(self.refresh_card_details)
        self.history_view=label('上次候选 · 最终选择未知\n尚无本次监测记录。',True);self.history_view.setAccessibleName('历史候选，不代表已选择的强化');self.history_view.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse|QtCore.Qt.TextInteractionFlag.TextSelectableByKeyboard);candidate_box.addWidget(self.history_view)
        self.advanced_panel=QtWidgets.QFrame();self.advanced_panel.setObjectName('section');advanced=QtWidgets.QVBoxLayout(self.advanced_panel);advanced.setContentsMargins(16,16,16,16);advanced.setSpacing(10);secondary.addWidget(self.advanced_panel);self.advanced_panel.hide();self.advanced_toggle.toggled.connect(self.set_advanced_visible)
        self.window_list=QtWidgets.QComboBox();self.window_list.setMinimumContentsLength(12);self.window_list.setSizeAdjustPolicy(QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon);self.window_list.setAccessibleName('窗口连接');self.refresh=QtWidgets.QPushButton('重新检测');row=QtWidgets.QHBoxLayout();row.addWidget(self.window_list,1);row.addWidget(self.refresh);caption=label('窗口连接',True);caption.setBuddy(self.window_list);advanced.addWidget(caption);advanced.addLayout(row)
        self.window_status=label('默认自动连接，无需选择窗口。',True);advanced.addWidget(self.window_status)
        self.client_follow=QtWidgets.QCheckBox('自动接续同目录的客户端与游戏');self.client_follow.setToolTip('仅接续已经核验、属于同一安装目录的英雄联盟客户端与游戏窗口');self.client_follow.setChecked(True);advanced.addWidget(self.client_follow)
        self.hero_box=QtWidgets.QComboBox();self.hero_box.setEditable(True);self.hero_box.setMinimumContentsLength(12);self.hero_box.setSizeAdjustPolicy(QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon);self.hero_box.setInsertPolicy(QtWidgets.QComboBox.InsertPolicy.NoInsert);self.hero_box.setEnabled(False);self.hero_box.setAccessibleName('人工纠正本人英雄');caption=label('本人英雄 · 关闭自动识别后可纠正',True);caption.setBuddy(self.hero_box);advanced.addWidget(caption);advanced.addWidget(self.hero_box)
        self.hero_status=label('本人头像模板准备中…',True);advanced.addWidget(self.hero_status)
        advanced.addWidget(label('截图范围 · 所选窗口内百分比',True));roi_row=QtWidgets.QGridLayout();self.roi_layout=roi_row;roi_row.setSpacing(8);self.roi=[];self.roi_fields=[]
        for name,value in [('左',15),('上',25),('宽',70),('高',35)]:
            field=QtWidgets.QWidget();column=QtWidgets.QVBoxLayout(field);column.setContentsMargins(0,0,0,0);caption=label(name,True);spin=QtWidgets.QSpinBox();spin.setRange(0,100);spin.setValue(value);spin.setSuffix('%');spin.setAccessibleName('截图范围'+name);caption.setBuddy(spin);spin.valueChanged.connect(self.roi_changed);self.roi.append(spin);column.addWidget(caption);column.addWidget(spin);self.roi_fields.append(field);roi_row.addWidget(field,0,len(self.roi_fields)-1)
        advanced.addLayout(roi_row)
        self.lcu_toggle=QtWidgets.QCheckBox('本机客户端只读选人（仅本次启动）');self.lcu_toggle.setChecked(False);advanced.addWidget(self.lcu_toggle)
        advanced.addWidget(label('可选：读取已核验安装目录的临时会话凭据，仅请求本机客户端选人和阶段资料；不读游戏内存、不修改客户端、不保存凭据。Riot 未正式支持此接口；失败时回退截图识别。',True))
        self.lcu_toggle.toggled.connect(self.lcu_consent_changed)
        self.monitor_preferences=load_preferences(self.state_dir)
        self.live_identity_toggle=QtWidgets.QCheckBox('本局英雄身份只读核验（默认开启，可关闭）');self.live_identity_toggle.setChecked(self.monitor_preferences['live_identity']);advanced.addWidget(self.live_identity_toggle)
        advanced.addWidget(label('通过 Riot 本机游戏接口读取当前玩家标识与玩家英雄列表，仅在内存中匹配本人英雄；不保存或记录玩家标识，不读游戏内存。连接失败不会被当作英雄变更；关闭后仅使用截图。此开关会记住你的选择。',True))
        self.live_identity_toggle.toggled.connect(self.live_identity_preference_changed)
        self.minimize_on_start=QtWidgets.QCheckBox('开始监测后自动最小化（默认关闭）');self.minimize_on_start.setChecked(self.monitor_preferences['minimize_on_start']);advanced.addWidget(self.minimize_on_start)
        self.minimize_on_start.toggled.connect(self.save_monitor_preferences)
        self.debug_toggle=QtWidgets.QCheckBox('本地诊断日志（此诊断版默认开启）');self.debug_toggle.setChecked(False);self.debug_toggle.setAccessibleName('本机诊断日志，此诊断版默认开启，可关闭');advanced.addWidget(self.debug_toggle)
        self.debug_export_button=QtWidgets.QPushButton('导出调试 ZIP');self.debug_export_button.setAccessibleName('仅在本机导出调试 ZIP');advanced.addWidget(self.debug_export_button)
        self.debug_status=label('此诊断版默认记录，最多 3 × 256 KiB，循环覆盖。仅记录阶段、耗时和已匹配词典的英雄/强化名称；无截图、原始识别文字、账号、窗口标题、路径或原始错误，不上传。可随时关闭。',True);advanced.addWidget(self.debug_status)
        self.debug_toggle.toggled.connect(self.toggle_debug);self.debug_export_button.clicked.connect(self.export_debug)
        self.about_panel=QtWidgets.QFrame();self.about_panel.setObjectName('section');about=QtWidgets.QVBoxLayout(self.about_panel);about.setContentsMargins(16,16,16,16);about.setSpacing(12);secondary.addWidget(self.about_panel);self.about_panel.hide()
        self.source=label('正在检查公开数据，首次启动可能需要数十秒…',True);about.addWidget(self.source)
        self.riot_notice=label('VGA ARAM Helper is not endorsed by Riot Games and does not reflect the views or opinions of Riot Games or anyone officially involved in producing or managing Riot Games properties. Riot Games and all associated properties are trademarks or registered trademarks of Riot Games, Inc.',True);self.riot_notice.setAccessibleName("Riot 非背书声明");about.addWidget(self.riot_notice)
        self.compatibility=label('默认核验窗口可见像素；可选本机只读接口，不读取游戏内存。支持窗口 / 无边框模式；实际 LoL 与 Vanguard 兼容性尚未验证。',True);about.addWidget(self.compatibility)
        about.addWidget(label('英雄整体强度使用公开源原始 T1–T5；强化评级使用 T1–T4，缺失显示暂无评级。保留三项原位置，不展示胜率、换算等级或推荐唯一最佳选项；公开源快照并非实时评级或 Riot 批准。',True))
        about.addWidget(label('开始后控制台自动最小化；切出、被遮挡或识别不确定时清空旧结果。截图不保存、不上传。',True))
        about.addWidget(label('持续捕获只绑定本次授权窗口；空闲帧池可能保留该窗口的 GPU 表面。仅在请求时核验前台、遮挡与身份并读回所选范围；停止或失效后清理，系统阻塞时不能保证 50 ms 内关闭。',True))
        self.portrait_diagnostics=None;self.cache_diagnostic_button=QtWidgets.QPushButton('头像缓存诊断');self.cache_diagnostic_button.hide();self.cache_diagnostic_button.clicked.connect(self.show_cache_diagnostics);about.addWidget(self.cache_diagnostic_button)
        self.capture_diagnostic=label('采集诊断：尚无画面。截图成功与全屏叠加可见是两项独立检查。',True);self.capture_diagnostic.setAccessibleName('最近采集阶段与耗时');about.addWidget(self.capture_diagnostic)
        self.update_status=label('软件更新待检查。',True);about.addWidget(self.update_status);self.update_button=QtWidgets.QPushButton('查看并安装软件更新');self.update_button.hide();about.addWidget(self.update_button)
        self.status=label('准备中…',True);self.status.setAccessibleName('当前监测状态');secondary.addWidget(self.status);secondary.addStretch()
        divider=QtWidgets.QFrame();divider.setObjectName('divider');divider.setFixedHeight(1);outer.addWidget(divider)
        footer=QtWidgets.QHBoxLayout();footer.setSpacing(16)
        self.hero_auto=Switch('自动识别');self.hero_auto.setToolTip('结合本局选人文字与局内 HUD，高置信连续识别后自动使用');self.hero_auto.setChecked(True);footer.addWidget(self.hero_auto)
        self.toggle_button=Switch('鼠标穿透');self.toggle_button.setChecked(True);self.toggle_button.setToolTip('Ctrl+Alt+O 切换鼠标穿透，不改变识别或叠加确认状态');footer.addWidget(self.toggle_button);footer.addStretch()
        self.footer_note=label('截图 + 本机只读英雄接口' if self.live_identity_toggle.isChecked() else '仅窗口像素 · 兼容性待验证',True);footer.addWidget(self.footer_note);self.shortcut_label=label('Ctrl + Alt + O',True);self.shortcut_label.setStyleSheet('border:1px solid #D9E0E9;border-radius:5px;padding:4px 8px');footer.addWidget(self.shortcut_label);outer.addLayout(footer)
        self.back_button.clicked.connect(lambda:self.show_page('main'));self.correction_button.clicked.connect(lambda:self.show_page('correction'));self.about_button.clicked.connect(lambda:self.show_page('about'))
        order=[self.start_button,self.stop_button,self.hero_auto,self.toggle_button,self.correction_button,self.advanced_toggle,self.about_button,*self.inputs,self.confirm_button,self.details_toggle,self.window_list,self.refresh,self.client_follow,self.hero_box,*self.roi,self.debug_toggle,self.debug_export_button,self.cache_diagnostic_button,self.update_button]
        for before,after in zip(order,order[1:]):QtWidgets.QWidget.setTabOrder(before,after)
        self.refresh.clicked.connect(self.refresh_windows);self.window_list.currentIndexChanged.connect(self.target_changed);self.hero_box.currentTextChanged.connect(self.hero_changed);self.hero_auto.toggled.connect(self.hero_mode_changed);self.client_follow.toggled.connect(self.follow_scope_changed);self.start_button.clicked.connect(self.start_monitor);self.stop_button.clicked.connect(self.stop_monitor);self.toggle_button.clicked.connect(self.toggle_clickthrough);self.update_button.clicked.connect(self.install_update)
        try:self.capture=Win32Capture(allow_visible_overlay=True) if enable_visible_capture else Win32Capture()
        except CaptureUnavailable as exc:self.status.setText(str(exc))
        self.overlay=Overlay(self.capture,self.portrait_bank,lambda hero:self.portrait_bank.hero_id(self.data,hero),debug_log=self.debug_log,before_capture_retirement=self.latest_capture.prepare_retirement);self.overlay.debug_context=lambda:dict(generation=self.state.generation,serial=self._capture_serial);self.overlay.winId();self.overlay.configure()
        for control in (self.hero_auto,self.client_follow,self.lcu_toggle,self.live_identity_toggle):control.toggled.connect(self.record_debug_config)
        for spin in self.roi:spin.valueChanged.connect(self.record_debug_config)
        self.monitor=QtCore.QTimer(self);self.monitor.setSingleShot(True);self.monitor.setInterval(200);self.monitor.timeout.connect(self.capture_tick)
        self.watchdog=QtCore.QTimer(self);self.watchdog.setInterval(200);self.watchdog.timeout.connect(self.check_target);self.watchdog.timeout.connect(self.refresh_status_badge);self.watchdog.timeout.connect(self.retry_portraits);self.watchdog.start()
        self.start_button.setEnabled(False);self.confirm_button.setEnabled(False);self.stop_button.setEnabled(False)
        self.fit_control_to_screen(initial=True);self.show();self.fit_control_to_screen();self.windowHandle().screenChanged.connect(lambda _:self.fit_control_to_screen());self.register_hotkey();self.refresh_windows();self.debug_toggle.setChecked(True);self.spawn('load',startup_loader)
    def toggle_debug(self,enabled):
        active=self.debug_log.set_enabled(enabled)
        if active!=enabled:
            self.debug_toggle.blockSignals(True);self.debug_toggle.setChecked(active);self.debug_toggle.blockSignals(False)
        self._debug_snapshot=None
        if active:self.record_debug_config()
        self.debug_status.setText('正在本机记录，最多 768 KiB；仅词典名称与诊断阶段，无截图/原始文字/账号，不上传。导出会替换本机上一份 VGA-debug.zip。' if active else '已关闭记录；已有日志和导出保留，可继续导出。' if not self.debug_log.failed else '本地日志无法写入，已停止记录；监测不受影响。')
        self.refresh_status_badge()
    def debug_config(self):
        return {'hero_auto':self.hero_auto.isChecked(),'client_follow':self.client_follow.isChecked(),
            'lcu_selection':self.lcu_toggle.isChecked(),'live_identity':self.live_identity_toggle.isChecked(),
            'click_through':self.overlay.click_through,'visible_capture':self.enable_visible_capture,
            'frozen':self.frozen,'updates_enabled':self.enable_updates,'roi_percent':[spin.value() for spin in self.roi]}
    def record_debug_config(self,*_):
        self.debug_log.record_config(self.debug_config())
    def export_debug(self):
        try:
            path=self.debug_log.export_zip(self.state_dir/'debug-exports',config=self.debug_config())
            self.debug_status.setText('已保存到本机：'+str(path)+'。仅含有界最近事件、版本、安全设置及覆盖计数；未上传。再次导出会替换此 ZIP。')
        except (OSError,ValueError):self.debug_status.setText('本地导出失败，请检查保存目录是否可写；没有上传或更改监测。')
    def debug_event(self,event,**fields):
        if not self.debug_log.enabled:return
        for key,value in dict(getattr(self.capture,'session_lifecycle_diagnostic',{})).items():fields.setdefault(key,value)
        fields.setdefault('target_role',self.debug_target_role())
        self.debug_log.record(event,generation=self.state.generation,serial=self._capture_serial,
            session_generation=self.selection_session.generation if self.selection_session else 0,**fields)
    def debug_target_role(self):
        if self.automatic_policy:return self.automatic_policy.bound.role if self.automatic_policy.bound else 'none'
        if self.client_phase():return 'client'
        if self.window_policy and self.target and self.target.identity==self.window_policy.game_identity:return 'game'
        return 'manual' if self.target else 'none'
    def debug_selection_gate(self,foreground=None):
        if not self.debug_log.enabled:return
        from automatic_windows import selection_gate_snapshot
        self.debug_event('selection_gate',**selection_gate_snapshot(closed=self.closed,
            running=self.state.running,ocr_busy=self.ocr_busy,capture_pending=self.capture_pending,
            target_present=bool(self.target),target_role=self.debug_target_role(),
            target_foreground=foreground,lcu_selection=self.lcu_toggle.isChecked(),
            hero_auto=self.hero_auto.isChecked(),pixel_fallback=self._lcu_pixel_fallback and not self.selection_retry.ready(time.monotonic())))
    def debug_state(self,state):
        if not self.debug_log.enabled:return
        # Revisions identify hero/round changes without persisting any names.
        hero=(self.state.hero,self.state.hero_observed,self.selection_session.candidate if self.selection_session else '')
        candidates=(tuple(self.state.observed),tuple(self.state.offered))
        if hero!=self._debug_hero:self._debug_hero=hero;self._debug_hero_revision+=1
        if candidates!=self._debug_candidates:self._debug_candidates=candidates;self._debug_candidate_revision+=1
        previous=self.selection_session.last_client_frame if self.client_phase() and self.selection_session else self.last_observation
        age=max(0.,(time.monotonic()-previous)*1000) if previous else None
        values=dict(state=state,running=self.state.running,confirmed=self.state.confirmed,
            generation=self.state.generation,serial=self._capture_serial,
            session_generation=self.selection_session.generation if self.selection_session else 0,
            stage=self.selection_session.stage if self.selection_session else 'idle',
            ocr_busy=self.ocr_busy,capture_pending=self.capture_pending,visible=self.overlay.isVisible(),
            rechecking=self.overlay._rechecking,hero_present=bool(self.state.hero),manual_editing=self.manual_editing,
            hero_revision=self._debug_hero_revision,candidate_revision=self._debug_candidate_revision,
            candidate_count=len(self.state.offered if self.state.confirmed else self.state.observed),stable_frames=self.state.stable_frames,
            automatic_frames=self.state.automatic_frames,hero_stable_frames=self.state.hero_stable_frames,
            fresh=bool(age is not None and age<=4000))
        if values!=self._debug_snapshot:
            self._debug_snapshot=values
            self.debug_log.record('state',**values,**({'age_ms':age} if age is not None else {}))
    def resizeEvent(self,event):
        if hasattr(self,'hero_avatar'):
            narrow=self.width()<660
            self.main_layout.setSpacing(10 if self.height()<490 else 16)
            self.brand_label.setVisible(self.width()>=520 or self.pages.currentIndex()==0)
            self.hero_avatar.setVisible(not narrow)
            self.hero_title.setStyleSheet('font-size:'+('24' if narrow else '30')+'px;font-weight:600')
            self.hero_row.setSpacing(12 if narrow else 24)
            self.layout().setContentsMargins(*((16,10,16,12) if narrow else (28,12,28,14)))
            self.candidate_row.setSpacing(8 if narrow else 16);self.candidate_row.setDirection(QtWidgets.QBoxLayout.Direction.TopToBottom if self.width()<520 else QtWidgets.QBoxLayout.Direction.LeftToRight)
            for view in self.candidate_views:
                view['frame'].layout().setContentsMargins(*((10,12,10,12) if narrow else (20,18,20,18)))
                view['name'].setStyleSheet('font-size:'+('16' if narrow else '18')+'px;font-weight:600')
            self.client_follow.setText('自动接续同目录的\n客户端与游戏' if self.width()<520 else '自动接续同目录的客户端与游戏')
            columns=2 if self.width()<520 else 4
            for index,field in enumerate(self.roi_fields):
                self.roi_layout.removeWidget(field);self.roi_layout.addWidget(field,index//columns,index%columns)
            self.footer_note.setVisible(self.width()>=600);self.shortcut_label.setVisible(self.width()>=480)
        super().resizeEvent(event)
    @staticmethod
    def neutral_augment(size):
        # One original neutral glyph for all slots: no invented art/category mapping.
        dpr=float(QtWidgets.QApplication.primaryScreen().devicePixelRatio());pixmap=QtGui.QPixmap(round(size*dpr),round(size*dpr));pixmap.setDevicePixelRatio(dpr);pixmap.fill(QtCore.Qt.GlobalColor.transparent)
        painter=QtGui.QPainter(pixmap);painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing);painter.setPen(QtGui.QPen(QtGui.QColor('#73869F'),1.6));painter.setBrush(QtGui.QColor('#F2F6FC'))
        points=QtGui.QPolygonF([QtCore.QPointF(size*.5,size*.08),QtCore.QPointF(size*.9,size*.5),QtCore.QPointF(size*.5,size*.92),QtCore.QPointF(size*.1,size*.5)])
        painter.drawPolygon(points);painter.drawLine(QtCore.QPointF(size*.5,size*.31),QtCore.QPointF(size*.5,size*.69));painter.drawLine(QtCore.QPointF(size*.32,size*.5),QtCore.QPointF(size*.68,size*.5));painter.end();return pixmap
    @staticmethod
    def neutral_portrait(size):
        # Original generic person glyph, never a claimed champion portrait.
        dpr=float(QtWidgets.QApplication.primaryScreen().devicePixelRatio());pixmap=QtGui.QPixmap(round(size*dpr),round(size*dpr));pixmap.setDevicePixelRatio(dpr);pixmap.fill(QtCore.Qt.GlobalColor.transparent)
        painter=QtGui.QPainter(pixmap);painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        painter.setPen(QtCore.Qt.PenStyle.NoPen);painter.setBrush(QtGui.QColor('#EDF1F7'));painter.drawEllipse(0,0,size,size)
        painter.setBrush(QtGui.QColor('#BFC9D9'));painter.drawEllipse(QtCore.QRectF(size*.35,size*.22,size*.3,size*.3));painter.drawRoundedRect(QtCore.QRectF(size*.23,size*.57,size*.54,size*.25),size*.12,size*.12);painter.end();return pixmap
    def fit_control_to_screen(self,*,initial=False):
        available=self.screen().availableGeometry()
        width=min(900 if initial else self.width(),max(360,available.width()-32))
        height=min(490 if initial else self.height(),max(280,available.height()-64))
        self.setMinimumSize(min(640,width),min(440,height));self.resize(width,height)
        if self.isVisible():
            frame=self.frameGeometry();self.move(available.x()+max(0,(available.width()-frame.width())//2),available.y()+max(0,(available.height()-frame.height())//2))
    def show_page(self,page):
        self.pages.setCurrentIndex(0 if page=='main' else 1);self.brand_label.setVisible(self.width()>=520 or page=='main');self.secondary_stop.setVisible(page!='main' and self.state.running);self.back_button.setVisible(page!='main')
        self.correction_panel.setVisible(page=='correction');self.advanced_panel.setVisible(page=='settings');self.about_panel.setVisible(page=='about')
        self.advanced_toggle.blockSignals(True);self.advanced_toggle.setChecked(page=='settings');self.advanced_toggle.blockSignals(False)
        self.secondary_title.setText({'correction':'核对与资料','settings':'监测设置','about':'关于与数据来源'}.get(page,''))
    def set_advanced_visible(self,visible):
        self.show_page('settings' if visible else 'main')
    def refresh_card_details(self,*_):
        self.refresh_dashboard()
        expanded=self.details_toggle.isChecked();self.card_details.setVisible(expanded);self.details_toggle.setArrowType(QtCore.Qt.ArrowType.DownArrow if expanded else QtCore.Qt.ArrowType.RightArrow)
        if self.overlay._titles_pending:
            self.card_details.setText('正在核对当前候选，确认后显示资料。');return
        if not expanded:return
        # A deliberate dictionary view of editable names, not a retained game
        # result. Foreground loss still revokes hero/overlay confirmation.
        hero=self.hero_box.currentText() if not self.hero_auto.isChecked() else ''
        hero=hero if self.data and hero in self.data.get('heroes',{}) else ''
        rows=['资料查阅 · 基于输入名称，不代表识别或确认。',
              '人工选择英雄：'+hero if hero else '未选择人工英雄：仅展示基础说明，不推断英雄专属评级或条件。']
        for index,edit in enumerate(self.inputs,1):
            name=edit.text().strip()
            if not self.data or name not in self.data.get('augments',{}):
                rows.append(f'{index} · 名称未精确匹配词典，请在上方核对。');continue
            card=display_cards(self.data,hero,[name])[0]
            text=f"{index} · {name}\n{card['description']}"
            if hero:
                text+=f"\n{card.get('sourceTierLabel','虎牙公开源评级')}：{card.get('sourceTier') or '暂无评级'}"
                if card.get('sourceHint'):text+='\n公开源搭配：'+card['sourceHint']
                if card['notes']:text+='\n条件/提醒：'+'；'.join(card['notes'])
            rows.append(text)
        text='\n\n'.join(rows)
        if self.card_details.text()!=text:self.card_details.setText(text)
    def client_assignment_visible(self):
        return bool(self.selection_session and self.selection_session.active and self.target and self.target.identity==self.selection_session.client)
    def save_monitor_preferences(self,*_):
        self.monitor_preferences={'live_identity':self.live_identity_toggle.isChecked(),'minimize_on_start':self.minimize_on_start.isChecked()}
        try:save_preferences(self.state_dir,self.monitor_preferences)
        except OSError:self.status.setText('设置已用于本次启动，但未能保存；下次启动请重新核对。')
    def live_identity_preference_changed(self,*_):
        self.lcu_consent_changed()
        self.save_monitor_preferences()
    def lcu_consent_changed(self,*_):
        self.stop_monitor();self.lcu_snapshot.clear()
        self.footer_note.setText('截图 + 本机只读接口' if self.lcu_toggle.isChecked() or self.live_identity_toggle.isChecked() else '仅窗口像素 · 兼容性待验证')
    def enable_client_selection(self):
        running=self.state.running
        self.lcu_toggle.setChecked(True)
        if running:self.start_monitor()
        self.status.setText('本机选人识别已开启，请切回客户端。' if running else '本机选人识别已开启，请点击开始监测。')
    def game_identity_scope(self,value):
        if not self.state.running or not self.hero_auto.isChecked() or self.client_phase():return None
        verified=bool((self.automatic_policy and self.automatic_policy.bound and self.automatic_policy.bound.role=='game') or (self.window_policy and self.target and self.target.identity==self.window_policy.game_identity))
        scope=value.get('_frameScope')
        if not verified or not self.partial_scope_current(scope):return None
        try:
            if scope[1]!=self.capture_metadata():return None
        except (CapturePaused,CaptureUnavailable,OSError,ValueError):return None
        from live_client_identity import source_hero_names
        mapping=tuple(sorted(source_hero_names(self.data).items()))
        if value.get('_identityMapping')!=mapping:return None
        return (self.discovery_scope,scope[0],scope[1],scope[4],scope[5],scope[6],mapping)
    def private_identity_binding_current(self):
        scope=self.hero_continuity.scope
        if not scope or not self.state.running or not self.target or self.client_phase():return False
        try:
            from live_client_identity import source_hero_names
            matcher=self.hero_matcher if self.hero_auto.isChecked() else None
            current=(self.discovery_scope,self.target.identity,self.capture_metadata(),tuple(self.data['augments']),
                (id(self.data),json.dumps(self.data.get('metadata',{}),sort_keys=True,ensure_ascii=False)),
                (matcher,matcher.proof_identity() if matcher and hasattr(matcher,'proof_identity') else None),
                tuple(sorted(source_hero_names(self.data).items())))
            return bool(scope==current and self.target_allowed())
        except (CapturePaused,CaptureUnavailable,OSError,ValueError,TypeError,KeyError):return False
    def identity_wait_message(self,value,*,working=False):
        prefix='已取得游戏画面，候选文字识别中。' if working else '候选文字已处理，但本人英雄尚未可靠确定。'
        if not self.live_identity_toggle.isChecked():
            return prefix+' 可在设置开启“本局英雄身份只读核验”，或人工纠正英雄。'
        if value.get('_liveIdentityUnavailable'):
            return prefix+' 本机英雄接口暂不可用；已有本局可靠身份会按同局范围保留，否则等待可靠画面或人工纠正。'
        return prefix+' 本机英雄只读核验已开启；等待可靠身份。'
    def canonical_champion_map(self,*,diagnostic_callback=None):
        from live_client_identity import report_outcome,MAP_OUTCOMES
        outcome='manifest_unavailable'
        try:
            if self._verified_roster_map:
                outcome='verified_roster';return dict(self._verified_roster_map)
            if self._portrait_memory_map:
                outcome='verified_memory';return dict(self._portrait_memory_map)
            cache=self.state_dir/'hero-portraits'
            try:raw=(cache/'manifest.json').read_text(encoding='utf8')
            except UnicodeError:
                outcome='manifest_invalid';raise
            outcome='manifest_invalid'
            manifest=json.loads(raw);version=manifest['version']
            if not isinstance(version,str) or not __import__('re').fullmatch(r'\d{1,3}\.\d{1,3}\.\d{1,3}',version):return {}
            outcome='roster_unavailable'
            roster=(cache/f'roster-{version}.json').read_bytes()
            outcome='hash_mismatch'
            if hashlib.sha256(roster).hexdigest()!=manifest.get('rosterSha256'):return {}
            outcome='roster_invalid'
            from hero_portraits import parse_roster
            mapping={row['asset'][:-4]:row['championId'] for row in parse_roster(roster,version)}
            outcome='verified'
            return mapping
        except (OSError,ValueError,KeyError,TypeError):return {}
        finally:report_outcome(diagnostic_callback,outcome,MAP_OUTCOMES)
    def client_selection_reference(self):
        if self.state.running and self.lcu_toggle.isChecked() and self.hero_auto.isChecked() and self.client_assignment_visible():
            from lcu_selection import selection_reference
            value=self.lcu_snapshot.current(self.target.identity,time.monotonic())
            reference=selection_reference(self.data,value)
            if reference:return reference
        return self.client_strength_reference()
    def client_strength_reference(self):
        if not self.state.running or not self.hero_auto.isChecked() or not self.client_assignment_visible() or not self.state.hero or self.selection_session.stage!='assigned':return None
        if not 0<=time.monotonic()-self.selection_session.last_client_frame<=4:return None
        from hero_strength import hero_strength_reference
        return hero_strength_reference(self.data,self.state.hero,champion_id=self.selection_session.assigned)
    def refresh_hero_portrait(self,hero):
        champion_id=self.portrait_bank.hero_id(self.data,hero) if hero else None
        dpr=float(self.hero_avatar.devicePixelRatioF());key=(hero,champion_id,self.portrait_bank.revision,dpr)
        if key==self._hero_portrait_key:return
        self._hero_portrait_key=key;portrait=self.portrait_bank.pixmap(champion_id,108,dpr)
        self.hero_avatar.setPixmap(portrait if portrait is not None else self.neutral_portrait(108))
        self.hero_avatar.setAccessibleName(hero+' · 官方基础头像' if portrait is not None else '通用身份占位图，不是英雄画像')
    def clear_partial_candidates(self):
        self.partial_candidates.clear();self._partial_revision+=1
        self._partial_hero='';self._partial_scope=None;self._partial_displayed=False
        self._accepted_partial_frame=None;self._semantic_partial_frame=None
    def partial_scope_current(self,scope):
        if not isinstance(scope,tuple) or len(scope)!=7 or not self.data or not self.target:return False
        matcher=self.hero_matcher if self.hero_auto.isChecked() else None
        source=(id(self.data),json.dumps(self.data.get('metadata',{}),sort_keys=True,ensure_ascii=False))
        return bool(scope[0]==self.target.identity and scope[2]==self.last_rect
            and scope[3]==tuple(spin.value()/100 for spin in self.roi)
            and scope[4]==tuple(self.data['augments']) and scope[5]==source
            and scope[6]==(matcher,matcher.proof_identity() if matcher and hasattr(matcher,'proof_identity') else None))
    def current_partial_names(self,now=None):
        if (not self.state.running or not self.state.hero or self.manual_editing
                or self.state.hero!=self._partial_hero or not self.partial_scope_current(self._partial_scope)):
            return EMPTY_SLOTS
        return self.partial_candidates.visible(time.monotonic() if now is None else now)
    def observe_partial_candidates(self,value,captured_at):
        # The first confident own-HUD observation may seed private title
        # evidence, just as the full-triplet path does. Display separately
        # requires state.hero's two-frame confirmation of that exact identity.
        observation=value.get('hero_observation',{})
        hero=(observation.get('hero') if observation.get('confident') is True else '') if self.hero_auto.isChecked() else self.state.hero
        scope=value.get('_frameScope')
        safe=bool(hero in self.data.get('heroes',{}) and not self.manual_editing and self.partial_scope_current(scope))
        if not safe:
            self.clear_partial_candidates();return EMPTY_SLOTS
        self._partial_hero=hero;self._partial_scope=scope
        return self.partial_candidates.observe(value.get('partial_title_evidence'),
            frame_serial=value.get('_captureSerial'),captured_at=captured_at,now=time.monotonic(),
            context=(self._partial_revision,scope,hero),guards_passed=True,ocr_reused=value.get('ocr_reused'))
    def partial_display_cards(self,names):
        cards=display_cards(self.data,self.state.hero,names)
        for name,card in zip(names,cards):
            if not name:
                card.update(name='待识别',description='',sourceTier=None,notes=[],pending=True)
        return cards
    def show_partial_candidates(self,*,rechecking=False):
        names=self.current_partial_names()
        if not any(names):
            self._partial_displayed=False;return False
        metadata=self.data.get('metadata',{})
        source_version=f"数据包 {metadata.get('wikiDataVersion') or '未知'} / 游戏资料 {metadata.get('gamePatch') or '未知'}"
        self._accepted_frame=None;self._restore_while_ocr=False
        self.overlay.set_cards(self.state.hero,self.partial_display_cards(names),metadata.get('sourceDataDate') or '未知',source_version,'部分候选连续高置信确认')
        self._restore_while_ocr=bool(rechecking);self.overlay.set_rechecking(rechecking)
        self._partial_displayed=True
        self.state.reason='已确认的候选单独显示资料；其余位置等待当前画面识别。';self.status.setText(self.state.reason)
        self.debug_event('recognition',reason='partial_confirmed',candidate_count=sum(bool(name) for name in names),hero_present=True)
        return True
    def refresh_dashboard(self):
        if not hasattr(self,'candidate_views'):return
        title_pending=self.overlay._titles_pending
        current=bool(not title_pending and self.state.running and self.state.confirmed and self.data and len(self.state.offered)==3 and all(name in self.data.get('augments',{}) for name in self.state.offered))
        partial=self.current_partial_names() if not current and not title_pending else EMPTY_SLOTS
        hero=self.state.hero if self.state.running and self.state.hero and not title_pending else ''
        from hero_strength import hero_strength_reference
        client_auto=self.client_assignment_visible() and self.hero_auto.isChecked()
        self.selection_optin.setVisible(bool(self.state.running and client_auto and not self.lcu_toggle.isChecked()))
        strength=self.client_strength_reference() if client_auto else hero_strength_reference(self.data,hero) if hero else None
        if client_auto and not strength:hero=''
        self.hero_title.setText(hero or '等待识别');self.refresh_hero_portrait(hero)
        self.hero_caption.setText(('人工查阅英雄' if hero and not self.hero_auto.isChecked() else '本局英雄')+(' · 英雄整体强度 '+(strength['sourceTier'] or '暂无评级') if strength else ''))
        self.hero_caption.setAccessibleName((strength['sourceTierLabel']+'：'+(strength['sourceTier'] or '暂无评级')) if strength else '本局英雄尚未可靠确定')
        self.hero_provenance.setText(('人工选择 · 未自动推断' if not self.hero_auto.isChecked() else '本局选人 · 仍可交换，HUD未复核' if self.client_assignment_visible() else '来自本局选人 · HUD未复核' if self.hero_origin=='client-provisional' else '本局选人 + HUD复核' if self.hero_origin=='client-verified' else '本局此前已确认 · 当前头像未重新确认' if self.hero_origin=='game-continuity' else '本机游戏接口 · 本人英雄连续核验' if self.hero_origin=='game-api' else '本人 HUD 连续确认') if hero else '')
        self.hero_provenance.setVisible(bool(hero and self.hero_origin=='game-continuity'));self.secondary_stop.setVisible(self.pages.currentIndex()!=0 and self.state.running)
        if hasattr(self,'overlay'):self.toggle_button.setChecked(self.overlay.click_through)
        self.monitor_actions.setCurrentWidget(self.stop_button if self.state.running else self.start_button);self.stop_button.setEnabled(bool(self.state.running))
        cards=display_cards(self.data,hero,self.state.offered) if current else self.partial_display_cards(partial) if any(partial) else []
        self.candidate_caption.setText('正在核对当前候选，确认后显示评级' if title_pending else '上次候选 · 正在复核，尚非本帧结果' if cards and self.overlay._rechecking else ('虚构演示资料' if self.data.get('metadata',{}).get('isDemo') else '虎牙公开源 · 非 Riot 评级') if current else '部分候选已确认 · 其余等待识别' if any(partial) else '等待三个候选稳定确认')
        for index,view in enumerate(self.candidate_views):
            card=cards[index] if cards else None;tier=card.get('sourceTier') if card else None
            view['name'].setText(card['name'] if card else '等待识别');view['tier'].setText(tier or '—')
            view['tier'].setAccessibleName((card['sourceTierLabel'] if card else '选项尚未确认')+'：'+(tier or '暂无评级'))
            view['tier'].setProperty('known',tier=='T1');view['tier'].style().unpolish(view['tier']);view['tier'].style().polish(view['tier'])
            view['detail'].setText((('暂无评级 · ' if not tier else '')+card['description'][:34]+('…' if len(card['description'])>34 else '')) if card and not card.get('pending') else '识别稳定后显示资料')
        self._refresh_badge()
        self.refresh_history()
        if self.last_timings:
            if self.last_timings.get('backend')=='lcu-read-only':
                from lcu_selection import unavailable_reason
                self.capture_diagnostic.setText('本机选人接口 · 本次未截图\n读取 '+str(self.last_timings.get('inference_ms','未知'))+' ms'+('\n'+unavailable_reason(self._lcu_error) if self._lcu_error else ''))
                return
            mode=getattr(self.capture,'visible_capture_status','unknown')
            mode_text={'eligible':'保护显示捕获：截图时无需隐藏评级','interactive':'交互模式：每次截图需暂时隐藏；开启鼠标穿透可尝试保护显示','backend_unavailable':'当前后端需隐藏截图，可能短暂闪烁','exclusion_unregistered':'系统未确认叠加排除：暂用隐藏截图','cleanup_pending':'等待上次截图关闭，暂不开始新截图','disabled':'保护显示捕获未启用','stopped':'截图已停止'}.get(mode,'截图模式待确认')
            self.capture_diagnostic.setText(mode_text+'\n'+f"最近后端 {getattr(self.capture,'last_backend','未知')} · 截图 {self.last_timings.get('capture_ms','未知')} ms · 本地识别 {self.last_timings.get('inference_ms','未知')} ms\n若已识别但游戏内不可见，请比较全屏与无边框；当前诊断不能证明真实独占全屏兼容。")
    def refresh_history(self):
        if not hasattr(self,'history_view'):return
        record=self.last_candidates
        if record and (record['scope']!=self.history_scope() or (self.state.hero and record['hero']!=self.state.hero)):
            self.last_candidates=None;record=None
        if not record:self.history_view.setText('上次候选 · 最终选择未知\n尚无本次监测记录。');return
        age=max(0,int(time.monotonic()-record['recorded_at']))
        rows=[f"上次候选 · 最终选择未知 · {age} 秒前",record['hero']+' · '+record['confirmation'],f"来源日期 {record['source_date']} · {record['source_version']}"]
        rows.extend(f"{('左','中','右')[i]}：{card['name']} · {card['sourceTierLabel']}：{card['sourceTier'] or '暂无评级'}" for i,card in enumerate(record['cards']))
        rows.append('这是先前确认过的三个候选，不是当前推荐，也没有推断最终选择；停止监测后清空。')
        self.history_view.setText('\n'.join(rows))
    def history_scope(self):
        identity=self.target.identity if self.target else self.state.target;metadata=self.manual_metadata
        if self.automatic_policy and self.automatic_policy.bound:metadata=self.automatic_policy.bound.metadata
        elif self.window_policy and self.target:metadata=self.window_policy.client_meta if self.target.identity==self.window_policy.client_identity else self.window_policy.game_meta
        return identity,metadata
    def refresh_status_badge(self):
        self.refresh_card_details()
    def _refresh_badge(self):
        if self.debug_log.failed and self.debug_toggle.isChecked():
            self.debug_toggle.blockSignals(True);self.debug_toggle.setChecked(False);self.debug_toggle.blockSignals(False)
            self.debug_status.setText('本地日志无法写入，已停止记录；已有日志和导出保留，监测不受影响。')
        # Presentation only: derive from explicit state, never status-text keywords.
        if self.startup_error:state,text='error','资料加载失败 · 关于查看详情'
        elif not self.data:state,text='waiting','资料待就绪'
        elif not self.capture:state,text='waiting',('演示资料 · 未连接游戏' if self.data.get('metadata',{}).get('isDemo') else '采集不可用')
        elif not self.state.running:state,text='idle','未开始'
        elif self.overlay._titles_pending:state,text='working','当前候选 · 正在复核'
        elif self.overlay._rechecking:state,text='working','上次资料 · 正在复核'
        elif self.state.confirmed:state,text='confirmed','资料已确认'
        elif any(self.current_partial_names()):state,text='working','部分候选已确认'
        elif self.client_selection_reference():state,text='provisional','当前选人资料已确认 · 仍可交换'
        elif self.ocr_busy:state,text='working','正在识别'
        elif self.target is None:state,text='waiting','等待连接'
        else:state,text='waiting','等待核对'
        if self.capture and self.state.running and self.state.hero and self.hero_auto.isChecked() and (self.hero_origin=='client-provisional' or self.client_assignment_visible()):state='provisional'
        if self.status_chip.property('state')!=state:
            self.status_chip.setProperty('state',state);self.status_chip.style().unpolish(self.status_chip);self.status_chip.style().polish(self.status_chip)
        if self.capture and self.state.running and self.state.hero:text=self.hero_provenance.text()+' · '+text
        self.status_chip.setText(text)
        mode=getattr(self.capture,'visible_capture_status','unknown') if self.capture else 'unknown'
        mode_text={'eligible':'保护显示捕获','interactive':'交互模式，需隐藏截图','exclusion_unregistered':'排除未确认，需隐藏截图','backend_unavailable':'后端需隐藏截图','cleanup_pending':'等待截图清理','disabled':'隐藏截图','stopped':'截图停止'}.get(mode,'等待截图')
        if self.client_assignment_visible():
            from selection_retry import selection_capture_status
            self.footer_note.setText(selection_capture_status(self._selection_capture_state)+(' · 接口稍后重试' if self._lcu_error and self._selection_capture_state!='interface_failed' else ''))
        else:self.footer_note.setText(('本机英雄核验开启' if self.live_identity_toggle.isChecked() else '仅截图身份')+' · '+mode_text)
        self.debug_state(state)
    def spawn(self,kind,fn,generation=0):
        logger=self.debug_log.scoped();queued_at=time.monotonic();serial=self._capture_serial if kind in ('ocr','selection') else 0
        logger.record('job',kind=kind,phase='queued',generation=generation,serial=serial)
        def worker():
            value=error=None
            logger.record('job',kind=kind,phase='started',generation=generation,serial=serial,queue_ms=max(0.,(time.monotonic()-queued_at)*1000))
            try:
                if self._cancel_workers.is_set():
                    logger.record('job',kind=kind,phase='cancelled',generation=generation,serial=serial,reason='closed');return
                try:value=fn()
                except Exception as exc:
                    error=str(exc)
                    error_code='capture_paused' if isinstance(exc,CapturePaused) else 'capture_unavailable' if isinstance(exc,CaptureUnavailable) else 'worker_error'
                    logger.record('job',kind=kind,phase='error',generation=generation,serial=serial,reason=getattr(exc,'reason_code','unknown'),
                        error_code=error_code,worker_error_category=classify_worker_error(exc,error_code=error_code))
                # Serialized with closeEvent: never emit into Qt after teardown starts.
                with self._worker_lock:
                    if not self._cancel_workers.is_set() and not self.closed:
                        if error is None:
                            logger.record('job',kind=kind,phase='completed',generation=generation,serial=serial)
                            self.signals.result.emit(kind,value,generation)
                        else:self.signals.error.emit(kind,error,generation)
                    else:logger.record('job',kind=kind,phase='discarded',generation=generation,serial=serial,reason='closed')
            finally:
                with self._worker_lock:self._workers.discard(threading.current_thread())
        job=threading.Thread(target=worker,name='vga-'+kind,daemon=True)
        with self._worker_lock:
            if self._cancel_workers.is_set():return
            self._workers.add(job);job.start()
    def request_portraits(self):
        """One public-asset worker; capture generations never own this lease."""
        if self.closed or self._portraits_busy or not self.data or self.data.get('metadata',{}).get('isDemo'):return
        from hero_portraits import load_portraits
        self._portraits_busy=True;self._portraits_attempt+=1;attempt=self._portraits_attempt
        self.debug_log.record('templates',template_outcome='loading',generation=attempt)
        def cached(bank,status):
            with self._worker_lock:
                if not self.closed and not self._cancel_workers.is_set():
                    self.signals.result.emit('portraits-cache',(bank,status),attempt)
        def roster(mapping,status):
            with self._worker_lock:
                if not self.closed and not self._cancel_workers.is_set():
                    self.signals.result.emit('portraits-roster',(mapping,status),attempt)
        self.spawn('portraits',lambda:load_portraits(self.state_dir/'hero-portraits',allow_download=self.enable_updates,
            cancelled=self._cancel_workers,cached_callback=cached,roster_callback=roster),attempt)
    def retry_portraits(self):
        if (self.closed or self._portraits_busy or self.hero_matcher is not None or self._pending_portraits is not None or not self.enable_updates
                or not self.state.running or not self.hero_auto.isChecked() or self._portraits_retry_at is None
                or time.monotonic()<self._portraits_retry_at):return
        self.request_portraits()
    def finish_portrait_attempt(self):
        self._portraits_busy=False
        if self.hero_matcher is not None or self._pending_portraits is not None:
            self._portraits_failures=0;self._portraits_retry_at=None
        elif self.enable_updates:
            self._portraits_failures+=1
            delay=(30,60,120,300)[min(self._portraits_failures-1,3)]
            self._portraits_retry_at=time.monotonic()+delay
            self.debug_log.record('templates',template_outcome='retry_wait',generation=self._portraits_attempt,ttl_ms=delay*1000)
    def portrait_model_key(self,portraits):
        """Exact decoded inputs and names, independent of bank/PIL identity."""
        digest=hashlib.sha256()
        for champion_id,image in sorted(portraits.items()):
            rgb=image.convert('RGB')
            digest.update(json.dumps((champion_id,rgb.size),separators=(',',':')).encode())
            digest.update(rgb.tobytes())
        names={str(row.get('championId')):name for name,row in self.data['heroes'].items()
            if isinstance(row,dict) and str(row.get('championId','')).isdigit()}
        return digest.digest(),tuple(sorted(names.items()))
    def receive_portrait_roster(self,value):
        """A complete verified public roster is usable before image readiness."""
        from live_client_identity import _valid_map
        try:
            snapshot,status=value
            if (not isinstance(snapshot,tuple) or not 100<=len(snapshot)<=400
                    or any(not isinstance(row,tuple) or len(row)!=2 for row in snapshot)
                    or not isinstance(status,dict) or status.get('state')!='verified-roster'):return
            mapping=dict(snapshot);version=status.get('version');digest=status.get('rosterSha256')
            if (len(mapping)!=len(snapshot) or not _valid_map(mapping) or status.get('count')!=len(mapping)
                    or not isinstance(version,str) or not __import__('re').fullmatch(r'\d{1,3}\.\d{1,3}\.\d{1,3}',version)
                    or not isinstance(digest,str) or not __import__('re').fullmatch(r'[0-9a-f]{64}',digest)):return
        except (TypeError,ValueError):return
        # Separate from a portrait bank's persistence status: missing/corrupt
        # images cannot erase a complete, independently validated identity map.
        # This supplies lookup data only; every API identity is still read and
        # reconciled afresh under the current game/process/capture guards.
        self._verified_roster_map=tuple(sorted(mapping.items()))
        self._verified_roster_source=(version,digest)
        self.debug_log.record('templates',template_outcome='roster_ready',generation=self._portraits_attempt)
    def set_portrait_memory_map(self,portraits,status):
        mapping=status.get('canonicalMap',{})
        self._portrait_memory_map=tuple(sorted(mapping.items())) if status.get('state')=='memory-only' and isinstance(mapping,dict) and len(mapping)==len(portraits) else ()
    def publish_portrait_images(self,portraits,key):
        # The bounded display copies grant no recognition authority. They may
        # update while their matching recognition model waits for a boundary.
        if self._portrait_display_key==(key[0],self.portrait_bank.revision):return
        self.portrait_bank.replace(portraits);self._hero_portrait_key=None
        self._portrait_display_key=(key[0],self.portrait_bank.revision)
    def publish_portraits(self,portraits,status,key,matcher):
        self.set_portrait_memory_map(portraits,status)
        self.publish_portrait_images(portraits,key)
        self._portraits_bank=portraits;self.hero_matcher=matcher;self._portrait_model_key=key
        self._pending_portraits=None
    def receive_portraits(self,portraits,status):
        key=self.portrait_model_key(portraits)
        if self.hero_matcher is not None and key==self._portrait_model_key:
            # New objects/version labels do not change recognition authority.
            self.set_portrait_memory_map(portraits,status);self._pending_portraits=None
            self.publish_portrait_images(portraits,key)
            return 'unchanged'
        from hero_recognition import PortraitMatcher
        matcher=self._pending_portraits[3] if self._pending_portraits is not None and key==self._pending_portraits[2] else PortraitMatcher(portraits,self.data['heroes'])
        if self.state.running and (self.hero_matcher is not None or self.ocr_busy or self.capture_pending or self.portrait_display_authority()):
            # Never replace a viable model underneath a live frame or display.
            # A first HUD model must also preserve an already accepted API
            # display; its None->matcher scope transition is equally real.
            # Keep only the latest fully prepared bank for a real scope boundary.
            self._pending_portraits=(portraits,dict(status),key,matcher)
            self.publish_portrait_images(portraits,key)
            return 'deferred'
        if self.state.running:
            # Even an idle first-model arrival must not count an earlier API
            # observation from the None-model scope toward its confirmation.
            self.invalidate_scene('头像模板已准备，等待当前画面重新识别。')
        self.publish_portraits(portraits,status,key,matcher)
        return 'installed'
    def portrait_display_authority(self):
        return bool(self.state.confirmed or self._partial_displayed or self._accepted_frame
            or self._accepted_partial_frame or self.overlay.reference or self.overlay.isVisible())
    def activate_idle_first_portraits(self):
        # Do not strand the first HUD model if the API becomes unavailable or
        # its display expires. Between captures, after all display authority
        # has gone, revoke remaining private counters before changing scope.
        if (self.hero_matcher is not None or self._pending_portraits is None
                or self.ocr_busy or self.capture_pending or self.portrait_display_authority()):return
        self.invalidate_scene('头像模板已准备，等待当前画面重新识别。')
        self.apply_pending_portraits()
    def apply_pending_portraits(self):
        """Publish after boundary invalidation, or idle first-model revocation."""
        if self.closed or self._pending_portraits is None:return
        portraits,status,key,matcher=self._pending_portraits
        try:
            current_key=self.portrait_model_key(portraits)
            if current_key!=key:
                from hero_recognition import PortraitMatcher
                matcher=PortraitMatcher(portraits,self.data['heroes'])
            self.publish_portraits(portraits,status,current_key,matcher)
            self.debug_log.record('templates',template_outcome='ready',generation=self._portraits_attempt)
            self.hero_status.setText(status.get('message','头像模板已更新'))
        except Exception as exc:
            self.debug_log.record('templates',template_outcome='unavailable',generation=self._portraits_attempt,worker_error_category=classify_worker_error(exc))
            self.hero_status.setText('新头像模板初始化失败；保留原模板，等待恢复或人工纠正。')
    def register_hotkey(self):
        if self.capture:
            self.hotkey_registered=self.capture.hotkey(int(self.winId()))
            if not self.hotkey_registered:self.toggle_button.setToolTip('快捷键占用，请使用此按钮切换鼠标穿透')
    def refresh_windows(self):
        if not self.capture:return
        current=self.window_list.currentData();self.window_list.blockSignals(True);self.window_list.clear()
        self.window_list.addItem('自动识别英雄联盟（推荐，无需选择）',None)
        for info in self.capture.windows():self.window_list.addItem('高级诊断·手动指定：'+info.title,info)
        if current:
            for i in range(1,self.window_list.count()):
                item=self.window_list.itemData(i)
                if item.identity==current.identity:self.window_list.setCurrentIndex(i);break
        self.window_list.blockSignals(False)
        if self.automatic_policy and self.state.running:self.queue_discovery(force=True)
        elif not self.state.running:self.target=self.window_list.currentData()
    def target_changed(self,*_):
        self.stop_monitor();self.target=self.window_list.currentData();self.last_rect=None
    def discovery_snapshot(self):
        snapshot=getattr(self.capture,'discovery_snapshot',None)
        if snapshot is not None:
            value=snapshot()
            # A partially implemented snapshot cannot quietly omit the focus
            # or availability guard and fall back to legacy role arbitration.
            valid=(isinstance(value,dict) and set(value)=={'windows','foreground_hwnd','available_hwnds'}
                and isinstance(value['windows'],(tuple,list))
                and type(value['foreground_hwnd']) is int and value['foreground_hwnd']>=0
                and isinstance(value['available_hwnds'],(set,frozenset))
                and all(type(hwnd) is int and hwnd>0 for hwnd in value['available_hwnds']))
            if valid:
                from screen_capture import WindowInfo
                valid=(all(isinstance(window,WindowInfo) for window in value['windows'])
                    and value['available_hwnds'].issubset({window.hwnd for window in value['windows']}))
            if not valid:raise CapturePaused('窗口发现状态不完整，等待重新核验。')
            return value
        # Older/owned capture adapters may not expose foreground snapshots.
        # A supported snapshot's failure propagates; never bypass it by retrying
        # with the legacy, less-specific window list.
        return dict(windows=self.capture.windows(include_untitled=True))
    def target_allowed(self):
        if not self.target:return False
        if self.automatic_policy:
            try:return self.automatic_policy.permits(self.target,**self.discovery_snapshot())
            except Exception:
                self.debug_event('window_binding',binding_outcome='query_failed')
                return False  # A failed fresh query grants no authority.
        if self.window_policy:return self.window_policy.permits(self.target)
        try:
            from session_windows import process_metadata
            return self.target.identity==self.manual_identity and self.manual_metadata is not None and process_metadata(self.target.pid)==self.manual_metadata
        except (OSError,ValueError):return False
    def capture_metadata(self):
        if self.automatic_policy and self.automatic_policy.bound:
            return self.automatic_policy.bound.metadata
        if self.window_policy:
            return self.window_policy.client_meta if self.target.identity==self.window_policy.client_identity else self.window_policy.game_meta
        if self.manual_metadata is None:raise CapturePaused('目标进程身份尚未确认，请重新开始监测。')
        return self.manual_metadata
    def client_phase(self):
        if self.automatic_policy:return bool(self.automatic_policy.bound and self.automatic_policy.bound.role=='client')
        return bool(self.window_policy and self.target and self.target.identity==self.window_policy.client_identity)
    def queue_discovery(self,*,force=False):
        if not self.automatic_policy or not self.state.running or self.discovery_busy:return
        now=time.monotonic()
        if not force and now-self.last_window_discovery<1:return
        with self._worker_lock:
            if any(job.name=='vga-windows' and job.is_alive() for job in self._workers):return
        self.last_window_discovery=now;self.discovery_busy=True
        policy=self.automatic_policy;scope=self.discovery_scope
        def discover():
            return policy.discover(**self.discovery_snapshot())
        self.spawn('windows',discover,scope)
    def pause_window_discovery(self,*,binding_outcome='query_failed'):
        # Revoke GUI/capture evidence without dropping the policy's installation
        # and bound-role restriction (especially when following is disabled).
        reason='窗口状态暂时无法核验，旧资料已隐藏，稍后自动重新连接。'
        self.debug_event('window_binding',binding_outcome=binding_outcome)
        self.target=None;self.state.target=None;self.client_target=None;self.last_rect=None
        self.was_target_foreground=False
        if self.selection_session:self.selection_session.stop()
        self.selection_session=None;self.last_selection_source=None
        self.unverified_candidate=None;self.trust_button.hide()
        self.invalidate_scene(reason,debug_reason='target_unavailable')
        self.window_status.setText(reason)
    def apply_discovery(self,value,scope):
        if scope!=self.discovery_scope or not self.automatic_policy or not self.state.running:return
        self.discovery_busy=False;policy=self.automatic_policy;previous_binding=policy.bound
        self.debug_event('job',kind='windows',phase='completed',reason=getattr(value,'reason_code','unknown'),**dict(getattr(value,'diagnostics',())))
        new_confirmation=value.confirmation is not None and value.confirmation!=self.unverified_candidate
        self.unverified_candidate=value.confirmation;self.trust_button.setVisible(value.confirmation is not None)
        if new_confirmation and self.isMinimized():QtWidgets.QApplication.alert(self,0)
        try:adopted=bool(value.candidate) and policy.adopt(value,**self.discovery_snapshot())
        except Exception:
            self.pause_window_discovery();return
        if not adopted:
            self.debug_event('window_binding',binding_outcome='no_candidate' if not value.candidate else 'adoption_rejected')
            if self.target:self.invalidate_scene('等待唯一且已核验的英雄联盟窗口。')
            self.target=None;self.state.target=None;self.overlay.hide('target_unavailable');self.last_rect=None
            reason=value.reason if not value.candidate else '窗口列表已变化，正在重新检测；不会使用过期连接。'
            self.window_status.setText(reason);self.status.setText(reason);return
        candidate=policy.bound;target=candidate.window
        if candidate.role=='game':self.note_verified_game_scope(target,candidate.metadata.created)
        if self.target and target.identity==self.target.identity and previous_binding and previous_binding.metadata==candidate.metadata:
            if not self.target_allowed():self.pause_window_discovery(binding_outcome='adoption_rejected');return
            self.debug_event('window_binding',binding_outcome='unchanged',target_role=candidate.role)
            self.window_status.setText(value.reason+' '+target.title);return
        previous=self.target;session=self.selection_session;carried=False
        self.manual_editing=False
        for edit in self.inputs:edit.clear()
        if previous_binding is not None:
            self.state.clear_hero();self.hero_box.blockSignals(True);self.hero_box.setCurrentText('');self.hero_box.blockSignals(False)
        if candidate.role=='game' and session and previous and previous.identity==session.client:
            carried=session.begin_handoff(target.identity,time.monotonic(),generation=session.generation,
                new_game_window=candidate.metadata.created>policy.started_after)
        if not carried:
            if session:session.stop()
            self.selection_session=None
            if candidate.role=='client':
                from selection_session import SelectionSession
                self.selection_session=SelectionSession();self.selection_session.start(target.identity)
        self.client_target=target if candidate.role=='client' else None
        self.target=target;self.state.target=target.identity;self.last_rect=None;self.was_target_foreground=False
        self.debug_event('window_binding',binding_outcome='adopted',target_role=candidate.role)
        self.invalidate_scene('已自动连接'+('客户端，等待选人画面。' if candidate.role=='client' else '游戏，等待本人 HUD 与候选画面。'))
        self.apply_pending_portraits()
        self.overlay.hide('selection_changed');self.window_status.setText(value.reason+' '+target.title);self.status.setText(self.state.reason)
    def note_verified_game_scope(self,target,created):
        # Existing policy already verified this binding. Private identity stays
        # in memory; only the local diagnostic counter can change here.
        identity=(target.identity,created)
        if identity==self._debug_game_window:return
        if self._debug_game_window is not None:self.debug_log.begin_game()
        self._debug_game_window=identity
        self.debug_event('session',phase='accepted',reason='game_connected',target_role='game')
    def confirm_game_installation(self):
        candidate=self.unverified_candidate;policy=self.automatic_policy
        if not candidate or not policy or not self.state.running:return
        scope=self.discovery_scope
        message=('Windows 未能自动确认这个程序的发行商或游戏身份。\n\n'
            +'窗口：'+candidate.window.title+'\n程序：'+candidate.metadata.path
            +'\n\n请确认这是你自己的英雄联盟安装。本次监测将仅信任这个目录中的英雄联盟客户端与 Game\\League of Legends.exe，停止后失效。是否继续？')
        answer=QtWidgets.QMessageBox.question(self,'确认自己的英雄联盟安装',message,
            QtWidgets.QMessageBox.StandardButton.Yes|QtWidgets.QMessageBox.StandardButton.No,QtWidgets.QMessageBox.StandardButton.No)
        if answer!=QtWidgets.QMessageBox.StandardButton.Yes:return
        if scope!=self.discovery_scope or policy is not self.automatic_policy:return
        try:confirmed=policy.confirm_installation(candidate,**self.discovery_snapshot())
        except Exception:
            self.pause_window_discovery();return
        if confirmed:
            self.trust_button.hide();self.unverified_candidate=None;self.queue_discovery(force=True)
            if self.minimize_on_start.isChecked():self.showMinimized()
        else:self.status.setText('窗口身份已变化，正在重新检测，请确认新的提示。')
    def show_cache_diagnostics(self):
        if not isinstance(self.portrait_diagnostics,dict):return
        dialog=QtWidgets.QMessageBox(self);dialog.setWindowTitle('头像缓存诊断（仅本机）')
        dialog.setText('以下是缓存写入的错误码与文件状态，用于定位原因。没有截图、用户名或完整路径；不会自动上传。')
        dialog.setDetailedText(json.dumps(self.portrait_diagnostics,ensure_ascii=False,indent=2))
        dialog.setStandardButtons(QtWidgets.QMessageBox.StandardButton.Ok);dialog.exec()
    def hero_mode_changed(self,automatic):
        self.overlay.clear_candidate_geometry()
        self._geometry_frame=None
        self.hero_continuity.clear()
        self.clear_partial_candidates()
        self.retire_capture_session()
        self._accepted_frame=None;self._restore_while_ocr=False;self.overlay.set_rechecking(False)
        if not automatic:self.advanced_toggle.setChecked(True)
        self.hero_box.setEnabled(not automatic);self.state.clear_hero();self.refresh_card_details();self.overlay.hide('selection_changed');self.manual_editing=False
        self.hero_box.blockSignals(True);self.hero_box.setCurrentText('');self.hero_box.blockSignals(False)
        self.refresh_dashboard();self.hero_status.setText('等待本人 HUD 头像，连续两帧高置信后自动使用。' if automatic else '人工纠正模式：请选择已确认的本人英雄。')
    def hero_changed(self,text):
        self.overlay.clear_candidate_geometry()
        self._geometry_frame=None
        self.hero_continuity.clear()
        self.clear_partial_candidates()
        self.retire_capture_session()
        self._accepted_frame=None;self._restore_while_ocr=False;self.overlay.set_rechecking(False)
        if text:self.advanced_toggle.setChecked(True)
        if text and self.hero_auto.isChecked():
            self.hero_auto.blockSignals(True);self.hero_auto.setChecked(False);self.hero_auto.blockSignals(False);self.hero_box.setEnabled(True)
        hero=text if self.data and text in self.data.get('heroes',{}) else getattr(self,'hero_aliases',{}).get(text,'')
        self.hero_origin='manual';self.state.select_hero(hero);self.refresh_card_details();self.overlay.hide('selection_changed');self.status.setText(self.state.reason)
    def retire_capture_session(self):
        self.latest_capture.clear()
        self.debug_event('session',phase='retired')
        self._visible_previous=False;self._mode_wait_started=None
        # The adapter marks revocation immediately and performs any wrapper
        # lock/pipe/process cleanup off-GUI. Its cleanup barrier blocks reuse.
        retire=getattr(self.capture,'retire_session',None)
        if retire:retire()
    def invalidate_scene(self,reason,*,debug_reason='invalidate'):
        self.overlay.clear_candidate_geometry()
        self._geometry_frame=None
        # Scene/capture freshness is independent of a verified game identity.
        # Only a still-live exact binding may survive temporary interruption.
        transient=debug_reason in ('geometry_changed','focus_lost','stale_frame','ocr_timeout','worker_error','target_unavailable')
        if not transient or not self.private_identity_binding_current():self.hero_continuity.clear()
        self.clear_partial_candidates()
        self.debug_event('invalidate',reason=debug_reason)
        self.debug_event('cancel',reason=debug_reason,cancelled=True)
        self._visible_previous=False
        # An OCR/capture worker failure does not make an unavailable optional
        # API healthy again. Authority changes still revoke its retry scope.
        if debug_reason!='worker_error':
            self._lcu_pixel_fallback=False;self._lcu_error='';self.selection_retry.reset()
        self._selection_capture_state='waiting'
        self.lcu_snapshot.clear()
        self._capture_cancel.set();self.ocr_reuse.clear()
        self.retire_capture_session()
        self._accepted_frame=None;self._restore_while_ocr=False;self.overlay.set_rechecking(False)
        if self.hero_auto.isChecked():
            self.state.clear_hero();self.hero_box.blockSignals(True);self.hero_box.setCurrentText('');self.hero_box.blockSignals(False)
        self.state.invalidate(reason);self.overlay.hide(debug_reason);self.status.setText(reason);self.refresh_card_details()
    def roi_changed(self,*_):
        self.invalidate_scene('截图范围改变，请重新识别确认',debug_reason='geometry_changed');self.overlay.hide('geometry_changed')
    def edit_changed(self,*_):
        self.clear_partial_candidates()
        self.retire_capture_session()
        self._accepted_frame=None;self._restore_while_ocr=False;self.overlay.set_rechecking(False)
        self.manual_editing=True;self.state.invalidate('候选已修改，请重新确认',clear_observed=False);self.refresh_card_details();self.overlay.hide('unconfirmed')
    def follow_scope_changed(self,*_):
        self.stop_monitor();self.status.setText("接续窗口范围已改变；本局授权已停止，请重新点击开始。")
    def start_monitor(self):
        from automatic_windows import CLIENT_CLASSES,CLIENT_EXECUTABLES
        self.stop_monitor() # Revoke old scope before any validation can fail.
        if not self.capture:return self.status.setText('当前系统不支持窗口采集。')
        if not self.data or not self.data.get('augments'):return self.status.setText('没有可用词典，暂不能监测。')
        self.manual_editing=False;self.hero_origin='hud';self.target=self.window_list.currentData()
        if self.target is None:
            from automatic_windows import AutomaticWindowPolicy
            self.automatic_policy=AutomaticWindowPolicy(follow_roles=self.client_follow.isChecked())
            self.state.running=True;self.state.target=None;self.state.invalidate('正在自动寻找英雄联盟；无需选择窗口。')
        else:
            try:
                from session_windows import process_metadata
                self.manual_metadata=process_metadata(self.target.pid);self.manual_identity=self.target.identity
            except (OSError,ValueError) as exc:return self.status.setText('无法核验所选窗口的进程身份，未开始监测：'+str(exc))
            # Recognizing this explicitly selected client does not authorize
            # following it into another window. Class AND verified process
            # metadata identify the role; arbitrary manual diagnostics remain
            # manual even when their caption/class resembles a client.
            if (self.target.class_name in CLIENT_CLASSES
                    and PureWindowsPath(self.manual_metadata.path).name.casefold() in CLIENT_EXECUTABLES):
                try:
                    from session_windows import SessionWindowPolicy
                    from selection_session import SelectionSession
                    self.window_policy=SessionWindowPolicy(self.target);self.client_target=self.target;self.selection_session=SelectionSession();self.selection_session.start(self.target.identity)
                except (OSError,ValueError) as exc:return self.status.setText('无法核验客户端所属安装目录，本局监测未开始：'+str(exc))
            self.state.start(self.target.identity)
        if self.hero_auto.isChecked():self.state.clear_hero()
        self.debug_log.begin_game()
        self.debug_event('session',phase='started',reason='start')
        self.monitor.start(0);self.overlay.hide('start');self.stop_button.setEnabled(True);self.confirm_button.setEnabled(True)
        self.refresh_status_badge();self.status.setText('已开始监测。请切回游戏窗口；此窗口保留设置和停止入口。')
        self.queue_discovery(force=True)
        # Minimize only by explicit preference; old versions had no saved
        # preference, so migration defaults to keeping controls reachable.
        if self.minimize_on_start.isChecked() and not self.smoke_report and not self.selection_smoke_input:self.showMinimized()
    def stop_monitor(self):
        self._debug_game_window=None
        self.overlay.clear_candidate_geometry()
        self._geometry_frame=None
        self.hero_continuity.clear()
        self.clear_partial_candidates()
        self.lcu_snapshot.clear();self.last_selection_source=None;self._lcu_pixel_fallback=False;self._lcu_error=''
        self.selection_retry.reset();self._selection_capture_state='waiting'
        self.debug_event('cancel',reason='stop',cancelled=True)
        self._visible_previous=False
        self.retire_capture_session()
        self.last_candidates=None
        self._capture_serial+=1;self.capture_pending=False;self._accepted_frame=None;self._restore_while_ocr=False;self.overlay.set_rechecking(False)
        self._capture_cancel.set();self.ocr_reuse.clear();self.manual_metadata=None;self.manual_identity=None
        self.discovery_scope+=1;self.discovery_busy=False
        if self.automatic_policy:self.automatic_policy.stop()
        self.automatic_policy=None;self.unverified_candidate=None;self.trust_button.hide()
        if self.selection_session:self.selection_session.stop()
        if self.window_policy:self.window_policy.stop()
        self.selection_session=None;self.window_policy=None;self.client_target=None;self.hero_origin='hud'
        self.monitor.stop();self.state.stop();self.refresh_card_details()
        if self.hero_auto.isChecked():self.state.clear_hero()
        self.overlay.hide('stop');self.stop_button.setEnabled(False);self.confirm_button.setEnabled(False)
        self.apply_pending_portraits()
        self.status.setText(self.state.reason);self.refresh_status_badge()
    def advance_session_window(self):
        if self.automatic_policy:
            if self.selection_session:
                old=self.selection_session.generation;stage=self.selection_session.stage;self.selection_session.expire(time.monotonic())
                if old!=self.selection_session.generation:self.invalidate_scene('选人记录已过期，等待当前画面重新识别。')
                elif stage!=self.selection_session.stage and self.selection_session.stage=='client-expired':self.expire_client_display()
                elif stage!=self.selection_session.stage and self.selection_session.stage=='game-expired':self.expire_game_display()
            return
        if not self.selection_session or not self.window_policy:return
        now=time.monotonic();old=self.selection_session.generation;stage=self.selection_session.stage;self.selection_session.expire(now)
        if old!=self.selection_session.generation:self.invalidate_scene('本局选人记录因画面断档失效，等待重新识别')
        elif stage!=self.selection_session.stage and self.selection_session.stage=='client-expired':self.expire_client_display()
        elif stage!=self.selection_session.stage and self.selection_session.stage=='game-expired':self.expire_game_display()
        if not self.client_follow.isChecked():return
        if self.target.identity!=self.window_policy.client_identity or self.selection_session.stage!='assigned' or now-self.last_window_discovery<.5:return
        self.last_window_discovery=now;windows=self.capture.windows();candidate=self.window_policy.discover_game(windows)
        if not candidate or not self.capture.foreground(candidate[0]):return
        token=self.selection_session.generation
        if not self.window_policy.adopt_game(candidate,windows=self.capture.windows(),confirmed_handoff=True):return
        if not self.selection_session.begin_handoff(candidate[0].identity,now,generation=token,new_game_window=True):return
        self.note_verified_game_scope(candidate[0],candidate[1].created)
        self.target=candidate[0];self.state.target=self.target.identity;self.window_list.blockSignals(True);self.window_list.addItem('本局游戏：'+self.target.title,self.target);self.window_list.setCurrentIndex(self.window_list.count()-1);self.window_list.blockSignals(False);self.last_rect=None;self.was_target_foreground=False;self.invalidate_scene('已接续本局新游戏窗口，选人记录等待局内复核');self.overlay.hide('target_unavailable')
        self.apply_pending_portraits()
    def expire_client_display(self):
        self.clear_partial_candidates()
        self.debug_event('expiry',reason='ttl_client',ttl_ms=4000)
        # The older selection is no longer displayable. Do not cancel or change
        # the generation of a newer same-authority inference solely for age.
        # Permission/focus/geometry/Stop still follow the hard invalidation path.
        if self.hero_auto.isChecked():
            self.state.hero='';self.state.hero_observed='';self.state.hero_stable_frames=0
            self.hero_box.blockSignals(True);self.hero_box.setCurrentText('');self.hero_box.blockSignals(False)
        self.state.confirmed=False;self.state.offered=();self.state.confirmed_observation=()
        self.state.reason='选人资料超过 4 秒，已隐藏；等待当前画面复核。'
        self.overlay.hide('ttl_client');self.status.setText(self.state.reason);self.refresh_card_details()
    def check_target(self):
        if not self.state.running or not self.capture:return
        if self.debug_log.enabled:
            self.debug_log.sample('session',generation=self.state.generation,serial=self._capture_serial,
                ocr_busy=self.ocr_busy,**dict(getattr(self.capture,'session_lifecycle_diagnostic',{})))
        self.queue_discovery()
        if not self.target:return
        try:
            self.advance_session_window()
            if not self.target_allowed():raise CapturePaused('等待重新连接已核验的英雄联盟窗口。')
            now=time.monotonic()
            if self.ocr_busy and now-self.ocr_started>8 and not self.ocr_timed_out:
                self.debug_event('expiry',reason='ocr_timeout',ttl_ms=8000,age_ms=max(0.,(now-self.ocr_started)*1000))
                self.ocr_timed_out=True;self.invalidate_scene('OCR 超时，旧资料已隐藏；等待任务结束或停止并重启助手',debug_reason='ocr_timeout');self.overlay.hide('target_unavailable');self.status.setText(self.state.reason)
            if (self.state.confirmed or self._partial_displayed) and now-self.last_observation>4:
                self.expire_game_display()
            rect=self.capture.rect(self.target)
            if self.last_rect and rect!=self.last_rect:
                self.clear_partial_candidates()
                self.debug_event('cancel',reason='geometry_changed',cancelled=True)
                self._capture_cancel.set();self.retire_capture_session()
                self._accepted_frame=None;self._restore_while_ocr=False;self.overlay.set_rechecking(False)
                if (rect.width,rect.height)!=(self.last_rect.width,self.last_rect.height):self.invalidate_scene('目标客户区大小改变，等待新画面重新识别',debug_reason='geometry_changed')
                self.overlay.hide('geometry_changed') # Pure moves keep fresh identity/offers; only reposition.
            self.last_rect=rect
            if not self.capture.foreground(self.target):
                if self.status.text()!='等待切回游戏；恢复前台后自动继续。':
                    self.debug_event('capture',phase='discarded',reason='focus_rejected')
                if self.was_target_foreground:self.invalidate_scene('离开目标窗口，旧资料已隐藏；重新确认后再显示',debug_reason='focus_lost')
                else:self.clear_partial_candidates()
                self.was_target_foreground=False;self.overlay.hide('focus_lost');self.status.setText('等待切回游戏；恢复前台后自动继续。');return
            self.was_target_foreground=True
            if self.latest_capture.take_failure() is not None:
                self.invalidate_scene('新窗口帧校验失败，已隐藏旧资料并重新连接。',debug_reason='target_unavailable');return
            self.queue_latest_capture(now,rect)
            reference=self.client_selection_reference()
            partial=any(self.current_partial_names(now))
            if self._partial_displayed and not partial:
                self.clear_partial_candidates();self.overlay.hide('unconfirmed')
            if self._visible_previous and self.overlay.isVisible() and (reference or (self.state.confirmed or partial) and 0<=now-self.last_observation<=4):
                self.overlay.set_rechecking(True)
            elif reference and not self.capture_pending and not self.ocr_busy:
                self.overlay.set_hero_reference(reference);self.overlay.show_at(rect,self.target)
            elif self.state.confirmed and not self.capture_pending and (not self.ocr_busy or self._restore_while_ocr):self.overlay.show_at(rect,self.target)
            elif partial and not self.capture_pending and (not self.ocr_busy or self._restore_while_ocr):self.overlay.show_at(rect,self.target)
            elif self.overlay.reference:self.overlay.hide('unconfirmed')
        except CapturePaused as exc:
            if self.state.reason!=str(exc):
                self.debug_event('capture',phase='discarded',reason=getattr(exc,'reason_code','capture_paused'))
                self.invalidate_scene(str(exc),debug_reason='target_unavailable')
            self.overlay.hide('target_unavailable');self.status.setText(str(exc))
        except Exception as exc:
            self.invalidate_scene('目标窗口状态异常：'+str(exc));self.overlay.hide('target_unavailable');self.status.setText(self.state.reason)
    def expire_game_display(self):
        # Attribute the withdrawal to expiry before clearing geometry, whose
        # defensive hide would otherwise obscure the actual cause in the log.
        self.debug_event('expiry',reason='ttl_game',ttl_ms=4000,age_ms=max(0.,(time.monotonic()-self.last_observation)*1000))
        self.overlay.hide('ttl_game')
        self.overlay.clear_candidate_geometry()
        self._geometry_frame=None
        # Hide partial display too, but retain private per-slot continuity for
        # a still-fresh independent capture already in flight. observe() checks
        # its capture-time gap; reused OCR cannot reauthorize expired display.
        self._partial_displayed=False
        self._accepted_partial_frame=None;self._semantic_partial_frame=None
        # Presentation age is not an authority change. A newer capture may
        # still be within its own freshness budget while inference is running.
        # Keep only private observation continuity; never cancel that worker or
        # advance its generation merely because the previous display expired.
        self._visible_previous=False
        self.state.confirmed=False;self.state.offered=();self.state.confirmed_observation=()
        if self.hero_auto.isChecked():
            self.state.hero=''
            self.hero_box.blockSignals(True);self.hero_box.setCurrentText('');self.hero_box.blockSignals(False)
        self._accepted_frame=None;self._restore_while_ocr=False;self.ocr_reuse.clear()
        self.overlay.set_rechecking(False);self.overlay.hide('ttl_game')
        self.state.reason='画面观察超过 4 秒，旧资料已隐藏；等待当前画面复核。'
        self.status.setText(self.state.reason);self.refresh_card_details()
    def schedule_capture(self,delay=None):
        # Schedule from completion, not a fixed grid that can hide a just-shown
        # result on the next timer tick. One acquisition/inference job at a time.
        if self.closed or not self.state.running or self.ocr_busy or self.capture_pending:return
        if delay is None:
            delay=700 if self.state.confirmed or self.client_selection_reference() else 200
            previous=self.selection_session.last_client_frame if self.client_phase() and self.selection_session else self.last_observation
            age=time.monotonic()-previous if previous else None
            from capture_cadence import next_capture_delay
            delay=next_capture_delay(delay,age,self.last_timings)
        self.monitor.start(delay)
    def queue_latest_capture(self,now,rect):
        """Acquire at most one latest frame while OCR is busy; never recognize it here."""
        if (not self.ocr_busy or self.capture_pending or self.client_phase()
                or getattr(self.overlay,'_capture_retirement_pending',False)
                or not self.enable_visible_capture or not self.overlay.click_through
                or not getattr(self.capture,'has_live_visible_session',False)
                or now-self._prefetch_last_attempt<.75 or self.latest_capture.busy):return
        current=self._current_capture_proof
        if not current or current[:2]!=(self.state.generation,self._capture_serial):return
        frame_scope=current[2].get('_frameScope')
        if (not frame_scope or frame_scope[0]!=self.target.identity or frame_scope[2]!=rect
                or frame_scope[1]!=self.capture_metadata()):return
        generation=self.state.generation;serial=self._capture_serial
        capture=self.capture;target=self.target;metadata=frame_scope[1]
        epoch=getattr(capture,'session_epoch',None)
        scope=(generation,self.discovery_scope,frame_scope,epoch)
        cancelled=self._capture_cancel;closing=self._cancel_workers;logger=self.debug_log.scoped()
        def acquire(revoked):
            is_cancelled=lambda:revoked() or cancelled.is_set() or closing.is_set()
            if is_cancelled() or not capture.has_live_visible_session:raise CapturePaused('截图已取消。')
            started=time.monotonic()
            logger.record('capture',phase='started',reason='prefetch_started',generation=generation,serial=serial)
            try:
                image,current_rect=capture.capture(target,(0.,0.,1.,1.),cancelled=is_cancelled,
                    expected_metadata=metadata,allow_visible_overlay=True)
                acquired=time.monotonic()
                if is_cancelled() or current_rect!=rect or capture.session_epoch!=epoch:
                    raise CapturePaused('新窗口帧范围已经变化。')
                logger.record('capture',phase='acquired',reason='prefetch_acquired',generation=generation,serial=serial,
                    capture_ms=(acquired-started)*1000,**dict(capture.last_capture_diagnostic))
                return CapturedFrame(image,current_rect,started,acquired)
            except Exception:
                logger.record('capture',phase='error',reason='prefetch_failed',generation=generation,serial=serial)
                raise
        if self.latest_capture.submit(scope,acquire):self._prefetch_last_attempt=now

    def capture_tick(self):
        if self.closed or self.ocr_busy or self.capture_pending or not self.state.running:self.debug_selection_gate();return
        if self.latest_capture.busy:self.schedule_capture(50);return
        self.activate_idle_first_portraits()
        if not self.target:self.debug_selection_gate();self.schedule_capture(400);return
        if not self.capture.foreground(self.target):self.debug_selection_gate(False);self.schedule_capture(400);return
        self.debug_selection_gate(True)
        if self.client_phase() and self.lcu_toggle.isChecked() and self.hero_auto.isChecked() and self.selection_retry.ready(time.monotonic()):
            self.capture_selection();return
        mode=getattr(self.capture,'visible_capture_status','unknown')
        self.debug_log.sample('capture',generation=self.state.generation,capture_mode=mode)
        was_visible=self.overlay.isVisible() or bool(self.capture and hasattr(self.capture,'u') and self.capture.u.IsWindowVisible(int(self.overlay.winId())))
        fresh_previous=bool(self.client_selection_reference() or (self.state.confirmed or any(self.current_partial_names())) and 0<=time.monotonic()-self.last_observation<=4)
        # Automatic partial displays carry their own scoped frame authority.
        # Manual/unscoped cards still use the conservative strict-hidden route.
        historical_authority=bool(self.client_selection_reference() or self._accepted_frame or self._accepted_partial_frame)
        previous=bool(self.enable_visible_capture and was_visible and fresh_previous and historical_authority and self.overlay.click_through)
        # Cleanup temporarily revokes readiness while preserving the requested
        # transition. Switching back to hidden here would cancel that transition
        # on every poll and repeatedly retire otherwise healthy sessions.
        waiting_visible=bool(self._mode_wait_started is not None and self._visible_previous and mode=='cleanup_pending')
        # An enrolled capture capability is independent of whether an old
        # recommendation is still allowed to be displayed. A hidden owned
        # overlay does not require tearing down a healthy visible-capable session.
        continuing=bool(self.enable_visible_capture and self.overlay.click_through
            and getattr(self.capture,'has_live_visible_session',False))
        visible=bool((previous or continuing) and (getattr(self.capture,'can_request_visible_overlay',False) or waiting_visible))
        try:
            # Only this v2 preparation owns a GUI-safe drain barrier. Pending
            # legacy v1 process/pipe cleanup must be drained by the subsequent
            # strict-hidden capture worker, never polled indefinitely on Qt.
            prepare=getattr(self.capture,'prepare_capture_mode',None)
            pending=bool(prepare and not prepare(visible))
            if pending:
                now=time.monotonic()
                if self._mode_wait_started is None:self._mode_wait_started=now
                if now-self._mode_wait_started>8:
                    self.stop_monitor();self.status.setText('上一次截图尚未确认关闭；监测已停止，请检查后重新开始。');return
                self.debug_event('capture',phase='requested',reason='mode_wait',visible_capture=visible)
                self._visible_previous=visible;self.overlay.set_rechecking(previous)
                self.refresh_status_badge();self.schedule_capture(50);return
            self._mode_wait_started=None
        except (CapturePaused,CaptureUnavailable) as exc:
            self.invalidate_scene(str(exc),debug_reason='target_unavailable');self.schedule_capture(1000);return
        self.monitor.stop();self.capture_pending=True;self._restore_while_ocr=False;self._visible_previous=visible;self.overlay.set_rechecking(visible)
        self._capture_serial+=1;serial=self._capture_serial
        route_reason=('capture_wait' if visible else 'disabled' if not self.enable_visible_capture else 'interactive' if not self.overlay.click_through else 'prior_frame_unproven' if was_visible and fresh_previous and not historical_authority else mode if mode!='eligible' else 'no_previous' if not was_visible else 'stale_previous')
        self.debug_event('capture',phase='requested',reason=route_reason,capture_mode=mode,visible_capture=visible,visible=was_visible,fresh=fresh_previous,click_through=self.overlay.click_through)
        if not visible:
            self.overlay.hide('capture_pending')
            if was_visible:self.overlay._last_hidden_at=time.monotonic()
        self.refresh_status_badge();generation=self.state.generation
        settle_ms=self.overlay.hidden_settle_ms() if not visible else 0
        self.debug_event('capture',phase='queued',reason='capture_wait',visible_capture=visible,settle_ms=settle_ms)
        # Legacy/unsupported paths remain strict-hide. The explicit experiment
        # uses only the exact registered opaque v2 window, never v1/GDI.
        QtCore.QTimer.singleShot(settle_ms,lambda:self.capture_hidden(generation,serial,allow_visible_overlay=visible))
    def capture_selection(self):
        """Read opted-in client state without making pixels a prerequisite.

        The GUI still proves the same foreground client/geometry before and
        after the worker. API failure schedules a separate strict pixel request;
        a worker can never hide widgets or silently switch capture backends.
        """
        try:
            if not self.target_allowed():raise CapturePaused('客户端连接正在更新，稍后自动继续。')
            target=self.target;rect=self.capture.rect(target);metadata=self.capture_metadata()
            generation=self.state.generation;session_generation=self.selection_session.generation if self.selection_session else None
            self.monitor.stop();self._capture_serial+=1;serial=self._capture_serial
            self._capture_cancel=threading.Event();cancelled=self._capture_cancel
            self.ocr_busy=True;self.capture_pending=False;self._active_capture_generation=generation
            self.ocr_started=time.monotonic();self.ocr_timed_out=False;self._restore_while_ocr=False
            self._visible_previous=bool(self.overlay.isVisible() and self.client_selection_reference())
            self.overlay.set_rechecking(self._visible_previous)
            self._selection_capture_state='interface'
            self.status.setText('正在读取本机客户端选人资料…');self.refresh_status_badge()
            def read_selection():
                from lcu_selection import LocalSelectionReader,LCUUnavailable,UNAVAILABLE_REASONS
                from session_windows import process_metadata
                captured_at=time.monotonic()
                try:result=LocalSelectionReader(metadata,resolver=process_metadata).read(cancelled=cancelled)
                except LCUUnavailable as exc:
                    code=str(exc) if str(exc) in UNAVAILABLE_REASONS else 'local_client_unavailable'
                    result={'_lcuUnavailable':code}
                result.update(_capturedAt=captured_at,_completedAt=time.monotonic(),
                    _sessionGeneration=session_generation,_windowIdentity=target.identity,
                    _captureRect=rect,_captureSerial=serial,
                    _timings={'capture_ms':0.,'inference_ms':round((time.monotonic()-captured_at)*1000,1),'backend':'lcu-read-only'})
                return result
            self.spawn('selection',read_selection,generation)
        except (CapturePaused,CaptureUnavailable) as exc:
            self.ocr_busy=False;self.capture_pending=False
            self.invalidate_scene(str(exc),debug_reason='target_unavailable');self.schedule_capture(1000)
    def capture_hidden(self,generation,serial=None,*,allow_visible_overlay=False):
        if serial is not None and serial!=self._capture_serial:
            self.debug_event('cancel',reason='serial_changed',cancelled=True);return
        if self.closed or not self.state.running or generation!=self.state.generation:
            self.debug_event('cancel',reason='generation_changed',cancelled=True)
            self.capture_pending=False;self.schedule_capture();return
        if self.latest_capture.busy:
            QtCore.QTimer.singleShot(50,lambda:self.capture_hidden(generation,serial,allow_visible_overlay=allow_visible_overlay));return
        if serial is None:self._capture_serial+=1;serial=self._capture_serial
        self.monitor.stop();self.capture_pending=True;self._restore_while_ocr=False
        try:
            if not self.target_allowed():raise CapturePaused('窗口连接正在更新，稍后自动继续。')
            if allow_visible_overlay and (not self.enable_visible_capture or not self._visible_previous or not getattr(self.capture,'can_request_visible_overlay',False)):
                raise CaptureUnavailable('可见叠加采集资格已变化，已跳过本帧。')
            if not allow_visible_overlay and (self.overlay.isVisible() or (self.capture and hasattr(self.capture,'u') and self.capture.u.IsWindowVisible(int(self.overlay.winId())))):raise CaptureUnavailable('自己的叠加尚未隐藏，已跳过本帧以避免识别反馈。')
            roi=tuple(spin.value()/100 for spin in self.roi)
            self.ocr_busy=True;self._active_capture_generation=generation;self.ocr_started=time.monotonic();self.ocr_timed_out=False;self.status.setText('正在本机处理所选窗口截图，图片不保存、不上传…')
            from local_ocr import LocalOCR
            if not hasattr(self,'ocr'):self.ocr=LocalOCR()
            matcher=self.hero_matcher if self.hero_auto.isChecked() else None
            session_generation=self.selection_session.generation if self.selection_session else None
            frame_window=self.target;client_phase=self.client_phase()
            if client_phase:
                self._selection_capture_state='capturing';self.refresh_status_badge()
            if client_phase and self.selection_detector is None:
                from champion_select import ChampionSelectDetector
                aliases={}
                for name,row in self.data['heroes'].items():
                    key=str(row.get('championId',''))
                    if key.isdecimal():aliases[key]=[name,*row.get('alias',[])]
                try:
                    manifest=json.loads((self.state_dir/'hero-portraits/manifest.json').read_text(encoding='utf8'));version=manifest['version']
                    if not __import__('re').fullmatch(r'\d{1,3}\.\d{1,3}\.\d{1,3}',version):raise ValueError('Invalid cached version')
                    roster_bytes=(self.state_dir/'hero-portraits'/f'roster-{version}.json').read_bytes()
                    if __import__('hashlib').sha256(roster_bytes).hexdigest()!=manifest.get('rosterSha256'):raise ValueError('Cached roster hash changed')
                    roster=json.loads(roster_bytes)
                    for row in roster.get('data',{}).values():aliases.setdefault(str(row.get('key')),[]).extend([row.get('name',''),row.get('title','')])
                except (OSError,ValueError,KeyError,TypeError):pass
                self.selection_detector=ChampionSelectDetector(aliases,self.ocr)
            # Primary capture and inference use one serialized worker; the
            # bounded producer is drained above. Native waits never block Qt.
            # Snapshot all Qt-derived choices here; no worker reads widgets.
            capture=self.capture;vocabulary=tuple(self.data['augments']);expected_metadata=self.capture_metadata()
            self._capture_cancel=threading.Event();cancelled=self._capture_cancel
            detector=self.selection_detector
            lcu_enabled=bool(client_phase and self.lcu_toggle.isChecked())
            lcu_error=self._lcu_error
            verified_game=bool((self.automatic_policy and self.automatic_policy.bound and self.automatic_policy.bound.role=='game') or (self.window_policy and frame_window.identity==self.window_policy.game_identity))
            live_identity_enabled=bool(verified_game and not client_phase and self.live_identity_toggle.isChecked() and self.hero_auto.isChecked())
            map_outcomes=[]
            try:canonical_map=self.canonical_champion_map(diagnostic_callback=map_outcomes.append) if live_identity_enabled else {}
            except Exception:
                # This is still on the GUI thread, before worker creation. Keep
                # the map cause without claiming later identity stages ran or
                # changing the existing propagated-error behavior.
                if map_outcomes:self.debug_log.record('identity',generation=generation,serial=serial,map_outcome=map_outcomes[-1])
                raise
            map_outcome=map_outcomes[-1] if map_outcomes else 'not_requested'
            from live_client_identity import source_hero_names
            source_heroes=source_hero_names(self.data)

            reuse_allowed=self.state.confirmed and self.state.confirmation_mode=='automatic' and self.hero_origin!='game-continuity'
            scoped_ocr=self.ocr_reuse.scoped(self.ocr,(frame_window.identity,roi,'game'),allow_reuse=reuse_allowed)
            source_key=(id(self.data),json.dumps(self.data.get('metadata',{}),sort_keys=True,ensure_ascii=False))
            matcher_key=(matcher,matcher.proof_identity() if matcher and hasattr(matcher,'proof_identity') else None)
            logger=self.debug_log.scoped();debug_dpi=float(self.overlay.devicePixelRatioF())*96
            debug_identity=logger.identity(frame_window.hwnd,frame_window.pid,getattr(expected_metadata,'created',None)) if logger.enabled else {}
            previous_geometry=self._geometry_frame
            accepted_title_proof=(self._accepted_frame or {}).get('title_proof')
            accepted_card_geometry=(self._accepted_frame or self._accepted_partial_frame or {}).get('card_geometry')
            frame_scope=(frame_window.identity,expected_metadata,self.last_rect,roi,vocabulary,source_key,matcher_key)
            prefetch_scope=(generation,self.discovery_scope,frame_scope,getattr(capture,'session_epoch',None))
            prefetched=self.latest_capture.take(prefetch_scope) if allow_visible_overlay else None
            if not allow_visible_overlay:self.latest_capture.clear()
            def infer():
                from hero_recognition import recognize_frame
                if self._cancel_workers.is_set() or cancelled.is_set():
                    logger.record('cancel',reason='capture_cancelled',generation=generation,serial=serial,cancelled=True)
                    raise CapturePaused('监测已结束。')
                # Initialize models before assigning a live frame timestamp or
                # opening WGC, so cold verification cannot consume that frame's
                # freshness budget or the capture session's idle lease.
                prepare_ocr=getattr(self.ocr,'prepare',None)
                if callable(prepare_ocr):
                    prepare_started=time.monotonic()
                    logger.record('inference',inference_stage='ocr_prepare',phase='started',generation=generation,serial=serial)
                    prepare_ocr()
                    logger.record('inference',inference_stage='ocr_prepare',phase='completed',generation=generation,serial=serial,
                        inference_ms=(time.monotonic()-prepare_started)*1000)
                    if self._cancel_workers.is_set() or cancelled.is_set():raise CapturePaused('监测已结束。')
                options={'allow_visible_overlay':True} if allow_visible_overlay else {}
                logger.record('capture',phase='started',generation=generation,serial=serial,visible_capture=allow_visible_overlay)
                captured_at=prefetched.captured_at if prefetched is not None else time.monotonic()
                try:
                    if prefetched is not None:
                        # Buffered pixels remain tied to their original capture time;
                        # revalidate live guards without manufacturing a new observation.
                        if not 0<=time.monotonic()-captured_at<=.8:raise CapturePaused('预取画面已过期。')
                        if not capture.has_live_visible_session or capture.session_epoch!=prefetch_scope[-1]:
                            raise CapturePaused('预取画面的会话已经变化。')
                        from session_windows import process_metadata
                        if process_metadata(frame_window.pid)!=expected_metadata:raise CapturePaused('预取画面的进程已经变化。')
                        capture.validate_compositor(frame_window,prefetched.rect,allow_visible_overlay=True)
                        if not 0<=time.monotonic()-captured_at<=.8:raise CapturePaused('预取画面在校验期间已过期。')
                        image,rect=prefetched.image,prefetched.rect
                    else:image,rect=capture.capture(frame_window,(0.,0.,1.,1.),cancelled=cancelled,expected_metadata=expected_metadata,**options)
                except Exception:
                    logger.record('capture',phase='error',generation=generation,serial=serial,capture_ms=(time.monotonic()-captured_at)*1000,**dict(getattr(capture,'last_capture_diagnostic',{})))
                    raise
                pixels_at=time.monotonic()
                capture_ms=(prefetched.acquired_at-prefetched.captured_at)*1000 if prefetched is not None else (pixels_at-captured_at)*1000
                logger.record('capture',phase='acquired',generation=generation,serial=serial,capture_ms=capture_ms,prefetched=prefetched is not None,
                    backend=getattr(capture,'last_backend','unknown'),width=rect.width,height=rect.height,dpi=debug_dpi,visible_capture=allow_visible_overlay,**debug_identity,**dict(getattr(capture,'last_capture_diagnostic',{})))
                if self._cancel_workers.is_set() or cancelled.is_set():
                    logger.record('cancel',reason='capture_cancelled',generation=generation,serial=serial,cancelled=True)
                    raise CapturePaused('监测已结束。')
                proof={'_identityMapping':tuple(sorted(source_heroes.items())),'_capturedAt':captured_at,'_sessionGeneration':session_generation,'_windowIdentity':frame_window.identity,'_captureRect':rect,'_captureSerial':serial,
                    '_frameScope':(frame_window.identity,expected_metadata,rect,roi,vocabulary,source_key,matcher_key)}
                if client_phase:
                    # A separate receipt distinguishes pixel acquisition from
                    # later OCR failure without storing or exposing the frame.
                    with self._worker_lock:
                        if not self.closed and not self._cancel_workers.is_set():self.signals.result.emit('selection-capture',dict(proof),generation)
                title_snapshot=[]
                def emit_phase():
                    with self._worker_lock:
                        if not self.closed and not self._cancel_workers.is_set():self.signals.result.emit('capture-proof',dict(proof),generation)
                phase_times={};current_crop=[];decoded_frame=[]
                def title_proof_for_crop(crop):
                    if current_crop and current_crop[0] is crop:return
                    current_crop[:]=[crop]
                    proof['_matchingTitleProof']=accepted_title_proof if accepted_title_proof is not None and accepted_title_proof.matches(crop) else None
                    proof['_matchingCardGeometry']=accepted_card_geometry if accepted_card_geometry is not None and accepted_card_geometry.matches(image,_decoded_rgb=decoded_frame[0] if decoded_frame else None) else None
                def before_match(signature,crop):
                    phase_times['prepared']=time.monotonic()
                    if self._cancel_workers.is_set() or cancelled.is_set():raise CapturePaused('监测已结束。')
                    title_proof_for_crop(crop)
                    proof['_roiDigest']=hashlib.sha256(crop).hexdigest();proof['_hudInputDigest']=signature
                    # Immutable phase snapshot owned by the title worker. It
                    # never reads a dict the HUD thread is still updating.
                    title_snapshot[:]=[dict(proof)]
                    emit_phase()
                def after_titles(result):
                    if self._cancel_workers.is_set() or cancelled.is_set():return
                    value={**title_snapshot[0],
                        'automatic_candidates':result.get('automatic_candidates'),
                        'partial_title_evidence':result.get('partial_title_evidence'),
                        'image_size':result.get('image_size'),
                        '_cardGeometry':result.get('_cardGeometry'),
                        'ocr_reused':result.get('ocr_reused') is True}
                    with self._worker_lock:
                        if not self.closed and not self._cancel_workers.is_set():self.signals.result.emit('title-proof',value,generation)
                def before_ocr(hero,crop):
                    phase_times['hud_done']=time.monotonic()
                    if self._cancel_workers.is_set() or cancelled.is_set():raise CapturePaused('监测已结束。')
                    if not live_identity_enabled:
                        emit_identity(hero,'disabled','hud_verified' if isinstance(hero,dict) and hero.get('confident') is True else 'hud_abstained')
                    title_proof_for_crop(crop)
                    proof['_roiDigest']=hashlib.sha256(crop).hexdigest();proof['hero_observation']=hero
                    # Pixel acquisition and its final guards are complete.
                    # Persistent capture additionally verified the exact guarded-
                    # idle trailer; its helper may remain alive without readback.
                    # Only the GUI thread may authorize re-display.
                    emit_phase()
                class TimedOCR:
                    def recognize_fresh(inner,*args):
                        started=time.monotonic()
                        try:
                            fresh=self.ocr.recognize(*args);fresh['ocr_reused']=False;return fresh
                        finally:phase_times['ocr_ms']=phase_times.get('ocr_ms',0)+(time.monotonic()-started)*1000
                    def recognize(inner,*args):
                        started=time.monotonic()
                        try:return scoped_ocr.recognize(*args)
                        finally:phase_times['ocr_ms']=(time.monotonic()-started)*1000
                def emit_identity(hud,api_outcome,identity_outcome):
                    from hero_recognition import hud_identity_outcome
                    logger.record('identity',generation=generation,serial=serial,
                        api_outcome=api_outcome,map_outcome=map_outcome,
                        hud_outcome=hud_identity_outcome(hud),identity_outcome=identity_outcome)
                def resolve_hero(hud):
                    if not live_identity_enabled:return hud
                    from live_client_identity import read_current_identity,reconcile_identity
                    from session_windows import process_metadata
                    def scope_probe():
                        if cancelled.is_set() or self._cancel_workers.is_set():return None
                        try:current=process_metadata(frame_window.pid)
                        except (OSError,ValueError):return None
                        return (frame_window.identity,generation,current) if current==expected_metadata else None
                    api_outcomes=[];identity_outcomes=[]
                    api=read_current_identity(canonical_map,enabled=True,cancelled=cancelled,scope_probe=scope_probe,diagnostic_callback=api_outcomes.append)
                    if not api:
                        proof['_liveIdentityUnavailable']=True
                    resolved=reconcile_identity(hud,api,source_heroes,diagnostic_callback=identity_outcomes.append)
                    # Retain the cause even if this frame's later OCR fails.
                    emit_identity(hud,api_outcomes[-1] if api_outcomes else 'unexpected_error',identity_outcomes[-1])
                    return resolved
                def trace_inference(stage,phase,elapsed):
                    cold={'ocr_cold_start':getattr(self.ocr,'_engine',None) is None} if stage=='ocr' and phase=='started' else {}
                    duration={'inference_ms':elapsed} if phase=='completed' else {}
                    logger.record('inference',inference_stage=stage,phase=phase,generation=generation,serial=serial,**duration,**cold)
                if client_phase:logger.record('inference',inference_stage='selection',phase='started',generation=generation,serial=serial)
                result=detector.recognize(image) if client_phase else recognize_frame(image,roi,TimedOCR(),vocabulary,matcher,before_match=before_match,before_ocr=before_ocr,after_titles=after_titles,inference_worker=self.frame_inference_worker,diagnostic_callback=trace_inference,prepared_frame=lambda rgb:decoded_frame.append(rgb),prior_card_geometry=(previous_geometry[1] if previous_geometry and previous_geometry[0]==proof['_frameScope'] else None),**({'resolve_hero':resolve_hero} if live_identity_enabled else {}))
                if client_phase:logger.record('inference',inference_stage='selection',phase='completed',inference_ms=(time.monotonic()-pixels_at)*1000,generation=generation,serial=serial)
                if lcu_enabled:result.update(lcuFallback=True,lcuError=lcu_error)
                if current_crop and not client_phase:
                    from card_title_proof import make_title_proof
                    result['_titleProof']=make_title_proof(current_crop[-1],result.get('automatic_candidates'),result.get('image_size'))
                result.update(proof);result['_timings']={'capture_ms':round(capture_ms,1),'inference_ms':round((time.monotonic()-pixels_at)*1000,1)}
                result['_completedAt']=time.monotonic()
                if not client_phase:
                    result['_timings'].update(prepare_ms=round((phase_times.get('prepared',pixels_at)-pixels_at)*1000,1),
                        hud_ms=round((phase_times.get('hud_done',pixels_at)-phase_times.get('prepared',pixels_at))*1000,1),
                        ocr_ms=round(phase_times.get('ocr_ms',0.),1))
                logger.record('capture',phase='completed',generation=generation,serial=serial,ocr_reused=result.get('ocr_reused') is True,**result['_timings'])
                return result
            self.spawn('selection' if client_phase else 'ocr',infer,generation)
        except CapturePaused as exc:
            self.debug_event('capture',phase='discarded',reason=getattr(exc,'reason_code','capture_paused'))
            self.ocr_busy=False;self.capture_pending=False
            if self.state.reason!=str(exc):self.invalidate_scene(str(exc),debug_reason='target_unavailable')
            self.status.setText(str(exc));self.overlay.hide('target_unavailable');self.schedule_capture(1000)
        except Exception as exc:
            client_failure=self.client_phase()
            self.ocr_busy=False;self.capture_pending=False;self.invalidate_scene('截图或识别初始化失败：'+str(exc),debug_reason='worker_error')
            if client_failure:self._selection_capture_state='capture_failed'
            self.status.setText(self.state.reason);self.overlay.hide('target_unavailable');self.schedule_capture(1000)
    def remember_accepted_partial_frame(self,value):
        """Snapshot final, independently confirmed fixed-slot display authority."""
        names=self.current_partial_names();hero=value.get('hero_observation',{})
        geometry=value.get('_cardGeometry');anchors=self.overlay._badge_anchors
        if (self._partial_displayed and not self.state.confirmed and any(names)
                and self.hero_auto.isChecked() and hero.get('confident') is True and hero.get('hero')==self.state.hero
                and value.get('ocr_reused') is False and geometry is not None and anchors is not None
                and all(not name or anchors.names[i]==name for i,name in enumerate(names))
                and self.partial_scope_current(value.get('_frameScope'))
                and value.get('_captureSerial')==self._capture_serial):
            self._accepted_partial_frame={'source_ref':self.data,'generation':self.state.generation,
                'hero':self.state.hero,'names':names,'scope':value['_frameScope'],
                'observed_at':value['_capturedAt'],'serial':value['_captureSerial'],
                'hud_digest':value.get('_hudInputDigest'),'card_geometry':geometry,'anchors':anchors}
        else:self._accepted_partial_frame=None
        self._semantic_partial_frame=None
    def accepted_partial_scope_current(self,value):
        reference=self._accepted_partial_frame;now=time.monotonic()
        return bool(reference and reference['source_ref'] is self.data and self.hero_auto.isChecked()
            and reference['generation']==self.state.generation and reference['hero']==self.state.hero
            and reference['names']==self.current_partial_names(now) and any(reference['names'])
            and value.get('_frameScope')==reference['scope'] and self.partial_scope_current(reference['scope'])
            and value.get('_matchingCardGeometry') is reference['card_geometry']
            and value.get('_captureSerial')==self._capture_serial and reference['serial']<self._capture_serial
            and 0<=now-reference['observed_at']<=4 and reference['observed_at']<value.get('_capturedAt',0)<=now)
    def may_restore_accepted_partial_frame(self,value):
        reference=self._accepted_partial_frame;semantic=self._semantic_partial_frame
        hero=value.get('hero_observation',{})
        return bool(self.accepted_partial_scope_current(value) and semantic and semantic[0] is reference
            and semantic[1:]==(self.state.generation,value.get('_captureSerial'),value.get('_frameScope'),value.get('_capturedAt'))
            and ((hero.get('confident') is True and hero.get('hero')==reference['hero']) if 'hero_observation' in value
                 else bool(reference['hud_digest'] and value.get('_hudInputDigest')==reference['hud_digest'])))
    def recheck_partial_titles(self,value,generation):
        """Apply only negative per-slot evidence; the final result observes once."""
        if not self.accepted_partial_scope_current(value):
            self.revoke_title_display('geometry_unproven');return
        from partial_candidates import TitleEvidence
        from card_badges import accepted_anchors
        evidence=value.get('partial_title_evidence');reference=self._accepted_partial_frame
        if value.get('ocr_reused') is not False or not isinstance(evidence,TitleEvidence) or not evidence.valid:
            self.revoke_title_display('title_changed');return
        # All three explicit rows, including the unknown one, must belong to
        # the same freshly proven cards. A dictionary subset cannot prove this.
        candidates=[{'name':slot.name,'box':slot.box} for slot in evidence.slots]
        anchors=accepted_anchors(candidates,value.get('image_size'),value['_frameScope'][3],value.get('_cardGeometry'))
        if (anchors is None or anchors.rects!=reference['anchors'].rects
                or anchors.names!=tuple(slot.name for slot in evidence.slots)):
            self.revoke_title_display('geometry_unproven');return
        before=reference['names'];names=self.partial_candidates.recheck(evidence,now=time.monotonic())
        if not any(names):
            self.revoke_title_display('title_changed');return
        if names!=before:
            # Preserve the original observation timestamp and accepted serial.
            # A later positive callback can never restore an erased slot/count.
            reference={**reference,'names':names};self._accepted_partial_frame=reference
            historical_visible=bool(self._visible_previous and self.overlay.isVisible())
            self.ocr_reuse.clear();self.show_partial_candidates(rechecking=True)
            self._restore_while_ocr=historical_visible
            self.debug_event('recognition',reason='title_changed',candidate_count=sum(bool(name) for name in names))
            self.refresh_card_details()
        self._semantic_partial_frame=(reference,generation,value['_captureSerial'],value['_frameScope'],value['_capturedAt'])
        current=self._current_capture_proof
        proof=current[2] if current and current[:2]==(generation,value['_captureSerial']) else value
        if self.may_restore_accepted_partial_frame(proof):
            self._restore_while_ocr=True;self.overlay.set_rechecking(True);self.check_target()
    def accepted_frame_scope_current(self,value):
        """Scope/freshness of a historical display; grants no new observation."""
        reference=self._accepted_frame;now=time.monotonic()
        scope=value.get('_frameScope');current_source=(id(self.data),json.dumps(self.data.get('metadata',{}),sort_keys=True,ensure_ascii=False)) if self.data else None
        return bool(reference and reference.get('source_ref') is self.data and self.state.confirmed and self.state.confirmation_mode=='automatic'
            and reference.get('card_geometry') is not None and value.get('_matchingCardGeometry') is reference['card_geometry']
            and reference['generation']==self.state.generation and reference['hero']==self.state.hero and reference['offered']==self.state.offered
            and isinstance(scope,tuple) and len(scope)==7 and scope==reference['scope'] and scope[3]==tuple(spin.value()/100 for spin in self.roi) and scope[4]==tuple(self.data['augments']) and scope[5]==current_source and scope[6][0] is self.hero_matcher and scope[6][1]==(self.hero_matcher.proof_identity() if self.hero_matcher and hasattr(self.hero_matcher,'proof_identity') else None)
            and value.get('_captureSerial')==self._capture_serial
            and 0<=now-reference['observed_at']<=4 and reference['observed_at']<value.get('_capturedAt',0)<=now)
    def may_restore_accepted_frame(self,value):
        reference=self._accepted_frame;hero=value.get('hero_observation',{})
        semantic=self._semantic_title_frame
        semantic_match=bool(semantic and reference is semantic[0]
            and (self.state.generation,value.get('_captureSerial'),value.get('_frameScope'),value.get('_capturedAt'))==semantic[1:])
        return bool(self.hero_auto.isChecked() and self.accepted_frame_scope_current(value)
            and (semantic_match or value.get('_roiDigest')==reference['digest'] or reference.get('title_proof') is not None and value.get('_matchingTitleProof') is reference['title_proof'])
            and ((hero.get('confident') is True and hero.get('hero')==reference['hero']) if 'hero_observation' in value else bool(reference['hud_digest'] and value.get('_hudInputDigest')==reference['hud_digest'])))
    def revoke_title_display(self,reason,*,preserve_partial=False):
        # Keep this capture's generation intact, but revoke title continuity.
        # The final joined result counts exactly once toward requalification.
        self.overlay.set_title_checking(True)
        self._accepted_frame=None;self._semantic_title_frame=None
        self._visible_previous=False;self._restore_while_ocr=False
        self.state.confirmed=False;self.state.offered=();self.state.confirmed_observation=()
        self.state.observed=();self.state.stable_frames=0
        self.state.automatic_observed=();self.state.automatic_frames=0
        # With unchanged freshly proven borders, private independent-slot
        # continuity can survive a different/weak middle title. Its own final
        # observer still resets that slot (or all slots for an absent row).
        if preserve_partial:self._partial_displayed=False
        else:self.clear_partial_candidates()
        self.ocr_reuse.clear()
        self.overlay.hide(reason);self.debug_event('recognition',reason=reason)
        self.refresh_card_details()
    def remember_accepted_frame(self,value):
        hero=value.get('hero_observation',{})
        if self.state.confirmed and self.state.confirmation_mode=='automatic' and self.hero_auto.isChecked() and ((hero.get('confident') is True and hero.get('hero')==self.state.hero) or self.hero_origin=='game-continuity' and bool(self.state.hero)) and value.get('_roiDigest') and value.get('_frameScope'):
            self._accepted_frame={'source_ref':self.data,'generation':self.state.generation,'hero':self.state.hero,'offered':self.state.offered,'scope':value['_frameScope'],'digest':value['_roiDigest'],'hud_digest':value.get('_hudInputDigest'),'observed_at':value['_capturedAt'],'title_proof':value.get('_titleProof'),'card_geometry':value.get('_cardGeometry')}
        else:self._accepted_frame=None
    def captured_frame_current(self,value):
        # Production workers always attach capture geometry. Validate on the Qt
        # thread again after inference, including advanced manual targets.
        rect=value.get('_captureRect')
        if rect is None:
            # Only explicit self-owned diagnostic launch modes inject synthetic
            # handler results. Ordinary monitoring requires capture provenance.
            if self.smoke_report or self.selection_smoke_input:return True
            self.invalidate_scene('截图来源信息缺失，已丢弃识别结果。');self.overlay.hide('target_unavailable');return False
        try:
            if not self.target or tuple(value.get('_windowIdentity',()))!=self.target.identity or not self.target_allowed() or not self.capture.foreground(self.target) or self.capture.rect(self.target)!=rect:
                raise CapturePaused('识别期间窗口身份、位置或大小变化，已丢弃旧画面。')
            self.last_rect=rect
            return True
        except (CapturePaused,CaptureUnavailable) as exc:
            self.invalidate_scene(str(exc),debug_reason='target_unavailable');self.overlay.hide('target_unavailable');self.status.setText(str(exc));return False
    def confirm(self, *, automatic=False, captured_at=None):
        try:
            if not automatic:self.clear_partial_candidates()
            self.state.confirm([edit.text() for edit in self.inputs],self.data['augments'],automatic=automatic);self.last_observation=captured_at if captured_at is not None else time.monotonic()
            self._partial_displayed=False
            self.manual_editing=False
            metadata=self.data.get('metadata',{})
            source_version=f"数据包 {metadata.get('wikiDataVersion') or '未知'} / 游戏资料 {metadata.get('gamePatch') or '未知'}"
            self.overlay.set_cards(self.state.hero,display_cards(self.data,self.state.hero,self.state.offered),metadata.get('sourceDataDate') or '未知',source_version,('来自本局选人 · HUD未复核' if self.hero_origin=='client-provisional' else '本局选人 + HUD复核' if self.hero_origin=='client-verified' else '本局此前确认英雄 + 本帧候选；头像未重新确认' if self.hero_origin=='game-continuity' else '本机接口英雄 + 候选连续确认' if self.hero_origin=='game-api' else '英雄/候选连续高置信自动识别' if self.hero_auto.isChecked() else '英雄人工纠正 · 候选自动识别') if automatic else '人工确认')
            self.last_candidates={'scope':self.history_scope(),'hero':self.state.hero,'cards':display_cards(self.data,self.state.hero,self.state.offered),'recorded_at':self.last_observation,'source_date':metadata.get('sourceDataDate') or '未知','source_version':source_version,'confirmation':'候选自动确认 · 按截图观察时间' if automatic else '候选人工确认 · 按确认时间'}
            self.refresh_card_details();self.status.setText(self.state.reason+'；切回目标窗口后显示。');self.check_target()
        except (ValueError,KeyError) as exc:self.status.setText(str(exc))
    def toggle_clickthrough(self):
        self._accepted_frame=None;self._restore_while_ocr=False;self.overlay.set_rechecking(False)
        try:self.overlay.set_click_through(not self.overlay.click_through)
        except CaptureUnavailable as exc:
            self.stop_monitor();self.overlay.hide('target_unavailable');self.status.setText(str(exc));return
        self.toggle_button.setChecked(self.overlay.click_through);self.record_debug_config();self.check_target()
    def discard_stale_capture_callback(self,kind,generation):
        if kind not in ('ocr','selection') or generation==self.state.generation:return False
        # An invalidated worker still owns its drain barrier. Release only that
        # exact lease; a callback from an older job must not touch a newer job.
        self.debug_log.record('job',kind=kind,phase='discarded',generation=generation,reason='generation_changed')
        if self._active_capture_generation==generation:
            self._active_capture_generation=None;self.ocr_busy=False;self.capture_pending=False
            self.schedule_capture()
        return True
    @QtCore.Slot(str,object,int)
    def task_result(self,kind,value,generation):
        if self.closed or self.discard_stale_capture_callback(kind,generation):return
        if kind in ('ocr','selection') and isinstance(value,dict) and '_captureSerial' in value and value['_captureSerial']!=self._capture_serial:
            self.debug_log.record('job',kind=kind,phase='discarded',generation=generation,reason='serial_changed');return
        if kind in ('ocr','selection') and isinstance(value,dict) and value.get('_captureSerial') is not None:
            if value['_captureSerial']==self._completed_capture_serial:return
            if self.state.running and generation==self.state.generation:self._completed_capture_serial=value['_captureSerial']
        if kind in ('ocr','selection') and isinstance(value,dict):
            completed=value.get('_completedAt')
            if isinstance(completed,(int,float)) and math.isfinite(completed):
                self.debug_log.record('job',kind=kind,phase='completed',generation=generation,serial=value.get('_captureSerial',0),dispatch_ms=max(0.,(time.monotonic()-completed)*1000))
        if kind in ('ocr','selection','capture-proof','title-proof') and (not self.state.running or generation!=self.state.generation):
            self.debug_log.record('job',kind=kind,phase='discarded',generation=generation,reason='generation_changed')
        try:
            if kind=='windows':
                self.apply_discovery(value,generation);return
            if kind=='load':
                if self.state.running:self.invalidate_scene('资料已改变，等待当前画面重新识别。')
                else:self.clear_partial_candidates()
                self.startup_error='';self.data=value['data'];meta=self.data.get('metadata',{});status=value.get('status',{})
                self.source.setText(('虚构演示，不能用于对局。 ' if meta.get('isDemo') else '')+f"软件 {self.current_version} · 来源日期 {meta.get('sourceDataDate','未知')} · 数据包 {meta.get('wikiDataVersion','未知')} · 游戏资料版本 {meta.get('gamePatch','未知')} · {status.get('message','资料已加载')} 获取成功不代表统计内容最新。")
                self.hero_aliases={}
                ambiguous=set()
                for name,record in self.data.get('heroes',{}).items():
                    for alias in record.get('alias',[]):
                        if alias in self.hero_aliases and self.hero_aliases[alias]!=name:ambiguous.add(alias)
                        self.hero_aliases[alias]=name
                for alias in ambiguous:self.hero_aliases.pop(alias,None)
                self.hero_box.addItem('');self.hero_box.addItems(sorted(self.data.get('heroes',{})))
                hero_completer=QtWidgets.QCompleter(sorted(set(self.data.get('heroes',{}))|set(self.hero_aliases)),self.hero_box);hero_completer.setCaseSensitivity(QtCore.Qt.CaseSensitivity.CaseInsensitive);hero_completer.setFilterMode(QtCore.Qt.MatchFlag.MatchContains);self.hero_box.setCompleter(hero_completer)
                self.debug_log.register_catalog(augment_names=self.data.get('augments',{}),hero_names=self.data.get('heroes',{}))
                vocabulary=sorted(self.data.get('augments',{}))
                for edit in self.inputs:
                    completer=QtWidgets.QCompleter(vocabulary,edit);completer.setCaseSensitivity(QtCore.Qt.CaseSensitivity.CaseInsensitive);edit.setCompleter(completer)
                self.start_button.setEnabled(bool(vocabulary and self.capture));self.status.setText('点击开始监测后自动识别本人英雄与三个候选；不确定时才人工纠正。' if self.capture else '当前系统不支持窗口采集；Windows 10/11 可用。')
                if not meta.get('isDemo'):
                    self.request_portraits()
                else:self.hero_status.setText('虚构演示没有真实头像；人工模式或合成识别测试可用。')
                QtCore.QTimer.singleShot(0,self.ready)
                if self.enable_updates and not self.smoke_report:self.spawn('update',lambda:__import__('updates').check_for_update(self.current_version))
                else:self.update_status.setText('本次启动已显式禁用软件更新检查。')
            elif kind=='title-proof':
                if (not self.state.running or generation!=self.state.generation
                        or value.get('_captureSerial')!=self._capture_serial or not self.ocr_busy
                        or self._active_capture_generation!=generation):return
                if not self.captured_frame_current(value):return
                # Fresh title OCR necessarily follows guarded pixel acquisition;
                # tolerate queued phase delivery in either order without leaving
                # a revoked-slot mask waiting for the slower HUD callback.
                self.capture_pending=False
                if self._accepted_partial_frame:
                    self.recheck_partial_titles(value,generation);return
                if not self._accepted_frame:return
                if not self.accepted_frame_scope_current(value):
                    self.revoke_title_display('geometry_unproven');return
                from card_title_proof import same_titles
                from card_badges import accepted_anchors
                reference=self._accepted_frame
                candidates=value.get('automatic_candidates');size=value.get('image_size')
                same=bool(value.get('ocr_reused') is not True and same_titles(reference['offered'],candidates,size))
                anchors=accepted_anchors(candidates,size,value['_frameScope'][3],value.get('_cardGeometry'))
                same_geometry=bool(anchors is not None and self.overlay._badge_anchors is not None and anchors.rects==self.overlay._badge_anchors.rects)
                if not same or anchors is None or anchors!=self.overlay._badge_anchors:
                    self.revoke_title_display('title_changed' if not same else 'geometry_unproven',preserve_partial=not same and same_geometry);return
                # A positive title phase is fresh evidence for this one capture,
                # not another state observation and not an extension of TTL.
                self._semantic_title_frame=(reference,generation,value['_captureSerial'],value['_frameScope'],value['_capturedAt'])
                current=self._current_capture_proof
                if current and current[:2]==(generation,value['_captureSerial']):value=current[2]
                if self.may_restore_accepted_frame(value):
                    self.overlay.set_title_checking(False)
                    self._restore_while_ocr=True;self.overlay.set_rechecking(True);self.check_target()
            elif kind=='capture-proof':
                if not self.state.running or generation!=self.state.generation or value.get('_captureSerial')!=self._capture_serial or not self.ocr_busy:return
                self.capture_pending=False;self._restore_while_ocr=False
                if not self.captured_frame_current(value):return
                self._current_capture_proof=(generation,value['_captureSerial'],dict(value))
                observation=value.get('hero_observation')
                unsafe_identity=isinstance(observation,dict) and (observation.get('abstentionKind')=='unsupported-layout' or observation.get('conflict') is True or (observation.get('method')=='game-client-api' and observation.get('confident') is not True))
                if self.hero_auto.isChecked() and isinstance(observation,dict):
                    private_conflict=bool(observation.get('confident') is True and self.hero_continuity.hero and (observation.get('hero'),observation.get('championId'))!=(self.hero_continuity.hero,self.hero_continuity.champion_id))
                    if self.hero_continuity.hero and self.game_identity_scope(value)!=self.hero_continuity.scope:private_conflict=True
                    unsafe_identity=unsafe_identity or private_conflict
                    if unsafe_identity:self.hero_continuity.clear()
                if self.hero_auto.isChecked() and self.state.hero and isinstance(observation,dict):
                    # A resolved identity contradiction is stronger than harmless
                    # animated pixels. Revoke before waiting for title OCR. A
                    # valid carried identity may still tolerate an unknown HUD.
                    explicit_conflict=unsafe_identity or (observation.get('confident') is True and observation.get('hero')!=self.state.hero) or (observation.get('method')=='game-client-api' and observation.get('confident') is not True)
                    continuity_ok=self.hero_continuity.eligible(observation,scope=self.game_identity_scope(value),captured_at=value.get('_capturedAt'),now=time.monotonic(),serial=value.get('_captureSerial'))
                    if explicit_conflict:self.hero_continuity.clear()
                    unknown_without_carry=observation.get('confident') is not True and self.hero_origin not in ('client-provisional','client-verified') and not continuity_ok
                    if explicit_conflict or unknown_without_carry:
                        if explicit_conflict and self.selection_session:self.selection_session.clear('Fresh hero proof contradicts previous identity')
                        # Revoke presentation without discarding this same
                        # fresh capture: the final result still must count as
                        # at most one observation of the new hero/title state.
                        self.clear_partial_candidates();self.ocr_reuse.clear()
                        self._accepted_frame=None;self._restore_while_ocr=False;self._visible_previous=False
                        self.state.confirmed=False;self.state.offered=();self.state.confirmed_observation=()
                        self.state.observed=();self.state.stable_frames=0;self.state.automatic_observed=();self.state.automatic_frames=0
                        self.state.hero='';self.hero_box.blockSignals(True);self.hero_box.setCurrentText('');self.hero_box.blockSignals(False)
                        self.state.reason=('当前英雄身份冲突，旧评级已隐藏。' if explicit_conflict else self.identity_wait_message(value,working=True))
                        self.overlay.set_rechecking(False);self.overlay.hide('hero_unknown');self.status.setText(self.state.reason)
                        self.debug_event('recognition',reason='hero_unknown',hero_present=False)
                        self.refresh_card_details()
                        return
                if self._visible_previous and self._accepted_frame:
                    reference=self._accepted_frame
                    if not self.accepted_frame_scope_current(value):
                        self.revoke_title_display('geometry_unproven');return
                    # Pixel mismatch is not semantic contradiction. Retain
                    # only the already accepted historical grade, under its
                    # original deadline, until fresh title OCR can decide.
                    # Never oscillate grade/checking merely for animated pixels.
                    if self.overlay._titles_pending and self.may_restore_accepted_frame(value):
                        self.overlay.set_title_checking(False);self._restore_while_ocr=True
                if self._visible_previous and self._accepted_partial_frame and not self.accepted_partial_scope_current(value):
                    self.revoke_title_display('geometry_unproven');return
                if self._visible_previous:
                    # The label describes the original accepted observation,
                    # never this still-unrecognized frame or a selected choice.
                    self.overlay.set_rechecking(True);self.check_target();return
                if not self.overlay.isVisible() and hasattr(self.capture,'validate_compositor'):
                    try:self.capture.validate_compositor(self.target,value['_captureRect'])
                    except (CapturePaused,CaptureUnavailable) as exc:
                        self.invalidate_scene(str(exc),debug_reason='target_unavailable');self.overlay.hide('target_unavailable');return
                self._restore_while_ocr=self.may_restore_accepted_frame(value) or self.may_restore_accepted_partial_frame(value)
                if self._restore_while_ocr:self.overlay.set_title_checking(False)
                self.overlay.set_rechecking(self._restore_while_ocr)
                if not self._restore_while_ocr:self.overlay.hide('capture_proof')
                self.check_target()
            elif kind=='selection-capture':
                if (not self.state.running or generation!=self.state.generation or not self.selection_session
                        or value.get('_captureSerial')!=self._capture_serial or not self.ocr_busy
                        or value.get('_sessionGeneration')!=self.selection_session.generation):return
                if self.captured_frame_current(value):self._selection_capture_state='captured'
            elif kind=='selection':
                if not self.state.running or generation!=self.state.generation or not self.selection_session:return
                self._visible_previous=False
                self.ocr_busy=False;self.capture_pending=False;self._restore_while_ocr=False;self.overlay.set_rechecking(False)
                if not self.state.running or generation!=self.state.generation or not self.selection_session:return
                session_generation=value.get('_sessionGeneration');captured_at=value.get('_capturedAt');now=time.monotonic()
                # Source changes are meaningful only for a current, independent
                # observation. A late callback must not clear a newer source.
                if (session_generation!=self.selection_session.generation
                        or not self.selection_session._fresh(captured_at,now)
                        or captured_at<=self.selection_session.last_event_frame):return
                if not self.captured_frame_current(value):return
                if not self.target_allowed() or tuple(value.get('_windowIdentity',()))!=self.target.identity:
                    self.selection_session.clear('Client permission changed during inference');self.invalidate_scene('客户端身份变化，旧选人资料已清空');return
                if value.get('_lcuUnavailable'):
                    from lcu_selection import unavailable_reason
                    self._lcu_pixel_fallback=True;self._lcu_error=value['_lcuUnavailable']
                    self.selection_retry.failed(time.monotonic());self._selection_capture_state='interface_failed'
                    self.lcu_snapshot.clear()
                    if self.last_selection_source and self.last_selection_source[0]=='lcu-read-only':
                        self.selection_session.clear('Local client unavailable; require fresh pixel evidence')
                        self.last_selection_source=None
                        if self.hero_auto.isChecked():
                            self.state.hero='';self.hero_box.blockSignals(True);self.hero_box.setCurrentText('');self.hero_box.blockSignals(False)
                        self.overlay.hide('selection_changed')
                    self.hero_status.setText(unavailable_reason(self._lcu_error)+'；正在尝试截图识别。')
                    self.status.setText(self.hero_status.text());return
                if value.get('method')=='lcu-read-only':
                    self._lcu_pixel_fallback=False;self._lcu_error='';self.selection_retry.reset();self._selection_capture_state='interface'
                self.clear_partial_candidates()
                self.hero_continuity.clear()
                now=time.monotonic()
                selection_source=(value.get('method'),value.get('_lcuInstance'))
                if self.last_selection_source is not None and selection_source!=self.last_selection_source:
                    self.selection_session.clear('Selection source/session changed')
                    session_generation=self.selection_session.generation
                self.last_selection_source=selection_source
                self.lcu_snapshot.observe(value,self.target.identity,value.get('_capturedAt',now-5),now)
                stable=self.selection_session.observe_client(value,self.target.identity,captured_at,now,generation=session_generation)
                if value.get('method')!='lcu-read-only':self._selection_capture_state='recognized' if stable else 'unrecognized'
                self.state.confirmed=False;self.state.offered=()
                hero=next((name for name,row in self.data['heroes'].items() if self.selection_session.assigned and str(row.get('championId'))==self.selection_session.assigned),'')
                if self.hero_auto.isChecked():
                    self.state.hero=hero;self.hero_box.blockSignals(True);self.hero_box.setCurrentText(hero);self.hero_box.blockSignals(False)
                reference=self.client_selection_reference()
                if not stable or not reference or self.overlay.reference!=reference:self.overlay.hide('selection_changed')
                self.refresh_card_details()
                self.hero_status.setText(('当前分配：'+hero+'；仍可交换，切入本局游戏后复核') if stable and hero else '选人文字尚不确定：'+value.get('reason',''))
                if not stable and not self.lcu_toggle.isChecked():self.hero_status.setText(self.hero_status.text()+'；可在设置开启客户端选人只读资料，辅助显示英雄评级。')
                if value.get('lcuFallback'):
                    from lcu_selection import unavailable_reason
                    self.hero_status.setText(unavailable_reason(value.get('lcuError'))+'；已回退截图识别。'+self.hero_status.text())
                elif value.get('method')=='lcu-read-only':self.hero_status.setText('本机客户端只读选人资料 · '+self.hero_status.text())
                self.debug_event('recognition',reason='recognized' if stable and hero else 'hero_unknown',hero_present=bool(hero),hero_name=hero,hero_source='lcu-read-only' if value.get('method')=='lcu-read-only' else 'selection-pixels',stage=self.selection_session.stage,stable_frames=self.selection_session.candidate_frames)
                self.status.setText(self.hero_status.text());self.check_target()
            elif kind=='ocr':
                self._visible_previous=False
                self.ocr_busy=False;self.capture_pending=False;self._restore_while_ocr=False;self.overlay.set_rechecking(False)
                if not self.state.running or generation!=self.state.generation:return
                if not self.captured_frame_current(value):return
                if value.get('_captureRect') is not None:self.last_rect=value['_captureRect']
                if value.get('_frameScope') is not None and not self.partial_scope_current(value['_frameScope']):
                    self.invalidate_scene('识别期间候选来源或范围变化，已丢弃旧画面。');return
                if (self.window_policy or self.automatic_policy) and (not self.target_allowed() or tuple(value.get('_windowIdentity',()))!=self.target.identity):
                    if self.selection_session:self.selection_session.clear('Game permission changed during inference')
                    self.invalidate_scene('游戏窗口身份变化，旧资料已清空');self.overlay.hide('target_unavailable');return
                captured_at=value.get('_capturedAt',0)
                if not isinstance(captured_at,(int,float)) or not math.isfinite(captured_at) or time.monotonic()-captured_at>4 or captured_at>time.monotonic():
                    self.debug_event('capture',phase='discarded',reason='stale_frame',age_ms=max(0.,(time.monotonic()-captured_at)*1000) if isinstance(captured_at,(int,float)) and math.isfinite(captured_at) else 0,ttl_ms=4000)
                    if (type(captured_at) in (int,float) and math.isfinite(captured_at) and 0<captured_at<=time.monotonic()
                            and time.monotonic()-captured_at>4 and self.partial_scope_current(value.get('_frameScope'))):
                        # A late result is not a lost window/session permission.
                        # Reject its authority and all confirmation continuity,
                        # while an independently captured latest frame may proceed.
                        self.expire_game_display();self.clear_partial_candidates()
                        self.state.observed=();self.state.stable_frames=0
                        self.state.automatic_observed=();self.state.automatic_frames=0
                        self.state.hero_observed='';self.state.hero_stable_frames=0
                        self.state.reason='识别完成时截图已过期，旧资料隐藏；等待新截图'
                        self.status.setText(self.state.reason);return
                    self.invalidate_scene('识别完成时截图时间无效，旧资料隐藏；等待新截图',debug_reason='stale_frame');self.overlay.hide('target_unavailable');self.status.setText(self.state.reason);return
                if self.last_observation and captured_at-self.last_observation>4:
                    # A fresh result after a long observation gap is useful,
                    # but cannot borrow old private confirmation counters.
                    self.expire_game_display()
                    self.state.observed=();self.state.stable_frames=0
                    self.state.automatic_observed=();self.state.automatic_frames=0
                    self.state.hero_observed='';self.state.hero_stable_frames=0
                self._geometry_frame=(value.get('_frameScope'),value.get('_cardGeometry')) if value.get('_cardGeometry') is not None else None
                auto_candidates=value.get('automatic_candidates',[])
                self.overlay.set_candidate_geometry(auto_candidates,value.get('image_size'),tuple(spin.value()/100 for spin in self.roi),value.get('_cardGeometry'))
                candidates=auto_candidates if len(auto_candidates)==3 else value.get('candidates',[])
                names=[item['name'] for item in candidates]
                hero_stable=True;retained_identity=None
                if self.hero_auto.isChecked():
                    raw_observation=value.get('hero_observation',{})
                    identity_scope=self.game_identity_scope(value);identity_now=time.monotonic()
                    retained_identity=self.hero_continuity.recover(raw_observation,scope=identity_scope,captured_at=captured_at,now=identity_now,serial=value.get('_captureSerial'),fresh_card_scene=automatic_candidates(auto_candidates,value.get('image_size')),ocr_reused=value.get('ocr_reused',False)) if raw_observation.get('confident') is not True else None
                    from live_client_identity import source_hero_names
                    canonical_names=source_hero_names(self.data)
                    if raw_observation.get('confident') is True and canonical_names.get(raw_observation.get('championId'))!=raw_observation.get('hero'):
                        self.hero_continuity.clear()
                    else:self.hero_continuity.observe(raw_observation,scope=identity_scope,captured_at=captured_at,now=identity_now,serial=value.get('_captureSerial'))
                    observation=value.get('hero_observation',{});recognized=observation.get('hero') if observation.get('confident') is True else '';self.hero_origin='game-api' if observation.get('method')=='game-client-api' and observation.get('confident') is True else 'hud'
                    if observation.get('method')=='game-client-api' and self.selection_session:
                        self.selection_session.stop();self.selection_session=None
                    if self.selection_session and self.target.identity==self.selection_session.game:
                        game_scene=bool(observation.get('confident') is True or automatic_candidates(auto_candidates,value.get('image_size')) )
                        if game_scene:
                            self.selection_session.observe_game(self.target.identity,captured_at,time.monotonic(),generation=value.get('_sessionGeneration'),game_scene=True,hud_hero=observation.get('championId') if observation.get('confident') is True else None)
                        elif self.selection_session.stage in ('game-provisional','game-verified','game-expired'):
                            self.selection_session.observe_game(self.target.identity,captured_at,time.monotonic(),generation=value.get('_sessionGeneration'),game_scene=False)
                        carried=self.selection_session.visible_identity(allow_provisional=True)
                        if carried:
                            recognized=next((name for name,row in self.data['heroes'].items() if str(row.get('championId'))==carried['championId']),'');self.hero_origin='client-verified' if carried['verified'] else 'client-provisional'
                            observation={**observation,'reason':'来自本局选人；'+('本人HUD已复核' if carried['verified'] else 'HUD尚未复核')}
                    if recognized not in self.data.get('heroes',{}):recognized=''
                    if retained_identity:
                        recognized=retained_identity['hero'];self.hero_origin='game-continuity'
                        self.state.hero=recognized;hero_stable=True
                        observation={**observation,'reason':retained_identity['reason']}
                    else:hero_stable=self.state.observe_hero(recognized)
                    self.hero_box.blockSignals(True);self.hero_box.setCurrentText(self.state.hero);self.hero_box.blockSignals(False)
                    self.hero_status.setText((self.state.hero+' · '+observation.get('reason','')) if hero_stable else observation.get('reason','本人头像尚不确定')+'；等待新画面或人工纠正')
                    if value.get('_liveIdentityUnavailable'):self.hero_status.setText('本机英雄接口不可用，已使用 HUD 识别。'+self.hero_status.text())
                safe_candidates=automatic_candidates(auto_candidates,value.get('image_size'))
                self.observe_partial_candidates(value,captured_at)
                partial_evidence=value.get('partial_title_evidence')
                # Keep card evidence independent of hero availability: an unknown
                # hero must not conceal whether title rows were found at all.
                card_diagnosis=('title_low_confidence' if getattr(partial_evidence,'valid',False) and any(slot.confidence<.93 for slot in partial_evidence.slots) else
                    'title_dictionary_miss' if getattr(partial_evidence,'valid',False) and any(not slot.name for slot in partial_evidence.slots) else
                    'candidate_missing' if len(auto_candidates)!=3 else
                    'candidate_untrusted' if any(item.get('match_method')!='exact' or item.get('ocr_confidence',0)<.93 for item in auto_candidates) else
                    'candidate_layout' if not safe_candidates else 'awaiting_confirmation')
                self.debug_event('card_observation',reason=card_diagnosis,candidate_count=len(auto_candidates),
                    hero_present=bool(self.state.hero),card_geometry_proven=value.get('_cardGeometry') is not None,
                    title_evidence_valid=getattr(partial_evidence,'valid',False))
                diagnosis=('hero_unknown' if not self.state.hero else
                    'title_low_confidence' if getattr(partial_evidence,'valid',False) and any(slot.confidence<.93 for slot in partial_evidence.slots) else
                    'title_dictionary_miss' if getattr(partial_evidence,'valid',False) and any(not slot.name for slot in partial_evidence.slots) else
                    'candidate_missing' if len(auto_candidates)!=3 else
                    'candidate_untrusted' if any(item.get('match_method')!='exact' or item.get('ocr_confidence',0)<.93 for item in auto_candidates) else
                    'candidate_layout' if not safe_candidates else 'awaiting_confirmation')
                self.debug_event('recognition',reason=diagnosis,candidate_count=len(auto_candidates),hero_present=bool(self.state.hero))
                for slot in getattr(partial_evidence,'slots',()):
                    tier=display_cards(self.data,self.state.hero,[slot.name])[0].get('sourceTier') if slot.name and self.state.hero else None
                    self.debug_event('recognition',reason='hero_unknown' if not self.state.hero else 'recognized' if slot.name and tier else 'source_tier_missing' if slot.name else 'title_low_confidence' if slot.confidence<.93 else 'title_dictionary_miss',slot=slot.slot-1,augment_name=slot.name,hero_name=self.state.hero,confidence=slot.confidence,catalog_match=bool(slot.name),tier_present=bool(tier),hero_source=self.hero_origin)
                if value.get('ocr_reused') is True and not self.state.confirmed:
                    self.clear_partial_candidates();self.ocr_reuse.clear();self.refresh_card_details();self.overlay.hide('unconfirmed');return
                if self.state.confirmed and self.state.confirmation_mode=='automatic' and not safe_candidates:self.state.invalidate('候选置信度或三卡布局不足，旧资料已隐藏')
                stable=self.state.observe(names,generation=self.state.generation)
                automatic_stable=(self.state.confirmed and self.state.confirmation_mode=='automatic') if value.get('ocr_reused') is True else self.state.observe_automatic_candidates(names,safe_candidates)
                self.debug_event('recognition',reason='awaiting_confirmation' if not (stable and automatic_stable and hero_stable) else 'recognized',stable_frames=self.state.stable_frames,automatic_frames=self.state.automatic_frames,hero_stable_frames=self.state.hero_stable_frames,hero_source=self.hero_origin,hero_present=bool(self.state.hero),fresh=True)
                self.last_observation=captured_at
                if not self.state.confirmed:self.refresh_card_details()
                if stable and not self.state.confirmed and not self.manual_editing:
                    for edit,name in zip(self.inputs,names):edit.setText(name)
                uncertainty=any(item.get('match_method')!='exact' or item.get('ocr_confidence',0)<.85 for item in candidates)
                self.status.setText((self.identity_wait_message(value) if self.hero_auto.isChecked() and not self.state.hero else (retained_identity['reason']+'；' if retained_identity else '本机英雄接口不可用，已回退 HUD。' if value.get('_liveIdentityUnavailable') else '')+self.state.reason)+('；存在模糊/低置信识别，务必人工核对。' if uncertainty else ''))
                if stable and automatic_stable and hero_stable and bool(self.state.hero) and safe_candidates and not self.manual_editing and not self.state.confirmed:
                    self.confirm(automatic=True,captured_at=captured_at)
                if not self.state.confirmed:
                    self._accepted_frame=None;self._restore_while_ocr=False
                    if not self.show_partial_candidates():self.overlay.hide('unconfirmed')
                if self.state.confirmed:
                    missing=any(card['sourceTier'] is None for card in display_cards(self.data,self.state.hero,self.state.offered))
                    self.debug_event('recognition',reason='source_tier_missing' if missing else 'recognized',candidate_count=len(self.state.offered),hero_present=True)
                self.remember_accepted_frame(value)
                self.remember_accepted_partial_frame(value)
                if (self.state.confirmed and safe_candidates and value.get('_cardGeometry') is not None
                        and (not self.overlay._titles_pending or value.get('ocr_reused') is not True)):
                    self.overlay.set_title_checking(False)
                self.check_target()
            elif kind=='portraits-roster':
                if (generation!=self._portraits_attempt or generation==self._portraits_completed_attempt
                        or not self._portraits_busy or self._cancel_workers.is_set()):return
                self.receive_portrait_roster(value)
            elif kind in ('portraits','portraits-cache'):
                if generation!=self._portraits_attempt or generation==self._portraits_completed_attempt:return
                portraits,status=value
                publication=None
                if portraits:
                    try:publication=self.receive_portraits(portraits,status)
                    except Exception as exc:
                        self.debug_log.record('templates',template_outcome='unavailable',generation=generation,worker_error_category=classify_worker_error(exc))
                        self.debug_log.record('job',kind='portraits',phase='error',generation=generation,error_code='worker_error',worker_error_category=classify_worker_error(exc))
                        if kind=='portraits':self._portraits_completed_attempt=generation;self.finish_portrait_attempt()
                        self.hero_status.setText('自动英雄模板初始化失败；等待恢复或人工纠正。');return
                outcome=publication if publication in ('unchanged','deferred') else ('cached_ready' if kind=='portraits-cache' else 'ready') if portraits else 'unavailable'
                self.debug_log.record('templates',template_outcome=outcome,generation=generation,**({'worker_error_category':status['errorCategory']} if 'errorCategory' in status else {}))
                roster_fingerprint=cached_roster_fingerprint(self.state_dir/'hero-portraits')
                if roster_fingerprint!=self._selection_roster_fingerprint:
                    self._selection_roster_fingerprint=roster_fingerprint;self.selection_detector=None
                self.portrait_diagnostics=status.get('cacheDiagnostics');self.cache_diagnostic_button.setVisible(isinstance(self.portrait_diagnostics,dict))
                if kind=='portraits':self._portraits_completed_attempt=generation;self.finish_portrait_attempt()
                self.hero_status.setText(status.get('message','头像模板状态未知')+('；新模板将在停止监测或接续新窗口后启用。' if publication=='deferred' else '；自动监测中将按退避间隔重试。' if kind=='portraits' and self.hero_matcher is None and self.enable_updates else ''))
                if self.overlay.reference:self.overlay.set_hero_reference(self.overlay.reference)
            elif kind=='update':
                self.update_status.setText('软件更新：'+value.get('message',value.get('state','未知')))
                self.release=value.get('release') if value.get('state')=='available' else None
                self.update_button.setVisible(bool(self.release and self.frozen))
            elif kind=='install':
                self.status.setText('更新已准备，正在关闭并由更新器重启。');self.close();QtWidgets.QApplication.instance().quit()
        finally:
            if kind in ('ocr','selection'):
                if isinstance(value,dict) and isinstance(value.get('_timings'),dict):self.last_timings=value['_timings']
                self.schedule_capture()
            self.refresh_status_badge()
    @QtCore.Slot(str,str,int)
    def task_error(self,kind,error,generation):
        if self.closed or self.discard_stale_capture_callback(kind,generation):return
        # The worker already counted its failure. This is a GUI receipt, never
        # another failure or a parse of the exception's message.
        self.debug_log.record('job',kind=kind,phase='accepted',generation=generation,
            serial=self._capture_serial if kind in ('ocr','selection') else 0,reason='worker_error')
        if kind=='windows':
            if generation==self.discovery_scope:
                self.discovery_busy=False;self.pause_window_discovery()
            return
        if kind in ('ocr','selection'):
            selection_failure=('interface_failed' if self._selection_capture_state=='interface' else 'recognition_failed' if self._selection_capture_state=='captured' else 'capture_failed') if kind=='selection' else None
            self._visible_previous=False
            self.ocr_busy=False;self.capture_pending=False;self._restore_while_ocr=False;self.overlay.set_rechecking(False)
            if kind=='selection' and self.selection_session:self.selection_session.clear('Client recognition failure')
            if generation==self.state.generation:self.invalidate_scene('识别失败：'+error,debug_reason='worker_error');self.overlay.hide('target_unavailable');self.status.setText(self.state.reason)
            if selection_failure:self._selection_capture_state=selection_failure
            if selection_failure=='interface_failed':
                self._lcu_pixel_fallback=True;self._lcu_error='local_client_unavailable';self.selection_retry.failed(time.monotonic())
            self.schedule_capture(1000)
        elif kind=='portraits':
            if generation!=self._portraits_attempt or generation==self._portraits_completed_attempt:return
            self._portraits_completed_attempt=generation;self.finish_portrait_attempt()
            self.hero_status.setText('自动英雄模板加载失败：'+error+('；自动监测中将重试，可人工纠正。' if self.enable_updates else '；可人工纠正。'))
        elif kind=='load':self.startup_error=error or '未提供错误详情';self.source.setText('资料加载失败：'+error);self.status.setText('未加载真实资料，不使用演示数据代替。')
        elif kind=='install':self.update_button.setEnabled(True);self.update_status.setText('更新失败，原程序不变：'+error)
        else:self.update_status.setText('更新检查失败：'+error)
        self.refresh_status_badge()
    def ready(self):
        try:
            if self.on_ready:
                if not self.capture or os.name!='nt' or QtWidgets.QApplication.instance().platformName()!='windows':raise CaptureUnavailable('原生 Windows 后端不可用，不能标记更新健康。')
                if not self.isVisible() or not self.capture.u.IsWindowVisible(int(self.winId())) or not self.capture.u.IsWindow(int(self.winId())) or not self.capture.u.IsWindow(int(self.overlay.winId())):raise CaptureUnavailable('原生窗口未就绪。')
                self.overlay.configure()
                self.on_ready()
            if self.selection_smoke_input:
                from selection_smoke import start_selection_smoke
                start_selection_smoke(self,Path(self.selection_smoke_input),Path(self.smoke_report))
            elif self.smoke_report:
                from native_smoke import start_smoke
                start_smoke(self,Path(self.smoke_report),Path(self.smoke_screenshot) if self.smoke_screenshot else Path(self.smoke_report).with_suffix('.png'))
        except Exception as exc:
            self.stop_monitor();self.start_button.setEnabled(False);self.overlay.hide('target_unavailable')
            self.status.setText('启动健康验证失败：'+str(exc))
            try:
                folder=self.state_dir/'logs';folder.mkdir(parents=True,exist_ok=True);(folder/'native-ready-error.txt').write_text(traceback.format_exc(),encoding='utf8')
            except OSError:pass
            if self.smoke_report:
                Path(self.smoke_report).write_text(json.dumps({'status':'failed','error':str(exc)},ensure_ascii=False),encoding='utf8');QtCore.QTimer.singleShot(0,lambda:QtWidgets.QApplication.instance().exit(1))
            elif self.on_ready:QtCore.QTimer.singleShot(0,lambda:QtWidgets.QApplication.instance().exit(1))
    def install_update(self):
        if not self.release or not self.frozen:return
        release=self.release
        box=QtWidgets.QMessageBox(self);box.setWindowTitle('确认软件更新');box.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        box.setText(f"安装 {APP_NAME} {release['version']}？下载和校验后将关闭并重启。\n\n{release.get('notes','')}")
        box.setStandardButtons(QtWidgets.QMessageBox.StandardButton.Yes|QtWidgets.QMessageBox.StandardButton.No);box.setDefaultButton(QtWidgets.QMessageBox.StandardButton.No)
        if box.exec()!=QtWidgets.QMessageBox.StandardButton.Yes:return
        self.stop_monitor();self.update_button.setEnabled(False)
        def install():
            from updates import prepare_update,launch_update
            plan=prepare_update(release,self.current_executable,self.state_dir,confirmed=True)
            if self._cancel_workers.is_set():raise RuntimeError('关闭期间取消更新启动')
            launch_update(plan);return True
        self.spawn('install',install)
    def nativeEvent(self,event_type,message):
        if os.name=='nt':
            msg=W.MSG.from_address(int(message))
            if msg.message==0x0312 and msg.wParam==0x5647:self.toggle_clickthrough();return True,0
        return super().nativeEvent(event_type,message)
    def closeEvent(self,event):
        self.debug_event('close',reason='close');self.debug_event('cancel',reason='close',cancelled=True)
        self.overlay._hide_reason='close'
        self._capture_cancel.set();self.ocr_reuse.clear()
        self.latest_capture.close()
        self.frame_inference_worker.close()
        close_capture=getattr(self.capture,'close',None)
        if close_capture:close_capture() # Nonblocking revocation before HWND destruction.
        with self._worker_lock:self.closed=True;self._cancel_workers.set();jobs=list(self._workers)
        if self.selection_session:self.selection_session.stop()
        if self.window_policy:self.window_policy.stop()
        if self.automatic_policy:self.automatic_policy.stop()
        self.discovery_scope+=1
        self.monitor.stop();self.watchdog.stop();self.state.stop();self.overlay.close()
        if self.capture and self.hotkey_registered:self.capture.release_hotkey(int(self.winId()));self.hotkey_registered=False
        # Running native inference cannot safely be killed; discard its result and
        # let the daemon exit naturally. Never wait indefinitely in the UI thread.
        deadline=time.monotonic()+.2
        for job in jobs:
            if job is not threading.current_thread():job.join(max(0,deadline-time.monotonic()))
        self.debug_log.set_enabled(False)
        event.accept()


def run_native(startup_loader,*,state_dir,current_executable,current_version,frozen,on_ready=None,smoke_report=None,smoke_screenshot=None,enable_updates=True,selection_smoke_input=None):
    app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([]);app.setApplicationName(APP_NAME);app.setQuitOnLastWindowClosed(True)
    # Keep existing native/selection diagnostic baselines strictly hidden.
    capture_options={'enable_visible_capture':False} if smoke_report or selection_smoke_input else {}
    control=ControlWindow(startup_loader,state_dir=state_dir,current_executable=current_executable,current_version=current_version,frozen=frozen,on_ready=on_ready,smoke_report=smoke_report,smoke_screenshot=smoke_screenshot,enable_updates=enable_updates,selection_smoke_input=selection_smoke_input,**capture_options)
    app._vga_control=control
    return app.exec()

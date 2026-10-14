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
from pathlib import Path
import threading
import traceback
import time
from PySide6 import QtCore,QtGui,QtWidgets
from native_state import RecognitionState,display_cards,automatic_candidates
from frame_ocr_cache import FrameOCRCache
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

class Overlay(QtWidgets.QWidget):
    def __init__(self,capture=None):
        super().__init__(None,QtCore.Qt.WindowType.Tool|QtCore.Qt.WindowType.FramelessWindowHint|QtCore.Qt.WindowType.WindowStaysOnTopHint|QtCore.Qt.WindowType.WindowDoesNotAcceptFocus)
        self.capture=capture;self.click_through=True;self.cards=[];self.reference=None;self._layout_revision=0;self._placed_key=None;self._detail_labels=[];self._compact=False;self._rechecking=False
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setWindowTitle(APP_NAME+' · 资料叠加');self.setStyleSheet(STYLE+'\nOverlay{background:transparent;}')
        self.setWindowFlag(QtCore.Qt.WindowType.WindowTransparentForInput,True)
        layout=QtWidgets.QVBoxLayout(self);layout.setContentsMargins(0,0,0,0)
        self.panel=QtWidgets.QFrame();self.panel.setObjectName('overlay-panel');self.panel.setStyleSheet('#overlay-panel{background:rgba(250,252,255,250);border:1px solid #D9E0E9;border-radius:10px} #overlay-panel QLabel{background:transparent;border:0} QLabel#overlay-heading{font-size:13px;font-weight:600} QLabel#source-tier-label{color:#536075;font-size:12px;font-weight:600}')
        layout.addWidget(self.panel);inner=QtWidgets.QVBoxLayout(self.panel);inner.setContentsMargins(10,10,10,10);inner.setSpacing(8)
        self.heading=label('');self.heading.setObjectName('overlay-heading');self.footer=label('仅窗口像素 · Ctrl+Alt+O · 非 Riot 评级/批准',True);summary=QtWidgets.QHBoxLayout();self.summary_layout=summary;summary.addWidget(self.heading,1);summary.addWidget(self.footer,1);self.metadata_label=label('',True);inner.addWidget(self.metadata_label);self.row=QtWidgets.QHBoxLayout();self.row.setSpacing(8);inner.addLayout(self.row);inner.addLayout(summary)
        self.resize(820,76)
    def set_cards(self,hero,cards,source_date='未知',source_version='未知',confirmation='人工确认'):
        signature=(hero,json.dumps(cards,ensure_ascii=False,sort_keys=True),source_date,source_version,confirmation)
        if self.reference is None and getattr(self,'_card_signature',None)==signature:
            self.set_rechecking(False);return
        self._card_signature=signature
        self.cards=cards;self.reference=None;self.tier_labels=[];self._pill_labels=[];self._detail_labels=[];self._card_layouts=[];self._title_labels=[];self._layout_revision+=1;self._placed_key=None
        while self.row.count():
            item=self.row.takeAt(0);widget=item.widget()
            if widget:widget.hide();widget.deleteLater()
        self._full_heading=f'{hero}  ·  {confirmation}'
        compact_confirmation={'英雄/候选连续高置信自动识别':'连续高置信自动识别','英雄人工纠正 · 候选自动识别':'英雄人工 · 候选自动'}.get(confirmation,confirmation)
        self._compact_heading=f'{hero} · {compact_confirmation}'
        self.heading.setStyleSheet('font-size:12px;font-weight:'+('600;color:#8D6600' if 'HUD未复核' in confirmation else '400;color:#687385'))
        self.heading.setText(self._full_heading);self.metadata_label.setText(f'来源日期 {source_date} · {source_version}')
        source_labels={card.get('sourceTierLabel','虎牙公开源评级') for card in cards}
        self._source_marker='虚构演示' if source_labels=={'虚构源评级（演示）'} else '虎牙公开源' if source_labels=={'虎牙公开源评级'} else '来源待核对'
        for card in cards:
            frame=QtWidgets.QFrame();frame.setObjectName('overlay-card');frame.setStyleSheet('#overlay-card{background:transparent;border:0;border-right:1px solid #E6EAF0;border-radius:0}')
            box=QtWidgets.QHBoxLayout(frame);box.setContentsMargins(10,8,10,8);box.setSpacing(8);self._card_layouts.append(box)
            title=label(card['name']);title.setAccessibleName(f"选项 {card['slot']} · {card['name']}");title.setObjectName('card-title');title.setStyleSheet('font-size:14px;font-weight:600');self._title_labels.append(title);box.addWidget(title,1)
            tier=card.get('sourceTier') or '暂无评级';tier_label=label(tier);tier_label.setAccessibleName(f"{card.get('sourceTierLabel','虎牙公开源评级')}：{tier}");tier_label.setObjectName('source-tier-label');tier_label.setStyleSheet('color:#536075;background:#EEF2F7;border-radius:5px;padding:3px 7px;font-size:12px;font-weight:600');self.tier_labels.append(tier_label);box.addWidget(tier_label,0,QtCore.Qt.AlignmentFlag.AlignVCenter);self.row.addWidget(frame,1)
        self._set_compact(True);self.adjustSize();self.resize(820,max(52,self.height()))
    def set_hero_reference(self,reference):
        if self.reference==reference:return
        self.cards=[];self.reference=dict(reference);self._rechecking=False;self.tier_labels=[];self._pill_labels=[];self._detail_labels=[];self._card_layouts=[];self._title_labels=[];self._layout_revision+=1;self._placed_key=None
        while self.row.count():
            item=self.row.takeAt(0);widget=item.widget()
            if widget:widget.hide();widget.deleteLater()
        self._full_heading=self._compact_heading='当前分配 · 仍可交换 · HUD未复核'
        self.heading.setStyleSheet('font-size:12px;font-weight:600;color:#8D6600')
        self._source_marker='虚构演示' if reference['isDemo'] else '虎牙公开源' if reference['sourceUrl'] else '来源待核对'
        self.metadata_label.setText(f"英雄评级快照 {reference['sourceDataDate'] or '日期未知'} · 英雄资料 {reference['sourceVersion'] or '未知'} · 游戏资料 {reference['gamePatch'] or '未知'} · 数据包 {reference['wikiDataVersion'] or '未知'}")
        frame=QtWidgets.QFrame();box=QtWidgets.QHBoxLayout(frame);box.setContentsMargins(8,4,8,4);box.setSpacing(12);self._card_layouts.append(box)
        title=label(reference['hero']);title.setAccessibleName('当前分配英雄：'+reference['hero']);self._title_labels.append(title);box.addWidget(title,1)
        tier=label('英雄整体强度：'+(reference['sourceTier'] or '暂无评级'));tier.setAccessibleName(reference['sourceTierLabel']+'：'+(reference['sourceTier'] or '暂无评级'));self.tier_labels.append(tier);box.addWidget(tier);self.row.addWidget(frame)
        self._set_compact(True);self.adjustSize();self.resize(820,max(52,self.height()))
    def configure(self):
        if self.capture:self.capture.configure_overlay(int(self.winId()),self.click_through)
    def set_rechecking(self,value):
        value=bool(value)
        if self._rechecking==value:return
        self._rechecking=value;self._layout_revision+=1;self._placed_key=None
        if self.cards:self._set_compact(self._compact,dense=getattr(self,'_dense',False))
    def set_click_through(self,value):
        self.click_through=bool(value);self.hide();self._placed_key=None;self._layout_revision+=1
        self.setWindowFlag(QtCore.Qt.WindowType.WindowTransparentForInput,self.click_through)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.configure()
    def _set_compact(self,compact,*,dense=False):
        self._compact=compact;self._dense=bool(dense)
        self.summary_layout.setDirection(QtWidgets.QBoxLayout.Direction.TopToBottom if dense else QtWidgets.QBoxLayout.Direction.LeftToRight)
        for pill in self._pill_labels:pill.setVisible(not dense)
        self.heading.setText((self._compact_heading if compact else self._full_heading)+(' · 上次候选复核中' if self._rechecking else ''))
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
            self.hide()
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
                self.hide();dpr=final_dpr
            raise CaptureUnavailable('叠加跨显示器缩放持续变化，暂时隐藏，等待稳定布局。')
        except Exception:
            self._placed_key=None;self.hide();raise
    def nativeEvent(self,event_type,message):
        if os.name=='nt':
            msg=W.MSG.from_address(int(message))
            if msg.message==0x0084 and self.click_through:return True,-1 # HTTRANSPARENT, no hooks
            if msg.message==0x0021:return True,3 # MA_NOACTIVATE
        return super().nativeEvent(event_type,message)

class ControlWindow(QtWidgets.QWidget):
    def __init__(self,startup_loader,*,state_dir,current_executable,current_version,frozen,on_ready=None,smoke_report=None,smoke_screenshot=None,enable_updates=True,selection_smoke_input=None):
        super().__init__();self.state=RecognitionState();self.data=None;self.startup_error='';self.target=None;self.capture=None;self.last_rect=None;self.was_target_foreground=False;self.ocr_busy=False;self.manual_editing=False;self.capture_pending=False;self.last_observation=0.;self.ocr_started=0.;self.ocr_timed_out=False;self.closed=False;self.on_ready=on_ready
        self._worker_lock=threading.Lock();self._cancel_workers=threading.Event();self._workers=set();self.ocr_reuse=FrameOCRCache();self._capture_cancel=threading.Event();self.manual_metadata=None;self.manual_identity=None
        self._capture_serial=0;self._accepted_frame=None;self._restore_while_ocr=False;self.last_timings=None;self.last_candidates=None
        self.enable_updates=enable_updates;self.hero_matcher=None;self.selection_session=None;self.window_policy=None;self.client_target=None;self.selection_detector=None;self.hero_origin='hud';self.selection_smoke_input=selection_smoke_input;self.last_window_discovery=0.;self.automatic_policy=None;self.discovery_busy=False;self.discovery_scope=0
        self.current_version=current_version;self.current_executable=Path(current_executable);self.state_dir=Path(state_dir);self.frozen=frozen;self.release=None;self.smoke_report=smoke_report;self.smoke_screenshot=smoke_screenshot;self.hotkey_registered=False
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
        self.about_panel=QtWidgets.QFrame();self.about_panel.setObjectName('section');about=QtWidgets.QVBoxLayout(self.about_panel);about.setContentsMargins(16,16,16,16);about.setSpacing(12);secondary.addWidget(self.about_panel);self.about_panel.hide()
        self.source=label('正在检查公开数据，首次启动可能需要数十秒…',True);about.addWidget(self.source)
        self.compatibility=label('仅核验窗口的可见像素，不读取游戏内存。支持窗口 / 无边框模式；实际 LoL 与 Vanguard 兼容性尚未验证。',True);about.addWidget(self.compatibility)
        about.addWidget(label('英雄整体强度使用公开源原始 T1–T5；强化评级使用 T1–T4，缺失显示暂无评级。保留三项原位置，不展示胜率、换算等级或推荐唯一最佳选项；公开源快照并非实时评级或 Riot 批准。',True))
        about.addWidget(label('开始后控制台自动最小化；切出、被遮挡或识别不确定时清空旧结果。截图不保存、不上传。',True))
        self.portrait_diagnostics=None;self.cache_diagnostic_button=QtWidgets.QPushButton('头像缓存诊断');self.cache_diagnostic_button.hide();self.cache_diagnostic_button.clicked.connect(self.show_cache_diagnostics);about.addWidget(self.cache_diagnostic_button)
        self.capture_diagnostic=label('采集诊断：尚无画面。截图成功与全屏叠加可见是两项独立检查。',True);self.capture_diagnostic.setAccessibleName('最近采集阶段与耗时');about.addWidget(self.capture_diagnostic)
        self.update_status=label('软件更新待检查。',True);about.addWidget(self.update_status);self.update_button=QtWidgets.QPushButton('查看并安装软件更新');self.update_button.hide();about.addWidget(self.update_button)
        self.status=label('准备中…',True);self.status.setAccessibleName('当前监测状态');secondary.addWidget(self.status);secondary.addStretch()
        divider=QtWidgets.QFrame();divider.setObjectName('divider');divider.setFixedHeight(1);outer.addWidget(divider)
        footer=QtWidgets.QHBoxLayout();footer.setSpacing(16)
        self.hero_auto=Switch('自动识别');self.hero_auto.setToolTip('结合本局选人文字与局内 HUD，高置信连续识别后自动使用');self.hero_auto.setChecked(True);footer.addWidget(self.hero_auto)
        self.toggle_button=Switch('鼠标穿透');self.toggle_button.setChecked(True);self.toggle_button.setToolTip('Ctrl+Alt+O 切换鼠标穿透，不改变识别或叠加确认状态');footer.addWidget(self.toggle_button);footer.addStretch()
        self.footer_note=label('仅窗口像素 · 兼容性待验证',True);footer.addWidget(self.footer_note);self.shortcut_label=label('Ctrl + Alt + O',True);self.shortcut_label.setStyleSheet('border:1px solid #D9E0E9;border-radius:5px;padding:4px 8px');footer.addWidget(self.shortcut_label);outer.addLayout(footer)
        self.back_button.clicked.connect(lambda:self.show_page('main'));self.correction_button.clicked.connect(lambda:self.show_page('correction'));self.about_button.clicked.connect(lambda:self.show_page('about'))
        order=[self.start_button,self.stop_button,self.hero_auto,self.toggle_button,self.correction_button,self.advanced_toggle,self.about_button,*self.inputs,self.confirm_button,self.details_toggle,self.window_list,self.refresh,self.client_follow,self.hero_box,*self.roi,self.cache_diagnostic_button,self.update_button]
        for before,after in zip(order,order[1:]):QtWidgets.QWidget.setTabOrder(before,after)
        self.refresh.clicked.connect(self.refresh_windows);self.window_list.currentIndexChanged.connect(self.target_changed);self.hero_box.currentTextChanged.connect(self.hero_changed);self.hero_auto.toggled.connect(self.hero_mode_changed);self.client_follow.toggled.connect(self.follow_scope_changed);self.start_button.clicked.connect(self.start_monitor);self.stop_button.clicked.connect(self.stop_monitor);self.toggle_button.clicked.connect(self.toggle_clickthrough);self.update_button.clicked.connect(self.install_update)
        try:self.capture=Win32Capture()
        except CaptureUnavailable as exc:self.status.setText(str(exc))
        self.overlay=Overlay(self.capture);self.overlay.winId();self.overlay.configure()
        self.monitor=QtCore.QTimer(self);self.monitor.setSingleShot(True);self.monitor.setInterval(200);self.monitor.timeout.connect(self.capture_tick)
        self.watchdog=QtCore.QTimer(self);self.watchdog.setInterval(200);self.watchdog.timeout.connect(self.check_target);self.watchdog.timeout.connect(self.refresh_status_badge);self.watchdog.start()
        self.start_button.setEnabled(False);self.confirm_button.setEnabled(False);self.stop_button.setEnabled(False)
        self.fit_control_to_screen(initial=True);self.show();self.fit_control_to_screen();self.windowHandle().screenChanged.connect(lambda _:self.fit_control_to_screen());self.register_hotkey();self.refresh_windows();self.spawn('load',startup_loader)
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
                if card['notes']:text+='\n条件/提醒：'+'；'.join(card['notes'])
            rows.append(text)
        text='\n\n'.join(rows)
        if self.card_details.text()!=text:self.card_details.setText(text)
    def client_assignment_visible(self):
        return bool(self.selection_session and self.selection_session.active and self.target and self.target.identity==self.selection_session.client)
    def client_strength_reference(self):
        if not self.state.running or not self.hero_auto.isChecked() or not self.client_assignment_visible() or not self.state.hero or self.selection_session.stage!='assigned':return None
        if not 0<=time.monotonic()-self.selection_session.last_client_frame<=4:return None
        from hero_strength import hero_strength_reference
        return hero_strength_reference(self.data,self.state.hero,champion_id=self.selection_session.assigned)
    def refresh_dashboard(self):
        if not hasattr(self,'candidate_views'):return
        current=bool(self.state.running and self.state.confirmed and self.data and len(self.state.offered)==3 and all(name in self.data.get('augments',{}) for name in self.state.offered))
        hero=self.state.hero if self.state.running and self.state.hero else ''
        self.hero_title.setText(hero or '等待识别')
        from hero_strength import hero_strength_reference
        strength=self.client_strength_reference() if self.client_assignment_visible() else hero_strength_reference(self.data,hero) if hero else None
        self.hero_caption.setText('本局英雄'+(' · 英雄整体强度 '+(strength['sourceTier'] or '暂无评级') if strength else ''))
        self.hero_caption.setAccessibleName((strength['sourceTierLabel']+'：'+(strength['sourceTier'] or '暂无评级')) if strength else '本局英雄尚未可靠确定')
        self.hero_provenance.setText(('人工选择 · 未自动推断' if not self.hero_auto.isChecked() else '本局选人 · 仍可交换，HUD未复核' if self.client_assignment_visible() else '来自本局选人 · HUD未复核' if self.hero_origin=='client-provisional' else '本局选人 + HUD复核' if self.hero_origin=='client-verified' else '本人 HUD 连续确认') if hero else '')
        self.hero_provenance.hide();self.secondary_stop.setVisible(self.pages.currentIndex()!=0 and self.state.running)
        if hasattr(self,'overlay'):self.toggle_button.setChecked(self.overlay.click_through)
        self.monitor_actions.setCurrentWidget(self.stop_button if self.state.running else self.start_button);self.stop_button.setEnabled(bool(self.state.running))
        cards=display_cards(self.data,hero,self.state.offered) if current else []
        self.candidate_caption.setText(('虚构演示资料' if self.data.get('metadata',{}).get('isDemo') else '虎牙公开源 · 非 Riot 评级') if current else '等待三个候选稳定确认')
        for index,view in enumerate(self.candidate_views):
            card=cards[index] if current else None;tier=card.get('sourceTier') if card else None
            view['name'].setText(card['name'] if card else '等待识别');view['tier'].setText(tier or '—')
            view['tier'].setAccessibleName((card['sourceTierLabel'] if card else '选项尚未确认')+'：'+(tier or '暂无评级'))
            view['tier'].setProperty('known',tier=='T1');view['tier'].style().unpolish(view['tier']);view['tier'].style().polish(view['tier'])
            view['detail'].setText((('暂无评级 · ' if not tier else '')+card['description'][:34]+('…' if len(card['description'])>34 else '')) if card else '识别稳定后显示资料')
        self._refresh_badge()
        self.refresh_history()
        if self.last_timings:
            self.capture_diagnostic.setText(f"最近后端 {getattr(self.capture,'last_backend','未知')} · 截图 {self.last_timings.get('capture_ms','未知')} ms · 本地识别 {self.last_timings.get('inference_ms','未知')} ms\n若已识别但游戏内不可见，请比较全屏与无边框；当前诊断不能证明真实独占全屏兼容。")
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
        # Presentation only: derive from explicit state, never status-text keywords.
        if self.startup_error:state,text='error','资料加载失败 · 关于查看详情'
        elif not self.data:state,text='waiting','资料待就绪'
        elif not self.capture:state,text='waiting',('演示资料 · 未连接游戏' if self.data.get('metadata',{}).get('isDemo') else '采集不可用')
        elif not self.state.running:state,text='idle','未开始'
        elif self.state.confirmed:state,text='confirmed','资料已确认'
        elif self.ocr_busy:state,text='working','正在识别'
        elif self.target is None:state,text='waiting','等待连接'
        else:state,text='waiting','等待核对'
        if self.capture and self.state.running and self.state.hero and self.hero_auto.isChecked() and (self.hero_origin=='client-provisional' or self.client_assignment_visible()):state='provisional'
        if self.status_chip.property('state')!=state:
            self.status_chip.setProperty('state',state);self.status_chip.style().unpolish(self.status_chip);self.status_chip.style().polish(self.status_chip)
        if self.capture and self.state.running and self.state.hero:text=self.hero_provenance.text()+' · '+text
        self.status_chip.setText(text)
    def spawn(self,kind,fn,generation=0):
        def worker():
            value=error=None
            try:
                if self._cancel_workers.is_set():return
                try:value=fn()
                except Exception as exc:error=str(exc)
                # Serialized with closeEvent: never emit into Qt after teardown starts.
                with self._worker_lock:
                    if not self._cancel_workers.is_set() and not self.closed:
                        if error is None:self.signals.result.emit(kind,value,generation)
                        else:self.signals.error.emit(kind,error,generation)
            finally:
                with self._worker_lock:self._workers.discard(threading.current_thread())
        job=threading.Thread(target=worker,name='vga-'+kind,daemon=True)
        with self._worker_lock:
            if self._cancel_workers.is_set():return
            self._workers.add(job);job.start()
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
    def target_allowed(self):
        if not self.target:return False
        if self.automatic_policy:return self.automatic_policy.permits(self.target,windows=self.capture.windows())
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
        self.spawn('windows',lambda:policy.discover(self.capture.windows()),scope)
    def apply_discovery(self,value,scope):
        if scope!=self.discovery_scope or not self.automatic_policy or not self.state.running:return
        self.discovery_busy=False;policy=self.automatic_policy;previous_binding=policy.bound
        new_confirmation=value.confirmation is not None and value.confirmation!=self.unverified_candidate
        self.unverified_candidate=value.confirmation;self.trust_button.setVisible(value.confirmation is not None)
        if new_confirmation and self.isMinimized():QtWidgets.QApplication.alert(self,0)
        if not value.candidate or not policy.adopt(value,windows=self.capture.windows()):
            if self.target:self.invalidate_scene('等待唯一且已核验的英雄联盟窗口。')
            self.target=None;self.state.target=None;self.overlay.hide();self.last_rect=None
            reason=value.reason if not value.candidate else '窗口列表已变化，正在重新检测；不会使用过期连接。'
            self.window_status.setText(reason);self.status.setText(reason);return
        candidate=policy.bound;target=candidate.window
        if self.target and target.identity==self.target.identity and previous_binding and previous_binding.metadata==candidate.metadata and self.target_allowed():
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
        self.invalidate_scene('已自动连接'+('客户端，等待选人画面。' if candidate.role=='client' else '游戏，等待本人 HUD 与候选画面。'))
        self.overlay.hide();self.window_status.setText(value.reason+' '+target.title);self.status.setText(self.state.reason)
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
        if policy.confirm_installation(candidate,windows=self.capture.windows()):
            self.trust_button.hide();self.unverified_candidate=None;self.queue_discovery(force=True);self.showMinimized()
        else:self.status.setText('窗口身份已变化，正在重新检测，请确认新的提示。')
    def show_cache_diagnostics(self):
        if not isinstance(self.portrait_diagnostics,dict):return
        dialog=QtWidgets.QMessageBox(self);dialog.setWindowTitle('头像缓存诊断（仅本机）')
        dialog.setText('以下是缓存写入的错误码与文件状态，用于定位原因。没有截图、用户名或完整路径；不会自动上传。')
        dialog.setDetailedText(json.dumps(self.portrait_diagnostics,ensure_ascii=False,indent=2))
        dialog.setStandardButtons(QtWidgets.QMessageBox.StandardButton.Ok);dialog.exec()
    def hero_mode_changed(self,automatic):
        self._accepted_frame=None;self._restore_while_ocr=False;self.overlay.set_rechecking(False)
        if not automatic:self.advanced_toggle.setChecked(True)
        self.hero_box.setEnabled(not automatic);self.state.clear_hero();self.refresh_card_details();self.overlay.hide();self.manual_editing=False
        self.hero_box.blockSignals(True);self.hero_box.setCurrentText('');self.hero_box.blockSignals(False)
        self.refresh_dashboard();self.hero_status.setText('等待本人 HUD 头像，连续两帧高置信后自动使用。' if automatic else '人工纠正模式：请选择已确认的本人英雄。')
    def hero_changed(self,text):
        self._accepted_frame=None;self._restore_while_ocr=False;self.overlay.set_rechecking(False)
        if text:self.advanced_toggle.setChecked(True)
        if text and self.hero_auto.isChecked():
            self.hero_auto.blockSignals(True);self.hero_auto.setChecked(False);self.hero_auto.blockSignals(False);self.hero_box.setEnabled(True)
        hero=text if self.data and text in self.data.get('heroes',{}) else getattr(self,'hero_aliases',{}).get(text,'')
        self.hero_origin='manual';self.state.select_hero(hero);self.refresh_card_details();self.overlay.hide();self.status.setText(self.state.reason)
    def invalidate_scene(self,reason):
        self._capture_cancel.set();self.ocr_reuse.clear()
        self._accepted_frame=None;self._restore_while_ocr=False;self.overlay.set_rechecking(False)
        if self.hero_auto.isChecked():
            self.state.clear_hero();self.hero_box.blockSignals(True);self.hero_box.setCurrentText('');self.hero_box.blockSignals(False)
        self.state.invalidate(reason);self.overlay.hide();self.status.setText(reason);self.refresh_card_details()
    def roi_changed(self,*_):
        self.invalidate_scene('截图范围改变，请重新识别确认');self.overlay.hide()
    def edit_changed(self,*_):
        self._accepted_frame=None;self._restore_while_ocr=False;self.overlay.set_rechecking(False)
        self.manual_editing=True;self.state.invalidate('候选已修改，请重新确认',clear_observed=False);self.refresh_card_details();self.overlay.hide()
    def follow_scope_changed(self,*_):
        self.stop_monitor();self.status.setText("接续窗口范围已改变；本局授权已停止，请重新点击开始。")
    def start_monitor(self):
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
            if self.client_follow.isChecked() and self.target.class_name in ('Chrome_WidgetWin_1','CEFCLIENT'):
                try:
                    from session_windows import SessionWindowPolicy
                    from selection_session import SelectionSession
                    self.window_policy=SessionWindowPolicy(self.target);self.client_target=self.target;self.selection_session=SelectionSession();self.selection_session.start(self.target.identity)
                except (OSError,ValueError) as exc:return self.status.setText('无法核验客户端所属安装目录，本局监测未开始：'+str(exc))
            self.state.start(self.target.identity)
        if self.hero_auto.isChecked():self.state.clear_hero()
        self.monitor.start(0);self.overlay.hide();self.stop_button.setEnabled(True);self.confirm_button.setEnabled(True)
        self.refresh_status_badge();self.status.setText('已开始自动监测。控制台将最小化，恢复它可随时停止。')
        self.queue_discovery(force=True)
        # On the GUI thread, minimize only after Start succeeds. Never hide a
        # different app and never restore/activate the game on the user's behalf.
        if not self.smoke_report and not self.selection_smoke_input:self.showMinimized()
    def stop_monitor(self):
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
        self.overlay.hide();self.stop_button.setEnabled(False);self.confirm_button.setEnabled(False)
        self.status.setText(self.state.reason);self.refresh_status_badge()
    def advance_session_window(self):
        if self.automatic_policy:
            if self.selection_session:
                old=self.selection_session.generation;self.selection_session.expire(time.monotonic())
                if old!=self.selection_session.generation:self.invalidate_scene('选人记录已过期，等待当前画面重新识别。')
            return
        if not self.selection_session or not self.window_policy:return
        now=time.monotonic();old=self.selection_session.generation;self.selection_session.expire(now)
        if old!=self.selection_session.generation:self.invalidate_scene('本局选人记录因画面断档失效，等待重新识别')
        if self.target.identity!=self.window_policy.client_identity or self.selection_session.stage!='assigned' or now-self.last_window_discovery<.5:return
        self.last_window_discovery=now;windows=self.capture.windows();candidate=self.window_policy.discover_game(windows)
        if not candidate or not self.capture.foreground(candidate[0]):return
        token=self.selection_session.generation
        if not self.window_policy.adopt_game(candidate,windows=self.capture.windows(),confirmed_handoff=True):return
        if not self.selection_session.begin_handoff(candidate[0].identity,now,generation=token,new_game_window=True):return
        self.target=candidate[0];self.state.target=self.target.identity;self.window_list.blockSignals(True);self.window_list.addItem('本局游戏：'+self.target.title,self.target);self.window_list.setCurrentIndex(self.window_list.count()-1);self.window_list.blockSignals(False);self.last_rect=None;self.was_target_foreground=False;self.invalidate_scene('已接续本局新游戏窗口，选人记录等待局内复核');self.overlay.hide()
    def check_target(self):
        if not self.state.running or not self.capture:return
        self.queue_discovery()
        if not self.target:return
        try:
            self.advance_session_window()
            if not self.target_allowed():raise CapturePaused('等待重新连接已核验的英雄联盟窗口。')
            now=time.monotonic()
            if self.ocr_busy and now-self.ocr_started>8 and not self.ocr_timed_out:
                self.ocr_timed_out=True;self.invalidate_scene('OCR 超时，旧资料已隐藏；等待任务结束或停止并重启助手');self.overlay.hide();self.status.setText(self.state.reason)
            if self.state.confirmed and now-self.last_observation>4:
                self.invalidate_scene('画面观察超过 4 秒未更新，旧资料已隐藏，请重新确认');self.overlay.hide();self.status.setText(self.state.reason)
            rect=self.capture.rect(self.target)
            if self.last_rect and rect!=self.last_rect:
                if (rect.width,rect.height)!=(self.last_rect.width,self.last_rect.height):self.invalidate_scene('目标客户区大小改变，等待新画面重新识别')
                self.overlay.hide() # Pure moves keep fresh identity/offers; only reposition.
            self.last_rect=rect
            if not self.capture.foreground(self.target):
                if self.was_target_foreground:self.invalidate_scene('离开目标窗口，旧资料已隐藏；重新确认后再显示')
                self.was_target_foreground=False;self.overlay.hide();self.status.setText('等待切回游戏；恢复前台后自动继续。');return
            self.was_target_foreground=True
            reference=self.client_strength_reference()
            if reference and not self.capture_pending and not self.ocr_busy:
                self.overlay.set_hero_reference(reference);self.overlay.show_at(rect,self.target)
            elif self.state.confirmed and not self.capture_pending and (not self.ocr_busy or self._restore_while_ocr):self.overlay.show_at(rect,self.target)
            elif self.overlay.reference:self.overlay.hide()
        except CapturePaused as exc:
            if self.state.reason!=str(exc):self.invalidate_scene(str(exc))
            self.overlay.hide();self.status.setText(str(exc))
        except Exception as exc:
            self.invalidate_scene('目标窗口状态异常：'+str(exc));self.overlay.hide();self.status.setText(self.state.reason)
    def schedule_capture(self,delay=None):
        # Schedule from completion, not a fixed grid that can hide a just-shown
        # result on the next timer tick. One acquisition/inference job at a time.
        if self.closed or not self.state.running or self.ocr_busy or self.capture_pending:return
        self.monitor.start((700 if self.state.confirmed or self.client_strength_reference() else 200) if delay is None else delay)
    def capture_tick(self):
        if self.closed or self.ocr_busy or self.capture_pending or not self.state.running:return
        if not self.target or not self.capture.foreground(self.target):self.schedule_capture(400);return
        self.monitor.stop();self.capture_pending=True;self._restore_while_ocr=False;self.overlay.set_rechecking(False);self.overlay.hide();generation=self.state.generation
        self._capture_serial+=1;serial=self._capture_serial
        # Always hide our own HWND before capturing, even if display exclusion succeeds.
        QtCore.QTimer.singleShot(60,lambda:self.capture_hidden(generation,serial))
    def capture_hidden(self,generation,serial=None):
        if serial is not None and serial!=self._capture_serial:return
        if self.closed or not self.state.running or generation!=self.state.generation:
            self.capture_pending=False;self.schedule_capture();return
        if serial is None:self._capture_serial+=1;serial=self._capture_serial
        self.monitor.stop();self.capture_pending=True;self._restore_while_ocr=False
        try:
            if not self.target_allowed():raise CapturePaused('窗口连接正在更新，稍后自动继续。')
            if self.overlay.isVisible() or (self.capture and hasattr(self.capture,'u') and self.capture.u.IsWindowVisible(int(self.overlay.winId()))):raise CaptureUnavailable('自己的叠加尚未隐藏，已跳过本帧以避免识别反馈。')
            roi=tuple(spin.value()/100 for spin in self.roi)
            self.ocr_busy=True;self.ocr_started=time.monotonic();self.ocr_timed_out=False;self.status.setText('正在本机处理所选窗口截图，图片不保存、不上传…')
            from local_ocr import LocalOCR
            if not hasattr(self,'ocr'):self.ocr=LocalOCR()
            matcher=self.hero_matcher if self.hero_auto.isChecked() else None
            session_generation=self.selection_session.generation if self.selection_session else None
            frame_window=self.target;client_phase=self.client_phase()
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
            # Capture and inference share the serialized worker. WGC's native
            # wait must never block the Qt message loop or Stop/Close controls.
            # Snapshot all Qt-derived choices here; no worker reads widgets.
            capture=self.capture;vocabulary=tuple(self.data['augments']);expected_metadata=self.capture_metadata()
            self._capture_cancel=threading.Event();cancelled=self._capture_cancel
            detector=self.selection_detector
            reuse_allowed=self.state.confirmed and self.state.confirmation_mode=='automatic'
            scoped_ocr=self.ocr_reuse.scoped(self.ocr,(frame_window.identity,roi,'game'),allow_reuse=reuse_allowed)
            source_key=(id(self.data),json.dumps(self.data.get('metadata',{}),sort_keys=True,ensure_ascii=False))
            matcher_key=(matcher,matcher.proof_identity() if matcher and hasattr(matcher,'proof_identity') else None)
            def infer():
                from hero_recognition import recognize_frame
                if self._cancel_workers.is_set() or cancelled.is_set():raise CapturePaused('监测已结束。')
                captured_at=time.monotonic();image,rect=capture.capture(frame_window,(0.,0.,1.,1.),cancelled=cancelled,expected_metadata=expected_metadata)
                pixels_at=time.monotonic()
                if self._cancel_workers.is_set() or cancelled.is_set():raise CapturePaused('监测已结束。')
                proof={'_capturedAt':captured_at,'_sessionGeneration':session_generation,'_windowIdentity':frame_window.identity,'_captureRect':rect,'_captureSerial':serial,
                    '_frameScope':(frame_window.identity,expected_metadata,rect,roi,vocabulary,source_key,matcher_key)}
                def emit_phase():
                    with self._worker_lock:
                        if not self.closed and not self._cancel_workers.is_set():self.signals.result.emit('capture-proof',dict(proof),generation)
                def before_match(signature,crop):
                    if self._cancel_workers.is_set() or cancelled.is_set():raise CapturePaused('监测已结束。')
                    proof['_roiDigest']=hashlib.sha256(crop).hexdigest();proof['_hudInputDigest']=signature
                    emit_phase()
                def before_ocr(hero,crop):
                    if self._cancel_workers.is_set() or cancelled.is_set():raise CapturePaused('监测已结束。')
                    proof['_roiDigest']=hashlib.sha256(crop).hexdigest();proof['hero_observation']=hero
                    # Pixel acquisition (including native helper cleanup) is
                    # complete; only the GUI thread may authorize re-display.
                    emit_phase()
                result=detector.recognize(image) if client_phase else recognize_frame(image,roi,scoped_ocr,vocabulary,matcher,before_match=before_match,before_ocr=before_ocr)
                result.update(proof);result['_timings']={'capture_ms':round((pixels_at-captured_at)*1000,1),'inference_ms':round((time.monotonic()-pixels_at)*1000,1)};return result
            self.spawn('selection' if client_phase else 'ocr',infer,generation)
        except CapturePaused as exc:
            self.ocr_busy=False;self.capture_pending=False
            if self.state.reason!=str(exc):self.invalidate_scene(str(exc))
            self.status.setText(str(exc));self.overlay.hide();self.schedule_capture(1000)
        except Exception as exc:
            self.ocr_busy=False;self.capture_pending=False;self.invalidate_scene('截图或识别初始化失败：'+str(exc));self.status.setText(self.state.reason);self.overlay.hide();self.schedule_capture(1000)
    def may_restore_accepted_frame(self,value):
        reference=self._accepted_frame;hero=value.get('hero_observation',{});now=time.monotonic()
        scope=value.get('_frameScope');current_source=(id(self.data),json.dumps(self.data.get('metadata',{}),sort_keys=True,ensure_ascii=False)) if self.data else None
        return bool(reference and reference.get('source_ref') is self.data and self.state.confirmed and self.state.confirmation_mode=='automatic' and self.hero_auto.isChecked()
            and reference['generation']==self.state.generation and reference['hero']==self.state.hero and reference['offered']==self.state.offered
            and isinstance(scope,tuple) and len(scope)==7 and scope==reference['scope'] and scope[3]==tuple(spin.value()/100 for spin in self.roi) and scope[4]==tuple(self.data['augments']) and scope[5]==current_source and scope[6][0] is self.hero_matcher and scope[6][1]==(self.hero_matcher.proof_identity() if self.hero_matcher and hasattr(self.hero_matcher,'proof_identity') else None) and value.get('_roiDigest')==reference['digest']
            and ((hero.get('confident') is True and hero.get('hero')==reference['hero']) if 'hero_observation' in value else bool(reference['hud_digest'] and value.get('_hudInputDigest')==reference['hud_digest']))
            and 0<=now-reference['observed_at']<=4 and reference['observed_at']<value.get('_capturedAt',0)<=now)
    def remember_accepted_frame(self,value):
        hero=value.get('hero_observation',{})
        if self.state.confirmed and self.state.confirmation_mode=='automatic' and self.hero_auto.isChecked() and hero.get('confident') is True and hero.get('hero')==self.state.hero and value.get('_roiDigest') and value.get('_frameScope'):
            self._accepted_frame={'source_ref':self.data,'generation':self.state.generation,'hero':self.state.hero,'offered':self.state.offered,'scope':value['_frameScope'],'digest':value['_roiDigest'],'hud_digest':value.get('_hudInputDigest'),'observed_at':value['_capturedAt']}
        else:self._accepted_frame=None
    def captured_frame_current(self,value):
        # Production workers always attach capture geometry. Validate on the Qt
        # thread again after inference, including advanced manual targets.
        rect=value.get('_captureRect')
        if rect is None:
            # Only explicit self-owned diagnostic launch modes inject synthetic
            # handler results. Ordinary monitoring requires capture provenance.
            if self.smoke_report or self.selection_smoke_input:return True
            self.invalidate_scene('截图来源信息缺失，已丢弃识别结果。');self.overlay.hide();return False
        try:
            if not self.target or tuple(value.get('_windowIdentity',()))!=self.target.identity or not self.target_allowed() or not self.capture.foreground(self.target) or self.capture.rect(self.target)!=rect:
                raise CapturePaused('识别期间窗口身份、位置或大小变化，已丢弃旧画面。')
            self.last_rect=rect
            return True
        except (CapturePaused,CaptureUnavailable) as exc:
            self.invalidate_scene(str(exc));self.overlay.hide();self.status.setText(str(exc));return False
    def confirm(self, *, automatic=False, captured_at=None):
        try:
            self.state.confirm([edit.text() for edit in self.inputs],self.data['augments'],automatic=automatic);self.last_observation=captured_at if captured_at is not None else time.monotonic()
            metadata=self.data.get('metadata',{})
            source_version=f"数据包 {metadata.get('wikiDataVersion') or '未知'} / 游戏资料 {metadata.get('gamePatch') or '未知'}"
            self.overlay.set_cards(self.state.hero,display_cards(self.data,self.state.hero,self.state.offered),metadata.get('sourceDataDate') or '未知',source_version,('来自本局选人 · HUD未复核' if self.hero_origin=='client-provisional' else '本局选人 + HUD复核' if self.hero_origin=='client-verified' else '英雄/候选连续高置信自动识别' if self.hero_auto.isChecked() else '英雄人工纠正 · 候选自动识别') if automatic else '人工确认')
            self.last_candidates={'scope':self.history_scope(),'hero':self.state.hero,'cards':display_cards(self.data,self.state.hero,self.state.offered),'recorded_at':self.last_observation,'source_date':metadata.get('sourceDataDate') or '未知','source_version':source_version,'confirmation':'候选自动确认 · 按截图观察时间' if automatic else '候选人工确认 · 按确认时间'}
            self.refresh_card_details();self.status.setText(self.state.reason+'；切回目标窗口后显示。');self.check_target()
        except (ValueError,KeyError) as exc:self.status.setText(str(exc))
    def toggle_clickthrough(self):
        try:self.overlay.set_click_through(not self.overlay.click_through)
        except CaptureUnavailable as exc:
            self.stop_monitor();self.overlay.hide();self.status.setText(str(exc));return
        self.toggle_button.setChecked(self.overlay.click_through);self.check_target()
    @QtCore.Slot(str,object,int)
    def task_result(self,kind,value,generation):
        if self.closed:return
        try:
            if kind=='windows':
                self.apply_discovery(value,generation);return
            if kind=='load':
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
                vocabulary=sorted(self.data.get('augments',{}))
                for edit in self.inputs:
                    completer=QtWidgets.QCompleter(vocabulary,edit);completer.setCaseSensitivity(QtCore.Qt.CaseSensitivity.CaseInsensitive);edit.setCompleter(completer)
                self.start_button.setEnabled(bool(vocabulary and self.capture));self.status.setText('点击开始监测后自动识别本人英雄与三个候选；不确定时才人工纠正。' if self.capture else '当前系统不支持窗口采集；Windows 10/11 可用。')
                if not meta.get('isDemo'):
                    from hero_portraits import load_portraits
                    self.spawn('portraits',lambda:load_portraits(self.state_dir/'hero-portraits',allow_download=self.enable_updates,cancelled=self._cancel_workers))
                else:self.hero_status.setText('虚构演示没有真实头像；人工模式或合成识别测试可用。')
                QtCore.QTimer.singleShot(0,self.ready)
                if self.enable_updates and not self.smoke_report:self.spawn('update',lambda:__import__('updates').check_for_update(self.current_version))
                else:self.update_status.setText('本次启动已显式禁用软件更新检查。')
            elif kind=='capture-proof':
                if not self.state.running or generation!=self.state.generation or value.get('_captureSerial')!=self._capture_serial:return
                self.capture_pending=False;self._restore_while_ocr=False
                if not self.captured_frame_current(value):return
                if not self.overlay.isVisible() and hasattr(self.capture,'validate_compositor'):
                    try:self.capture.validate_compositor(self.target,value['_captureRect'])
                    except (CapturePaused,CaptureUnavailable) as exc:
                        self.invalidate_scene(str(exc));self.overlay.hide();return
                self._restore_while_ocr=self.may_restore_accepted_frame(value)
                self.overlay.set_rechecking(self._restore_while_ocr)
                if not self._restore_while_ocr:self.overlay.hide()
                self.check_target()
            elif kind=='selection':
                self.ocr_busy=False;self.capture_pending=False;self._restore_while_ocr=False;self.overlay.set_rechecking(False)
                if not self.state.running or generation!=self.state.generation or not self.selection_session:return
                if not self.captured_frame_current(value):return
                if not self.target_allowed() or tuple(value.get('_windowIdentity',()))!=self.target.identity:
                    self.selection_session.clear('Client permission changed during inference');self.invalidate_scene('客户端身份变化，旧选人资料已清空');return
                now=time.monotonic();stable=self.selection_session.observe_client(value,self.target.identity,value.get('_capturedAt'),now,generation=value.get('_sessionGeneration'))
                self.overlay.hide();self.state.confirmed=False;self.state.offered=();self.refresh_card_details()
                hero=next((name for name,row in self.data['heroes'].items() if self.selection_session.assigned and str(row.get('championId'))==self.selection_session.assigned),'')
                if self.hero_auto.isChecked():
                    self.state.hero=hero;self.hero_box.blockSignals(True);self.hero_box.setCurrentText(hero);self.hero_box.blockSignals(False)
                self.hero_status.setText(('当前分配：'+hero+'；仍可交换，切入本局游戏后复核') if stable and hero else '选人文字尚不确定：'+value.get('reason',''))
                self.status.setText(self.hero_status.text());self.check_target()
            elif kind=='ocr':
                self.ocr_busy=False;self.capture_pending=False;self._restore_while_ocr=False;self.overlay.set_rechecking(False)
                if not self.state.running or generation!=self.state.generation:return
                if not self.captured_frame_current(value):return
                if (self.window_policy or self.automatic_policy) and (not self.target_allowed() or tuple(value.get('_windowIdentity',()))!=self.target.identity):
                    if self.selection_session:self.selection_session.clear('Game permission changed during inference')
                    self.invalidate_scene('游戏窗口身份变化，旧资料已清空');self.overlay.hide();return
                captured_at=value.get('_capturedAt',0)
                if not isinstance(captured_at,(int,float)) or not math.isfinite(captured_at) or time.monotonic()-captured_at>4 or captured_at>time.monotonic():
                    self.invalidate_scene('识别完成时截图已过期，旧资料隐藏；等待新截图');self.overlay.hide();self.status.setText(self.state.reason);return
                auto_candidates=value.get('automatic_candidates',[])
                candidates=auto_candidates if len(auto_candidates)==3 else value.get('candidates',[])
                names=[item['name'] for item in candidates]
                hero_stable=True
                if self.hero_auto.isChecked():
                    observation=value.get('hero_observation',{});recognized=observation.get('hero') if observation.get('confident') is True else '';self.hero_origin='hud'
                    if self.selection_session and self.target.identity==self.selection_session.game:
                        game_scene=bool(observation.get('confident') is True or automatic_candidates(auto_candidates,value.get('image_size')) )
                        if game_scene:
                            self.selection_session.observe_game(self.target.identity,captured_at,time.monotonic(),generation=value.get('_sessionGeneration'),game_scene=True,hud_hero=observation.get('championId') if observation.get('confident') is True else None)
                        elif self.selection_session.stage in ('game-provisional','game-verified'):
                            self.selection_session.observe_game(self.target.identity,captured_at,time.monotonic(),generation=value.get('_sessionGeneration'),game_scene=False)
                        carried=self.selection_session.visible_identity(allow_provisional=True)
                        if carried:
                            recognized=next((name for name,row in self.data['heroes'].items() if str(row.get('championId'))==carried['championId']),'');self.hero_origin='client-verified' if carried['verified'] else 'client-provisional'
                            observation={**observation,'reason':'来自本局选人；'+('本人HUD已复核' if carried['verified'] else 'HUD尚未复核')}
                    if recognized not in self.data.get('heroes',{}):recognized=''
                    hero_stable=self.state.observe_hero(recognized)
                    self.hero_box.blockSignals(True);self.hero_box.setCurrentText(self.state.hero);self.hero_box.blockSignals(False)
                    self.hero_status.setText((self.state.hero+' · '+observation.get('reason','')) if hero_stable else observation.get('reason','本人头像尚不确定')+'；等待新画面或人工纠正')
                safe_candidates=automatic_candidates(auto_candidates,value.get('image_size'))
                if value.get('ocr_reused') is True and not self.state.confirmed:
                    self.ocr_reuse.clear();self.refresh_card_details();self.overlay.hide();return
                if self.state.confirmed and self.state.confirmation_mode=='automatic' and not safe_candidates:self.state.invalidate('候选置信度或三卡布局不足，旧资料已隐藏')
                stable=self.state.observe(names,generation=self.state.generation)
                automatic_stable=(self.state.confirmed and self.state.confirmation_mode=='automatic') if value.get('ocr_reused') is True else self.state.observe_automatic_candidates(names,safe_candidates)
                self.last_observation=captured_at
                if not self.state.confirmed:self.refresh_card_details();self.overlay.hide()
                if stable and not self.state.confirmed and not self.manual_editing:
                    for edit,name in zip(self.inputs,names):edit.setText(name)
                uncertainty=any(item.get('match_method')!='exact' or item.get('ocr_confidence',0)<.85 for item in candidates)
                self.status.setText(self.state.reason+('；存在模糊/低置信识别，务必人工核对。' if uncertainty else ''))
                if stable and automatic_stable and hero_stable and bool(self.state.hero) and safe_candidates and not self.manual_editing and not self.state.confirmed:
                    self.confirm(automatic=True,captured_at=captured_at)
                self.remember_accepted_frame(value)
                self.check_target()
            elif kind=='portraits':
                portraits,status=value
                self.portrait_diagnostics=status.get('cacheDiagnostics');self.cache_diagnostic_button.setVisible(isinstance(self.portrait_diagnostics,dict))
                if portraits:
                    from hero_recognition import PortraitMatcher
                    self.hero_matcher=PortraitMatcher(portraits,self.data['heroes'])
                self.hero_status.setText(status.get('message','头像模板状态未知'))
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
        if self.closed:return
        if kind=='windows':
            if generation==self.discovery_scope:
                self.discovery_busy=False;self.window_status.setText('窗口检测暂未完成，稍后自动重试。')
            return
        if kind in ('ocr','selection'):
            self.ocr_busy=False;self.capture_pending=False;self._restore_while_ocr=False;self.overlay.set_rechecking(False)
            if kind=='selection' and self.selection_session:self.selection_session.clear('Client recognition failure')
            if generation==self.state.generation:self.invalidate_scene('识别失败：'+error);self.overlay.hide();self.status.setText(self.state.reason)
            self.schedule_capture(1000)
        elif kind=='portraits':self.hero_status.setText('自动英雄模板加载失败：'+error+'；可人工纠正。')
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
            self.stop_monitor();self.start_button.setEnabled(False);self.overlay.hide()
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
        self._capture_cancel.set();self.ocr_reuse.clear()
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
        event.accept()


def run_native(startup_loader,*,state_dir,current_executable,current_version,frozen,on_ready=None,smoke_report=None,smoke_screenshot=None,enable_updates=True,selection_smoke_input=None):
    app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([]);app.setApplicationName(APP_NAME);app.setQuitOnLastWindowClosed(True)
    control=ControlWindow(startup_loader,state_dir=state_dir,current_executable=current_executable,current_version=current_version,frozen=frozen,on_ready=on_ready,smoke_report=smoke_report,smoke_screenshot=smoke_screenshot,enable_updates=enable_updates,selection_smoke_input=selection_smoke_input)
    app._vga_control=control
    return app.exec()

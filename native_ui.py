"""Native QtWidgets controls and a nonactivating Windows pixel-only overlay.

No browser engine. Screenshot buffers stay in memory. Session handoff queries
only OS process path/creation metadata, never game process memory.
"""
from __future__ import annotations
import ctypes
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
from screen_capture import Win32Capture,CaptureUnavailable,CapturePaused

ROOT=Path(__file__).resolve().parent
APP_NAME='VGA乱斗助手'
STYLE='''QWidget{background:#121e24;color:#ecf5ef;font-family:"Microsoft YaHei","Noto Sans CJK SC";font-size:13px} QLineEdit,QComboBox,QSpinBox{background:#1d3037;border:1px solid #45616b;border-radius:5px;padding:6px} QPushButton{background:#264b50;border:1px solid #557d75;border-radius:5px;padding:8px} QPushButton:disabled{color:#738580;background:#253335} QLabel#muted{color:#adbbb5;font-size:11px} QGroupBox{border:1px solid #3b555b;border-radius:7px;margin-top:13px;padding-top:13px} QGroupBox::title{subcontrol-origin:margin;left:12px}'''

def label(text='',muted=False):
    widget=QtWidgets.QLabel(text);widget.setTextFormat(QtCore.Qt.TextFormat.PlainText);widget.setWordWrap(True)
    if muted:widget.setObjectName('muted')
    return widget

class TaskSignals(QtCore.QObject):
    result=QtCore.Signal(str,object,int)
    error=QtCore.Signal(str,str,int)

class Overlay(QtWidgets.QWidget):
    def __init__(self,capture=None):
        super().__init__(None,QtCore.Qt.WindowType.Tool|QtCore.Qt.WindowType.FramelessWindowHint|QtCore.Qt.WindowType.WindowStaysOnTopHint|QtCore.Qt.WindowType.WindowDoesNotAcceptFocus)
        self.capture=capture;self.click_through=True;self.cards=[];self._layout_revision=0;self._placed_key=None;self._detail_labels=[];self._compact=False
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setWindowTitle(APP_NAME+' · 资料叠加');self.setStyleSheet(STYLE+'\nOverlay{background:transparent;}')
        self.setWindowFlag(QtCore.Qt.WindowType.WindowTransparentForInput,True)
        layout=QtWidgets.QVBoxLayout(self);layout.setContentsMargins(0,0,0,0)
        self.panel=QtWidgets.QFrame();self.panel.setObjectName('overlay-panel');self.panel.setStyleSheet('#overlay-panel{background:rgba(12,24,29,235);border:1px solid #b4c97b;border-radius:10px} #overlay-panel QLabel{background:transparent;border:0}')
        layout.addWidget(self.panel);inner=QtWidgets.QVBoxLayout(self.panel)
        self.heading=label('');inner.addWidget(self.heading);self.row=QtWidgets.QHBoxLayout();inner.addLayout(self.row)
        self.footer=label('仅窗口像素 · Ctrl+Alt+O 切换鼠标穿透 · 不是 Riot 评级/批准',True);inner.addWidget(self.footer)
        self.resize(940,230)
    def set_cards(self,hero,cards,source_date='未知',source_version='未知',confirmation='人工确认'):
        self.cards=cards;self.tier_labels=[];self._detail_labels=[];self._layout_revision+=1;self._placed_key=None
        while self.row.count():
            item=self.row.takeAt(0);widget=item.widget()
            if widget:widget.hide();widget.deleteLater()
        self._full_heading=f'{APP_NAME}  |  {hero}  |  {confirmation}  |  来源日期 {source_date}  |  {source_version}'
        self._compact_heading=f'{hero} | {confirmation}\n来源日期 {source_date} | {source_version}'
        self.heading.setText(self._full_heading)
        for card in cards:
            frame=QtWidgets.QFrame();frame.setObjectName('overlay-card');frame.setStyleSheet('#overlay-card{background:#1b3036;border:1px solid #49646a;border-radius:7px}');box=QtWidgets.QVBoxLayout(frame)
            box.addWidget(label(f"选项 {card['slot']} · {card['name']}"))
            tier_label=label(f"{card.get('sourceTierLabel','虎牙公开源评级')}：{card.get('sourceTier') or '暂无评级'}",True);tier_label.setObjectName('source-tier-label');self.tier_labels.append(tier_label);box.addWidget(tier_label)
            desc=card['description'];detail=label(desc[:140]+('…' if len(desc)>140 else ''),True);box.addWidget(detail);self._detail_labels.append(detail)
            if card['notes']:
                note=label('条件/提醒：'+'；'.join(card['notes'])[:160],True);box.addWidget(note);self._detail_labels.append(note)
            self.row.addWidget(frame,1)
        self.adjustSize();self.resize(max(750,min(self.width(),1020)),max(200,self.height()))
    def configure(self):
        if self.capture:self.capture.configure_overlay(int(self.winId()),self.click_through)
    def set_click_through(self,value):
        self.click_through=bool(value);self.hide();self._placed_key=None;self._layout_revision+=1
        self.setWindowFlag(QtCore.Qt.WindowType.WindowTransparentForInput,self.click_through)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.configure()
    def _set_compact(self,compact):
        self._compact=compact
        self.heading.setText(self._compact_heading if compact else self._full_heading)
        for widget in self._detail_labels:widget.setVisible(not compact)
        self.footer.setText(('紧凑：说明隐藏 · ' if compact else '')+'穿透'+('开' if self.click_through else '关')+' Ctrl+Alt+O · 非 Riot 评级/批准')
        for layout in reversed(self.findChildren(QtWidgets.QLayout)):layout.invalidate();layout.activate()
        self.layout().invalidate();self.layout().activate()
    def _fit_layout(self,rect,dpr):
        from overlay_geometry import layout_budget,placement
        budget=layout_budget(rect,dpr)
        for compact in (False,True):
            self._set_compact(compact)
            width=budget.logical_width
            self.resize(width,max(100,min(self.height(),budget.logical_height)))
            self.layout().activate()
            hint=self.layout().totalHeightForWidth(width)
            height=max(self.minimumSizeHint().height(),hint if hint>=0 else self.sizeHint().height(),100)
            if self.minimumSizeHint().width()<=width and height<=budget.logical_height:
                self.resize(width,height);self.layout().activate()
                return placement(rect,budget,height)
        raise CaptureUnavailable(f'客户区 {rect.width}×{rect.height} 像素 / 叠加缩放 {dpr:g} 倍：紧凑资料卡仍放不下，已隐藏。')
    def _verify_rect(self,rect):
        actual=W.RECT()
        if not self.capture.u.GetWindowRect(int(self.winId()),ctypes.byref(actual)) or actual.right<=actual.left or actual.bottom<=actual.top or actual.left<rect.x or actual.top<rect.y or actual.right>rect.x+rect.width or actual.bottom>rect.y+rect.height:
            raise CaptureUnavailable(f'叠加实际范围超出客户区 {rect.width}×{rect.height}，已隐藏。')
    def show_at(self,rect,target):
        if not self.cards:return
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
        super().__init__();self.state=RecognitionState();self.data=None;self.target=None;self.capture=None;self.last_rect=None;self.was_target_foreground=False;self.ocr_busy=False;self.manual_editing=False;self.capture_pending=False;self.last_observation=0.;self.ocr_started=0.;self.ocr_timed_out=False;self.closed=False;self.on_ready=on_ready
        self._worker_lock=threading.Lock();self._cancel_workers=threading.Event();self._workers=set()
        self.enable_updates=enable_updates;self.hero_matcher=None;self.selection_session=None;self.window_policy=None;self.client_target=None;self.selection_detector=None;self.hero_origin='hud';self.selection_smoke_input=selection_smoke_input;self.last_window_discovery=0.;self.automatic_policy=None;self.discovery_busy=False;self.discovery_scope=0
        self.current_version=current_version;self.current_executable=Path(current_executable);self.state_dir=Path(state_dir);self.frozen=frozen;self.release=None;self.smoke_report=smoke_report;self.smoke_screenshot=smoke_screenshot;self.hotkey_registered=False
        self.signals=TaskSignals(self);self.signals.result.connect(self.task_result);self.signals.error.connect(self.task_error)
        self.setWindowTitle(APP_NAME+' · 原生控制台');self.setWindowIcon(QtGui.QIcon(str(ROOT/'assets/branding/vga.ico')));self.setStyleSheet(STYLE);self.resize(790,760)
        outer=QtWidgets.QVBoxLayout(self);outer.setContentsMargins(8,8,8,8);scroll=QtWidgets.QScrollArea();scroll.setWidgetResizable(True);container=QtWidgets.QWidget();scroll.setWidget(container);outer.addWidget(scroll)
        layout=QtWidgets.QVBoxLayout(container);layout.addWidget(label(APP_NAME+'  ·  原生窗口资料助手'))
        layout.addWidget(label('自动模式只看已核验英雄联盟窗口的可见像素；不读取游戏内存、不注入、不装输入钩子。初版支持窗口/无边框模式；实际 LoL 与 Vanguard 兼容性尚未验证。',True))
        self.source=label('正在检查公开数据，首次启动可能需要数十秒…',True);layout.addWidget(self.source)
        group=QtWidgets.QGroupBox('1  窗口与本人英雄自动识别');form=QtWidgets.QFormLayout(group);layout.addWidget(group)
        self.window_list=QtWidgets.QComboBox();self.refresh=QtWidgets.QPushButton('重新检测');row=QtWidgets.QHBoxLayout();row.addWidget(self.window_list,1);row.addWidget(self.refresh);form.addRow('窗口连接',row);self.window_status=label('默认自动连接，无需选择窗口。',True);form.addRow(self.window_status);self.trust_button=QtWidgets.QPushButton('确认自己的游戏安装目录…');self.trust_button.hide();self.trust_button.clicked.connect(self.confirm_game_installation);form.addRow(self.trust_button);self.unverified_candidate=None
        self.hero_auto=QtWidgets.QCheckBox('自动识别本人英雄（选人文字 + 局内 HUD，无需预选）');self.hero_auto.setChecked(True);form.addRow(self.hero_auto)
        self.hero_status=label('本人头像模板准备中…',True);form.addRow(self.hero_status)
        self.portrait_diagnostics=None;self.cache_diagnostic_button=QtWidgets.QPushButton('头像缓存诊断');self.cache_diagnostic_button.hide();self.cache_diagnostic_button.clicked.connect(self.show_cache_diagnostics);form.addRow(self.cache_diagnostic_button)
        self.client_follow=QtWidgets.QCheckBox('自动接续同一安装目录的客户端与游戏窗口');self.client_follow.setChecked(True);form.addRow(self.client_follow)
        self.hero_box=QtWidgets.QComboBox();self.hero_box.setEditable(True);self.hero_box.setInsertPolicy(QtWidgets.QComboBox.InsertPolicy.NoInsert);self.hero_box.setEnabled(False);form.addRow('英雄 / 不确定时人工纠正',self.hero_box)
        layout.addWidget(label('点击开始后自动寻找已核验的英雄联盟窗口，并最小化此控制台以免遮挡游戏。游戏晚启动、重开或窗口重建会自动重连；切出或被遮挡时等待，截图不保存。',True))
        roi_group=QtWidgets.QGroupBox('2  截图范围（所选窗口内的百分比，可按游戏界面调整）');roi_row=QtWidgets.QHBoxLayout(roi_group);layout.addWidget(roi_group);self.roi=[]
        for name,value in [('左',15),('上',25),('宽',70),('高',35)]:
            roi_row.addWidget(label(name));spin=QtWidgets.QSpinBox();spin.setRange(0,100);spin.setValue(value);spin.setSuffix('%');spin.valueChanged.connect(self.roi_changed);self.roi.append(spin);roi_row.addWidget(spin)
        self.start_button=QtWidgets.QPushButton('开始本局监测');self.stop_button=QtWidgets.QPushButton('停止');self.toggle_button=QtWidgets.QPushButton('鼠标穿透：开（Ctrl+Alt+O）');buttons=QtWidgets.QHBoxLayout();buttons.addWidget(self.start_button);buttons.addWidget(self.stop_button);buttons.addWidget(self.toggle_button);layout.addLayout(buttons)
        group=QtWidgets.QGroupBox('3  三个候选（高置信稳定后自动显示；不确定时核对）');form=QtWidgets.QFormLayout(group);layout.addWidget(group);self.inputs=[]
        for i in range(3):
            edit=QtWidgets.QLineEdit();edit.textEdited.connect(self.edit_changed);self.inputs.append(edit);form.addRow(['左侧','中间','右侧'][i],edit)
        self.confirm_button=QtWidgets.QPushButton('人工纠正并确认三项');self.confirm_button.clicked.connect(self.confirm);form.addRow(self.confirm_button)
        self.status=label('准备中…');layout.addWidget(self.status)
        layout.addWidget(label('叠加按三张牌原位置显示名称、效果及当前英雄的虎牙公开源评级（T1–T4）；缺失显示暂无评级。不展示胜率、不自行换算等级或自动排序，也不输出唯一最佳选项。公开源评级不等于云端实时结果，也不代表 Riot 批准。',True))
        self.update_status=label('软件更新待检查。',True);layout.addWidget(self.update_status);self.update_button=QtWidgets.QPushButton('查看并安装软件更新');self.update_button.hide();layout.addWidget(self.update_button)
        self.refresh.clicked.connect(self.refresh_windows);self.window_list.currentIndexChanged.connect(self.target_changed);self.hero_box.currentTextChanged.connect(self.hero_changed);self.hero_auto.toggled.connect(self.hero_mode_changed);self.client_follow.toggled.connect(self.follow_scope_changed);self.start_button.clicked.connect(self.start_monitor);self.stop_button.clicked.connect(self.stop_monitor);self.toggle_button.clicked.connect(self.toggle_clickthrough);self.update_button.clicked.connect(self.install_update)
        try:self.capture=Win32Capture()
        except CaptureUnavailable as exc:self.status.setText(str(exc))
        self.overlay=Overlay(self.capture);self.overlay.winId();self.overlay.configure()
        self.monitor=QtCore.QTimer(self);self.monitor.setInterval(1300);self.monitor.timeout.connect(self.capture_tick)
        self.watchdog=QtCore.QTimer(self);self.watchdog.setInterval(200);self.watchdog.timeout.connect(self.check_target);self.watchdog.start()
        self.start_button.setEnabled(False);self.confirm_button.setEnabled(False);self.stop_button.setEnabled(False)
        self.show();self.register_hotkey();self.refresh_windows();self.spawn('load',startup_loader)
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
            if not self.hotkey_registered:self.toggle_button.setText('鼠标穿透：开（快捷键占用，请用按钮）')
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
        return not self.window_policy or self.window_policy.permits(self.target)
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
        self.hero_box.setEnabled(not automatic);self.state.clear_hero();self.overlay.hide();self.manual_editing=False
        self.hero_box.blockSignals(True);self.hero_box.setCurrentText('');self.hero_box.blockSignals(False)
        self.hero_status.setText('等待本人 HUD 头像，连续两帧高置信后自动使用。' if automatic else '人工纠正模式：请选择已确认的本人英雄。')
    def hero_changed(self,text):
        if text and self.hero_auto.isChecked():
            self.hero_auto.blockSignals(True);self.hero_auto.setChecked(False);self.hero_auto.blockSignals(False);self.hero_box.setEnabled(True)
        hero=text if self.data and text in self.data.get('heroes',{}) else getattr(self,'hero_aliases',{}).get(text,'')
        self.hero_origin='manual';self.state.select_hero(hero);self.overlay.hide();self.status.setText(self.state.reason)
    def invalidate_scene(self,reason):
        if self.hero_auto.isChecked():
            self.state.clear_hero();self.hero_box.blockSignals(True);self.hero_box.setCurrentText('');self.hero_box.blockSignals(False)
        self.state.invalidate(reason)
    def roi_changed(self,*_):
        self.invalidate_scene('截图范围改变，请重新识别确认');self.overlay.hide()
    def edit_changed(self,*_):
        self.manual_editing=True;self.state.invalidate('候选已修改，请重新确认',clear_observed=False);self.overlay.hide()
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
            if self.client_follow.isChecked() and self.target.class_name in ('Chrome_WidgetWin_1','CEFCLIENT'):
                try:
                    from session_windows import SessionWindowPolicy
                    from selection_session import SelectionSession
                    self.window_policy=SessionWindowPolicy(self.target);self.client_target=self.target;self.selection_session=SelectionSession();self.selection_session.start(self.target.identity)
                except (OSError,ValueError) as exc:return self.status.setText('无法核验客户端所属安装目录，本局监测未开始：'+str(exc))
            self.state.start(self.target.identity)
        if self.hero_auto.isChecked():self.state.clear_hero()
        self.monitor.start();self.overlay.hide();self.stop_button.setEnabled(True);self.confirm_button.setEnabled(True)
        self.status.setText('已开始自动监测。控制台将最小化，恢复它可随时停止。')
        self.queue_discovery(force=True)
        # On the GUI thread, minimize only after Start succeeds. Never hide a
        # different app and never restore/activate the game on the user's behalf.
        if not self.smoke_report and not self.selection_smoke_input:self.showMinimized()
    def stop_monitor(self):
        self.discovery_scope+=1;self.discovery_busy=False
        if self.automatic_policy:self.automatic_policy.stop()
        self.automatic_policy=None;self.unverified_candidate=None;self.trust_button.hide()
        if self.selection_session:self.selection_session.stop()
        if self.window_policy:self.window_policy.stop()
        self.selection_session=None;self.window_policy=None;self.client_target=None;self.hero_origin='hud'
        self.monitor.stop();self.state.stop();
        if self.hero_auto.isChecked():self.state.clear_hero()
        self.overlay.hide();self.stop_button.setEnabled(False);self.confirm_button.setEnabled(False)
        self.status.setText(self.state.reason)
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
            if self.state.confirmed and not self.capture_pending:self.overlay.show_at(rect,self.target)
        except CapturePaused as exc:
            if self.state.reason!=str(exc):self.invalidate_scene(str(exc))
            self.overlay.hide();self.status.setText(str(exc))
        except Exception as exc:
            self.invalidate_scene('目标窗口状态异常：'+str(exc));self.overlay.hide();self.status.setText(self.state.reason)
    def capture_tick(self):
        if self.closed or self.ocr_busy or self.capture_pending or not self.state.running or not self.target:return
        if not self.capture.foreground(self.target):return
        self.capture_pending=True;self.overlay.hide();generation=self.state.generation
        # Always hide our own HWND before capturing, even if display exclusion succeeds.
        QtCore.QTimer.singleShot(60,lambda:self.capture_hidden(generation))
    def capture_hidden(self,generation):
        self.capture_pending=False
        if self.closed or not self.state.running or generation!=self.state.generation:return
        try:
            if not self.target_allowed():raise CapturePaused('窗口连接正在更新，稍后自动继续。')
            if self.overlay.isVisible() or (self.capture and hasattr(self.capture,'u') and self.capture.u.IsWindowVisible(int(self.overlay.winId()))):raise CaptureUnavailable('自己的叠加尚未隐藏，已跳过本帧以避免识别反馈。')
            roi=tuple(spin.value()/100 for spin in self.roi);captured_at=time.monotonic();image,rect=self.capture.capture(self.target,(0.,0.,1.,1.))
            if not self.target_allowed():raise CapturePaused('截图期间窗口身份变化，已丢弃本帧。')
            self.last_rect=rect;self.ocr_busy=True;self.ocr_started=time.monotonic();self.ocr_timed_out=False;self.status.setText('正在本机处理所选窗口截图，图片不保存、不上传…')
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
            def infer():
                from hero_recognition import recognize_frame
                result=self.selection_detector.recognize(image) if client_phase else recognize_frame(image,roi,self.ocr,self.data['augments'],matcher)
                result['_capturedAt']=captured_at;result['_sessionGeneration']=session_generation;result['_windowIdentity']=frame_window.identity;return result
            self.spawn('selection' if client_phase else 'ocr',infer,generation)
        except CapturePaused as exc:
            self.ocr_busy=False
            if self.state.reason!=str(exc):self.invalidate_scene(str(exc))
            self.status.setText(str(exc));self.overlay.hide()
        except Exception as exc:
            self.ocr_busy=False;self.invalidate_scene('截图或识别初始化失败：'+str(exc));self.status.setText(self.state.reason);self.overlay.hide()
    def confirm(self, *, automatic=False, captured_at=None):
        try:
            self.state.confirm([edit.text() for edit in self.inputs],self.data['augments'],automatic=automatic);self.last_observation=captured_at if captured_at is not None else time.monotonic()
            metadata=self.data.get('metadata',{})
            source_version=f"数据包 {metadata.get('wikiDataVersion') or '未知'} / 游戏资料 {metadata.get('gamePatch') or '未知'}"
            self.overlay.set_cards(self.state.hero,display_cards(self.data,self.state.hero,self.state.offered),metadata.get('sourceDataDate') or '未知',source_version,('来自本局选人 · HUD未复核' if self.hero_origin=='client-provisional' else '本局选人 + HUD复核' if self.hero_origin=='client-verified' else '英雄/候选连续高置信自动识别' if self.hero_auto.isChecked() else '英雄人工纠正 · 候选自动识别') if automatic else '人工确认')
            self.status.setText(self.state.reason+'；切回目标窗口后显示。');self.check_target()
        except (ValueError,KeyError) as exc:self.status.setText(str(exc))
    def toggle_clickthrough(self):
        try:self.overlay.set_click_through(not self.overlay.click_through)
        except CaptureUnavailable as exc:
            self.stop_monitor();self.overlay.hide();self.status.setText(str(exc));return
        self.toggle_button.setText('鼠标穿透：'+('开' if self.overlay.click_through else '关')+'（Ctrl+Alt+O）');self.check_target()
    @QtCore.Slot(str,object,int)
    def task_result(self,kind,value,generation):
        if self.closed:return
        if kind=='windows':
            self.apply_discovery(value,generation);return
        if kind=='load':
            self.data=value['data'];meta=self.data.get('metadata',{});status=value.get('status',{})
            self.source.setText(('虚构演示，不能用于对局。 ' if meta.get('isDemo') else '')+f"软件 {self.current_version} · 来源日期 {meta.get('sourceDataDate','未知')} · 游戏资料版本 {meta.get('gamePatch','未知')} · {status.get('message','资料已加载')} 获取成功不代表统计内容最新。")
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
        elif kind=='selection':
            self.ocr_busy=False
            if not self.state.running or generation!=self.state.generation or not self.selection_session:return
            if not self.target_allowed() or tuple(value.get('_windowIdentity',()))!=self.target.identity:
                self.selection_session.clear('Client permission changed during inference');self.invalidate_scene('客户端身份变化，旧选人资料已清空');return
            now=time.monotonic();stable=self.selection_session.observe_client(value,self.target.identity,value.get('_capturedAt'),now,generation=value.get('_sessionGeneration'))
            self.overlay.hide();self.state.confirmed=False;self.state.offered=()
            hero=next((name for name,row in self.data['heroes'].items() if self.selection_session.assigned and str(row.get('championId'))==self.selection_session.assigned),'')
            if self.hero_auto.isChecked():
                self.state.hero=hero;self.hero_box.blockSignals(True);self.hero_box.setCurrentText(hero);self.hero_box.blockSignals(False)
            self.hero_status.setText(('当前分配：'+hero+'；仍可交换，切入本局游戏后复核') if stable and hero else '选人文字尚不确定：'+value.get('reason',''))
            self.status.setText(self.hero_status.text());self.check_target()
        elif kind=='ocr':
            self.ocr_busy=False
            if not self.state.running or generation!=self.state.generation:return
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
            if self.state.confirmed and self.state.confirmation_mode=='automatic' and not safe_candidates:self.state.invalidate('候选置信度或三卡布局不足，旧资料已隐藏')
            stable=self.state.observe(names,generation=self.state.generation);automatic_stable=self.state.observe_automatic_candidates(names,safe_candidates);self.last_observation=captured_at
            if not self.state.confirmed:self.overlay.hide()
            if stable and not self.state.confirmed and not self.manual_editing:
                for edit,name in zip(self.inputs,names):edit.setText(name)
            uncertainty=any(item.get('match_method')!='exact' or item.get('ocr_confidence',0)<.85 for item in candidates)
            self.status.setText(self.state.reason+('；存在模糊/低置信识别，务必人工核对。' if uncertainty else ''))
            if stable and automatic_stable and hero_stable and bool(self.state.hero) and safe_candidates and not self.manual_editing and not self.state.confirmed:
                self.confirm(automatic=True,captured_at=captured_at)
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
    @QtCore.Slot(str,str,int)
    def task_error(self,kind,error,generation):
        if self.closed:return
        if kind=='windows':
            if generation==self.discovery_scope:
                self.discovery_busy=False;self.window_status.setText('窗口检测暂未完成，稍后自动重试。')
            return
        if kind in ('ocr','selection'):
            self.ocr_busy=False
            if kind=='selection' and self.selection_session:self.selection_session.clear('Client recognition failure')
            if generation==self.state.generation:self.invalidate_scene('识别失败：'+error);self.overlay.hide();self.status.setText(self.state.reason)
        elif kind=='portraits':self.hero_status.setText('自动英雄模板加载失败：'+error+'；可人工纠正。')
        elif kind=='load':self.source.setText('资料加载失败：'+error);self.status.setText('未加载真实资料，不使用演示数据代替。')
        elif kind=='install':self.update_button.setEnabled(True);self.update_status.setText('更新失败，原程序不变：'+error)
        else:self.update_status.setText('更新检查失败：'+error)
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

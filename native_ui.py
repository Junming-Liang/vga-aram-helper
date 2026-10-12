"""Native QtWidgets controls and a nonactivating Windows pixel-only overlay.

No browser engine. Screenshot buffers stay in memory; no game process is opened.
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
from screen_capture import Win32Capture,CaptureUnavailable

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
        self.capture=capture;self.click_through=True;self.cards=[]
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
        self.cards=cards;self.tier_labels=[]
        while self.row.count():
            item=self.row.takeAt(0);widget=item.widget()
            if widget:widget.hide();widget.deleteLater()
        self.heading.setText(f'{APP_NAME}  |  {hero}  |  {confirmation}  |  来源日期 {source_date}  |  {source_version}')
        for card in cards:
            frame=QtWidgets.QFrame();frame.setObjectName('overlay-card');frame.setStyleSheet('#overlay-card{background:#1b3036;border:1px solid #49646a;border-radius:7px}');box=QtWidgets.QVBoxLayout(frame)
            box.addWidget(label(f"选项 {card['slot']} · {card['name']}"))
            tier_label=label(f"{card.get('sourceTierLabel','虎牙公开源评级')}：{card.get('sourceTier') or '暂无评级'}",True);tier_label.setObjectName('source-tier-label');self.tier_labels.append(tier_label);box.addWidget(tier_label)
            desc=card['description'];box.addWidget(label(desc[:140]+('…' if len(desc)>140 else ''),True))
            if card['notes']:box.addWidget(label('条件/提醒：'+'；'.join(card['notes'])[:160],True))
            self.row.addWidget(frame,1)
        self.adjustSize();self.resize(max(750,min(self.width(),1020)),max(200,self.height()))
    def configure(self):
        if self.capture:self.capture.configure_overlay(int(self.winId()),self.click_through)
    def set_click_through(self,value):
        self.click_through=bool(value);visible=self.isVisible()
        self.setWindowFlag(QtCore.Qt.WindowType.WindowTransparentForInput,self.click_through)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_ShowWithoutActivating)
        if visible:self.show()
        self.configure()
        self.footer.setText('仅窗口像素 · Ctrl+Alt+O 切换鼠标穿透 · '+('鼠标穿透已开' if value else '鼠标穿透已关')+' · 非 Riot 批准')
    def show_at(self,rect,target):
        if not self.cards:return
        self.show();self.configure()
        if self.capture:
            # Win32 coordinates are physical pixels; avoids Qt/global-DPI mismatch.
            getdpi=getattr(self.capture.u,'GetDpiForWindow',None)
            if getdpi:getdpi.argtypes=[W.HWND];getdpi.restype=W.UINT
            dpi=int(getdpi(target.hwnd)) if getdpi else 96
            if not 48<=dpi<=960:raise CaptureUnavailable('无法取得有效的目标窗口 DPI，叠加已隐藏。')
            factor=dpi/96
            if rect.width<600*factor or rect.height<260*factor:raise CaptureUnavailable('目标客户区太小，请放大窗口后再显示叠加。')
            margin=min(round(18*factor),max(0,(rect.height-32)//4))
            width=min(rect.width-2*margin,round(950*factor));height=min(rect.height-2*margin,round(max(210,self.sizeHint().height())*factor))
            x=rect.x+(rect.width-width)//2;y=rect.y+rect.height-height-margin
            if not self.capture.u.SetWindowPos(int(self.winId()),W.HWND(-1),x,y,width,height,0x0010):raise CaptureUnavailable('无法把叠加放在目标窗口内，已隐藏。')
            actual=W.RECT()
            if not self.capture.u.GetWindowRect(int(self.winId()),ctypes.byref(actual)) or actual.left<rect.x or actual.top<rect.y or actual.right>rect.x+rect.width or actual.bottom>rect.y+rect.height:raise CaptureUnavailable('叠加几何范围未通过系统校验，已隐藏。')
        else:self.move(rect.x+20,rect.y+max(20,rect.height-self.height()-20))
    def nativeEvent(self,event_type,message):
        if os.name=='nt':
            msg=W.MSG.from_address(int(message))
            if msg.message==0x0084 and self.click_through:return True,-1 # HTTRANSPARENT, no hooks
            if msg.message==0x0021:return True,3 # MA_NOACTIVATE
        return super().nativeEvent(event_type,message)

class ControlWindow(QtWidgets.QWidget):
    def __init__(self,startup_loader,*,state_dir,current_executable,current_version,frozen,on_ready=None,smoke_report=None,smoke_screenshot=None,enable_updates=True):
        super().__init__();self.state=RecognitionState();self.data=None;self.target=None;self.capture=None;self.last_rect=None;self.was_target_foreground=False;self.ocr_busy=False;self.manual_editing=False;self.capture_pending=False;self.last_observation=0.;self.ocr_started=0.;self.ocr_timed_out=False;self.closed=False;self.on_ready=on_ready
        self._worker_lock=threading.Lock();self._cancel_workers=threading.Event();self._workers=set()
        self.enable_updates=enable_updates;self.hero_matcher=None
        self.current_version=current_version;self.current_executable=Path(current_executable);self.state_dir=Path(state_dir);self.frozen=frozen;self.release=None;self.smoke_report=smoke_report;self.smoke_screenshot=smoke_screenshot;self.hotkey_registered=False
        self.signals=TaskSignals(self);self.signals.result.connect(self.task_result);self.signals.error.connect(self.task_error)
        self.setWindowTitle(APP_NAME+' · 原生控制台');self.setWindowIcon(QtGui.QIcon(str(ROOT/'assets/branding/vga.ico')));self.setStyleSheet(STYLE);self.resize(790,760)
        outer=QtWidgets.QVBoxLayout(self);outer.setContentsMargins(8,8,8,8);scroll=QtWidgets.QScrollArea();scroll.setWidgetResizable(True);container=QtWidgets.QWidget();scroll.setWidget(container);outer.addWidget(scroll)
        layout=QtWidgets.QVBoxLayout(container);layout.addWidget(label(APP_NAME+'  ·  原生窗口资料助手'))
        layout.addWidget(label('只看用户选择窗口的可见像素；不读取游戏内存、不注入、不装输入钩子。初版支持窗口/无边框模式；实际 LoL 与 Vanguard 兼容性尚未验证。',True))
        self.source=label('正在检查公开数据，首次启动可能需要数十秒…',True);layout.addWidget(self.source)
        group=QtWidgets.QGroupBox('1  窗口与本人英雄自动识别');form=QtWidgets.QFormLayout(group);layout.addWidget(group)
        self.window_list=QtWidgets.QComboBox();self.refresh=QtWidgets.QPushButton('刷新窗口');row=QtWidgets.QHBoxLayout();row.addWidget(self.window_list,1);row.addWidget(self.refresh);form.addRow('目标窗口',row)
        self.hero_auto=QtWidgets.QCheckBox('自动识别本人 HUD 头像（默认，无需预选英雄）');self.hero_auto.setChecked(True);form.addRow(self.hero_auto)
        self.hero_status=label('本人头像模板准备中…',True);form.addRow(self.hero_status)
        self.hero_box=QtWidgets.QComboBox();self.hero_box.setEditable(True);self.hero_box.setInsertPolicy(QtWidgets.QComboBox.InsertPolicy.NoInsert);self.hero_box.setEnabled(False);form.addRow('英雄 / 不确定时人工纠正',self.hero_box)
        layout.addWidget(label('窗口选择只显示普通标题/几何信息。开始监测后，仅截取所选前台窗口的客户区；检测到遮挡或切换到其他应用时暂停。',True))
        roi_group=QtWidgets.QGroupBox('2  截图范围（所选窗口内的百分比，可按游戏界面调整）');roi_row=QtWidgets.QHBoxLayout(roi_group);layout.addWidget(roi_group);self.roi=[]
        for name,value in [('左',15),('上',25),('宽',70),('高',35)]:
            roi_row.addWidget(label(name));spin=QtWidgets.QSpinBox();spin.setRange(0,100);spin.setValue(value);spin.setSuffix('%');spin.valueChanged.connect(self.roi_changed);self.roi.append(spin);roi_row.addWidget(spin)
        self.start_button=QtWidgets.QPushButton('开始窗口截图监测');self.stop_button=QtWidgets.QPushButton('停止');self.toggle_button=QtWidgets.QPushButton('鼠标穿透：开（Ctrl+Alt+O）');buttons=QtWidgets.QHBoxLayout();buttons.addWidget(self.start_button);buttons.addWidget(self.stop_button);buttons.addWidget(self.toggle_button);layout.addLayout(buttons)
        group=QtWidgets.QGroupBox('3  三个候选（高置信稳定后自动显示；不确定时核对）');form=QtWidgets.QFormLayout(group);layout.addWidget(group);self.inputs=[]
        for i in range(3):
            edit=QtWidgets.QLineEdit();edit.textEdited.connect(self.edit_changed);self.inputs.append(edit);form.addRow(['左侧','中间','右侧'][i],edit)
        self.confirm_button=QtWidgets.QPushButton('人工纠正并确认三项');self.confirm_button.clicked.connect(self.confirm);form.addRow(self.confirm_button)
        self.status=label('准备中…');layout.addWidget(self.status)
        layout.addWidget(label('叠加按三张牌原位置显示名称、效果及当前英雄的虎牙公开源评级（T1–T4）；缺失显示暂无评级。不展示胜率、不自行换算等级或自动排序，也不输出唯一最佳选项。公开源评级不等于云端实时结果，也不代表 Riot 批准。',True))
        self.update_status=label('软件更新待检查。',True);layout.addWidget(self.update_status);self.update_button=QtWidgets.QPushButton('查看并安装软件更新');self.update_button.hide();layout.addWidget(self.update_button)
        self.refresh.clicked.connect(self.refresh_windows);self.window_list.currentIndexChanged.connect(self.target_changed);self.hero_box.currentTextChanged.connect(self.hero_changed);self.hero_auto.toggled.connect(self.hero_mode_changed);self.start_button.clicked.connect(self.start_monitor);self.stop_button.clicked.connect(self.stop_monitor);self.toggle_button.clicked.connect(self.toggle_clickthrough);self.update_button.clicked.connect(self.install_update)
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
        current=self.window_list.currentData();self.window_list.blockSignals(True);self.window_list.clear();self.window_list.addItem('请选择你要监测的游戏窗口',None)
        for info in self.capture.windows():self.window_list.addItem(info.title,info)
        if current:
            for i in range(self.window_list.count()):
                item=self.window_list.itemData(i)
                if item and item.identity==current.identity:self.window_list.setCurrentIndex(i);break
        # Auto-select only one exact known game-class/title match; never capture yet.
        if self.window_list.currentIndex()==0:
            matches=[i for i in range(1,self.window_list.count()) if self.window_list.itemData(i).class_name=='RiotWindowClass' and self.window_list.itemData(i).title in ('League of Legends (TM) Client','League of Legends')]
            if len(matches)==1:self.window_list.setCurrentIndex(matches[0])
        self.window_list.blockSignals(False);self.target_changed()
    def target_changed(self,*_):
        self.stop_monitor();self.target=self.window_list.currentData();self.last_rect=None
    def hero_mode_changed(self,automatic):
        self.hero_box.setEnabled(not automatic);self.state.clear_hero();self.overlay.hide();self.manual_editing=False
        self.hero_box.blockSignals(True);self.hero_box.setCurrentText('');self.hero_box.blockSignals(False)
        self.hero_status.setText('等待本人 HUD 头像，连续两帧高置信后自动使用。' if automatic else '人工纠正模式：请选择已确认的本人英雄。')
    def hero_changed(self,text):
        if text and self.hero_auto.isChecked():
            self.hero_auto.blockSignals(True);self.hero_auto.setChecked(False);self.hero_auto.blockSignals(False);self.hero_box.setEnabled(True)
        hero=text if self.data and text in self.data.get('heroes',{}) else getattr(self,'hero_aliases',{}).get(text,'')
        self.state.select_hero(hero);self.overlay.hide();self.status.setText(self.state.reason)
    def invalidate_scene(self,reason):
        if self.hero_auto.isChecked():
            self.state.clear_hero();self.hero_box.blockSignals(True);self.hero_box.setCurrentText('');self.hero_box.blockSignals(False)
        self.state.invalidate(reason)
    def roi_changed(self,*_):
        self.invalidate_scene('截图范围改变，请重新识别确认');self.overlay.hide()
    def edit_changed(self,*_):
        self.manual_editing=True;self.state.invalidate('候选已修改，请重新确认',clear_observed=False);self.overlay.hide()
    def start_monitor(self):
        if not self.target or not self.capture:return self.status.setText('请先选择一个目标窗口。')
        if not self.data or not self.data.get('augments'):return self.status.setText('没有可用词典，暂不能监测。')
        self.manual_editing=False
        if self.hero_auto.isChecked():self.state.clear_hero()
        self.state.start(self.target.identity);self.monitor.start();self.overlay.hide();self.stop_button.setEnabled(True);self.confirm_button.setEnabled(True);self.status.setText('已开始。请切回目标游戏窗口；仅本机处理截图，不保存图片。')
    def stop_monitor(self):
        self.monitor.stop();self.state.stop();
        if self.hero_auto.isChecked():self.state.clear_hero()
        self.overlay.hide();self.stop_button.setEnabled(False);self.confirm_button.setEnabled(False)
        self.status.setText(self.state.reason)
    def check_target(self):
        if not self.state.running or not self.target or not self.capture:return
        try:
            now=time.monotonic()
            if self.ocr_busy and now-self.ocr_started>8 and not self.ocr_timed_out:
                self.ocr_timed_out=True;self.invalidate_scene('OCR 超时，旧资料已隐藏；等待任务结束或停止并重启助手');self.overlay.hide();self.status.setText(self.state.reason)
            if self.state.confirmed and now-self.last_observation>4:
                self.invalidate_scene('画面观察超过 4 秒未更新，旧资料已隐藏，请重新确认');self.overlay.hide();self.status.setText(self.state.reason)
            rect=self.capture.rect(self.target)
            if self.last_rect and rect!=self.last_rect:
                self.invalidate_scene('目标窗口位置/尺寸改变，旧资料隐藏，需重新确认');self.overlay.hide()
            self.last_rect=rect
            if not self.capture.foreground(self.target):
                if self.was_target_foreground:self.invalidate_scene('离开目标窗口，旧资料已隐藏；重新确认后再显示')
                self.was_target_foreground=False;self.overlay.hide();return
            self.was_target_foreground=True
            if self.state.confirmed and not self.capture_pending:self.overlay.show_at(rect,self.target)
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
            if self.overlay.isVisible() or (self.capture and hasattr(self.capture,'u') and self.capture.u.IsWindowVisible(int(self.overlay.winId()))):raise CaptureUnavailable('自己的叠加尚未隐藏，已跳过本帧以避免识别反馈。')
            roi=tuple(spin.value()/100 for spin in self.roi);captured_at=time.monotonic();image,rect=self.capture.capture(self.target,(0.,0.,1.,1.))
            self.last_rect=rect;self.ocr_busy=True;self.ocr_started=time.monotonic();self.ocr_timed_out=False;self.status.setText('正在本机处理所选窗口截图，图片不保存、不上传…')
            from local_ocr import LocalOCR
            if not hasattr(self,'ocr'):self.ocr=LocalOCR()
            matcher=self.hero_matcher if self.hero_auto.isChecked() else None
            def infer():
                from hero_recognition import recognize_frame
                result=recognize_frame(image,roi,self.ocr,self.data['augments'],matcher);result['_capturedAt']=captured_at;return result
            self.spawn('ocr',infer,generation)
        except Exception as exc:
            self.ocr_busy=False;self.invalidate_scene('截图或识别初始化失败：'+str(exc));self.status.setText(self.state.reason);self.overlay.hide()
    def confirm(self, *, automatic=False, captured_at=None):
        try:
            self.state.confirm([edit.text() for edit in self.inputs],self.data['augments'],automatic=automatic);self.last_observation=captured_at if captured_at is not None else time.monotonic()
            metadata=self.data.get('metadata',{})
            source_version=f"数据包 {metadata.get('wikiDataVersion') or '未知'} / 游戏资料 {metadata.get('gamePatch') or '未知'}"
            self.overlay.set_cards(self.state.hero,display_cards(self.data,self.state.hero,self.state.offered),metadata.get('sourceDataDate') or '未知',source_version,('英雄/候选连续高置信自动识别' if self.hero_auto.isChecked() else '英雄人工纠正 · 候选自动识别') if automatic else '人工确认')
            self.status.setText(self.state.reason+'；切回目标窗口后显示。');self.check_target()
        except (ValueError,KeyError) as exc:self.status.setText(str(exc))
    def toggle_clickthrough(self):
        try:self.overlay.set_click_through(not self.overlay.click_through)
        except CaptureUnavailable as exc:
            self.stop_monitor();self.overlay.hide();self.status.setText(str(exc));return
        self.toggle_button.setText('鼠标穿透：'+('开' if self.overlay.click_through else '关')+'（Ctrl+Alt+O）')
    @QtCore.Slot(str,object,int)
    def task_result(self,kind,value,generation):
        if self.closed:return
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
        elif kind=='ocr':
            self.ocr_busy=False
            if not self.state.running or generation!=self.state.generation:return
            captured_at=value.get('_capturedAt',0)
            if not isinstance(captured_at,(int,float)) or not math.isfinite(captured_at) or time.monotonic()-captured_at>4 or captured_at>time.monotonic():
                self.invalidate_scene('识别完成时截图已过期，旧资料隐藏；等待新截图');self.overlay.hide();self.status.setText(self.state.reason);return
            auto_candidates=value.get('automatic_candidates',[])
            candidates=auto_candidates if len(auto_candidates)==3 else value.get('candidates',[])
            names=[item['name'] for item in candidates]
            hero_stable=True
            if self.hero_auto.isChecked():
                observation=value.get('hero_observation',{});recognized=observation.get('hero') if observation.get('confident') is True else ''
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
        if kind=='ocr':
            self.ocr_busy=False
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
            if self.smoke_report:
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
        self.monitor.stop();self.watchdog.stop();self.state.stop();self.overlay.close()
        if self.capture and self.hotkey_registered:self.capture.release_hotkey(int(self.winId()));self.hotkey_registered=False
        # Running native inference cannot safely be killed; discard its result and
        # let the daemon exit naturally. Never wait indefinitely in the UI thread.
        deadline=time.monotonic()+.2
        for job in jobs:
            if job is not threading.current_thread():job.join(max(0,deadline-time.monotonic()))
        event.accept()


def run_native(startup_loader,*,state_dir,current_executable,current_version,frozen,on_ready=None,smoke_report=None,smoke_screenshot=None,enable_updates=True):
    app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([]);app.setApplicationName(APP_NAME);app.setQuitOnLastWindowClosed(True)
    control=ControlWindow(startup_loader,state_dir=state_dir,current_executable=current_executable,current_version=current_version,frozen=frozen,on_ready=on_ready,smoke_report=smoke_report,smoke_screenshot=smoke_screenshot,enable_updates=enable_updates)
    app._vga_control=control
    return app.exec()

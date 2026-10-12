"""Actual Windows Qt/GDI/CPU-OCR smoke against our OWN synthetic mock window.

Only this explicit diagnostic saves an original synthetic screenshot. Normal
monitoring never writes image buffers to disk and never sends them to a service.
"""
from pathlib import Path
import ctypes
from ctypes import wintypes as W
import json
import os
import sys
import time
from PySide6 import QtCore,QtGui,QtWidgets
from native_state import display_cards


def smoke_dimensions(width,height):
    width=min(1280,width-60);height=min(720,height-70,int(width/1.6))
    if width<64 or height<600:raise ValueError('Desktop cannot fit supported600px own-HUD mock')
    return width,height

def start_smoke(control,report_path,screenshot_path):
    app=QtWidgets.QApplication.instance();checks=[];root=Path(__file__).resolve().parent
    report={'status':'running','backend':'qtwidgets','qt_platform':app.platformName(),'frozen':bool(getattr(sys,'frozen',False)),'applicationVersion':control.current_version,'native_window':False,'window_closed':False,'capture_passed':False,'ocr_passed':False,'click_through_passed':False,'scope':'Original synthetic mock game only; not LoL/Vanguard, live-game accuracy or approval','checks':checks}
    control._smoke_objects=[]
    def save():
        report_path.parent.mkdir(parents=True,exist_ok=True);report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    def fail(exc):
        report.update(status='failed',error=str(exc));save()
        for widget in control._smoke_objects:widget.close()
        control.close();app.exit(1)
    def run(fn):
        try:fn()
        except Exception as exc:fail(exc)
    if os.name!='nt' or app.platformName()!='windows':return fail(RuntimeError('Native Windows smoke requires the real Windows Qt platform, not offscreen/minimal.'))
    if not control.capture:return fail(RuntimeError('Win32 capture adapter unavailable'))
    control.watchdog.stop();control.monitor.stop()
    available=app.primaryScreen().availableGeometry();mock_width,mock_height=smoke_dimensions(available.width(),available.height())
    if mock_height<600:return fail(RuntimeError('Automatic-HUD smoke needs a landscape mock client at least600px high.'))
    mock=QtWidgets.QWidget();mock.setWindowTitle('VGA original synthetic mock game');mock.resize(mock_width,mock_height)
    layout=QtWidgets.QVBoxLayout(mock);layout.setContentsMargins(0,0,0,0)
    image=QtWidgets.QLabel();image.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
    from synthetic_vision import portraits,frame,encoded,configure_data
    from PIL import Image
    from hero_recognition import PortraitMatcher,recognize_frame
    bank=portraits()
    configure_data(control.data)
    control.hero_matcher=PortraitMatcher(bank,control.data['heroes'])
    def paint_mock(key='9001'):
        canvas=frame(bank[key],width=mock_width,height=mock_height)
        cards=Image.open(root/'fixtures/auto-scene.png').convert('RGB').resize((mock_width,mock_height),Image.Resampling.LANCZOS)
        canvas.paste(cards.crop((0,0,mock_width,round(mock_height*.8))),(0,0))
        pixmap=QtGui.QPixmap();assert pixmap.loadFromData(encoded(canvas));image.setPixmap(pixmap)
    paint_mock();layout.addWidget(image)
    mock.move(available.x()+20,available.y()+20);control._smoke_objects.append(mock)
    def prepare():
        control.hide();mock.show();mock.raise_();mock.activateWindow()
        report['controlHwnd']=int(control.winId());report['mockHwnd']=int(mock.winId());report['overlayHwnd']=int(control.overlay.winId())
        report['native_window']=all(control.capture.u.IsWindow(h) for h in (report['controlHwnd'],report['mockHwnd'],report['overlayHwnd']))
        assert report['native_window'];checks.append('Real QtWidgets control, overlay and synthetic mock HWNDs exist')
        QtCore.QTimer.singleShot(700,lambda:run(capture))
    def capture():
        target=control.capture.info(int(mock.winId()));control.target=target
        control.overlay.hide();captured_at=time.monotonic();bytes_,rect=control.capture.capture(target)
        report['capture_passed']=True;report['captureBytes']=len(bytes_);report['clientRect']={'x':rect.x,'y':rect.y,'width':rect.width,'height':rect.height}
        checks.append('GDI captured only selected mock client area into an in-memory PNG')
        from local_ocr import LocalOCR
        engine=LocalOCR();control.ocr=engine
        expected=['星火共鸣','晶盾回路','风步微光']
        control.hero_auto.setChecked(True);control.state.clear_hero();control.state.start(target.identity)
        assert control.state.hero=='' and control.hero_auto.isChecked()
        def observe_current():
            control.overlay.hide();assert not control.overlay.isVisible()
            assert not control.capture.u.IsWindowVisible(int(control.overlay.winId()))
            captured_at=time.monotonic();pixels,_=control.capture.capture(target)
            value=recognize_frame(pixels,(.15,.25,.7,.35),engine,control.data['augments'],control.hero_matcher)
            if time.monotonic()-captured_at>3:
                captured_at=time.monotonic();pixels,_=control.capture.capture(target);value=recognize_frame(pixels,(.15,.25,.7,.35),engine,control.data['augments'],control.hero_matcher)
            value['_capturedAt']=captured_at
            control.task_result('ocr',value,control.state.generation)
            return value
        result=observe_current();assert not control.state.confirmed
        result=observe_current();names=[item['name'] for item in result['automatic_candidates']]
        assert names==expected,('OCR names',names)
        assert control.state.hero=='星火术士（演示）' and control.state.confirmed and control.state.confirmation_mode=='automatic'
        assert control.hero_auto.isChecked() and not control.hero_box.isEnabled()
        report.update(automatic_hero_passed=True,automatic_choices_passed=True,auto_without_manual_hero_selection=True,own_overlay_hidden_capture_passed=True)
        report['ocr_passed']=True;report['recognized']=names;checks.append('Actual OS capture + original synthetic portrait matcher + OCR feed production handlers; two frames auto-confirm hero and three cards without hero selection or confirm click')
        report['targetForegroundBefore']=int(control.capture.u.GetForegroundWindow() or 0)
        unknown={**result,'hero_observation':{'hero':None,'confident':False,'reason':'Synthetic unknown portrait'},'_capturedAt':time.monotonic()}
        control.task_result('ocr',unknown,control.state.generation);assert not control.state.confirmed and control.state.hero=='' and not control.overlay.isVisible();report['auto_unknown_clears_passed']=True
        observe_current();observe_current();assert control.state.confirmed
        paint_mock('9002');app.processEvents();observe_current();assert not control.state.confirmed and control.state.hero==''
        observe_current();assert control.state.hero=='磐石守卫（演示）' and control.state.confirmed;report['auto_hero_change_clears_passed']=True
        paint_mock('9001');app.processEvents();observe_current();observe_current();assert control.state.confirmed
        assert [card['name'] for card in control.overlay.cards]==names
        assert [card['sourceTier'] for card in control.overlay.cards]==['T1','T2','T3']
        assert [widget.text() for widget in control.overlay.tier_labels]==['虚构源评级（演示）：T1','虚构源评级（演示）：T2','虚构源评级（演示）：T3']
        assert '来源日期' in control.overlay.heading.text() and '数据包' in control.overlay.heading.text() and '游戏资料' in control.overlay.heading.text()
        control.hero_box.setCurrentText('磐石守卫（演示）');assert not control.state.confirmed and not control.overlay.isVisible()
        control.confirm();assert [card['name'] for card in control.overlay.cards]==names and [card['sourceTier'] for card in control.overlay.cards]==['T3','T1','T2']
        report['source_tier_hero_specific']=True;report['auto_manual_fallback_passed']=not control.hero_auto.isChecked()
        tier_row=control.data['heroAugmentStats']['磐石守卫（演示）'][0];saved_tier=tier_row['tier']
        for missing in [None,'UNKNOWN']:
            tier_row['tier']=missing;control.confirm();assert control.overlay.tier_labels[1].text()=='虚构源评级（演示）：暂无评级'
        tier_row['tier']=saved_tier;report['source_tier_missing_passed']=True
        control.hero_box.setCurrentText('星火术士（演示）');control.confirm()
        assert [card['name'] for card in control.overlay.cards]==names
        assert all('winRate' not in card and 'sourceRank' not in card and 'recommendedName' not in card for card in control.overlay.cards)
        rendered=' '.join(widget.text() for widget in control.overlay.tier_labels)
        assert all(value not in rendered for value in ['60.00%','55.00%','50.00%','胜率'])
        report.update(source_tier_display_passed=True,source_tier_screen_order_preserved=True,source_tier_no_winrate_display=True,
                      source_tier_rendered=[widget.text() for widget in control.overlay.tier_labels])
        checks.append('Actual native source-tier labels are hero-specific literals; null/unknown remain ungraded; screen order preserved with no win-rate/rank/best-choice fields')
        QtCore.QTimer.singleShot(250,lambda:run(verify_overlay))
    def verify_overlay():
        names=report['recognized'];overlay=control.overlay;u=control.capture.u;hwnd=int(overlay.winId());style=int(control.capture.get_long(hwnd,-20))
        assert style&0x80000 and style&0x08000000 and style&0x20 and style&0x8,hex(style)
        assert int(u.GetForegroundWindow() or 0)==control.target.hwnd,'Overlay stole focus'
        assert overlay.isVisible();assert all(widget.isVisible() for widget in overlay.tier_labels)
        visible_text=' '.join(widget.text() for widget in overlay.findChildren(QtWidgets.QLabel) if widget.isVisible())
        assert '源顺位' not in visible_text and 'winRate' not in visible_text
        fixture_rates=[row.get('winRate') for rows in control.data.get('heroAugmentStats',{}).values() for row in rows]
        assert all(formatted not in visible_text for rate in fixture_rates if isinstance(rate,(int,float)) for formatted in (f'{rate:g}%',f'{rate:.2f}%',f'{rate}%'))
        checks.append('Overlay is layered/topmost/noactivate/transparent and does not steal foreground focus')
        report['overlayStyle']=hex(style);report['foregroundPreserved']=True
        # Actual Win32 point hit test at a point inside the overlay; no game input.
        rect=W.RECT();u.GetWindowRect.argtypes=[W.HWND,ctypes.POINTER(W.RECT)];u.GetWindowRect.restype=W.BOOL;assert u.GetWindowRect(hwnd,ctypes.byref(rect))
        point=W.POINT(rect.left+(rect.right-rect.left)//2,rect.top+20)
        hit=int(u.GetAncestor(u.WindowFromPoint(point),2) or 0)
        assert hit==control.target.hwnd,('Transparent overlay intercepted point',hit,control.target.hwnd)
        control.toggle_clickthrough();style_off=int(control.capture.get_long(int(overlay.winId()),-20));assert not style_off&0x20
        control.toggle_clickthrough();style_on=int(control.capture.get_long(int(overlay.winId()),-20));assert style_on&0x20
        report['click_through_passed']=True;checks.append('Real OS point hit testing reaches the mock through overlay; click-through toggle changes WS_EX_TRANSPARENT')
        assert control.hotkey_registered,'Ctrl+Alt+O registration failed in test session';checks.append('RegisterHotKey succeeded without input hooks')
        # Compose ONLY our two rendered widgets; never save a user desktop screenshot.
        canvas=QtGui.QPixmap(1100,780);canvas.fill(QtGui.QColor('#102029'));painter=QtGui.QPainter(canvas);painter.drawPixmap(0,0,mock.grab());painter.drawPixmap(20,530,overlay.grab().scaled(1060,230,QtCore.Qt.AspectRatioMode.KeepAspectRatio));painter.end()
        screenshot_path.parent.mkdir(parents=True,exist_ok=True);assert canvas.save(str(screenshot_path),'PNG')
        report['screenshot']=str(screenshot_path);report['screenshot_method']='Qt QWidget.grab of our synthetic mock and overlay only, composited locally; OS capture/OCR separately asserted'
        checks.append('Original synthetic native mock/overlay rendering saved, with no user desktop pixels')
        control.task_result('ocr',{'candidates':[],'_capturedAt':time.monotonic()},control.state.generation);assert not control.state.confirmed and not overlay.isVisible();checks.append('Production OCR result handler hides overlay on scene/candidate loss')
        old_generation=control.state.generation;control.hero_box.setCurrentText('磐石守卫（演示）');assert control.state.generation>old_generation;checks.append('Actual hero selection signal invalidates prior scene state')
        control.state.confirm(names,control.data['augments']);control.last_observation=__import__('time').monotonic();control.last_rect=control.capture.rect(control.target)
        mock.move(mock.x()+7,mock.y()+5);QtWidgets.QApplication.processEvents();control.check_target();assert control.state.confirmed and overlay.isVisible();overlay._verify_rect(control.capture.rect(control.target));checks.append('Real same-size mock translation preserves fresh confirmed identity/offers and repositions overlay inside the new physical client bounds')
        control.last_observation=time.monotonic()-5;control.check_target();assert not control.state.confirmed and not overlay.isVisible();checks.append('Expired observations cannot be revived by translating the target window')
        control.state.confirm(names,control.data['augments']);control.last_observation=time.monotonic();mock.resize(mock.width()-20,mock.height()-20);QtWidgets.QApplication.processEvents();control.check_target();assert not control.state.confirmed and not overlay.isVisible();checks.append('Real target size change still invalidates cards pending fresh recognition')
        control.state.confirm(names,control.data['augments']);mock.showMinimized();QtWidgets.QApplication.processEvents();control.check_target();assert not control.state.confirmed and not overlay.isVisible();checks.append('Real mock minimization hides old cards through production watchdog')
        control.close();mock.close();report['window_closed']=not control.isVisible() and not overlay.isVisible() and not mock.isVisible() and not control.hotkey_registered
        assert report['window_closed'];report['status']='passed';checks.append('Control, overlay and mock closed; timer monitoring and registered hotkey released');save();app.exit(0)
    QtCore.QTimer.singleShot(150,lambda:run(prepare))

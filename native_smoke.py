"""Actual Windows Qt/GDI/CPU-OCR smoke against our OWN synthetic mock window.

Only this explicit diagnostic saves an original synthetic screenshot. Normal
monitoring never writes image buffers to disk and never sends them to a service.
"""
from pathlib import Path
import ctypes
from ctypes import wintypes as W
import json
import math
import os
import sys
import time
import traceback
from PySide6 import QtCore,QtGui,QtWidgets
from native_state import display_cards


def smoke_dimensions(width,height):
    if any(not isinstance(v,int) or isinstance(v,bool) for v in (width,height)) or width<1000 or height<640:
        raise ValueError('Physical desktop work area cannot fit the fixed960x600 own-HUD mock with20px margins')
    return 960,600

def smoke_pixmap(portrait,cards_path,width,height,dpr):
    """Original fixed-physical diagnostic artwork, never a user screenshot."""
    from PIL import Image
    from synthetic_vision import frame,encoded
    if not math.isfinite(dpr) or dpr<=0:raise ValueError('Invalid artwork DPR')
    canvas=frame(portrait,width=width,height=height)
    cards=Image.open(cards_path).convert('RGB').resize((width,height),Image.Resampling.LANCZOS)
    canvas.paste(cards.crop((0,0,width,round(height*.8))),(0,0))
    pixmap=QtGui.QPixmap()
    if not pixmap.loadFromData(encoded(canvas)):raise RuntimeError('Original mock artwork could not be decoded')
    pixmap.setDevicePixelRatio(dpr)
    return pixmap


def shrink_smoke_mock(mock,image):
    """Release only the owned fixture's pixmap minimum before resize testing."""
    before=mock.size()
    image.clear();mock.layout().invalidate();mock.layout().activate()
    mock.resize(before.width()-20,before.height()-20)
    QtWidgets.QApplication.processEvents()
    assert mock.width()<before.width() and mock.height()<before.height(),'Owned diagnostic mock did not shrink'


def inspect_smoke_layout(overlay):
    """Diagnostic-only check of actual visible Qt layout, including text fit."""
    if not overlay.isVisible():raise AssertionError('Overlay is not visible')
    rows=[]
    for widget in overlay.findChildren(QtWidgets.QWidget):
        if not widget.isVisibleTo(overlay):continue
        parent=widget.parentWidget();pos=widget.mapTo(overlay,QtCore.QPoint(0,0))
        assert widget.width()>0 and widget.height()>0
        assert pos.x()>=0 and pos.y()>=0 and pos.x()+widget.width()<=overlay.width() and pos.y()+widget.height()<=overlay.height(),'Visible widget escapes overlay'
        if parent:
            assert widget.x()>=0 and widget.y()>=0 and widget.x()+widget.width()<=parent.width() and widget.y()+widget.height()<=parent.height(),'Visible widget escapes parent'
        row={'type':type(widget).__name__,'logical_rect':{'x':pos.x(),'y':pos.y(),'width':widget.width(),'height':widget.height()}}
        if isinstance(widget,QtWidgets.QLabel):
            required=widget.heightForWidth(widget.width());minimum=widget.minimumSizeHint().width()
            assert required<=widget.height()+1,('Label height clipped',widget.text(),required,widget.height())
            assert minimum<=widget.width()+1,('Label width clipped',widget.text(),minimum,widget.width())
            row.update(text=widget.text(),required_height_at_width=required,minimum_width=minimum)
        rows.append(row)
    assert len(overlay.cards)==3 and len(overlay.tier_labels)==3 and all(label.isVisibleTo(overlay) for label in overlay.tier_labels)
    for i,card in enumerate(overlay.cards):
        labels=overlay.row.itemAt(i).widget().findChildren(QtWidgets.QLabel)
        assert labels[0].isVisibleTo(overlay) and labels[0].text()==f"选项 {card['slot']} · {card['name']}"
    return rows


def start_smoke(control,report_path,screenshot_path):
    app=QtWidgets.QApplication.instance();checks=[];root=Path(__file__).resolve().parent
    report={'status':'running','backend':'qtwidgets','qt_platform':app.platformName(),'frozen':bool(getattr(sys,'frozen',False)),'applicationVersion':control.current_version,'native_window':False,'window_closed':False,'capture_passed':False,'ocr_passed':False,'click_through_passed':False,'scope':'Original synthetic mock game only; not LoL/Vanguard, live-game accuracy or approval','checks':checks}
    control._smoke_objects=[]
    def save():
        report_path.parent.mkdir(parents=True,exist_ok=True);report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    def fail(exc):
        report.update(status='failed',error=str(exc)[:2000],error_type=type(exc).__name__,error_traceback=traceback.format_exc(limit=4)[-4000:]);save()
        for widget in control._smoke_objects:widget.close()
        control.close();app.exit(1)
    def run(fn):
        try:fn()
        except Exception as exc:fail(exc)
    if os.name!='nt' or app.platformName()!='windows':return fail(RuntimeError('Native Windows smoke requires the real Windows Qt platform, not offscreen/minimal.'))
    if not control.capture:return fail(RuntimeError('Win32 capture adapter unavailable'))
    control.watchdog.stop();control.monitor.stop()
    # SPI_GETWORKAREA only reads physical bounds; never change OS settings.
    u=control.capture.u;u.SystemParametersInfoW.argtypes=[W.UINT,W.UINT,W.LPVOID,W.UINT];u.SystemParametersInfoW.restype=W.BOOL
    available=W.RECT()
    if not u.SystemParametersInfoW(0x0030,0,ctypes.byref(available),0):return fail(RuntimeError('Physical work area unavailable'))
    work_area={'x':available.left,'y':available.top,'width':available.right-available.left,'height':available.bottom-available.top}
    mock_width,mock_height=smoke_dimensions(work_area['width'],work_area['height'])
    requested_scale=float(os.environ.get('QT_SCALE_FACTOR','1'))
    if not math.isfinite(requested_scale) or not .5<=requested_scale<=4:return fail(ValueError('Unsupported diagnostic app scale'))
    report.update(requested_app_scale=requested_scale,desktop_work_area_physical=work_area)
    mock=QtWidgets.QWidget(None,QtCore.Qt.WindowType.Window|QtCore.Qt.WindowType.FramelessWindowHint);mock.setWindowTitle('VGA original synthetic mock game');mock.winId()
    mock_dpr=float(mock.windowHandle().devicePixelRatio())
    if not math.isfinite(mock_dpr) or mock_dpr<=0:return fail(ValueError('Invalid native mock DPR'))
    mock.resize(round(mock_width/mock_dpr),round(mock_height/mock_dpr))
    def native_rect(hwnd):
        rect=W.RECT()
        if not u.GetWindowRect(hwnd,ctypes.byref(rect)):raise RuntimeError('Owned native window rectangle unavailable')
        return {'x':rect.left,'y':rect.top,'width':rect.right-rect.left,'height':rect.bottom-rect.top}
    def inside(outer,inner):
        return inner['width']>0 and inner['height']>0 and inner['x']>=outer['x'] and inner['y']>=outer['y'] and inner['x']+inner['width']<=outer['x']+outer['width'] and inner['y']+inner['height']<=outer['y']+outer['height']

    layout=QtWidgets.QVBoxLayout(mock);layout.setContentsMargins(0,0,0,0)
    image=QtWidgets.QLabel();image.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
    from synthetic_vision import portraits,configure_data
    from hero_recognition import PortraitMatcher,recognize_frame
    bank=portraits()
    configure_data(control.data)
    control.hero_matcher=PortraitMatcher(bank,control.data['heroes'])
    def paint_mock(key='9001'):
        image.setPixmap(smoke_pixmap(bank[key],root/'fixtures/auto-scene.png',mock_width,mock_height,float(mock.windowHandle().devicePixelRatio())))
    paint_mock();layout.addWidget(image)
    control._smoke_objects.append(mock)
    def prepare():
        control.hide();mock.show()
        assert u.SetWindowPos(int(mock.winId()),None,work_area['x']+20,work_area['y']+20,mock_width,mock_height,0x0004|0x0040),'Could not place owned physical mock'
        app.processEvents();paint_mock();app.processEvents();mock.raise_();mock.activateWindow()
        actual=control.capture.rect(control.capture.info(int(mock.winId())))
        assert (actual.width,actual.height)==(mock_width,mock_height),('Mock physical dimensions changed',actual)
        assert inside(work_area,native_rect(int(mock.winId()))),'Owned mock must be fully inside physical work area'
        report.update(mock_qwindow_dpr=float(mock.windowHandle().devicePixelRatio()),mock_window_physical=native_rect(int(mock.winId())),physical_mock_geometry_passed=True)

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
        report.update(overlay_qwindow_dpr=float(overlay.windowHandle().devicePixelRatio()),overlay_window_physical=native_rect(hwnd),overlay_compact=overlay._compact)
        assert inside(report['clientRect'],report['overlay_window_physical']),'Actual native overlay escaped fixed physical mock'
        report['overlay_layout_widgets']=inspect_smoke_layout(overlay);report['overlay_layout_passed']=True
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
        mock_pixels=mock.grab();mock_pixels.setDevicePixelRatio(1);overlay_pixels=overlay.grab();overlay_pixels.setDevicePixelRatio(1)
        canvas=QtGui.QPixmap(1100,780);canvas.fill(QtGui.QColor('#102029'));painter=QtGui.QPainter(canvas);painter.drawPixmap(0,0,mock_pixels);painter.drawPixmap(20,530,overlay_pixels.scaled(1060,230,QtCore.Qt.AspectRatioMode.KeepAspectRatio));painter.end()
        screenshot_path.parent.mkdir(parents=True,exist_ok=True);assert canvas.save(str(screenshot_path),'PNG')
        report['screenshot']=str(screenshot_path);report['screenshot_method']='Qt QWidget.grab of our synthetic mock and overlay only, composited locally; OS capture/OCR separately asserted'
        checks.append('Original synthetic native mock/overlay rendering saved, with no user desktop pixels')
        control.task_result('ocr',{'candidates':[],'_capturedAt':time.monotonic()},control.state.generation);assert not control.state.confirmed and not overlay.isVisible();checks.append('Production OCR result handler hides overlay on scene/candidate loss')
        old_generation=control.state.generation;control.hero_box.setCurrentText('磐石守卫（演示）');assert control.state.generation>old_generation;checks.append('Actual hero selection signal invalidates prior scene state')
        control.state.confirm(names,control.data['augments']);control.last_observation=__import__('time').monotonic();control.last_rect=control.capture.rect(control.target)
        mock.move(mock.x()+7,mock.y()+5);QtWidgets.QApplication.processEvents();control.check_target();assert control.state.confirmed and overlay.isVisible();overlay._verify_rect(control.capture.rect(control.target));checks.append('Real same-size mock translation preserves fresh confirmed identity/offers and repositions overlay inside the new physical client bounds')
        control.last_observation=time.monotonic()-5;control.check_target();assert not control.state.confirmed and not overlay.isVisible();checks.append('Expired observations cannot be revived by translating the target window')
        control.state.confirm(names,control.data['augments']);control.last_observation=time.monotonic()
        before_resize=control.capture.rect(control.target);shrink_smoke_mock(mock,image);after_resize=control.capture.rect(control.target)
        assert after_resize.width<before_resize.width and after_resize.height<before_resize.height,'Actual physical mock size did not shrink'
        assert inside(work_area,native_rect(int(mock.winId()))),'Resized own mock escaped physical work area'
        report['resize_physical_before']={'width':before_resize.width,'height':before_resize.height};report['resize_physical_after']={'width':after_resize.width,'height':after_resize.height}
        control.check_target();assert not control.state.confirmed and not overlay.isVisible();checks.append('Actual physical mock size changed after clearing its own artwork minimum; production watchdog hides old cards pending fresh recognition')
        control.state.confirm(names,control.data['augments']);mock.showMinimized();QtWidgets.QApplication.processEvents();control.check_target();assert not control.state.confirmed and not overlay.isVisible();checks.append('Real mock minimization hides old cards through production watchdog')
        control.close();mock.close();report['window_closed']=not control.isVisible() and not overlay.isVisible() and not mock.isVisible() and not control.hotkey_registered
        assert report['window_closed'];report['status']='passed';checks.append('Control, overlay and mock closed; timer monitoring and registered hotkey released');save();app.exit(0)
    QtCore.QTimer.singleShot(150,lambda:run(prepare))

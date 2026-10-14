"""Render original Qt design fixtures at the process's real app scale.

This is widget/layout evidence only. No OS capture, game, input interception,
network activity or modified display settings. Outputs are opt-in local files.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6 import QtCore,QtWidgets
from native_ui import ControlWindow
from native_state import display_cards
from native_smoke import inspect_smoke_layout
from engine import load_data
from screen_capture import CaptureUnavailable,ClientRect


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    app.setQuitOnLastWindowClosed(False)
    images=[];observations=[]
    data=load_data(ROOT/'fixtures/demo.json')
    with tempfile.TemporaryDirectory() as temporary,patch('native_ui.Win32Capture',side_effect=CaptureUnavailable('Original design fixture; no OS capture')):
        w=ControlWindow(lambda:{'data':data},state_dir=Path(temporary),current_executable=Path('/unused.exe'),current_version='0.4.6',frozen=False,enable_updates=False)
        try:
            deadline=time.monotonic()+3
            while w.data is None and time.monotonic()<deadline:app.processEvents();time.sleep(.005)
            assert w.data is not None
            w.watchdog.stop();w.monitor.stop();w.refresh_status_badge();app.processEvents()
            scale=float(w.windowHandle().devicePixelRatio());requested=float(os.environ.get('QT_SCALE_FACTOR','1'))
            assert abs(scale-requested)<.01
            def rect(value):return dict(x=value.x(),y=value.y(),width=value.width(),height=value.height())
            def save(widget,name):
                app.processEvents();image=widget.grab();path=args.output/(name+'.png');assert image.save(str(path),'PNG')
                images.append(dict(path=path.name,sha256=hashlib.sha256(path.read_bytes()).hexdigest(),physical_size=[image.width(),image.height()],widget_dpr=float(image.devicePixelRatio()),logical_size=[widget.width(),widget.height()]))
            assert w.screen().availableGeometry().contains(w.frameGeometry())
            observations.append(dict(case='initial-available-area',available_logical=rect(w.screen().availableGeometry()),frame_logical=rect(w.frameGeometry()),minimum_logical=[w.minimumWidth(),w.minimumHeight()]))
            save(w,'control-initial')
            w.advanced_toggle.setChecked(True);w.scroll.ensureWidgetVisible(w.advanced_panel);save(w,'control-advanced')
            w.hero_auto.setChecked(False);w.hero_box.setCurrentText(next(iter(data['heroes'])));w.scroll.ensureWidgetVisible(w.hero_box);save(w,'control-manual-correction')
            w.advanced_toggle.setChecked(False)
            w.status.setText('窗口身份已变化，旧资料已隐藏；请恢复游戏前台并等待重新核验。');save(w,'control-paused')
            if scale==1:
                w.resize(640,560);app.processEvents();assert w.screen().availableGeometry().contains(w.frameGeometry());save(w,'control-narrow-640x560')
            hero=next(iter(data['heroes']));names=list(data['augments'])[:3]
            overlay=w.overlay
            cards=display_cards(data,hero,names);cards[-1]['sourceTier']=None
            overlay.set_cards(hero,cards,'2026-10-14','数据包 演示 / 游戏资料 演示','高置信自动识别')
            for name,client in [('small-client',ClientRect(0,0,960,600)),('large-client',ClientRect(0,0,1920,1080))]:
                overlay.hide();x,y,width,height=overlay._fit_layout(client,scale);overlay.show();app.processEvents()
                assert abs(float(overlay.windowHandle().devicePixelRatio())-scale)<.01
                rows=inspect_smoke_layout(overlay)
                assert height<=client.height*.5
                observations.append(dict(case=name,client_physical=[client.width,client.height],overlay_physical=[width,height],compact=overlay._compact,visible_labels=[row['text'] for row in rows if 'text' in row]))
                save(overlay,'overlay-'+name)
            overlay.hide()
            concise=[dict(card,description='原创简短资料说明，供本地布局验证。',notes=[]) for card in cards]
            overlay.set_cards(hero,concise,'2026-10-14','数据包 演示 / 游戏资料 演示','高置信自动识别')
            overlay._fit_layout(ClientRect(0,0,1920,1080),scale);overlay.show();app.processEvents();inspect_smoke_layout(overlay)
            assert not overlay._compact and overlay.metadata_label.isVisibleTo(overlay)
            save(overlay,'overlay-full-metadata');overlay.hide()
            w.hero_auto.setChecked(False);w.hero_box.setCurrentText(hero)
            for edit,name in zip(w.inputs,names):edit.setText(name)
            w.details_toggle.setChecked(True);w.scroll.ensureWidgetVisible(w.card_details);save(w,'control-card-details')
            w.invalidate_scene('Owned UI state changed')
            assert '不代表识别或确认' in w.card_details.text() and not w.state.confirmed
        finally:
            overlay=w.overlay;w.capture=None;w.close()
            deadline=time.monotonic()+3
            while w._workers and time.monotonic()<deadline:app.processEvents();time.sleep(.005)
            assert not w._workers
            overlay.deleteLater();w.deleteLater();QtCore.QCoreApplication.sendPostedEvents(None,QtCore.QEvent.Type.DeferredDelete);app.processEvents()
    report=dict(status='passed',scope='Original offscreen Qt widgets and per-process app scaling; not actual Windows, game capture, monitor DPI or game compatibility proof',qt_platform=app.platformName(),requested_scale=requested,measured_scale=scale,observations=observations,images=images,source_files={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in ('native_ui.py','overlay_geometry.py','native_smoke.py','tests/native_design_qt_validation.py')})
    (args.output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':main()

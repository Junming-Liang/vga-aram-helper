"""Source-bound actual Qt widget renders; explicitly synthetic, never game proof.

An optional owned offscreen-screen configuration makes nominal desktop layouts
reproducible without altering the OS display. Each DPI is a separate process.
"""
import argparse
import copy
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
from app_version import __version__

SOURCE_FILES=('native_ui.py','overlay_geometry.py','native_smoke.py','tests/native_design_qt_validation.py','fixtures/demo.json','app_version.py','hero_strength.py')

class PresentationCapture:
    """Only existing window setup hooks; no pixels, discovery or OS calls."""
    def configure_overlay(self,*_):pass
    def hotkey(self,*_):return True
    def unhotkey(self,*_):pass
    def windows(self):return []
    def foreground(self,*_):return False
    def capture(self,*_,**__):raise AssertionError('Presentation fixture cannot capture pixels')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--screen-width',type=int)
    parser.add_argument('--screen-height',type=int)
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    if args.screen_width or args.screen_height:
        if not args.screen_width or not args.screen_height or not os.environ['QT_QPA_PLATFORM'].startswith('offscreen'):
            parser.error('An owned synthetic screen requires both dimensions and offscreen Qt')
        config=dict(windowFrameMargins=True,screens=[dict(name='Owned synthetic render screen',x=0,y=0,width=args.screen_width,height=args.screen_height,logicalDpi=96,logicalBaseDpi=96,dpr=1)])
        config_path=args.output/'offscreen-screen.json';config_path.write_text(json.dumps(config),encoding='utf8')
        os.environ['QT_QPA_PLATFORM']='offscreen:configfile='+str(config_path.resolve())
    before={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in SOURCE_FILES}
    app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([]);app.setQuitOnLastWindowClosed(False)
    images=[];observations=[];data=load_data(ROOT/'fixtures/demo.json')
    with tempfile.TemporaryDirectory() as temporary,patch('native_ui.Win32Capture',side_effect=CaptureUnavailable('Offscreen fixture: no Windows capture')):
        w=ControlWindow(lambda:{'data':copy.deepcopy(data)},state_dir=Path(temporary),current_executable=Path('/unused.exe'),current_version=__version__,frozen=False,enable_updates=False)
        try:
            deadline=time.monotonic()+3
            while w.data is None and time.monotonic()<deadline:app.processEvents();time.sleep(.005)
            assert w.data is not None
            w.watchdog.stop();w.monitor.stop();w.refresh_status_badge();app.processEvents()
            scale=float(w.windowHandle().devicePixelRatio());requested=float(os.environ.get('QT_SCALE_FACTOR','1'));assert abs(scale-requested)<.01
            def rect(value):return dict(x=value.x(),y=value.y(),width=value.width(),height=value.height())
            def save(widget,name,context):
                app.processEvents();image=widget.grab();path=args.output/(name+'.png');assert image.save(str(path),'PNG')
                images.append(dict(path=path.name,sha256=hashlib.sha256(path.read_bytes()).hexdigest(),physical_size=[image.width(),image.height()],widget_dpr=float(image.devicePixelRatio()),logical_size=[widget.width(),widget.height()],context=context))
            def dashboard():
                w.show_page('main');w.refresh_status_badge();app.processEvents()
                for view in w.candidate_views:
                    for key in ('name','tier','detail'):
                        widget=view[key];assert widget.heightForWidth(widget.width())<=widget.height()+1,(key,widget.text(),widget.size())
                if w.width()>=860 and w.height()>=470:
                    for view in w.candidate_views:
                        bounds=QtCore.QRect(view['frame'].mapTo(w.dashboard_scroll.viewport(),QtCore.QPoint()),view['frame'].size())
                        assert w.dashboard_scroll.viewport().rect().contains(bounds),(bounds,w.dashboard_scroll.viewport().rect())
                action=w.stop_button if w.state.running else w.start_button
                bounds=QtCore.QRect(action.mapTo(w,QtCore.QPoint()),action.size());assert action.isVisibleTo(w) and w.rect().contains(bounds)
            assert w.screen().availableGeometry().contains(w.frameGeometry())
            observations.append(dict(case='initial-available-area',available_logical=rect(w.screen().availableGeometry()),frame_logical=rect(w.frameGeometry()),minimum_logical=[w.minimumWidth(),w.minimumHeight()]))
            dashboard();assert not w.start_button.isEnabled();save(w,'control-unavailable','Actual offscreen unavailable state, original demo dictionary; no capture capability')
            w.capture=PresentationCapture();w.start_button.setEnabled(bool(w.data['augments'] and w.capture));dashboard()
            assert w.start_button.isEnabled();save(w,'control-ready','Injected presentation-only capture capability; enabled production Start widget, no game connection or pixels')
            hero=next(iter(data['heroes']));names=list(data['augments'])[:3]
            w.hero_auto.setChecked(False);w.hero_box.setCurrentText(hero)
            w.data['heroAugmentStats'][hero][2]['tier']=None
            w.state.start((1,1,'original-presentation-fixture'));w.state.hero=hero;w.state.confirm(names,w.data['augments'])
            for edit,name in zip(w.inputs,names):edit.setText(name)
            dashboard();assert w.stop_button.isEnabled();assert '人工选择' in w.status_chip.text();assert '暂无评级' in w.candidate_views[2]['detail'].text()
            save(w,'control-confirmed-demo','Original synthetic data and manually seeded confirmation state; enabled production Stop widget; no game or OCR execution')
            w.hero_auto.blockSignals(True);w.hero_auto.setChecked(True);w.hero_auto.blockSignals(False)
            for origin in ('client-provisional','client-verified','hud'):
                w.hero_origin=origin;dashboard();save(w,'control-'+origin,'Original synthetic identity-provenance presentation state; no game connection')
            w.hero_origin='client-provisional';w.refresh_status_badge()
            overlay=w.overlay;cards=display_cards(w.data,hero,names)
            overlay.set_cards(hero,cards,'2026-10-14','数据包 演示 / 游戏资料 演示','来自本局选人 · HUD未复核')
            for name,client in [('small-client',ClientRect(0,0,960,600)),('large-client',ClientRect(0,0,1920,1080))]:
                overlay.hide();x,y,width,height=overlay._fit_layout(client,scale);overlay.show();app.processEvents()
                assert abs(float(overlay.windowHandle().devicePixelRatio())-scale)<.01
                rows=inspect_smoke_layout(overlay);assert height<=client.height*.5
                assert 'HUD未复核' in overlay.heading.text() and overlay.heading.isVisibleTo(overlay)
                observations.append(dict(case=name,client_physical=[client.width,client.height],overlay_physical=[width,height],compact=overlay._compact,visible_labels=[row['text'] for row in rows if 'text' in row]))
                save(overlay,'overlay-'+name,'Original synthetic cards, including one missing tier and explicit provisional identity; not a game screenshot')
            overlay.hide();overlay.set_cards(hero,cards,'2026-10-14','数据包 演示 / 游戏资料 演示','英雄/候选连续高置信自动识别')
            x,y,width,height=overlay._fit_layout(ClientRect(0,0,960,600),scale);overlay.show();app.processEvents();inspect_smoke_layout(overlay)
            assert height<=300
            save(overlay,'overlay-hud-verified','Original synthetic fully confirmed HUD presentation; not an actual recognition result')
            overlay.set_rechecking(True);overlay._fit_layout(ClientRect(0,0,960,600),scale);app.processEvents()
            assert '上次候选复核中' in overlay.heading.text() and overlay.heading.isVisibleTo(overlay)
            save(overlay,'overlay-rechecking','Original synthetic previous-candidate recheck label; no live capture or freshness claim')
            overlay.hide();overlay.set_rechecking(False)
            from hero_strength import hero_strength_reference
            w.data['heroes'][hero].update(championId='9001',overallTier='T5')
            reference=hero_strength_reference(w.data,hero,champion_id='9001');assert reference['sourceTier']=='T5'
            overlay.set_hero_reference(reference);_,_,width,height=overlay._fit_layout(ClientRect(0,0,960,600),scale);overlay.show();app.processEvents()
            for widget in (overlay.heading,overlay.metadata_label,overlay.footer,*overlay._title_labels,*overlay.tier_labels):
                assert widget.isVisibleTo(overlay) and widget.heightForWidth(widget.width())<=widget.height()+1
                assert overlay.rect().contains(QtCore.QRect(widget.mapTo(overlay,QtCore.QPoint()),widget.size()))
            assert not overlay.cards and height<=300 and 'HUD未复核' in overlay.heading.text()
            save(overlay,'overlay-selection-strength','Original synthetic canonical hero with explicit demoT5; hero-only provisional reference, not augment confirmation or game evidence')
            overlay.hide();w.show_page('correction');w.details_toggle.setChecked(True);app.processEvents();save(w,'control-card-details','Read-only exact-name dictionary lookup, explicitly not current confirmation')
            w.confirm();w.invalidate_scene('Owned candidate scene disappeared');w.show_page('correction');w.details_toggle.setChecked(False);app.processEvents()
            assert w.last_candidates and not w.state.confirmed and not w.overlay.isVisible()
            w.scroll.ensureWidgetVisible(w.history_view);app.processEvents()
            save(w,'control-last-candidates','Actual separate last-candidates memory view after invalidation; final selected augment explicitly unknown')
            w.show_page('settings');save(w,'control-settings','Actual retained settings controls; presentation-only fixture')
            w.show_page('about');save(w,'control-about','Actual source version, safety limitations and update controls')
            w.invalidate_scene('Owned presentation scene invalidated');dashboard()
            assert not w.state.confirmed and w.hero_title.text()=='等待识别' and all(v['name'].text()=='等待识别' for v in w.candidate_views)
            save(w,'control-stale','Actual immediate revocation of previously seeded state; no stale hero or ratings')
            w.stop_monitor();dashboard();save(w,'control-stopped','Actual Stop handler after seeded presentation state')
            if w.screen().availableGeometry().width()>=640 and w.screen().availableGeometry().height()>=504:
                w.resize(640,440);w.fit_control_to_screen();app.processEvents();dashboard();save(w,'control-narrow','Actual640DIP narrow layout on the configured screen')
        finally:
            overlay=w.overlay;w.capture=None;w.close();deadline=time.monotonic()+3
            while w._workers and time.monotonic()<deadline:app.processEvents();time.sleep(.005)
            assert not w._workers
            overlay.deleteLater();w.deleteLater();QtCore.QCoreApplication.sendPostedEvents(None,QtCore.QEvent.Type.DeferredDelete);app.processEvents()
    after={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in SOURCE_FILES};assert before==after,'Sources changed while rendering'
    report=dict(status='passed',applicationVersion=__version__,scope='Actual original offscreen Qt widgets, injected presentation-only capability and per-process app scaling; not actual Windows/game/OCR/monitor DPI proof',qt_platform=app.platformName(),requested_scale=requested,measured_scale=scale,observations=observations,images=images,source_files=after)
    (args.output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8');print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=='__main__':main()

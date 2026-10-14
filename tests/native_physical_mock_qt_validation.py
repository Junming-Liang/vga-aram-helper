"""Qt pixel/OCR preflight for fixed-physical smoke artwork; no Windows proof."""
import json,os,sys
from pathlib import Path
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from PySide6 import QtCore,QtWidgets
from engine import load_data
from hero_recognition import PortraitMatcher,recognize_frame
from local_ocr import LocalOCR
from native_smoke import smoke_dimensions,smoke_pixmap,inspect_smoke_layout,shrink_smoke_mock
from native_state import automatic_candidates
from synthetic_vision import portraits,configure_data
app=QtWidgets.QApplication([]);widget=QtWidgets.QWidget();widget.winId()
dpr=float(widget.windowHandle().devicePixelRatio());width,height=smoke_dimensions(1024,728)
layout=QtWidgets.QVBoxLayout(widget);layout.setContentsMargins(0,0,0,0)
image=QtWidgets.QLabel();layout.addWidget(image)
bank=portraits();image.setPixmap(smoke_pixmap(bank['9001'],ROOT/'fixtures/auto-scene.png',width,height,dpr))
widget.resize(round(width/dpr),round(height/dpr));widget.show();app.processEvents()
pixels=widget.grab();assert (pixels.width(),pixels.height())==(960,600),pixels.size()
assert abs(float(pixels.devicePixelRatio())-dpr)<1e-6
buffer=QtCore.QBuffer();buffer.open(QtCore.QIODevice.OpenModeFlag.WriteOnly);assert pixels.save(buffer,'PNG')
data=configure_data(load_data(ROOT/'fixtures/demo.json'))
result=recognize_frame(bytes(buffer.data()),(.15,.25,.7,.35),LocalOCR(),data['augments'],PortraitMatcher(bank,data['heroes']))
assert result['hero_observation']['hero']=='星火术士（演示）' and result['hero_observation']['confident'],result['hero_observation']
assert [c['name'] for c in result['automatic_candidates']]==['星火共鸣','晶盾回路','风步微光'],result['automatic_candidates']
assert automatic_candidates(result['automatic_candidates'],result['image_size'])
from native_ui import Overlay
from native_state import display_cards
from screen_capture import ClientRect
overlay=Overlay();overlay.set_cards('星火术士（演示）',display_cards(data,'星火术士（演示）',['星火共鸣','晶盾回路','风步微光']),'虚构日期','数据包演示 / 游戏资料演示','高置信自动识别')
overlay._fit_layout(ClientRect(20,20,width,height),dpr);overlay.show();app.processEvents()
layout_rows=inspect_smoke_layout(overlay);assert ('来源日期' in overlay.metadata_label.text() and overlay.metadata_label.isVisibleTo(overlay) is (not overlay._compact))
overlay.tier_labels[0].resize(1,1)
try:inspect_smoke_layout(overlay)
except AssertionError:pass
else:raise AssertionError('Diagnostic accepted deliberately clipped tier label')
before=widget.size();widget.resize(before.width()-20,before.height()-20);app.processEvents()
assert widget.size()==before,'Regression premise: fixture pixmap minimum should prevent naive shrink'
shrink_smoke_mock(widget,image);assert widget.width()<before.width() and widget.height()<before.height()
widget.close();overlay.close();app.processEvents();assert not widget.isVisible() and not overlay.isVisible()
print(json.dumps({'status':'passed','scope':'Original Qt-rendered fixture and local OCR only; no Windows capture or physical monitor proof','qt_platform':app.platformName(),'requested_app_scale':float(os.environ.get('QT_SCALE_FACTOR','1')),'qwindow_dpr':dpr,'rendered_physical_size':[pixels.width(),pixels.height()],'layout_checks_passed':True,'clipped_label_rejected':True,'mock_minimum_released_and_shrunk':True,'hero':result['hero_observation']['hero'],'recognized':[c['name'] for c in result['automatic_candidates']]},ensure_ascii=False))

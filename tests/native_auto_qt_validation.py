"""Real Qt widgets and original image/OCR pipeline; not Windows capture evidence."""
import io,json,os,sys,time,tempfile
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from PySide6 import QtWidgets,QtTest
from PIL import Image
from engine import load_data
from native_ui import ControlWindow
from hero_recognition import PortraitMatcher,recognize_frame
from synthetic_vision import portraits,frame,encoded,configure_data
from local_ocr import LocalOCR
from screen_capture import CaptureUnavailable
app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([]);checks=[]
from native_smoke import smoke_dimensions
assert smoke_dimensions(1024,728)==(960,600);checks.append('Physical1024x728 work area fits fixed960x600 own-HUD mock without changing display settings')
for invalid in [(999,728),(1024,639),(True,728),(1024,728.0)]:
    try:smoke_dimensions(*invalid)
    except ValueError:pass
    else:raise AssertionError('Unsupported physical work area accepted')
with tempfile.TemporaryDirectory() as temp,patch('native_ui.Win32Capture',side_effect=CaptureUnavailable('Offscreen: no Windows capture')):
    w=ControlWindow(lambda:{'data':load_data(ROOT/'fixtures/demo.json'),'status':{}},state_dir=Path(temp),current_executable=Path('/unused.exe'),current_version='test',frozen=False,enable_updates=False)
    for _ in range(40):
        app.processEvents();QtTest.QTest.qWait(10)
        if w.data:break
    assert w.hero_auto.isChecked() and w.state.hero=='' and not w.hero_box.isEnabled();checks.append('Automatic hero is default, with no preselected hero or required manual setup')
    configure_data(w.data)
    bank=portraits();matcher=PortraitMatcher(bank,w.data['heroes']);ocr=LocalOCR()
    def observation(key):
        im=frame(bank[key]);cards=Image.open(ROOT/'fixtures/auto-scene.png').convert('RGB');im.paste(cards.crop((0,0,1280,576)),(0,0))
        started=time.monotonic();result=recognize_frame(encoded(im),(.15,.25,.7,.35),ocr,w.data['augments'],matcher);result['_capturedAt']=started;return result
    a=observation('9001');b=observation('9002');w.state.start((1,2,'synthetic'))
    def deliver(value):
        value={**value,'_capturedAt':time.monotonic()};w.task_result('ocr',value,w.state.generation)
    deliver(a);assert not w.state.confirmed and not w.state.hero
    deliver(a);assert w.state.confirmed and w.state.hero=='星火术士（演示）' and w.state.confirmation_mode=='automatic';checks.append('Actual portrait matching + CPU OCR reach production handlers; two consistent frames automatically show hero-specific tiers')
    assert [c['sourceTier'] for c in w.overlay.cards]==['T1','T2','T3'];assert w.hero_auto.isChecked() and not w.hero_box.isEnabled();checks.append('No hero dropdown or manual confirmation used on high-confidence path')
    deliver({**a,'hero_observation':{'hero':None,'confident':False}});assert not w.state.confirmed and not w.state.hero and not w.overlay.isVisible();checks.append('Unknown own-HUD portrait immediately clears hero and old tiers')
    deliver(a);deliver(a);deliver(b);assert not w.state.confirmed and not w.state.hero
    deliver(b);assert w.state.hero=='磐石守卫（演示）' and [c['sourceTier'] for c in w.overlay.cards]==['T3','T1','T2'];checks.append('Hero change clears stale state before recomputing same ordered offers')
    low={**b,'automatic_candidates':[dict(item) for item in b['automatic_candidates']]};low['automatic_candidates'][0]['ocr_confidence']=.7
    deliver(low);assert not w.state.confirmed;checks.append('Low-confidence or wrong-layout candidates cannot preserve an automatic confirmation')
    deliver(b);assert not w.state.confirmed;deliver(b);assert w.state.confirmed;checks.append('One unsafe title frame followed by only one safe frame cannot auto-confirm; two consecutive safe frames are required')
    w.inputs[0].setText('人工未确认');w.edit_changed();deliver(b);assert not w.state.confirmed and w.inputs[0].text()=='人工未确认';checks.append('In-progress manual correction is not overwritten by automatic observations')
    w.hero_auto.setChecked(False);w.hero_box.setCurrentText('星火术士（演示）')
    for edit,item in zip(w.inputs,a['automatic_candidates']):edit.setText(item['name'])
    w.confirm();assert w.state.confirmed and w.state.confirmation_mode=='manual';checks.append('Explicit manual fallback remains available when automation is uncertain')
    w.hero_auto.setChecked(True);assert w.state.hero=='' and not w.state.confirmed
    deliver(a);deliver(a);w.overlay.show();app.processEvents();w.capture_hidden(w.state.generation);assert not w.state.confirmed and not w.overlay.isVisible();checks.append('Production capture setup refuses visible own overlay even if display-affinity exclusion is absent')
    w.close();app.processEvents()
report={'status':'passed','scope':'Real Qt offscreen + original synthetic portrait/OCR pipeline only. No Windows GDI or real gameplay accuracy claim.','checks':checks}
(ROOT/'reports/native-auto-qt.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps(report,ensure_ascii=False,indent=2))

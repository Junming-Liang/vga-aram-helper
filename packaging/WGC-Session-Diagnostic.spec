# DEFAULT-OFF test-only fixture; never add it to the production VGA bundle.
from pathlib import Path
import sys
ROOT=Path(SPECPATH).parent
sys.path.insert(0,str(ROOT))
from scripts.build_wgc_session_capture import verify_built_helper,FILENAME,MANIFEST
from scripts.microsoft_runtime import replace_runtime_entries
verify_built_helper()
a=Analysis([str(ROOT/'wgc_session_diagnostic.py')],pathex=[str(ROOT)],
    binaries=[(str(ROOT/'build/native'/FILENAME),'native')],
    datas=[(str(ROOT/'build/native'/MANIFEST),'native'),
           (str(ROOT/'build/wgc-session-diagnostic/licenses'),'licenses'),
           (str(ROOT/'LICENSE'),'.'),(str(ROOT/'THIRD_PARTY_NOTICES.md'),'.')],
    hiddenimports=['PySide6.QtCore','PySide6.QtGui','PySide6.QtWidgets','PIL.Image',
                   'PIL.ImageDraw','PIL.ImageChops','PIL.ImageStat'],
    excludes=['numpy','cv2','rapidocr','onnxruntime','torch','tensorflow','paddle',
              'PySide6.QtWebEngineCore','PySide6.QtWebEngineWidgets','PySide6.QtPdf',
              'PySide6.QtPdfWidgets','tkinter'],noarchive=False)
a.binaries=[entry for entry in a.binaries if Path(entry[0]).name.lower() not in
    {'opengl32sw.dll','d3dcompiler_47.dll','qopensslbackend.dll','qpdf.dll','qtuiotouchplugin.dll'}]
a.binaries=replace_runtime_entries(a.binaries)
pyz=PYZ(a.pure)
exe=EXE(pyz,a.scripts,a.binaries,a.datas,[],name='WGC-Session-Diagnostic',
    debug=False,bootloader_ignore_signals=False,strip=False,upx=False,
    manifest=str(ROOT/'packaging/windows.manifest'),console=True,
    target_arch='x86_64',runtime_tmpdir=None,uac_admin=False,uac_uiaccess=False)

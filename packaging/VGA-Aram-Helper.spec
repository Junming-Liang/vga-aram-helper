# -*- mode: python ; coding: utf-8 -*-
# Build this only on native Windows x64, using the pinned build environment.
from pathlib import Path
import sys
from PyInstaller.utils.hooks import collect_data_files, copy_metadata

ROOT = Path(SPECPATH).parent
sys.path.insert(0, str(ROOT))
from model_inventory import verify_models
from scripts.microsoft_runtime import replace_runtime_entries
from scripts.build_wgc_capture import verify_built_helper, FILENAME as WGC_FILENAME, MANIFEST as WGC_MANIFEST
from scripts.build_wgc_session_capture import (verify_built_helper as verify_session_helper,
                                               FILENAME as SESSION_FILENAME, MANIFEST as SESSION_MANIFEST)
from scripts.windows_package import BRANDING_FILES, EXCLUDED_IMPORTS, CUSTOM_EXCLUDED_IMPORTS, custom_package, trim_unused_binaries
import json
verify_models()  # Missing/changed wheel models fail the build, never download at runtime.

verify_built_helper()  # No optional omission or runtime download of either capture helper.
verify_session_helper()
binaries = [(str(ROOT / 'build' / 'native' / name), 'native')
            for name in (WGC_FILENAME, SESSION_FILENAME)]
datas = [(str(ROOT / 'assets' / 'riotgames.pem'), 'assets'), (str(ROOT / 'build' / 'native' / WGC_MANIFEST), 'native'),
         (str(ROOT / 'build' / 'native' / SESSION_MANIFEST), 'native'),
         (str(ROOT / 'static'), 'static'), (str(ROOT / 'fixtures'), 'fixtures'),
         (str(ROOT / 'build' / 'licenses'), 'licenses'), (str(ROOT / 'LICENSE'), '.'), *[(str(ROOT / 'assets' / 'branding' / name), 'assets/branding') for name in BRANDING_FILES]]
hiddenimports = ['badge_contract', 'source_combo_hints', 'hero_identity_continuity', 'monitor_preferences', 'card_title_proof', 'augment_card_geometry', 'card_badges', 'frame_inference_worker', 'partial_candidates', 'public_payload', 'lcu_selection', 'live_client_identity', 'server', 'engine', 'local_ocr', 'model_inventory', 'app_version', 'updates', 'data_updates', 'update_network', 'native_ui', 'portrait_display', 'local_debug', 'owned_diagnostic_json', 'wgc_visible_overlay_smoke', 'native_state', 'overlay_geometry', 'screen_capture', 'native_smoke', 'hero_portraits', 'hero_recognition', 'champion_select', 'selection_session', 'session_windows', 'selection_smoke', 'wgc_capture', 'wgc_smoke', 'wgc_session_capture', 'wgc_session_smoke', 'persistent_capture_adapter']
# RapidOCR exports RapidOCR lazily, so explicitly retain its entry point and
# CPU backend. Normal import analysis then follows their real dependencies.
# Data collection excludes duplicate .py source, while preserving all wheel
# model/config/dictionary files. Models are unchanged and hash-checked above.
hiddenimports += ['rapidocr.main', 'rapidocr.inference_engine.onnxruntime']
datas += collect_data_files('rapidocr', include_py_files=False)
datas += collect_data_files('certifi')
if custom_package():
    datas += copy_metadata('opencv-python-headless')
for distribution in ('rapidocr', 'onnxruntime', 'numpy', 'Pillow', 'PySide6-Essentials', 'shiboken6'):
    datas += copy_metadata(distribution)
# Maintained PyInstaller hooks collect the ONNX, OpenCV, NumPy and geometry
# native dependencies; do not collect ORT training/export tools or test data.

a = Analysis([str(ROOT / 'launcher.py')], pathex=[str(ROOT)], binaries=binaries, datas=datas,
             hiddenimports=hiddenimports, hookspath=[], hooksconfig={}, runtime_hooks=[],
             excludes=['torch', 'paddle', 'tensorflow', 'openvino', 'tensorrt', 'tkinter', 'PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets', 'PySide6.QtWebEngineQuick', 'PySide6.QtPdf', 'PySide6.QtPdfWidgets', *EXCLUDED_IMPORTS, *(CUSTOM_EXCLUDED_IMPORTS if custom_package() else ())], noarchive=False)
# Our ordinary QWidget painters use the raster backend. Do not distribute Qt's
# optional software-OpenGL fallback or Microsoft shader compiler; neither is
# needed by this UI. Native Windows acceptance tests exercise this exact bundle.
# Keep Qt's required Network dependency with its native Windows/certificate
# backends, but omit the unused OpenSSL and PDF plugins. Application HTTPS uses
# Python's separately bundled SSL runtime, not Qt's optional OpenSSL backend.
# TUIO network touch input is unused by the mouse-driven overlay/control window.
a.binaries = [entry for entry in a.binaries
              if Path(entry[0]).name.lower() not in {'opengl32sw.dll', 'd3dcompiler_47.dll',
                  'qopensslbackend.dll', 'qpdf.dll', 'qt6pdf.dll', 'qt6pdfwidgets.dll',
                  'qtuiotouchplugin.dll'}]
# Use only the signed, unmodified release CRT supplied by the Community product
# installed for this build, consistently replacing root and package duplicates.
a.binaries = replace_runtime_entries(a.binaries)
# The retained PE import graph must not depend on any newly removed binary.
# Actual Windows frozen-EXE tests also cover the dynamically loaded CPU backend.
a.binaries, pruning = trim_unused_binaries(a.binaries)
(ROOT / 'build' / 'windows-packaging-prune.json').write_text(
    json.dumps(pruning, indent=2) + '\n', encoding='utf-8')
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name='VGA-Aram-Helper',
          debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
          icon=str(ROOT / 'assets' / 'branding' / 'vga.ico'),
          version=str(ROOT / 'build' / 'version_info.txt'),
          manifest=str(ROOT / 'packaging' / 'windows.manifest'),
          console=False, disable_windowed_traceback=False, target_arch='x86_64',
          runtime_tmpdir=None, uac_admin=False, uac_uiaccess=False)

# -*- mode: python ; coding: utf-8 -*-
# Build this only on native Windows x64, using the pinned build environment.
from pathlib import Path
import sys
from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_dynamic_libs, copy_metadata

ROOT = Path(SPECPATH).parent
sys.path.insert(0, str(ROOT))
from model_inventory import verify_models
verify_models()  # Missing/changed wheel models fail the build, never download at runtime.

binaries = []
datas = [(str(ROOT / 'static'), 'static'), (str(ROOT / 'fixtures'), 'fixtures'),
         (str(ROOT / 'build' / 'licenses'), 'licenses'), (str(ROOT / 'LICENSE'), '.'), (str(ROOT / 'assets' / 'branding'), 'assets/branding')]
hiddenimports = ['server', 'engine', 'local_ocr', 'model_inventory', 'app_version', 'updates', 'data_updates', 'update_network', 'native_ui', 'native_state', 'screen_capture', 'native_smoke']
# Includes RapidOCR config, dictionaries, three ONNX models and package metadata.
# Optional CUDA/Paddle/Torch engines are not dependencies of the chosen CPU runtime.
for package in ('rapidocr', 'onnxruntime'):
    package_datas, package_binaries, package_hidden = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hidden
datas += collect_data_files('certifi')
for distribution in ('rapidocr', 'onnxruntime', 'numpy', 'Pillow', 'PySide6-Essentials', 'shiboken6'):
    datas += copy_metadata(distribution)
# ONNX Runtime, OpenCV, NumPy, Shapely and PyClipper native DLLs are also handled by
# PyInstaller's maintained hooks; explicit ONNX collection prevents hidden providers.
binaries += collect_dynamic_libs('onnxruntime')

a = Analysis([str(ROOT / 'launcher.py')], pathex=[str(ROOT)], binaries=binaries, datas=datas,
             hiddenimports=hiddenimports, hookspath=[], hooksconfig={}, runtime_hooks=[],
             excludes=['torch', 'paddle', 'tensorflow', 'openvino', 'tensorrt', 'tkinter', 'PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets', 'PySide6.QtWebEngineQuick'], noarchive=False)
# Our ordinary QWidget painters use the raster backend. Do not distribute Qt's
# optional software-OpenGL fallback or Microsoft shader compiler; neither is
# needed by this UI. Native Windows acceptance tests exercise this exact bundle.
a.binaries = [entry for entry in a.binaries
              if Path(entry[0]).name.lower() not in {'opengl32sw.dll', 'd3dcompiler_47.dll'}]
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name='VGA-Aram-Helper',
          debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
          icon=str(ROOT / 'assets' / 'branding' / 'vga.ico'),
          version=str(ROOT / 'build' / 'version_info.txt'),
          manifest=str(ROOT / 'packaging' / 'windows.manifest'),
          console=False, disable_windowed_traceback=False, target_arch='x86_64',
          runtime_tmpdir=None, uac_admin=False, uac_uiaccess=False)

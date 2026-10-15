"""Fail-closed official/custom OpenCV gate, run in separate Python processes.

Usage (the caller installs the appropriate wheel before EACH generate command):
  python scripts/probe_opencv_parity.py generate --output baseline.json
  python scripts/probe_opencv_parity.py generate --output candidate.json
  python scripts/probe_opencv_parity.py compare baseline.json candidate.json --output comparison.json

The default comparison requires official 5.0.0.93 and custom 5.0.0.93+vga1 on
one Windows host. --allow-non-windows is for diagnostic runs only. Hashes cover
array dtype, shape and all raw bytes: no numeric tolerance is silently accepted.
Only elapsed_seconds is excluded from full OCR results. Timing is a repeated,
warmed, same-host regression screen, not a proof for every image, CPU or load.
No genuine gameplay images, user screenshots, downloads or cloud APIs are used.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import importlib
import importlib.metadata
import io
import json
import math
import os
from pathlib import Path
import pkgutil
import platform
import re
import statistics
import sys
import time
import uuid
import zlib

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SCHEMA_VERSION = 1
# Stable for this imported process, unlike per-report IDs. Numeric PIDs can be
# reused by the OS or identical in distinct executor PID namespaces.
PROCESS_NONCE = str(uuid.uuid4())
# Fail-closed diagnostics retain an owned fixture until this standalone probe
# exits if a daemon capture worker/helper has not confirmed cleanup. Never
# destroy its HWND or start another capture while that uncertainty remains.
_RETAINED_CAPTURE_FIXTURES = []
OFFICIAL_VERSION = '5.0.0.93'
CUSTOM_VERSION = '5.0.0.93+vga1'
CUSTOM_MODULES = {'core', 'flann', 'geometry', 'imgcodecs', 'imgproc', 'python3'}
FORMATS = {'PNG': '.png', 'JPEG': '.jpg', 'WEBP': '.webp', 'BMP': '.bmp'}
ICC_FORMATS = ('PNG', 'JPEG', 'WEBP')  # Pillow BMP does not preserve ICC profiles.
PERFORMANCE_CASES = {'resize_area_u8', 'resize_linear_u8', 'resize_cubic_f32',
                     'match_template_u8', 'match_template_f32', 'ocr_app_demo', 'hero_1080p'}
OCR_CASES = {'ocr-synthetic.png', 'ocr-blank.png', 'ocr-app-demo.png', *FORMATS,
             *(f'{name}-ICC' for name in ICC_FORMATS)}
HERO_CASES = {'1280x720', '1920x1080', '2560x1440', '3440x1440',
              'sidebar', 'gray', 'blank', 'portrait'}
FIXTURE_NAMES = ['珠光护手', '炼狱导管', '双刀流']
DEMO_NAMES = ['星火共鸣（演示）', '晶盾回路（演示）', '风步微光（演示）']
SOURCE_FILES = ('local_ocr.py', 'hero_recognition.py', 'synthetic_vision.py',
                'model_inventory.py', 'ocr_privacy.py', 'screen_capture.py', 'scripts/probe_opencv_parity.py',
                'wgc_capture.py', 'wgc_session_capture.py', 'persistent_capture_adapter.py', 'session_windows.py',
                'native/wgc_capture.cpp', 'native/wgc_session_capture.cpp',
                'scripts/build_wgc_capture.py', 'scripts/build_wgc_session_capture.py', 'scripts/probe_capture_phases.py')
DEPENDENCIES = ('numpy', 'Pillow', 'rapidocr', 'onnxruntime')
SCOPE = ('Exact deterministic sample parity and same-host warmed regression screen only; '
         'not proof for all screenshots, CPU families, real gameplay accuracy, or performance. '
         'A passing result does not replace packaged Windows GUI/OCR/hero checks.')
# Standard sRGB profile produced by LittleCMS, with a fixed 2020-01-01 header.
# Its copyright tag permits free use. Embedding avoids a runtime ImageCms dependency.
SRGB_ICC = base64.b64decode(
    'AAACTGxjbXMEQAAAbW50clJHQiBYWVogB+QAAQABAAAAAAAAYWNzcEFQUEwAAAAAAAAAAAAAAAAA'
    'AAAAAAAAAAAAAAAAAPbWAAEAAAAA0y1sY21zAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA'
    'AAAAAAAAAAAAAAAAAAAAAAALZGVzYwAAAQgAAAA2Y3BydAAAAUAAAABMd3RwdAAAAYwAAAAUY2hh'
    'ZAAAAaAAAAAsclhZWgAAAcwAAAAUYlhZWgAAAeAAAAAUZ1hZWgAAAfQAAAAUclRSQwAAAggAAAAg'
    'Z1RSQwAAAggAAAAgYlRSQwAAAggAAAAgY2hybQAAAigAAAAkbWx1YwAAAAAAAAABAAAADGVuVVMA'
    'AAAaAAAAHABzAFIARwBCACAAYgB1AGkAbAB0AC0AaQBuAABtbHVjAAAAAAAAAAEAAAAMZW5VUwAA'
    'ADAAAAAcAE4AbwAgAGMAbwBwAHkAcgBpAGcAaAB0ACwAIAB1AHMAZQAgAGYAcgBlAGUAbAB5WFla'
    'IAAAAAAAAPbWAAEAAAAA0y1zZjMyAAAAAAABDEIAAAXe///zJQAAB5MAAP2Q///7of///aIAAAPc'
    'AADAblhZWiAAAAAAAABvoAAAOPUAAAOQWFlaIAAAAAAAACSfAAAPhAAAtsNYWVogAAAAAAAAYpcA'
    'ALeHAAAY2XBhcmEAAAAAAAMAAAACZmYAAPKnAAANWQAAE9AAAApbY2hybQAAAAAAAwAAAACj1wAA'
    'VHsAAEzNAACZmgAAJmYAAA9c')


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def snapshot(value, np):
    """Exact array/scalar record, including floating signed zero and byte order."""
    if isinstance(value, np.ndarray):
        return {'shape': list(value.shape), 'dtype': value.dtype.str,
                'bytes': value.nbytes, 'sha256': sha256(value.tobytes(order='C'))}
    if isinstance(value, np.generic):
        return snapshot(np.asarray(value), np)
    if isinstance(value, (tuple, list)):
        return [snapshot(item, np) for item in value]
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError('Non-finite API result')
        return {'float64_hex': value.hex()}
    return value


def expected_api_cases():
    keys = {'COLOR_RGB2GRAY', 'COLOR_RGB2HSV', 'COLOR_RGB2BGR', 'COLOR_GRAY2BGR',
            'COLOR_BGRA2BGR', 'COLOR_RGBA2BGR', 'rotate180', 'bitwise_not',
            'bitwise_and', 'add', 'BORDER_CONSTANT', 'BORDER_REPLICATE', 'fillPoly',
            'dilate', 'mean', 'Canny', 'contours', 'hierarchy', 'boundingRects',
            'minAreaRect', 'boxPoints', 'perspectiveMatrix', 'invert',
            'warp-INTER_CUBIC', 'warp-INTER_LINEAR', 'polylines', 'putText'}
    keys.update(f'resize-{dtype}-{interp}-{width}x{height}' for dtype in ('u8', 'f32')
                for interp in ('INTER_LINEAR', 'INTER_CUBIC', 'INTER_AREA')
                for width, height in ((58, 97), (427, 201)))
    keys.update(f'{operation}-{size}' for size in (20, 32, 48)
                for operation in ('matchTemplate', 'minMaxLoc'))
    keys.update(f'{operation}-{fmt}' for fmt in FORMATS
                for operation in ('imdecode', 'imencode', 'imencode-decoded'))
    keys.update(f'imdecode-{fmt}-ICC' for fmt in ICC_FORMATS)
    for shape in ('73x119x3', '601x1069x3', '720x1280x3'):
        keys.update(f'numeric/{shape}_{color}' for color in ('gray', 'hsv', 'bgr'))
        keys.update(f'numeric/{shape}_{interp}_{ratio}' for interp in ('area', 'linear', 'cubic')
                    for ratio in (0.37, 1.13))
    keys.update('numeric/' + name for name in ('match_u8', 'match_f32', 'minmax_u8',
                'minmax_f32', 'geometry', 'edges', 'contours', 'bounding', 'box',
                'dilate', 'masked_mean', 'border', 'rotate', 'perspective', 'inverse', 'warp'))
    keys.update('numeric/codec' + ext for ext in FORMATS.values())
    keys.update('performance/' + key for key in PERFORMANCE_CASES if key.startswith(('resize_', 'match_')))
    return keys


def expected_input_cases():
    return (set(SOURCE_FILES) | {'api-' + fmt for fmt in FORMATS}
            | {'api-' + fmt + '-ICC' for fmt in ICC_FORMATS}
            | {'ocr/' + name for name in OCR_CASES} | {'hero/' + name for name in HERO_CASES})


def valid_snapshot(value):
    if isinstance(value, list):
        return all(valid_snapshot(item) for item in value)
    if isinstance(value, dict):
        if set(value) == {'float64_hex'}:
            try:
                return math.isfinite(float.fromhex(value['float64_hex']))
            except (ValueError, TypeError):
                return False
        if set(value) != {'shape', 'dtype', 'bytes', 'sha256'}:
            return False
        dtype = re.fullmatch(r'[<>=|][biufc?](\d+)', str(value['dtype']))
        shape = value['shape']
        return bool(dtype and isinstance(shape, list)
                    and all(type(size) is int and size >= 0 for size in shape)
                    and type(value['bytes']) is int
                    and value['bytes'] == math.prod(shape) * int(dtype.group(1))
                    and re.fullmatch('[0-9a-f]{64}', str(value['sha256'])))
    return value is None or type(value) in (int, bool, str)


def performance_output(report, name):
    if name.startswith(('resize_', 'match_')):
        return report['api_results']['performance/' + name]
    if name == 'ocr_app_demo':
        return report['ocr_results']['ocr-app-demo.png']
    if name == 'hero_1080p':
        return report['hero_results']['1920x1080']
    raise ValueError('No saved correctness result for performance case: ' + name)


def parse_build_information(text):
    """Extract advertised settings, without treating Python package names as modules."""
    def field(name):
        match = re.search(r'^\s*' + re.escape(name) + r':\s*(.*?)\s*$', text, re.M)
        return match.group(1) if match else None
    release = [field('C++ flags (Release)'), field('C flags (Release)')]
    flags = ' '.join(value or '' for value in release)
    fast_flags = re.findall(r'(?i)(?:/fp:fast|-ffast-math|-Ofast|-funsafe-math-optimizations|'
                            r'-fassociative-math|-freciprocal-math)', flags)
    codecs = {}
    for name in ('JPEG', 'PNG', 'WEBP'):
        value = field(name)
        version = re.search(r'\(ver\s+(.+?)\)', value or '')
        codecs[name] = {'enabled': bool(value and not value.startswith('NO')),
                        'version': version.group(1) if version else None,
                        'reported': value}
    return {'modules': sorted((field('To be built') or '').split()),
            'cpu_baseline': sorted((field('Baseline') or '').split()),
            'cpu_dispatch': sorted((field('Dispatched code generation') or '').split()),
            'ipp': field('Intel IPP'), 'ipp_iw': field('Intel IPP IW'),
            'opencl': field('OpenCL'), 'jpeg_simd': field('SIMD Support'),
            'jpeg_simd_requested': field('SIMD Support Request'),
            'algorithm_hint': field('Algorithm Hint'), 'custom_hal': field('Custom HAL'),
            'parallel_framework': field('Parallel framework'), 'codecs': codecs,
            'png_metadata': field('Metadata Support'),
            'floating_point': {'release_flags_present': all(release),
                               'precise': bool(all(release) and not fast_flags),
                               'explicit_precise': bool(re.search(r'(?i)/fp:(?:precise|strict)\b', flags)),
                               'fast_flags': fast_flags},
            'release_flags': release}


def encoded_image(image, fmt, *, icc=False):
    output = io.BytesIO()
    image.save(output, format=fmt, **({'icc_profile': SRGB_ICC} if icc else {}))
    raw = output.getvalue()
    if icc:
        from PIL import Image
        with Image.open(io.BytesIO(raw)) as reopened:
            if reopened.info.get('icc_profile') != SRGB_ICC:
                raise RuntimeError(f'{fmt} did not preserve the ICC fixture')
    return raw


def api_corpus(cv, np, Image, inputs):
    output = {}
    def snap(name, data):
        output[name] = snapshot(data, np)
    rng = np.random.default_rng(2349781)
    rgb = rng.integers(0, 256, (173, 271, 3), dtype=np.uint8)
    for code in ('COLOR_RGB2GRAY', 'COLOR_RGB2HSV', 'COLOR_RGB2BGR'):
        snap(code, cv.cvtColor(rgb, getattr(cv, code)))
    gray = cv.cvtColor(rgb, cv.COLOR_RGB2GRAY)
    rgba = np.dstack((rgb, rng.integers(0, 256, gray.shape, dtype=np.uint8)))
    for code, source in (('COLOR_GRAY2BGR', gray), ('COLOR_BGRA2BGR', rgba), ('COLOR_RGBA2BGR', rgba)):
        snap(code, cv.cvtColor(source, getattr(cv, code)))
    for dtype, source in (('u8', rgb), ('f32', rgb.astype(np.float32) / 255)):
        for name in ('INTER_LINEAR', 'INTER_CUBIC', 'INTER_AREA'):
            for width, height in ((58, 97), (427, 201)):
                snap(f'resize-{dtype}-{name}-{width}x{height}',
                     cv.resize(source, (width, height), interpolation=getattr(cv, name)))
    snap('rotate180', cv.rotate(rgb, cv.ROTATE_180))
    snap('bitwise_not', cv.bitwise_not(gray))
    snap('bitwise_and', cv.bitwise_and(rgb, rgb))
    snap('add', cv.add(rgb, cv.bitwise_not(rgb)))
    for name in ('BORDER_CONSTANT', 'BORDER_REPLICATE'):
        snap(name, cv.copyMakeBorder(rgb, 9, 13, 5, 7, getattr(cv, name)))
    mask = np.zeros(gray.shape, np.uint8)
    points = np.array([[13, 20], [252, 31], [222, 142], [22, 161]], np.int32)
    cv.fillPoly(mask, [points], 255)
    snap('fillPoly', mask)
    snap('dilate', cv.dilate(mask, np.ones((3, 3), np.uint8)))
    snap('mean', cv.mean(rgb, mask))
    edges = cv.Canny(gray, 35, 100)
    snap('Canny', edges)
    contours, hierarchy = cv.findContours(edges, cv.RETR_LIST, cv.CHAIN_APPROX_SIMPLE)
    snap('contours', contours)
    snap('hierarchy', hierarchy)
    snap('boundingRects', [cv.boundingRect(c) for c in contours])
    rect = cv.minAreaRect(points)
    snap('minAreaRect', rect)
    snap('boxPoints', cv.boxPoints(rect))
    source = np.array([[3, 11], [245, 0], [269, 162], [5, 167]], np.float32)
    dest = np.array([[0, 0], [219, 0], [219, 119], [0, 119]], np.float32)
    matrix = cv.getPerspectiveTransform(source, dest)
    snap('perspectiveMatrix', matrix)
    snap('invert', cv.invert(matrix))
    for name in ('INTER_CUBIC', 'INTER_LINEAR'):
        snap('warp-' + name, cv.warpPerspective(rgb, matrix, (220, 120),
                                              flags=getattr(cv, name), borderMode=cv.BORDER_REPLICATE))
    canvas = rgb.copy()
    cv.polylines(canvas, [points], True, (0, 120, 255), 2)
    snap('polylines', canvas)
    cv.putText(canvas, 'RapidOCR123', (7, 45), cv.FONT_HERSHEY_SIMPLEX, 1.0, (255, 0, 0), 2)
    snap('putText', canvas)
    for size in (20, 32, 48):
        template = cv.resize(gray[32:63, 51:82], (size, size), interpolation=cv.INTER_AREA)
        scores = cv.matchTemplate(gray, template, cv.TM_CCOEFF_NORMED)
        snap('matchTemplate-' + str(size), scores)
        snap('minMaxLoc-' + str(size), cv.minMaxLoc(scores))
    for fmt, ext in FORMATS.items():
        raw = encoded_image(Image.fromarray(rgb), fmt)
        inputs['api-' + fmt] = sha256(raw)
        snap('imdecode-' + fmt, cv.imdecode(np.frombuffer(raw, np.uint8), cv.IMREAD_COLOR))
        ok, encoded = cv.imencode(ext, rgb)
        if not ok:
            raise RuntimeError(f'OpenCV {fmt} encoding failed')
        snap('imencode-' + fmt, encoded)
        snap('imencode-decoded-' + fmt, cv.imdecode(encoded, cv.IMREAD_COLOR))
        if fmt in ICC_FORMATS:
            raw = encoded_image(Image.fromarray(rgb), fmt, icc=True)
            inputs['api-' + fmt + '-ICC'] = sha256(raw)
            snap('imdecode-' + fmt + '-ICC', cv.imdecode(np.frombuffer(raw, np.uint8), cv.IMREAD_COLOR))

    # Independent reviewer's larger numerical corpus, with contours grouped only
    # to give the manifest stable names. Every contour/box/rectangle is retained.
    numeric = {}
    rng = np.random.default_rng(0x564741)
    for shape in ((73, 119, 3), (601, 1069, 3), (720, 1280, 3)):
        name = 'x'.join(map(str, shape))
        pixels = rng.integers(0, 256, shape, dtype=np.uint8)
        for color in ('gray', 'hsv', 'bgr'):
            numeric[name + '_' + color] = cv.cvtColor(pixels, getattr(cv, 'COLOR_RGB2' + color.upper()))
        for interp, label in ((cv.INTER_AREA, 'area'), (cv.INTER_LINEAR, 'linear'), (cv.INTER_CUBIC, 'cubic')):
            for ratio in (0.37, 1.13):
                size = (max(1, round(shape[1] * ratio)), max(1, round(shape[0] * ratio)))
                numeric[f'{name}_{label}_{ratio}'] = cv.resize(pixels, size, interpolation=interp)
    small = numeric['73x119x3_gray']
    template = small[19:43, 25:51].copy()
    for pixels, label in ((small, 'u8'), (small.astype(np.float32) / 255, 'f32')):
        templ = template if label == 'u8' else template.astype(np.float32) / 255
        scores = cv.matchTemplate(pixels, templ, cv.TM_CCOEFF_NORMED)
        numeric['match_' + label] = scores
        mn, mx, ml, xl = cv.minMaxLoc(scores)
        numeric['minmax_' + label] = np.asarray([mn, mx, *ml, *xl], dtype=np.float64)
    geometry = np.zeros((163, 277), dtype=np.uint8)
    cv.fillPoly(geometry, [np.array([[5, 11], [244, 19], [220, 103], [20, 125]], np.int32)], 255)
    cv.fillPoly(geometry, [np.array([[70, 55], [85, 57], [84, 64], [70, 62]], np.int32)], 0)
    numeric['geometry'] = geometry
    edges = cv.Canny(geometry, 35, 100)
    numeric['edges'] = edges
    contours, _ = cv.findContours(edges, cv.RETR_LIST, cv.CHAIN_APPROX_SIMPLE)
    numeric['contours'] = contours
    numeric['bounding'] = [np.array(cv.boundingRect(c)) for c in contours]
    numeric['box'] = [cv.boxPoints(cv.minAreaRect(c)) for c in contours]
    numeric['dilate'] = cv.dilate(geometry, np.ones((3, 3), np.uint8))
    numeric['masked_mean'] = np.asarray(cv.mean(numeric['73x119x3_bgr'], (small > 125).astype(np.uint8)), dtype=np.float64)
    numeric['border'] = cv.copyMakeBorder(small, 3, 5, 9, 11, cv.BORDER_CONSTANT, value=17)
    numeric['rotate'] = cv.rotate(small, cv.ROTATE_180)
    source = np.asarray([[3, 8], [102, 2], [113, 67], [9, 71]], np.float32)
    dest = np.asarray([[0, 0], [99, 0], [99, 47], [0, 47]], np.float32)
    matrix = cv.getPerspectiveTransform(source, dest)
    numeric['perspective'] = matrix
    numeric['inverse'] = cv.invert(matrix)[1]
    numeric['warp'] = cv.warpPerspective(numeric['73x119x3_bgr'], matrix, (100, 48),
                                         flags=cv.INTER_CUBIC, borderMode=cv.BORDER_REPLICATE)
    for ext in FORMATS.values():
        ok, data = cv.imencode(ext, numeric['73x119x3_bgr'])
        if not ok:
            raise RuntimeError(f'OpenCV {ext} encoding failed')
        numeric['codec' + ext] = cv.imdecode(data, cv.IMREAD_COLOR)
    for name, value in numeric.items():
        snap('numeric/' + name, value)
    return output


def without_ocr_time(result):
    output = dict(result)
    output.pop('elapsed_seconds', None)
    return output


def benchmark(operation, *, samples, warmups, iterations, fingerprint):
    expected = None
    timings = []
    for sample in range(warmups + samples):
        elapsed = 0.0
        for _ in range(iterations):
            start = time.perf_counter()
            result = operation()
            elapsed += time.perf_counter() - start
            # Verify all warmed/measured results outside the measured interval.
            actual = canonical(fingerprint(result))
            if expected is None:
                expected = actual
            elif actual != expected:
                raise RuntimeError('Repeated operation changed its exact output')
        if sample >= warmups:
            timings.append(elapsed / iterations)
    return {'samples_seconds': timings, 'median_seconds': statistics.median(timings),
            'min_seconds': min(timings), 'max_seconds': max(timings),
            'warmups': warmups, 'iterations_per_sample': iterations,
            'output_sha256': sha256(expected.encode('utf-8'))}


def capture_benchmark(*, samples, warmups):
    """Measure normal bounded capture of this process's own synthetic window only."""
    if _RETAINED_CAPTURE_FIXTURES:
        raise RuntimeError('Prior capture cleanup is unconfirmed; refusing a replacement fixture')
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QPainter
    from PySide6.QtWidgets import QApplication, QWidget
    from screen_capture import Win32Capture
    from scripts import probe_capture_phases as phases

    class FixtureWindow(QWidget):
        def paintEvent(self, event):
            painter = QPainter(self)
            painter.fillRect(self.rect(), QColor(24, 42, 62))
            painter.scale(self.width() / 960, self.height() / 640)
            for index, color in enumerate(('#d77528', '#64b2a8', '#9450c7', '#c9c741')):
                painter.fillRect(40 + index * 215, 50 + index * 90, 170, 140, QColor(color))
            painter.end()

    app = QApplication.instance() or QApplication([])
    if app.platformName() != 'windows':
        raise RuntimeError('Capture latency requires the real Windows Qt platform')
    screen = app.primaryScreen()
    if screen is None:
        raise RuntimeError('Capture latency requires an interactive Windows desktop')
    dpr = float(screen.devicePixelRatio())
    window = FixtureWindow()
    window.setWindowTitle('VGA original synthetic capture performance fixture')
    window.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)
    window.setWindowFlag(Qt.WindowType.FramelessWindowHint)
    window.setFixedSize(round(960 / dpr), round(640 / dpr))
    area = screen.availableGeometry()
    window.move(area.x() + round(20 / dpr), area.y() + round(20 / dpr))
    window.show()
    window.raise_()
    window.activateWindow()
    safe_to_close = True
    capture = None
    try:
        for _ in range(5):
            app.processEvents()
            time.sleep(0.05)
        if not area.contains(window.frameGeometry()):
            raise RuntimeError('The desktop cannot contain the entire own-process capture fixture')
        capture = Win32Capture()
        target = capture.info(int(window.winId()))
        if target.pid != os.getpid():
            raise RuntimeError('Capture fixture does not belong to this process')
        initial = capture.validate(target)
        diagnostic = {'schema_version': 1, 'status': 'failed', 'errors': [],
                      'authoritative_observations': [], 'expected_output': None,
                      'expected_client_rect': [initial.x, initial.y, initial.width, initial.height]}
        bound_helper = getattr(capture, '_wgc', None)
        def identity(label):
            try:
                diagnostic[label] = phases.identity_snapshot(ROOT, bound_helper)
            except Exception as error:
                diagnostic[label] = None
                diagnostic['errors'].append({'stage': label, **phases.error_record(error)})
        def fingerprint(value):
            raw, rect = value
            output = {'image_sha256': sha256(raw), 'width': rect.width, 'height': rect.height}
            # benchmark() calls this only AFTER stopping the operation timer.
            diagnostic['authoritative_observations'].append(phases.observation(capture))
            if diagnostic['expected_output'] is None:
                diagnostic['expected_output'] = output
            return output
        result = benchmark(lambda: capture.capture(target), samples=samples, warmups=warmups,
                           iterations=3, fingerprint=fingerprint)
        result['fixture'] = {'kind': 'own-process synthetic painted Qt window',
                             'width': initial.width, 'height': initial.height,
                             'device_pixel_ratio': dpr,
                             'qt_version': importlib.metadata.version('PySide6-Essentials')}
        # Tracing is installed only after all original warmed/measured operations.
        # A diagnostic failure retains those original raw samples for inspection.
        identity('identity_before_supplemental')
        try:
            diagnostic['supplemental'] = (phases.skipped_supplemental(capture) if diagnostic['errors'] else
                phases.run_supplemental(capture, target, diagnostic['expected_output'], app.processEvents))
        except Exception as error:
            diagnostic['supplemental'] = {'status': 'failed'}
            diagnostic['errors'].append({'stage': 'supplemental', **phases.error_record(error)})
        safe_to_close = diagnostic['supplemental'].get('safe_to_close_fixture') is True
        identity('identity_after_supplemental')
        diagnostic['status'] = 'passed' if (not diagnostic['errors']
            and diagnostic['supplemental']['status'] == 'passed') else 'failed'
        result['capture_diagnostics'] = diagnostic
        if safe_to_close:
            capture.close()
        return result
    finally:
        # Includes failure in an original authoritative call, before diagnostics.
        if capture is not None and phases.observation(capture)['cleanup_pending'] is not False:
            safe_to_close = False
        if safe_to_close:
            window.close()
            app.processEvents()
        else:
            _RETAINED_CAPTURE_FIXTURES.append((app, window, capture))


def collect_metadata(cv):
    build = cv.getBuildInformation()
    native = getattr(cv, '_native', cv)
    binary = Path(native.__file__).resolve()
    if binary.suffix.lower() not in {'.pyd', '.so'}:
        raise RuntimeError(f'Cannot identify the loaded OpenCV extension: {binary}')
    data = binary.read_bytes()
    imported, errors = [], []
    for info in pkgutil.walk_packages(cv.__path__, cv.__name__ + '.'):
        if info.name in {'cv2.config', 'cv2.config-3', 'cv2.cv2'}:
            continue
        try:
            importlib.import_module(info.name)
            imported.append(info.name)
        except Exception as exc:
            errors.append({'module': info.name, 'error': repr(exc)})
    installed = {}
    for name in ('opencv-python-headless', 'opencv-python', 'opencv-contrib-python', 'opencv-contrib-python-headless'):
        try:
            installed[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            pass
    return {'cv_version': cv.__version__, 'distributions': installed,
            'cv_file': cv.__file__, 'build_information': build,
            'build_features': parse_build_information(build),
            'binary': {'path': str(binary), 'sha256': sha256(data), 'raw_bytes': len(data),
                       'zlib9_bytes': len(zlib.compress(data, 9))},
            'imported_python_submodules': sorted(imported), 'import_errors': errors,
            'exported_native_namespaces': sorted(name for name, value in vars(native).items()
                                                 if type(value).__name__ == 'module'),
            'runtime': {'threads': cv.getNumThreads(), 'optimized': cv.useOptimized(),
                        'cpu_features': cv.getCPUFeaturesLine(),
                        'ipp_enabled': cv.ipp.useIPP(), 'ipp_not_exact': cv.ipp.useIPP_NotExact(),
                        'ipp_version': cv.ipp.getIppVersion(), 'opencl_available': cv.ocl.haveOpenCL(),
                        'opencl_enabled': cv.ocl.useOpenCL()}}


def create_ocr_engine():
    """Disable ONNX Runtime telemetry before importing or constructing OCR code.

    This uses the supported runtime switch; it neither installs a networking
    workaround nor grants permission to send device/environment metadata.
    """
    # ORT 1.31.0 docs/Privacy.md: this must precede the first import, so its
    # telemetry uploader and device-ID initialization never start.
    os.environ['ORT_DISABLE_TELEMETRY'] = '1'
    runtime = importlib.import_module('onnxruntime')
    runtime.disable_telemetry_events()
    local_ocr = importlib.import_module('local_ocr')
    engine = local_ocr.LocalOCR()
    return engine, {'disabled_before_ocr_import_and_construction': True,
                    'environment': {'ORT_DISABLE_TELEMETRY': '1'},
                    'environment_set_before_onnxruntime_import': True,
                    'method': 'ORT_DISABLE_TELEMETRY=1 then onnxruntime.disable_telemetry_events'}


def generate_report(repo, *, samples=7, warmups=2):
    if samples < 7 or warmups < 2:
        raise ValueError('At least seven samples and two warmups are required')
    os.environ['ORT_DISABLE_TELEMETRY'] = '1'  # Before any third-party import.
    sys.path.insert(0, str(repo))
    import cv2 as cv
    import numpy as np
    from PIL import Image
    ocr, telemetry = create_ocr_engine()
    from model_inventory import verify_models
    from hero_recognition import PortraitMatcher
    from synthetic_vision import portraits, frame, encoded
    cv.setNumThreads(2)  # The application's PortraitMatcher uses the same limit.
    inputs = {name: sha256((repo / name).read_bytes()) for name in SOURCE_FILES}
    api = api_corpus(cv, np, Image, inputs)
    ocr_results, ocr_inputs = {}, {}
    for fixture, names in (('ocr-synthetic.png', FIXTURE_NAMES), ('ocr-blank.png', []),
                           ('ocr-app-demo.png', DEMO_NAMES)):
        raw = (repo / 'fixtures' / fixture).read_bytes()
        ocr_inputs[fixture] = (raw, names)
    with Image.open(repo / 'fixtures/ocr-app-demo.png') as source:
        image = source.convert('RGB')
        for fmt in FORMATS:
            ocr_inputs[fmt] = (encoded_image(image, fmt), DEMO_NAMES)
        for fmt in ICC_FORMATS:
            ocr_inputs[fmt + '-ICC'] = (encoded_image(image, fmt, icc=True), DEMO_NAMES)
    for name, (raw, names) in ocr_inputs.items():
        inputs['ocr/' + name] = sha256(raw)
        result = without_ocr_time(ocr.recognize(raw, names))
        if [candidate['name'] for candidate in result['candidates']] != names:
            raise RuntimeError(f'Unexpected OCR candidates: {name}: {result}')
        ocr_results[name] = result
    bank = portraits()
    matcher = PortraitMatcher(bank, {f'虚构英雄{i}': {'championId': str(9001 + i)} for i in range(6)})
    hero_inputs, hero_results = {}, {}
    for width, height in ((1280, 720), (1920, 1080), (2560, 1440), (3440, 1440)):
        hero_inputs[f'{width}x{height}'] = (encoded(frame(bank['9001'], width=width, height=height)), '9001')
    for image, name in ((frame(bank['9001'], side=True), 'sidebar'),
                        (frame(bank['9001'], gray=True), 'gray'),
                        (Image.new('RGB', (1280, 720), (20, 30, 40)), 'blank'),
                        (frame(bank['9001'], width=900, height=1200), 'portrait')):
        hero_inputs[name] = (encoded(image), None)
    for name, (raw, champion) in hero_inputs.items():
        inputs['hero/' + name] = sha256(raw)
        result = matcher.recognize(raw)
        if result['championId'] != champion:
            raise RuntimeError(f'Unexpected hero result: {name}: {result}')
        hero_results[name] = result
    rng = np.random.default_rng(0xBEEF)
    large = rng.integers(0, 256, (1080, 1920, 3), dtype=np.uint8)
    floating = large.astype(np.float32) / 255
    gray = cv.cvtColor(large[:360, :640], cv.COLOR_RGB2GRAY)
    gray_float = gray.astype(np.float32) / 255
    operations = {
        'resize_area_u8': lambda: cv.resize(large, (1280, 720), interpolation=cv.INTER_AREA),
        'resize_linear_u8': lambda: cv.resize(large, (1280, 720), interpolation=cv.INTER_LINEAR),
        'resize_cubic_f32': lambda: cv.resize(floating, (1280, 720), interpolation=cv.INTER_CUBIC),
        'match_template_u8': lambda: cv.matchTemplate(gray, gray[70:110, 90:130], cv.TM_CCOEFF_NORMED),
        'match_template_f32': lambda: cv.matchTemplate(gray_float, gray_float[70:110, 90:130], cv.TM_CCOEFF_NORMED)}
    performance = {}
    for name, operation in operations.items():
        api['performance/' + name] = snapshot(operation(), np)
        performance[name] = benchmark(operation, samples=samples, warmups=warmups, iterations=10,
                                      fingerprint=lambda result: snapshot(result, np))
    performance['ocr_app_demo'] = benchmark(
        lambda: ocr.recognize(*ocr_inputs['ocr-app-demo.png']), samples=samples,
        warmups=warmups, iterations=1, fingerprint=without_ocr_time)
    performance['hero_1080p'] = benchmark(
        lambda: matcher.recognize(hero_inputs['1920x1080'][0]), samples=samples,
        warmups=warmups, iterations=1, fingerprint=lambda result: result)
    if platform.system() == 'Windows':
        performance['capture_synthetic_window'] = capture_benchmark(samples=samples, warmups=warmups)
    metadata = collect_metadata(cv)
    report = {'schema_version': SCHEMA_VERSION, 'status': 'completed', 'scope': SCOPE,
              'run': {'id': str(uuid.uuid4()), 'process_nonce': PROCESS_NONCE,
                      'pid': os.getpid(), 'created_unix': time.time()},
              'host': {'system': platform.system(), 'release': platform.release(),
                       'version': platform.version(), 'machine': platform.machine(),
                       'processor': platform.processor(), 'logical_cpus': os.cpu_count(),
                       'identity_sha256': sha256(platform.node().encode('utf-8')),
                       'python': platform.python_version(), 'python_implementation': platform.python_implementation()},
              'dependencies': {name: importlib.metadata.version(name) for name in DEPENDENCIES},
              'onnxruntime_telemetry': telemetry,
              'opencv': metadata, 'native': {'sha256': metadata['binary']['sha256'],
              'size': metadata['binary']['raw_bytes'], 'zlib9_size': metadata['binary']['zlib9_bytes'],
              'path': metadata['binary']['path']}, 'inputs': inputs, 'models': verify_models(),
              'api_results': api, 'ocr_results': ocr_results, 'hero_results': hero_results,
              'performance': performance,
              'coverage': {'api_cases': len(api), 'ocr_cases': len(ocr_results), 'hero_cases': len(hero_results),
                           'ocr_formats': sorted(FORMATS), 'icc_formats': list(ICC_FORMATS)}}
    errors = validate_report(report)
    if errors:
        # Retain already-collected authoritative samples even if supplemental
        # identity, output, cleanup, or validation fails. The CLI exits nonzero.
        report['status'] = 'failed'
        report['failures'] = errors
    return report


def validate_report(report):
    """Dependency-free structural checks; empty/partial reports never pass."""
    errors = []
    try:
        canonical(report)  # Reject NaN/infinity even in fields not compared below.
        if report['onnxruntime_telemetry'] != {'disabled_before_ocr_import_and_construction': True,
                                               'environment': {'ORT_DISABLE_TELEMETRY': '1'},
                                               'environment_set_before_onnxruntime_import': True,
                                               'method': 'ORT_DISABLE_TELEMETRY=1 then onnxruntime.disable_telemetry_events'}:
            errors.append('ONNX telemetry was not disabled before OCR import/construction')
        if report['schema_version'] != SCHEMA_VERSION or report['status'] != 'completed':
            errors.append('report is incomplete or has an unsupported schema')
        for section, expected in (('api_results', expected_api_cases()), ('ocr_results', OCR_CASES),
                                  ('hero_results', HERO_CASES), ('performance', PERFORMANCE_CASES | (
                                      {'capture_synthetic_window'} if report['host']['system'] == 'Windows' else set()))):
            if set(report[section]) != expected:
                errors.append(f'{section} inventory differs from the required corpus')
            if any(value is None or value == {} for value in report[section].values()):
                errors.append(f'{section} contains empty results')
        if any(not valid_snapshot(value) for value in report['api_results'].values()):
            errors.append('API results contain an invalid exact array/scalar record')
        for section in ('api', 'ocr', 'hero'):
            if report['coverage'][section + '_cases'] != len(report[section + '_results']):
                errors.append(f'{section} coverage count is incorrect')
        if report['coverage']['ocr_formats'] != sorted(FORMATS) or report['coverage']['icc_formats'] != list(ICC_FORMATS):
            errors.append('image format coverage differs')
        for name, result in report['ocr_results'].items():
            required = {'mode', 'network_transmission', 'image_saved', 'image_size', 'ocr_lines', 'candidates', 'warning'}
            if set(result) != required:
                errors.append(f'OCR {name} does not contain the full non-timing result')
            if result['network_transmission'] is not False or result['image_saved'] is not False:
                errors.append(f'OCR {name} changed local-only behavior')
            expected = [] if name == 'ocr-blank.png' else FIXTURE_NAMES if name == 'ocr-synthetic.png' else DEMO_NAMES
            if [item['name'] for item in result['candidates']] != expected:
                errors.append(f'OCR {name} expected candidates are missing')
        for name, result in report['hero_results'].items():
            expected = None if name in {'sidebar', 'gray', 'blank', 'portrait'} else '9001'
            if result['championId'] != expected or not {'hero', 'confident', 'method', 'reason'} <= set(result):
                errors.append(f'hero {name} result is incomplete or unexpected')
        for name, record in report['performance'].items():
            samples = record['samples_seconds']
            if (len(samples) < 7 or record['warmups'] < 2 or record['iterations_per_sample'] < 1
                    or any(isinstance(x, bool) or not isinstance(x, (float, int)) or x <= 0 for x in samples)):
                errors.append(f'performance {name} needs positive repeated warmed samples')
            elif (record['median_seconds'] != statistics.median(samples)
                  or record['min_seconds'] != min(samples) or record['max_seconds'] != max(samples)):
                errors.append(f'performance {name} summaries disagree with raw samples')
            if not re.fullmatch('[0-9a-f]{64}', record['output_sha256']):
                errors.append(f'performance {name} lacks an exact repeated-output fingerprint')
            elif name in PERFORMANCE_CASES and record['output_sha256'] != sha256(canonical(performance_output(report, name)).encode('utf-8')):
                errors.append(f'performance {name} exact warmed output differs from its saved correctness result')
            if name == 'capture_synthetic_window':
                fixture = record['fixture']
                if (fixture['kind'] != 'own-process synthetic painted Qt window' or not fixture['qt_version']
                        or min(fixture['width'], fixture['height']) < 64
                        or not math.isfinite(fixture['device_pixel_ratio']) or fixture['device_pixel_ratio'] <= 0):
                    errors.append('Windows capture fixture metadata is invalid')
                from scripts.probe_capture_phases import validate_diagnostics
                errors.extend(validate_diagnostics(record.get('capture_diagnostics', {}), record,
                    inputs=report['inputs'], native_sha256=report['opencv']['binary']['sha256'],
                    pillow_version=report['dependencies']['Pillow']))
        cv = report['opencv']
        if cv['build_features'] != parse_build_information(cv['build_information']):
            errors.append('build feature metadata disagrees with getBuildInformation')
        if cv['import_errors']:
            errors.append('OpenCV Python submodule imports failed')
        if not cv['imported_python_submodules'] or not cv['exported_native_namespaces']:
            errors.append('OpenCV module introspection is missing')
        binary = cv['binary']
        if (not re.fullmatch('[0-9a-f]{64}', binary['sha256'])
                or not 0 < binary['zlib9_bytes'] <= binary['raw_bytes']):
            errors.append('native extension size/hash metadata is invalid')
        if report['native'] != {'sha256': binary['sha256'], 'size': binary['raw_bytes'],
                                'zlib9_size': binary['zlib9_bytes'], 'path': binary['path']}:
            errors.append('native metadata disagrees with the measured extension')
        if (set(report['inputs']) != expected_input_cases()
                or any(not re.fullmatch('[0-9a-f]{64}', value) for value in report['inputs'].values())
                or not report['models']):
            errors.append('source/input/model identities are missing or invalid')
        if set(report['dependencies']) != set(DEPENDENCIES):
            errors.append('dependency version inventory differs')
        if (not report['run']['id'] or not report['run']['process_nonce'] or type(report['run']['pid']) is not int or report['run']['pid'] <= 0
                or report['run']['created_unix'] <= 0 or not report['host']['identity_sha256']):
            errors.append('process or host identity is missing')
        if not {'system', 'release', 'version', 'machine', 'processor', 'logical_cpus',
                'identity_sha256', 'python', 'python_implementation'} <= set(report['host']):
            errors.append('host/CPU/Python identity is incomplete')
        if (not isinstance(cv['distributions'], dict) or not cv['cv_version']
                or set(cv['runtime']) != {'threads', 'optimized', 'cpu_features', 'ipp_enabled',
                                         'ipp_not_exact', 'ipp_version', 'opencl_available', 'opencl_enabled'}):
            errors.append('OpenCV distribution/runtime metadata is incomplete')
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        errors.append(f'invalid report schema: {exc}')
    return errors


def compare_reports(baseline, candidate, *, allow_non_windows=False, regression_ratio=1.5, noise_floor_seconds=0.005):
    if not math.isfinite(regression_ratio) or regression_ratio <= 1:
        raise ValueError('Regression ratio must be finite and greater than one')
    if not math.isfinite(noise_floor_seconds) or noise_floor_seconds < 0:
        raise ValueError('Noise floor must be finite and nonnegative')
    failures = []
    for label, report in (('baseline', baseline), ('candidate', candidate)):
        failures.extend(f'{label}: {error}' for error in validate_report(report))
    result = {'schema_version': SCHEMA_VERSION, 'status': 'failed', 'scope': SCOPE,
              'failures': failures, 'differences': {}, 'performance': {},
              'performance_policy': {'regression_ratio': regression_ratio,
                                     'absolute_noise_floor_seconds': noise_floor_seconds,
                                     'rule': 'Fail when candidate median exceeds BOTH baseline times ratio and baseline plus noise floor.',
                                     'all_sample_medians_reported': True}}
    if failures:
        return result
    base_cv, cand_cv = baseline['opencv'], candidate['opencv']
    for label, cv, version in (('baseline', base_cv, OFFICIAL_VERSION), ('candidate', cand_cv, CUSTOM_VERSION)):
        if cv['distributions'] != {'opencv-python-headless': version} or cv['cv_version'] != '5.0.0':
            failures.append(f'{label}: expected only opencv-python-headless {version} and OpenCV 5.0.0')
    if not allow_non_windows and any(r['host']['system'] != 'Windows' for r in (baseline, candidate)):
        failures.append('The release gate requires Windows measurements')
    if baseline['host'] != candidate['host']:
        failures.append('Measurements must use the same host, OS, Python and CPU')
    if (baseline['run']['id'] == candidate['run']['id']
            or baseline['run']['process_nonce'] == candidate['run']['process_nonce']):
        failures.append('Measurements must run in fresh, separate Python processes')
    for section in ('inputs', 'models', 'dependencies'):
        if canonical(baseline[section]) != canonical(candidate[section]):
            failures.append(f'{section} changed between measurements')
    for section in ('api_results', 'ocr_results', 'hero_results'):
        changed = [name for name in sorted(baseline[section])
                   if canonical(baseline[section][name]) != canonical(candidate[section][name])]
        result['differences'][section] = changed
        if changed:
            failures.append(f'{section}: {len(changed)} exact-output differences')
    before, after = base_cv['build_features'], cand_cv['build_features']
    if set(after['modules']) != CUSTOM_MODULES:
        failures.append('Candidate compiled modules must be exactly core/flann/geometry/imgcodecs/imgproc/python3')
    if not CUSTOM_MODULES < set(before['modules']):
        failures.append('Baseline must contain the retained modules and additional official modules')
    retained = ('cpu_baseline', 'cpu_dispatch', 'ipp', 'ipp_iw', 'opencl', 'jpeg_simd',
                'jpeg_simd_requested', 'algorithm_hint', 'custom_hal', 'parallel_framework', 'png_metadata')
    for feature in retained:
        if not before[feature] or before[feature] != after[feature]:
            failures.append(f'Retained build feature differs or is missing: {feature}')
    for label, feature in (('baseline', before), ('candidate', after)):
        if not feature['floating_point']['precise']:
            failures.append(f'{label}: precise floating-point release flags are missing or fast-math is enabled')
        if feature['jpeg_simd'] != 'YES':
            failures.append(f'{label}: JPEG SIMD is not enabled')
        if not feature['ipp'] or feature['ipp'].startswith('NO') or not (feature['opencl'] or '').startswith('YES'):
            failures.append(f'{label}: IPP/OpenCL must remain compiled in')
    for codec in ('PNG', 'JPEG', 'WEBP'):
        old, new = before['codecs'][codec], after['codecs'][codec]
        if not old['enabled'] or not new['enabled'] or not old['version'] or old['version'] != new['version']:
            failures.append(f'Retained image codec differs or is unavailable: {codec}')
    if base_cv['runtime'] != cand_cv['runtime']:
        failures.append('OpenCV runtime CPU/IPP/OpenCL/optimization/thread settings differ')
    if (base_cv['runtime']['threads'] != 2 or not base_cv['runtime']['optimized']
            or not base_cv['runtime']['ipp_enabled'] or base_cv['runtime']['ipp_not_exact']):
        failures.append('Expected optimized, precise IPP application runtime with two OpenCV threads')
    if base_cv['binary']['sha256'] == cand_cv['binary']['sha256']:
        failures.append('Candidate and official native extensions are identical')
    result['binary_sizes'] = {label: cv['binary'] for label, cv in (('baseline', base_cv), ('candidate', cand_cv))}
    result['modules'] = {'baseline_compiled': before['modules'], 'candidate_compiled': after['modules'],
                         'removed_compiled': sorted(set(before['modules']) - set(after['modules'])),
                         'baseline_python_submodules': base_cv['imported_python_submodules'],
                         'candidate_python_submodules': cand_cv['imported_python_submodules']}
    if set(baseline['performance']) != set(candidate['performance']):
        failures.append('Performance inventory differs between hosts')
    for name in sorted(set(baseline['performance']) & set(candidate['performance'])):
        old, new = baseline['performance'][name], candidate['performance'][name]
        if (old['warmups'], old['iterations_per_sample'], len(old['samples_seconds'])) != (
                new['warmups'], new['iterations_per_sample'], len(new['samples_seconds'])):
            failures.append(f'performance {name}: sampling configuration differs')
        if old.get('fixture') != new.get('fixture'):
            failures.append(f'performance {name}: capture fixture/Qt version differs')
        if old['output_sha256'] != new['output_sha256']:
            failures.append(f'performance {name}: exact warmed output differs')
        if name == 'capture_synthetic_window':
            a_identity = dict(old['capture_diagnostics']['identity_before_supplemental'])
            b_identity = dict(new['capture_diagnostics']['identity_before_supplemental'])
            a_identity['loaded'] = {k: v for k, v in a_identity['loaded'].items() if k != 'cv2_native'}
            b_identity['loaded'] = {k: v for k, v in b_identity['loaded'].items() if k != 'cv2_native'}
            from scripts.probe_capture_phases import same_value
            if (not same_value(a_identity, b_identity) or old['capture_diagnostics']['authoritative_observations'][0]['backend']
                    != new['capture_diagnostics']['authoritative_observations'][0]['backend']):
                failures.append('performance capture_synthetic_window: backend/helper/source/Pillow identity differs')
        a, b = old['median_seconds'], new['median_seconds']
        regression = b > a * regression_ratio and b > a + noise_floor_seconds
        result['performance'][name] = {'baseline_median_seconds': a, 'candidate_median_seconds': b,
                                       'ratio': b / a, 'delta_seconds': b - a, 'regression': regression,
                                       'baseline_samples_seconds': old['samples_seconds'],
                                       'candidate_samples_seconds': new['samples_seconds']}
        if regression:
            failures.append(f'performance {name}: {b / a:.3f}x median regression ({b - a:.6f}s slower)')
    result['status'] = 'failed' if failures else 'passed'
    result['windows_release_evidence'] = not allow_non_windows and not failures
    result['coverage'] = baseline['coverage']
    return result


def write_json(path, report):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def main(argv=None, *, standalone=False):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='operation', required=True)
    generate = commands.add_parser('generate', help='Measure the currently installed wheel in this fresh process')
    generate.add_argument('--repo', type=Path, default=ROOT)
    generate.add_argument('--output', type=Path, required=True)
    generate.add_argument('--samples', type=int, default=7)
    generate.add_argument('--warmups', type=int, default=2)
    compare = commands.add_parser('compare', help='Fail on exact parity, feature, identity or substantial timing differences')
    compare.add_argument('baseline', type=Path)
    compare.add_argument('candidate', type=Path)
    compare.add_argument('--output', type=Path, required=True)
    compare.add_argument('--allow-non-windows', action='store_true', help='Diagnostic only; cannot produce Windows release evidence')
    compare.add_argument('--regression-ratio', type=float, default=1.5)
    compare.add_argument('--noise-floor-seconds', type=float, default=0.005)
    args = parser.parse_args(argv)
    try:
        if args.operation == 'generate':
            report = generate_report(args.repo.resolve(), samples=args.samples, warmups=args.warmups)
        else:
            baseline = json.loads(args.baseline.read_text(encoding='utf-8'))
            candidate = json.loads(args.candidate.read_text(encoding='utf-8'))
            report = compare_reports(baseline, candidate, allow_non_windows=args.allow_non_windows,
                                     regression_ratio=args.regression_ratio, noise_floor_seconds=args.noise_floor_seconds)
    except Exception as exc:
        report = {'schema_version': SCHEMA_VERSION, 'status': 'failed', 'scope': SCOPE,
                  'failures': [f'{type(exc).__name__}: {exc}']}
    if _RETAINED_CAPTURE_FIXTURES:
        report['status'] = 'failed'
        report.setdefault('failures', []).append('Unconfirmed capture cleanup; owned fixture retained until process exit; Job termination is unobserved')
    capture_text = None
    if args.operation == 'generate':
        capture_record = report.get('performance', {}).get('capture_synthetic_window')
        if capture_record is not None:
            from scripts.probe_capture_phases import bounded_json
            try:
                # Readable complete rows in rendered CI logs; never truncate them.
                capture_text = bounded_json({'capture_synthetic_window': capture_record})
            except ValueError:
                report['status'] = 'failed'
                report.setdefault('failures', []).append('Capture diagnostic exceeds bounded output budget; full evidence retained in report')
    try:
        try:
            write_json(args.output, report)
        except Exception as error:
            # If file output fails, still attempt the complete bounded stdout
            # evidence, then report the write failure without exposing raw paths.
            report['status'] = 'failed'
            report.setdefault('failures', []).append('Report write failed: ' + type(error).__name__)
        if capture_text is not None:
            print(capture_text, flush=True)
        print(json.dumps({'status': report['status'], 'output': str(args.output),
                          'coverage': report.get('coverage'), 'failures': report.get('failures', [])}, ensure_ascii=False), flush=True)
    finally:
        if standalone and _RETAINED_CAPTURE_FIXTURES:
            # Even failed file/stdout/flush attempts cannot enter normal Qt
            # destruction with an unconfirmed worker. Only this CLI process exits.
            # Owned Job-on-exit termination is not observed graceful cleanup.
            try:
                sys.stdout.flush()
            finally:
                try:
                    sys.stderr.flush()
                finally:
                    os._exit(1)
    return 1 if report['status'] == 'failed' else 0


if __name__ == '__main__':
    raise SystemExit(main(standalone=True))

"""Reviewed Windows-only packaging policy and measured single-file size evidence.

No runtime models/code are rewritten. Optional binaries are removed only when
no retained PE import (including delay imports) points at them. Dynamic paths
are intentionally reviewed separately and exercised in actual-EXE Windows CI.
"""
from __future__ import annotations
from collections import defaultdict
import hashlib
from pathlib import Path
import re

BASELINE = {
    'version': '0.4.2',
    'source_commit': '151bb0a5d0a73946bad5e603c8f07373ed19248e',
    'size': 150_291_542,
    'sha256': '66e7798b5deb056e182f7a33bbdecf13498eaa62b6bf8ca0c6db3ae01ff48886',
}
# Conservative first target: at least 16.8% smaller than the immutable v0.4.2.
# A changed dependency must pass this guard or receive an explicit policy edit.
MAX_EXE_BYTES = 125_000_000
BRANDING_FILES = ('vga.ico', 'vga-icon-512.png')
EXCLUDED_IMPORTS = (
    'PIL.AvifImagePlugin', 'PIL._avif',
    'onnxruntime.tools', 'onnxruntime.backend', 'onnxruntime.quantization',
    'onnxruntime.transformers', 'onnxruntime.datasets', 'onnxruntime.training',
    'rapidocr.inference_engine.openvino', 'rapidocr.inference_engine.paddle',
    'rapidocr.inference_engine.pytorch', 'rapidocr.inference_engine.tensorrt',
    'rapidocr.inference_engine.mnn',
)


def normalized_path(value):
    return str(value).replace('\\', '/').lower()


def unused_binary_reason(name):
    name = normalized_path(name).rsplit('/', 1)[-1]
    if re.fullmatch(r'opencv_videoio_ffmpeg[0-9]+_64\.dll', name):
        return 'OpenCV video codec; this application only decodes still screenshots'
    if name == 'onnxruntime.dll':
        return 'Standalone C API; Python CPU inference is linked into pybind11_state'
    if name in {'libcrypto-3-x64.dll', 'libssl-3-x64.dll'}:
        return 'Orphaned optional Qt OpenSSL backend; Python SSL dependencies are retained'
    if name.startswith('_avif.') and name.endswith('.pyd'):
        return 'AVIF is outside the supported PNG/JPEG/WebP/BMP screenshot formats'
    return None


def pe_imports(path):
    # pefile is already a pinned PyInstaller Windows build dependency.
    import pefile
    pe = pefile.PE(str(path), fast_load=True)
    try:
        pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY[key] for key in
            ('IMAGE_DIRECTORY_ENTRY_IMPORT', 'IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT')])
        return [entry.dll.decode('ascii').lower() for key in
                ('DIRECTORY_ENTRY_IMPORT', 'DIRECTORY_ENTRY_DELAY_IMPORT')
                for entry in getattr(pe, key, ())]
    finally:
        pe.close()


def trim_unused_binaries(entries, import_reader=pe_imports):
    kept, removed = [], []
    for entry in entries:
        reason = unused_binary_reason(entry[0])
        if reason:
            removed.append({'path': normalized_path(entry[0]), 'source_size': Path(entry[1]).stat().st_size,
                            'reason': reason})
        else:
            kept.append(entry)
    removed_names = {row['path'].rsplit('/', 1)[-1] for row in removed}
    for name, source, _ in kept:
        if Path(source).suffix.lower() not in {'.dll', '.pyd'}:
            continue
        missing = removed_names.intersection(import_reader(source))
        if missing:
            raise RuntimeError(f'Refusing to remove PE dependencies required by {name}: {sorted(missing)}')
    return kept, {'removed': removed, 'removed_source_bytes': sum(row['source_size'] for row in removed),
                  'retained_pe_imports_checked': True,
                  'scope': 'Static and delay PE imports; dynamic use separately covered by Windows EXE tests'}


def assert_slim_inventory(names):
    names = {normalized_path(name) for name in names}
    unwanted = sorted(name for name in names if unused_binary_reason(name) or
                       (name.startswith('assets/branding/') and name.rsplit('/', 1)[-1] not in BRANDING_FILES) or
                       (name.startswith(('rapidocr/', 'onnxruntime/')) and name.endswith(('.py', '.pyc'))))
    if unwanted:
        raise RuntimeError('Unused or duplicate package payload returned: ' + ', '.join(unwanted))
    required = {'assets/branding/' + name for name in BRANDING_FILES} | {
        'rapidocr/config.yaml', 'rapidocr/default_models.yaml',
        'onnxruntime/capi/onnxruntime_pybind11_state.pyd',
        'onnxruntime/capi/onnxruntime_providers_shared.dll',
        '_ssl.pyd', 'libcrypto-3.dll', 'libssl-3.dll',
        'pyside6/plugins/tls/qcertonlybackend.dll', 'pyside6/plugins/tls/qschannelbackend.dll',
    }
    missing = sorted(required - names)
    if missing:
        raise RuntimeError('Required slim-package resources are missing: ' + ', '.join(missing))


def measure_archive(archive, executable):
    """Use real CArchive stored lengths, not installed-wheel or guessed ZIP size."""
    from model_inventory import EXPECTED_MODELS
    executable = Path(executable)
    entries, groups = [], defaultdict(lambda: {'stored_bytes': 0, 'unpacked_bytes': 0, 'entries': 0})
    models = []
    for name, row in archive.toc.items():
        normalized = normalized_path(name)
        stored, unpacked = row[1:3]
        if type(stored) is not int or type(unpacked) is not int or min(stored, unpacked) < 0:
            raise RuntimeError('Invalid package archive lengths')
        item = {'path': normalized, 'stored_bytes': stored, 'unpacked_bytes': unpacked}
        entries.append(item)
        group = normalized.split('/', 1)[0]
        groups[group]['stored_bytes'] += stored
        groups[group]['unpacked_bytes'] += unpacked
        groups[group]['entries'] += 1
        model_name = normalized.rsplit('/', 1)[-1]
        expected = next((digest for original, digest in EXPECTED_MODELS.items() if original.lower() == model_name), None)
        if expected:
            data = archive.extract(name)
            digest = hashlib.sha256(data).hexdigest()
            if digest != expected:
                raise RuntimeError('Bundled OCR model changed: ' + name)
            models.append({'path': normalized, 'sha256': digest, 'size': len(data)})
    if len(models) != len(EXPECTED_MODELS):
        raise RuntimeError('Bundled OCR model inventory incomplete or duplicated')
    size = executable.stat().st_size
    stored = sum(item['stored_bytes'] for item in entries)
    if stored > size:
        raise RuntimeError('Archive stored bytes exceed the executable size')
    with executable.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    return {'schema_version': 1, 'status': 'passed' if size <= MAX_EXE_BYTES else 'failed',
            'measurement': 'Actual Windows EXE CArchive; stored sizes include existing lossless zlib compression',
            'executable': {'size': size, 'sha256': digest}, 'baseline': BASELINE,
            'maximum_exe_bytes': MAX_EXE_BYTES, 'saved_bytes': BASELINE['size'] - size,
            'saved_percent': round(100 * (BASELINE['size'] - size) / BASELINE['size'], 3),
            'stored_payload_bytes': stored, 'unpacked_payload_bytes': sum(item['unpacked_bytes'] for item in entries),
            'container_overhead_bytes': size - stored, 'entry_count': len(entries),
            'groups': [{'name': name, **sizes} for name, sizes in sorted(groups.items(), key=lambda x: -x[1]['stored_bytes'])],
            'largest_entries': sorted(entries, key=lambda x: -x['stored_bytes'])[:25],
            'unchanged_models': models, 'compression': 'PyInstaller default zlib; UPX disabled',
            'limitations': ['Size evidence alone is not functional acceptance; require the actual-EXE Windows suite.']}

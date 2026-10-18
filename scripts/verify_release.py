"""Verify fresh same-job native Windows evidence, then optionally publish a prerelease.

This helper never reads or prints credentials. gh alone consumes GH_TOKEN supplied
by the final workflow step. An existing tag/release is never updated or replaced.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import subprocess
import struct
import statistics
import sys
import zlib
import zipfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.microsoft_runtime import verify_runtime_evidence, verify_notice_archive
from scripts.windows_package import read_archive_measurement, OFFICIAL_PROFILE, ADOPTED_PROFILE
from scripts.minimal_opencv_package import validate_build_profile, verify_custom_evidence, verify_custom_notice_archive, verify_custom_source_archive, CUSTOM_VERSION, OFFICIAL_VERSION
from scripts.check_package_candidate import validate_evidence as validate_package_evidence

REPOSITORY = 'Junming-Liang/vga-aram-helper'
PREVIEW_VERSION = '0.4.14'
PREVIEW_WORKFLOW = '.github/workflows/build-native-preview.yml'
NATIVE_AUTOMATION_FIELDS = ('automatic_hero_passed', 'automatic_choices_passed', 'auto_without_manual_hero_selection', 'auto_unknown_clears_passed', 'auto_hero_change_clears_passed', 'auto_manual_fallback_passed', 'own_overlay_hidden_capture_passed', 'unchanged_frame_ocr_reuse_passed', 'partial_candidate_slots_passed', 'partial_to_full_recovery_passed', 'async_capture_ui_passed')
NATIVE_REQUIRED_FIELDS = ('native_window', 'window_closed', 'capture_passed', 'ocr_passed', 'click_through_passed',
                         'source_hint_renderer_passed', 'three_badge_regions_verified', 'badge_gap_hit_test_passed', 'badge_above_cards_verified', 'badge_revocation_hidden_verified', 'source_tier_display_passed', 'source_tier_hero_specific', 'source_tier_missing_passed',
                         'source_tier_screen_order_preserved', 'source_tier_no_winrate_display', 'overlay_layout_passed')
NATIVE_SCALES = ((1.0, 'windows-native'), (1.5, 'windows-native-scale150'), (2.0, 'windows-native-scale200'))
AUTO_SOURCE_FILES = ('badge_contract.py', 'source_combo_hints.py', 'tests/badge_fixture.py', 'hero_identity_continuity.py', 'monitor_preferences.py', 'card_title_proof.py', 'augment_card_geometry.py', 'card_badges.py', 'automatic_windows.py','native_ui.py','portrait_display.py', 'local_debug.py','screen_capture.py','session_windows.py','tests/windows_automatic_capture.py','tests/SessionWindowFixture.cs','wgc_capture.py','native/wgc_capture.cpp','persistent_capture_adapter.py','wgc_session_capture.py','native/wgc_session_capture.cpp','owned_diagnostic_json.py', 'tests/windows_session_fixture.py')
AUTO_CAPTURE_FIELDS = ('wait_without_window','helper_visible_after_default_start','helper_minimized_after_start','wait_client_new_game','hwnd_blank_fallback','bounded_roi_passed','minimize_restore','foreign_occlusion_failed_closed','same_process_recreation_cleared_stale','process_restart_auto_reconnected','preexisting_game_auto_connected','no_manual_window_selection','self_overlay_hidden_before_capture','stop_close_cleanup','owned_process_job_empty','temporary_directory_removed','authenticode_abi_passed')
DPI_SOURCE_FILES = ('native_ui.py', 'portrait_display.py', 'local_debug.py', 'screen_capture.py', 'native_state.py', 'overlay_geometry.py', 'card_badges.py', 'augment_card_geometry.py', 'badge_contract.py', 'native_smoke.py')
# Load only the trusted local pure validator, never Python from a source archive.
# An installed package named "tests" must not select a different validator.
_dpi_spec = importlib.util.spec_from_file_location('release_windows_dpi_matrix',
    Path(__file__).resolve().parents[1] / 'tests' / 'windows_dpi_matrix.py')
dpi_matrix = importlib.util.module_from_spec(_dpi_spec)
_dpi_spec.loader.exec_module(dpi_matrix)

_wgc_spec = importlib.util.spec_from_file_location('release_windows_wgc_capture',
    Path(__file__).resolve().parents[1] / 'tests' / 'windows_wgc_capture.py')
wgc_fixture = importlib.util.module_from_spec(_wgc_spec)
_wgc_spec.loader.exec_module(wgc_fixture)

_session_spec = importlib.util.spec_from_file_location('release_windows_wgc_session_capture',
    Path(__file__).resolve().parents[1] / 'tests' / 'windows_wgc_session_capture.py')
session_capture_fixture = importlib.util.module_from_spec(_session_spec)
_session_spec.loader.exec_module(session_capture_fixture)

_visible_spec = importlib.util.spec_from_file_location('release_windows_wgc_visible_overlay',
    Path(__file__).resolve().parents[1] / 'tests' / 'windows_wgc_visible_overlay.py')
visible_capture_fixture = importlib.util.module_from_spec(_visible_spec)
_visible_spec.loader.exec_module(visible_capture_fixture)

_selection_spec = importlib.util.spec_from_file_location('release_windows_selection_smoke',
    Path(__file__).resolve().parents[1] / 'tests' / 'windows_selection_smoke.py')
selection_fixture = importlib.util.module_from_spec(_selection_spec)
_selection_spec.loader.exec_module(selection_fixture)

_duty_spec = importlib.util.spec_from_file_location('release_overlay_duty_contract',
    Path(__file__).resolve().parents[1] / 'tests' / 'overlay_duty_contract.py')
duty_contract = importlib.util.module_from_spec(_duty_spec)
_duty_spec.loader.exec_module(duty_contract)

HERO_GENUINE_FILES = ('hero_recognition.py','hero_portraits.py','local_ocr.py','ocr_privacy.py','model_inventory.py','screen_capture.py','native_state.py','engine.py')
SELECTION_GENUINE_FILES = ('champion_select.py','local_ocr.py','ocr_privacy.py','model_inventory.py')

SELECTION_FIELDS = ('champion_select_own_row_passed', 'champion_select_ambiguity_passed', 'champion_select_session_carry_passed', 'champion_select_stale_clear_passed', 'champion_select_window_scope_passed', 'metadata_query_passed')

BROWSER_CHECK = 'Actual EXE Chromium UI: hero + 3 slots, switch hero, recompute, clear round; screenshot saved'
COMPARE_CHECK = 'Frozen comparison API: exact hero-specific source grades in original slots, with no rates, rankings or unique recommendation'
OCR_CHECK = 'Actual bundled ONNX inference: Chinese fixture 3/3; blank fixture 0; all model SHA256 match'
MODEL_HASHES = {
    'PP-OCRv6_det_small.onnx': '090f04abcd9d9a7498bc4ebf677e4cb9bdce1fe4197ddb7e529f1ef44e1ff94f',
    'PP-OCRv6_rec_small.onnx': '6f327246b50388f3c176ae304bd95767ea6dc0c9ae92153ef8cbe210b3c14884',
    'ch_ppocr_mobile_v2.0_cls_mobile.onnx': 'e47acedf663230f8863ff1ab0e64dd2d82b838fceb5957146dab185a89d6215c',
}
EVIDENCE_NAMES = ('windows-wgc-source.json', 'windows-wgc-frozen.json',
                  'windows-wgc-session-application-source.json', 'windows-wgc-session-application-frozen.json',
                  'windows-wgc-visible-overlay-source.json', 'windows-wgc-visible-overlay-frozen.json',
                  'windows-automatic-capture.json', 'windows-package-size.json', 'windows-ota-smoke.json', 'windows-build.json', 'windows-exe-smoke.json', 'windows-exe-self-test.json',
                  'windows-exe-ui.png', 'windows-exe-self-test.log', 'windows-exe-server.log',
                  'windows-build-environment.txt', 'windows-artifact-budget.json', 'hero-recognition-genuine.json',
                  'windows-selection-smoke.json', 'windows-selection-handoff.json', 'champion-select-genuine.json',
                  'windows-dpi-candidate-matrix.json', 'windows-selection-source.json') + tuple(
                      visible_capture_fixture.scale_report_name(scale, frozen=frozen)
                      for frozen in (False, True) for scale in visible_capture_fixture.SCALES) + tuple(
                      selection_fixture.native_report_name(frozen, scale)
                      for frozen in (False, True) for scale in selection_fixture.SCALES
                      if not (frozen and scale == 1)) + tuple(
                      prefix + '-' + suffix for _, prefix in NATIVE_SCALES
                      for suffix in ('smoke.json', 'overlay.json', 'overlay.png', 'process.log'))
QT_VERSION = '6.11.2'
PSL_SOURCE_URL = 'https://raw.githubusercontent.com/publicsuffix/list/e452c7058d6946bd76952b128c12f5ce87a5acb8/public_suffix_list.dat'
PSL_SOURCE_SHA256 = '5c75b7ea88e26f7940a888a34872345cb85c9484a4d0056c4063525d8c8aa184'
QT_RUNTIME_DLLS = {'qt6core.dll', 'qt6gui.dll', 'qt6widgets.dll', 'qwindows.dll'}
# Proprietary Microsoft release runtimes, reviewed separately from Qt LGPL
# sources. Only these observed dependency names are eligible; no debug/runtime
# prefix wildcard is permitted. Their notice and original bytes are checked too.
MICROSOFT_RUNTIME_DLLS = {'msvcp140.dll', 'msvcp140_1.dll', 'msvcp140_2.dll',
                          'vcruntime140.dll', 'vcruntime140_1.dll'}
RUNTIME_DLLS = {'python312.dll', 'vcruntime140.dll', 'vcruntime140_1.dll', 'msvcp140.dll'} | QT_RUNTIME_DLLS
QT_NOTICE_FILES = ('qt-licenses/NOTICE.txt', 'qt-licenses/SOURCE_AND_RELINKING.txt',
                   'qt-licenses/PROVENANCE.json',
                   'qt-licenses/qtbase/src/3rdparty/libpsl/PSL-LICENSE.txt',
                   'qt-licenses/qtbase/src/3rdparty/libpsl/src/LICENSE.chromium',
                   'qt-licenses/pyside-setup/LICENSES/LGPL-3.0-only.txt',
                   'qt-licenses/pyside-setup/LICENSES/GPL-3.0-only.txt')

QT_SOURCES = [{'filename': 'pyside-setup-everywhere-src-6.11.2.tar.xz',
  'size': 18053248,
  'sha256': 'cba47efbaad1bedd529725cbc14e21f156c7a19366f07b3edfbb076ffd7afdf8',
  'url': 'https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-6.11.2-src/pyside-setup-everywhere-src-6.11.2.tar.xz'},
 {'filename': 'qtbase-everywhere-src-6.11.2.tar.xz',
  'size': 50582668,
  'sha256': '5b2e00eccaf5a4d8c14134ffa0ea8dfd0a35ae1ffc7f8d87fa4305a1ed23cf22',
  'url': 'https://download.qt.io/official_releases/qt/6.11/6.11.2/submodules/qtbase-everywhere-src-6.11.2.tar.xz'},
 {'filename': 'qtsvg-everywhere-src-6.11.2.tar.xz',
  'size': 2341860,
  'sha256': 'd594337feca84c26fb67fe87b85e6a5c12fda404b611d905f9d138210c311876',
  'url': 'https://download.qt.io/official_releases/qt/6.11/6.11.2/submodules/qtsvg-everywhere-src-6.11.2.tar.xz'},
 {'filename': 'qtimageformats-everywhere-src-6.11.2.tar.xz',
  'size': 2050424,
  'sha256': 'cecd8900f34b6550076309bc94f62f828008b633a4239e0a08c86788f41001f8',
  'url': 'https://download.qt.io/official_releases/qt/6.11/6.11.2/submodules/qtimageformats-everywhere-src-6.11.2.tar.xz'}]
BASELINE_CHECKS = {
    'Standalone version command without Python/site-packages on PATH',
    'Embedded third-party license texts readable from EXE',
    'Frozen HTTP server: readiness, loopback UI/assets, CSP and synthetic data',
    'Frozen HTTP OCR API recognizes original demo fixture with bundled models',
    BROWSER_CHECK, COMPARE_CHECK, OCR_CHECK,
}


class VerificationError(RuntimeError):
    pass


def require(condition, message):
    if not condition:
        raise VerificationError(message)


def digest(path):
    with Path(path).open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def checked_file(path, allow_empty=False):
    path = Path(path)
    require(path.is_file() and not path.is_symlink(), f'Missing or symlinked release input: {path.name}')
    require((0 if allow_empty else 1) <= path.stat().st_size <= 512 * 1024 * 1024, f'Invalid release input size: {path.name}')
    return path


def read_json(path):
    checked_file(path)
    require(path.stat().st_size < 5 * 1024 * 1024, f'JSON exceeds size limit: {path.name}')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 'Duplicate JSON key')
            result[key] = value
        return result
    return json.loads(path.read_text(encoding='utf-8-sig'), object_pairs_hook=unique)


def evidence_file(folder, name):
    # upload-artifact can preserve reports/ when the warning-log path shares
    # the repository as common parent. Accept only these two exact layouts.
    candidates = [folder / name, folder / 'reports' / name]
    matches = [path for path in candidates if path.is_file()]
    require(len(matches) == 1, f'Missing or ambiguous evidence: {name}')
    return checked_file(matches[0], allow_empty=name.endswith('.log'))


def verify_png(path):
    """Verify a bounded non-interlaced 8-bit RGB/RGBA screenshot without Pillow."""
    require(path.stat().st_size <= 32 * 1024 * 1024, 'PNG screenshot exceeds size limit')
    data = path.read_bytes()
    require(data.startswith(b'\x89PNG\r\n\x1a\n'), 'Invalid PNG signature')
    offset, header, ended, idat_closed = 8, None, False, False
    compressed = bytearray()
    while offset < len(data):
        require(offset + 12 <= len(data), 'Truncated PNG chunk')
        size = struct.unpack('>I', data[offset:offset + 4])[0]
        kind = data[offset + 4:offset + 8]
        require(all(65 <= byte <= 90 or 97 <= byte <= 122 for byte in kind) and not kind[2] & 32,
                'Invalid PNG chunk type')
        require(offset + 12 + size <= len(data), 'Truncated PNG payload')
        payload = data[offset + 8:offset + 8 + size]
        crc = struct.unpack('>I', data[offset + 8 + size:offset + 12 + size])[0]
        require(zlib.crc32(kind + payload) & 0xffffffff == crc, 'PNG chunk CRC mismatch')
        if header is None:
            require(kind == b'IHDR' and size == 13, 'PNG must start with IHDR')
            header = struct.unpack('>IIBBBBB', payload)
            width, height, depth, color, compression, filtering, interlace = header
            require(1 <= width <= 8192 and 1 <= height <= 8192 and depth == 8 and
                    color in (2, 6) and compression == filtering == interlace == 0,
                    'Unsupported screenshot dimensions/PNG encoding')
            channels = 3 if color == 2 else 4
            expected = height * (1 + width * channels)
            require(expected <= 64 * 1024 * 1024, 'Decoded PNG exceeds size limit')
        elif kind == b'IDAT':
            require(not idat_closed, 'PNG IDAT chunks are not contiguous')
            compressed.extend(payload)
        elif kind == b'IEND':
            require(size == 0 and compressed, 'PNG image data/end missing')
            ended = True
            offset += 12
            break
        else:
            require(kind != b'IHDR' and (kind[0] & 32 or kind == b'PLTE'), 'Unknown or duplicate critical PNG chunk')
            if compressed:
                idat_closed = True
        offset += 12 + size
    require(ended and offset == len(data), 'Missing PNG end or trailing data')
    try:
        decoder = zlib.decompressobj()
        pixels = decoder.decompress(bytes(compressed), expected + 1)
    except zlib.error as error:
        raise VerificationError('Invalid PNG compressed pixels') from error
    require(len(pixels) == expected and decoder.eof and not decoder.unused_data and
            not decoder.unconsumed_tail, 'PNG pixel stream length mismatch')
    stride = 1 + width * channels
    require(all(pixels[row * stride] <= 4 for row in range(height)), 'Invalid PNG row filter')


def verify_budget(budget, release_dir, evidence):
    require(budget.get('status') == 'passed' and 'error' not in budget and
            budget.get('upload_scope') == 'evidence-only', 'Evidence-only artifact budget gate did not pass')
    keys = ('existing_repository_artifact_bytes', 'proposed_upper_estimate_bytes',
            'projected_bytes', 'project_budget_bytes', 'reserve_bytes')
    require(all(type(budget.get(key)) is int and budget[key] >= 0 for key in keys), 'Invalid artifact budget numbers')
    require(budget['project_budget_bytes'] == 500_000_000 and budget['reserve_bytes'] == 10_000_000,
            'Artifact budget/reserve differs from approved limit')
    require(budget['projected_bytes'] == budget['existing_repository_artifact_bytes'] + budget['proposed_upper_estimate_bytes'] and
            budget['projected_bytes'] <= budget['project_budget_bytes'] - budget['reserve_bytes'],
            'Artifact budget arithmetic or capacity check failed')
    # This report gates the small-evidence upload only. Non-publishing candidate
    # retention has a separate full budget gate after verification and staging.
    measured = sum(path.stat().st_size for name, path in evidence.items() if name != 'windows-artifact-budget.json')
    require(budget['proposed_upper_estimate_bytes'] >= measured, 'Artifact budget underestimates uploaded evidence')


def verify_qt_licenses(archive, build):
    names = archive.namelist()
    require(len(names) == len(set(names)), 'Ambiguous duplicate entries in license archive')
    require(sum(row.file_size for row in archive.infolist()) <= 64 * 1024 * 1024, 'License archive expands beyond limit')
    require(archive.testzip() is None and names, 'Invalid license archive')
    for name in QT_NOTICE_FILES:
        require(name in names and archive.getinfo(name).file_size > 0, 'Missing Qt license/source notice: ' + name)
    archived = json.loads(archive.read('dependency-inventory.json')) if 'dependency-inventory.json' in names else None
    require(archived == build.get('dependencies') and isinstance(archived, list), 'License and build dependency inventories differ')
    for package in ('pyside6_essentials', 'shiboken6'):
        rows = [row for row in archived if str(row.get('name', '')).casefold().replace('-', '_') == package]
        require(len(rows) == 1 and rows[0].get('version') == QT_VERSION, 'Missing/wrong Qt dependency version: ' + package)
        paths = rows[0].get('license_files')
        require(isinstance(paths, list) and paths, 'Empty Qt dependency license inventory: ' + package)
        for path in paths:
            require(isinstance(path, str), 'Invalid license inventory path')
            name = path.replace('\\', '/')
            require(name in names and archive.getinfo(name).file_size > 0, 'Qt dependency license file is missing')
    provenance = json.loads(archive.read('qt-licenses/PROVENANCE.json'))
    require(provenance.get('schema_version') == 1 and provenance.get('upstream_version') == QT_VERSION,
            'Qt notice provenance/version mismatch')
    rows = provenance.get('files')
    require(isinstance(rows, list) and rows, 'Qt notice provenance has no files')
    seen = set()
    for row in rows:
        name = 'qt-licenses/' + row.get('path', '')
        require(name not in seen and name in names, 'Missing/duplicate Qt provenance file')
        seen.add(name)
        data = archive.read(name)
        require(len(data) == row.get('size') and hashlib.sha256(data).hexdigest() == row.get('sha256'),
                'Qt notice provenance checksum mismatch')
    sources = archive.read('qt-licenses/SOURCE_AND_RELINKING.txt').decode('utf-8')
    require('SOURCE' in sources.upper() and 'RELINK' in sources.upper() and
            'https://download.qt.io/official_releases/' in sources,
            'Qt corresponding-source/relinking access notice missing')
    require(PSL_SOURCE_URL in sources and PSL_SOURCE_SHA256 in sources,
            'Exact preferred-form MPL Public Suffix List source access is missing')


def verify_source_access(release_dir, build, source_sha, version):
    path = checked_file(release_dir / 'source-access.json')
    access = read_json(path)
    require(access == build.get('source_access') and access.get('source_commit') == source_sha,
            'Build/source-access identity mismatch')
    expected = {row['filename']: row for row in QT_SOURCES}
    sources = access.get('qt_sources')
    require(isinstance(sources, list) and len(sources) == len(expected) and
            {row.get('filename'): row for row in sources} == expected,
            'Qt corresponding-source inventory differs from pinned official archives')
    app = access.get('application_source')
    require(isinstance(app, dict) and app.get('filename') == f'vga-aram-helper-{version}-source.zip',
            'Application source archive name/version mismatch')
    assets = [path]
    for row in [app, *sources]:
        archive_path = checked_file(release_dir / row['filename'])
        require(type(row.get('size')) is int and archive_path.stat().st_size == row['size'] and
                digest(archive_path) == row.get('sha256'), 'Corresponding-source archive size/hash mismatch')
        assets.append(archive_path)
    with zipfile.ZipFile(assets[1]) as archive:
        require(archive.comment == source_sha.encode('ascii'), 'Application git archive commit differs from tested SHA')
        require(sum(row.file_size for row in archive.infolist()) <= 256 * 1024 * 1024 and
                len(archive.namelist()) <= 10000, 'Application source archive exceeds limits')
        require(archive.testzip() is None, 'Corrupt application source archive')
        require({'native/wgc_capture.cpp', 'wgc_capture.py', 'wgc_smoke.py', 'frame_ocr_cache.py', 'scripts/build_wgc_capture.py', 'tests/windows_wgc_capture.py', 'launcher.py', 'ocr_privacy.py', 'native_ui.py', 'screen_capture.py', 'native_state.py', 'overlay_geometry.py', 'native_smoke.py', 'hero_portraits.py', 'portrait_display.py', 'local_debug.py', 'wgc_visible_overlay_smoke.py', 'owned_diagnostic_json.py', 'tests/windows_wgc_visible_overlay.py', 'portrait_cache_diagnostics.py', 'hero_recognition.py', 'champion_select.py', 'selection_session.py', 'session_windows.py', 'automatic_windows.py', 'selection_smoke.py', 'tests/windows_automatic_capture.py', 'tests/SessionWindowFixture.cs', 'requirements-build.txt',
                 'scripts/build_windows.py', 'scripts/windows_package.py', 'scripts/check_package_candidate.py',
                 'tests/windows_dpi_matrix.py', 'tests/windows_ota_smoke.py', 'packaging/windows-build-constraints.txt',
                 'packaging/VGA-Aram-Helper.spec'} <= set(archive.namelist()),
                'Application source archive lacks native packaging inputs')
        if build.get('opencv_custom_build'):
            require({'scripts/build_minimal_opencv.py', 'scripts/minimal_opencv_package.py',
                     'scripts/probe_opencv_parity.py', 'ocr_privacy.py', 'packaging/opencv-minimal-patch.py',
                     'packaging/opencv-build-requirements.txt', 'WINDOWS_MINIMAL_OPENCV_EXPERIMENT.md'} <= set(archive.namelist()),
                    'Custom source archive lacks its exact build recipe')
    return assets


def verify_dpi_matrix(path, source_archive):
    """Bind the complete source-only Windows matrix to same-release raw bytes."""
    report = read_json(path)
    require(isinstance(report, dict) and type(report.get('schema_version')) is int and
            report['schema_version'] == 1 and report.get('status') == 'candidate_passed' and
            report.get('expect') == 'candidate' and report.get('os_name') == 'nt' and
            report.get('gate_errors') == [] and 'error' not in report,
            'Windows candidate source matrix did not pass')
    try:
        errors = dpi_matrix.validate_matrix(report, 'candidate')
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError) as exc:
        raise VerificationError('Malformed Windows candidate source matrix') from exc
    require(not errors, 'Windows candidate source matrix failed: ' + ', '.join(errors))
    rows = report.get('source_metadata')
    require(isinstance(rows, list) and len(rows) == len(DPI_SOURCE_FILES),
            'Windows source matrix implementation inventory mismatch')
    hashes = {}
    for row in rows:
        require(isinstance(row, dict) and isinstance(row.get('path'), str) and
                isinstance(row.get('sha256'), str) and re.fullmatch(r'[0-9a-f]{64}', row['sha256']),
                'Windows source matrix implementation path/hash missing')
        # The harness records absolute Windows paths. Only normalize separators
        # to identify an exact expected basename; never normalize file bytes.
        parts = row['path'].replace('\\', '/').split('/')
        name = parts[-1]
        require('..' not in parts and name in DPI_SOURCE_FILES and name not in hashes,
                'Windows source matrix implementation inventory mismatch')
        hashes[name] = row['sha256']
    require(set(hashes) == set(DPI_SOURCE_FILES), 'Windows source matrix implementation inventory mismatch')
    with zipfile.ZipFile(source_archive) as archive:
        for name, checksum in hashes.items():
            require(archive.namelist().count(name) == 1 and hashlib.sha256(archive.read(name)).hexdigest() == checksum,
                    'Windows source matrix evaluated different release source bytes: ' + name)


def physical_rectangle(value, label):
    require(isinstance(value, dict) and set(value) == {'x', 'y', 'width', 'height'} and
            all(type(value[key]) is int for key in value) and value['width'] > 0 and value['height'] > 0,
            'Invalid physical rectangle: ' + label)
    return value


def contains_rectangle(outer, inner, strict=False):
    margin = 1 if strict else 0
    return (inner['x'] >= outer['x'] + margin and inner['y'] >= outer['y'] + margin and
            inner['x'] + inner['width'] <= outer['x'] + outer['width'] - margin and
            inner['y'] + inner['height'] <= outer['y'] + outer['height'] - margin)


def verify_native_scale(files, checksum, version, scale, prefix, source_archive, source_commit, exe_size):
    smoke = read_json(files[prefix + '-smoke.json'])
    native = read_json(files[prefix + '-overlay.json'])
    require(smoke.get('status') == 'passed' and 'error' not in smoke and
            smoke.get('executable_sha256') == checksum and smoke.get('applicationVersion') == version and
            smoke.get('process_exited') is True and smoke.get('executable_size') == exe_size and
            type(smoke.get('executable_size')) is int, 'Native smoke failed, did not exit, or tested different EXE/version: ' + prefix)
    require(smoke.get('native_report') == prefix + '-overlay.json' and
            smoke.get('native_screenshot') == prefix + '-overlay.png', 'Native smoke references unexpected evidence: ' + prefix)
    require(native.get('status') == 'passed' and 'error' not in native and native.get('backend') == 'qtwidgets' and
            native.get('frozen') is True and native.get('qt_platform') == 'windows' and
            native.get('applicationVersion') == version and native.get('executable_sha256') == checksum, 'Native evidence is not passing frozen QtWidgets on Windows: ' + prefix)
    require(all(native.get(field) is True for field in NATIVE_REQUIRED_FIELDS),
            'Required native window/capture/OCR/click-through/close/source-tier proof missing: ' + prefix)
    require(all(native.get(field) is True for field in NATIVE_AUTOMATION_FIELDS),
            'Automatic hero/candidate native lifecycle proof missing: ' + prefix)
    require(native.get('source_hint_render_scope') == 'Original synthetic sourceHint renderer only; not live-game or source-combo accuracy' and isinstance(native.get('source_hint_visible_text'),str) and native['source_hint_visible_text'], 'Native owned source-hint renderer proof missing: '+prefix)
    require(native.get('recognized') == ['星火共鸣', '晶盾回路', '风步微光'],
            'Actual native OCR did not recognize the three original mock choices: ' + prefix)
    require(native.get('card_names_accessible') == ['星火共鸣','晶盾回路','风步微光'],
            'Native ordered accessible card identities missing: ' + prefix)
    require(native.get('source_tier_rendered') == ['T1', 'T2', 'T3'],
            'Actual native literal source-tier rendering evidence is missing or changed: ' + prefix)
    require(native.get('source_tier_accessible') == [f'选项 {i} · {name} · T{i} · 演示评级' for i,name in enumerate(['星火共鸣','晶盾回路','风步微光'],1)],
            'Native exact accessible source-tier evidence missing: ' + prefix)
    require(native.get('badge_source_markers') == ['演示评级']*3 and native.get('source_details_reachable') is True,
            'Native visible source or reachable full source details missing: ' + prefix)
    require(isinstance(native.get('screenshot_method'), str) and native['screenshot_method'].strip(),
            'Native screenshot method missing: ' + prefix)
    for report in (smoke, native):
        require(type(report.get('requested_app_scale')) in (int, float) and report['requested_app_scale'] == scale,
                'Native requested app scale differs from required scale: ' + prefix)
    for field in ('mock_qwindow_dpr', 'overlay_qwindow_dpr'):
        value = native.get(field)
        require(type(value) in (int, float) and math.isfinite(value) and abs(value - scale) <= .01,
                'Native QWindow DPR does not match requested app scale on the 96-DPI runner: ' + prefix)
    require(native.get('physical_mock_geometry_passed') is True and type(native.get('overlay_compact')) is bool,
            'Native fixed physical mock/compact-layout evidence missing: ' + prefix)
    work = physical_rectangle(native.get('desktop_work_area_physical'), 'work area')
    mock = physical_rectangle(native.get('mock_window_physical'), 'mock window')
    client = physical_rectangle(native.get('clientRect'), 'mock client')
    overlay = physical_rectangle(native.get('overlay_window_physical'), 'overlay window')
    require((client['width'], client['height']) == (960, 600), 'Native mock client must remain physical 960x600: ' + prefix)
    require(contains_rectangle(work, mock) and contains_rectangle(mock, client) and
            contains_rectangle(client, overlay, strict=True), 'Native physical windows escaped their required bounds: ' + prefix)
    require(overlay['height']*2<=client['height'], 'Native overlay exceeds the half-client-height budget: ' + prefix)
    try:
        duty_contract.validate_badge_regions(native)
    except (RuntimeError,KeyError,TypeError,ValueError) as exc:
        raise VerificationError('Native badge-region receipt invalid: '+str(exc)) from exc
    verify_png(files[prefix + '-overlay.png'])
    require(smoke.get('native_report_sha256') == digest(files[prefix + '-overlay.json']) and
            smoke.get('native_screenshot_sha256') == digest(files[prefix + '-overlay.png']),
            'Native wrapper does not bind exact report and screenshot bytes: ' + prefix)
    require(smoke.get('source_commit') == source_commit, 'Native source commit differs: ' + prefix)
    verify_source_inventory(smoke.get('source_files'), duty_contract.SOURCE_FILES, source_archive, 'Native duty')
    try:
        duty = duty_contract.validate_overlay_duty(native, expected_fixture_sha256=smoke['source_files']['fixtures/auto-scene.png'])
    except (AssertionError, RuntimeError, ValueError, TypeError, KeyError) as exc:
        raise VerificationError('Native duty-cycle evidence failed: ' + prefix + ': ' + str(exc)) from exc
    summary = {key: native[key] for key in ('requested_app_scale', 'mock_qwindow_dpr', 'overlay_qwindow_dpr',
        'desktop_work_area_physical', 'mock_window_physical', 'clientRect', 'overlay_window_physical',
        'overlay_compact', 'physical_mock_geometry_passed', 'overlay_layout_passed')}
    summary.update(overlay_duty_cycle=duty, overlay_duty_scope=duty_contract.SCOPE, native_report_sha256=smoke['native_report_sha256'],
                   native_screenshot_sha256=smoke['native_screenshot_sha256'])
    return summary


def verify_source_inventory(hashes, expected, source_archive, label):
    require(type(hashes) is dict and set(hashes) == set(expected) and
            all(type(value) is str and re.fullmatch(r'[0-9a-f]{64}', value) for value in hashes.values()),
            label + ' exact source inventory is missing or changed')
    with zipfile.ZipFile(source_archive) as archive:
        for name, checksum in hashes.items():
            require(archive.namelist().count(name) == 1 and
                    hashlib.sha256(archive.read(name)).hexdigest() == checksum,
                    label + ' tested different source bytes: ' + name)


def verify_selection_bundle(files, source_archive, version, source_commit, checksum, exe_size):
    summaries = []
    for frozen, kind in ((False, 'source'), (True, 'frozen')):
        filename = 'windows-selection-smoke.json' if frozen else 'windows-selection-source.json'
        report = read_json(files[filename])
        try:
            selection_fixture.validate_aggregate(report, version, frozen=frozen,
                source_commit=source_commit, executable_sha256=checksum if frozen else None,
                executable_size=exe_size if frozen else None)
        except (AssertionError, RuntimeError, ValueError, TypeError, KeyError, AttributeError) as exc:
            raise VerificationError('Selection ' + kind + ' evidence failed: ' + str(exc)) from exc
        if frozen:
            require(type(report.get('executable_size')) is int and report['executable_size'] == exe_size,
                    'Selection frozen EXE size differs')
        verify_source_inventory(report.get('source_files'), selection_fixture.SOURCE_FILES,
                                source_archive, 'Selection ' + kind)
        runs = []
        for row in report['runs']:
            path = files[row['native_report']]
            native = read_json(path)
            try:
                selection_fixture.validate_report(native, version, frozen=frozen, scale=row['app_scale'],
                    executable_sha256=checksum if frozen else None)
                same_detail = json.dumps(native, sort_keys=True, allow_nan=False) == json.dumps(
                    row['detail'], sort_keys=True, allow_nan=False)
            except (AssertionError, RuntimeError, ValueError, TypeError, KeyError, AttributeError) as exc:
                raise VerificationError('Selection ' + kind + ' native report failed: ' + str(exc)) from exc
            require(same_detail and row.get('native_report_sha256') == digest(path),
                    'Selection aggregate does not bind exact native report bytes: ' + row['native_report'])
            if frozen:
                require(native.get('executable_sha256') == checksum,
                        'Selection native report tested different frozen EXE bytes')
            detail = native['client_hero_reference']
            runs.append({'app_scale': row['app_scale'], 'native_report_sha256': row['native_report_sha256'],
                         'hero': detail['reference']['hero'], 'sourceTier': detail['reference']['sourceTier'],
                         'visible': detail['visible'], 'native_visible': detail['native_visible'],
                         'confirmed': detail['confirmed'], 'augment_card_count': detail['augment_card_count'],
                         'client_rect': detail['client_rect'], 'overlay_rect': detail['overlay_rect'],
                         'safety': native['client_hero_safety'], 'completed_fields': row['completed_fields']})
        summaries.append({'kind': kind, 'source_commit': source_commit, 'runs': runs})
    return summaries


def genuine_report_version_matches(recorded, version):
    # v0.4.11 may carry the original v0.4.10 static-image observations only
    # when the validators below prove every evaluated module is byte-identical.
    return recorded == version or (version == '0.4.11' and recorded == '0.4.10')


def verify_genuine_report(path, source_archive, version):
    """Bind limited, honestly partial still-image observations to released source.

    This validates recorded provenance/results, not broad accuracy or live-game
    behavior. The genuine images themselves are never packaged or fetched here.
    """
    report = read_json(path)
    require(report.get('schema_version') == 1 and genuine_report_version_matches(report.get('applicationVersion'), version) and
            report.get('status') == 'partial_with_abstentions' and report.get('platform') == 'Linux',
            'Genuine screenshot report identity/scope differs from reviewed local evaluation')
    scope = report.get('scope', '')
    require(isinstance(scope, str) and all(text in scope for text in
            ('small selected public sample', 'Not Windows live-game capture', 'Genuine images are not redistributed')),
            'Genuine screenshot scope/limitations are missing')
    hashes = report.get('implementation_sha256', {})
    require(set(hashes) == set(HERO_GENUINE_FILES), 'Genuine report implementation inventory mismatch')
    with zipfile.ZipFile(source_archive) as archive:
        for name, checksum in hashes.items():
            require(archive.namelist().count(name) == 1 and hashlib.sha256(archive.read(name)).hexdigest() == checksum,
                    'Genuine screenshot evidence evaluated different source: ' + name)
    templates = report.get('templates', {})
    require(templates.get('source_url') == 'https://ddragon.leagueoflegends.com/api/versions.json' and
            isinstance(templates.get('version'), str) and re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', templates['version']) and
            type(templates.get('count')) is int and templates['count'] >= 100 and
            isinstance(templates.get('roster_sha256'), str) and re.fullmatch(r'[0-9a-f]{64}', templates['roster_sha256']),
            'Genuine screenshot template provenance missing')
    cases = report.get('cases')
    require(isinstance(cases, list) and 2 <= len(cases) <= 100, 'Genuine screenshot cases missing')
    counts = dict(positive_cases=0, positive_recognized=0, positive_abstained=0,
                  wrong_hero_predictions=0, negative_cases=0, negative_abstained=0)
    seen = set()
    for case in cases:
        require(isinstance(case, dict) and case.get('kind') == 'genuine_public_screenshot' and
                case.get('transformation') is None and case.get('image_redistributed') is False and
                case.get('safety_pass') is True, 'Genuine case scope or safety check failed')
        url, image_hash = case.get('source_url', ''), case.get('image_sha256', '')
        require(isinstance(url, str) and url.startswith('https://') and len(url) <= 2048 and
                isinstance(image_hash, str) and re.fullmatch(r'[0-9a-f]{64}', image_hash) and
                image_hash not in seen and case.get('condition') and case.get('gold_hero_id'),
                'Genuine image source/hash/gold label missing or duplicated')
        seen.add(image_hash)
        observed = case.get('observed', {})
        confident = observed.get('confident')
        require(type(confident) is bool, 'Genuine case confidence must be boolean')
        require((confident and str(observed.get('championId')) == str(case['gold_hero_id'])) or
                (not confident and observed.get('championId') is None), 'Wrong or contradictory genuine hero prediction')
        expected = case.get('expected_outcome')
        if expected == 'recognize_own_hero':
            counts['positive_cases'] += 1
            counts['positive_recognized' if confident else 'positive_abstained'] += 1
            require(case.get('case_pass') is confident, 'Positive abstention must remain a reported limitation')
        else:
            require(expected == 'abstain' and not confident and case.get('case_pass') is True,
                    'Negative genuine screenshot did not abstain')
            counts['negative_cases'] += 1
            counts['negative_abstained'] += 1
    require(counts['positive_recognized'] > 0 and counts['positive_abstained'] > 0 and counts['negative_cases'] > 0 and
            report.get('summary') == counts, 'Genuine report counts omit a result or overstate coverage')
    selection = report.get('genuine_selection_frame', {})
    matches = [case for case in cases if case['source_url'] == selection.get('source_url') and case['observed']['confident']]
    require(len(matches) == 1 and isinstance(selection.get('hero'), dict) and
            all(selection['hero'].get(key) == matches[0]['observed'].get(key) for key in
                ('championId', 'confident', 'method', 'score', 'margin', 'box')) and
            selection.get('passes_title_geometry') is True and 'not temporal/video or native Windows proof' in selection.get('scope', ''),
            'Single genuine selection frame identity or limited scope missing')
    titles = selection.get('automatic_titles', [])
    require(isinstance(titles, list) and len(titles) == 3 and len({row.get('name') for row in titles}) == 3 and
            all(row.get('name') and row.get('name') == row.get('recognized_text') and row.get('match_method') == 'exact' and
                type(row.get('ocr_confidence')) in (int, float) and .96 <= row['ocr_confidence'] <= 1 and
                row.get('name_similarity') == 1 for row in titles), 'Genuine title evidence lacks three exact confident names')
    return counts


def verify_selection_genuine_report(path, source_archive, version):
    """Limited recorded client still images; not a current stock-client claim."""
    report = read_json(path)
    require(report.get('schema_version') == 1 and genuine_report_version_matches(report.get('applicationVersion'), version) and
            report.get('status') == 'passed' and report.get('platform') == 'Linux',
            'Champion-select screenshot report identity mismatch')
    scope = report.get('scope', '')
    require(isinstance(scope, str) and all(text in scope for text in
            ('modified by a third-party plugin', 'two distinct scenes', 'Not current stock-client', 'Images are not redistributed')),
            'Champion-select evidence omits its modified-client/duplicate-scene limitations')
    hashes = report.get('implementation_sha256', {})
    require(set(hashes) == set(SELECTION_GENUINE_FILES), 'Champion-select evaluated module inventory mismatch')
    with zipfile.ZipFile(source_archive) as archive:
        for name, checksum in hashes.items():
            require(archive.namelist().count(name) == 1 and hashlib.sha256(archive.read(name)).hexdigest() == checksum,
                    'Champion-select screenshot evidence evaluated different source: ' + name)
    cases = report.get('cases')
    require(isinstance(cases, list) and len(cases) == 4, 'Reviewed champion-select sample is incomplete')
    counts = dict(positive_cases=0, positive_recognized=0, negative_cases=0, negative_abstained=0,
                  wrong_hero_predictions=0, distinct_negative_scenes=0)
    seen, negative_pages = set(), set()
    for case in cases:
        require(isinstance(case, dict) and case.get('kind') == 'genuine_public_screenshot' and
                case.get('transformation') is None and case.get('image_redistributed') is False and
                case.get('case_pass') is True and case.get('safety_pass') is True,
                'Champion-select sample safety/scope failed')
        image_hash = case.get('image_sha256', '')
        require(isinstance(image_hash, str) and re.fullmatch(r'[0-9a-f]{64}', image_hash) and image_hash not in seen and
                all(isinstance(case.get(key), str) and case[key].startswith('https://') for key in ('source_url', 'source_page')) and
                case.get('condition') and case.get('limitations'), 'Champion-select source/hash/limits missing')
        seen.add(image_hash)
        observed = case.get('observed', {})
        if case.get('expected_outcome') == 'recognize_current_assignment':
            require(observed.get('assigned') is True and observed.get('scene') == 'assigned-selection' and
                    observed.get('championId') == case.get('gold_hero_id') and bool(case.get('gold_hero_id')) and
                    observed.get('method') == 'client-own-row-and-center-ocr' and observed.get('requiresTemporalStability') is True,
                    'Champion-select positive identity/ownership evidence differs')
            counts['positive_cases'] += 1; counts['positive_recognized'] += 1
        else:
            require(case.get('expected_outcome') == 'abstain' and observed.get('assigned') is False and
                    observed.get('championId') is None and case.get('gold_hero_id') is None,
                    'Unassigned champion-card screen must abstain')
            counts['negative_cases'] += 1; counts['negative_abstained'] += 1
            negative_pages.add(case['source_page'])
    counts['distinct_negative_scenes'] = len(negative_pages)
    require(report.get('summary') == counts == dict(positive_cases=1, positive_recognized=1, negative_cases=3,
            negative_abstained=3, wrong_hero_predictions=0, distinct_negative_scenes=2),
            'Champion-select results overstate reviewed independent coverage')
    return counts


def verify_qt_runtime(binaries):
    """Reject any DLL/plugin outside the separately reviewed component inventory."""
    paths = {name.replace('\\', '/').casefold() for name in binaries}
    require(len(paths) == len(binaries), 'Duplicate Qt runtime paths')
    allowed_dlls = {'qt6core.dll', 'qt6gui.dll', 'qt6widgets.dll', 'qt6svg.dll', 'qt6network.dll', 'pyside6.abi3.dll'}
    allowed_bindings = {'qtcore.pyd', 'qtgui.pyd', 'qtwidgets.pyd', 'qtsvg.pyd', 'qtnetwork.pyd'}
    plugins = {
        'platforms': {'qwindows.dll', 'qminimal.dll', 'qoffscreen.dll', 'qdirect2d.dll'},
        'iconengines': {'qsvgicon.dll'},
        'styles': {'qmodernwindowsstyle.dll', 'qwindowsvistastyle.dll'},
        'tls': {'qcertonlybackend.dll', 'qschannelbackend.dll'},
        'networkinformation': {'qnetworklistmanager.dll'},
        'imageformats': {'qgif.dll', 'qico.dll', 'qjpeg.dll', 'qsvg.dll', 'qicns.dll',
                         'qtga.dll', 'qtiff.dll', 'qwbmp.dll', 'qwebp.dll', 'qdds.dll'},
    }
    for path in paths:
        require(not path.startswith('/') and '..' not in path.split('/'), 'Unsafe Qt archive path')
        if path.startswith('pyside6/'):
            relative = path.removeprefix('pyside6/')
        else:
            relative = path
        if path.startswith('pyside6/') and relative in MICROSOFT_RUNTIME_DLLS:
            continue
        if relative in allowed_dlls or relative in allowed_bindings:
            continue
        plugin_path = relative.removeprefix('qt/')
        parts = plugin_path.split('/')
        require(len(parts) == 3 and parts[0] == 'plugins' and
                parts[1] in plugins and parts[2] in plugins[parts[1]],
                'Qt runtime/plugin is outside reviewed source coverage: ' + path)
    require(QT_RUNTIME_DLLS <= {name.rsplit('/', 1)[-1] for name in paths},
            'Required Qt DLL/plugin absent from archive')
    return paths


def verify_run_provenance(repository, source_sha, run_id, run_attempt):
    """GET-only authenticated identity check for this still-running publishing job."""
    require(repository == REPOSITORY and re.fullmatch(r'[0-9a-f]{40}', source_sha) and
            type(run_id) is int and run_id > 0 and type(run_attempt) is int and run_attempt > 0, 'Invalid current workflow identity')
    run = gh_api(f'repos/{REPOSITORY}/actions/runs/{run_id}')
    require(type(run.get('id')) is int and run['id'] == run_id and type(run.get('run_attempt')) is int and
            run['run_attempt'] == run_attempt and run.get('status') == 'in_progress' and
            'conclusion' in run and run['conclusion'] is None and run.get('event') == 'workflow_dispatch' and
            run.get('head_branch') == 'main' and run.get('head_sha') == source_sha and
            run.get('path') == PREVIEW_WORKFLOW,
            'Current run is not the approved active main native-preview dispatch')
    repository_data, head_repository = run.get('repository', {}), run.get('head_repository', {})
    require(repository_data.get('full_name') == REPOSITORY and repository_data.get('private') is False and
            head_repository.get('full_name') == REPOSITORY and
            type(repository_data.get('id')) is int and repository_data['id'] > 0 and
            head_repository.get('id') == repository_data['id'], 'Current run repository/fork identity mismatch')
    return {'repository': REPOSITORY, 'run_id': run_id, 'run_attempt': run_attempt, 'source_sha': source_sha,
            'workflow': PREVIEW_WORKFLOW, 'event': 'workflow_dispatch', 'branch': 'main'}


def check_runner_context(repository, source_sha, run_id, run_attempt):
    """Read only nonsecret workflow context; never inspect credential variables."""
    expected = {'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': repository, 'GITHUB_SHA': source_sha,
                'GITHUB_RUN_ID': str(run_id), 'GITHUB_RUN_ATTEMPT': str(run_attempt), 'GITHUB_REF': 'refs/heads/main',
                'GITHUB_EVENT_NAME': 'workflow_dispatch',
                'GITHUB_WORKFLOW_REF': f'{REPOSITORY}/{PREVIEW_WORKFLOW}@refs/heads/main'}
    require(all(os.environ.get(key) == value for key, value in expected.items()),
            'Publication must run in this exact approved GitHub workflow context')


def check_preview_identity(verified, provenance):
    require(isinstance(provenance, dict) and provenance.get('repository') == REPOSITORY and
            provenance.get('workflow') == PREVIEW_WORKFLOW and provenance.get('event') == 'workflow_dispatch' and
            provenance.get('branch') == 'main' and type(provenance.get('run_id')) is int and provenance['run_id'] > 0 and
            type(provenance.get('run_attempt')) is int and provenance['run_attempt'] > 0,
            'Missing authenticated current-run provenance')
    require(verified.get('source_sha') == provenance.get('source_sha') and
            verified.get('run_id') == provenance['run_id'] and verified.get('run_attempt') == provenance['run_attempt'] and verified.get('version') == PREVIEW_VERSION and
            verified.get('tag') == 'v' + PREVIEW_VERSION and
            isinstance(verified.get('exe_sha256'), str) and re.fullmatch(r'[0-9a-f]{64}', verified['exe_sha256']) and
            type(verified.get('exe_size')) is int and verified['exe_size'] > 0,
            'Preview source/run/version/EXE identity differs from the fresh tested build')
    matches = [asset for asset in verified.get('assets', [])
               if asset.get('name') == f'vga-aram-helper-{PREVIEW_VERSION}-windows-x64.exe']
    require(len(matches) == 1 and matches[0].get('sha256') == verified['exe_sha256'] and
            matches[0].get('size') == verified['exe_size'], 'Preview EXE identity differs from verified release asset')


def verify_automatic_capture(path,source_archive,version,source_sha):
    report=read_json(path)
    require(report.get('schema_version')==1 and report.get('status')=='passed' and 'error' not in report
        and report.get('platform')=='win32' and report.get('backend')=='qtwidgets' and report.get('frozen') is False
        and report.get('checks_use_real_windows') is True and report.get('application_version')==version
        and report.get('source_commit')==source_sha,'Automatic Windows source-fixture identity/scope mismatch')
    require(all(report.get(field) is True for field in AUTO_CAPTURE_FIELDS),'Automatic lifecycle/capture/cleanup evidence is incomplete')
    trust=report.get('trust_injection',{})
    require(all(trust.get(field) is True for field in ('source_only','exact_paths_and_sha256_only','real_process_metadata_unchanged'))
        and type(trust.get('calls')) is int and trust['calls']>0,'Source fixture must disclose bounded trust injection separately')
    hashes=report.get('source_sha256')
    require(isinstance(hashes,dict) and set(hashes)==set(AUTO_SOURCE_FILES),'Automatic source hash inventory differs')
    with zipfile.ZipFile(source_archive) as archive:
        require(archive.comment==source_sha.encode('ascii'),'Automatic source archive commit differs')
        for name in AUTO_SOURCE_FILES:
            require(name in archive.namelist() and hashlib.sha256(archive.read(name)).hexdigest()==hashes[name],
                'Automatic fixture tested different source bytes: '+name)
    return {'status':'passed','scope':'Actual Windows source UI, owned synthetic processes/pixels; fixture publisher trust injected; not frozen-auto-discovery or live LoL evidence',
            'checks':list(AUTO_CAPTURE_FIELDS)}


def verify_frozen_wgc_archive(executable, proof):
    # Re-read the final distribution bytes, not only the build-time inventory.
    from PyInstaller.archive.readers import CArchiveReader
    from scripts.build_wgc_capture import verify_archive
    try:
        return verify_archive(CArchiveReader(str(executable)), proof)
    except (RuntimeError, ValueError, KeyError, TypeError, OSError) as exc:
        raise VerificationError('Final frozen WGC helper/manifest differs: ' + str(exc)) from exc


def verify_frozen_session_archive(executable, proof):
    from PyInstaller.archive.readers import CArchiveReader
    from scripts.build_wgc_session_capture import verify_archive
    try:
        return verify_archive(CArchiveReader(str(executable)), proof)
    except (RuntimeError, ValueError, KeyError, TypeError, OSError) as exc:
        raise VerificationError('Final frozen persistent helper/manifest differs: ' + str(exc)) from exc


def verify_frozen_visible_modules(executable):
    """Re-read product bytecode from the final EXE using the trusted validator."""
    from PyInstaller.archive.readers import CArchiveReader
    return visible_capture_fixture.verify_product_modules(CArchiveReader(str(executable)))


def verify_visible_capture_bundle(files, source_archive, version, source_sha, build,
                                  executable, checksum, exe_size):
    """Bind the two visible aggregates to all six original, fixed-name reports."""
    fixture = visible_capture_fixture
    from scripts.probe_opencv_postbuild import check_directory
    summaries = []
    try:
        helper = build.get('wgc_session_helper_build')
        fixture_inventory = build.get('archive_inventory', {})
        session_capture_fixture.validate_manifest(helper)
        require(helper.get('source_commit') == source_sha and
                fixture.same_json(helper, fixture_inventory.get('wgc_session_helper')),
                'Visible helper build/bundle/source binding differs')
        with zipfile.ZipFile(source_archive) as archive:
            require(archive.comment == source_sha.encode('ascii'), 'Visible source archive commit differs')
            for name, record in helper['source_files'].items():
                require(archive.namelist().count(name) == 1, 'Visible helper source missing/duplicated: ' + name)
                raw = archive.read(name)
                require(type(record.get('size')) is int and len(raw) == record['size'] and
                        hashlib.sha256(raw).hexdigest() == record['sha256'],
                        'Visible helper tested different source bytes: ' + name)
        for frozen, kind in ((False, 'source'), (True, 'frozen')):
            path = files['windows-wgc-visible-overlay-' + kind + '.json']
            check_directory(path.parent)
            report = read_json(path)
            require(type(report) is dict and fixture.same_json(report, report) and
                    report.get('status') == 'passed' and 'error' not in report and
                    'report_binding_errors' not in report and report.get('frozen') is frozen and
                    report.get('scope') == fixture.SCOPE and report.get('applicationVersion') == version and
                    report.get('source_commit') == source_sha and
                    fixture.same_json(report.get('scales'), list(fixture.SCALES)) and
                    fixture.same_json(report.get('helper_build'), helper),
                    'Visible ' + kind + ' aggregate identity/source/scales/helper differs')
            verify_source_inventory(report.get('source_files'), fixture.SOURCE_FILES, source_archive,
                                    'Visible ' + kind)
            foreign = report.get('foreign_fixture')
            require(type(foreign) is dict and set(foreign) == {'source_sha256', 'executable_sha256'} and
                    foreign['source_sha256'] == report['source_files']['tests/SessionWindowFixture.cs'],
                    'Visible foreign fixture source differs')
            fixture.digest(foreign['executable_sha256'])
            if frozen:
                require(report.get('executable_sha256') == checksum and
                        type(report.get('executable_size')) is int and report['executable_size'] == exe_size and
                        fixture.same_json(report.get('archive_inventory'), fixture_inventory),
                        'Visible frozen EXE/inventory differs')
                modules = verify_frozen_visible_modules(executable)
                require(fixture.same_json(report.get('product_modules'), modules),
                        'Visible frozen product modules differ from final EXE')
                for name, record in modules.items():
                    require(record['source_sha256'] == report['source_files'].get(name + '.py'),
                            'Visible frozen product source differs from archive: ' + name)
            else:
                require(all(report.get(key) is None for key in
                            ('executable_sha256', 'executable_size', 'archive_inventory', 'product_modules')),
                        'Visible source aggregate claims frozen evidence')
            runs = report.get('runs')
            require(type(runs) is list and len(runs) == len(fixture.SCALES),
                    'Visible ordered scale inventory missing')
            validated = []
            for run, scale in zip(runs, fixture.SCALES):
                name = fixture.scale_report_name(scale, frozen=frozen)
                require(type(run) is dict and fixture.same_json(run.get('scale'), scale) and
                        run.get('detail_report') == name and run.get('coordination') == 'passed' and
                        type(run.get('exit_code')) is int and run['exit_code'] == 0 and
                        run.get('outer_cleanup_complete') is True and
                        not any(key in run for key in ('coordination_error', 'outer_cleanup_errors',
                                                      'detail_error', 'report_binding_error')),
                        'Visible scale identity/coordination/cleanup differs: ' + name)
                raw_path = files[name]
                check_directory(raw_path.parent)
                require(raw_path.name == name and
                        raw_path.parent.resolve(strict=True) == path.parent.resolve(strict=True),
                        'Visible raw report is outside its aggregate directory: ' + name)
                detail = fixture.read_bound_detail(run, path.parent, frozen=frozen)
                require('detail' not in run or fixture.same_json(detail, run['detail']),
                        'Visible inline/raw report types or values differ: ' + name)
                require(fixture.same_json(detail.get('helper'),
                        dict(manifest=helper, sha256=helper['sha256'], size=helper['size'])),
                        'Visible raw helper inventory types or values differ: ' + name)
                fixture.validate_report(detail, scale=scale, frozen=frozen, helper=helper,
                    version=version,
                    executable_sha256=checksum if frozen else None,
                    foreign_proof=run.get('foreign'), foreign_fixture_sha256=foreign['executable_sha256'])
                validated.append({'scale': scale, 'report': name, 'sha256': run['report_sha256'],
                                  'size': run['report_size']})
            summaries.append({'status': 'passed', 'frozen': frozen, 'scope': fixture.SCOPE,
                              'source_commit': source_sha, 'helper_sha256': helper['sha256'],
                              'runs': validated})
    except (AssertionError, RuntimeError, ValueError, TypeError, KeyError, AttributeError, OSError) as exc:
        raise VerificationError('Visible-overlay release evidence failed: ' + str(exc)) from exc
    return summaries


def verify_session_capture(path, source_archive, version, source_sha, build, *, frozen, checksum, exe_size):
    """Application-entrypoint synthetic protocol evidence, separate from UI duty."""
    report = read_json(path)
    helper = build.get('wgc_session_helper_build')
    inventory = build.get('archive_inventory', {})
    require(isinstance(helper, dict) and helper == inventory.get('wgc_session_helper')
            and helper.get('source_commit') == source_sha
            and build.get('wgc_helper_build', {}).get('source_commit') == source_sha,
            'Persistent helper build/bundle/source binding differs')
    try:
        session_capture_fixture.validate_acceptance(report, frozen=frozen, application=True,
            helper_build=helper, source_commit=source_sha, version=version,
            executable_sha256=checksum if frozen else None,
            executable_size=exe_size if frozen else None,
            archive_inventory=inventory if frozen else None)
    except (RuntimeError, ValueError, KeyError, TypeError) as exc:
        raise VerificationError('Application persistent session acceptance failed: ' + str(exc)) from exc
    with zipfile.ZipFile(source_archive) as archive:
        require(archive.comment == source_sha.encode('ascii'), 'Session source archive commit differs')
        for name, record in helper['source_files'].items():
            require(archive.namelist().count(name) == 1, 'Session source input missing/duplicated: ' + name)
            data = archive.read(name)
            require(len(data) == record['size'] and hashlib.sha256(data).hexdigest() == record['sha256'],
                    'Session tested source bytes differ: ' + name)
    kind = 'frozen' if frozen else 'source'
    for row, scale in zip(report['runs'], (1, 1.5, 2)):
        require(row.get('report') == f'windows-wgc-session-application-{kind}-scale{round(scale*100)}.json',
                'Application session scale/report name differs')
    return {'status': 'passed', 'frozen': frozen, 'scales': [1, 1.5, 2],
            'scope': 'Application entrypoint; owned synthetic protocol/lifecycle checks, separate from product UI duty evidence',
            'helper_sha256': helper['sha256'], 'checks': list(session_capture_fixture.CHECK_FIELDS),
            'shutdown_stress_cases': sum(len(row['detail']['shutdown_stress']['rows']) for row in report['runs'])}


def verify_wgc_capture(path, source_archive, version, source_sha, build, *, frozen, checksum, exe_size):
    report = read_json(path)
    require(report.get('schema_version') == 1 and report.get('status') == 'passed' and 'error' not in report
            and report.get('frozen') is frozen and report.get('source_commit') == source_sha
            and report.get('applicationVersion') == version and report.get('scales') == [1, 1.5, 2],
            'WGC acceptance identity, source or scale scope differs')
    if frozen:
        require(report.get('executable_sha256') == checksum and report.get('executable_size') == exe_size,
                'Frozen WGC acceptance tested different application bytes')
    helper = report.get('helper_build')
    require(isinstance(helper, dict) and helper == build.get('wgc_helper_build')
            and helper == build.get('archive_inventory', {}).get('wgc_helper')
            and helper.get('source_commit') == source_sha, 'WGC helper build/bundle identity differs')
    try:
        wgc_fixture.validate_manifest(helper)
    except (RuntimeError, TypeError, KeyError) as exc:
        raise VerificationError('Invalid WGC helper build proof: ' + str(exc)) from exc
    hashes = report.get('source_files')
    require(isinstance(hashes, dict) and set(hashes) == set(wgc_fixture.SOURCE_FILES),
            'WGC tested-source inventory differs')
    with zipfile.ZipFile(source_archive) as archive:
        require(archive.comment == source_sha.encode('ascii'), 'WGC source commit differs')
        for name, expected in hashes.items():
            require(archive.namelist().count(name) == 1 and hashlib.sha256(archive.read(name)).hexdigest() == expected,
                    'WGC tested source bytes differ: ' + name)
    require(helper['source_sha256'] == hashes['native/wgc_capture.cpp']
            and helper['build_recipe_sha256'] == hashes['scripts/build_wgc_capture.py'],
            'WGC compiled native source/recipe differs from tested archive')
    runs = report.get('runs')
    require(isinstance(runs, list) and len(runs) == 3, 'WGC acceptance scale runs missing')
    prefix = 'windows-wgc-frozen' if frozen else 'windows-wgc-source'
    for row, scale in zip(runs, (1, 1.5, 2)):
        require(isinstance(row, dict) and row.get('app_scale') == scale
                and row.get('report') == prefix + '-scale' + str(round(scale * 100)) + '.json',
                'WGC run scale/report identity differs')
        try:
            wgc_fixture.validate_report(row.get('detail'), frozen=frozen, scale=scale, helper_build=helper, version=version)
        except (RuntimeError, TypeError, KeyError) as exc:
            raise VerificationError('WGC acceptance check failed: ' + str(exc)) from exc
    return {'status': 'passed', 'frozen': frozen, 'scales': [1, 1.5, 2],
            'helper_sha256': helper['sha256'], 'checks': list(wgc_fixture.CHECK_FIELDS)}


def verify_adopted_performance(report):
    """Tighter publication screen; seconds throughout, not a universal speed claim."""
    from scripts.probe_opencv_parity import PERFORMANCE_CASES
    performance = report.get('performance', {})
    require(report.get('status') == 'passed' and isinstance(performance, dict)
            and set(performance) == PERFORMANCE_CASES | {'capture_synthetic_window'},
            'Complete same-run performance evidence is required for adoption')
    regressions = []
    for name, row in performance.items():
        require(isinstance(row, dict), 'Malformed timing row: '+name)
        medians = []
        for prefix in ('baseline', 'candidate'):
            samples = row.get(prefix+'_samples_seconds')
            require(isinstance(samples, list) and len(samples) == 7
                    and all(type(value) in (int, float) and math.isfinite(value) and value > 0 for value in samples),
                    'Invalid seven-sample timing evidence: '+name)
            median = statistics.median(samples)
            reported = row.get(prefix+'_median_seconds')
            require(type(reported) in (int, float) and math.isclose(reported, median, rel_tol=1e-12, abs_tol=1e-12),
                    'Reported timing median differs from raw samples: '+name)
            medians.append(median)
        ratio, delta = medians[1]/medians[0], medians[1]-medians[0]
        require(type(row.get('ratio')) in (int, float) and type(row.get('delta_seconds')) in (int, float)
                and math.isclose(row['ratio'], ratio, rel_tol=1e-12, abs_tol=1e-12)
                and math.isclose(row['delta_seconds'], delta, rel_tol=1e-12, abs_tol=1e-12),
                'Reported timing ratio/delta differs from raw samples: '+name)
        if ratio > 1.15 + 1e-12 and delta > 0.005 + 1e-12:
            regressions.append(name)
    require(not regressions, 'Material timing regression; pause publication and review: '+', '.join(regressions))
    return {'status': 'passed', 'policy': {'ratio_above': 1.15, 'delta_seconds_above': 0.005, 'both_required': True},
            'performance': performance}



def verify_postbuild_adoption(evidence_dir, build, source_archive, source_sha):
    """Require the fixed post-build pair and bind measured/restored B to the EXE proof."""
    from scripts import probe_opencv_postbuild as postbuild
    # Resolve only our fixed evidence name/layout, never a path supplied by JSON.
    selected_dir = evidence_file(Path(evidence_dir), 'windows-opencv-postbuild-export.json').parent
    try:
        postbuild.check_directory(selected_dir)
        report_dir = selected_dir.resolve()
        bundle, receipt = postbuild.validate_export(report_dir)
    except (RuntimeError, ValueError, TypeError, KeyError, OSError) as exc:
        raise VerificationError('Post-build comparison/restoration evidence failed: ' + str(exc)) from exc
    require(bundle.get('status') == 'completed' and bundle.get('validation_errors') == []
            and bundle.get('excluded_from_adoption') is False,
            'Post-build comparison/restoration did not complete')
    records = bundle['files']
    result, prepared = records['result']['value'], records['prepared']['value']
    sources = result.get('sources')
    require(isinstance(sources, dict) and sources.get('commit') == source_sha
            and postbuild.same(sources, prepared.get('sources')),
            'Post-build comparison source commit differs')
    inventory = sources.get('files')
    require(isinstance(inventory, dict) and set(inventory) == set(postbuild.SOURCE_FILES),
            'Post-build comparison source inventory differs')
    with zipfile.ZipFile(source_archive) as archive:
        require(archive.comment == source_sha.encode('ascii'), 'Post-build source archive commit differs')
        for name, record in inventory.items():
            require(isinstance(record, dict) and set(record) == {'size', 'sha256'}
                    and type(record.get('size')) is int and 0 < record['size'] <= 1_000_000
                    and isinstance(record.get('sha256'), str) and bool(re.fullmatch('[0-9a-f]{64}', record['sha256'])),
                    'Malformed post-build source record: ' + name)
            require(archive.namelist().count(name) == 1,
                    'Missing or ambiguous post-build source: ' + name)
            raw = archive.read(name)
            require(len(raw) == record['size'] and hashlib.sha256(raw).hexdigest() == record['sha256'],
                    'Post-build source bytes differ: ' + name)
    proof_path = evidence_file(report_dir, 'windows-opencv-build.json')
    proof = read_json(proof_path)
    require(postbuild.same(proof, build.get('opencv_custom_build'))
            and proof.get('source_commit') == source_sha,
            'Post-build custom build proof differs from packaged build')
    try:
        postbuild.verify_record(result.get('build_report_file'), proof_path)
    except (RuntimeError, ValueError, TypeError, KeyError, OSError) as exc:
        raise VerificationError('Post-build custom build raw hash/path differs: ' + str(exc)) from exc
    custom = result.get('custom', {})
    require(custom.get('version') == CUSTOM_VERSION and proof.get('version') == CUSTOM_VERSION,
            'Post-build custom version differs')
    for kind in ('native', 'wheel'):
        measured, built = custom.get(kind), proof.get(kind)
        require(isinstance(measured, dict) and isinstance(built, dict)
                and type(measured.get('size')) is int and type(built.get('size')) is int
                and measured['size'] > 0 and measured['size'] == built['size']
                and measured.get('sha256') == built.get('sha256')
                and isinstance(measured.get('sha256'), str)
                and bool(re.fullmatch('[0-9a-f]{64}', measured['sha256'])),
                'Post-build measured custom ' + kind + ' differs from packaged build')
    require(receipt.get('source_commit') == source_sha,
            'Post-build export source commit differs')
    names = tuple(postbuild.EVIDENCE_NAMES)
    require(len(names) == len(set(names)) and all(isinstance(name, str)
            and re.fullmatch(r'windows-opencv-postbuild-[A-Za-z0-9-]+\.json', name) for name in names),
            'Unexpected post-build evidence inventory')
    # The full strict validator already checks the fresh process identities,
    # complete fixed sequence, all raw payloads and the final B reinstall proof.
    # Existing verify_custom_evidence independently extracts B from the EXE.
    summary = {'status': 'passed', 'fixed_order': list(postbuild.BLOCKS),
               'source_commit': source_sha, 'custom_native_sha256': custom['native']['sha256'],
               'custom_wheel_sha256': custom['wheel']['sha256'],
               'restoration': 'verified',
               'export_sha256': digest(evidence_file(Path(evidence_dir), 'windows-opencv-postbuild-export.json'))}
    return summary, names


def verify(release_dir, evidence_dir, repository, source_sha, output_dir, run_id, run_attempt):
    require(repository == REPOSITORY, 'Repository is not the approved project')
    require(bool(re.fullmatch(r'[0-9a-f]{40}', source_sha)) and type(run_id) is int and run_id > 0 and type(run_attempt) is int and run_attempt > 0, 'Invalid source commit/run')
    release_dir, evidence_dir, output_dir = map(Path, (release_dir, evidence_dir, output_dir))
    manifest = read_json(release_dir / 'update-manifest.json')
    version = manifest.get('version')
    require(isinstance(version, str) and bool(re.fullmatch(r'(0|[1-9][0-9]{0,4})\.(0|[1-9][0-9]{0,4})\.(0|[1-9][0-9]{0,4})', version)), 'Invalid stable version')
    require(type(manifest.get('schema_version')) is int and manifest.get('schema_version') == 1 and manifest.get('platform') == 'windows-x64', 'Unsupported manifest')
    require(all(int(part) <= 65535 for part in version.split('.')), 'Version exceeds Windows resource limits')
    tag = 'v' + version
    filename = f'vga-aram-helper-{version}-windows-x64.exe'
    expected_url = f'https://github.com/{REPOSITORY}/releases/download/{tag}/{filename}'
    require(manifest.get('url') == expected_url, 'Manifest URL/repository/version mismatch')
    exe = checked_file(release_dir / filename)
    require(exe.stat().st_size == manifest.get('size') and type(manifest.get('size')) is int, 'EXE size mismatch')
    checksum = digest(exe)
    require(checksum == manifest.get('sha256'), 'EXE SHA256 mismatch')
    with exe.open('rb') as source:
        require(source.read(2) == b'MZ', 'Asset is not a Windows executable')
    sums = checked_file(release_dir / 'SHA256SUMS.txt').read_text(encoding='ascii').strip()
    require(sums == f'{checksum}  {filename}', 'SHA256SUMS does not match exactly')
    files = {name: evidence_file(evidence_dir, name) for name in EVIDENCE_NAMES}
    build = read_json(files['windows-build.json'])
    try:
        profile = validate_build_profile(build)
    except (RuntimeError, ValueError, TypeError, KeyError) as exc:
        raise VerificationError('Invalid package profile: '+str(exc)) from exc
    experimental = build['experimental']
    adoption = None
    postbuild_adoption = None
    if profile != OFFICIAL_PROFILE:
        try:
            extra = verify_custom_evidence(exe, evidence_dir, build)
            files.update({name: evidence_file(evidence_dir, name) for name in extra})
        except (RuntimeError, ValueError, TypeError, KeyError) as exc:
            raise VerificationError('Custom OpenCV evidence failed: '+str(exc)) from exc
        if profile == ADOPTED_PROFILE:
            postbuild_adoption, extra = verify_postbuild_adoption(evidence_dir, build,
                release_dir / f'vga-aram-helper-{version}-source.zip', source_sha)
            files.update({name: evidence_file(evidence_dir, name) for name in extra})
            adoption = verify_adopted_performance(read_json(files['windows-opencv-parity.json']))
    smoke = read_json(files['windows-exe-smoke.json'])
    selftest = read_json(files['windows-exe-self-test.json'])
    require(build.get('source_commit') == source_sha and build.get('version') == version, 'Build source/version mismatch')
    require(build.get('manifest') == manifest, 'Build and release manifests differ')
    require(build.get('status') == 'built-not-yet-smoke-tested', 'Unexpected build status')
    package_size = read_json(files['windows-package-size.json'])
    ota = read_json(files['windows-ota-smoke.json'])
    require(build.get('package_size') == package_size, 'Build and measured package-size evidence differ')
    try:
        measured = read_archive_measurement(exe, profile=profile)
        require(all(package_size.get(key) == value for key, value in measured.items()),
                'Saved size/model inventory differs from actual release EXE')
        validate_package_evidence(package_size, smoke, ota, source_sha)
    except (RuntimeError, ValueError, TypeError, KeyError) as exc:
        raise VerificationError('Package size, supported formats or candidate OTA gate failed: ' + str(exc)) from exc
    require(package_size.get('pruning', {}).get('retained_pe_imports_checked') is True,
            'Retained PE dependency check is missing')
    require(ota.get('applicationVersion') == version, 'Candidate OTA version differs from release')
    require({m.get('name'): m.get('sha256') for m in build.get('bundled_models', [])} == MODEL_HASHES, 'Build model identity mismatch')
    inventory = build.get('archive_inventory', {})
    require(inventory.get('model_assets') == 3 and set(inventory.get('required_runtime_dlls', [])) ==
            RUNTIME_DLLS,
            'Missing standalone runtime/archive evidence')
    qt_binaries = inventory.get('qt_binaries', [])
    require(isinstance(qt_binaries, list) and qt_binaries and all(isinstance(name, str) for name in qt_binaries),
            'Missing Qt binary archive inventory')
    require(len(qt_binaries) <= 100 and all(len(name) <= 240 for name in qt_binaries), 'Unexpectedly large Qt inventory')
    print(json.dumps({'qt_binaries_under_review': sorted(qt_binaries)}, indent=2), flush=True)
    qt_paths = verify_qt_runtime(qt_binaries)
    try:
        verify_runtime_evidence(inventory.get('microsoft_runtime', {}), qt_paths)
    except (RuntimeError, TypeError, AttributeError) as exc:
        raise VerificationError('Licensed Microsoft runtime evidence is missing or changed: ' + str(exc)) from exc
    require(smoke.get('status') == 'passed' and 'error' not in smoke and smoke.get('executable_sha256') == checksum, 'EXE smoke failed or tested different bytes')
    require(BASELINE_CHECKS.issubset(set(smoke.get('checks', []))), 'Required browser/comparison/OCR smoke evidence is missing')
    require(smoke.get('health', {}).get('applicationVersion') == version, 'HTTP smoke version mismatch')
    require(smoke.get('health', {}).get('ocr_enabled') is True and smoke.get('health', {}).get('status') == 'ok', 'HTTP OCR was not enabled')
    require(selftest.get('status') == 'passed' and 'error' not in selftest and selftest.get('frozen') is True, 'Self-test was not a passing frozen executable')
    require(selftest.get('applicationVersion') == version, 'OCR self-test version mismatch')
    require(selftest.get('recognized') == ['珠光护手', '炼狱导管', '双刀流'] and selftest.get('blank_candidates') == 0, 'OCR result mismatch')
    models = selftest.get('bundled_models', [])
    require(len(models) == 3 and {m.get('name'): m.get('sha256') for m in models} == MODEL_HASHES, 'Bundled model identity mismatch')
    verify_png(files['windows-exe-ui.png'])
    budget = read_json(files['windows-artifact-budget.json'])
    verify_budget(budget, release_dir, files)
    assets = [exe, release_dir / 'update-manifest.json', release_dir / 'SHA256SUMS.txt']
    for name in ('third-party-licenses.zip', 'WINDOWS_EXECUTABLE.md', 'THIRD_PARTY_NOTICES.md', 'LICENSE'):
        assets.append(checked_file(release_dir / name))
    licenses = assets[3]
    with zipfile.ZipFile(licenses) as archive:
        verify_qt_licenses(archive, build)
        try:
            verify_notice_archive(archive, inventory['microsoft_runtime'])
        except (RuntimeError, KeyError, ValueError) as exc:
            raise VerificationError('Microsoft component notices/source proof missing or changed: ' + str(exc)) from exc
    assets.extend(verify_source_access(release_dir, build, source_sha, version))
    if profile != OFFICIAL_PROFILE:
        try:
            verify_custom_notice_archive(release_dir/'third-party-licenses.zip', build['opencv_custom_build'])
            verify_custom_source_archive(release_dir/f'vga-aram-helper-{version}-source.zip', evidence_dir, build)
        except (RuntimeError, KeyError, ValueError, TypeError) as exc:
            raise VerificationError('Custom OpenCV downloadable source/license proof failed: '+str(exc)) from exc
    source_archive = release_dir / f'vga-aram-helper-{version}-source.zip'
    native_scales = [verify_native_scale(files, checksum, version, scale, prefix,
        source_archive, source_sha, exe.stat().st_size) for scale, prefix in NATIVE_SCALES]
    require(len({digest(files[prefix + '-overlay.png']) for _, prefix in NATIVE_SCALES}) == len(NATIVE_SCALES),
            'Native scale screenshots must be distinct original evidence')
    selection_summary = verify_selection_bundle(files, source_archive, version, source_sha, checksum, exe.stat().st_size)
    verify_dpi_matrix(files['windows-dpi-candidate-matrix.json'],
        release_dir / f'vga-aram-helper-{version}-source.zip')
    automatic_capture = verify_automatic_capture(files['windows-automatic-capture.json'],
        release_dir / f'vga-aram-helper-{version}-source.zip',version,source_sha)
    wgc_summary = [verify_wgc_capture(files['windows-wgc-' + kind + '.json'],
        release_dir / f'vga-aram-helper-{version}-source.zip', version, source_sha, build,
        frozen=(kind == 'frozen'), checksum=checksum, exe_size=exe.stat().st_size) for kind in ('source', 'frozen')]
    verify_frozen_wgc_archive(exe, build['wgc_helper_build'])
    session_summary = [verify_session_capture(files['windows-wgc-session-application-' + kind + '.json'],
        source_archive, version, source_sha, build, frozen=(kind == 'frozen'),
        checksum=checksum, exe_size=exe.stat().st_size) for kind in ('source', 'frozen')]
    verify_frozen_session_archive(exe, build['wgc_session_helper_build'])
    visible_summary = verify_visible_capture_bundle(files, source_archive, version, source_sha, build,
                                                    exe, checksum, exe.stat().st_size)
    genuine_counts = verify_genuine_report(files['hero-recognition-genuine.json'],
        release_dir / f'vga-aram-helper-{version}-source.zip', version)
    selection_counts = verify_selection_genuine_report(files['champion-select-genuine.json'],
        release_dir / f'vga-aram-helper-{version}-source.zip', version)
    output_dir.mkdir(parents=True, exist_ok=True)
    require(not output_dir.is_symlink(), 'Output directory cannot be a symlink')
    evidence_zip = output_dir / f'windows-test-evidence-{version}.zip'
    require(not evidence_zip.is_symlink(), 'Evidence output cannot be a symlink')
    with zipfile.ZipFile(evidence_zip, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, path in files.items():
            archive.write(path, arcname=name)
    assets.append(evidence_zip)
    # Exact existing original mock screenshot, already fully PNG-validated above.
    assets.append(files['windows-native-overlay.png'])
    result = {'experimental': experimental, 'package_profile': profile,
              'opencv_build_profile': (build.get('opencv_custom_build') or {}).get('package_profile'),
              'opencv_distribution_version': CUSTOM_VERSION if profile != OFFICIAL_PROFILE else OFFICIAL_VERSION,
              'opencv_adoption': adoption, 'opencv_postbuild': postbuild_adoption, 'repository': REPOSITORY, 'source_sha': source_sha, 'run_id': run_id, 'run_attempt': run_attempt, 'version': version, 'tag': tag,
              'exe_sha256': checksum, 'exe_size': exe.stat().st_size, 'artifact_budget': budget, 'qt_binaries': sorted(qt_paths),
              'wgc_capture_summary': wgc_summary, 'wgc_session_application_summary': session_summary,
              'wgc_visible_overlay_summary': visible_summary,
              'automatic_capture_source_summary': automatic_capture, 'native_scale_summary': native_scales, 'selection_summary': selection_summary, 'package_size': package_size, 'native_ota_summary': {'status': ota['status'], 'cases': [case['case'] for case in ota['cases']]},
              'genuine_screenshot_summary': genuine_counts, 'champion_select_screenshot_summary': selection_counts,
              'genuine_report_versions': {name: read_json(files[name])['applicationVersion'] for name in
                  ('hero-recognition-genuine.json', 'champion-select-genuine.json')},
              'evidence_sha256': {name: digest(path) for name, path in files.items()}, 'assets': [{'name': path.name, 'path': str(path.resolve()),
                'size': path.stat().st_size, 'sha256': digest(path)} for path in assets]}
    (output_dir / 'verified-release.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    notes = (f'VGA startup recovery DIAGNOSTIC PREVIEW {version} / 诊断测试版 (pre-release).\n\n'
             '诊断测试版默认开启可关闭的本地日志：有界日志文件合计最多 768 KiB，导出只替换同一个本地 ZIP，不自动上传。仅记录白名单诊断信息及已匹配的目录英雄/强化名称，不含截图、原始 OCR、玩家账号、凭据或私有路径。用户反馈闪烁已不再出现，但有一次初始识别未成功；未取得该次诊断 ZIP，原因尚不能确认，完整实战验收仍未完成。\n\n'
             '本版不再仅因标题原始像素变化而隐藏或重绘评级；以同帧新鲜语义检查撤销已变化或不确定的标题，保留显示的旧已接受证明仍遵守原有四秒截止时间，绝不因复核而续期。部分候选独立核验已确认槽位，未知卡片不显示旧评级；新 OCR 返回前可能短暂保留旧评级，不保证即时发现换牌。单独的关键事件记录与常规采样保留小体积因果日志。新增选人路径门槛诊断，不宣称已修好真实客户端。接受阈值、歧义规则、新鲜度和失败时隐藏的安全边界不放宽；选人接口仍默认关闭，仅本次启动授权。Windows 受控验收不等同于用户国服实战已验收。\n\n'
             '本候选修复可复现的启动恢复缺陷：空头像库遇临时失败时按 30/60/120/300 秒有上限退避重试；完整已验证缓存先交付，再尝试联网刷新；完整头像库写盘失败时使用不可变的已验证内存规范映射；畸形 roster 和缓存对象安全拒绝，不阻断独立 HUD/卡片 OCR。保留单工作租约、停止/关闭/模式门槛与身份、新鲜度、两次独立确认等约束。可复现缺陷不等于已确认用户那次初始漏识别的原因。\n\n'
             f'The public still-image reports were rerun for v{version}; every evaluated module must match the release source byte-for-byte. These limited Linux still-image observations are not actual-game verification.\n\n'
             'Native overlay PREVIEW with screenshot-based identification of the player’s own bottom-HUD portrait and separate local API controls: current-game read-only identity is enabled by default with a saved Off switch; selection/bench access remains default-off for the current launch. '
             'When the hero and candidate names are stable and confident, their literal source tiers from the public dataset appear automatically. Two independent fresh title observations can display verified slots while unknown slots remain blank; changed slots never borrow the old grade. '
             'This candidate combines the selected light dashboard with bounded HWND-only Windows Graphics Capture, off-GUI capture and cleanup, '
             'fixes Chinese exact-title matching and reuses identical title OCR only after two independent confirmations. '
             'The persistent helper reuses one explicitly authorized target and permits visible CPU acquisition only for the exact enrolled owned opaque overlay with WDA_EXCLUDEFROMCAPTURE (17), after all registration and freshness checks pass. '
             'Idle overlay exclusion never exempts other windows, and every request retains fresh identity/geometry/focus/occlusion/ROI and timestamp checks. '
             'Stop and invalidation revoke immediately, with off-GUI ownership cleanup blocking replacement. Initial unsupported capability may use the original guarded single-shot path; later persistent failures remain fail-closed. '
             'The user-selected interactive overlay mode retires the session before using the strict-hide single-shot path; it is not an automatic error fallback. '
             'The normal system capture border stays enabled. Idle GPU frame-pool surfaces may continue until revocation is detected; scheduled checks do not guarantee a 50 ms close under a blocked driver. '
             'Foreign occlusion, changed identities and missing/minimized windows pause safely and retry. '
             'The unchanged OCR models and approved minimal OpenCV package profile are retained. '
             'This candidate adds stable window-identity comparisons independent of caption changes, verified untitled-window discovery, and bounded window/focus/capture diagnostic reasons. '
             'One reusable bounded worker overlaps same-frame HUD and OCR processing; this is not a guaranteed live-game speedup. '
             'Two separate controls permit verified local HTTPS read-only selection/bench IDs and current-self identity, with no raw identities or credentials logged. Two independently confirmed own identities may be retained through death/countdown or transient API failure only within the exact verified game process and canonical source mapping. Retained identity is labelled historical; current cards still require independent fresh proof and expire after four seconds. Stop, process/client/source changes and explicit contradictions revoke identity. Starting monitoring stays visible by default, with optional saved auto-minimization. Three disjoint opaque native regions display tiers and short source-backed combo examples above freshly detected card bounds; no win rates, selected-history assumptions or live-optimal claims are shown. '
             'The confirmed Qt logical/Win32 physical coordinate mismatch and rigid overlay layout fixes remain included. '
             'The historical cache-lock owner is not established; current diagnostics distinguish observed write failures without inventing their owner. '
             'Screenshot-only champion-select name detection now exposes the exact assigned hero’s public T1–T5 overall tier as a separate provisional reference, without confirming augment choices. '
             'The control-only last-candidates record preserves literal previous source fields and labels the final choice unknown; no selected augment is inferred from disappearing cards. '
             'Completion-driven capture cadence and accepted-frame proof can keep or restore explicitly labelled previous/rechecking candidates during inference without renewing their original four-second expiry. '
             'This diagnostic prerelease enables local logs by default, with a visible Settings Off switch. Bounded on-disk log files have an aggregate 768 KiB budget; one local ZIP is replaced on export. No automatic upload occurs. '
             'Correlated frame IDs, hide reasons, stage timings, confirmation gates and matched catalog hero/augment names are recorded; screenshots, raw OCR text, player/account identity, credentials and private paths are excluded. '
             'A separate critical-event ledger and routine sampling preserve compact causal diagnostics; bounded lifetime summaries survive rotation, and exports disclose dropped or truncated detail. '
             'Raw title pixel variation alone no longer hides or repaints grades. Fresh same-frame semantic checks revoke changed or uncertain titles; any retained accepted proof keeps its original four-second deadline, never renewed by rechecking. Partial candidates preserve independently verified known slots without grading unknown slots. A real reroll may retain its old grade until fresh OCR returns; detection is not instantaneous. Controlled non-game fixtures do not establish live-game stability. Selection-route gate diagnostics explain eligibility and routing; they are not proof of a fixed real-client selection path. Earlier same-card provenance/tier stability and threshold-equivalent fuzzy pruning remain included. '
             'Startup recovery now retries an empty portrait bank after transient download failure with 30/60/120/300-second capped backoff and a single worker lease. A complete validated cache is delivered before network refresh; a failed or empty refresh cannot remove it. A completely verified bank has an immutable in-memory fallback for the canonical public token-to-ID map when disk persistence fails. Explicit shape checks reject malformed nested roster data and invalid cache objects without aborting independent HUD/card OCR. Stop/Start does not reset backoff; stopped monitoring, manual mode, disabled updates, Close, stale attempts and duplicate callbacks cannot overlap retries or replace current assets. No cached player identity is added; API double-read/self-match, process scope, HUD contradiction, per-slot confirmation and freshness thresholds are unchanged. '
             'User feedback reports that flicker is no longer observed, but an isolated initial recognition miss remains unexplained; no incident diagnostic ZIP was supplied. The reproduced recovery defects are not a confirmed cause of that incident. Other startup failures and broader acceptance in actual gameplay remain unverified; this is a diagnostic build, not a claim that every live-game cause is fixed. '
             'A carried selection identity is labelled provisional until independently verified by the own-HUD portrait; contradictory or expired evidence clears it. '
             'Window scoping uses limited OS executable-path/creation-time metadata, without process-memory reads. '
             'Official Data Dragon base-portrait templates are cached locally at runtime, not bundled in the EXE. '
             'Unsupported skins, transformations or layouts may require manual correction; uncertain matches are withheld. '
             'Ungraded or unmatched live inputs remain '
             'neutral; no invented grade, synthetic upgrade or inferred ranking. This is not a claim of a finished '
             'Huya-equivalent product or real-game validation.\n\n'
             f'Tested source commit: {source_sha}\nEXE SHA256: {checksum}\n'
             f'Actual release size: {exe.stat().st_size:,} bytes; {package_size["saved_bytes"]:,} bytes ({package_size["saved_percent"]:.3f}%) smaller than v{package_size["baseline"]["version"]}.\n'
             f'Tested Windows run: https://github.com/{REPOSITORY}/actions/runs/{run_id}\n\n' +
             (f'OpenCV distribution: {CUSTOM_VERSION}, a maintained downstream build from pinned official source; '
              'the application source ZIP includes its exact recipe and packaging-only patches, and the complete supplemental notices are included. '
              'All three OCR models are unchanged. Same-run image/OCR/hero outputs match the official wheel. '
              'The fixed official-to-custom timing pair runs after the native build in fresh interpreters, with exact offline wheel payloads, complete owned-child cleanup and verified custom restoration before packaging. '
              'The release timing screen requires no operation to be both over 15% and over 5 ms slower; raw seven-sample timings are attached. '
              'This is limited fixture evidence, not a speed guarantee for every computer. '
              'ORT_DISABLE_TELEMETRY=1 is set before runtime initialization and the API opt-out remains; this is not a general network firewall.\n\n'
              if profile == ADOPTED_PROFILE else '') +
             'Separate source and exact-frozen-EXE WGC fixtures at application scales 1, 1.5 and 2 require the WGC backend, original owned-window pixel/ROI agreement, stale/closed/resized/focus/protected-window rejection and bounded helper cleanup. '
             'Additional source and actual-application-EXE session fixtures at all three scales require static-frame freshness, exact opaque profile/exclusion, strict negatives, parent/lease cleanup and sixty fresh-helper Stop/EOF stress cases in total. '
             'Separate source and exact-frozen-EXE visible-overlay fixtures at all three scales use the ordinary ControlWindow() constructor, preserve the visible owned overlay across two GUI capture cycles including changed target ROI pixels, and bind both aggregates to all six original raw reports. '
             'Those visible checks retain hidden-reference pixel equality, strict negative cases and exact helper/foreign-process cleanup; they do not establish live-game, borderless or exclusive-fullscreen behavior. '
             'Those synthetic protocol checks remain separate from the actual product Overlay/backend duty measurement, which requires both full five-case single-shot and persistent passes in the same owned scene, real persistent request receipts and helper reuse, Stop responsiveness and cleanup. '
             'Declared inference holds and raw observed hidden/acquisition/visible timings are recorded without a speed-factor guarantee. '
             'A source-only Windows fixture separately verifies no-HWND automatic discovery, lifecycle recovery, guarded compositor fallback and cleanup; its publisher trust is injected only for exact owned test binaries. Native offline signature API checks use signed/unsigned/tampered files. This is distinct from the packaged-EXE tests. '
             'Machine-verified on a standard Windows runner against an ORIGINAL SYNTHETIC MOCK WINDOW only: '
             'the SAME frozen EXE at controlled QT_SCALE_FACTOR 1, 1.5 and 2 on an unchanged 96-DPI desktop, '
             'each with a fixed physical 960x600 owned mock client fully inside the work area and an overlay strictly inside that client. '
             'Each scale independently exercises frozen QtWidgets native windows, local capture/portrait matching/OCR, automatic hero and three-choice flow, '
             'unknown/changed-hero clearing, manual fallback, hide-before-capture, click-through, close/cleanup, source-tier rendering '
             '(including missing-grade fallback, original slot order and no displayed win rate/rank), partial two-slot rendering with an unknown middle slot and fresh full recovery, and visible child/text layout checks. '
             'Baseline HTTP/browser tests also ran once on that same EXE; frozen OCR independently decoded PNG, JPEG, WebP and BMP. '
             'The same exact candidate also passed local native OTA success/concurrency and mismatched-version rollback with OCR health checks. '
             'This is a same-binary fixture test, not a genuine two-version upgrade, live GitHub download/discovery or UI confirmation handoff. '
             'A separate owned synthetic client/game fixture exercises actual Windows metadata and screenshot-based selection-to-game carry; ambiguity and stale-session cases are focused state tests. '
             'A separate same-build source-only Windows matrix at application scales 1, 1.25, 1.5, 2 and 2.5 checks required visible layouts, '
             'three-card text/tier containment, repeated placement, target translation and safe hide/recovery; its four implementation file hashes exactly match the attached application source ZIP. '
             'That source matrix does not test the frozen EXE, pixels, input or real game. '
             'Controlled application scaling does not establish real OS 125/150/200/250-percent monitor behavior, mixed-DPI monitor transitions, full visible 4K or visual font quality. '
             'Screenshots and machine evidence are attached; this statement does not claim human visual inspection. '
             'No process-memory reads, game injection, Vanguard approval or real-game compatibility claim. '
             f'A separate source-bound Linux still-screenshot report records {genuine_counts["positive_recognized"]}/{genuine_counts["positive_cases"]} selected positive examples recognized, '
             f'{genuine_counts["positive_abstained"]} positive abstention, {genuine_counts["negative_abstained"]}/{genuine_counts["negative_cases"]} selected negatives withheld, and no observed wrong hero in this small sample. '
             'It includes one still-frame hero-and-three-title observation, not temporal, all-hero or live-game accuracy proof. '
             'Champion-select text was also evaluated on one modified-client positive and three prerelease unassigned-card images from only two distinct scenes; all four recorded cases behaved as expected. '
             'This does not establish current unmodified client coverage or real trade/cancel behavior. '
             'Windows 10/11 clean machines, exclusive fullscreen and live-game OCR remain unverified.\n'
             'Unsigned executable: SmartScreen may warn about an unknown publisher. No signing or antivirus certification claim.\n'
             'This is prerelease=true. The existing stable /releases/latest OTA endpoint does NOT discover this preview. '
             f'Download manually if you choose to try it. The fixed {tag} tag preserves the tested immutable manifest URL.\n\n'
             'MICROSOFT RUNTIME TERMS: READ BEFORE USE\n'
             'Using the bundled Microsoft Visual C++ runtime components requires agreement to their Microsoft end-user terms. '
             f'Read [the same-release complete terms and scope notice](https://github.com/{REPOSITORY}/releases/download/{tag}/third-party-licenses.zip), '
             'under microsoft-runtime/MICROSOFT_VISUAL_CPP_2015_2022_RUNTIME_TERMS.txt and MICROSOFT_RUNTIME_NOTICE.txt, before use. '
             'These conditions apply only to the five named Microsoft CRT DLLs, not the MIT application or LGPL Qt components. '
             'The publisher distribution basis is the approved Visual Studio Community 2022 installation/use and its Section 4; '
             'the runtime end-user terms themselves do not grant redistribution rights. The build record proves installed product, '
             'Microsoft signatures, x64 dependency inspection and unchanged source-to-EXE DLL hashes.\n\n'
             'QT / PYSIDE / SHIBOKEN: LGPLv3\n'
             'Applicable Qt, PySide6 and Shiboken6 6.11.2 shared libraries are offered under LGPLv3. '
             'Their notices and complete LGPL/GPL license texts are in third-party-licenses.zip, including '
             'qt-licenses/NOTICE.txt and qt-licenses/SOURCE_AND_RELINKING.txt. '
             'source-access.json identifies the matching four official source tar.xz archives and their SHA256 hashes, '
             'available alongside this binary in the SAME release, plus the same-commit application source ZIP '
             '(including specification, resources and build scripts). Corresponding sources remain available alongside the binary '
             'for as long as required by the applicable licenses.\n'
             'Recipients may modify the LGPL components, recombine/relink the application, and reverse-engineer/debug '
             'those modifications under the applicable license terms. No secret signing key is needed to run a modified build. '
             'This supplies a source/rebuild route under LGPLv3 section 4(d)(0); temporary one-file extraction is NOT claimed '
             'as a user-replaceable mechanism under section 4(d)(1).\n\n'
             'RECIPIENT REBUILD ROUTE (not represented as a tested modified-library rebuild)\n'
             'Use native Windows x64, MSVC 2022 x64 development tools, Python 3.12 x64, Git, CMake and Ninja. '
             'Extract the attached same-commit application source ZIP and the exact matching Qt/PySide/Shiboken sources. '
             'The packaging script uses git archive, so initialize the extracted application directory as your own local Git repository, '
             'commit its source/resources using your own Git identity, and commit later source changes before building. '
             'Follow the official Qt and Qt for Python instructions to build ABI-compatible modified 6.11.2 shared libraries:\n'
             'https://doc.qt.io/qt-6.11/windows-building.html\n'
             'https://doc.qt.io/qtforpython-6/building_from_source/index.html\n'
             'Prepare the remaining pinned requirements before replacing Qt. Install the modified ABI-compatible Qt/PySide/Shiboken '
             'libraries into that same Python packaging environment. Read and accept the Community terms before preparing licensed '
             'CRT inputs. The supplied install-community-runtime.ps1 -AcceptCommunityLicense route is limited to an ephemeral GitHub-hosted '
             'Windows runner; use your own source fork/workflow, or adapt that open-source preparation step under your own valid license '
             'for local tooling while retaining signature, dependency and source checks. From the application source root run:\n'
             'python scripts/build_windows.py\n'
             'Do not reinstall the official pinned Qt wheels after installing modified libraries. Retain the native resources/specification, '
             'record your modifications and their source, and run the supplied Windows/native acceptance tests on your rebuilt EXE. '
             'Version identity checks require ABI-compatible 6.11.2; adapt documented packaging checks if your intended modification changes '
             'that identity, preserving accurate notices/source availability.\n')
    links = [('Complete license and notice ZIP', 'third-party-licenses.zip'),
             ('Source inventory and SHA256 hashes', 'source-access.json'),
             ('Same-commit application source, specification and resources', f'vga-aram-helper-{version}-source.zip')]
    links += [('Corresponding source: ' + row['filename'], row['filename']) for row in QT_SOURCES]
    links += [('Original synthetic native overlay screenshot', 'windows-native-overlay.png'),
              ('Test evidence including limited genuine screenshot report', f'windows-test-evidence-{version}.zip')]
    notes += '\nSAME-RELEASE FILES AND CORRESPONDING SOURCES\n'
    notes += ''.join(f'- [{label}](https://github.com/{REPOSITORY}/releases/download/{tag}/{name})\n'
                     for label, name in links)
    (output_dir / 'release-notes.txt').write_text(notes, encoding='utf-8')
    return result


def gh_run(arguments):
    # The token is only supplied to the final workflow step. Never read it,
    # write it to disk, authenticate persistently, or include it in argv/output.
    command = subprocess.run(['gh', *arguments], capture_output=True, text=True,
                             check=False, timeout=300)
    if command.returncode:
        raise VerificationError('GitHub command failed; publication stopped without cleanup')
    return command.stdout


def gh_api(path, allow_absent=False, fields=None):
    arguments = ['gh', 'api', '--hostname', 'github.com',
                 '-H', 'Accept: application/vnd.github+json', path]
    if fields is not None:
        arguments += ['--method', 'POST']
        for key, value in fields.items():
            arguments += ['--raw-field', f'{key}={value}']
    command = subprocess.run(arguments, capture_output=True, text=True,
                             check=False, timeout=300)
    if command.returncode:
        if allow_absent and '(HTTP 404)' in command.stderr:
            return None
        # Fail closed on all authentication, validation and network errors.
        raise VerificationError('GitHub API check failed; publication stopped without cleanup')
    return json.loads(command.stdout)


def find_release(repo, tag):
    # The tag endpoint documents published releases only. Listing with this
    # job's write token also finds pre-existing drafts, so they cannot be reused.
    matches = []
    for page in range(1, 101):
        rows = gh_api(f'repos/{repo}/releases?per_page=100&page={page}')
        require(isinstance(rows, list), 'Invalid release listing')
        matches.extend(row for row in rows if row.get('tag_name') == tag)
        require(len(matches) <= 1, 'Ambiguous releases for version tag')
        if len(rows) < 100:
            return matches[0] if matches else None
    raise VerificationError('Release listing limit reached; refusing to guess absence')


def check_tag(reference, tag, sha):
    require(isinstance(reference, dict) and reference.get('ref') == 'refs/tags/' + tag and
            reference.get('object', {}).get('sha') == sha and
            reference.get('object', {}).get('type') == 'commit',
            'Tag does not point directly at the exact tested commit')


def check_remote_assets(release, assets):
    remote = release.get('assets', [])
    require(len(remote) == len(assets), 'Unexpected or incomplete release asset list')
    for asset in assets:
        matches = [item for item in remote if item.get('name') == asset['name']]
        require(len(matches) == 1, 'Missing or ambiguous uploaded asset')
        item = matches[0]
        require(item.get('state') == 'uploaded' and item.get('size') == asset['size'], 'Remote asset size/state mismatch')
        require(item.get('digest') == 'sha256:' + asset['sha256'], 'Remote asset SHA256 mismatch or unavailable')


def publish(verified, notes_file, provenance):
    require(verified.get('experimental') is not True, 'Experimental custom dependencies are not approved for publication')
    require(verified.get('package_profile') == ADOPTED_PROFILE
            and verified.get('opencv_build_profile') == ADOPTED_PROFILE
            and verified.get('opencv_distribution_version') == CUSTOM_VERSION,
            'This release requires the explicitly adopted, provenance-bound OpenCV profile')
    adoption = verified.get('opencv_adoption')
    require(isinstance(adoption, dict) and adoption == verify_adopted_performance(adoption),
            'Adopted timing evidence differs from the publishing policy')
    postbuild = verified.get('opencv_postbuild')
    require(isinstance(postbuild, dict) and postbuild.get('status') == 'passed'
            and postbuild.get('fixed_order') == ['A1', 'B1']
            and postbuild.get('restoration') == 'verified'
            and postbuild.get('source_commit') == verified.get('source_sha')
            and isinstance(postbuild.get('export_sha256'), str)
            and bool(re.fullmatch('[0-9a-f]{64}', postbuild['export_sha256']))
            and postbuild['export_sha256'] == verified.get('evidence_sha256', {}).get('windows-opencv-postbuild-export.json'),
            'Post-build adoption sequence or restoration binding is missing')
    check_preview_identity(verified, provenance)
    repo, tag, sha = verified['repository'], verified['tag'], verified['source_sha']
    require(repo == REPOSITORY and tag == 'v' + verified['version'] and
            re.fullmatch(r'v[0-9]{1,5}\.[0-9]{1,5}\.[0-9]{1,5}', tag) and
            re.fullmatch(r'[0-9a-f]{40}', sha), 'Publication identity mismatch')
    # No overwrite, clobber, update-ref, delete, reset, or automatic retries.
    require(gh_api(f'repos/{repo}/git/ref/tags/{tag}', allow_absent=True) is None, 'Tag already exists; never overwrite')
    require(find_release(repo, tag) is None, 'Release already exists; never overwrite')
    assets = verified['assets']
    for asset in assets:
        path = checked_file(asset['path'])
        require(path.stat().st_size == asset['size'] and digest(path) == asset['sha256'], 'Asset changed after verification')
    checked_file(notes_file)
    # Draft release creation may defer creation of its tag. Reserve the tag
    # atomically first: POST fails if another writer won, even for the same SHA.
    # A later failure intentionally leaves the tag/draft for manual inspection.
    reference = gh_api(f'repos/{repo}/git/refs', fields={'ref': 'refs/tags/' + tag, 'sha': sha})
    check_tag(reference, tag, sha)
    check_tag(gh_api(f'repos/{repo}/git/ref/tags/{tag}'), tag, sha)
    command = ['release', 'create', tag, '--repo', repo, '--target', sha, '--verify-tag', '--draft', '--prerelease', '--latest=false',
               '--title', f'VGA Capture Stability DIAGNOSTIC PREVIEW {verified["version"]} / 诊断测试版', '--notes-file', str(notes_file)]
    command += [asset['path'] for asset in assets]
    gh_run(command)
    # Creating/uploading while draft prevents OTA from seeing incomplete assets.
    release = find_release(repo, tag)
    require(isinstance(release, dict), 'Created draft release is missing')
    require(release.get('draft') is True and release.get('prerelease') is True and release.get('tag_name') == tag, 'Unexpected created release')
    require(release.get('target_commitish') == sha, 'Release target differs from tested source')
    require(type(release.get('id')) is int and release['id'] > 0, 'Created release has no stable identity')
    check_remote_assets(release, assets)
    check_tag(gh_api(f'repos/{repo}/git/ref/tags/{tag}'), tag, sha)
    # Publish only the specific verified draft, never resolve the mutable tag again.
    # gh --field converts false to a JSON boolean; no shell or token persistence.
    gh_run(['api', '--hostname', 'github.com', '--method', 'PATCH',
            '-H', 'Accept: application/vnd.github+json',
            f'repos/{repo}/releases/{release["id"]}', '--field', 'draft=false',
            '--field', 'prerelease=true', '--raw-field', 'make_latest=false'])
    final = gh_api(f'repos/{repo}/releases/{release["id"]}')
    check_tag(gh_api(f'repos/{repo}/git/ref/tags/{tag}'), tag, sha)
    require(final.get('draft') is False and final.get('prerelease') is True and final.get('id') == release['id'] and
            final.get('tag_name') == tag and final.get('target_commitish') == sha,
            'Published release identity verification failed')
    check_remote_assets(final, assets)
    expected_url = f'https://github.com/{repo}/releases/tag/{tag}'
    require(final.get('html_url') == expected_url, 'Unexpected release URL')
    return expected_url


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--release-dir', type=Path, required=True)
    parser.add_argument('--evidence-dir', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--repository', required=True)
    parser.add_argument('--source-sha', required=True)
    parser.add_argument('--run-id', type=int, required=True)
    parser.add_argument('--run-attempt', type=int, required=True)
    parser.add_argument('--publish', action='store_true')
    args = parser.parse_args()
    result = verify(args.release_dir, args.evidence_dir, args.repository, args.source_sha, args.output_dir, args.run_id, args.run_attempt)
    require(result['version'] == PREVIEW_VERSION, f'This manual preview approval covers v{PREVIEW_VERSION} only')
    summary = {key: result[key] for key in ('repository', 'run_id', 'run_attempt', 'source_sha', 'version', 'tag',
                                          'exe_sha256', 'exe_size', 'artifact_budget', 'qt_binaries', 'native_scale_summary', 'selection_summary', 'package_size', 'native_ota_summary', 'genuine_screenshot_summary', 'champion_select_screenshot_summary')}
    summary.update(prerelease=True, release_asset_count=len(result['assets']),
                   evidence_file_count=len(result['evidence_sha256']), evidence_sha256=result['evidence_sha256'])
    print(json.dumps(summary, indent=2), flush=True)
    if args.publish:
        check_runner_context(args.repository, args.source_sha, args.run_id, args.run_attempt)
        provenance = verify_run_provenance(args.repository, args.source_sha, args.run_id, args.run_attempt)
        print(publish(result, args.output_dir / 'release-notes.txt', provenance))


if __name__ == '__main__':
    main()

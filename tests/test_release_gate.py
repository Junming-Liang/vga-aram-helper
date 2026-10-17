"""Offline release gate tests. No GitHub request or external mutation is made."""
import ast
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import struct
import zlib
import hashlib
import tempfile
import unittest
from unittest.mock import patch
import zipfile
from tests.test_microsoft_runtime import runtime_fixture
from scripts import microsoft_runtime as ms_runtime
from scripts import minimal_opencv_package as custom_package
from scripts.probe_opencv_parity import PERFORMANCE_CASES
from tests.test_native_packaging import overlay_duty_fixture, NativePackagingTests
from tests.test_windows_selection_smoke import SelectionHarnessTests
from tests.test_visible_release_binding import visible_reports, write_visible_reports

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('verify_release', ROOT / 'scripts' / 'verify_release.py')
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)
SHA = 'a' * 40
RUN_ID = 987654321
RUN_ATTEMPT = 1
from app_version import __version__ as VERSION


def current_provenance():
    return {'repository': gate.REPOSITORY, 'source_sha': SHA, 'run_id': RUN_ID, 'run_attempt': RUN_ATTEMPT,
            'workflow': gate.PREVIEW_WORKFLOW, 'event': 'workflow_dispatch', 'branch': 'main'}


def adoption_timing_fixture(baseline=0.2, candidate=0.204):
    row = {'baseline_samples_seconds': [baseline]*7, 'candidate_samples_seconds': [candidate]*7,
           'baseline_median_seconds': baseline, 'candidate_median_seconds': candidate,
           'ratio': candidate/baseline, 'delta_seconds': candidate-baseline, 'regression': False}
    return {'status': 'passed', 'performance': {name: copy.deepcopy(row)
            for name in PERFORMANCE_CASES | {'capture_synthetic_window'}}}


def source_matrix_fixture():
    """Original synthetic report data; no Qt or Windows runtime is invoked."""
    harness = gate.dpi_matrix
    children = []
    for scale in harness.SCALES:
        rows = []
        for case in harness.CASES:
            name, width, height, offset, _ = case
            expectation = harness.expectation_for(case, scale)
            shown = expectation != 'hidden'
            rows.append(dict(id=name, expectation=expectation, visible=shown,
                target_fully_onscreen=True, target_native_visible=True, same_process_owned_windows=True,
                target_pmv2=True, overlay_pmv2=True, target_dpi=96,
                qt_window_dpr=float(scale), target_qt_scale_mismatch=float(scale) != 1.,
                target_client_physical=harness.rectangle(10 + offset, 10 + offset, width, height),
                overlay_window_physical=harness.rectangle(20 + offset, 20 + offset, min(width - 20, 900), min(height - 20, 200)),
                native_badge_regions_verified=shown, target_hit_test_baseline=shown, gap_hit_test_passed=shown, badge_above_cards_verified=shown,
                geometry_mapping_matches=True, layout_issues=[], visible_card_count=3 if shown else 0,
                visible_tier_count=3 if shown else 0,
                visible_card_names=list(harness.EXPECTED_CARD_NAMES) if shown else [],
                visible_tier_text=list(harness.EXPECTED_TIERS) if shown else [],
                visible_source_attribution=harness.EXPECTED_SOURCE if shown else None,
                tier_accessible_names=list(harness.EXPECTED_ACCESSIBLE_TIERS) if shown else [],
                error=None if shown else 'Layout does not fit', error_type=None if shown else 'CaptureUnavailable'))
        children.append(dict(qt_scale_factor=scale, status='completed', process_exit_code=0,
            qt_platform='windows', frozen=False, process_pmv2=True, badge_lifecycle_verified=True, badge_reference_transition_verified=True, owned_windows_destroyed=True,
            cases=rows, timed_out=False))
    return dict(schema_version=1, status='candidate_passed', expect='candidate',
        scope=copy.deepcopy(harness.SCOPE), os_name='nt', gate_errors=[], children=children)


class ReleaseFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.release = self.root / 'release'
        self.evidence = self.root / 'evidence'
        self.output = self.root / 'verified'
        self.release.mkdir()
        self.evidence.mkdir()
        self.filename = f'vga-aram-helper-{VERSION}-windows-x64.exe'
        self.exe = self.release / self.filename
        self.exe.write_bytes(b'MZ' + b'fake executable for gate unit testing' * 10)
        self.hash = gate.digest(self.exe)
        self.manifest = {'schema_version': 1, 'version': VERSION, 'platform': 'windows-x64',
                         'url': f'https://github.com/{gate.REPOSITORY}/releases/download/v{VERSION}/{self.filename}',
                         'sha256': self.hash, 'size': self.exe.stat().st_size}
        self.write_json(self.release / 'update-manifest.json', self.manifest)
        (self.release / 'SHA256SUMS.txt').write_text(f'{self.hash}  {self.filename}\n', encoding='ascii')
        for name in ('LICENSE', 'WINDOWS_EXECUTABLE.md', 'THIRD_PARTY_NOTICES.md'):
            (self.release / name).write_text('Unit-test license/document fixture.\n', encoding='utf-8')
        models = [{'name': name, 'sha256': digest} for name, digest in gate.MODEL_HASHES.items()]
        self.build = {'status': 'built-not-yet-smoke-tested', 'source_commit': SHA, 'version': VERSION,
                      'manifest': self.manifest, 'bundled_models': models,
                      'archive_inventory': {'model_assets': 3, 'required_runtime_dlls':
                          sorted(gate.RUNTIME_DLLS), 'qt_binaries': ['PySide6/' + name for name in sorted(gate.QT_RUNTIME_DLLS - {'qwindows.dll'})] + ['PySide6/plugins/platforms/qwindows.dll']}}
        # Release fixture bytes are synthetic. Dedicated custom-package tests
        # exercise the complete provenance, CArchive, license ZIP and source bindings.
        self.custom_proof = {'status': 'passed', 'version': custom_package.CUSTOM_VERSION,
                             'package_profile': gate.ADOPTED_PROFILE, 'source_commit': SHA}
        self.build.update(package_profile=gate.ADOPTED_PROFILE, experimental=False,
                          opencv_custom_build=self.custom_proof)
        for name, result in (('verify_custom_evidence', custom_package.EVIDENCE_NAMES),
                             ('verify_custom_notice_archive', None), ('verify_custom_source_archive', None)):
            wrapper = patch.object(gate, name, return_value=result)
            wrapper.start(); self.addCleanup(wrapper.stop)
        for name in custom_package.EVIDENCE_NAMES:
            self.write_json(self.evidence/name, adoption_timing_fixture() if name.endswith('-parity.json') else {'unit_fixture': True})
        # The post-build validator has dedicated raw/source/EXE-proof binding tests.
        # This all-product fixture keeps its new evidence file and publication binding explicit.
        self.postbuild_names = ('windows-opencv-postbuild-export.json',)
        self.write_json(self.evidence/self.postbuild_names[0], {'unit_fixture': 'postbuild-export'})
        self.postbuild_summary = {'status': 'passed', 'fixed_order': ['A1', 'B1'],
            'source_commit': SHA, 'custom_native_sha256': 'a'*64, 'custom_wheel_sha256': 'b'*64,
            'restoration': 'verified', 'export_sha256': gate.digest(self.evidence/self.postbuild_names[0])}
        wrapper = patch.object(gate, 'verify_postbuild_adoption',
            return_value=(self.postbuild_summary, self.postbuild_names))
        wrapper.start(); self.addCleanup(wrapper.stop)
        self.build['archive_inventory']['qt_binaries'] += ['pyside6/' + row['filename'] for row in runtime_fixture()['files']]
        proof = runtime_fixture()
        paths = ['pyside6/' + row['filename'] for row in proof['files']] + ['msvcp140.dll', 'vcruntime140.dll', 'vcruntime140_1.dll']
        self.build['archive_inventory']['microsoft_runtime'] = {'provenance': proof, 'embedded_files': [
            {'path': path, 'size': 2048, 'sha256': hashlib.sha256(b'X' * 2048).hexdigest()} for path in sorted(paths)]}
        self.smoke = {'status': 'passed', 'executable_sha256': self.hash,
                      'checks': sorted(gate.BASELINE_CHECKS),
                      'health': {'status': 'ok', 'applicationVersion': VERSION, 'ocr_enabled': True}}
        self.smoke['supported_image_formats'] = {kind: ['星火共鸣（演示）', '晶盾回路（演示）', '风步微光（演示）']
                                                  for kind in ('PNG', 'JPEG', 'WEBP', 'BMP')}
        self.package_size = {'schema_version': 1, 'status': 'passed', 'source_commit': SHA,
            'executable': {'size': self.manifest['size'], 'sha256': self.hash},
            'saved_bytes': 150291542 - self.manifest['size'], 'saved_percent': 99.999,
            'baseline': {'version': '0.4.2'},
            'pruning': {'retained_pe_imports_checked': True}}
        self.build['package_size'] = self.package_size
        # Tiny synthetic EXE fixtures test gate logic. Only the archive reader is
        # substituted; production always reparses and rehashes the actual EXE.
        archive_patch = patch.object(gate, 'read_archive_measurement', return_value=copy.deepcopy(self.package_size))
        archive_patch.start(); self.addCleanup(archive_patch.stop)
        self.ota = {'status': 'passed', 'executable_sha256': self.hash, 'executable_bytes': self.manifest['size'],
            'applicationVersion': VERSION, 'release_source_commit': SHA, 'harness_source_commit': SHA,
            'all_owned_processes_exited': True,
            'cases': [{'case': kind, 'status': 'passed', 'original_sha256': self.hash,
                      'target_sha256': self.hash, 'actual_file_identity_changed': True}
                     for kind in ('success-concurrency', 'version-mismatch-rollback')]}
        self.selftest = {'status': 'passed', 'frozen': True, 'applicationVersion': VERSION,
                         'recognized': ['珠光护手', '炼狱导管', '双刀流'], 'blank_candidates': 0,
                         'bundled_models': models}
        self.native_smoke = {'status': 'passed', 'executable_sha256': self.hash, 'applicationVersion': VERSION,
                             'process_exited': True, 'native_report': 'windows-native-overlay.json',
                             'native_screenshot': 'windows-native-overlay.png', 'requested_app_scale': 1.0}
        self.native = {'status': 'passed', 'backend': 'qtwidgets', 'frozen': True, 'qt_platform': 'windows',
                       'applicationVersion': VERSION, 'native_window': True, 'window_closed': True,
                       'capture_passed': True, 'ocr_passed': True, 'click_through_passed': True,
                       'screenshot_method': 'Qt QWidget.grab synthetic mock and overlay composite',
                       'source_hint_renderer_passed': True, 'source_hint_render_scope':'Original synthetic sourceHint renderer only; not live-game or source-combo accuracy', 'source_hint_visible_text':'搭配：原创…', 'three_badge_regions_verified': True, 'badge_gap_hit_test_passed': True, 'badge_above_cards_verified': True, 'badge_revocation_hidden_verified': True, 'source_tier_display_passed': True, 'source_tier_hero_specific': True, 'source_tier_missing_passed': True,
                       'source_tier_screen_order_preserved': True, 'source_tier_no_winrate_display': True,
                       'card_names_accessible':['星火共鸣','晶盾回路','风步微光'],
                       'source_tier_rendered': ['T1','T2','T3'],
                       'source_tier_accessible': [f'选项 {i} · {name} · T{i} · 演示评级' for i,name in enumerate(['星火共鸣','晶盾回路','风步微光'],1)],
                       'badge_source_markers':['演示评级']*3, 'source_details_reachable':True,
                       'recognized': ['星火共鸣', '晶盾回路', '风步微光'],
                       'requested_app_scale': 1.0, 'mock_qwindow_dpr': 1.0, 'overlay_qwindow_dpr': 1.0,
                       'desktop_work_area_physical': dict(x=0, y=0, width=1024, height=720),
                       'mock_window_physical': dict(x=20, y=20, width=960, height=600),
                       'clientRect': dict(x=20, y=20, width=960, height=600),
                       'overlay_window_physical': dict(x=40, y=380, width=920, height=220),
                       'overlay_compact': False, 'physical_mock_geometry_passed': True, 'overlay_layout_passed': True}
        NativePackagingTests.badge_receipt_fixture(self.native)
        self.native.update(dict.fromkeys(gate.NATIVE_AUTOMATION_FIELDS, True))
        self.native.update(overlay_duty_fixture(), executable_sha256=self.hash)
        self.extra_scale_smokes, self.extra_natives = {}, {}
        for scale, prefix in gate.NATIVE_SCALES[1:]:
            self.extra_scale_smokes[prefix] = dict(self.native_smoke, requested_app_scale=scale,
                native_report=prefix + '-overlay.json', native_screenshot=prefix + '-overlay.png')
            self.extra_natives[prefix] = copy.deepcopy(self.native)
            self.extra_natives[prefix].update(requested_app_scale=scale, mock_qwindow_dpr=scale,
                overlay_qwindow_dpr=scale, overlay_compact=scale == 2.)
            NativePackagingTests.badge_receipt_fixture(self.extra_natives[prefix])
        self.selection_smoke = SelectionHarnessTests().good_aggregate(frozen=True)
        self.selection_source = SelectionHarnessTests().good_aggregate(frozen=False)
        for aggregate in (self.selection_smoke, self.selection_source):
            aggregate['applicationVersion'] = VERSION
            if aggregate['frozen']:
                aggregate.update(executable_sha256=self.hash, executable_size=self.exe.stat().st_size)
            for row in aggregate['runs']:
                row['applicationVersion'] = VERSION
                row['detail']['applicationVersion'] = VERSION
                if aggregate['frozen']:
                    row['executable_sha256'] = self.hash
                    row['detail']['executable_sha256'] = self.hash
        self.selection = self.selection_smoke['runs'][0]['detail']
        self.budget = {'status': 'passed', 'upload_scope': 'evidence-only', 'existing_repository_artifact_bytes': 100_000_000,
                       'proposed_upper_estimate_bytes': 1_000_000, 'projected_bytes': 101_000_000,
                       'project_budget_bytes': 500_000_000, 'reserve_bytes': 10_000_000}
        self.license_entries = {name: b'Unit-test full license fixture' for name in gate.QT_NOTICE_FILES}
        self.license_entries.update({'microsoft-runtime/' + name: (ms_runtime.NOTICE_ROOT / name).read_bytes() for name in ms_runtime.NOTICE_HASHES})
        self.license_entries['microsoft-runtime/BUILD-PROVENANCE.json'] = json.dumps(runtime_fixture()).encode()
        self.license_entries['qt-licenses/SOURCE_AND_RELINKING.txt'] = ('SOURCE AND RELINKING: https://download.qt.io/official_releases/ source access fixture. '
            + gate.PSL_SOURCE_URL + ' SHA256 ' + gate.PSL_SOURCE_SHA256).encode('utf-8')
        self.provenance = {'schema_version': 1, 'upstream_version': gate.QT_VERSION, 'files': []}
        for name in ('qt-licenses/pyside-setup/LICENSES/LGPL-3.0-only.txt', 'qt-licenses/pyside-setup/LICENSES/GPL-3.0-only.txt'):
            data = self.license_entries[name]
            self.provenance['files'].append({'path': name.removeprefix('qt-licenses/'), 'size': len(data),
                                              'sha256': hashlib.sha256(data).hexdigest()})
        self.build['dependencies'] = [{'name': name, 'version': gate.QT_VERSION,
                                      'license_files': ['qt-licenses/pyside-setup/LICENSES/LGPL-3.0-only.txt']}
                                     for name in ('PySide6-Essentials', 'shiboken6')]
        self.build['dependencies'].append({'name': 'opencv-python-headless', 'version': custom_package.CUSTOM_VERSION,
                                           'license_files': ['opencv-test-LICENSE.txt']})
        self.license_entries['opencv-test-LICENSE.txt'] = b'Unit-test OpenCV notice fixture'
        self.write_license_archive()
        # Small stand-ins test byte validation without copying 73 MB in each unit case.
        # A separate unpatched test checks the actual production pinned inventory.
        qt_sources = copy.deepcopy(gate.QT_SOURCES)
        for row in qt_sources:
            archive = self.release / row['filename']
            archive.write_bytes(('source test fixture ' + row['filename']).encode())
            row.update(size=archive.stat().st_size, sha256=gate.digest(archive))
        source_patch = patch.object(gate, 'QT_SOURCES', copy.deepcopy(qt_sources))
        source_patch.start()
        self.addCleanup(source_patch.stop)
        source = self.release / f'vga-aram-helper-{VERSION}-source.zip'
        self.source_entries = {name: b'Unit-test source fixture' for name in
            ('launcher.py', 'ocr_privacy.py', 'native_ui.py', 'screen_capture.py', 'native_state.py', 'overlay_geometry.py',
             'native_smoke.py', 'hero_portraits.py', 'portrait_cache_diagnostics.py', 'hero_recognition.py', 'champion_select.py',
             'selection_session.py', 'session_windows.py', 'automatic_windows.py', 'selection_smoke.py', 'tests/windows_automatic_capture.py', 'tests/SessionWindowFixture.cs', 'tests/windows_session_fixture.py', 'requirements-build.txt',
             'scripts/build_windows.py', 'scripts/windows_package.py', 'scripts/check_package_candidate.py',
             'tests/windows_dpi_matrix.py', 'tests/windows_ota_smoke.py', 'packaging/windows-build-constraints.txt',
             'packaging/VGA-Aram-Helper.spec', 'scripts/build_minimal_opencv.py', 'scripts/minimal_opencv_package.py',
             'scripts/probe_opencv_parity.py', 'packaging/opencv-minimal-patch.py', 'packaging/opencv-build-requirements.txt',
             'WINDOWS_MINIMAL_OPENCV_EXPERIMENT.md')}
        for name in (*gate.AUTO_SOURCE_FILES, *gate.wgc_fixture.SOURCE_FILES, *gate.session_capture_fixture.SOURCE_FILES, *gate.visible_capture_fixture.SOURCE_FILES, *gate.HERO_GENUINE_FILES, *gate.SELECTION_GENUINE_FILES, *gate.selection_fixture.SOURCE_FILES, *gate.duty_contract.SOURCE_FILES, 'frame_ocr_cache.py'):
            self.source_entries.setdefault(name, b'Unit-test source fixture')
        for name in gate.DPI_SOURCE_FILES:
            self.source_entries[name] = ('Distinct unit-test source: ' + name + '\r\n').encode()
        with zipfile.ZipFile(source, 'w') as archive:
            archive.comment = SHA.encode('ascii')
            for name, data in self.source_entries.items():
                archive.writestr(name, data)
        for aggregate in (self.selection_smoke, self.selection_source):
            aggregate['source_files'] = {name:hashlib.sha256(self.source_entries[name]).hexdigest()
                                         for name in gate.selection_fixture.SOURCE_FILES}
            for row in aggregate['runs']:
                row['fixture_source_sha256'] = aggregate['source_files']['tests/SessionWindowFixture.cs']
            aggregate['fixture_source_sha256'] = aggregate['runs'][0]['fixture_source_sha256']
        for _, _, smoke, native in self.native_reports():
            native['overlay_duty_cycle']['scene_binding']['fixture_sha256'] = hashlib.sha256(self.source_entries['fixtures/auto-scene.png']).hexdigest()
            smoke.update(executable_size=self.exe.stat().st_size, source_commit=SHA,
                source_files={name:hashlib.sha256(self.source_entries[name]).hexdigest() for name in gate.duty_contract.SOURCE_FILES})
        self.access = {'source_commit': SHA, 'application_source': {'filename': source.name,
                       'size': source.stat().st_size, 'sha256': gate.digest(source)}, 'qt_sources': qt_sources}
        self.build['source_access'] = copy.deepcopy(self.access)
        self.write_json(self.release / 'source-access.json', self.access)
        self.selection_genuine = json.loads((ROOT / 'reports/champion-select-genuine.json').read_text(encoding='utf-8'))
        self.selection_genuine['implementation_sha256'] = {name:hashlib.sha256(self.source_entries[name]).hexdigest() for name in gate.SELECTION_GENUINE_FILES}
        self.genuine = json.loads((ROOT / 'reports/hero-recognition-genuine.json').read_text(encoding='utf-8'))
        self.genuine['implementation_sha256'] = {name:hashlib.sha256(self.source_entries[name]).hexdigest() for name in gate.HERO_GENUINE_FILES}
        self.dpi_report = source_matrix_fixture()
        self.dpi_report['source_metadata'] = [dict(path='D:\\a\\vga-aram-helper\\vga-aram-helper\\' + name,
            sha256=hashlib.sha256(self.source_entries[name]).hexdigest()) for name in gate.DPI_SOURCE_FILES]
        self.automatic_capture = dict(schema_version=1,status='passed',platform='win32',backend='qtwidgets',frozen=False,checks_use_real_windows=True,application_version=VERSION,source_commit=SHA,
            trust_injection=dict(source_only=True,exact_paths_and_sha256_only=True,real_process_metadata_unchanged=True,calls=2),
            source_sha256={name:hashlib.sha256(self.source_entries[name]).hexdigest() for name in gate.AUTO_SOURCE_FILES},**dict.fromkeys(gate.AUTO_CAPTURE_FIELDS,True))
        from test_wgc_build import manifest as wgc_manifest, passing_report as wgc_report
        helper = wgc_manifest()
        helper.update(source_commit=SHA, source_sha256=hashlib.sha256(self.source_entries['native/wgc_capture.cpp']).hexdigest(),
                      build_recipe_sha256=hashlib.sha256(self.source_entries['scripts/build_wgc_capture.py']).hexdigest())
        archive_patch=patch.object(gate,'verify_frozen_wgc_archive',return_value=helper)
        archive_patch.start();self.addCleanup(archive_patch.stop)
        self.build['wgc_helper_build'] = helper
        self.build['archive_inventory']['wgc_helper'] = helper
        self.wgc_reports = {}
        for frozen, kind in ((False,'source'), (True,'frozen')):
            report = dict(schema_version=1, status='passed', frozen=frozen, source_commit=SHA,
                applicationVersion=VERSION, scales=[1,1.5,2], helper_build=helper,
                source_files={name:hashlib.sha256(self.source_entries[name]).hexdigest() for name in gate.wgc_fixture.SOURCE_FILES}, runs=[])
            if frozen:report.update(executable_sha256=self.hash, executable_size=self.exe.stat().st_size)
            for scale in (1,1.5,2):
                detail=wgc_report(scale=scale,frozen=frozen)
                detail['applicationVersion'] = VERSION
                detail['helper']={'manifest':helper,'sha256':helper['sha256'],'size':helper['size']}
                report['runs'].append(dict(app_scale=scale, report=f'windows-wgc-{kind}-scale{round(scale*100)}.json', detail=detail))
            self.wgc_reports[kind]=report
        from test_wgc_session_build import manifest as session_manifest, passing_report as session_report
        session_helper = session_manifest()
        session_helper.update(source_commit=SHA, source_files={name:{'sha256':hashlib.sha256(self.source_entries[name]).hexdigest(),
            'size':len(self.source_entries[name])} for name in gate.session_capture_fixture.SOURCE_FILES})
        session_helper['source_sha256'] = session_helper['source_files']['native/wgc_session_capture.cpp']['sha256']
        session_helper['build_recipe_sha256'] = session_helper['source_files']['scripts/build_wgc_session_capture.py']['sha256']
        self.build['wgc_session_helper_build'] = session_helper
        self.build['archive_inventory'].update(wgc_session_helper=session_helper, launch_script='launcher')
        archive_patch=patch.object(gate,'verify_frozen_session_archive',return_value=session_helper)
        archive_patch.start();self.addCleanup(archive_patch.stop)
        self.session_capture_reports = {}
        for frozen, kind in ((False,'source'), (True,'frozen')):
            report = dict(schema_version=1, status='passed', frozen=frozen, source_commit=SHA,
                applicationVersion=VERSION, scales=[1,1.5,2], helper_build=session_helper,
                **gate.session_capture_fixture.diagnostic_contract(True),
                source_files={name:row['sha256'] for name,row in session_helper['source_files'].items()}, runs=[])
            if frozen:report.update(executable_sha256=self.hash, executable_size=self.exe.stat().st_size,
                                    archive_inventory=copy.deepcopy(self.build['archive_inventory']))
            for scale in (1,1.5,2):
                detail=session_report(scale=scale,frozen=frozen,application=True)
                detail['applicationVersion'] = VERSION
                detail['helper']={'manifest':session_helper,'sha256':session_helper['sha256'],'size':session_helper['size']}
                report['runs'].append(dict(app_scale=scale, report=f'windows-wgc-session-application-{kind}-scale{round(scale*100)}.json', detail=detail))
            self.session_capture_reports[kind]=report
        self.visible_capture_reports, visible_modules = visible_reports(self.source_entries, session_helper,
            self.build['archive_inventory'], self.hash, self.exe.stat().st_size)
        archive_patch = patch.object(gate, 'verify_frozen_visible_modules', return_value=visible_modules)
        archive_patch.start(); self.addCleanup(archive_patch.stop)
        self.write_reports()
        for number, name in enumerate(name for name in gate.EVIDENCE_NAMES if name.endswith('.png')):
            (self.evidence / name).write_bytes(self.make_png(pixels=(b'\x00' + bytes([number, 34, 51]) * 2) * 2))
        for name in (name for name in gate.EVIDENCE_NAMES if name.endswith('.log') or name == 'windows-build-environment.txt'):
            (self.evidence / name).write_text('fixture\n', encoding='utf-8')
        self.write_reports()

    @staticmethod
    def make_png(pixels=None, width=2, height=2):
        def chunk(kind, data):
            return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)
        header = struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)
        if pixels is None:
            pixels = (b'\x00' + b'\x11\x22\x33' * width) * height
        return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', header) + chunk(b'IDAT', zlib.compress(pixels)) + chunk(b'IEND', b'')

    def write_license_archive(self):
        self.license_entries['qt-licenses/PROVENANCE.json'] = json.dumps(self.provenance).encode()
        self.license_entries['dependency-inventory.json'] = json.dumps(self.build['dependencies']).encode()
        with zipfile.ZipFile(self.release / 'third-party-licenses.zip', 'w') as archive:
            for name, data in self.license_entries.items():
                archive.writestr(name, data)

    def write_json(self, path, value):
        path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')

    def write_reports(self):
        write_visible_reports(self.evidence, self.visible_capture_reports)
        for kind, report in self.wgc_reports.items():
            self.write_json(self.evidence / f'windows-wgc-{kind}.json', report)
        for kind, report in self.session_capture_reports.items():
            self.write_json(self.evidence / f'windows-wgc-session-application-{kind}.json', report)
        self.write_json(self.evidence / 'windows-automatic-capture.json', self.automatic_capture)
        self.write_json(self.evidence / 'windows-package-size.json', self.package_size)
        self.write_json(self.evidence / 'windows-ota-smoke.json', self.ota)
        self.selection_smoke['runs'][0]['detail'] = self.selection
        for aggregate, filename in ((self.selection_smoke, 'windows-selection-smoke.json'),
                                    (self.selection_source, 'windows-selection-source.json')):
            for row in aggregate['runs']:
                path = self.evidence / row['native_report']
                self.write_json(path, row['detail'])
                row['native_report_sha256'] = gate.digest(path)
            aggregate['native_report_sha256'] = aggregate['runs'][0]['native_report_sha256']
            self.write_json(self.evidence / filename, aggregate)
        self.write_json(self.evidence / 'hero-recognition-genuine.json', self.genuine)
        self.write_json(self.evidence / 'champion-select-genuine.json', self.selection_genuine)
        self.write_json(self.evidence / 'windows-build.json', self.build)
        self.write_json(self.evidence / 'windows-exe-smoke.json', self.smoke)
        self.write_json(self.evidence / 'windows-exe-self-test.json', self.selftest)
        self.write_json(self.evidence / 'windows-native-smoke.json', self.native_smoke)
        self.write_json(self.evidence / 'windows-native-overlay.json', self.native)
        for _, prefix in gate.NATIVE_SCALES[1:]:
            self.write_json(self.evidence / (prefix + '-smoke.json'), self.extra_scale_smokes[prefix])
            self.write_json(self.evidence / (prefix + '-overlay.json'), self.extra_natives[prefix])
        for _, prefix, smoke, _ in self.native_reports():
            smoke['native_report_sha256'] = gate.digest(self.evidence / (prefix+'-overlay.json'))
            screenshot = self.evidence / (prefix+'-overlay.png')
            if screenshot.exists():
                smoke['native_screenshot_sha256'] = gate.digest(screenshot)
            self.write_json(self.evidence / (prefix+'-smoke.json'), smoke)
        self.write_json(self.evidence / 'windows-dpi-candidate-matrix.json', self.dpi_report)
        self.write_json(self.evidence / 'windows-artifact-budget.json', self.budget)

    def verify(self, **kwargs):
        args = dict(release_dir=self.release, evidence_dir=self.evidence, repository=gate.REPOSITORY,
                    source_sha=SHA, output_dir=self.output, run_id=RUN_ID, run_attempt=RUN_ATTEMPT)
        args.update(kwargs)
        return gate.verify(**args)

    def native_reports(self):
        return [(1.0, 'windows-native', self.native_smoke, self.native)] + [
            (scale, prefix, self.extra_scale_smokes[prefix], self.extra_natives[prefix])
            for scale, prefix in gate.NATIVE_SCALES[1:]]

    def test_wgc_requires_source_and_frozen_acceptance(self):
        for kind in ('source','frozen'):
            self.write_reports();(self.evidence/f'windows-wgc-{kind}.json').unlink()
            with self.subTest(kind=kind),self.assertRaises(gate.VerificationError):self.verify()

    def test_wgc_rejects_fallback_missing_negative_and_wrong_exe(self):
        original=copy.deepcopy(self.wgc_reports)
        edits=[lambda r:r['frozen'].update(executable_sha256='0'*64),
               lambda r:r['source']['runs'][0]['detail'].update(last_backend='hwnd-gdi'),
               lambda r:r['frozen']['runs'][1]['detail'].update(timeout_watchdog_passed=False),
               lambda r:r['source']['runs'][2]['detail'].update(frozen=True),
               lambda r:r['source'].update(scales=[1,2])]
        for edit in edits:
            self.wgc_reports=copy.deepcopy(original);edit(self.wgc_reports);self.write_reports()
            with self.assertRaises(gate.VerificationError):self.verify()

    def test_wgc_rejects_wrong_source_or_helper_binding(self):
        original=copy.deepcopy(self.wgc_reports)
        for kind in ('source','frozen'):
            for field in ('native/wgc_capture.cpp','wgc_capture.py','scripts/build_wgc_capture.py'):
                self.wgc_reports=copy.deepcopy(original)
                self.wgc_reports[kind]['source_files'][field]='0'*64;self.write_reports()
                with self.subTest(kind=kind,field=field),self.assertRaises(gate.VerificationError):self.verify()
        self.wgc_reports=copy.deepcopy(original)
        self.wgc_reports['frozen']['runs'][0]['detail']['helper']['sha256']='0'*64;self.write_reports()
        with self.assertRaises(gate.VerificationError):self.verify()

    def test_automatic_source_capture_evidence_required(self):
        (self.evidence/'windows-automatic-capture.json').unlink()
        with self.assertRaises(gate.VerificationError):self.verify()
    def test_automatic_capture_each_case_must_pass(self):
        for field in gate.AUTO_CAPTURE_FIELDS:
            report=copy.deepcopy(self.automatic_capture);report[field]=False
            self.write_json(self.evidence/'windows-automatic-capture.json',report)
            with self.subTest(field=field),self.assertRaisesRegex(gate.VerificationError,'Automatic lifecycle'):self.verify()
    def test_automatic_capture_binds_exact_source_bytes(self):
        self.automatic_capture['source_sha256']['automatic_windows.py']='0'*64;self.write_reports()
        with self.assertRaisesRegex(gate.VerificationError,'different source bytes'):self.verify()
    def test_automatic_capture_cannot_claim_frozen_or_live_game_trust(self):
        self.automatic_capture['frozen']=True;self.write_reports()
        with self.assertRaisesRegex(gate.VerificationError,'identity/scope'):self.verify()
    def test_automatic_capture_requires_trust_injection_disclosure(self):
        self.automatic_capture['trust_injection']['source_only']=False;self.write_reports()
        with self.assertRaisesRegex(gate.VerificationError,'trust injection'):self.verify()

    def test_valid_bundle_and_exact_evidence_zip(self):
        result = self.verify()
        self.assertEqual(result['tag'], f'v{VERSION}')
        self.assertEqual(result['genuine_report_versions'], {
            'hero-recognition-genuine.json': VERSION,
            'champion-select-genuine.json': VERSION})
        self.assertEqual(result['exe_sha256'], self.hash)
        self.assertEqual(len(result['assets']), 15)
        self.assertEqual([row['requested_app_scale'] for row in result['native_scale_summary']], [1., 1.5, 2.])
        self.assertTrue(all(row['overlay_layout_passed'] for row in result['native_scale_summary']))
        self.assertEqual([row['frozen'] for row in result['wgc_visible_overlay_summary']], [False, True])
        with zipfile.ZipFile(self.output / f'windows-test-evidence-{VERSION}.zip') as archive:
            self.assertEqual(set(archive.namelist()), set(gate.EVIDENCE_NAMES) | set(custom_package.EVIDENCE_NAMES) | set(self.postbuild_names))
        self.assertEqual(json.loads((self.output / 'verified-release.json').read_text()), result)

    def test_selection_source_and_frozen_every_scale_and_native_bytes_are_required(self):
        for frozen in (False, True):
            for scale in gate.selection_fixture.SCALES:
                self.write_reports()
                path=self.evidence/gate.selection_fixture.native_report_name(frozen,scale)
                path.unlink()
                with self.subTest(frozen=frozen,scale=scale),self.assertRaises(gate.VerificationError):self.verify()
                self.write_reports();path.write_text(path.read_text()+' ',encoding='utf-8')
                with self.subTest(frozen=frozen,scale=scale,tamper='bytes'),self.assertRaises(gate.VerificationError):self.verify()
        for filename in ('windows-selection-source.json','windows-selection-smoke.json'):
            self.write_reports();(self.evidence/filename).unlink()
            with self.subTest(file=filename),self.assertRaises(gate.VerificationError):self.verify()

    def test_selection_source_inventories_are_exact_and_bound_to_archive(self):
        for aggregate in (self.selection_source,self.selection_smoke):
            original=copy.deepcopy(aggregate['source_files'])
            for name in gate.selection_fixture.SOURCE_FILES:
                aggregate['source_files']=dict(original,**{name:'0'*64});self.write_reports()
                with self.subTest(frozen=aggregate['frozen'],source=name),self.assertRaises(gate.VerificationError):self.verify()
            for bad in ({},dict(original,unexpected='f'*64),dict(original,**{'hero_strength.py':True})):
                aggregate['source_files']=bad;self.write_reports()
                with self.assertRaises(gate.VerificationError):self.verify()
            aggregate['source_files']=original

    def test_selection_raw_native_types_cannot_differ_from_validated_aggregate(self):
        for frozen in (False, True):
            for scale in gate.selection_fixture.SCALES:
                for field, forged in (('visible', 1), ('augment_card_count', 0.0), ('elapsed_seconds', 1.0)):
                    self.write_reports()
                    filename = 'windows-selection-smoke.json' if frozen else 'windows-selection-source.json'
                    aggregate_path = self.evidence / filename
                    aggregate = json.loads(aggregate_path.read_text(encoding='utf-8'))
                    row = next(item for item in aggregate['runs'] if item['app_scale'] == scale)
                    native_path = self.evidence / row['native_report']
                    native = json.loads(native_path.read_text(encoding='utf-8'))
                    if field == 'elapsed_seconds':
                        row['detail']['diagnostic_state'] = {'elapsed_seconds': 1}
                        native['diagnostic_state'] = {'elapsed_seconds': forged}
                    else:
                        native['client_hero_reference'][field] = forged
                    # Ordinary Python equality conceals these JSON type changes.
                    self.assertEqual(native, row['detail'])
                    self.write_json(native_path, native)
                    row['native_report_sha256'] = gate.digest(native_path)
                    if scale == 1:
                        aggregate['native_report_sha256'] = row['native_report_sha256']
                    self.write_json(aggregate_path, aggregate)
                    with self.subTest(frozen=frozen, scale=scale, field=field), self.assertRaises(gate.VerificationError):
                        self.verify()

    def test_new_selection_observations_cannot_be_replaced_by_passing_flags(self):
        for aggregate in (self.selection_source,self.selection_smoke):
            for row in aggregate['runs']:
                original=copy.deepcopy(row['detail'])
                mutations=[lambda d:d['client_hero_reference'].update(visible=False),
                    lambda d:d['client_hero_reference'].update(confirmed=True),
                    lambda d:d['client_hero_reference'].update(augment_card_count=3),
                    lambda d:d['client_hero_reference']['reference'].update(sourceTier='T1'),
                    lambda d:d['client_hero_reference']['overlay_rect'].update(height=400),
                    lambda d:d['client_hero_safety'].update(unknown_handler_hidden=1)]
                for mutate in mutations:
                    mutate(row['detail']);self.write_reports()
                    with self.subTest(frozen=aggregate['frozen'],scale=row['app_scale']),self.assertRaises(gate.VerificationError):self.verify()
                    row['detail'].clear();row['detail'].update(copy.deepcopy(original))

    def test_native_report_bytes_exe_and_source_binding_cannot_be_substituted(self):
        for scale,prefix,smoke,native in self.native_reports():
            for field,bad in [('executable_size',True),('executable_size',1),('source_commit','f'*40)]:
                old=smoke[field];smoke[field]=bad;self.write_reports()
                with self.subTest(scale=scale,field=field),self.assertRaises(gate.VerificationError):self.verify()
                smoke[field]=old
            original=copy.deepcopy(smoke['source_files'])
            for name in gate.duty_contract.SOURCE_FILES:
                smoke['source_files']=dict(original,**{name:'0'*64});self.write_reports()
                with self.subTest(scale=scale,source=name),self.assertRaises(gate.VerificationError):self.verify()
            smoke['source_files']=original
            for suffix in ('overlay.json','overlay.png'):
                self.write_reports();path=self.evidence/(prefix+'-'+suffix);old=path.read_bytes();path.write_bytes(old+b' ')
                with self.subTest(scale=scale,tamper=suffix),self.assertRaises(gate.VerificationError):self.verify()
                path.write_bytes(old)
            original_hash=native['executable_sha256'];native['executable_sha256']='0'*64;self.write_reports()
            with self.assertRaises(gate.VerificationError):self.verify()
            native['executable_sha256']=original_hash

    def test_native_duty_scene_requires_the_source_archive_fixture_bytes(self):
        for scale, _, _, native in self.native_reports():
            original = native['overlay_duty_cycle']['scene_binding']['fixture_sha256']
            native['overlay_duty_cycle']['scene_binding']['fixture_sha256'] = '0'*64
            self.write_reports()
            with self.subTest(scale=scale), self.assertRaisesRegex(gate.VerificationError, 'externally verified source bytes'):
                self.verify()
            native['overlay_duty_cycle']['scene_binding']['fixture_sha256'] = original

    def test_native_duty_evidence_cannot_be_replaced_by_success_flag(self):
        for scale,_,_,native in self.native_reports():
            original=copy.deepcopy(native['overlay_duty_cycle'])
            for row in native['overlay_duty_cycle']['cases']:
                row['capture_visible_samples']=1;self.write_reports()
                with self.subTest(scale=scale,case=row['name']),self.assertRaises(gate.VerificationError):self.verify()
                row['capture_visible_samples']=0
            for bad in (None,{},dict(original,cases=[])):
                native['overlay_duty_cycle']=bad;self.write_reports()
                with self.subTest(scale=scale),self.assertRaises(gate.VerificationError):self.verify()
            native['overlay_duty_cycle']=original

    def test_package_size_report_is_required_and_remeasured(self):
        for key, value in [('status', 'failed'), ('source_commit', 'c' * 40),
                           ('saved_bytes', 1), ('pruning', {'retained_pe_imports_checked': False})]:
            original = copy.deepcopy(self.package_size)
            self.package_size[key] = value; self.write_reports()
            with self.subTest(key=key), self.assertRaises(gate.VerificationError): self.verify()
            self.package_size.clear(); self.package_size.update(original)
        self.write_reports()
        with patch.object(gate, 'read_archive_measurement', side_effect=RuntimeError('embedded model changed')):
            with self.assertRaises(gate.VerificationError): self.verify()

    def test_release_requires_all_frozen_formats_and_exact_candidate_ota(self):
        original = copy.deepcopy(self.smoke['supported_image_formats'])
        self.smoke['supported_image_formats'].pop('WEBP'); self.write_reports()
        with self.assertRaises(gate.VerificationError): self.verify()
        self.smoke['supported_image_formats'] = original
        for key, value in [('status', 'failed'), ('executable_sha256', 'f' * 64),
                ('executable_bytes', 1), ('applicationVersion', '0.4.2'),
                ('release_source_commit', 'c' * 40), ('all_owned_processes_exited', False), ('cases', [])]:
            original = copy.deepcopy(self.ota); self.ota[key] = value; self.write_reports()
            with self.subTest(key=key), self.assertRaises(gate.VerificationError): self.verify()
            self.ota.clear(); self.ota.update(original)

    def test_each_frozen_scale_requires_every_old_and_new_native_flag(self):
        for scale, _, _, native in self.native_reports():
            for field in (*gate.NATIVE_REQUIRED_FIELDS, *gate.NATIVE_AUTOMATION_FIELDS, 'physical_mock_geometry_passed'):
                for bad in (None, False, 1, 'true'):
                    native[field] = bad
                    self.write_reports()
                    with self.subTest(scale=scale, field=field, bad=bad), self.assertRaises(gate.VerificationError):
                        self.verify()
                native.pop(field)
                self.write_reports()
                with self.subTest(scale=scale, missing=field), self.assertRaises(gate.VerificationError):
                    self.verify()
                native[field] = True

    def test_each_frozen_scale_requires_exact_same_exe_and_own_evidence_names(self):
        for scale, _, smoke, native in self.native_reports():
            for field, bad in [('executable_sha256', '0' * 64), ('applicationVersion', '0.4.1'),
                               ('process_exited', False), ('status', 'failed'), ('error', None),
                               ('native_report', 'other-overlay.json'), ('native_screenshot', 'other-overlay.png')]:
                original = copy.deepcopy(smoke)
                smoke[field] = bad
                self.write_reports()
                with self.subTest(scale=scale, field=field), self.assertRaises(gate.VerificationError): self.verify()
                smoke.clear(); smoke.update(original)
            for field, bad in [('frozen', False), ('qt_platform', 'offscreen'), ('backend', 'browser'),
                               ('applicationVersion', '0.4.1'), ('status', 'failed'), ('error', None),
                               ('recognized', ['星火共鸣', '晶盾回路']), ('source_tier_rendered', ['T3', 'T1', 'T2'])]:
                original = copy.deepcopy(native)
                native[field] = bad
                self.write_reports()
                with self.subTest(scale=scale, field=field), self.assertRaises(gate.VerificationError): self.verify()
                native.clear(); native.update(original)

    def test_requested_scales_and_effective_dprs_are_numeric_finite_and_exact(self):
        for scale, _, smoke, native in self.native_reports():
            for report in (smoke, native):
                for bad in (None, True, str(scale), scale + .01, float('nan'), float('inf')):
                    report['requested_app_scale'] = bad
                    self.write_reports()
                    with self.subTest(scale=scale, requested=bad), self.assertRaises(gate.VerificationError): self.verify()
                report['requested_app_scale'] = scale
            for field in ('mock_qwindow_dpr', 'overlay_qwindow_dpr'):
                for bad in (None, True, str(scale), 0, scale + .011, float('nan'), float('inf')):
                    native[field] = bad
                    self.write_reports()
                    with self.subTest(scale=scale, field=field, bad=bad), self.assertRaises(gate.VerificationError): self.verify()
                native[field] = scale
            for bad in (None, 0, 1, 'false'):
                native['overlay_compact'] = bad
                self.write_reports()
                with self.subTest(scale=scale, compact=bad), self.assertRaises(gate.VerificationError): self.verify()
            native['overlay_compact'] = scale == 2.

    def test_effective_dpr_small_measurement_tolerance_is_bounded(self):
        for scale, _, _, native in self.native_reports():
            native['mock_qwindow_dpr'] = scale + .009
            native['overlay_qwindow_dpr'] = scale - .009
            # A changed measured DPR requires its actual corresponding region
            # shape; retaining the old rectangles is stale evidence, not tolerance.
            import math
            from badge_contract import choose_width, HEIGHT, top_gap, align_physical_regions
            dpr=native['overlay_qwindow_dpr'];cards=native['badge_card_bounds_physical']
            logical_width=choose_width([c[0]+c[2]/2 for c in cards],dpr)
            bw,bh=math.ceil(logical_width*dpr),math.ceil(HEIGHT*dpr)
            physical=[(round(c[0]+c[2]/2-bw/2),math.floor(c[1]-top_gap(dpr)-bh),bw,bh) for c in cards]
            bounds,regions=align_physical_regions(physical,dpr,logical_width)
            native['overlay_window_physical']=dict(zip(('x','y','width','height'),bounds))
            native['badge_regions_physical']=[list(r) for r in regions]
        self.write_reports()
        self.verify()

    def test_each_scale_requires_fixed_physical_size_and_strict_nested_containment(self):
        for scale, _, _, native in self.native_reports():
            mutations = [
                ('clientRect', 'width', 640), ('clientRect', 'height', 400),
                ('clientRect', 'x', 19), ('clientRect', 'y', 21),
                ('mock_window_physical', 'x', -1), ('mock_window_physical', 'y', -1),
                ('mock_window_physical', 'width', 2000), ('mock_window_physical', 'height', 2000),
                ('overlay_window_physical', 'x', 20), ('overlay_window_physical', 'y', 20),
                ('overlay_window_physical', 'x', 60), ('overlay_window_physical', 'y', 401),
                ('overlay_window_physical', 'width', 961), ('overlay_window_physical', 'height', 601),
            ]
            for rect, field, bad in mutations:
                old = native[rect][field]
                native[rect][field] = bad
                self.write_reports()
                with self.subTest(scale=scale, rect=rect, field=field), self.assertRaises(gate.VerificationError): self.verify()
                native[rect][field] = old
            for rect in ('desktop_work_area_physical', 'mock_window_physical', 'clientRect', 'overlay_window_physical'):
                original = copy.deepcopy(native[rect])
                for bad in (None, {}, dict(original, x=True), dict(original, x=1.5), dict(original, width=0),
                            dict(original, height=-1), dict(original, width='960'), dict(original, extra=1)):
                    native[rect] = bad
                    self.write_reports()
                    with self.subTest(scale=scale, rect=rect, bad=bad), self.assertRaises(gate.VerificationError): self.verify()
                native[rect] = original

    def test_all_scale_files_and_source_matrix_are_mandatory(self):
        names = [name for name in gate.EVIDENCE_NAMES if name.startswith(('windows-native', 'windows-dpi-'))]
        self.assertEqual(len(names), 13)
        for name in names:
            path = self.evidence / name
            saved = path.read_bytes()
            path.unlink()
            with self.subTest(name=name), self.assertRaises(gate.VerificationError): self.verify()
            path.write_bytes(saved)

    def test_each_scale_png_is_valid_distinct_and_only_default_is_standalone(self):
        original_png = (self.evidence / 'windows-native-overlay.png').read_bytes()
        for _, prefix in gate.NATIVE_SCALES[1:]:
            path = self.evidence / (prefix + '-overlay.png')
            saved = path.read_bytes()
            for bad in (b'not a PNG', original_png):
                path.write_bytes(bad)
                with self.subTest(prefix=prefix, bad=bad[:8]), self.assertRaises(gate.VerificationError): self.verify()
            path.write_bytes(saved)
        result = self.verify()
        self.assertEqual([row['name'] for row in result['assets'] if row['name'].endswith('.png')], ['windows-native-overlay.png'])

    def test_source_matrix_identity_scope_and_full_pure_validation_are_required(self):
        original = copy.deepcopy(self.dpi_report)
        for field, bad in [('schema_version', True), ('status', 'historical_regression_observed'), ('expect', 'historical'),
                           ('os_name', 'posix'), ('gate_errors', ['regression']), ('error', None),
                           ('scope', dict(original['scope'], frozen_executable_tested=True)), ('children', [])]:
            self.dpi_report = dict(original, **{field: bad})
            self.write_reports()
            with self.subTest(field=field), self.assertRaises(gate.VerificationError): self.verify()
        for mutation in ('missing_scale', 'offscreen', 'frozen', 'cleanup', 'layout_clipped', 'hidden_required',
                         'card_missing', 'changed_tier', 'placement_drift', 'translation_drift', 'wrong_dpr',
                         'changed_fixture', 'escaped_overlay', 'malformed_case'):
            self.dpi_report = copy.deepcopy(original)
            child = self.dpi_report['children'][3]
            row = child['cases'][0]
            if mutation == 'missing_scale': self.dpi_report['children'].pop()
            elif mutation == 'offscreen': child['qt_platform'] = 'offscreen'
            elif mutation == 'frozen': child['frozen'] = True
            elif mutation == 'cleanup': child['owned_windows_destroyed'] = False
            elif mutation == 'layout_clipped': row['layout_issues'] = ['clipped']
            elif mutation == 'hidden_required': row.update(visible=False, error='small', error_type='CaptureUnavailable')
            elif mutation == 'card_missing': row['visible_card_count'] = 2
            elif mutation == 'changed_tier': row['visible_tier_text'].reverse()
            elif mutation == 'placement_drift': child['cases'][1]['overlay_window_physical']['x'] += 1
            elif mutation == 'translation_drift': child['cases'][2]['overlay_window_physical']['x'] += 2
            elif mutation == 'wrong_dpr': row['qt_window_dpr'] = 1.
            elif mutation == 'changed_fixture': row['target_client_physical']['width'] = 480
            elif mutation == 'escaped_overlay': row['overlay_window_physical']['x'] = -50
            else: row.pop('target_client_physical')
            self.write_reports()
            with self.subTest(mutation=mutation), self.assertRaises(gate.VerificationError): self.verify()

    def test_source_matrix_requires_exact_four_release_source_hashes(self):
        original = copy.deepcopy(self.dpi_report['source_metadata'])
        for bad in ([], original[:-1], original + [original[0]], [None] * 4,
                    [dict(row, sha256='0' * 64) for row in original],
                    [dict(row, path=row['path'] + '.bak') for row in original]):
            self.dpi_report['source_metadata'] = bad
            self.write_reports()
            with self.subTest(metadata=bad), self.assertRaises(gate.VerificationError): self.verify()
        for field, bad in [('path', '../native_ui.py'), ('path', original[1]['path']),
                           ('sha256', original[1]['sha256']), ('sha256', True)]:
            self.dpi_report['source_metadata'] = copy.deepcopy(original)
            self.dpi_report['source_metadata'][0][field] = bad
            self.write_reports()
            with self.subTest(field=field, bad=bad), self.assertRaises(gate.VerificationError): self.verify()
        self.dpi_report['source_metadata'] = [dict(row, path=row['path'].replace('\\', '/')) for row in original]
        self.write_reports()
        self.verify()

    def test_source_matrix_hashes_cannot_fuzz_lf_crlf_or_run_archived_code(self):
        source = self.release / self.access['application_source']['filename']
        path = self.evidence / 'windows-dpi-candidate-matrix.json'
        for name in gate.DPI_SOURCE_FILES:
            entries = copy.deepcopy(self.source_entries)
            entries[name] = entries[name].replace(b'\r\n', b'\n')
            # This intentionally invalid Python must never be imported/executed.
            entries['tests/windows_dpi_matrix.py'] = b'raise AssertionError("Archive code executed")\n'
            with zipfile.ZipFile(source, 'w') as archive:
                for item, data in entries.items(): archive.writestr(item, data)
            with self.subTest(name=name), self.assertRaises(gate.VerificationError):
                gate.verify_dpi_matrix(path, source)
        with zipfile.ZipFile(source, 'w') as archive:
            for item, data in self.source_entries.items(): archive.writestr(item, data)
        gate.verify_dpi_matrix(path, source)

    def test_overlay_geometry_and_matrix_harness_are_required_source_inputs(self):
        source = self.release / self.access['application_source']['filename']
        for missing in ('overlay_geometry.py', 'screen_capture.py', 'tests/windows_dpi_matrix.py'):
            with zipfile.ZipFile(source, 'w') as archive:
                archive.comment = SHA.encode()
                for name, data in self.source_entries.items():
                    if name != missing: archive.writestr(name, data)
            self.access['application_source'].update(size=source.stat().st_size, sha256=gate.digest(source))
            self.build['source_access'] = copy.deepcopy(self.access)
            self.write_json(self.release / 'source-access.json', self.access)
            self.write_reports()
            with self.subTest(missing=missing), self.assertRaises(gate.VerificationError): self.verify()

    def test_diagnostic_notes_disclose_default_logs_bounds_and_live_game_limits(self):
        self.verify()
        notes = (self.output / 'release-notes.txt').read_text()
        for phrase in ('DIAGNOSTIC PREVIEW', '诊断测试版', 'enables local logs by default',
                       '768 KiB', 'Settings Off switch', 'No automatic upload',
                       'matched catalog hero/augment names', 'raw OCR text',
                       'actual gameplay remain unverified', f'rerun for v{VERSION}',
                       'Raw title pixel variation alone', 'Fresh same-frame semantic checks',
                       'original four-second deadline, never renewed by rechecking',
                       'separate critical-event ledger and routine sampling',
                       'Controlled non-game fixtures', 'Selection-route gate diagnostics',
                       'not proof of a fixed real-client selection path'):
            self.assertIn(phrase, notes)
        self.assertNotIn('default-off, current-launch local debug', notes)
        self.assertNotIn('retain their original v0.4.10 evaluation identity', notes)

    def test_scaling_notes_preserve_the_confirmed_fix_and_unverified_user_error_limits(self):
        self.verify()
        notes = (self.output / 'release-notes.txt').read_text()
        for phrase in ('confirmed Qt logical/Win32 physical coordinate mismatch', 'rigid overlay layout',
                       'historical cache-lock owner is not established', 'SAME frozen EXE',
                       'QT_SCALE_FACTOR 1, 1.5 and 2', 'fixed physical 960x600', 'same-build source-only Windows matrix',
                       'Baseline HTTP/browser tests also ran once on that same EXE',
                       'real OS 125/150/200/250-percent monitor behavior', 'mixed-DPI monitor transitions',
                       'full visible 4K', 'visual font quality', 'real-game validation', 'Vanguard approval',
                       'same-binary fixture test', 'prerelease=true', 'does NOT discover this preview'):
            self.assertIn(phrase, notes)

    def test_selection_handoff_requires_owned_windows_frozen_exe_and_all_flags(self):
        original = copy.deepcopy(self.selection)
        for field in gate.SELECTION_FIELDS:
            for bad in (None, False, 1, 'true'):
                self.selection = dict(original, **{field: bad}); self.write_reports()
                with self.subTest(field=field, bad=bad), self.assertRaises(gate.VerificationError): self.verify()
        self.selection = original
        for key, bad in [('executable_sha256', '0' * 64), ('applicationVersion', '0.4.0'), ('process_exited', False),
                         ('owned_processes_exited', False), ('game_launched_after_selection_request', False), ('native_report', 'other.json')]:
            old = copy.deepcopy(self.selection_smoke)
            self.selection_smoke[key] = bad; self.write_reports()
            with self.subTest(field=key), self.assertRaises(gate.VerificationError): self.verify()
            self.selection_smoke = old

    def test_selection_genuine_report_preserves_limited_scope_and_exact_source(self):
        original = copy.deepcopy(self.selection_genuine)
        for field, bad in [('applicationVersion', '0.4.0'), ('status', 'failed'), ('scope', 'All stock clients supported'),
                           ('implementation_sha256', {'champion_select.py': '0' * 64}), ('summary', {}), ('cases', [])]:
            self.selection_genuine = dict(original, **{field: bad}); self.write_reports()
            with self.subTest(field=field), self.assertRaises(gate.VerificationError): self.verify()
        self.selection_genuine = copy.deepcopy(original)
        self.selection_genuine['cases'][0]['observed'].update(assigned=True, championId='31')
        self.write_reports()
        with self.assertRaises(gate.VerificationError): self.verify()

    def test_genuine_report_is_required_and_bound_to_archive_source(self):
        original = copy.deepcopy(self.genuine)
        for field, bad in [('applicationVersion', '0.3.0'), ('status', 'passed'), ('platform', 'Windows'),
                           ('scope', 'all heroes accurate'), ('implementation_sha256', {}), ('summary', {})]:
            with self.subTest(field=field):
                self.genuine = dict(original, **{field: bad}); self.write_reports()
                with self.assertRaises(gate.VerificationError): self.verify()
        self.genuine = copy.deepcopy(original)
        self.genuine['implementation_sha256']['hero_recognition.py'] = '0' * 64
        self.write_reports()
        with self.assertRaises(gate.VerificationError): self.verify()
        (self.evidence / 'hero-recognition-genuine.json').unlink()
        with self.assertRaises(gate.VerificationError): self.verify()

    def test_genuine_wrong_hero_and_hidden_abstention_rejected(self):
        for change in ('wrong_hero', 'hidden_abstention', 'negative_prediction', 'low_title_confidence'):
            with self.subTest(change=change):
                self.genuine = json.loads((ROOT / 'reports/hero-recognition-genuine.json').read_text(encoding='utf-8'))
                self.genuine['implementation_sha256'] = {name:hashlib.sha256(self.source_entries[name]).hexdigest() for name in gate.HERO_GENUINE_FILES}
                if change == 'wrong_hero':
                    row = next(row for row in self.genuine['cases'] if row['observed']['confident'])
                    row['observed']['championId'] = '999999'
                elif change == 'hidden_abstention':
                    row = next(row for row in self.genuine['cases'] if row['expected_outcome'] == 'recognize_own_hero' and not row['observed']['confident'])
                    row['case_pass'] = True
                elif change == 'negative_prediction':
                    row = next(row for row in self.genuine['cases'] if row['expected_outcome'] == 'abstain')
                    row['observed'].update(confident=True, championId=row['gold_hero_id'])
                else:
                    self.genuine['genuine_selection_frame']['automatic_titles'][0]['ocr_confidence'] = .5
                self.write_reports()
                with self.assertRaises(gate.VerificationError): self.verify()

    def test_accept_reports_subdirectory_layout(self):
        nested = self.evidence / 'reports'
        nested.mkdir()
        for file in list(self.evidence.iterdir()):
            if file.is_file():
                file.rename(nested / file.name)
        self.verify()

    def test_reject_ambiguous_evidence_layout(self):
        nested = self.evidence / 'reports'
        nested.mkdir()
        (nested / 'windows-exe-ui.png').write_bytes((self.evidence / 'windows-exe-ui.png').read_bytes())
        with self.assertRaises(gate.VerificationError): self.verify()

    def test_reject_tampered_exe(self):
        self.exe.write_bytes(b'MZtampered')
        with self.assertRaises(gate.VerificationError): self.verify()

    def test_reject_wrong_repository_and_source(self):
        for kwargs in ({'repository': 'other/repo'}, {'source_sha': 'b' * 40}, {'source_sha': 'main'}):
            with self.subTest(kwargs=kwargs), self.assertRaises(gate.VerificationError): self.verify(**kwargs)

    def test_reject_manifest_mutations(self):
        for field, value in [('url', 'https://example.com/app.exe'), ('size', True), ('sha256', '0' * 64),
                             ('platform', 'linux'), ('schema_version', 2), ('schema_version', True), ('version', '1.2.3;echo bad'),
                             ('version', '01.2.3'), ('version', '65536.2.3'), ('version', '１.2.3')]:
            with self.subTest(field=field, value=value):
                manifest = dict(self.manifest, **{field: value})
                self.write_json(self.release / 'update-manifest.json', manifest)
                with self.assertRaises(gate.VerificationError): self.verify()
        self.write_json(self.release / 'update-manifest.json', self.manifest)

    def test_actual_producer_receipts_satisfy_entire_release_gate(self):
        # Derive receipts from the actual producer, not the verifier's constants:
        # otherwise a stale expectation creates a self-consistent fake fixture.
        producer = ast.parse((ROOT / 'tests/windows_exe_smoke.py').read_text(encoding='utf-8'))
        receipts = [node.args[0].value for node in ast.walk(producer)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name) and node.func.value.id == 'checks'
            and node.func.attr == 'append' and len(node.args) == 1
            and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)]
        self.assertTrue(gate.BASELINE_CHECKS.issubset(receipts),
                        gate.BASELINE_CHECKS.difference(receipts))
        self.smoke['checks'] = receipts
        self.write_reports()
        self.verify()

    def test_obsolete_priority_receipt_cannot_replace_grade_only_contract(self):
        self.smoke['checks'].remove(gate.COMPARE_CHECK)
        self.smoke['checks'].append('Frozen comparison API: same three slots produce different hero-specific priorities')
        self.write_reports()
        with self.assertRaisesRegex(gate.VerificationError, 'browser/comparison/OCR'):
            self.verify()

    def test_reject_missing_browser_comparison_or_actual_ocr(self):
        checks = self.smoke['checks'][:]
        for check in checks:
            self.smoke['checks'] = [item for item in checks if item != check]
            self.write_reports()
            with self.subTest(check=check), self.assertRaises(gate.VerificationError): self.verify()

    def test_reject_smoke_or_frozen_mutations(self):
        mutations = [('smoke', 'status', 'failed'), ('smoke', 'executable_sha256', '0' * 64),
                     ('selftest', 'frozen', False), ('selftest', 'status', 'failed'),
                     ('selftest', 'applicationVersion', '2.0.0'), ('selftest', 'blank_candidates', 1),
                     ('selftest', 'recognized', []), ('build', 'source_commit', 'b' * 40),
                     ('build', 'bundled_models', []), ('selftest', 'bundled_models', [])]
        for obj, key, value in mutations:
            with self.subTest(obj=obj, key=key):
                report = getattr(self, obj)
                old = report[key]
                report[key] = value
                self.write_reports()
                with self.assertRaises(gate.VerificationError): self.verify()
                report[key] = old
        self.write_reports()

    def test_reject_error_field_even_with_passed_status(self):
        for error in ('cleanup failed', '', None):
            self.smoke['error'] = error
            self.write_reports()
            with self.subTest(error=error), self.assertRaises(gate.VerificationError):
                self.verify()

    def test_application_session_requires_source_and_exact_frozen_acceptance(self):
        for kind in ('source', 'frozen'):
            self.write_reports();(self.evidence/f'windows-wgc-session-application-{kind}.json').unlink()
            with self.assertRaises(gate.VerificationError):self.verify()

    def test_application_session_rejects_standalone_missing_guard_and_forged_native_exit(self):
        original=copy.deepcopy(self.session_capture_reports)
        edits=(lambda reports:reports['source'].update(diagnostic_entrypoint='standalone'),
               lambda reports:reports['frozen'].update(executable_sha256='0'*64),
               lambda reports:reports['source']['runs'][0]['detail'].update(idle_overlay_passed=False),
               lambda reports:reports['frozen']['runs'][1]['detail']['shutdown_stress']['rows'][0].__setitem__(13,True),
               lambda reports:reports['source']['runs'][2].update(report='unobserved-scale.json'))
        for edit in edits:
            self.session_capture_reports=copy.deepcopy(original);edit(self.session_capture_reports);self.write_reports()
            with self.assertRaises(gate.VerificationError):self.verify()

    def test_application_session_rereads_exact_source_lengths_and_final_helper(self):
        helper=self.build['wgc_session_helper_build']
        helper['source_files']['wgc_session_capture.py']['size']+=1
        self.session_capture_reports['frozen']['archive_inventory']=copy.deepcopy(self.build['archive_inventory'])
        self.write_reports()
        with self.assertRaisesRegex(gate.VerificationError,'source bytes'):self.verify()
        helper['source_files']['wgc_session_capture.py']['size']-=1
        self.session_capture_reports['frozen']['archive_inventory']=copy.deepcopy(self.build['archive_inventory'])
        self.write_reports()
        with patch.object(gate,'verify_frozen_session_archive',side_effect=gate.VerificationError('Owned helper mismatch')):
            with self.assertRaisesRegex(gate.VerificationError,'Owned helper mismatch'):self.verify()

    def test_reject_missing_document_and_bad_sums(self):
        (self.release / 'LICENSE').unlink()
        with self.assertRaises(gate.VerificationError): self.verify()
        (self.release / 'LICENSE').write_text('fixture')
        (self.release / 'SHA256SUMS.txt').write_text(f'{self.hash}  other.exe')
        with self.assertRaises(gate.VerificationError): self.verify()

    def test_reject_native_symlink(self):
        original = self.exe.read_bytes()
        elsewhere = self.root / 'elsewhere.exe'
        elsewhere.write_bytes(original)
        self.exe.unlink()
        try:
            self.exe.symlink_to(elsewhere)
        except OSError:
            self.skipTest('Host does not permit unprivileged symlinks')
        with self.assertRaises(gate.VerificationError): self.verify()

    def test_reject_duplicate_json_keys_without_symlink_dependency(self):
        (self.release / 'update-manifest.json').write_text('{"version":"1.2.3", "version":"9.9.9"}')
        with self.assertRaises(gate.VerificationError): self.verify()

    def test_reject_symlink_logic_without_host_privilege(self):
        with patch.object(Path, 'is_symlink', return_value=True), self.assertRaises(gate.VerificationError):
            gate.checked_file(self.exe)

    def test_reject_native_smoke_identity_and_error(self):
        for field, value in [('status', 'failed'), ('executable_sha256', '0' * 64), ('applicationVersion', '9.9.9'),
                             ('process_exited', False), ('native_report', 'other.json'), ('native_screenshot', 'other.png'),
                             ('error', None)]:
            with self.subTest(field=field):
                saved = copy.deepcopy(self.native_smoke)
                self.native_smoke[field] = value
                self.write_reports()
                with self.assertRaises(gate.VerificationError): self.verify()
                self.native_smoke = saved

    def test_reject_native_browser_offscreen_nonfrozen_or_incomplete_proof(self):
        mutations = [('status', 'failed'), ('error', None), ('backend', 'webengine'), ('qt_platform', 'offscreen'),
                     ('qt_platform', 'minimal'), ('frozen', False), ('applicationVersion', '9.9.9'), ('screenshot_method', '')]
        mutations += [(field, value) for field in ('native_window', 'window_closed', 'capture_passed', 'ocr_passed', 'click_through_passed',
                                        'source_tier_display_passed', 'source_tier_hero_specific', 'source_tier_missing_passed',
                                        'source_tier_screen_order_preserved', 'source_tier_no_winrate_display')
                      for value in (False, 1, 'true', None)]
        for field, value in mutations:
            with self.subTest(field=field, value=value):
                saved = copy.deepcopy(self.native)
                self.native[field] = value
                self.write_reports()
                with self.assertRaises(gate.VerificationError): self.verify()
                self.native = saved

    def test_native_overlay_must_fit_half_height_even_inside_client(self):
        self.native['overlay_window_physical'].update(y=30,height=301)
        self.write_reports()
        with self.assertRaisesRegex(gate.VerificationError,'half-client-height'):
            self.verify()

    def test_automatic_hero_lifecycle_proof_is_mandatory(self):
        for field in gate.NATIVE_AUTOMATION_FIELDS:
            for bad in (False, None, 1, 'true'):
                self.native[field] = bad
                self.write_reports()
                with self.subTest(field=field, value=bad), self.assertRaises(gate.VerificationError):
                    self.verify()
            self.native.pop(field)
            self.write_reports()
            with self.subTest(field=field, missing=True), self.assertRaises(gate.VerificationError):
                self.verify()
            self.native[field] = True

    def test_reject_png_signature_only_corruption_truncation_and_bad_pixels(self):
        png = self.make_png()
        invalid = [b'\x89PNG\r\n\x1a\n', png[:-1], png + b'extra', png[:20] + b'x' + png[21:],
                   self.make_png(b'too short'), self.make_png(b'\x05' + b'\0' * 6 + b'\0' * 7),
                   self.make_png(width=9000)]
        path = self.evidence / 'windows-native-overlay.png'
        for data in invalid:
            with self.subTest(size=len(data)), self.assertRaises(gate.VerificationError):
                path.write_bytes(data)
                self.verify()

    def test_reject_missing_native_evidence(self):
        for name in ('windows-native-smoke.json', 'windows-native-overlay.json', 'windows-native-overlay.png', 'windows-artifact-budget.json'):
            path = self.evidence / name
            saved = path.read_bytes()
            path.unlink()
            with self.subTest(name=name), self.assertRaises(gate.VerificationError): self.verify()
            path.write_bytes(saved)

    def test_windowed_executable_logs_may_be_empty_but_must_exist(self):
        logs = ('windows-exe-self-test.log', 'windows-exe-server.log', 'windows-native-process.log')
        for name in logs:
            (self.evidence / name).write_bytes(b'')
        self.verify()
        (self.evidence / logs[0]).unlink()
        with self.assertRaises(gate.VerificationError): self.verify()

    def test_reject_failed_malformed_or_underestimated_budget(self):
        for field, value in [('status', 'blocked'), ('error', None), ('upload_scope', 'release-and-evidence'), ('project_budget_bytes', 600_000_000),
                             ('reserve_bytes', 0), ('projected_bytes', 490_000_001),
                             ('existing_repository_artifact_bytes', True), ('proposed_upper_estimate_bytes', 1)]:
            with self.subTest(field=field):
                saved = copy.deepcopy(self.budget)
                self.budget[field] = value
                self.write_reports()
                with self.assertRaises(gate.VerificationError): self.verify()
                self.budget = saved

    def test_reject_missing_or_unexpected_qt_inventory(self):
        original = copy.deepcopy(self.build['archive_inventory'])
        for change in ({'required_runtime_dlls': sorted(gate.RUNTIME_DLLS - {'qwindows.dll'})},
                       {'qt_binaries': []}, {'qt_binaries': ['PySide6/Qt6Core.dll']},
                       {'qt_binaries': original['qt_binaries'] + ['PySide6/Qt6WebEngineCore.dll']},
                       {'qt_binaries': original['qt_binaries'] + ['PySide6/opengl32sw.dll']}):
            with self.subTest(change=change):
                self.build['archive_inventory'] = dict(original, **change)
                self.write_reports()
                with self.assertRaises(gate.VerificationError): self.verify()

    def test_reject_empty_missing_or_wrong_version_qt_license_inventory(self):
        original = copy.deepcopy(self.build['dependencies'])
        for key, value in [('license_files', []), ('license_files', ['missing.txt']), ('version', '6.11.1')]:
            self.build['dependencies'] = copy.deepcopy(original)
            self.build['dependencies'][0][key] = value
            self.write_license_archive()
            self.write_reports()
            with self.subTest(key=key, value=value), self.assertRaises(gate.VerificationError): self.verify()

    def test_reject_missing_qt_source_notice_and_bad_provenance(self):
        name = 'qt-licenses/SOURCE_AND_RELINKING.txt'
        saved = self.license_entries.pop(name)
        self.write_license_archive()
        with self.assertRaises(gate.VerificationError): self.verify()
        self.license_entries[name] = saved
        self.provenance['files'][0]['sha256'] = '0' * 64
        self.write_license_archive()
        with self.assertRaises(gate.VerificationError): self.verify()

    def test_reject_source_access_source_commit_inventory_or_build_mismatch(self):
        original = copy.deepcopy(self.access)
        for field, value in [('source_commit', 'b' * 40), ('qt_sources', []),
                             ('application_source', dict(self.access['application_source'], filename='../other.zip'))]:
            self.access = dict(original, **{field: value})
            self.build['source_access'] = copy.deepcopy(self.access)
            self.write_reports()
            self.write_json(self.release / 'source-access.json', self.access)
            with self.subTest(field=field), self.assertRaises(gate.VerificationError): self.verify()
        self.write_json(self.release / 'source-access.json', original)
        with self.assertRaises(gate.VerificationError): self.verify()

    def test_reject_tampered_qt_source_bytes_or_official_url(self):
        source = self.release / self.access['qt_sources'][0]['filename']
        original = source.read_bytes()
        source.write_bytes(b'tampered')
        with self.assertRaises(gate.VerificationError): self.verify()
        source.write_bytes(original)
        with self.assertRaises(gate.VerificationError):
            self.access['qt_sources'][0]['url'] = 'https://example.com/wrong-source.tar.xz'
            self.build['source_access'] = copy.deepcopy(self.access)
            self.write_reports()
            self.write_json(self.release / 'source-access.json', self.access)
            self.verify()

    def test_reject_application_git_archive_wrong_commit_even_when_hash_matches(self):
        row = self.access['application_source']
        path = self.release / row['filename']
        with zipfile.ZipFile(path, 'a') as archive:
            archive.comment = ('b' * 40).encode()
        row.update(size=path.stat().st_size, sha256=gate.digest(path))
        self.build['source_access'] = copy.deepcopy(self.access)
        self.write_reports()
        self.write_json(self.release / 'source-access.json', self.access)
        with self.assertRaises(gate.VerificationError): self.verify()

    def test_preview_cannot_publish_wrong_source_hash_version_size_or_provenance(self):
        valid = self.verify()
        for key, value in [('source_sha', 'b' * 40), ('exe_sha256', '0' * 64), ('version', '0.5.0'),
                           ('tag', 'v0.5.0'), ('version', '0.4.2'), ('tag', 'v0.4.2'), ('version', '0.4.1'), ('tag', 'v0.4.1'), ('version', '0.3.0'), ('tag', 'v0.3.0'), ('exe_size', 0), ('run_id', RUN_ID + 1), ('run_attempt', 2)]:
            result = dict(valid, **{key: value})
            with self.subTest(key=key), patch.object(gate, 'gh_api') as api, self.assertRaises(gate.VerificationError):
                gate.publish(result, self.output / 'release-notes.txt', current_provenance())
            api.assert_not_called()
        with patch.object(gate, 'gh_api') as api, self.assertRaises(gate.VerificationError):
            gate.publish(valid, self.output / 'release-notes.txt', {})
        api.assert_not_called()

    def test_release_notes_make_microsoft_scope_and_terms_conspicuous(self):
        self.verify()
        notes = (self.output / 'release-notes.txt').read_text()
        self.assertIn('MICROSOFT RUNTIME TERMS: READ BEFORE USE', notes)
        self.assertIn('requires agreement to their Microsoft end-user terms', notes)
        self.assertIn('not the MIT application or LGPL Qt components', notes)
        self.assertIn('runtime end-user terms themselves do not grant redistribution rights', notes)
        self.assertIn(f'https://github.com/{gate.REPOSITORY}/releases/download/v{VERSION}/third-party-licenses.zip', notes)

    def test_microsoft_terms_and_build_provenance_must_be_present_and_exact(self):
        for name in ms_runtime.NOTICE_HASHES:
            key = 'microsoft-runtime/' + name
            data = self.license_entries.pop(key)
            self.write_license_archive()
            with self.subTest(missing=name), self.assertRaises(gate.VerificationError): self.verify()
            self.license_entries[key] = data + b'altered'
            self.write_license_archive()
            with self.subTest(changed=name), self.assertRaises(gate.VerificationError): self.verify()
            self.license_entries[key] = data
        self.license_entries['microsoft-runtime/BUILD-PROVENANCE.json'] = b'{}'
        self.write_license_archive()
        with self.assertRaises(gate.VerificationError): self.verify()

    def test_missing_changed_microsoft_runtime_identity_fails(self):
        for value in ([], None, {'provenance': runtime_fixture(), 'embedded_files': []}):
            self.build['archive_inventory']['microsoft_runtime'] = value
            self.write_reports()
            with self.subTest(value=value), self.assertRaises(gate.VerificationError):
                self.verify()

    def test_actual_full_windows_inventory_only_excludes_unused_tuio(self):
        inventory = json.loads((ROOT / 'tests' / 'qt-runtime-windows-6.11.2.json').read_text())['qt_binaries']
        self.assertEqual(len(inventory), 34)
        excluded = 'pyside6/plugins/generic/qtuiotouchplugin.dll'
        with self.assertRaisesRegex(gate.VerificationError, 'qtuiotouchplugin'):
            gate.verify_qt_runtime(inventory)
        self.assertEqual(gate.verify_qt_runtime([name for name in inventory if name != excluded]),
                         set(inventory) - {excluded})
        for unexpected in ('pyside6/msvcp140d.dll', 'pyside6/vcruntime140d.dll',
                           'pyside6/msvcp140_3.dll', 'pyside6/concrt140.dll',
                           'pyside6/debug_nonredist/msvcp140.dll', 'pyside6/other/msvcp140.dll',
                           'pyside6/plugins/generic/unknown.dll'):
            with self.subTest(unexpected=unexpected), self.assertRaises(gate.VerificationError):
                gate.verify_qt_runtime([name for name in inventory if name != excluded] + [unexpected])

    def test_qt_runtime_rejects_unreviewed_modules_binding_dlls_and_plugin_trees(self):
        runtime = self.build['archive_inventory']['qt_binaries']
        for unexpected in ('PySide6/Qt6Pdf.dll', 'PySide6/pyside6qml.abi3.dll',
                           'PySide6/plugins/imageformats/qpdf.dll', 'PySide6/plugins/tls/qopensslbackend.dll',
                           'PySide6/plugins/platforminputcontexts/qtvirtualkeyboardplugin.dll',
                           'PySide6/plugins/styles/unknown.dll'):
            with self.subTest(unexpected=unexpected), self.assertRaises(gate.VerificationError):
                gate.verify_qt_runtime(runtime + [unexpected])
        self.assertTrue(gate.verify_qt_runtime(runtime + ['PySide6/Qt6Svg.dll', 'PySide6/plugins/imageformats/qsvg.dll',
                                                     'PySide6/plugins/iconengines/qsvgicon.dll',
                                                     'PySide6/plugins/platforms/qdirect2d.dll']))

    def test_qt_network_allows_only_reviewed_windows_backends_and_requires_psl_notices(self):
        runtime = self.build['archive_inventory']['qt_binaries']
        network = ['PySide6/Qt6Network.dll', 'PySide6/QtNetwork.pyd',
                   'PySide6/plugins/tls/qcertonlybackend.dll', 'PySide6/plugins/tls/qschannelbackend.dll',
                   'PySide6/plugins/networkinformation/qnetworklistmanager.dll']
        self.assertTrue(gate.verify_qt_runtime(runtime + network))
        for unexpected in ('PySide6/plugins/tls/qopensslbackend.dll', 'PySide6/plugins/tls/unknownbackend.dll',
                           'PySide6/plugins/networkinformation/unknown.dll'):
            with self.subTest(unexpected=unexpected), self.assertRaises(gate.VerificationError):
                gate.verify_qt_runtime(runtime + network + [unexpected])
        for name in ('qt-licenses/qtbase/src/3rdparty/libpsl/PSL-LICENSE.txt',
                     'qt-licenses/qtbase/src/3rdparty/libpsl/src/LICENSE.chromium'):
            original = self.license_entries.pop(name)
            self.write_license_archive()
            with self.subTest(name=name), self.assertRaises(gate.VerificationError):
                self.verify()
            self.license_entries[name] = original
        source_notice = 'qt-licenses/SOURCE_AND_RELINKING.txt'
        self.license_entries[source_notice] = self.license_entries[source_notice].replace(gate.PSL_SOURCE_URL.encode(), b'https://publicsuffix.org/list/public_suffix_list.dat')
        self.write_license_archive()
        with self.assertRaises(gate.VerificationError):
            self.verify()

    def test_existing_native_png_is_a_standalone_asset_without_regeneration(self):
        original = (self.evidence / 'windows-native-overlay.png').read_bytes()
        verified = self.verify()
        assets = [row for row in verified['assets'] if row['name'] == 'windows-native-overlay.png']
        self.assertEqual(len(assets), 1)
        self.assertEqual(Path(assets[0]['path']).read_bytes(), original)
        self.assertEqual(assets[0]['sha256'], hashlib.sha256(original).hexdigest())
        notes = (self.output / 'release-notes.txt').read_text()
        for phrase in ('PREVIEW', 'literal source tier', 'no invented grade', 'Huya-equivalent',
                       'does NOT discover this preview', 'LGPLv3', '4(d)(0)', '4(d)(1)'):
            self.assertIn(phrase, notes)

    def test_notes_link_exact_same_release_sources_license_and_native_png(self):
        self.verify()
        notes = (self.output / 'release-notes.txt').read_text()
        filenames = ['third-party-licenses.zip', 'source-access.json',
                     f'vga-aram-helper-{VERSION}-source.zip', 'windows-native-overlay.png']
        filenames += [row['filename'] for row in gate.QT_SOURCES]
        for name in filenames:
            self.assertIn(f'https://github.com/{gate.REPOSITORY}/releases/download/v{VERSION}/{name}', notes)
        self.assertIn('Corresponding sources remain available alongside the binary for as long as required', notes)

    def test_source_tier_literal_rendering_and_missing_flags_fail_closed(self):
        for rendering in ([], ['T3', 'T1', 'T2'], [f'选项 {i} · {name} · T{i} · 演示评级' for i,name in enumerate(['星火共鸣','晶盾回路','风步微光'],1)]):
            self.native['source_tier_rendered'] = rendering
            self.write_reports()
            with self.subTest(rendering=rendering), self.assertRaises(gate.VerificationError): self.verify()
        self.native['source_tier_rendered'] = ['T1','T2','T3']
        for field in ('source_tier_display_passed', 'source_tier_hero_specific', 'source_tier_missing_passed',
                      'source_tier_screen_order_preserved', 'source_tier_no_winrate_display'):
            saved = self.native.pop(field)
            self.write_reports()
            with self.subTest(missing=field), self.assertRaises(gate.VerificationError): self.verify()
            self.native[field] = saved

    def test_compact_visible_source_names_and_accessibility_are_all_required(self):
        for field,bad in [('card_names_accessible',[]),('card_names_accessible',['风步微光','晶盾回路','星火共鸣']),('badge_source_markers',None),('badge_source_markers','虎牙公开源 · 非 Riot 评级/批准'),('source_tier_accessible',['T1','T2','T3']),('source_tier_accessible',['虚构源评级（演示）：T3','虚构源评级（演示）：T1','虚构源评级（演示）：T2']),('source_details_reachable',False),('source_details_reachable',1)]:
            saved=self.native[field];self.native[field]=bad;self.write_reports()
            with self.subTest(field=field,bad=bad),self.assertRaises(gate.VerificationError):self.verify()
            self.native[field]=saved

    def test_evidence_only_budget_ignores_release_bytes_but_requires_explicit_scope(self):
        # A source file larger than the evidence allowance does not go to Actions storage.
        (self.release / 'irrelevant-large-source').write_bytes(b'x' * 1_100_000)
        self.budget.update(existing_repository_artifact_bytes=360_000_000, projected_bytes=361_000_000)
        self.write_reports()
        self.verify()
        self.budget['upload_scope'] = 'release-and-evidence'
        self.write_reports()
        with self.assertRaises(gate.VerificationError): self.verify()

    def reference(self):
        return {'ref': f'refs/tags/v{VERSION}', 'object': {'sha': SHA, 'type': 'commit'}}

    def remote_release(self, result, draft=True):
        return {'id': 123, 'tag_name': f'v{VERSION}', 'target_commitish': SHA, 'draft': draft, 'prerelease': True,
                'html_url': f'https://github.com/{gate.REPOSITORY}/releases/tag/v{VERSION}',
                'assets': [{'name': a['name'], 'size': a['size'], 'state': 'uploaded',
                            'digest': 'sha256:' + a['sha256']} for a in result['assets']]}

    def test_custom_release_gates_are_mandatory_and_receive_metadata_profile(self):
        for function in ('verify_custom_evidence', 'verify_custom_notice_archive', 'verify_custom_source_archive'):
            with self.subTest(function=function), patch.object(gate, function, side_effect=RuntimeError('custom proof changed')):
                with self.assertRaisesRegex(gate.VerificationError, 'custom proof changed'):
                    self.verify()
        with patch.object(gate, 'read_archive_measurement', return_value=copy.deepcopy(self.package_size)) as reader:
            self.verify()
            self.assertEqual(reader.call_args.kwargs, {'profile': gate.ADOPTED_PROFILE})

    def test_postbuild_sequence_gate_is_mandatory_and_bound_in_publication(self):
        with patch.object(gate, 'verify_postbuild_adoption', side_effect=gate.VerificationError('postbuild proof changed')):
            with self.assertRaisesRegex(gate.VerificationError, 'postbuild proof changed'):
                self.verify()
        valid = self.verify()
        for key, value in (('status', 'failed'), ('fixed_order', ['B1', 'A1']),
                           ('restoration', 'failed'), ('source_commit', 'c'*40),
                           ('export_sha256', 'c'*64)):
            bad = copy.deepcopy(valid); bad['opencv_postbuild'][key] = value
            with self.subTest(key=key), patch.object(gate, 'gh_api') as api:
                with self.assertRaisesRegex(gate.VerificationError, 'Post-build'):
                    gate.publish(bad, self.output/'release-notes.txt', current_provenance())
                api.assert_not_called()

    def test_publish_requires_adopted_profile_and_rechecks_raw_speed_evidence(self):
        valid = self.verify()
        for key, value in (('package_profile', gate.OFFICIAL_PROFILE), ('opencv_build_profile', 'experimental-minimal-opencv-v1'),
                           ('opencv_distribution_version', custom_package.OFFICIAL_VERSION), ('opencv_adoption', None),
                           ('opencv_postbuild', None)):
            with self.subTest(key=key), patch.object(gate, 'gh_api') as api, self.assertRaises(gate.VerificationError):
                gate.publish({**valid, key: value}, self.output/'release-notes.txt', current_provenance())
            api.assert_not_called()
        bad = copy.deepcopy(valid)
        bad['opencv_adoption']['performance']['ocr_app_demo']['candidate_samples_seconds'] = [0.9]*7
        with patch.object(gate, 'gh_api') as api, self.assertRaisesRegex(gate.VerificationError, 'median'):
            gate.publish(bad, self.output/'release-notes.txt', current_provenance())
        api.assert_not_called()

    def test_publish_reserves_tag_then_draft_verifies_then_publishes(self):
        result = self.verify()
        draft = self.remote_release(result)
        final = self.remote_release(result, draft=False)
        reference = self.reference()
        replies = [None, [], reference, reference, [draft], reference, final, reference]
        with patch.object(gate, 'gh_api', side_effect=replies) as api, patch.object(gate, 'gh_run') as run:
            self.assertEqual(gate.publish(result, self.output / 'release-notes.txt', current_provenance()), final['html_url'])
        self.assertEqual(api.call_args_list[2].kwargs['fields'], {'ref': f'refs/tags/v{VERSION}', 'sha': SHA})
        create, publish = [call.args[0] for call in run.call_args_list]
        self.assertIn('--draft', create)
        self.assertIn('--verify-tag', create)
        self.assertIn('--prerelease', create)
        self.assertEqual(create[create.index('--title') + 1],
                         f'VGA Capture Stability DIAGNOSTIC PREVIEW {VERSION} / 诊断测试版')
        self.assertIn('--latest=false', create)
        self.assertEqual(create[create.index('--target') + 1], SHA)
        self.assertEqual(publish, ['api', '--hostname', 'github.com', '--method', 'PATCH',
                                   '-H', 'Accept: application/vnd.github+json',
                                   f'repos/{gate.REPOSITORY}/releases/123', '--field', 'draft=false',
                                   '--field', 'prerelease=true', '--raw-field', 'make_latest=false'])
        self.assertNotIn(f'v{VERSION}', ' '.join(publish))
        self.assertEqual(api.call_args_list[-2].args[0], f'repos/{gate.REPOSITORY}/releases/123')
        self.assertNotIn('--clobber', create)

    def test_publish_by_recorded_id_still_checks_final_identity_and_digests(self):
        result = self.verify()
        draft = self.remote_release(result)
        for mutation in ('identity', 'digest', 'not-prerelease'):
            final = self.remote_release(result, draft=False)
            if mutation == 'identity':
                final['id'] = 456
            elif mutation == 'not-prerelease':
                final['prerelease'] = False
            else:
                final['assets'][0]['digest'] = 'sha256:' + '0' * 64
            reference = self.reference()
            replies = [None, [], reference, reference, [draft], reference, final, reference]
            with self.subTest(mutation=mutation), patch.object(gate, 'gh_api', side_effect=replies), \
                 patch.object(gate, 'gh_run') as run, self.assertRaises(gate.VerificationError):
                gate.publish(result, self.output / 'release-notes.txt', current_provenance())
            self.assertEqual(run.call_count, 2)
            command = run.call_args.args[0]
            self.assertIn(f'repos/{gate.REPOSITORY}/releases/123', command)
            self.assertIn('PATCH', command)
            self.assertNotIn('edit', command)

    def test_publish_rejects_existing_tag_or_draft_without_write(self):
        result = self.verify()
        for replies in ([self.reference()], [None, [self.remote_release(result)]]):
            with self.subTest(replies=replies), patch.object(gate, 'gh_api', side_effect=replies), \
                 patch.object(gate, 'gh_run') as run, self.assertRaises(gate.VerificationError):
                gate.publish(result, self.output / 'release-notes.txt', current_provenance())
            run.assert_not_called()

    def test_publish_stops_on_tag_creation_race(self):
        result = self.verify()
        with patch.object(gate, 'gh_api', side_effect=[None, [], gate.VerificationError('HTTP 422')]), \
             patch.object(gate, 'gh_run') as run, self.assertRaises(gate.VerificationError):
            gate.publish(result, self.output / 'release-notes.txt', current_provenance())
        run.assert_not_called()

    def test_publish_rechecks_local_assets_before_any_write(self):
        result = self.verify()
        self.exe.write_bytes(b'MZchanged')
        with patch.object(gate, 'gh_api', side_effect=[None, []]) as api, \
             patch.object(gate, 'gh_run') as run, self.assertRaises(gate.VerificationError):
            gate.publish(result, self.output / 'release-notes.txt', current_provenance())
        self.assertEqual(api.call_count, 2)
        run.assert_not_called()

    def test_never_publish_remote_digest_mismatch_or_wrong_tag(self):
        result = self.verify()
        reference = self.reference()
        bad = self.remote_release(result)
        bad['assets'][0]['digest'] = 'sha256:' + '0' * 64
        wrong_ref = copy.deepcopy(reference)
        wrong_ref['object']['sha'] = 'b' * 40
        for replies in ([None, [], reference, reference, [bad]],
                        [None, [], reference, reference, [self.remote_release(result)], wrong_ref]):
            with self.subTest(replies=replies), patch.object(gate, 'gh_api', side_effect=replies), \
                 patch.object(gate, 'gh_run') as run, self.assertRaises(gate.VerificationError):
                gate.publish(result, self.output / 'release-notes.txt', current_provenance())
            self.assertEqual(run.call_count, 1)
            self.assertEqual(run.call_args.args[0][:2], ['release', 'create'])

    def test_find_release_includes_drafts_and_handles_pagination(self):
        first = [{'tag_name': f'v0.0.{number}'} for number in range(100)]
        draft = {'id': 12, 'tag_name': f'v{VERSION}', 'draft': True}
        with patch.object(gate, 'gh_api', side_effect=[first, [draft]]) as api:
            self.assertEqual(gate.find_release(gate.REPOSITORY, f'v{VERSION}'), draft)
        self.assertIn('page=2', api.call_args.args[0])
        with patch.object(gate, 'gh_api', return_value=[draft, draft]), self.assertRaises(gate.VerificationError):
            gate.find_release(gate.REPOSITORY, f'v{VERSION}')

    def test_api_only_explicit_404_is_absent(self):
        for stderr in ('HTTP 403', 'connection timed out', 'not found'):
            fake = subprocess.CompletedProcess([], 1, '', stderr)
            with patch.object(gate.subprocess, 'run', return_value=fake), self.assertRaises(gate.VerificationError):
                gate.gh_api('repos/example', allow_absent=True)
        fake = subprocess.CompletedProcess([], 1, '', 'gh: Not Found (HTTP 404)')
        with patch.object(gate.subprocess, 'run', return_value=fake):
            self.assertIsNone(gate.gh_api('repos/example', allow_absent=True))
        with patch.object(gate.subprocess, 'run', return_value=fake), self.assertRaises(gate.VerificationError):
            gate.gh_api('repos/example')

    def test_api_uses_argument_list_and_does_not_echo_failures(self):
        fake = subprocess.CompletedProcess([], 1, 'untrusted stdout', 'untrusted stderr')
        with patch.object(gate.subprocess, 'run', return_value=fake) as run:
            with self.assertRaises(gate.VerificationError) as error:
                gate.gh_run(['release', 'create', f'v{VERSION}'])
        self.assertNotIn('untrusted', str(error.exception))
        self.assertEqual(run.call_args.args[0], ['gh', 'release', 'create', f'v{VERSION}'])
        self.assertNotIn('shell', run.call_args.kwargs)


class AdoptedTimingTests(unittest.TestCase):
    def test_run40_capture_samples_remain_rejected_despite_fast_supplemental_diagnostics(self):
        # Exact numeric row from the permitted rendered run40 summary. Its
        # loose parity flag does not supersede the stricter publication screen.
        row = {
            'baseline_median_seconds': 0.11452916666663289,
            'candidate_median_seconds': 0.15629203333332953,
            'ratio': 1.3646483064725197,
            'delta_seconds': 0.04176286666669664,
            'regression': False,
            'baseline_samples_seconds': [0.11496369999997569, 0.10876619999999093,
                0.1199700000000045, 0.10953830000001592, 0.11452916666663289,
                0.11440919999999248, 0.1148544000000129],
            'candidate_samples_seconds': [0.1510123333333316, 0.15629203333332953,
                0.1563260000000355, 0.156270799999902, 0.16134846666667121,
                0.16195260000010117, 0.15608356666659043],
        }
        for supplemental in (None, {'status': 'passed', 'samples_seconds': [0.000001] * 7}):
            with self.subTest(supplemental=supplemental is not None):
                report = adoption_timing_fixture()
                report['performance']['capture_synthetic_window'] = copy.deepcopy(row)
                if supplemental is not None:
                    report['capture_diagnostics'] = copy.deepcopy(supplemental)
                    report['performance']['capture_synthetic_window']['supplemental_diagnostics'] = copy.deepcopy(supplemental)
                before = copy.deepcopy(report)
                with self.assertRaisesRegex(gate.VerificationError, 'Material timing regression.*capture_synthetic_window'):
                    gate.verify_adopted_performance(report)
                self.assertEqual(report, before)

    def test_seconds_and_both_thresholds_are_required(self):
        # 20 percent but only 4ms, or 10ms but only 5 percent, must not fail.
        for baseline, candidate in ((0.020, 0.024), (0.020, 0.025), (0.2, 0.23), (0.200, 0.210), (0.2, 0.2), (0.2, 0.19)):
            self.assertEqual(gate.verify_adopted_performance(adoption_timing_fixture(baseline, candidate))['status'], 'passed')
        for baseline, candidate in ((0.2, 0.24), (0.020, 0.026)):
            with self.assertRaisesRegex(gate.VerificationError, 'Material timing regression'):
                gate.verify_adopted_performance(adoption_timing_fixture(baseline, candidate))

    def test_missing_samples_fake_units_and_changed_ratios_fail(self):
        for field, value in (('candidate_samples_seconds', [204]*7), ('ratio', 0.1), ('delta_seconds', 4.0),
                             ('baseline_samples_seconds', [0.2]*6), ('baseline_samples_seconds', [float('nan')]*7)):
            report = adoption_timing_fixture(); report['performance']['ocr_app_demo'][field] = value
            with self.subTest(field=field), self.assertRaises(gate.VerificationError):
                gate.verify_adopted_performance(report)
        report = adoption_timing_fixture(); report['performance'].pop('ocr_app_demo')
        with self.assertRaises(gate.VerificationError): gate.verify_adopted_performance(report)


class WorkflowSafetyTests(unittest.TestCase):
    def test_diagnostic_release_version_and_workflow_are_consistent(self):
        self.assertEqual(VERSION, '0.4.13')
        self.assertEqual(gate.PREVIEW_VERSION, VERSION)
        text = (ROOT / gate.PREVIEW_WORKFLOW).read_text(encoding='utf-8')
        self.assertIn(f'publish v{VERSION}', text)
        self.assertIn(f'group: vga-native-preview-v{VERSION}', text)
        self.assertIn('DIAGNOSTIC prerelease', text)
        self.assertTrue(gate.genuine_report_version_matches(VERSION, VERSION))
        for old in ('0.4.10', '0.4.11', '0.4.12'):
            self.assertFalse(gate.genuine_report_version_matches(old, VERSION))
        # Preserve the narrowly scoped historical exception, not for this release.
        self.assertTrue(gate.genuine_report_version_matches('0.4.10', '0.4.11'))

    def test_windows_git_archive_preserves_every_probe_and_recipe_input(self):
        from scripts.probe_opencv_parity import SOURCE_FILES
        names = (*SOURCE_FILES, 'scripts/build_minimal_opencv.py',
                 'packaging/opencv-minimal-patch.py', 'packaging/opencv-build-requirements.txt')
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            def git(*args):
                return subprocess.run(['git', '-c', 'core.autocrlf=true', *args], cwd=root,
                                      check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            git('init')
            (root/'.gitattributes').write_bytes((ROOT/'.gitattributes').read_bytes())
            for name in names:
                path = root/name; path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes((ROOT/name).read_bytes())
            git('add', '.gitattributes', *names)
            git('-c', 'user.name=Packaging test', '-c', 'user.email=packaging-test@example.invalid',
                'commit', '--no-gpg-sign', '-m', 'Probe source archive fixture')
            for name in names: (root/name).unlink()
            git('checkout-index', '--force', '--all')
            output = root/'source.zip'; git('archive', '--format=zip', '--output', str(output), 'HEAD')
            with zipfile.ZipFile(output) as archive:
                for name in names:
                    checkout = (root/name).read_bytes()
                    with self.subTest(name=name):
                        self.assertEqual(archive.read(name), checkout)
                        self.assertEqual(hashlib.sha256(archive.read(name)).hexdigest(), hashlib.sha256(checkout).hexdigest())
                for name in names[-3:]:
                    self.assertEqual(archive.read(name), (ROOT/name).read_bytes())

    def test_windows_git_archive_preserves_all_four_evaluated_dpi_module_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            def git(*args):
                return subprocess.run(['git', '-c', 'core.autocrlf=true', *args], cwd=root,
                                      check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            git('init')
            (root / '.gitattributes').write_bytes((ROOT / '.gitattributes').read_bytes())
            for name in gate.DPI_SOURCE_FILES:
                (root / name).write_bytes((ROOT / name).read_bytes())
            git('add', '.gitattributes', *gate.DPI_SOURCE_FILES)
            git('-c', 'user.name=Packaging test', '-c', 'user.email=packaging-test@example.invalid',
                'commit', '--no-gpg-sign', '-m', 'DPI source archive fixture')
            for name in gate.DPI_SOURCE_FILES:
                (root / name).unlink()
            git('checkout-index', '--force', '--all')
            source = root / 'source.zip'
            git('archive', '--format=zip', '--output', str(source), 'HEAD')
            report = source_matrix_fixture()
            # Precisely model the Windows harness: hash the actual post-checkout
            # bytes, never Linux canonical bytes or a normalized approximation.
            report['source_metadata'] = gate.dpi_matrix.source_metadata(root / 'native_ui.py', root)
            self.assertEqual(len(report['source_metadata']), len(gate.DPI_SOURCE_FILES))
            with zipfile.ZipFile(source) as archive:
                for row in report['source_metadata']:
                    name = Path(row['path']).name
                    checkout = (root / name).read_bytes()
                    self.assertNotIn(b'\r\n',checkout)
                    self.assertEqual(archive.read(name), checkout)
                    self.assertEqual(hashlib.sha256(archive.read(name)).hexdigest(), row['sha256'])
            path = root / 'windows-dpi-candidate-matrix.json'
            path.write_text(json.dumps(report), encoding='utf-8')
            gate.verify_dpi_matrix(path, source)

    def test_windows_archive_preserves_automatic_fixture_source_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            def git(*args):
                return subprocess.run(['git','-c','core.autocrlf=true',*args],cwd=root,check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            git('init');(root/'.gitattributes').write_bytes((ROOT/'.gitattributes').read_bytes())
            for name in gate.AUTO_SOURCE_FILES:
                path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes((ROOT/name).read_bytes())
            git('add','.gitattributes',*gate.AUTO_SOURCE_FILES)
            git('-c','user.name=Packaging test','-c','user.email=packaging-test@example.invalid','commit','--no-gpg-sign','-m','Automatic capture source fixture')
            for name in gate.AUTO_SOURCE_FILES:(root/name).unlink()
            git('checkout-index','--force','--all');archive=root/'source.zip';git('archive','--format=zip','--output',str(archive),'HEAD')
            with zipfile.ZipFile(archive) as zipped:
                for name in gate.AUTO_SOURCE_FILES:
                    checkout=(root/name).read_bytes();self.assertNotIn(b'\r\n',checkout,name)
                    self.assertEqual(checkout,(ROOT/name).read_bytes(),name)
                    self.assertEqual(zipped.read(name),checkout,name)

    def test_windows_git_archive_preserves_every_feedback_source_inventory_byte(self):
        names=sorted(set(gate.selection_fixture.SOURCE_FILES)|set(gate.duty_contract.SOURCE_FILES))
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            def git(*args):
                return subprocess.run(['git','-c','core.autocrlf=true',*args],cwd=root,check=True,
                    stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            git('init');(root/'.gitattributes').write_bytes((ROOT/'.gitattributes').read_bytes())
            for name in names:
                path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes((ROOT/name).read_bytes())
            git('add','.gitattributes',*names)
            git('-c','user.name=Packaging test','-c','user.email=packaging-test@example.invalid','commit','--no-gpg-sign','-m','Feedback source fixture')
            for name in names:(root/name).unlink()
            git('checkout-index','--force','--all');archive=root/'source.zip';git('archive','--format=zip','--output',str(archive),'HEAD')
            with zipfile.ZipFile(archive) as zipped:
                for name in names:
                    checkout=(root/name).read_bytes()
                    self.assertEqual(checkout,(ROOT/name).read_bytes(),name)
                    self.assertEqual(zipped.read(name),checkout,name)

    def test_windows_git_archive_preserves_evaluated_portrait_module_bytes(self):
        report = json.loads((ROOT / 'reports/hero-recognition-genuine.json').read_text(encoding='utf-8'))
        selection = json.loads((ROOT / 'reports/champion-select-genuine.json').read_text(encoding='utf-8'))
        hashes = dict(report['implementation_sha256'], **selection['implementation_sha256'])
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            def git(*args):
                return subprocess.run(['git', '-c', 'core.autocrlf=true', *args], cwd=root,
                                      check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            git('init')
            (root / '.gitattributes').write_bytes((ROOT / '.gitattributes').read_bytes())
            for name, expected in hashes.items():
                data = (ROOT / name).read_bytes()
                self.assertEqual(hashlib.sha256(data).hexdigest(), expected)
                (root / name).write_bytes(data)
            git('add', '.gitattributes', *hashes)
            git('-c', 'user.name=Packaging test', '-c', 'user.email=packaging-test@example.invalid',
                'commit', '--no-gpg-sign', '-m', 'Source archive fixture')
            for name in hashes:
                (root / name).unlink()
            git('checkout-index', '--force', '--all')
            source = root / 'source.zip'
            git('archive', '--format=zip', '--output', str(source), 'HEAD')
            with zipfile.ZipFile(source) as archive:
                for name, expected in hashes.items():
                    self.assertEqual(hashlib.sha256((root / name).read_bytes()).hexdigest(), expected)
                    self.assertEqual(hashlib.sha256(archive.read(name)).hexdigest(), expected)
            self.assertEqual(gate.verify_genuine_report(ROOT / 'reports/hero-recognition-genuine.json', source, VERSION), report['summary'])
            self.assertEqual(gate.verify_selection_genuine_report(ROOT / 'reports/champion-select-genuine.json', source, VERSION), selection['summary'])

    def test_production_qt_source_inventory_remains_pinned(self):
        self.assertEqual(len(gate.QT_SOURCES), 4)
        self.assertEqual(sum(row['size'] for row in gate.QT_SOURCES), 73_028_200)
        self.assertEqual({row['sha256'] for row in gate.QT_SOURCES}, {
            'cba47efbaad1bedd529725cbc14e21f156c7a19366f07b3edfbb076ffd7afdf8',
            '5b2e00eccaf5a4d8c14134ffa0ea8dfd0a35ae1ffc7f8d87fa4305a1ed23cf22',
            'd594337feca84c26fb67fe87b85e6a5c12fda404b611d905f9d138210c311876',
            'cecd8900f34b6550076309bc94f62f828008b633a4239e0a08c86788f41001f8'})

    def test_diagnostic_dispatch_runs_all_gates_but_cannot_publish(self):
        text=(ROOT / '.github/workflows/build-native-preview.yml').read_text(encoding='utf-8')
        job=text.split('  native-preview:',1)[1].split('    runs-on:',1)[0]
        self.assertNotIn('inputs.publish_preview',job)
        self.assertIn("github.event_name == 'workflow_dispatch'",job)
        self.assertIn('github.event.repository.private == false',job)
        self.assertIn("github.ref == 'refs/heads/main'",job)
        publication=text.split('- name: Create verified draft',1)[1]
        self.assertIn('if: ${{ success() && inputs.publish_preview }}',publication)
        self.assertEqual(text.count('--publish'),1)
        self.assertEqual(text.count('GH_TOKEN:'),1)
        self.assertIn('GH_TOKEN:',publication)
        self.assertIn('run: python tests/windows_selection_smoke.py --report-dir reports',text)

    def test_workflow_direct_build_has_only_bounded_evidence_upload_and_final_token(self):
        text = (ROOT / '.github/workflows/build-native-preview.yml').read_text(encoding='utf-8')
        self.assertIn('workflow_dispatch:', text)
        self.assertIn('publish_preview:', text)
        self.assertIn('default: false', text)
        self.assertIn('permissions: {}', text)
        self.assertEqual(text.count('contents: write'), 1)
        self.assertEqual(text.count('actions: read'), 1)
        self.assertIn("github.ref == 'refs/heads/main'", text)
        self.assertIn("github.event_name == 'workflow_dispatch'", text)
        self.assertIn('persist-credentials: false', text)
        self.assertIn('ref: ${{ github.sha }}', text)
        self.assertIn('runs-on: windows-2022', text)
        self.assertIn('timeout-minutes: 60', text)
        self.assertNotIn('actions/download-artifact', text)
        self.assertEqual(text.count('actions/upload-artifact@v4'), 1)
        self.assertIn('path: |\n            reports/windows-*\n            reports/hero-recognition-genuine.json\n            reports/champion-select-genuine.json', text)
        self.assertNotIn('path: dist/', text)
        self.assertIn('python scripts/check_artifact_budget.py --evidence-only', text)
        self.assertIn("always() && steps.evidence_budget.outcome == 'success'", text)
        self.assertEqual(text.count('retention-days: 1'), 1)
        self.assertIn('python scripts/build_windows.py', text)
        self.assertIn('tests/windows_exe_smoke.py --exe dist/VGA-Aram-Helper.exe --browser', text)
        self.assertIn('python tests/windows_native_smoke.py --exe dist/VGA-Aram-Helper.exe', text)
        self.assertIn('python tests/windows_selection_smoke.py --exe dist/VGA-Aram-Helper.exe', text)
        self.assertIn('python tests/windows_ota_smoke.py --exe dist/VGA-Aram-Helper.exe', text)
        self.assertIn('--expected-sha256 $manifest.sha256 --expected-size $manifest.size', text)
        self.assertIn('python scripts/check_package_candidate.py', text)
        self.assertLess(text.index('Verify fresh native preview'), text.index('Upload only small test evidence'))
        self.assertEqual(text.count('GH_TOKEN:'), 1)
        self.assertGreater(text.index('GH_TOKEN:'), text.index('Create verified draft'))
        self.assertIn('--source-sha "$env:GITHUB_SHA"', text)
        self.assertIn('--run-id "$env:GITHUB_RUN_ID"', text)
        self.assertIn('--run-attempt "$env:GITHUB_RUN_ATTEMPT"', text)
        self.assertNotIn('38226534574', text)
        self.assertNotIn('11736459413', text)
        self.assertNotIn('publish-preview.yml', [path.name for path in (ROOT / '.github/workflows').iterdir()])


class RunProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.run = {'id': RUN_ID, 'run_attempt': RUN_ATTEMPT, 'status': 'in_progress', 'conclusion': None,
                    'event': 'workflow_dispatch', 'head_branch': 'main', 'head_sha': SHA,
                    'path': gate.PREVIEW_WORKFLOW,
                    'repository': {'id': 123, 'full_name': gate.REPOSITORY, 'private': False},
                    'head_repository': {'id': 123, 'full_name': gate.REPOSITORY}}

    def test_current_active_main_manual_run_and_attempt_pass(self):
        with patch.object(gate, 'gh_api', return_value=self.run) as api:
            result = gate.verify_run_provenance(gate.REPOSITORY, SHA, RUN_ID, RUN_ATTEMPT)
        self.assertEqual(result, current_provenance())
        api.assert_called_once_with(f'repos/{gate.REPOSITORY}/actions/runs/{RUN_ID}')

    def test_wrong_completed_failed_stale_run_or_attempt_rejected(self):
        for key, value in [('id', 123), ('run_attempt', 2), ('status', 'completed'), ('conclusion', 'success'),
                           ('conclusion', 'failure'), ('event', 'pull_request'), ('head_branch', 'other'),
                           ('head_sha', 'b' * 40), ('path', '.github/workflows/windows-build.yml')]:
            run = dict(self.run, **{key: value})
            with self.subTest(key=key, value=value), patch.object(gate, 'gh_api', return_value=run), \
                 self.assertRaises(gate.VerificationError):
                gate.verify_run_provenance(gate.REPOSITORY, SHA, RUN_ID, RUN_ATTEMPT)

    def test_private_wrong_repo_and_fork_rejected(self):
        for container, key, value in [('repository', 'private', True), ('repository', 'full_name', 'other/repo'),
                                      ('head_repository', 'full_name', 'fork/repo'), ('head_repository', 'id', 999)]:
            run = copy.deepcopy(self.run)
            run[container][key] = value
            with self.subTest(container=container, key=key), patch.object(gate, 'gh_api', return_value=run), \
                 self.assertRaises(gate.VerificationError):
                gate.verify_run_provenance(gate.REPOSITORY, SHA, RUN_ID, RUN_ATTEMPT)

    def test_runner_context_binds_current_sha_run_and_attempt_without_reading_token(self):
        env = {'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': gate.REPOSITORY, 'GITHUB_SHA': SHA,
               'GITHUB_RUN_ID': str(RUN_ID), 'GITHUB_RUN_ATTEMPT': str(RUN_ATTEMPT), 'GITHUB_REF': 'refs/heads/main',
               'GITHUB_EVENT_NAME': 'workflow_dispatch',
               'GITHUB_WORKFLOW_REF': f'{gate.REPOSITORY}/{gate.PREVIEW_WORKFLOW}@refs/heads/main'}
        with patch.dict(gate.os.environ, env, clear=True):
            gate.check_runner_context(gate.REPOSITORY, SHA, RUN_ID, RUN_ATTEMPT)
        for key in env:
            wrong = dict(env, **{key: 'wrong'})
            with self.subTest(key=key), patch.dict(gate.os.environ, wrong, clear=True), self.assertRaises(gate.VerificationError):
                gate.check_runner_context(gate.REPOSITORY, SHA, RUN_ID, RUN_ATTEMPT)


if __name__ == '__main__':
    unittest.main()

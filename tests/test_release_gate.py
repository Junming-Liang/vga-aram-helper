"""Offline release gate tests. No GitHub request or external mutation is made."""
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

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('verify_release', ROOT / 'scripts' / 'verify_release.py')
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)
SHA = 'a' * 40
RUN_ID = 987654321
RUN_ATTEMPT = 1
VERSION = '0.3.0'


def current_provenance():
    return {'repository': gate.REPOSITORY, 'source_sha': SHA, 'run_id': RUN_ID, 'run_attempt': RUN_ATTEMPT,
            'workflow': gate.PREVIEW_WORKFLOW, 'event': 'workflow_dispatch', 'branch': 'main'}


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
        self.build['archive_inventory']['qt_binaries'] += ['pyside6/' + row['filename'] for row in runtime_fixture()['files']]
        proof = runtime_fixture()
        paths = ['pyside6/' + row['filename'] for row in proof['files']] + ['msvcp140.dll', 'vcruntime140.dll', 'vcruntime140_1.dll']
        self.build['archive_inventory']['microsoft_runtime'] = {'provenance': proof, 'embedded_files': [
            {'path': path, 'size': 2048, 'sha256': hashlib.sha256(b'X' * 2048).hexdigest()} for path in sorted(paths)]}
        self.smoke = {'status': 'passed', 'executable_sha256': self.hash,
                      'checks': sorted(gate.BASELINE_CHECKS),
                      'health': {'status': 'ok', 'applicationVersion': VERSION, 'ocr_enabled': True}}
        self.selftest = {'status': 'passed', 'frozen': True, 'applicationVersion': VERSION,
                         'recognized': ['珠光护手', '炼狱导管', '双刀流'], 'blank_candidates': 0,
                         'bundled_models': models}
        self.native_smoke = {'status': 'passed', 'executable_sha256': self.hash, 'applicationVersion': VERSION,
                             'process_exited': True, 'native_report': 'windows-native-overlay.json',
                             'native_screenshot': 'windows-native-overlay.png'}
        self.native = {'status': 'passed', 'backend': 'qtwidgets', 'frozen': True, 'qt_platform': 'windows',
                       'applicationVersion': VERSION, 'native_window': True, 'window_closed': True,
                       'capture_passed': True, 'ocr_passed': True, 'click_through_passed': True,
                       'screenshot_method': 'Qt QWidget.grab synthetic mock and overlay composite',
                       'source_tier_display_passed': True, 'source_tier_hero_specific': True, 'source_tier_missing_passed': True,
                       'source_tier_screen_order_preserved': True, 'source_tier_no_winrate_display': True,
                       'source_tier_rendered': ['虚构源评级（演示）：T1', '虚构源评级（演示）：T2', '虚构源评级（演示）：T3']}
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
        with zipfile.ZipFile(source, 'w') as archive:
            archive.comment = SHA.encode('ascii')
            for name in ('launcher.py', 'native_ui.py', 'native_smoke.py', 'requirements-build.txt',
                         'scripts/build_windows.py', 'packaging/VGA-Aram-Helper.spec'):
                archive.writestr(name, 'Unit-test source fixture')
        self.access = {'source_commit': SHA, 'application_source': {'filename': source.name,
                       'size': source.stat().st_size, 'sha256': gate.digest(source)}, 'qt_sources': qt_sources}
        self.build['source_access'] = copy.deepcopy(self.access)
        self.write_json(self.release / 'source-access.json', self.access)
        self.write_reports()
        for name in ('windows-exe-ui.png', 'windows-native-overlay.png'):
            (self.evidence / name).write_bytes(self.make_png())
        for name in ('windows-exe-self-test.log', 'windows-exe-server.log', 'windows-native-process.log', 'windows-build-environment.txt'):
            (self.evidence / name).write_text('fixture\n', encoding='utf-8')

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
        self.write_json(self.evidence / 'windows-build.json', self.build)
        self.write_json(self.evidence / 'windows-exe-smoke.json', self.smoke)
        self.write_json(self.evidence / 'windows-exe-self-test.json', self.selftest)
        self.write_json(self.evidence / 'windows-native-smoke.json', self.native_smoke)
        self.write_json(self.evidence / 'windows-native-overlay.json', self.native)
        self.write_json(self.evidence / 'windows-artifact-budget.json', self.budget)

    def verify(self, **kwargs):
        args = dict(release_dir=self.release, evidence_dir=self.evidence, repository=gate.REPOSITORY,
                    source_sha=SHA, output_dir=self.output, run_id=RUN_ID, run_attempt=RUN_ATTEMPT)
        args.update(kwargs)
        return gate.verify(**args)

    def test_valid_bundle_and_exact_evidence_zip(self):
        result = self.verify()
        self.assertEqual(result['tag'], 'v0.3.0')
        self.assertEqual(result['exe_sha256'], self.hash)
        self.assertEqual(len(result['assets']), 15)
        with zipfile.ZipFile(self.output / f'windows-test-evidence-{VERSION}.zip') as archive:
            self.assertEqual(set(archive.namelist()), set(gate.EVIDENCE_NAMES))
        self.assertEqual(json.loads((self.output / 'verified-release.json').read_text()), result)

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
        for key, value in [('source_sha', 'b' * 40), ('exe_sha256', '0' * 64), ('version', '0.4.0'),
                           ('tag', 'v0.4.0'), ('exe_size', 0), ('run_id', RUN_ID + 1), ('run_attempt', 2)]:
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
        self.assertIn(f'https://github.com/{gate.REPOSITORY}/releases/download/v0.3.0/third-party-licenses.zip', notes)

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
        for rendering in ([], ['T1', 'T2', 'T3'], ['虚构源评级（演示）：T3', '虚构源评级（演示）：T1', '虚构源评级（演示）：T2']):
            self.native['source_tier_rendered'] = rendering
            self.write_reports()
            with self.subTest(rendering=rendering), self.assertRaises(gate.VerificationError): self.verify()
        self.native['source_tier_rendered'] = ['虚构源评级（演示）：T1', '虚构源评级（演示）：T2', '虚构源评级（演示）：T3']
        for field in ('source_tier_display_passed', 'source_tier_hero_specific', 'source_tier_missing_passed',
                      'source_tier_screen_order_preserved', 'source_tier_no_winrate_display'):
            saved = self.native.pop(field)
            self.write_reports()
            with self.subTest(missing=field), self.assertRaises(gate.VerificationError): self.verify()
            self.native[field] = saved

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
        return {'ref': 'refs/tags/v0.3.0', 'object': {'sha': SHA, 'type': 'commit'}}

    def remote_release(self, result, draft=True):
        return {'id': 123, 'tag_name': 'v0.3.0', 'target_commitish': SHA, 'draft': draft, 'prerelease': True,
                'html_url': f'https://github.com/{gate.REPOSITORY}/releases/tag/v0.3.0',
                'assets': [{'name': a['name'], 'size': a['size'], 'state': 'uploaded',
                            'digest': 'sha256:' + a['sha256']} for a in result['assets']]}

    def test_publish_reserves_tag_then_draft_verifies_then_publishes(self):
        result = self.verify()
        draft = self.remote_release(result)
        final = self.remote_release(result, draft=False)
        reference = self.reference()
        replies = [None, [], reference, reference, [draft], reference, final, reference]
        with patch.object(gate, 'gh_api', side_effect=replies) as api, patch.object(gate, 'gh_run') as run:
            self.assertEqual(gate.publish(result, self.output / 'release-notes.txt', current_provenance()), final['html_url'])
        self.assertEqual(api.call_args_list[2].kwargs['fields'], {'ref': 'refs/tags/v0.3.0', 'sha': SHA})
        create, publish = [call.args[0] for call in run.call_args_list]
        self.assertIn('--draft', create)
        self.assertIn('--verify-tag', create)
        self.assertIn('--prerelease', create)
        self.assertIn('--latest=false', create)
        self.assertEqual(create[create.index('--target') + 1], SHA)
        self.assertEqual(publish, ['api', '--hostname', 'github.com', '--method', 'PATCH',
                                   '-H', 'Accept: application/vnd.github+json',
                                   f'repos/{gate.REPOSITORY}/releases/123', '--field', 'draft=false',
                                   '--field', 'prerelease=true', '--raw-field', 'make_latest=false'])
        self.assertNotIn('v0.3.0', ' '.join(publish))
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
        draft = {'id': 12, 'tag_name': 'v0.3.0', 'draft': True}
        with patch.object(gate, 'gh_api', side_effect=[first, [draft]]) as api:
            self.assertEqual(gate.find_release(gate.REPOSITORY, 'v0.3.0'), draft)
        self.assertIn('page=2', api.call_args.args[0])
        with patch.object(gate, 'gh_api', return_value=[draft, draft]), self.assertRaises(gate.VerificationError):
            gate.find_release(gate.REPOSITORY, 'v0.3.0')

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
                gate.gh_run(['release', 'create', 'v0.3.0'])
        self.assertNotIn('untrusted', str(error.exception))
        self.assertEqual(run.call_args.args[0], ['gh', 'release', 'create', 'v0.3.0'])
        self.assertNotIn('shell', run.call_args.kwargs)


class WorkflowSafetyTests(unittest.TestCase):
    def test_production_qt_source_inventory_remains_pinned(self):
        self.assertEqual(len(gate.QT_SOURCES), 4)
        self.assertEqual(sum(row['size'] for row in gate.QT_SOURCES), 73_028_200)
        self.assertEqual({row['sha256'] for row in gate.QT_SOURCES}, {
            'cba47efbaad1bedd529725cbc14e21f156c7a19366f07b3edfbb076ffd7afdf8',
            '5b2e00eccaf5a4d8c14134ffa0ea8dfd0a35ae1ffc7f8d87fa4305a1ed23cf22',
            'd594337feca84c26fb67fe87b85e6a5c12fda404b611d905f9d138210c311876',
            'cecd8900f34b6550076309bc94f62f828008b633a4239e0a08c86788f41001f8'})

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
        self.assertIn('timeout-minutes: 35', text)
        self.assertNotIn('actions/download-artifact', text)
        self.assertEqual(text.count('actions/upload-artifact@v4'), 1)
        self.assertIn('path: reports/windows-*', text)
        self.assertNotIn('path: dist/', text)
        self.assertIn('python scripts/check_artifact_budget.py --evidence-only', text)
        self.assertIn("always() && steps.evidence_budget.outcome == 'success'", text)
        self.assertEqual(text.count('retention-days: 1'), 1)
        self.assertIn('python scripts/build_windows.py', text)
        self.assertIn('tests/windows_exe_smoke.py --exe dist/VGA-Aram-Helper.exe --browser', text)
        self.assertIn('python tests/windows_native_smoke.py --exe dist/VGA-Aram-Helper.exe', text)
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

"""Portable integration contracts only, never native Windows or product acceptance."""
from __future__ import annotations
from contextlib import redirect_stderr, redirect_stdout
import copy
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace, ModuleType
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT/'tests'))
import launcher
import wgc_session_smoke as runtime
import windows_wgc_session_capture as harness
from scripts import build_windows as product
from scripts import build_wgc_capture as one_shot
from scripts import build_wgc_session_capture as session
from scripts import microsoft_runtime
from test_wgc_build import manifest as one_shot_manifest
from test_wgc_session_build import manifest, passing_report
from test_microsoft_runtime import runtime_fixture


def archive_fixture():
    """Synthetic CArchive and signed-CRT-shaped fixtures, not executable binaries."""
    entries = {name: b'fixture' for name in (
        'launcher', 'python312.dll', 'PySide6/Qt6Core.dll', 'PySide6/Qt6Gui.dll',
        'PySide6/Qt6Widgets.dll', 'PySide6/plugins/platforms/qwindows.dll',
        'static/index.html', 'fixtures/ocr-synthetic.png', 'fixtures/ocr-blank.png',
        'assets/branding/vga.ico', 'rapidocr/models/PP-OCRv6_det_small.onnx',
        'rapidocr/models/PP-OCRv6_rec_small.onnx',
        'rapidocr/models/ch_ppocr_mobile_v2.0_cls_mobile.onnx')}
    first, second = one_shot_manifest(), manifest()
    for module, proof, char in ((one_shot, first, b'a'), (session, second, b'b')):
        binary = b'MZ' + char*2046
        proof.update(size=len(binary), sha256=hashlib.sha256(binary).hexdigest())
        entries['native/'+module.FILENAME] = binary
        entries['native/'+module.MANIFEST] = json.dumps(proof).encode()
    crt = runtime_fixture()
    for row in crt['files']:
        binary = (row['filename'].encode()*2048)[:2048]
        row.update(size=len(binary), sha256=hashlib.sha256(binary).hexdigest())
        entries['PySide6/'+row['filename']] = binary
        if row['filename'] in ('msvcp140.dll', 'vcruntime140.dll', 'vcruntime140_1.dll'):
            entries[row['filename']] = binary
    archive = SimpleNamespace(toc=entries, extract=entries.__getitem__)
    return archive, first, second, crt


class ProductionBundleTests(unittest.TestCase):
    def setUp(self):
        self.archive, self.first, self.second, self.crt = archive_fixture()
        self.runtime = patch.object(microsoft_runtime, 'verify_source_files', return_value=self.crt)
        self.runtime.start(); self.addCleanup(self.runtime.stop)

    def verify(self):
        return product.verify_application_archive(self.archive, wgc_build=self.first, session_build=self.second)

    def test_current_inventory_includes_both_exact_helpers_and_original_runtime(self):
        result = self.verify()
        self.assertEqual(result['wgc_helper'], self.first)
        self.assertEqual(result['wgc_session_helper'], self.second)
        self.assertEqual(result['launch_script'], 'launcher')
        self.assertEqual(result['microsoft_runtime']['provenance'], self.crt)
        self.assertEqual(len(result['microsoft_runtime']['embedded_files']), 8)
        self.assertEqual(result['model_assets'], 3)

    def test_each_helper_manifest_and_application_launcher_are_mandatory(self):
        for name in ('launcher', 'native/'+one_shot.FILENAME, 'native/'+one_shot.MANIFEST,
                     'native/'+session.FILENAME, 'native/'+session.MANIFEST):
            data = self.archive.toc.pop(name)
            with self.subTest(name=name), self.assertRaises(RuntimeError): self.verify()
            self.archive.toc[name] = data

    def test_corrupt_or_substituted_helper_bytes_never_pass(self):
        for module in (one_shot, session):
            name = 'native/'+module.FILENAME; original = self.archive.toc[name]
            for bad in (b'!', original+b'!', b'!'+original[1:]):
                self.archive.toc[name] = bad
                with self.subTest(name=name, size=len(bad)), self.assertRaises(RuntimeError): self.verify()
            self.archive.toc[name] = original
            name = 'native/'+module.MANIFEST; original = self.archive.toc[name]
            changed = json.loads(original); changed['source_commit'] = 'f'*40
            self.archive.toc[name] = json.dumps(changed).encode()
            with self.assertRaises(RuntimeError): self.verify()
            self.archive.toc[name] = original

    def test_helper_source_mismatch_is_rejected(self):
        self.second['source_commit'] = 'f'*40
        with self.assertRaisesRegex(RuntimeError, 'different source commits'): self.verify()

    def test_session_archive_rejects_duplicate_paths_or_manifest_keys(self):
        path = 'native/'+session.FILENAME
        self.archive.toc[path.upper()] = self.archive.toc[path]
        with self.assertRaisesRegex(RuntimeError, 'duplicate paths'): self.verify()
        del self.archive.toc[path.upper()]
        path = 'native/'+session.MANIFEST; original = self.archive.toc[path]
        self.archive.toc[path] = b'{"status":"passed",'+original[1:]
        with self.assertRaisesRegex(RuntimeError, 'duplicate keys'): self.verify()
        for bad in (b' '*65537, 'not bytes'):
            self.archive.toc[path] = bad
            with self.assertRaisesRegex(RuntimeError, 'manifest'): self.verify()

    def test_existing_crt_and_optional_runtime_gates_remain_mandatory(self):
        name = 'PySide6/msvcp140.dll'; original = self.archive.toc[name]
        self.archive.toc[name] = b'!'+original[1:]
        with self.assertRaisesRegex(RuntimeError, 'licensed source'): self.verify()
        self.archive.toc[name] = original
        for unwanted in ('PySide6/Qt6WebEngineCore.dll', 'PySide6/opengl32sw.dll', 'PySide6/qopensslbackend.dll'):
            self.archive.toc[unwanted] = b'!'
            with self.subTest(unwanted=unwanted), self.assertRaises(RuntimeError): self.verify()
            del self.archive.toc[unwanted]

    def test_spec_requests_verified_helpers_manifests_and_explicit_runtime_modules(self):
        # Execute only the recipe with mocked PyInstaller interfaces. No Windows
        # binaries, models, or dependencies are built/loaded by this contract test.
        hooks = ModuleType('PyInstaller.utils.hooks')
        hooks.collect_data_files = Mock(return_value=[]); hooks.copy_metadata = Mock(return_value=[])
        analyze = Mock(return_value=SimpleNamespace(binaries=[], datas=[], pure=[], scripts=[]))
        freeze = Mock()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); (root/'build').mkdir()
            namespace = {'SPECPATH': str(root/'packaging'), 'Analysis': analyze, 'PYZ': Mock(), 'EXE': freeze}
            with patch.dict(sys.modules, {'PyInstaller.utils.hooks': hooks}), \
                 patch('model_inventory.verify_models'), \
                 patch.object(one_shot, 'verify_built_helper', return_value=self.first) as old_verify, \
                 patch.object(session, 'verify_built_helper', return_value=self.second) as new_verify, \
                 patch.object(microsoft_runtime, 'replace_runtime_entries', side_effect=lambda entries: entries), \
                 patch('scripts.windows_package.trim_unused_binaries', side_effect=lambda entries:(entries, {})), \
                 patch('scripts.windows_package.custom_package', return_value=False), \
                 patch.object(sys, 'path', list(sys.path)):
                path = ROOT/'packaging/VGA-Aram-Helper.spec'
                exec(compile(path.read_text(), str(path), 'exec'), namespace)
            old_verify.assert_called_once_with(); new_verify.assert_called_once_with()
            self.assertEqual(analyze.call_args.args[0], [str(root/'launcher.py')])
            self.assertEqual(analyze.call_args.kwargs['binaries'],
                [(str(root/'build/native'/name), 'native') for name in (one_shot.FILENAME, session.FILENAME)])
            for name in (one_shot.MANIFEST, session.MANIFEST):
                self.assertIn((str(root/'build/native'/name), 'native'), analyze.call_args.kwargs['datas'])
            for name in ('wgc_capture', 'wgc_smoke', 'wgc_session_capture', 'wgc_session_smoke', 'persistent_capture_adapter', 'native_ui', 'local_ocr'):
                self.assertIn(name, analyze.call_args.kwargs['hiddenimports'])
            self.assertEqual(freeze.call_args.kwargs['name'], 'VGA-Aram-Helper')
            self.assertIs(freeze.call_args.kwargs['console'], False)
            self.assertIs(freeze.call_args.kwargs['upx'], False)


class ApplicationLauncherTests(unittest.TestCase):
    def test_explicit_modes_short_circuit_all_normal_app_startup(self):
        # Source import guard catches accidental imports even without Qt/OCR.
        import builtins
        original = builtins.__import__
        def guarded(name, *args, **kwargs):
            if name in ('native_ui', 'server', 'updates', 'local_ocr'):
                raise AssertionError('Diagnostic entered normal application startup: '+name)
            return original(name, *args, **kwargs)
        for flag, target in (('--wgc-session-smoke-report', 'run'),
                             ('--wgc-session-job-owner-report', 'job_owner')):
            with patch.object(runtime, target, return_value=7) as call, patch.object(builtins, '__import__', guarded):
                self.assertEqual(launcher.main([flag, 'owned.json']), 7)
            call.assert_called_once_with(Path('owned.json'), application=True)

    def test_every_normal_option_and_other_diagnostic_conflicts(self):
        extras = (['--headless'], ['--no-browser'], ['--demo'], ['--no-updates'], ['--version'], ['--help'],
                  ['--port', '8765'], ['--version-file', 'x'], ['--licenses-file', 'x'], ['--licenses'],
                  ['--wgc-smoke-report', 'x'], ['--native-smoke-report', 'x'], ['--selection-smoke-input', 'x'],
                  ['--selection-smoke-report', 'x'], ['--self-test'], ['--report', 'x'], ['--ready-file', 'x'],
                  ['--apply-update', 'x'], ['--update-health', 'x'], ['--hwnd', '123'], ['--target', '123'])
        for flag in ('--wgc-session-smoke-report', '--wgc-session-job-owner-report'):
            for extra in extras:
                for argv in ([flag, 'owned.json', *extra], [*extra, flag+'=owned.json']):
                    with self.subTest(argv=argv), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                        launcher.main(argv)
                    self.assertEqual(error.exception.code, 2)
        for argv in (['--wgc-session-smoke-report', 'x', '--wgc-session-job-owner-report', 'y'],
                     ['--wgc-session-smoke-report', 'x', '--wgc-session-smoke-report', 'y'],
                     ['--wgc-session-smoke-r', 'x']):
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit): launcher.main(argv)

    def test_source_and_frozen_parent_death_use_only_exact_intended_entrypoint(self):
        for application in (False, True):
            for frozen in (False, True):
                with patch.object(runtime.sys, 'frozen', frozen, create=True), \
                     patch.object(runtime.sys, 'executable', 'exact-current.exe'):
                    command = runtime.parent_death_command(Path('owner.json'), application=application)
                expected = ['exact-current.exe']
                if not frozen:
                    expected += [str(ROOT/('launcher.py' if application else 'wgc_session_diagnostic.py'))]
                expected += ['--wgc-session-job-owner-report' if application else '--job-owner-report', 'owner.json']
                self.assertEqual(command, expected)

    def test_harness_command_separates_source_and_exact_application_exe(self):
        self.assertEqual(harness.diagnostic_command('r.json', application=True),
                         [sys.executable, str(ROOT/'launcher.py'), '--wgc-session-smoke-report', 'r.json'])
        self.assertEqual(harness.diagnostic_command('r.json', application=True, executable='exact.exe'),
                         ['exact.exe', '--wgc-session-smoke-report', 'r.json'])
        self.assertEqual(harness.diagnostic_command('r.json', application=False, executable='fixture.exe'),
                         ['fixture.exe', '--report', 'r.json'])

    def test_linux_application_diagnostic_fails_with_scoped_mode_report(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'r.json'
            with patch.object(runtime, 'os', SimpleNamespace(name='posix')):
                self.assertEqual(runtime.run(path, application=True), 1)
            report = json.loads(path.read_text())
            self.assertEqual(report['status'], 'failed')
            self.assertEqual(report['diagnostic_entrypoint'], 'application')
            self.assertEqual(report['scope'], runtime.APPLICATION_SCOPE)
            self.assertNotIn('owned_pixels_passed', report)


class ApplicationEvidenceTests(unittest.TestCase):
    def evidence(self, *, frozen=True, application=True):
        proof = manifest()
        inventory = {'launch_script': 'launcher', 'wgc_session_helper': proof}
        report = {'schema_version': 1, 'status': 'passed', 'frozen': frozen, 'applicationVersion': harness.__version__,
                  **runtime.diagnostic_contract(application), 'scales': list(harness.SCALES),
                  'source_commit': proof['source_commit'], 'helper_build': proof,
                  'source_files': {name:row['sha256'] for name,row in proof['source_files'].items()},
                  'runs': [{'app_scale': scale, 'detail': passing_report(scale, frozen, application)}
                           for scale in harness.SCALES]}
        expected = {'frozen': frozen, 'application': application, 'helper_build': proof, 'source_commit': proof['source_commit']}
        if frozen:
            report.update(executable_sha256='f'*64, executable_size=12345)
            expected.update(executable_sha256='f'*64, executable_size=12345)
            if application:
                report['archive_inventory'] = inventory; expected['archive_inventory'] = copy.deepcopy(inventory)
        return report, expected

    def test_both_modes_all_scales_validate_only_against_external_exact_inputs(self):
        for frozen in (False, True):
            for application in (False, True):
                report, expected = self.evidence(frozen=frozen, application=application)
                self.assertIs(harness.validate_acceptance(report, **expected), report)
                self.assertEqual(len(report['runs']), 3)
                self.assertEqual(len(harness.CHECK_FIELDS), 40)
                for row in report['runs']:
                    self.assertEqual(len(row['detail']['shutdown_stress']['rows']), 10)

    def test_product_evidence_rejects_standalone_substitution_at_every_level(self):
        report, expected = self.evidence()
        for alter in (lambda v:v.update(runtime.diagnostic_contract()),
                      lambda v:v['runs'][0]['detail'].update(runtime.diagnostic_contract()),
                      lambda v:v['runs'][0]['detail']['parent_death_observation'].update(diagnostic_entrypoint='standalone'),
                      lambda v:v.pop('diagnostic_entrypoint'),
                      lambda v:v.pop('archive_inventory')):
            changed = copy.deepcopy(report); alter(changed)
            with self.assertRaises(RuntimeError): harness.validate_acceptance(changed, **expected)

    def test_frozen_mode_requires_supplied_exact_exe_and_archive_inputs(self):
        report, expected = self.evidence()
        for key, bad in (('executable_sha256', None), ('executable_sha256', '0'*64),
                         ('executable_size', None), ('executable_size', True), ('executable_size', 12346),
                         ('archive_inventory', None), ('archive_inventory', {})):
            with self.subTest(key=key, bad=bad), self.assertRaises(RuntimeError):
                harness.validate_acceptance(report, **dict(expected, **{key:bad}))
        for key, bad in (('executable_sha256', '0'*64), ('executable_size', 12346), ('source_commit', '0'*40),
                         ('source_files', {}), ('scales', [1, 2]), ('runs', []), ('status', 'skipped'),
                         ('applicationVersion', '0.0.0'), ('frozen', 1), ('schema_version', True)):
            changed = copy.deepcopy(report); changed[key] = bad
            with self.subTest(key=key), self.assertRaises(RuntimeError): harness.validate_acceptance(changed, **expected)
        for alter in (lambda v:v['runs'].reverse(), lambda v:v['runs'].pop(),
                      lambda v:v['runs'][0]['detail'].update(native_shutdown_stress_passed=False),
                      lambda v:v['runs'][1]['detail']['shutdown_stress']['rows'].pop(),
                      lambda v:v['source_files'].pop('launcher.py'),
                      lambda v:v['archive_inventory'].update(launch_script='wgc_session_diagnostic')):
            changed = copy.deepcopy(report); alter(changed)
            with self.assertRaises(RuntimeError): harness.validate_acceptance(changed, **expected)

    def test_source_and_standalone_cannot_claim_product_frozen_archive(self):
        for frozen, application in ((False, True), (False, False), (True, False)):
            report, expected = self.evidence(frozen=frozen, application=application)
            report['archive_inventory'] = {'launch_script': 'launcher'}
            with self.assertRaises(RuntimeError): harness.validate_acceptance(report, **expected)
        report, expected = self.evidence(frozen=False)
        for key, value in (('executable_sha256', 'f'*64), ('executable_size', 12345), ('archive_inventory', {})):
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                harness.validate_acceptance(report, **dict(expected, **{key:value}))

    def test_mode_selection_must_be_boolean_and_summary_cannot_run_exe(self):
        for value in (1, 'application', None):
            with self.assertRaises(ValueError): runtime.diagnostic_contract(value)
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            harness.main(['--application', '--summarize', '--exe', 'app.exe'])

    def test_application_summary_binds_build_and_all_six_product_runs(self):
        source, unused = self.evidence(frozen=False)
        frozen, expected = self.evidence()
        proof = manifest()
        build = {'status': 'built-not-yet-smoke-tested', 'version': harness.__version__,
                 'source_commit': proof['source_commit'], 'wgc_session_helper_build': proof,
                 'manifest': {'sha256': expected['executable_sha256'], 'size': expected['executable_size'],
                              'version': harness.__version__}, 'archive_inventory': expected['archive_inventory']}
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            values = {'windows-wgc-session-build.json': proof, 'windows-build.json': build,
                      'windows-wgc-session-application-source.json': source,
                      'windows-wgc-session-application-frozen.json': frozen}
            for name, value in values.items(): (root/name).write_text(json.dumps(value))
            with redirect_stdout(io.StringIO()):
                self.assertEqual(harness.main(['--application', '--summarize', '--reports', str(root)]), 0)
            summary = json.loads((root/'windows-wgc-session-application-summary.json').read_text())
            self.assertEqual(summary['status'], 'passed'); self.assertEqual(len(summary['runs']), 6)
            self.assertEqual(summary['diagnostic_entrypoint'], 'application')
            self.assertEqual(summary['application_executable']['sha256'], expected['executable_sha256'])
            self.assertEqual(summary['limitations'], runtime.LIMITATIONS)
            self.assertFalse((root/'windows-wgc-session-summary.json').exists())
            build['manifest']['sha256'] = '0'*64
            (root/'windows-build.json').write_text(json.dumps(build))
            with redirect_stdout(io.StringIO()): self.assertEqual(harness.summarize(root, application=True), 1)
            build['manifest']['sha256'] = expected['executable_sha256']
            (root/'windows-build.json').write_text(json.dumps(build))
            frozen.update(runtime.diagnostic_contract())
            (root/'windows-wgc-session-application-frozen.json').write_text(json.dumps(frozen))
            with redirect_stdout(io.StringIO()): self.assertEqual(harness.summarize(root, application=True), 1)
            (root/'windows-wgc-session-application-source.json').unlink()
            with redirect_stdout(io.StringIO()): self.assertEqual(harness.summarize(root, application=True), 1)



if __name__ == '__main__': unittest.main()

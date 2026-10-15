"""Portable, dependency-free schema/parity/performance gate tests."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import probe_opencv_parity as probe
from scripts import probe_capture_phases as phases


BUILD = '''
General configuration for OpenCV 5.0.0
  Algorithm Hint: ALGO_HINT_ACCURATE
  CPU/HW features:
    Baseline: SSE SSE2 SSE3
    Dispatched code generation: SSE4_1 SSE4_2 AVX FP16 AVX2 AVX512_SKX
  C/C++:
    C++ flags (Release): /O2 /fp:precise /DNDEBUG
    C flags (Release): /O2 /fp:precise /DNDEBUG
  OpenCV modules:
    To be built: calib core dnn features flann geometry highgui imgcodecs imgproc objdetect photo ptcloud python3 stereo stitching video videoio
  Media I/O:
    JPEG: build-libjpeg-turbo (ver 3.1.2-70)
      SIMD Support Request: YES
      SIMD Support: YES
    WEBP: build (ver decoder: 0x0210, encoder: 0x0210, demux: 0x0107)
    PNG: build (ver 1.6.58)
      Metadata Support: EXIF XMP ICC cICP
  Parallel framework: Concurrency
  Other third-party libraries:
    Intel IPP: 2026.0.0 [2026.0.0]
    Intel IPP IW: sources (2026.0.0)
    Custom HAL: YES (ipp (ver 0.0.1))
  OpenCL: YES (no extra features)
'''


def sample_record(value=0.1):
    return {'samples_seconds': [value] * 7, 'median_seconds': value,
            'min_seconds': value, 'max_seconds': value, 'warmups': 2,
            'iterations_per_sample': 10, 'output_sha256': 'a' * 64}


def capture_diagnostic(report):
    record = report['performance']['capture_synthetic_window']
    record['iterations_per_sample'] = 3
    output = {'image_sha256': '8' * 64, 'width': 960, 'height': 640}
    record['output_sha256'] = probe.sha256(probe.canonical(output).encode('utf-8'))
    proof = {'sha256': '2' * 64, 'size': 100}
    identity = {'loaded': {key: dict(proof) for key in ('cv2_native', 'pillow_native', 'pillow_image', 'pillow_png')},
                'sources': {name: dict(proof) for name in phases.SOURCE_FILES},
                'helpers': {}, 'bound_one_shot': True, 'pillow_version': report['dependencies']['Pillow']}
    identity['loaded']['cv2_native']['sha256'] = report['opencv']['binary']['sha256']
    for name, protocol in (('one_shot', 1), ('session', 2)):
        identity['helpers'][name] = {'status': 'verified', 'binary': dict(proof), 'manifest': dict(proof),
            'protocol': protocol, 'source_commit': '1' * 40, 'source_sha256': '2' * 64, 'build_recipe_sha256': '2' * 64}
    observation = {'backend': 'windows-graphics-capture', 'cleanup_pending': False,
                   'one_shot_helper_sha256': '2' * 64, 'fallback_reason': 'not-applicable'}
    rows = []
    for context in phases.CONTEXTS:
        for index in range(phases.CALLS_PER_CONTEXT):
            row = dict(observation, context=context, index=index, status='passed',
                phase_seconds={'wgc_inclusive': .08, 'helper_verify': .001, 'frame_decode': .001, 'png_encode': .01},
                phase_calls={name: 1 for name in phases.PHASES}, total_seconds=.1,
                outer_residual_seconds=.1-.08-.01, helper_starts=1, helpers_exited=True,
                helper_pipes_closed=True, helper_jobs_closed=True, worker_exited=True, cancelled=False,
                qt_pumps=0 if context == 'gui_blocked' else 10, capture_on_caller_thread=context == 'gui_blocked',
                output=dict(output), client_rect=[20, 20, 960, 640])
            rows.append(row)
    return {'schema_version': 1, 'status': 'passed', 'errors': [],
        'authoritative_observations': [dict(observation) for _ in range((record['warmups'] + len(record['samples_seconds'])) * 3)],
        'expected_output': output, 'expected_client_rect': [20, 20, 960, 640],
        **{key: copy.deepcopy(identity) for key in ('identity_before_supplemental', 'identity_after_supplemental')},
        'supplemental': {'schema_version': 1, 'status': 'passed', 'scope': phases.SCOPE,
            'excluded_from_adoption': True, 'calls_per_context': phases.CALLS_PER_CONTEXT,
            'call_timeout_seconds': phases.CALL_TIMEOUT, 'cancellation_grace_seconds': phases.CANCEL_GRACE,
            'deadline_kind': phases.DEADLINE_KIND, 'safe_to_close_fixture': True, 'rows': rows}}


def reports():
    ocr = {}
    for name in probe.OCR_CASES:
        names = [] if name == 'ocr-blank.png' else probe.FIXTURE_NAMES if name == 'ocr-synthetic.png' else probe.DEMO_NAMES
        ocr[name] = {'mode': 'local-screenshot-ocr', 'network_transmission': False,
                     'image_saved': False, 'image_size': {'width': 1280, 'height': 720},
                     'ocr_lines': [{'text': value, 'confidence': 0.95, 'box': [[1, 2], [3, 4]]} for value in names],
                     'candidates': [{'name': value, 'requires_confirmation': True} for value in names],
                     'warning': 'Synthetic fixture only'}
    hero = {name: {'hero': 'synthetic' if 'x' in name else None,
                   'championId': '9001' if 'x' in name else None,
                   'confident': 'x' in name, 'method': 'own-hud-portrait', 'reason': 'synthetic'}
            for name in probe.HERO_CASES}
    api = {name: {'shape': [1], 'dtype': '|u1', 'bytes': 1, 'sha256': '0' * 64}
           for name in probe.expected_api_cases()}
    binary = {'path': 'baseline/cv2.pyd', 'sha256': '1' * 64, 'raw_bytes': 100, 'zlib9_bytes': 80}
    performance = {name: sample_record() for name in probe.PERFORMANCE_CASES | {'capture_synthetic_window'}}
    performance['capture_synthetic_window']['fixture'] = {'kind': 'own-process synthetic painted Qt window',
                                                          'width': 960, 'height': 640, 'device_pixel_ratio': 1.0, 'qt_version': '6.11.2'}
    baseline = {'schema_version': probe.SCHEMA_VERSION, 'status': 'completed', 'scope': probe.SCOPE,
                'run': {'id': 'official-report', 'process_nonce': 'official-process', 'pid': 100, 'created_unix': 10000},
                'host': {'system': 'Windows', 'identity_sha256': '7' * 64, 'python': '3.12.10',
                         'release': '11', 'version': '10.0', 'machine': 'AMD64', 'processor': 'x86',
                         'logical_cpus': 4, 'python_implementation': 'CPython'},
                'dependencies': {name: 'pinned' for name in probe.DEPENDENCIES},
                'onnxruntime_telemetry': {'disabled_before_ocr_import_and_construction': True,
                                        'environment': {'ORT_DISABLE_TELEMETRY': '1'},
                                        'environment_set_before_onnxruntime_import': True,
                                        'method': 'ORT_DISABLE_TELEMETRY=1 then onnxruntime.disable_telemetry_events'},
                'opencv': {'cv_version': '5.0.0', 'distributions': {'opencv-python-headless': probe.OFFICIAL_VERSION},
                           'build_information': BUILD, 'build_features': probe.parse_build_information(BUILD),
                           'binary': binary, 'imported_python_submodules': ['cv2.data', 'cv2.typing'],
                           'exported_native_namespaces': ['ipp', 'ocl'], 'import_errors': [],
                           'runtime': {'threads': 2, 'optimized': True, 'cpu_features': 'SSE3 *AVX2',
                                       'ipp_enabled': True, 'ipp_not_exact': False, 'ipp_version': '2026',
                                       'opencl_available': False, 'opencl_enabled': False}},
                'native': {'path': binary['path'], 'sha256': binary['sha256'], 'size': 100, 'zlib9_size': 80},
                'inputs': {name: '2' * 64 for name in probe.expected_input_cases()},
                'models': [{'name': 'local.onnx', 'size': 100, 'sha256': '3' * 64}],
                'api_results': api, 'ocr_results': ocr, 'hero_results': hero, 'performance': performance,
                'coverage': {'api_cases': len(api), 'ocr_cases': len(ocr), 'hero_cases': len(hero),
                             'ocr_formats': sorted(probe.FORMATS), 'icc_formats': list(probe.ICC_FORMATS)}}
    for name in probe.PERFORMANCE_CASES:
        baseline['performance'][name]['output_sha256'] = probe.sha256(probe.canonical(probe.performance_output(baseline, name)).encode('utf-8'))
    candidate = copy.deepcopy(baseline)
    candidate['run'] = {'id': 'custom-report', 'process_nonce': 'custom-process', 'pid': 101, 'created_unix': 10001}
    candidate['opencv']['distributions']['opencv-python-headless'] = probe.CUSTOM_VERSION
    text = BUILD.replace('calib core dnn features flann geometry highgui imgcodecs imgproc objdetect photo ptcloud python3 stereo stitching video videoio',
                         'core flann geometry imgcodecs imgproc python3')
    candidate['opencv']['build_information'] = text
    candidate['opencv']['build_features'] = probe.parse_build_information(text)
    candidate['opencv']['binary'] = {'path': 'candidate/cv2.pyd', 'sha256': '4' * 64, 'raw_bytes': 60, 'zlib9_bytes': 40}
    candidate['native'] = {'path': 'candidate/cv2.pyd', 'sha256': '4' * 64, 'size': 60, 'zlib9_size': 40}
    for report in (baseline, candidate):
        report['performance']['capture_synthetic_window']['capture_diagnostics'] = capture_diagnostic(report)
    return baseline, candidate


def set_timing(report, name, value):
    old = report['performance'][name]
    record = sample_record(value)
    record['output_sha256'] = old['output_sha256']
    if 'fixture' in old:
        record['fixture'] = old['fixture']
    if 'capture_diagnostics' in old:
        record['capture_diagnostics'] = old['capture_diagnostics']
        record['iterations_per_sample'] = old['iterations_per_sample']
    report['performance'][name] = record


def change_build(report, old, new):
    report['opencv']['build_information'] = report['opencv']['build_information'].replace(old, new)
    report['opencv']['build_features'] = probe.parse_build_information(report['opencv']['build_information'])


class OpenCVParityTests(unittest.TestCase):
    def assert_fails(self, baseline, candidate, fragment):
        result = probe.compare_reports(baseline, candidate)
        self.assertEqual(result['status'], 'failed', result)
        self.assertTrue(any(fragment in message for message in result['failures']), result['failures'])
        return result

    def test_complete_pair_is_deterministic_and_requires_windows(self):
        baseline, candidate = reports()
        self.assertEqual(probe.validate_report(baseline), [])
        self.assertEqual(probe.validate_report(candidate), [])
        first = probe.compare_reports(baseline, candidate)
        self.assertEqual(first['status'], 'passed', first)
        self.assertTrue(first['windows_release_evidence'])
        self.assertEqual(first, probe.compare_reports(baseline, candidate))
        self.assertEqual(first['coverage'], {'api_cases': 112, 'ocr_cases': 10, 'hero_cases': 8,
                                            'ocr_formats': ['BMP', 'JPEG', 'PNG', 'WEBP'],
                                            'icc_formats': ['PNG', 'JPEG', 'WEBP']})
        for report in (baseline, candidate):
            report['host']['system'] = 'Linux'
            del report['performance']['capture_synthetic_window']
        self.assert_fails(baseline, candidate, 'requires Windows')
        diagnostic = probe.compare_reports(baseline, candidate, allow_non_windows=True)
        self.assertEqual(diagnostic['status'], 'passed')
        self.assertFalse(diagnostic['windows_release_evidence'])

    def test_reused_numeric_pid_does_not_confuse_distinct_process_nonces(self):
        baseline, candidate = reports()
        candidate['run']['pid'] = baseline['run']['pid']
        self.assertEqual(probe.compare_reports(baseline, candidate)['status'], 'passed')
        candidate['run']['process_nonce'] = baseline['run']['process_nonce']
        self.assert_fails(baseline, candidate, 'fresh, separate')

    def test_no_output_tolerance_or_ocr_confidence_rounding(self):
        for section, key in (('api_results', 'matchTemplate-20'),
                             ('ocr_results', 'PNG-ICC'), ('hero_results', '1920x1080')):
            baseline, candidate = reports()
            if section == 'api_results':
                candidate[section][key]['sha256'] = 'f' * 64
            elif section == 'ocr_results':
                candidate[section][key]['ocr_lines'][0]['confidence'] += 1e-12
            else:
                candidate[section][key]['reason'] = 'Changed abstention behavior'
            if section == 'hero_results':
                candidate['performance']['hero_1080p']['output_sha256'] = probe.sha256(probe.canonical(candidate[section][key]).encode('utf-8'))
            result = self.assert_fails(baseline, candidate, 'exact-output differences')
            self.assertEqual(result['differences'][section], [key])

    def test_missing_or_empty_corpus_cannot_pass(self):
        for section in ('api_results', 'ocr_results', 'hero_results', 'performance'):
            baseline, candidate = reports()
            candidate[section] = {}
            self.assert_fails(baseline, candidate, 'inventory differs')
        baseline, candidate = reports()
        del candidate['ocr_results']['PNG-ICC']['ocr_lines']
        self.assert_fails(baseline, candidate, 'full non-timing result')
        baseline, candidate = reports()
        candidate['ocr_results']['PNG']['elapsed_seconds'] = [1.2]
        self.assert_fails(baseline, candidate, 'full non-timing result')

    def test_feature_reductions_and_fast_math_are_not_silent(self):
        for old, new, error in (('SSE4_1 SSE4_2 AVX FP16 AVX2 AVX512_SKX', 'AVX2', 'cpu_dispatch'),
                                ('Intel IPP: 2026.0.0 [2026.0.0]', 'Intel IPP: NO', 'ipp'),
                                ('OpenCL: YES (no extra features)', 'OpenCL: NO', 'opencl'),
                                ('SIMD Support: YES', 'SIMD Support: NO', 'JPEG SIMD'),
                                ('/fp:precise', '/fp:fast', 'fast-math'),
                                ('EXIF XMP ICC cICP', 'EXIF XMP', 'png_metadata'),
                                ('core flann geometry', 'core geometry', 'compiled modules'),
                                ('ver 3.1.2-70', 'ver 3.0', 'image codec')):
            with self.subTest(change=new):
                baseline, candidate = reports()
                change_build(candidate, old, new)
                self.assert_fails(baseline, candidate, error)

    def test_exact_array_records_and_complete_input_hashes_are_required(self):
        for field, value in (('sha256', 'missing'), ('bytes', 2), ('shape', [-1]), ('dtype', 'unknown')):
            baseline, candidate = reports()
            candidate['api_results']['COLOR_RGB2GRAY'][field] = value
            self.assert_fails(baseline, candidate, 'invalid exact array/scalar record')
        baseline, candidate = reports()
        del candidate['inputs']['ocr/WEBP-ICC']
        self.assert_fails(baseline, candidate, 'identities are missing')
        baseline, candidate = reports()
        candidate['performance']['ocr_app_demo']['output_sha256'] = 'f' * 64
        self.assert_fails(baseline, candidate, 'saved correctness result')
        self.assertTrue(probe.valid_snapshot({'float64_hex': '-0x0.0p+0'}))
        self.assertFalse(probe.valid_snapshot({'float64_hex': 'nan'}))
        self.assertFalse(probe.valid_snapshot({'float64_hex': 12}))

    def test_cross_platform_pair_fails_without_crashing(self):
        baseline, candidate = reports()
        candidate['host']['system'] = 'Linux'
        del candidate['performance']['capture_synthetic_window']
        self.assert_fails(baseline, candidate, 'same host')

    def test_truthful_build_and_native_metadata_required(self):
        baseline, candidate = reports()
        candidate['opencv']['build_features']['cpu_dispatch'] = []
        self.assert_fails(baseline, candidate, 'disagrees with getBuildInformation')
        baseline, candidate = reports()
        candidate['native']['sha256'] = '8' * 64
        self.assert_fails(baseline, candidate, 'native metadata disagrees')
        baseline, candidate = reports()
        candidate['opencv']['import_errors'] = [{'module': 'cv2.typing', 'error': 'Missing API'}]
        self.assert_fails(baseline, candidate, 'imports failed')

    def test_wheel_process_host_and_dependency_identity_required(self):
        changes = ((lambda r: r['opencv']['distributions'].update({'opencv-python': '5.0.0.93'}), 'expected only'),
                   (lambda r: r['run'].update({'process_nonce': 'official-process'}), 'fresh, separate'),
                   (lambda r: r['host'].update({'python': '3.13'}), 'same host'),
                   (lambda r: r['dependencies'].update({'numpy': 'different'}), 'dependencies changed'),
                   (lambda r: r['inputs'].update({'local_ocr.py': 'f' * 64}), 'inputs changed'),
                   (lambda r: r['opencv']['runtime'].update({'ipp_enabled': False}), 'runtime CPU'))
        for change, fragment in changes:
            baseline, candidate = reports()
            change(candidate)
            self.assert_fails(baseline, candidate, fragment)

    def test_all_slowdowns_reported_but_gate_uses_ratio_and_noise_floor(self):
        baseline, candidate = reports()
        set_timing(candidate, 'ocr_app_demo', 0.12)
        result = probe.compare_reports(baseline, candidate)
        self.assertEqual(result['status'], 'passed')
        self.assertAlmostEqual(result['performance']['ocr_app_demo']['ratio'], 1.2)
        set_timing(candidate, 'ocr_app_demo', 0.16)
        self.assert_fails(baseline, candidate, 'median regression')
        set_timing(baseline, 'ocr_app_demo', 0.001)
        set_timing(candidate, 'ocr_app_demo', 0.003)
        result = probe.compare_reports(baseline, candidate)
        self.assertEqual(result['status'], 'passed')
        self.assertEqual(result['performance']['ocr_app_demo']['ratio'], 3)
        self.assertFalse(result['performance']['ocr_app_demo']['regression'])
        set_timing(candidate, 'ocr_app_demo', 0.01)
        self.assert_fails(baseline, candidate, 'median regression')

    def test_raw_samples_warmups_and_summary_validated(self):
        for field, value in (('samples_seconds', [0.1]), ('samples_seconds', [0] * 7),
                             ('samples_seconds', [float('nan')] * 7), ('warmups', 0),
                             ('median_seconds', 0.2), ('output_sha256', 'missing')):
            baseline, candidate = reports()
            candidate['performance']['ocr_app_demo'][field] = value
            self.assertTrue(probe.validate_report(candidate), (field, value))
        baseline, candidate = reports()
        candidate['performance']['ocr_app_demo']['iterations_per_sample'] = 1
        self.assert_fails(baseline, candidate, 'sampling configuration differs')
        baseline, candidate = reports()
        candidate['performance']['hero_1080p']['output_sha256'] = '0' * 64
        self.assert_fails(baseline, candidate, 'exact warmed output differs')

    def test_capture_latency_is_required_on_windows_and_checks_its_fixture(self):
        baseline, candidate = reports()
        del candidate['performance']['capture_synthetic_window']
        self.assert_fails(baseline, candidate, 'performance inventory')
        baseline, candidate = reports()
        candidate['performance']['capture_synthetic_window']['fixture']['qt_version'] = 'different'
        self.assert_fails(baseline, candidate, 'capture fixture/Qt version differs')
        baseline, candidate = reports()
        candidate['performance']['capture_synthetic_window']['fixture']['width'] = 961
        self.assert_fails(baseline, candidate, 'output size differs')

    def test_benchmark_rejects_nondeterminism_without_timing_the_fingerprint(self):
        values = iter([1, 1, 2])
        with self.assertRaisesRegex(RuntimeError, 'changed its exact output'):
            probe.benchmark(lambda: next(values), samples=7, warmups=2,
                            iterations=1, fingerprint=lambda x: x)
        record = probe.benchmark(lambda: 1, samples=7, warmups=2, iterations=2, fingerprint=lambda x: x)
        self.assertEqual(len(record['samples_seconds']), 7)
        self.assertEqual(record['output_sha256'], probe.sha256(b'1'))


    def test_capture_diagnostic_sources_native_helpers_and_all_rows_are_bound(self):
        baseline, candidate = reports()
        self.assertTrue(set(phases.SOURCE_FILES) <= set(probe.SOURCE_FILES))
        record = candidate['performance']['capture_synthetic_window']
        value = record['capture_diagnostics']
        text = phases.bounded_json(value)
        self.assertLess(len(text.encode('utf-8')), phases.MAX_DIAGNOSTIC_BYTES)
        self.assertEqual(json.loads(text), value)
        with self.assertRaises(ValueError):
            phases.bounded_json(dict(value, oversized='x' * phases.MAX_DIAGNOSTIC_BYTES))
        self.assertEqual(len(value['authoritative_observations']), 27)
        self.assertEqual(len(value['supplemental']['rows']), 6)
        for change in (
            lambda d: d['identity_after_supplemental']['loaded']['cv2_native'].update(sha256='0' * 64),
            lambda d: d['identity_before_supplemental']['sources'].pop('scripts/probe_capture_phases.py'),
            lambda d: d['identity_before_supplemental']['helpers']['session'].update(source_sha256='0' * 64),
            lambda d: d['authoritative_observations'][0].update(one_shot_helper_sha256='0' * 64),
            lambda d: d['authoritative_observations'].pop(),
            lambda d: d['supplemental']['rows'].pop(),
            lambda d: d['supplemental']['rows'][0].update(output={}),
            lambda d: d['supplemental']['rows'][3].update(capture_on_caller_thread=True),
            lambda d: d['supplemental']['rows'][3].update(qt_pumps=0),
            lambda d: d['supplemental']['rows'][0].update(outer_residual_seconds=99),
            lambda d: d['supplemental'].update(safe_to_close_fixture=False),
            lambda d: d.update(schema_version=True),
            lambda d: d['supplemental']['rows'][0].update(index=False),
            lambda d: d['supplemental']['rows'][0].update(helper_starts=True),
            lambda d: d['supplemental']['rows'][0].update(outer_residual_seconds=True),
            lambda d: d['identity_before_supplemental'].update(bound_one_shot=1),
            lambda d: d['identity_before_supplemental']['helpers']['one_shot'].update(protocol=True),
            lambda d: d.update(expected_client_rect=[20.0, 20, 960, 640]),
        ):
            damaged = copy.deepcopy(candidate)
            change(damaged['performance']['capture_synthetic_window']['capture_diagnostics'])
            self.assertTrue(probe.validate_report(damaged))

    def test_coherent_diagnostic_type_forgery_is_rejected(self):
        for field in ('geometry', 'bound', 'protocol', 'schema', 'count'):
            _, candidate = reports()
            value = candidate['performance']['capture_synthetic_window']['capture_diagnostics']
            if field == 'geometry':
                value['expected_client_rect'][0] = 20.0
                for row in value['supplemental']['rows']:
                    row['client_rect'][0] = 20.0
            elif field in {'bound', 'protocol'}:
                for key in ('identity_before_supplemental', 'identity_after_supplemental'):
                    if field == 'bound':
                        value[key]['bound_one_shot'] = 1
                    else:
                        value[key]['helpers']['one_shot']['protocol'] = True
            elif field == 'schema':
                value['schema_version'] = value['supplemental']['schema_version'] = True
            else:
                value['supplemental']['rows'][0]['index'] = False
                value['supplemental']['rows'][0]['helper_starts'] = True
            self.assertTrue(probe.validate_report(candidate), field)

    def test_supplemental_timings_never_replace_authoritative_samples(self):
        baseline, candidate = reports()
        set_timing(candidate, 'capture_synthetic_window', .2)
        rows = candidate['performance']['capture_synthetic_window']['capture_diagnostics']['supplemental']['rows']
        for row in rows:
            row['phase_seconds'] = {key: value / 1000 for key, value in row['phase_seconds'].items()}
            row['total_seconds'] /= 1000
            row['outer_residual_seconds'] = row['total_seconds'] - row['phase_seconds']['wgc_inclusive'] - row['phase_seconds']['png_encode']
        result = self.assert_fails(baseline, candidate, 'median regression')
        self.assertEqual(result['performance']['capture_synthetic_window']['candidate_samples_seconds'], [.2] * 7)

    def test_failed_generate_cli_keeps_capture_samples_and_prints_complete_record(self):
        report, _ = reports()
        report.update(status='failed', failures=['capture diagnostics failed'])
        record = report['performance']['capture_synthetic_window']
        record['capture_diagnostics']['status'] = 'failed'
        with tempfile.TemporaryDirectory() as folder, patch.object(probe, 'generate_report', return_value=report), patch('builtins.print') as output:
            target = Path(folder) / 'failed.json'
            status = probe.main(['generate', '--output', str(target)])
            saved = json.loads(target.read_text())
            self.assertEqual(status, 1)
            self.assertEqual(saved['performance']['capture_synthetic_window'], record)
            printed = json.loads(output.call_args_list[0].args[0])
            self.assertEqual(printed['capture_synthetic_window'], record)

    def test_standalone_unconfirmed_cleanup_saves_flushes_then_exits_nonzero(self):
        report, _ = reports()
        record = report['performance']['capture_synthetic_window']
        record['capture_diagnostics']['status'] = 'failed'
        record['capture_diagnostics']['supplemental']['safe_to_close_fixture'] = False
        with tempfile.TemporaryDirectory() as folder, patch.object(probe, 'generate_report', return_value=report), \
                patch.object(probe, '_RETAINED_CAPTURE_FIXTURES', [object()]), \
                patch('builtins.print') as output, patch.object(probe.sys.stdout, 'flush') as stdout_flush, \
                patch.object(probe.sys.stderr, 'flush') as stderr_flush:
            target = Path(folder) / 'retained.json'
            def terminate(code):
                self.assertEqual(code, 1)
                saved = json.loads(target.read_text())
                self.assertEqual(saved['status'], 'failed')
                self.assertEqual(saved['performance']['capture_synthetic_window'], record)
                self.assertTrue(any('unobserved' in item for item in saved['failures']))
                self.assertEqual(json.loads(output.call_args_list[0].args[0])['capture_synthetic_window'], record)
                self.assertTrue(all(call.kwargs.get('flush') is True for call in output.call_args_list))
                stdout_flush.assert_called_once()
                stderr_flush.assert_called_once()
            with patch.object(probe.os, '_exit', side_effect=terminate) as exit_process:
                self.assertEqual(probe.main(['generate', '--output', str(target)], standalone=True), 1)
                exit_process.assert_called_once_with(1)
            with patch.object(probe.os, '_exit') as exit_process:
                self.assertEqual(probe.main(['generate', '--output', str(target)]), 1)
                exit_process.assert_not_called()

    def test_standalone_retained_fixture_write_or_stdout_failure_still_exits(self):
        report, _ = reports()
        with tempfile.TemporaryDirectory() as folder, patch.object(probe, 'generate_report', return_value=report), \
                patch.object(probe, '_RETAINED_CAPTURE_FIXTURES', [object()]), \
                patch.object(probe, 'write_json', side_effect=OSError('private filesystem detail')), \
                patch.object(probe.sys.stdout, 'flush') as stdout_flush, \
                patch.object(probe.sys.stderr, 'flush') as stderr_flush, patch.object(probe.os, '_exit') as exit_process:
            with patch('builtins.print') as output:
                self.assertEqual(probe.main(['generate', '--output', str(Path(folder) / 'failed.json')], standalone=True), 1)
                record = json.loads(output.call_args_list[0].args[0])['capture_synthetic_window']
                self.assertEqual(len(record['samples_seconds']), 7)
                summary = json.loads(output.call_args_list[-1].args[0])
                self.assertIn('Report write failed: OSError', summary['failures'])
                self.assertNotIn('private filesystem', json.dumps(summary))
            exit_process.assert_called_once_with(1)
            stdout_flush.assert_called_once()
            stderr_flush.assert_called_once()
            exit_process.reset_mock()
            with patch('builtins.print', side_effect=BrokenPipeError('closed stdout')):
                with self.assertRaises(BrokenPipeError):
                    probe.main(['generate', '--output', str(Path(folder) / 'failed.json')], standalone=True)
            exit_process.assert_called_once_with(1)

    def test_icc_fixture_has_valid_declared_length_and_d50_header(self):
        self.assertEqual(int.from_bytes(probe.SRGB_ICC[:4], 'big'), len(probe.SRGB_ICC))
        self.assertEqual(probe.SRGB_ICC[36:40], b'acsp')
        self.assertEqual(probe.SRGB_ICC[68:80].hex(), '0000f6d6000100000000d32d')

    def test_bad_schema_and_nonfinite_limits_fail_closed(self):
        self.assert_fails({}, {}, 'invalid report schema')
        baseline, candidate = reports()
        for kwargs in ({'regression_ratio': float('inf')}, {'regression_ratio': 1},
                       {'noise_floor_seconds': -1}, {'noise_floor_seconds': float('nan')}):
            with self.assertRaises(ValueError):
                probe.compare_reports(baseline, candidate, **kwargs)

    def test_telemetry_disabled_before_any_ocr_import_or_construction(self):
        events = []
        runtime = Mock()
        runtime.disable_telemetry_events.side_effect = lambda: events.append('disable')
        local_ocr = Mock()
        local_ocr.LocalOCR.side_effect = lambda: events.append('construct') or 'engine'
        def import_module(name):
            self.assertEqual(probe.os.environ.get('ORT_DISABLE_TELEMETRY'), '1')
            events.append('import:' + name)
            return {'onnxruntime': runtime, 'local_ocr': local_ocr}[name]
        with patch.dict(probe.os.environ, {'ORT_DISABLE_TELEMETRY': '0'}), patch.object(
                probe.importlib, 'import_module', side_effect=import_module):
            engine, evidence = probe.create_ocr_engine()
        self.assertEqual(engine, 'engine')
        self.assertEqual(events, ['import:onnxruntime', 'disable', 'import:local_ocr', 'construct'])
        self.assertTrue(evidence['disabled_before_ocr_import_and_construction'])
        baseline, candidate = reports()
        candidate['onnxruntime_telemetry']['disabled_before_ocr_import_and_construction'] = False
        self.assert_fails(baseline, candidate, 'telemetry was not disabled')

    def test_cli_persists_machine_readable_failure_and_exit_status(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            baseline, candidate = reports()
            for filename, report in (('baseline.json', baseline), ('candidate.json', candidate)):
                (root / filename).write_text(json.dumps(report), encoding='utf-8')
            command = [sys.executable, str(ROOT / 'scripts/probe_opencv_parity.py'), 'compare',
                       str(root / 'baseline.json'), str(root / 'candidate.json'), '--output', str(root / 'out.json')]
            success = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(success.returncode, 0, success.stdout + success.stderr)
            self.assertEqual(json.loads((root / 'out.json').read_text())['status'], 'passed')
            set_timing(candidate, 'ocr_app_demo', 0.3)
            (root / 'candidate.json').write_text(json.dumps(candidate), encoding='utf-8')
            failed = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(failed.returncode, 1)
            self.assertEqual(json.loads((root / 'out.json').read_text())['status'], 'failed')


if __name__ == '__main__':
    unittest.main()

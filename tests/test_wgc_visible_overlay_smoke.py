"""Portable contract regressions only; never Windows exclusion evidence."""
import copy
from contextlib import redirect_stderr
import io
import json
from pathlib import Path
import re
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
import launcher
import wgc_visible_overlay_smoke as runtime
import windows_wgc_visible_overlay as harness


def native_diagnostic(code):
    return dict(schema_version=1,code=code,phase='validate-idle',
        check='display-affinity' if code==13 else 'overlay-generation',hresult=0,
        observed=[120,135,960,600],expected=[120,135,960,600],
        window_rect=[120,135,960,600],frame_rect=[120,135,960,600],
        style=2516582400,extended_style=134742184)


def fixture():
    helper={'sha256':'a'*64,'size':2048}
    value=dict(status='passed',schema_version=1,scope=runtime.SCOPE,limitations=dict(runtime.LIMITATIONS),
        applicationVersion=harness.__version__,frozen=False,qt_platform='windows',
        constructor='ControlWindow(enable_visible_capture=True)',executable_sha256=None,
        requested_app_scale=1,measured_qt_scale=1,helper=dict(manifest=helper,**helper),
        client_rect=dict(x=20,y=20,width=960,height=600),target_identity=[1,6,'OwnedWindow'],target_created=3,overlay_hwnd=4,control_hwnd=5,
        overlay_rendering=dict(qt_opacity=1,qt_translucent_background=False,qt_opaque_paint_event=True,
                               qt_surface_has_alpha=False,magenta_grid_samples=30),
        requests=[],transitions=[],pixel_pairs=[],negative_results={},fallback_calls=['v1'])
    names=('cold-hidden','hidden-confirmation','visible-product-1','visible-product-2',None,None,None,None)
    for index,name in enumerate(names):
        visible=index in (2,3,5,6,7);generation=0 if index<2 else 1 if index<4 else 2 if index==4 else 3
        identity=dict(helper_pid=10+generation,helper_created=20+generation,session_generation=30+generation)
        state=int(index in (4,6,7))
        start=100+index*100
        row=dict(identity,request_id=index+1,capture_start_100ns=start,request_cutoff_100ns=start+1,
            frame_100ns=start+2,idle_enter_100ns=start+3,capture_return_100ns=start+4,
            elapsed_ms=1,status='passed',backend='windows-graphics-capture-session',
            overlay_registration_valid=True,overlay_hwnd=4,overlay_affinity=17,overlay_extended_style=0x080800a8,
            parent_pid=6,overlay_owner_pid=6,visible_request=visible,
            paint_state=state,pixels_sha256=str(state)*64,
            native_visible_before=visible,native_visible_after=visible,overlay_window_style=123,enrolled_window_style=123,
            visibility=dict(samples=2,qt_hidden_samples=0 if visible else 2,native_hidden_samples=0 if visible else 2,
                duration_us=1000,samples_us=[[250,3 if visible else 0],[750,3 if visible else 0]],
                sample_format=runtime.SAMPLE_FORMAT,max_sample_gap_ms=.5),
            observation=dict(identity,helper_alive=True,overlay_registration_valid=True,overlay_opaque=True,
                overlay_hwnd=4,overlay_affinity=17,overlay_extended_style=0x080800a8,native_visible=visible))
        if name:row.update(case=name,product=dict(confirmed=index>0,automatic_frames=2,hide_events=0,show_events=0,overlay_visible=True))
        value['requests'].append(row)
    for index,(state,placement) in enumerate(((0,'titles'),(1,'hud'),(1,'titles'))):
        value['pixel_pairs'].append(dict(state=state,placement=placement,max_channel_error=0,changed_pixels=0,
            mean_channel_error=0,hidden_sha256=str(state)*64,visible_sha256=str(state)*64,
            hidden_magenta_pixels=0,visible_magenta_pixels=0,request_index=index+5,
            hidden_reference_index=1 if state==0 else 4,
            overlay_rect=[20,240 if placement=='titles' else 548,900,80]))
    injected={'owner_change','wrong_hwnd','cancel','stop','active_affinity_change'}
    for number,name in enumerate(runtime.NEGATIVES):
        start=1000+number*100
        rejected=dict(status='rejected',negative_case=name,visible_request=True,helper_pid=13,helper_created=23,
                      session_generation=33,capture_start_100ns=start,capture_return_100ns=start+20)
        row=dict(status='rejected',fallback_calls=0,helper_pid=13,helper_created=23,session_generation=33,
                 actual_native_idle_rejection=name not in injected,
                 native_exit_code=runtime.NATIVE_NEGATIVE_EXIT_CODES.get(name,12),
                 request_index=len(value['requests']),capture_start_100ns=start,capture_return_100ns=start+20,
                 mutation_100ns=start-1,request_id=None)
        if name not in injected:row['native_diagnostic']=native_diagnostic(row['native_exit_code'])
        rejected['mutation_100ns']=start-1
        if name in ('stop','cancel','active_affinity_change'):
            row.update(actual_pending_native_exchange=True,mutation_100ns=start+10,request_id=20+number)
            rejected.update(mutation_100ns=start+10,pending_exchange_request_id=20+number)
        if name=='stop':row.update(late_result_discarded=True,gui_restart_after_stop=False)
        if name=='foreign_pid_occluder':
            row.update(foreign_pid=88,foreign_hwnd=99,foreign_created=100,foreign_fixture_sha256='f'*64,
                       job_verified=True,mutation_100ns=None)
            rejected['mutation_100ns']=None
        value['requests'].append(rejected)
        value['negative_results'][name]=row
    value['transitions']=[dict(dict.fromkeys(('owner_revoked','transport_revoked','owner_close_done',
        'capture_call_done','process_exited','pipes_closed','pipe_worker_done','stderr_worker_done',
        'job_closed','ready_for_replacement','adapter_cleanup_complete'),True),
        helper_pid=10+i,helper_created=20+i,session_generation=30+i,observed_ms=1,process_exit_code=0)
        for i in range(4)]
    value.update(dict.fromkeys(('product_helper_reuse_passed','pixel_exclusion_passed','hidden_compatibility_passed',
        'helpers_exited_passed','pipe_readers_exited_passed','job_handles_closed_passed','windows_closed_passed'),True))
    foreign=dict(pid=88,hwnd=99,created=100,job_verified=True,executable_sha256='f'*64,
                 owner_pid=6,owner_created=3,launcher_pid=6,launcher_created=3,owner_ancestry_verified=True)
    return value,dict(scale=1,frozen=False,helper=helper,foreign_proof=foreign,foreign_fixture_sha256='f'*64)


class VisibleContracts(unittest.TestCase):
    def test_complete_synthetic_report_contract(self):
        value,kwargs=fixture();self.assertIs(harness.validate_report(value,**kwargs),value)

    def test_native_negative_codes_match_actual_native_guard_sources(self):
        source=(ROOT/'native/wgc_session_capture.cpp').read_text()
        declaration=re.search(r'constexpr int unsupported\s*=.*?;',source).group()
        codes={name:int(code) for name,code in re.findall(r'(\w+)\s*=\s*(\d+)',declaration)}
        self.assertEqual((codes['stale'],codes['protected_content']),(12,13))
        cases={
            'same_pid_occluder':('stale','occluder-overlap'),
            'foreign_pid_occluder':('stale','occluder-overlap'),
            'replaced_hwnd_token':('stale','overlay-generation'),
            'token_change':('stale','overlay-generation'),
            'extended_style_change':('stale','overlay-style'),
            'window_style_change':('stale','overlay-style'),
            'affinity_change':('stale','overlay-affinity'),
            'opacity_change':('stale','overlay-opacity'),
            'protected_target':('protected_content','display-affinity'),
            'focus_loss':('stale','foreground-root'),
            'geometry_loss':('stale','client-geometry'),
        }
        self.assertEqual(runtime.NATIVE_NEGATIVE_EXIT_CODES,
                         {name:codes[symbol] for name,(symbol,_) in cases.items()})
        self.assertEqual(set(runtime.NEGATIVES)-set(cases),
                         {'owner_change','wrong_hwnd','active_affinity_change','cancel','stop'})
        for symbol,check in set(cases.values()):
            if check=='occluder-overlap':
                self.assertIn('require(!order.blocked, stale, order.unreadable ? "occluder-query" : "occluder-overlap")',source)
            else:
                self.assertEqual(set(re.findall(r'(\w+),\s*"'+check+r'"\)',source)),{symbol})
        self.assertIn('if (GetWindowDisplayAffinity(p.hwnd, &affinity)) require(!affinity, protected_content, "display-affinity")',source)
        self.assertIn('if (!value) throw Failure{code, check};',source)
        self.assertIn('catch (Failure const& error) { report_failure(error.code, error.check); return error.code; }',source)

    def test_validator_requires_each_exact_native_code(self):
        for name,expected in runtime.NATIVE_NEGATIVE_EXIT_CODES.items():
            for code in (expected,13 if expected==12 else 12,0,14,None,True,float(expected),str(expected)):
                value,kwargs=fixture();value['negative_results'][name]['native_exit_code']=code
                with self.subTest(name=name,code=code):
                    if type(code) is int and code==expected:
                        self.assertIs(harness.validate_report(value,**kwargs),value)
                    else:
                        with self.assertRaises(RuntimeError):harness.validate_report(value,**kwargs)

    def native_negative_fixture(self,code):
        # Exercise the actual Python producer method without launching Windows.
        diagnostic=native_diagnostic(code)
        transport=SimpleNamespace(process=SimpleNamespace(returncode=code),
            revoked=SimpleNamespace(is_set=lambda:True),diagnostic=json.dumps(diagnostic).encode())
        owner=SimpleNamespace(session=SimpleNamespace(_transport=transport))
        binding=dict(helper_pid=13,helper_created=23,session_generation=33)
        f=runtime.ProductFixture.__new__(runtime.ProductFixture)
        f.records=[dict(binding,status='rejected',capture_start_100ns=101,capture_return_100ns=102)]
        f.result=dict(negative_results={},requests=f.records,transitions=[])
        f.fallback_calls=[];f.fresh_visible=Mock(return_value=owner)
        f.capture=SimpleNamespace(retire_session=Mock(),last_session_receipt=None)
        def cleanup(*args):
            row=dict(binding,process_exit_code=code);f.result['transitions'].append(row);return row
        f.cleanup_owner=cleanup
        f.wait=lambda predicate,seconds,message:self.assertTrue(predicate(),message)
        f.request_product=Mock(side_effect=RuntimeError('actual request rejected'))
        f.pump=Mock()
        return f,diagnostic

    def test_producer_persists_exact_rejection_before_native_code_assertion(self):
        for name,expected in runtime.NATIVE_NEGATIVE_EXIT_CODES.items():
            for code in (expected,13 if expected==12 else 12,0,True,float(expected),None):
                f,diagnostic=self.native_negative_fixture(code);restore=Mock()
                with self.subTest(name=name,code=code),patch('wgc_session_capture._qpc_100ns',return_value=100):
                    if type(code) is int and code==expected:
                        f.negative(name,Mock(),restore)
                    else:
                        with self.assertRaisesRegex(AssertionError,re.escape(f'{name}: expected {expected}, observed {code!r}')):
                            f.negative(name,Mock(),restore)
                    row=f.result['negative_results'][name]
                    self.assertEqual(row['native_exit_code'],code)
                    self.assertEqual(row['request_index'],0)
                    self.assertEqual((row['capture_start_100ns'],row['mutation_100ns']),(101,100))
                    self.assertEqual(row['helper_created'],23)
                    self.assertEqual(row['error_type'],'RuntimeError')
                    self.assertEqual(f.records[0]['negative_case'],name)
                    self.assertEqual(f.result['transitions'][0]['process_exit_code'],code)
                    self.assertEqual(row['native_diagnostic'],diagnostic if type(code) is int and code in (12,13) else None)
                    restore.assert_called_once_with();f.capture.retire_session.assert_called_once_with()

    def test_wrong_native_code_is_saved_in_failed_report(self):
        for name,code in (('protected_target',12),('token_change',13)):
            f,diagnostic=self.native_negative_fixture(code)
            def execute(result,path):
                result.update(f.result);f.result=result
                f.negative(name,Mock())
            with self.subTest(name=name),tempfile.TemporaryDirectory() as folder,\
                    patch.object(runtime,'execute',side_effect=execute),\
                    patch('wgc_session_capture._qpc_100ns',return_value=100):
                path=Path(folder)/'report.json'
                self.assertEqual(runtime.run(path),1)
                result=json.loads(path.read_text())
                self.assertEqual((result['status'],result['error_type']),('failed','AssertionError'))
                self.assertIn(f'expected {runtime.NATIVE_NEGATIVE_EXIT_CODES[name]}, observed {code}',result['error'])
                row=result['negative_results'][name]
                self.assertEqual((row['native_exit_code'],row['native_diagnostic']),(code,diagnostic))
                self.assertEqual(result['requests'][row['request_index']]['negative_case'],name)
                self.assertEqual(result['transitions'][0]['process_exit_code'],code)

    def test_foreign_producer_persists_observed_exit_before_assertion(self):
        for code in (12,13):
            f,_=self.native_negative_fixture(code)
            f.report_path=Path('unused.json');f.target=SimpleNamespace(hwnd=5);f.rect=SimpleNamespace(x=20,y=20,width=960,height=600)
            f.capture.info=lambda hwnd:SimpleNamespace(pid=88,hwnd=hwnd)
            f.capture.foreground=lambda target:True;f.u=SimpleNamespace(IsWindow=lambda hwnd:False)
            proof=dict(pid=88,hwnd=99,created=100,job_verified=True,executable_sha256='f'*64)
            with self.subTest(code=code),patch.object(runtime,'write_report') as write,\
                    patch.object(runtime,'poll_owned_json',return_value=proof),\
                    patch('session_windows.process_metadata',return_value=SimpleNamespace(created=100)):
                if code==12:runtime.foreign_negative(f)
                else:
                    with self.assertRaisesRegex(AssertionError,'foreign_pid_occluder: expected 12, observed 13'):
                        runtime.foreign_negative(f)
                row=f.result['negative_results']['foreign_pid_occluder']
                self.assertEqual(row['native_exit_code'],code)
                self.assertEqual(row['foreign_pid'],88)
                self.assertEqual(row['request_index'],0)
                self.assertEqual(f.records[0]['negative_case'],'foreign_pid_occluder')
                self.assertEqual(f.result['transitions'][0]['process_exit_code'],code)
                self.assertEqual(write.call_count,2 if code==12 else 1)

    def test_visibility_freshness_identity_pixels_lifecycle_mutations_rejected(self):
        mutations=(
            lambda v:v['requests'][2]['visibility'].update(qt_hidden_samples=1),
            lambda v:v['requests'][2]['visibility'].update(native_hidden_samples=1),
            lambda v:v['requests'][2]['product'].update(hide_events=1),
            lambda v:v['requests'][2].update(frame_100ns=v['requests'][2]['request_cutoff_100ns']),
            lambda v:v['requests'][2].update(enrolled_window_style=456),
            lambda v:v['requests'][2].update(overlay_owner_pid=7),
            lambda v:v['requests'][3].update(helper_created=999),
            lambda v:v['requests'][1]['product'].update(automatic_frames=1),
            lambda v:v['pixel_pairs'][0].update(max_channel_error=1),
            lambda v:v['pixel_pairs'][0].update(visible_magenta_pixels=1),
            lambda v:v['negative_results']['stop'].update(gui_restart_after_stop=True),
            lambda v:v['negative_results']['stop'].update(actual_pending_native_exchange=False),
            lambda v:v['negative_results']['active_affinity_change'].update(actual_pending_native_exchange=False),
            lambda v:v['negative_results']['foreign_pid_occluder'].update(actual_native_idle_rejection=False),
            lambda v:v['transitions'][0].update(job_closed=False),
            lambda v:v.update(fallback_calls=['v1','gdi']),
            lambda v:v['overlay_rendering'].update(magenta_grid_samples=0),
            lambda v:v['client_rect'].update(width=960.0),
            lambda v:v['requests'][2].update(enrolled_window_style=None,overlay_window_style=None),
            lambda v:v['requests'][2]['visibility'].update(samples=True),
            lambda v:v['requests'][2]['visibility'].update(samples_us=[[250,True,True],[99999,True,True]]),
            lambda v:v['requests'].insert(2,copy.deepcopy(v['requests'][1])),
            lambda v:v['pixel_pairs'][0].update(hidden_reference_index=4),
            lambda v:v['pixel_pairs'][0].update(changed_pixels=False),
            lambda v:v['pixel_pairs'][0].update(hidden_sha256='pretend',visible_sha256='pretend'),
            lambda v:v['negative_results']['stop'].update(helper_created=999),
            lambda v:v['transitions'].pop(),
            lambda v:v['negative_results']['stop'].update(request_index=0),
            lambda v:v['negative_results']['stop'].update(capture_return_100ns=1),
            lambda v:v['requests'][v['negative_results']['stop']['request_index']].update(mutation_100ns=1),
            lambda v:v['negative_results']['foreign_pid_occluder'].update(foreign_pid=True),
            lambda v:v['negative_results']['foreign_pid_occluder'].update(foreign_fixture_sha256='e'*64),
            lambda v:v['negative_results']['foreign_pid_occluder'].update(job_verified=False),
        )
        for mutate in mutations:
            value,kwargs=fixture();mutate(value)
            with self.subTest(mutate=mutate),self.assertRaises(RuntimeError):harness.validate_report(value,**kwargs)

    def test_pixels_are_exact_and_bright_contamination_is_counted(self):
        from PIL import Image
        from synthetic_vision import encoded
        before=Image.new('RGB',(20,20),(5,10,15));after=before.copy();after.putpixel((4,4),(255,0,255))
        exact=runtime.compare_pixels(encoded(before),encoded(before))
        self.assertEqual((exact['max_channel_error'],exact['changed_pixels']),(0,0))
        changed=runtime.compare_pixels(encoded(before),encoded(after))
        self.assertEqual(changed['changed_pixels'],1);self.assertEqual(changed['visible_magenta_pixels'],1)
        self.assertNotEqual(changed['hidden_sha256'],changed['visible_sha256'])

    def test_timestamp_native_bounds_not_relaxed(self):
        value,_=fixture();row=value['requests'][0]
        self.assertTrue(runtime.strict_timing(row))
        for field in ('request_cutoff_100ns','frame_100ns','idle_enter_100ns','capture_return_100ns'):
            changed=dict(row);changed[field]=0
            self.assertFalse(runtime.strict_timing(changed))
        changed=dict(row,request_id=True);self.assertFalse(runtime.strict_timing(changed))

    def test_explicit_launcher_only_and_normal_startup_untouched(self):
        with patch.object(runtime,'run',return_value=7) as run:
            self.assertEqual(launcher.main(['--wgc-visible-overlay-report','owned.json']),7)
            run.assert_called_once_with(Path('owned.json'))
        for extra in (['--demo'],['--version'],['--hwnd','1'],['--headless'],['--native-smoke-report','x'],
                      ['--wgc-session-smoke-report','x'],['--wgc-visible-overlay-report','y']):
            with redirect_stderr(io.StringIO()),self.assertRaises(SystemExit) as error:
                launcher.main(['--wgc-visible-overlay-report','owned.json',*extra])
            self.assertEqual(error.exception.code,2)

    def test_foreign_identity_requires_independent_outer_exact_proof(self):
        for key,value in (('pid',89),('hwnd',100),('created',101),('job_verified',False),
                          ('owner_ancestry_verified',False),('owner_pid',7),('owner_created',4),
                          ('launcher_pid',7),('executable_sha256','e'*64)):
            report,kwargs=fixture();kwargs['foreign_proof'][key]=value
            with self.subTest(key=key),self.assertRaises(RuntimeError):harness.validate_report(report,**kwargs)

    def test_handshake_reader_is_strict_and_shared_poller_reexported(self):
        import owned_diagnostic_json
        import windows_session_fixture
        self.assertIs(runtime.poll_owned_json,owned_diagnostic_json.poll_owned_json)
        self.assertIs(windows_session_fixture.poll_owned_json,owned_diagnostic_json.poll_owned_json)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'ready.json'
            self.assertIsNone(runtime.poll_owned_json(path,runtime.read_live_json))
            for data in ('{"a":1,"a":2}','{"a":NaN}', '{', ' '*8193):
                path.write_text(data)
                with self.assertRaises(ValueError):runtime.poll_owned_json(path,runtime.read_live_json)

    def test_bytecode_binding_ignores_only_build_path(self):
        a=compile('def f():\n return 17\n','source.py','exec')
        b=compile('def f():\n return 17\n','C:/build/source.py','exec')
        c=compile('def f():\n return 18\n','source.py','exec')
        self.assertEqual(harness.code_fingerprint(a),harness.code_fingerprint(b))
        self.assertNotEqual(harness.code_fingerprint(a),harness.code_fingerprint(c))

    def test_entire_product_pyz_compiles_without_inherited_future_flags(self):
        names=('wgc_visible_overlay_smoke','native_ui','native_smoke','screen_capture',
               'persistent_capture_adapter','wgc_session_capture','owned_diagnostic_json',
               'portrait_display','local_debug','selection_session')
        modules={name:compile((ROOT/(name+'.py')).read_bytes(),'C:/independent/'+name+'.py','exec',
                             dont_inherit=True,optimize=0) for name in names}
        archive=SimpleNamespace(toc={'PYZ.pyz':None},
            open_embedded_archive=lambda _:SimpleNamespace(extract=modules.__getitem__))
        self.assertEqual(set(harness.verify_product_modules(archive)),set(names))
        modules['native_smoke']=compile('changed = True','different.py','exec',dont_inherit=True)
        with self.assertRaises(RuntimeError):harness.verify_product_modules(archive)

    def test_lossless_full_three_scale_aggregate_stays_under_existing_cap(self):
        from test_wgc_session_build import manifest
        detail,kwargs=fixture();helper=manifest()
        detail['helper']=dict(manifest=helper,sha256=helper['sha256'],size=helper['size']);kwargs['helper']=helper
        # Complete producer shape: eight initial successful acquisitions, one
        # fresh owner + one rejected request for every negative, full cleanups,
        # real manifest shape, and 100 raw GUI samples per successful capture.
        initial=detail['requests'][:8];rejected=detail['requests'][8:];detail['requests']=initial
        template=copy.deepcopy(initial[-1])
        for index,(name,failure) in enumerate(zip(runtime.NEGATIVES,rejected)):
            success=copy.deepcopy(template);binding=dict(helper_pid=100+index,helper_created=200+index,session_generation=300+index)
            success.update(binding);success['observation'].update(binding);success['request_id']=1
            detail['requests'].append(success)
            failure.update(binding);negative=detail['negative_results'][name];negative.update(binding)
            negative['request_index']=len(detail['requests']);detail['requests'].append(failure)
            cleanup=copy.deepcopy(detail['transitions'][0]);cleanup.update(binding);detail['transitions'].append(cleanup)
        for row in detail['requests']:
            if row['status']=='passed':
                visible=row['visible_request'];row['elapsed_ms']=101
                row['visibility']=dict(samples=100,qt_hidden_samples=0 if visible else 100,
                    native_hidden_samples=0 if visible else 100,duration_us=101000,
                    samples_us=[[1000*i,3 if visible else 0] for i in range(1,101)],
                    sample_format=runtime.SAMPLE_FORMAT,max_sample_gap_ms=1)
        aggregate=dict(status='passed',helper_build=helper,source_files={name:'a'*64 for name in runtime.SOURCE_FILES},runs=[])
        for scale in runtime.SCALES:
            current=copy.deepcopy(detail);current.update(requested_app_scale=scale,measured_qt_scale=scale)
            harness.validate_report(current,**dict(kwargs,scale=scale))
            aggregate['runs'].append(dict(scale=scale,detail=current,foreign=kwargs['foreign_proof']))
        compact=runtime.report_payload(aggregate)
        self.assertEqual(json.loads(compact),aggregate)
        self.assertLessEqual(len(compact.encode()),runtime.MAX_REPORT_BYTES)
        self.assertGreater(len(json.dumps(aggregate,indent=2).encode()),runtime.MAX_REPORT_BYTES)
        rendered=harness.rendered_report(compact)
        self.assertEqual(json.loads(rendered),aggregate)
        self.assertLessEqual(max(map(len,rendered.splitlines())),1024)

    def test_non_windows_diagnostic_fails_with_truthful_report(self):
        if sys.platform=='win32':self.skipTest('Portable rejection test')
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'report.json'
            self.assertEqual(runtime.run(path),1)
            result=json.loads(path.read_text())
            self.assertEqual(result['status'],'failed');self.assertNotIn('pixel_exclusion_passed',result)


if __name__=='__main__':unittest.main()

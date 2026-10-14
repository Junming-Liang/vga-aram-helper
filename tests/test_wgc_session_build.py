"""Portable contract checks only. They do NOT execute or certify Windows WGC."""
from __future__ import annotations
import copy
import hashlib
import io
from contextlib import redirect_stdout
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
from scripts import build_wgc_session_capture as build
import windows_wgc_session_capture as smoke
import wgc_session_diagnostic as launcher


def manifest():
    tool={'signature_status':'Valid','signer_subject':'CN=Microsoft, O=Microsoft Corporation, C=US',
          'sha256':'e'*64,'size':2048}
    inputs={name:{'sha256':'e'*64,'size':1024}for name in build.SOURCE_FILES}
    inputs['native/wgc_session_capture.cpp']['sha256']='b'*64
    inputs['scripts/build_wgc_session_capture.py']['sha256']='c'*64
    return {'schema_version':1,'protocol':2,'filename':build.FILENAME,'profile':build.PROFILE,
        'status':'passed','size':2048,'sha256':'a'*64,'source_sha256':'b'*64,'build_recipe_sha256':'c'*64,
        'source_commit':'d'*40,'source_files':inputs,'sdk_version':build.SDK_VERSION,
        'compile_flags':list(build.COMPILE_FLAGS),'link_flags':list(build.LINK_FLAGS),'libraries':list(build.LIBRARIES),
        'machine':'x64','crt':'static-release-/MT','dependencies':['d3d11.dll','kernel32.dll'],
        'sdk_headers':{name:{'sha256':'e'*64,'size':2048}for name in build.SDK_HEADERS},
        'toolchain':{'product_id':build.microsoft_runtime.PRODUCT_ID,'compiler':dict(tool),'linker':dict(tool)}}


def passing_report(scale=1,frozen=True):
    proof=manifest();roi=[round(80*scale),round(60*scale),round(160*scale),round(120*scale)]
    result={'schema_version':1,'status':'passed','applicationVersion':smoke.__version__,'frozen':frozen,
        'scope':smoke.SCOPE,'limitations':dict(smoke.LIMITATIONS),'qt_platform':'windows',
        'requested_app_scale':scale,'measured_qt_scale':scale,
        'helper':{'manifest':proof,'sha256':proof['sha256'],'size':proof['size']},
        'client_rect':{'x':20,'y':20,'width':round(320*scale),'height':round(240*scale)},'roi':roi,
        'requests':[],'transitions':[],'negative_results':{},'helper_process_count':30,
        'parent_death_observation':{'wait_result':0,'elapsed_ms':20,'owner_pid':123,'owner_created':499,'helper_pid':124,
            'helper_created':500,'exact_handle_observed':True,'helper_sha256':proof['sha256'],
            'owner_ancestry_verified':True,'helper_ancestry_verified':True,'popen_pid':122 if frozen else 123,
            'popen_created':498 if frozen else 499,
            'scope':'parent-death-eventual-cleanup'},
        'suspended_job_close_observation':{'wait_result':0,'elapsed_ms':12,'helper_pid':789,'exit_code':1,
            'job_closed':True,'never_resumed':True,'start_gate_released':False}}
    result.update(dict.fromkeys(smoke.CHECK_FIELDS,True))
    for number in range(4):
        result['requests'].append({'helper_pid':123,'helper_created':456,'session_generation':789,
            'request_id':number+1,'request_cutoff_100ns':number*100+10,'frame_100ns':number*100+20,
            'idle_enter_100ns':number*100+30,'roi':list(roi),'mean_channel_error':0.,'elapsed_ms':50.})
    result['static_requests']=copy.deepcopy(result['requests'][:3])
    for name in smoke.TRANSITIONS:
        elapsed=4025 if name=='idle_lease_passed' else 25
        result['transitions'].append({'case':name,'helper_pid':123,'exit_code':0 if name in
            ('native_stop_passed','pipe_eof_passed')else 12,'revoked_ms':elapsed,'process_exit_ms':elapsed,
            'cleanup_ms':elapsed+1,'observed_exit_within_50ms':elapsed<=50,'job_closed':True,
            'io_done':True,'stderr_done':True,'threads_exited':True,'pipes_closed':True,**({'close_call_ms':1}if name=='stop'else {})})
    for name in smoke.NEGATIVES:
        status='cancelled' if name.startswith('cancel_')else 'timeout' if name=='request_deadline_passed'else 'stale'
        result['negative_results'][name]={'status':status,'elapsed_ms':25}
    return result


class BuildTests(unittest.TestCase):
    def test_pinned_separate_build_contract(self):
        build.validate_manifest(manifest())
        self.assertEqual(build.PROFILE,'hwnd-wgc-session-v2');self.assertEqual(build.PROTOCOL,2)
        self.assertEqual(build.SDK_VERSION,'10.0.26100.0');self.assertIn('/MT',build.COMPILE_FLAGS)
        self.assertEqual(build.FILENAME,'vga-wgc-session-capture.exe')
        source=(ROOT/'scripts/build_wgc_session_capture.py').read_text()
        self.assertNotIn('urlopen(',source);self.assertNotIn('pip install',source)
        self.assertNotIn("ROOT / 'packaging' / 'VGA-Aram-Helper.spec'",source)
        self.assertEqual(len(set(build.SOURCE_FILES)),len(build.SOURCE_FILES))
        for path in build.SOURCE_FILES:self.assertTrue((ROOT/path).is_file(),path)

    def test_manifest_rejects_identity_and_source_provenance_gaps(self):
        edits={'schema_version':True,'protocol':1,'filename':'vga-wgc-capture.exe','profile':'hwnd-wgc-v1',
            'status':'skipped','size':0,'sha256':'A'*64,'source_sha256':'x','build_recipe_sha256':None,
            'source_commit':'short','source_files':{},'sdk_version':'latest','compile_flags':['/MD'],
            'link_flags':[],'libraries':['external.lib'],'machine':'x86','crt':'dynamic',
            'dependencies':['vcruntime140.dll'],'toolchain':{},'sdk_headers':{}}
        for key,value in edits.items():
            with self.subTest(key=key),self.assertRaises((RuntimeError,TypeError)):
                build.validate_manifest(dict(manifest(),**{key:value}))
        for edit in (lambda v:v['source_files']['wgc_session_smoke.py'].update(size=True),
                     lambda v:v['source_files']['native/wgc_session_capture.cpp'].update(sha256='f'*64),
                     lambda v:v['toolchain']['compiler'].update(signature_status='NotSigned'),
                     lambda v:v.update(error='invalid even when passed')):
            value=manifest();edit(value)
            with self.assertRaises(RuntimeError):build.validate_manifest(value)

    def test_every_fixture_source_and_helper_byte_is_bound(self):
        with tempfile.TemporaryDirectory()as temporary:
            root=Path(temporary);folder=root/'build/native';folder.mkdir(parents=True)
            value=manifest()
            for name in build.SOURCE_FILES:
                path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('fixture '+name)
            value['source_files']={name:build.record(root/name)for name in build.SOURCE_FILES}
            value['source_sha256']=value['source_files']['native/wgc_session_capture.cpp']['sha256']
            value['build_recipe_sha256']=value['source_files']['scripts/build_wgc_session_capture.py']['sha256']
            helper=folder/build.FILENAME;helper.write_bytes(b'MZ'+b'x'*2046);value.update(build.record(helper))
            (folder/build.MANIFEST).write_text(json.dumps(value))
            self.assertEqual(build.verify_built_helper(folder,root=root),value)
            for name in build.SOURCE_FILES:
                path=root/name;old=path.read_bytes();path.write_bytes(old+b'changed')
                with self.subTest(name=name),self.assertRaises(RuntimeError):build.verify_built_helper(folder,root=root)
                path.write_bytes(old)
            helper.write_bytes(b'MZ'+b'z'*2046)
            with self.assertRaises(RuntimeError):build.verify_built_helper(folder,root=root)

    def test_archive_verifies_exact_helper_and_manifest(self):
        proof=manifest();binary=b'MZ'+b'x'*2046;proof['sha256']=hashlib.sha256(binary).hexdigest()
        entries={'native/'+build.FILENAME:binary,'native/'+build.MANIFEST:json.dumps(proof).encode()}
        class Archive:
            toc=entries
            def extract(self,name):return entries[name]
        self.assertEqual(build.verify_archive(Archive(),proof),proof)
        entries['native/'+build.FILENAME]=binary+b'x'
        with self.assertRaises(RuntimeError):build.verify_archive(Archive(),proof)
        entries['native/'+build.FILENAME]=binary
        entries['native/'+build.MANIFEST]=json.dumps(dict(proof,source_commit='f'*40)).encode()
        with self.assertRaises(RuntimeError):build.verify_archive(Archive(),proof)
        del entries['native/'+build.MANIFEST]
        with self.assertRaises(RuntimeError):build.verify_archive(Archive(),proof)

    def test_build_requires_windows_never_installs(self):
        with patch.object(build.sys,'platform','linux'):
            for function in (build.build,build.freeze_diagnostic):
                with self.assertRaisesRegex(RuntimeError,'native Windows x64'):function()

    def test_production_surface_stays_default_off(self):
        for name in ('launcher.py','packaging/VGA-Aram-Helper.spec','scripts/build_windows.py'):
            self.assertNotIn('wgc_session',(ROOT/name).read_text(),name)
        spec=(ROOT/'packaging/WGC-Session-Diagnostic.spec').read_text()
        self.assertIn('wgc_session_diagnostic.py',spec)
        self.assertNotIn('launcher.py',spec)


class OverlaySetupDiagnosticTests(unittest.TestCase):
    def fixture(self,*,hidden_failure=False,always_failure=False,readback=0x11,dwm_enabled=True):
        import wgc_session_smoke as runtime
        from types import SimpleNamespace
        state=SimpleNamespace(error=0,visible=False,affinity=0,style=0x080800a8,owner=71,hwnd=123,
                              set_calls=[],hidden_failure=hidden_failure,always_failure=always_failure,
                              readback=readback,dwm_enabled=dwm_enabled,hide_drops_affinity=False)
        class User:
            def IsWindow(self,hwnd):return hwnd==state.hwnd
            def GetAncestor(self,hwnd,kind):return state.hwnd
            def GetWindowThreadProcessId(self,hwnd,out):out._obj.value=state.owner;return 91
            def GetWindowLongPtrW(self,hwnd,index):return state.style if index==-20 else 0x80000000
            def IsWindowVisible(self,hwnd):return state.visible
            def SetWindowDisplayAffinity(self,hwnd,affinity):
                state.set_calls.append((hwnd,affinity,state.visible))
                if state.always_failure or state.hidden_failure and not state.visible:
                    state.error=87;return False
                state.affinity=state.readback;return True
            def GetWindowDisplayAffinity(self,hwnd,out):
                out._obj.value=state.affinity
                # Deliberately change last-error so set's WinError must already
                # have been preserved, even when this read succeeds.
                state.error=1400
                return True
        class Dwm:
            def DwmIsCompositionEnabled(self,out):out._obj.value=state.dwm_enabled;return 0
        class Widget:
            def winId(self):return state.hwnd
            def show(self):state.visible=True
            def update(self):pass
            def hide(self):
                state.visible=False
                if state.hide_drops_affinity:state.affinity=0
        return runtime,state,User(),Dwm(),Widget()

    def run_setup(self,runtime,state,user,dwm,widget,result):
        with patch.object(runtime.ctypes,'set_last_error',lambda value:setattr(state,'error',value),create=True), \
             patch.object(runtime.ctypes,'get_last_error',lambda:state.error,create=True):
            runtime.prepare_owned_overlay(widget,user,dwm,123,0x080800a8,71,lambda _:None,result,
                                          label='registered-overlay')

    def test_bounded_hidden_then_realized_retry_keeps_exact_affinity_and_error(self):
        runtime,state,user,dwm,widget=self.fixture(hidden_failure=True);result={}
        self.run_setup(runtime,state,user,dwm,widget,result)
        rows=result['overlay_setup']
        self.assertEqual([row['stage']for row in rows],['created-hidden','realized-visible','verified-hidden'])
        self.assertEqual(state.set_calls,[(123,0x11,False),(123,0x11,True)])
        self.assertEqual(rows[0]['set_winerror'],87)
        self.assertEqual(rows[0]['affinity_winerror'],1400)
        self.assertFalse(rows[0]['set_ok']);self.assertTrue(rows[1]['set_ok'])
        self.assertEqual(rows[2]['affinity'],0x11);self.assertFalse(state.visible)
        self.assertTrue(all(row['owner_is_self']and row['top_level']and row['dwm_composing']for row in rows))
        self.assertLess(len(json.dumps(result)),4096)
        self.assertFalse(any(word in json.dumps(result)for word in ('window_title','pixel_data','image_path')))

    def test_realized_failure_dwm_off_and_nonexact_readback_never_pass(self):
        for options in ({'always_failure':True},{'readback':1},{'readback':0},{'dwm_enabled':False}):
            runtime,state,user,dwm,widget=self.fixture(**options);result={}
            with self.subTest(options=options),self.assertRaises(AssertionError):
                self.run_setup(runtime,state,user,dwm,widget,result)
            self.assertFalse(state.visible)
            self.assertEqual(len(result['overlay_setup']),3)
            self.assertTrue(all(row[1]==0x11 for row in state.set_calls))

    def test_hidden_affinity_loss_fails_and_foreign_owner_is_never_modified(self):
        runtime,state,user,dwm,widget=self.fixture();state.hide_drops_affinity=True;result={}
        with self.assertRaisesRegex(AssertionError,'retain exact exclusion'):
            self.run_setup(runtime,state,user,dwm,widget,result)
        runtime,state,user,dwm,widget=self.fixture();state.owner=999;result={}
        with self.assertRaisesRegex(AssertionError,'identity/styles'):
            self.run_setup(runtime,state,user,dwm,widget,result)
        self.assertEqual(state.set_calls,[])
        self.assertFalse(result['overlay_setup'][0]['owner_is_self'])

    def test_show_cannot_replace_window_or_weaken_exact_styles(self):
        for changed in ('hwnd','style'):
            runtime,state,user,dwm,widget=self.fixture();result={}
            original=widget.show
            def show():
                original();setattr(state,changed,getattr(state,changed)+1)
            widget.show=show
            with self.subTest(changed=changed),self.assertRaisesRegex(AssertionError,'identity/styles'):
                self.run_setup(runtime,state,user,dwm,widget,result)
            self.assertFalse(state.visible)
            if changed=='hwnd':self.assertEqual(len(state.set_calls),1)


class AcceptanceTests(unittest.TestCase):
    def test_validates_source_frozen_and_three_scales(self):
        for scale in smoke.SCALES:
            for frozen in (True,False):
                smoke.validate_report(passing_report(scale,frozen),frozen=frozen,scale=scale,helper_build=manifest())

    def test_requires_every_check_and_honest_limitations(self):
        for name in smoke.CHECK_FIELDS:
            value=passing_report();value[name]=False
            with self.subTest(name=name),self.assertRaises(RuntimeError):
                smoke.validate_report(value,frozen=True,scale=1,helper_build=manifest())
        for key,new in (('status','skipped'),('qt_platform','offscreen'),('scope','production ready'),
                        ('limitations',{}),('frozen',False),('requested_app_scale',True),('measured_qt_scale',float('nan')),
                        ('requests',[]),('static_requests',[]),('negative_results',{}),('transitions',[]),('parent_death_observation',{})):
            value=passing_report();value[key]=new
            with self.subTest(key=key),self.assertRaises(RuntimeError):
                smoke.validate_report(value,frozen=True,scale=1,helper_build=manifest())
        for field in ('idle_cpu_readback_runtime_proven','teardown_50ms_guaranteed','production_enabled'):
            value=passing_report();value['limitations'][field]=True
            with self.assertRaises(RuntimeError):smoke.validate_report(value,frozen=True,scale=1,helper_build=manifest())

    def test_exact_helper_and_fresh_frame_order(self):
        for key,new in (('helper_pid',999),('helper_created',999),('session_generation',999),('request_id',1),
                        ('request_cutoff_100ns',20),('frame_100ns',1),('idle_enter_100ns',1),
                        ('mean_channel_error',2.01),('mean_channel_error',float('nan')),('roi',[0,0,160,120])):
            value=passing_report();value['requests'][1][key]=new
            with self.subTest(key=key),self.assertRaises(RuntimeError):
                smoke.validate_report(value,frozen=True,scale=1,helper_build=manifest())
        value=passing_report();value['helper']['sha256']='f'*64
        with self.assertRaises(RuntimeError):smoke.validate_report(value,frozen=True,scale=1,helper_build=manifest())

    def test_every_roi_is_a_list_of_four_strict_integers(self):
        self.assertFalse(smoke.strict_roi([True,0,16,16],[1,0,16,16]))
        for target in ('top','requests','static_requests'):
            for position in range(4):
                for transform in (float,lambda _:True,lambda _:False,str):
                    value=passing_report()
                    row=value if target=='top'else value[target][0]
                    row['roi'][position]=transform(row['roi'][position])
                    with self.subTest(target=target,position=position,transform=transform),self.assertRaises(RuntimeError):
                        smoke.validate_report(value,frozen=True,scale=1,helper_build=manifest())
            for transform in (tuple,lambda row:row[:3],lambda row:row+[0]):
                value=passing_report();row=value if target=='top'else value[target][0]
                row['roi']=transform(row['roi'])
                with self.subTest(target=target,shape=transform),self.assertRaises(RuntimeError):
                    smoke.validate_report(value,frozen=True,scale=1,helper_build=manifest())

    def test_static_window_cannot_reuse_frames_replace_helper_or_hide_timeout(self):
        for key,new in (('helper_pid',999),('request_id',1),('request_cutoff_100ns',20),('frame_100ns',1)):
            value=passing_report();value['static_requests'][1][key]=new
            with self.subTest(key=key),self.assertRaises(RuntimeError):
                smoke.validate_report(value,frozen=True,scale=1,helper_build=manifest())
        value=passing_report();value['static_frame_failure']={'status':'timeout'}
        with self.assertRaises(RuntimeError):smoke.validate_report(value,frozen=True,scale=1,helper_build=manifest())

    def test_cleanup_is_observation_not_50ms_promise(self):
        value=passing_report();row=value['transitions'][0]
        row.update(revoked_ms=100,process_exit_ms=120,cleanup_ms=150,observed_exit_within_50ms=False)
        smoke.validate_report(value,frozen=True,scale=1,helper_build=manifest())
        for key,new in (('pipes_closed',False),('threads_exited',False),('job_closed',False),('exit_code',None),
                        ('process_exit_ms',float('nan')),('cleanup_ms',1),('observed_exit_within_50ms',True)):
            broken=copy.deepcopy(value);broken['transitions'][0][key]=new
            with self.subTest(key=key),self.assertRaises(RuntimeError):
                smoke.validate_report(broken,frozen=True,scale=1,helper_build=manifest())
        value=passing_report();value['transitions'].append(dict(value['transitions'][0]))
        with self.assertRaises(RuntimeError):smoke.validate_report(value,frozen=True,scale=1,helper_build=manifest())

    def test_parent_death_requires_exact_handle_and_signaled_exit(self):
        for key,new in (('wait_result',258),('wait_result',False),('elapsed_ms',3501),('exact_handle_observed',False),
                        ('helper_created',0),('helper_sha256','f'*64),('owner_ancestry_verified',False),('helper_ancestry_verified',False)):
            value=passing_report();value['parent_death_observation'][key]=new
            with self.subTest(key=key),self.assertRaises(RuntimeError):
                smoke.validate_report(value,frozen=True,scale=1,helper_build=manifest())

    def test_parent_relations_are_checked_independently_of_true_flags(self):
        for frozen,edit in (
            (False,{'popen_pid':122}),
            (False,{'popen_created':498}),
            (True,{'popen_pid':123}),
            (True,{'popen_created':500}),
            (True,{'helper_pid':123}),
            (True,{'helper_pid':122}),
            (True,{'helper_created':498}),
            (False,{'helper_pid':123}),
            (False,{'helper_created':498})):
            value=passing_report(frozen=frozen);value['parent_death_observation'].update(edit)
            with self.subTest(frozen=frozen,edit=edit),self.assertRaises(RuntimeError):
                smoke.validate_report(value,frozen=frozen,scale=1,helper_build=manifest())
        # Equality is allowed for OS creation-time granularity; strict causal
        # ordering means nondecreasing timestamps, never a fabricated epsilon.
        value=passing_report();value['parent_death_observation'].update(popen_created=499,helper_created=499)
        smoke.validate_report(value,frozen=True,scale=1,helper_build=manifest())

    def test_summary_requires_all_six_runs_and_exact_unchanged_helper(self):
        with tempfile.TemporaryDirectory()as temporary:
            root=Path(temporary);proof=manifest()
            executable={'source_commit':proof['source_commit'],'filename':'WGC-Session-Diagnostic.exe',
                'sha256':'9'*64,'size':12345,'helper':proof,'test_only':True,'production_enabled':False}
            values={'windows-wgc-session-build.json':proof,
                    'windows-wgc-session-frozen-build.json':dict(proof,diagnostic=executable)}
            for frozen in (False,True):
                value={'status':'passed','frozen':frozen,'scope':smoke.SCOPE,'limitations':dict(smoke.LIMITATIONS),
                    'scales':list(smoke.SCALES),'source_commit':proof['source_commit'],'helper_build':proof,
                    'source_files':{name:row['sha256']for name,row in proof['source_files'].items()},
                    'runs':[{'app_scale':scale,'detail':passing_report(scale,frozen)}for scale in smoke.SCALES]}
                if frozen:value.update(executable_sha256=executable['sha256'],executable_size=executable['size'])
                values['windows-wgc-session-'+('frozen'if frozen else 'source')+'.json']=value
            for name,value in values.items():(root/name).write_text(json.dumps(value))
            with redirect_stdout(io.StringIO()):self.assertEqual(smoke.summarize(root),0)
            summary=json.loads((root/'windows-wgc-session-summary.json').read_text())
            self.assertEqual(summary['status'],'passed');self.assertEqual(len(summary['runs']),6)
            values['windows-wgc-session-frozen.json']['executable_sha256']='8'*64
            (root/'windows-wgc-session-frozen.json').write_text(json.dumps(values['windows-wgc-session-frozen.json']))
            with redirect_stdout(io.StringIO()):self.assertEqual(smoke.summarize(root),1)
            summary=json.loads((root/'windows-wgc-session-summary.json').read_text())
            self.assertIn('Frozen acceptance executable differs from the standalone build',summary['errors'])
            (root/'windows-wgc-session-source.json').unlink()
            with redirect_stdout(io.StringIO()):self.assertEqual(smoke.summarize(root),1)

    def test_summary_records_malformed_missing_stages_without_false_success(self):
        with tempfile.TemporaryDirectory()as temporary:
            root=Path(temporary)
            (root/'windows-wgc-session-build.json').write_text('{"status":"passed","source_files":[]}')
            (root/'windows-wgc-session-frozen-build.json').write_text('{"status":"passed","diagnostic":[]}')
            (root/'windows-wgc-session-source.json').write_text('{"runs":[[],{"detail":[]}]}')
            with redirect_stdout(io.StringIO()):self.assertEqual(smoke.summarize(root),1)
            report=json.loads((root/'windows-wgc-session-summary.json').read_text())
            self.assertEqual(report['status'],'failed');self.assertGreater(len(report['errors']),3)
            for text in ('{"status":"passed","status":"failed"}','{"nan":NaN}'):
                path=root/'bad.json';path.write_text(text)
                with self.assertRaises(ValueError):smoke.read_report(path)

    def test_frozen_environment_has_no_python_compiler_or_foreign_qt(self):
        env=smoke.child_environment({'SystemRoot':r'C:\Windows','PATH':r'C:\Python;C:\VC',
            'PYTHONPATH':'foreign','QT_PLUGIN_PATH':'foreign','QT_QPA_PLATFORM':'offscreen'},Path('work'),1.5,frozen=True)
        self.assertEqual(env['PATH'],r'C:\Windows\System32;C:\Windows')
        self.assertNotIn('PYTHONPATH',env);self.assertNotIn('QT_PLUGIN_PATH',env)
        self.assertEqual(env['QT_QPA_PLATFORM'],'windows');self.assertEqual(env['QT_SCALE_FACTOR'],'1.5')

    def test_explicit_standalone_launcher_rejects_target_input_and_mode_combination(self):
        for argv in ([],['--hwnd','123'],['--report','r.json','--job-owner-report','c.json'],
                     ['--report','r.json','--headless']):
            with self.subTest(argv=argv),self.assertRaises(SystemExit):launcher.main(argv)
        with patch('wgc_session_smoke.run',return_value=0)as run:
            self.assertEqual(launcher.main(['--report','r.json']),0);run.assert_called_once_with(Path('r.json'))

    def test_linux_diagnostic_is_failure_not_skipped_pass(self):
        import wgc_session_smoke
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory()as temporary:
            path=Path(temporary)/'report.json'
            # Replace only this module's platform observation. Mutating the
            # shared os.name also changes pathlib's host path implementation.
            with patch.object(wgc_session_smoke,'os',SimpleNamespace(name='posix')):
                self.assertEqual(wgc_session_smoke.run(path),1)
            value=json.loads(path.read_text())
            self.assertEqual(value['status'],'failed');self.assertNotIn('owned_pixels_passed',value)
            self.assertIn('Actual Windows x64 desktop is mandatory',value['error'])


if __name__=='__main__':unittest.main()

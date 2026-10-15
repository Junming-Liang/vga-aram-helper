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
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
from scripts import build_wgc_session_capture as build
import windows_wgc_session_capture as smoke
import wgc_session_diagnostic as launcher
from test_microsoft_runtime import runtime_fixture


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


def overlay_report():
    """Synthetic portable report data; never represents Windows execution."""
    import wgc_session_smoke as runtime
    rendering={'active_profile':runtime.OPAQUE_PROFILE,'selection':'preselected-before-probe',
               'production_translucent_compatibility_proven':False}
    rows=[]
    for role,name in (('translucent-probe','translucent_probe'),('registered-overlay','registered_overlay'),
                      ('lookalike-occluder','lookalike_occluder')):
        probe=role=='translucent-probe';profile=runtime.TRANSLUCENT_PROFILE if probe else runtime.OPAQUE_PROFILE
        qt={'qt_translucent_background':probe,'qt_opaque_paint_event':not probe,'qt_surface_has_alpha':probe,
            'qt_surface_alpha_buffer_size':8 if probe else -1,'qt_opacity':1.0}
        rendering[name]={'profile':profile,**qt}
        if probe:rendering[name].update(exclusion_available=False,destroyed_before_registration=True)
        for index,stage in enumerate(('created-hidden','realized-visible','verified-hidden')):
            rows.append({'role':role,'profile':profile,'stage':stage,**qt,
                'is_window':True,'top_level':True,'visible':index==1,'owner_query_ok':True,
                'owner_is_self':True,'owner_winerror':0,'style':0x80000000|(0x10000000 if index==1 else 0),
                'extended_style':0x080800a8,'expected_extended_style':0x080800a8,
                'dwm_hresult':0,'dwm_composing':True,'set_attempted':index<2,'set_ok':not probe and index<2,
                'set_winerror':8 if probe and index<2 else 0,'affinity_query_ok':True,
                'affinity_winerror':0,'affinity':0 if probe else 0x11,'hwnd_unchanged':True,
                'layered_attributes_query_ok':not probe,'layered_attributes_winerror':87 if probe else 0,
                'layered_color_key':0,'layered_alpha':0 if probe else 255,'layered_flags':0 if probe else 2})
    return {'overlay_rendering':rendering,'overlay_setup':rows}


def shutdown_stress_report(scale=1):
    rows=[]
    for index in range(smoke.SHUTDOWN_STRESS_PAIRS*2):
        rows.append([index//2+1,('stop','eof')[index%2],1000+index,134364808860193529+index,
            2973183492968784245+index,1,4561453775+index*1000,4561453800+index*1000,
            4561453900+index*1000,0.,50.,0,True,False,25.,26.,31])
    return {'schema_version':1,'pairs':smoke.SHUTDOWN_STRESS_PAIRS,
        'deadline_ms':smoke.SHUTDOWN_STRESS_SECONDS*1000,'columns':list(smoke.SHUTDOWN_STRESS_COLUMNS),
        'cleanup_bit_fields':list(smoke.SHUTDOWN_CLEANUP_FIELDS),
        'roi':[round(80*scale),round(60*scale),round(160*scale),round(120*scale)],
        'rows':rows,'elapsed_ms':5000.}


def passing_report(scale=1,frozen=True,application=False):
    proof=manifest();roi=[round(80*scale),round(60*scale),round(160*scale),round(120*scale)]
    result={'schema_version':1,'status':'passed','applicationVersion':smoke.__version__,'frozen':frozen,
        **smoke.diagnostic_contract(application),'qt_platform':'windows',
        'requested_app_scale':scale,'measured_qt_scale':scale,
        'windows_version':{'major':10,'minor':0,'build':20348},
        'helper':{'manifest':proof,'sha256':proof['sha256'],'size':proof['size']},
        'client_rect':{'x':20,'y':20,'width':round(320*scale),'height':round(240*scale)},'roi':roi,
        'requests':[],'transitions':[],'negative_results':{},'helper_process_count':30,
        'parent_death_observation':{'wait_result':0,'elapsed_ms':20,'owner_pid':123,'owner_created':499,'helper_pid':124,
            'helper_created':500,'exact_handle_observed':True,'helper_sha256':proof['sha256'],
            'owner_ancestry_verified':True,'helper_ancestry_verified':True,'popen_pid':122 if frozen else 123,
            'popen_created':498 if frozen else 499,
            'scope':'parent-death-eventual-cleanup',
            'diagnostic_entrypoint':'application' if application else 'standalone'},
        'suspended_job_close_observation':{'wait_result':0,'elapsed_ms':12,'helper_pid':789,'exit_code':1,
            'job_closed':True,'never_resumed':True,'start_gate_released':False}}
    result.update(overlay_report())
    result['shutdown_stress']=shutdown_stress_report(scale)
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
        if name in ('native_stop_passed','pipe_eof_passed'):
            result['transitions'][-1].update(native_checkpoints_complete=True,parent_termination_requested=False)
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

    def test_standalone_surface_stays_separate_from_application(self):
        spec=(ROOT/'packaging/WGC-Session-Diagnostic.spec').read_text()
        self.assertIn('wgc_session_diagnostic.py',spec)
        self.assertNotIn('launcher.py',spec)
        for name in ('launcher.py','packaging/VGA-Aram-Helper.spec','native_ui.py',
                     'automatic_windows.py','selection_session.py','persistent_capture_adapter.py','scripts/windows_package.py'):
            self.assertIn(name,build.SOURCE_FILES)


class DiagnosticRuntimePackagingTests(unittest.TestCase):
    """Execute the spec with synthetic Analysis output, never native packaging.

    The real source/archive verifiers inspect synthetic bytes and provenance.
    These checks establish the recipe contract, not a Windows EXE or WGC pass.
    """
    DLLS={'msvcp140.dll','msvcp140_1.dll','msvcp140_2.dll',
          'vcruntime140.dll','vcruntime140_1.dll'}
    REQUIRED={'pyside6/'+name for name in DLLS}|{
        'msvcp140.dll','vcruntime140.dll','vcruntime140_1.dll'}

    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.addCleanup(self.temporary.cleanup)
        self.folder=Path(self.temporary.name)
        self.proof=runtime_fixture()
        for row in self.proof['files']:
            # Different synthetic bytes per DLL catch cross-file substitution.
            data=(row['filename'].encode()*2048)[:2048]
            (self.folder/row['filename']).write_bytes(data)
            row.update(size=len(data),sha256=hashlib.sha256(data).hexdigest())
        self.write_proof()
        self.analysis=Mock(side_effect=self.analyze);self.exe=Mock();self.discovered=[]

    def write_proof(self):
        (self.folder/'provenance.json').write_text(json.dumps(self.proof),encoding='utf-8')

    def analyze(self,*_args,**kwargs):
        entries=[((Path(destination)/Path(source).name).as_posix(),source,'BINARY')
                 for source,destination in kwargs['binaries']]
        return SimpleNamespace(binaries=entries+self.discovered,datas=kwargs['datas'],pure=[],scripts=[])

    def execute_spec(self,discovered=()):
        self.discovered=list(discovered)
        path=ROOT/'packaging/WGC-Session-Diagnostic.spec'
        namespace={'SPECPATH':str(path.parent),'Analysis':self.analysis,'PYZ':Mock(),'EXE':self.exe}
        with patch.object(build,'verify_built_helper')as verify_helper, \
             patch.object(build.microsoft_runtime,'RUNTIME_ROOT',self.folder), \
             patch.object(sys,'path',list(sys.path)):
            exec(compile(path.read_text(),str(path),'exec'),namespace)
        verify_helper.assert_called_once_with()
        return self.exe.call_args.args[2]

    def archive(self,entries):
        # Synthetic CArchive interface only; no DLL execution or PyInstaller.
        contents={name:Path(source).read_bytes()for name,source,_kind in entries
                  if name.replace('\\','/').rsplit('/',1)[-1].casefold()in self.DLLS}
        return SimpleNamespace(toc=contents,extract=contents.__getitem__)

    def test_explicit_exact_licensed_inventory_without_analysis_discovery(self):
        self.assertEqual(build.microsoft_runtime.RUNTIME_DLLS,self.DLLS)
        entries=self.execute_spec()
        requested=self.analysis.call_args.kwargs['binaries']
        self.assertEqual(requested,[(str(ROOT/'build/native'/build.FILENAME),'native')]+
            [(str(self.folder/name),'PySide6')for name in sorted(self.DLLS)]+
            [(str(self.folder/name),'.')for name in
             ('msvcp140.dll','vcruntime140.dll','vcruntime140_1.dll')])
        bundle=build.microsoft_runtime.verify_embedded_runtime(self.archive(entries),self.proof)
        self.assertEqual({row['path']for row in bundle['embedded_files']},self.REQUIRED)
        self.assertEqual(len(bundle['embedded_files']),8)
        self.assertEqual(entries[0],('native/'+build.FILENAME,
                                    str(ROOT/'build/native'/build.FILENAME),'BINARY'))

    def test_every_discovered_copy_replaced_and_other_binaries_preserved(self):
        discovered=[('MSVCP140.dll','unlicensed/root.dll','BINARY'),
                    (r'PySide6\VCRUNTIME140.dll','unlicensed/wheel.dll','BINARY'),
                    ('shiboken6/msvcp140_2.dll','unlicensed/other.dll','BINARY'),
                    ('PySide6/Qt6Core.dll','retained/Qt6Core.dll','BINARY')]
        entries=self.execute_spec(discovered)
        for name,source,kind in entries:
            basename=name.replace('\\','/').rsplit('/',1)[-1].casefold()
            if basename in self.DLLS:
                self.assertEqual(source,str(self.folder/basename));self.assertEqual(kind,'BINARY')
        self.assertIn(discovered[-1],entries)
        for name,_source,kind in discovered[:-1]:
            basename=name.replace('\\','/').rsplit('/',1)[-1].casefold()
            self.assertIn((name,str(self.folder/basename),kind),entries)
        build.microsoft_runtime.verify_embedded_runtime(self.archive(entries),self.proof)

    def test_missing_changed_or_unsigned_runtime_fails_before_analysis(self):
        path=self.folder/'msvcp140.dll';original=path.read_bytes()
        for failure in ('missing','changed','unsigned'):
            with self.subTest(failure=failure):
                if failure=='missing':path.unlink()
                elif failure=='changed':path.write_bytes(b'!'+original[1:])
                else:
                    self.proof['files'][0]['signature_status']='NotSigned';self.write_proof()
                with self.assertRaises(RuntimeError):self.execute_spec()
                self.analysis.assert_not_called();self.exe.assert_not_called()
                path.write_bytes(original)

    def test_unknown_or_debug_discovered_crt_is_rejected_before_exe(self):
        for name in ('msvcp140d.dll','vcruntime140d.dll','concrt140.dll','other/msvcp140_3.dll'):
            with self.subTest(name=name),self.assertRaisesRegex(RuntimeError,'Unexpected or debug'):
                self.execute_spec([(name,'unreviewed/source.dll','BINARY')])
            self.exe.assert_not_called()

    def test_every_required_archive_path_and_exact_byte_remain_mandatory(self):
        archive=self.archive(self.execute_spec())
        for name in list(archive.toc):
            data=archive.toc.pop(name)
            with self.subTest(missing=name),self.assertRaisesRegex(RuntimeError,'paths are missing'):
                build.microsoft_runtime.verify_embedded_runtime(archive,self.proof)
            archive.toc[name]=b'!'+data[1:]
            with self.subTest(changed=name),self.assertRaisesRegex(RuntimeError,'differ from licensed source'):
                build.microsoft_runtime.verify_embedded_runtime(archive,self.proof)
            archive.toc[name]=data


class OverlaySetupDiagnosticTests(unittest.TestCase):
    def fixture(self,*,hidden_failure=False,always_failure=False,readback=0x11,dwm_enabled=True):
        import wgc_session_smoke as runtime
        from types import SimpleNamespace
        state=SimpleNamespace(error=0,visible=False,affinity=0,style=0x080800a8,owner=71,hwnd=123,
                              set_calls=[],hidden_failure=hidden_failure,always_failure=always_failure,
                              readback=readback,dwm_enabled=dwm_enabled,hide_drops_affinity=False,
                              qt={'qt_translucent_background':False,'qt_opaque_paint_event':True,
                                  'qt_surface_has_alpha':False,'qt_surface_alpha_buffer_size':-1,'qt_opacity':1.0},
                              layered_ok=True,layered_alpha=255,layered_flags=2,layered_color=0)
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
            def GetLayeredWindowAttributes(self,hwnd,color,alpha,flags):
                color._obj.value=state.layered_color;alpha._obj.value=state.layered_alpha;flags._obj.value=state.layered_flags
                state.error=0 if state.layered_ok else 87
                return state.layered_ok
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

    def run_setup(self,runtime,state,user,dwm,widget,result,*,label='registered-overlay'):
        with patch.object(runtime.ctypes,'set_last_error',lambda value:setattr(state,'error',value),create=True), \
             patch.object(runtime.ctypes,'get_last_error',lambda:state.error,create=True), \
             patch.object(runtime,'qt_overlay_observation',lambda _:dict(state.qt)):
            return runtime.prepare_owned_overlay(widget,user,dwm,123,0x080800a8,71,lambda _:None,result,
                                          label=label)

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
        self.assertLess(len(json.dumps(result)),8192)
        self.assertFalse(any(word in json.dumps(result)for word in ('window_title','pixel_data','image_path')))

    def test_realized_failure_dwm_off_and_nonexact_readback_never_pass(self):
        for options in ({'always_failure':True},{'readback':1},{'readback':0},{'dwm_enabled':False}):
            runtime,state,user,dwm,widget=self.fixture(**options);result={}
            with self.subTest(options=options),self.assertRaises(AssertionError):
                self.run_setup(runtime,state,user,dwm,widget,result)
            self.assertFalse(state.visible)
            self.assertEqual(len(result['overlay_setup']),1 if options.get('dwm_enabled')is False else 3)
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


    def test_translucent_affinity_failure_is_separate_from_active_proof(self):
        runtime,state,user,dwm,widget=self.fixture(always_failure=True);result={}
        state.qt.update(qt_translucent_background=True,qt_opaque_paint_event=False,
                        qt_surface_has_alpha=True,qt_surface_alpha_buffer_size=8)
        state.layered_ok=False;state.layered_alpha=state.layered_flags=0
        summary=self.run_setup(runtime,state,user,dwm,widget,result,label='translucent-probe')
        self.assertFalse(summary['exclusion_available'])
        self.assertEqual(summary['profile'],runtime.TRANSLUCENT_PROFILE)
        self.assertEqual([row['set_winerror']for row in result['overlay_setup']],[87,87,0])
        self.assertEqual([row['layered_attributes_winerror']for row in result['overlay_setup']],[87]*3)
        self.assertNotIn('registered_overlay',result)
        self.assertFalse(state.visible)
        # The very same failed exclusion remains fatal for the active profile.
        state.qt.update(qt_translucent_background=False,qt_opaque_paint_event=True,
                        qt_surface_has_alpha=False,qt_surface_alpha_buffer_size=0)
        state.layered_ok=True;state.layered_alpha=255;state.layered_flags=2
        with self.assertRaisesRegex(AssertionError,'exact exclusion unavailable'):
            self.run_setup(runtime,state,user,dwm,widget,{},label='registered-overlay')

    def test_probe_exception_never_waives_identity_dwm_or_actual_translucency(self):
        for change,value in (('owner',999),('dwm_enabled',False),('hwnd',999)):
            runtime,state,user,dwm,widget=self.fixture(always_failure=True);result={}
            state.qt.update(qt_translucent_background=True,qt_opaque_paint_event=False,
                            qt_surface_has_alpha=True,qt_surface_alpha_buffer_size=8)
            setattr(state,change,value)
            with self.subTest(change=change),self.assertRaises(AssertionError):
                self.run_setup(runtime,state,user,dwm,widget,result,label='translucent-probe')
            self.assertEqual(state.set_calls,[])
        runtime,state,user,dwm,widget=self.fixture(always_failure=True)
        state.qt.update(qt_translucent_background=True,qt_opaque_paint_event=False)
        with self.assertRaisesRegex(AssertionError,'rendering profile'):
            self.run_setup(runtime,state,user,dwm,widget,{},label='translucent-probe')

    def test_active_rejects_alpha_opacity_missing_paint_flag_and_layered_mismatch(self):
        for qt in ({'qt_translucent_background':True},{'qt_opaque_paint_event':False},
                   {'qt_surface_has_alpha':True,'qt_surface_alpha_buffer_size':8},
                   {'qt_surface_alpha_buffer_size':1},{'qt_opacity':.9}):
            runtime,state,user,dwm,widget=self.fixture();state.qt.update(qt)
            with self.subTest(qt=qt),self.assertRaisesRegex(AssertionError,'rendering profile'):
                self.run_setup(runtime,state,user,dwm,widget,{})
            self.assertEqual(state.set_calls,[])
        for field,value in (('layered_ok',False),('layered_alpha',254),('layered_flags',3),('layered_color',1)):
            runtime,state,user,dwm,widget=self.fixture();setattr(state,field,value)
            with self.subTest(field=field),self.assertRaisesRegex(AssertionError,'rendering profile'):
                self.run_setup(runtime,state,user,dwm,widget,{})

    def test_unknown_role_and_duplicate_role_cannot_bypass_profile(self):
        runtime,state,user,dwm,widget=self.fixture();result={}
        with self.assertRaisesRegex(AssertionError,'Unknown'):
            self.run_setup(runtime,state,user,dwm,widget,result,label='fallback')
        self.run_setup(runtime,state,user,dwm,widget,result)
        with self.assertRaisesRegex(AssertionError,'role repeated'):
            self.run_setup(runtime,state,user,dwm,widget,result)

    def test_alpha_change_after_realization_is_fatal_and_hidden(self):
        runtime,state,user,dwm,widget=self.fixture();result={}
        original=widget.show
        def show():
            original();state.qt.update(qt_surface_has_alpha=True,qt_surface_alpha_buffer_size=8)
        widget.show=show
        with self.assertRaisesRegex(AssertionError,'rendering profile'):
            self.run_setup(runtime,state,user,dwm,widget,result)
        self.assertFalse(state.visible)
        self.assertEqual(len(state.set_calls),1)


    def test_factory_uses_separate_actual_alpha_profiles_and_never_sla_on_probe(self):
        import wgc_session_smoke as runtime
        from types import SimpleNamespace
        qt=SimpleNamespace(Tool=1,FramelessWindowHint=2,WindowStaysOnTopHint=4,
            WindowDoesNotAcceptFocus=8,WindowTransparentForInput=16,
            WA_ShowWithoutActivating=1,WA_TranslucentBackground=2,WA_OpaquePaintEvent=3)
        state=SimpleNamespace(style=0x80,error=0,sla=[],fail=False)
        class Widget:
            def __init__(self,parent,flags):self.attributes={};self.flags=flags;self.css='';self.opacity=1.0
            def setAttribute(self,key,value=True):self.attributes[key]=value
            def testAttribute(self,key):return self.attributes.get(key,False)
            def setWindowOpacity(self,value):self.opacity=value
            def windowOpacity(self):return self.opacity
            def setStyleSheet(self,value):self.css=value
            def resize(self,*args):pass
            def move(self,*args):pass
            def winId(self):return 123
            def windowHandle(self):
                alpha=self.testAttribute(qt.WA_TranslucentBackground)
                return SimpleNamespace(format=lambda:SimpleNamespace(hasAlpha=lambda:alpha,
                    alphaBufferSize=lambda:8 if alpha else -1))
        class User:
            def IsWindow(self,hwnd):return hwnd==123
            def GetAncestor(self,hwnd,kind):return hwnd
            def GetWindowThreadProcessId(self,hwnd,out):out._obj.value=runtime.os.getpid();return 91
            def GetWindowLongPtrW(self,hwnd,index):return state.style
            def SetWindowLongPtrW(self,hwnd,index,value):state.style=value;return 0x80
            def SetWindowPos(self,*args):return True
            def SetLayeredWindowAttributes(self,hwnd,color,alpha,flags):
                state.sla.append((hwnd,color,alpha,flags));state.error=8 if state.fail else 0
                return not state.fail
        f=runtime.Fixture.__new__(runtime.Fixture)
        f.QtCore=SimpleNamespace(Qt=qt);f.QtWidgets=SimpleNamespace(QWidget=Widget);f.QtGui=object()
        f.windows=[];f.u=User();f.session=SimpleNamespace(REQUIRED_OVERLAY_STYLE=0x080800a8)
        with patch.dict(sys.modules,{'PySide6':SimpleNamespace(QtCore=f.QtCore)}), \
             patch.object(runtime.ctypes,'set_last_error',lambda v:setattr(state,'error',v),create=True), \
             patch.object(runtime.ctypes,'get_last_error',lambda:state.error,create=True):
            probe,_,_=f.new_overlay(runtime.TRANSLUCENT_PROFILE)
            self.assertEqual(state.sla,[])
            self.assertTrue(runtime.qt_overlay_observation(probe)['qt_surface_has_alpha'])
            self.assertIn('rgba',probe.css)
            active,_,_=f.new_overlay(runtime.OPAQUE_PROFILE)
            actual=runtime.qt_overlay_observation(active)
            self.assertFalse(actual['qt_translucent_background']);self.assertFalse(actual['qt_surface_has_alpha'])
            self.assertTrue(actual['qt_opaque_paint_event']);self.assertEqual(actual['qt_opacity'],1.0)
            self.assertEqual(active.css,'');self.assertIn('paintEvent',type(active).__dict__)
            self.assertIsNot(probe,active);self.assertEqual(state.sla,[(123,0,255,2)])
            state.fail=True
            with self.assertRaisesRegex(AssertionError,'WinError=8'):
                f.new_overlay(runtime.OPAQUE_PROFILE)

    def test_fixed_opaque_selection_destroys_probe_first_regardless_of_its_outcome(self):
        import wgc_session_smoke as runtime
        from types import SimpleNamespace
        for available in (False,True):
            events=[];live=set()
            f=runtime.Fixture.__new__(runtime.Fixture)
            f.sessions=[];f.windows=[];f.app=SimpleNamespace(processEvents=lambda:events.append('pump'))
            f.u=SimpleNamespace(IsWindow=lambda hwnd:hwnd in live);f.dwm=object();f.pump=lambda _:None
            f.new_target=lambda:object()
            class Widget:
                def __init__(self,profile):self.profile=profile;self.hwnd=100+len(events);live.add(self.hwnd)
                def close(self):events.append('close:'+self.profile)
                def destroy(self):events.append('destroy:'+self.profile);live.remove(self.hwnd)
                def hide(self):pass
            def new_overlay(profile):
                if profile==runtime.OPAQUE_PROFILE:
                    self.assertFalse(live,'Original probe must be destroyed before opaque construction')
                events.append('create:'+profile);widget=Widget(profile);f.windows.append(widget)
                return widget,widget.hwnd,0x080800a8
            def prepare(widget,*args,label):
                events.append('prepare:'+label)
                return {'profile':widget.profile,**({'exclusion_available':available}if label=='translucent-probe'else {})}
            def stop_after_setup(_):raise StopIteration('end controlled setup')
            f.new_overlay=new_overlay;f.focus=stop_after_setup
            result={}
            with patch.object(runtime,'prepare_owned_overlay',prepare),self.assertRaises(StopIteration):
                f.initialize_windows(result)
            self.assertEqual([event for event in events if event.startswith('create:')],
                             ['create:'+runtime.TRANSLUCENT_PROFILE,'create:'+runtime.OPAQUE_PROFILE])
            summary=result['overlay_rendering']
            self.assertEqual(summary['active_profile'],runtime.OPAQUE_PROFILE)
            self.assertTrue(summary['translucent_probe']['destroyed_before_registration'])
            self.assertIs(summary['translucent_probe']['exclusion_available'],available)
            self.assertEqual(len(f.windows),1)
            self.assertEqual(f.windows[0].profile,runtime.OPAQUE_PROFILE)

    def test_surviving_probe_stops_before_active_profile_or_any_session(self):
        import wgc_session_smoke as runtime
        from types import SimpleNamespace
        f=runtime.Fixture.__new__(runtime.Fixture)
        f.sessions=[];f.windows=[];f.app=SimpleNamespace(processEvents=lambda:None)
        f.u=SimpleNamespace(IsWindow=lambda hwnd:True);f.dwm=object();f.pump=lambda _:None
        f.new_target=lambda:object();calls=[]
        widget=SimpleNamespace(close=lambda:None,destroy=lambda:None)
        def new_overlay(profile):calls.append(profile);f.windows.append(widget);return widget,123,0x080800a8
        f.new_overlay=new_overlay
        with patch.object(runtime,'prepare_owned_overlay',return_value={'exclusion_available':False}), \
             self.assertRaisesRegex(AssertionError,'probe survived'):
            result={};f.initialize_windows(result)
        self.assertEqual(calls,[runtime.TRANSLUCENT_PROFILE])
        self.assertFalse(result['overlay_rendering']['translucent_probe']['destroyed_before_registration'])
        self.assertFalse(f.sessions)


class OverlayRenderingAcceptanceTests(unittest.TestCase):
    def test_failed_probe_is_honest_and_cannot_supply_active_exclusion(self):
        value=overlay_report();smoke.validate_overlay_rendering(value)
        value['overlay_rendering']['translucent_probe']['exclusion_available']=True
        with self.assertRaises(RuntimeError):smoke.validate_overlay_rendering(value)
        value=overlay_report();value['overlay_setup'][4]['affinity']=0
        with self.assertRaises(RuntimeError):smoke.validate_overlay_rendering(value)
        value=overlay_report()
        for row in value['overlay_setup'][:3]:
            row.update(set_ok=row['set_attempted'],set_winerror=0,affinity=0x11)
        value['overlay_rendering']['translucent_probe']['exclusion_available']=True
        smoke.validate_overlay_rendering(value)
        self.assertEqual(value['overlay_rendering']['active_profile'],'qt-opaque-redirected-v1')
        self.assertFalse(value['overlay_rendering']['production_translucent_compatibility_proven'])

    def test_required_schema_and_profile_boundaries(self):
        for field,new in (('active_profile','qt-translucent-comparison-v1'),('selection','fallback-after-failure'),
                          ('production_translucent_compatibility_proven',True)):
            value=overlay_report();value['overlay_rendering'][field]=new
            with self.subTest(field=field),self.assertRaises(RuntimeError):smoke.validate_overlay_rendering(value)
        for name in ('translucent_probe','registered_overlay','lookalike_occluder'):
            value=overlay_report();value['overlay_rendering'][name]['profile']='unknown'
            with self.subTest(name=name),self.assertRaises(RuntimeError):smoke.validate_overlay_rendering(value)
        value=overlay_report();value['overlay_rendering']['translucent_probe']['destroyed_before_registration']=False
        with self.assertRaises(RuntimeError):smoke.validate_overlay_rendering(value)
        for field in ('overlay_setup','overlay_rendering'):
            value=overlay_report();value.pop(field)
            with self.subTest(field=field),self.assertRaises(RuntimeError):smoke.validate_overlay_rendering(value)
        value=overlay_report();value['overlay_setup']=value['overlay_setup'][3:]
        with self.assertRaises(RuntimeError):smoke.validate_overlay_rendering(value)

    def test_every_stage_rejects_wrong_identity_native_styles_and_invalid_types(self):
        edits={'owner_is_self':False,'owner_query_ok':False,'is_window':False,'top_level':False,
               'hwnd_unchanged':False,'dwm_composing':False,'dwm_hresult':0x80070008,
               'style':True,'extended_style':float(0x080800a8),'layered_alpha':True,
               'layered_flags':2.0,'expected_extended_style':0,'affinity':True,
               'qt_surface_has_alpha':1,'qt_surface_alpha_buffer_size':True,'qt_opacity':True}
        for index in range(9):
            for field,new in edits.items():
                value=overlay_report();value['overlay_setup'][index][field]=new
                with self.subTest(index=index,field=field),self.assertRaises(RuntimeError):
                    smoke.validate_overlay_rendering(value)
        for mask in (0x20,0x8,0x80,0x80000,0x8000000):
            value=overlay_report()
            for row in value['overlay_setup'][3:6]:
                row['extended_style']&=~mask;row['expected_extended_style']&=~mask
            with self.subTest(mask=mask),self.assertRaises(RuntimeError):smoke.validate_overlay_rendering(value)
        for base in (0,0xc0000000,0x80c00000,0x80040000):
            value=overlay_report()
            for row in value['overlay_setup'][3:6]:
                row['style']=base|(0x10000000 if row['stage']=='realized-visible'else 0)
            with self.subTest(base=base),self.assertRaises(RuntimeError):smoke.validate_overlay_rendering(value)
        value=overlay_report()
        for row in value['overlay_setup'][3:6]:
            row['extended_style']|=0x200000;row['expected_extended_style']|=0x200000
        with self.assertRaises(RuntimeError):smoke.validate_overlay_rendering(value)

    def test_active_no_alpha_opaque_layered_and_exact_affinity_are_mandatory(self):
        edits={'qt_translucent_background':True,'qt_opaque_paint_event':False,'qt_surface_has_alpha':True,
               'qt_surface_alpha_buffer_size':8,'qt_opacity':.99,'layered_attributes_query_ok':False,
               'layered_alpha':254,'layered_flags':3,'layered_color_key':1}
        for index in range(3,9):
            for field,new in edits.items():
                value=overlay_report();value['overlay_setup'][index][field]=new
                with self.subTest(index=index,field=field),self.assertRaises(RuntimeError):
                    smoke.validate_overlay_rendering(value)
        for index in (4,5,7,8):
            for field,new in (('affinity',0),('affinity',1),('affinity_query_ok',False)):
                value=overlay_report();value['overlay_setup'][index][field]=new
                with self.subTest(index=index,field=field,new=new),self.assertRaises(RuntimeError):
                    smoke.validate_overlay_rendering(value)
        value=overlay_report();value['overlay_setup'][4]['set_ok']=False
        with self.assertRaises(RuntimeError):smoke.validate_overlay_rendering(value)

    def test_valid_but_changed_hidden_probe_alpha_size_is_rejected(self):
        value=overlay_report();value['overlay_setup'][2]['qt_surface_alpha_buffer_size']=16
        with self.assertRaisesRegex(RuntimeError,'changed between realized and hidden'):
            smoke.validate_overlay_rendering(value)

    def test_summary_and_stage_order_cannot_be_swapped_or_omitted(self):
        for field in tuple(overlay_report()['overlay_setup'][0]):
            value=overlay_report();value['overlay_setup'][0].pop(field)
            with self.subTest(field=field),self.assertRaises(RuntimeError):smoke.validate_overlay_rendering(value)
        value=overlay_report();value['overlay_setup'][0],value['overlay_setup'][3]=value['overlay_setup'][3],value['overlay_setup'][0]
        with self.assertRaises(RuntimeError):smoke.validate_overlay_rendering(value)
        value=overlay_report();value['overlay_rendering']['registered_overlay']['qt_opacity']=.5
        with self.assertRaises(RuntimeError):smoke.validate_overlay_rendering(value)


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

    def test_shutdown_record_is_strict_and_bound_to_actual_nonzero_exit(self):
        record={'schema_version':1,'exit_code':12,'checkpoints':[1,2,3,4,5,6],
                'last_started_stage':'apartment-uninit'}
        value=passing_report();value['transitions'][0]['shutdown_diagnostic']=record
        smoke.validate_report(value,frozen=True,scale=1,helper_build=manifest())
        mutations=[None,dict(record,exit_code=14),dict(record,exit_code=True),
            dict(record,schema_version=True),dict(record,checkpoints=[True]),
            dict(record,checkpoints=[1,2,2]),dict(record,checkpoints=[2]),
            dict(record,checkpoints=[1.,2,3,4,5,6]),dict(record,last_started_stage='process-return'),
            dict(record,address='forbidden'),dict(record,checkpoints=list(range(1,9)))]
        for bad in mutations:
            value=passing_report();value['transitions'][0]['shutdown_diagnostic']=bad
            with self.subTest(bad=bad),self.assertRaisesRegex(RuntimeError,'shutdown diagnostic'):
                smoke.validate_report(value,frozen=True,scale=1,helper_build=manifest())
        for case in ('native_stop_passed','pipe_eof_passed'):
            value=passing_report();row=next(x for x in value['transitions']if x['case']==case)
            row['exit_code']=0xc0000005
            row['shutdown_diagnostic']=dict(record,exit_code=0xc0000005)
            with self.subTest(case=case),self.assertRaisesRegex(RuntimeError,'graceful shutdown'):
                smoke.validate_report(value,frozen=True,scale=1,helper_build=manifest())
            row['exit_code']=0
            with self.subTest(case=case,forged_zero=True),self.assertRaisesRegex(RuntimeError,'shutdown diagnostic'):
                smoke.validate_report(value,frozen=True,scale=1,helper_build=manifest())

    def test_graceful_shutdown_requires_complete_native_trace_and_no_parent_attempt(self):
        for case in ('native_stop_passed','pipe_eof_passed'):
            for field,bad in (('native_checkpoints_complete',False),('native_checkpoints_complete',1),
                ('parent_termination_requested',True),('parent_termination_requested',None),
                ('parent_termination_requested',0)):
                value=passing_report();row=next(x for x in value['transitions']if x['case']==case)
                row[field]=bad
                with self.subTest(case=case,field=field,bad=bad),self.assertRaisesRegex(RuntimeError,'graceful shutdown'):
                    smoke.validate_report(value,frozen=True,scale=1,helper_build=manifest())

    def test_shutdown_stress_requires_exact_complete_rows_fresh_helpers_and_types(self):
        value=shutdown_stress_report();smoke.validate_shutdown_stress(value,value['roi'])
        # Reused numerical PID with a later creation is a different process.
        reused=copy.deepcopy(value);reused['rows'][1][2]=reused['rows'][0][2]
        smoke.validate_shutdown_stress(reused,reused['roi'])
        edits=[lambda x:x.update(pairs=True),lambda x:x.update(pairs=4),
            lambda x:x.update(columns=list(reversed(x['columns']))),lambda x:x.update(rows=x['rows'][:-1]),
            lambda x:x.update(cleanup_bit_fields=list(reversed(x['cleanup_bit_fields']))),
            lambda x:x.update(elapsed_ms=45000),lambda x:x.update(deadline_ms=45001),
            lambda x:x.update(failure_diagnostic={}),lambda x:x['roi'].__setitem__(0,float(x['roi'][0])),
            lambda x:x['rows'][1].__setitem__(slice(2,4),x['rows'][0][2:4])]
        for position,bad in ((0,True),(1,'eof'),(2,True),(3,0),(4,True),(5,2),(6,0),(7,1),(8,1),
            (9,1),(9,False),(10,float('inf')),(10,.1234),(11,0xc0000005),(11,False),(12,False),(12,1),
            (13,True),(13,None),(13,0),(14,-1),(15,1),(16,30),(16,31.)):
            edits.append(lambda x,p=position,b=bad:x['rows'][0].__setitem__(p,b))
        for edit in edits:
            broken=copy.deepcopy(value);edit(broken)
            with self.subTest(broken=broken),self.assertRaises(RuntimeError):
                smoke.validate_shutdown_stress(broken,value['roi'])
        forged=copy.deepcopy(value)
        for row in forged['rows']:row[10]=3000.;row[15]=3000.
        forged['elapsed_ms']=6000.
        with self.assertRaisesRegex(RuntimeError,'elapsed total'):
            smoke.validate_shutdown_stress(forged,forged['roi'])
        rounded=copy.deepcopy(value)
        total=sum(row[10]+row[15] for row in rounded['rows'])
        rounding=(len(rounded['rows'])*2+1)*.0005
        rounded['elapsed_ms']=round(total-rounding+.0005,3)
        smoke.validate_shutdown_stress(rounded,rounded['roi'])
        rounded['elapsed_ms']=round(total-rounding-.001,3)
        with self.assertRaisesRegex(RuntimeError,'elapsed total'):
            smoke.validate_shutdown_stress(rounded,rounded['roi'])

    def test_stress_summary_preserves_failure_and_unknown_parent_observation(self):
        value=shutdown_stress_report();value['rows']=value['rows'][:1]
        value['rows'][0][11]=0xc0000005;value['rows'][0][12]=False;value['rows'][0][13]=None
        value['failure_diagnostic']={'schema_version':1,'exit_code':0xc0000005,
            'checkpoints':[1,2,3,4,5,6],'last_started_stage':'apartment-uninit'}
        self.assertEqual(smoke.summary_shutdown_stress(value),value)
        with self.assertRaises(RuntimeError):smoke.validate_shutdown_stress(value,value['roi'])
        forged=copy.deepcopy(value);forged['failure_diagnostic']['address']='forbidden'
        self.assertIsNone(smoke.summary_shutdown_stress(forged))
        forged=copy.deepcopy(value);forged['rows'][0][13]='unknown'
        self.assertIsNone(smoke.summary_shutdown_stress(forged))

    def test_complete_real_sized_summary_retains_every_stress_row_under_budget(self):
        runs=[]
        for scale in (*smoke.SCALES,*smoke.SCALES):
            value=shutdown_stress_report(scale);value['elapsed_ms']=44999.999
            for index,row in enumerate(value['rows']):
                for position in (2,3,4):row[position]=2**63-100000+index
                for position in (6,7,8):row[position]=2**63-100000+index*1000+position
                row[10]=2000.;row[14]=1999.999;row[15]=2000.
            smoke.validate_shutdown_stress(value,value['roi'])
            runs.append({'shutdown_stress':value})
        self.assertEqual(sum(len(row['shutdown_stress']['rows'])for row in runs),60)
        # Run34's complete three source rows duplicated into six runs occupy
        # 216627 bytes with the exact summary serializer. Keep extra space for
        # new single-case fields and proof changes; no evidence row is dropped.
        measured_existing_summary=216627
        complete_size=measured_existing_summary+len(json.dumps(runs,indent=2).encode())+2048
        self.assertLess(complete_size,256*1024)

    def test_actual_stress_driver_is_bounded_and_keeps_failures(self):
        import wgc_session_smoke as runtime
        def fixture(*,forced=False,complete=True,pixels=0.,exit_code=0,wrong_pid=False,wrong_roi=False):
            samples=shutdown_stress_report()['rows'];sessions=[];result={};counter=iter(samples)
            def new_session():
                row=next(counter)
                s=SimpleNamespace(_request_id=1,close=Mock(),sample=row,
                    _transport=SimpleNamespace(generation=row[4],process=SimpleNamespace(stdin=Mock())))
                sessions.append(s);return s
            def positive(s,**kwargs):
                row=s.sample
                return dict(zip(('helper_pid','helper_created','session_generation','request_id',
                    'request_cutoff_100ns','frame_100ns','idle_enter_100ns'),row[2:9]),
                    mean_channel_error=pixels,elapsed_ms=50.,roi=[81 if wrong_roi else 80,60,160,120])
            observed={'exit_code':exit_code,'native_checkpoints_complete':complete,
                'parent_termination_requested':forced,'process_exit_ms':25.,'cleanup_ms':26.,
                **dict.fromkeys(runtime.SHUTDOWN_CLEANUP_FIELDS,True)}
            f=SimpleNamespace(roi=(80,60,160,120),session=SimpleNamespace(encode_request=Mock(return_value=b'request')),
                new_session=Mock(side_effect=new_session),positive=Mock(side_effect=positive),
                retirement=Mock(side_effect=lambda s,*a,**kw:dict(observed,helper_pid=s.sample[2]+int(wrong_pid))))
            return f,result,sessions
        f,result,sessions=fixture()
        clock=iter(x/10 for x in range(1000))
        with patch.object(runtime.time,'monotonic',side_effect=lambda:next(clock)):
            runtime.verify_native_shutdown_stress(f,result)
        self.assertIs(result['native_shutdown_stress_passed'],True)
        self.assertEqual(len(sessions),runtime.SHUTDOWN_STRESS_PAIRS*2)
        self.assertEqual(f.session.encode_request.call_count,runtime.SHUTDOWN_STRESS_PAIRS)
        smoke.validate_shutdown_stress(result['shutdown_stress'],list(f.roi))
        for i,s in enumerate(sessions):
            s.close.assert_called_once_with()
            (s._transport.process.stdin.write if i%2==0 else s._transport.process.stdin.close).assert_called_once()
        for kwargs in ({'forced':True},{'forced':None},{'complete':False},{'pixels':1.},{'exit_code':0xc0000005}):
            f,result,sessions=fixture(**kwargs)
            with self.subTest(kwargs=kwargs),self.assertRaises(AssertionError):
                runtime.verify_native_shutdown_stress(f,result)
            self.assertEqual(len(result['shutdown_stress']['rows']),1)
            self.assertNotIn('native_shutdown_stress_passed',result);sessions[0].close.assert_called_once_with()
        for kwargs in ({'wrong_pid':True},{'wrong_roi':True}):
            f,result,sessions=fixture(**kwargs)
            with self.subTest(kwargs=kwargs),self.assertRaises(AssertionError):
                runtime.verify_native_shutdown_stress(f,result)
            self.assertEqual(result['shutdown_stress']['rows'],[]);sessions[0].close.assert_called_once_with()
        f,result,sessions=fixture()
        with patch.object(runtime.time,'monotonic',side_effect=[0.,46.,46.]),self.assertRaisesRegex(AssertionError,'deadline'):
            runtime.verify_native_shutdown_stress(f,result)
        f.new_session.assert_not_called()

    def test_retirement_forwards_only_completed_pipe_checkpoint_evidence(self):
        import threading,time
        import wgc_session_smoke as runtime
        import wgc_session_capture as session_module
        def event():
            value=threading.Event();value.set();return value
        for code,data,wanted in ((0xc0000005,b'S1\nS2\nS3\nS4\nS5\nS6\n',True),
                                 (0,b'S1\nS2\nS3\nS4\nS5\nS6\nS7\n',False),
                                 (0xc0000005,b'S1\nS3\nprivate data',False)):
            with self.subTest(code=code,data=data):
                thread=SimpleNamespace(join=Mock(),is_alive=lambda:False)
                process=SimpleNamespace(pid=42,returncode=code,poll=lambda:code,
                    stdin=SimpleNamespace(closed=True),stdout=SimpleNamespace(closed=True),
                    stderr=SimpleNamespace(closed=True))
                transport=SimpleNamespace(process=process,diagnostic=bytearray(data),revoked=event(),
                    ready_for_replacement=event(),worker=thread,watchdog=thread,stderr_done=event(),
                    io_done=event(),job_closed=True,job=SimpleNamespace(handle=None))
                fixture=SimpleNamespace(session=session_module,result={'transitions':[]},pump=Mock())
                row=runtime.Fixture.retirement(fixture,SimpleNamespace(_transport=transport),
                                              'native_stop_passed',time.monotonic())
                self.assertEqual(row['exit_code'],code)
                self.assertEqual('shutdown_diagnostic'in row,wanted)
                if wanted:
                    self.assertEqual(row['shutdown_diagnostic']['last_started_stage'],'apartment-uninit')
                    self.assertEqual(row['shutdown_diagnostic']['exit_code'],code)
                self.assertEqual(fixture.result['transitions'],[row])

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
                value={'status':'passed','frozen':frozen,**smoke.diagnostic_contract(),
                    'scales':list(smoke.SCALES),'source_commit':proof['source_commit'],'helper_build':proof,
                    'source_files':{name:row['sha256']for name,row in proof['source_files'].items()},
                    'runs':[{'app_scale':scale,'detail':passing_report(scale,frozen)}for scale in smoke.SCALES]}
                if frozen:value.update(executable_sha256=executable['sha256'],executable_size=executable['size'])
                values['windows-wgc-session-'+('frozen'if frozen else 'source')+'.json']=value
            for name,value in values.items():(root/name).write_text(json.dumps(value))
            with redirect_stdout(io.StringIO()):self.assertEqual(smoke.summarize(root),0)
            summary=json.loads((root/'windows-wgc-session-summary.json').read_text())
            self.assertEqual(summary['status'],'passed');self.assertEqual(len(summary['runs']),6)
            self.assertLess((root/'windows-wgc-session-summary.json').stat().st_size,256*1024)
            for row in summary['runs']:
                expected=passing_report(row['scale'],row['frozen'])
                for field in ('windows_version','overlay_rendering','overlay_setup'):
                    self.assertEqual(row[field],expected[field],field)
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

    def test_summary_preserves_only_allowlisted_clock_failure_without_success(self):
        diagnostic={'schema_version':1,'code':12,'phase':'frame-wait','check':'frame-timestamp',
            'hresult':0,'observed':[0]*4,'expected':[0]*4,'window_rect':[0]*4,'frame_rect':[0]*4,
            'style':0,'extended_style':0,'clock':{'qpc_counter':123,'qpc_frequency':10000000,
            'cutoff_100ns':100,'frame_100ns':124,'observed_now_100ns':123,'previous_frame_100ns':0}}
        with tempfile.TemporaryDirectory()as temporary:
            root=Path(temporary)
            for forged in (False,True):
                detail={'status':'failed','native_diagnostic':copy.deepcopy(diagnostic)}
                if forged:detail['native_diagnostic']['clock']['window_title']='not allowed'
                value={'status':'failed','runs':[{'app_scale':1,'detail':detail}]}
                (root/'windows-wgc-session-source.json').write_text(json.dumps(value))
                with redirect_stdout(io.StringIO()):self.assertEqual(smoke.summarize(root),1)
                path=root/'windows-wgc-session-summary.json';report=json.loads(path.read_text())
                self.assertEqual(report['status'],'failed')
                self.assertEqual(report['runs'][0]['native_diagnostic'],None if forged else diagnostic)
                self.assertLess(path.stat().st_size,256*1024)

    def test_summary_preserves_abnormal_shutdown_and_never_promotes_crash(self):
        diagnostic={'schema_version':1,'exit_code':0xc0000005,'checkpoints':[1,2,3,4,5,6],
                    'last_started_stage':'apartment-uninit'}
        with tempfile.TemporaryDirectory()as temporary:
            root=Path(temporary)
            for forged in (False,True):
                row={'case':'native_stop_passed','exit_code':0xc0000005,
                     'shutdown_diagnostic':copy.deepcopy(diagnostic)}
                if forged:row['shutdown_diagnostic']['address']='not allowed'
                original=copy.deepcopy(row)
                detail={'status':'failed','error':'Native stop/EOF was not graceful','transitions':[row]}
                value={'status':'failed','runs':[{'app_scale':1,'detail':detail}]}
                (root/'windows-wgc-session-frozen.json').write_text(json.dumps(value))
                with redirect_stdout(io.StringIO()):self.assertEqual(smoke.summarize(root),1)
                path=root/'windows-wgc-session-summary.json';report=json.loads(path.read_text())
                self.assertEqual(report['status'],'failed');self.assertEqual(row,original)
                actual=report['runs'][0]['transitions'][0]
                self.assertEqual(actual['exit_code'],0xc0000005)
                self.assertEqual(actual.get('shutdown_diagnostic'),None if forged else diagnostic)
                self.assertLess(path.stat().st_size,256*1024)

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

"""Portable contract regressions only; never Windows exclusion evidence."""
import copy
from contextlib import chdir, redirect_stderr, redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import threading
import time
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
        constructor='ControlWindow()',visible_capture_enabled=True,executable_sha256=None,
        requested_app_scale=1,measured_qt_scale=1,helper=dict(manifest=helper,**helper),
        client_rect=dict(x=20,y=20,width=960,height=600),target_identity=[1,6,'OwnedWindow'],target_created=3,overlay_hwnd=4,control_hwnd=5,
        overlay_rendering=dict(qt_opacity=1,qt_translucent_background=False,qt_opaque_paint_event=True,
                               qt_surface_has_alpha=False,magenta_grid_samples=30,
                               badge_magenta_grid_samples=[10,10,10],badge_native_region_verified=True),
        requests=[],transitions=[],pixel_pairs=[],negative_results={},fallback_calls=['v1'],
        title_band_variation=dict(patch=[146,260,4,4],pixel_proof_changed=True))
    names=('cold-hidden','hidden-confirmation','visible-product-1','visible-product-2',None,None,None,None)
    for index,name in enumerate(names):
        visible=index in (2,3,5,6,7);generation=0 if index<2 else 1 if index<4 else 2 if index==4 else 3
        identity=dict(helper_pid=10+generation,helper_created=20+generation,session_generation=30+generation)
        state=int(index in (3,4,6,7))
        start=100+index*100
        row=dict(identity,request_id=index+1,capture_start_100ns=start,request_cutoff_100ns=start+1,
            frame_100ns=start+2,idle_enter_100ns=start+3,capture_return_100ns=start+4,
            elapsed_ms=1,status='passed',backend='windows-graphics-capture-session',
            overlay_registration_valid=True,overlay_hwnd=4,overlay_affinity=17,overlay_extended_style=0x080800a8,
            parent_pid=6,overlay_owner_pid=6,visible_request=visible,
            paint_state=state,pixels_sha256=str(state)*64,
            native_visible_before=visible,native_visible_after=visible,overlay_window_style=0x90000000,enrolled_window_style=0x90000000,
            visibility=dict(samples=2,qt_hidden_samples=0 if visible else 2,native_hidden_samples=0 if visible else 2,
                duration_us=1000,samples_us=[[250,3 if visible else 0],[750,3 if visible else 0]],
                sample_format=runtime.SAMPLE_FORMAT,max_sample_gap_ms=.5),
            observation=dict(identity,helper_alive=True,overlay_registration_valid=True,overlay_opaque=True,
                overlay_hwnd=4,overlay_affinity=17,overlay_extended_style=0x080800a8,native_visible=visible))
        if name:row.update(case=name,product=dict(capture_serial=index+1,confirmed=index>0,automatic_frames=2,hide_events=0,show_events=0,
            overlay_visible=True,tier_texts=['T1','T2','T3'],title_check_transitions=[],titles_pending=False,hero='Owned hero',offered=['Title A','Title B','Title C'] if index>0 else []))
        value['requests'].append(row)
    for index,(state,placement) in enumerate(((0,'titles'),(1,'hud'),(1,'titles'))):
        value['pixel_pairs'].append(dict(state=state,placement=placement,max_channel_error=0,changed_pixels=0,
            mean_channel_error=0,hidden_sha256=str(state)*64,visible_sha256=str(state)*64,
            hidden_magenta_pixels=0,visible_magenta_pixels=0,request_index=index+5,
            hidden_reference_index=1 if state==0 else 4,
            overlay_rect=[20,240 if placement=='titles' else 548,900,80]))
    install_presentation_fixture(value)
    for offset in range(3):
        row=copy.deepcopy(value['requests'][7]);visible=offset==2;generation=5 if visible else 4
        binding=dict(helper_pid=10+generation,helper_created=20+generation,session_generation=30+generation)
        row.update(binding);row['observation'].update(binding,native_visible=visible)
        row.update(request_id=1 if visible else offset+1,visible_request=visible,paint_state=int(visible),pixels_sha256=str(int(visible))*64,
                   native_visible_before=visible,native_visible_after=visible)
        start=900+offset*100
        row.update(capture_start_100ns=start,request_cutoff_100ns=start+1,frame_100ns=start+2,idle_enter_100ns=start+3,capture_return_100ns=start+4)
        row['visibility'].update(qt_hidden_samples=0 if visible else 2,native_hidden_samples=0 if visible else 2,
                                 samples_us=[[250,3 if visible else 0],[750,3 if visible else 0]])
        row['product']=dict(capture_serial=21+offset,confirmed=False,partial_names=['Title A','','Title C'] if offset else ['','',''],
            tier_texts=['T1','','T3'] if offset else ['','',''],overlay_visible=bool(offset),hide_events=0,show_events=0,title_check_transitions=[],titles_pending=False)
        value['requests'].append(row)
    value['partial_product']=dict(request_indices=[8,9,10],reference_serial=22,expected_names=['Title A','','Title C'],unknown_slot=2,
        same_overlay_hwnd=True,title_band_pixels_changed=True,visible_slots=[1,3],native_region_count=2,native_mask_verified=True,unknown_accessible_ungraded=True)
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
        for i in range(6)]
    value.update(dict.fromkeys(('product_helper_reuse_passed','pixel_exclusion_passed','hidden_compatibility_passed',
        'helpers_exited_passed','pipe_readers_exited_passed','job_handles_closed_passed','windows_closed_passed'),True))
    foreign=dict(pid=88,hwnd=99,created=100,job_verified=True,executable_sha256='f'*64,
                 owner_pid=6,owner_created=3,launcher_pid=6,launcher_created=3,owner_ancestry_verified=True)
    for index,row in enumerate(value['requests']):
        if row['status']!='passed':continue
        product=row.get('product')
        row.update(acquisition_role='primary' if product else 'direct',
            producer_epoch=index+1,product_serial=product['capture_serial'] if product else 0,
            product_generation=1,capture_started_at=1000.+index,capture_returned_at=1000.1+index)
        if product:
            product.update(generation=1,producer_epoch=index+1,paint_state=row['paint_state'],
                boundary_producer_epoch=index+1-(0 if row['visible_request'] else 1),
                captured_at=999.999+index,boundary_at=999.998+index)
    return value,dict(scale=1,frozen=False,helper=helper,foreign_proof=foreign,foreign_fixture_sha256='f'*64)


def stepped_product_fixture():
    """Real fixture boundary/buffer logic with a controlled acquisition callback."""
    from latest_capture_frame import LatestCaptureFrame
    value,_=fixture();f=runtime.ProductFixture.__new__(runtime.ProductFixture)
    f.records=[];f.event_rows=[];f.title_check_events=[];f.bridge_results=[];f._cycle_serial=None
    f.paint_state=0;f.target=SimpleNamespace(identity=(1,6,'OwnedWindow'))
    f.overlay=SimpleNamespace(isVisible=lambda:True,_titles_pending=False,
        _badge_widgets=[SimpleNamespace(tier=t) for t in ('T1','T2','T3')])
    state=SimpleNamespace(confirmed=True,automatic_frames=2,hero='Owned hero',
        offered=['Title A','Title B','Title C'],generation=1)
    f.control=SimpleNamespace(state=state,ocr_busy=False,capture_pending=False,_capture_serial=3,
        latest_capture=LatestCaptureFrame(),current_partial_names=lambda:('Title A','Title B','Title C'))
    f.wait=lambda predicate,*args:unittest.TestCase().assertTrue(predicate())
    def complete_primary(*,paint_state=None,captured_at=None):
        captured_at=time.monotonic() if captured_at is None else captured_at
        row=copy.deepcopy(value['requests'][3])
        row.update(paint_state=f.paint_state if paint_state is None else paint_state,
            acquisition_role='primary',product_serial=f.control._capture_serial,
            product_generation=1,producer_epoch=f.control.latest_capture._epoch,
            capture_started_at=time.monotonic(),capture_returned_at=time.monotonic())
        f.records.append(row)
        f.observe_product_result('ocr',dict(_captureSerial=f.control._capture_serial,
            _capturedAt=captured_at,_windowIdentity=f.target.identity),1)
        return row
    return f,complete_primary


def install_presentation_fixture(value):
    """Synthetic native lifecycle metadata, never live Windows evidence."""
    baseline=value['requests'][7]
    lifecycle=dict(baseline_request_index=7,adapter_epoch=9,fallback_calls=0,requests=[])
    value['presentation_lifecycle']=lifecycle
    for index,visible in enumerate((False,True,False,True)):
        start=baseline['capture_return_100ns']+100+index*100
        row={key:copy.deepcopy(baseline[key]) for key in (
            'helper_pid','helper_created','session_generation','overlay_hwnd','overlay_affinity',
            'overlay_extended_style','overlay_registration_valid','observation','enrolled_window_style','pixels_sha256')}
        row.update(request_id=baseline['request_id']+1+index,visible=visible,adapter_epoch=9,
                   watchdog_dwell_ms=100.,elapsed_ms=1.,capture_start_100ns=start,
                   request_cutoff_100ns=start+1,frame_100ns=start+2,idle_enter_100ns=start+3,
                   capture_return_100ns=start+4,overlay_window_style=0x90000000 if visible else 0x80000000)
        row['observation']['native_visible']=visible
        lifecycle['requests'].append(row)


def observed_shape_fixture():
    """Synthetic run50-sized data, never a claim of actual Windows acceptance."""
    from test_wgc_session_build import manifest
    detail,kwargs=fixture();helper=manifest()
    detail['helper']=dict(manifest=helper,sha256=helper['sha256'],size=helper['size']);kwargs['helper']=helper
    initial=detail['requests'][:11];rejected=detail['requests'][11:];detail['requests']=initial
    template=copy.deepcopy(initial[7])
    for index,(name,failure) in enumerate(zip(runtime.NEGATIVES,rejected)):
        success=copy.deepcopy(template);binding=dict(helper_pid=100+index,helper_created=200+index,session_generation=300+index)
        success.update(binding);success['observation'].update(binding);success['request_id']=1
        detail['requests'].append(success)
        failure.update(binding);negative=detail['negative_results'][name];negative.update(binding)
        negative['request_index']=len(detail['requests']);detail['requests'].append(failure)
        cleanup=copy.deepcopy(detail['transitions'][0]);cleanup.update(binding);detail['transitions'].append(cleanup)
    # The observed 24 successful and 16 rejected captures retained 2,672 raw
    # samples. Include samples on rejected captures, not only successful ones.
    counts=iter((138,88,102,51,130,105,104,88,100,142,116,130,118,101,106,100,103,118,102,112,112,114,115,99,88,92,100))
    failed_counts={'stop':7,'owner_change':1,'cancel':41,'active_affinity_change':29}
    for index,row in enumerate(detail['requests']):
        passed=row['status']=='passed';visible=row['visible_request']
        count=next(counts) if passed else failed_counts.get(row['negative_case'],0)
        duration=1173*(count+1)+index
        row['elapsed_ms']=duration/1000
        row['visibility']=dict(samples=count,qt_hidden_samples=0 if visible else count,
            native_hidden_samples=0 if visible else count,duration_us=duration,
            samples_us=[[1173*i,3 if visible else 0] for i in range(1,count+1)],
            sample_format=runtime.SAMPLE_FORMAT,max_sample_gap_ms=(1173+index)/1000)
        start=4_260_000_000_000+index*2_500_000
        row.update(capture_start_100ns=start,capture_return_100ns=start+duration*10)
        if passed:
            row.update(request_cutoff_100ns=start+100,frame_100ns=start+duration*9,idle_enter_100ns=start+duration*9+100)
        else:
            row.update(error='Actual pending native exchange rejected by owned diagnostic guard: '+row['negative_case'],
                       error_type='CaptureError',native_visible_before=True,paint_state=1)
            negative=detail['negative_results'][row['negative_case']]
            mutation=None if row['negative_case']=='foreign_pid_occluder' else start+duration*5 if 'pending_exchange_request_id' in row else start-100
            row['mutation_100ns']=mutation
            negative.update(capture_start_100ns=start,capture_return_100ns=start+duration*10,mutation_100ns=mutation)
    install_presentation_fixture(detail)
    # Real-sized creation times and generations make the old compact-JSON-only
    # test unable to hide the production aggregate overflow behind tiny IDs.
    def identities(value):
        if type(value) is dict:
            for key,item in value.items():
                if key=='helper_pid':value[key]=3900+item*4
                elif key=='helper_created':value[key]=134365520183600000+item*1000
                elif key=='session_generation':value[key]=7324629758592700000+item
                else:identities(item)
        elif type(value) is list:
            for item in value:identities(item)
    identities(detail)
    while len(detail['transitions'])<53:detail['transitions'].append(copy.deepcopy(detail['transitions'][len(detail['transitions'])%20]))
    for index,row in enumerate(detail['transitions']):
        row.update(observed_ms=float(index%7),termination_requested_while_alive=True,shutdown_diagnostic=None,
                   case='owned-visible-negative-before-replacement-drain-'+str(index))
    detail.update(windows_version=dict(major=10,minor=0,build=20348),helper_process_count=20,
        pattern='original owned deterministic target, title/HUD, and opaque overlay',
        overlay_setup=[dict(stage=stage,overlay_hwnd=4,overlay_affinity=17,overlay_extended_style=0x080800a8,
                            qt_translucent_background=False,qt_opaque_paint_event=True,qt_surface_has_alpha=False)
                       for stage in ('created-hidden','realized-visible','verified-hidden')])
    return detail,kwargs


def write_scale_reports(folder, *, count=3):
    detail,kwargs=observed_shape_fixture()
    aggregate=dict(status='passed',frozen=False,scope=runtime.SCOPE,applicationVersion=harness.__version__,
        scales=list(runtime.SCALES),source_commit='d'*40,helper_build=kwargs['helper'],
        source_files={name:'a'*64 for name in runtime.SOURCE_FILES},runs=[])
    for scale in runtime.SCALES[:count]:
        current=copy.deepcopy(detail);current.update(requested_app_scale=scale,measured_qt_scale=scale)
        harness.validate_report(current,**dict(kwargs,scale=scale))
        path=Path(folder)/harness.scale_report_name(scale,frozen=False)
        raw=runtime.report_payload(current).encode();path.write_bytes(raw)
        aggregate['runs'].append(dict(scale=scale,detail=current,foreign=copy.deepcopy(kwargs['foreign_proof']),
            coordination='passed',exit_code=0,outer_cleanup_complete=True,
            report_sha256=hashlib.sha256(raw).hexdigest(),report_size=len(raw)))
    return aggregate,kwargs


class VisibleContracts(unittest.TestCase):
    def test_complete_synthetic_report_contract(self):
        value,kwargs=fixture();self.assertIs(harness.validate_report(value,**kwargs),value)

    def test_presentation_lifecycle_is_separate_and_strictly_bound(self):
        mutations=(
            lambda v:v.pop('presentation_lifecycle'),
            lambda v:v['presentation_lifecycle'].update(baseline_request_index=0),
            lambda v:v['presentation_lifecycle'].update(fallback_calls=1),
            lambda v:v['presentation_lifecycle']['requests'].pop(),
            lambda v:v['presentation_lifecycle']['requests'][0].update(visible=True),
            lambda v:v['presentation_lifecycle']['requests'][0].update(visible=0),
            lambda v:v['presentation_lifecycle']['requests'][0].update(helper_pid=999),
            lambda v:v['presentation_lifecycle']['requests'][0].update(adapter_epoch=10),
            lambda v:v['presentation_lifecycle']['requests'][0].update(adapter_epoch=True),
            lambda v:v['presentation_lifecycle']['requests'][0].update(request_id=8),
            lambda v:v['presentation_lifecycle']['requests'][0].update(frame_100ns=1),
            lambda v:v['presentation_lifecycle']['requests'][0].update(watchdog_dwell_ms=24),
            lambda v:v['presentation_lifecycle']['requests'][0].update(overlay_window_style=0x90000000),
            lambda v:v['presentation_lifecycle']['requests'][0].update(overlay_window_style=0x80000001),
            lambda v:v['presentation_lifecycle']['requests'][0].update(enrolled_window_style=0x80000000),
            lambda v:v['presentation_lifecycle']['requests'][0].update(overlay_hwnd=8),
            lambda v:v['presentation_lifecycle']['requests'][0].update(overlay_affinity=1),
            lambda v:v['presentation_lifecycle']['requests'][0].update(overlay_extended_style=0x08080088),
            lambda v:v['presentation_lifecycle']['requests'][0].update(overlay_registration_valid=False),
            lambda v:v['presentation_lifecycle']['requests'][0]['observation'].update(native_visible=True),
            lambda v:v['presentation_lifecycle']['requests'][0]['observation'].update(overlay_opaque=False),
            lambda v:v['presentation_lifecycle']['requests'][0].update(pixels_sha256='f'*64),
            lambda v:v['presentation_lifecycle']['requests'][0].update(_png='private'),
        )
        for index,mutate in enumerate(mutations):
            with self.subTest(index=index):
                value,kwargs=fixture();mutate(value)
                with self.assertRaises(RuntimeError):harness.validate_report(value,**kwargs)
        # The lifecycle allowance never relaxes the original continuously shown
        # product/pixel proof, even for a presentation-only style difference.
        value,kwargs=fixture();value['requests'][2]['overlay_window_style']^=0x10000000
        with self.assertRaises(RuntimeError):harness.validate_report(value,**kwargs)

    def test_presentation_producer_keeps_main_capture_inventory_and_uses_real_backend(self):
        value,_=fixture();f=runtime.ProductFixture.__new__(runtime.ProductFixture)
        f.records=[copy.deepcopy(value['requests'][7])];f.result={};f.fallback_calls=[]
        raw=b'owned deterministic pixels';f.records[0]['pixels_sha256']=hashlib.sha256(raw).hexdigest()
        state=dict(visible=True,now=100.,qpc=100000,request=8)
        owner=SimpleNamespace(binding=('exact',True),session=SimpleNamespace(_overlay_window_style=0x90000000))
        f.capture=SimpleNamespace(_persistent=SimpleNamespace(_owner=owner),session_epoch=9,
            prepare_capture_mode=Mock(return_value=True),last_session_receipt=None,
            get_long=lambda hwnd,field:0x90000000 if state['visible'] else 0x80000000)
        f.overlay=SimpleNamespace(isVisible=lambda:state['visible'],
            show=lambda:state.update(visible=True),hide=lambda reason:state.update(visible=False))
        f.overlay_hwnd=4;f.u=SimpleNamespace(IsWindowVisible=lambda hwnd:state['visible'])
        f.target=object();f.rect=object();f.control=SimpleNamespace(manual_metadata=object())
        f.pump=lambda seconds:state.update(now=state['now']+seconds)
        def wait(predicate,*args):
            deadline=time.monotonic()+1
            while not predicate():
                self.assertLess(time.monotonic(),deadline);time.sleep(.001)
        f.wait=wait
        def qpc():state['qpc']+=1;return state['qpc']
        def capture(*args,**kwargs):
            self.assertEqual(args,(f.target,));self.assertIs(kwargs['allow_visible_overlay'],True)
            self.assertIs(kwargs['expected_metadata'],f.control.manual_metadata)
            state['request']+=1
            f.capture.last_session_receipt={key:f.records[0][key] for key in (
                'helper_pid','helper_created','session_generation','overlay_hwnd','overlay_affinity',
                'overlay_extended_style','overlay_registration_valid')}
            f.capture.last_session_receipt.update(request_id=state['request'],request_cutoff_100ns=qpc(),
                                                frame_100ns=qpc(),idle_enter_100ns=qpc())
            return b'encoded pixels',f.rect
        f.real_capture=Mock(side_effect=capture)
        def observe(capture,receipt,*,hidden):
            self.assertIs(capture,f.capture);self.assertIs(hidden,not state['visible'])
            proof=copy.deepcopy(f.records[0]['observation']);proof['native_visible']=state['visible']
            return owner,None,proof
        with patch.dict(sys.modules,{'native_smoke':SimpleNamespace(_duty_session_observation=observe)}), \
                patch('wgc_session_capture._qpc_100ns',side_effect=qpc), \
                patch.object(runtime,'time',SimpleNamespace(monotonic=lambda:state['now'])), \
                patch.object(runtime,'pixels',return_value=SimpleNamespace(tobytes=lambda:raw)):
            f.presentation_lifecycle()
        self.assertEqual(len(f.records),1)
        self.assertEqual(f.real_capture.call_count,4)
        self.assertEqual(f.capture.prepare_capture_mode.call_args_list,[((True,),)]*4)
        self.assertIs(f.capture._persistent._owner,owner)
        self.assertTrue(state['visible'])
        harness.validate_presentation_lifecycle(f.result,f.records)

    def test_explicit_release_version_binds_the_detail_report(self):
        value,kwargs=fixture()
        version='99.0.0'
        self.assertNotEqual(harness.__version__,version)
        with self.assertRaises(RuntimeError):harness.validate_report(value,version=version,**kwargs)
        value['applicationVersion']=version
        self.assertIs(harness.validate_report(value,version=version,**kwargs),value)
        with self.assertRaises(RuntimeError):harness.validate_report(value,**kwargs)

    def test_visible_limits_truthfully_enable_only_the_ordinary_product(self):
        from wgc_session_smoke import LIMITATIONS as session_limits
        self.assertIs(session_limits['production_enabled'],False)
        self.assertIs(runtime.LIMITATIONS['production_enabled'],True)
        self.assertIsNot(runtime.LIMITATIONS,session_limits)
        self.assertIs(harness.LIMITATIONS,runtime.LIMITATIONS)
        self.assertEqual(runtime.LIMITATIONS,dict(session_limits,production_enabled=True))
        for reported in (False,0,1,1.0,None,'true'):
            value,kwargs=fixture();value['limitations']['production_enabled']=reported
            with self.subTest(reported=reported),self.assertRaises(RuntimeError):harness.validate_report(value,**kwargs)

    def test_ordinary_default_and_changed_gui_identity_contract_is_strict(self):
        mutations=(
            lambda v:v.update(constructor='ControlWindow(enable_visible_capture=True)'),
            lambda v:v.pop('visible_capture_enabled'),
            lambda v:v.update(visible_capture_enabled=False),
            lambda v:v.update(visible_capture_enabled=1),
            lambda v:v['requests'][3].update(visible_request=False),
            lambda v:v['requests'][3].update(paint_state=0),
            lambda v:v['requests'][3].update(paint_state=True),
            lambda v:v['requests'][2].update(paint_state=False),
            lambda v:v['requests'][3].update(pixels_sha256=v['requests'][2]['pixels_sha256']),
            lambda v:v['requests'][2].update(pixels_sha256='a'*64),
            lambda v:v['requests'][3].update(pixels_sha256='b'*64),
            lambda v:v['requests'][3]['product'].update(hide_events=1),
            lambda v:v['requests'][3]['product'].update(title_check_transitions=[True,False]),
            lambda v:v['requests'][3]['product'].update(titles_pending=True),
            lambda v:v['title_band_variation'].update(pixel_proof_changed=False),
            lambda v:v.pop('title_band_variation'),
            lambda v:v['requests'][3]['product'].update(tier_texts=['T2','T2','T3']),
            lambda v:v['requests'][3]['product'].pop('tier_texts'),
            lambda v:v.pop('partial_product'),
            lambda v:v['partial_product'].update(reference_serial=21),
            lambda v:v['requests'][10]['product'].update(overlay_visible=False),
            lambda v:v['requests'][10]['product'].update(hide_events=False),
            lambda v:v['partial_product'].update(native_mask_verified=False),
            lambda v:v['partial_product'].update(title_band_pixels_changed=False),
            lambda v:v['requests'][10]['product'].update(tier_texts=['T1','T2','T3']),
            lambda v:v['requests'][10]['product'].update(partial_names=['Title C','','Title A']),
            lambda v:v['requests'][10]['product'].update(title_check_transitions=[True,False]),
            lambda v:v['requests'][3]['product'].update(hide_events=False),
            lambda v:v['requests'][3]['product'].update(hero='Different hero'),
            lambda v:v['requests'][3]['product'].update(offered=['Title B','Title A','Title C']),
            lambda v:v['requests'][1]['product'].pop('hero'),
            lambda v:v['requests'][1]['product'].pop('offered'),
            lambda v:[row['product'].update(hero=True) for row in v['requests'][1:4]],
            lambda v:[row['product'].update(offered=[True,'Title B','Title C']) for row in v['requests'][1:4]],
            lambda v:[row['product'].update(offered=['Title A','Title A','Title C']) for row in v['requests'][1:4]],
            lambda v:[row['product'].update(offered=('Title A','Title B','Title C')) for row in v['requests'][1:4]],
        )
        for index,mutate in enumerate(mutations):
            value,kwargs=fixture();mutate(value)
            with self.subTest(index=index),self.assertRaises(RuntimeError):harness.validate_report(value,**kwargs)

    def test_changed_gui_paint_is_inside_the_zero_hide_observation(self):
        for hide_during_paint in (False,True):
            f,complete=stepped_product_fixture();actions=[]
            def paint(paint_state):
                actions.append(('paint',paint_state));f.paint_state=paint_state
                if hide_during_paint:f.event_rows.append(dict(event='hide'))
            def capture():
                actions.append(('capture',f.paint_state))
                f.control._capture_serial+=1;complete()
            f.paint=paint;f.control.capture_tick=capture
            with self.subTest(hide_during_paint=hide_during_paint):
                if hide_during_paint:
                    with self.assertRaisesRegex(AssertionError,'hid/reflowed'):
                        f.product_cycle('visible-product-2',visible=True,paint_state=1)
                else:
                    row=f.product_cycle('visible-product-2',visible=True,paint_state=1)
                    self.assertEqual(row['product']['hide_events'],0)
                self.assertEqual(actions,[('paint',1),('capture',1)])

    def test_explicit_fixture_cadence_disconnects_due_real_qt_monitor(self):
        try:
            from PySide6 import QtCore, QtWidgets
        except ImportError:
            self.skipTest('PySide6 is needed for the real Qt timer regression')
        app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        for explicit in (False,True):
            with self.subTest(explicit=explicit):
                calls=[]
                monitor=QtCore.QTimer();monitor.setSingleShot(True)
                watchdog=QtCore.QTimer()
                capture=lambda:calls.append('capture')
                monitor.timeout.connect(capture)
                f=runtime.ProductFixture.__new__(runtime.ProductFixture)
                f.control=SimpleNamespace(monitor=monitor,watchdog=watchdog,capture_tick=capture)
                f.app=app;f.end=time.monotonic()+2;f.active=None
                monitor.start(0)
                if explicit:f.use_explicit_capture_cadence()
                # A real result handler may restart the monitor before the
                # fixture next pumps events, including at an already due time.
                monitor.start(0)
                f.pump(.01)
                self.assertEqual(calls,[] if explicit else ['capture'])
                if explicit:
                    # Manual stepping and independent one-shot acquisition
                    # callbacks remain real and runnable.
                    f.control.capture_tick()
                    QtCore.QTimer.singleShot(0,capture)
                    f.pump(.01)
                    self.assertEqual(calls,['capture','capture'])

    def test_changed_gui_cycle_rejects_prepaint_acquisition_association(self):
        f,complete=stepped_product_fixture()
        def paint(state):
            f.paint_state=state
        def capture():
            f.control._capture_serial+=1;complete(paint_state=0)
        f.paint=paint;f.control.capture_tick=capture
        with self.assertRaisesRegex(AssertionError,'earlier paint state'):
            f.product_cycle('visible-product-2',visible=True,paint_state=1)

    def test_hidden_primary_accounts_for_only_its_normal_buffer_clear(self):
        for clears in (0,1,2):
            with self.subTest(clears=clears):
                f,complete=stepped_product_fixture()
                def capture():
                    f.control._capture_serial+=1
                    for _ in range(clears):f.control.latest_capture.clear()
                    row=complete();row['visible_request']=False
                f.control.capture_tick=capture
                if clears==1:
                    row=f.product_cycle('hidden-confirmation',visible=False)
                    self.assertEqual(row['product']['boundary_producer_epoch'],1)
                    self.assertEqual(row['product']['producer_epoch'],2)
                else:
                    with self.assertRaisesRegex(AssertionError,'explicit acquisition boundary'):
                        f.product_cycle('hidden-confirmation',visible=False)

    def test_real_qt_boundary_drains_old_producer_and_keeps_new_background_rows(self):
        try:
            from PySide6 import QtCore,QtWidgets
        except ImportError:
            self.skipTest('PySide6 is needed for the real Qt producer regression')
        from latest_capture_frame import CapturedFrame
        app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        f,complete=stepped_product_fixture();latest=f.control.latest_capture
        f.app=app;f.end=time.monotonic()+5;f.active=None
        f.control.monitor=QtCore.QTimer();f.control.monitor.setSingleShot(True)
        f.control.watchdog=QtCore.QTimer()
        f.wait=runtime.ProductFixture.wait.__get__(f)
        calls=[];old_released=threading.Event();new_released=threading.Event()
        def background(state,released):
            def acquire(cancelled):
                started=time.monotonic()
                if not released.wait(2):raise AssertionError('Producer was not released by Qt')
                f.records.append(dict(acquisition_role='background',paint_state=state,
                    producer_epoch=latest._epoch,capture_started_at=started))
                return CapturedFrame(b'owned synthetic bytes',object(),started,time.monotonic())
            return acquire
        def paint(state):
            self.assertFalse(latest.busy)
            self.assertIsNone(latest.take('old'))
            self.assertEqual(len(f.records),1)
            self.assertEqual(f.records[0]['paint_state'],0)
            f.paint_state=state;f.pump(.005)
        def primary():
            calls.append('primary')
            f.control._capture_serial+=1
            f.control.ocr_busy=True;f.control.capture_pending=True
            def finish():
                complete()
                # Reproduce capture+OCR completing in a single event pump,
                # which previously caused an unconditional capture_tick retry.
                f.control.ocr_busy=False;f.control.capture_pending=False
                self.assertTrue(latest.submit('new',background(1,new_released)))
                QtCore.QTimer.singleShot(0,new_released.set)
            QtCore.QTimer.singleShot(0,finish)
        f.paint=paint;f.control.capture_tick=primary
        f.control.monitor.timeout.connect(primary)
        f.use_explicit_capture_cadence()
        try:
            self.assertTrue(latest.submit('old',background(0,old_released)))
            QtCore.QTimer.singleShot(0,old_released.set)
            row=f.product_cycle('visible-product-2',visible=True,paint_state=1)
            self.assertEqual(calls,['primary'])
            self.assertEqual([r['acquisition_role'] for r in f.records],['background','primary','background'])
            self.assertIs(row,f.records[1])
            self.assertEqual((row['paint_state'],row['producer_epoch']),(1,1))
            self.assertLessEqual(row['product']['boundary_at'],row['product']['captured_at'])
            self.assertLessEqual(row['product']['captured_at'],row['capture_started_at'])
            self.assertEqual([r.get('case') for r in f.records],[None,'visible-product-2',None])
            self.assertFalse(latest.busy)
            self.assertIsNotNone(latest.take('new'))
        finally:
            old_released.set();new_released.set();latest.close()
            latest._thread.join(2)
            self.assertFalse(latest._thread.is_alive())

    def test_original_bridge_observation_is_not_mutated(self):
        f,_=stepped_product_fixture()
        value=dict(_captureSerial=7,_capturedAt=1.25,_windowIdentity=(1,2,'Owned'),
                   untouched={'nested':['metadata']})
        original=copy.deepcopy(value)
        f.observe_product_result('capture-proof',value,8)
        self.assertEqual(f.bridge_results,[])
        f.observe_product_result('ocr',value,8)
        self.assertEqual(value,original)
        self.assertEqual(f.bridge_results,[dict(generation=8,serial=7,captured_at=1.25,
            window_identity=(1,2,'Owned'))])

    def test_product_acquisition_boundary_rejects_stale_metadata(self):
        mutations=(
            lambda r:r.update(acquisition_role='background'),
            lambda r:r.update(acquisition_role='direct'),
            lambda r:r.update(product_serial=r['product_serial']-1),
            lambda r:r.update(product_generation=r['product_generation']+1),
            lambda r:r.update(producer_epoch=r['producer_epoch']+1),
            lambda r:r['product'].update(boundary_producer_epoch=r['producer_epoch']-1),
            lambda r:r['product'].update(captured_at=r['product']['boundary_at']-1),
            lambda r:r['product'].update(captured_at=r['capture_started_at']+1),
            lambda r:r['product'].update(captured_at=float('nan')),
            lambda r:r['product'].update(captured_at=True),
            lambda r:r['product'].update(paint_state=0),
            lambda r:r.update(capture_returned_at=r['capture_started_at']-1),
        )
        for index,mutate in enumerate(mutations):
            value,kwargs=fixture();mutate(value['requests'][3])
            with self.subTest(index=index),self.assertRaises(RuntimeError):
                harness.validate_report(value,**kwargs)

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
            lambda v:v['overlay_rendering'].update(badge_magenta_grid_samples=[10,0,10]),
            lambda v:v['overlay_rendering'].update(badge_native_region_verified=False),
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

    def test_comparison_hashes_independently_decoded_rgb8_bytes(self):
        from PIL import Image
        from synthetic_vision import encoded
        before=Image.new('RGBA',(2,1),(255,0,255,17))
        after=before.copy();after.putpixel((0,0),(0,255,0,240))
        reference,captured=encoded(before),encoded(after)
        comparison=runtime.compare_pixels(reference,captured)
        for key,png in (('hidden_sha256',reference),('visible_sha256',captured)):
            with Image.open(io.BytesIO(png)) as decoded:
                expected=hashlib.sha256(decoded.convert('RGB').tobytes()).hexdigest()
            self.assertEqual(comparison[key],expected)
        self.assertEqual((comparison['max_channel_error'],comparison['changed_pixels']),(255,1))
        self.assertEqual(comparison['mean_channel_error'],127.5)
        self.assertEqual((comparison['hidden_magenta_pixels'],comparison['visible_magenta_pixels']),(2,1))

    def test_real_pixel_comparisons_bind_to_producer_shaped_acquisitions(self):
        import numpy as np
        from PIL import Image
        from synthetic_vision import encoded
        value,kwargs=fixture()
        first=Image.new('RGB',(960,600),(24,42,62));second=first.copy()
        second.paste((75,60,85),(192,162,204,174))
        frames=[encoded(first),encoded(second)]
        # Acquisition evidence independently decodes to RGB8, as the real
        # observed_capture producer does; no shared placeholder digest can
        # conceal a different byte encoding in compare_pixels.
        for row in value['requests']:
            if row['status']=='passed':
                with Image.open(io.BytesIO(frames[row['paint_state']])) as decoded:
                    row['pixels_sha256']=hashlib.sha256(decoded.convert('RGB').tobytes()).hexdigest()
        for pair in value['pixel_pairs']:
            hidden=value['requests'][pair['hidden_reference_index']]
            visible=value['requests'][pair['request_index']]
            pair.update(runtime.compare_pixels(frames[hidden['paint_state']],frames[visible['paint_state']]))
        install_presentation_fixture(value)
        self.assertIs(harness.validate_report(value,**kwargs),value)
        # Even mutually equal hashes over widened arithmetic buffers must
        # remain rejected when they do not bind to the acquired RGB8 bytes.
        widened=hashlib.sha256(np.asarray(first,dtype=np.int16).tobytes()).hexdigest()
        value['pixel_pairs'][0].update(hidden_sha256=widened,visible_sha256=widened)
        with self.assertRaisesRegex(RuntimeError,'Pixel equality not bound'):
            harness.validate_report(value,**kwargs)

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
               'portrait_display','local_debug','selection_session','card_badges','badge_contract',
                 'augment_card_geometry','hero_identity_continuity','monitor_preferences','card_title_proof','source_combo_hints')
        modules={name:compile((ROOT/(name+'.py')).read_bytes(),'C:/independent/'+name+'.py','exec',
                             dont_inherit=True,optimize=0) for name in names}
        archive=SimpleNamespace(toc={'PYZ.pyz':None},
            open_embedded_archive=lambda _:SimpleNamespace(extract=modules.__getitem__))
        self.assertEqual(set(harness.verify_product_modules(archive)),set(names))
        modules['native_smoke']=compile('changed = True','different.py','exec',dont_inherit=True)
        with self.assertRaises(RuntimeError):harness.verify_product_modules(archive)

    def test_lossless_full_three_scale_aggregate_stays_under_existing_cap(self):
        with tempfile.TemporaryDirectory() as folder:
            original,kwargs=write_scale_reports(folder)
            before=copy.deepcopy(original)
            self.assertGreater(len(json.dumps(original,separators=(',',':')).encode()),runtime.MAX_REPORT_BYTES)
            aggregate,blocks=harness.aggregate_evidence(original,folder,frozen=False)
            self.assertEqual(original,before)
            compact=runtime.report_payload(aggregate)
            self.assertLessEqual(len(compact.encode()),runtime.MAX_REPORT_BYTES)
            self.assertEqual(len(blocks),3)
            for run,source,(filename,complete) in zip(aggregate['runs'],original['runs'],blocks):
                self.assertNotIn('detail',run)
                self.assertEqual(run['detail_report'],filename)
                decoded=harness.read_bound_detail(run,folder,frozen=False)
                self.assertTrue(harness.same_json(decoded,source['detail']))
                harness.validate_report(decoded,**dict(kwargs,scale=run['scale']))
                self.assertEqual(len(decoded['requests']),43)
                self.assertEqual(len(decoded['transitions']),53)
                self.assertEqual(sum(row['visibility']['samples'] for row in decoded['requests']),2952)
                self.assertLessEqual(len(complete.encode()),runtime.MAX_REPORT_BYTES)
                rendered=harness.rendered_report(complete)
                self.assertTrue(harness.same_json(json.loads(rendered),source['detail']))
                self.assertLessEqual(max(map(len,rendered.splitlines())),1024)
                raw=(Path(folder)/filename).read_bytes()
                self.assertEqual(hashlib.sha256(raw).hexdigest(),source['report_sha256'])
                self.assertEqual(len(raw),source['report_size'])
            self.assertEqual(json.loads(harness.rendered_report(compact)),aggregate)
            output=io.StringIO()
            with redirect_stdout(output):self.assertEqual(harness.finish_reports(original,Path(folder),frozen=False),0)
            self.assertEqual(output.getvalue().count('Complete bounded visible-overlay scale evidence:'),3)

    def test_bound_scale_reports_are_relocatable_and_allow_relative_root(self):
        with tempfile.TemporaryDirectory() as folder:
            old=Path(folder)/'original';old.mkdir();original,_=write_scale_reports(old)
            aggregate,_=harness.aggregate_evidence(original,old,frozen=False)
            moved=old.with_name('moved');old.rename(moved)
            with chdir(folder):
                for run,source in zip(aggregate['runs'],original['runs']):
                    self.assertTrue(harness.same_json(harness.read_bound_detail(run,'moved',frozen=False),source['detail']))
            for scale in runtime.SCALES:
                self.assertEqual(harness.scale_report_name(scale,frozen=True),
                                 'windows-wgc-visible-overlay-frozen-scale'+str(round(scale*100))+'.json')

    def test_aggregate_retains_failed_current_detail_after_two_complete_scales(self):
        with tempfile.TemporaryDirectory() as folder:
            original,_=write_scale_reports(folder);last=original['runs'][-1]
            original.update(status='failed',error='Original native rejection must survive')
            last['detail'].update(status='failed',error='Full current failure including all samples')
            # Its changed original file has a matching raw binding, so failures
            # can be referenced losslessly just like successful complete files.
            path=Path(folder)/harness.scale_report_name(last['scale'],frozen=False)
            raw=runtime.report_payload(last['detail']).encode();path.write_bytes(raw)
            last.update(report_sha256=hashlib.sha256(raw).hexdigest(),report_size=len(raw))
            aggregate,blocks=harness.aggregate_evidence(original,folder,frozen=False)
            self.assertEqual(aggregate['error'],original['error']);self.assertEqual(len(blocks),3)
            self.assertEqual(harness.read_bound_detail(aggregate['runs'][-1],folder,frozen=False),last['detail'])
            self.assertLessEqual(len(runtime.report_payload(aggregate).encode()),runtime.MAX_REPORT_BYTES)
            # A vanished failed file stays inline, with its complete evidence,
            # while the first two verified reports remain referenced.
            path.unlink();aggregate,blocks=harness.aggregate_evidence(original,folder,frozen=False)
            self.assertEqual(aggregate['error'],original['error'])
            self.assertEqual(aggregate['runs'][-1]['detail'],last['detail'])
            self.assertTrue(all('detail_report' in run for run in aggregate['runs'][:2]))
            self.assertLessEqual(len(runtime.report_payload(aggregate).encode()),runtime.MAX_REPORT_BYTES)
            self.assertEqual(json.loads(blocks[-1][1]),last['detail'])
            with redirect_stdout(io.StringIO()):self.assertEqual(harness.finish_reports(original,Path(folder),frozen=False),1)

    def test_unbound_scale_evidence_is_never_dropped_or_reported_as_success(self):
        edits={
            'missing':lambda run,path:path.unlink(),
            'hash':lambda run,path:run.update(report_sha256='b'*64),
            'size':lambda run,path:run.update(report_size=run['report_size']+1),
            'boolean_size':lambda run,path:run.update(report_size=True),
            'unsafe_name':lambda run,path:run.update(detail_report='../other.json'),
            'absolute_name':lambda run,path:run.update(detail_report=str(path.resolve())),
            'wrong_mode':lambda run,path:run.update(detail_report=harness.scale_report_name(run['scale'],frozen=True)),
            'boolean_scale':lambda run,path:run.update(scale=True),
            'unknown_scale':lambda run,path:run.update(scale=3),
            'field_missing':lambda run,path:run['detail'].pop('windows_version'),
            'sample_missing':lambda run,path:run['detail']['requests'][0]['visibility']['samples_us'].pop(),
            'boolean_for_int':lambda run,path:run['detail']['requests'][0]['visibility']['samples_us'][0].__setitem__(1,False),
            'float_for_int':lambda run,path:run['detail'].update(schema_version=1.0),
            'extra_field':lambda run,path:run['detail'].update(unbound_extra='preserve this'),
        }
        for label,edit in edits.items():
            with self.subTest(label=label),tempfile.TemporaryDirectory() as folder:
                original,_=write_scale_reports(folder,count=1);run=original['runs'][0]
                path=Path(folder)/harness.scale_report_name(run['scale'],frozen=False);edit(run,path)
                aggregate,blocks=harness.aggregate_evidence(original,folder,frozen=False)
                self.assertEqual(aggregate['status'],'failed')
                self.assertTrue(harness.same_json(aggregate['runs'][0]['detail'],run['detail']))
                self.assertTrue(harness.same_json(json.loads(blocks[0][1]),run['detail']))
                self.assertIn('report_binding_error',aggregate['runs'][0])
                with redirect_stdout(io.StringIO()):self.assertEqual(harness.finish_reports(original,Path(folder),frozen=False),1)

    def test_strict_bound_reader_rejects_duplicate_nonfinite_oversize_and_symlink(self):
        for label,raw in (('duplicate',b'{"status":"passed","status":"failed"}'),
                          ('nonfinite',b'{"value":NaN}'),('overflow',b'{"value":1e999}'),
                          ('array',b'[]'),('oversize',b' '*runtime.MAX_REPORT_BYTES+b'{}')):
            with self.subTest(label=label),tempfile.TemporaryDirectory() as folder:
                original,_=write_scale_reports(folder,count=1);run=original['runs'][0]
                path=Path(folder)/harness.scale_report_name(run['scale'],frozen=False);path.write_bytes(raw)
                run.update(report_size=len(raw),report_sha256=hashlib.sha256(raw).hexdigest())
                aggregate,blocks=harness.aggregate_evidence(original,folder,frozen=False)
                self.assertEqual(aggregate['status'],'failed');self.assertEqual(aggregate['runs'][0]['detail'],run['detail'])
                self.assertEqual(json.loads(blocks[0][1]),run['detail'])
        with tempfile.TemporaryDirectory() as folder:
            original,_=write_scale_reports(folder,count=1);run=original['runs'][0]
            path=Path(folder)/harness.scale_report_name(run['scale'],frozen=False)
            other=path.with_name('untrusted.json');path.rename(other)
            try:path.symlink_to(other)
            except NotImplementedError:self.skipTest('Symlink creation unavailable')
            except OSError as error:
                if os.name=='nt' and getattr(error,'winerror',None) in (1,50,1314):
                    self.skipTest('Symlink creation is not available for this Windows account')
                raise
            with self.assertRaisesRegex(RuntimeError,'symlinked'):harness.read_bound_detail(run,folder,frozen=False)

    def test_missing_and_duplicate_scale_inventory_retains_all_available_evidence(self):
        with tempfile.TemporaryDirectory() as folder:
            original,_=write_scale_reports(folder,count=1)
            original['runs'].append(copy.deepcopy(original['runs'][0]))
            aggregate,blocks=harness.aggregate_evidence(original,folder,frozen=False)
            self.assertEqual(aggregate['status'],'failed');self.assertEqual(len(blocks),2)
            self.assertIn('detail_report',aggregate['runs'][0]);self.assertIn('detail',aggregate['runs'][1])
            missing=dict(scale=1.5,detail_error='Final native report never appeared')
            original['runs'][-1]=missing
            aggregate,blocks=harness.aggregate_evidence(original,folder,frozen=False)
            self.assertEqual(aggregate['status'],'failed');self.assertEqual(len(blocks),1)
            self.assertEqual(aggregate['runs'][-1]['detail_error'],missing['detail_error'])
            self.assertNotIn('detail_report',aggregate['runs'][-1])
        self.assertFalse(harness.same_json({'x':0.0},{'x':-0.0}))
        self.assertFalse(harness.same_json({'x':False},{'x':0}))
        self.assertFalse(harness.same_json({'x':1},{'x':1.0}))

    def test_aggregate_requires_complete_ordered_mode_and_scale_inventory(self):
        edits=(lambda v:v.update(runs=[]),lambda v:v['runs'].pop(),lambda v:v['runs'].reverse(),
               lambda v:v.update(frozen=True),lambda v:v.update(scales=[1,2]))
        for edit in edits:
            with tempfile.TemporaryDirectory() as folder:
                original,_=write_scale_reports(folder);edit(original)
                aggregate,_=harness.aggregate_evidence(original,folder,frozen=False)
                self.assertEqual(aggregate['status'],'failed');self.assertIn('report_binding_errors',aggregate)
        for key,value in (('frozen',True),('requested_app_scale',2),('measured_qt_scale',True)):
            with self.subTest(key=key),tempfile.TemporaryDirectory() as folder:
                original,_=write_scale_reports(folder);run=original['runs'][0]
                run['detail'][key]=value
                raw=runtime.report_payload(run['detail']).encode()
                (Path(folder)/harness.scale_report_name(1,frozen=False)).write_bytes(raw)
                run.update(report_size=len(raw),report_sha256=hashlib.sha256(raw).hexdigest())
                aggregate,blocks=harness.aggregate_evidence(original,folder,frozen=False)
                self.assertEqual(aggregate['status'],'failed');self.assertIn('detail',aggregate['runs'][0])
                self.assertEqual(json.loads(blocks[0][1]),run['detail'])

    def test_symlinked_reports_directory_cannot_bind_or_write_receipts(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'real';root.mkdir();original,_=write_scale_reports(root)
            link=root.with_name('alias')
            try:link.symlink_to(root,target_is_directory=True)
            except NotImplementedError:self.skipTest('Symlink creation unavailable')
            except OSError as error:
                if os.name=='nt' and getattr(error,'winerror',None) in (1,50,1314):
                    self.skipTest('Symlink creation is not available for this Windows account')
                raise
            with self.assertRaisesRegex(RuntimeError,'directory is symlinked'):
                harness.read_bound_detail(original['runs'][0],link,frozen=False)
            with redirect_stdout(io.StringIO()):self.assertEqual(harness.finish_reports(original,link,frozen=False),1)
            self.assertFalse((root/'windows-wgc-visible-overlay-source.json').exists())

    def test_all_unbound_details_keep_cap_failure_honest_and_preserve_full_logs(self):
        with tempfile.TemporaryDirectory() as folder:
            original,_=write_scale_reports(folder)
            original.update(status='failed',error='Primary diagnostic failure survives finalization')
            for run in original['runs']:(Path(folder)/harness.scale_report_name(run['scale'],frozen=False)).unlink()
            aggregate,blocks=harness.aggregate_evidence(original,folder,frozen=False)
            self.assertTrue(all('detail' in run for run in aggregate['runs']))
            with self.assertRaisesRegex(AssertionError,'metadata budget'):runtime.report_payload(aggregate)
            destination=Path(folder)/'windows-wgc-visible-overlay-source.json'
            destination.write_text('{"status":"passed"}')
            output=io.StringIO()
            with redirect_stdout(output):self.assertEqual(harness.finish_reports(original,folder,frozen=False),1)
            self.assertFalse(destination.exists())
            self.assertIn(original['error'],output.getvalue())
            self.assertEqual(output.getvalue().count('Complete bounded visible-overlay scale evidence:'),3)
            for run,(_,complete) in zip(original['runs'],blocks):
                self.assertEqual(json.loads(complete),run['detail'])

    def test_oversized_inline_detail_removes_stale_receipt_before_aggregation(self):
        with tempfile.TemporaryDirectory() as folder:
            original,_=write_scale_reports(folder,count=1)
            original.update(status='failed',error='Keep the original native failure')
            original['runs'][0]['detail']['oversized_evidence']='x'*runtime.MAX_REPORT_BYTES
            destination=Path(folder)/'windows-wgc-visible-overlay-source.json'
            destination.write_text('{"status":"passed"}')
            output=io.StringIO()
            with redirect_stdout(output):self.assertEqual(harness.finish_reports(original,folder,frozen=False),1)
            self.assertFalse(destination.exists());self.assertEqual(original['status'],'failed')
            self.assertEqual(original['error'],'Keep the original native failure')
            self.assertIn(original['error'],output.getvalue());self.assertIn('metadata budget',output.getvalue())
            self.assertEqual(len(original['runs'][0]['detail']['oversized_evidence']),runtime.MAX_REPORT_BYTES)

    def test_interruption_still_finalizes_evidence_without_suppressing_interrupt(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(harness,'os',SimpleNamespace(name='nt',environ={})), \
                 patch('scripts.build_windows.verify_source_checkout',side_effect=KeyboardInterrupt), \
                 redirect_stdout(io.StringIO()),self.assertRaises(KeyboardInterrupt):
                harness.main(['--reports',folder])
            report=json.loads((Path(folder)/'windows-wgc-visible-overlay-source.json').read_text())
            self.assertEqual(report['status'],'failed');self.assertEqual(report['runs'],[])

    def test_non_windows_diagnostic_fails_with_truthful_report(self):
        if sys.platform=='win32':self.skipTest('Portable rejection test')
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'report.json'
            self.assertEqual(runtime.run(path),1)
            result=json.loads(path.read_text())
            self.assertEqual(result['status'],'failed');self.assertNotIn('pixel_exclusion_passed',result)


if __name__=='__main__':unittest.main()

"""Run the test-only source/frozen v2 fixture on a real Windows desktop.

No production entrypoint/spec/workflow changes. A passing report means the named
owned-window checks passed, not production readiness or proof of zero idle CPU
readback. The remaining instrumentation/GPU/OS-latency limitations are mandatory
report fields and must never be collapsed into an unconditional safety claim.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
from app_version import __version__
from scripts.build_wgc_session_capture import SOURCE_FILES,validate_manifest,verify_built_helper,verify_archive
from wgc_session_smoke import CHECK_FIELDS,SCOPE,LIMITATIONS
from windows_exe_smoke import isolated_windows_environment,smoke_workspace,terminate_tree
SCALES=(1,1.5,2)
MAX_REPORT_BYTES=256*1024
NATIVE_REJECTIONS=('native_roi_rejected','native_generation_rejected','native_duplicate_id_rejected','native_pipeline_rejected')
NEGATIVES=('outside_overlay_request_rejected','visible_overlay_request_rejected','process_identity_rejected','hwnd_retarget_rejected',
    'cancel_before_launch_passed','cancel_during_wait_passed','request_deadline_passed',*NATIVE_REJECTIONS)
TRANSITIONS=('outside_overlay_request_rejected','visible_overlay_request_rejected','other_same_process_occluder_rejected',
    'layered_same_process_occluder_rejected','focus_loss_rejected','geometry_change_rejected',
    'target_hide_rejected','overlay_style_rejected','overlay_affinity_rejected','overlay_registration_rejected',
    'process_identity_rejected','hwnd_retarget_rejected',*NATIVE_REJECTIONS,'stop','native_stop_passed',
    'pipe_eof_passed','job_close_passed','idle_lease_passed','cancel_during_wait_passed',
    'request_deadline_passed','overlay_destroy_rejected','target_destroy_rejected')


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def finite(value,low=0,high=math.inf):
    return type(value) in (int,float) and math.isfinite(value) and low<=value<=high


def positive_int(value):
    return type(value)is int and 0<value<2**63


def strict_roi(value,expected):
    return type(value)is list and len(value)==4 and all(type(item)is int for item in value) and value==expected


def validate_overlay_rendering(value):
    """Bind the explicitly different fixture renderer, without promoting its probe."""
    from wgc_session_capture import REQUIRED_OVERLAY_STYLE
    active='qt-opaque-redirected-v1';probe='qt-translucent-comparison-v1'
    roles=('translucent-probe','registered-overlay','lookalike-occluder')
    summary_names=('translucent_probe','registered_overlay','lookalike_occluder')
    stages=('created-hidden','realized-visible','verified-hidden')
    qt_fields={'qt_translucent_background','qt_opaque_paint_event','qt_surface_has_alpha',
               'qt_surface_alpha_buffer_size','qt_opacity'}
    native_fields={'stage','is_window','top_level','visible','owner_query_ok','owner_is_self',
        'owner_winerror','style','extended_style','expected_extended_style','dwm_hresult',
        'dwm_composing','set_attempted','set_ok','set_winerror','affinity_query_ok',
        'affinity_winerror','affinity','role','hwnd_unchanged','profile',
        'layered_attributes_query_ok','layered_attributes_winerror','layered_color_key',
        'layered_alpha','layered_flags'}
    flags={'is_window','top_level','visible','owner_query_ok','owner_is_self','dwm_composing',
           'set_attempted','set_ok','affinity_query_ok','hwnd_unchanged','layered_attributes_query_ok'}
    uints={'owner_winerror','style','extended_style','expected_extended_style','dwm_hresult',
           'set_winerror','affinity_winerror','affinity','layered_attributes_winerror',
           'layered_color_key','layered_flags'}
    rendering=value.get('overlay_rendering')
    if (type(rendering)is not dict or set(rendering)!={'active_profile','selection',
            'production_translucent_compatibility_proven',*summary_names}
        or rendering['active_profile']!=active or rendering['selection']!='preselected-before-probe'
        or rendering['production_translucent_compatibility_proven']is not False):
        raise RuntimeError('Explicit opaque experiment profile or translucent limitation missing')
    rows=value.get('overlay_setup')
    if type(rows)is not list or len(rows)!=9:
        raise RuntimeError('Complete three-profile overlay setup observations required')
    for role_index,(role,name) in enumerate(zip(roles,summary_names)):
        expected_profile=probe if role_index==0 else active
        summary=rendering[name]
        extra={'exclusion_available','destroyed_before_registration'}if role_index==0 else set()
        if (type(summary)is not dict or set(summary)!={'profile',*qt_fields,*extra}
            or summary.get('profile')!=expected_profile):
            raise RuntimeError('Overlay renderer summary schema/profile differs')
        observations=rows[role_index*3:role_index*3+3]
        expected_style=base_style=None
        for stage_index,(row,stage) in enumerate(zip(observations,stages)):
            if (type(row)is not dict or set(row)!=native_fields|qt_fields or row.get('role')!=role
                or row.get('stage')!=stage or row.get('profile')!=expected_profile):
                raise RuntimeError('Overlay setup role/order/schema differs')
            if (any(type(row[key])is not bool for key in flags)
                or any(type(row[key])is not int or not 0<=row[key]<2**32 for key in uints)
                or type(row['layered_alpha'])is not int or not 0<=row['layered_alpha']<=255):
                raise RuntimeError('Overlay setup native metadata types differ')
            if (any(row[key]is not True for key in ('is_window','top_level','owner_query_ok',
                   'owner_is_self','dwm_composing','hwnd_unchanged'))
                or row['dwm_hresult']>=2**31 or row['visible']is not (stage_index==1)
                or row['set_attempted']is not (stage_index<2)):
                raise RuntimeError('Overlay identity/composition/lifecycle evidence invalid')
            if stage_index==2 and (row['set_ok']is not False or row['set_winerror']!=0):
                raise RuntimeError('Hidden observation unexpectedly modified affinity')
            style=row['extended_style']
            if (style!=row['expected_extended_style'] or style & REQUIRED_OVERLAY_STYLE!=REQUIRED_OVERLAY_STYLE
                or style & 0x00200000):
                raise RuntimeError('Opaque experiment weakened full overlay native styles')
            if not row['style'] & 0x80000000 or row['style'] & 0x40c40000:
                raise RuntimeError('Overlay is not the declared frameless top-level popup')
            if expected_style is None:expected_style=style;base_style=row['style']&~0x10000000
            if style!=expected_style or row['style']&~0x10000000!=base_style:
                raise RuntimeError('Overlay style changed during setup')
            if (any(type(row[key])is not bool for key in ('qt_translucent_background',
                    'qt_opaque_paint_event','qt_surface_has_alpha'))
                or type(row['qt_surface_alpha_buffer_size'])is not int
                or not -1<=row['qt_surface_alpha_buffer_size']<=64
                or row['qt_surface_has_alpha']is not (row['qt_surface_alpha_buffer_size']>0)
                or not finite(row['qt_opacity'],1,1)):
                raise RuntimeError('Actual Qt renderer observations invalid')
            if role_index==0:
                if (row['qt_translucent_background']is not True or row['qt_opaque_paint_event']is not False
                    or stage_index>0 and row['qt_surface_has_alpha']is not True):
                    raise RuntimeError('Translucent probe did not test its declared Qt renderer')
            elif (row['qt_translucent_background']is not False or row['qt_opaque_paint_event']is not True
                  or row['qt_surface_has_alpha']is not False
                  or row['layered_attributes_query_ok']is not True or row['layered_alpha']!=255
                  or row['layered_flags']!=2 or row['layered_color_key']!=0):
                raise RuntimeError('Active renderer lacks exact opaque redirected attributes')
        shown,hidden=observations[1:]
        if any(hidden[key]!=shown[key] or type(hidden[key])is not type(shown[key]) for key in qt_fields):
            raise RuntimeError('Qt renderer changed between realized and hidden observations')
        available=(shown['set_ok'] and shown['affinity_query_ok'] and shown['affinity']==0x11
                   and hidden['affinity_query_ok'] and hidden['affinity']==0x11)
        if any(summary[key]!=shown[key] or type(summary[key])is not type(shown[key]) for key in qt_fields):
            raise RuntimeError('Overlay renderer summary differs from realized observations')
        if role_index==0:
            if summary['exclusion_available']is not available or summary['destroyed_before_registration']is not True:
                raise RuntimeError('Translucent probe outcome/destruction evidence differs')
        elif not available:
            raise RuntimeError('Active opaque overlay must retain exact capture exclusion')


def validate_report(value,*,frozen,scale,helper_build,version=__version__):
    if (not isinstance(value,dict) or value.get('status')!='passed' or 'error'in value
        or type(value.get('schema_version'))is not int or value['schema_version']!=1
        or value.get('frozen')is not frozen or value.get('applicationVersion')!=version
        or value.get('qt_platform')!='windows' or value.get('scope')!=SCOPE
        or value.get('limitations')!=LIMITATIONS):
        raise RuntimeError('Missing scoped native Windows session evidence or mandatory limitations')
    validate_overlay_rendering(value)
    if not positive_int(value.get('helper_process_count')) or value['helper_process_count']<20:
        raise RuntimeError('Owned helper lifecycle inventory incomplete')
    for field in CHECK_FIELDS:
        if value.get(field)is not True:raise RuntimeError('Missing mandatory session check: '+field)
    for field in ('requested_app_scale','measured_qt_scale'):
        if not finite(value.get(field)) or abs(value[field]-scale)>.01:
            raise RuntimeError('Session physical Qt scale differs')
    helper=value.get('helper',{})
    if helper!={'manifest':helper_build,'sha256':helper_build['sha256'],'size':helper_build['size']}:
        raise RuntimeError('Actual session helper bytes/source manifest differ')
    validate_manifest(helper_build)
    rect=value.get('client_rect')
    if (type(rect)is not dict or set(rect)!={'x','y','width','height'}
        or any(type(v)is not int for v in rect.values())
        or (rect['width'],rect['height'])!=(round(320*scale),round(240*scale))):
        raise RuntimeError('Session client physical geometry differs')
    roi=[rect['width']//4,rect['height']//4,rect['width']//2,rect['height']//2]
    if not strict_roi(value.get('roi'),roi):raise RuntimeError('Required strict integer bounded ROI missing')
    requests=value.get('requests')
    if type(requests)is not list or len(requests)!=4:raise RuntimeError('Four repeated session requests required')
    previous=None
    for row in requests:
        if (type(row)is not dict or not strict_roi(row.get('roi'),roi) or not finite(row.get('mean_channel_error'),0,2)
            or not finite(row.get('elapsed_ms'),0,3500)
            or any(not positive_int(row.get(key)) for key in ('helper_pid','helper_created','session_generation',
                'request_id','request_cutoff_100ns','frame_100ns','idle_enter_100ns'))
            or not row['request_cutoff_100ns']<row['frame_100ns']<=row['idle_enter_100ns']):
            raise RuntimeError('Malformed session pixel/fresh-frame evidence')
        if previous and (any(row[key]!=previous[key] for key in ('helper_pid','helper_created','session_generation'))
            or row['request_id']<=previous['request_id'] or row['request_cutoff_100ns']<=previous['frame_100ns']):
            raise RuntimeError('Helper replaced, request duplicated or stale frame reused')
        previous=row
    static=value.get('static_requests')
    if type(static)is not list or len(static)!=3:
        raise RuntimeError('Three truly static-window fresh requests are required')
    previous=None
    for row in static:
        if (type(row)is not dict or not strict_roi(row.get('roi'),roi) or not finite(row.get('mean_channel_error'),0,2)
            or not finite(row.get('elapsed_ms'),0,3500)
            or any(not positive_int(row.get(key)) for key in ('helper_pid','helper_created','session_generation',
                'request_id','request_cutoff_100ns','frame_100ns','idle_enter_100ns'))
            or not row['request_cutoff_100ns']<row['frame_100ns']<=row['idle_enter_100ns']):
            raise RuntimeError('Static-window fresh-frame evidence malformed')
        if previous and (any(row[key]!=previous[key] for key in ('helper_pid','helper_created','session_generation'))
            or row['request_id']<=previous['request_id'] or row['request_cutoff_100ns']<=previous['frame_100ns']):
            raise RuntimeError('Static-window session replaced or stale frame accepted')
        previous=row
    if 'static_frame_failure' in value:
        raise RuntimeError('Static-window failure cannot be promoted to passing evidence')
    negatives=value.get('negative_results',{})
    if type(negatives)is not dict:raise RuntimeError('Negative request evidence missing')
    expected={'cancel_before_launch_passed':{'cancelled'},'cancel_during_wait_passed':{'cancelled'},
        'request_deadline_passed':{'timeout'},'process_identity_rejected':{'stale'},'hwnd_retarget_rejected':{'stale'},
        'visible_overlay_request_rejected':{'stale','invalid-reply'},
        'outside_overlay_request_rejected':{'stale','invalid-reply'},
        **{name:{'backend-error','invalid-reply','stale'} for name in NATIVE_REJECTIONS}}
    for name in NEGATIVES:
        row=negatives.get(name,{})
        if row.get('status')not in expected[name] or not finite(row.get('elapsed_ms'),0,3500):
            raise RuntimeError('Unbounded or incorrect negative result: '+name)
    rows=value.get('transitions')
    if type(rows)is not list or len(rows)>80:raise RuntimeError('Measured retirement evidence missing')
    by_case={}
    for row in rows:
        if (type(row)is not dict or type(row.get('case'))is not str or not positive_int(row.get('helper_pid'))
            or type(row.get('exit_code'))is not int or not -(2**31)<=row['exit_code']<2**32
            or any(row.get(key)is not True for key in ('job_closed','io_done','stderr_done','threads_exited','pipes_closed'))
            or any(not finite(row.get(key),0,6000) for key in ('revoked_ms','process_exit_ms','cleanup_ms'))
            or row.get('observed_exit_within_50ms')is not (row['process_exit_ms']<=50)
            or row['cleanup_ms']<max(row['revoked_ms'],row['process_exit_ms'])):
            raise RuntimeError('Malformed cleanup observation, leaked ownership, or invented latency claim')
        by_case.setdefault(row['case'],[]).append(row)
    for name in TRANSITIONS:
        if len(by_case.get(name,()))!=1:raise RuntimeError('Exact retirement case missing/duplicated: '+name)
    lease=by_case['idle_lease_passed'][0]
    if not 3000<=lease['process_exit_ms']<=5500:raise RuntimeError('Four-second lease observation missing')
    for name in ('native_stop_passed','pipe_eof_passed'):
        if by_case[name][0]['exit_code']!=0:raise RuntimeError('Native graceful shutdown did not occur')
    stop=by_case['stop'][0]
    if not finite(stop.get('close_call_ms'),0,250):raise RuntimeError('Stop caller responsiveness missing')
    job=value.get('suspended_job_close_observation',{})
    if (type(job.get('wait_result'))is not int or job['wait_result']!=0
        or not finite(job.get('elapsed_ms'),0,3500)or not positive_int(job.get('helper_pid'))
        or type(job.get('exit_code'))is not int or not 0<=job['exit_code']<2**32
        or job.get('job_closed')is not True or job.get('never_resumed')is not True
        or job.get('start_gate_released')is not False):
        raise RuntimeError('Suspended exact helper Job-close mechanism evidence missing')
    parent=value.get('parent_death_observation',{})
    if (type(parent.get('wait_result'))is not int or parent['wait_result']!=0
        or not finite(parent.get('elapsed_ms'),0,3500) or parent.get('exact_handle_observed')is not True
        or parent.get('helper_sha256')!=helper_build['sha256']
        or parent.get('scope')!='parent-death-eventual-cleanup'
        or parent.get('owner_ancestry_verified')is not True or parent.get('helper_ancestry_verified')is not True
        or any(not positive_int(parent.get(key)) for key in ('owner_pid','owner_created','helper_pid','helper_created','popen_pid','popen_created'))):
        raise RuntimeError('Exact owned parent-death/Job cleanup observation missing')
    if (parent['helper_pid'] in (parent['owner_pid'],parent['popen_pid'])
        or parent['helper_created']<parent['owner_created']):
        raise RuntimeError('Recorded helper ancestry/creation contradicts the owned parent')
    if frozen:
        if parent['owner_pid']==parent['popen_pid'] or parent['owner_created']<parent['popen_created']:
            raise RuntimeError('Frozen owner must be a later distinct child of the exact Popen bootloader')
    elif parent['owner_pid']!=parent['popen_pid'] or parent['owner_created']!=parent['popen_created']:
        raise RuntimeError('Source owner must be the exact creation-bound Popen process')
    return value


def child_environment(environ,work,scale,*,frozen):
    env=isolated_windows_environment(environ,work) if frozen else dict(environ)
    for key in tuple(env):
        if key.upper().startswith(('QT_','PYSIDE_','_PYI_')):env.pop(key)
    env.update(QT_SCALE_FACTOR=str(scale),QT_QPA_PLATFORM='windows',PYINSTALLER_RESET_ENVIRONMENT='1',
               VGA_STATE_DIR=str(work/'state'),LOCALAPPDATA=str(work/'local-appdata'))
    return env


def read_report(path):
    path=Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size>MAX_REPORT_BYTES:
        raise RuntimeError('Bounded session report missing')
    def unique(pairs):
        value={}
        for key,item in pairs:
            if key in value:raise ValueError('Duplicate report key')
            value[key]=item
        return value
    def invalid_constant(value):raise ValueError('Non-finite JSON constant')
    value=json.loads(path.read_text(encoding='utf-8'),object_pairs_hook=unique,parse_constant=invalid_constant)
    if type(value)is not dict:raise RuntimeError('Session report must be an object')
    return value


def summary_native_diagnostic(value):
    """Carry only the session parser's bounded allowlisted failure metadata."""
    from wgc_session_capture import decode_session_diagnostic
    if type(value)is not dict:return None
    try:
        data=json.dumps(value,ensure_ascii=True,allow_nan=False).encode('ascii')
        return decode_session_diagnostic(data,value.get('code'))
    except (TypeError,ValueError,RecursionError):
        return None


def summarize(reports):
    """Print and persist bounded metadata even when an earlier Windows step failed."""
    reports=Path(reports);reports.mkdir(parents=True,exist_ok=True)
    result={'schema_version':1,'status':'failed','scope':SCOPE,'limitations':dict(LIMITATIONS),
            'files':{},'runs':[],'errors':[]}
    evidence={}
    for name in ('windows-wgc-session-build.json','windows-wgc-session-frozen-build.json',
                 'windows-wgc-session-source.json','windows-wgc-session-frozen.json'):
        try:
            evidence[name]=read_report(reports/name)
            result['files'][name]={'sha256':sha256(reports/name),'size':(reports/name).stat().st_size,
                                  'status':evidence[name].get('status')}
        except Exception as error:result['errors'].append(name+': '+str(error)[:500])
    proof=evidence.get('windows-wgc-session-build.json',{})
    valid_proof=False
    try:
        validate_manifest(proof);valid_proof=True
    except Exception as error:result['errors'].append('native build: '+str(error)[:500])
    expected_sources={name:row['sha256']for name,row in proof['source_files'].items()}if valid_proof else {}
    if proof.get('status')=='passed':
        result.update(helper_sha256=proof.get('sha256'),source_commit=proof.get('source_commit'),
                      source_sha256=proof.get('source_sha256'),build_recipe_sha256=proof.get('build_recipe_sha256'))
    frozen_container=evidence.get('windows-wgc-session-frozen-build.json',{})
    if frozen_container.get('status')!='passed' or 'error' in frozen_container:
        result['errors'].append('Standalone frozen build failed or is missing')
    frozen_build=frozen_container.get('diagnostic',{})
    if type(frozen_build)is not dict:frozen_build={}
    if (frozen_build.get('helper')!=proof or frozen_build.get('test_only')is not True
        or frozen_build.get('production_enabled')is not False
        or frozen_build.get('source_commit')!=proof.get('source_commit')
        or type(frozen_build.get('sha256'))is not str or len(frozen_build['sha256'])!=64
        or any(c not in '0123456789abcdef'for c in frozen_build['sha256'])
        or not positive_int(frozen_build.get('size'))):
        result['errors'].append('Frozen diagnostic is missing exact helper/source binding')
    result['diagnostic']=frozen_build
    for frozen in (False,True):
        name='windows-wgc-session-'+('frozen'if frozen else 'source')+'.json'
        report=evidence.get(name,{})
        if (report.get('status')!='passed' or 'error'in report or report.get('helper_build')!=proof
            or report.get('source_commit')!=proof.get('source_commit')or report.get('frozen')is not frozen
            or report.get('limitations')!=LIMITATIONS or report.get('scope')!=SCOPE
            or report.get('scales')!=list(SCALES)
            or report.get('source_files')!=expected_sources):
            result['errors'].append(name+': source/build/acceptance failed: '+str(report.get('error','missing or changed evidence'))[:500])
        if frozen and (report.get('executable_sha256')!=frozen_build.get('sha256')
                       or report.get('executable_size')!=frozen_build.get('size')):
            result['errors'].append('Frozen acceptance executable differs from the standalone build')
        runs=report.get('runs',[])
        if not isinstance(runs,list)or len(runs)!=3:
            result['errors'].append(name+': all three scales are required');runs=runs if isinstance(runs,list)else []
        for index,row in enumerate(runs[:3]):
            if type(row)is not dict:row={}
            detail=row.get('detail',{});scale=SCALES[index]
            if type(detail)is not dict:detail={}
            try:
                if row.get('app_scale')!=scale:raise RuntimeError('Scale order differs')
                validate_report(detail,frozen=frozen,scale=scale,helper_build=proof)
            except Exception as error:result['errors'].append(name+' scale '+str(scale)+': '+str(error)[:500])
            transitions=detail.get('transitions',[])
            result['runs'].append({'frozen':frozen,'scale':scale,'status':detail.get('status'),
                'error':detail.get('error'),'requests':detail.get('requests',[]),
                'native_diagnostic':summary_native_diagnostic(detail.get('native_diagnostic')),
                'windows_version':detail.get('windows_version'),
                'overlay_rendering':detail.get('overlay_rendering'),
                'overlay_setup':detail.get('overlay_setup',[]),
                'static_requests':detail.get('static_requests',[]),'static_frame_failure':detail.get('static_frame_failure'),
                'transitions':transitions,'negative_results':detail.get('negative_results',{}),
                'parent_death_observation':detail.get('parent_death_observation'),
                'suspended_job_close_observation':detail.get('suspended_job_close_observation'),
                'checks':{field:detail.get(field)for field in CHECK_FIELDS}})
    if not result['errors']:result['status']='passed'
    payload=json.dumps(result,indent=2)+'\n'
    if len(payload.encode('utf-8'))>256*1024:raise RuntimeError('Summary exceeds metadata budget')
    (reports/'windows-wgc-session-summary.json').write_text(payload,encoding='utf-8')
    print(payload,flush=True)
    return 0 if result['status']=='passed'else 1


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exe',type=Path,help='Only the standalone WGC-Session-Diagnostic.exe')
    parser.add_argument('--reports',type=Path,default=ROOT/'reports')
    parser.add_argument('--summarize',action='store_true',help='Validate and print bounded source+frozen summary')
    args=parser.parse_args(argv)
    if args.summarize:
        if args.exe:parser.error('--summarize cannot run an executable')
        return summarize(args.reports)
    if os.name!='nt':raise SystemExit('Actual Windows required; Linux/offscreen cannot pass')
    reports=args.reports.resolve();reports.mkdir(parents=True,exist_ok=True)
    frozen=args.exe is not None;prefix='windows-wgc-session-'+('frozen' if frozen else 'source')
    result={'schema_version':1,'status':'failed','frozen':frozen,'scope':SCOPE,
            'limitations':dict(LIMITATIONS),'scales':list(SCALES),'runs':[]}
    try:
        from scripts.build_windows import verify_source_checkout
        commit=verify_source_checkout(ROOT,os.environ.get('GITHUB_SHA'))
        proof=verify_built_helper()
        if proof['source_commit']!=commit:raise RuntimeError('Helper source commit differs from tested fixture')
        result.update(source_commit=commit,helper_build=proof,source_files={name:sha256(ROOT/name)for name in SOURCE_FILES},
                      applicationVersion=__version__)
        original=args.exe.resolve(strict=True) if frozen else None
        if original:
            from PyInstaller.archive.readers import CArchiveReader
            verify_archive(CArchiveReader(str(original)),proof)
            result.update(executable_sha256=sha256(original),executable_size=original.stat().st_size)
        with smoke_workspace()as work:
            if frozen:
                executable=work/'WGC-Session-Diagnostic.exe';shutil.copyfile(original,executable)
                if sha256(executable)!=result['executable_sha256']:raise RuntimeError('Copied diagnostic bytes differ')
            for scale in SCALES:
                report=reports/(prefix+'-scale'+str(round(scale*100))+'.json');report.unlink(missing_ok=True)
                command=[str(executable)] if frozen else [sys.executable,str(ROOT/'wgc_session_diagnostic.py')]
                command+=['--report',str(report)]
                process=subprocess.Popen(command,cwd=work,env=child_environment(os.environ,work,scale,frozen=frozen),
                    stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                try:code=process.wait(timeout=180)
                finally:terminate_tree(process)
                detail=read_report(report);result['runs'].append({'app_scale':scale,'report':report.name,'detail':detail})
                if code:raise RuntimeError('Actual session diagnostic failed: '+str(detail.get('error',code))[:2000])
                validate_report(detail,frozen=frozen,scale=scale,helper_build=proof)
        if verify_source_checkout(ROOT,commit)!=commit:raise RuntimeError('Source changed during session acceptance')
        result['status']='passed';return 0
    except Exception as error:
        result['error']=str(error)[:3000];raise
    finally:
        (reports/(prefix+'.json')).write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
        print(json.dumps(result,indent=2),flush=True)


if __name__=='__main__':raise SystemExit(main())

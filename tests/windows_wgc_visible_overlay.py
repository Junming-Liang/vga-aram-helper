"""Run explicit real-product visible-overlay acceptance at 100/150/200% Qt scales.

This checks ordinary default construction without replacing the independent
strict-hidden acceptance diagnostics. Windows only.
"""
from __future__ import annotations
import argparse
import ctypes
from ctypes import wintypes as W
import hashlib
import json
import marshal
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import time
import types

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT));sys.path.insert(0, str(ROOT/'tests'))
from wgc_visible_overlay_smoke import SCALES, SCOPE, LIMITATIONS, SOURCE_FILES, NEGATIVES, NATIVE_NEGATIVE_EXIT_CODES, strict_timing, MAX_REPORT_BYTES, read_live_json, report_payload, SAMPLE_FORMAT
from wgc_session_smoke import write_report
from windows_wgc_session_capture import child_environment, read_report, positive_int, finite
from windows_exe_smoke import smoke_workspace, terminate_tree
from windows_ota_smoke import NativeJob
from windows_session_fixture import compile_fixture, fixture_argv, validate_ready, poll_owned_json
from scripts.build_wgc_session_capture import verify_built_helper
from app_version import __version__
from overlay_duty_contract import integer, number, CLEANUP_FIELDS


def sha256(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def digest(value):
    if type(value) is not str or re.fullmatch('[0-9a-f]{64}',value) is None:
        raise RuntimeError('Invalid SHA256 evidence')
    return value


def identity(row):
    return tuple(integer(row.get(key),key,minimum=1,maximum=(2**32-1 if key=='helper_pid' else 2**63-1))
                 for key in ('helper_pid','helper_created','session_generation'))


def rendered_report(payload, width=240):
    """Print the COMPLETE compact evidence with safe JSON-token line breaks.

    Never split a quoted string or omit raw sample/request records. Individual
    producer strings remain independently bounded by their existing limits.
    """
    lines=[];line=[];quoted=escaped=False
    for character in payload.strip():
        line.append(character)
        if quoted:
            if escaped:escaped=False
            elif character=='\\':escaped=True
            elif character=='"':quoted=False
        elif character=='"':quoted=True
        if not quoted and character in ',}]' and len(line)>=width:
            lines.append(''.join(line));line=[]
    if line:lines.append(''.join(line))
    return '\n'.join(lines)


def scale_report_name(scale, *, frozen):
    """Only runner-owned mode and one typed supported scale select a filename."""
    if type(frozen) is not bool or type(scale) not in (int,float) or scale not in SCALES:
        raise RuntimeError('Invalid fixed scale report identity')
    return 'windows-wgc-visible-overlay-'+('frozen' if frozen else 'source')+'-scale'+str(round(scale*100))+'.json'


def same_json(left, right):
    """JSON equality without bool/int/float coercion or signed-zero loss."""
    if type(left) is not type(right):return False
    if type(left) is dict:
        return (left.keys()==right.keys() and all(type(key) is str and same_json(value,right[key])
                                                for key,value in left.items()))
    if type(left) is list:return len(left)==len(right) and all(same_json(a,b) for a,b in zip(left,right))
    if type(left) is float:return left.hex()==right.hex() and left not in (float('inf'),float('-inf')) and left==left
    return type(left) in (str,int,bool,type(None)) and left==right


def read_bound_detail(run, reports, *, frozen):
    """Read the complete original report through a fixed local name and binding.

    References are portable with their reports directory. No path supplied by a
    report is ever opened; filename, exact bytes, and strict JSON are all checked.
    """
    name=scale_report_name(run.get('scale'),frozen=frozen)
    if 'detail_report' in run and (type(run['detail_report']) is not str or run['detail_report']!=name):
        raise RuntimeError('Scale report reference is not its fixed filename')
    expected_hash=digest(run.get('report_sha256'));size=run.get('report_size')
    if type(size) is not int or not 0<size<=MAX_REPORT_BYTES:raise RuntimeError('Invalid bounded scale report size')
    root=Path(reports)
    if root.is_symlink():raise RuntimeError('Reports directory is symlinked')
    path=root.resolve(strict=True)/name
    if path.is_symlink() or not path.is_file():raise RuntimeError('Fixed scale report missing or symlinked')
    with path.open('rb') as source:raw=source.read(MAX_REPORT_BYTES+1)
    if len(raw)!=size or hashlib.sha256(raw).hexdigest()!=expected_hash:
        raise RuntimeError('Fixed scale report bytes differ from original SHA256/size')
    def unique(pairs):
        value={}
        for key,item in pairs:
            if key in value:raise ValueError('Duplicate scale report key')
            value[key]=item
        return value
    def invalid(_):raise ValueError('Non-finite scale report constant')
    detail=json.loads(raw.decode('utf-8'),object_pairs_hook=unique,parse_constant=invalid)
    if type(detail) is not dict or not same_json(detail,detail):raise RuntimeError('Scale report is not strict JSON evidence')
    if (detail.get('frozen') is not frozen or any(not finite(detail.get(key)) or abs(detail[key]-run['scale'])>.01
            for key in ('requested_app_scale','measured_qt_scale'))):
        raise RuntimeError('Scale report mode/physical scale differs from fixed identity')
    return detail


def aggregate_evidence(result, reports, *, frozen):
    """Deduplicate only bound per-scale files; retain every full JSON log block.

    Per-scale raw files and their hashes stay unchanged. An unbound detail is
    retained inline and fails the run, including when the old aggregate cap then
    refuses serialization. A primary diagnostic error is never replaced.
    """
    aggregate=dict(result,runs=[]);blocks=[];failures=[];seen=set()
    if result.get('status')=='passed' and (result.get('frozen') is not frozen
            or not same_json(result.get('scales'),list(SCALES))
            or [row.get('scale') for row in result['runs']]!=list(SCALES)):
        failures.append('Passed aggregate requires its exact mode and complete ordered scale inventory')
    for index,original in enumerate(result['runs']):
        run=dict(original);aggregate['runs'].append(run)
        block=None
        if 'detail' in run:
            block=['inline scale report '+str(index+1),report_payload(run['detail'])];blocks.append(block)
        try:
            name=scale_report_name(run.get('scale'),frozen=frozen)
            if name in seen:raise RuntimeError('Duplicate fixed scale report')
            seen.add(name)
            if 'detail' not in run:raise RuntimeError('Complete scale report detail missing')
            # Keep the complete in-memory evidence even if the file changed.
            block[0]=name
            detail=read_bound_detail(run,reports,frozen=frozen)
            if not same_json(detail,run['detail']):raise RuntimeError('Scale report JSON differs from in-memory evidence')
            run.pop('detail');run['detail_report']=name
        except Exception as error:
            message=str(error)[:2000];run['report_binding_error']=message;failures.append(message)
    if failures:
        aggregate['status']='failed';aggregate['report_binding_errors']=failures
        if 'error' not in aggregate:aggregate['error']='Scale report evidence binding failed: '+failures[0]
    return aggregate,blocks


def code_fingerprint(code):
    """Normalize build paths only; preserve bytecode, constants and line tables."""
    if not isinstance(code, types.CodeType):raise RuntimeError('Expected bundled Python code')
    def normalize(value):
        return value.replace(co_filename='<exact-source>', co_consts=tuple(
            normalize(item) if isinstance(item, types.CodeType) else item for item in value.co_consts))
    return hashlib.sha256(marshal.dumps(normalize(code))).hexdigest()


def verify_product_modules(archive):
    pyz_name = next((name for name in archive.toc if name.lower().startswith('pyz') and name.endswith('.pyz')), None)
    if pyz_name is None:raise RuntimeError('Frozen product Python archive missing')
    pyz = archive.open_embedded_archive(pyz_name)
    proof = {}
    for name in ('wgc_visible_overlay_smoke','native_ui','native_smoke','screen_capture',
                 'persistent_capture_adapter','wgc_session_capture','owned_diagnostic_json',
                 'portrait_display','local_debug','selection_session'):
        expected = compile((ROOT/(name+'.py')).read_bytes(), '<exact-source>', 'exec', optimize=0,dont_inherit=True)
        actual = pyz.extract(name)
        if code_fingerprint(actual) != code_fingerprint(expected):
            raise RuntimeError('Frozen product module differs from source: '+name)
        proof[name] = dict(source_sha256=sha256(ROOT/(name+'.py')), code_sha256=code_fingerprint(actual))
    return proof


def validate_report(value, *, scale, frozen, helper, executable_sha256=None,
                    foreign_proof=None, foreign_fixture_sha256=None):
    if (type(value) is not dict or value.get('status') != 'passed' or 'error' in value
        or value.get('schema_version') != 1 or type(value.get('schema_version')) is not int
        or value.get('scope') != SCOPE or not same_json(value.get('limitations'),LIMITATIONS)
        or value.get('applicationVersion') != __version__ or value.get('frozen') is not frozen
        or value.get('qt_platform') != 'windows' or value.get('constructor') != 'ControlWindow()'
        or value.get('visible_capture_enabled') is not True
        or value.get('executable_sha256') != executable_sha256):
        raise RuntimeError('Missing exact ordinary-default real-product diagnostic identity')
    for field in ('requested_app_scale','measured_qt_scale'):
        if not finite(value.get(field)) or abs(value[field]-scale) > .01:raise RuntimeError('Physical Qt scale differs')
    if value.get('helper') != dict(manifest=helper,sha256=helper['sha256'],size=helper['size']):
        raise RuntimeError('Bundled native helper/source manifest differs')
    rendering=value.get('overlay_rendering',{})
    if (not finite(rendering.get('qt_opacity'),1,1) or rendering.get('qt_translucent_background') is not False
        or rendering.get('qt_opaque_paint_event') is not True or rendering.get('qt_surface_has_alpha') is not False
        or type(rendering.get('magenta_grid_samples')) is not int or rendering['magenta_grid_samples']<=20):
        raise RuntimeError('Actual bright opaque product rendering evidence missing')
    rect=value.get('client_rect',{})
    if (type(rect) is not dict or set(rect)!={'x','y','width','height'}
        or any(type(n) is not int for n in rect.values()) or (rect['width'],rect['height'])!=(960,600)):
        raise RuntimeError('Owned physical target size differs')
    target=value.get('target_identity')
    if (type(target) is not list or len(target)!=3 or any(not positive_int(n) for n in target[:2])
        or target[1]>=2**32 or type(target[2]) is not str or not 0<len(target[2])<=256):
        raise RuntimeError('Target HWND/PID/class binding malformed')
    if frozen:digest(value['executable_sha256'])
    for field in ('target_created','overlay_hwnd','control_hwnd'):
        if not positive_int(value.get(field)):raise RuntimeError('Live identity missing: '+field)
    rows=value.get('requests')
    if type(rows) is not list or not 4 <= len(rows) <= 64:raise RuntimeError('Bounded request inventory missing')
    cases={row.get('case'):row for row in rows if type(row) is dict and row.get('case')}
    expected=('cold-hidden','hidden-confirmation','visible-product-1','visible-product-2')
    if [row.get('case') for row in rows if type(row) is dict and row.get('case')] != list(expected):
        raise RuntimeError('Cold confirmation/product cases duplicated, reordered or missing')
    observed={}
    for row in rows:
        if type(row) is not dict or row.get('status') not in ('passed','rejected'):raise RuntimeError('Malformed request row')
        if '_png' in row or '_samples' in row:raise RuntimeError('Private pixel/sample buffers leaked into report')
        if row['status']=='rejected':continue
        if not strict_timing(row) or not finite(row.get('elapsed_ms'),0,3500):raise RuntimeError('Native freshness/caller bound differs')
        binding=identity(row)
        previous=observed.get(binding)
        if previous and (row['request_id']<=previous['request_id'] or row['request_cutoff_100ns']<=previous['frame_100ns']):
            raise RuntimeError('Duplicate or stale helper request')
        observed[binding]=row
        integer(row.get('paint_state'),'paint state',maximum=1);digest(row.get('pixels_sha256'))
        if row.get('backend')!='windows-graphics-capture-session':raise RuntimeError('Persistent row came from legacy backend')
        proof=row.get('observation',{})
        if (any(proof.get(key) is not True for key in ('helper_alive','overlay_registration_valid','overlay_opaque'))
            or proof.get('overlay_hwnd')!=value['overlay_hwnd'] or proof.get('overlay_affinity')!=17
            or identity(proof)!=binding
            or row.get('overlay_registration_valid') is not True or row.get('overlay_affinity')!=17):
            raise RuntimeError('Independent live exact owned overlay/helper proof missing')
        for key in ('overlay_hwnd','overlay_affinity','overlay_extended_style'):
            maximum=2**63-1 if key=='overlay_hwnd' else 2**32-1
            integer(row.get(key),key,minimum=1,maximum=maximum)
            integer(proof.get(key),'live '+key,minimum=1,maximum=maximum)
            if row[key]!=proof[key]:raise RuntimeError('Typed live overlay receipt differs')
        integer(row.get('parent_pid'),'parent PID',minimum=1,maximum=2**32-1)
        integer(row.get('overlay_owner_pid'),'overlay owner PID',minimum=1,maximum=2**32-1)
        if row['parent_pid']!=target[1]:raise RuntimeError('Overlay parent differs from owned target process')
        if (row.get('overlay_owner_pid')!=row.get('parent_pid') or not positive_int(row.get('parent_pid'))
            or row.get('overlay_extended_style')!=proof.get('overlay_extended_style')
            or type(row.get('overlay_extended_style')) is not int
            or row['overlay_extended_style'] & 0x080800a8 != 0x080800a8):
            raise RuntimeError('Exact overlay owner/full extended style proof missing')
        visible=row.get('visible_request')
        if type(visible) is not bool:raise RuntimeError('Capture mode not explicit')
        sampling=row.get('visibility',{})
        samples=integer(sampling.get('samples'),'samples',maximum=2000)
        for key in ('qt_hidden_samples','native_hidden_samples'):
            integer(sampling.get(key),key,maximum=samples)
        duration=integer(sampling.get('duration_us'),'sample duration',maximum=3500000)
        raw=sampling.get('samples_us')
        if type(raw) is not list or len(raw)!=samples or sampling.get('sample_format')!=SAMPLE_FORMAT:
            raise RuntimeError('Visibility sample inventory/encoding differs')
        last=0;qt_hidden=native_hidden=0
        for item in raw:
            if type(item) is not list or len(item)!=2 or type(item[1]) is not int or not 0<=item[1]<=3:
                raise RuntimeError('Visibility sample types differ')
            stamp=integer(item[0],'sample offset',maximum=duration)
            if stamp<last:raise RuntimeError('Visibility samples out of acquisition order')
            last=stamp;qt_hidden+=not bool(item[1]&2);native_hidden+=not bool(item[1]&1)
        edges=[0,*[item[0] for item in raw],duration]
        gap=number(sampling.get('max_sample_gap_ms'),'sample gap',maximum=150)
        if (gap!=round(max(b-a for a,b in zip(edges,edges[1:]))/1000,3)
            or qt_hidden!=sampling['qt_hidden_samples'] or native_hidden!=sampling['native_hidden_samples']
            or abs(row['elapsed_ms']-duration/1000)>.001):raise RuntimeError('Visibility count/edge coverage differs')
        integer(row.get('overlay_window_style'),'window style',maximum=2**32-1)
        if visible:
            integer(row.get('enrolled_window_style'),'enrolled window style',maximum=2**32-1)
            if (samples<2 or sampling.get('qt_hidden_samples')!=0
                or sampling.get('native_hidden_samples')!=0 or row.get('native_visible_before') is not True
                or row.get('native_visible_after') is not True or proof.get('native_visible') is not True
                or row.get('overlay_window_style')!=row.get('enrolled_window_style')):
                raise RuntimeError('Visible acquisition hid or changed exact enrolled overlay')
        elif row.get('native_visible_before') is not False or row.get('native_visible_after') is not False:
            raise RuntimeError('Strict-hidden request had a visible overlay')
    a,b,c,d=(cases[name] for name in expected)
    if (identity(a)!=identity(b) or identity(c)!=identity(d) or identity(b)==identity(c)
        or a['visible_request'] or b['visible_request'] or not c['visible_request'] or not d['visible_request']
        or a.get('product',{}).get('confirmed') is not False
        or b.get('product',{}).get('confirmed') is not True or b['product'].get('automatic_frames')!=2):
        raise RuntimeError('Actual cold confirmation / drained visible helper reuse differs')
    for row in (a,b,c,d):
        product=row.get('product',{})
        for key in ('automatic_frames','hide_events','show_events'):integer(product.get(key),'product '+key)
        for key in ('confirmed','overlay_visible'):
            if type(product.get(key)) is not bool:raise RuntimeError('Product flag type differs')
    for row in (c,d):
        product=row.get('product',{})
        if product.get('hide_events')!=0 or product.get('overlay_visible') is not True or product.get('confirmed') is not True:
            raise RuntimeError('Stable actual product result hid/reflowed or lost confirmation')
    for row in (b,c,d):
        product=row['product'];hero=product.get('hero');offered=product.get('offered')
        if (type(hero) is not str or not 0<len(hero)<=256 or type(offered) is not list or len(offered)!=3
            or any(type(name) is not str or not 0<len(name)<=256 for name in offered)
            or len(set(offered))!=3 or not same_json(hero,b['product']['hero'])
            or not same_json(offered,b['product']['offered'])):
            raise RuntimeError('Changed GUI pixels lost the accepted hero or ordered candidate trio')
    if (c['paint_state']!=0 or d['paint_state']!=1 or c['pixels_sha256']==d['pixels_sha256']):
        raise RuntimeError('Second visible GUI cycle did not acquire changed target pixels')
    pairs=value.get('pixel_pairs')
    if type(pairs) is not list or [(r.get('state'),r.get('placement')) for r in pairs]!=[(0,'titles'),(1,'hud'),(1,'titles')]:
        raise RuntimeError('Moving overlay deterministic/static pixel matrix missing')
    for pair in pairs:
        if type(pair) is not dict:raise RuntimeError('Pixel pair malformed')
        integer(pair.get('state'),'pair paint state',maximum=1)
        for key in ('max_channel_error','changed_pixels','hidden_magenta_pixels','visible_magenta_pixels'):
            integer(pair.get(key),key,maximum=960*600)
        number(pair.get('mean_channel_error'),'mean channel error',maximum=0)
        digest(pair.get('hidden_sha256'));digest(pair.get('visible_sha256'))
        bounds=pair.get('overlay_rect')
        if (type(bounds) is not list or len(bounds)!=4 or any(type(n) is not int for n in bounds)
            or not all(-32768<=n<=32768 for n in bounds[:2]) or not all(0<n<=4096 for n in bounds[2:])):
            raise RuntimeError('Pixel overlay placement malformed')
        roi_y=(rect['y']+round(600*.37)) if pair['placement']=='titles' else (rect['y']+round(600*.94))
        if not (bounds[0]<rect['x']+960 and bounds[0]+bounds[2]>rect['x']
                and bounds[1]<=roi_y<bounds[1]+bounds[3]):raise RuntimeError('Overlay did not overlap required title/HUD band')
        hidden_index=integer(pair.get('hidden_reference_index'),'hidden reference index',maximum=len(rows)-1)
        visible_index=integer(pair.get('request_index'),'visible reference index',maximum=len(rows)-1)
        hidden_row,visible_row=rows[hidden_index],rows[visible_index]
        if (hidden_index>=visible_index or hidden_row.get('status')!='passed' or hidden_row.get('visible_request') is not False
            or visible_row.get('status')!='passed' or visible_row.get('visible_request') is not True
            or hidden_row.get('paint_state')!=pair['state'] or visible_row.get('paint_state')!=pair['state']
            or hidden_row.get('pixels_sha256')!=pair['hidden_sha256'] or visible_row.get('pixels_sha256')!=pair['visible_sha256']):
            raise RuntimeError('Pixel equality not bound to corresponding real hidden/visible acquisitions')
        if (pair.get('max_channel_error')!=0 or pair.get('changed_pixels')!=0 or pair.get('mean_channel_error')!=0
            or pair.get('hidden_sha256')!=pair.get('visible_sha256')
            or pair.get('hidden_magenta_pixels')!=pair.get('visible_magenta_pixels')
            or type(pair.get('request_index')) is not int or not 0<=pair['request_index']<len(rows)
            or rows[pair['request_index']].get('visible_request') is not True):
            raise RuntimeError('Hidden-reference exact pixel exclusion failed')
    if pairs[0]['hidden_sha256']==pairs[1]['hidden_sha256']:raise RuntimeError('Changed target paint state was not tested')
    if c['pixels_sha256']!=pairs[0]['hidden_sha256'] or d['pixels_sha256']!=pairs[1]['hidden_sha256']:
        raise RuntimeError('Visible GUI changed pixels differ from exact hidden paint-state references')
    negatives=value.get('negative_results')
    if type(negatives) is not dict or set(negatives)!=set(NEGATIVES):raise RuntimeError('Negative matrix incomplete')
    injected={'owner_change','wrong_hwnd','active_affinity_change','cancel','stop'}
    rejected_indices=set()
    for name,row in negatives.items():
        if type(row) is not dict:raise RuntimeError('Negative row malformed')
        integer(row.get('fallback_calls'),'negative fallback count',maximum=0)
        integer(row.get('native_exit_code'),'native exit code',minimum=-(2**31),maximum=2**32-1)
        if identity(row) not in observed:raise RuntimeError('Negative helper was never observed alive')
        index=integer(row.get('request_index'),'negative request index',maximum=len(rows)-1)
        rejected=rows[index]
        if (index in rejected_indices or rejected.get('status')!='rejected' or rejected.get('negative_case')!=name
            or rejected.get('visible_request') is not True or identity(rejected)!=identity(row)):
            raise RuntimeError('Negative is not bound to its exact rejected request: '+name)
        rejected_indices.add(index)
        for key in ('capture_start_100ns','capture_return_100ns'):
            integer(row.get(key),key,minimum=1,maximum=2**63-1)
            integer(rejected.get(key),'rejected '+key,minimum=1,maximum=2**63-1)
            if row[key]!=rejected[key]:raise RuntimeError('Rejected capture timestamp differs: '+name)
        if row['capture_return_100ns']<row['capture_start_100ns']:raise RuntimeError('Rejected capture interval reversed')
        if (type(row.get('mutation_100ns')) is not type(rejected.get('mutation_100ns'))
            or row.get('mutation_100ns')!=rejected.get('mutation_100ns')
            or type(row.get('request_id')) is not type(rejected.get('pending_exchange_request_id'))
            or row.get('request_id')!=rejected.get('pending_exchange_request_id')):
            raise RuntimeError('Negative mutation/exchange differs from rejected capture')
        if (type(row) is not dict or row.get('status')!='rejected' or row.get('fallback_calls')!=0
            or not positive_int(row.get('helper_pid')) or not positive_int(row.get('helper_created'))
            or row.get('actual_native_idle_rejection') is not (name not in injected)):
            raise RuntimeError('Negative native/product evidence mislabeled: '+name)
        if name not in injected:
            expected=NATIVE_NEGATIVE_EXIT_CODES[name]
            if row['native_exit_code']!=expected:
                raise RuntimeError(f'Native rejection exit differs for {name}: expected {expected}, observed {row["native_exit_code"]!r}')
        if name in ('active_affinity_change','cancel','stop'):
            if (row.get('actual_pending_native_exchange') is not True
                or not positive_int(row.get('mutation_100ns')) or not positive_int(row.get('request_id'))
                or not positive_int(row.get('capture_start_100ns'))
                or not row['capture_start_100ns']<=row['mutation_100ns']<=row['capture_return_100ns']):
                raise RuntimeError('Missing actual pending native exchange mutation: '+name)
        else:
            if row.get('request_id') is not None:raise RuntimeError('Pre-request denial invented a native exchange')
            if name=='foreign_pid_occluder':
                if row.get('mutation_100ns') is not None:raise RuntimeError('Foreign observation invented an exact mutation instant')
            elif (not positive_int(row.get('mutation_100ns')) or row['mutation_100ns']>row['capture_start_100ns']):
                raise RuntimeError('Idle mutation did not precede rejected capture')
    if rejected_indices!={i for i,row in enumerate(rows) if row.get('status')=='rejected'}:
        raise RuntimeError('Rejected request inventory not covered exactly once')
    foreign=negatives['foreign_pid_occluder']
    if type(foreign_proof) is not dict:raise RuntimeError('Independent outer foreign fixture proof missing')
    for inner,outer,limit in (('foreign_pid','pid',2**32-1),('foreign_hwnd','hwnd',2**63-1),
                              ('foreign_created','created',2**63-1)):
        integer(foreign.get(inner),inner,minimum=1,maximum=limit)
        integer(foreign_proof.get(outer),'outer '+outer,minimum=1,maximum=limit)
        if foreign[inner]!=foreign_proof[outer]:raise RuntimeError('Foreign fixture identity differs from outer owned Job')
    for key in ('launcher_pid','launcher_created','owner_pid','owner_created'):
        integer(foreign_proof.get(key),key,minimum=1,maximum=2**32-1 if key.endswith('pid') else 2**63-1)
    if (foreign['foreign_pid']==target[1] or foreign['foreign_hwnd']==target[0]
        or foreign.get('job_verified') is not True or foreign_proof.get('job_verified') is not True
        or foreign_proof.get('owner_ancestry_verified') is not True
        or foreign_proof['owner_pid']!=target[1] or foreign_proof['owner_created']!=value['target_created']
        or (foreign_proof['launcher_pid']!=foreign_proof['owner_pid']) is not frozen
        or foreign_proof['launcher_created']>foreign_proof['owner_created']
        or not frozen and foreign_proof['launcher_created']!=foreign_proof['owner_created']):
        raise RuntimeError('Foreign Job or exact outer product ownership evidence differs')
    if not (digest(foreign.get('foreign_fixture_sha256'))==digest(foreign_proof.get('executable_sha256'))
            ==digest(foreign_fixture_sha256)):
        raise RuntimeError('Foreign fixture does not match externally built exact bytes')
    if negatives['stop'].get('late_result_discarded') is not True or negatives['stop'].get('gui_restart_after_stop') is not False:
        raise RuntimeError('Actual GUI Stop did not discard late work or restarted')
    transitions=value.get('transitions')
    if type(transitions) is not list or not transitions or len(transitions)>64:raise RuntimeError('Cleanup inventory missing')
    cleaned=set()
    for row in transitions:
        if type(row) is not dict or identity(row) not in observed:raise RuntimeError('Cleanup helper was never observed alive')
        cleaned.add(identity(row));number(row.get('observed_ms'),'cleanup observation',maximum=8000)
        integer(row.get('process_exit_code'),'cleanup exit code',minimum=-(2**31),maximum=2**32-1)
        if any(row.get(key) is not True for key in CLEANUP_FIELDS):
            raise RuntimeError('Exact helper/process/reader/Job cleanup incomplete')
    if cleaned!=set(observed):raise RuntimeError('An observed native owner lacks complete cleanup')
    if value.get('fallback_calls')!=['v1']:raise RuntimeError('Unexpected v1/GDI entry or missing hidden compatibility capture')
    for field in ('product_helper_reuse_passed','pixel_exclusion_passed','hidden_compatibility_passed',
                  'helpers_exited_passed','pipe_readers_exited_passed','job_handles_closed_passed','windows_closed_passed'):
        if value.get(field) is not True:raise RuntimeError('Missing completed check: '+field)
    return value


def verify_launched_owner(data,process,*,frozen,executable):
    """Same Toolhelp parent check used by the existing owned parent-death test."""
    from session_windows import process_metadata,final_image_path
    pid=integer(data.get('pid'),'diagnostic owner PID',minimum=1,maximum=2**32-1)
    created=integer(data.get('created'),'diagnostic owner creation',minimum=1,maximum=2**63-1)
    if process.poll() is not None:raise RuntimeError('Outer owned launch exited before owner binding')
    launch=process_metadata(process.pid);owner=process_metadata(pid)
    if owner.created!=created or owner.path!=final_image_path(str(executable)):
        raise RuntimeError('Diagnostic owner image/creation differs from exact launch')
    if not frozen:
        if pid!=process.pid or owner.created!=launch.created:raise RuntimeError('Source diagnostic is not exact Popen child')
    else:
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        class Entry(ctypes.Structure):
            _fields_=[('dwSize',W.DWORD),('cntUsage',W.DWORD),('th32ProcessID',W.DWORD),
                ('th32DefaultHeapID',ctypes.c_size_t),('th32ModuleID',W.DWORD),('cntThreads',W.DWORD),
                ('th32ParentProcessID',W.DWORD),('pcPriClassBase',W.LONG),('dwFlags',W.DWORD),('szExeFile',W.WCHAR*260)]
        kernel.CreateToolhelp32Snapshot.argtypes=[W.DWORD,W.DWORD];kernel.CreateToolhelp32Snapshot.restype=W.HANDLE
        kernel.CloseHandle.argtypes=[W.HANDLE];kernel.CloseHandle.restype=W.BOOL
        for name in ('Process32FirstW','Process32NextW'):
            fn=getattr(kernel,name);fn.argtypes=[W.HANDLE,ctypes.POINTER(Entry)];fn.restype=W.BOOL
        snapshot=kernel.CreateToolhelp32Snapshot(2,0)
        if snapshot in (None,ctypes.c_void_p(-1).value):raise RuntimeError('Owned ancestry snapshot failed')
        parent=None
        try:
            entry=Entry();entry.dwSize=ctypes.sizeof(entry)
            found=kernel.Process32FirstW(snapshot,ctypes.byref(entry))
            while found:
                if entry.th32ProcessID==pid:parent=int(entry.th32ParentProcessID);break
                found=kernel.Process32NextW(snapshot,ctypes.byref(entry))
        finally:kernel.CloseHandle(snapshot)
        if (pid==process.pid or parent!=process.pid or owner.created<launch.created
            or launch.path!=owner.path):raise RuntimeError('Frozen owner is not exact live bootloader child')
    if process.poll() is not None or process_metadata(pid)!=owner:raise RuntimeError('Owner exited or changed during ancestry binding')
    return dict(launcher_pid=process.pid,launcher_created=launch.created,owner_pid=pid,
                owner_created=created,owner_ancestry_verified=True)


def coordinate_foreign(report, fixture, work, env, job, process, end,*,frozen,executable):
    """Drive only the one exact fixture created suspended in this private Job."""
    from session_windows import process_metadata
    request=report.with_suffix('.foreign-request.json');ready=report.with_suffix('.foreign-ready.json')
    release=report.with_suffix('.foreign-release.json');state=None
    while process.poll() is None:
        if time.monotonic()>=end:raise RuntimeError('Product diagnostic exceeded existing 180-second run bound')
        data=poll_owned_json(request,read_live_json) if state is None else None
        if data is not None:
            launch_proof=verify_launched_owner(data,process,frozen=frozen,executable=executable)
            rect=data['rect'];x,y=rect['x']+40,rect['y']+40
            png=work/'occluder.png'
            from PIL import Image
            Image.new('RGB',(80,80),(23,240,240)).save(png)
            evidence=work/(report.stem+'-foreign-window.json')
            argv=fixture_argv(fixture['game_exe'],'game',png,evidence,x=x,y=y,width=80,height=80,lifetime=30,no_activate=True)
            child=job.spawn(argv[0],argv[1:],env,work)
            until=min(end,time.monotonic()+8);published=None
            while published is None:
                if time.monotonic()>=until or job.poll(child) is not None:raise RuntimeError('Owned foreign fixture did not paint')
                published=poll_owned_json(evidence,read_live_json);time.sleep(.01)
            window=validate_ready(published,role='game',pid=child['pid'],width=80,height=80)
            if child['pid'] not in job.pids() or job.image(child['pid'])!=os.path.normcase(os.path.abspath(fixture['game_exe'])):
                raise RuntimeError('Foreign fixture escaped exact Job/image ownership')
            meta=process_metadata(child['pid'])
            proof=dict(window,created=meta.created,job_verified=True,executable_sha256=fixture['executable_sha256'],**launch_proof)
            write_report(ready,proof)
            state=dict(process=child,window=window,proof=proof,closed=False)
        released=poll_owned_json(release,read_live_json) if state is not None and not state['closed'] else None
        if released is not None:
            if released!={'status':'release'}:raise RuntimeError('Owned fixture release malformed')
            if state['process']['pid'] not in job.pids():raise RuntimeError('Foreign fixture disappeared before owned cleanup')
            job.close_window(state['window']);job.wait_exit(state['process'],min(end,time.monotonic()+8))
            state['closed']=True
        time.sleep(.01)
    if state is None or not state['closed']:raise RuntimeError('Foreign owned fixture check/cleanup incomplete')
    return state['proof']


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exe',type=Path,help='Exact frozen product VGA EXE; omit for source')
    parser.add_argument('--reports',type=Path,default=ROOT/'reports')
    args=parser.parse_args(argv)
    if os.name!='nt':raise SystemExit('Actual Windows desktop required; Linux/offscreen cannot pass')
    reports=args.reports.resolve();reports.mkdir(parents=True,exist_ok=True)
    frozen=args.exe is not None;name='windows-wgc-visible-overlay-'+('frozen' if frozen else 'source')
    result=dict(status='failed',scope=SCOPE,applicationVersion=__version__,frozen=frozen,scales=list(SCALES),runs=[])
    try:
        from scripts.build_windows import verify_source_checkout,verify_application_archive
        commit=verify_source_checkout(ROOT,os.environ.get('GITHUB_SHA'));helper=verify_built_helper()
        if helper['source_commit']!=commit:raise RuntimeError('Helper was built from another source commit')
        result.update(source_commit=commit,helper_build=helper,source_files={path:sha256(ROOT/path) for path in SOURCE_FILES})
        original=args.exe.resolve(strict=True) if frozen else None
        if original:
            from PyInstaller.archive.readers import CArchiveReader
            archive=CArchiveReader(str(original))
            result.update(executable_sha256=sha256(original),executable_size=original.stat().st_size,
                archive_inventory=verify_application_archive(archive,session_build=helper),
                product_modules=verify_product_modules(archive))
        with smoke_workspace() as work:
            fixture=compile_fixture(work/'foreign-fixture')
            result['foreign_fixture']={key:fixture[key] for key in ('source_sha256','executable_sha256')}
            if original:
                executable=work/'VGA-Aram-Helper.exe';shutil.copyfile(original,executable)
                if sha256(executable)!=result['executable_sha256']:raise RuntimeError('Staged EXE changed bytes')
            for scale in SCALES:
                report=reports/scale_report_name(scale,frozen=frozen)
                for path in (report,*(report.with_suffix(suffix) for suffix in
                        ('.foreign-request.json','.foreign-ready.json','.foreign-release.json'))):path.unlink(missing_ok=True)
                env=child_environment(os.environ,work,scale,frozen=frozen)
                command=([str(executable)] if frozen else [sys.executable,str(ROOT/'launcher.py')])+['--wgc-visible-overlay-report',str(report)]
                job=NativeJob();process=None;failure=None;cleanup_errors=[]
                run=dict(scale=scale,coordination='failed');result['runs'].append(run)
                try:
                    process=subprocess.Popen(command,cwd=work,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                    foreign=coordinate_foreign(report,fixture,work,env,job,process,time.monotonic()+180,
                        frozen=frozen,executable=executable if frozen else sys.executable)
                    run.update(foreign=foreign,coordination='passed')
                    code=process.wait(timeout=5)
                    run['exit_code']=code
                    if code:raise RuntimeError('Actual product diagnostic exited with code '+str(code))
                except Exception as error:failure=error;run['coordination_error']=str(error)[:2000]
                finally:
                    try:
                        if process is not None:terminate_tree(process)
                    except Exception as error:cleanup_errors.append(str(error)[:1000])
                    try:job.cleanup()
                    except Exception as error:cleanup_errors.append(str(error)[:1000])
                    run['outer_cleanup_complete']=not cleanup_errors
                    if cleanup_errors:run['outer_cleanup_errors']=cleanup_errors
                    # Preserve the strict final report even if failure preceded
                    # the foreign handshake. Never treat a .tmp as completion.
                    try:
                        detail=read_report(report)
                        run.update(detail=detail,report_sha256=sha256(report),report_size=report.stat().st_size)
                    except Exception as error:
                        run['detail_error']=str(error)[:2000]
                        if failure is None:failure=error
                if failure is not None:
                    native_error=run.get('detail',{}).get('error')
                    raise RuntimeError(str(native_error or failure)) from failure
                if cleanup_errors:raise RuntimeError('Exact owned outer cleanup failed: '+ '; '.join(cleanup_errors))
                validate_report(run['detail'],scale=scale,frozen=frozen,helper=helper,
                                executable_sha256=result.get('executable_sha256'),
                                foreign_proof=run['foreign'],foreign_fixture_sha256=fixture['executable_sha256'])
                if original and sha256(executable)!=result['executable_sha256']:raise RuntimeError('Staged EXE changed during test')
        if original and sha256(original)!=result['executable_sha256']:raise RuntimeError('Original EXE changed during test')
        verify_source_checkout(ROOT,commit)
        result['status']='passed'
    except Exception as error:
        result['error']=str(error)[:3000]
    finally:
        exit_code=finish_reports(result,reports,frozen=frozen)
    return exit_code


def finish_reports(result, reports, *, frozen):
    """Finish diagnostics only after all evidence bindings and writes succeed."""
    name='windows-wgc-visible-overlay-'+('frozen' if frozen else 'source')
    reports=Path(reports)
    try:
        if reports.is_symlink():raise RuntimeError('Reports directory is symlinked')
        destination=reports/(name+'.json')
        if destination.is_symlink():raise RuntimeError('Aggregate report is symlinked')
        # Clear a stale receipt before aggregation, serialization, or printing
        # can fail, including an oversized inline detail in a failed run.
        destination.unlink(missing_ok=True)
        aggregate,blocks=aggregate_evidence(result,reports,frozen=frozen)
        result['status']=aggregate['status']
        if 'error' in aggregate:result['error']=aggregate['error']
        for filename,complete in blocks:
            print('Complete bounded visible-overlay scale evidence: '+filename,flush=True)
            print(rendered_report(complete),flush=True)
        payload=report_payload(aggregate)
        print(json.dumps(dict(status=result['status'],frozen=frozen,source_commit=result.get('source_commit'),
            report=name+'.json',report_bytes=len(payload.encode('utf-8')),error=result.get('error'),
            runs=[dict(scale=row['scale'],status=row.get('detail',{}).get('status'),
                requests=len(row.get('detail',{}).get('requests',[])),
                negatives=len(row.get('detail',{}).get('negative_results',{})),
                error=row.get('detail',{}).get('error') or row.get('coordination_error'))
                for row in result['runs']]),indent=2),flush=True)
        print('Complete bounded visible-overlay evidence follows:',flush=True)
        print(rendered_report(payload),flush=True)
        destination.write_text(payload,encoding='utf-8')
    except Exception as error:
        result['status']='failed'
        if result.get('error'):print('Primary diagnostic failure: '+result['error'],flush=True)
        print('Failed to preserve bounded visible-overlay aggregate: '+str(error),flush=True)
        return 1
    return 0 if result['status']=='passed' else 1


if __name__=='__main__':raise SystemExit(main())

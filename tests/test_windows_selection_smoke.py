"""Portable selection-harness contracts, never actual Windows handoff proof."""
import ast
import copy
import errno
import json
import os
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
import windows_selection_smoke as smoke
import selection_smoke as diagnostic


def replace_error(code=5):
    error=PermissionError(errno.EACCES,'Synthetic Windows report replace denial')
    error.winerror=code
    return error


def good_owned_focus(role='client', *, route='pair', source_role=None):
    ids={'client':(100,101,133000000000000001),'game':(500,501,133000000000000200),
         'controller':(600,601,133000000000000050)}
    def identity(role):
        hwnd,pid,created=ids[role]
        return dict(hwnd=hwnd,pid=pid,created=created,role=role)
    target=identity(role);source=identity(source_role or ('game' if role=='client' else 'client'))
    value=dict(route=route,target=target,focus=dict(sent=route!='already',result=1,
        api=None if route=='already' else True,drained=False,
        before=target['hwnd'] if route=='already' else source['hwnd'],after=target['hwnd']))
    if route!='already':value['source']=source
    return value


class SelectionReportWriterTests(unittest.TestCase):
    def payload(self,value):
        return (json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode('utf8')

    def test_transient_replace_denials_reuse_one_closed_complete_payload(self):
        for code in (5,32,33):
            for status in ('passed','failed'):
                with self.subTest(winerror=code,status=status),tempfile.TemporaryDirectory() as directory:
                    path=Path(directory)/'report.json';old={'status':'running','phase':'recovering-foreground'}
                    path.write_bytes(self.payload(old));value={'status':status,'text':'完整证据'}
                    if status=='failed':value.update(error='original failure',error_traceback='original trace')
                    payload=self.payload(value);sources=[];replace=Path.replace
                    def contended(source,target):
                        sources.append(source)
                        self.assertEqual(target,path)
                        self.assertEqual(source.parent,path.parent)
                        self.assertEqual(source.read_bytes(),payload)
                        self.assertEqual(path.read_bytes(),self.payload(old))
                        if len(sources)<3:raise replace_error(code)
                        return replace(source,target)
                    with patch.object(Path,'replace',autospec=True,side_effect=contended) as publish,\
                         patch.object(Path,'write_bytes',autospec=True,side_effect=Path.write_bytes) as write,\
                         patch.object(diagnostic,'time',SimpleNamespace(monotonic=lambda:0.,sleep=Mock())):
                        diagnostic.atomic_report(path,value)
                    self.assertEqual(publish.call_count,3);write.assert_called_once_with(sources[0],payload)
                    self.assertEqual(len(set(sources)),1)
                    self.assertEqual(path.read_bytes(),payload)
                    self.assertEqual(json.loads(path.read_bytes()),value)
                    self.assertEqual(list(Path(directory).iterdir()),[path])

    def test_permanent_denial_is_attempt_bounded_and_preserves_both_complete_reports(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'report.json';previous=self.payload({'status':'running'})
            path.write_bytes(previous);value={'status':'failed','error':'original evidence'};error=replace_error()
            sleep=Mock()
            with patch.object(Path,'replace',side_effect=error) as publish,\
                 patch.object(diagnostic,'time',SimpleNamespace(monotonic=lambda:0.,sleep=sleep)):
                with self.assertRaises(PermissionError) as caught:diagnostic.atomic_report(path,value)
            self.assertIs(caught.exception,error)
            self.assertEqual(publish.call_count,diagnostic._REPORT_REPLACE_ATTEMPTS)
            self.assertEqual(sleep.call_count,diagnostic._REPORT_REPLACE_ATTEMPTS-1)
            self.assertEqual(path.read_bytes(),previous)
            self.assertEqual(path.with_name(path.name+'.tmp').read_bytes(),self.payload(value))

    def test_replace_retry_respects_monotonic_cap_and_existing_deadline(self):
        for deadline,limit in ((None,.25),(.01,.01),(-1,0)):
            with self.subTest(deadline=deadline),tempfile.TemporaryDirectory() as directory:
                now=[0.];sleeps=[];error=replace_error(32)
                def sleep(seconds):sleeps.append(seconds);now[0]+=seconds
                with patch.object(Path,'replace',side_effect=error) as publish,\
                     patch.object(diagnostic,'time',SimpleNamespace(monotonic=lambda:now[0],sleep=sleep)):
                    with self.assertRaises(PermissionError) as caught:
                        diagnostic.atomic_report(Path(directory)/'report.json',{'status':'failed'},deadline=deadline)
                self.assertIs(caught.exception,error)
                self.assertLessEqual(sum(sleeps),limit)
                self.assertLessEqual(publish.call_count,diagnostic._REPORT_REPLACE_ATTEMPTS)
                if deadline is not None:self.assertEqual(publish.call_count,1)

    def test_retry_does_not_run_again_after_scheduler_overshoots_deadline(self):
        with tempfile.TemporaryDirectory() as directory:
            now=[0.]
            def sleep(_):now[0]=1.
            with patch.object(Path,'replace',side_effect=replace_error(33)) as publish,\
                 patch.object(diagnostic,'time',SimpleNamespace(monotonic=lambda:now[0],sleep=sleep)):
                with self.assertRaises(PermissionError):
                    diagnostic.atomic_report(Path(directory)/'report.json',{'status':'failed'})
            self.assertEqual(publish.call_count,1)

    def test_non_windows_or_unrelated_errors_are_never_retried(self):
        for error in (PermissionError(errno.EACCES,'Denied'),replace_error(2),OSError(errno.ENOSPC,'Full')):
            with self.subTest(error=error),tempfile.TemporaryDirectory() as directory:
                sleep=Mock()
                with patch.object(Path,'replace',side_effect=error) as publish,\
                     patch.object(diagnostic,'time',SimpleNamespace(monotonic=lambda:0.,sleep=sleep)):
                    with self.assertRaises(OSError) as caught:
                        diagnostic.atomic_report(Path(directory)/'report.json',{'status':'failed'})
                self.assertIs(caught.exception,error);publish.assert_called_once();sleep.assert_not_called()

    def test_serialization_and_temp_write_errors_are_not_retried(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'report.json';old=self.payload({'status':'running'});path.write_bytes(old)
            with patch.object(Path,'replace') as publish,patch.object(Path,'write_bytes') as write:
                with self.assertRaises(TypeError):diagnostic.atomic_report(path,{'invalid':object()})
                write.assert_not_called();publish.assert_not_called()
            with patch.object(Path,'replace') as publish,\
                 patch.object(Path,'write_bytes',side_effect=replace_error()) as write:
                with self.assertRaises(PermissionError):diagnostic.atomic_report(path,{'status':'failed'})
                write.assert_called_once();publish.assert_not_called()
            self.assertEqual(path.read_bytes(),old)

    def test_encoded_size_cap_is_exact_and_rejects_before_mutation(self):
        self.assertEqual(diagnostic._MAX_REPORT_BYTES,smoke.MAX_LOG_BYTES)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'report.json';overhead=len(self.payload({'text':''}))
            value={'text':'x'*(smoke.MAX_LOG_BYTES-overhead)}
            diagnostic.atomic_report(path,value)
            self.assertEqual(path.stat().st_size,smoke.MAX_LOG_BYTES)
            previous=path.read_bytes()
            for text in (value['text']+'x','证'*(smoke.MAX_LOG_BYTES//3)):
                with self.subTest(length=len(text)),patch.object(Path,'write_bytes') as write,\
                     patch.object(Path,'replace') as publish:
                    with self.assertRaisesRegex(ValueError,'64 KiB'):diagnostic.atomic_report(path,{'text':text})
                    write.assert_not_called();publish.assert_not_called()
                self.assertEqual(path.read_bytes(),previous)

    def test_initial_publication_can_record_terminal_failure_after_deadline(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'report.json';value={'status':'failed','error':'Selection handoff timeout'}
            diagnostic.atomic_report(path,value,deadline=time.monotonic()-1)
            self.assertEqual(path.read_bytes(),self.payload(value))
        source=Path(diagnostic.__file__).read_text()
        self.assertIn('atomic_report(report_path,report,deadline=started+170)',source)
        self.assertIn("time.monotonic()-started>170",source)

    def test_terminal_report_denial_still_closes_and_exits_with_original_failure_evidence(self):
        # Synthetic Qt lifecycle only; these objects cannot provide Windows acceptance.
        for denied in (False,True):
            for close_fails in (False,True):
                with self.subTest(denied=denied,close_fails=close_fails),tempfile.TemporaryDirectory() as directory:
                    path=Path(directory)/'report.json';control=Mock(current_version='0.4.7');app=Mock();timer=Mock()
                    app.platformName.return_value='offscreen'  # Force the real-backend guard to fail.
                    qt=SimpleNamespace(QtWidgets=SimpleNamespace(QApplication=Mock(instance=Mock(return_value=app))),
                                       QtCore=SimpleNamespace(QTimer=Mock(return_value=timer)))
                    write_error=replace_error();close_error=RuntimeError('synthetic close failure')
                    if close_fails:control.close.side_effect=close_error
                    replace=Path.replace;published=[]
                    def publish(source,target):
                        value=json.loads(source.read_bytes())
                        if denied and value['status']=='failed':raise write_error
                        published.append(value)
                        return replace(source,target)
                    with patch.dict(sys.modules,{'PySide6':qt}),\
                         patch.object(diagnostic,'diagnostic_state',return_value={'synthetic':True}),\
                         patch.object(diagnostic,'time',SimpleNamespace(monotonic=lambda:0.,sleep=Mock())),\
                         patch.object(Path,'replace',autospec=True,side_effect=publish):
                        if denied or close_fails:
                            with self.assertRaises(Exception) as caught:
                                diagnostic.start_selection_smoke(control,'unused-input.json',path)
                            self.assertIs(caught.exception,write_error if denied else close_error)
                        else:diagnostic.start_selection_smoke(control,'unused-input.json',path)
                    timer.stop.assert_called_once();control.close.assert_called_once();app.exit.assert_called_once_with(1)
                    terminal=path.with_name(path.name+'.tmp') if denied else path
                    evidence=json.loads(terminal.read_bytes())
                    self.assertEqual(evidence['status'],'failed')
                    self.assertEqual(evidence['error'],'Requires real Windows Qt/capture backend')
                    self.assertEqual(evidence['error_type'],'RuntimeError')
                    self.assertIn(evidence['error'],evidence['error_traceback'])
                    self.assertEqual(json.loads(path.read_bytes())['status'],'running' if denied else 'failed')
                    self.assertEqual(len(published),1 if denied else 2)


@unittest.skipUnless(os.name=='nt','Requires actual Windows file-sharing semantics')
class WindowsSelectionReportSharingTests(unittest.TestCase):
    def test_real_ordinary_reader_release_publishes_exact_terminal_payload(self):
        for status in ('passed','failed'):
            with self.subTest(status=status),tempfile.TemporaryDirectory() as directory:
                path=Path(directory)/'report.json';previous=b'{"status":"running"}\n';path.write_bytes(previous)
                value={'status':status,'text':'完整证据'}
                if status=='failed':value.update(error='original failure',error_traceback='original trace')
                replace=Path.replace;failures=[]
                # Match the observer's ordinary Python reader, which denies delete sharing.
                with path.open('r',encoding='utf8') as reader:
                    def observed(source,target):
                        try:return replace(source,target)
                        except OSError as exc:
                            failures.append(exc.winerror)
                            self.assertEqual(json.load(reader),{'status':'running'})
                            self.assertEqual(path.read_bytes(),previous)
                            reader.close()
                            raise
                    with patch.object(Path,'replace',autospec=True,side_effect=observed):
                        diagnostic.atomic_report(path,value)
                self.assertEqual(len(failures),1)
                self.assertIn(failures[0],(5,32,33))
                self.assertEqual(path.read_bytes(),(json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode('utf8'))
                self.assertEqual(list(Path(directory).iterdir()),[path])

    def test_real_permanent_reader_fails_boundedly_and_keeps_failure_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'report.json';previous=b'{"status":"running"}\n';path.write_bytes(previous)
            value={'status':'failed','error':'original failure','error_traceback':'original trace'}
            with path.open('r',encoding='utf8') as reader,\
                 patch.object(Path,'replace',autospec=True,side_effect=Path.replace) as publish:
                started=time.monotonic()
                with self.assertRaises(OSError) as caught:diagnostic.atomic_report(path,value)
                self.assertLess(time.monotonic()-started,2.)
                self.assertIn(caught.exception.winerror,(5,32,33))
                self.assertGreater(publish.call_count,1)
                self.assertLessEqual(publish.call_count,diagnostic._REPORT_REPLACE_ATTEMPTS)
                self.assertEqual(json.load(reader),{'status':'running'})
                self.assertEqual(path.read_bytes(),previous)
            self.assertEqual(json.loads(path.with_name(path.name+'.tmp').read_bytes()),value)


class SelectionHarnessTests(unittest.TestCase):
    def good_report(self, *, frozen=True, scale=1):
        labels = {}
        rects = {'hero': (5, 5, 150, 20), 'tier': (170, 5, 180, 20),
                 'metadata': (5, 30, 440, 30), 'heading': (5, 65, 280, 20), 'footer': (300, 65, 145, 20)}
        for role, expected in smoke.EXPECTED_TEXT.items():
            labels[role] = {'text': expected, 'visible': True, 'minimum_width': 100,
                'required_height_at_width': 20, 'logical_rect': dict(zip(('x','y','width','height'),rects[role])),
                'accessible_name': ('当前分配英雄：星火术士（演示）' if role == 'hero'
                                    else '虚构英雄评级（演示）：T5' if role == 'tier' else '')}
        reference = {'reference': dict(smoke.EXPECTED_REFERENCE), 'assigned': '9001', 'stage': 'assigned',
            'state_hero': '星火术士（演示）', 'observation_count': 2, 'confirmed': False, 'offered': [],
            'augment_card_count': 0, 'visible': True, 'native_visible': True, 'foreground_preserved': True,
            'overlay_hwnd': 300, 'click_through_hit_hwnd': 100, 'window_style': 0x80000|0x08000000|0x20|0x8|0x80,
            'client_rect': {'x':20,'y':20,'width':964,'height':602},
            'overlay_rect': {'x':30,'y':400,'width':round(450*scale),'height':round(100*scale)},
            'logical_size': {'width':450,'height':100}, 'qt_dpr': scale, 'labels': labels}
        result = dict(schemaVersion=2, status='passed', phase='complete', backend='qtwidgets',
                    qt_platform='windows', frozen=frozen, applicationVersion='0.4.1',
                    requested_app_scale=scale, window_closed=True, foreground_recovery_start_count=2,
                    foreground_recovery_observations=2, recognizedHero='星火术士（演示）',
                    assignedHero='星火术士（演示）', recognized=['星火共鸣','晶盾回路','风步微光'],
                    provenance='client-provisional', renderedBadgeProvenance=[dict(slot=i,visible=True,text='HUD未复核',paintedText='HUD未复核',
                        accessible=f'选项 {i} · {name} · T{i} · HUD未复核 · 来自本局选人 · HUD未复核',
                        tooltip='来自本局选人 · HUD未复核\n') for i,name in enumerate(['星火共鸣','晶盾回路','风步微光'],1)],
                    clientHwnd=100,clientPid=101,clientCreated=133000000000000001,gameHwnd=200,gamePid=201,gameCreated=133000000000000400,clientGeneration=2,
                    client_hero_reference=reference, client_hero_safety=dict.fromkeys(smoke.SAFETY_FIELDS,True),
                    **dict.fromkeys(smoke.FIELDS, True))
        result['initial_focus']=dict(route='controller',source_hwnd=600,source_pid=601,source_created=133000000000000050,
            target_hwnd=100,sent=True,api=True,drained=False,observed_hwnd=100)
        result['manual_client_follow_off']=dict(follow_enabled=False,target_hwnd=100,
            assigned='9001',observation_count=2,started_after=133000000000000100,game_hwnd=500,game_pid=501,game_created=133000000000000200,
            foreground_game_hwnd=500,fresh_no_handoff_age_seconds=.2,
            game_bound=False,expired_stage='client-expired',expired_observation_age_seconds=4.2,
            expiry_hidden=True,follow_on_started_after=133000000000000300)
        result['foreground_transition']={'sink_hwnd':400,'sink_pid':101,'sink_class':smoke.FOCUS_SINK_CLASS,
            'sink_title':smoke.FOCUS_SINK_TITLE,'foreground_sink_hwnd':400,'client_visible_during':True,
            'overlay_hwnd':300,'overlay_visible_before':True,'overlay_native_visible_before':True,
            'overlay_hidden_after':True,'sink_destroyed':True,'client_foreground_returned':True,
            **{key:dict(reference['client_rect']) for key in ('client_rect_before','client_rect_during','client_rect_returned')}}
        if frozen:
            result['executable_sha256']='c'*64
        return result

    def good_aggregate(self, *, frozen=True):
        value = {'schemaVersion':2, 'status':'passed', 'frozen':frozen, 'applicationVersion':'0.4.1',
                 'source_commit':'a'*40, 'source_files':dict.fromkeys(smoke.SOURCE_FILES,'b'*64),
                 'scales':list(smoke.SCALES), 'runs':[]}
        if frozen:
            value['executable_sha256']='c'*64
            value['executable_size']=123456
        for scale in smoke.SCALES:
            row = {'app_scale':scale, 'applicationVersion':'0.4.1', 'fixture_source_sha256':'b'*64,
                   'native_report':smoke.native_report_name(frozen,scale), 'native_report_sha256':'e'*64,
                   'detail':self.good_report(frozen=frozen,scale=scale), 'process_exited':True,
                   'owned_processes_exited':True, 'game_launched_after_selection_request':True,
                   'completed_fields':list(smoke.FIELDS),
                   'client':{'hwnd':100,'pid':101,'class_name':smoke.CLASSES['client'],'client_size':[964,602]},
                   'game':{'hwnd':200,'pid':201,'class_name':smoke.CLASSES['game'],'client_size':[964,602]}}
            row['follow_off_fixture']={'hwnd':500,'pid':501,'created':133000000000000200,'class_name':smoke.CLASSES['game'],
                'client_size':[964,602],'launched_after_selection_request':True,'process_exited':True,'closed_before_follow_on':True,
                'focus':{'sent':True,'result':1,'api':True,'drained':False,'before':100,'after':500}}
            row['application_process']={'pid':601,'created':133000000000000050,'hwnd':600}
            owner=row['application_process']
            launcher=row['application_launcher']={'pid':599 if frozen else owner['pid'],
                'created':133000000000000040 if frozen else owner['created']}
            row['application_binding']=dict(status='passed',stage='complete',mode='onefile-child' if frozen else 'source-direct',
                launcher=dict(launcher),reported_owner=dict(owner),observed_owner_pid=owner['pid'],observed_owner_scope='owned',
                proof=dict(launcher_pid=launcher['pid'],launcher_created=launcher['created'],owner_pid=owner['pid'],
                    owner_created=owner['created'],owner_ancestry_verified=True),
                **dict.fromkeys(('launcher_live','owner_live','job_verified','hwnd_verified','creation_verified',
                    'image_verified','lineage_verified','revalidated'),True))
            row['negative_game_return_focus']=good_owned_focus()
            row['final_game_focus']=good_owned_focus('game',route='already')
            row['final_game_focus']['target'].update(hwnd=200,pid=201,created=row['detail']['gameCreated'])
            row['final_game_focus']['focus'].update(before=200,after=200)
            row['focus_fixture']={key:copy.deepcopy(val) for key,val in row['detail']['foreground_transition'].items()
                                  if key not in ('sink_hwnd','sink_pid','overlay_hidden_after','overlay_hwnd',
                                                 'overlay_visible_before','overlay_native_visible_before')}
            row['focus_fixture'].update(sink={'hwnd':400,'pid':101},request_message=smoke.WM_FOCUS_OWNED_SINK,
                response_hwnd=400,request_sent=True,return_message=smoke.WM_RETURN_OWNED_CLIENT,
                return_response_hwnd=1,return_sent=True)
            if frozen:
                row['executable_sha256']='c'*64
            value['runs'].append(row)
        value.update({key:copy.deepcopy(value['runs'][0][key]) for key in ('process_exited',
            'owned_processes_exited','game_launched_after_selection_request','native_report','native_report_sha256',
            'fixture_source_sha256','completed_fields','client','game')})
        return value

    def producer_report(self, *, frozen, scale):
        """Full synthetic producer shape; never evidence of a Windows run."""
        value=self.good_report(frozen=frozen,scale=scale)
        tree=ast.parse(Path(diagnostic.__file__).read_text())
        checks=[node.args[0].value for node in ast.walk(tree) if isinstance(node,ast.Call)
                and isinstance(node.func,ast.Attribute) and isinstance(node.func.value,ast.Name)
                and node.func.value.id=='checks' and node.func.attr=='append']
        self.assertEqual(len(checks),6)
        # Use every current producer check verbatim, including Unicode labels.
        value.update(checks=checks,elapsed_seconds=11.797,
            scope='Original synthetic owned client/game processes only. Actual Windows metadata, capture and CPU OCR; no real LoL/Vanguard compatibility claim.',
            metadata_scope='Actual PROCESS_QUERY_LIMITED_INFORMATION path/creation + FILE_READ_ATTRIBUTES canonicalization, no process memory read')
        control=SimpleNamespace(state=SimpleNamespace(running=False,generation=16,hero='',confirmed=False),
            ocr_busy=False,capture_pending=False,_capture_serial=15,monitor=Mock(isActive=lambda:False),
            status=Mock(text=lambda:'未稳定识别到三个不同候选，旧叠加已隐藏'),
            capture=SimpleNamespace(last_backend='windows-graphics-capture-session'),
            selection_session=SimpleNamespace(active=False,generation=11,stage='idle',candidate_frames=0,
                candidate='',assigned='',last_client_frame=None,reason='Capture stopped'))
        value['diagnostic_state']=diagnostic.diagnostic_state(control,100.,111.797)
        value['requested_app_scale']=float(scale)
        value['client_hero_reference']['qt_dpr']=float(scale)
        return value

    def execute_producer_aggregate(self, root, *, frozen, extra=None):
        """Exercise real aggregation, preservation, serialization and validation."""
        template=self.good_aggregate(frozen=frozen)
        template['scope']=smoke.SCOPE
        template['source_files']={name:smoke.sha256(smoke.ROOT/name) for name in smoke.SOURCE_FILES}
        reports=root/'reports';reports.mkdir();work=root/'work';work.mkdir();payloads={}
        def run(original,destination,row,*,frozen,scale):
            expected=copy.deepcopy(template['runs'][smoke.SCALES.index(scale)])
            expected['fixture_source_sha256']=template['source_files']['tests/SessionWindowFixture.cs']
            expected['detail']=self.producer_report(frozen=frozen,scale=scale)
            if extra is not None:expected['detail']['additional_evidence']=extra
            prefix=('windows-selection-' if frozen else 'windows-selection-source-')+'scale'+str(round(scale*100))+'-'
            expected.update(cleanup='Both fixtures exited 0 after WM_CLOSE; private job empty',
                            logs=[prefix+'last-launch-error.txt'])
            row.update(expected)
            path=work/row['native_report'];diagnostic.atomic_report(path,row['detail'])
            row['native_report_sha256']=smoke.sha256(path);payloads[path.name]=path.read_bytes()
            smoke.preserve_native_report(path,destination,row,completed=True)
        value={key:copy.deepcopy(item) for key,item in template.items()
               if key not in smoke.LEGACY_FIELDS and key!='runs'}
        value['runs']=[]
        with patch.object(smoke,'execute_run',side_effect=run):
            smoke.execute(Path('candidate.exe') if frozen else None,reports,value)
        smoke.validate_aggregate(value,'0.4.1',frozen=frozen,source_commit='a'*40,
            executable_sha256='c'*64 if frozen else None,executable_size=123456 if frozen else None)
        return value,reports,payloads

    def test_full_producer_three_scale_reports_fit_compact_json_without_duplicate_snapshots(self):
        for frozen in (False,True):
            with self.subTest(frozen=frozen),tempfile.TemporaryDirectory() as directory:
                value,reports,payloads=self.execute_producer_aggregate(Path(directory),frozen=frozen)
                original=copy.deepcopy(value)
                for row in original['runs']:row['native_report_snapshot']=copy.deepcopy(row['detail'])
                original.update({key:copy.deepcopy(item) for key,item in original['runs'][0].items()
                                 if key not in ('app_scale','detail')})
                encoded=lambda item:(json.dumps(item,ensure_ascii=False,indent=2)+'\n').encode('utf8')
                self.assertGreater(len(encoded(original)),smoke.MAX_LOG_BYTES)  # Reproduce run38's shape.
                self.assertLess(len(encoded(value)),smoke.MAX_LOG_BYTES)
                name='windows-selection-smoke.json' if frozen else 'windows-selection-source.json'
                path=reports/name;smoke.write_json(path,value)
                compact=(json.dumps(value,ensure_ascii=False,separators=(',',':'),allow_nan=False)+'\n').encode('utf8')
                self.assertEqual(path.read_bytes(),compact)  # Same full evidence; logs remain pretty-printed.
                self.assertLess(len(compact),len(encoded(value)))
                restored=smoke.read_json(path)
                smoke.validate_aggregate(restored,'0.4.1',frozen=frozen,source_commit='a'*40,
                    executable_sha256='c'*64 if frozen else None,executable_size=123456 if frozen else None)
                self.assertNotIn('native_report_snapshot',restored)
                self.assertNotIn('focus_fixture',restored)
                self.assertEqual(len(restored['runs']),3)
                for key in smoke.LEGACY_FIELDS:self.assertEqual(restored[key],restored['runs'][0][key])
                for row in restored['runs']:
                    self.assertNotIn('native_report_snapshot',row)
                    self.assertTrue(row['native_report_present'])
                    self.assertEqual(row['native_report_snapshot_sha256'],row['native_report_sha256'])
                    raw=reports/row['native_report']
                    self.assertEqual(raw.read_bytes(),payloads[raw.name])
                    self.assertEqual(smoke.sha256(raw),row['native_report_sha256'])
                    self.assertEqual(json.dumps(json.loads(raw.read_bytes()),sort_keys=True),
                                     json.dumps(row['detail'],sort_keys=True))
                    self.assertIn('diagnostic_state',row['detail'])
                    self.assertEqual(len(row['detail']['checks']),6)
                    self.assertIn('focus_fixture',row);self.assertIn('cleanup',row);self.assertTrue(row['logs'])
                # Deduplication cannot weaken a required field at any scale.
                for index in range(3):
                    changed=copy.deepcopy(restored)
                    changed['runs'][index]['detail']['client_hero_reference']['visible']=1
                    with self.assertRaises(AssertionError):
                        smoke.validate_aggregate(changed,'0.4.1',frozen=frozen)

    def test_nonduplicate_aggregate_overflow_still_fails_closed_without_truncation(self):
        for frozen in (False,True):
            with self.subTest(frozen=frozen),tempfile.TemporaryDirectory() as directory:
                value,reports,payloads=self.execute_producer_aggregate(Path(directory),frozen=frozen,extra='证'*8000)
                path=reports/'aggregate.json';previous=b'{"status":"failed","error":"previous evidence"}\n'
                path.write_bytes(previous)
                with self.assertRaisesRegex(AssertionError,'size limit'):smoke.write_json(path,value)
                self.assertEqual(path.read_bytes(),previous)
                self.assertFalse(path.with_suffix('.tmp').exists())
                for row in value['runs']:
                    raw=reports/row['native_report']
                    self.assertEqual(raw.read_bytes(),payloads[raw.name])
                    self.assertLess(raw.stat().st_size,smoke.MAX_LOG_BYTES)
                    self.assertEqual(row['detail']['additional_evidence'],'证'*8000)

    def test_two_complete_scales_and_full_failed_current_snapshot_fit_evidence_bound(self):
        for frozen in (False,True):
            for status,retain_detail in (('running',False),('failed',False),('running',True),('failed',True)):
                with self.subTest(frozen=frozen,status=status,retain_detail=retain_detail),tempfile.TemporaryDirectory() as directory:
                    root=Path(directory)
                    value,reports,payloads=self.execute_producer_aggregate(root,frozen=frozen)
                    previous=copy.deepcopy(value['runs'][:2]);row=value['runs'][2]
                    observed_detail=copy.deepcopy(row['detail']);snapshot=copy.deepcopy(observed_detail)
                    name=row['native_report']
                    if not retain_detail:
                        for key in ('detail','native_report','native_report_sha256','completed_fields','cleanup'):row.pop(key)
                        row.update(process_exited=False,owned_processes_exited=False)
                    snapshot.update(status=status,phase='recovering-foreground',window_closed=False)
                    snapshot['diagnostic_state']['status']=('正在等待自有窗口前台恢复；' * 40)[:400]
                    snapshot['diagnostic_state']['session']['reason']=('Waiting for owned client foreground; ' * 10)[:240]
                    error="[WinError 5] Access is denied: 'C:\\Users\\runneradmin\\AppData\\Local\\Temp\\vga-exe-smoke-owned\\report.json.tmp' -> 'C:\\Users\\runneradmin\\AppData\\Local\\Temp\\vga-exe-smoke-owned\\report.json'"
                    if status=='failed':
                        trace=('Traceback (most recent call last):\n'+
                               '  File "D:\\a\\vga-aram-helper\\vga-aram-helper\\selection_smoke.py", line 40, in atomic_report\n'+
                               '    temporary.replace(path)\n'+error+'\n')
                        error=(error+'\n')*12;error=error[:2000]
                        snapshot.update(error=error,error_type='PermissionError',
                                        error_traceback=(trace*12)[-4000:])
                    path=root/'work'/name;diagnostic.atomic_report(path,snapshot)
                    payload=path.read_bytes()
                    smoke.preserve_native_report(path,reports,row,completed=False)
                    value.update(status='failed',error=repr(AssertionError(error if status=='failed' else
                        'Application did not confirm selection before game launch'))[:2000])
                    aggregate=reports/'failed-aggregate.json';smoke.write_json(aggregate,value)
                    self.assertLess(aggregate.stat().st_size,smoke.MAX_LOG_BYTES)
                    restored=smoke.read_json(aggregate)
                    self.assertEqual(restored['status'],'failed')
                    self.assertEqual(restored['error'],value['error'])
                    self.assertEqual(restored['runs'][:2],previous)
                    current=restored['runs'][2]
                    if retain_detail:self.assertEqual(current['detail'],observed_detail)
                    else:self.assertNotIn('detail',current)
                    self.assertEqual(current['native_report_snapshot'],snapshot)
                    self.assertEqual((reports/name).read_bytes(),payload)
                    self.assertEqual(current['native_report_snapshot_sha256'],smoke.sha256(path))
                    for complete in previous:
                        self.assertEqual((reports/complete['native_report']).read_bytes(),payloads[complete['native_report']])
                    with self.assertRaises(AssertionError):
                        smoke.validate_aggregate(restored,'0.4.1',frozen=frozen)

    def test_provisional_badges_require_visible_exact_order_and_full_qualifier(self):
        for field,value in [('slot',True),('slot',2),('visible',False),('text','源评级'),
                            ('paintedText','源评级'),('paintedText',None),('paintedText',''),('accessible','来自本局选人'),('tooltip','')]:
            report=self.good_report();report['renderedBadgeProvenance'][0][field]=value
            with self.subTest(field=field,value=value),self.assertRaises(AssertionError):
                smoke.validate_report(report,'0.4.1')
        for rows in (None,[],self.good_report()['renderedBadgeProvenance'][:2]):
            report=self.good_report();report['renderedBadgeProvenance']=rows
            with self.assertRaises(AssertionError):smoke.validate_report(report,'0.4.1')

    def test_report_requires_every_native_identity_and_all_original_and_new_flags(self):
        smoke.validate_report(self.good_report(), '0.4.1')
        for field, value in [('status', 'running'), ('backend', 'browser'), ('qt_platform', 'offscreen'),
                             ('frozen', False), ('applicationVersion', '0.4.0'), ('error', 'problem'),
                             ('schemaVersion', True), ('window_closed', False), ('clientHwnd', True),
                             ('foreground_recovery_start_count',True),('foreground_recovery_observations',1),
                             ('requested_app_scale', True), ('requested_app_scale',1.5),
                             ('recognized',['风步微光','晶盾回路','星火共鸣']), ('provenance','hud')]:
            with self.subTest(field=field), self.assertRaises(AssertionError):
                smoke.validate_report(dict(self.good_report(), **{field: value}), '0.4.1')
        for field in smoke.FIELDS:
            for value in (False, None, 1, 'true'):
                with self.subTest(field=field, value=value), self.assertRaises(AssertionError):
                    smoke.validate_report(dict(self.good_report(), **{field: value}), '0.4.1')
        self.assertEqual(len(smoke.FIELDS), 11)
        self.assertEqual(smoke.FIELDS[:6], ('champion_select_own_row_passed','champion_select_ambiguity_passed',
            'champion_select_session_carry_passed','champion_select_stale_clear_passed',
            'champion_select_window_scope_passed','metadata_query_passed'))

    def test_native_reports_require_source_or_frozen_at_each_exact_scale(self):
        for frozen in (False,True):
            for scale in smoke.SCALES:
                value=self.good_report(frozen=frozen,scale=scale)
                smoke.validate_report(value,'0.4.1',frozen=frozen,scale=scale)
                with self.assertRaises(AssertionError):
                    smoke.validate_report(value,'0.4.1',frozen=not frozen,scale=scale)
                with self.assertRaises(AssertionError):
                    smoke.validate_report(value,'0.4.1',frozen=frozen,scale=scale+.5)

    def test_manual_follow_off_requires_fresh_negative_then_expiry_and_separate_start_scopes(self):
        for key in self.good_report()['manual_client_follow_off']:
            value=self.good_report();del value['manual_client_follow_off'][key]
            with self.subTest(missing=key),self.assertRaises(AssertionError):smoke.validate_report(value,'0.4.1')
        mutations=[('follow_enabled',True),('follow_enabled',0),('game_bound',True),('game_bound',0),
            ('target_hwnd',500),('target_hwnd',True),('game_hwnd',100),('game_pid',101),
            ('game_created',True),('game_created',1),('started_after',133000000000000200),
            ('follow_on_started_after',133000000000000200),('follow_on_started_after',133000000000000400),
            ('foreground_game_hwnd',100),('observation_count',1),('observation_count',True),('assigned','9002'),
            ('fresh_no_handoff_age_seconds',4.01),('fresh_no_handoff_age_seconds',True),
            ('fresh_no_handoff_age_seconds',float('nan')),('expired_observation_age_seconds',4),
            ('expired_observation_age_seconds',170),('expired_observation_age_seconds',float('inf')),
            ('expired_stage','assigned')]
        mutations += [(key,bad) for key in ('expiry_hidden',)
                      for bad in (False,1)]
        for key,bad in mutations:
            value=self.good_report();value['manual_client_follow_off'][key]=bad
            with self.subTest(key=key,bad=bad),self.assertRaises(AssertionError):smoke.validate_report(value,'0.4.1')
        for bad in (None,True,133000000000000300):
            value=self.good_report();value['gameCreated']=bad
            with self.subTest(final_game_created=bad),self.assertRaises(AssertionError):smoke.validate_report(value,'0.4.1')

    def test_outer_negative_game_lifetime_and_identity_must_match_each_native_scale(self):
        for frozen in (False,True):
            for index in range(3):
                for field,bad in (('hwnd',999),('pid',999),('created',True),('created',1),('class_name','RCLIENT'),
                    ('client_size',[True,602]),('launched_after_selection_request',False),('process_exited',False),
                    ('closed_before_follow_on',1)):
                    value=self.good_aggregate(frozen=frozen);value['runs'][index]['follow_off_fixture'][field]=bad
                    with self.subTest(frozen=frozen,scale=index,field=field),self.assertRaises(AssertionError):
                        smoke.validate_aggregate(value,'0.4.1',frozen=frozen)
        self.assertIn('automatic_windows.py',smoke.SOURCE_FILES)

    def test_creation_observer_uses_only_exact_existing_owned_handle_and_fails_closed(self):
        calls=[];handle=object()
        def query(observed,created,exited,kernel,user):
            calls.append(observed);created._obj.dwHighDateTime=3;created._obj.dwLowDateTime=17
            return True
        native=SimpleNamespace(k=SimpleNamespace(GetProcessTimes=Mock(side_effect=query)))
        self.assertEqual(smoke.owned_process_created(native,{'handle':handle,'pid':101}),(3<<32)|17)
        self.assertEqual(calls,[handle])
        native.k.GetProcessTimes.side_effect=None;native.k.GetProcessTimes.return_value=False
        with self.assertRaisesRegex(AssertionError,'creation time unavailable'):
            smoke.owned_process_created(native,{'handle':handle,'pid':101})

    def test_owned_game_focus_transfer_records_success_or_immediate_failure_once(self):
        for sent,result,after,drain,passes in ((True,1,500,False,True),(False,0,100,False,False),
                (False,1,500,False,False),(True,2,100,False,False),(True,1,100,False,False),
                (True,3,500,True,True),(True,3,500,False,False),(True,3,999,True,False),
                (True,999999,999,False,False)):
            with self.subTest(sent=sent,result=result,after=after):
                foreground=[100];evidence={'created':200};calls=[]
                def send(*args):
                    calls.append(args)
                    if args[1]==0:foreground[0]=after;return drain
                    args[-1]._obj.value=result
                    if result!=3:foreground[0]=after
                    return sent
                native=SimpleNamespace(u=SimpleNamespace(GetForegroundWindow=lambda:foreground[0],SendMessageTimeoutW=send))
                args=(native,{'pid':101},'client.exe',{'hwnd':100,'pid':101},(964,602),
                      {'pid':501},'game.exe',{'hwnd':500,'pid':501},(964,602),100,evidence)
                with patch.object(smoke,'assert_owned_window') as identity, \
                     patch.object(smoke,'owned_process_created',side_effect=lambda n,p:100 if p['pid']==101 else 200):
                    if passes:smoke.focus_owned_game(*args)
                    else:
                        with self.assertRaisesRegex(AssertionError,'Owned focus handshake failed'):smoke.focus_owned_game(*args)
                    count=2 if sent and result==3 else 1
                    self.assertEqual(identity.call_count,6 if count==2 else 4)
                    self.assertEqual(len(calls),count)
                    self.assertEqual(calls[0][:6],(100,smoke.WM_FOCUS_OWNED_GAME,500,200,2,1000))
                    if count==2:self.assertEqual(calls[1][:6],(500,0,0,0,2,1000))
                    observed=evidence['focus']
                    self.assertEqual(observed,dict(sent=sent,result=result if result in (0,1,2,3) else 4,
                        api=True if result in (1,3) else False if result==2 else None,drained=drain,before=100,
                        after=after if after in (100,500) else 0))
                    # Delayed focus cannot turn an already-failed request into a
                    # pass or overwrite its fixed evidence, even if called again.
                    before=copy.deepcopy(observed);foreground[0]=500
                    with self.assertRaisesRegex(AssertionError,'must not be retried'):smoke.focus_owned_game(*args)
                    self.assertEqual(len(calls),count);self.assertEqual(evidence['focus'],before)

    def test_owned_game_focus_transfer_revalidates_identity_and_transport(self):
        native=SimpleNamespace(u=SimpleNamespace(GetForegroundWindow=Mock(return_value=100),SendMessageTimeoutW=Mock()))
        def args(evidence):
            return (native,{'pid':101},'client.exe',{'hwnd':100,'pid':101},(964,602),
                {'pid':501},'game.exe',{'hwnd':500,'pid':501},(964,602),100,evidence)
        for created in (True,200.,0,-1,2**63):
            with self.subTest(created=created),self.assertRaisesRegex(AssertionError,'x64 range'):
                smoke.focus_owned_game(*args({'created':created}))
        with patch.object(smoke.ctypes,'sizeof',return_value=4),self.assertRaisesRegex(AssertionError,'x64 transport'):
            smoke.focus_owned_game(*args({'created':200}))
        for failure in ('identity','creation','foreground'):
            with self.subTest(failure=failure),patch.object(smoke,'assert_owned_window') as identity, \
                 patch.object(smoke,'owned_process_created',side_effect=[100,201] if failure=='creation' else [100,200]):
                if failure=='identity':identity.side_effect=AssertionError('Owned identity changed')
                native.u.GetForegroundWindow.return_value=999 if failure=='foreground' else 100
                evidence={'created':200}
                with self.assertRaises(AssertionError):smoke.focus_owned_game(*args(evidence))
                if failure=='foreground':self.assertEqual(evidence['focus'],dict(sent=False,result=0,api=None,drained=False,before=0,after=0))
        native.u.SendMessageTimeoutW.assert_not_called()
        foreground=[100]
        def send(*values):values[-1]._obj.value=1;foreground[0]=500;return True
        native.u.GetForegroundWindow=lambda:foreground[0];native.u.SendMessageTimeoutW=Mock(side_effect=send)
        with patch.object(smoke,'assert_owned_window'),patch.object(smoke,'owned_process_created',side_effect=[100,200,100,201]), \
             self.assertRaisesRegex(AssertionError,'process creation changed'):
            smoke.focus_owned_game(*args({'created':200}))
        native.u.SendMessageTimeoutW.assert_called_once()

    def test_owned_game_focus_receipt_is_strict_at_all_scales_and_entrypoints(self):
        for frozen in (False,True):
            for index in range(3):
                for key,bad in (('sent',False),('sent',1),('result',True),('result',2),('result',3),('api',False),('api',1),('drained',1),('drained',True),
                                ('before',0),('before',100.),('after',100),('after',500.)):
                    with self.subTest(frozen=frozen,scale=index,key=key,bad=bad):
                        value=self.good_aggregate(frozen=frozen);value['runs'][index]['follow_off_fixture']['focus'][key]=bad
                        with self.assertRaisesRegex(AssertionError,'focus handshake'):smoke.validate_aggregate(value,'0.4.1',frozen=frozen)
                value=self.good_aggregate(frozen=frozen);del value['runs'][index]['follow_off_fixture']['focus']
                with self.assertRaisesRegex(AssertionError,'focus handshake'):smoke.validate_aggregate(value,'0.4.1',frozen=frozen)
                value=self.good_aggregate(frozen=frozen)
                value['runs'][index]['follow_off_fixture']['focus'].update(result=3,drained=True)
                smoke.validate_aggregate(value,'0.4.1',frozen=frozen)

    def test_actual_wrapper_phase_driver_closes_negative_game_before_final_request(self):
        import ctypes
        # Execute the real nested driver with owned native-call fakes. Only its
        # closure addressing changes; no Windows or process-lifecycle claim.
        tree=ast.parse(Path(smoke.__file__).read_text())
        driver=copy.deepcopy(next(node for node in ast.walk(tree) if isinstance(node,ast.FunctionDef) and node.name=='awaiting_game'))
        driver.body=[ast.copy_location(ast.Global(node.names),node) if isinstance(node,ast.Nonlocal) else node for node in driver.body]
        calls=[];current={'phase':'await-follow-off-game'};foreground=[100]
        app={'pid':1};client={'pid':101};negative={'pid':501,'handle':object()};window={'hwnd':500,'pid':501}
        def focus(native,target,owners,evidence):
            self.assertEqual(foreground[0],500);native.close_window.assert_not_called()
            calls.append(('foreground',target['role'],target['window']['hwnd']));foreground[0]=target['window']['hwnd'];return True
        def transfer(*args):
            calls.append(('owned-transfer',args[3]['hwnd'],args[7]['hwnd']));foreground[0]=args[7]['hwnd']
            args[-1]['focus']={'sent':True,'result':1,'api':True,'drained':False,'before':100,'after':500}
        native=SimpleNamespace(poll=lambda process:None,spawn=Mock(return_value=negative),
            close_window=Mock(),wait_exit=Mock(return_value=0),
            u=SimpleNamespace(SetWindowPos=Mock(return_value=True),GetForegroundWindow=lambda:foreground[0]))
        namespace=dict(smoke.__dict__,native=native,app=app,client=client,negative_game=None,negative_window=None,
            handoff_path=Path('/owned/report.json'),work=Path('/owned'),result={},x=20,y=20,env={},
            fixture={'client_exe':Path('/owned/client.exe'),'game_exe':Path('/owned/game.exe')},
            sizes={'client':(964,602),'game':(964,602)},client_window={'hwnd':100,'pid':101},
            budget=SimpleNamespace(until=lambda seconds:seconds),
            report_when=lambda *args:current if current['phase']=='await-game-window' else None,
            poll_owned_json=lambda *args:current,focus_owned_target=focus,focus_owned_game=Mock(side_effect=transfer),client_created=100,
            client_owner=dict(role='client',window={'hwnd':100,'pid':101}),
            fixture_argv=Mock(return_value=['/owned/game.exe']),wait_fixture=Mock(return_value=window),
            assert_owned_window=Mock(),owned_process_created=Mock(return_value=133000000000000200))
        exec(compile(ast.fix_missing_locations(ast.Module(body=[driver],type_ignores=[])),'owned-phase-driver','exec'),namespace)
        advance=namespace['awaiting_game']
        self.assertIsNone(advance());self.assertIs(namespace['negative_game'],negative)
        self.assertTrue(namespace['fixture_argv'].call_args.kwargs['no_activate'])
        self.assertEqual(native.u.SetWindowPos.call_args.args[0],500)
        current['phase']='testing-follow-off-game';self.assertIsNone(advance())
        self.assertEqual(calls[-1],('owned-transfer',100,500));native.close_window.assert_not_called()
        self.assertIsNone(advance());namespace['focus_owned_game'].assert_called_once()
        foreground[0]=999
        with self.assertRaisesRegex(AssertionError,'lost foreground'):advance()
        foreground[0]=500
        current['phase']='await-game-window'
        with self.assertRaisesRegex(AssertionError,'before negative-game cleanup'):advance()
        current['phase']='closing-follow-off-game';self.assertIsNone(advance());self.assertIsNone(advance())
        native.close_window.assert_called_once_with(window)
        native.wait_exit.assert_called_once_with(negative,10)
        self.assertEqual(calls[-1],('foreground','client',100))
        current['phase']='capturing-client';foreground[0]=999
        with self.assertRaisesRegex(AssertionError,'during selection observation'):advance()
        foreground[0]=100
        current['phase']='await-game-window'
        current['initial_focus']=self.good_report()['initial_focus']
        namespace['app']['pid']=599;namespace['result']['application_launcher']={'pid':599,'created':133000000000000200}
        namespace.update(target=Path('/owned/app.exe'),frozen=True,bind_application_owner=Mock(return_value={'pid':601,'created':133000000000000050,'hwnd':600}))
        def app_pid(hwnd,pointer):
            self.assertEqual(hwnd,600)
            ctypes.cast(pointer,ctypes.POINTER(smoke.W.DWORD)).contents.value=601;return 1
        native.u.GetWindowThreadProcessId=app_pid
        self.assertIs(advance(),current)
        self.assertEqual(namespace['result']['application_process']['hwnd'],600)
        namespace['bind_application_owner'].assert_called_once_with(native,app,Path('/owned/app.exe'),current['initial_focus'],
            namespace['result']['application_launcher'],frozen=True,executable_sha256=None,evidence={})
        self.assertEqual(native.spawn.call_count,1)
        native.wait_exit.return_value=1;native.close_window.reset_mock();foreground[0]=500
        namespace['result']['follow_off_fixture']['process_exited']=False
        current['phase']='closing-follow-off-game'
        with self.assertRaisesRegex(AssertionError,'did not exit cleanly'):advance()

    def test_new_owned_focus_receipts_are_strict_at_each_scale_and_mode(self):
        for frozen in (False,True):
            for index in range(3):
                for field,replacement in (('negative_game_return_focus',{}),('final_game_focus',{}),('application_process',{})):
                    value=self.good_aggregate(frozen=frozen);value['runs'][index][field]=replacement
                    with self.subTest(frozen=frozen,index=index,field=field),self.assertRaises(AssertionError):
                        smoke.validate_aggregate(value,'0.4.1',frozen=frozen)
                for field,replacement in (('source_pid',True),('source_created',0),('source_hwnd',100),
                        ('target_hwnd',999),('observed_hwnd',0),('sent',1),('api',1),('drained',1)):
                    value=self.good_aggregate(frozen=frozen);value['runs'][index]['detail']['initial_focus'][field]=replacement
                    with self.subTest(frozen=frozen,index=index,initial=field),self.assertRaises(AssertionError):
                        smoke.validate_aggregate(value,'0.4.1',frozen=frozen)
                for key in ('pid','created','hwnd'):
                    value=self.good_aggregate(frozen=frozen);value['runs'][index]['application_process'][key]+=1
                    with self.subTest(frozen=frozen,index=index,application=key),self.assertRaises(AssertionError):
                        smoke.validate_aggregate(value,'0.4.1',frozen=frozen)
                value=self.good_aggregate(frozen=frozen);value['runs'][index]['negative_game_return_focus']['target']['created']+=1
                with self.assertRaises(AssertionError):smoke.validate_aggregate(value,'0.4.1',frozen=frozen)

    def test_literal_hero_reference_and_no_augment_confirmation_are_strict(self):
        mutations=[('assigned','9002'),('stage','assigning'),('state_hero',''),('observation_count',1),
            ('observation_count',True),('observation_count',2.0),('confirmed',True),('confirmed',0),
            ('offered',['星火共鸣']),('offered',()),('augment_card_count',False),('augment_card_count',3),
            ('visible',False),('native_visible',False),('foreground_preserved',False),
            ('click_through_hit_hwnd',300),('qt_dpr',True),('qt_dpr',float('nan')),('qt_dpr',2),
            ('window_style',0),('window_style',-1),('window_style',2**32+0x080800A8),
            ('window_style',0x08080028),('overlay_hwnd',100)]
        for key,replacement in mutations:
            value=self.good_report();value['client_hero_reference'][key]=replacement
            with self.subTest(key=key,replacement=replacement),self.assertRaises(AssertionError):
                smoke.validate_report(value,'0.4.1')
        for key,replacement in [('championId','9002'),('hero','未知英雄'),('sourceTier','T1'),
            ('sourceTierLabel','虎牙公开源英雄评级'),('sourceLabel','unknown'),('sourceDataDate','2026-01-03'),
            ('sourceVersion','0.2'),('gamePatch','0.1'),('wikiDataVersion','latest'),
            ('sourceUrl','https://example.com'),('isDemo',1)]:
            value=self.good_report();value['client_hero_reference']['reference'][key]=replacement
            with self.subTest(reference=key),self.assertRaises(AssertionError):
                smoke.validate_report(value,'0.4.1')
        for key in smoke.SAFETY_FIELDS:
            value=self.good_report();del value['client_hero_safety'][key]
            with self.subTest(safety=key),self.assertRaises(AssertionError):
                smoke.validate_report(value,'0.4.1')

    def test_visible_label_and_native_geometry_forgery_is_rejected(self):
        for field in ('client_rect','overlay_rect'):
            for key,replacement in [('x',True),('width',450.0),('height',0),('width',-1)]:
                value=self.good_report();value['client_hero_reference'][field][key]=replacement
                with self.subTest(field=field,key=key),self.assertRaises(AssertionError):
                    smoke.validate_report(value,'0.4.1')
        for role in smoke.EXPECTED_TEXT:
            for key,replacement in [('text',''),('visible',1),('minimum_width',1000),
                                    ('required_height_at_width',1000),('accessible_name','forged')]:
                value=self.good_report();value['client_hero_reference']['labels'][role][key]=replacement
                with self.subTest(role=role,key=key),self.assertRaises(AssertionError):
                    smoke.validate_report(value,'0.4.1')
        value=self.good_report();value['client_hero_reference']['overlay_rect']['height']=302
        with self.assertRaises(AssertionError):smoke.validate_report(value,'0.4.1')
        value=self.good_report();value['client_hero_reference']['labels']['hero']['logical_rect']['x']=1000
        with self.assertRaises(AssertionError):smoke.validate_report(value,'0.4.1')
        value=self.good_report();value['client_hero_reference']['labels']['tier']['logical_rect']['x']=5
        with self.assertRaises(AssertionError):smoke.validate_report(value,'0.4.1')
        value=self.good_report();del value['client_hero_reference']['labels']['metadata']
        with self.assertRaises(AssertionError):smoke.validate_report(value,'0.4.1')

    def test_aggregate_requires_three_complete_independently_bound_runs(self):
        for frozen in (True,False):
            value=self.good_aggregate(frozen=frozen)
            smoke.validate_aggregate(value,'0.4.1',frozen=frozen,source_commit='a'*40,
                                     executable_sha256='c'*64 if frozen else None)
            for key,replacement in [('status','failed'),('schemaVersion',True),('frozen',not frozen),
                ('source_commit','d'*40),('source_files',{}),('scales',[True,1.5,2]),('scales',[1,1.5]),
                ('process_exited',1),('native_report','other.json'),('native_report_sha256','f'*64),
                ('fixture_source_sha256','f'*64),('runs',value['runs'][:2])]:
                changed=copy.deepcopy(value);changed[key]=replacement
                with self.subTest(frozen=frozen,key=key),self.assertRaises(AssertionError):
                    smoke.validate_aggregate(changed,'0.4.1',frozen=frozen,source_commit='a'*40)
            for index in range(3):
                for key,replacement in [('app_scale',True),('native_report','other.json'),('detail',{}),
                    ('process_exited',False),('owned_processes_exited',False),
                    ('game_launched_after_selection_request',False),('completed_fields',[]),
                    ('applicationVersion','9.9.9'),('fixture_source_sha256','d'*64),('native_report_sha256',''),('client',{})]:
                    changed=copy.deepcopy(value);changed['runs'][index][key]=replacement
                    with self.subTest(frozen=frozen,index=index,key=key),self.assertRaises(AssertionError):
                        smoke.validate_aggregate(changed,'0.4.1',frozen=frozen)
        for size in (None,True,0,-1,123456.0):
            value=self.good_aggregate();value['executable_size']=size
            with self.assertRaises(AssertionError):smoke.validate_aggregate(value,'0.4.1',frozen=True)
        value=self.good_aggregate()
        with self.assertRaises(AssertionError):smoke.validate_aggregate(value,'0.4.1',frozen=True,executable_size=999)
        value=self.good_aggregate();value['runs'][2]['client']['client_size']=[964.0,602]
        with self.assertRaises(AssertionError):smoke.validate_aggregate(value,'0.4.1',frozen=True)
        value=self.good_aggregate();value['client']['hwnd']=100.0
        with self.assertRaises(AssertionError):smoke.validate_aggregate(value,'0.4.1',frozen=True)
        value=self.good_aggregate();value['runs'][2]['detail']['executable_sha256']='d'*64
        with self.assertRaises(AssertionError):smoke.validate_aggregate(value,'0.4.1',frozen=True)
        value=self.good_aggregate();value['runs'][2]['executable_sha256']='d'*64
        with self.assertRaises(AssertionError):smoke.validate_aggregate(value,'0.4.1',frozen=True)
        value=self.good_aggregate(frozen=False);value['executable_sha256']='c'*64
        with self.assertRaises(AssertionError):smoke.validate_aggregate(value,'0.4.1',frozen=False)

    def test_standard_runner_geometry_and_too_small_desktop(self):
        self.assertEqual(smoke.fixture_dimensions(1024, 768), {'client': (964, 602), 'game': (964, 602)})
        self.assertEqual(smoke.fixture_dimensions(1920, 1080)['game'], (964, 602))
        for bounds in ((800, 600), (1024, 650), (True, 768)):
            with self.subTest(bounds=bounds), self.assertRaises(ValueError):
                smoke.fixture_dimensions(*bounds)

    def test_environment_removes_test_overrides_preserves_original_network(self):
        with tempfile.TemporaryDirectory() as directory:
            original = {'SystemRoot': r'C:\Windows', 'Path': r'C:\Python312', 'QT_QPA_PLATFORM': 'offscreen',
                        'VGA_FORGED_REPORT': 'yes', '_PYI_ARCHIVE_FILE': 'outside', 'PYSIDE_PLUGIN': 'outside',
                        'HTTPS_PROXY': 'http://existing-authorized-proxy:8000'}
            env = smoke.child_environment(original, Path(directory).resolve())
            self.assertEqual(env['PATH'], r'C:\Windows\System32;C:\Windows')
            self.assertEqual(env['HTTPS_PROXY'], original['HTTPS_PROXY'])
            self.assertEqual(env['VGA_STATE_DIR'], str(Path(directory).resolve() / 'state'))
            self.assertTrue(Path(env['TEMP']).is_dir())
            for key in ('QT_QPA_PLATFORM', 'VGA_FORGED_REPORT', '_PYI_ARCHIVE_FILE', 'PYSIDE_PLUGIN'):
                self.assertNotIn(key, env)
            self.assertEqual(original['QT_QPA_PLATFORM'], 'offscreen')
            self.assertEqual(env['QT_SCALE_FACTOR'], '1')

    def test_report_read_waits_for_exact_phase_or_success(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory).resolve() / 'report.json'
            self.assertIsNone(smoke.report_when(path, 'await-game-window'))
            path.write_text('{')
            self.assertIsNone(smoke.report_when(path, 'await-game-window'))
            path.write_text(json.dumps({'status': 'running', 'phase': 'selected'}))
            self.assertIsNone(smoke.report_when(path, 'await-game-window'))
            path.write_text(json.dumps({'status': 'running', 'phase': 'await-game-window'}))
            self.assertEqual(smoke.report_when(path, 'await-game-window')['phase'], 'await-game-window')
            self.assertIsNone(smoke.report_when(path, terminal=True))
            path.write_text(json.dumps(self.good_report()))
            self.assertEqual(smoke.report_when(path, terminal=True)['status'], 'passed')
            path.write_text(json.dumps({'status': 'failed', 'error': 'expected'}))
            with self.assertRaisesRegex(AssertionError, 'expected'):
                smoke.report_when(path, terminal=True)

    def test_mismatched_owned_pid_blocks_before_foreground(self):
        native = Mock()
        native.poll.return_value = None
        native.windows.return_value = [{'hwnd': 100, 'pid': 200}]
        with self.assertRaisesRegex(AssertionError, 'exact owned'):
            smoke.foreground_owned(native, {'pid': 201}, Path('own.exe'), 'client',
                                   {'hwnd': 100, 'pid': 200}, (960, 540))
        native.u.ShowWindow.assert_not_called()
        native.u.SetForegroundWindow.assert_not_called()

    def test_focus_sink_evidence_rejects_foreign_identity_geometry_or_unobserved_return(self):
        for key,new in (('sink_hwnd',100),('sink_hwnd',True),('sink_pid',999),('sink_pid',101.),
                        ('sink_class','RiotWindowClass'),('sink_title','other'),('foreground_sink_hwnd',100),
                        ('overlay_hwnd',400),('overlay_visible_before',False),('overlay_native_visible_before',False),
                        ('overlay_hidden_after',False),('client_visible_during',False),
                        ('sink_destroyed',False),('client_foreground_returned',False),
                        ('client_rect_during',{'x':20.,'y':20,'width':964,'height':602}),
                        ('client_rect_returned',{'x':21,'y':20,'width':964,'height':602})):
            value=self.good_report();value['foreground_transition'][key]=new
            with self.subTest(key=key),self.assertRaises(AssertionError):smoke.validate_report(value,'0.4.1')
        for key,new in (('sink',{'hwnd':400,'pid':999}),('request_message',smoke.WM_RETURN_OWNED_CLIENT),
                        ('request_sent',False),('response_hwnd',True),('return_sent',False),
                        ('return_response_hwnd',100),('sink_destroyed',False),('foreground_sink_hwnd',100)):
            value=self.good_aggregate();value['runs'][0]['focus_fixture'][key]=new
            with self.subTest(key=key),self.assertRaises(AssertionError):smoke.validate_aggregate(value,'0.4.1',frozen=True)

    def test_focus_request_checks_exact_fixture_ownership_before_sending(self):
        native=Mock()
        with patch.object(smoke,'assert_owned_window',side_effect=AssertionError('unowned')):
            with self.assertRaisesRegex(AssertionError,'unowned'):
                smoke.drive_focus_fixture(native,{},Path('owned.exe'),{'hwnd':100,'pid':101},(964,602),
                                          'testing-client-foreground-loss',{})
        native.u.SendMessageTimeoutW.assert_not_called()

    def test_focus_sink_commands_are_bounded_same_process_and_idempotent(self):
        import ctypes
        rect={'x':20,'y':20,'width':964,'height':602};window={'hwnd':100,'pid':101};sink={'hwnd':400,'pid':101}
        native=Mock();result={};foreground=[100];live=[True]
        native.windows.return_value=[sink];native.u.IsWindowVisible.return_value=True
        native.u.GetForegroundWindow.side_effect=lambda:foreground[0]
        native.u.IsWindow.side_effect=lambda hwnd:live[0]
        def send(hwnd,message,wparam,lparam,flags,timeout,response):
            self.assertEqual((hwnd,wparam,lparam,flags,timeout),(100,0,0,2,1000))
            if message==smoke.WM_FOCUS_OWNED_SINK:answer=400;foreground[0]=400
            else:
                self.assertEqual(message,smoke.WM_RETURN_OWNED_CLIENT);answer=1;foreground[0]=100;live[0]=False
            ctypes.cast(response,ctypes.POINTER(ctypes.c_size_t)).contents.value=answer
            return 1
        native.u.SendMessageTimeoutW.side_effect=send
        def get_class(hwnd,buffer,size):buffer.value=smoke.FOCUS_SINK_CLASS;return len(buffer.value)
        native.u.GetClassNameW.side_effect=get_class
        with patch.object(smoke,'assert_owned_window'),patch.object(smoke,'client_physical_rect',return_value=rect),\
             patch.object(smoke,'foreground_owned',return_value=True):
            for _ in range(2):smoke.drive_focus_fixture(native,{'pid':101},Path('own.exe'),window,(964,602),
                                                       'testing-client-foreground-loss',result)
            self.assertEqual(native.u.SendMessageTimeoutW.call_count,1)
            for _ in range(2):smoke.drive_focus_fixture(native,{'pid':101},Path('own.exe'),window,(964,602),
                                                       'requesting-client-focus-return',result)
            self.assertEqual(native.u.SendMessageTimeoutW.call_count,2)
        self.assertTrue(result['focus_fixture']['sink_destroyed'])
        self.assertTrue(result['focus_fixture']['client_foreground_returned'])

    def test_exited_owned_fixture_blocks_before_window_mutation(self):
        native = Mock()
        native.poll.return_value = 0
        with self.assertRaisesRegex(AssertionError, 'exited'):
            smoke.foreground_owned(native, {'pid': 201}, Path('own.exe'), 'client',
                                   {'hwnd': 100, 'pid': 201}, (960, 540))
        native.windows.assert_not_called()
        native.u.SetForegroundWindow.assert_not_called()

    def test_logs_are_bounded_no_png_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory).resolve() / 'work'; reports = Path(directory).resolve() / 'reports'
            logs = work / 'state' / 'logs'; logs.mkdir(parents=True); reports.mkdir()
            (logs / 'diagnostic.txt').write_text('original test')
            (logs / 'screen.png').write_bytes(b'never collect screenshots')
            (work / 'client-ready.json.error.txt').write_text('original error')
            self.assertEqual(smoke.collect_logs(work, reports),
                             ['windows-selection-diagnostic.txt', 'windows-selection-client-ready.json.error.txt'])
            (logs / 'large.txt').write_bytes(b'x' * (smoke.MAX_LOG_BYTES + 1))
            with self.assertRaisesRegex(AssertionError, 'bound'):
                smoke.collect_logs(work, reports)

    def test_failed_native_report_is_preserved_exactly_in_rendered_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);reports=root/'reports';reports.mkdir();path=root/'owned.json';result={}
            smoke.preserve_native_report(path,reports,result)
            self.assertEqual(result,{'native_report_present':False})
            value={'status':'running','phase':'recovering-foreground','checks':['owned pixels'],
                   'diagnostic_state':{'ocr_busy':True,'capture_pending':True,'status':'fixture state'}}
            payload=(json.dumps(value,ensure_ascii=False)+'\n').encode('utf-8');path.write_bytes(payload)
            smoke.preserve_native_report(path,reports,result)
            self.assertTrue(result['native_report_present'])
            self.assertEqual(result['native_report_snapshot'],value)
            self.assertEqual(result['native_report_snapshot_sha256'],smoke.sha256(path))
            self.assertEqual((reports/path.name).read_bytes(),payload)
            self.assertNotIn('detail',result)
            self.assertNotIn('status',result)  # Diagnostic retention never turns a failed run into a pass.

    def test_completed_snapshot_requires_exact_bytes_and_type_sensitive_full_value(self):
        for change in ('whitespace','extra-field','bool-int','int-float','failed','name','process','cleanup'):
            with self.subTest(change=change),tempfile.TemporaryDirectory() as directory:
                root=Path(directory);reports=root/'reports';reports.mkdir();path=root/'owned.json'
                detail=self.producer_report(frozen=True,scale=1)
                detail['diagnostic_state']['type_probe']={'flag':True,'count':1}
                original=(json.dumps(detail,ensure_ascii=False,indent=2)+'\n').encode('utf8')
                path.write_bytes(original)
                result={'detail':copy.deepcopy(detail),'native_report':path.name,
                        'native_report_sha256':smoke.sha256(path),'process_exited':True,'owned_processes_exited':True}
                observed=copy.deepcopy(detail)
                if change=='whitespace':path.write_bytes(original+b'\n')
                elif change=='name':result['native_report']='other.json'
                elif change=='process':result['process_exited']=False
                elif change=='cleanup':result['owned_processes_exited']=False
                else:
                    if change=='extra-field':observed['new_unobserved_evidence']={'message':'完整新证据'}
                    elif change=='bool-int':observed['diagnostic_state']['type_probe']['flag']=1
                    elif change=='int-float':observed['diagnostic_state']['type_probe']['count']=1.0
                    else:observed.update(status='failed',error='original terminal failure',error_traceback='original trace')
                    diagnostic.atomic_report(path,observed)
                    # Match the raw hash to isolate the parsed-value check.
                    result['native_report_sha256']=smoke.sha256(path)
                if change in ('bool-int','int-float'):self.assertEqual(detail,observed)
                payload=path.read_bytes()
                with self.assertRaisesRegex(AssertionError,'changed after validation|lacks successful'):
                    smoke.preserve_native_report(path,reports,result,completed=True)
                self.assertEqual((reports/path.name).read_bytes(),payload)
                self.assertEqual(result['native_report_snapshot'],observed)
                self.assertEqual(result['native_report_snapshot_sha256'],smoke.sha256(path))
                self.assertEqual(json.dumps(result['detail'],sort_keys=True),json.dumps(detail,sort_keys=True))
                self.assertNotIn('status',result)

    def test_failed_or_incomplete_cleanup_keeps_full_snapshot_even_with_matching_detail(self):
        for status in ('running','failed','passed'):
            with self.subTest(status=status),tempfile.TemporaryDirectory() as directory:
                root=Path(directory);reports=root/'reports';reports.mkdir();path=root/'owned.json'
                detail=self.producer_report(frozen=False,scale=1)
                observed=copy.deepcopy(detail);observed['status']=status
                if status=='running':observed['phase']='recovering-foreground'
                if status=='failed':observed.update(error='original failure',error_type='RuntimeError',error_traceback='original trace')
                diagnostic.atomic_report(path,observed);payload=path.read_bytes()
                result={'detail':detail,'native_report':path.name,'native_report_sha256':smoke.sha256(path),
                        'process_exited':True,'owned_processes_exited':True}
                failure=RuntimeError('original outer cleanup failure')
                try:raise failure
                except RuntimeError:
                    smoke.preserve_native_report(path,reports,result,completed=sys.exc_info()[0] is None)
                    self.assertIs(sys.exc_info()[1],failure)
                self.assertEqual(result['native_report_snapshot'],observed)
                self.assertEqual((reports/path.name).read_bytes(),payload)
                self.assertEqual(result['native_report_snapshot_sha256'],smoke.sha256(path))
                self.assertEqual(result['detail'],detail)

    def test_successful_snapshot_accepts_key_order_only_and_missing_raw_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);reports=root/'reports';reports.mkdir();path=root/'owned.json'
            detail=self.producer_report(frozen=False,scale=1)
            diagnostic.atomic_report(path,detail)
            result={'detail':dict(reversed(list(detail.items()))),'native_report':path.name,
                    'native_report_sha256':smoke.sha256(path),'process_exited':True,'owned_processes_exited':True}
            smoke.preserve_native_report(path,reports,result,completed=True)
            self.assertNotIn('native_report_snapshot',result)
            path.unlink()
            with self.assertRaisesRegex(AssertionError,'native report is missing'):
                smoke.preserve_native_report(path,reports,result,completed=True)
            self.assertFalse(result['native_report_present'])

    def test_native_diagnostic_rejects_oversized_invalid_and_nonobject_json(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);reports=root/'reports';reports.mkdir();path=root/'owned.json'
            for payload,error in ((b'x'*(smoke.MAX_LOG_BYTES+1),AssertionError),
                                  (b'{',json.JSONDecodeError),(b'[]',AssertionError)):
                with self.subTest(payload_size=len(payload)):
                    path.write_bytes(payload)
                    with self.assertRaises(error):smoke.preserve_native_report(path,reports,{})
                    self.assertFalse((reports/path.name).exists())

    def test_lifecycle_contract_launches_new_game_only_after_app_request(self):
        source = Path(smoke.__file__).read_text()
        self.assertLess(source.index("Deadline.wait(awaiting_game"), source.index("game = native.spawn"))
        self.assertIn("'scope': 'owned-synthetic-only'", source)
        self.assertIn("native.wait_exit(app", source)
        self.assertIn('native.close_window(window)', source)
        self.assertIn('lambda: not native.pids()', source)
        self.assertIn('native.cleanup()', source)
        self.assertIn('preserve_native_report(current_handoff,reports,result,completed=sys.exc_info()[0] is None)',source)
        self.assertIn('work = work.resolve()', source)
        self.assertIn('handoff_path = work / native_report_name(frozen, scale)', source)
        self.assertIn('for scale in SCALES:', source)
        self.assertIn("phase in ('testing-client-foreground-loss','requesting-client-focus-return')",source)
        self.assertIn('print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)', source)
        self.assertLessEqual(smoke.MAX_SECONDS + smoke.DIRECTORY_CLEANUP_SECONDS, 270)
        self.assertEqual(smoke.JOB_CLEANUP_SECONDS, 15)
        for forbidden in ('SendInput', 'AttachThreadInput', 'SetWindowsHookEx', 'ReadProcessMemory',
                          'WriteProcessMemory', 'resolver=', 'taskkill', 'TerminateProcess(', 'ChangeDisplaySettings'):
            self.assertNotIn(forbidden, source)
        self.assertIn('synthetic policy', source.replace('\n', ' '))

    def test_source_imports_no_production_identity_stubs(self):
        tree = ast.parse(Path(smoke.__file__).read_text())
        modules = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        self.assertNotIn('session_windows', modules)
        self.assertNotIn('unittest.mock', modules)
        self.assertIn('windows_ota_smoke', modules)


if __name__ == '__main__':
    unittest.main()

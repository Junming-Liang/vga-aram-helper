"""Exact one-file owner contracts using Run84 identities and native API fakes."""
import copy
import ctypes
from pathlib import Path
from types import SimpleNamespace
import unittest
import tempfile
import json
import selection_smoke as diagnostic
from unittest.mock import Mock,patch

import windows_selection_smoke as smoke
from windows_ota_smoke import NativeJob
from session_windows import ProcessMetadata
import test_windows_selection_smoke as fixtures


class OwnedApplicationProcessTests(unittest.TestCase):
    # Actual Run84 exported values. Parent lineage was NOT retained in that run;
    # the fake direct-parent record below is a regression input, not CI proof.
    LAUNCH_PID=2056;OWNER_PID=6024;HWND=2228752
    LAUNCH_CREATED=134368257972497252;OWNER_CREATED=134368257988878017

    def fixture(self,*,frozen=True,change=None):
        pid=self.OWNER_PID if frozen else self.LAUNCH_PID
        created=self.OWNER_CREATED if frozen else self.LAUNCH_CREATED
        app={'pid':self.LAUNCH_PID,'handle':501};launcher={'pid':app['pid'],'created':self.LAUNCH_CREATED}
        initial={'source_pid':pid,'source_created':created,'source_hwnd':self.HWND}
        evidence={};kernel=Mock();native=SimpleNamespace(k=kernel,u=Mock());snapshots=[0];observations=[0]
        native.poll=lambda process:NativeJob.poll(native,process)
        members={app['pid'],pid}
        if change=='sibling':members.add(777)  # Same Job and image, but a different live launch.
        if change=='other-job':members.discard(pid)
        if change=='missing-launcher-job':members.discard(app['pid'])
        native.pids=Mock(return_value=members)
        if change=='job-after':native.pids.side_effect=[members,members,members,{app['pid']}]
        def window(hwnd,pointer):
            self.assertEqual(hwnd,self.HWND);observations[0]+=1
            observed=pid if change!='wrong-hwnd' and not(change=='hwnd-after' and observations[0]>2) else 999
            ctypes.cast(pointer,ctypes.POINTER(smoke.W.DWORD)).contents.value=observed
            return 0 if change=='dead-hwnd' else 1
        native.u.GetWindowThreadProcessId.side_effect=window
        kernel.OpenProcess.return_value=0 if change=='open-denied' else 502
        def wait(handle,timeout):
            self.assertEqual(timeout,0)
            if change=='launcher-exited' and handle==501:return 0
            if change=='owner-exited' and handle==502:return 0
            if change=='owner-exited-after' and handle==502 and observations[0]>2:return 0
            return 258
        kernel.WaitForSingleObject.side_effect=wait
        kernel.GetExitCodeProcess.return_value=True
        def times(handle,output,*rest):
            value=self.LAUNCH_CREATED if handle==501 else created
            if change=='launcher-reused' and handle==501:value+=1
            if change=='owner-reused' and handle==502:value+=1
            if change=='owner-reused-after' and handle==502 and observations[0]>2:value+=1
            output._obj.dwLowDateTime=value&0xffffffff;output._obj.dwHighDateTime=value>>32;return True
        kernel.GetProcessTimes.side_effect=times
        kernel.CloseHandle.side_effect=lambda handle:not(change=='close-failed' and handle==502)
        kernel.CreateToolhelp32Snapshot.return_value=901
        if change=='snapshot-failed':kernel.CreateToolhelp32Snapshot.return_value=ctypes.c_void_p(-1).value
        def first(handle,pointer):
            self.assertEqual(handle,901);snapshots[0]+=1
            entry=pointer._obj;entry.th32ProcessID=pid
            entry.th32ParentProcessID=app['pid'] if change not in ('wrong-parent','sibling') else 777
            if change=='parent-after' and snapshots[0]>1:entry.th32ParentProcessID=777
            return True
        kernel.Process32FirstW.side_effect=first;kernel.Process32NextW.return_value=False
        calls=[0]
        def metadata(observed):
            calls[0]+=1
            path=r'c:\owned\helper.exe';time=self.LAUNCH_CREATED if observed==app['pid'] else created
            if change=='wrong-image' and observed==pid:path=r'c:\other\helper.exe'
            if change=='metadata-reused' and observed==pid:time+=1
            if change=='metadata-after' and observed==pid and calls[0]>3:time+=1
            return ProcessMetadata(path,time)
        return native,app,launcher,initial,evidence,metadata,snapshots

    def run_binding(self,*,frozen=True,change=None):
        native,app,launcher,initial,evidence,metadata,snapshots=self.fixture(frozen=frozen,change=change)
        with patch('session_windows.process_metadata',side_effect=metadata),\
             patch('session_windows.final_image_path',return_value=r'c:\owned\helper.exe'),\
             patch.object(ctypes,'WinDLL',return_value=native.k,create=True),\
             patch.object(smoke,'sha256',side_effect=['a'*64,'b'*64] if change=='hash-after' else None,
                          return_value='b'*64 if change=='wrong-hash' else 'a'*64):
            result=smoke.bind_application_owner(native,app,Path('owned.exe'),initial,launcher,
                frozen=frozen,executable_sha256='a'*64 if frozen else None,evidence=evidence)
        return result,native,launcher,evidence,snapshots

    def test_real_run84_values_bind_only_with_verified_direct_child_lineage(self):
        owner,native,launcher,evidence,snapshots=self.run_binding()
        self.assertEqual(owner,dict(pid=6024,created=134368257988878017,hwnd=2228752))
        self.assertEqual(snapshots[0],2)
        native.k.OpenProcess.assert_called_once_with(0x101000,False,6024)
        self.assertEqual(native.k.CloseHandle.call_args_list[-1].args,(502,))
        row=dict(application_process=owner,application_launcher=launcher,application_binding=evidence)
        smoke.validate_application_binding(row,{f'source_{k}':v for k,v in owner.items()},frozen=True)
        self.assertEqual(evidence['observed_owner_pid'],6024);self.assertEqual(evidence['status'],'passed')

    def test_source_stays_exact_launch_and_never_uses_parent_snapshot(self):
        owner,_,launcher,evidence,snapshots=self.run_binding(frozen=False)
        self.assertEqual(owner['pid'],launcher['pid']);self.assertEqual(owner['created'],launcher['created'])
        self.assertEqual(snapshots[0],0)
        smoke.validate_application_binding(dict(application_process=owner,application_launcher=launcher,
            application_binding=evidence),{f'source_{k}':v for k,v in owner.items()},frozen=False)
        native,app,launcher,initial,evidence,metadata,_=self.fixture(frozen=True)
        with patch('session_windows.process_metadata',side_effect=metadata),\
             patch('session_windows.final_image_path',return_value=r'c:\owned\helper.exe'):
            with self.assertRaisesRegex(RuntimeError,'exact Popen child'):
                smoke.bind_application_owner(native,app,Path('owned.exe'),initial,launcher,
                    frozen=False,executable_sha256=None,evidence=evidence)
        native.k.CloseHandle.assert_called_once_with(502)

    def test_foreign_sibling_reused_exited_and_racing_owners_fail_with_fixed_evidence(self):
        changes=('other-job','missing-launcher-job','job-after','wrong-hwnd','dead-hwnd','hwnd-after',
            'open-denied','launcher-exited','owner-exited','owner-exited-after','launcher-reused','owner-reused',
            'owner-reused-after','wrong-parent','sibling','parent-after','snapshot-failed','wrong-image',
            'metadata-reused','metadata-after','wrong-hash','hash-after','close-failed')
        for change in changes:
            with self.subTest(change=change):
                native,app,launcher,initial,evidence,metadata,_=self.fixture(change=change)
                with patch('session_windows.process_metadata',side_effect=metadata),\
                     patch('session_windows.final_image_path',return_value=r'c:\owned\helper.exe'),\
                     patch.object(ctypes,'WinDLL',return_value=native.k,create=True),\
                     patch.object(smoke,'sha256',side_effect=['a'*64,'b'*64] if change=='hash-after' else None,
                                  return_value='b'*64 if change=='wrong-hash' else 'a'*64):
                    with self.assertRaises((AssertionError,RuntimeError)):
                        smoke.bind_application_owner(native,app,Path('owned.exe'),initial,launcher,
                            frozen=True,executable_sha256='a'*64,evidence=evidence)
                self.assertEqual(evidence['status'],'failed');self.assertNotEqual(evidence['stage'],'complete')
                self.assertEqual(evidence['launcher'],launcher);self.assertEqual(evidence['reported_owner']['pid'],6024)
                if native.k.OpenProcess.called and change!='open-denied':
                    self.assertEqual(native.k.CloseHandle.call_args_list[-1].args,(502,))
                if change in ('wrong-hwnd','hwnd-after'):
                    self.assertEqual(evidence['observed_owner_pid'],0)
                    self.assertEqual(evidence['observed_owner_scope'],'outside-job')
                before=copy.deepcopy(evidence)
                with self.assertRaisesRegex(AssertionError,'must not be retried'):
                    smoke.bind_application_owner(native,app,Path('owned.exe'),initial,launcher,
                        frozen=True,executable_sha256='a'*64,evidence=evidence)
                self.assertEqual(evidence,before)

    def test_strict_typed_topology_receipts_all_scales_and_source_frozen(self):
        harness=fixtures.SelectionHarnessTests()
        for frozen in (False,True):
            for index in range(3):
                mutations=[('status','failed'),('stage','input'),('mode','source-direct' if frozen else 'onefile-child'),
                    ('observed_owner_pid',True),('observed_owner_pid',999),('observed_owner_scope','outside-job'),
                    ('launcher',{}),('reported_owner',{}),('proof',{})]
                mutations += [(key,bad) for key in ('launcher_live','owner_live','job_verified','hwnd_verified',
                    'creation_verified','image_verified','lineage_verified','revalidated') for bad in (False,1)]
                for key,value in mutations:
                    aggregate=harness.good_aggregate(frozen=frozen);row=aggregate['runs'][index]
                    row['application_binding'][key]=value
                    with self.subTest(frozen=frozen,index=index,key=key,value=value),self.assertRaises(AssertionError):
                        smoke.validate_aggregate(aggregate,'0.4.1',frozen=frozen)
                aggregate=harness.good_aggregate(frozen=frozen);row=aggregate['runs'][index]
                launcher=row['application_launcher'];owner=row['application_process']
                launcher['pid']=owner['pid'] if frozen else owner['pid']+1
                row['application_binding']['launcher']=dict(launcher)
                row['application_binding']['proof']['launcher_pid']=launcher['pid']
                with self.assertRaises(AssertionError):smoke.validate_aggregate(aggregate,'0.4.1',frozen=frozen)

    def test_maximum_width_owner_receipts_fit_full_success_and_failed_evidence_caps(self):
        harness=fixtures.SelectionHarnessTests()
        for frozen in (False,True):
            with self.subTest(frozen=frozen),tempfile.TemporaryDirectory() as directory:
                root=Path(directory);value,reports,_=harness.execute_producer_aggregate(root,frozen=frozen)
                for row in value['runs']:
                    owner=row['application_process'];owner.update(pid=2**32-1,created=2**63-1,hwnd=2**63-1)
                    launcher=row['application_launcher'];launcher.update(pid=2**32-2 if frozen else owner['pid'],
                        created=2**63-2 if frozen else owner['created'])
                    row['detail']['initial_focus'].update({f'source_{k}':v for k,v in owner.items()})
                    binding=row['application_binding'];binding.update(launcher=dict(launcher),reported_owner=dict(owner),
                        observed_owner_pid=owner['pid'],proof=dict(launcher_pid=launcher['pid'],launcher_created=launcher['created'],
                            owner_pid=owner['pid'],owner_created=owner['created'],owner_ancestry_verified=True))
                    raw=reports/row['native_report'];diagnostic.atomic_report(raw,row['detail'])
                    row['native_report_sha256']=row['native_report_snapshot_sha256']=smoke.sha256(raw)
                value.update({key:copy.deepcopy(value['runs'][0][key]) for key in smoke.LEGACY_FIELDS})
                smoke.validate_aggregate(value,'0.4.1',frozen=frozen)
                path=reports/'complete.json';smoke.write_json(path,value)
                self.assertLess(path.stat().st_size,64*1024)
                failed=copy.deepcopy(value);row=failed['runs'][2]
                snapshot=copy.deepcopy(row['detail']);snapshot.update(status='failed',error='x'*2000,error_traceback='y'*4000)
                row.update(native_report_snapshot=snapshot,process_exited=False,owned_processes_exited=False)
                row['application_binding'].update(status='failed',stage='lineage-after',revalidated=False)
                failed.update(status='failed',error='z'*2000)
                path=reports/'failed.json';smoke.write_json(path,failed)
                self.assertLess(path.stat().st_size,64*1024)
                self.assertEqual(json.loads(path.read_bytes()),failed)

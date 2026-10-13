"""Filesystem evidence is local, bounded, non-mutating and privacy-minimized."""
import errno
import json
import os
from pathlib import Path
import stat
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import hero_portraits as portraits
import portrait_cache_diagnostics as diagnostics
from test_portrait_cache import fetcher,windows_error,windows_read_lock


class PortraitCacheDiagnosticTests(unittest.TestCase):
    def write(self,path):
        return portraits._write_cache(path,b'new',cancelled=threading.Event(),deadline=time.monotonic()+5)

    def test_replace_failure_records_stage_closed_temp_and_errors_without_paths(self):
        with tempfile.TemporaryDirectory(prefix='PRIVATE_USERNAME-') as temp:
            path=Path(temp)/'16.20.1/Briar.png'
            path.parent.mkdir();path.write_bytes(b'old')
            with patch.object(portraits.os,'replace',side_effect=windows_error(5)), \
                 patch.object(portraits,'_CACHE_RETRY_DELAYS',(0,0,0)):
                with self.assertRaises(OSError) as result:self.write(path)
            evidence=result.exception.cache_diagnostic
            self.assertEqual(evidence['stage'],'replace')
            self.assertEqual(evidence['asset'],'Briar.png')
            self.assertEqual(evidence['version'],'16.20.1')
            self.assertTrue(evidence['tempCreated'] and evidence['tempFlushed'] and evidence['tempClosed'])
            self.assertTrue(evidence['sourceAndDestinationSameParent'])
            self.assertTrue(evidence['source']['exists'] and evidence['destination']['exists'])
            self.assertEqual([row['winerror'] for row in evidence['attemptErrors']],[5]*4)
            self.assertIsInstance(evidence['processId'],int)
            text=json.dumps(evidence)
            self.assertNotIn(temp,text);self.assertNotIn('PRIVATE_USERNAME',text)
            self.assertNotIn('Synthetic Windows sharing error',text)

    def test_temp_creation_failure_is_distinct_from_replace(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(portraits.tempfile,'mkstemp',side_effect=PermissionError(errno.EACCES,'PRIVATE_PATH')):
                with self.assertRaises(OSError) as result:self.write(Path(temp)/'Briar.png')
            evidence=result.exception.cache_diagnostic
            self.assertEqual(evidence['stage'],'create-temp')
            self.assertFalse(evidence['tempCreated'])
            self.assertNotIn('destinationDeleteAccess',evidence)
            self.assertNotIn('PRIVATE_PATH',json.dumps(evidence))

    def test_flush_failure_still_records_closed_file_handle(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(portraits.os,'fsync',side_effect=OSError(errno.ENOSPC,'Full')):
                with self.assertRaises(OSError) as result:self.write(Path(temp)/'Briar.png')
            evidence=result.exception.cache_diagnostic
            self.assertEqual(evidence['stage'],'flush-temp')
            self.assertTrue(evidence['tempCreated'] and evidence['tempClosed'])
            self.assertFalse(evidence['tempFlushed'])
            self.assertEqual(evidence['error']['errno'],errno.ENOSPC)

    def test_transient_failure_records_recovery_without_claiming_why(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'Briar.png';replace=os.replace;attempts=[]
            def once(source,destination):
                attempts.append(source)
                if len(attempts)==1:raise windows_error(32)
                return replace(source,destination)
            with patch.object(portraits.os,'replace',side_effect=once), \
                 patch.object(portraits,'_CACHE_RETRY_DELAYS',(0,0,0)):
                evidence=self.write(path)
            self.assertEqual(evidence['outcome'],'recovered-after-retry')
            self.assertEqual(evidence['attemptErrors'],[{'stage':'replace','errno':errno.EACCES,'winerror':32}])
            self.assertEqual(path.read_bytes(),b'new')

    def test_readonly_attribute_is_observed_without_changing_it(self):
        details=SimpleNamespace(st_mode=stat.S_IFREG|0o444,st_size=123,st_file_attributes=1)
        with patch.object(Path,'lstat',return_value=details):
            observed=diagnostics.file_snapshot(Path('Briar.png'))
        self.assertTrue(observed['windowsReadOnly'])
        self.assertFalse(observed['windowsReparsePoint'])
        self.assertEqual(observed['sizeBytes'],123)

    def test_same_parent_comparison_normalizes_relative_cache_without_recording_it(self):
        result=diagnostics.capture_failure(Path('cache/Briar.png'),Path.cwd()/'cache/.temporary',
            'replace',windows_error(),temp_created=True,temp_flushed=True,temp_closed=True)
        self.assertTrue(result['sourceAndDestinationSameParent'])
        self.assertNotIn(str(Path.cwd()),json.dumps(result))

    def test_unrecognized_asset_name_is_not_copied_into_report(self):
        result=diagnostics.capture_failure(Path('PRIVATE_USERNAME.secret'),None,'create-temp',
            PermissionError(errno.EACCES,'PRIVATE_PATH'),temp_created=False,temp_flushed=False,temp_closed=False)
        self.assertEqual(result['asset'],'other-cache-file')
        self.assertNotIn('PRIVATE_',json.dumps(result))

    def test_report_count_size_and_private_persistence_are_bounded(self):
        details=diagnostics.report([{'stage':'replace','error':{'winerror':5}}]*20)
        self.assertEqual(len(details['failures']),6)
        with tempfile.TemporaryDirectory() as temp:
            cache=Path(temp)/'hero-portraits'
            self.assertTrue(diagnostics.save_report(cache,details))
            saved=Path(temp)/'logs'/diagnostics.REPORT_NAME
            self.assertLess(saved.stat().st_size,32*1024)
            self.assertEqual(json.loads(saved.read_text()),details)
            self.assertFalse(diagnostics.save_report(cache,{'oversize':'a'*(32*1024)}))
            self.assertEqual(json.loads(saved.read_text()),details)

    def test_persistent_error_is_retained_when_recovered_errors_fill_report(self):
        records=[]
        for _ in range(8):diagnostics.retain_failure(records,{'outcome':'recovered-after-retry'})
        self.assertEqual(len(records),6)
        failure={'outcome':'failed','error':{'winerror':5}}
        diagnostics.retain_failure(records,failure)
        self.assertEqual(len(records),6)
        self.assertIn(failure,records)
        for _ in range(8):diagnostics.retain_failure(records,{'outcome':'recovered-after-retry'})
        self.assertIn(failure,records)
        self.assertEqual(len(records),6)

    def test_unwritable_report_does_not_mask_original_failure(self):
        with patch.object(diagnostics,'atomic_write',side_effect=PermissionError('PRIVATE_PATH')):
            self.assertFalse(diagnostics.save_report(Path('cache'),diagnostics.report([])))

    @patch.object(portraits,'decode_portrait',side_effect=lambda payload:'decoded:'+payload.decode())
    def test_complete_bank_retains_evidence_when_local_log_cannot_be_saved(self,_):
        with tempfile.TemporaryDirectory() as temp:
            cache=Path(temp)/'hero-portraits';replace=os.replace
            write=portraits._write_cache;retain=diagnostics.retain_failure
            replace_started=threading.Event();contention_recorded=threading.Event()
            # Six workers report in completion order. Force a real bounded
            # in-process lock timeout (which has no WinError) before Hero0's
            # injected replacement error. Never assume the first record is it.
            def ordered_write(path,payload,**kwargs):
                if Path(path).name!='Hero0.png':self.assertTrue(replace_started.wait(5))
                return write(path,payload,**kwargs)
            def denied(source,destination):
                if Path(destination).name=='Hero0.png':
                    replace_started.set()
                    raise windows_error(5)
                return replace(source,destination)
            def retain_and_signal(records,diagnostic):
                retain(records,diagnostic)
                if diagnostic['stage']=='acquire-lock':contention_recorded.set()
            def controlled_probe(path):
                self.assertTrue(contention_recorded.wait(5))
                return {'state':'test-controlled-probe'}
            with patch.object(portraits.os,'replace',side_effect=denied), \
                 patch.object(portraits,'_write_cache',side_effect=ordered_write), \
                 patch.object(portraits,'_CACHE_LOCKS',(threading.Lock(),)), \
                 patch.object(portraits,'_CACHE_LOCK_TIMEOUT',0.05), \
                 patch.object(portraits,'_CACHE_RETRY_DELAYS',(0,0,0)), \
                 patch.object(diagnostics,'sharing_probe',side_effect=controlled_probe), \
                 patch.object(diagnostics,'retain_failure',side_effect=retain_and_signal), \
                 patch.object(diagnostics,'save_report',return_value=False):
                bank,status=portraits.load_portraits(cache,fetcher=fetcher())
            self.assertEqual(len(bank),100)
            self.assertEqual(status['state'],'memory-only')
            self.assertFalse(status['cacheDiagnosticSaved'])
            failures=status['cacheDiagnostics']['failures']
            self.assertEqual(failures[0]['stage'],'acquire-lock')
            self.assertNotIn('winerror',failures[0]['error'])
            target=[row for row in failures if row['asset']=='Hero0.png' and row['stage']=='replace']
            self.assertEqual(len(target),1,failures)
            self.assertEqual(target[0]['error']['winerror'],5)
            self.assertEqual([row['winerror'] for row in target[0]['attemptErrors']],[5]*4)
            self.assertIn('头像缓存诊断',status['message'])


@unittest.skipUnless(os.name=='nt','Requires actual Windows filesystem semantics')
class WindowsPortraitDiagnosticTests(unittest.TestCase):
    def write(self,path):
        return portraits._write_cache(path,b'new',cancelled=threading.Event(),deadline=time.monotonic()+5)

    def test_sharing_probe_observes_real_lock_without_mutating_target(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'Briar.png';path.write_bytes(b'old')
            self.assertEqual(diagnostics.sharing_probe(path)['state'],'opened')
            with windows_read_lock(path):
                result=diagnostics.sharing_probe(path)
            self.assertEqual(result,{'state':'denied','winerror':32})
            self.assertEqual(path.read_bytes(),b'old')

    def test_normal_python_cache_reader_can_reproduce_transient_replace_denial(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'Briar.png';path.write_bytes(b'old')
            with path.open('rb') as reader:
                replace=os.replace
                def observed(source,destination):
                    try:return replace(source,destination)
                    except OSError:
                        reader.close()
                        raise
                with patch.object(portraits.os,'replace',side_effect=observed):evidence=self.write(path)
            self.assertEqual(evidence['outcome'],'recovered-after-retry')
            self.assertIn(evidence['error']['winerror'],(5,32,33))
            self.assertEqual(path.read_bytes(),b'new')

    def test_owned_readonly_fixture_reproduces_winerror5_without_acl_changes(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'Briar.png';path.write_bytes(b'old')
            # Only this disposable fixture's DOS read-only attribute is changed.
            # No user cache, ACL, privilege, antivirus or security setting changes.
            os.chmod(path,stat.S_IREAD)
            try:
                with patch.object(portraits,'_CACHE_RETRY_DELAYS',(0,0,0)):
                    with self.assertRaises(PermissionError) as result:self.write(path)
                evidence=result.exception.cache_diagnostic
                self.assertEqual(evidence['error']['winerror'],5)
                self.assertTrue(evidence['destination']['windowsReadOnly'])
                self.assertEqual(path.read_bytes(),b'old')
            finally:os.chmod(path,stat.S_IREAD|stat.S_IWRITE)


if __name__=='__main__':unittest.main()

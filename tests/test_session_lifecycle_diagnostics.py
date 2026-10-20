"""Synthetic bounded lifecycle evidence; never live Windows compatibility proof."""
import unittest
from unittest.mock import patch
from test_persistent_capture_adapter import AdapterFixture
from local_debug import _fields
from wgc_capture import WgcError

class LifecycleDiagnosticTests(AdapterFixture,unittest.TestCase):
    def test_read_only_snapshot_never_constructs_or_renews(self):
        epoch=self.adapter.epoch
        value=dict(self.adapter.lifecycle_diagnostic)
        self.assertEqual(value,dict(session_owners=0,session_retirements=0,session_owner_state='absent',session_failure='none'))
        self.assertFalse(self.adapter.has_live_visible_session)
        self.assertEqual(self.adapter.epoch,epoch)
        self.factory.assert_not_called();self.proof.assert_not_called()
    def test_owner_counter_reuse_and_native_idle_timeout(self):
        self.capture();self.capture()
        value=dict(self.adapter.lifecycle_diagnostic)
        self.assertEqual(value['session_owners'],1)
        self.assertEqual(value['session_owner_state'],'active')
        self.assertFalse(self.adapter.has_live_visible_session)
        transport=self.sessions[0]._transport
        transport.failure=WgcError('timeout','private text not retained')
        transport.request_deadline=None;transport.revoked.set()
        value=dict(self.adapter.lifecycle_diagnostic)
        self.assertEqual(value['session_failure'],'idle_timeout')
        self.assertEqual(value['session_owner_state'],'native_revoked')
        self.assertNotIn('private',str(value))
        self.adapter.retire();self.adapter.retire()
        self.assertEqual(self.adapter.lifecycle_diagnostic['session_retirements'],1)
    def test_sink_enums_and_numeric_fields_are_allowlisted(self):
        values=dict(session_owners=2,session_retirements=1,session_owner_state='active',session_failure='idle_timeout',session_request_age_ms=4100.)
        self.assertEqual(_fields(values),values)
        self.assertEqual(_fields(dict(session_owner_state='private path',session_failure='secret',session_owners=-1,session_request_age_ms=float('inf'))),{})
if __name__=='__main__':unittest.main()

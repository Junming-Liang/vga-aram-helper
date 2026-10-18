"""Synthetic initial-stage event coverage; no real window or player data."""
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
import zipfile
from tests import test_native_capture_worker as fixture
from tests import test_semantic_title_recheck as semantic_fixture

@unittest.skipIf(fixture.QtWidgets is None, 'Optional Qt runtime missing')
class InitialStageDiagnosticsTests(unittest.TestCase):
    setUpClass=classmethod(fixture.NativeCaptureWorkerTests.setUpClass.__func__)
    setUp=fixture.NativeCaptureWorkerTests.setUp
    wait=fixture.NativeCaptureWorkerTests.wait
    dispose_window=fixture.NativeCaptureWorkerTests.dispose_window
    accepted_proof_fixture=fixture.NativeCaptureWorkerTests.accepted_proof_fixture
    scene=semantic_fixture.SemanticTitleRecheckTests.scene

    def exported(self):
        path=self.window.debug_log.export_zip(Path(self.directory.name)/'exports',config={})
        with zipfile.ZipFile(path) as archive:
            text='\n'.join(archive.read(name).decode() for name in archive.namelist())
            rows=[]
            for name in ('events.jsonl','critical.jsonl','context.jsonl'):
                rows.extend(json.loads(line) for line in archive.read(name).splitlines())
        self.assertNotIn('PRIVATE_',text)
        return rows

    def test_discovery_connected_is_not_misreported_as_successful_adoption(self):
        w=self.window;w.target=None;w.discovery_scope=7
        policy=SimpleNamespace(bound=None,adopt=lambda *a,**k:False)
        w.automatic_policy=policy;w.capture=SimpleNamespace(windows=lambda **k:[])
        value=SimpleNamespace(confirmation=None,candidate=True,reason='PRIVATE_TITLE',reason_code='game_connected',diagnostics=())
        try:
            w.apply_discovery(value,7)
            rows=self.exported()
            self.assertTrue(any(r['event']=='job' and r.get('reason')=='game_connected' for r in rows))
            self.assertTrue(any(r['event']=='window_binding' and r.get('binding_outcome')=='adoption_rejected' for r in rows))
            self.assertFalse(any(r.get('binding_outcome')=='adopted' for r in rows))
            self.assertIsNone(w.target)
        finally:w.automatic_policy=None

    def test_accepted_binding_has_explicit_outcome_without_native_identity(self):
        from screen_capture import WindowInfo
        from session_windows import ProcessMetadata
        w=self.window;w.target=None;w.discovery_scope=8
        target=WindowInfo(98765,87654,'PRIVATE_TITLE','PRIVATE_CLASS')
        candidate=SimpleNamespace(window=target,role='game',metadata=ProcessMetadata('C:/PRIVATE_PATH/game.exe',111))
        policy=SimpleNamespace(bound=None)
        def adopt(*a,**k):policy.bound=candidate;return True
        policy.adopt=adopt;w.automatic_policy=policy;w.capture=SimpleNamespace(windows=lambda **k:[])
        value=SimpleNamespace(confirmation=None,candidate=candidate,reason='PRIVATE_TITLE',reason_code='game_connected',diagnostics=())
        try:
            w.apply_discovery(value,8)
            rows=self.exported()
            self.assertTrue(any(r['event']=='window_binding' and r.get('binding_outcome')=='adopted' and r.get('target_role')=='game' for r in rows))
            self.assertIs(w.target,target)
        finally:w.automatic_policy=None

    def test_missing_cards_are_logged_even_when_hero_is_unknown(self):
        value,_,_=self.scene();w=self.window
        value.update(automatic_candidates=[],candidates=[],partial_title_evidence=None,
                     hero_observation={'hero':None,'confident':False,'reason':'PRIVATE_FAILURE'})
        w.task_result('ocr',value,w.state.generation)
        rows=self.exported()
        row=next(r for r in rows if r['event']=='card_observation' and r.get('serial')==value['_captureSerial'])
        self.assertEqual(row['reason'],'candidate_missing');self.assertEqual(row['candidate_count'],0)
        self.assertFalse(row['hero_present']);self.assertFalse(row['title_evidence_valid'])
        self.assertFalse(w.state.confirmed)
        self.assertTrue(any(r['event']=='recognition' and r.get('reason')=='hero_unknown' for r in rows))

    def test_valid_cards_remain_distinguishable_from_unknown_identity(self):
        value,_,_=self.scene();w=self.window
        value['hero_observation']={'hero':None,'confident':False,'reason':'PRIVATE_FAILURE'}
        w.task_result('ocr',value,w.state.generation)
        rows=self.exported()
        row=next(r for r in rows if r['event']=='card_observation' and r.get('serial')==value['_captureSerial'])
        self.assertEqual(row['reason'],'awaiting_confirmation');self.assertEqual(row['candidate_count'],3)
        self.assertFalse(row['hero_present']);self.assertTrue(row['card_geometry_proven'])
        self.assertFalse(w.state.confirmed)

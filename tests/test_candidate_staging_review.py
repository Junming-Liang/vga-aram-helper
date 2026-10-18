"""Synthetic producer-to-retention integration checks, not Windows acceptance."""
import json
from pathlib import Path
import unittest

from scripts import check_artifact_budget as budget
from scripts import stage_verified_artifact as candidate
from tests import test_release_gate as release_tests


class CandidateStagingProducerContractTests(unittest.TestCase):
    def test_real_verifier_inventory_stages_without_rebuilding_or_changing_assets(self):
        fixture = release_tests.ReleaseFixture()
        self.addCleanup(fixture.doCleanups)
        fixture.setUp()
        # Reuse the release gate's small synthetic inputs, but run its real
        # receipt producer in the exact directory layout used by Windows CI.
        release = fixture.root / 'dist' / 'release'
        release.parent.mkdir()
        fixture.release.rename(release)
        fixture.release = release
        evidence = fixture.root / 'reports'
        fixture.evidence.rename(evidence)
        fixture.evidence = evidence
        fixture.output = fixture.root / 'build' / 'verified-preview'
        verified = fixture.verify()
        expected_exe = f'vga-aram-helper-{release_tests.VERSION}-windows-x64.exe'
        names = {row['name'] for row in verified['assets']}
        self.assertIn(expected_exe, names)
        self.assertNotIn('VGA-Aram-Helper.exe', names)
        self.assertEqual(names, candidate.expected_names(release_tests.VERSION))
        original_assets = {row['name']: Path(row['path']).read_bytes()
                           for row in verified['assets']}
        original_evidence = (evidence / 'windows-artifact-budget.json').read_bytes()
        original_receipt = (fixture.output / 'verified-release.json').read_bytes()
        original_notes = (fixture.output / 'release-notes.txt').read_bytes()
        staged = fixture.root / 'build' / 'verified-artifact'
        result = candidate.stage(fixture.output, staged, release_tests.SHA,
                                 release_tests.RUN_ID, release_tests.RUN_ATTEMPT,
                                 root=fixture.root)
        self.assertEqual(result['asset_count'], 15)
        self.assertEqual(result['exe_sha256'], verified['exe_sha256'])
        self.assertEqual(result['exe_size'], verified['exe_size'])
        receipt = json.loads((staged / 'verified-release.json').read_text())
        self.assertNotIn(str(fixture.root), json.dumps(receipt))
        for row in receipt['assets']:
            self.assertEqual(row['path'], row['name'])
            self.assertEqual((staged / row['name']).read_bytes(), original_assets[row['name']])
            self.assertEqual(candidate.digest(staged / row['name']), row['sha256'])
        self.assertEqual((staged / 'release-notes.txt').read_bytes(), original_notes)
        self.assertEqual((fixture.output / 'verified-release.json').read_bytes(), original_receipt)
        report = budget.check_budget(fixture.root,
                                     fetcher=lambda url: {'total_count': 0, 'artifacts': []},
                                     output_path='build/verified-artifact-budget.json')
        self.assertEqual((evidence / 'windows-artifact-budget.json').read_bytes(), original_evidence)
        raw_small_evidence = sum(path.stat().st_size for path in evidence.iterdir()
                                 if path.name.startswith('windows-') or path.name in (
                                     'hero-recognition-genuine.json', 'champion-select-genuine.json'))
        self.assertGreaterEqual(report['proposed_upper_estimate_bytes'],
                                result['staged_bytes'] + raw_small_evidence)


if __name__ == '__main__':
    unittest.main()

"""Final adoption bindings, independent of the coordinator's protocol tests."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from scripts import probe_opencv_postbuild as postbuild
from scripts import verify_release as gate

ROOT = Path(__file__).resolve().parents[1]
SHA = 'a' * 40


class PostbuildReleaseBindingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root/'source.zip'
        self.proof = {'source_commit': SHA, 'version': gate.CUSTOM_VERSION,
                      'native': {'size': 512, 'sha256': 'b'*64},
                      'wheel': {'size': 1024, 'sha256': 'c'*64}}
        self.build = {'opencv_custom_build': self.proof}
        self.build_file = self.root/'windows-opencv-build.json'
        self.build_file.write_text(json.dumps(self.proof), encoding='utf-8')
        for name in postbuild.EVIDENCE_NAMES:
            (self.root/name).write_text('{"unit_fixture": true}\n', encoding='utf-8')
        inventory = {name: postbuild.bytes_record((ROOT/name).read_bytes()) for name in postbuild.SOURCE_FILES}
        sources = {'commit': SHA, 'files': inventory}
        self.result = {'sources': sources, 'build_report_file': postbuild.file_record(self.build_file),
                       'custom': {'version': gate.CUSTOM_VERSION,
                                  'native': copy.deepcopy(self.proof['native']),
                                  'wheel': copy.deepcopy(self.proof['wheel'])}}
        self.bundle = {'status': 'completed', 'validation_errors': [], 'excluded_from_adoption': False,
                       'files': {'result': {'value': self.result},
                                 'prepared': {'value': {'sources': copy.deepcopy(sources)}}}}
        self.receipt = {'source_commit': SHA}
        self.write_archive()

    def write_archive(self, *, changed=None, comment=SHA):
        with zipfile.ZipFile(self.source, 'w') as archive:
            archive.comment = comment.encode('ascii')
            for name in postbuild.SOURCE_FILES:
                archive.writestr(name, (ROOT/name).read_bytes() + (b'changed' if name == changed else b''))

    def verify(self):
        # Only the separately tested pure protocol validator is replaced. This
        # test executes actual final source/file/native/wheel binding checks.
        with patch.object(postbuild, 'validate_export', return_value=(self.bundle, self.receipt)):
            return gate.verify_postbuild_adoption(self.root, self.build, self.source, SHA)

    def test_exact_source_build_and_export_bindings_pass(self):
        summary, names = self.verify()
        self.assertEqual(set(names), set(postbuild.EVIDENCE_NAMES))
        self.assertEqual(summary['fixed_order'], ['A1', 'B1'])
        self.assertEqual(summary['custom_native_sha256'], self.proof['native']['sha256'])
        self.assertEqual(summary['export_sha256'], gate.digest(self.root/'windows-opencv-postbuild-export.json'))

    def test_relative_reports_argument_resolves_to_exact_absolute_producer_records(self):
        import os
        before = Path.cwd()
        try:
            os.chdir(self.root.parent)
            with patch.object(postbuild, 'validate_export', return_value=(self.bundle, self.receipt)) as reader:
                summary, _ = gate.verify_postbuild_adoption(Path(self.root.name), self.build, self.source, SHA)
                self.assertEqual(summary['status'], 'passed')
                reader.assert_called_once_with(self.root.resolve())
        finally:
            os.chdir(before)

    def test_original_report_directory_is_checked_before_resolution(self):
        with patch.object(postbuild, 'check_directory', side_effect=RuntimeError('Linked/reparse directory')) as check:
            with patch.object(postbuild, 'validate_export') as reader:
                with self.assertRaisesRegex(gate.VerificationError, 'Linked/reparse'):
                    gate.verify_postbuild_adoption(self.root, self.build, self.source, SHA)
                check.assert_called_once_with(self.root)
                reader.assert_not_called()

    def test_nested_relocated_evidence_retains_original_proof_identity(self):
        import shutil
        moved = self.root/'downloaded'/'reports'; moved.mkdir(parents=True)
        for name in (*postbuild.EVIDENCE_NAMES, 'windows-opencv-build.json'):
            shutil.copyfile(self.root/name, moved/name)
        with patch.object(postbuild, 'validate_export', return_value=(self.bundle, self.receipt)) as reader:
            summary, _ = gate.verify_postbuild_adoption(moved.parent, self.build, self.source, SHA)
            self.assertEqual(summary['status'], 'passed')
            reader.assert_called_once_with(moved.resolve())
        self.assertNotEqual(self.result['build_report_file']['path'], str(moved/'windows-opencv-build.json'))

    def test_missing_or_failed_protocol_never_reaches_acceptance(self):
        for key, value in (('status', 'failed'), ('validation_errors', ['failed']),
                           ('excluded_from_adoption', True), ('excluded_from_adoption', 0)):
            original = self.bundle[key]; self.bundle[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(gate.VerificationError): self.verify()
            self.bundle[key] = original
        with patch.object(postbuild, 'validate_export', side_effect=RuntimeError('restoration missing')):
            with self.assertRaisesRegex(gate.VerificationError, 'restoration missing'):
                gate.verify_postbuild_adoption(self.root, self.build, self.source, SHA)

    def test_exact_commit_inventory_checkout_and_archive_bytes_are_required(self):
        name = postbuild.SOURCE_FILES[0]
        for mutation in ('commit', 'prepared', 'inventory', 'size_type', 'digest'):
            prior = copy.deepcopy(self.bundle)
            if mutation == 'commit': self.result['sources']['commit'] = 'd'*40
            if mutation == 'prepared': self.bundle['files']['prepared']['value']['sources']['commit'] = 'd'*40
            if mutation == 'inventory': self.result['sources']['files'].pop(name)
            if mutation == 'size_type': self.result['sources']['files'][name]['size'] = float(self.result['sources']['files'][name]['size'])
            if mutation == 'digest': self.result['sources']['files'][name]['sha256'] = 'd'*64
            with self.subTest(mutation=mutation), self.assertRaises(gate.VerificationError): self.verify()
            self.bundle = prior; self.result = self.bundle['files']['result']['value']
        for options in ({'changed': name}, {'comment': 'd'*40}):
            self.write_archive(**options)
            with self.subTest(options=options), self.assertRaises(gate.VerificationError): self.verify()
        self.write_archive()

    def test_measured_wheel_and_native_must_equal_packaged_build(self):
        for kind in ('wheel', 'native'):
            for field, value in (('size', 1), ('size', float(self.proof[kind]['size'])),
                                  ('size', True), ('sha256', 'd'*64)):
                original = self.result['custom'][kind][field]
                self.result['custom'][kind][field] = value
                with self.subTest(kind=kind, field=field, value=value), self.assertRaises(gate.VerificationError): self.verify()
                self.result['custom'][kind][field] = original
        self.build['opencv_custom_build'] = {**self.proof, 'version': 'wrong'}
        with self.assertRaisesRegex(gate.VerificationError, 'packaged build'): self.verify()

    def test_raw_build_proof_and_export_commit_cannot_be_substituted(self):
        self.build_file.write_text(json.dumps(self.proof)+' ', encoding='utf-8')
        with self.assertRaisesRegex(gate.VerificationError, 'raw hash'): self.verify()
        self.build_file.write_text(json.dumps(self.proof), encoding='utf-8')
        self.receipt['source_commit'] = 'e'*40
        with self.assertRaisesRegex(gate.VerificationError, 'export source'): self.verify()


class PostbuildWorkflowTests(unittest.TestCase):
    def test_one_pair_after_build_before_every_packaging_gate(self):
        value = (ROOT/'.github/workflows/build-native-preview.yml').read_text(encoding='utf-8')
        commands = ['scripts/probe_opencv_postbuild.py prepare', 'scripts/build_minimal_opencv.py',
                    'scripts/probe_opencv_postbuild.py run', 'scripts/probe_opencv_postbuild.py export',
                    'scripts/build_windows.py']
        offsets = [value.index(command) for command in commands]
        self.assertEqual(offsets, sorted(offsets))
        for command in commands: self.assertEqual(value.count(command), 1)
        self.assertIn('--no-deps --dest build/opencv-postbuild/official opencv-python-headless==5.0.0.93', value)
        self.assertNotIn('probe_opencv_parity.py generate', value)
        self.assertNotIn('probe_opencv_parity.py compare', value)
        self.assertNotIn('--regression-ratio', value)
        self.assertNotIn('--noise-floor-seconds', value)
        self.assertNotIn('continue-on-error', value)
        self.assertEqual(postbuild.BLOCKS, ('A1', 'B1'))
        summary = value.index('scripts/probe_opencv_postbuild.py summarize')
        self.assertLess(summary, value.index('scripts/check_artifact_budget.py --evidence-only'))
        self.assertIn('if: ${{ always() }}', value[value.rindex('- name:', 0, summary):summary])

    def test_every_bound_checkout_input_has_exact_lf_archive_bytes(self):
        import subprocess
        names = list(postbuild.SOURCE_FILES)
        output = subprocess.run(['git', 'check-attr', '-z', '--stdin', 'eol'], cwd=ROOT,
            input=('\0'.join(names)+'\0').encode(), check=True, stdout=subprocess.PIPE).stdout.decode().split('\0')
        rows = [output[i:i+3] for i in range(0, len(output)-1, 3)]
        # Binary fixtures have no line-ending conversion; each text input is LF.
        for name, attribute, value in rows:
            with self.subTest(name=name):
                self.assertEqual(attribute, 'eol')
                if not name.endswith('.png'): self.assertEqual(value, 'lf')


if __name__ == '__main__':
    unittest.main()

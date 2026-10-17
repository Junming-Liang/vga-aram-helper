"""Offline final visible-proof bindings; synthetic reports are not Windows proof."""
import copy
from contextlib import chdir
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from scripts import verify_release as gate
from tests.test_wgc_visible_overlay_smoke import fixture
from tests.test_wgc_session_build import manifest

SHA = 'a' * 40
MODULES = ('wgc_visible_overlay_smoke', 'native_ui', 'native_smoke', 'screen_capture',
           'persistent_capture_adapter', 'wgc_session_capture', 'owned_diagnostic_json',
           'portrait_display', 'local_debug', 'selection_session')


def visible_reports(source_entries, helper, inventory, checksum, exe_size, source_sha=SHA):
    """Complete raw synthetic reports reuse the production validator's fixture."""
    modules = {name: {'source_sha256': hashlib.sha256(source_entries[name + '.py']).hexdigest(),
                      'code_sha256': 'c' * 64} for name in MODULES}
    reports = {}
    for frozen, kind in ((False, 'source'), (True, 'frozen')):
        report = dict(status='passed', scope=gate.visible_capture_fixture.SCOPE,
            applicationVersion=gate.PREVIEW_VERSION, frozen=frozen,
            scales=list(gate.visible_capture_fixture.SCALES), source_commit=source_sha,
            helper_build=copy.deepcopy(helper),
            source_files={name: hashlib.sha256(source_entries[name]).hexdigest()
                          for name in gate.visible_capture_fixture.SOURCE_FILES}, runs=[])
        report['foreign_fixture'] = dict(source_sha256=report['source_files']['tests/SessionWindowFixture.cs'],
                                         executable_sha256='f' * 64)
        if frozen:
            report.update(executable_sha256=checksum, executable_size=exe_size,
                          archive_inventory=copy.deepcopy(inventory), product_modules=copy.deepcopy(modules))
        for scale in gate.visible_capture_fixture.SCALES:
            detail, kwargs = fixture()
            detail.update(applicationVersion=report['applicationVersion'],
                          frozen=frozen, requested_app_scale=scale, measured_qt_scale=scale,
                          executable_sha256=checksum if frozen else None,
                          helper=dict(manifest=copy.deepcopy(helper), sha256=helper['sha256'], size=helper['size']))
            foreign = kwargs['foreign_proof']
            if frozen:
                foreign.update(launcher_pid=2, launcher_created=2)
            report['runs'].append(dict(scale=scale, detail=detail, foreign=foreign,
                coordination='passed', exit_code=0, outer_cleanup_complete=True))
        reports[kind] = report
    return reports, modules


def write_visible_reports(folder, reports):
    for kind, report in reports.items():
        aggregate = copy.deepcopy(report)
        for run in aggregate['runs']:
            name = gate.visible_capture_fixture.scale_report_name(run['scale'], frozen=report['frozen'])
            raw = gate.visible_capture_fixture.report_payload(run.pop('detail')).encode('utf-8')
            (folder / name).write_bytes(raw)
            run.update(detail_report=name, report_size=len(raw), report_sha256=hashlib.sha256(raw).hexdigest())
        (folder / ('windows-wgc-visible-overlay-' + kind + '.json')).write_text(
            gate.visible_capture_fixture.report_payload(aggregate), encoding='utf-8')


class VisibleReleaseBindingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.evidence = self.root / 'reports'; self.evidence.mkdir()
        self.source = self.root / 'source.zip'
        self.executable = self.root / 'product.exe'; self.executable.write_bytes(b'MZ unit fixture')
        self.checksum = gate.digest(self.executable)
        self.source_entries = {name: ('Synthetic source: ' + name).encode() for name in
            (*gate.visible_capture_fixture.SOURCE_FILES, *gate.session_capture_fixture.SOURCE_FILES)}
        helper = manifest()
        helper.update(source_commit=SHA, source_files={name: {'size': len(self.source_entries[name]),
            'sha256': hashlib.sha256(self.source_entries[name]).hexdigest()}
            for name in gate.session_capture_fixture.SOURCE_FILES})
        helper['source_sha256'] = helper['source_files']['native/wgc_session_capture.cpp']['sha256']
        helper['build_recipe_sha256'] = helper['source_files']['scripts/build_wgc_session_capture.py']['sha256']
        self.build = dict(wgc_session_helper_build=helper,
                          archive_inventory=dict(wgc_session_helper=copy.deepcopy(helper), launch_script='launcher'))
        self.reports, self.modules = visible_reports(self.source_entries, helper, self.build['archive_inventory'],
                                                    self.checksum, self.executable.stat().st_size)
        self.write_source()
        self.write()
        wrapper = patch.object(gate, 'verify_frozen_visible_modules', return_value=self.modules)
        self.reader = wrapper.start(); self.addCleanup(wrapper.stop)

    def write_source(self, *, comment=SHA):
        with zipfile.ZipFile(self.source, 'w') as archive:
            archive.comment = comment.encode('ascii')
            for name, raw in self.source_entries.items(): archive.writestr(name, raw)

    def write(self):
        write_visible_reports(self.evidence, self.reports)

    def verify(self, evidence=None):
        folder = self.evidence if evidence is None else evidence
        names = [name for name in gate.EVIDENCE_NAMES if name.startswith('windows-wgc-visible-overlay-')]
        files = {name: gate.evidence_file(folder, name) for name in names}
        return gate.verify_visible_capture_bundle(files, self.source, gate.PREVIEW_VERSION, SHA,
            self.build, self.executable, self.checksum, self.executable.stat().st_size)

    def change_aggregate(self, kind, change):
        path = self.evidence / ('windows-wgc-visible-overlay-' + kind + '.json')
        value = gate.read_json(path); change(value)
        path.write_text(json.dumps(value), encoding='utf-8')

    def test_both_modes_all_scales_raw_bytes_and_final_exe_are_bound(self):
        summary = self.verify()
        self.assertEqual([row['frozen'] for row in summary], [False, True])
        self.reader.assert_called_once_with(self.executable)
        for row in summary:
            self.assertEqual([run['scale'] for run in row['runs']], [1, 1.5, 2])
            for run in row['runs']:
                self.assertEqual(run['sha256'], gate.digest(self.evidence / run['report']))
                self.assertEqual(run['size'], (self.evidence / run['report']).stat().st_size)

    def test_relative_evidence_directory_and_nested_relocation(self):
        with chdir(self.root): self.assertEqual(len(self.verify(Path('reports'))), 2)
        nested = self.root / 'downloaded' / 'reports'; nested.mkdir(parents=True)
        for path in self.evidence.iterdir(): shutil.copyfile(path, nested / path.name)
        with chdir(self.root): self.assertEqual(len(self.verify(Path('downloaded'))), 2)

    def test_each_aggregate_and_raw_file_is_mandatory(self):
        names = [name for name in gate.EVIDENCE_NAMES if name.startswith('windows-wgc-visible-overlay-')]
        self.assertEqual(len(names), 8)
        for name in names:
            self.write(); (self.evidence / name).unlink()
            with self.subTest(name=name), self.assertRaises(gate.VerificationError): self.verify()

    def test_raw_byte_hash_size_and_fixed_path_are_not_receipt_only(self):
        mutations = (
            lambda run: run.update(report_sha256='0' * 64),
            lambda run: run.update(report_size=run['report_size'] + 1),
            lambda run: run.update(report_size=float(run['report_size'])),
            lambda run: run.update(detail_report='../outside.json'),
            lambda run: run.update(detail_report='/tmp/forged.json'),
            lambda run: run.pop('detail_report'),
        )
        for kind in ('source', 'frozen'):
            for mutation in mutations:
                self.write(); self.change_aggregate(kind, lambda report: mutation(report['runs'][0]))
                with self.subTest(kind=kind, mutation=mutation), self.assertRaises(gate.VerificationError): self.verify()
            self.write()
            path = self.evidence / gate.visible_capture_fixture.scale_report_name(1, frozen=kind == 'frozen')
            path.write_bytes(path.read_bytes() + b' ')
            with self.subTest(kind=kind, mutation='raw bytes'), self.assertRaises(gate.VerificationError): self.verify()

    def test_aggregate_modes_scales_source_helper_and_outer_cleanup_are_exact(self):
        mutations = (
            lambda report: report.update(status='failed'),
            lambda report: report.update(frozen=not report['frozen']),
            lambda report: report.update(source_commit='d' * 40),
            lambda report: report.update(scales=[1.0, 1.5, 2]),
            lambda report: report['runs'].reverse(),
            lambda report: report['runs'].pop(),
            lambda report: report['runs'][0].update(scale=True),
            lambda report: report['runs'][0].update(coordination='failed'),
            lambda report: report['runs'][0].update(exit_code=False),
            lambda report: report['runs'][0].update(outer_cleanup_complete=1),
            lambda report: report['runs'][0].pop('foreign'),
            lambda report: report['helper_build'].update(size=float(report['helper_build']['size'])),
            lambda report: report['foreign_fixture'].update(source_sha256='e' * 64),
            lambda report: report['foreign_fixture'].update(executable_sha256='e' * 64),
        )
        for kind in ('source', 'frozen'):
            for mutation in mutations:
                self.write(); self.change_aggregate(kind, mutation)
                with self.subTest(kind=kind, mutation=mutation), self.assertRaises(gate.VerificationError): self.verify()

    def test_source_inventory_and_downloadable_archive_are_exact(self):
        for kind in ('source', 'frozen'):
            for mutation in (lambda report: report['source_files'].pop('native_ui.py'),
                             lambda report: report['source_files'].update(native_ui='a' * 64),
                             lambda report: report['source_files'].update({'native_ui.py': '0' * 64})):
                self.write(); self.change_aggregate(kind, mutation)
                with self.subTest(kind=kind, mutation=mutation), self.assertRaises(gate.VerificationError): self.verify()
        self.write(); self.write_source(comment='b' * 40)
        with self.assertRaises(gate.VerificationError): self.verify()
        self.source_entries['native_ui.py'] += b'changed'; self.write_source()
        with self.assertRaises(gate.VerificationError): self.verify()

    def test_frozen_exe_inventory_and_embedded_modules_cannot_be_substituted(self):
        mutations = (
            lambda report: report.update(executable_sha256='0' * 64),
            lambda report: report.update(executable_size=report['executable_size'] + 1),
            lambda report: report.update(executable_size=float(report['executable_size'])),
            lambda report: report['archive_inventory'].update(launch_script='other'),
            lambda report: report['product_modules'].pop('native_ui'),
            lambda report: report['product_modules']['native_ui'].update(code_sha256='0' * 64),
            lambda report: report['product_modules']['native_ui'].update(source_sha256='0' * 64),
        )
        for mutation in mutations:
            self.write(); self.change_aggregate('frozen', mutation)
            with self.subTest(mutation=mutation), self.assertRaises(gate.VerificationError): self.verify()
        self.write(); self.change_aggregate('source', lambda report: report.update(executable_sha256=self.checksum))
        with self.assertRaises(gate.VerificationError): self.verify()
        self.write(); self.reader.side_effect = RuntimeError('Actual frozen module differs')
        with self.assertRaisesRegex(gate.VerificationError, 'Actual frozen module differs'): self.verify()

    def test_forged_passed_raw_report_still_runs_complete_trusted_validator(self):
        original = copy.deepcopy(self.reports)
        for kind in ('source', 'frozen'):
            for change in (
                lambda detail: detail.update(frozen=not detail['frozen']),
                lambda detail: detail.update(executable_sha256='0' * 64),
                lambda detail: detail.update(constructor='forged'),
                lambda detail: detail.update(pixel_exclusion_passed=False),
                lambda detail: detail['negative_results'].pop('stop'),
                lambda detail: detail['helper'].update(size=float(detail['helper']['size'])),
            ):
                self.reports = copy.deepcopy(original)
                change(self.reports[kind]['runs'][0]['detail']); self.write()
                with self.subTest(kind=kind, change=change), self.assertRaises(gate.VerificationError): self.verify()

    def test_inline_equality_is_type_strict_and_never_replaces_missing_raw(self):
        for changed in (False, True):
            self.write()
            detail = copy.deepcopy(self.reports['source']['runs'][0]['detail'])
            if changed: detail['helper']['size'] = float(detail['helper']['size'])
            self.change_aggregate('source', lambda report: report['runs'][0].update(detail=detail))
            if changed:
                with self.assertRaisesRegex(gate.VerificationError, 'inline/raw'): self.verify()
            else: self.verify()
        self.write()
        self.change_aggregate('source', lambda report: report['runs'][0].update(
            detail=self.reports['source']['runs'][0]['detail']))
        (self.evidence / gate.visible_capture_fixture.scale_report_name(1, frozen=False)).unlink()
        with self.assertRaises(gate.VerificationError): self.verify()

    def test_raw_symlinks_fail_closed(self):
        raw_name = gate.visible_capture_fixture.scale_report_name(1, frozen=False)
        path = self.evidence / raw_name
        moved = self.root / 'saved.json'; path.rename(moved)
        try: path.symlink_to(moved)
        except NotImplementedError: self.skipTest('Symlink creation unavailable')
        except OSError as error:
            if os.name == 'nt' and getattr(error, 'winerror', None) in (1, 50, 1314):
                self.skipTest('Symlink creation is not available for this Windows account')
            raise
        with self.assertRaises(gate.VerificationError): self.verify()

    def test_split_evidence_layout_fails_closed(self):
        raw_name = gate.visible_capture_fixture.scale_report_name(1, frozen=False)
        path = self.evidence / raw_name
        nested = self.evidence / 'reports'; nested.mkdir(); path.rename(nested / raw_name)
        with self.assertRaisesRegex(gate.VerificationError, 'outside its aggregate directory'): self.verify()

    def test_linked_ancestor_is_rejected_before_relative_or_nested_resolution(self):
        linked = self.root / 'linked'
        try: linked.symlink_to(self.root, target_is_directory=True)
        except NotImplementedError: self.skipTest('Symlink creation unavailable')
        except OSError as error:
            if os.name == 'nt' and getattr(error, 'winerror', None) in (1, 50, 1314):
                self.skipTest('Symlink creation is not available for this Windows account')
            raise
        for folder in (linked, linked / 'reports'):
            with self.subTest(folder=folder), self.assertRaisesRegex(gate.VerificationError, 'Linked/reparse'):
                self.verify(folder)
        with chdir(self.root):
            with self.assertRaisesRegex(gate.VerificationError, 'Linked/reparse'): self.verify(Path('linked/reports'))


if __name__ == '__main__': unittest.main()

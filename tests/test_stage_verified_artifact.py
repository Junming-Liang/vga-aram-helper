"""Synthetic byte-copy/inventory tests, never Windows acceptance evidence."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from scripts import stage_verified_artifact as candidate


class StageVerifiedArtifactTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.verified = self.root/'build/verified-preview'
        self.output = self.root/'build/verified-artifact'; self.verified.mkdir(parents=True)
        self.sha = 'a'*40; self.rows = []
        for name in sorted(candidate.expected_names(candidate.__version__)):
            parent = self.verified if name.startswith('windows-test-evidence-') else self.root/'reports' if name=='windows-native-overlay.png' else self.root/'dist/release'
            parent.mkdir(parents=True,exist_ok=True); path=parent/name; path.write_bytes(('owned-synthetic-'+name).encode())
            self.rows.append({'name':name,'path':str(path),'size':path.stat().st_size,'sha256':candidate.digest(path)})
        exe=next(r for r in self.rows if r['name'].endswith('.exe'))
        self.value={'repository':candidate.REPOSITORY,'version':candidate.__version__,'tag':'v'+candidate.__version__,
            'source_sha':self.sha,'run_id':123,'run_attempt':2,'exe_sha256':exe['sha256'],'exe_size':exe['size'],'assets':self.rows}
        self.save(); (self.verified/'release-notes.txt').write_text('Owned synthetic staging fixture; no Windows claim.')

    def save(self): (self.verified/'verified-release.json').write_text(json.dumps(self.value))
    def stage(self): return candidate.stage(self.verified,self.output,self.sha,123,2,root=self.root)

    def test_all_exact_assets_and_portable_provenance_retained(self):
        result=self.stage(); self.assertEqual(result['asset_count'],15)
        receipt=json.loads((self.output/'verified-release.json').read_text())
        self.assertNotIn(str(self.root),json.dumps(receipt))
        self.assertEqual(set(p.name for p in self.output.iterdir()),candidate.expected_names(candidate.__version__)|{'verified-release.json','release-notes.txt'})
        for row in receipt['assets']:
            self.assertEqual(row['path'],row['name']); self.assertEqual(candidate.digest(self.output/row['name']),row['sha256'])
        self.assertEqual(result['exe_sha256'],self.value['exe_sha256'])

    def restage_via_root_alias(self, alias, *, canonical_assets=False):
        original_root = self.root
        self.root = alias
        self.verified = alias / self.verified.relative_to(original_root)
        self.output = alias / self.output.relative_to(original_root)
        for row in self.rows:
            path = alias / Path(row['path']).relative_to(original_root)
            row['path'] = str(path.resolve() if canonical_assets else path)
        self.save()
        result = self.stage()
        self.assertEqual(result['asset_count'], 15)
        self.assertEqual(result['exe_sha256'], self.value['exe_sha256'])

    @unittest.skipIf(os.name == 'nt', 'Windows short-name alias has its own native test')
    def test_trusted_root_ancestor_alias_is_not_mistaken_for_an_outside_file(self):
        # A trusted root's ancestor alias models the different root spelling
        # caused by Windows short-name expansion. Links BELOW root stay forbidden.
        with tempfile.TemporaryDirectory() as parent:
            alias = Path(parent) / 'ancestor-alias'
            alias.symlink_to(self.root.parent, target_is_directory=True)
            aliased_root = alias / self.root.name
            self.assertNotEqual(aliased_root.absolute(), aliased_root.resolve())
            self.restage_via_root_alias(aliased_root, canonical_assets=True)

    @unittest.skipUnless(os.name == 'nt', 'Requires real Windows short-path semantics')
    def test_windows_short_root_spelling_retains_exact_assets(self):
        import ctypes
        get_short_path = ctypes.WinDLL('kernel32', use_last_error=True).GetShortPathNameW
        get_short_path.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32]
        get_short_path.restype = ctypes.c_uint32
        buffer = ctypes.create_unicode_buffer(32768)
        length = get_short_path(str(self.root), buffer, len(buffer))
        if not length or length >= len(buffer):
            self.skipTest('Host does not expose a short path for the owned temporary root')
        alias = Path(buffer.value)
        if alias == alias.resolve():
            self.skipTest('Host has no distinct short-name ancestor for this fixture')
        self.restage_via_root_alias(alias, canonical_assets=True)

    def test_wrong_source_version_run_or_repository_is_rejected(self):
        for key,bad in [('source_sha','b'*40),('version','0.0.0'),('tag','v0.0.0'),('run_id',124),('run_attempt',1),('repository','other/repo')]:
            with self.subTest(key=key):
                old=self.value[key];self.value[key]=bad;self.save()
                with self.assertRaisesRegex(RuntimeError, 'Verified candidate identity mismatch'):self.stage()
                self.assertFalse(self.output.exists());self.value[key]=old

    def test_incomplete_duplicate_and_extra_asset_inventories_fail(self):
        for rows in [self.rows[:-1],self.rows+[self.rows[0]],self.rows[:-1]+[self.rows[0]],self.rows+[{'name':'private.zip'}]]:
            self.value['assets']=rows;self.save()
            with self.assertRaisesRegex(RuntimeError, 'Verified candidate asset inventory mismatch'):self.stage()
        self.assertFalse(self.output.exists())

    def test_changed_bytes_wrong_size_and_wrong_executable_proof_fail(self):
        path=Path(self.rows[0]['path']); original=path.read_bytes();path.write_bytes(b'tampered')
        with self.assertRaisesRegex(RuntimeError, 'Verified asset path, size or hash changed'):self.stage()
        path.write_bytes(original);self.rows[0]['size']+=1;self.save()
        with self.assertRaisesRegex(RuntimeError, 'Verified asset path, size or hash changed'):self.stage()
        self.rows[0]['size']-=1;self.value['exe_sha256']='0'*64;self.save()
        with self.assertRaisesRegex(RuntimeError, 'Executable is not the exact tested asset'):self.stage()
        self.assertFalse(self.output.exists())

    def test_outside_and_wrong_internal_asset_paths_rejected(self):
        original_bytes = Path(self.rows[0]['path']).read_bytes()
        for path, reason in ((self.root.parent/'private', 'Candidate source lies outside checkout'),
                             (self.root/'private', 'Verified asset path, size or hash changed')):
            if path.parent == self.root: path.write_bytes(original_bytes)
            self.rows[0]['path']=str(path);self.save()
            with self.assertRaisesRegex(RuntimeError, reason):self.stage()
        self.assertFalse(self.output.exists())

    def test_symlink_source_or_output_rejected(self):
        path=Path(self.rows[0]['path']); real=path.with_name('owned-real');path.rename(real)
        try:path.symlink_to(real)
        except (OSError,NotImplementedError):self.skipTest('Host does not permit owned symlink fixtures')
        with self.assertRaisesRegex(RuntimeError, 'Candidate symlink rejected'):self.stage()
        path.unlink();real.rename(path);self.output.symlink_to(self.root,target_is_directory=True)
        with self.assertRaisesRegex(RuntimeError, 'Candidate output symlink rejected'):self.stage()

    def test_output_outside_checkout_is_rejected_before_any_copy(self):
        self.output = self.root.parent / (self.root.name + '-outside')
        with self.assertRaisesRegex(RuntimeError, 'Candidate output lies outside checkout'):
            self.stage()
        self.assertFalse(self.output.exists())

    def test_parent_traversal_is_rejected_before_resolution(self):
        self.rows[0]['path'] = str(self.root / 'dist' / '..' / 'dist' / 'release' / self.rows[0]['name'])
        self.save()
        with self.assertRaisesRegex(RuntimeError, 'Invalid candidate path'):
            self.stage()
        self.assertFalse(self.output.exists())

    def test_descendant_directory_alias_is_rejected_even_when_target_is_owned(self):
        alias = self.root / 'directory-alias'
        try:
            alias.symlink_to(self.verified, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest('Host does not permit owned directory symlink fixtures')
        with self.assertRaisesRegex(RuntimeError, 'Candidate symlink rejected'):
            candidate.stage(alias, self.output, self.sha, 123, 2, root=self.root)
        self.assertFalse(self.output.exists())

    def test_existing_output_is_never_clobbered(self):
        self.output.mkdir();sentinel=self.output/'keep';sentinel.write_text('preserve')
        with self.assertRaisesRegex(RuntimeError, 'Candidate output already exists'):self.stage()
        self.assertEqual(sentinel.read_text(),'preserve')

    def test_oversized_metadata_rejected_before_copy(self):
        (self.verified/'release-notes.txt').write_text('x'*candidate.MAX_METADATA_BYTES)
        with self.assertRaisesRegex(RuntimeError, 'Candidate metadata exceeds reserved budget'):self.stage()
        self.assertFalse(self.output.exists())

    def test_serialized_unicode_metadata_respects_actual_byte_budget(self):
        self.value['scope'] = '字'*200000
        (self.verified/'verified-release.json').write_text(json.dumps(self.value,ensure_ascii=False),encoding='utf8')
        self.assertLess((self.verified/'verified-release.json').stat().st_size,candidate.MAX_METADATA_BYTES)
        with self.assertRaisesRegex(RuntimeError, 'Serialized candidate metadata exceeds reserved budget'):self.stage()
        self.assertFalse(self.output.exists())

    def test_corrupt_copy_fails_and_never_returns_a_success_receipt(self):
        def corrupt(src,dst):Path(dst).write_bytes(b'bad')
        with patch.object(candidate.shutil,'copyfile',side_effect=corrupt):
            with self.assertRaisesRegex(RuntimeError, 'Staged copy differs from tested asset'):self.stage()
        self.assertFalse((self.output/'verified-release.json').exists())


if __name__=='__main__':unittest.main()

"""Original Microsoft runtime identity checks, without executing DLLs."""
import hashlib
import unittest
from unittest.mock import patch
from scripts import microsoft_runtime as runtime


class MicrosoftRuntimeTests(unittest.TestCase):
    def test_exact_release_runtime_names_and_version(self):
        self.assertEqual(runtime.RUNTIME_DLLS, {'msvcp140.dll', 'msvcp140_1.dll', 'msvcp140_2.dll',
                                             'vcruntime140.dll', 'vcruntime140_1.dll'})
        self.assertEqual({row['version_resource']['FileVersion'] for row in runtime.PROVENANCE['files']},
                         {'14.44.35211.0'})
        self.assertTrue(all(row['version_resource']['CompanyName'] == 'Microsoft Corporation'
                            for row in runtime.PROVENANCE['files']))
        self.assertEqual(runtime.PROVENANCE['wheel']['sha256'],
                         'c8a29def77032773a30879f7f24415b5395ad08592d147c170824ef4c735dfc1')

    def test_original_extracted_bytes_pass_but_changed_or_missing_fail(self):
        proof = runtime_fixture()
        data = b'X' * 2048
        names = ['pyside6/' + name for name in sorted(runtime.RUNTIME_DLLS)] + ['msvcp140.dll', 'vcruntime140.dll', 'vcruntime140_1.dll']
        class Archive:
            toc = names
            def extract(self, _name):
                return data
        archive = Archive()
        bundle = runtime.verify_embedded_runtime(archive, proof)
        self.assertEqual(runtime.verify_runtime_evidence(bundle, {name for name in names if name.startswith('pyside6/')}), proof)
        with patch.object(archive, 'extract', return_value=data[:-1]):
            with self.assertRaisesRegex(RuntimeError, 'differ from licensed source'):
                runtime.verify_embedded_runtime(archive, proof)
        archive.toc = []
        with self.assertRaisesRegex(RuntimeError, 'archive paths are missing'):
            runtime.verify_embedded_runtime(archive, proof)

    def test_failed_contradictory_or_unsigned_installation_evidence_fails(self):
        import copy
        original = runtime_fixture()
        cases = []
        for key, value in [('status', 'failed'), ('error', None), ('verified', False)]:
            proof = copy.deepcopy(original); proof[key] = value; cases.append(proof)
        for key, value in [('exit_code', 3010), ('exit_code', True), ('community_license_accepted', False)]:
            proof = copy.deepcopy(original); proof['installer'][key] = value; cases.append(proof)
        proof = copy.deepcopy(original); proof['product']['is_reboot_required'] = True; cases.append(proof)
        proof = copy.deepcopy(original); proof['tool']['signature_status'] = 'NotSigned'; cases.append(proof)
        for proof in cases:
            with self.subTest(proof=proof), self.assertRaises(RuntimeError): runtime.verify_provenance(proof)

    def test_workflows_require_licensed_setup_and_explicit_acceptance(self):
        for name in ('windows-build.yml', 'build-native-preview.yml'):
            workflow = (runtime.ROOT / '.github' / 'workflows' / name).read_text()
            self.assertIn('./scripts/install-community-runtime.ps1 -AcceptCommunityLicense', workflow)
            self.assertLess(workflow.index('install-community-runtime.ps1'), workflow.index('python scripts/build_windows.py'))
        script = (runtime.ROOT / 'scripts' / 'install-community-runtime.ps1').read_text()
        for text in ('[switch] $AcceptCommunityLicense', "'github-hosted'", "'dumpbin /dependents'", "'Microsoft.VisualStudio.Product.Community'", "'Valid'", "'14.44.35211.0'"):
            self.assertIn(text, script)

    def test_unknown_debug_crt_anywhere_and_ci_only_dependency_fail(self):
        for name in ('msvcp140d.dll', 'vcruntime140d.dll', 'concrt140.dll', 'other/msvcp140_3.dll'):
            with self.subTest(name=name), self.assertRaises(RuntimeError):
                runtime.reject_unreviewed_runtime_names([name])
        proof = runtime_fixture()
        proof['files'][0]['dependencies'] = ['unbundled.dll']
        with self.assertRaisesRegex(RuntimeError, 'unreviewed or unbundled'):
            runtime.verify_provenance(proof)

    def test_wrong_product_unsigned_old_debug_and_outside_source_fail(self):
        import copy
        proof = runtime_fixture()
        cases = []
        for key, value in [('id', 'Microsoft.VisualStudio.Product.BuildTools'), ('is_complete', False)]:
            changed = copy.deepcopy(proof); changed['product'][key] = value; cases.append(changed)
        for key, value in [('signature_status', 'UnknownError'), ('file_version', '14.43.00000.0'),
                           ('source_path', r'C:\other\msvcp140.dll'), ('machine', 'x86')]:
            changed = copy.deepcopy(proof); changed['files'][0][key] = value; cases.append(changed)
        changed = copy.deepcopy(proof)
        changed['files'][0]['source_path'] = changed['files'][0]['source_path'].replace('x64', 'debug_nonredist/x64')
        cases.append(changed)
        for changed in cases:
            with self.subTest(changed=changed), self.assertRaises(RuntimeError):
                runtime.verify_provenance(changed)


def runtime_fixture():
    base = r'C:\VGA-VS-Community-2022'
    signer = 'CN=Microsoft Corporation, O=Microsoft Corporation, L=Redmond, S=Washington, C=US'
    return {'schema_version': 1, 'status': 'passed', 'verified': True, 'source': 'Microsoft Visual Studio Community 2022',
            'license_url': runtime.LICENSE_URL,
            'product': {'id': runtime.PRODUCT_ID, 'installation_path': base, 'installation_version': '17.14.1.0',
                        'is_complete': True, 'is_launchable': True, 'is_reboot_required': False},
            'installer': {'url': 'https://aka.ms/vs/17/release/vs_community.exe', 'sha256': 'a' * 64,
                          'signature_status': 'Valid', 'signer_subject': signer, 'community_license_accepted': True, 'exit_code': 0,
                          'requested_components': ['Microsoft.VisualStudio.Component.VC.Tools.x86.x64', 'Microsoft.VisualStudio.Component.VC.Redist.14.Latest']},
            'tool': {'path': base + r'\VC\Tools\MSVC\14.44.35207\bin\Hostx64\x64\dumpbin.exe',
                     'sha256': 'b' * 64, 'used': 'dumpbin /headers', 'dependency_check': 'dumpbin /dependents', 'signature_status': 'Valid', 'signer_subject': signer},
            'files': [{'filename': name, 'size': 2048, 'sha256': hashlib.sha256(b'X' * 2048).hexdigest(),
                       'file_version': '14.44.35211.0', 'source_path': base + '/VC/Redist/MSVC/14.44.35211/x64/Microsoft.VC143.CRT/' + name,
                       'signature_status': 'Valid', 'signer_subject': signer, 'machine': 'x64', 'dependencies': ['kernel32.dll', 'api-ms-win-crt-runtime-l1-1-0.dll']}
                      for name in sorted(runtime.RUNTIME_DLLS)]}


if __name__ == '__main__':
    unittest.main()

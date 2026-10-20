"""Fixed-destination, read-only ephemeral Actions authentication."""
import io
import os
from pathlib import Path
import unittest
from unittest.mock import patch, Mock
from urllib.error import HTTPError, URLError
from scripts import check_artifact_budget as budget

URL=f'https://api.github.com/repos/{budget.REPOSITORY}/actions/artifacts?per_page=100&page=1'

class InventoryAuthenticationTests(unittest.TestCase):
    def fetch(self, env):
        response=io.BytesIO(b'{"total_count":0,"artifacts":[]}')
        opener=Mock();opener.open.return_value=response
        with patch.dict(os.environ,env,clear=True), patch.object(budget,'build_opener',return_value=opener) as build:
            self.assertEqual(budget.fetch_json(URL),{'total_count':0,'artifacts':[]})
        self.assertIsInstance(build.call_args.args[0],budget.NoRedirect)
        request=opener.open.call_args.args[0]
        self.assertEqual(request.full_url,URL);self.assertEqual(request.get_method(),'GET')
        self.assertEqual(opener.open.call_args.kwargs,{'timeout':20})
        return request
    def test_ephemeral_token_only_on_fixed_get(self):
        self.assertEqual(self.fetch({'VGA_ARTIFACT_READ_TOKEN':'synthetic-token'}).get_header('Authorization'),'Bearer synthetic-token')
    def test_does_not_read_general_credentials(self):
        self.assertIsNone(self.fetch({'GH_TOKEN':'private','GITHUB_TOKEN':'private'}).get_header('Authorization'))
    def test_invalid_endpoints_rejected_before_network(self):
        for url in (URL.replace('https:','http:'),URL.replace('api.github.com','evil.test'),URL.replace(budget.REPOSITORY,'other/repo'),URL+'&extra=1',URL.replace('page=1','page=11'),URL+'#fragment',URL.replace('/actions/artifacts','/releases')):
            with self.subTest(url=url),patch.object(budget,'build_opener') as build:
                with self.assertRaisesRegex(RuntimeError,'Unexpected'):budget.fetch_json(url)
                build.assert_not_called()
    def test_redirects_never_forward_authorization(self):
        from urllib.request import Request
        request=Request(URL,headers={'Authorization':'Bearer synthetic-token'})
        for code in (301,302,303,307,308):
            for destination in ('https://evil.test/',URL):
                with self.assertRaisesRegex(RuntimeError,'redirect refused'):
                    budget.NoRedirect().redirect_request(request,None,code,'',{},destination)
    def test_error_output_is_fixed_without_response_or_token(self):
        for error in (HTTPError(URL,403,'synthetic-secret',{},None),URLError('synthetic-secret')):
            opener=Mock();opener.open.side_effect=error
            with patch.dict(os.environ,{'VGA_ARTIFACT_READ_TOKEN':'synthetic-secret'},clear=True),patch.object(budget,'build_opener',return_value=opener):
                with self.assertRaises(RuntimeError) as raised:budget.fetch_json(URL)
                self.assertNotIn('synthetic-secret',str(raised.exception))
                self.assertTrue(raised.exception.__suppress_context__)
    def test_invalid_token_is_not_sent(self):
        for token in ('a\nb','a b','x'*4097):
            with patch.dict(os.environ,{'VGA_ARTIFACT_READ_TOKEN':token},clear=True),patch.object(budget,'build_opener') as build:
                with self.assertRaisesRegex(RuntimeError,'Invalid'):budget.fetch_json(URL)
                build.assert_not_called()
    def test_workflow_token_is_scoped_to_two_budget_steps(self):
        text=(Path(__file__).resolve().parents[1]/'.github/workflows/build-native-preview.yml').read_text()
        blocks=text.split('      - name:')[1:]
        authenticated=[block for block in blocks if 'VGA_ARTIFACT_READ_TOKEN:' in block]
        self.assertEqual(len(authenticated),2)
        for block in authenticated:
            self.assertIn('run: python scripts/check_artifact_budget.py',block)
            self.assertIn('VGA_ARTIFACT_READ_TOKEN: ${{ github.token }}',block)
            self.assertNotIn('uses:',block)
        self.assertEqual(text.count('actions: read'),1)
        self.assertEqual(text.count('GH_TOKEN:'),2)
        before_release_steps=text.split('- name: Create verified private draft without publishing',1)[0]
        self.assertNotIn('GH_TOKEN:',before_release_steps)

if __name__=='__main__':unittest.main()

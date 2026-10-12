"""Offline fixtures deliberately synthetic; never shipped as production data."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from urllib.error import HTTPError

from data_updates import (WIKI_FILES, WIKI_PAGE, _bounded_tree, discover_sources,
                          refresh_official_data, validate_wiki)
from update_network import HUYA_HOSTS, SafeRedirects, UpdateError, json_bytes, strict_json, validate_url

BUNDLE = 'https://huyafedltc.msstatic.com/gametool/league-of-legends/wiki/assets/index-NEW123.js'
ROOT = 'https://fileserver.cdn.huya.com/game_tools/1-test123-500/500/'


def fixture():
    rec = {'augmentId': '2', 'augmentName': '测试强化', 'tier': 'T1', 'winRate': '55.25%',
           'pickRate': '10%', 'numGames': 100}
    hero = {'championId': '1', 'championName': '测试英雄', 'version': '16.17',
            'winRate': '52%', 'pickRate': '', 'augmentRecommendations': [rec]}
    augment = {'augmentId': '2', 'augmentName': '测试强化', 'winRate': '55.25%', 'pickRate': ''}
    return {'champion-list': [copy.deepcopy(hero)], 'champion-detail': [copy.deepcopy(hero)],
            'augment-list': [copy.deepcopy(augment)], 'augment-detail': [copy.deepcopy(augment)],
            'item-detail': {'测试装备': {'name': '测试装备', 'itemId': '3'}}}


class DataUpdateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cache = Path(self.tmp.name)
        self.data = fixture()
        self.requested = []

    def tearDown(self):
        self.tmp.cleanup()

    def fetch(self, url, *, max_bytes):
        self.requested.append(url)
        if url == WIKI_PAGE:
            return ('<script src="' + BUNDLE + '"></script>').encode()
        if url == BUNDLE:
            return b'var cfg={VITE_TOOL_ID:"test123"};throw new Error("never executed");'
        return json_bytes(self.data[url.rsplit('/', 1)[1].removesuffix('.json')])

    def version(self, tool_id, **kwargs):
        self.assertIn(tool_id, ('test123', 'p81hl812'))
        return {'version': '500', 'dataBaseUrl': ROOT.rsplit('/500/', 1)[0] + '/'}

    def refresh(self, **kwargs):
        return refresh_official_data(self.cache, fetcher=kwargs.get('fetcher', self.fetch),
                                     version_fetcher=kwargs.get('version_fetcher', self.version))

    def test_fresh_data_and_hash_provenance(self):
        result = self.refresh()
        self.assertEqual(result['status']['state'], 'fresh')
        self.assertEqual(result['data']['wiki']['version'], '500')
        self.assertEqual(result['data']['metadata']['gamePatch'], '16.17')
        self.assertEqual(len(result['status']['artifacts']), 5)
        self.assertEqual(result['status']['sha256'], hashlib.sha256(json_bytes(result['data'])).hexdigest())
        self.assertIsNone(result['status']['sourceUpdatedAt'])
        self.assertTrue((self.cache / 'current.json').is_file())
        self.assertEqual(len(self.requested), 7)

    def test_first_launch_offline_has_no_data_or_demo(self):
        def offline(*args, **kwargs):
            raise OSError('offline')
        result = self.refresh(fetcher=offline)
        self.assertIsNone(result['data'])
        self.assertEqual(result['status']['state'], 'unavailable')
        self.assertFalse((self.cache / 'current.json').exists())

    def test_invalid_download_retains_last_good_cache(self):
        old = self.refresh()
        original = (self.cache / 'current.json').read_bytes()
        self.data['champion-detail'][0]['augmentRecommendations'][0]['winRate'] = '999%'
        result = self.refresh()
        self.assertEqual(result['status']['state'], 'cached')
        self.assertEqual(result['data'], old['data'])
        self.assertEqual((self.cache / 'current.json').read_bytes(), original)

    def test_corrupt_current_falls_back_to_verified_previous(self):
        self.refresh()
        self.refresh()
        (self.cache / 'current.json').write_text('{}')
        def offline(*args, **kwargs):
            raise TimeoutError()
        result = self.refresh(fetcher=offline)
        self.assertEqual(result['status']['state'], 'cached')
        self.assertTrue(result['status']['usingCached'])

    def test_cache_hash_tampering_is_not_used(self):
        self.refresh()
        path = self.cache / 'current.json'
        envelope = json.loads(path.read_text())
        envelope['data']['wiki']['version'] = 'evil'
        path.write_text(json.dumps(envelope))
        def offline(*args, **kwargs):
            raise OSError()
        self.assertIsNone(self.refresh(fetcher=offline)['data'])

    def test_mismatched_file_sets_fail_transaction(self):
        self.data['augment-detail'][0]['augmentId'] = 'other'
        self.assertEqual(self.refresh()['status']['state'], 'unavailable')

    def test_invalid_version_root_rejected_before_data_fetch(self):
        for root in ['http://fileserver.cdn.huya.com/game_tools/x/', 'https://evil.test/game_tools/x/',
                     'https://fileserver.cdn.huya.com/game_tools/../private/',
                     'https://fileserver.cdn.huya.com/game_tools/%2e%2e/private/']:
            with self.subTest(root=root):
                self.requested.clear()
                result = self.refresh(version_fetcher=lambda *a, **k: {'version': '500', 'dataBaseUrl': root})
                self.assertIsNone(result['data'])
                self.assertEqual(len(self.requested), 2)

    def test_future_bundle_hash_is_discovered(self):
        future = BUNDLE.replace('NEW123', 'FUTURE456')
        def fetch(url, *, max_bytes):
            if url == WIKI_PAGE:
                return ('<script src="' + future + '"></script>').encode()
            return self.fetch(BUNDLE if url == future else url, max_bytes=max_bytes)
        result = self.refresh(fetcher=fetch)
        self.assertEqual(result['status']['state'], 'fresh')
        self.assertIn(future, result['status']['sourceUrls'])

    def test_duplicate_or_missing_tool_id_fails_closed(self):
        for bundle in [b'var nothing=1', b'var a={VITE_TOOL_ID:"a"},b={VITE_TOOL_ID:"b"}']:
            def fetch(url, *, max_bytes):
                return bundle if url == BUNDLE else self.fetch(url, max_bytes=max_bytes)
            self.assertIsNone(self.refresh(fetcher=fetch)['data'])

    def test_transient_html_failure_uses_live_public_version_service(self):
        def fetch(url, *, max_bytes):
            if url == WIKI_PAGE:
                raise HTTPError(url, 502, 'temporary', {}, None)
            return self.fetch(url, max_bytes=max_bytes)
        result = self.refresh(fetcher=fetch)
        self.assertEqual(result['status']['state'], 'fresh')
        self.assertEqual(result['status']['discoveryMethod'], 'verified-public-tool-id-fallback')
        self.assertEqual(result['status']['version'], '500')
        self.assertIsNone(result['status']['bundleSha256'])

    def test_access_denial_does_not_trigger_alternate_discovery(self):
        called = []
        def fetch(url, *, max_bytes):
            raise HTTPError(url, 403, 'denied', {}, None)
        def version(*args, **kwargs):
            called.append(True)
            return self.version(*args, **kwargs)
        self.assertIsNone(self.refresh(fetcher=fetch, version_fetcher=version)['data'])
        self.assertFalse(called)

    def test_oversized_response_rejected(self):
        def fetch(url, *, max_bytes):
            return b'x' * (max_bytes + 1)
        self.assertIsNone(self.refresh(fetcher=fetch)['data'])

    def test_zero_samples_valid_negative_invalid(self):
        self.data['champion-detail'][0]['augmentRecommendations'][0]['numGames'] = 0
        self.assertEqual(self.refresh()['status']['state'], 'fresh')
        self.data['champion-detail'][0]['augmentRecommendations'][0]['numGames'] = -1
        self.assertEqual(self.refresh()['status']['state'], 'cached')

    def test_legacy_asset_discovery_is_not_hardcoded(self):
        names = ('heroIndex', 'augments', 'items', 'relations', 'combinations', 'changelogs', 'equipment-categories')
        script = ';'.join('new URL("//huyafedltc.msstatic.com/gametool/league-of-legends/work/assets/' + name + '-FUTURE.json",import.meta.url)' for name in names)
        sources = discover_sources('', [('https://huyafedltc.msstatic.com/gametool/league-of-legends/work/assets/index-NEXT.js', script)])
        self.assertEqual(len(sources), 1)
        self.assertEqual(len(sources[0]['urls']), 7)

    def test_deep_nested_data_rejected(self):
        value = 0
        for _ in range(30):
            value = [value]
        with self.assertRaises(UpdateError):
            _bounded_tree(value)

    def test_transport_rejects_bad_domains_and_credentials(self):
        for url in ['http://gametool.huya.com/lolhex', 'https://gametool.huya.com.evil.test/lolhex',
                    'https://user:pass@gametool.huya.com/lolhex', 'https://gametool.huya.com:444/lolhex',
                    'https://127.0.0.1/', 'file:///tmp/foo']:
            with self.subTest(url=url), self.assertRaises(UpdateError):
                validate_url(url, HUYA_HOSTS)

    def test_redirect_destination_is_checked_before_request(self):
        redirect = SafeRedirects(HUYA_HOSTS)
        with self.assertRaises(UpdateError):
            redirect.redirect_request(None, None, 302, '', {}, 'http://127.0.0.1/private')

    def test_non_finite_and_duplicate_json_rejected(self):
        for payload in [b'{"a":NaN}', b'{"a":1,"a":2}']:
            with self.assertRaises(UpdateError):
                strict_json(payload)


if __name__ == '__main__':
    unittest.main()

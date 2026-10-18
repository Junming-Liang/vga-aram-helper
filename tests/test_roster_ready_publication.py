"""Verified canonical roster publication is independent of portrait completion.

Owned public-asset and local-API transports only. No live requests, game process,
Qt rendering, or screenshot evidence is claimed by these tests.
"""
import hashlib
import io
import json
from pathlib import Path
import ssl
import tempfile
import threading
import unittest
from unittest.mock import patch

from PIL import Image
import hero_portraits
import live_client_identity as live
from tests.test_live_client_identity import Connection, Response


VERSION = '16.20.1'
NAME = 'Owned identity#TEST'


def roster(version=VERSION):
    return {'version': version, 'data': {
        str(i): {'key': str(i), 'id': 'Owned' + str(i),
                 'image': {'full': 'Owned' + str(i) + '.png'}}
        for i in range(1, 101)}}


class OwnedAssets:
    def __init__(self, *, version=VERSION, payload=None, block_second=False,
                 fail_second=False, cancel_after_roster=None):
        self.version = version
        self.payload = json.dumps(roster(version)).encode() if payload is None else payload
        image = Image.new('RGB', (64, 64), (100, 50, 25))
        output = io.BytesIO(); image.save(output, 'PNG'); self.png = output.getvalue()
        self.block_second = block_second
        self.fail_second = fail_second
        self.cancel_after_roster = cancel_after_roster
        self.entered = threading.Event(); self.release = threading.Event()
        self.calls = []; self.image_calls = []

    def __call__(self, url, **kwargs):
        if kwargs['hosts'] != hero_portraits.HOSTS:
            raise AssertionError('The verified public host boundary changed')
        if not url.startswith(hero_portraits.BASE + '/') or kwargs['timeout'] != 8:
            raise AssertionError('The public request boundary changed')
        self.calls.append(url)
        if url.endswith('/versions.json'):
            if kwargs['max_bytes'] != 64 * 1024: raise AssertionError('Version limit changed')
            return json.dumps([self.version]).encode()
        if url.endswith('/champion.json'):
            if kwargs['max_bytes'] != 2 * 1024 * 1024: raise AssertionError('Roster limit changed')
            if self.cancel_after_roster is not None: self.cancel_after_roster.set()
            return self.payload
        self.image_calls.append(url)
        if url.endswith('/Owned2.png'):
            self.entered.set()
            if self.block_second and not self.release.wait(5):
                raise TimeoutError('Owned portrait was not released')
            if self.fail_second: raise TimeoutError('Owned portrait failure')
        return self.png


class RosterReadyPublicationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.cache = Path(self.directory.name) / 'portraits'

    def healthy_api(self, mapping):
        player = {'riotId': NAME, 'rawChampionName': live.PREFIX + 'Owned1'}
        owned = [Connection(Response(json.dumps(body).encode()))
                 for body in (NAME, [player], NAME, [player])]
        outcomes = []
        context = ssl.create_default_context()
        with patch.object(live.ssl, 'create_default_context', return_value=context), \
                patch.object(live.http.client, 'HTTPSConnection', side_effect=owned) as factory:
            result = live.read_current_identity(mapping, enabled=True,
                cancelled=threading.Event(), scope_probe=lambda: (123, 456, 789),
                diagnostic_callback=outcomes.append)
        if result is not None:
            self.assertTrue(all(connection.closed for connection in owned))
            self.assertEqual([c.calls[0][0] for c in owned],
                             [('GET', '/liveclientdata/activeplayername'),
                              ('GET', '/liveclientdata/playerlist')] * 2)
        return result, outcomes[-1], factory.call_count

    def test_slow_second_portrait_no_longer_blocks_verified_roster_api(self):
        server = OwnedAssets(block_second=True)
        published = []; complete = []
        def publish(mapping, status):
            self.assertFalse(server.image_calls)
            published.append((mapping, status))
        worker = threading.Thread(target=lambda: complete.append(hero_portraits.load_portraits(
            self.cache, fetcher=server, roster_callback=publish)))
        worker.start()
        try:
            self.assertTrue(server.entered.wait(3))
            self.assertEqual(len(published), 1)
            snapshot, status = published[0]
            self.assertIsInstance(snapshot, tuple)
            self.assertTrue(all(isinstance(pair, tuple) for pair in snapshot))
            self.assertEqual(len(snapshot), 100)
            self.assertEqual(status, {'state': 'verified-roster', 'version': VERSION,
                'rosterSha256': hashlib.sha256(server.payload).hexdigest(), 'count': 100})
            self.assertFalse(complete)
            self.assertFalse((self.cache / 'manifest.json').exists())
            self.assertFalse((self.cache / ('roster-' + VERSION + '.json')).exists())
            self.assertEqual(self.healthy_api({}), (None, 'map_invalid', 0))
            result, outcome, calls = self.healthy_api(dict(snapshot))
            self.assertEqual((outcome, calls), ('verified', 4))
            self.assertEqual(result, {'championId': '1', 'confident': True, 'method': 'game-client-api'})
            detached = dict(snapshot); detached['Owned1'] = '999'
            self.assertEqual(dict(snapshot)['Owned1'], '1')
        finally:
            server.release.set(); worker.join(5)
        self.assertFalse(worker.is_alive())
        self.assertEqual(len(complete[0][0]), 100)
        self.assertEqual(complete[0][1]['state'], 'fresh')
        self.assertEqual(complete[0][1]['canonicalMap'], dict(published[0][0]))

    def test_malformed_mismatched_incomplete_or_noncanonical_roster_fails_closed(self):
        invalid = [b'{', b'null', b'{"version":"16.20.1","version":"16.20.1","data":{}}']
        variants = []
        value = roster(); value['version'] = '16.19.1'; variants.append(value)
        value = roster(); value['data'].pop('100'); variants.append(value)
        value = roster(); value['data']['2']['key'] = '1'; variants.append(value)
        value = roster(); value['data']['2']['id'] = 'Owned1'; value['data']['2']['image']['full'] = 'Owned1.png'; variants.append(value)
        value = roster(); value['data']['2']['image']['full'] = '../Owned2.png'; variants.append(value)
        value = roster(); value['data']['2']['image'] = []; variants.append(value)
        invalid.extend(json.dumps(value).encode() for value in variants)
        for index, payload in enumerate(invalid):
            with self.subTest(index=index):
                server = OwnedAssets(payload=payload); published = []
                bank, status = hero_portraits.load_portraits(self.cache,
                    fetcher=server, roster_callback=lambda *args: published.append(args))
                self.assertEqual(bank, {}); self.assertEqual(status['state'], 'unavailable')
                self.assertFalse(published); self.assertFalse(server.image_calls)
                self.assertFalse((self.cache / 'manifest.json').exists())

    def test_noncanonical_identity_ids_never_publish_api_dictionary(self):
        # The existing portrait-only parser accepts numeric strings such as
        # zero; that must not turn into weaker local identity validation.
        for key in ('0', '02'):
            with self.subTest(key=key), tempfile.TemporaryDirectory() as directory:
                value = roster(); value['data']['2']['key'] = key
                server = OwnedAssets(payload=json.dumps(value).encode()); published = []
                bank, status = hero_portraits.load_portraits(Path(directory), fetcher=server,
                    roster_callback=lambda *args: published.append(args))
                self.assertEqual(len(bank), 100); self.assertFalse(published)
                self.assertEqual(self.healthy_api(status['canonicalMap']), (None, 'map_invalid', 0))

    def test_cancel_after_roster_fetch_never_publishes_or_downloads_images(self):
        cancelled = threading.Event(); server = OwnedAssets(cancel_after_roster=cancelled)
        published = []
        bank, status = hero_portraits.load_portraits(self.cache, fetcher=server,
            cancelled=cancelled, roster_callback=lambda *args: published.append(args))
        self.assertFalse(bank); self.assertFalse(published); self.assertFalse(server.image_calls)
        self.assertEqual(status['state'], 'unavailable')

    def test_cancel_in_roster_callback_stops_before_any_image(self):
        cancelled = threading.Event(); server = OwnedAssets(); published = []
        def publish(*args):
            published.append(args); cancelled.set()
        bank, status = hero_portraits.load_portraits(self.cache, fetcher=server,
            cancelled=cancelled, roster_callback=publish)
        self.assertEqual(len(published), 1); self.assertFalse(server.image_calls)
        self.assertFalse(bank); self.assertEqual(status['state'], 'unavailable')

    def test_image_failure_keeps_verified_dictionary_without_partial_bank_or_manifest(self):
        server = OwnedAssets(fail_second=True); published = []
        bank, status = hero_portraits.load_portraits(self.cache, fetcher=server,
            roster_callback=lambda *args: published.append(args))
        self.assertFalse(bank); self.assertEqual(status['state'], 'unavailable')
        self.assertEqual(len(published), 1)
        self.assertEqual(self.healthy_api(dict(published[0][0]))[1:], ('verified', 4))
        self.assertFalse((self.cache / 'manifest.json').exists())

    def test_failed_new_version_never_replaces_complete_old_manifest(self):
        initial, _ = hero_portraits.load_portraits(self.cache, fetcher=OwnedAssets())
        self.assertEqual(len(initial), 100)
        manifest = (self.cache / 'manifest.json').read_bytes()
        server = OwnedAssets(version='16.21.1', fail_second=True); published = []
        bank, status = hero_portraits.load_portraits(self.cache, fetcher=server,
            roster_callback=lambda *args: published.append(args))
        self.assertEqual(len(bank), 100); self.assertEqual(status['version'], VERSION)
        self.assertEqual(published[0][1]['version'], '16.21.1')
        self.assertEqual((self.cache / 'manifest.json').read_bytes(), manifest)
        self.assertFalse((self.cache / 'roster-16.21.1.json').exists())

    def test_disabled_downloads_do_not_publish_unverified_dictionary(self):
        published = []
        with patch.object(hero_portraits, 'fetch_bytes') as fetch:
            bank, status = hero_portraits.load_portraits(self.cache, allow_download=False,
                roster_callback=lambda *args: published.append(args))
        self.assertFalse(bank); self.assertFalse(published); fetch.assert_not_called()


if __name__ == '__main__': unittest.main()

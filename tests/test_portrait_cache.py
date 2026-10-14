"""Synthetic portrait-cache failures, plus real Windows sharing-lock fixtures.

No game images, live network calls, administrator rights or ACL changes.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import errno
import gc
import importlib.util
import json
import os
from pathlib import Path
import struct
import tempfile
import threading
import time
import unittest
import weakref
from unittest.mock import patch
import zlib

import hero_portraits as portraits
from update_network import UpdateError


def roster(version):
    return json.dumps({'version': version, 'data': {
        str(i): {'key': str(i), 'id': 'Hero'+str(i),
                 'image': {'full': 'Hero'+str(i)+'.png'}} for i in range(100)
    }}).encode()


def fetcher(version='16.20.1', bad_asset=None):
    def fetch(url, **kwargs):
        if kwargs['hosts'] != portraits.HOSTS:
            raise AssertionError('Portrait HTTPS allowlist changed')
        if url.endswith('versions.json'):
            return json.dumps([version]).encode()
        if url.endswith('champion.json'):
            return roster(version)
        if bad_asset and url.endswith('/'+bad_asset):
            raise ValueError('Synthetic invalid image')
        return ('synthetic-icon-'+version).encode()
    return fetch


def windows_error(code=5):
    error = PermissionError(errno.EACCES, 'Synthetic Windows sharing error')
    error.winerror = code
    return error


class CacheWriteTests(unittest.TestCase):
    def write(self, path, payload=b'new', **kwargs):
        return portraits._write_cache(path, payload,
            cancelled=kwargs.get('cancelled', threading.Event()),
            deadline=kwargs.get('deadline', time.monotonic()+5))

    def test_transient_windows_errors_retry_closed_same_unique_temp(self):
        for code in (5, 32, 33):
            with self.subTest(winerror=code), tempfile.TemporaryDirectory() as temp:
                path = Path(temp)/'Briar.png'
                path.write_bytes(b'old')
                replace = os.replace
                sources = []
                def flaky(source, destination):
                    sources.append(source)
                    # Opening for write is also a real Windows handle-close check.
                    with open(source, 'ab'):
                        pass
                    if len(sources) < 3:
                        raise windows_error(code)
                    replace(source, destination)
                with patch.object(portraits.os, 'replace', side_effect=flaky), \
                     patch.object(portraits, '_CACHE_RETRY_DELAYS', (0, 0, 0)):
                    self.write(path)
                self.assertEqual(len(sources), 3)
                self.assertEqual(len(set(sources)), 1)
                self.assertEqual(path.read_bytes(), b'new')
                self.assertEqual(list(Path(temp).iterdir()), [path])

    def test_persistent_lock_is_bounded_and_preserves_destination(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'Briar.png'
            path.write_bytes(b'old')
            with patch.object(portraits.os, 'replace', side_effect=windows_error()) as replace, \
                 patch.object(portraits, '_CACHE_RETRY_DELAYS', (0, 0, 0)):
                with self.assertRaises(PermissionError):
                    self.write(path)
            self.assertEqual(replace.call_count, 4)
            self.assertEqual(path.read_bytes(), b'old')
            self.assertEqual(list(Path(temp).iterdir()), [path])

    def test_non_sharing_errors_are_not_retried(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(portraits.os, 'replace', side_effect=OSError(errno.ENOSPC, 'Full')) as replace:
                with self.assertRaises(OSError):
                    self.write(Path(temp)/'Briar.png')
            self.assertEqual(replace.call_count, 1)
            self.assertFalse(list(Path(temp).iterdir()))

    def test_equal_existing_bytes_do_not_need_write_access(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'Briar.png'
            path.write_bytes(b'new')
            with patch.object(portraits.tempfile, 'mkstemp', side_effect=AssertionError('Unnecessary write')):
                self.write(path)

    def test_retry_wait_is_cancelled_and_cleans_own_temp(self):
        with tempfile.TemporaryDirectory() as temp:
            event = threading.Event()
            def locked(*args):
                event.set()
                raise windows_error()
            with patch.object(portraits.os, 'replace', side_effect=locked) as replace:
                with self.assertRaisesRegex(UpdateError, 'cancelled'):
                    self.write(Path(temp)/'Briar.png', cancelled=event)
            self.assertEqual(replace.call_count, 1)
            self.assertFalse(list(Path(temp).iterdir()))

    def test_expired_deadline_performs_no_io(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(UpdateError, 'timed out'):
                self.write(Path(temp)/'Briar.png', deadline=time.monotonic()-1)
            self.assertFalse(list(Path(temp).iterdir()))

    def test_contended_cache_lock_has_a_bounded_wait(self):
        with tempfile.TemporaryDirectory() as temp:
            lock = threading.Lock()
            with lock, patch.object(portraits, '_cache_lock', return_value=lock), \
                 patch.object(portraits, '_CACHE_LOCK_TIMEOUT', 0.01):
                with self.assertRaisesRegex(OSError, 'busy'):
                    self.write(Path(temp)/'Briar.png')
            self.assertFalse(list(Path(temp).iterdir()))

    def test_unrelated_paths_do_not_share_a_contended_lock(self):
        # Find a pair that the old 32-stripe implementation conflated. No slow
        # disks, Windows-only timing assumptions or weakened timeout required.
        with tempfile.TemporaryDirectory() as temp:
            buckets={};pair=None
            for index in range(33):
                path=Path(temp)/f'Hero{index}.png'
                stripe=hash(os.path.normcase(str(path.resolve())))%32
                if stripe in buckets:
                    pair=(buckets[stripe],path);break
                buckets[stripe]=path
            self.assertIsNotNone(pair)
            first,second=pair
            held=portraits._cache_lock(first)
            self.assertIsNot(held,portraits._cache_lock(second))
            self.assertIs(held,portraits._cache_lock(first.parent/'nested'/'..'/first.name))
            with held:
                self.write(second)
            self.assertEqual(second.read_bytes(),b'new')
            self.assertFalse(first.exists())

    def test_exact_path_registry_is_atomic_and_releases_historical_keys(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'Hero0.png';barrier=threading.Barrier(6)
            def obtain(_):
                lock=portraits._cache_lock(path)
                barrier.wait(timeout=5)
                return lock
            with ThreadPoolExecutor(max_workers=6) as pool:locks=list(pool.map(obtain,range(6)))
            self.assertTrue(all(lock is locks[0] for lock in locks))
            reference=weakref.ref(locks[0]);key=os.path.normcase(str(path.resolve()))
            self.assertIn(key,portraits._CACHE_LOCKS)
            del locks
            gc.collect()
            self.assertIsNone(reference())
            self.assertNotIn(key,portraits._CACHE_LOCKS)

    def test_same_key_concurrent_writers_publish_only_once(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'Briar.png'
            barrier = threading.Barrier(6)
            def write(_):
                barrier.wait(timeout=5)
                self.write(path)
            with patch.object(portraits.os, 'replace', wraps=os.replace) as replace:
                with ThreadPoolExecutor(max_workers=6) as pool:
                    list(pool.map(write, range(6)))
            self.assertEqual(replace.call_count, 1)
            self.assertEqual(path.read_bytes(), b'new')
            self.assertEqual(list(Path(temp).iterdir()), [path])

    def test_cleanup_error_does_not_replace_primary_error(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(portraits.os, 'replace', side_effect=OSError(errno.ENOSPC, 'Full')), \
                 patch.object(portraits.os, 'unlink', side_effect=PermissionError('Temp scanned')):
                with self.assertRaises(OSError) as result:
                    self.write(Path(temp)/'Briar.png')
            self.assertEqual(result.exception.errno, errno.ENOSPC)


@patch.object(portraits, 'decode_portrait', side_effect=lambda payload: 'decoded:'+payload.decode())
class PortraitBankPersistenceTests(unittest.TestCase):
    def test_one_locked_portrait_keeps_complete_bank_without_manifest(self, _):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'16.20.1/Hero0.png'
            path.parent.mkdir()
            path.write_bytes(b'old-incomplete-cache')
            replace = os.replace
            attempts = []
            def locked(source, destination):
                if Path(destination) == path:
                    attempts.append(source)
                    raise windows_error()
                return replace(source, destination)
            with patch.object(portraits.os, 'replace', side_effect=locked), \
                 patch.object(portraits, '_CACHE_RETRY_DELAYS', (0, 0, 0)):
                bank, status = portraits.load_portraits(temp, fetcher=fetcher())
            self.assertEqual(len(bank), 100)
            self.assertEqual(status['state'], 'memory-only')
            self.assertIn('本次仍可自动识别', status['message'])
            self.assertEqual(len(attempts), 4)
            self.assertEqual(path.read_bytes(), b'old-incomplete-cache')
            self.assertFalse((Path(temp)/'manifest.json').exists())
            offline, _ = portraits.load_portraits(temp, allow_download=False)
            self.assertFalse(offline)

    def test_unwritable_directory_stops_further_writes_but_not_downloads(self, _):
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(portraits, '_write_cache', side_effect=PermissionError('Read-only')) as write:
                bank, status = portraits.load_portraits(temp, fetcher=fetcher())
            self.assertEqual(len(bank), 100)
            self.assertEqual(status['state'], 'memory-only')
            self.assertLessEqual(write.call_count, 6)
            self.assertFalse(list(Path(temp).iterdir()))

    def test_manifest_or_roster_write_failure_keeps_complete_memory_bank(self, _):
        for failed_name in ('manifest.json', 'roster-16.20.1.json'):
            with self.subTest(file=failed_name), tempfile.TemporaryDirectory() as temp:
                original = portraits._write_cache
                def fail(path, payload, **kwargs):
                    if Path(path).name == failed_name:
                        raise PermissionError('Read-only')
                    return original(path, payload, **kwargs)
                with patch.object(portraits, '_write_cache', side_effect=fail):
                    bank, status = portraits.load_portraits(temp, fetcher=fetcher())
                self.assertEqual(len(bank), 100)
                self.assertEqual(status['state'], 'memory-only')
                self.assertFalse((Path(temp)/'manifest.json').exists())

    def test_failed_refresh_preserves_previous_valid_manifest_and_cache(self, _):
        with tempfile.TemporaryDirectory() as temp:
            old_bank, _ = portraits.load_portraits(temp, fetcher=fetcher())
            manifest = (Path(temp)/'manifest.json').read_bytes()
            with patch.object(portraits, '_write_cache', side_effect=PermissionError('Read-only')):
                new_bank, status = portraits.load_portraits(temp, fetcher=fetcher('16.21.1'))
            self.assertEqual(len(new_bank), 100)
            self.assertNotEqual(new_bank, old_bank)
            self.assertEqual(status['state'], 'memory-only')
            self.assertEqual((Path(temp)/'manifest.json').read_bytes(), manifest)
            offline, _ = portraits.load_portraits(temp, allow_download=False)
            self.assertEqual(offline, old_bank)

    def test_incomplete_download_never_becomes_memory_only_bank(self, _):
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(portraits, '_write_cache', side_effect=PermissionError('Read-only')):
                bank, status = portraits.load_portraits(temp, fetcher=fetcher(bad_asset='Hero99.png'))
            self.assertFalse(bank)
            self.assertEqual(status['state'], 'unavailable')

    def test_invalid_refresh_returns_previous_complete_verified_bank(self, _):
        with tempfile.TemporaryDirectory() as temp:
            old_bank, _ = portraits.load_portraits(temp, fetcher=fetcher())
            with patch.object(portraits, '_write_cache', side_effect=PermissionError('Read-only')):
                bank, status = portraits.load_portraits(temp, fetcher=fetcher('16.21.1', 'Hero99.png'))
            self.assertEqual(bank, old_bank)
            self.assertEqual(status['version'], '16.20.1')

    def test_two_complete_loads_can_share_cache_directory(self, _):
        with tempfile.TemporaryDirectory() as temp:
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda _: portraits.load_portraits(temp, fetcher=fetcher()), range(2)))
            for bank, status in results:
                self.assertEqual(len(bank), 100)
                self.assertIn(status['state'], ('fresh', 'current'))
            bank, status = portraits.load_portraits(temp, allow_download=False)
            self.assertEqual(len(bank), 100)
            self.assertEqual(status['state'], 'cached')
            self.assertFalse(list(Path(temp).rglob('.*-*')))


@unittest.skipUnless(importlib.util.find_spec('PIL'), 'Pillow is an optional source dependency')
class DecodedPortraitFallbackTests(unittest.TestCase):
    def test_memory_only_bank_contains_real_decoded_images(self):
        def chunk(kind, data):
            return struct.pack('!I', len(data))+kind+data+struct.pack('!I', zlib.crc32(kind+data))
        png = (b'\x89PNG\r\n\x1a\n'
               +chunk(b'IHDR', struct.pack('!2I5B', 64, 64, 8, 2, 0, 0, 0))
               +chunk(b'IDAT', zlib.compress((b'\0'+b'\x10\x20\x30'*64)*64))
               +chunk(b'IEND', b''))
        official = fetcher()
        def fetch(url, **kwargs):
            return png if url.endswith('.png') else official(url, **kwargs)
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(portraits, '_write_cache', side_effect=PermissionError('Read-only')):
                bank, status = portraits.load_portraits(temp, fetcher=fetch)
            self.assertEqual(len(bank), 100)
            self.assertEqual(status['state'], 'memory-only')
            self.assertTrue(all(image.mode == 'RGB' and image.size == (64, 64) for image in bank.values()))

    def test_invalid_image_does_not_bypass_decode_when_cache_is_unwritable(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(portraits, '_write_cache', side_effect=PermissionError('Read-only')):
                bank, status = portraits.load_portraits(temp, fetcher=fetcher())
            self.assertFalse(bank)
            self.assertEqual(status['state'], 'unavailable')


@contextmanager
def windows_read_lock(path):
    """Hold a real Windows handle that permits reads/writes but denies delete."""
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.CreateFileW(str(path), 0x80000000, 0x1 | 0x2, None, 3, 0x80, None)
    if handle == wintypes.HANDLE(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    closed = False
    def close():
        nonlocal closed
        if not closed:
            if not kernel.CloseHandle(handle):
                raise ctypes.WinError(ctypes.get_last_error())
            closed = True
    try:
        yield close
    finally:
        close()


@unittest.skipUnless(os.name == 'nt', 'Requires actual Windows file-sharing semantics')
class WindowsPortraitCacheTests(unittest.TestCase):
    def test_real_sharing_lock_recovers_after_release(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'Briar.png'
            path.write_bytes(b'old')
            failures = []
            replace = os.replace
            with windows_read_lock(path) as release:
                def observed(source, destination):
                    try:
                        return replace(source, destination)
                    except OSError as exc:
                        failures.append(exc.winerror)
                        release()
                        raise
                with patch.object(portraits.os, 'replace', side_effect=observed):
                    portraits._write_cache(path, b'new', cancelled=threading.Event(), deadline=time.monotonic()+5)
            self.assertEqual(len(failures), 1)
            self.assertIn(failures[0], (5, 32, 33))
            self.assertEqual(path.read_bytes(), b'new')
            self.assertEqual(list(Path(temp).iterdir()), [path])

    @patch.object(portraits, 'decode_portrait', side_effect=lambda payload: 'decoded:'+payload.decode())
    def test_real_persistent_lock_preserves_file_and_still_loads_complete_bank(self, _):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'16.20.1/Hero0.png'
            path.parent.mkdir()
            path.write_bytes(b'old')
            with windows_read_lock(path):
                bank, status = portraits.load_portraits(temp, fetcher=fetcher())
                self.assertEqual(path.read_bytes(), b'old')
            self.assertEqual(len(bank), 100)
            self.assertEqual(status['state'], 'memory-only')
            self.assertFalse((Path(temp)/'manifest.json').exists())
            self.assertFalse(list(Path(temp).rglob('.*-*')))

    def test_real_locked_equal_destination_is_reused_without_replace(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'Briar.png'
            path.write_bytes(b'new')
            with windows_read_lock(path), patch.object(portraits.os, 'replace', wraps=os.replace) as replace:
                portraits._write_cache(path, b'new', cancelled=threading.Event(), deadline=time.monotonic()+5)
            replace.assert_not_called()

    @patch.object(portraits, 'decode_portrait', side_effect=lambda payload: 'decoded:'+payload.decode())
    def test_real_locked_manifest_keeps_old_offline_bank_and_new_memory_bank(self, _):
        with tempfile.TemporaryDirectory() as temp:
            old_bank, _ = portraits.load_portraits(temp, fetcher=fetcher())
            manifest = Path(temp)/'manifest.json'
            previous = manifest.read_bytes()
            with windows_read_lock(manifest):
                bank, status = portraits.load_portraits(temp, fetcher=fetcher('16.21.1'))
                self.assertEqual(manifest.read_bytes(), previous)
            self.assertEqual(len(bank), 100)
            self.assertEqual(status['state'], 'memory-only')
            self.assertEqual(status['version'], '16.21.1')
            offline, _ = portraits.load_portraits(temp, allow_download=False)
            self.assertEqual(offline, old_bank)
            self.assertFalse(list(Path(temp).rglob('.*-*')))


if __name__ == '__main__':
    unittest.main()

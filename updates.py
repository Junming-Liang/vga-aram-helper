"""User-confirmed Windows one-file OTA from this app's own public GitHub Releases.

Checksums protect integrity, not publisher identity: these releases are unsigned.
The currently installed, trusted executable runs the replacement/rollback process.
No downloaded updater script, shell command, ZIP payload, or remote code is run.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit
from urllib.request import HTTPSHandler, Request, build_opener

from update_network import (GITHUB_HOSTS, SafeRedirects, UpdateError, atomic_write, fetch_bytes,
                            json_bytes, runtime_state_dir, strict_json, validate_url)

REPOSITORY = 'Junming-Liang/vga-aram-helper'
REPO_URL = 'https://github.com/' + REPOSITORY
LATEST_API = 'https://api.github.com/repos/' + REPOSITORY + '/releases/latest'
PLATFORM = 'windows-x64'
MAX_EXE_BYTES = 512 * 1024 * 1024
MANIFEST_NAME = 'update-manifest.json'


def _version(value):
    if not isinstance(value, str) or not re.fullmatch(r'v?\d{1,5}\.\d{1,5}(?:\.\d{1,5})?', value):
        raise UpdateError('Invalid stable release version')
    parts = tuple(int(x) for x in value.removeprefix('v').split('.'))
    return parts + (0,) * (3 - len(parts))


def _release_url(url, *, tag=None, filename=None):
    validate_url(url, frozenset({'github.com'}))
    parsed = urlsplit(url)
    if parsed.query or parsed.fragment:
        raise UpdateError('Release URL cannot contain a query')
    prefix = '/' + REPOSITORY + '/releases/download/'
    if not parsed.path.startswith(prefix):
        raise UpdateError('Update is not from the approved repository')
    path = parsed.path[len(prefix):].split('/')
    if len(path) != 2 or not path[1]:
        raise UpdateError('Invalid release asset URL')
    _version(path[0])
    if tag is not None and path[0] != tag:
        raise UpdateError('Release tag mismatch')
    if filename is not None and path[1] != filename:
        raise UpdateError('Release asset name mismatch')
    return url


def validate_manifest(manifest, *, tag=None):
    if not isinstance(manifest, dict) or manifest.get('schema_version') != 1:
        raise UpdateError('Unsupported update manifest')
    version = manifest.get('version')
    _version(version)
    if version.startswith('v'):
        raise UpdateError('Manifest version must not start with v')
    if tag is not None and _version(tag) != _version(version):
        raise UpdateError('Manifest version does not match release')
    if manifest.get('platform') != PLATFORM:
        raise UpdateError('Update platform mismatch')
    size = manifest.get('size')
    if type(size) is not int or not 2 <= size <= MAX_EXE_BYTES:
        raise UpdateError('Invalid executable size')
    checksum = manifest.get('sha256')
    if not isinstance(checksum, str) or not re.fullmatch(r'[0-9a-f]{64}', checksum):
        raise UpdateError('Invalid executable checksum')
    filename = f'vga-aram-helper-{version}-{PLATFORM}.exe'
    _release_url(manifest.get('url'), tag=tag, filename=filename)
    return {'schema_version': 1, 'version': version, 'platform': PLATFORM,
            'url': manifest['url'], 'sha256': checksum, 'size': size}


def check_for_update(current_version: str, *, fetcher=None) -> dict:
    """Read-only check. A new version is NEVER downloaded or installed here."""
    if fetcher is None:
        def fetcher(url, *, max_bytes):
            return fetch_bytes(url, max_bytes=max_bytes, hosts=GITHUB_HOSTS, timeout=10)
    try:
        current = _version(current_version)
        payload = fetcher(LATEST_API, max_bytes=1024 * 1024)
        if len(payload) > 1024 * 1024:
            raise UpdateError('Release metadata exceeds size limit')
        release = strict_json(payload)
        if not isinstance(release, dict) or release.get('draft') or release.get('prerelease'):
            raise UpdateError('No stable release')
        tag = release.get('tag_name')
        latest = _version(tag)
        release_page = REPO_URL + '/releases/tag/' + tag
        if release.get('html_url') != release_page:
            raise UpdateError('Release repository mismatch')
        if latest <= current:
            return {'state': 'current', 'message': '当前已是最新稳定版。', 'currentVersion': current_version}
        assets = release.get('assets', [])
        if not isinstance(assets, list):
            raise UpdateError('Invalid release assets')
        matches = [a for a in assets if isinstance(a, dict) and a.get('name') == MANIFEST_NAME]
        if len(matches) != 1:
            raise UpdateError('Release has no unique update manifest')
        manifest_url = _release_url(matches[0].get('browser_download_url'), tag=tag, filename=MANIFEST_NAME)
        raw_manifest = fetcher(manifest_url, max_bytes=65536)
        if len(raw_manifest) > 65536:
            raise UpdateError('Manifest exceeds size limit')
        manifest = validate_manifest(strict_json(raw_manifest), tag=tag)
        binary_matches = [a for a in assets if isinstance(a, dict)
                          and a.get('browser_download_url') == manifest['url']]
        if len(binary_matches) != 1 or binary_matches[0].get('size') != manifest['size']:
            raise UpdateError('Binary is missing from the release or has the wrong size')
        api_digest = binary_matches[0].get('digest')
        if api_digest and api_digest != 'sha256:' + manifest['sha256']:
            raise UpdateError('GitHub asset checksum disagrees with manifest')
        notes = release.get('body')
        return {'state': 'available', 'currentVersion': current_version,
                'message': '发现新版本。仅在你确认后下载并安装；SHA-256 校验不等于代码签名。',
                'release': {'version': manifest['version'], 'url': release_page,
                            'notes': notes[:12000] if isinstance(notes, str) else '',
                            'manifest': manifest, 'signed': False}}
    except (OSError, ValueError, TypeError, TimeoutError, RecursionError):
        return {'state': 'unavailable', 'currentVersion': current_version,
                'message': '暂时无法校验新版本（网络或发布资源尚未就绪）。当前软件仍可继续使用。'}


def _sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def _download_exe(manifest, destination):
    """Stream bounded bytes to a non-executable staging file; TLS redirects checked."""
    url = _release_url(manifest['url'])
    opener = build_opener(SafeRedirects(GITHUB_HOSTS), HTTPSHandler())
    request = Request(url, headers={'User-Agent': 'VGA-Aram-Helper-Updater/1', 'Accept-Encoding': 'identity'})
    deadline, size, digest = time.monotonic() + 300, 0, hashlib.sha256()
    with opener.open(request, timeout=15) as response, Path(destination).open('xb') as output:
        validate_url(response.geturl(), GITHUB_HOSTS)
        length = response.headers.get('Content-Length')
        if length is not None and (not length.isdecimal() or int(length) != manifest['size']):
            raise UpdateError('Download length does not match release')
        while True:
            if time.monotonic() > deadline:
                raise UpdateError('Executable download timed out')
            chunk = response.read(min(1024 * 1024, manifest['size'] + 1 - size))
            if not chunk:
                break
            size += len(chunk)
            if size > manifest['size']:
                raise UpdateError('Executable exceeds approved size')
            digest.update(chunk)
            output.write(chunk)
        output.flush()
        os.fsync(output.fileno())
    if size != manifest['size'] or digest.hexdigest() != manifest['sha256']:
        raise UpdateError('Executable checksum or size mismatch')
    _verify_exe(destination, manifest)


def _verify_exe(path, manifest):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size != manifest['size']:
        raise UpdateError('Invalid staged executable')
    if _sha256(path) != manifest['sha256']:
        raise UpdateError('Staged executable checksum mismatch')
    with path.open('rb') as handle:
        if handle.read(2) != b'MZ':
            raise UpdateError('Not a Windows executable')
        handle.seek(60)
        pointer = handle.read(4)
        if len(pointer) != 4:
            raise UpdateError('Invalid PE header')
        offset = int.from_bytes(pointer, 'little')
        if offset < 64 or offset > min(manifest['size'] - 6, 1024 * 1024):
            raise UpdateError('Invalid PE header offset')
        handle.seek(offset)
        if handle.read(6) != b'PE\x00\x00\x64\x86':
            raise UpdateError('Expected a Windows x64 PE executable')


def prepare_update(release: dict, current_executable: Path, state_dir: Path, *, confirmed=False,
                   downloader=None) -> Path:
    """Download only after explicit UI confirmation. Does not replace or run files."""
    if confirmed is not True:
        raise UpdateError('请先确认安装此版本。')
    if not isinstance(release, dict):
        raise UpdateError('Invalid release')
    manifest = validate_manifest(release.get('manifest'))
    if release.get('version') != manifest['version']:
        raise UpdateError('Confirmation version mismatch')
    current = Path(current_executable).resolve(strict=True)
    if not _valid_executable_name(current.name) or not current.is_file():
        raise UpdateError('请使用正式 Windows 独立 EXE 进行软件更新。')
    updates_dir = Path(state_dir).resolve() / 'updates'
    updates_dir.mkdir(parents=True, exist_ok=True)
    job = Path(tempfile.mkdtemp(prefix='update-', dir=updates_dir)).resolve()
    try:
        candidate = job / 'candidate.bin'
        (downloader or _download_exe)(manifest, candidate)
        _verify_exe(candidate, manifest)
        # Run a copy of CURRENT app as updater, never a downloaded script/updater.
        updater = job / 'updater.exe'
        shutil.copy2(current, updater)
        original_hash = _sha256(current)
        if _sha256(updater) != original_hash:
            raise UpdateError('Updater copy verification failed')
        plan = {'schema_version': 1, 'manifest': manifest, 'target': str(current),
                'job': str(job), 'parent_pid': os.getpid(), 'original_sha256': original_hash,
                'created_at': time.time(), 'health_token': os.urandom(24).hex()}
        plan_path = job / 'plan.json'
        atomic_write(plan_path, json_bytes(plan))
        return plan_path
    except Exception:
        shutil.rmtree(job, ignore_errors=True)
        raise


def _valid_executable_name(name):
    return (name.lower() == 'vga-aram-helper.exe'
            or re.fullmatch(r'vga-aram-helper-\d{1,5}\.\d{1,5}(?:\.\d{1,5})?-windows-x64\.exe', name) is not None)


def _read_plan(plan_path):
    path = Path(plan_path).resolve(strict=True)
    if path.name != 'plan.json' or path.stat().st_size > 65536:
        raise UpdateError('Invalid update plan')
    plan = strict_json(path.read_bytes())
    if not isinstance(plan, dict) or plan.get('schema_version') != 1:
        raise UpdateError('Invalid update plan schema')
    job = Path(plan.get('job', '')).resolve(strict=True)
    if job != path.parent or not re.fullmatch(r'update-[A-Za-z0-9_-]+', job.name) or job.parent.name != 'updates':
        raise UpdateError('Invalid update staging directory')
    target = Path(plan.get('target', ''))
    if not target.is_absolute() or not _valid_executable_name(target.name) or target.is_symlink():
        raise UpdateError('Invalid update target')
    target = target.resolve()
    if job == target.parent or job in target.parents:
        raise UpdateError('Executable cannot be inside staging')
    if type(plan.get('parent_pid')) is not int or plan['parent_pid'] <= 0:
        raise UpdateError('Invalid parent process')
    if not isinstance(plan.get('original_sha256'), str) or not re.fullmatch(r'[0-9a-f]{64}', plan['original_sha256']):
        raise UpdateError('Invalid original checksum')
    if not isinstance(plan.get('health_token'), str) or not re.fullmatch(r'[0-9a-f]{48}', plan['health_token']):
        raise UpdateError('Invalid health token')
    created = plan.get('created_at')
    if type(created) not in (int, float) or not 0 <= time.time() - created <= 24 * 3600:
        raise UpdateError('Update plan expired')
    plan['manifest'] = validate_manifest(plan.get('manifest'))
    return plan, job, target


def _windows_frozen():
    return os.name == 'nt' and getattr(sys, 'frozen', False)


def launch_update(plan_path: Path):
    """Start the current trusted updater copy. Caller must then exit the old app."""
    if not _windows_frozen():
        raise UpdateError('软件安装更新只适用于正式 Windows EXE。')
    plan, job, target = _read_plan(plan_path)
    if target != Path(sys.executable).resolve() or plan['parent_pid'] != os.getpid():
        raise UpdateError('Update does not belong to this process')
    if _sha256(job / 'updater.exe') != plan['original_sha256']:
        raise UpdateError('Updater has changed')
    _verify_exe(job / 'candidate.bin', plan['manifest'])
    return subprocess.Popen([str(job / 'updater.exe'), '--apply-update', str(Path(plan_path).resolve())],
                            close_fds=True, creationflags=0x00000008 | 0x00000200,
                            env={**os.environ, 'PYINSTALLER_RESET_ENVIRONMENT': '1'})


def _wait_for_parent(pid, timeout=90):
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    handle = kernel.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE only
    if not handle:
        if ctypes.get_last_error() == 87:  # ERROR_INVALID_PARAMETER: process gone
            return
        raise UpdateError('Cannot safely wait for the running application')
    try:
        if kernel.WaitForSingleObject(handle, int(timeout * 1000)) != 0:
            raise UpdateError('The current application has not exited')
    finally:
        kernel.CloseHandle(handle)


def _replace_with_retry(source, target, seconds=15):
    deadline = time.monotonic() + seconds
    while True:
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.25)


def _copy_synced(source, destination):
    with Path(source).open('rb') as source_file, Path(destination).open('xb') as output:
        shutil.copyfileobj(source_file, output, 1024 * 1024)
        output.flush()
        os.fsync(output.fileno())


def mark_update_healthy(token_path):
    """Launcher calls this ONLY after the new application's localhost health check."""
    path = Path(token_path).resolve()
    plan, job, target = _read_plan(path.parent / 'plan.json')
    from app_version import __version__
    if _version(__version__) != _version(plan['manifest']['version']):
        raise UpdateError('Running application version does not match the approved release')
    if path != job / 'health.json' or Path(sys.executable).resolve() != target:
        raise UpdateError('Health marker is not for this executable')
    if _sha256(target) != plan['manifest']['sha256']:
        raise UpdateError('Installed executable does not match the update')
    atomic_write(path, json_bytes({'token': plan['health_token'], 'version': plan['manifest']['version']}))


def _healthy(job, plan):
    try:
        path = job / 'health.json'
        if path.stat().st_size > 1024:
            return False
        marker = strict_json(path.read_bytes())
        return marker == {'token': plan['health_token'], 'version': plan['manifest']['version']}
    except (OSError, ValueError):
        return False


def _apply_update_locked(plan_path: Path) -> int:
    """Separate Windows updater process: wait, atomic swap, verify readiness, rollback.

    Transaction files are adjacent to the target for atomic same-volume rename.
    A verified backup is retained after success for manual recovery.
    """
    if not _windows_frozen():
        return 2
    job = None
    backup = None
    target = None
    swapped = False
    child = None
    try:
        plan, job, target = _read_plan(plan_path)
        if Path(sys.executable).resolve() != job / 'updater.exe' or _sha256(sys.executable) != plan['original_sha256']:
            raise UpdateError('Unexpected updater executable')
        _verify_exe(job / 'candidate.bin', plan['manifest'])
        _wait_for_parent(plan['parent_pid'])
        if not target.is_file() or _sha256(target) != plan['original_sha256']:
            raise UpdateError('Installed application changed before update')
        staged = target.with_name(target.name + '.' + job.name + '.new')
        backup = target.with_name(target.name + '.previous')
        backup_stage = target.with_name(target.name + '.' + job.name + '.backup')
        if staged.exists() or backup_stage.exists() or backup.is_symlink():
            raise UpdateError('Update transaction files already exist; inspect them before retrying')
        _copy_synced(job / 'candidate.bin', staged)
        _verify_exe(staged, plan['manifest'])
        # Make the recovery copy BEFORE the single atomic replacement. The live
        # target is never renamed away, including between transaction steps.
        _copy_synced(target, backup_stage)
        if _sha256(backup_stage) != plan['original_sha256']:
            raise UpdateError('Recovery copy checksum mismatch')
        _replace_with_retry(backup_stage, backup)
        _replace_with_retry(staged, target)
        swapped = True
        marker = job / 'health.json'
        marker.unlink(missing_ok=True)
        child = subprocess.Popen([str(target), '--update-health', str(marker)], cwd=target.parent, close_fds=True,
                                 env={**os.environ, 'PYINSTALLER_RESET_ENVIRONMENT': '1'})
        deadline = time.monotonic() + 150
        while time.monotonic() < deadline:
            if _healthy(job, plan):
                atomic_write(job / 'result.json', json_bytes({'state': 'installed', 'version': plan['manifest']['version'],
                             'backup': str(backup), 'signed': False}))
                return 0
            if child.poll() is not None:
                break
            time.sleep(0.5)
        raise UpdateError('New version did not become healthy in time')
    except Exception as exc:
        restored = False
        if swapped and backup is not None and backup.exists():
            if child is not None and child.poll() is None:
                # A PyInstaller onefile app has a bootloader and worker process.
                # Stop only our spawned process tree before restoring the EXE.
                taskkill = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32' / 'taskkill.exe'
                try:
                    subprocess.run([str(taskkill), '/PID', str(child.pid), '/T', '/F'],
                                   timeout=20, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                except (OSError, subprocess.TimeoutExpired):
                    pass
                try:
                    child.wait(timeout=15)
                except (OSError, subprocess.TimeoutExpired):
                    try:
                        child.kill()
                        child.wait(timeout=10)
                    except (OSError, subprocess.TimeoutExpired):
                        pass
            try:
                _replace_with_retry(backup, target)
                restored = True
                subprocess.Popen([str(target), '--no-updates'], cwd=target.parent, close_fds=True,
                                 env={**os.environ, 'PYINSTALLER_RESET_ENVIRONMENT': '1'})
            except OSError:
                pass  # Keep verified .previous backup for manual recovery.
        if job is not None:
            try:
                atomic_write(job / 'result.json', json_bytes({'state': 'rolled_back' if restored else 'failed',
                             'error': type(exc).__name__, 'message': str(exc)[:500]}))
            except OSError:
                pass
        return 1


@contextmanager
def _target_lock(target):
    """OS-held per-target lock, automatically released if the updater crashes."""
    lock_path = Path(target).with_name(Path(target).name + '.update.lock')
    if lock_path.is_symlink():
        raise UpdateError('Invalid update lock file')
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        if os.fstat(fd).st_size == 0:
            os.write(fd, b'0')
        os.lseek(fd, 0, os.SEEK_SET)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise UpdateError('Another updater is already installing this application') from exc
        try:
            yield
        finally:
            os.lseek(fd, 0, os.SEEK_SET)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def apply_update(plan_path: Path) -> int:
    """One transaction per installed EXE, including its readiness and rollback."""
    if not _windows_frozen():
        return 2
    job = None
    try:
        _, job, target = _read_plan(plan_path)
        with _target_lock(target):
            return _apply_update_locked(plan_path)
    except Exception as exc:
        if job is not None:
            try:
                atomic_write(job / 'result.json', json_bytes({'state': 'failed',
                             'error': type(exc).__name__, 'message': str(exc)[:500]}))
            except OSError:
                pass
        return 1

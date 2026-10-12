"""Execute the built EXE from an empty folder, without Python in its PATH."""
from __future__ import annotations
import argparse
from contextlib import ExitStack, contextmanager
import base64
import hashlib
import json
import ntpath
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.request import ProxyHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]


def isolated_windows_environment(environ, work):
    """A copied Windows environment is a case-sensitive dict; normalize its keys."""
    env = {key.upper(): value for key, value in environ.items()}
    for key in ('PYTHONHOME', 'PYTHONPATH', 'VIRTUAL_ENV', 'CONDA_PREFIX'):
        env.pop(key, None)
    system_root = env.get('SYSTEMROOT') or env.get('WINDIR')
    if not system_root or not ntpath.isabs(system_root):
        raise RuntimeError('Windows SystemRoot/WINDIR must identify the system directory for isolated EXE testing')
    env['SYSTEMROOT'] = system_root
    # Windows path syntax is deliberate, so this helper can be regression-tested
    # on other hosts without ever adding the maintainer's Python to child PATH.
    env['PATH'] = ';'.join((ntpath.join(system_root, 'System32'), system_root))
    env['VGA_STATE_DIR'] = str(work / 'state')
    env['LOCALAPPDATA'] = str(work / 'local-appdata')
    env['PYTHONUTF8'] = '1'
    return env


def terminate_tree(process):
    """Stop the onefile parent and its child; wait before removing their image."""
    if process.poll() is not None:
        process.wait(timeout=5)
        return
    if os.name == 'nt':
        try:
            result = subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                                    capture_output=True, timeout=20)
        except subprocess.TimeoutExpired as exc:
            process.kill()
            process.wait(timeout=10)
            raise RuntimeError('Windows process-tree shutdown command timed out') from exc
        if result.returncode != 0 and process.poll() is None:
            # Do not turn a failed tree shutdown into a passing smoke result.
            process.kill()
            process.wait(timeout=10)
            raise RuntimeError(f'Windows process-tree shutdown failed with code {result.returncode}')
    else:
        process.terminate()
    try:
        process.wait(timeout=20)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)
        raise RuntimeError('EXE process did not finish within the shutdown deadline')


def remove_smoke_directory(path, timeout=30):
    """Windows image/AV handles can outlive process exit briefly; retry boundedly."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            shutil.rmtree(path)
            return
        except FileNotFoundError:
            if not path.exists():
                return
        except OSError:
            if time.monotonic() >= deadline:
                raise
        if time.monotonic() >= deadline:
            raise RuntimeError('Temporary EXE directory could not be removed before cleanup deadline')
        time.sleep(0.25)


@contextmanager
def smoke_workspace():
    path = Path(tempfile.mkdtemp(prefix='vga-exe-smoke-'))
    try:
        yield path
    finally:
        remove_smoke_directory(path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--exe', type=Path, required=True)
    parser.add_argument('--browser', action='store_true')
    parser.add_argument('--report-dir', type=Path, default=ROOT / 'reports')
    args = parser.parse_args()
    original = args.exe.resolve()
    if os.name != 'nt' or original.suffix.lower() != '.exe':
        raise SystemExit('This smoke test requires the actual Windows .exe on Windows.')
    reports = args.report_dir.resolve()
    reports.mkdir(parents=True, exist_ok=True)
    checks = []
    report = {'status': 'failed', 'platform': platform.platform(), 'executable_sha256': hashlib.sha256(original.read_bytes()).hexdigest(),
              'checks': checks, 'limitations': ['Not a Windows 10/11 clean VM test', 'No real game, Vanguard, live capture or genuine screenshot accuracy test',
                                                 'PATH isolation does not remove every preinstalled system DLL']}
    process = None
    try:
        with smoke_workspace() as work, ExitStack() as cleanup:
            executable = work / 'VGA-Aram-Helper.exe'
            shutil.copyfile(original, executable)
            env = isolated_windows_environment(os.environ, work)
            # The only program in the working directory is the complete EXE.
            output = subprocess.run([str(executable), '--version'], env=env, cwd=work,
                                    capture_output=True, text=True, encoding='utf-8', timeout=90, check=True)
            assert output.stdout.strip(), 'Missing app version'
            checks.append('Standalone version command without Python/site-packages on PATH')
            self_report = work / 'self-test.json'
            output = subprocess.run([str(executable), '--self-test', '--report', str(self_report)], env=env, cwd=work,
                                    capture_output=True, text=True, encoding='utf-8', timeout=180, check=True)
            (reports / 'windows-exe-self-test.log').write_text(output.stdout + output.stderr, encoding='utf-8')
            self_test = json.loads(self_report.read_text(encoding='utf-8'))
            assert self_test['status'] == 'passed' and self_test['frozen'] is True, self_test
            assert self_test['recognized'] == ['珠光护手', '炼狱导管', '双刀流']
            assert self_test['blank_candidates'] == 0 and len(self_test['bundled_models']) == 3
            shutil.copyfile(self_report, reports / 'windows-exe-self-test.json')
            checks.append('Actual bundled ONNX inference: Chinese fixture 3/3; blank fixture 0; all model SHA256 match')
            licenses = subprocess.run([str(executable), '--licenses'], env=env, cwd=work,
                                      capture_output=True, text=True, encoding='utf-8', timeout=90, check=True)
            assert 'Apache' in licenses.stdout and 'PYTHON-LICENSE' in licenses.stdout
            checks.append('Embedded third-party license texts readable from EXE')
            ready = work / 'ready.json'
            with (reports / 'windows-exe-server.log').open('w', encoding='utf-8') as log:
                process = subprocess.Popen([str(executable), '--demo', '--no-updates', '--no-browser', '--port', '0', '--ready-file', str(ready)],
                                           cwd=work, env=env, stdout=log, stderr=subprocess.STDOUT)
                cleanup.callback(terminate_tree, process)
                deadline = time.monotonic() + 90
                while not ready.exists():
                    assert process.poll() is None, f'EXE exited before HTTP readiness (code {process.returncode})'
                    if time.monotonic() > deadline:
                        raise TimeoutError('EXE did not become ready within 90 seconds')
                    time.sleep(0.25)
                info = json.loads(ready.read_text(encoding='utf-8'))
                assert info['frozen'] is True
                url = info['url']
                opener = build_opener(ProxyHandler({}))
                def fetch(path, payload=None):
                    request = Request(url + path, None if payload is None else json.dumps(payload).encode(),
                                      headers={} if payload is None else {'Content-Type': 'application/json', 'Origin': url})
                    with opener.open(request, timeout=90) as response:
                        return response.status, response.read(), dict(response.headers)
                status, raw, _ = fetch('/health')
                health = json.loads(raw)
                assert status == 200 and health['status'] == 'ok' and health['ocr_enabled'] is True
                status, html, headers = fetch('/')
                assert status == 200 and 'VGA' in html.decode('utf-8')
                assert 'Content-Security-Policy' in headers
                status, raw, _ = fetch('/api/data')
                data = json.loads(raw)
                assert data['metadata']['isDemo'] is True and len(data['augments']) >= 3
                checks.append('Frozen HTTP server: readiness, loopback UI/assets, CSP and synthetic data')
                payload = {'image_base64': base64.b64encode((ROOT / 'fixtures' / 'ocr-app-demo.png').read_bytes()).decode()}
                status, raw, _ = fetch('/api/ocr', payload)
                ocr = json.loads(raw)
                assert status == 200 and ocr['network_transmission'] is False
                assert [item['name'] for item in ocr['candidates']] == ['星火共鸣（演示）', '晶盾回路（演示）', '风步微光（演示）'], ocr
                checks.append('Frozen HTTP OCR API recognizes original demo fixture with bundled models')
                offered = ['星火共鸣（演示）', '晶盾回路（演示）', '风步微光（演示）']
                for hero, preferred in [('星火术士（演示）', offered[0]), ('磐石守卫（演示）', offered[1])]:
                    status, raw, _ = fetch('/api/compare', {'hero': hero, 'offered': offered})
                    comparison = json.loads(raw)
                    assert status == 200 and comparison['recommendedName'] == preferred, comparison
                    assert comparison['hero'] == hero and comparison['offered'] == offered
                    assert len(comparison['cards']) == 3
                checks.append('Frozen comparison API: same three slots produce different hero-specific priorities')
                if args.browser:
                    from playwright.sync_api import sync_playwright, expect
                    with sync_playwright() as playwright:
                        browser = playwright.chromium.launch(headless=True)
                        page = browser.new_page(viewport={'width': 1440, 'height': 1000})
                        errors = []
                        page.on('pageerror', lambda error: errors.append(str(error)))
                        page.goto(url)
                        expect(page.locator('#source-banner')).to_contain_text('演示')
                        expect(page.locator('#choice-title')).to_be_visible()
                        page.locator('#hero-search').fill('星火术士')
                        page.locator('.hero-row').first.click()
                        for index, name in enumerate(offered):
                            page.locator(f'#choice-{index}').fill(name)
                        expect(page.locator('#compare-choices')).to_be_enabled()
                        page.locator('#compare-choices').click()
                        expect(page.locator('.comparison-card.preferred')).to_contain_text(offered[0])
                        page.locator('#hero-search').fill('磐石守卫')
                        page.locator('.hero-row').first.click()
                        expect(page.locator('#choice-result')).to_be_empty()
                        page.locator('#compare-choices').click()
                        expect(page.locator('.comparison-card.preferred')).to_contain_text(offered[1])
                        page.screenshot(path=str(reports / 'windows-exe-ui.png'), full_page=True)
                        page.locator('#clear-choices').click()
                        expect(page.locator('#choice-result')).to_be_empty()
                        expect(page.locator('#compare-choices')).to_be_disabled()
                        assert not errors, errors
                        browser.close()
                    checks.append('Actual EXE Chromium UI: hero + 3 slots, switch hero, recompute, clear round; screenshot saved')
                else:
                    report['limitations'].append('Optional Chromium screenshot not requested')
                report['health'] = health
        # Passing means functional checks AND process/directory cleanup completed.
        report['status'] = 'passed'
    except Exception as exc:
        report['error'] = repr(exc)
        raise
    finally:
        (reports / 'windows-exe-smoke.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()

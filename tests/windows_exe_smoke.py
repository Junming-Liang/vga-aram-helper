"""Execute the built EXE from an empty folder, without Python in its PATH."""
from __future__ import annotations
import argparse
from contextlib import ExitStack, contextmanager
import base64
import hashlib
import io
import json
import ntpath
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.request import ProxyHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
from windows_session_fixture import poll_owned_json



DEMO_OFFERED = ('星火共鸣（演示）', '晶盾回路（演示）', '风步微光（演示）')
DEMO_HERO_GRADES = {'星火术士（演示）': ('T1', 'T2', 'T3'),
                    '磐石守卫（演示）': ('T3', 'T1', 'T2')}
FORBIDDEN_PUBLIC_FIELDS = frozenset(('recommendedName', 'recommended', 'preferred',
    'recommendationRank', 'rank', 'score', 'winRate', 'pairWinRate', 'globalWinRate',
    'pickRate', 'numGames', 'sampleSize', 'officialRank', 'sourceRank',
    'recommendedIndex', 'officialStats'))


def assert_grade_only_comparison(comparison, hero, offered, expected_grades):
    """Validate actual EXE JSON, independently of the product projection code."""
    def inspect(value):
        if isinstance(value, dict):
            assert not FORBIDDEN_PUBLIC_FIELDS.intersection(value), value
            for child in value.values(): inspect(child)
        elif isinstance(value, list):
            for child in value: inspect(child)
    inspect(comparison)
    assert comparison['policy'] == 'literal-source-grades-v1', comparison
    assert comparison['hero'] == hero and comparison['offered'] == list(offered), comparison
    cards = comparison['cards']
    assert len(cards) == 3, comparison
    assert [card['slot'] for card in cards] == [1, 2, 3], comparison
    assert [card['name'] for card in cards] == list(offered), comparison
    assert [card['sourceTier'] for card in cards] == list(expected_grades), comparison


def assert_grade_only_browser(page, expect, offered, expected_grades):
    """Inspect all three rendered cards without permitting a unique-best card."""
    fixture = json.loads((ROOT / 'fixtures' / 'demo.json').read_text(encoding='utf-8'))
    descriptions = [fixture['augments'][name]['description'] for name in offered]
    cards = page.locator('.comparison-card')
    expect(cards).to_have_count(3)
    expect(page.locator('.comparison-card.preferred')).to_have_count(0)
    for index, (name, grade) in enumerate(zip(offered, expected_grades)):
        card = cards.nth(index)
        expect(card.locator('h3')).to_have_text(name)
        expect(card.locator('.card-top .badge')).to_have_text(f'原选项 {index + 1}')
        expect(card.locator(':scope > .badge')).to_have_text(f'源评级 {grade}')
        expect(card.locator(':scope > p')).to_have_text(descriptions[index])
    text = page.locator('#choice-result').inner_text()
    # Source effect descriptions may mention rates without displaying any rate.
    # Validate them exactly above, then exclude only those trusted fixture texts.
    for description in descriptions:
        text = text.replace(description, '', 1)
    assert not any(word in text for word in ('胜率', '选取率', '样本量', '优先选择', '唯一推荐', '源顺位', '推荐首选')), text
    # These original synthetic descriptions contain no effect percentages.
    assert not re.search(r'\d+(?:[.,]\d+)?\s*[%％]', text), text


def supported_image_payloads(path):
    """Encode the same owned fixture for every supported screenshot decoder."""
    from PIL import Image
    yield 'PNG', Path(path).read_bytes()
    with Image.open(path) as source:
        image = source.convert('RGB')
        for kind, options in (('JPEG', {'quality': 100, 'subsampling': 0}),
                              ('WEBP', {'lossless': True}), ('BMP', {})):
            output = io.BytesIO()
            image.save(output, format=kind, **options)
            yield kind, output.getvalue()


def icc_image_payloads(path):
    """ICC metadata must remain harmless without the unused Pillow CMS extension.

    ImageCms is used only by this external fixture generator, never by the EXE.
    """
    from PIL import Image, ImageCms
    profile = ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()
    with Image.open(path) as source:
        image = source.convert('RGB')
        for kind, options in (('PNG', {}), ('JPEG', {'quality': 100, 'subsampling': 0}),
                              ('WEBP', {'lossless': True})):
            output = io.BytesIO()
            image.save(output, format=kind, icc_profile=profile, **options)
            with Image.open(io.BytesIO(output.getvalue())) as encoded:
                if encoded.info.get('icc_profile') != profile:
                    raise RuntimeError('ICC screenshot fixture did not retain its profile')
            yield kind, output.getvalue()


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
            version_file = work / 'version.json'
            output = subprocess.run([str(executable), '--version-file', str(version_file)], env=env, cwd=work,
                                    capture_output=True, text=True, encoding='utf-8', timeout=90, check=True)
            version_info = json.loads(version_file.read_text(encoding='utf-8'))
            assert version_info['applicationVersion'] and version_info['frozen'] is True, 'Missing frozen app version'
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
            licenses_file = work / 'licenses.txt'
            licenses = subprocess.run([str(executable), '--licenses-file', str(licenses_file)], env=env, cwd=work,
                                      capture_output=True, text=True, encoding='utf-8', timeout=90, check=True)
            license_text = licenses_file.read_text(encoding='utf-8')
            assert 'Apache' in license_text and 'PYTHON-LICENSE' in license_text
            checks.append('Embedded third-party license texts readable from EXE')
            ready = work / 'ready.json'
            with (reports / 'windows-exe-server.log').open('w', encoding='utf-8') as log:
                process = subprocess.Popen([str(executable), '--demo', '--no-updates', '--no-browser', '--port', '0', '--ready-file', str(ready)],
                                           cwd=work, env=env, stdout=log, stderr=subprocess.STDOUT)
                cleanup.callback(terminate_tree, process)
                deadline = time.monotonic() + 90
                info = None
                while info is None:
                    assert process.poll() is None, f'EXE exited before HTTP readiness (code {process.returncode})'
                    if time.monotonic() > deadline:
                        raise TimeoutError('EXE did not become ready within 90 seconds')
                    info = poll_owned_json(ready, lambda path: json.loads(path.read_text(encoding='utf-8')))
                    if info is None:
                        time.sleep(0.25)
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
                format_results = {}
                for kind, image in supported_image_payloads(ROOT / 'fixtures' / 'ocr-app-demo.png'):
                    status, raw, _ = fetch('/api/ocr', {'image_base64': base64.b64encode(image).decode()})
                    result = json.loads(raw)
                    actual = [item['name'] for item in result['candidates']]
                    assert status == 200 and actual == ['星火共鸣（演示）', '晶盾回路（演示）', '风步微光（演示）'], (kind, result)
                    assert result['network_transmission'] is False
                    format_results[kind] = actual
                report['supported_image_formats'] = format_results
                checks.append('Actual EXE OCR decodes PNG, JPEG, WebP and BMP; each fixture matches 3/3')
                icc_results = {}
                for kind, image in icc_image_payloads(ROOT / 'fixtures' / 'ocr-app-demo.png'):
                    status, raw, _ = fetch('/api/ocr', {'image_base64': base64.b64encode(image).decode()})
                    result = json.loads(raw)
                    actual = [item['name'] for item in result['candidates']]
                    assert status == 200 and actual == ['星火共鸣（演示）', '晶盾回路（演示）', '风步微光（演示）'], (kind, result)
                    assert result['network_transmission'] is False
                    icc_results[kind] = actual
                report['icc_image_formats'] = icc_results
                checks.append('Actual EXE OCR preserves PNG/JPEG/WebP screenshots carrying ICC metadata')
                for path in ('/favicon.ico', '/brand.png'):
                    status, raw, _ = fetch(path)
                    assert status == 200 and len(raw) > 0, path
                offered = list(DEMO_OFFERED)
                for hero, grades in DEMO_HERO_GRADES.items():
                    status, raw, _ = fetch('/api/compare', {'hero': hero, 'offered': offered})
                    comparison = json.loads(raw)
                    assert status == 200, comparison
                    assert_grade_only_comparison(comparison, hero, offered, grades)
                checks.append('Frozen comparison API: exact hero-specific source grades in original slots, with no rates, rankings or unique recommendation')
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
                        assert_grade_only_browser(page, expect, offered, DEMO_HERO_GRADES['星火术士（演示）'])
                        page.locator('#hero-search').fill('磐石守卫')
                        page.locator('.hero-row').first.click()
                        expect(page.locator('#choice-result')).to_be_empty()
                        page.locator('#compare-choices').click()
                        assert_grade_only_browser(page, expect, offered, DEMO_HERO_GRADES['磐石守卫（演示）'])
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

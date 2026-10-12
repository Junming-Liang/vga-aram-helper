"""Optional real-browser localhost QA. No external assets, no automatic installs."""
import argparse
import json
import os
from pathlib import Path
import platform
import sys
import threading
from urllib.parse import urlsplit
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from engine import load_data
from server import make_server
from playwright.sync_api import sync_playwright,expect
parser=argparse.ArgumentParser();parser.add_argument('--browser-executable',default=os.environ.get('HEX_BROWSER_EXECUTABLE'));parser.add_argument('--screenshots',action='store_true');args=parser.parse_args()
checks=[]
def passed(name):checks.append(name);print('PASS',name,flush=True)
server=make_server(load_data(ROOT/'fixtures/demo.json'),0);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
try:
    with sync_playwright() as p:
        options={'headless':True}
        if args.browser_executable:options['executable_path']=args.browser_executable
        browser=p.chromium.launch(**options);context=browser.new_context(viewport={'width':1440,'height':1000});page=context.new_page();errors=[];external=[]
        page.on('pageerror',lambda e:errors.append(str(e)));page.on('request',lambda r:external.append(r.url) if urlsplit(r.url).hostname not in ['127.0.0.1','localhost'] else None)
        page.goto(f'http://127.0.0.1:{server.server_port}');expect(page.locator('#source-banner')).to_contain_text('演示模式');expect(page.locator('#choice-title')).to_be_visible();passed('Explicit synthetic warning and main three-choice panel render')
        page.locator('#hero-search').fill('小星');expect(page.locator('.hero-row')).to_have_count(1);page.locator('.hero-row').click();passed('Hero alias lookup and selection')
        names=['星火共鸣（演示）','晶盾回路（演示）','风步微光（演示）']
        for i,name in enumerate(names):page.locator(f'#choice-{i}').fill(name)
        page.locator('#compare-choices').click();expect(page.locator('.comparison-card')).to_have_count(3);expect(page.locator('.comparison-card.preferred')).to_contain_text(names[0]);expect(page.locator('#choice-result')).to_contain_text('虚构演示');passed('Confirmed hero plus three names renders synthetic source-ordered comparison')
        page.locator('#hero-search').fill('小石');page.locator('.hero-row').click();expect(page.locator('#choice-result')).to_be_empty();page.locator('#compare-choices').click();expect(page.locator('.comparison-card.preferred')).to_contain_text(names[1]);passed('Hero change clears old result and changes recommendation')
        page.locator('#choice-2').fill(names[0]);expect(page.locator('#compare-choices')).to_be_disabled();expect(page.locator('#choice-result')).to_be_empty();passed('Duplicate/manual edit blocks compare and clears result')
        page.locator('#clear-choices').click();expect(page.locator('#choice-0')).to_have_value('');passed('New round clears slots')
        page.locator('.reference-details>summary').click();expect(page.locator('.card')).to_have_count(3);page.locator('#rarity').select_option('gold');expect(page.locator('.card')).to_have_count(1);page.locator('#show-deleted').check();expect(page.locator('.card')).to_have_count(2);passed('Reference rarity/deleted filters remain usable')
        page.locator('#show-deleted').uncheck();page.locator('.card-title').first.click();expect(page.locator('dialog')).to_be_visible();page.locator('#close-detail').click();passed('Reference detail opens and closes')
        page.locator('#about').click();expect(page.locator('#detail-content')).to_contain_text('augmentRecommendations');page.locator('#close-detail').click();passed('Source policy visible')
        if args.screenshots:page.screenshot(path=str(ROOT/'reports/synthetic-desktop.png'),full_page=True)
        mobile=browser.new_context(viewport={'width':390,'height':844},is_mobile=True);mp=mobile.new_page();mp.goto(f'http://127.0.0.1:{server.server_port}');expect(mp.locator('#choice-title')).to_be_visible();assert mp.evaluate('document.documentElement.scrollWidth<=innerWidth');passed('390px mobile fits without horizontal overflow')
        if args.screenshots:mp.screenshot(path=str(ROOT/'reports/synthetic-mobile.png'),full_page=True)
        assert not errors,errors;assert not external,external;passed('No page errors or external asset requests');browser.close()
    report={'result':'passed','environment':platform.platform(),'checks':checks,'count':len(checks),'browser_rendering_passed':True,'notTested':['Windows unless run there','live official-data startup','OTA Windows replace/restart/rollback','live game capture or accuracy']}
except Exception as exc:
    report={'result':'failed_or_blocked','checks':checks,'count':len(checks),'environment':platform.platform(),'errorType':type(exc).__name__,'error':str(exc)[:4000],'browser_rendering_passed':False};raise
finally:
    (ROOT/'reports/browser-validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8');server.shutdown();server.server_close();thread.join()

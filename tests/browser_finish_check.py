"""No playoff checkbox; legacy playoff tournaments can export after final results."""
import os, sys, tempfile, threading, time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import app
from playwright.sync_api import sync_playwright
with tempfile.TemporaryDirectory() as tmp:
 app.DB=os.path.join(tmp,'test.sqlite3')
 server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
 threading.Thread(target=server.serve_forever,daemon=True).start()
 base=os.environ.get('TEBIKOSHKA_TEST_URL',f'http://127.0.0.1:{server.server_port}')
 try:
  with sync_playwright() as p:
   b=p.chromium.launch(executable_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',headless=True)
   page=b.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
   def state():return page.request.get(base+'/api/state').json()['tournament']
   def api(action,data=None):
    t=state();res=page.request.post(base+'/api/'+action,data={**(data or {}),'revision':t['revision'] if t else None});assert res.ok,res.text()
   def signup(prefix):
    page.goto(base);page.locator('#toggle').click();page.locator('[name=login]').fill(prefix+str(time.time_ns()));page.locator('[name=password]').fill('secret123');page.locator('#auth button').click();page.locator('#create').wait_for()
   signup('no-playoff-');page.locator('#create').click();page.locator('[name=name]').wait_for()
   assert page.locator('[name=playoff]').count()==0
   assert page.get_by_text('Плей-офф қарастырылған',exact=True).count()==0
   page.locator('[name=name]').fill('Жаңа турнир')
   with page.expect_request('**/api/settings') as request:page.get_by_role('button',name='Сақтау және тіркеуге өту',exact=True).click()
   page.locator('#teams-tab').wait_for();assert 'playoff' not in request.value.post_data_json
   api('logout');signup('legacy-playoff-')
   api('create');api('setup',dict(step=0,name='Бұрын белгіленген турнир',format='APF',playoff=True));api('setup',dict(step=1,count=1))
   for name in ['Фракция A','Фракция B']:api('team',dict(name=name,speaker1='Бірінші',speaker2='Екінші'))
   api('judge',dict(name='Төреші'));api('setup',dict(step=2));api('setup',dict(step=3,high='none'));api('setup',dict(step=4))
   # Reload a persisted tournament whose old checkbox was checked.
   assert state()['playoff'] is True and not state().get('playoff_done')
   page.reload();page.get_by_role('heading',name='Турнирді бастау',exact=True).wait_for();page.locator('#setup-next').click();page.locator('.room').wait_for()
   page.locator('.assign-judge').click();page.locator('[data-judge]').click();page.wait_for_function('!draftPending && !document.querySelector("dialog").open')
   page.locator('#confirm').click();page.locator('tr.clickable').click();page.locator('[name=winner]').select_option(index=1)
   for score in page.locator('#result input').all():score.fill('75')
   page.locator('#result button').first.click();page.wait_for_function('!document.querySelector("dialog").open')
   assert page.locator('#next').is_enabled();page.locator('#next').click();page.locator('#finish').wait_for()
   assert page.locator('#finish').is_enabled();assert page.locator('#playoff').count()==0
   assert state()['playoff'] is True and not state().get('playoff_done')
   page.reload();page.locator('#finish').wait_for();assert page.locator('#finish').is_enabled()
   page.locator('#finish').click();page.locator('#export [name=password]').fill('secret123')
   with page.expect_download() as download:page.locator('#export button').click()
   assert download.value.suggested_filename=='ratings.xlsx';assert page.locator('#final').is_enabled()
   assert not errors,errors
   print('PASS: checkbox absent; settings request omits playoff; legacy playoff=True resumes; final results saved; finish enabled without playoff confirmation; Excel download succeeds')
   b.close()
 finally:server.shutdown();server.server_close()

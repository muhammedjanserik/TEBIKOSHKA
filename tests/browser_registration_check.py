"""Isolated browser regression for settings and registration; uses a temporary DB."""
import os, sys, tempfile, threading, time, json
sys.path.insert(0,os.path.dirname(os.path.dirname(__file__)))
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
   page=b.new_page();errors=[];network=[];
   def capture(r):
    if '/api/' in r.url and r.request.method=='POST' and r.url.rsplit('/',1)[-1] in ['settings','setup_back','finish_registration','start']:
     network.append(dict(method=r.request.method,url=r.url,payload=r.request.post_data_json,status=r.status,response=r.json()))
   page.on('response',capture);errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
   page.goto(base);page.locator('#toggle').click()
   page.locator('[name=login]').fill('registration-'+str(time.time_ns()));page.locator('[name=password]').fill('secret123');page.locator('#auth button').click();page.locator('#create').click()
   page.locator('[name=name]').fill('Тест');page.locator('[name=format]').select_option('BPF')
   page.locator('[name=high]').select_option('previous');page.locator('[name=count]').fill('5')
   assert page.locator('[name=high_rounds]').count()==4
   page.locator('[name=high_rounds][value="5"]').check();page.locator('[name=count]').fill('2')
   assert page.locator('[name=high_rounds]').count()==1
   page.locator('[name=high_rounds]').check();page.locator('#setup-next').click()
   page.locator('#judges-tab').click();page.get_by_role('button',name='Төреші қосу',exact=True).click();page.locator('dialog input').fill('Алғашқы');page.locator('#judge button').click();page.wait_for_function('t.judges.length===1')
   def api(a,d):
    st=page.request.get(base+'/api/state').json()['tournament']
    r=page.request.post(base+'/api/'+a,data={**d,'revision':st['revision'] if st else None});assert r.ok,r.text()
   for i in range(47):api('team',dict(name=f'T{i}',speaker1='A',speaker2='B'))
   page.reload();page.locator('#teams-tab').click();assert page.locator('.teamlist>.card').count()==47
   page.locator('#judges-tab').click();assert page.locator('#setup-next').is_disabled()
   page.reload();assert page.locator('#judges-tab').get_attribute('aria-selected')=='true';assert 'Алғашқы' in page.locator('#registration-panel').inner_text()
   for i in range(10):api('judge',{'name':f'J{i}'})
   api('team',dict(name='T48',speaker1='A',speaker2='B'));page.reload()
   page.get_by_text('Тағы 1 төреші қажет',exact=True).wait_for();assert page.locator('#setup-next').is_disabled()
   page.get_by_role('button',name='Төреші қосу',exact=True).click();page.locator('dialog input').fill('J12');page.locator('#judge button').click();page.wait_for_function('t.judges.length===12')
   assert page.locator('#setup-next').is_enabled();page.locator('#setup-next').click();page.get_by_role('heading',name='Турнирді бастау',exact=True).wait_for()
   page.reload();assert page.locator('#setup-next').inner_text()=='Турнирді бастау'
   # Exercise both Back buttons as real UI requests, then save an empty High/Low selection.
   page.locator('#back').click();page.locator('#teams-tab').wait_for();page.locator('#back').click();page.locator('[name=count]').wait_for()
   page.locator('[name=high]').select_option('previous');page.locator('[name=high_rounds]').uncheck();page.locator('#setup-next').click();page.locator('#teams-tab').wait_for()
   assert page.request.get(base+'/api/state').json()['tournament']['high']=='none'
   page.locator('#setup-next').click();page.get_by_role('heading',name='Турнирді бастау',exact=True).wait_for();page.locator('#setup-next').click();page.locator('.room').first.wait_for()
   assert page.locator('.room').count()==12
   # Previously saved legacy setup: no setup_stage field, one bye, one room/judge.
   api('logout',{});page.reload();page.locator('#toggle').click()
   login='legacy-'+str(time.time_ns())
   page.locator('[name=login]').fill(login);page.locator('[name=password]').fill('secret123');page.locator('#auth button').click();page.locator('#create').wait_for()
   api('create',{});api('setup',dict(step=0,name='Saved legacy',format='APF',playoff=False));api('setup',dict(step=1,count=3))
   for i in range(3):api('team',dict(name=f'Legacy{i}',speaker1='A',speaker2='B'))
   api('judge',dict(name='Legacy judge'))
   saved=page.request.get(base+'/api/state').json()['tournament'];assert 'setup_stage' not in saved
   api('logout',{});page.reload();page.locator('[name=login]').fill(login);page.locator('[name=password]').fill('secret123');page.locator('#auth button').click();page.locator('#teams-tab').wait_for()
   page.locator('#teams-tab').click();assert page.locator('.teamlist>.card').count()==3
   page.locator('#judges-tab').click();assert 'Legacy judge' in page.locator('#registration-panel').inner_text();assert page.locator('#setup-next').is_disabled()
   page.locator('[name=allow_bye]').check();assert page.locator('#setup-next').is_enabled()
   page.locator('#setup-next').click();page.get_by_role('heading',name='Турнирді бастау',exact=True).wait_for();page.locator('#setup-next').click();page.locator('.room').first.wait_for()
   current=page.request.get(base+'/api/state').json()['tournament'];assert len(current['rounds'][0]['rooms'])==1 and current['rounds'][0]['bye'] is not None
   assert all(x['status']==200 for x in network),network
   assert {x['url'].rsplit('/',1)[-1] for x in network}>={'settings','setup_back','finish_registration','start'}
   message=page.evaluate("""async()=>{const version=state.setup_api_version;delete state.setup_api_version;try{await api('settings',{});return ''}catch(e){return e.message}finally{state.setup_api_version=version}}""")
   assert 'қайта іске қосып' in message
   out=os.path.join(os.path.dirname(os.path.dirname(__file__)),'artifacts','registration-network.json')
   with open(out,'w') as f:json.dump(network,f,ensure_ascii=False,indent=2)
   assert not errors,errors
   print('PASS: dynamic settings; judge first; 47 tabs; persistence; 48/11 shortage; 48/12 completion; both Back buttons; empty High/Low; first BPF draw; saved legacy APF resume/bye/draw')
   b.close()
 finally:server.shutdown();server.server_close()

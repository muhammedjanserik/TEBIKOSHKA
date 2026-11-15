"""Clash registration and draw warnings in real Chrome; isolated DB by default."""
import os, sys, tempfile, threading, time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import app
from playwright.sync_api import sync_playwright
with tempfile.TemporaryDirectory() as tmp:
 app.DB=os.path.join(tmp,'clash.sqlite3')
 server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
 threading.Thread(target=server.serve_forever,daemon=True).start()
 base=os.environ.get('TEBIKOSHKA_TEST_URL',f'http://127.0.0.1:{server.server_port}')
 try:
  with sync_playwright() as p:
   b=p.chromium.launch(executable_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',headless=True)
   page=b.new_page(viewport={'width':1440,'height':1000});errors=[]
   page.on('pageerror',lambda e:errors.append(str(e)))
   def state():return page.request.get(base+'/api/state').json()['tournament']
   def api(action,data=None):
    t=state();res=page.request.post(base+'/api/'+action,data={**(data or {}),'revision':t['revision'] if t else None});assert res.ok,res.text()
   def settled():page.wait_for_function('!draftPending');page.wait_for_timeout(100)
   def team_form(name,clashes):
    page.get_by_role('button',name='Фракция қосу',exact=True).click()
    for field,value in [('name',name),('speaker1','Бірінші'),('speaker2','Екінші'),('clashes',clashes)]:page.locator(f'#team [name={field}]').fill(value)
    assert not page.locator('#team [name=clashes]').get_attribute('required')
    assert page.locator('#clash-help').inner_text()=='Клэш бар төрешілердің аты-жөнін үтірмен бөліп жазыңыз'
    page.locator('#team button').click();page.wait_for_function('!document.querySelector("dialog").open')
    page.wait_for_function('(name)=>t.teams.some(x=>x.name===name)',arg=name)
   page.goto(base);page.locator('#toggle').click();page.locator('[name=login]').fill('clash-'+str(time.time_ns()));page.locator('[name=password]').fill('secret123');page.locator('#auth button').click();page.locator('#create').click()
   page.locator('[name=name]').fill('Клэш сынағы');page.locator('#setup-next').click();page.locator('#teams-tab').wait_for()
   team_form('Революция','аБАй    сӘрСеН, Басқа төреші')
   team_form('Екінші фракция','Абай Сәрсен')
   team_form('Клэшсіз','')
   api('team',dict(name='Бұрынғы фракция',speaker1='A',speaker2='B'))
   # Legacy records with no field must open as empty (only in our temporary test DB).
   if not os.environ.get('TEBIKOSHKA_TEST_URL'):
    t=state();t['teams'][-1].pop('clashes')
    with app.connect() as c:c.execute('UPDATE tournaments SET data=?',(app.json.dumps(t),))
   page.reload();page.locator('#teams-tab').click();page.locator('.teamlist>.card').filter(has_text='Бұрынғы фракция').get_by_role('button',name='Өңдеу',exact=True).click()
   assert page.locator('#team [name=clashes]').input_value()=='';page.locator('dialog > button').click()
   page.locator('.teamlist>.card').filter(has_text='Революция').get_by_role('button',name='Өңдеу',exact=True).click()
   assert page.locator('#team [name=clashes]').input_value()=='аБАй    сӘрСеН, Басқа төреші'
   page.locator('#team [name=clashes]').fill('  аБАй    сӘрСеН, Басқа төреші  ');page.locator('#team button').click();page.wait_for_function('!document.querySelector("dialog").open')
   page.locator('#judges-tab').click()
   for name in ['Абай Сәрсен','Абай Сәрсенов']:
    page.get_by_role('button',name='Төреші қосу',exact=True).click();page.locator('#judge input').fill(name);page.locator('#judge button').click();page.wait_for_function('!document.querySelector("dialog").open');page.wait_for_function('(name)=>t.judges.some(j=>j.name===name)',arg=name)
   page.locator('#setup-next').click();page.get_by_role('heading',name='Турнирді бастау',exact=True).wait_for();page.locator('#setup-next').click();page.locator('.room').first.wait_for()
   t=state();ids={x['name']:x['id'] for x in t['teams']};jids={x['name']:x['id'] for x in t['judges']}
   rooms=t['rounds'][0]['rooms'];rooms[0]['teams']=[ids['Революция'],ids['Екінші фракция']];rooms[1]['teams']=[ids['Клэшсіз'],ids['Бұрынғы фракция']]
   api('draft',dict(number=1,rooms=rooms));page.reload();page.locator('.room').first.wait_for();assert page.locator('.clash-badge').count()==0
   # Same prefix is not a full-name match.
   page.locator('[data-room="0"] .assign-judge').click();page.locator(f'[data-judge="{jids["Абай Сәрсенов"]}"]').click();settled();assert page.locator('.clash-badge').count()==0
   page.locator('[data-room="0"]').get_by_role('button',name='Босату',exact=True).click();settled()
   # Actual HTML drag; assert warnings already exist before the draft request completes.
   expected=[3]
   def draft_request(route):
    assert page.locator('.clash-badge').count()==expected[0]
    route.continue_()
   page.route('**/api/draft',draft_request)
   source=page.locator('.free-judges .card').filter(has_text='Абай Сәрсен').filter(has_not_text='Абай Сәрсенов')
   source.drag_to(page.locator('[data-room="0"]'));settled()
   assert page.locator('[data-clash-team] .clash-badge').count()==2
   badge=page.locator('[data-clash-judge] .clash-badge');assert 'Клэш · Абай Сәрсен — Революция' in badge.get_attribute('title');assert 'Екінші фракция' in badge.get_attribute('title')
   badge.click();assert 'Клэш · Абай Сәрсен — Революция' in page.locator('dialog').inner_text();page.locator('dialog > button').click()
   # Move one clashing team to a room without that judge: both affected rooms update immediately.
   expected[0]=2
   page.locator('.room').nth(0).locator('.slot .card').first.drag_to(page.locator('.room').nth(1).locator('.slot').first);settled()
   assert page.locator('.room').nth(1).locator('.clash-badge').count()==0
   expected[0]=3
   page.locator('.room').nth(1).locator('.slot .card').first.drag_to(page.locator('.room').nth(0).locator('.slot').first);settled()
   expected[0]=0;page.locator('[data-room="0"]').get_by_role('button',name='Босату',exact=True).click();settled();assert page.locator('.clash-badge').count()==0
   expected[0]=3;page.locator('[data-room="0"] .assign-judge').click();page.locator(f'[data-judge="{jids["Абай Сәрсен"]}"]').click();settled();assert page.locator('.clash-badge').count()==3
   page.reload();page.locator('.room').first.wait_for();assert page.locator('.clash-badge').count()==3
   page.locator('[data-room="1"] .assign-judge').click();page.locator(f'[data-judge="{jids["Абай Сәрсенов"]}"]').click();settled()
   out=Path(__file__).resolve().parents[1]/'artifacts';out.mkdir(exist_ok=True)
   page.screenshot(path=str(out/'clash-draw.png'),full_page=True)
   page.locator('#confirm').click();page.locator('tr.clickable').first.wait_for();assert page.locator('.clash-badge').count()==0
   page.locator('tr.clickable').first.click();assert page.locator('.clash-badge').count()==0
   page.screenshot(path=str(out/'clash-results.png'),full_page=True)
   assert not errors,errors
   print('PASS: optional/legacy fields; save/edit/reload before judge; normalized full names; two clashing teams; real drag/picker; immediate warnings; swap/release; persisted warnings; confirm with clash; no warnings in results')
   b.close()
 finally:server.shutdown();server.server_close()

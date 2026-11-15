"""Run against a separate test server, never the production database:
TAB_DB=/private/tmp/tebikoshka-emojis.sqlite3 PORT=8019 python3 app.py
Requires Playwright and installed Google Chrome.
python tests/browser_emojis_check.py
"""
import os,time
from pathlib import Path
from playwright.sync_api import sync_playwright
BASE=os.environ.get('TEBIKOSHKA_TEST_URL','http://127.0.0.1:8019')
OUT=Path(__file__).resolve().parents[1]/'artifacts'
OUT.mkdir(exist_ok=True)
with sync_playwright() as p:
 browser=p.chromium.launch(executable_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',headless=True)
 errors=[]
 for fmt,n in [('APF',3),('APF',4),('BPF',4)]:
  context=browser.new_context(viewport={'width':1366,'height':900});page=context.new_page()
  page.on('pageerror',lambda e:errors.append(str(e)))
  page.goto(BASE);page.locator('#toggle').click()
  login=f'emoji-{fmt}-{time.time_ns()}'
  page.locator('[name=login]').fill(login);page.locator('[name=password]').fill('secret123');page.locator('#auth button').click();page.locator('#create').wait_for()
  def state():return page.request.get(BASE+'/api/state').json()
  def api(action,data=None):
   t=state()['tournament'];response=page.request.post(BASE+'/api/'+action,data={**(data or {}),'revision':t['revision'] if t else None})
   assert response.ok,(action,response.text());return response.json()
  api('create');api('setup',{'step':0,'name':f'{fmt} белгі сынағы','format':fmt,'playoff':False});api('setup',{'step':1,'count':2})
  api('team',{'name':'САФ','club':'Ортақ клуб','speaker1':'Айсұлу','speaker2':'Әли'})
  page.reload();page.get_by_role('button',name='Фракция қосу',exact=True).click()
  page.locator('dialog [name=name]').fill('Революция');page.locator('[name=club]').focus()
  assert page.locator('[name=club]').get_attribute('autocomplete')=='off'
  assert page.locator('#team').get_attribute('autocomplete')=='off'
  assert page.locator('datalist,input[list]').count()==0
  assert page.get_by_role('listbox').count()==1
  assert page.get_by_role('option',name='Ортақ клуб',exact=True).count()==1
  page.screenshot(path=str(OUT/f'club-{fmt.lower()}-add.png'))
  page.get_by_role('option',name='Ортақ клуб',exact=True).click()
  page.locator('[name=speaker1]').fill('Аружан');page.locator('[name=speaker2]').fill('Данияр')
  page.get_by_role('button',name='Сақтау',exact=True).click();page.wait_for_function('t.teams.length===2')
  emoji=state()['tournament']['club_emojis']['Ортақ клуб']
  assert page.locator('.teamlist .card b').all_text_contents()==[f'{emoji} САФ',f'{emoji} Революция']
  api('team',{'name':'САФ','club':'Басқа клуб','speaker1':'А','speaker2':'Б'})
  if n==4:api('team',{'name':'Клубсыз','club':'','speaker1':'В','speaker2':'Г'})
  page.reload();page.locator('.teamlist .card').first.get_by_role('button',name='Өңдеу',exact=True).click()
  page.locator('[name=club]').click()
  assert page.get_by_role('listbox').count()==1
  assert page.get_by_role('option',name='Ортақ клуб',exact=True).count()==1
  assert page.locator('[name=club]').get_attribute('autocomplete')=='off'
  assert page.locator('datalist,input[list]').count()==0
  page.screenshot(path=str(OUT/f'club-{fmt.lower()}-edit.png'))
  page.locator('[name=club]').fill('Жаңа клуб атауы')
  assert page.locator('[name=club]').input_value()=='Жаңа клуб атауы'
  page.locator('[name=club]').fill('Ортақ');page.get_by_role('option',name='Ортақ клуб',exact=True).click()
  page.get_by_role('button',name='Сақтау',exact=True).click();page.wait_for_function('!document.querySelector("dialog").open')
  mapping=state()['tournament']['club_emojis'];assert len(set(mapping.values()))==2
  page.reload();assert state()['tournament']['club_emojis']==mapping
  # Re-login with a fresh page session, then verify the persisted assignment.
  api('logout');page.reload();page.locator('[name=login]').fill(login);page.locator('[name=password]').fill('secret123');page.locator('#auth button').click();page.locator('.teamlist').wait_for()
  assert state()['tournament']['club_emojis']==mapping
  api('setup',{'step':2,'allow_bye':True});api('setup',{'step':3,'high':'none'})
  for j in range(n//(2 if fmt=='APF' else 4)):api('judge',{'name':f'Сынақ төрешісі {j+1}'})
  api('setup',{'step':4});api('start')
  page.reload();page.locator('.room').first.wait_for()
  labels=page.locator('.room .card b').all_text_contents()
  for team in state()['tournament']['teams']:
   text=(mapping.get(team['club'],'')+' '+team['name']).strip()
   assert text in page.locator('main').inner_text()
  if n==4:assert 'Клубсыз' in labels
  def play_round():
   t=state()['tournament'];r=t['rounds'][-1]
   for ri,room in enumerate(r['rooms']):room['judges']=[t['judges'][ri]['id']]
   api('confirm',{'number':r['number'],'rooms':r['rooms']})
   for ri,room in enumerate(r['rooms']):
    values={str(id):{'rank':i+1,'scores':[24,24-i]} for i,id in enumerate(room['teams'])}
    api('result',{'number':r['number'],'room':str(ri),'values':values})
   if r['bye'] is not None:api('result',{'number':r['number'],'room':'bye','values':{str(r['bye']):{'rank':1,'scores':[24,25]}}})
   return r
  r=play_round();page.reload()
  def check_confirmed_names():
   page.get_by_role('heading',name='1-раунд · Нәтижелер',exact=True).wait_for()
   teams_by_id={x['id']:x for x in state()['tournament']['teams']}
   for ri,room in enumerate(r['rooms']):
    cells=page.locator('tr.clickable').nth(ri).locator('td')
    for pi,id in enumerate(room['teams']):
     x=teams_by_id[id];label=(mapping.get(x['club'],'')+' '+x['name']).strip()
     assert cells.nth(pi+1).inner_text()==label
   table=page.locator('table').inner_text()
   assert f'{emoji} САФ' in table and f'{emoji} Революция' in table
   assert all(not x['name'].startswith(emoji) for x in teams_by_id.values())
   assert state()['tournament']['club_emojis']==mapping
  check_confirmed_names();page.reload();check_confirmed_names()
  page.screenshot(path=str(OUT/f'confirmed-{fmt.lower()}-emojis.png'),full_page=True)
  page.get_by_role('button',name='Ағымдағы рейтинг',exact=True).click()
  def check_rankings(rounds):
   tables=page.locator('table');team_rows=tables.nth(0).locator('tbody tr');speaker_rows=tables.nth(1).locator('tbody tr')
   snapshot=state();ranked=snapshot['rankings'][0]
   for i,team in enumerate(ranked):
    prefix=mapping.get(team.get('club',''),'');label=(prefix+' '+team['name']).strip()
    assert team_rows.nth(i).locator('td').nth(1).inner_text()==label
    assert speaker_rows.filter(has_text=label).count()==2
    for round_i in range(2):
     cell=team_rows.nth(i).locator('td').nth(2+round_i)
     if round_i>=rounds:assert cell.inner_text()=='—';continue
     data=team['cells'][round_i];assert cell.locator('.round-score').inner_text()==str(data['score'])
     if fmt=='APF':
      name='Автожеңіс' if data['bye'] else 'Жеңіс' if data['rank']==1 else 'Жеңіліс'
      circle=cell.get_by_role('img',name=name,exact=True);assert circle.get_attribute('title')==name
      assert circle.inner_text()==('✓' if data['rank']==1 else '×')
      color=circle.evaluate('(e)=>getComputedStyle(e).backgroundColor');assert color==('rgb(21, 128, 61)' if data['rank']==1 else 'rgb(220, 38, 38)')
     else:
      rank=data['rank'];assert cell.locator('.rank-line>span').inner_text()==str(rank)
      assert cell.locator('svg path').count()==(2 if rank in [1,4] else 1)
      assert cell.locator('svg').evaluate('(e)=>getComputedStyle(e).color')=={1:'rgb(21, 128, 61)',2:'rgb(37, 99, 235)',3:'rgb(202, 138, 4)',4:'rgb(220, 38, 38)'}[rank]
   assert snapshot['tournament']['club_emojis']==mapping
  check_rankings(1)
  page.screenshot(path=str(OUT/f'emoji-{fmt.lower()}-current.png'),full_page=True)
  api('next',{'number':1});page.reload();page.locator('.room').first.wait_for();assert state()['tournament']['club_emojis']==mapping
  play_round();api('next',{'number':2});page.reload();page.get_by_role('heading',name='Турнир нәтижелері',exact=True).wait_for()
  check_rankings(2)
  page.screenshot(path=str(OUT/f'emoji-{fmt.lower()}-final.png'),full_page=True)
  page.set_viewport_size({'width':390,'height':844});page.wait_for_timeout(150)
  assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
  page.screenshot(path=str(OUT/f'emoji-{fmt.lower()}-mobile.png'),full_page=True)
  print(f'PASS {fmt} ({n} teams): single club list in add/edit, confirmed result table by ID before/after refresh, duplicate names across clubs, emoji persistence, draw and both rankings, badges + scores, mobile overflow')
  context.close()
 assert not errors,errors
 print('PASS: no JavaScript errors')
 browser.close()

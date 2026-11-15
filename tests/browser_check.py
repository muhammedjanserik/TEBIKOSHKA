"""Chrome integration check using test accounts only.
Start a separate server first:
  TAB_DB=/private/tmp/tebikoshka-features.sqlite3 PORT=8018 python3 app.py
Requires Playwright and installed Google Chrome; run: python tests/browser_check.py.
Does not open the production database or use existing accounts.
"""
import time,json
from pathlib import Path
from playwright.sync_api import sync_playwright
out=Path(__file__).resolve().parents[1]/'artifacts';out.mkdir(exist_ok=True);base='http://127.0.0.1:8018'
with sync_playwright() as p:
 b=p.chromium.launch(executable_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',headless=True)
 errors=[]
 def new(fmt,n,tag):
  ctx=b.new_context(viewport={'width':1440,'height':900});page=ctx.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
  page.goto(base);page.locator('#auth').wait_for()
  assert page.locator('[name=login]').get_attribute('autocomplete')=='username'
  assert page.locator('[name=password]').get_attribute('autocomplete')=='current-password'
  page.locator('#toggle').click();assert page.locator('[name=password]').get_attribute('autocomplete')=='new-password'
  page.locator('[name=login]').fill(tag+str(time.time_ns()));page.locator('[name=password]').fill('secret123');page.locator('#auth button').click();page.locator('#create').wait_for()
  def api(a,d={}):
   st=page.request.get(base+'/api/state').json()['tournament'];res=page.request.post(base+'/api/'+a,data={**d,'revision':st['revision'] if st else None});assert res.ok,(a,res.text());return res.json()
  api('create');api('setup',{'step':0,'name':tag,'format':fmt,'playoff':False});api('setup',{'step':1,'count':1})
  for i in range(n):api('team',{'name':f'Фракция {i+1}','club':'Сынақ клубы','speaker1':f'Спикер {i+1} A','speaker2':f'Спикер {i+1} B'})
  page.reload();page.get_by_role('heading',name='Фракциялар',exact=True).wait_for()
  return ctx,page,api
 ctx,page,api=new('BPF',49,'БПФ сынақ ')
 # Named confirmation: cancellation preserves the team, confirmation removes it.
 messages=[]
 def cancel(d):messages.append(d.message);d.dismiss()
 page.once('dialog',cancel);page.get_by_role('button',name='Жою',exact=True).last.click();assert page.locator('.teamlist>.card').count()==49;assert page.get_by_role('button',name='Келесі қадам →',exact=True).is_disabled()
 assert 'Фракция 49' in messages[0]
 page.once('dialog',lambda d:d.accept());page.get_by_role('button',name='Жою',exact=True).last.click();page.wait_for_function('t.teams.length===48')
 assert page.locator('.teamlist>.card').count()==48;assert page.get_by_role('button',name='Келесі қадам →',exact=True).is_enabled()
 assert not page.locator('.warning').count()
 page.get_by_role('button',name='Фракция қосу',exact=True).click()
 club=page.locator('[name=club]');club.focus();assert club.get_attribute('aria-controls')=='club-options';assert page.locator('#club-options [role=option]').count()==1
 club.fill('Сынақ');club.press('ArrowDown');page.keyboard.press('Enter');assert club.input_value()=='Сынақ клубы'
 # Site suggestions are keyboard-accessible and exclusive to the club input.
 assert page.locator('.club-suggestions').count()==1
 for name in ['name','speaker1','speaker2']:assert page.locator(f'dialog [name={name}]').get_attribute('autocomplete')=='off'
 page.locator('dialog > button').click()
 page.get_by_role('button',name='Келесі қадам →',exact=True).click();page.get_by_role('heading',name='High/Low',exact=True).wait_for()
 api('setup',{'step':3,'high':'none'})
 for i in range(32):api('judge',{'name':f'Төреші {i+1}'})
 api('setup',{'step':4});api('start');page.reload();page.locator('.room').first.wait_for()
 assert page.locator('.room').count()==12
 page.get_by_role('button',name='Төреші қосу',exact=True).last.click();page.locator('dialog input').focus()
 assert page.locator('dialog input').get_attribute('autocomplete')=='off';assert page.locator('dialog input').get_attribute('list') is None
 page.locator('dialog > button').click()
 def wait_draft():page.wait_for_function('!draftPending');page.wait_for_timeout(80)
 # Real pointer drag; move several times to activate Chrome HTML drag events.
 def drag_to_room(ri):
  target=page.locator(f'[data-room="{ri}"]');target.scroll_into_view_if_needed()
  source=page.locator('.free-judges .card').first;source.scroll_into_view_if_needed()
  sb=source.bounding_box();tb=target.bounding_box()
  sx=sb['x']+sb['width']/2;sy=sb['y']+sb['height']/2
  tx=tb['x']+tb['width']/2;ty=tb['y']+min(tb['height']/2,70)
  page.mouse.move(sx,sy);page.mouse.down();page.mouse.move(sx-15,sy+3,steps=5);page.mouse.move(tx,ty,steps=15);page.mouse.move(tx+2,ty+2);page.mouse.up()
  page.wait_for_function(f't.rounds.at(-1).rooms[{ri}].judges.length===1');wait_draft()
 drag_to_room(0)
 page.locator('[data-room="11"]').scroll_into_view_if_needed()
 box=page.locator('.judges-sidebar').bounding_box();assert box['y']>=0 and box['y']+box['height']<=901,box
 assert page.locator('.free-judges').evaluate('(e)=>e.scrollHeight>e.clientHeight')
 drag_to_room(11)
 # Multiple judges, release and pick from both top and bottom rooms.
 for ri in [0,11]:
  page.locator(f'[data-room="{ri}"] .assign-judge').click();page.locator('[data-judge]').first.click();page.wait_for_function('!document.querySelector("dialog").open');wait_draft()
  assert page.locator(f'[data-room="{ri}"] .card').count()==2
  page.locator(f'[data-room="{ri}"] button').filter(has_text='Босату').first.click();wait_draft()
  assert page.locator(f'[data-room="{ri}"] .card').count()==1
 page.screenshot(path=str(out/'draw-bottom-desktop.png'),full_page=False)
 page.set_viewport_size({'width':390,'height':844});page.locator('[data-room="1"] .assign-judge').click();page.locator('[data-judge]').first.click();page.wait_for_function('!document.querySelector("dialog").open');wait_draft()
 assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
 page.screenshot(path=str(out/'draw-mobile.png'),full_page=False)
 st=page.request.get(base+'/api/state').json()['tournament'];r=st['rounds'][-1];used={j for room in r['rooms'] for j in room['judges']};free=[j['id'] for j in st['judges'] if j['id'] not in used]
 for room in r['rooms']:
  if not room['judges']:room['judges']=[free.pop()]
 api('confirm',{'number':1,'rooms':r['rooms']});page.reload();page.locator('tr.clickable').first.click()
 # Blank and bad score errors stay in the open modal.
 page.locator('#result button').first.click();assert page.locator('#result-error').inner_text();assert page.locator('dialog').evaluate('(e)=>e.open')
 selects=page.locator('#result select')
 for i in range(4):
  selects.nth(i).select_option(str(i+1))
  for j in range(4):
   if j!=i:assert selects.nth(j).locator(f'option[value="{i+1}"]').is_disabled()
 selects.nth(0).select_option('');assert not selects.nth(1).locator('option[value="1"]').is_disabled();selects.nth(0).select_option('1')
 scores=page.locator('#result input[type=number]')
 for i in range(8):scores.nth(i).fill('75')
 scores.first.fill('-1');page.locator('#result button').first.click();assert 'Балл' in page.locator('#result-error').inner_text();assert scores.first.input_value()=='-1'
 scores.first.fill('75')
 def invalid_server_score(route):
  payload=route.request.post_data_json;next(iter(payload['values'].values()))['scores'][0]=-1;route.continue_(post_data=json.dumps(payload))
 page.route('**/api/result',invalid_server_score)
 page.locator('#result button').first.click();page.get_by_text('Спикер балдарын санмен енгізіңіз',exact=True).wait_for();assert scores.first.input_value()=='75';assert page.locator('dialog').evaluate('(e)=>e.open')
 page.screenshot(path=str(out/'result-bpf-mobile-error.png'))
 page.unroute('**/api/result');page.set_viewport_size({'width':1366,'height':768});page.wait_for_timeout(300);page.screenshot(path=str(out/'result-bpf-desktop.png'))
 assert page.locator('#result button').first.is_visible();save_box=page.locator('#result button').first.bounding_box();assert 0<=save_box['y'] and save_box['y']+save_box['height']<=768
 page.locator('#result button').first.click();page.wait_for_function('!document.querySelector("dialog").open');page.locator('tr.clickable').first.click();assert selects.nth(3).input_value()=='4';assert scores.last.input_value()=='75'
 print('PASS BPF: 49→48 deletion/cancel; club-only suggestions and autocomplete; 12-room sticky sidebar; top/bottom HTML drag and picker; multiple judges/release; mobile picker; unique ranks/free rank; inline validation/server error; reopen persisted scores')
 ctx.close()
 ctx,page,api=new('APF',3,'АПФ сынақ ')
 api('setup',{'step':2,'allow_bye':True});api('setup',{'step':3,'high':'none'});api('judge',{'name':'АПФ төрешісі'});api('setup',{'step':4});api('start')
 st=page.request.get(base+'/api/state').json()['tournament'];r=st['rounds'][-1];r['rooms'][0]['judges']=[st['judges'][0]['id']];api('confirm',{'number':1,'rooms':r['rooms']})
 page.reload();page.locator('tr.clickable').first.click();assert page.locator('#result select').count()==1;assert page.locator('[name=winner] option').count()==3
 winner=str(r['rooms'][0]['teams'][1]);page.locator('[name=winner]').select_option(winner)
 for i in range(4):page.locator('#result input').nth(i).fill(str(70+i))
 page.locator('#result button').first.click();page.wait_for_function('!document.querySelector("dialog").open');page.locator('tr.clickable').first.click();assert page.locator('[name=winner]').input_value()==winner;assert page.locator('#result input').last.input_value()=='73'
 page.screenshot(path=str(out/'result-apf-desktop.png'));page.locator('#result button').last.click();page.locator('tr.clickable').last.click();assert page.locator('#result select').count()==0;assert page.locator('#result input').count()==2
 for inp in page.locator('#result input').all():inp.fill('77')
 page.locator('#result button').first.click();page.wait_for_function('!document.querySelector("dialog").open')
 saved=page.request.get(base+'/api/state').json()['tournament']['rounds'][-1]['results'];assert sorted(v['rank'] for v in saved['0'].values())==[1,2];assert saved['0'][winner]['rank']==1;assert len(saved['bye'])==1
 assert not errors,errors
 print('PASS APF: single winner maps to win/loss; independent scores; saved winner/scores reopen; bye two scores; no JavaScript errors')
 b.close()

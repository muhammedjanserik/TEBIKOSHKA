import unittest, tempfile, os, sys, threading, urllib.request, urllib.error, json, http.cookiejar, zipfile, io, base64
sys.path.insert(0,os.path.dirname(os.path.dirname(__file__)))
import app
class Flow(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(); app.DB=os.path.join(self.tmp.name,'db'); self.server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler); threading.Thread(target=self.server.serve_forever,daemon=True).start(); self.base='http://127.0.0.1:'+str(self.server.server_port); self.client=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
 def tearDown(self): self.server.shutdown(); self.server.server_close(); self.tmp.cleanup()
 def call(self,a,d=None,ok=True):
  if d is not None and a not in ['register','login']:
   state=self.call('state'); d=dict(d,revision=(state['tournament'] or {}).get('revision'))
  req=urllib.request.Request(self.base+'/api/'+a,data=json.dumps(d).encode() if d is not None else None,headers={'Content-Type':'application/json'})
  try: r=self.client.open(req); v=json.load(r); self.assertTrue(ok,v); return v
  except urllib.error.HTTPError as e:
   v=json.load(e); self.assertFalse(ok,v); return v
 def build(self,fmt,n,count=3):
  self.call('register',{'login':'user','password':'secret1'});self.call('create',{}); self.call('create',{},False)
  self.call('setup',{'step':0,'name':'Сынақ','format':fmt,'playoff':False});self.call('setup',{'step':1,'count':count})
  for i in range(n):self.call('team',dict(name=f'T{i}',club='Клуб',speaker1=f'A{i}',speaker2=f'B{i}'))
 def finish_setup(self):
  self.call('setup',{'step':2,'allow_bye':True}); self.call('setup',{'step':3,'high':'all'});self.call('setup',{'step':4},False)
  t=self.call('state')['tournament']
  for i in range(app.minimum(t)):self.call('judge',{'name':f'J{i}'})
  self.call('setup',{'step':4}); self.call('start',{})
 def play(self):
  t=self.call('state')['tournament']; r=t['rounds'][-1]; self.call('confirm',{'number':r['number'],'rooms':r['rooms']},False)
  for i,room in enumerate(r['rooms']):room['judges']=[t['judges'][i]['id']]
  self.call('confirm',{'number':r['number'],'rooms':r['rooms']});self.call('next',{'number':r['number']},False)
  for i,room in enumerate(r['rooms']):
   vals={str(id):{'rank':j+1,'scores':[75,75]} for j,id in enumerate(room['teams'])}
   invalid={k:dict(v,rank=1) for k,v in vals.items()};self.call('result',{'number':r['number'],'room':str(i),'values':invalid},False)
   self.call('result',{'number':r['number'],'room':str(i),'values':vals})
  if r['bye'] is not None:self.call('result',{'number':r['number'],'room':'bye','values':{str(r['bye']):{'rank':1,'scores':[75,75]}}})
  self.call('next',{'number':r['number']});self.call('next',{'number':r['number']},False)
 def export_finish(self):
  self.call('finish',{'password':'secret1','token':'fake'},False)
  original=app.export
  def fail(t):raise OSError('simulated export failure')
  app.export=fail
  try:self.call('export',{'password':'secret1'},False)
  finally:app.export=original
  self.assertIsNotNone(self.call('state')['tournament'])
  self.call('export',{'password':'wrong'},False); ex=self.call('export',{'password':'secret1'})
  with zipfile.ZipFile(io.BytesIO(base64.b64decode(ex['file']))) as z:
   self.assertIn('Фракциялар рейтингі',z.read('xl/workbook.xml').decode());self.assertIn('Спикерлер рейтингі',z.read('xl/workbook.xml').decode());self.assertEqual(z.testzip(),None)
  self.call('finish',{'password':'secret1','token':ex['token']});self.assertIsNone(self.call('state')['tournament']);self.call('create',{})
 def test_apf_full(self):
  self.build('APF',3);self.finish_setup()
  for i in range(3):self.play()
  t=self.call('state')['tournament'];self.assertEqual(len(set(r['bye'] for r in t['rounds'])),3);self.assertTrue(all(x['place']==1 for x in app.rankings(t)[1]));self.export_finish()
 def test_bpf_full(self):
  self.build('BPF',5,1);self.call('setup',{'step':2},False)
  for i in range(3):self.call('team',dict(name=f'Extra{i}',club='C',speaker1='A',speaker2='B'))
  self.finish_setup();self.call('delete_judge',{'id':self.call('state')['tournament']['judges'][0]['id']},False);self.play();self.export_finish()
 def test_isolation_persistence(self):
  self.build('APF',2,1); self.call('logout',{});self.call('register',{'login':'other','password':'secret2'});self.assertIsNone(self.call('state')['tournament']);self.call('logout',{});self.call('login',{'login':'user','password':'secret1'});self.assertEqual(len(self.call('state')['tournament']['teams']),2)
 def test_playoff_and_parallel_transition(self):
  self.build('APF',2,2); self.finish_setup(); self.play()
  t=self.call('state')['tournament']; r=t['rounds'][-1]
  for i,room in enumerate(r['rooms']):room['judges']=[t['judges'][i]['id']]
  self.call('confirm',{'number':2,'rooms':r['rooms']})
  vals={str(id):{'rank':j+1,'scores':[70,71]} for j,id in enumerate(r['rooms'][0]['teams'])}
  self.call('result',{'number':2,'room':'0','values':vals})
  t=self.call('state')['tournament']; revision=t['revision']; results=[]
  def advance():
   req=urllib.request.Request(self.base+'/api/next',data=json.dumps({'number':2,'revision':revision}).encode(),headers={'Content-Type':'application/json'})
   try:results.append(self.client.open(req).status)
   except urllib.error.HTTPError as e:results.append(e.code)
  workers=[threading.Thread(target=advance) for _ in range(2)]
  for w in workers:w.start()
  for w in workers:w.join()
  self.assertEqual(sorted(results),[200,400]);self.assertEqual(len(self.call('state')['tournament']['rounds']),2)
  self.call('playoff',{'done':True})
 def test_rankings_and_minimum(self):
  for fmt,expected in [('APF',32),('BPF',16)]:self.assertEqual(app.minimum({'format':fmt,'teams':list(range(64))}),expected)
  t={'format':'BPF','teams':[{'id':i,'name':str(i),'speakers':['A','B']} for i in range(3)],'rounds':[{'results':{'0':{'0':{'rank':1,'scores':[70,70]},'1':{'rank':1,'scores':[71,71]},'2':{'rank':1,'scores':[71,71]}}}}]}
  teams,speakers=app.rankings(t);self.assertEqual([x['id'] for x in teams],[1,2,0]);self.assertEqual([x['place'] for x in teams],[1,1,3]);self.assertEqual([x['place'] for x in speakers],[1,1,1,1,5,5])
 def test_delete_team_and_ownership(self):
  self.build('BPF',49,1)
  original=self.call('state')['tournament']; target=original['teams'][-1]['id']
  self.call('setup',{'step':2},False)
  self.call('delete_team',{'id':-1},False)
  self.call('logout',{});self.call('register',{'login':'other','password':'secret2'});self.call('create',{})
  self.call('delete_team',{'id':target},False)
  self.call('logout',{});self.call('login',{'login':'user','password':'secret1'})
  self.assertEqual(len(self.call('state')['tournament']['teams']),49)
  self.call('delete_team',{'id':target});self.assertEqual(len(self.call('state')['tournament']['teams']),48)
  self.finish_setup();self.call('delete_team',{'id':original['teams'][0]['id']},False)
 def test_judge_uniqueness_and_bad_scores(self):
  self.build('APF',4,1);self.finish_setup()
  t=self.call('state')['tournament'];r=t['rounds'][-1]
  for room in r['rooms']:room['judges']=[t['judges'][0]['id']]
  self.call('draft',{'number':1,'rooms':r['rooms']},False)
  for i,room in enumerate(r['rooms']):room['judges']=[t['judges'][i]['id']]
  self.call('confirm',{'number':1,'rooms':r['rooms']})
  ids=r['rooms'][0]['teams'];values={str(id):{'rank':i+1,'scores':[70,71]} for i,id in enumerate(ids)}
  values[str(ids[0])]['scores']=[-1,71]
  self.call('result',{'number':1,'room':'0','values':values},False)
  self.assertEqual(self.call('state')['tournament']['rounds'][-1]['results'],{})
 def test_club_emojis_persist_and_follow_club(self):
  self.build('APF',2,2)
  first=self.call('state')['tournament'];mapping=first['club_emojis'].copy()
  self.assertEqual(set(mapping),{'Клуб'});self.assertIn(mapping['Клуб'],app.CLUB_EMOJIS)
  self.call('team',dict(name='Басқа',club='Басқа клуб',speaker1='C',speaker2='D'))
  self.call('team',dict(name='Клубсыз',club='',speaker1='E',speaker2='F'))
  current=self.call('state')['tournament'];self.assertEqual(len(current['club_emojis']),2)
  self.assertNotEqual(current['club_emojis']['Клуб'],current['club_emojis']['Басқа клуб'])
  mapping=current['club_emojis'].copy()
  self.call('logout',{});self.call('login',dict(login='user',password='secret1'))
  self.assertEqual(self.call('state')['tournament']['club_emojis'],mapping)
  self.finish_setup();self.play()
  self.assertEqual(self.call('state')['tournament']['club_emojis'],mapping)
 def test_legacy_club_migration_is_saved_once(self):
  self.build('APF',2,1);old=self.call('state')['tournament'];old.pop('club_emojis')
  old['teams'][1].pop('club')
  with app.connect() as c:c.execute('UPDATE tournaments SET data=?',(json.dumps(old),))
  first=self.call('state')['tournament'];self.assertEqual(set(first['club_emojis']),{'Клуб'})
  self.assertEqual(first['revision'],old['revision']);self.assertEqual(first['teams'],old['teams'])
  with app.connect() as c:saved=json.loads(c.execute('SELECT data FROM tournaments').fetchone()[0])
  self.assertEqual(saved,first);self.assertEqual(self.call('state')['tournament'],first)
 def test_emoji_pool_and_rankings_export_unchanged(self):
  t={'teams':[{'id':i,'club':str(i),'name':str(i),'speakers':['A','B']} for i in range(len(app.CLUB_EMOJIS)+1)],'rounds':[],'format':'APF','count':1}
  before=app.rankings(t);before_export=app.export(t)
  self.assertTrue(app.ensure_club_emojis(t));self.assertEqual(len(set(list(t['club_emojis'].values())[:-1])),len(app.CLUB_EMOJIS))
  self.assertFalse(app.ensure_club_emojis(t));self.assertEqual(app.rankings(t),before)
  with zipfile.ZipFile(io.BytesIO(before_export)) as old,zipfile.ZipFile(io.BytesIO(app.export(t))) as new:
   for name in old.namelist():self.assertEqual(old.read(name),new.read(name))
 def test_settings_empty_high_and_api_version(self):
  self.call('register',{'login':'user','password':'secret1'});self.call('create',{})
  self.assertEqual(self.call('state')['setup_api_version'],app.SETUP_API_VERSION)
  for mode in [None,'','none','previous']:
   self.call('settings',dict(name='Тест',format='APF',count=3,high=mode,high_rounds=[]))
   self.assertEqual(self.call('state')['tournament']['high'],'none')
   self.call('setup_back',{})
   self.assertEqual(self.call('state')['tournament']['setup_stage'],'settings')
 def test_registration_workflow(self):
  self.call('register',{'login':'user','password':'secret1'});self.call('create',{})
  settings=dict(name='Жаңа турнир',format='BPF',count=5,high='previous',high_rounds=[2,5],playoff=True)
  self.call('settings',settings)
  self.call('judge',{'name':'Бірінші төреші'})
  for i in range(47):self.call('team',dict(name=f'T{i}',speaker1='A',speaker2='B'))
  self.call('finish_registration',{},False);self.call('start',{},False)
  for i in range(10):self.call('judge',{'name':f'J{i}'})
  self.call('team',dict(name='T48',speaker1='A',speaker2='B'))
  self.call('finish_registration',{},False)
  self.call('judge',{'name':'J12'});self.call('finish_registration',{})
  saved=self.call('state')['tournament'];self.assertTrue(saved['registration_complete']);self.assertEqual(saved['setup_stage'],'start')
  # Recheck persisted counts at start, even when completion was already saved.
  saved['judges'].pop()
  with app.connect() as c:c.execute('UPDATE tournaments SET data=?',(json.dumps(saved),))
  self.call('start',{},False)
  self.call('judge',{'name':'Replacement'});self.call('finish_registration',{});self.call('start',{})
  self.assertEqual(len(self.call('state')['tournament']['rounds'][0]['rooms']),12)
 def test_registration_apf_bye_and_legacy(self):
  self.build('APF',3,2)
  self.call('judge',{'name':'One'})
  self.call('finish_registration',{},False)
  self.call('finish_registration',{'allow_bye':True})
  self.call('start',{})
  r=self.call('state')['tournament']['rounds'][0]
  self.assertEqual(len(r['rooms']),1);self.assertIsNotNone(r['bye'])
 def test_legacy_playoff_does_not_block_finishing(self):
  self.build('APF',2,1)
  t=self.call('state')['tournament'];t.update(playoff=True,playoff_done=False)
  with app.connect() as c:c.execute('UPDATE tournaments SET data=?',(json.dumps(t),))
  self.finish_setup()
  self.call('export',dict(password='secret1'),False)
  self.play()
  saved=self.call('state')['tournament'];self.assertTrue(saved['playoff']);self.assertFalse(saved['playoff_done'])
  self.export_finish()
 def test_clashes_persist_before_judge_and_allow_confirmation(self):
  self.build('APF',2,1)
  t=self.call('state')['tournament'];first=t['teams'][0];second=t['teams'][1]
  data=dict(id=first['id'],name=first['name'],speaker1='A',speaker2='B',clashes='  абай   СӘРСЕН, Басқа төреші  ')
  self.call('team',data)
  self.call('logout',{});self.call('login',dict(login='user',password='secret1'))
  saved=self.call('state')['tournament']['teams'][-1]
  self.assertEqual(saved['clashes'],'абай   СӘРСЕН, Басқа төреші')
  # An older client editing another field must preserve the saved clashes.
  data.pop('clashes');self.call('team',data)
  self.assertEqual(self.call('state')['tournament']['teams'][-1]['clashes'],saved['clashes'])
  self.call('judge',dict(name='Абай Сәрсен'))
  self.call('setup',dict(step=2));self.call('setup',dict(step=3,high='none'));self.call('setup',dict(step=4));self.call('start',{})
  t=self.call('state')['tournament'];r=t['rounds'][0];r['rooms'][0]['judges']=[t['judges'][0]['id']]
  self.call('confirm',dict(number=1,rooms=r['rooms']))
  self.assertTrue(self.call('state')['tournament']['rounds'][0]['confirmed'])
 def test_positions(self):
  t={'format':'BPF','teams':[{'id':i} for i in range(16)],'rounds':[],'high':'none'}
  for _ in range(4):
   r=app.draw(t);r['confirmed']=True;t['rounds'].append(r)
  pos,_,_=app.history(t);self.assertTrue(all(v==[1,1,1,1] for v in pos.values()))
if __name__=='__main__':unittest.main()

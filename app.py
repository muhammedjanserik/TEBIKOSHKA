import os, json, sqlite3, secrets, hashlib, time, random, itertools, io, zipfile, math
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from http.cookies import SimpleCookie
from xml.sax.saxutils import escape

DB=os.environ.get('TAB_DB','tab.sqlite3')
SETUP_API_VERSION=3
POSITIONS={'APF':['Үкімет','Оппозиция'],'BPF':['Ашушы үкімет','Ашушы оппозиция','Жабушы үкімет','Жабушы оппозиция']}
CLUB_EMOJIS=('🐾','🐱','🦊','🐼','🐯','🦁','🐸','🐨','🐧','🦉','🦋','🐝','🐙','🐳','🦄','🐢','🦀','🦜','🐬','🦔','🌻','🌵','🍀','🍄','🌈','⭐','🔥','⚡','🌙','🍒','🍋','🍉','🥑','🎯','🎨','🎸','🚀','🧩','💎','🏆','🎈','🪁','🦚','🦩','🦦','🦥','🐿️','🦌','🐲','🌸','🌊','🪐','🍓','🥝','🍊','🎲','🎭','🎺','⛵','🏔️','🪷','🍍','🦕','🦈')
def ensure_club_emojis(t):
 """Assign once, retaining even unused clubs so later re-registration is stable."""
 changed='club_emojis' not in t
 mapping=t.setdefault('club_emojis',{})
 for team in t['teams']:
  club=(team.get('club') or '').strip()
  if club and not mapping.get(club):
   available=[emoji for emoji in CLUB_EMOJIS if emoji not in mapping.values()]
   mapping[club]=random.choice(available or CLUB_EMOJIS); changed=True
 return changed

def connect():
 from database import database_url
 url=database_url()
 if url:
  from database import PostgresConnection
  return PostgresConnection(url)
 if os.environ.get('VERCEL'):
  raise RuntimeError('Connect a PostgreSQL database in Vercel Storage and redeploy')
 c=sqlite3.connect(DB,timeout=30); c.row_factory=sqlite3.Row
 c.executescript('CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY,login TEXT UNIQUE,password TEXT); CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY,user INTEGER,expires REAL); CREATE TABLE IF NOT EXISTS tournaments(user INTEGER UNIQUE,data TEXT);')
 return c
def password(p,s=None):
 s=s or secrets.token_hex(16)
 return s+':'+hashlib.scrypt(p.encode(),salt=s.encode(),n=16384,r=8,p=1).hex()
def verify(p,h): return secrets.compare_digest(password(p,h.split(':')[0]),h)
def require(ok,msg):
 if not ok: raise ValueError(msg)
def minimum(t): return len(t['teams'])//len(POSITIONS[t['format']])
def history(t):
 pos={x['id']:[0]*len(POSITIONS[t['format']]) for x in t['teams']}; pairs={}; byes={x['id']:0 for x in t['teams']}
 for r in t['rounds']:
  if not r['confirmed']: continue
  if r['bye'] is not None: byes[r['bye']]+=1
  for room in r['rooms']:
   for i,a in enumerate(room['teams']): pos[a][i]+=1
   for a,b in itertools.combinations(sorted(room['teams']),2): pairs[a,b]=pairs.get((a,b),0)+1
 return pos,pairs,byes
def rankings(t):
 teams=[]; speakers=[]
 for team in t['teams']:
  cells=[]; scores=[[],[]]; points=0
  for r in t['rounds']:
   result=next((v for v in r['results'].values() if str(team['id']) in v),None)
   v=result.get(str(team['id'])) if result else None
   if v:
    p=(1 if v['rank']==1 else 0) if t['format']=='APF' else 4-v['rank']; points+=p
    cells.append({'rank':v['rank'],'score':sum(v['scores']),'bye':r.get('bye')==team['id']})
    for i in range(2): scores[i].append(v['scores'][i])
   else:
    cells.append(None)
    for i in range(2): scores[i].append(None)
  total=sum(sum(s for s in row if s is not None) for row in scores)
  teams.append(dict(team,cells=cells,points=points,total=total))
  for i in range(2): speakers.append({'name':team['speakers'][i],'team':team['name'],'team_id':team['id'],'cells':scores[i],'total':sum(s for s in scores[i] if s is not None)})
 teams.sort(key=lambda x:(-x['points'],-x['total'])); speakers.sort(key=lambda x:-x['total'])
 for rows,keys in [(teams,['points','total']),(speakers,['total'])]:
  prev=None
  for i,x in enumerate(rows):
   val=tuple(x[k] for k in keys); x['place']=rows[i-1]['place'] if val==prev else i+1; prev=val
 return teams,speakers
def draw(t):
 n=len(t['rounds'])+1; size=len(POSITIONS[t['format']]); ids=[x['id'] for x in t['teams']]; pos,pairs,byes=history(t); bye=None
 if len(ids)%size:
  low=min(byes.values()); bye=random.choice([i for i in ids if byes[i]==low]); ids.remove(bye)
 ratings={i:0 for i in ids}
 if n>1 and (t['high']=='all' or (t['high']=='previous' and n in t['high_rounds'])):
  rounds=t['rounds'] if t['high']=='all' else t['rounds'][-1:]
  for r in rounds:
   for result in r['results'].values():
    for k,v in result.items():
     if int(k) in ratings: ratings[int(k)]+= (1 if v['rank']==1 else 0) if t['format']=='APF' else 4-v['rank']
 # Equal-score draws use a global minimum-cost position assignment. This
 # avoids trapping a team in a repeated position through random room grouping.
 buckets=None
 if len(set(ratings.values()))<=1 and ids:
  m=len(ids); capacities=m//size; slots=[p for p in range(size) for _ in range(capacities)]
  costs=[[pos[a][p]*100000+random.randrange(100) for p in slots] for a in ids]
  u=[0]*(m+1); v=[0]*(m+1); matched=[0]*(m+1); way=[0]*(m+1)
  for a in range(1,m+1):
   matched[0]=a; j0=0; dist=[float('inf')]*(m+1); used=[False]*(m+1)
   while True:
    used[j0]=True; i0=matched[j0]; delta=float('inf'); j1=0
    for j in range(1,m+1):
     if not used[j]:
      cur=costs[i0-1][j-1]-u[i0]-v[j]
      if cur<dist[j]: dist[j]=cur; way[j]=j0
      if dist[j]<delta: delta=dist[j]; j1=j
    for j in range(m+1):
     if used[j]: u[matched[j]]+=delta; v[j]-=delta
     else: dist[j]-=delta
    j0=j1
    if matched[j0]==0: break
   while True:
    j1=way[j0]; matched[j0]=matched[j1]; j0=j1
    if j0==0: break
  buckets=[[] for _ in range(size)]
  for j in range(1,m+1): buckets[slots[j-1]].append(ids[matched[j]-1])
 best=None
 for attempt in range(160):
  order=ids[:]; random.shuffle(order); order.sort(key=lambda i:-ratings[i]); rooms=[]; cost=0
  if buckets:
   for bucket in buckets: random.shuffle(bucket)
   order=[buckets[p][i] for i in range(len(buckets[0])) for p in range(size)]
  # Equal scores are shuffled; score distance remains the primary room criterion.
  for k in range(0,len(order),size):
   group=order[k:k+size]; perms=list(itertools.permutations(group)); random.shuffle(perms)
   group=tuple(group) if buckets else min(perms,key=lambda p:sum(pos[a][i] for i,a in enumerate(p)))
   cost+=sum(pos[a][i] for i,a in enumerate(group))*100000+sum(pairs.get(tuple(sorted((a,b))),0) for a,b in itertools.combinations(group,2))
   old=t['rounds'][-1]['rooms'] if t['rounds'] else []
   rooms.append({'cabinet':old[k//size]['cabinet'] if k//size<len(old) else str(k//size+1),'teams':list(group),'judges':[]})
  if best is None or cost<best[0]: best=(cost,rooms)
 return {'number':n,'rooms':best[1],'bye':bye,'confirmed':False,'results':{}}
def ready(t):
 require(len(t['teams'])>=2 if t['format']=='APF' else len(t['teams'])>=4,'Фракциялар жеткіліксіз')
 require(t['format']!='BPF' or len(t['teams'])%4==0,'БПФ: фракциялар саны төртке бөлінуі керек')
 require(t['format']!='APF' or len(t['teams'])%2==0 or t.get('allow_bye'),'Тақ құрам үшін автожеңісті растаңыз')
 require(len(t['judges'])>=minimum(t),'Төрешілер жеткіліксіз')
def complete(r): return set(r['results'])==({str(i) for i in range(len(r['rooms']))}|({'bye'} if r['bye'] is not None else set()))
def export(t):
 teams,speakers=rankings(t); rounds=t['count']
 sheets=[('Фракциялар рейтингі',[['Орын','Фракция']+[f'{i+1}-раунд: нәтиже / балл' for i in range(rounds)]+['Командалық ұпай','Спикерлік балл']]+[[x['place'],x['name']]+[f"{v['rank']} / {v['score']}" if v else '' for v in x['cells']]+[x['points'],x['total']] for x in teams]),('Спикерлер рейтингі',[['Орын','Аты-жөні','Фракция']+[f'{i+1}-раунд' for i in range(rounds)]+['Жалпы балл']]+[[x['place'],x['name'],x['team']]+x['cells']+[x['total']] for x in speakers])]
 out=io.BytesIO()
 with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
  z.writestr('[Content_Types].xml','<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'+''.join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' for i in (1,2))+'</Types>')
  z.writestr('_rels/.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
  z.writestr('xl/workbook.xml','<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'+''.join(f'<sheet name="{name}" sheetId="{i}" r:id="rId{i}"/>' for i,(name,_) in enumerate(sheets,1))+'</sheets></workbook>')
  z.writestr('xl/_rels/workbook.xml.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'+''.join(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>' for i in (1,2))+'</Relationships>')
  for i,(_,rows) in enumerate(sheets,1):
   xml=[]
   for row in rows:
    xml.append('<row>'+''.join(f'<c><v>{v}</v></c>' if isinstance(v,(int,float)) else '<c t="inlineStr"><is><t>'+escape(str(v or ''))+'</t></is></c>' for v in row)+'</row>')
   z.writestr(f'xl/worksheets/sheet{i}.xml','<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'+''.join(xml)+'</sheetData></worksheet>')
 return out.getvalue()

def mutate(t,action,d):
 if action=='settings':
  require(t['status']=='setup','Баптау аяқталған')
  require(str(d.get('name','')).strip() and d.get('format') in POSITIONS,'Атау мен форматты енгізіңіз')
  require(type(d.get('count'))==int and 1<=d['count']<=30,'Раунд саны: 1–30')
  high=d.get('high') or 'none'
  require(high in ['none','previous','all'],'High/Low режимі қате')
  selected=d.get('high_rounds',[])
  require(isinstance(selected,list) and all(type(n)==int and 2<=n<=d['count'] for n in selected),'Раунд таңдауы қате')
  t.update(name=d['name'].strip(),format=d['format'],count=d['count'],high='none' if high=='previous' and not selected else high,high_rounds=selected,setup_stage='registration',registration_complete=False,step=2)
 elif action=='finish_registration':
  require(t['status']=='setup','Турнир басталған')
  require(t.get('setup_stage')=='registration' or ('setup_stage' not in t and t['step']>=2),'Алдымен баптауларды сақтаңыз')
  t['allow_bye']=bool(d.get('allow_bye')); ready(t)
  t.update(registration_complete=True,setup_stage='start',step=5)
 elif action=='setup_back':
  require(t['status']=='setup','Баптау аяқталған')
  t.update(setup_stage='registration' if (t.get('setup_stage')=='start' or ('setup_stage' not in t and t['step']==5)) else 'settings',registration_complete=False)
 elif action=='setup':
  require(t['status']=='setup','Баптау аяқталған')
  step=int(d['step']); require(0<=step<=4 and step==t['step'],'Қадам қате')
  if step==0:
   require(d['name'].strip() and d['format'] in POSITIONS,'Атау мен форматты енгізіңіз'); t.update(name=d['name'].strip(),format=d['format'],playoff=bool(d.get('playoff')))
  elif step==1: require(isinstance(d['count'],int) and 1<=d['count']<=30,'Раунд саны: 1–30'); t['count']=d['count']
  elif step==2:
   require(len(t['teams'])>=2,'Кемінде екі фракция қажет'); require(t['format']!='BPF' or (len(t['teams'])>=4 and len(t['teams'])%4==0),'БПФ құрамы төртке бөлінуі керек'); t['allow_bye']=bool(d.get('allow_bye')); require(t['format']!='APF' or len(t['teams'])%2==0 or t['allow_bye'],'Автожеңісті растаңыз')
  elif step==3:
   require(d['high'] in ['none','previous','all'],'High/Low режимі қате'); require(all(isinstance(n,int) and 2<=n<=t['count'] for n in d.get('high_rounds',[])),'Раунд таңдауы қате'); t.update(high='none' if d['high']=='previous' and not d.get('high_rounds') else d['high'],high_rounds=d.get('high_rounds',[]))
  elif step==4: ready(t)
  t['step']=step+1
 elif action=='back': require(t['status']=='setup','Баптау аяқталған'); t['step']=max(0,t['step']-1)
 elif action=='team':
  require(t['status']=='setup','Турнир басталған'); require(all(str(d.get(k,'')).strip() for k in ['name','speaker1','speaker2']),'Барлық өрісті толтырыңыз')
  existing=next((x for x in t['teams'] if x['id']==d.get('id')),{})
  clashes=d.get('clashes',existing.get('clashes','')); require(isinstance(clashes,str),'Клэш есімдерін мәтінмен енгізіңіз')
  item={'id':d.get('id') or secrets.randbelow(10**12),'name':d['name'].strip(),'club':str(d.get('club') or '').strip(),'speakers':[d['speaker1'].strip(),d['speaker2'].strip()],'clashes':clashes.strip()}; t['teams']=[x for x in t['teams'] if x['id']!=item['id']]+[item]
  ensure_club_emojis(t)
 elif action=='delete_team':
  require(t['status']=='setup' and not t['rounds'],'Турнир басталған: фракцияны жоюға болмайды')
  require(any(x['id']==d.get('id') for x in t['teams']),'Фракция осы турнирден табылмады')
  t['teams']=[x for x in t['teams'] if x['id']!=d['id']]
 elif action=='judge':
  require(str(d.get('name','')).strip(),'Төрешінің атын енгізіңіз'); jid=d.get('id') or secrets.randbelow(10**12); t['judges']=[dict(x,name=d['name'].strip()) if x['id']==jid else x for x in t['judges']]
  if not any(x['id']==jid for x in t['judges']): t['judges'].append({'id':jid,'name':d['name'].strip()})
 elif action=='delete_judge':
  require(t['status']=='setup' or len(t['judges'])-1>=minimum(t),'Төреші саны минимумнан төмен болады'); t['judges']=[x for x in t['judges'] if x['id']!=d['id']]
  for r in t['rounds']:
   if not r['confirmed']:
    for room in r['rooms']: room['judges']=[j for j in room['judges'] if j!=d['id']]
 elif action=='start':
  require(t['status']=='setup' and t['step']==5 and (t.get('registration_complete') if 'setup_stage' in t else True),'Баптауды аяқтаңыз'); ready(t); t['status']='active'; t['rounds'].append(draw(t))
 elif action in ['draft','confirm']:
  r=t['rounds'][-1]; require(not r['confirmed'] and d['number']==r['number'],'Раунд бұрын расталған немесе ескірген'); rooms=d['rooms']; size=len(POSITIONS[t['format']]); require(len(rooms)==minimum(t),'Рум саны қате')
  ids=[i for room in rooms for i in room['teams']]; require(sorted(ids)==sorted(x['id'] for x in t['teams'] if x['id']!=r['bye']) and all(len(x['teams'])==size for x in rooms),'Позициялар толық емес немесе фракция қайталанған')
  judges=[i for room in rooms for i in room['judges']]; require(len(set(judges))==len(judges) and set(judges)<=set(x['id'] for x in t['judges']),'Төреші қайталанған немесе табылмады'); require(all(str(x['cabinet']).strip() for x in rooms),'Кабинетті енгізіңіз')
  if action=='confirm': require(all(x['judges'] for x in rooms),'Әр румға төреші тағайындаңыз')
  r['rooms']=rooms; r['confirmed']=action=='confirm'
  if r['confirmed']: r['judge_names']={str(x['id']):x['name'] for x in t['judges']}
 elif action=='result':
  r=t['rounds'][-1]; require(r['confirmed'] and d['number']==r['number'] and t['status']=='active','Раунд нәтижесін өзгертуге болмайды'); key=str(d['room']); require(key in {str(i) for i in range(len(r['rooms']))} or (key=='bye' and r['bye'] is not None),'Рум табылмады'); ids=[r['bye']] if key=='bye' else r['rooms'][int(key)]['teams']; values=d['values']; require(set(values)==set(map(str,ids)),'Фракциялар сәйкес емес')
  ranks=[]
  for v in values.values():
   require(isinstance(v.get('scores'),list) and len(v['scores'])==2 and all(type(s) in (int,float) and math.isfinite(s) and s>=0 for s in v['scores']),'Спикер балдарын санмен енгізіңіз'); require(type(v.get('rank'))==int,'Рангті таңдаңыз'); ranks.append(v['rank'])
  require(ranks==[1] if key=='bye' else sorted(ranks)==([1,2] if t['format']=='APF' else [1,2,3,4]),'Жеңімпазды таңдаңыз немесе 1–4 рангтерін қайталамай енгізіңіз'); r['results'][key]=values
 elif action=='next':
  require(t['status']=='active','Іріктеу аяқталған')
  r=t['rounds'][-1]; require(d['number']==r['number'],'Келесі раунд бұрын жасалған'); require(r['confirmed'] and complete(r),'Барлық нәтижені сақтаңыз')
  if len(t['rounds'])==t['count']: t['status']='results'
  else: t['rounds'].append(draw(t))
 elif action=='playoff': require(t['status']=='results','Іріктеу аяқталмаған'); t['playoff_done']=bool(d.get('done'))
 else: raise ValueError('Белгісіз әрекет')
 if action in ['team','delete_team','judge','delete_judge'] and t['status']=='setup' and 'setup_stage' in t:
  t['registration_complete']=False
  if t['setup_stage']=='start': t.update(setup_stage='registration',step=2)
 t.pop('export_token',None)

class Handler(BaseHTTPRequestHandler):
 def send(self,status,data,ctype='application/json; charset=utf-8',cookie=None):
  data=json.dumps(data,ensure_ascii=False).encode() if isinstance(data,(dict,list)) else data
  self.send_response(status); self.send_header('Content-Type',ctype); self.send_header('Content-Length',str(len(data))); self.send_header('Cache-Control','no-store'); self.send_header('X-Content-Type-Options','nosniff')
  if cookie: self.send_header('Set-Cookie',cookie)
  self.end_headers(); self.wfile.write(data)
 def do_GET(self):
  if self.path.startswith('/api/'): return self.api()
  path={'/':'index.html','/app.js':'app.js','/style.css':'style.css','/cat-icon.svg':'cat-icon.svg','/debate-cat.svg':'debate-cat.svg','/debate-pattern.svg':'debate-pattern.svg'}.get(self.path)
  if not path: return self.send(404,b'Not found','text/plain')
  with open(os.path.join(os.path.dirname(__file__),'static',path),'rb') as f: self.send(200,f.read(),{'html':'text/html; charset=utf-8','js':'text/javascript; charset=utf-8','css':'text/css; charset=utf-8','svg':'image/svg+xml'}[path.split('.')[-1]])
 def do_POST(self): self.api()
 def api(self):
  c=None
  try:
   c=connect()
   if self.command=='POST':
    require(self.headers.get('Sec-Fetch-Site')!='cross-site','Басқа сайттан сұраныс қабылданбайды')
    origin=self.headers.get('Origin'); require(not origin or origin in ['http://'+self.headers.get('Host',''),'https://'+self.headers.get('Host','')],'Сұраныс көзі қате')
    length=int(self.headers.get('Content-Length',0)); require(0<length<2000000,'Сұраныс көлемі қате'); d=json.loads(self.rfile.read(length))
   else: d={}
   c.execute('BEGIN IMMEDIATE')
   action=self.path.split('/')[-1]
   if action in ['login','register']:
    require(self.command=='POST','POST қажет'); login=str(d.get('login','')).strip(); p=str(d.get('password','')); require(1<=len(login)<=100 and 6<=len(p)<=256,'Логинді және кемінде 6 таңбалы парольді енгізіңіз')
    if action=='register':
     try: c.execute('INSERT INTO users(login,password) VALUES (?,?)',(login,password(p)))
     except sqlite3.IntegrityError: raise ValueError('Бұл логин тіркелген')
    user=c.execute('SELECT * FROM users WHERE login=?',(login,)).fetchone(); require(user and verify(p,user['password']),'Логин немесе пароль қате'); token=secrets.token_urlsafe(32); c.execute('INSERT INTO sessions VALUES (?,?,?)',(token,user['id'],time.time()+604800)); c.commit(); return self.send(200,{'ok':True},cookie=f'session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=604800')
   cookies=SimpleCookie(self.headers.get('Cookie','')); token=cookies['session'].value if 'session' in cookies else ''; session=c.execute('SELECT * FROM sessions WHERE token=? AND expires>?',(token,time.time())).fetchone()
   if not session: c.rollback(); return self.send(401,{'error':'Аккаунтқа кіріңіз'})
   uid=session['user']; user=c.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone(); row=c.execute('SELECT data FROM tournaments WHERE user=?',(uid,)).fetchone(); t=json.loads(row['data']) if row else None
   if t is not None and ensure_club_emojis(t):
    # Display metadata is server-owned; keep the tournament revision unchanged.
    c.execute('UPDATE tournaments SET data=? WHERE user=?',(json.dumps(t),uid))
   if action=='state': c.commit(); return self.send(200,{'login':user['login'],'tournament':t,'rankings':rankings(t) if t else None,'setup_api_version':SETUP_API_VERSION})
   require(self.command=='POST','POST қажет')
   if action=='logout': c.execute('DELETE FROM sessions WHERE token=?',(token,)); c.commit(); return self.send(200,{'ok':True},cookie='session=; Path=/; Max-Age=0; HttpOnly; SameSite=Strict')
   if action=='create':
    require(t is None,'Аккаунтта турнир бар'); t={'name':'','format':'APF','status':'setup','step':0,'count':3,'teams':[],'judges':[],'rounds':[],'high':'none','high_rounds':[],'playoff':False,'club_emojis':{},'revision':0}; c.execute('INSERT INTO tournaments VALUES (?,?)',(uid,json.dumps(t)))
   else:
    require(t is not None,'Турнир жоқ'); require(d.get('revision')==t['revision'],'Деректер өзгерген. Бетті жаңартып, қайталаңыз.')
    if action in ['export','finish']:
     require(verify(str(d.get('password','')),user['password']),'Пароль қате'); require(t['status']=='results' and complete(t['rounds'][-1]),'Турнир аяқтауға дайын емес')
     if action=='export':
      binary=export(t); t['export_token']=secrets.token_urlsafe(24); t['revision']+=1; c.execute('UPDATE tournaments SET data=? WHERE user=?',(json.dumps(t),uid)); c.commit()
      return self.send(200,{'file':__import__('base64').b64encode(binary).decode(),'token':t['export_token'],'revision':t['revision']})
     require(t.get('export_token') and d.get('token')==t['export_token'],'Алдымен Excel файлын жүктеңіз'); c.execute('DELETE FROM tournaments WHERE user=?',(uid,)); c.commit(); return self.send(200,{'ok':True})
    mutate(t,action,d); t['revision']+=1; c.execute('UPDATE tournaments SET data=? WHERE user=?',(json.dumps(t),uid))
   c.commit(); self.send(200,{'ok':True})
  except (ValueError,KeyError,IndexError,TypeError) as e:
   if c: c.rollback()
   self.send(400,{'error':str(e)})
  except Exception as e:
   if c: c.rollback()
   print(type(e).__name__); self.send(500,{'error':'Сервер қатесі. Деректер сақталды, қайта көріңіз.'})
  finally:
   if c: c.close()
if __name__=='__main__':
 connect().close(); print('Сайт: http://127.0.0.1:8000'); ThreadingHTTPServer(('127.0.0.1',int(os.environ.get('PORT',8000))),Handler).serve_forever()

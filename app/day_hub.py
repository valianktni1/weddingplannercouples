"""Wedding-day coordination, scoped sharing and seating. No guest health data is shared."""
import csv
import io
import json
import re
import secrets
import time
from datetime import date,datetime,timedelta,timezone
from zoneinfo import ZoneInfo
from flask import g,request,jsonify,render_template,abort,send_file,make_response
from .core import digest,cipher,date_valid,config
from .mail_service import smtp_ready

SCHEMA='''
CREATE TABLE IF NOT EXISTS hub_meta(wedding_id TEXT PRIMARY KEY,revision INTEGER NOT NULL DEFAULT 0,updated REAL NOT NULL DEFAULT 0,ready INTEGER NOT NULL DEFAULT 0,last_active REAL);
CREATE TABLE IF NOT EXISTS hub_events(id TEXT PRIMARY KEY,wedding_id TEXT NOT NULL,title TEXT NOT NULL,start INTEGER NOT NULL,duration INTEGER NOT NULL,location TEXT NOT NULL,instructions TEXT NOT NULL,audience TEXT NOT NULL,supplier_id TEXT NOT NULL,kind TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS hub_jobs(id TEXT PRIMARY KEY,wedding_id TEXT NOT NULL,title TEXT NOT NULL,owner TEXT NOT NULL,start INTEGER,instructions TEXT NOT NULL,assigned_share TEXT NOT NULL,done INTEGER NOT NULL DEFAULT 0,revision INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS hub_tables(id TEXT PRIMARY KEY,wedding_id TEXT NOT NULL,name TEXT COLLATE NOCASE NOT NULL,capacity INTEGER,shape TEXT NOT NULL,x REAL NOT NULL,y REAL NOT NULL,UNIQUE(wedding_id,name));
CREATE TABLE IF NOT EXISTS hub_shares(id TEXT PRIMARY KEY,wedding_id TEXT NOT NULL,label TEXT NOT NULL,role TEXT NOT NULL,scopes TEXT NOT NULL,supplier_ids TEXT NOT NULL,email TEXT NOT NULL,notify INTEGER NOT NULL,expires REAL NOT NULL,revoked INTEGER NOT NULL DEFAULT 0,secret_encrypted TEXT NOT NULL,last_notice_hash TEXT NOT NULL,created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS hub_ack(share_id TEXT PRIMARY KEY,content_hash TEXT NOT NULL,snapshot TEXT NOT NULL,confirmed REAL NOT NULL);
'''
ROLES=['photographer','venue','party','coordinator']
SCOPES=['timeline','contacts','photos','seating','jobs']
DEFAULT_SCOPES={'photographer':['timeline','photos','jobs'],'venue':['timeline','seating','jobs'],'party':['timeline','jobs'],'coordinator':['timeline','jobs']}


def clock(n):
    if n is None:return 'Not set'
    if n<0:return clock(n%1440)+' (-1 day)'
    return f'{n//60:02d}:{n%60:02d}' if n<1440 else f'{n//60%24:02d}:{n%60:02d} (+{n//1440} day)'


def text(value,label,limit=300,required=False):
    if not isinstance(value,str) or len(value)>limit or '\0' in value or (required and not value.strip()):raise ValueError('Check '+label+'.')
    return value.strip()


def integer(value,label,low=0,high=1439,optional=False):
    if optional and value is None:return None
    if type(value) is not int or not low<=value<=high:raise ValueError('Check '+label+'.')
    return value


def timeline(state,extra,role=None):
    d=state['day'];photo=d['ceremony']+d['ceremonyMinutes']+d['confetti'];end=photo+d['groupsMinutes']+d['portraits']
    rows=[('ceremony',d['ceremony'],'Ceremony',d['ceremonyMinutes'],d['venue']),('confetti',d['ceremony']+d['ceremonyMinutes'],'Congratulations and confetti',d['confetti'],d['venue']),('groups',photo,'Family and wedding-party photographs',d['groupsMinutes'],d['venue']),('portraits',photo+d['groupsMinutes'],'Time for the two of us',d['portraits'],d['venue']),('seating',d['meal']-d['seating'],'Guests take their seats',d['seating'],d['receptionVenue'] or d['venue']),('meal',d['meal'],'Wedding meal',0,d['receptionVenue'] or d['venue']),('dance',d['firstDance'],'First dance',0,d['receptionVenue'] or d['venue'])]
    if d['receptionTravel']:rows.append(('travel',end,'Travel to reception',d['receptionTravel'],d['receptionVenue']))
    result=[{'id':'core-'+i,'start':at,'title':title,'duration':duration,'location':location,'instructions':'','core':True} for i,at,title,duration,location in rows]
    for e in extra:
        if role is not None and e['audience'] not in ('everyone',role):continue
        result.append({k:e[k] for k in ['id','title','start','duration','location','instructions']}|{'core':False})
    return sorted(result,key=lambda e:(e['start'],e['id']))


def table_guests(state):
    return [{'id':g['id'],'name':g['name'],'table':g['table'],'attendance':g['attendance'],'rsvp':g['rsvp']} for g in state['guests']]


def readiness(state,events,jobs,tables,shares=()):
    checks=[];d=state['day'];today=datetime.now(ZoneInfo(state['timezone'])).date().isoformat()
    def add(code,message):checks.append({'code':code,'message':message})
    if not state['date']:add('date','Choose your wedding date.')
    if not d['venue'].strip():add('venue','Enter the ceremony venue.')
    if not d['mealConfirmed']:add('meal','Confirm the meal time with your venue.')
    for i,m in enumerate(d['mornings']):
        if m['ready']+m['loading']+m['travel']>d['ceremony']:add('morning-'+str(i),(state['names'][i] or 'Partner '+str(i+1))+' arrives after the ceremony time; review preparation and travel.')
    if d['meal']-d['seating']<d['ceremony']:add('seating-time','The call to be seated falls before the ceremony. Review the meal and seating allowances.')
    end=d['ceremony']+d['ceremonyMinutes']+d['confetti']+d['groupsMinutes']+d['portraits']+d['receptionTravel']
    if end>d['meal']-d['seating']:add('photo-meal','Photographs and reception travel overlap the call to be seated by '+str(end-d['meal']+d['seating'])+' minutes.')
    if sum(x['minutes'] for x in state['groups'])>d['groupsMinutes']:add('photo-groups','Your photo-group estimates exceed the time allowed.')
    if d['lightEnd'] is not None and end-d['receptionTravel']>d['lightEnd']:add('light','Photographs finish after your entered outdoor-light cutoff.')
    booked=[x for x in state['suppliers'] if x['booked']]
    missing=sum(not x['contact'].strip() for x in booked)
    if missing:add('contacts',f'{missing} booked supplier contact(s) still need entering.')
    arrivals={e['supplier_id'] for e in events if e['kind']=='arrival'}
    missing=sum(x['id'] not in arrivals for x in booked)
    if missing:add('arrivals',f'{missing} booked supplier arrival time(s) still need checking.')
    for s in booked:
        if re.search('photo|video',s['category'],re.I) and s['finish'] is not None and s['finish']<d['firstDance']:add('coverage-'+s['id'],s['name']+' finishes before the first dance; check the agreed coverage.')
    unpaid=[p for p in state['payments'] if p['paid']<p['amount'] and p['due'] and p['due']<=today]
    if unpaid:add('payments',f'{len(unpaid)} instalment(s) are due or overdue in your records. Confirm balances with suppliers.')
    waiting=sum(g['rsvp']=='Waiting' for g in state['guests'])
    if waiting:add('rsvp',f'{waiting} guest reply/replies still need checking.')
    unseated=sum(g['rsvp']=='Accepted' and g['attendance']=='Day' and not g['table'] for g in state['guests'])
    if unseated:add('seating',f'{unseated} accepted day guest(s) have no table assignment.')
    if any(g['rsvp']=='Declined' and g['table'] for g in state['guests']):add('declined','Some declined guests still have table assignments.')
    for t in tables:
        count=sum(g['table']==t['name'] and g['rsvp']!='Declined' for g in state['guests'])
        if t['capacity'] is None:add('capacity-'+t['id'],'Confirm the capacity of '+t['name']+'.')
        elif count>t['capacity']:add('capacity-'+t['id'],t['name']+' has more guests than its entered capacity.')
    names={t['name'] for t in tables}
    if any(g['table'] and g['table'] not in names for g in state['guests']):add('legacy-tables','Some guest table labels have not been added to your visual layout. Use Import existing table labels.')
    if any(not j['done'] and not j['owner'] and not j['assigned_share'] for j in jobs):add('jobs','Choose who is responsible for the unassigned wedding-day jobs.')
    active_ids={sh['id'] for sh in shares if not sh['revoked'] and sh['expires']>time.time()}
    if any(j['assigned_share'] and j['assigned_share'] not in active_ids for j in jobs):add('job-links','Some jobs point to an expired or revoked link. Reassign them or keep them private.')
    intervals=[e for e in timeline(state,events) if e['duration']>0]
    clashes=[]
    for i,a in enumerate(intervals):
        for b in intervals[i+1:]:
            if b['start']>=a['start']+a['duration']:break
            if not a['core'] or not b['core']:clashes.append(a['title']+' / '+b['title'])
    if clashes:add('overlaps','Check overlapping activities (some may be intentional): '+', '.join(clashes[:6])+'.')
    return checks


def change_lines(previous,current):
    changes=[]
    if previous.get('date')!=current.get('date'):changes.append('Wedding date changed.')
    for key,label in [('timeline','Timeline'),('contacts','Supplier contacts'),('photos','Photo groups'),('seating','Seating plan'),('jobs','Responsibilities')]:
        if previous.get(key)!=current.get(key):
            changes.append(label+' changed.')
            if key=='timeline':
                old={e['id']:e for e in previous.get(key,[])}
                for e in current.get(key,[]):
                    before=old.get(e['id'])
                    if before and before['start']!=e['start']:changes.append(e['title']+': '+clock(before['start'])+' → '+clock(e['start'])+'.')
    return changes[:12]


def stable_view(view):
    value=json.loads(json.dumps(view))
    for job in value.get('jobs',[]):
        job.pop('done',None);job.pop('revision',None)
    return value


def view_hash(view):return digest(json.dumps(stable_view(view),sort_keys=True,separators=(',',':')))


def journey(db,w,state):
    meta=db.execute('SELECT * FROM hub_meta WHERE wedding_id=?',(w['id'],)).fetchone()
    verified=db.execute('SELECT max(u.verified) FROM users u JOIN members m ON m.user_id=u.id WHERE m.wedding_id=?',(w['id'],)).fetchone()[0]
    if state['stage']=='finished':stage='Archived'
    elif not verified:stage='Invited'
    elif not state['ready']:stage='Joined'
    elif meta and meta['ready']:stage='Ready for the day'
    elif any(state[k] for k in ['suppliers','tasks','guests','events']) or meta and meta['updated']:stage='Actively planning'
    else:stage='Getting started'
    return {'stage':stage,'last_active':meta['last_active'] if meta else None,'last_changed':meta['updated'] if meta else None,'support_requested':bool(db.execute('SELECT 1 FROM support WHERE wedding_id=? AND expires>?',(w['id'],time.time())).fetchone()),'expires_soon':date.today().isoformat()<=w['access_until']<=(date.today()+timedelta(days=14)).isoformat(),'expired':w['access_until']<date.today().isoformat()}


def register_hub(app,db,auth,wedding,json_body,audit,queue,token,token_row,rate,update_state):
    app.jinja_env.filters['hubclock']=clock
    app.jinja_env.filters['hubdate']=lambda value:date.fromisoformat(value).strftime('%d %B %Y') if value else 'Date to confirm'
    def rows(table,wid):return [dict(r) for r in db().execute('SELECT * FROM '+table+' WHERE wedding_id=? ORDER BY rowid',(wid,))]
    def meta(wid):
        db().execute('INSERT OR IGNORE INTO hub_meta(wedding_id) VALUES(?)',(wid,))
        return dict(db().execute('SELECT * FROM hub_meta WHERE wedding_id=?',(wid,)).fetchone())
    def projection(w,share=None,profile='couple'):
        s=json.loads(w['state']);role=share['role'] if share else profile;scopes=json.loads(share['scopes']) if share else SCOPES if profile=='couple' else DEFAULT_SCOPES[profile]
        result={'names':' & '.join(s['names']),'date':s['date'],'timezone':s['timezone']}
        if 'timeline' in scopes:result['timeline']=timeline(s,rows('hub_events',w['id']),None if role=='couple' else role)
        if 'contacts' in scopes:
            ids=json.loads(share['supplier_ids']) if share else [x['id'] for x in s['suppliers']]
            result['contacts']=[{k:x[k] for k in ['id','name','category','contact']} for x in s['suppliers'] if x['id'] in ids]
        if 'photos' in scopes:result['photos']=[{'title':x['title'],'minutes':x['minutes']} for x in s['groups']]
        if 'seating' in scopes:result['seating']=[{k:x[k] for k in ['name','table','attendance','rsvp']} for x in s['guests'] if x['rsvp']!='Declined']
        if 'jobs' in scopes:
            jobs=rows('hub_jobs',w['id']);share_rows={x['id']:x for x in rows('hub_shares',w['id'])};shares={k:x['label'] for k,x in share_rows.items()}
            result['jobs']=[{k:j[k] for k in ['id','title','start','instructions','done','revision']}|{'owner':shares.get(j['assigned_share'],j['owner'])} for j in jobs if role=='couple' or (share and j['assigned_share']==share['id']) or (not share and j['assigned_share'] in share_rows and share_rows[j['assigned_share']]['role']==role and not share_rows[j['assigned_share']]['revoked'] and 'jobs' in json.loads(share_rows[j['assigned_share']]['scopes']))]
        return result
    def active_share(share,w):return not share['revoked'] and share['expires']>time.time() and not w['suspended'] and w['access_until']>=date.today().isoformat()
    def notify(wid,reset_ready=True):
        w=db().execute('SELECT * FROM weddings WHERE id=?',(wid,)).fetchone()
        if not w:return
        meta(wid)
        if reset_ready:db().execute('UPDATE hub_meta SET ready=0,updated=? WHERE wedding_id=?',(time.time(),wid))
        for share in rows('hub_shares',wid):
            if not active_share(share,w):continue
            visible=projection(w,share);hashed=view_hash(visible)
            if hashed==share['last_notice_hash']:continue
            db().execute('UPDATE hub_shares SET last_notice_hash=? WHERE id=?',(hashed,share['id']))
            if share['email'] and share['notify']:
                value=cipher(app.config['SECRET_VALUE']).decrypt(share['secret_encrypted'].encode()).decode()
                queue(share['email'],'Wedding day plan updated','The wedding-day details shared with you have changed. Open your private link to review them and confirm the latest version:\n'+app.config['APP_URL']+'/day/'+value,dedupe='hub-change:'+share['id']+':'+hashed)
    def share_config(body,w):
        label=text(body.get('label'),'the recipient name',100,True);role=body.get('role');scopes=body.get('scopes');ids=body.get('supplier_ids',[])
        if role not in ROLES or not isinstance(scopes,list) or not scopes or any(not isinstance(x,str) for x in scopes) or len(scopes)!=len(set(scopes)) or any(x not in SCOPES for x in scopes):raise ValueError('Choose a recipient role and the sections to share.')
        if not isinstance(ids,list) or len(ids)>1000 or any(not isinstance(x,str) for x in ids) or len(ids)!=len(set(ids)):raise ValueError('Choose supplier contacts to share.')
        state=json.loads(w['state']);known={x['id'] for x in state['suppliers']}
        if any(x not in known for x in ids) or 'contacts' in scopes and not ids:raise ValueError('Select the specific supplier contacts this person may see.')
        until=body.get('until')
        if not date_valid(until,False) or until<date.today().isoformat() or until>w['access_until']:raise ValueError('Choose a link expiry between today and your planning access end date.')
        expires=datetime.combine(date.fromisoformat(until),datetime.max.time(),ZoneInfo(state['timezone'])).timestamp()
        email=text(body.get('email',''),'the recipient email',160)
        if email and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email):raise ValueError('Enter a valid recipient email.')
        notify_email=body.get('notify',False);send=body.get('send_email',False)
        if type(notify_email) is not bool or type(send) is not bool:raise ValueError('Check the email choices.')
        if (notify_email or send) and (not email or not smtp_ready(config(db()))):raise ValueError('An email address and a configured sending mailbox are needed for email updates.')
        return {'label':label,'role':role,'scopes':json.dumps(scopes),'supplier_ids':json.dumps(ids),'expires':expires,'email':email,'notify':int(notify_email),'send_email':send}
    def owned(table,identity,wid):
        if not isinstance(identity,str):abort(404)
        row=db().execute('SELECT * FROM '+table+' WHERE id=? AND wedding_id=?',(identity,wid)).fetchone()
        if not row:abort(404)
        return row
    def result(w):
        wid=w['id'];s=json.loads(w['state']);m=meta(wid);events=rows('hub_events',wid);jobs=rows('hub_jobs',wid);tables=rows('hub_tables',wid);shares=[]
        for sh in rows('hub_shares',wid):
            ack=db().execute('SELECT * FROM hub_ack WHERE share_id=?',(sh['id'],)).fetchone();hashed=view_hash(projection(w,sh))
            shares.append({k:sh[k] for k in ['id','label','role','email','notify','expires','revoked']}|{'scopes':json.loads(sh['scopes']),'supplier_ids':json.loads(sh['supplier_ids']),'confirmed':bool(ack and ack['content_hash']==hashed),'confirmed_at':ack['confirmed'] if ack else None,'active':active_share(sh,w)})
        return {'revision':m['revision'],'plan_revision':w['revision'],'ready':bool(m['ready']),'updated':m['updated'],'names':s['names'],'date':s['date'],'until':w['access_until'],'readonly':w['access_until']<date.today().isoformat(),'timeline':timeline(s,events),'events':events,'jobs':jobs,'tables':tables,'guests':table_guests(s),'suppliers':[{k:x[k] for k in ['id','name','category','contact']} for x in s['suppliers']],'shares':shares,'checks':readiness(s,events,jobs,tables,rows('hub_shares',wid))}
    @app.get('/hub')
    @auth()
    def hub_page():wedding();return render_template('hub.html')
    @app.get('/api/hub')
    @auth()
    def get_hub():return jsonify(result(wedding()))
    @app.post('/api/hub/share-preview')
    @auth()
    def share_preview():
        w=wedding(True);sh=share_config(json_body(),w);sh['id']='preview';return jsonify(view=projection(w,sh),label=sh['label'],scopes=json.loads(sh['scopes']))
    @app.get('/api/hub/shares/<sid>/link')
    @auth()
    def owner_share_link(sid):
        w=wedding();sh=owned('hub_shares',sid,w['id'])
        if not active_share(sh,w):raise ValueError('This link has expired or was revoked. Create a new one.')
        value=cipher(app.config['SECRET_VALUE']).decrypt(sh['secret_encrypted'].encode()).decode();return jsonify(url=app.config['APP_URL']+'/day/'+value)
    @app.get('/api/hub/shares/<sid>/preview')
    @auth()
    def owner_share_preview(sid):
        w=wedding();sh=owned('hub_shares',sid,w['id']);return jsonify(view=projection(w,sh),label=sh['label'],scopes=json.loads(sh['scopes']))
    @app.post('/api/hub/action')
    @auth()
    def hub_action():
        body=json_body();rate('hub-edit-'+g.user['id'],1200,900,per_ip=False);db().execute('BEGIN IMMEDIATE');w=wedding(True);wid=w['id'];s=json.loads(w['state']);m=meta(wid)
        if type(body.get('revision')) is not int or type(body.get('plan_revision')) is not int or body['revision']!=m['revision'] or body['plan_revision']!=w['revision']:abort(409,description='Your shared plan changed. Reload the Hub before trying this action again.')
        action=body.get('action');identity=body.get('id');state_changed=False;response={}
        if action=='event_save':
            if identity:owned('hub_events',identity,wid)
            elif len(rows('hub_events',wid))>=200:raise ValueError('Keep the day plan to 200 added activities.')
            identity=identity or secrets.token_hex(12);title=text(body.get('title'),'the activity title',150,True);at=integer(body.get('start'),'the activity time');duration=integer(body.get('duration'),'the duration',0,600);location=text(body.get('location',''),'the activity location',200);instructions=text(body.get('instructions',''),'the shared activity instructions',600);audience=body.get('audience','private');supplier=body.get('supplier_id','');kind=body.get('kind','event')
            if not isinstance(supplier,str) or audience not in ['everyone','private',*ROLES] or kind not in ['event','arrival'] or supplier and supplier not in {x['id'] for x in s['suppliers']}:raise ValueError('Check the activity audience and supplier.')
            db().execute('INSERT OR REPLACE INTO hub_events VALUES(?,?,?,?,?,?,?,?,?,?)',(identity,wid,title,at,duration,location,instructions,audience,supplier,kind))
        elif action=='event_delete':owned('hub_events',identity,wid);db().execute('DELETE FROM hub_events WHERE id=?',(identity,))
        elif action=='job_save':
            old=owned('hub_jobs',identity,wid) if identity else None
            if not identity and len(rows('hub_jobs',wid))>=200:raise ValueError('Keep the day jobs to 200 entries.')
            identity=identity or secrets.token_hex(12);title=text(body.get('title'),'the job title',150,True);owner=text(body.get('owner',''),'the responsible person',100);at=integer(body.get('start'),'the job time',optional=True);instructions=text(body.get('instructions',''),'the job instructions',600);assigned=text(body.get('assigned_share',''),'the responsible recipient',100)
            if assigned:sh=owned('hub_shares',assigned,wid)
            if assigned and (not active_share(sh,w) or 'jobs' not in json.loads(sh['scopes'])):raise ValueError('Choose an active person whose link includes responsibilities.')
            db().execute('INSERT OR REPLACE INTO hub_jobs VALUES(?,?,?,?,?,?,?,?,?)',(identity,wid,title,owner,at,instructions,assigned,int(old['done']) if old else 0,(old['revision']+1) if old else 0))
        elif action=='job_done':
            old=owned('hub_jobs',identity,wid)
            if type(body.get('done')) is not bool:raise ValueError('Check the job completion choice.')
            db().execute('UPDATE hub_jobs SET done=?,revision=revision+1 WHERE id=?',(int(body['done']),identity))
        elif action=='job_delete':owned('hub_jobs',identity,wid);db().execute('DELETE FROM hub_jobs WHERE id=?',(identity,))
        elif action=='table_save':
            old=owned('hub_tables',identity,wid) if identity else None;identity=identity or secrets.token_hex(12);name=text(body.get('name'),'the table name',60,True);capacity=integer(body.get('capacity'),'the table capacity',1,100);shape=body.get('shape','round')
            if shape not in ['round','long']:raise ValueError('Choose round or long table shape.')
            if db().execute('SELECT 1 FROM hub_tables WHERE wedding_id=? AND name=? COLLATE NOCASE AND id!=?',(wid,name,identity)).fetchone():raise ValueError('Each table needs a different name.')
            if not old and len(rows('hub_tables',wid))>=100:raise ValueError('A maximum of 100 tables is supported.')
            n=len(rows('hub_tables',wid));x=body.get('x',old['x'] if old else 20+(n%3)*30);y=body.get('y',old['y'] if old else min(90,15+(n//3)*15))
            if type(x) not in (int,float) or type(y) not in (int,float) or not 0<=x<=100 or not 0<=y<=100:raise ValueError('Keep the table within the room layout.')
            db().execute('INSERT OR REPLACE INTO hub_tables VALUES(?,?,?,?,?,?,?)',(identity,wid,name,capacity,shape,x,y))
            if old and old['name']!=name:
                for guest in s['guests']:
                    if guest['table']==old['name']:guest['table']=name;state_changed=True
        elif action=='table_move':
            owned('hub_tables',identity,wid);x=body.get('x');y=body.get('y')
            if type(x) not in (int,float) or type(y) not in (int,float) or not 0<=x<=100 or not 0<=y<=100:raise ValueError('Keep the table within the room layout.')
            db().execute('UPDATE hub_tables SET x=?,y=? WHERE id=?',(x,y,identity))
        elif action=='table_delete':
            table=owned('hub_tables',identity,wid);assigned=[x for x in s['guests'] if x['table']==table['name']]
            if assigned and body.get('unseat') is not True:raise ValueError('Confirm that assigned guests should return to the unseated list before removing this table.')
            for guest in assigned:guest['table']='';state_changed=True
            db().execute('DELETE FROM hub_tables WHERE id=?',(identity,))
        elif action=='import_tables':
            existing={x['name'].casefold() for x in rows('hub_tables',wid)};labels=sorted({x['table'] for x in s['guests'] if x['table']})
            if len(existing|{x.casefold() for x in labels})>100:raise ValueError('A maximum of 100 table labels can be laid out.')
            for i,label in enumerate(labels):
                if label.casefold() in existing:continue
                if len(label)>60:raise ValueError('Shorten table labels to 60 characters in Guests & photos before importing.')
                db().execute('INSERT INTO hub_tables VALUES(?,?,?,?,?,?,?)',(secrets.token_hex(12),wid,label,None,'round',20+(i%4)*20,20+(i//4%4)*20));existing.add(label.casefold())
        elif action=='seat':
            guest=next((x for x in s['guests'] if x['id']==body.get('guest_id')),None)
            if not guest:abort(404)
            table=owned('hub_tables',body['table_id'],wid) if body.get('table_id') else None
            if table and guest['rsvp']=='Declined':raise ValueError('This guest has declined. Change their reply before assigning a seat.')
            if table and guest['table']!=table['name'] and table['capacity'] is not None and sum(x['table']==table['name'] and x['rsvp']!='Declined' for x in s['guests'])>=table['capacity']:raise ValueError('This table is at its entered capacity. Choose another table or check its capacity.')
            guest['table']=table['name'] if table else '';state_changed=True
        elif action=='share_create':
            if len([x for x in rows('hub_shares',wid) if not x['revoked']])>=50:raise ValueError('Revoke an old link before adding more than 50 recipients.')
            sh=share_config(body,w);identity=secrets.token_hex(12);value=token('hub_share',wedding=wid,payload={'share_id':identity},hours=max(1,(sh['expires']-time.time())/3600));sh['id']=identity
            hashed=view_hash(projection(w,sh));encrypted=cipher(app.config['SECRET_VALUE']).encrypt(value.encode()).decode()
            db().execute('INSERT INTO hub_shares VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',(identity,wid,sh['label'],sh['role'],sh['scopes'],sh['supplier_ids'],sh['email'],sh['notify'],sh['expires'],0,encrypted,hashed,time.time()))
            response['url']=app.config['APP_URL']+'/day/'+value
            if sh['send_email']:queue(sh['email'],'Your wedding-day plan',sh['label']+', here is the wedding-day plan shared with you. Review it and confirm you have the latest version:\n'+response['url'],dedupe='hub-invite:'+identity)
        elif action=='share_revoke':
            owned('hub_shares',identity,wid);db().execute('UPDATE hub_shares SET revoked=1 WHERE id=?',(identity,));db().execute('UPDATE tokens SET used=1 WHERE kind="hub_share" AND wedding_id=? AND json_extract(payload,\'$.share_id\')=?',(wid,identity))
        elif action=='ready':
            if type(body.get('ready')) is not bool:raise ValueError('Check the ready choice.')
            if body['ready'] and readiness(s,rows('hub_events',wid),rows('hub_jobs',wid),rows('hub_tables',wid),rows('hub_shares',wid)) and body.get('checks_reviewed') is not True:raise ValueError('Review the outstanding checks and confirm you have noted them before marking the plan ready.')
            db().execute('UPDATE hub_meta SET ready=? WHERE wedding_id=?',(int(body['ready']),wid))
        else:raise ValueError('Choose a supported Hub action.')
        if state_changed:update_state(w,s,w['revision'])
        db().execute('UPDATE hub_meta SET revision=revision+1,updated=? WHERE wedding_id=?',(time.time(),wid))
        notify(wid,reset_ready=action not in ['ready','job_done','share_create','share_revoke'])
        audit('Wedding Day Hub: '+action,wid)
        return jsonify(ok=True,**response,hub=result(db().execute('SELECT * FROM weddings WHERE id=?',(wid,)).fetchone()))
    def from_link(value):
        t=token_row(value,'hub_share')
        if not t:abort(404,description='This day-plan link expired or was revoked. Ask the couple for a new link.')
        share=db().execute('SELECT * FROM hub_shares WHERE id=? AND wedding_id=?',(json.loads(t['payload']).get('share_id'),t['wedding_id'])).fetchone();w=db().execute('SELECT * FROM weddings WHERE id=?',(t['wedding_id'],)).fetchone()
        if not share or not w or not active_share(share,w):abort(404,description='This day-plan link is no longer available. Ask the couple for a new link.')
        return w,share
    @app.get('/day/<value>')
    def shared_day(value):
        w,sh=from_link(value);view=projection(w,sh);ack=db().execute('SELECT * FROM hub_ack WHERE share_id=?',(sh['id'],)).fetchone();hashed=view_hash(view)
        changes=change_lines(json.loads(ack['snapshot']),stable_view(view)) if ack and ack['content_hash']!=hashed else []
        return render_template('shared_day.html',view=view,label=sh['label'],role=sh['role'],expires=sh['expires'],confirmed=bool(ack and ack['content_hash']==hashed),version_hash=hashed,changes=changes,offline=False)
    @app.get('/day/<value>/status')
    def shared_day_status(value):
        w,sh=from_link(value);return jsonify(hash=view_hash(projection(w,sh)))
    @app.post('/day/<value>/confirm')
    def confirm_shared(value):
        initial_w,initial_sh=from_link(value);rate('hub-confirm-'+initial_sh['id'],60,900,per_ip=False);db().execute('BEGIN IMMEDIATE')
        w,sh=from_link(value);view=projection(w,sh)
        if request.form.get('version_hash')!=view_hash(view):abort(409,description='The plan changed while you were reading. Reload it before confirming.')
        db().execute('INSERT OR REPLACE INTO hub_ack VALUES(?,?,?,?)',(sh['id'],view_hash(view),json.dumps(stable_view(view)),time.time()));return render_template('shared_day.html',view=view,label=sh['label'],role=sh['role'],expires=sh['expires'],confirmed=True,version_hash=view_hash(view),changes=[],offline=False,message='Thank you. The couple can see you confirmed this version.')
    @app.post('/day/<value>/job/<jid>')
    def complete_shared_job(value,jid):
        initial_w,initial_sh=from_link(value);rate('hub-job-'+initial_sh['id'],120,900,per_ip=False);db().execute('BEGIN IMMEDIATE')
        w,sh=from_link(value)
        if 'jobs' not in json.loads(sh['scopes']):abort(403)
        job=owned('hub_jobs',jid,w['id'])
        if job['assigned_share']!=sh['id']:abort(403)
        version=request.form.get('revision');done=request.form.get('done')
        if done not in ['0','1'] or version!=str(job['revision']):abort(409,description='This job changed. Reload the shared plan first.')
        db().execute('UPDATE hub_jobs SET done=?,revision=revision+1 WHERE id=? AND revision=?',(int(done),jid,job['revision']));db().execute('UPDATE hub_meta SET revision=revision+1,updated=? WHERE wedding_id=?',(time.time(),w['id']));return shared_day(value)
    def download(view,profile,kind):
        stamp=datetime.now(timezone.utc).strftime('%d %B %Y, %H:%M UTC')
        if kind=='pdf':return send_file(io.BytesIO(day_pdf(view,profile,stamp)),mimetype='application/pdf',as_attachment=True,download_name='wedding-day-'+profile+'.pdf')
        if kind=='html':
            response=make_response(render_template('day_snapshot.html',view=view,label=profile,stamp=stamp));response.headers['Content-Disposition']='attachment; filename="wedding-day-'+profile+'.html"';return response
        abort(404)
    @app.get('/api/hub/pack/<profile>.<kind>')
    @auth()
    def private_pack(profile,kind):
        if profile not in ['couple',*ROLES]:abort(404)
        return download(projection(wedding(),profile=profile),profile,kind)
    @app.get('/day/<value>/pack.<kind>')
    def shared_pack(value,kind):
        w,sh=from_link(value);return download(projection(w,sh),sh['role'],kind)
    @app.get('/api/hub/seating.csv')
    @auth()
    def seating_csv():
        s=json.loads(wedding()['state']);out=io.StringIO();writer=csv.writer(out);writer.writerow(['Guest','Table','Invitation','Reply'])
        for guest in sorted(s['guests'],key=lambda x:(x['table'],x['name'])):
            writer.writerow([("'"+str(v)) if str(v).lstrip().startswith(('=','+','-','@')) or str(v).startswith(('\t','\r')) else v for v in [guest['name'],guest['table'],guest['attendance'],guest['rsvp']]])
        response=make_response('\ufeff'+out.getvalue());response.headers['Content-Type']='text/csv; charset=utf-8';response.headers['Content-Disposition']='attachment; filename="wedding-seating.csv"';return response
    return notify


def day_pdf(view,label,stamp):
    from xml.sax.saxutils import escape
    from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,Table,TableStyle,KeepTogether
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    import reportlab
    from pathlib import Path
    fonts=Path(reportlab.__file__).parent/'fonts'
    if 'IvoryVera' not in pdfmetrics.getRegisteredFontNames():pdfmetrics.registerFont(TTFont('IvoryVera',str(fonts/'Vera.ttf')))
    styles=getSampleStyleSheet()
    for style in styles.byName.values():style.fontName='IvoryVera'
    styles['BodyText'].fontSize=11;styles['BodyText'].leading=16;styles['Title'].fontSize=23;styles['Title'].leading=29
    buf=io.BytesIO();doc=SimpleDocTemplate(buf,pagesize=A4,rightMargin=40,leftMargin=40,topMargin=42,bottomMargin=46,title=view['names']+' - Wedding Day Hub',author='Ivory Digital / Weddings By Mark',subject='Dated wedding-day pack');story=[]
    def para(value,style='BodyText'):return Paragraph(escape(str(value)).replace('\n','<br/>'),styles[style])
    story.extend([para(view['names'],'Title'),para('Wedding Day Hub - '+label.title(),'Heading2'),para((date.fromisoformat(view['date']).strftime('%d %B %Y') if view['date'] else 'Date to confirm')+' | '+view['timezone']),para('Saved copy: '+stamp+'. This copy will not update. Check the online plan for later changes.'),Spacer(1,18)])
    def section(title,headers,rows,widths):
        story.append(para(title,'Heading2'))
        if not rows:story.append(para('Nothing entered for this section.'));return
        data=[[para(x) for x in headers]]+[[para(x) for x in row] for row in rows]
        table=Table(data,colWidths=widths,repeatRows=1,hAlign='LEFT');table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#e9f0e9')),('VALIGN',(0,0),(-1,-1),'TOP'),('BOTTOMPADDING',(0,0),(-1,-1),9),('TOPPADDING',(0,0),(-1,-1),7),('LINEBELOW',(0,0),(-1,-1),.4,colors.HexColor('#d7ddd7'))]));story.extend([table,Spacer(1,16)])
    if 'timeline' in view:section('Wedding-day timeline',['Time','Activity / location'],[[clock(e['start']),e['title']+'\n'+e['location']+('\n'+e['instructions'] if e['instructions'] else '')] for e in view['timeline']],[70,445])
    if 'contacts' in view:section('Shared supplier contacts',['Supplier','Contact'],[[x['name']+'\n'+x['category'],x['contact'] or 'To confirm'] for x in view['contacts']],[220,295])
    if 'photos' in view:section('Family photograph groups',['Group','Estimate'],[[x['title'],str(x['minutes'])+' min'] for x in view['photos']],[440,75])
    if 'jobs' in view:section('Responsibilities',['Time / person','Job'],[[(clock(j['start']) if j['start'] is not None else 'Time to agree')+'\n'+(j['owner'] or 'Unassigned'),j['title']+'\n'+j['instructions']+'\n'+('Done' if j['done'] else 'To do')] for j in view['jobs']],[145,370])
    if 'seating' in view:section('Guest seating (no dietary or access details)',['Guest','Table / invitation'],[[x['name'],(x['table'] or 'Unseated')+'\n'+x['attendance']+' / '+x['rsvp']] for x in sorted(view['seating'],key=lambda g:(g['table'],g['name']))],[290,225])
    def footer(canvas,document):
        canvas.setFont('IvoryVera',8);canvas.setFillColor(colors.HexColor('#56615a'));canvas.drawString(40,25,'Ivory Digital | Built by Weddings By Mark | Saved day pack');canvas.drawRightString(A4[0]-40,25,str(document.page))
    doc.build(story,onFirstPage=footer,onLaterPages=footer);return buf.getvalue()

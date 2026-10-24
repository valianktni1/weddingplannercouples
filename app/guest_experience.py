"""Published guest information, scoped invitations and course-by-course replies.

Private planning JSON keeps its existing shape. Structured replies are stored separately;
the existing meal field remains a readable summary for the original guest tools/exports.
"""
import copy
import csv
import io
import json
import re
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from flask import abort, jsonify, render_template, request, send_file
from PIL import Image
from .core import digest, date_valid
from .stationery import build_layout, draw_png, validate, RENDER_LOCK

SCHEMA='''CREATE TABLE IF NOT EXISTS guest_replies(
 wedding_id TEXT NOT NULL,guest_id TEXT NOT NULL,choices TEXT NOT NULL DEFAULT '{}',
 meal TEXT NOT NULL DEFAULT '',replied REAL NOT NULL,
 PRIMARY KEY(wedding_id,guest_id),FOREIGN KEY(wedding_id) REFERENCES weddings(id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS guest_invitation_activity(
 token_hash TEXT PRIMARY KEY,wedding_id TEXT NOT NULL,created REAL NOT NULL,mail_id TEXT,
 FOREIGN KEY(wedding_id) REFERENCES weddings(id) ON DELETE CASCADE);'''
TEXT_FIELDS=('order_day','order_evening','food','drinks','evening_food','venue_day','venue_evening')
TIME_FIELDS=('arrival_day','arrival_evening','end_day','end_evening')


def courses_for(site,attendance):
    return [c for c in site.get('courses',[]) if c['audience'] in ('All',attendance)]


def reply_version(guests,site):
    return digest(json.dumps({'guests':[{k:g.get(k,'') for k in ('id','attendance','rsvp','meal','diet','access')} for g in guests],
                              'courses':site.get('courses',[])},sort_keys=True))


def validate_guest_fields(incoming,previous,db,wid):
    result={}
    for key in TEXT_FIELDS:
        v=incoming.get(key,previous.get(key,''))
        if not isinstance(v,str) or len(v)>5000 or '\0' in v:raise ValueError('Keep guest information to 5,000 characters per section.')
        result[key]=v.strip()
    for key in TIME_FIELDS:
        v=incoming.get(key,previous.get(key,''))
        if not isinstance(v,str) or v and not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d',v):raise ValueError('Check the guest arrival and finish times.')
        result[key]=v
    deadline=incoming.get('reply_by',previous.get('reply_by',''))
    if not isinstance(deadline,str) or not date_valid(deadline):raise ValueError('Check the RSVP date.')
    result['reply_by']=deadline
    courses=incoming.get('courses',previous.get('courses',[]))
    if not isinstance(courses,list) or len(courses)>6:raise ValueError('Use up to six meal courses.')
    clean=[];seen=set()
    for course in courses:
        if not isinstance(course,dict):raise ValueError('Check the meal courses.')
        label=course.get('label','');audience=course.get('audience','Day');choices=course.get('choices',[])
        if not isinstance(label,str) or not label.strip() or len(label)>60 or audience not in ('Day','Evening','All'):raise ValueError('Name each course and choose who it is for.')
        label=label.strip();cid=digest(label.casefold()+'|'+audience)[:16]
        if cid in seen:raise ValueError('Use a different name for each course for the same guests.')
        seen.add(cid)
        if not isinstance(choices,list) or not 1<=len(choices)<=12:raise ValueError('Add between one and twelve choices for each course.')
        options=[];labels=set()
        for option in choices:
            text=option.get('label','') if isinstance(option,dict) else option
            if not isinstance(text,str) or not text.strip() or len(text)>100:raise ValueError('Keep meal choices to 100 characters each.')
            text=text.strip()
            if text.casefold() in labels:raise ValueError('Remove the repeated meal choice.')
            labels.add(text.casefold());options.append({'id':digest(text.casefold())[:16],'label':text})
        clean.append({'id':cid,'label':label,'audience':audience,'choices':options})
    result['courses']=clean
    use=incoming.get('use_stationery',previous.get('use_stationery',False))
    if type(use) is not bool:raise ValueError('Choose whether to publish matching stationery.')
    result['use_stationery']=use
    designs=copy.deepcopy(previous.get('_designs',{})) if use else {}
    if use and incoming.get('refresh_stationery',False):designs={}
    if use and not designs:
        for kind in ('day','evening'):
            row=db.execute('SELECT data FROM stationery_drafts WHERE wedding_id=? AND kind=?',(wid,kind)).fetchone()
            if row:
                design=validate(json.loads(row['data']),kind)
                design['recipient']='';design['guest_id']='';designs[kind]=design
                photo=design['collection']=='photo'
                if photo and not db.execute('SELECT 1 FROM uploads WHERE id=? AND wedding_id=? AND kind="cover"',(design['photo'],wid)).fetchone():raise ValueError('Choose a photograph in your saved invitation before publishing it.')
                rendered=build_layout(design,kind,{},Image.new('RGB',(20,20)) if photo else None)
                if rendered.issues:raise ValueError('Check your '+kind+' stationery invitation first. '+rendered.issues[0])
        if not designs:raise ValueError('Save a day or evening invitation in Our stationery first.')
    result['_designs']=designs
    return result


def ics_escape(text):return str(text).replace('\\','\\\\').replace('\r','').replace('\n','\\n').replace(';','\\;').replace(',','\\,')


def fold_ics(line):
    chunks=[];current=''
    for char in line:
        if len((current+char).encode('utf8'))>75:chunks.append(current);current=' '+char
        else:current+=char
    return '\r\n'.join(chunks+[current])


class GuestExperience:
    def __init__(self,app,db,auth,wedding,public_wedding,token_row,rate,update_state,audit):
        self.app=app;self.db=db;self.wedding=wedding;self.public_wedding=public_wedding;self.token_row=token_row;self.rate=rate;self.update_state=update_state;self.audit=audit
        @app.get('/api/guest-summary')
        @auth()
        def guest_summary():return jsonify(self.summary(wedding()))
        @app.get('/api/guest-summary.csv')
        @auth()
        def guest_csv():
            data=self.summary(wedding());out=io.StringIO();writer=csv.writer(out);writer.writerow(['Guest','Invitation','Reply','Meal choices','Dietary needs','Access arrangements','Menu review needed','Reply received (UTC)'])
            def safe(v):
                text=str(v)
                return "'"+text if text.lstrip().startswith(('=','+','-','@')) or text.startswith(('\t','\r')) else text
            for guest in data['guests']:
                writer.writerow([safe(guest[k]) for k in ('name','attendance','rsvp','meal','diet','access','review_needed','replied_at')])
            return send_file(io.BytesIO(('\ufeff'+out.getvalue()).encode()),mimetype='text/csv',as_attachment=True,download_name='our-guest-replies.csv')
        @app.get('/weddings/<slug>/invite/<value>/design/<audience>.png')
        def guest_design(slug,value,audience):
            w,guests=self.authorise(slug,value)
            if audience not in {g['attendance'].lower() for g in guests}:abort(404)
            return self.design(w,audience)
        @app.get('/website/preview/design/<audience>.png')
        @auth()
        def preview_design(audience):return self.design(wedding(),audience)
        @app.get('/weddings/<slug>/invite/<value>/calendar/<audience>.ics')
        def guest_calendar(slug,value,audience):
            w,guests=self.authorise(slug,value)
            if audience not in {g['attendance'].lower() for g in guests}:abort(404)
            return self.calendar(w,audience)

    def authorise(self,slug,value):
        w=self.public_wedding(slug);t=self.token_row(value,'rsvp')
        if not t or t['wedding_id']!=w['id']:abort(404)
        ids=json.loads(t['payload'])['guest_ids'];s=json.loads(w['state']);guests=[copy.deepcopy(g) for g in s['guests'] if g['id'] in ids]
        if not guests:abort(404)
        return w,guests

    def render(self,w,slug,invitation=None,guests=None,preview=False,error='',submitted=None,saved=False,status=200):
        site=json.loads(w['site']);guests=guests or []
        audience=request.args.get('audience','day') if preview else None
        if preview and audience not in ('day','evening','all'):audience='day'
        audiences=sorted({g['attendance'].lower() for g in guests}) if invitation else [audience] if preview and audience!='all' else ['day','evening']
        meals={g['id']:g['meal'] for g in guests}
        replies={row['guest_id']:json.loads(row['choices']) for row in self.db().execute('SELECT * FROM guest_replies WHERE wedding_id=?',(w['id'],)) if row['meal']==meals.get(row['guest_id'])}
        designs={a:site.get('_designs',{}).get('evening' if a=='evening' else 'day') for a in audiences} if invitation or preview else {}
        return render_template('wedding.html',site=site,slug=slug,invitation=invitation,guests=guests,preview=preview,error=error,
                               audiences=audiences,designs=designs,courses={g['id']:courses_for(site,g['attendance']) for g in guests},
                               replies=replies,submitted=submitted,reply_version=reply_version(guests,site),saved=saved,today=date.today().isoformat(),
                               preview_courses={a:courses_for(site,a.title()) for a in audiences},
                               date_label=date.fromisoformat(site['date']).strftime('%A %-d %B %Y') if site.get('date') else 'Date to be confirmed'),status

    def design(self,w,audience):
        if audience not in ('day','evening'):abort(404)
        site=json.loads(w['site']);kind='evening' if audience=='evening' else 'day';data=site.get('_designs',{}).get(kind)
        if not site.get('use_stationery') or not data:abort(404)
        photo=None
        if data.get('photo'):
            f=self.db().execute('SELECT * FROM uploads WHERE id=? AND wedding_id=? AND kind="cover"',(data['photo'],w['id'])).fetchone()
            if f:
                path=Path(self.app.config['DATA_DIR'])/'files'/w['id']/Path(f['path']).name
                try:
                    with Image.open(path) as original:photo=original.convert('RGB')
                except OSError:pass
        self.rate('guest-design-'+w['id'],500,900,per_ip=False)
        if not RENDER_LOCK.acquire(timeout=8):abort(503,description='Your invitation is opening. Please try again in a moment.')
        try:picture=draw_png(build_layout(data,kind,{},photo),1400)
        finally:RENDER_LOCK.release()
        return send_file(io.BytesIO(picture),mimetype='image/png')

    def calendar(self,w,audience):
        site=json.loads(w['site']);start=site.get('arrival_'+audience,'');day=site.get('date','')
        if not day or not start:abort(404)
        zone=ZoneInfo('Europe/London');dt=datetime.fromisoformat(day+'T'+start).replace(tzinfo=zone)
        title=site.get('title','Our wedding')+(' · Evening reception' if audience=='evening' else ' · Wedding day')
        lines=['BEGIN:VCALENDAR','VERSION:2.0','PRODID:-//Ivory Digital//Wedding invitations//EN','CALSCALE:GREGORIAN','BEGIN:VEVENT',
               'UID:'+digest(w['id']+'|'+audience)+'@planner.ivorydigital.uk','DTSTAMP:'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'),
               'DTSTART:'+dt.astimezone(timezone.utc).strftime('%Y%m%dT%H%M%SZ'),'SUMMARY:'+ics_escape(title),
               'LOCATION:'+ics_escape(site.get('venue_'+audience,'')),
               'DESCRIPTION:'+ics_escape(site.get('reception','') if audience=='evening' else site.get('ceremony',''))]
        finish=site.get('end_'+audience,'')
        if finish:
            end=datetime.fromisoformat(day+'T'+finish).replace(tzinfo=zone)
            if end<=dt:end+=timedelta(days=1)
            lines.append('DTEND:'+end.astimezone(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
        lines+=['END:VEVENT','END:VCALENDAR']
        return send_file(io.BytesIO(('\r\n'.join(fold_ics(line) for line in lines)+'\r\n').encode()),mimetype='text/calendar',as_attachment=True,download_name='our-wedding-'+audience+'.ics')

    def respond(self,slug,value):
        w,guests=self.authorise(slug,value);site=json.loads(w['site']);ajax=request.headers.get('X-Requested-With')=='guest-rsvp'
        if request.method=='GET':return self.render(w,slug,value,guests)
        self.rate('rsvp-'+digest(value),30);submitted=request.form.to_dict();errors=[]
        expected=reply_version(guests,site);original_guests=copy.deepcopy(guests)
        if submitted.get('reply_version') and submitted['reply_version']!=expected:
            message='This invitation or menu changed while you were replying. Your answers are still here. Open the invitation in another tab to check the latest details before updating.'
            return (jsonify(error=message),409) if ajax else self.render(w,slug,value,guests,error=message,submitted=submitted,status=409)
        choices={}
        for guest in guests:
            prefix=guest['id']+'-';answer=submitted.get(prefix+'rsvp','');choices[guest['id']]={}
            if answer not in ('Accepted','Declined'):errors.append('Please choose a reply for every person.');continue
            guest['rsvp']=answer
            for key in ('meal','diet','access'):
                v=submitted.get(prefix+key,'').strip()
                if len(v)>160:errors.append('Keep each dietary or access answer to 160 characters.')
                guest[key]=v if answer=='Accepted' else ''
            configured=courses_for(site,guest['attendance'])
            if answer=='Accepted' and configured:
                summary=[]
                for course in configured:
                    option=next((o for o in course['choices'] if o['id']==submitted.get(prefix+'course-'+course['id'])),None)
                    if not option:errors.append('Choose each meal course for every guest who is attending.');continue
                    choices[guest['id']][course['id']]={'course':course['label'],'option':option['id'],'label':option['label']}
                    summary.append(course['label']+': '+option['label'])
                guest['meal']=' · '.join(summary)
        if errors:
            return (jsonify(error=errors[0]),400) if ajax else self.render(w,slug,value,original_guests,error=errors[0],submitted=submitted,status=400)
        # Reload under a write lock, preserving unrelated partner edits made while the form was open.
        self.db().execute('BEGIN IMMEDIATE')
        current=self.db().execute('SELECT * FROM weddings WHERE id=?',(w['id'],)).fetchone();s=json.loads(current['state'])
        current_guests=[g for g in s['guests'] if g['id'] in {x['id'] for x in guests}]
        current_site=json.loads(current['site'])
        if current['suspended'] or current['access_until']<date.today().isoformat() or not current_site.get('published') or not self.token_row(value,'rsvp') or reply_version(current_guests,current_site)!=expected:
            message='The invitation changed while saving. Your answers have not been submitted. Please check the latest invitation.'
            return (jsonify(error=message),409) if ajax else self.render(current,slug,value,current_guests,error=message,submitted=submitted,status=409)
        edited={g['id']:g for g in guests}
        for guest in s['guests']:
            if guest['id'] in edited:
                guest.update({k:edited[guest['id']][k] for k in ('rsvp','meal','diet','access')})
                self.db().execute('INSERT INTO guest_replies VALUES(?,?,?,?,?) ON CONFLICT(wedding_id,guest_id) DO UPDATE SET choices=excluded.choices,meal=excluded.meal,replied=excluded.replied',
                                  (w['id'],guest['id'],json.dumps(choices[guest['id']]),guest['meal'],time.time()))
        self.update_state(current,s,current['revision']);self.audit('Guest RSVP submitted',w['id'])
        if ajax:return jsonify(ok=True,message='Your replies are saved. You can use this invitation link to update them.',reply_version=reply_version(guests,current_site))
        return self.render(current,slug,value,guests,saved=True)

    def summary(self,w):
        state=json.loads(w['state']);site=json.loads(w['site']);stored={r['guest_id']:r for r in self.db().execute('SELECT * FROM guest_replies WHERE wedding_id=?',(w['id'],))}
        totals={a:{s:0 for s in ('Accepted','Waiting','Declined')} for a in ('Day','Evening')};counts={};rows=[]
        for guest in state['guests']:
            totals[guest['attendance']][guest['rsvp']]+=1;row=stored.get(guest['id']);answers=json.loads(row['choices']) if row else {};review=False
            for course in courses_for(site,guest['attendance']):
                bucket=counts.setdefault(course['id'],{'label':course['label'],'audience':course['audience'],'choices':{o['label']:0 for o in course['choices']},'missing':0})
                if guest['rsvp']!='Accepted':continue
                answer=answers.get(course['id']);option=next((o for o in course['choices'] if answer and o['id']==answer.get('option')),None)
                if not row or row['meal']!=guest['meal'] or not option:bucket['missing']+=1;review=True
                else:bucket['choices'][option['label']]+=1
            rows.append({k:guest[k] for k in ('id','name','attendance','rsvp','meal','diet','access')}|{'review_needed':review,'replied_at':datetime.fromtimestamp(row['replied'],timezone.utc).isoformat() if row else ''})
        return {'totals':totals,'courses':list(counts.values()),'guests':rows,'waiting':[g['name'] for g in state['guests'] if g['rsvp']=='Waiting']}

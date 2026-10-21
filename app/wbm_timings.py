"""Explicit WBM-only timing snapshots, pulled by the authenticated booking app.

No guest list, budget, private notes or supplier contacts leave the planner.
No outbound connection or new email is made by this module.
"""
import json
import re
import time
import uuid
from datetime import date
from flask import jsonify, g, abort
from .core import config, empty_state, digest
from .day_hub import timeline, clock

SCHEMA = '''
CREATE TABLE IF NOT EXISTS wbm_timing_links(
 booking_id TEXT PRIMARY KEY,wedding_id TEXT UNIQUE NOT NULL,email TEXT NOT NULL,
 wedding_date TEXT NOT NULL,template TEXT NOT NULL,created REAL NOT NULL,checked_at REAL NOT NULL,
 FOREIGN KEY(wedding_id) REFERENCES weddings(id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS wbm_timing_submissions(
 id TEXT PRIMARY KEY,booking_id TEXT NOT NULL,content_hash TEXT NOT NULL,
 payload TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'queued',message TEXT NOT NULL DEFAULT '',
 created REAL NOT NULL,received REAL,UNIQUE(booking_id,content_hash),
 FOREIGN KEY(booking_id) REFERENCES wbm_timing_links(booking_id) ON DELETE CASCADE);
'''


def register_wbm_timings(app, db, auth, wedding, json_body, audit):
    def valid_link(link, w):
        if not link or not w or w['suspended'] or w['access_until'] < date.today().isoformat():
            return False
        state = json.loads(w['state'])
        return state['date'] == link['wedding_date'] and bool(db().execute(
            'SELECT 1 FROM members m JOIN users u ON u.id=m.user_id WHERE m.wedding_id=? AND lower(u.email)=? AND u.verified=1',
            (w['id'], link['email'])).fetchone())

    def linked(w):
        link = db().execute('SELECT * FROM wbm_timing_links WHERE wedding_id=?', (w['id'],)).fetchone()
        if not config(db()).get('wbm_booking_enabled') or not valid_link(link, w) or time.time()-link['checked_at']>600:
            return None
        return link

    def public_status(row):
        return {k: row[k] for k in ('id', 'status', 'message', 'created', 'received')} if row else None

    def prefill(w, link):
        state = json.loads(w['state']); d = state['day']
        previous = db().execute('SELECT payload FROM wbm_timing_submissions WHERE booking_id=? ORDER BY created DESC LIMIT 1', (link['booking_id'],)).fetchone()
        answers = json.loads(previous['payload'])['answers'] if previous else {}
        answers.update(ceremony_time=clock(d['ceremony']), ceremony_duration=d['ceremonyMinutes'],
            ceremony_venue=d['venue'], reception_same=not bool(d['receptionVenue']) or d['receptionVenue']==d['venue'],
            reception_venue=d['receptionVenue'], first_dance_time=clock(d['firstDance']),
            meal_time=clock(d['meal']), group_photo_time=clock(d['ceremony']+d['ceremonyMinutes']+d['confetti']))
        answers.setdefault('prep_photos', '')  # ask; never assume the coverage purchased
        answers.setdefault('start_choice', 'normal'); answers.setdefault('travel_minutes', 0)
        answers.setdefault('speeches_position', 'After the meal'); answers.setdefault('later_event', False)
        n = len(state['groups']); answers.setdefault('group_count', 'None' if n==0 else '1-5' if n<=5 else '6-10' if n<=10 else 'More than 10')
        answers['_template_revision'] = json.loads(link['template'])['revision']
        return answers

    @app.post('/api/integrations/wbm/timings/link')
    def match_booking():
        body = json_body()
        if set(body) != {'booking_id', 'email', 'wedding_date', 'template'}:
            abort(400)
        if not isinstance(body['booking_id'], str) or not re.fullmatch(r'[0-9a-f-]{36}', body['booking_id']): abort(400)
        if not isinstance(body['email'], str) or not isinstance(body['template'], dict): abort(400)
        if not isinstance(body['template'].get('fields'), list) or not body['template'].get('revision'): abort(400)
        email = body['email'].strip().lower()
        rows = db().execute('SELECT DISTINCT w.* FROM weddings w JOIN members m ON w.id=m.wedding_id JOIN users u ON u.id=m.user_id WHERE lower(u.email)=? AND u.verified=1', (email,)).fetchall()
        rows = [w for w in rows if not w['suspended'] and w['access_until']>=date.today().isoformat() and json.loads(w['state'])['date']==body['wedding_date']]
        if not rows: abort(404, description='No verified planner with the matching email and wedding date.')
        if len(rows)!=1: abort(409, description='More than one matching planner needs review.')
        w=rows[0]
        db().execute('BEGIN IMMEDIATE')
        old=db().execute('SELECT * FROM wbm_timing_links WHERE booking_id=? OR wedding_id=?', (body['booking_id'],w['id'])).fetchall()
        if old and (len(old)!=1 or old[0]['booking_id']!=body['booking_id'] or old[0]['wedding_id']!=w['id'] or old[0]['email']!=email or old[0]['wedding_date']!=body['wedding_date']):
            abort(409, description='An existing booking link needs review; it was not changed.')
        if not old:
            db().execute('INSERT INTO wbm_timing_links VALUES(?,?,?,?,?,?,?)', (body['booking_id'],w['id'],email,body['wedding_date'],json.dumps(body['template']),time.time(),time.time()))
            audit('WBM photography booking linked for explicit timing submissions',w['id'])
        else:
            db().execute('UPDATE wbm_timing_links SET template=?,checked_at=? WHERE booking_id=?', (json.dumps(body['template']),time.time(),body['booking_id']))
        state=json.loads(w['state'])
        # Signing in or accepting an invite alone never holds a booking email.
        active=state['day']!=empty_state()['day'] or bool(db().execute('SELECT 1 FROM hub_events WHERE wedding_id=? LIMIT 1',(w['id'],)).fetchone())
        pending=db().execute("SELECT * FROM wbm_timing_submissions WHERE booking_id=? AND status='queued' ORDER BY created,id LIMIT 1", (body['booking_id'],)).fetchone()
        latest=db().execute('SELECT status FROM wbm_timing_submissions WHERE booking_id=? ORDER BY created DESC,id DESC LIMIT 1',(body['booking_id'],)).fetchone()
        payload=json.loads(pending['payload']) if pending else None
        return jsonify(booking_id=body['booking_id'],wedding_id=w['id'],email=email,wedding_date=state['date'],active=active,submission=payload,latest_status=latest['status'] if latest else None)

    @app.get('/api/wbm-timings')
    @auth()
    def couple_status():
        w=wedding();link=linked(w)
        if not link: return jsonify(linked=False)
        recent=db().execute('SELECT * FROM wbm_timing_submissions WHERE booking_id=? ORDER BY created DESC,id DESC LIMIT 1',(link['booking_id'],)).fetchone()
        state=json.loads(w['state']); events=db().execute('SELECT * FROM hub_events WHERE wedding_id=?',(w['id'],)).fetchall()
        return jsonify(linked=True,template=json.loads(link['template']),answers=prefill(w,link),revision=w['revision'],
            hub_revision=(db().execute('SELECT revision FROM hub_meta WHERE wedding_id=?',(w['id'],)).fetchone() or {'revision':0})['revision'],
            timeline=timeline(state,events,'photographer'),groups=[x['title'] for x in state['groups']],
            latest=public_status(recent))

    @app.post('/api/wbm-timings')
    @auth()
    def submit():
        w=wedding(True); link=linked(w)
        if not link: abort(409,description='No active WBM photography booking is linked. Nothing was submitted.')
        body=json_body()
        if body.get('confirmed') is not True or not isinstance(body.get('answers'),dict): abort(400)
        db().execute('BEGIN IMMEDIATE')
        # Snapshot only the saved revision displayed in the explicit review.
        w=wedding(True); meta=db().execute('SELECT revision FROM hub_meta WHERE wedding_id=?',(w['id'],)).fetchone()
        if body.get('revision')!=w['revision'] or body.get('hub_revision')!=(meta['revision'] if meta else 0): abort(409,description='The plan changed. Reopen the preview before sending.')
        schema=json.loads(link['template']); answers=body['answers']
        if answers.get('_template_revision')!=schema['revision']: abort(409,description='Mark’s questions changed. Reopen the preview before sending.')
        allowed={q['key'] for q in schema['fields'] if q['enabled']}|{'_template_revision'}
        if set(answers)-allowed or len(json.dumps(answers))>50000: abort(400)
        # Definitive photography validation/calculation happens in the booking
        # app. Never claim receipt until that app acknowledges the snapshot.
        state=json.loads(w['state']); events=db().execute('SELECT * FROM hub_events WHERE wedding_id=?',(w['id'],)).fetchall()
        package={'booking_id':link['booking_id'],'wedding_id':w['id'],'email':link['email'],'wedding_date':link['wedding_date'],
            'answers':answers,'timeline':timeline(state,events,'photographer'),'groups':[x['title'] for x in state['groups']]}
        hashed=digest(json.dumps(package,sort_keys=True,separators=(',',':')))
        old=db().execute('SELECT * FROM wbm_timing_submissions WHERE booking_id=? AND content_hash=?',(link['booking_id'],hashed)).fetchone()
        if old and old['status'] in ('queued','received'): return jsonify(**public_status(old))
        if old: abort(409,description='This version needs attention. Correct the details shown before resubmitting.')
        sid=str(uuid.uuid4());package.update(submission_id=sid,submitted_at=time.time())
        db().execute('INSERT INTO wbm_timing_submissions(id,booking_id,content_hash,payload,created) VALUES(?,?,?,?,?)',(sid,link['booking_id'],hashed,json.dumps(package),package['submitted_at']))
        audit('Final photography timings explicitly queued for Mark',w['id'])
        return jsonify(id=sid,status='queued',message='Saved for transfer. Mark’s booking app has not acknowledged receipt yet.'),201

    @app.post('/api/integrations/wbm/timings/<booking_id>/ack')
    def acknowledge(booking_id):
        body=json_body()
        if body.get('status') not in ('received','needs_attention') or not isinstance(body.get('submission_id'),str): abort(400)
        row=db().execute('SELECT * FROM wbm_timing_submissions WHERE booking_id=? AND id=?',(booking_id,body['submission_id'])).fetchone()
        if not row: abort(404)
        if row['status']=='received': return jsonify(ok=True)
        message=str(body.get('message') or '')[:500]
        db().execute('UPDATE wbm_timing_submissions SET status=?,message=?,received=? WHERE id=?',(body['status'],message,time.time() if body['status']=='received' else None,row['id']))
        return jsonify(ok=True)

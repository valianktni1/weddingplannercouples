from datetime import date, timedelta
import json
import time

from test_app import app, database
from test_booking_connection import setup, body

PATH = '/api/integrations/control-centre/overview'
KEY = 'separate-dashboard-key-' + 'x'*40


def enable(monkeypatch):
    monkeypatch.setenv('PLANNER_CONTROL_CENTRE_KEY', KEY)
    monkeypatch.setenv('PLANNER_CONTROL_CENTRE_ENABLED', 'true')
    return {'X-Control-Centre-Key': KEY}


def dump(app):
    db = database(app)
    result = '\n'.join(db.iterdump())
    db.close()
    return result


def test_disabled_scoped_and_does_not_create_sessions_or_write(app, monkeypatch):
    c = app.test_client()
    original = dump(app)
    assert c.get(PATH).status_code == 401
    h = enable(monkeypatch)
    monkeypatch.setenv('PLANNER_CONTROL_CENTRE_ENABLED', 'false')
    assert c.get(PATH, headers=h).status_code == 503
    monkeypatch.setenv('PLANNER_CONTROL_CENTRE_ENABLED', 'true')
    response = c.get(PATH, headers=h)
    assert response.status_code == 200
    assert 'Set-Cookie' not in response.headers
    assert response.headers['Cache-Control'] == 'no-store'
    assert c.post(PATH, headers=h, json={}).status_code == 405
    assert dump(app) == original
    assert c.get('/api/integrations/wbm/status', headers=h).status_code == 401
    assert c.get('/api/admin', headers=h).status_code == 401


def test_real_invitation_flow_and_private_data_stay_independent(app, monkeypatch):
    admin, booking_headers = setup(app)
    c = app.test_client()
    result = c.post('/api/integrations/wbm/invitations', headers=booking_headers, json=body())
    assert result.status_code == 201
    wid = result.json['wedding_id']
    h = enable(monkeypatch)
    db = database(app)
    until = (date.today() + timedelta(days=5)).isoformat()
    db.execute('UPDATE weddings SET access_until=? WHERE id=?', (until, wid))
    db.execute("INSERT OR REPLACE INTO settings VALUES('worker_heartbeat',?)", (json.dumps(time.time()),))
    db.execute('INSERT INTO hub_meta(wedding_id,last_active) VALUES(?,?)', ('wu1', time.time()))
    state = json.loads(db.execute('SELECT state FROM weddings WHERE id=?', (wid,)).fetchone()[0])
    state['private_note'] = 'PRIVATE-NOTE-NEVER-EXPORT'
    db.execute('UPDATE weddings SET state=? WHERE id=?', (json.dumps(state), wid))
    db.commit(); db.close()
    before = dump(app)
    response = c.get(PATH, headers=h)
    assert dump(app) == before
    data = response.json
    assert data['counts'] == dict(active_accounts=3, awaiting_couples=1, invitation_problems=0,
                                  expiring_access=1, active_last_seven_days=1)
    assert data['worker_status'] == 'ok'
    assert data['queues']['awaiting_couples'][0]['title'] == 'Sophie & Dan'
    for private in ('PRIVATE-NOTE-NEVER-EXPORT', 'sophie@example.com', KEY, 'wbm_booking_key_hash', 'welcome/'):
        assert private not in response.text
    assert c.get(PATH, headers={'X-Control-Centre-Key':booking_headers['Authorization'][7:]}).status_code == 401
    assert c.get('/api/integrations/wbm/status', headers=booking_headers).status_code == 200
    duplicate = c.post('/api/integrations/wbm/invitations', headers=booking_headers, json=body(booking_id=result.json['booking_id']))
    assert duplicate.status_code == 200
    db = database(app)
    db.execute("UPDATE mail SET status='retry' WHERE id=(SELECT mail_id FROM wbm_booking_invitations WHERE wedding_id=?)", (wid,))
    db.commit(); db.close()
    assert c.get(PATH, headers=h).json['counts']['invitation_problems'] == 1
    db = database(app)
    db.execute('INSERT INTO cancelled_couple_invitations VALUES(?,?)', (wid, time.time()))
    db.commit(); db.close()
    data = c.get(PATH, headers=h).json
    assert data['counts']['active_accounts'] == 2
    assert data['counts']['invitation_problems'] == 0
    assert data['counts']['expiring_access'] == 0


def test_summary_limits_rows_and_excludes_expired_suspended_and_joined(app, monkeypatch):
    h = enable(monkeypatch)
    db = database(app)
    for i in range(8):
        uid = 'pending'+str(i); wid = 'w'+uid
        db.execute('INSERT INTO users(id,email,password,created) VALUES(?,?,?,?)', (uid,uid+'@example.com','unused',time.time()))
        state = json.dumps({'names':['Example',str(i)],'date':''})
        db.execute('INSERT INTO weddings(id,state,access_until,created) VALUES(?,?,?,?)',
                   (wid,state,(date.today()+timedelta(days=7)).isoformat(),time.time()))
        db.execute('INSERT INTO members VALUES(?,?)',(wid,uid))
        db.execute("INSERT INTO tokens(hash,kind,user_id,wedding_id,expires) VALUES(?,'welcome',?,?,?)",(uid,uid,wid,time.time()+3600))
    db.execute("UPDATE weddings SET suspended=1 WHERE id='wu1'")
    db.execute("UPDATE weddings SET access_until='2000-01-01' WHERE id='wu2'")
    db.commit(); db.close()
    result = app.test_client().get(PATH,headers=h).json
    assert result['counts']['active_accounts'] == 8
    assert result['counts']['invitation_problems'] == 8
    assert result['counts']['expiring_access'] == 8
    assert len(result['queues']['invitation_problems']) == 5
    assert len(result['queues']['expiring_access']) == 5
    assert result['worker_status'] == 'unknown'

from concurrent.futures import ThreadPoolExecutor
from datetime import date,timedelta
import json
import uuid

from test_onboarding import prepared
from test_app import app,headers,database,login


def setup(app):
    admin=prepared(app)
    response=admin.post('/api/admin/booking-connection',json={'enabled':True,'rotate':True},headers=headers(admin,'/ivoryadmin'))
    assert response.status_code==200
    return admin,{'Authorization':'Bearer '+response.json['key']}


def body(**extra):
    return {'booking_id':str(uuid.uuid4()),'first_name':'Sophie','partner_first_name':'Dan','email':'sophie@example.com','wedding_date':(date.today()+timedelta(days=365)).isoformat(),**extra}


def test_scoped_auth_and_admin_key_privacy(app):
    c=app.test_client();assert c.post('/api/integrations/wbm/invitations',json=body()).status_code==401
    admin,h=setup(app)
    assert c.get('/api/integrations/wbm/status',headers=h).json['ready']
    assert 'wbm_booking_key_hash' not in admin.get('/api/admin').json['settings']
    assert c.post('/api/admin/booking-connection',json={'enabled':True},headers=h).status_code==403
    admin.post('/api/admin/booking-connection',json={'enabled':False},headers=headers(admin,'/ivoryadmin'))
    assert c.post('/api/integrations/wbm/invitations',json=body(),headers=h).status_code==409
    admin.post('/api/admin/booking-connection',json={'enabled':True,'rotate':True},headers=headers(admin,'/ivoryadmin'))
    assert c.get('/api/integrations/wbm/status',headers=h).status_code==401


def test_creates_one_complimentary_invitation_until_wedding_plus_30(app):
    admin,h=setup(app);c=app.test_client();payload=body()
    r=c.post('/api/integrations/wbm/invitations',json=payload,headers=h)
    assert r.status_code==201,r.json
    assert 'Set-Cookie' not in r.headers
    wid=r.json['wedding_id']
    for _ in range(3):
        again=c.post('/api/integrations/wbm/invitations',json=payload,headers=h)
        assert again.status_code==200 and again.json['wedding_id']==wid
    status=c.get('/api/integrations/wbm/invitations/'+payload['booking_id'],headers=h)
    assert status.json['status']=='queued'
    db=database(app)
    w=db.execute('SELECT * FROM weddings WHERE id=?',(wid,)).fetchone();state=json.loads(w['state'])
    assert state['names']==['Sophie','Dan'] and state['date']==payload['wedding_date']
    assert w['access_kind']=='Complimentary'
    assert w['access_until']==(date.fromisoformat(payload['wedding_date'])+timedelta(days=30)).isoformat()
    assert db.execute('SELECT count(*) FROM purchases WHERE wedding_id=?',(wid,)).fetchone()[0]==0
    assert db.execute('SELECT count(*) FROM mail WHERE to_address=?',(payload['email'],)).fetchone()[0]==1
    db.execute('UPDATE mail SET status="sent" WHERE to_address=?',(payload['email'],));db.commit();db.close()
    assert c.get('/api/integrations/wbm/invitations/'+payload['booking_id'],headers=h).json['status']=='sent'
    changed=c.post('/api/integrations/wbm/invitations',json={**payload,'partner_first_name':'Someone else'},headers=h)
    assert changed.status_code==409


def test_existing_accounts_invalid_inputs_and_unconfigured_mail_do_not_create(app):
    admin,h=setup(app);c=app.test_client()
    assert c.post('/api/integrations/wbm/invitations',json=body(email='one@example.com'),headers=h).status_code==409
    for patch in [{'wedding_date':''},{'first_name':''},{'email':'invalid'},{'wedding_date':'2020-01-01'},{'first_name':'Sophie\nBCC:bad'},{'access':'Paid'}]:
        assert c.post('/api/integrations/wbm/invitations',json=body(**patch),headers=h).status_code==400
    admin.put('/api/admin/settings',json={'terms_text':''},headers=headers(admin,'/ivoryadmin'))
    assert c.post('/api/integrations/wbm/invitations',json=body(),headers=h).status_code==400
    db=database(app);assert db.execute('SELECT count(*) FROM wbm_booking_invitations').fetchone()[0]==0;db.close()


def test_concurrent_replays_queue_once(app):
    admin,h=setup(app);payload=body()
    def post(_):
        with app.test_client() as c:
            r=c.post('/api/integrations/wbm/invitations',json=payload,headers=h)
            return r.status_code,r.json
    with ThreadPoolExecutor(max_workers=2) as pool: result=list(pool.map(post,range(2)))
    assert sorted(r[0] for r in result)==[200,201],result
    assert len({r[1]['wedding_id'] for r in result})==1
    db=database(app);assert db.execute('SELECT count(*) FROM mail WHERE to_address=?',(payload['email'],)).fetchone()[0]==1;db.close()


def test_status_follows_deliberate_admin_resend(app):
    admin,h=setup(app);c=app.test_client();payload=body()
    r=c.post('/api/integrations/wbm/invitations',json=payload,headers=h);wid=r.json['wedding_id']
    db=database(app);db.execute('UPDATE mail SET status="failed" WHERE to_address=?',(payload['email'],));db.commit();db.close()
    url='/api/integrations/wbm/invitations/'+payload['booking_id']
    assert c.get(url,headers=h).json['status']=='failed'
    assert admin.post('/api/admin/couples/'+wid+'/resend-invitation',json={},headers=headers(admin,'/ivoryadmin')).status_code==200
    assert c.get(url,headers=h).json['status']=='queued'

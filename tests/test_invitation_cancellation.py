import json
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from app.core import config, digest, initialise
from app.worker import current_mail, prune_tokens
from test_app import app, csrf, database, headers, login
from test_onboarding import prepared, invite, invitation
from test_booking_connection import setup as booking_setup, body as booking_body


def action(admin, wid, name, **body):
    return admin.post('/api/admin/couples/'+wid+'/'+name+'-invitation',
                      json={'confirmed': True, **body}, headers=headers(admin, '/ivoryadmin'))


def test_cancel_removes_from_active_list_revokes_links_and_stops_queued_mail(app):
    admin=prepared(app);wid=invite(admin).json['wedding_id'];path,mail=invitation(app)
    visitor=app.test_client();form_csrf=csrf(visitor,path)
    assert action(admin,wid,'cancel',confirmed=False).status_code==400
    assert visitor.get(path).status_code==200
    assert action(admin,wid,'cancel').status_code==200
    data=admin.get('/api/admin').json
    assert wid not in {w['id'] for w in data['couples']}
    assert [w['id'] for w in data['cancelled_invitations']]==[wid]
    assert visitor.get(path).status_code==400
    # A welcome form opened before cancellation must also fail when submitted.
    assert visitor.post(path,data={'csrf':form_csrf,'password':'long-new-password','accept_terms':'yes'}).status_code==400
    db=database(app)
    assert db.execute('SELECT status FROM mail WHERE id=?',(mail['id'],)).fetchone()[0]=='cancelled'
    assert current_mail(db,mail,config(db),datetime.now(ZoneInfo('UTC'))) is None
    assert db.execute('SELECT count(*) FROM audit WHERE wedding_id=? AND action LIKE "%invitation cancelled%"',(wid,)).fetchone()[0]==1
    assert db.execute('SELECT suspended FROM weddings WHERE id=?',(wid,)).fetchone()[0]==1
    assert db.execute('SELECT state FROM weddings WHERE id=?',(wid,)).fetchone() # no destructive deletion
    db.close()
    assert action(admin,wid,'cancel').status_code==200
    assert admin.get('/api/admin/couples/'+wid+'/invitation-preview').status_code==409
    assert admin.post('/api/admin/couples/'+wid+'/resend-invitation',json={},headers=headers(admin,'/ivoryadmin')).status_code==409
    assert admin.post('/api/admin/access/'+wid,json={'access':'Complimentary','until':'2030-01-01','reason':'test'},headers=headers(admin,'/ivoryadmin')).status_code==409


def test_restore_sends_nothing_old_links_stay_dead_and_new_link_works(app):
    admin=prepared(app);wid=invite(admin).json['wedding_id'];old,mail=invitation(app)
    assert action(admin,wid,'cancel').status_code==200
    assert action(admin,wid,'restore',confirmed=False).status_code==400
    db=database(app);db.execute('UPDATE tokens SET expires=0 WHERE wedding_id=?',(wid,));prune_tokens(db,time.time());db.commit();db.close()
    assert action(admin,wid,'restore').status_code==200
    # Housekeeping after restoration must not remove the invitation provenance.
    db=database(app);prune_tokens(db,time.time());db.commit()
    assert db.execute('SELECT count(*) FROM mail WHERE to_address=?',(mail['to_address'],)).fetchone()[0]==1
    assert db.execute('SELECT suspended FROM weddings WHERE id=?',(wid,)).fetchone()[0]==0
    db.close()
    assert not admin.get('/api/admin').json['cancelled_invitations']
    assert app.test_client().get(old).status_code==400
    assert admin.get('/api/admin/couples/'+wid+'/invitation-preview').status_code==200
    assert admin.post('/api/admin/couples/'+wid+'/resend-invitation',json={},headers=headers(admin,'/ivoryadmin')).status_code==200
    new,_=invitation(app);assert new!=old
    visitor=app.test_client()
    assert visitor.post(new,data={'csrf':csrf(visitor,new),'password':'long-new-password','accept_terms':'yes'}).status_code==302
    assert visitor.get('/api/state').status_code==200
    assert action(admin,wid,'cancel').status_code==409


def test_cannot_cancel_accepted_or_self_registered_accounts(app):
    admin=prepared(app)
    assert action(admin,'wu1','cancel').status_code==409
    wid=invite(admin).json['wedding_id'];path,_=invitation(app);c=app.test_client()
    assert c.post(path,data={'csrf':csrf(c,path),'password':'long-new-password','accept_terms':'yes'}).status_code==302
    assert action(admin,wid,'cancel').status_code==409
    assert c.get('/api/state').status_code==200
    assert action(admin,wid,'restore').status_code==409
    assert action(admin,'not-found','cancel').status_code==404


def test_payment_history_blocks_cancellation(app):
    admin=prepared(app);wid=invite(admin).json['wedding_id'];db=database(app)
    db.execute('INSERT INTO purchases(id,wedding_id,amount,terms,created) VALUES(?,?,?,?,?)',('p',wid,2500,'{}',time.time()));db.commit();db.close()
    assert action(admin,wid,'cancel').status_code==409
    assert not admin.get('/api/admin').json['cancelled_invitations']


@pytest.mark.parametrize('name',['cancel','restore'])
def test_admin_auth_and_csrf_required(app,name):
    admin=prepared(app);wid=invite(admin).json['wedding_id'];url='/api/admin/couples/'+wid+'/'+name+'-invitation'
    assert admin.post(url,json={'confirmed':True}).status_code==403
    c=login(app)
    assert c.post(url,json={'confirmed':True},headers=headers(c)).status_code==403
    anonymous=app.test_client()
    assert anonymous.post(url,json={'confirmed':True},headers=headers(anonymous,'/login')).status_code==401


def test_booking_replays_do_not_resend_cancelled_invitation(app):
    admin,h=booking_setup(app);c=app.test_client();body=booking_body()
    first=c.post('/api/integrations/wbm/invitations',json=body,headers=h).json;wid=first['wedding_id']
    assert action(admin,wid,'cancel').status_code==200
    for _ in range(2):
        r=c.post('/api/integrations/wbm/invitations',json=body,headers=h)
        assert r.status_code==200 and r.json['status']=='cancelled' and r.json['wedding_id']==wid
    assert c.get('/api/integrations/wbm/invitations/'+body['booking_id'],headers=h).json['status']=='cancelled'
    db=database(app)
    assert db.execute('SELECT count(*) FROM mail WHERE to_address=?',(body['email'],)).fetchone()[0]==1
    assert db.execute('SELECT count(*) FROM wbm_booking_invitations').fetchone()[0]==1
    db.close()
    assert action(admin,wid,'restore').status_code==200
    assert c.get('/api/integrations/wbm/invitations/'+body['booking_id'],headers=h).json['status']=='cancelled' # no new email until an explicit resend


def test_cancellation_invalidates_other_account_tokens_and_sessions(app):
    admin=prepared(app);wid=invite(admin).json['wedding_id'];db=database(app)
    uid=db.execute('SELECT user_id FROM members WHERE wedding_id=?',(wid,)).fetchone()[0]
    for kind in ['reset','verify','partner']:
        db.execute('INSERT INTO tokens(hash,kind,user_id,wedding_id,expires) VALUES(?,?,?,?,?)',(digest(kind),kind,uid,wid,time.time()+3600))
    db.execute('INSERT INTO sessions(id,user_id,csrf,expires) VALUES(?,?,?,?)',('test-session',uid,'csrf',time.time()+3600));db.commit();db.close()
    assert action(admin,wid,'cancel').status_code==200
    db=database(app)
    assert db.execute('SELECT count(*) FROM tokens WHERE user_id=? AND used=0',(uid,)).fetchone()[0]==0
    assert db.execute('SELECT count(*) FROM sessions WHERE user_id=?',(uid,)).fetchone()[0]==0
    db.close()


def test_additive_schema_survives_reinitialisation(app):
    admin=prepared(app);wid=invite(admin).json['wedding_id'];assert action(admin,wid,'cancel').status_code==200
    initialise(app.config['DATA_DIR'])
    assert admin.get('/api/admin').json['cancelled_invitations'][0]['id']==wid

import json
import re
from datetime import date,timedelta,datetime
from zoneinfo import ZoneInfo
import pytest
from app.core import config,totp
from app.worker import current_mail
from test_app import app,login,headers,database,csrf


def prepared(app):
    admin=login(app,'mark@example.com',True)
    r=admin.put('/api/admin/settings',json={'sender':'planner@example.com','terms_text':'Invitation terms','privacy_text':'Invitation privacy'},headers=headers(admin,'/ivoryadmin'))
    assert r.status_code==200
    return admin


def invite(admin,**extra):
    body={'names':['Sam','Alex'],'email':'new-couple@example.com','date':'2027-06-19','access':'Complimentary','until':'2030-01-01',**extra}
    return admin.post('/api/admin/couples/invite',json=body,headers=headers(admin,'/ivoryadmin'))


def invitation(app):
    db=database(app);row=db.execute('SELECT * FROM mail WHERE subject="Your wedding planner invitation" ORDER BY created DESC LIMIT 1').fetchone();db.close()
    path=re.search(r'http://localhost(/welcome/\S+)',row['body']).group(1)
    return path,row


def test_pending_admin_survives_reopening_admin_and_login_and_reload(app):
    c=app.test_client()
    r=c.post('/ivoryadmin/login',data={'csrf':csrf(c,'/ivoryadmin/login'),'email':'mark@example.com','password':'long-test-password'})
    assert r.location.endswith('/two-step')
    assert c.get('/api/admin').status_code==401 # still requires the second factor
    for path in ['/ivoryadmin','/ivoryadmin/login']:
        assert c.get(path).location.endswith('/two-step')
    c.get('/') # switching away and returning does not consume the challenge
    for _ in range(3): assert 'Your sign-in code' in c.get('/ivoryadmin/two-step').text
    bad=c.post('/ivoryadmin/two-step',data={'csrf':csrf(c,'/ivoryadmin/two-step'),'code':'invalid'})
    assert bad.status_code==400 and 'name="code"' in bad.text and 'latest code' in bad.text
    assert c.post('/ivoryadmin/two-step',data={'csrf':csrf(c,'/ivoryadmin/two-step'),'code':totp('JBSWY3DPEHPK3PXP')}).location.endswith('/ivoryadmin')
    assert c.get('/api/admin').status_code==200
    assert c.get('/ivoryadmin/two-step').location.endswith('/ivoryadmin')


def test_expired_pending_session_requires_password_again(app):
    c=app.test_client();c.post('/ivoryadmin/login',data={'csrf':csrf(c,'/ivoryadmin/login'),'email':'mark@example.com','password':'long-test-password'})
    db=database(app);db.execute('UPDATE sessions SET expires=0 WHERE pending="admin"');db.commit();db.close()
    assert c.get('/ivoryadmin/two-step').location.endswith('/ivoryadmin/login')
    assert c.get('/api/admin').status_code==401


def test_complimentary_invitation_password_terms_acceptance_and_repeat(app):
    admin=prepared(app);r=invite(admin);assert r.status_code==201,r.json
    wid=r.json['wedding_id'];path,row=invitation(app)
    assert 'Complimentary access' in row['body']
    assert admin.get('/api/admin').json['couples'][0]['invitation_pending']
    c=app.test_client();html=c.get(path).text
    assert 'No payment is needed' in html and 'Invitation terms' in html
    assert c.post(path,data={'csrf':csrf(c,path),'password':'a-new-long-password'}).status_code==400
    assert c.post(path,data={'csrf':csrf(c,path),'password':'a-new-long-password','accept_terms':'yes'}).status_code==302
    state=c.get('/api/state').json
    assert state['state']['names']==['Sam','Alex'] and state['access_until']=='2030-01-01' and not state['readonly']
    db=database(app);assert db.execute('SELECT access_kind FROM weddings WHERE id=?',(wid,)).fetchone()[0]=='Complimentary'
    assert db.execute('SELECT count(*) FROM purchases WHERE wedding_id=?',(wid,)).fetchone()[0]==0;db.close()
    assert c.post(path,data={'csrf':csrf(c,'/app'),'password':'replace-long-password','accept_terms':'yes'}).status_code==400
    assert admin.post('/api/admin/couples/'+wid+'/resend-invitation',json={},headers=headers(admin,'/ivoryadmin')).status_code==400
    assert not next(w for w in admin.get('/api/admin').json['couples'] if w['id']==wid)['invitation_pending']


def test_trial_starts_on_acceptance_not_when_admin_invites(app):
    admin=prepared(app);r=invite(admin,access='Trial',until='');assert r.status_code==201
    path,row=invitation(app);db=database(app);db.execute('UPDATE weddings SET access_until="2020-01-01" WHERE id=?',(r.json['wedding_id'],));days=config(db)['trial_days'];db.commit();db.close()
    c=app.test_client();assert c.post(path,data={'csrf':csrf(c,path),'password':'new-long-password','accept_terms':'yes'}).status_code==302
    assert c.get('/api/state').json['access_until']==(date.today()+timedelta(days=days)).isoformat()


def test_resend_invalidates_old_email_link_and_worker_cancels_it(app):
    admin=prepared(app);r=invite(admin);wid=r.json['wedding_id'];old,oldrow=invitation(app)
    assert admin.post('/api/admin/couples/'+wid+'/resend-invitation',json={},headers=headers(admin,'/ivoryadmin')).status_code==200
    new,newrow=invitation(app);assert old!=new
    c=app.test_client();assert c.get(old).status_code==400 and c.get(new).status_code==200
    db=database(app);now=datetime.now(ZoneInfo('UTC'));assert current_mail(db,oldrow,config(db),now) is None;assert current_mail(db,newrow,config(db),now)==newrow['body'];db.close()


def test_invitation_does_not_replace_existing_account_or_allow_couple_admin_access(app):
    admin=prepared(app);assert invite(admin,email='one@example.com').status_code==409
    db=database(app);assert db.execute('SELECT count(*) FROM weddings').fetchone()[0]==2;db.close()
    c=login(app);assert c.post('/api/admin/couples/invite',json={},headers=headers(c)).status_code==403
    assert c.get('/welcome/not-a-token').status_code==400
    assert admin.post('/api/admin/couples/invite',json={},headers={}).status_code==403


@pytest.mark.parametrize('extra',[{'names':['Sam','']},{'email':'invalid'},{'date':'bad-date'},{'until':'2020-01-01'},{'access':'Paid'}])
def test_invalid_invitations_do_not_create_accounts(app,extra):
    admin=prepared(app);assert invite(admin,**extra).status_code==400
    db=database(app);assert db.execute('SELECT count(*) FROM weddings').fetchone()[0]==2;db.close()


def test_missing_email_or_policies_rolls_back_account(app,monkeypatch):
    admin=prepared(app);monkeypatch.delenv('SMTP_HOST');assert invite(admin).status_code==400
    db=database(app);assert db.execute('SELECT count(*) FROM weddings').fetchone()[0]==2;db.close()


def test_invitation_expiry_does_not_activate_or_allow_password_login(app):
    admin=prepared(app);r=invite(admin);path,row=invitation(app)
    c=app.test_client();assert c.get(path).status_code==200 # mail-scanner GET does not consume it
    assert c.get(path).status_code==200
    db=database(app);db.execute('UPDATE tokens SET expires=0 WHERE kind="welcome"');db.commit();db.close()
    assert c.get(path).status_code==400
    assert c.post(path,data={'csrf':csrf(c,'/login'),'password':'new-long-password','accept_terms':'yes'}).status_code==400
    assert c.get('/api/state').status_code==401


def test_invitation_records_original_policies_and_preserves_longer_access(app):
    admin=prepared(app);r=invite(admin);wid=r.json['wedding_id'];path,row=invitation(app)
    assert admin.put('/api/admin/settings',json={'terms_text':'Changed terms','privacy_text':'Changed privacy'},headers=headers(admin,'/ivoryadmin')).status_code==200
    assert admin.post('/api/admin/access/'+wid,json={'access':'Complimentary','until':'2032-01-01','reason':'Extended before acceptance'},headers=headers(admin,'/ivoryadmin')).status_code==200
    c=app.test_client();assert c.post(path,data={'csrf':csrf(c,path),'password':'new-long-password','accept_terms':'yes'}).status_code==302
    assert c.get('/api/state').json['access_until']=='2032-01-01'
    db=database(app);record=db.execute('SELECT * FROM policy_acceptances WHERE wedding_id=?',(wid,)).fetchone();db.close()
    assert record['terms']=='Invitation terms' and record['privacy']=='Invitation privacy'


def test_missing_policies_or_suspended_invitation_cannot_activate(app):
    admin=prepared(app);assert admin.put('/api/admin/settings',json={'privacy_text':''},headers=headers(admin,'/ivoryadmin')).status_code==200
    assert invite(admin).status_code==400
    assert admin.put('/api/admin/settings',json={'privacy_text':'Privacy restored'},headers=headers(admin,'/ivoryadmin')).status_code==200
    r=invite(admin);path,row=invitation(app);db=database(app);db.execute('UPDATE weddings SET suspended=1 WHERE id=?',(r.json['wedding_id'],));db.commit();db.close()
    c=app.test_client();assert c.get(path).status_code==403
    assert c.post(path,data={'csrf':csrf(c,'/login'),'password':'new-long-password','accept_terms':'yes'}).status_code==403


def test_housekeeping_preserves_resend_for_long_expired_invitation(app):
    import time
    from app.worker import prune_tokens
    admin=prepared(app);r=invite(admin);wid=r.json['wedding_id'];old,row=invitation(app)
    db=database(app);db.execute('UPDATE tokens SET expires=0 WHERE kind="welcome"');prune_tokens(db,time.time());db.commit();db.close()
    assert app.test_client().get(old).status_code==400
    assert next(w for w in admin.get('/api/admin').json['couples'] if w['id']==wid)['invitation_pending']
    assert admin.post('/api/admin/couples/'+wid+'/resend-invitation',json={},headers=headers(admin,'/ivoryadmin')).status_code==200
    new,row=invitation(app);assert app.test_client().get(new).status_code==200

import json
import secrets
import time
import pytest
from werkzeug.security import check_password_hash
from app.core import digest
from test_app import app,login,headers,database,csrf

NEW='a-new-admin-password-for-tests'

def test_change_requires_fully_signed_in_admin_and_csrf(app):
    body={'password':NEW,'confirm_password':NEW}
    guest=app.test_client()
    assert guest.post('/api/admin/password',json=body,headers={'X-CSRF-Token':csrf(guest)}).status_code==401
    couple=login(app)
    assert couple.post('/api/admin/password',json=body,headers=headers(couple)).status_code==403
    pending=app.test_client()
    assert pending.post('/ivoryadmin/login',data={'csrf':csrf(pending,'/ivoryadmin/login'),'email':'mark@example.com','password':'long-test-password'}).status_code==302
    assert pending.post('/api/admin/password',json=body,headers=headers(pending,'/ivoryadmin/two-step')).status_code==401
    admin=login(app,'mark@example.com',True)
    assert admin.post('/api/admin/password',json=body).status_code==403
    db=database(app);assert check_password_hash(db.execute('SELECT password FROM users WHERE id="admin"').fetchone()['password'],'long-test-password');db.close()

@pytest.mark.parametrize('password,confirm',[('short','short'),(NEW,'different'),(None,None),('x'*201,'x'*201)])
def test_invalid_new_password_keeps_current_login(app,password,confirm):
    admin=login(app,'mark@example.com',True)
    assert admin.post('/api/admin/password',json={'password':password,'confirm_password':confirm},headers=headers(admin,'/ivoryadmin')).status_code==400
    assert admin.get('/api/admin').status_code==200
    db=database(app);assert check_password_hash(db.execute('SELECT password FROM users WHERE id="admin"').fetchone()['password'],'long-test-password');db.close()

def test_change_rotates_this_session_revokes_other_logins_and_reset_links(app):
    admin=login(app,'mark@example.com',True);couple=login(app);before=couple.get('/api/state').json
    old_cookie=admin.get_cookie('ivory_session').value;old_csrf=headers(admin,'/ivoryadmin')['X-CSRF-Token']
    db=database(app);original=dict(db.execute('SELECT * FROM users WHERE id="admin"').fetchone())
    other_raw=secrets.token_urlsafe(32);pending_raw=secrets.token_urlsafe(32)
    for raw,uid,pending in [(other_raw,'admin',None),(pending_raw,None,'admin')]:
        db.execute('INSERT INTO sessions VALUES(?,?,?,?,?,?)',(digest(raw),uid,'other-token',time.time()+3600,pending,None))
    db.execute('INSERT INTO tokens VALUES(?,?,?,?,?,?,?,0)',(digest('old-reset-link'),'reset','admin',None,None,'{}',time.time()+3600));db.commit();db.close()
    other=app.test_client();other.set_cookie('ivory_session',other_raw);assert other.get('/api/admin').status_code==200
    response=admin.post('/api/admin/password',json={'password':NEW,'confirm_password':NEW},headers={'X-CSRF-Token':old_csrf})
    assert response.status_code==200 and response.json['csrf']!=old_csrf
    assert admin.get_cookie('ivory_session').value!=old_cookie
    assert admin.get('/api/admin').status_code==200
    assert other.get('/api/admin').status_code==401
    stolen=app.test_client();stolen.set_cookie('ivory_session',old_cookie);assert stolen.get('/api/admin').status_code==401
    assert couple.get('/api/state').json==before
    db=database(app);updated=dict(db.execute('SELECT * FROM users WHERE id="admin"').fetchone())
    assert check_password_hash(updated['password'],NEW) and updated['password']!=NEW
    for field in ['totp','totp_last','recovery','email','role']:assert updated[field]==original[field]
    assert db.execute('SELECT count(*) FROM sessions WHERE pending="admin"').fetchone()[0]==0
    assert db.execute('SELECT used FROM tokens WHERE hash=?',(digest('old-reset-link'),)).fetchone()['used']==1
    log=' '.join(r['action'] for r in db.execute('SELECT action FROM audit'))
    assert 'Administrator password changed' in log and NEW not in log;db.close()
    # New CSRF works for further console actions; the old token no longer authorises writes.
    assert admin.post('/api/sessions/revoke-others',json={},headers={'X-CSRF-Token':response.json['csrf']}).status_code==200
    assert admin.post('/api/sessions/revoke-others',json={},headers={'X-CSRF-Token':old_csrf}).status_code==403
    signin=app.test_client()
    assert signin.post('/ivoryadmin/login',data={'csrf':csrf(signin,'/ivoryadmin/login'),'email':'mark@example.com','password':'long-test-password'}).status_code==401
    result=signin.post('/ivoryadmin/login',data={'csrf':csrf(signin,'/ivoryadmin/login'),'email':'mark@example.com','password':NEW})
    assert result.status_code==302 and result.headers['Location']=='/ivoryadmin/two-step'

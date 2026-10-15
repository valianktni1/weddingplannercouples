"""SMTP admin settings and transport regressions; never contact a real provider."""
import json
import smtplib
import ssl
import time
import pytest
from app import create_app
from app.core import cipher,config
from app.mail_service import smtp_configuration,smtp_ready,send_email
from app.worker import deliver
from test_app import app,login,headers,database

PASSWORD='test-only-mailbox-password'

def settings_body(**changes):
    body={'smtp_source':'panel','smtp_host':'smtp.example.com','smtp_port':587,'smtp_security':'starttls',
        'smtp_user':'mail@example.com','smtp_password':PASSWORD,'sender':'mail@example.com','reply_to':'replies@example.com'}
    body.update(changes);return body


def setup_mail(app):
    admin=login(app,'mark@example.com',True)
    assert admin.put('/api/admin/settings',json=settings_body(),headers=headers(admin,'/ivoryadmin')).status_code==200
    return admin


def test_smtp_password_encrypted_hidden_preserved_rotated_and_removed(app):
    admin=setup_mail(app);db=database(app);stored=config(db)['smtp_password_encrypted'];db.close()
    assert PASSWORD not in stored and cipher(app.config['SECRET_VALUE']).decrypt(stored.encode()).decode()==PASSWORD
    response=admin.get('/api/admin');assert PASSWORD not in response.text and stored not in response.text
    assert 'smtp_password_encrypted' not in response.json['settings'] and response.json['smtp']['password_saved']
    assert response.json['status']['smtp_configured']
    # Ordinary settings and blank password edits must not erase the existing encrypted value.
    for body in ({'sender':'another@example.com'},{'smtp_password':''}):
        assert admin.put('/api/admin/settings',json=body,headers=headers(admin,'/ivoryadmin')).status_code==200
    db=database(app);assert config(db)['smtp_password_encrypted']==stored;db.close()
    assert admin.put('/api/admin/settings',json={'smtp_password':'replacement-only-password'},headers=headers(admin,'/ivoryadmin')).status_code==200
    db=database(app);assert smtp_configuration(config(db),app.config['SECRET_VALUE'])['password']=='replacement-only-password';db.close()
    assert admin.put('/api/admin/settings',json={'smtp_clear_password':True},headers=headers(admin,'/ivoryadmin')).status_code==200
    assert not admin.get('/api/admin').json['smtp']['password_saved']
    assert not admin.get('/api/admin').json['status']['smtp_configured']
    couple=login(app);assert couple.get('/api/admin').status_code==403
    assert couple.put('/api/admin/settings',json=settings_body(),headers=headers(couple)).status_code==403


@pytest.mark.parametrize('invalid',[
    {'smtp_port':0},{'smtp_port':65536},{'smtp_port':True},{'smtp_security':'none'},
    {'smtp_source':'other'},{'smtp_host':'https://smtp.example.com'},{'smtp_host':'smtp.example.com\r\nInjected'},
    {'smtp_user':['invalid']},{'smtp_password':['invalid']},{'smtp_clear_password':'yes'},
    {'smtp_password_encrypted':'raw-ciphertext'},{'smtp_clear_password':True,'smtp_password':'both'},
])
def test_invalid_smtp_settings_leave_existing_connection(app,invalid):
    admin=setup_mail(app);db=database(app);before=config(db);db.close()
    assert admin.put('/api/admin/settings',json=invalid,headers=headers(admin,'/ivoryadmin')).status_code==400
    db=database(app);assert config(db)==before;db.close()


class FakeSMTP:
    calls=[]
    def __init__(self,host,port,**kwargs):self.calls.append(('connect',host,port,kwargs))
    def ehlo(self):self.calls.append(('ehlo',))
    def starttls(self,**kwargs):self.calls.append(('starttls',kwargs))
    def login(self,user,password):self.calls.append(('login',user,password))
    def send_message(self,message):self.calls.append(('message',message))
    def quit(self):self.calls.append(('quit',))
    def close(self):self.calls.append(('close',))


@pytest.mark.parametrize('security,port',[('starttls',587),('ssl',465)])
def test_test_email_and_queued_delivery_use_saved_smtp(app,monkeypatch,security,port):
    import app.mail_service as service
    admin=setup_mail(app);assert admin.put('/api/admin/settings',json={'smtp_security':security,'smtp_port':port},headers=headers(admin,'/ivoryadmin')).status_code==200
    FakeSMTP.calls=[];monkeypatch.setattr(service.smtplib,'SMTP',FakeSMTP);monkeypatch.setattr(service.smtplib,'SMTP_SSL',FakeSMTP)
    result=admin.post('/api/admin/email-test',json={},headers=headers(admin,'/ivoryadmin'))
    assert result.status_code==200 and result.json['status']=='sent'
    assert 'Accepted' in result.json['message']
    connect=next(c for c in FakeSMTP.calls if c[0]=='connect');assert connect[1:3]==('smtp.example.com',port)
    assert ('login','mail@example.com',PASSWORD) in FakeSMTP.calls
    tls=next(c[1]['context'] for c in FakeSMTP.calls if c[0]=='starttls') if security=='starttls' else connect[3]['context']
    assert tls.check_hostname and tls.verify_mode==ssl.CERT_REQUIRED
    messages=[c[1] for c in FakeSMTP.calls if c[0]=='message'];assert len(messages)==1
    assert messages[0]['To']=='mark@example.com' and messages[0]['Reply-To']=='replies@example.com'
    db=database(app);row=db.execute('SELECT * FROM mail WHERE id=?',(result.json['delivery_id'],)).fetchone();assert row['status']=='sent' and row['attempts']==1
    db.execute('INSERT INTO mail(id,to_address,subject,body,created) VALUES(?,?,?,?,?)',('queued','couple@example.com','Queued mail','Hello',time.time()));db.commit()
    deliver(db,config(db),secret=app.config['SECRET_VALUE'])
    assert db.execute('SELECT status FROM mail WHERE id="queued"').fetchone()['status']=='sent'
    assert len([c for c in FakeSMTP.calls if c[0]=='message'])==2 # no duplicate test message
    db.close()


def test_test_email_failure_is_recorded_without_secret_or_retry(app,monkeypatch):
    import app.mail_service as service
    admin=setup_mail(app)
    class Rejected(FakeSMTP):
        def login(self,*args):raise smtplib.SMTPAuthenticationError(535,PASSWORD.encode())
    monkeypatch.setattr(service.smtplib,'SMTP',Rejected)
    result=admin.post('/api/admin/email-test',json={},headers=headers(admin,'/ivoryadmin'))
    assert result.status_code==400 and 'Login rejected' in result.json['error'] and PASSWORD not in result.text
    db=database(app);row=db.execute('SELECT * FROM mail WHERE id=?',(result.json['delivery_id'],)).fetchone()
    assert row['status']=='failed' and row['attempts']==1 and PASSWORD not in row['last_error'];db.close()
    assert PASSWORD not in admin.get('/api/admin').text


def test_missing_smtp_is_explained_without_queuing_a_false_success(app,monkeypatch):
    monkeypatch.delenv('SMTP_HOST',raising=False);admin=login(app,'mark@example.com',True)
    result=admin.post('/api/admin/email-test',json={},headers=headers(admin,'/ivoryadmin'))
    assert result.status_code==400 and 'SMTP' in result.json['error']
    db=database(app);assert db.execute('SELECT count(*) n FROM mail').fetchone()['n']==0;db.close()


def test_environment_mail_compatibility_and_panel_precedence(app,monkeypatch):
    for key,value in {'SMTP_HOST':'legacy.example.com','SMTP_PORT':'465','SMTP_SECURITY':'ssl','SMTP_USER':'old@example.com','SMTP_PASSWORD':'old-secret'}.items():monkeypatch.setenv(key,value)
    db=database(app);s=config(db);s['sender']='old@example.com'
    legacy=smtp_configuration(s,app.config['SECRET_VALUE']);assert legacy['host']=='legacy.example.com' and legacy['password']=='old-secret' and smtp_ready(s);db.close()
    setup_mail(app);db=database(app);assert smtp_configuration(config(db),app.config['SECRET_VALUE'])['host']=='smtp.example.com';db.close()


def test_signups_accept_panel_email_without_environment(app,monkeypatch):
    monkeypatch.delenv('SMTP_HOST',raising=False);admin=setup_mail(app)
    assert admin.put('/api/admin/settings',json={'privacy_text':'Privacy notice','terms_text':'Terms','signups_enabled':True},headers=headers(admin,'/ivoryadmin')).status_code==200
    assert admin.put('/api/admin/settings',json={'smtp_clear_password':True},headers=headers(admin,'/ivoryadmin')).status_code==400


def test_migration_adds_smtp_without_changing_existing_key_or_records(app):
    db=database(app);db.execute('DELETE FROM settings WHERE key LIKE "smtp_%"');db.commit();old_users=db.execute('SELECT count(*) n FROM users').fetchone()['n'];db.close()
    upgraded=create_app({'TESTING':True,'DATA_DIR':app.config['DATA_DIR'],'BACKUP_DIR':app.config['BACKUP_DIR'],'SECURE_COOKIES':False})
    assert upgraded.config['SECRET_VALUE']==app.config['SECRET_VALUE']
    db=database(upgraded);assert config(db)['smtp_source']=='environment';assert db.execute('SELECT count(*) n FROM users').fetchone()['n']==old_users;db.close()


def test_worker_reports_failure_and_retries_without_leaking_password(app,monkeypatch):
    import app.mail_service as service
    setup_mail(app)
    class Rejected(FakeSMTP):
        def login(self,*args):raise smtplib.SMTPAuthenticationError(535,PASSWORD.encode())
    monkeypatch.setattr(service.smtplib,'SMTP',Rejected)
    db=database(app);db.execute('INSERT INTO mail(id,to_address,subject,body,created) VALUES(?,?,?,?,?)',('retry-test','couple@example.com','Queued mail','Hello',time.time()));db.commit()
    deliver(db,config(db),secret=app.config['SECRET_VALUE'])
    row=db.execute('SELECT * FROM mail WHERE id="retry-test"').fetchone()
    assert row['status']=='retry' and row['attempts']==1 and row['next_attempt']>time.time()
    assert 'Login rejected' in row['last_error'] and PASSWORD not in row['last_error'];db.close()


def test_quit_failure_after_acceptance_is_not_a_failed_delivery(app,monkeypatch):
    import app.mail_service as service
    setup_mail(app)
    class LostQuit(FakeSMTP):
        def quit(self):raise smtplib.SMTPServerDisconnected('test-only disconnect after acceptance')
    FakeSMTP.calls=[];monkeypatch.setattr(service.smtplib,'SMTP',LostQuit)
    db=database(app);send_email(config(db),app.config['SECRET_VALUE'],'admin@example.com','Test','Hello','quit-test');db.close()
    assert len([c for c in FakeSMTP.calls if c[0]=='message'])==1

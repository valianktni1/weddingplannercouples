import json
import re
from pathlib import Path
import pytest
from app.core import config,initialise
from app.worker import deliver
from test_app import app,headers,database,login
from test_onboarding import prepared,invitation
from test_booking_connection import setup,body as booking_body
from test_smtp import FakeSMTP

DETAILS={'names':['Sophie','Dan'],'email':'sophie@example.com','date':'2027-06-19','access':'Complimentary','until':'2027-07-19'}


def preview(admin,body):
    return admin.post('/api/admin/couples/invitation-preview',json=body,headers=headers(admin,'/ivoryadmin'))


def counts(app):
    db=database(app);result=[db.execute('SELECT count(*) FROM '+table).fetchone()[0] for table in ['users','weddings','tokens','mail','wbm_booking_invitations']];db.close();return result


def test_preview_is_read_only_and_send_matches_both_bodies(app):
    admin=prepared(app);before=counts(app);p=preview(admin,DETAILS);assert p.status_code==200,p.json;p=p.json
    assert counts(app)==before and p['preview_only']
    assert 'Built by Weddings By Mark' in p['html'] and '30 days after your wedding' in p['body']
    fields={**p['email'],'subject':'A little gift for Sophie & Dan','message':'Hi Sophie & Dan,\n\nLovely chatting today! <script>alert(1)</script>','signoff':'See you soon,\nMark'}
    p=preview(admin,{**DETAILS,'invitation_email':fields}).json
    assert '<script>' not in p['html'] and '&lt;script&gt;' in p['html']
    r=admin.post('/api/admin/couples/invite',json={**DETAILS,'invitation_email':fields,'preview_hash':p['preview_hash']},headers=headers(admin,'/ivoryadmin'));assert r.status_code==201,r.json
    path,row=invitation(app);url='http://localhost'+path;placeholder='http://localhost/welcome/personal-link-generated-when-sent'
    assert row['subject']==fields['subject']
    assert row['body']==p['body'].replace(placeholder,url)
    assert row['html_body']==p['html'].replace(placeholder,url)
    assert counts(app)[-1]==0 # a manual invitation does not create a booking mapping


def test_trial_preview_uses_configured_days_and_no_booking_claim(app):
    admin=prepared(app);assert admin.put('/api/admin/settings',json={'trial_days':21},headers=headers(admin,'/ivoryadmin')).status_code==200
    p=preview(admin,{**DETAILS,'access':'Trial','until':''}).json
    assert '21-day trial' in p['body'] and 'Start our free trial' in p['html']
    assert 'booking your wedding' not in p['body'] and 'Thank you again for booking' not in p['body'] and '30 days after' not in p['body']


def test_resend_preview_keeps_old_link_until_send_and_personal_edits(app):
    admin=prepared(app);p=preview(admin,DETAILS).json
    fields={**p['email'],'subject':'Our private note','message':'Hi both,\n\nHere is your planner, as promised.'}
    r=admin.post('/api/admin/couples/invite',json={**DETAILS,'invitation_email':fields},headers=headers(admin,'/ivoryadmin'));wid=r.json['wedding_id'];old,row=invitation(app);before=counts(app)
    p=admin.get('/api/admin/couples/'+wid+'/invitation-preview');assert p.status_code==200;p=p.json
    assert p['email']==fields and p['previous']['subject']=='Our private note';assert counts(app)==before
    assert app.test_client().get(old).status_code==200
    fields={**fields,'message':'A new personal note.'};p=preview(admin,{'wedding_id':wid,'invitation_email':fields}).json
    r=admin.post('/api/admin/couples/'+wid+'/resend-invitation',json={'invitation_email':fields,'preview_hash':p['preview_hash']},headers=headers(admin,'/ivoryadmin'));assert r.status_code==200
    assert app.test_client().get(old).status_code==400
    new,row=invitation(app);assert 'A new personal note.' in row['body'];assert app.test_client().get(new).status_code==200


def test_manual_customisation_does_not_change_automatic_contract_or_defaults(app):
    admin,h=setup(app);p=preview(admin,DETAILS).json
    fields={**p['email'],'subject':'Manual custom subject','message':'ONLY THIS COUPLE'}
    assert admin.post('/api/admin/couples/invite',json={**DETAILS,'invitation_email':fields},headers=headers(admin,'/ivoryadmin')).status_code==201
    payload=booking_body(email='automatic@example.com');c=app.test_client();r=c.post('/api/integrations/wbm/invitations',json=payload,headers=h);assert r.status_code==201,r.json
    for _ in range(2): assert c.post('/api/integrations/wbm/invitations',json=payload,headers=h).json['wedding_id']==r.json['wedding_id']
    db=database(app);mapping=db.execute('SELECT * FROM wbm_booking_invitations WHERE booking_id=?',(payload['booking_id'],)).fetchone();row=db.execute('SELECT * FROM mail WHERE id=?',(mapping['mail_id'],)).fetchone();db.close()
    assert row['html_body'] and 'ONLY THIS COUPLE' not in row['body'] and row['subject']=='Your wedding planner is ready, Sophie & Dan'
    assert c.get('/api/integrations/wbm/invitations/'+payload['booking_id'],headers=h).json['status']=='queued'
    assert c.post('/api/integrations/wbm/invitations',json={**payload,'invitation_email':fields},headers=h).status_code==400


@pytest.mark.parametrize('bad',[{'subject':'Hi\r\nBcc: other@example.com'},{'heading':'bad\nheading'},{'message':''},{'message':'x'*6001},{'signoff':None}])
def test_invalid_email_edits_fail_without_creating_accounts(app,bad):
    admin=prepared(app);p=preview(admin,DETAILS).json;fields={**p['email'],**bad};before=counts(app)
    assert preview(admin,{**DETAILS,'invitation_email':fields}).status_code==400
    assert admin.post('/api/admin/couples/invite',json={**DETAILS,'invitation_email':fields},headers=headers(admin,'/ivoryadmin')).status_code==400
    assert counts(app)==before


def test_changed_trial_settings_require_preview_again(app):
    admin=prepared(app);details={**DETAILS,'access':'Trial','until':''};p=preview(admin,details).json
    assert admin.put('/api/admin/settings',json={'trial_days':28},headers=headers(admin,'/ivoryadmin')).status_code==200
    before=counts(app)
    assert admin.post('/api/admin/couples/invite',json={**details,'invitation_email':p['email'],'preview_hash':p['preview_hash']},headers=headers(admin,'/ivoryadmin')).status_code==400
    assert counts(app)==before


def test_preview_authorisation_and_csrf(app):
    admin=prepared(app);c=login(app)
    assert c.post('/api/admin/couples/invitation-preview',json=DETAILS,headers=headers(c)).status_code==403
    assert admin.post('/api/admin/couples/invitation-preview',json=DETAILS).status_code==403
    assert app.test_client().get('/api/admin/couples/wu1/invitation-preview').status_code==401


def test_worker_sends_multipart_html_and_plain_text(app,monkeypatch):
    import app.mail_service as service
    admin=prepared(app);p=preview(admin,DETAILS).json
    assert admin.post('/api/admin/couples/invite',json={**DETAILS,'invitation_email':p['email']},headers=headers(admin,'/ivoryadmin')).status_code==201
    FakeSMTP.calls=[];monkeypatch.setattr(service.smtplib,'SMTP',FakeSMTP)
    db=database(app);deliver(db,config(db),secret=app.config['SECRET_VALUE']);db.close()
    message=next(c[1] for c in FakeSMTP.calls if c[0]=='message')
    assert message.get_content_type()=='multipart/alternative'
    assert 'Built by Weddings By Mark' in message.get_body(preferencelist=('html',)).get_content()
    assert '/welcome/' in message.get_body(preferencelist=('plain',)).get_content()


def test_additive_html_migration_preserves_old_mail_and_secret(app):
    db=database(app);db.execute('ALTER TABLE mail DROP COLUMN html_body');db.execute('INSERT INTO mail(id,to_address,subject,body,created) VALUES("legacy","old@example.com","Old message","Keep this",0)');db.commit();db.close()
    secret=Path(app.config['DATA_DIR'],'app-secret').read_text();initialise(app.config['DATA_DIR'])
    db=database(app);row=db.execute('SELECT * FROM mail WHERE id="legacy"').fetchone();db.close()
    assert row['body']=='Keep this' and row['html_body']==''
    assert Path(app.config['DATA_DIR'],'app-secret').read_text()==secret

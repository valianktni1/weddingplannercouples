import io
import json
import re
import time
import hashlib
import hmac
import tarfile
from datetime import date,timedelta
import pytest
from werkzeug.security import generate_password_hash
from app import create_app
from app.core import connect,empty_state,cipher,totp,validate_state,access_end
from app.worker import backup,schedule

@pytest.fixture
def app(tmp_path,monkeypatch):
    monkeypatch.setenv('SMTP_HOST','test.invalid')
    a=create_app({'TESTING':True,'DATA_DIR':str(tmp_path/'data'),'BACKUP_DIR':str(tmp_path/'backups'),'APP_URL':'http://localhost','SECURE_COOKIES':False})
    db=connect(a.config['DATABASE'])
    for uid,email,role in [('u1','one@example.com','couple'),('u2','two@example.com','couple'),('admin','mark@example.com','admin')]:
        secret=cipher(a.config['SECRET_VALUE']).encrypt(b'JBSWY3DPEHPK3PXP').decode() if role=='admin' else None
        db.execute('INSERT INTO users(id,email,password,role,verified,totp,created) VALUES(?,?,?,?,1,?,?)',(uid,email,generate_password_hash('long-test-password'),role,secret,time.time()))
        if role=='couple':
            s=empty_state();s['email']=email;s['ready']=True;s['names']=['Emma','Jamie']
            db.execute('INSERT INTO weddings(id,state,access_until,created) VALUES(?,?,?,?)',('w'+uid,json.dumps(s),'2030-01-01',time.time()))
            db.execute('INSERT INTO members VALUES(?,?)',('w'+uid,uid))
    db.commit();db.close();return a

def csrf(client,path='/login'):
    html=client.get(path).get_data(as_text=True)
    return re.search(r'name="csrf-token" content="([^"]+)"',html).group(1)

def login(app,email='one@example.com',admin=False):
    c=app.test_client();path='/ivoryadmin/login' if admin else '/login'
    response=c.post(path,data={'csrf':csrf(c,path),'email':email,'password':'long-test-password'})
    assert response.status_code==302
    if admin:
        response=c.post('/ivoryadmin/two-step',data={'csrf':csrf(c,'/ivoryadmin/two-step'),'code':totp('JBSWY3DPEHPK3PXP')});assert response.status_code==302
    return c

def headers(c,path='/app'): return {'X-CSRF-Token':csrf(c,path)}
def database(app):return connect(app.config['DATABASE'])
def save(c,s,rev):return c.put('/api/state',json={'state':s,'revision':rev},headers=headers(c))
def prepare(c):
    state=c.get('/api/state').json;s=state['state']
    s['suppliers']=[{'id':'photo','name':'Photographer','category':'Photo + video','total':899,'booked':True,'contact':'','finish':1200}]
    s['payments']=[{'id':'p1','supplier':'photo','title':'Balance','amount':699,'paid':0,'due':'2027-05-22','paidDate':''}]
    s['guests']=[{'id':'g1','name':'Pat','household':'Pat and Robin','attendance':'Day','rsvp':'Waiting','meal':'','diet':'','access':'','table':''},{'id':'g2','name':'Robin','household':'Pat and Robin','attendance':'Evening','rsvp':'Waiting','meal':'','diet':'','access':'','table':''}]
    assert save(c,s,state['revision']).status_code==200
    return s

def publish(c,protected=False):
    body={'slug':'emma-and-jamie','site':{'published':True,'title':'Emma & Jamie','date':'2027-06-19','intro':'Welcome','ceremony':'SECRET DAY CEREMONY','reception':'The reception','theme':'garden'},'access_code':'our-code' if protected else ''}
    body['revision']=c.get('/api/website').json['revision']
    result=c.put('/api/website',json=body,headers=headers(c));assert result.status_code==200

def test_csrf_and_role_boundary(app):
    c=login(app)
    assert c.put('/api/state',json={}).status_code==403
    assert c.get('/api/admin').status_code==403
    assert c.get('/ivoryadmin').status_code==403
    assert app.test_client().get('/api/state').status_code==401

def test_shared_state_conflict_and_validation(app):
    c=login(app);prepare(c);original=c.get('/api/state').json;s=original['state'];s['payments'][0].update(paid=300,paidDate='2026-10-13')
    assert save(c,s,original['revision']).status_code==200
    assert save(c,s,original['revision']).status_code==409
    current=c.get('/api/state').json;s=current['state'];s['payments'][0]['paid']=700
    assert save(c,s,current['revision']).status_code==400
    other=login(app,'two@example.com');assert other.get('/api/state').json['state']['suppliers']==[]

def test_expired_accounts_can_export_not_edit(app):
    c=login(app);db=database(app);db.execute('UPDATE weddings SET access_until="2020-01-01" WHERE id="wu1"');db.commit();db.close()
    result=c.get('/api/state').json;assert result['readonly']
    assert save(c,result['state'],result['revision']).status_code==403
    assert c.get('/api/export').status_code==200

def test_partner_invitation_and_cancellation(app):
    c=login(app);result=c.post('/api/partner/invite',json={'email':'partner@example.com'},headers=headers(c));assert result.status_code==200
    db=database(app);link=db.execute('SELECT body FROM mail WHERE to_address="partner@example.com"').fetchone()['body'];db.close()
    path=link.replace('http://localhost','');partner=app.test_client();code=csrf(partner,path)
    assert partner.post(path,data={'csrf':code,'password':'different-long-password'}).status_code==302
    assert partner.get('/api/state').json['state']['invite']['status']=='Accepted'
    assert c.post('/api/partner/invite',json={'email':'third@example.com'},headers=headers(c)).status_code==400

def test_rsvp_updates_only_invited_individuals(app):
    c=login(app);prepare(c);publish(c,True)
    result=c.post('/api/invitations',json={'guest_ids':['g2']},headers=headers(c));assert result.status_code==200
    path=result.json['url'].replace('http://localhost','');guest=app.test_client();html=guest.get(path).get_data(as_text=True)
    assert 'Robin' in html and 'SECRET DAY CEREMONY' not in html
    assert 'name="g1-rsvp"' not in html
    code=re.search(r'name="csrf-token" content="([^"]+)"',html).group(1)
    response=guest.post(path,data={'csrf':code,'g2-rsvp':'Accepted','g2-meal':'Vegan','g2-diet':'No nuts','g1-rsvp':'Accepted'})
    assert response.status_code==200
    state=c.get('/api/state').json['state'];assert state['guests'][1]['meal']=='Vegan';assert state['guests'][0]['rsvp']=='Waiting'
    assert 'Wedding website access code' in guest.get('/weddings/emma-and-jamie').get_data(as_text=True)

def test_website_escape_and_duplicate_slug(app):
    c=login(app);publish(c);body=c.get('/api/website').json;body['site']['intro']='<script>alert(1)</script>'
    assert c.put('/api/website',json=body,headers=headers(c)).status_code==200
    html=app.test_client().get('/weddings/emma-and-jamie').get_data(as_text=True);assert '&lt;script&gt;' in html
    other=login(app,'two@example.com');body['revision']=other.get('/api/website').json['revision'];assert other.put('/api/website',json=body,headers=headers(other)).status_code==400

def test_private_documents_and_file_limits(app):
    c=login(app);response=c.post('/api/files',data={'kind':'document','file':(io.BytesIO(b'%PDF-1.4\nprivate'),'invoice.pdf')},headers=headers(c),content_type='multipart/form-data')
    assert response.status_code==200;uid=response.json['id'];assert c.get('/api/files/'+uid).status_code==200
    assert login(app,'two@example.com').get('/api/files/'+uid).status_code==404
    assert app.test_client().get('/api/files/'+uid).status_code==401
    bad=c.post('/api/files',data={'kind':'document','file':(io.BytesIO(b'<script>bad</script>'),'bad.pdf')},headers=headers(c),content_type='multipart/form-data');assert bad.status_code==400

def test_support_requires_couple_grant_and_filters_notes(app):
    c=login(app);prepare(c);admin=login(app,'mark@example.com',True)
    assert admin.get('/api/admin/support/wu1').status_code==403
    assert c.post('/api/support',json={'reason':'Payment question'},headers=headers(c)).status_code==200
    response=admin.get('/api/admin/support/wu1');assert response.status_code==200
    assert set(response.json)=={'suppliers','payments','reason','expires'}
    c.post('/api/support',json={'revoke':True},headers=headers(c));assert admin.get('/api/admin/support/wu1').status_code==403

def test_admin_access_no_fake_sale_and_checkout_guard(app):
    admin=login(app,'mark@example.com',True)
    assert admin.post('/api/admin/access/wu1',json={'access':'Complimentary','until':'2028-01-01','reason':'Included with photography'},headers=headers(admin,'/ivoryadmin')).status_code==200
    assert admin.get('/api/admin').json['status']['paid_sales_pence']==0
    assert admin.put('/api/admin/settings',json={'checkout_enabled':True},headers=headers(admin,'/ivoryadmin')).status_code==400
    assert login(app).post('/api/checkout',json={},headers=headers(login(app))).status_code==403

def test_signup_verify_and_recovery(app):
    db=database(app);db.execute('UPDATE settings SET value="true" WHERE key="signups_enabled"');db.commit();db.close()
    c=app.test_client();response=c.post('/signup',data={'csrf':csrf(c,'/signup'),'email':'new@example.com','password':'a-very-long-password'});assert response.status_code==200
    db=database(app);value=db.execute('SELECT body FROM mail WHERE to_address="new@example.com"').fetchone()['body'].replace('http://localhost','');db.close()
    assert c.post(value,data={'csrf':csrf(c,value)}).status_code==302
    assert c.post(value,data={'csrf':csrf(c,'/login')}).status_code==400
    response=c.post('/recover',data={'csrf':csrf(c,'/recover'),'email':'new@example.com'});assert response.status_code==200
    db=database(app);reset=db.execute('SELECT body FROM mail WHERE subject="Reset your planner password"').fetchone()['body'].replace('http://localhost','');db.close()
    assert c.post(reset,data={'csrf':csrf(c,reset),'password':'another-long-password'}).status_code==302

def test_webhook_signed_idempotent_and_amount_check(app,monkeypatch):
    monkeypatch.setenv('STRIPE_WEBHOOK_SECRET','whsec-test')
    db=database(app);db.execute('INSERT INTO purchases(id,wedding_id,amount,checkout_id,terms,created) VALUES(?,?,?,?,?,?)',('purchase','wu1',7900,'cs_test',json.dumps({'access_until':'2031-01-01'}),time.time()));db.commit();db.close()
    body={'id':'evt_test','type':'checkout.session.completed','data':{'object':{'id':'cs_test','payment_status':'paid','amount_total':7900,'currency':'gbp','metadata':{'purchase_id':'purchase'}}}}
    raw=json.dumps(body).encode();timestamp=str(int(time.time()));sig=hmac.new(b'whsec-test',timestamp.encode()+b'.'+raw,hashlib.sha256).hexdigest();c=app.test_client()
    assert c.post('/api/stripe/webhook',data=raw,headers={'Stripe-Signature':'bad'}).status_code==400
    for _ in range(2): assert c.post('/api/stripe/webhook',data=raw,headers={'Stripe-Signature':f't={timestamp},v1={sig}'}).status_code==200
    db=database(app);assert db.execute('SELECT access_kind FROM weddings WHERE id="wu1"').fetchone()['access_kind']=='Paid';assert db.execute('SELECT count(*) n FROM webhook_events').fetchone()['n']==1;db.close()

def test_backup_integrity_and_reminder_dedupe(app,tmp_path):
    c=login(app);prepare(c);path=backup(Path(app.config['DATA_DIR']),Path(app.config['BACKUP_DIR']))
    with tarfile.open(path) as archive: assert {'planner.sqlite3','app-secret','files'}.issubset(set(archive.getnames()))
    db=database(app);from app.core import config
    from datetime import datetime
    from zoneinfo import ZoneInfo
    now=datetime(2027,5,15,12,tzinfo=ZoneInfo('UTC'));schedule(db,config(db),now);schedule(db,config(db),now);db.commit()
    assert db.execute('SELECT count(*) n FROM mail WHERE dedupe LIKE "payment:%"').fetchone()['n']==1
    s=json.loads(db.execute('SELECT state FROM weddings WHERE id="wu1"').fetchone()['state']);s['stage']='finished';db.execute('UPDATE weddings SET state=? WHERE id="wu1"',(json.dumps(s),));db.commit()
    schedule(db,config(db),datetime(2027,5,21,12,tzinfo=ZoneInfo('UTC')));assert db.execute('SELECT count(*) n FROM mail WHERE dedupe LIKE "payment:%"').fetchone()['n']==1;db.close()

from pathlib import Path

def test_admin_enrolment_and_one_use_recovery(app):
    db=database(app);db.execute('UPDATE users SET totp=NULL WHERE id="admin"');db.commit();db.close()
    c=app.test_client();result=c.post('/ivoryadmin/login',data={'csrf':csrf(c,'/ivoryadmin/login'),'email':'mark@example.com','password':'long-test-password'})
    assert result.location.endswith('/two-step/setup')
    html=c.get('/ivoryadmin/two-step/setup').get_data(as_text=True)
    secret=re.search(r'<p class="secret">([^<]+)</p>',html).group(1)
    response=c.post('/ivoryadmin/two-step/setup',data={'csrf':csrf(c,'/ivoryadmin/two-step/setup'),'code':totp(secret)})
    assert response.status_code==200
    codes=re.findall(r'\b[a-f0-9]{10}\b',response.get_data(as_text=True));assert len(codes)==8
    assert c.get('/api/admin').status_code==200
    other=app.test_client();other.post('/ivoryadmin/login',data={'csrf':csrf(other,'/ivoryadmin/login'),'email':'mark@example.com','password':'long-test-password'})
    assert other.post('/ivoryadmin/two-step',data={'csrf':csrf(other,'/ivoryadmin/two-step'),'code':codes[0]}).status_code==302
    third=app.test_client();third.post('/ivoryadmin/login',data={'csrf':csrf(third,'/ivoryadmin/login'),'email':'mark@example.com','password':'long-test-password'})
    assert third.post('/ivoryadmin/two-step',data={'csrf':csrf(third,'/ivoryadmin/two-step'),'code':codes[0]}).status_code==400

def test_resend_verification_replaces_old_link(app):
    db=database(app);db.execute('UPDATE settings SET value="true" WHERE key="signups_enabled"');db.commit();db.close()
    c=app.test_client();c.post('/signup',data={'csrf':csrf(c,'/signup'),'email':'resend@example.com','password':'another-long-password'})
    db=database(app);old=db.execute('SELECT body FROM mail WHERE to_address="resend@example.com" ORDER BY created').fetchone()['body'].replace('http://localhost','');db.close()
    assert c.post('/verification',data={'csrf':csrf(c,'/verification'),'email':'resend@example.com'}).status_code==200
    assert c.get(old).status_code==400

def test_restore_archive_referenced_files(app,tmp_path):
    c=login(app);c.post('/api/files',data={'kind':'document','file':(io.BytesIO(b'%PDF-1.4\narchive-test'),'invoice.pdf')},headers=headers(c),content_type='multipart/form-data')
    archive_path=backup(Path(app.config['DATA_DIR']),Path(app.config['BACKUP_DIR']));target=tmp_path/'restore';target.mkdir()
    with tarfile.open(archive_path) as archive: archive.extractall(target,filter='data')
    import subprocess,sys
    result=subprocess.run([sys.executable,'scripts/verify-backup.py',str(target)],capture_output=True,text=True)
    assert result.returncode==0,result.stderr

def test_website_revision_alias_preview_and_revoke(app):
    c=login(app);prepare(c);publish(c)
    invite=c.post('/api/invitations',json={'guest_ids':['g1']},headers=headers(c)).json['url'].replace('http://localhost','')
    old=c.get('/api/website').json;changed=dict(old);changed['slug']='new-address'
    assert c.put('/api/website',json=changed,headers=headers(c)).status_code==200
    assert c.put('/api/website',json=old,headers=headers(c)).status_code==409
    guest=app.test_client();assert guest.get(invite).status_code==200
    current=c.get('/api/website').json;current['site']['published']=False
    assert c.put('/api/website',json=current,headers=headers(c)).status_code==200
    assert c.get('/website/preview').status_code==200
    assert guest.get('/website/preview').status_code in (302,401)
    assert guest.get('/weddings/new-address').status_code==404
    current=c.get('/api/website').json;current['site']['published']=True
    assert c.put('/api/website',json=current,headers=headers(c)).status_code==200
    tid=c.get('/api/invitations').json['invitations'][0]['id']
    other=login(app,'two@example.com')
    assert other.post('/api/invitations/'+tid+'/revoke',json={},headers=headers(other)).status_code==404
    assert c.post('/api/invitations/'+tid+'/revoke',json={},headers=headers(c)).status_code==200
    assert guest.get(invite).status_code==404

@pytest.mark.parametrize('change',[
    lambda s:s.update(budget=12.345),
    lambda s:s['day'].update(mealConfirmed='yes'),
    lambda s:s['day'].update(ceremonyMinutes=0),
    lambda s:s['suppliers'][0].update(total=100.001),
    lambda s:s['guests'][0].update(id='<unsafe>'),
])
def test_invalid_state_keeps_saved_copy(app,change):
    c=login(app);prepare(c);before=c.get('/api/state').json
    edited=json.loads(json.dumps(before['state']));change(edited)
    assert save(c,edited,before['revision']).status_code==400
    assert c.get('/api/state').json['state']==before['state']

def test_stale_reminders_cancel_and_update_amount(app):
    from app.worker import current_mail
    from app.core import config
    from datetime import datetime
    from zoneinfo import ZoneInfo
    c=login(app);prepare(c);db=database(app);settings=config(db);now=datetime(2027,5,15,12,tzinfo=ZoneInfo('UTC'))
    schedule(db,settings,now);db.commit();row=db.execute('SELECT * FROM mail WHERE dedupe LIKE "payment:%"').fetchone()
    assert '£699.00' in current_mail(db,row,settings,now)
    s=json.loads(db.execute('SELECT state FROM weddings WHERE id="wu1"').fetchone()['state']);s['payments'][0]['paid']=300
    db.execute('UPDATE weddings SET state=? WHERE id="wu1"',(json.dumps(s),));db.commit()
    assert '£399.00' in current_mail(db,row,settings,now)
    s['payments'][0]['paid']=699;db.execute('UPDATE weddings SET state=? WHERE id="wu1"',(json.dumps(s),));db.commit()
    assert current_mail(db,row,settings,now) is None
    db.close()

def test_restored_download_uses_restored_files(app,tmp_path):
    c=login(app);result=c.post('/api/files',data={'kind':'document','file':(io.BytesIO(b'%PDF-1.4\noriginal'),'original.pdf')},headers=headers(c),content_type='multipart/form-data');uid=result.json['id']
    archive_path=backup(Path(app.config['DATA_DIR']),Path(app.config['BACKUP_DIR']));target=tmp_path/'restored';target.mkdir()
    with tarfile.open(archive_path) as archive:archive.extractall(target,filter='data')
    for f in (Path(app.config['DATA_DIR'])/'files').rglob('*'):
        if f.is_file():f.write_bytes(b'LIVE FILE MUST NOT BE USED')
    restored=create_app({'TESTING':True,'DATA_DIR':str(target),'BACKUP_DIR':str(tmp_path/'other-backups'),'APP_URL':'http://localhost','SECURE_COOKIES':False})
    assert login(restored).get('/api/files/'+uid).data==b'%PDF-1.4\noriginal'

def test_backup_releases_write_lock_before_archive(app,tmp_path,monkeypatch):
    import app.worker as worker
    real=worker.tarfile.open
    def checked(*args,**kwargs):
        if len(args)>1 and args[1]=='w:gz':
            db=database(app);db.execute('BEGIN IMMEDIATE');db.rollback();db.close()
        return real(*args,**kwargs)
    monkeypatch.setattr(worker.tarfile,'open',checked)
    a=backup(Path(app.config['DATA_DIR']),Path(app.config['BACKUP_DIR']));b=backup(Path(app.config['DATA_DIR']),Path(app.config['BACKUP_DIR']))
    assert a!=b and a.exists() and b.exists()

def test_paid_entitlement_survives_suspension(app):
    admin=login(app,'mark@example.com',True);db=database(app)
    db.execute('INSERT INTO purchases(id,wedding_id,amount,status,terms,created) VALUES(?,?,?,?,?,?)',('paid','wu1',2500,'paid',json.dumps({'access_until':'2031-01-01'}),time.time()));db.execute('UPDATE weddings SET access_kind="Paid",access_until="2031-01-01" WHERE id="wu1"');db.commit();db.close()
    for kind,until,status in [('Suspended','2031-01-01',200),('Manual extension','2028-01-01',400),('Manual extension','2032-01-01',200)]:
        assert admin.post('/api/admin/access/wu1',json={'access':kind,'until':until,'reason':'Test change'},headers=headers(admin,'/ivoryadmin')).status_code==status

def test_invalid_invitation_rolls_back_token(app):
    c=login(app);prepare(c);publish(c);db=database(app);before=db.execute('SELECT count(*) n FROM tokens WHERE kind="rsvp"').fetchone()['n'];db.close()
    assert c.post('/api/invitations',json={'guest_ids':['g1'],'email':'invalid'},headers=headers(c)).status_code==400
    db=database(app);assert db.execute('SELECT count(*) n FROM tokens WHERE kind="rsvp"').fetchone()['n']==before;db.close()

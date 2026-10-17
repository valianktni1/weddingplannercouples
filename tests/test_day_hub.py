import io
import json
import re
import time
from datetime import date,timedelta,datetime,timezone
import pytest
from pypdf import PdfReader
from app.core import config,initialise
from app.worker import current_mail
from test_app import app,login,headers,database,prepare,csrf
from test_onboarding import prepared


def hub(c):return c.get('/api/hub').json

def act(c,action,**extra):
    h=hub(c);return c.post('/api/hub/action',json={'action':action,'revision':h['revision'],'plan_revision':h['plan_revision'],**extra},headers=headers(c))

def seed(c):
    s=prepare(c);s['names']=['Emma','Jamie'];s['date']='2027-06-19';s['notes']='PRIVATE FAMILY NOTE';s['noteScope']='Photographer handover';s['guests'][0].update(diet='PRIVATE HEALTH DETAIL',access='PRIVATE ACCESS DETAIL');s['groups']=[{'id':'family','title':'Emma with mum and dad','minutes':3}]
    revision=c.get('/api/state').json['revision'];assert c.put('/api/state',json={'state':s,'revision':revision},headers=headers(c)).status_code==200


def share(c,**extra):
    body={'label':'Photographer','role':'photographer','scopes':['timeline','photos','jobs'],'supplier_ids':[],'until':'2027-07-01','email':'','notify':False,'send_email':False,**extra}
    result=act(c,'share_create',**body);assert result.status_code==200,result.json
    return result.json['url'].replace('http://localhost',''),result.json['hub']['shares'][-1]['id']


def test_hub_auth_ownership_and_existing_state_shape(app):
    c=login(app);seed(c);state=c.get('/api/state').json['state'];assert c.get('/hub').status_code==200;assert hub(c)['guests'][0]['name']=='Pat'
    assert set(c.get('/api/state').json['state'])==set(state)
    assert app.test_client().get('/api/hub').status_code==401
    assert c.post('/api/hub/action',json={'action':'ready'}).status_code==403
    admin=login(app,'mark@example.com',True);assert admin.get('/api/hub').status_code==403


def test_scoped_recipient_preview_is_read_only_and_excludes_private_information(app):
    c=login(app);seed(c);before=hub(c)
    p=c.post('/api/hub/share-preview',json={'label':'Venue','role':'venue','scopes':['timeline','seating'],'supplier_ids':[],'until':'2027-07-01'},headers=headers(c));assert p.status_code==200
    assert len(hub(c)['shares'])==0 and hub(c)['revision']==before['revision']
    assert 'PRIVATE' not in p.text and 'payments' not in p.json['view'] and 'contacts' not in p.json['view']
    path,sid=share(c,role='venue',scopes=['timeline','seating']);public=app.test_client().get(path)
    assert public.status_code==200 and 'Pat' in public.text and 'PRIVATE' not in public.text and '699' not in public.text
    assert public.headers['Cache-Control']=='no-store' and public.headers['Referrer-Policy']=='no-referrer'


def test_extra_timeline_events_have_explicit_audiences_and_safe_text(app):
    c=login(app);seed(c)
    for audience,title in [('private','PRIVATE ACTIVITY'),('photographer','PHOTO ACTIVITY'),('everyone','ALL ACTIVITY')]:
        assert act(c,'event_save',title=title,start=600,duration=15,location='Main venue',instructions='<script>literal</script>',audience=audience).status_code==200
    photo,sid=share(c);party,pid=share(c,label='Best person',role='party',scopes=['timeline'])
    p=app.test_client().get(photo).text;q=app.test_client().get(party).text
    assert 'PHOTO ACTIVITY' in p and 'PRIVATE ACTIVITY' not in p and '<script>literal</script>' not in p
    assert '&lt;script&gt;' in p and 'PHOTO ACTIVITY' not in q and 'ALL ACTIVITY' in q
    item=hub(c)['events'][0];assert act(c,'event_delete',id=item['id']).status_code==200


def test_concurrent_hub_or_planner_changes_require_reload_and_preserve_data(app):
    c=login(app);seed(c);old=hub(c)
    assert act(c,'table_save',name='Table One',capacity=8,shape='round').status_code==200
    r=c.post('/api/hub/action',json={'action':'ready','ready':True,'checks_reviewed':True,'revision':old['revision'],'plan_revision':old['plan_revision']},headers=headers(c));assert r.status_code==409
    old=hub(c);current=c.get('/api/state').json;current['state']['tasks'].append({'id':'newtask','title':'Partner edit','owner':'Together','due':'','done':False});assert c.put('/api/state',json={'state':current['state'],'revision':current['revision']},headers=headers(c)).status_code==200
    r=c.post('/api/hub/action',json={'action':'table_move','id':old['tables'][0]['id'],'x':10,'y':10,'revision':old['revision'],'plan_revision':old['plan_revision']},headers=headers(c));assert r.status_code==409
    assert c.get('/api/state').json['state']['tasks'][-1]['title']=='Partner edit'


def test_table_capacity_assignment_rename_delete_and_cross_wedding_protection(app):
    c=login(app);seed(c);r=act(c,'table_save',name='Family',capacity=1,shape='round');assert r.status_code==200;r=r.json;tid=r['hub']['tables'][0]['id']
    assert act(c,'seat',guest_id='g1',table_id=tid).status_code==200
    assert c.get('/api/state').json['state']['guests'][0]['table']=='Family'
    assert act(c,'seat',guest_id='g2',table_id=tid).status_code==400
    assert act(c,'table_save',id=tid,name='Top Table',capacity=2,shape='long',x=80,y=20).status_code==200
    assert c.get('/api/state').json['state']['guests'][0]['table']=='Top Table'
    assert act(login(app,'two@example.com'),'seat',guest_id='g1',table_id=tid).status_code==404
    assert act(c,'table_delete',id=tid).status_code==400
    assert act(c,'table_delete',id=tid,unseat=True).status_code==200
    assert c.get('/api/state').json['state']['guests'][0]['table']==''


def test_import_preserves_legacy_labels_and_marks_capacity_unknown(app):
    c=login(app);seed(c);s=c.get('/api/state').json;s['state']['guests'][0]['table']='Existing table';assert c.put('/api/state',json={'state':s['state'],'revision':s['revision']},headers=headers(c)).status_code==200
    result=act(c,'import_tables');assert result.status_code==200
    table=result.json['hub']['tables'][0];assert table['name']=='Existing table' and table['capacity'] is None
    assert any(x['code'].startswith('capacity-') for x in hub(c)['checks'])
    assert act(c,'import_tables').status_code==200 and len(hub(c)['tables'])==1


def test_recipient_can_complete_only_their_assigned_jobs(app):
    c=login(app);seed(c);path,sid=share(c);other,oid=share(c,label='Other person',role='party',scopes=['jobs'])
    assert act(c,'job_save',title='Gather the family',owner='',start=840,instructions='Meet outside',assigned_share=sid).status_code==200
    job=hub(c)['jobs'][0];visitor=app.test_client();html=visitor.get(path).text
    assert 'Gather the family' in html
    assert visitor.post(path+'/job/'+job['id'],data={'csrf':csrf(visitor,path),'revision':job['revision'],'done':'1'}).status_code==200
    assert hub(c)['jobs'][0]['done']==1
    assert visitor.post(other+'/job/'+job['id'],data={'csrf':csrf(visitor,other),'revision':job['revision']+1,'done':'0'}).status_code==403
    assert visitor.post(path+'/job/'+job['id'],data={'csrf':csrf(visitor,path),'revision':job['revision'],'done':'0'}).status_code==409


def test_acknowledgement_change_notices_and_stale_confirmation(app):
    c=login(app);seed(c);path,sid=share(c);v=app.test_client();html=v.get(path).text
    hashed=re.search(r'name="version_hash" value="([^"]+)"',html).group(1)
    assert v.post(path+'/confirm',data={'csrf':csrf(v,path),'version_hash':hashed}).status_code==200
    assert hub(c)['shares'][0]['confirmed']
    s=c.get('/api/state').json;s['state']['day']['ceremony']+=30
    assert c.put('/api/state',json={'state':s['state'],'revision':s['revision']},headers=headers(c)).status_code==200
    assert not hub(c)['shares'][0]['confirmed']
    changed=v.get(path).text;assert 'Changed since your last confirmation' in changed and 'Ceremony:' in changed
    assert v.post(path+'/confirm',data={'csrf':csrf(v,path),'version_hash':hashed}).status_code==409
    assert v.get(path+'/status').json['hash']!=hashed


def test_revocation_expiry_suspension_and_ended_access_close_links_and_packs(app):
    c=login(app);seed(c);path,sid=share(c)
    assert act(c,'share_revoke',id=sid).status_code==200
    v=app.test_client();assert v.get(path).status_code==404 and v.get(path+'/pack.pdf').status_code==404
    path,sid=share(c);db=database(app);db.execute('UPDATE hub_shares SET expires=0 WHERE id=?',(sid,));db.commit();db.close();assert v.get(path).status_code==404
    path,sid=share(c);db=database(app);db.execute('UPDATE weddings SET suspended=1 WHERE id="wu1"');db.commit();db.close();assert v.get(path).status_code==404
    db=database(app);db.execute('UPDATE weddings SET suspended=0,access_until="2020-01-01" WHERE id="wu1"');db.commit();db.close();assert v.get(path).status_code==404
    assert c.get('/api/hub/pack/couple.pdf').status_code==200 # own exports remain available
    assert act(c,'table_save',name='No',capacity=8,shape='round').status_code==403


def test_optional_change_email_is_deduplicated_and_cancelled_if_link_revoked(app):
    admin=prepared(app);c=login(app);seed(c);path,sid=share(c,email='person@example.com',notify=True,send_email=True)
    db=database(app);assert db.execute('SELECT count(*) FROM mail WHERE dedupe LIKE "hub-invite:%"').fetchone()[0]==1;db.close()
    s=c.get('/api/state').json;s['state']['day']['ceremony']+=10;assert c.put('/api/state',json={'state':s['state'],'revision':s['revision']},headers=headers(c)).status_code==200
    db=database(app);rows=db.execute('SELECT * FROM mail WHERE dedupe LIKE "hub-change:%"').fetchall();assert len(rows)==1;db.close()
    assert act(c,'share_revoke',id=sid).status_code==200
    db=database(app);assert current_mail(db,rows[0],config(db),datetime.now(timezone.utc)) is None;db.close()


def test_packs_have_scoped_content_and_offline_copy_has_no_live_controls(app):
    c=login(app);seed(c);path,sid=share(c,scopes=['timeline','photos'])
    for endpoint in ['/api/hub/pack/couple.pdf',path+'/pack.pdf']:
        result=c.get(endpoint);assert result.status_code==200 and result.data.startswith(b'%PDF')
        text='\n'.join(page.extract_text() for page in PdfReader(io.BytesIO(result.data)).pages)
        assert 'Emma' in text and 'PRIVATE' not in text and '699' not in text
    result=c.get(path+'/pack.html');assert result.status_code==200 and 'offline snapshot' in result.text
    assert '<script' not in result.text and '<form' not in result.text and 'name="csrf"' not in result.text and 'PRIVATE' not in result.text
    assert 'Pat' not in result.text # no seating scope


def test_ready_dashboard_activity_and_private_notes_not_exposed(app):
    admin=prepared(app);c=login(app);seed(c);assert act(c,'ready',ready=True).status_code==400
    assert act(c,'ready',ready=True,checks_reviewed=True).status_code==200
    data=admin.get('/api/admin').json;one=next(x for x in data['couples'] if x['id']=='wu1')
    assert one['journey']['stage']=='Ready for the day' and one['journey']['last_active']
    assert 'PRIVATE' not in json.dumps(data)
    assert act(c,'event_save',title='Extra speech',start=1100,duration=10,audience='private').status_code==200
    assert next(x for x in admin.get('/api/admin').json['couples'] if x['id']=='wu1')['journey']['stage']=='Actively planning'


@pytest.mark.parametrize('action,extra',[('event_save',{'title':'X','start':1440,'duration':0}),('table_save',{'name':'X','capacity':0,'shape':'round'}),('share_create',{'label':'X','role':'venue','scopes':[{}],'until':'2027-07-01'}),('share_create',{'label':'X','role':'party','scopes':['contacts'],'supplier_ids':[],'until':'2027-07-01'})])
def test_invalid_mutations_roll_back(app,action,extra):
    c=login(app);seed(c);before=hub(c);r=act(c,action,**extra);assert r.status_code==400,r.json
    after=hub(c);assert after['revision']==before['revision'] and after['plan_revision']==before['plan_revision']


def test_selected_contacts_and_pack_profiles_do_not_include_unselected_data(app):
    c=login(app);seed(c);s=c.get('/api/state').json;s['state']['suppliers'].append({'id':'private','name':'UNSELECTED SUPPLIER','category':'Other','total':None,'booked':False,'contact':'SECRET CONTACT','finish':None});assert c.put('/api/state',json={'state':s['state'],'revision':s['revision']},headers=headers(c)).status_code==200
    path,sid=share(c,scopes=['contacts','jobs'],supplier_ids=['photo'])
    assert act(c,'job_save',title='Shared photo job',owner='',start=None,instructions='Only the photo plan',assigned_share=sid).status_code==200
    assert act(c,'job_save',title='PRIVATE COUPLE JOB',owner='Emma',start=None,instructions='Keep this private',assigned_share='').status_code==200
    public=app.test_client().get(path).text;assert 'Photographer' in public and 'SECRET CONTACT' not in public and 'PRIVATE COUPLE JOB' not in public
    data=c.get('/api/hub/pack/photographer.pdf').data;text='\n'.join(p.extract_text() for p in PdfReader(io.BytesIO(data)).pages)
    assert 'Shared photo job' in text and 'PRIVATE COUPLE JOB' not in text and 'SECRET CONTACT' not in text


def test_seating_csv_is_plain_and_protects_spreadsheet_formula_names(app):
    c=login(app);seed(c);s=c.get('/api/state').json;s['state']['guests'][0]['name']='=HYPERLINK("bad")';assert c.put('/api/state',json={'state':s['state'],'revision':s['revision']},headers=headers(c)).status_code==200
    result=c.get('/api/hub/seating.csv');assert result.status_code==200
    assert "'=HYPERLINK" in result.text and 'PRIVATE' not in result.text


def test_legacy_empty_account_with_hub_content_is_not_discarded_on_partner_join(app):
    c=login(app);other=login(app,'two@example.com')
    db=database(app);from app.core import empty_state
    state=empty_state();state['email']='two@example.com';db.execute('UPDATE weddings SET state=? WHERE id="wu2"',(json.dumps(state),));db.commit();db.close()
    assert act(other,'job_save',title='Keep my hub job',owner='Me',start=None,instructions='',assigned_share='').status_code==200
    assert c.post('/api/partner/invite',json={'email':'two@example.com'},headers=headers(c)).status_code==200
    db=database(app);link=db.execute('SELECT body FROM mail WHERE to_address="two@example.com" ORDER BY created DESC LIMIT 1').fetchone()[0];db.close();path=link.replace('http://localhost','')
    result=other.post(path,data={'csrf':csrf(other,path),'password':'long-test-password'});assert result.status_code==400
    assert hub(other)['jobs'][0]['title']=='Keep my hub job'


def test_expiry_cannot_exceed_access_and_notification_requires_mail_setup(app):
    c=login(app);seed(c)
    common={'label':'Venue','role':'venue','scopes':['timeline'],'supplier_ids':[],'until':'2031-01-01'}
    assert c.post('/api/hub/share-preview',json=common,headers=headers(c)).status_code==400
    assert act(c,'share_create',**{**common,'until':'2027-07-01','email':'someone@example.com','notify':True}).status_code==400
    assert not hub(c)['shares']


def test_revoked_job_links_are_flagged_and_cannot_receive_new_assignments(app):
    c=login(app);seed(c);path,sid=share(c)
    assert act(c,'job_save',title='Bring rings',owner='',start=None,instructions='',assigned_share=sid).status_code==200
    assert act(c,'share_revoke',id=sid).status_code==200
    assert any(check['code']=='job-links' for check in hub(c)['checks'])
    assert act(c,'job_save',title='New job',owner='',start=None,instructions='',assigned_share=sid).status_code==400


def test_private_changes_do_not_change_public_version_or_send_change_email(app):
    admin=prepared(app);c=login(app);seed(c);path,sid=share(c,email='person@example.com',notify=True)
    v=app.test_client();before=v.get(path+'/status').json['hash']
    s=c.get('/api/state').json;s['state']['notes']='A new private family note';s['state']['budget']=10000
    assert c.put('/api/state',json={'state':s['state'],'revision':s['revision']},headers=headers(c)).status_code==200
    assert v.get(path+'/status').json['hash']==before
    db=database(app);assert db.execute('SELECT count(*) FROM mail WHERE dedupe LIKE "hub-change:%"').fetchone()[0]==0;db.close()


def test_edit_rate_limits_are_separate_for_each_couple_login(app):
    from app.core import digest
    c=login(app);other=login(app,'two@example.com');db=database(app)
    db.execute('INSERT OR REPLACE INTO rate_limits VALUES(?,?,?)',(digest('hub-edit-u1|account'),1200,time.time()+900));db.commit();db.close()
    assert act(c,'table_save',name='Blocked',capacity=8,shape='round').status_code==429
    assert act(other,'table_save',name='Other couple',capacity=8,shape='round').status_code==200

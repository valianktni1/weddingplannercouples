import copy
import io
import json
import re
import sqlite3
import tarfile
from PIL import Image
from test_app import app,login,headers,database,prepare,publish
from app.guest_experience import reply_version
from app.stationery import defaults,source


def configure(c,**changes):
    web=c.get('/api/website').json;web['site'].update(changes)
    response=c.put('/api/website',json=web,headers=headers(c));assert response.status_code==200,response.get_data(as_text=True)
    return c.get('/api/website').json['site']


def setup(c):
    s=prepare(c);publish(c,True)
    site=configure(c,arrival_day='12:30',arrival_evening='19:00',end_evening='01:00',venue_day='Day Hall',venue_evening='Evening Hall',order_day='SECRET DAY TIMINGS',order_evening='19:00 Party',food='SECRET DAY MENU',evening_food='Pizza',courses=[{'label':'Main','audience':'Day','choices':['Chicken','Vegan']},{'label':'Evening snack','audience':'Evening','choices':['Pizza','Falafel']}])
    return s,site


def link(c,ids=('g1','g2')):
    response=c.post('/api/invitations',json={'guest_ids':list(ids)},headers=headers(c));assert response.status_code==200
    return response.json['url'].replace('http://localhost','')


def form(guest,path):
    page=guest.get(path).get_data(as_text=True)
    return {'csrf':re.search(r'name="csrf-token" content="([^"]+)"',page).group(1),'reply_version':re.search(r'name="reply_version" value="([^"]+)"',page).group(1)}


def answers(guest,path,site,day='Accepted',evening='Accepted'):
    body=form(guest,path);body.update({'g1-rsvp':day,'g2-rsvp':evening,'g1-diet':'No nuts','g2-access':'Step-free entrance'})
    for i,course in enumerate(site['courses']):body[f'g{i+1}-course-'+course['id']]=course['choices'][0]['id']
    return body


def save_stationery(c,kind,**changes):
    data=c.get('/api/stationery').json['drafts'][kind];data['data'].update(date='2027-06-19',venue='Day Design Hall' if kind=='day' else 'Evening Design Hall',arrival='12.30pm' if kind=='day' else '7pm',recipient='PRIVATE RECIPIENT');data['data'].update(changes)
    result=c.put('/api/stationery/'+kind,json={'data':data['data'],'revision':data['revision'],'source':data['source']},headers=headers(c));assert result.status_code==200


def test_matching_scoped_designs_and_day_evening_information(app):
    c=login(app);setup(c);save_stationery(c,'day');save_stationery(c,'evening');configure(c,use_stationery=True)
    guest=app.test_client();path=link(c,('g2',));html=guest.get(path).get_data(as_text=True)
    for private in ['SECRET DAY CEREMONY','SECRET DAY TIMINGS','SECRET DAY MENU','Day Design Hall','PRIVATE RECIPIENT','g1-rsvp']:assert private not in html
    assert 'Evening Design Hall' in html and '19:00 Party' in html and 'Pizza' in html
    assert guest.get(path+'/design/evening.png').status_code==200
    assert guest.get(path+'/design/day.png').status_code==404
    assert guest.get(path+'/calendar/day.ics').status_code==404
    assert guest.get('/weddings/emma-and-jamie').status_code==200
    assert 'Wedding website access code' in guest.get('/weddings/emma-and-jamie').get_data(as_text=True)


def test_household_course_replies_and_confirmed_totals(app):
    c=login(app);s,site=setup(c);path=link(c);guest=app.test_client();body=answers(guest,path,site)
    response=guest.post(path,data=body,headers={'X-Requested-With':'guest-rsvp'});assert response.status_code==200,response.get_data(as_text=True)
    current=c.get('/api/state').json['state'];assert current['payments']==s['payments'];assert current['guests'][0]['meal']=='Main: Chicken';assert current['guests'][1]['meal']=='Evening snack: Pizza'
    summary=c.get('/api/guest-summary').json;assert summary['totals']['Day']['Accepted']==1;assert summary['courses'][0]['choices']['Chicken']==1
    assert not summary['waiting'];assert not any(g['review_needed'] for g in summary['guests'])
    invitation=c.get('/api/invitations').json['invitations'][0];assert invitation['reply_status']=='Replied' and invitation['mail_status']=='Link to share yourself'


def test_invalid_choices_atomic_with_wording_retained_and_retry(app):
    c=login(app);setup_state,site=setup(c);path=link(c);guest=app.test_client();body=answers(guest,path,site);original=copy.deepcopy(body)
    key='g1-course-'+site['courses'][0]['id'];body[key]='forged'
    response=guest.post(path,data=body);assert response.status_code==400 and 'No nuts' in response.get_data(as_text=True)
    assert c.get('/api/state').json['state']==setup_state
    original['reply_version']=re.search(r'name="reply_version" value="([^"]+)"',response.get_data(as_text=True)).group(1)
    assert guest.post(path,data=original).status_code==200


def test_declines_need_no_food_and_do_not_enter_totals(app):
    c=login(app);_,site=setup(c);path=link(c);guest=app.test_client();body=answers(guest,path,site,'Declined','Declined')
    for key in list(body):
        if '-course-' in key:body.pop(key)
    assert guest.post(path,data=body).status_code==200
    summary=c.get('/api/guest-summary').json;assert all(sum(x['choices'].values())==0 and x['missing']==0 for x in summary['courses'])
    assert not c.get('/api/state').json['state']['guests'][0]['meal']


def test_reply_conflicts_preserve_other_edits_and_prevent_overwrite(app):
    c=login(app);_,site=setup(c);path=link(c);guest=app.test_client();body=answers(guest,path,site)
    current=c.get('/api/state').json;current['state']['notes']='Partner is working';assert c.put('/api/state',json=current,headers=headers(c)).status_code==200
    assert guest.post(path,data=body).status_code==200
    assert c.get('/api/state').json['state']['notes']=='Partner is working'
    body['g1-rsvp']='Declined';response=guest.post(path,data=body,headers={'X-Requested-With':'guest-rsvp'});assert response.status_code==409
    assert c.get('/api/state').json['state']['guests'][0]['rsvp']=='Accepted'


def test_changed_menu_and_manual_meal_edits_require_review(app):
    c=login(app);_,site=setup(c);path=link(c);guest=app.test_client();assert guest.post(path,data=answers(guest,path,site)).status_code==200
    configure(c,courses=[{'label':'Main','audience':'Day','choices':['Fish','Vegan']},{'label':'Evening snack','audience':'Evening','choices':['Pizza','Falafel']}])
    summary=c.get('/api/guest-summary').json;assert summary['courses'][0]['missing']==1 and summary['courses'][0]['choices']['Fish']==0
    current=c.get('/api/state').json;current['state']['guests'][1]['meal']='Manually changed';assert c.put('/api/state',json=current,headers=headers(c)).status_code==200
    assert c.get('/api/guest-summary').json['courses'][1]['missing']==1


def test_calendar_uk_time_night_finish_and_no_private_token(app):
    c=login(app);setup(c);configure(c,venue_evening='Evening Hall, Manchester\nEntrance B');path=link(c,('g2',));guest=app.test_client();result=guest.get(path+'/calendar/evening.ics');assert result.status_code==200
    text=result.get_data(as_text=True);assert 'DTSTART:20270619T180000Z' in text and 'DTEND:20270620T000000Z' in text
    assert 'Evening Hall\\, Manchester\\nEntrance B' in text and 'SECRET DAY' not in text and path.rsplit('/',1)[1] not in text
    assert max(len(line) for line in result.data.split(b'\r\n'))<=75


def test_published_snapshot_stays_until_explicit_refresh_and_dates_match(app):
    c=login(app);setup(c);save_stationery(c,'day');configure(c,use_stationery=True);path=link(c,('g1',));guest=app.test_client()
    before=guest.get(path+'/design/day.png').data
    save_stationery(c,'day',venue='Changed draft venue');assert guest.get(path+'/design/day.png').data==before
    configure(c,refresh_stationery=True);assert guest.get(path+'/design/day.png').data!=before
    body=c.get('/api/website').json;body['site']['date']='2028-01-01';assert c.put('/api/website',json=body,headers=headers(c)).status_code==400


def test_preview_and_reports_private_and_exports_do_not_inject_csv(app):
    c=login(app);setup(c);state=c.get('/api/state').json;state['state']['guests'][0]['name']='=FORMULA';assert c.put('/api/state',json=state,headers=headers(c)).status_code==200
    before=c.get('/api/state').json;preview=c.get('/website/preview?audience=evening').get_data(as_text=True)
    assert 'SECRET DAY CEREMONY' not in preview and 'guest-rsvp-form' not in preview
    assert c.get('/api/state').json==before
    anonymous=app.test_client();assert anonymous.get('/api/guest-summary').status_code==401;assert anonymous.get('/api/guest-summary.csv').status_code==401
    csv=c.get('/api/guest-summary.csv').get_data(as_text=True);assert "'=FORMULA" in csv
    assert login(app,'mark@example.com',True).get('/api/guest-summary').status_code==403
    assert login(app,'two@example.com').get('/api/guest-summary').json['guests']==[]


def test_old_aliases_revocation_unpublish_suspend_and_photo_guard(app):
    c=login(app);setup(c);path=link(c,('g2',));guest=app.test_client();body=c.get('/api/website').json;body['slug']='our-new-address';assert c.put('/api/website',json=body,headers=headers(c)).status_code==200
    assert guest.get(path).status_code==200
    tid=c.get('/api/invitations').json['invitations'][0]['id'];assert c.post('/api/invitations/'+tid+'/revoke',json={},headers=headers(c)).status_code==200
    for suffix in ('','/calendar/evening.ics','/design/evening.png'):assert guest.get(path+suffix).status_code==404
    path=link(c,('g2',));configure(c,published=False);assert guest.get(path).status_code==404
    configure(c,published=True);db=database(app);db.execute('UPDATE weddings SET suspended=1 WHERE id="wu1"');db.commit();db.close();assert guest.get(path).status_code==404


def test_backup_export_and_guest_delete_include_reply_records(app,tmp_path):
    from app.worker import backup
    from scripts.test_restore import restore
    c=login(app);_,site=setup(c);path=link(c);guest=app.test_client();assert guest.post(path,data=answers(guest,path,site)).status_code==200
    assert len(c.get('/api/export').json['guest_replies'])==2
    archive=backup(app.config['DATA_DIR'],app.config['BACKUP_DIR']);target=tmp_path/'restored';target.mkdir()
    weddings,files=restore(archive,target);assert weddings>=1
    db=sqlite3.connect(target/'planner.sqlite3');assert db.execute('SELECT count(*) FROM guest_replies').fetchone()[0]==2;db.close()
    current=c.get('/api/state').json;current['state']['guests']=current['state']['guests'][:1];assert c.put('/api/state',json=current,headers=headers(c)).status_code==200
    assert len(c.get('/api/export').json['guest_replies'])==1


def test_invalid_course_configuration_and_guest_lists_rollback(app):
    c=login(app);setup(c);before=c.get('/api/website').json
    for courses in ('invalid',[{'label':'Main','audience':'Day','choices':[]}],[{'label':'Main','audience':'Day','choices':['Fish','fish']}],[{'label':'Main','audience':'Other','choices':['Fish']}]):
        body=copy.deepcopy(before);body['site']['courses']=courses;assert c.put('/api/website',json=body,headers=headers(c)).status_code==400
    assert c.get('/api/website').json==before
    for ids in ('g1',[{}],['g1','g1']):assert c.post('/api/invitations',json={'guest_ids':ids},headers=headers(c)).status_code==400


def test_snapshot_photo_ownership_and_delete_protection(app):
    c=login(app);setup(c);out=io.BytesIO();Image.new('RGB',(200,100),'green').save(out,'JPEG')
    uid=c.post('/api/files',data={'kind':'cover','file':(io.BytesIO(out.getvalue()),'our-photo.jpg')},headers=headers(c)).json['id']
    save_stationery(c,'day',collection='photo',palette='neutral',photo=uid);configure(c,use_stationery=True)
    save_stationery(c,'day',collection='botanical',palette='sage',photo='')
    assert c.delete('/api/files/'+uid,headers=headers(c)).status_code==400
    configure(c,use_stationery=False);assert c.delete('/api/files/'+uid,headers=headers(c)).status_code==200


def test_invitation_mail_tracking_uses_smtp_acceptance_not_delivery(app):
    c=login(app);setup(c)
    result=c.post('/api/invitations',json={'guest_ids':['g2'],'email':'guest@example.com'},headers=headers(c));assert result.status_code==200 and result.json['queued']
    invite=c.get('/api/invitations').json['invitations'][0];assert invite['mail_status']=='Queued'
    db=database(app);row=db.execute('SELECT * FROM mail WHERE to_address="guest@example.com"').fetchone();assert 'Open our invitation' in row['html_body'];assert 'SECRET DAY' not in row['html_body']
    db.execute('UPDATE mail SET status="retry" WHERE id=?',(row['id'],));db.commit();assert c.get('/api/invitations').json['invitations'][0]['mail_status']=='Retrying email'
    db.execute('UPDATE mail SET status="sent",accepted_at=123 WHERE id=?',(row['id'],));db.commit();db.close()
    invite=c.get('/api/invitations').json['invitations'][0];assert invite['mail_status']=='Accepted by mail server' and invite['mail_accepted_at']==123


def test_anonymous_expired_session_can_retry_with_fresh_csrf(app):
    c=login(app);_,site=setup(c);path=link(c);guest=app.test_client();body=answers(guest,path,site)
    db=database(app);db.execute('DELETE FROM sessions WHERE user_id IS NULL');db.commit();db.close()
    assert guest.post(path,data=body).status_code==403
    body['csrf']=guest.get('/api/session').json['csrf'];assert guest.post(path,data=body).status_code==200


def test_largest_supported_household_with_unicode_answers(app):
    c=login(app);setup(c);current=c.get('/api/state').json;base=current['state']['guests'][0]
    current['state']['guests']=[dict(base,id='g'+str(i).zfill(99),name='Guest '+str(i),rsvp='Waiting') for i in range(30)]
    assert c.put('/api/state',json=current,headers=headers(c)).status_code==200
    site=configure(c,courses=[{'label':'Course '+str(i),'audience':'Day','choices':['A'*100]} for i in range(6)])
    path=link(c,[g['id'] for g in current['state']['guests']]);guest=app.test_client();body=form(guest,path)
    for person in current['state']['guests']:
        prefix=person['id']+'-';body[prefix+'rsvp']='Accepted';body[prefix+'diet']='🍀'*160;body[prefix+'access']='🍀'*160
        for course in site['courses']:body[prefix+'course-'+course['id']]=course['choices'][0]['id']
    response=guest.post(path,data=body);assert response.status_code==200,response.status_code
    assert c.get('/api/guest-summary').json['totals']['Day']['Accepted']==30

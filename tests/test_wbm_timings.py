import json,time,uuid
from test_app import app,database,login,headers
from test_booking_connection import setup

def linked(app):
    _,machine=setup(app);db=database(app)
    state=json.loads(db.execute('SELECT state FROM weddings WHERE id="wu1"').fetchone()[0]);state['date']='2027-06-19';state['day']['venue']='Example Hall'
    db.execute('UPDATE weddings SET state=? WHERE id="wu1"',(json.dumps(state),));db.commit();db.close()
    body={'booking_id':str(uuid.uuid4()),'email':'one@example.com','wedding_date':'2027-06-19','template':{'revision':'fixture-v1','fields':[{'key':'day_contact','label':'Contact','enabled':True,'step':3,'kind':'builtin'}]}}
    r=app.test_client().post('/api/integrations/wbm/timings/link',json=body,headers=machine);assert r.status_code==200,r.json
    return body,machine

def test_scoping_and_csrf(app):
    one=login(app);two=login(app,'two@example.com');assert one.get('/api/wbm-timings').json=={'linked':False}
    body,machine=linked(app);assert one.get('/api/wbm-timings').json['linked'];assert two.get('/api/wbm-timings').json=={'linked':False}
    assert app.test_client().post('/api/integrations/wbm/timings/link',json=body).status_code==401
    assert app.test_client().post('/api/integrations/wbm/timings/link',json={**body,'wedding_date':'2027-06-20'},headers=machine).status_code==404
    assert one.post('/api/wbm-timings',json={}).status_code==403
    assert two.post('/api/wbm-timings',json={'confirmed':True,'answers':{}},headers=headers(two)).status_code==409

def test_snapshot_dedupe_ack_and_no_plan_or_mail_changes(app):
    body,machine=linked(app);c=login(app);v=c.get('/api/wbm-timings').json
    db=database(app);before=db.execute('SELECT state FROM weddings WHERE id="wu1"').fetchone()[0];mail=db.execute('SELECT count(*) FROM mail').fetchone()[0];db.close()
    payload={'answers':{'day_contact':'Example contact','_template_revision':'fixture-v1'},'confirmed':True,'revision':v['revision'],'hub_revision':v['hub_revision']}
    r=c.post('/api/wbm-timings',json=payload,headers=headers(c));assert r.status_code==201;assert r.json['status']=='queued'
    assert c.post('/api/wbm-timings',json=payload,headers=headers(c)).json['id']==r.json['id']
    url='/api/integrations/wbm/timings/'+body['booking_id']+'/ack';ack={'submission_id':r.json['id'],'status':'received'}
    assert c.post(url,json=ack).status_code==401;assert app.test_client().post(url,json=ack,headers=machine).status_code==200
    assert c.get('/api/wbm-timings').json['latest']['status']=='received'
    db=database(app);assert db.execute('SELECT count(*) FROM wbm_timing_submissions').fetchone()[0]==1
    assert db.execute('SELECT state FROM weddings WHERE id="wu1"').fetchone()[0]==before
    assert db.execute('SELECT count(*) FROM mail').fetchone()[0]==mail;db.close()

def test_stale_revision_and_lease_block_sending(app):
    linked(app);c=login(app);v=c.get('/api/wbm-timings').json;db=database(app)
    db.execute('UPDATE weddings SET revision=revision+1 WHERE id="wu1"');db.commit();db.close()
    payload={'answers':{'_template_revision':'fixture-v1'},'confirmed':True,'revision':v['revision'],'hub_revision':v['hub_revision']}
    assert c.post('/api/wbm-timings',json=payload,headers=headers(c)).status_code==409
    db=database(app);db.execute('UPDATE wbm_timing_links SET checked_at=?',(time.time()-601,));db.commit();db.close()
    assert c.get('/api/wbm-timings').json=={'linked':False}

def test_backup_restores_pending_timings_without_delivery(app,tmp_path):
    from pathlib import Path
    from app.worker import backup
    from scripts.test_restore import restore
    linked(app);c=login(app);v=c.get('/api/wbm-timings').json
    payload={'answers':{'day_contact':'Example contact','_template_revision':'fixture-v1'},'confirmed':True,'revision':v['revision'],'hub_revision':v['hub_revision']}
    response=c.post('/api/wbm-timings',json=payload,headers=headers(c));assert response.status_code==201
    archive=backup(Path(app.config['DATA_DIR']),tmp_path/'archives')
    restored=tmp_path/'restored';restored.mkdir()
    assert restore(archive,restored)[0]>=1
    import sqlite3
    with sqlite3.connect(restored/'planner.sqlite3') as db:
        row=db.execute('SELECT id,status,payload FROM wbm_timing_submissions').fetchone()
        assert row[0]==response.json['id'] and row[1]=='queued'
        assert json.loads(row[2])['answers']['day_contact']=='Example contact'

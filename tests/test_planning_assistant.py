import copy
import io
import json
import secrets
import time
import pytest
from test_app import app,login,headers,database,prepare
from app import planning_assistant as ai


def body(task='invitation',**extra):
    return dict(request_id=secrets.token_hex(16),task=task,consent=True,kind='day',collection='deco',palette='midnight',tone='relaxed',arrival='Arrive at 12.30pm',instructions='Friendly wording please',table_count=2,seats=3,shape='round',together=[],apart=[],**extra)


def result(payload):
    context=json.loads(payload['input'])
    if context['task']=='invitation':output={'summary':'A relaxed invitation.','intro':'Together with their families','message':'invite you to celebrate their wedding','closing':'Reception and celebrations to follow'}
    else:
        ts=context['tables'];output={'summary':'A seating suggestion.','assignments':[{'guest_id':g['id'],'table_id':ts[i//3]['id']} for i,g in enumerate(context['guests'])]}
    return {'status':'completed','model':ai.MODEL,'output':[{'type':'message','content':[{'type':'output_text','text':json.dumps(output)}]}],'usage':{'input_tokens':1000,'output_tokens':1000}}


@pytest.fixture
def enabled(app,monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY','test-only-not-a-real-key');calls=[]
    def provider(payload):calls.append(copy.deepcopy(payload));return result(payload)
    monkeypatch.setattr(ai,'provider_request',provider)
    db=database(app);state=json.loads(db.execute('SELECT state FROM weddings WHERE id="wu1"').fetchone()[0]);state['date']='2027-06-19';state['day']['venue']='The Garden House';state['notes']='PRIVATE FAMILY NOTE'
    state['guests']=[dict(id='g'+str(i),name='Sample Guest '+str(i),household='Sample household',attendance='Day',rsvp='Accepted',meal='PRIVATE MEAL',diet='PRIVATE DIET',access='PRIVATE ACCESS',table='') for i in range(4)]
    db.execute('UPDATE weddings SET state=? WHERE id="wu1"',(json.dumps(state),));db.execute('INSERT OR REPLACE INTO settings VALUES("assistant_enabled","true")');db.commit();db.close()
    return app,calls


def generate(client,data=None):return client.post('/api/assistant/generate',json=data or body(),headers=headers(client))
def action(client,jid,kind,**data):return client.post('/api/assistant/'+jid+'/'+kind,json=data or {'confirmed':True},headers=headers(client))


def test_disabled_by_default_no_key_no_provider_calls(app,monkeypatch):
    monkeypatch.delenv('OPENAI_API_KEY',raising=False)
    monkeypatch.setattr(ai,'provider_request',lambda _:pytest.fail('Disabled assistant reached provider'))
    c=login(app);assert c.get('/assistant').status_code==200;assert c.get('/api/assistant').json['enabled'] is False
    assert generate(c).status_code==409
    admin=login(app,'mark@example.com',True)
    assert admin.put('/api/admin/assistant/settings',json=ai.DEFAULTS|{'assistant_enabled':True},headers=headers(admin)).status_code==400


def test_full_invitation_preview_apply_undo_and_idempotency(enabled):
    app,calls=enabled;c=login(app);before=c.get('/api/state').json;before_stationery=c.get('/api/stationery').json
    data=body();response=generate(c,data);assert response.status_code==200,response.json
    job=response.json['job'];assert job['status']=='ready' and response.json['allowance']['remaining']==2
    assert c.get('/api/state').json==before and c.get('/api/stationery').json==before_stationery
    assert generate(c,data).json['job']['id']==job['id'] and len(calls)==1
    preview=c.get('/api/assistant/'+job['id']+'/preview.png');assert preview.status_code==200 and preview.data.startswith(b'\x89PNG')
    assert action(c,job['id'],'apply',confirmed=False).status_code==400
    assert action(c,job['id'],'apply').status_code==200
    saved=c.get('/api/stationery').json['drafts']['day'];assert saved['revision']==1 and saved['data']['collection']=='deco'
    assert action(c,job['id'],'apply').status_code==200 and c.get('/api/stationery').json['drafts']['day']['revision']==1
    assert action(c,job['id'],'undo').status_code==200;assert c.get('/api/stationery').json['drafts']['day']['revision']==0
    assert c.get('/api/state').json==before
    payload=calls[0];assert payload['model']=='gpt-6.1-sol' and payload['reasoning']=={'effort':'medium','mode':'standard'}
    assert payload['store'] is False and payload['service_tier']=='default' and 'tools' not in payload
    assert payload['max_output_tokens']==8192 and payload['text']['format']['strict'] is True
    assert 'PRIVATE' not in payload['input'] and 'test-only-not-a-real-key' not in json.dumps(response.json)


def test_auth_csrf_expiry_and_cross_couple_isolation(enabled):
    app,_=enabled;c=login(app);other=login(app,'two@example.com');admin=login(app,'mark@example.com',True)
    assert app.test_client().get('/api/assistant').status_code==401
    assert admin.get('/api/assistant').status_code==403
    assert c.get('/api/admin/assistant').status_code==403
    assert c.post('/api/assistant/generate',json=body()).status_code==403
    job=generate(c).json['job']
    assert other.get('/api/assistant/'+job['id']+'/preview.png').status_code==404
    assert action(other,job['id'],'apply').status_code==404
    assert action(other,job['id'],'report',reason='not mine').status_code==404
    db=database(app);db.execute('UPDATE weddings SET access_until="2000-01-01" WHERE id="wu1"');db.commit();db.close()
    assert generate(c).status_code==403 and action(c,job['id'],'apply').status_code==403


def test_shared_partner_allowance_not_reset_by_different_kind(enabled):
    app,calls=enabled;c=login(app);other=login(app,'two@example.com');db=database(app)
    db.execute('DELETE FROM members WHERE user_id="u2"');db.execute('INSERT INTO members VALUES("wu1","u2")');db.commit();db.close()
    for i in range(3):assert generate(c if i%2==0 else other,body()).status_code==200
    assert c.get('/api/assistant').json['allowance']['invitation']['remaining']==0
    fourth=body();fourth['kind']='evening';assert generate(other,fourth).status_code==409 and len(calls)==3


def test_seating_apply_capacity_private_data_and_undo(enabled):
    app,calls=enabled;c=login(app);before=c.get('/api/state').json
    response=generate(c,body('seating'));assert response.status_code==200,response.json;job=response.json['job']
    assert c.get('/api/hub').json['tables']==[]
    assert action(c,job['id'],'apply').status_code==200
    state=c.get('/api/state').json;assert [g['table'] for g in state['state']['guests']]==['Table 1','Table 1','Table 1','Table 2']
    assert len(c.get('/api/hub').json['tables'])==2
    assert all(secret not in calls[0]['input'] for secret in ['PRIVATE','one@example.com','payment','diet'])
    assert action(c,job['id'],'undo').status_code==200
    assert c.get('/api/state').json['state']==before['state'] and not c.get('/api/hub').json['tables']


@pytest.mark.parametrize('bad',['duplicate','missing','foreign','capacity','apart','together'])
def test_invalid_seating_never_saves_or_uses_round(enabled,monkeypatch,bad):
    app,_=enabled;c=login(app);before=c.get('/api/state').json;data=body('seating')
    if bad=='apart':data['apart']=[['g0','g1']]
    if bad=='together':data['together']=[['g2','g3']]
    def provider(payload):
        r=result(payload);value=json.loads(r['output'][0]['content'][0]['text']);rows=value['assignments']
        if bad=='duplicate':rows[1]['guest_id']=rows[0]['guest_id']
        if bad=='missing':rows.pop()
        if bad=='foreign':rows[0]['guest_id']='another-wedding-guest'
        if bad=='capacity':
            for row in rows:row['table_id']=rows[0]['table_id']
        r['output'][0]['content'][0]['text']=json.dumps(value);return r
    monkeypatch.setattr(ai,'provider_request',provider)
    assert generate(c,data).status_code==502
    assert c.get('/api/state').json==before and c.get('/api/assistant').json['allowance']['seating']['remaining']==3
    db=database(app);assert db.execute('SELECT sum(charged) FROM ai_costs').fetchone()[0]>0;db.close()


def test_impossible_seating_checked_before_provider(enabled):
    app,calls=enabled;c=login(app);data=body('seating');data.update(table_count=1,seats=2)
    assert generate(c,data).status_code==400
    data=body('seating');data.update(together=[['g0','g1']],apart=[['g0','g1']]);assert generate(c,data).status_code==400
    assert not calls


def test_existing_tables_preserve_other_guest_capacity(enabled):
    app,calls=enabled;c=login(app);db=database(app)
    for i in range(2):db.execute('INSERT INTO hub_tables VALUES(?,?,?,?,?,?,?)',('t'+str(i),'wu1','Rose' if i==0 else 'Lily',3,'round',20,20))
    state=json.loads(db.execute('SELECT state FROM weddings WHERE id="wu1"').fetchone()[0]);state['guests'].append(dict(state['guests'][0],id='waiting',name='Waiting guest',rsvp='Waiting',table='Rose'))
    db.execute('UPDATE weddings SET state=? WHERE id="wu1"',(json.dumps(state),));db.commit();db.close()
    # Fake provider seats 3 at Rose: one seat is already reserved for the waiting guest.
    assert generate(c,body('seating')).status_code==502
    assert json.loads(calls[0]['input'])['tables'][0]['available']==2


def test_stale_proposal_and_undo_protect_newer_work(enabled):
    app,_=enabled;c=login(app);job=generate(c).json['job'];state=c.get('/api/state').json;state['state']['names']=['New','Names']
    assert c.put('/api/state',json={'state':state['state'],'revision':state['revision']},headers=headers(c)).status_code==200
    assert action(c,job['id'],'apply').status_code==409
    newer=generate(c).json['job'];assert action(c,newer['id'],'apply').status_code==200
    draft=c.get('/api/stationery').json['drafts']['day'];draft['data']['message']='Newer manual wording'
    assert c.put('/api/stationery/day',json={k:draft[k] for k in ['data','revision','source']},headers=headers(c)).status_code==200
    assert action(c,newer['id'],'undo').status_code==409
    assert c.get('/api/stationery').json['drafts']['day']['data']['message']=='Newer manual wording'


def test_plan_changes_during_generation_dont_consume_round(enabled,monkeypatch):
    app,_=enabled;c=login(app)
    def provider(payload):
        db=database(app);state=json.loads(db.execute('SELECT state FROM weddings WHERE id="wu1"').fetchone()[0]);state['names']=['Changed','Together'];db.execute('UPDATE weddings SET state=?,revision=revision+1 WHERE id="wu1"',(json.dumps(state),));db.commit();db.close();return result(payload)
    monkeypatch.setattr(ai,'provider_request',provider)
    assert generate(c).status_code==502
    assert c.get('/api/assistant').json['allowance']['invitation']['remaining']==3


@pytest.mark.parametrize('failure',['timeout','refusal','incomplete','bad_json','long_wording'])
def test_provider_failures_account_cost_without_using_round(enabled,monkeypatch,failure):
    app,_=enabled;c=login(app)
    def provider(payload):
        if failure=='timeout':raise TimeoutError('secret-provider-details-must-not-escape')
        r=result(payload)
        if failure=='refusal':r['output'][0]['content']=[{'type':'refusal','refusal':'Cannot'}]
        if failure=='incomplete':r['status']='incomplete'
        if failure=='bad_json':r['output'][0]['content'][0]['text']='not JSON'
        if failure=='long_wording':r['output'][0]['content'][0]['text']=json.dumps({'summary':'ok','intro':'a'*1000,'message':'ok','closing':'ok'})
        return r
    monkeypatch.setattr(ai,'provider_request',provider)
    r=generate(c);assert r.status_code==502 and 'secret-provider' not in r.get_data(as_text=True)
    assert c.get('/api/assistant').json['allowance']['invitation']['remaining']==3
    db=database(app);column='reserved' if failure=='timeout' else 'charged';assert db.execute('SELECT sum('+column+') FROM ai_costs').fetchone()[0]>0;db.close()


def test_running_duplicate_and_changed_idempotency_request(enabled,monkeypatch):
    app,calls=enabled;c=login(app);data=body();r=generate(c,data);assert r.status_code==200
    changed=data|{'instructions':'Different'};assert generate(c,changed).status_code==409 and len(calls)==1
    db=database(app);db.execute('UPDATE ai_drafts SET status="running",counted=0 WHERE id=?',(data['request_id'],));db.commit();db.close()
    assert generate(c).status_code==409 and len(calls)==1


@pytest.mark.parametrize('limit',['assistant_monthly_microusd','assistant_couple_microusd'])
def test_budget_reservation_stops_call_before_provider(enabled,limit):
    app,calls=enabled;c=login(app);db=database(app);db.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',(limit,'1'));db.commit();db.close()
    assert generate(c).status_code==409 and not calls


def test_report_and_one_time_admin_correction_credit(enabled):
    app,_=enabled;c=login(app);job=generate(c).json['job'];assert action(c,job['id'],'report',reason='Assistant added the wrong closing line').status_code==200
    assert c.post('/api/admin/assistant/correction/'+job['id'],json={'checked':True},headers=headers(c)).status_code==403
    admin=login(app,'mark@example.com',True)
    for _ in range(2):assert admin.post('/api/admin/assistant/correction/'+job['id'],json={'checked':True},headers=headers(admin)).status_code==200
    assert c.get('/api/assistant').json['allowance']['invitation']['remaining']==3


def test_paid_revision_topup_requires_verification_and_unique_payment(enabled):
    app,_=enabled;c=login(app);admin=login(app,'mark@example.com',True)
    payload=dict(wedding_id='wu1',task='invitation',quantity=2,amount=400,transaction_id='PAYMENT-UNIQUE-1',verified=True)
    assert admin.post('/api/admin/assistant/credits',json=payload,headers=headers(admin)).status_code==400
    db=database(app);db.execute('INSERT OR REPLACE INTO settings VALUES("assistant_revision_pence","200")');db.commit();db.close()
    assert admin.post('/api/admin/assistant/credits',json=payload|{'verified':False},headers=headers(admin)).status_code==400
    assert admin.post('/api/admin/assistant/credits',json=payload,headers=headers(admin)).status_code==200
    assert admin.post('/api/admin/assistant/credits',json=payload,headers=headers(admin)).status_code==400
    assert c.get('/api/assistant').json['allowance']['invitation']['remaining']==5
    db=database(app);assert db.execute('SELECT access_kind FROM weddings WHERE id="wu1"').fetchone()[0]=='Trial';db.close()


def test_deletion_removes_private_drafts_but_retains_anonymous_costs(enabled):
    from app.couple_deletion import manifest,purge_rows
    app,_=enabled;c=login(app);assert generate(c).status_code==200
    db=database(app);before=db.execute('SELECT sum(charged) FROM ai_costs').fetchone()[0];purge_rows(db,'wu1',manifest(db,'wu1'));db.commit()
    assert not db.execute('SELECT 1 FROM ai_drafts').fetchone();assert db.execute('SELECT sum(charged) FROM ai_costs').fetchone()[0]==before
    assert not db.execute('PRAGMA foreign_key_check').fetchone();db.close()


def test_simultaneous_couple_requests_share_atomic_global_budget(enabled,monkeypatch):
    import threading
    app,calls=enabled;c=login(app);other=login(app,'two@example.com');db=database(app)
    state=db.execute('SELECT state FROM weddings WHERE id="wu1"').fetchone()[0]
    db.execute('UPDATE weddings SET state=? WHERE id="wu2"',(state,));db.execute('INSERT OR REPLACE INTO settings VALUES("assistant_monthly_microusd","140000")');db.commit();db.close()
    entered=threading.Event();release=threading.Event();responses=[]
    def provider(payload):calls.append(payload);entered.set();assert release.wait(5);return result(payload)
    monkeypatch.setattr(ai,'provider_request',provider)
    def first():responses.append(generate(c))
    thread=threading.Thread(target=first);thread.start();assert entered.wait(5)
    try:
        assert generate(other).status_code==409
        assert len(calls)==1
    finally:release.set();thread.join(8)
    assert not thread.is_alive() and responses[0].status_code==200


def test_paid_topup_receipt_cannot_also_activate_planner_access(enabled):
    app,_=enabled;admin=login(app,'mark@example.com',True);db=database(app)
    db.execute('INSERT OR REPLACE INTO settings VALUES("assistant_revision_pence","200")');db.commit();db.close()
    payload=dict(wedding_id='wu1',task='invitation',quantity=1,amount=200,transaction_id='SAME-TRANSACTION',verified=True)
    assert admin.post('/api/admin/assistant/credits',json=payload,headers=headers(admin)).status_code==200
    db=database(app);db.execute('INSERT INTO purchases(id,wedding_id,amount,terms,created) VALUES("p","wu1",200,?,?)',(json.dumps({'provider':'bank','accepted_at':time.time()}),time.time()));db.commit();db.close()
    result=admin.post('/api/admin/paypal/p/confirm',json={'verified':True,'transaction_id':'SAME-TRANSACTION','amount_pence':200,'currency':'GBP'},headers=headers(admin))
    assert result.status_code==400 and 'AI revisions' in result.json['error']


def test_private_export_includes_own_drafts_without_keys_or_provider_ledger(enabled):
    app,_=enabled;c=login(app);job=generate(c).json['job'];exported=c.get('/api/export').json
    assert exported['assistant_drafts'][0]['id']==job['id']
    assert 'test-only-not-a-real-key' not in json.dumps(exported)
    assert 'ai_costs' not in exported


def test_key_setup_preserves_other_environment_and_hides_key(tmp_path):
    from scripts.configure_assistant_key import save_key
    env=tmp_path/'private.env';original='OTHER_SECRET=keep-this\nOPENAI_API_KEY=old\n# existing comment\nOPENAI_API_KEY=duplicate\n';env.write_text(original)
    key='sk-test-only-abcdefghijklmnopqrstuvwxyz';backup=save_key(env,key)
    assert backup.read_text()==original and backup.stat().st_mode&0o777==0o600
    assert env.read_text().count('OPENAI_API_KEY=')==1 and 'OTHER_SECRET=keep-this' in env.read_text()
    assert env.stat().st_mode&0o777==0o600
    with pytest.raises(ValueError):save_key(env,'invalid\nBAD=value')


def test_known_provider_auth_rejection_releases_reserve_and_pauses_assistant(enabled,monkeypatch):
    import urllib.error
    app,_=enabled;c=login(app)
    def reject(_):raise urllib.error.HTTPError('https://api.openai.com/v1/responses',401,'Unauthorised',{},None)
    monkeypatch.setattr(ai,'provider_request',reject)
    assert generate(c).status_code==502
    ctx=c.get('/api/assistant').json;assert ctx['enabled'] is False and ctx['allowance']['invitation']['remaining']==3
    db=database(app);assert db.execute('SELECT sum(reserved) FROM ai_costs').fetchone()[0]==0;db.close()


def test_current_wedding_details_used_over_stale_invitation_wording(enabled):
    from test_stationery import save_design
    app,calls=enabled;c=login(app);save_design(c,changes={'names':'Old & Names','date':'2025-01-01','venue':'Old Venue'})
    r=generate(c);assert r.status_code==200
    data=r.json['job']['proposal']['data'];assert data['names']=='Emma & Jamie' and data['date']=='2027-06-19' and data['venue']=='The Garden House'
    assert 'Old Venue' not in calls[0]['input']

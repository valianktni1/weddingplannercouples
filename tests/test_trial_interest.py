import time
from test_app import app,login,headers,database


def submit(c,**fields):
    return c.post('/trial-interest',data={'csrf':headers(c,'/trial-interest')['X-CSRF-Token'],'email':'interested@example.com','name':'Emma','consent':'yes',**fields})


def test_closed_signup_captures_consent_without_account_or_email(app):
    c=app.test_client();page=c.get('/?welcome=1');assert b'Let me know when trials open' in page.data
    assert c.get('/signup').location=='/trial-interest'
    c.get('/trial-interest');assert submit(c,consent='').status_code==400
    assert submit(c,email='not-an-email').status_code==400
    assert submit(c,source='website').status_code==303
    assert submit(c).status_code==303
    db=database(app);r=db.execute('SELECT * FROM trial_interest').fetchone();assert r['source']=='website' and r['consent'] and not r['contacted']
    assert db.execute('SELECT count(*) FROM trial_interest').fetchone()[0]==1
    assert not db.execute('SELECT 1 FROM users WHERE email="interested@example.com"').fetchone()
    assert not db.execute('SELECT 1 FROM mail WHERE to_address="interested@example.com"').fetchone();db.close()


def test_interest_permissions_csv_and_followup_deletion(app):
    c=app.test_client();c.get('/trial-interest');assert submit(c,name='=FORMULA()',source='<script>bad</script>').status_code==303
    assert c.get('/ivoryadmin/interest').status_code in (302,401)
    couple=login(app);assert couple.get('/api/admin/interest.csv').status_code==403
    a=login(app,'mark@example.com',True);page=a.get('/ivoryadmin/interest');assert b'&lt;script&gt;' in page.data
    csv=a.get('/api/admin/interest.csv');assert csv.status_code==200 and b"'=FORMULA()" in csv.data
    db=database(app);oid=db.execute('SELECT id FROM trial_interest').fetchone()[0];db.close()
    assert a.post('/ivoryadmin/interest',data={'id':oid,'action':'delete'}).status_code==403
    body={'csrf':headers(a)['X-CSRF-Token'],'id':oid,'action':'contacted'}
    assert a.post('/ivoryadmin/interest',data=body).status_code==303
    db=database(app);assert db.execute('SELECT contacted FROM trial_interest').fetchone()[0];db.close()
    body['action']='delete';assert a.post('/ivoryadmin/interest',data=body).status_code==303
    assert b'No trial interest recorded' in a.get('/ivoryadmin/interest').data


def test_interest_honeypot_expiry_and_open_signup(app):
    c=app.test_client();c.get('/trial-interest');assert submit(c,website='spam').status_code==303
    db=database(app);assert db.execute('SELECT count(*) FROM trial_interest').fetchone()[0]==0;db.close()
    assert submit(c).status_code==303
    db=database(app);db.execute('UPDATE trial_interest SET created=?',(time.time()-181*86400,));db.commit();db.close()
    a=login(app,'mark@example.com',True);assert b'No trial interest recorded' in a.get('/ivoryadmin/interest').data


def test_open_trials_keep_normal_signup_and_optional_interest(app):
    db=database(app);db.execute('UPDATE settings SET value="true" WHERE key="signups_enabled"');db.commit();db.close()
    c=app.test_client();assert b'Start your trial' in c.get('/?welcome=1').data
    assert b'Create your planner' in c.get('/signup').data
    assert b'Start your trial now' in c.get('/trial-interest').data

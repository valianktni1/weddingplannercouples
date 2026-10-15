import json
import pytest
from app.core import config
from test_app import app,login,headers,database
from test_paypal import open_paypal,start,confirm

BANK={'bank_name':'Test Bank','bank_account_name':'Test Recipient','bank_sort_code':'00-11-22','bank_account_number':'00123456','bank_instructions':'Use your wedding payment reference.'}


def setup_bank(app):
    admin=open_paypal(app)
    assert admin.put('/api/admin/settings',json=BANK,headers=headers(admin,'/ivoryadmin')).status_code==200
    return admin


def request(admin,wid='wu1',provider='bank',send=False):
    return admin.post('/api/admin/payments/request/'+wid,json={'provider':provider,'send_email':send},headers=headers(admin,'/ivoryadmin'))


def accept(c,p):
    return c.post('/api/payments/'+p['id']+'/accept',json={'accept_terms':True},headers=headers(c))


def test_admin_bank_request_overrides_default_paypal_and_confirms_only_after_checks(app):
    admin=setup_bank(app);c=login(app);result=request(admin);assert result.status_code==200
    p=result.json['request'];assert p['provider']=='bank' and not p['accepted'];assert p['bank']['account_number']=='00123456' and p['bank']['sort_code']=='001122'
    assert c.get('/api/billing').json['provider']=='paypalme' # the global default is not changed
    assert c.get('/api/billing').json['payment_request']['id']==p['id']
    assert not c.get('/api/billing').json['already_active']
    assert confirm(admin,p).status_code==400 # admin cannot skip the couple's terms
    assert accept(c,p).status_code==200
    report=c.post('/api/payments/'+p['id']+'/report',json={'payer_name':'Example Payer','payment_date':'2026-10-15'},headers=headers(c));assert report.status_code==200
    assert not c.get('/api/billing').json['already_active']
    assert admin.get('/api/admin').json['manual_payments'][0]['reported_payer']=='Example Payer'
    assert confirm(admin,p,transaction_id='BANK-STATEMENT-12345',amount_pence=2400).status_code==400
    assert confirm(admin,p,transaction_id='BANK-STATEMENT-12345').status_code==200
    assert confirm(admin,p,transaction_id='BANK-STATEMENT-12345').status_code==200
    assert c.get('/api/billing').json['already_active']
    db=database(app);assert db.execute('SELECT count(*) n FROM bank_receipts').fetchone()['n']==1;assert db.execute('SELECT count(*) n FROM paypal_receipts').fetchone()['n']==0;db.close()


def test_per_couple_methods_are_independent_and_old_details_frozen(app):
    admin=setup_bank(app);one=request(admin).json['request'];two=request(admin,'wu2','paypalme').json['request']
    assert one['provider']=='bank' and two['provider']=='paypalme'
    assert request(admin,provider='paypalme').status_code==400
    assert admin.put('/api/admin/settings',json={'bank_account_number':'00987654','price_pence':3500},headers=headers(admin,'/ivoryadmin')).status_code==200
    current=login(app).get('/api/billing').json['payment_request'];assert current['bank']['account_number']=='00123456' and current['amount_pence']==2500


def test_request_email_only_to_verified_members_contains_no_bank_details_and_dedupes(app):
    admin=setup_bank(app);assert admin.put('/api/admin/settings',json={'sender':'planner@example.com'},headers=headers(admin,'/ivoryadmin')).status_code==200
    db=database(app);db.execute('DELETE FROM members WHERE user_id="u2"');db.execute('INSERT INTO members VALUES("wu1","u2")');db.commit();db.close()
    result=request(admin,send=True);assert result.status_code==200 and result.json['queued']==2
    assert request(admin,send=True).json['queued']==0
    db=database(app);rows=db.execute('SELECT * FROM mail WHERE subject="Your wedding planner payment request"').fetchall()
    assert {r['to_address'] for r in rows}=={'one@example.com','two@example.com'}
    for row in rows:
        assert '/upgrade' in row['body'] and 'Bank transfer' in row['body'] and '£25.00' in row['body']
        assert BANK['bank_account_number'] not in row['body'] and BANK['bank_account_name'] not in row['body']
    db.close()


def test_bank_details_not_public_or_visible_to_other_wedding(app):
    admin=setup_bank(app);p=request(admin).json['request'];other=login(app,'two@example.com')
    assert p['id'] not in str(other.get('/api/billing').json)
    assert other.post('/api/payments/'+p['id']+'/accept',json={'accept_terms':True},headers=headers(other)).status_code==404
    assert other.post('/api/payments/'+p['id']+'/report',json={'payer_name':'Wrong','payment_date':'2026-10-15'},headers=headers(other)).status_code==404
    assert BANK['bank_account_number'] not in app.test_client().get('/').text
    assert other.post('/api/admin/payments/request/wu1',json={'provider':'bank'},headers=headers(other)).status_code==403


@pytest.mark.parametrize('bad',[
    {'bank_sort_code':'12345'},{'bank_sort_code':123456},{'bank_sort_code':'12ab56'},
    {'bank_account_number':'1234567'},{'bank_account_number':12345678},{'bank_account_name':['name']},
    {'bank_account_name':'Bad\r\nHeader'},
])
def test_invalid_bank_setup_is_rejected_and_not_saved(app,bad):
    admin=setup_bank(app);db=database(app);before=config(db);db.close()
    assert admin.put('/api/admin/settings',json=bad,headers=headers(admin,'/ivoryadmin')).status_code==400
    db=database(app);assert config(db)==before;db.close()


def test_bank_self_service_and_missing_setup_guards(app):
    admin=open_paypal(app)
    assert request(admin).status_code==400
    assert admin.put('/api/admin/settings',json={'payment_provider':'bank'},headers=headers(admin,'/ivoryadmin')).status_code==400
    assert admin.put('/api/admin/settings',json={**BANK,'payment_provider':'bank'},headers=headers(admin,'/ivoryadmin')).status_code==200
    c=login(app);p=start(c);assert p['provider']=='bank' and p['accepted']


def test_reported_bank_reference_cannot_verify_two_weddings(app):
    admin=setup_bank(app);p=request(admin).json['request'];q=request(admin,'wu2').json['request']
    assert accept(login(app),p).status_code==200;assert accept(login(app,'two@example.com'),q).status_code==200
    assert confirm(admin,p,transaction_id='BANK-ENTRY-12345').status_code==200
    assert confirm(admin,q,transaction_id='bank-entry-12345').status_code==400


def test_email_configuration_failure_rolls_back_request(app,monkeypatch):
    monkeypatch.delenv('SMTP_HOST',raising=False);admin=setup_bank(app)
    assert request(admin,send=True).status_code==400
    db=database(app);assert db.execute('SELECT count(*) n FROM purchases').fetchone()['n']==0;db.close()


def test_admin_can_target_request_when_public_payments_closed(app):
    admin=setup_bank(app);assert admin.put('/api/admin/settings',json={'checkout_enabled':False},headers=headers(admin,'/ivoryadmin')).status_code==200
    result=request(admin);assert result.status_code==200
    c=login(app);assert accept(c,result.json['request']).status_code==200
    assert c.get('/api/billing').json['payment_request']['provider']=='bank'


def test_closed_unpaid_request_can_be_replaced_with_other_method(app):
    admin=setup_bank(app);p=request(admin).json['request']
    assert admin.post('/api/admin/payments/'+p['id']+'/close',json={'verified':True},headers=headers(admin,'/ivoryadmin')).status_code==200
    new=request(admin,provider='paypalme');assert new.status_code==200 and new.json['request']['provider']=='paypalme'

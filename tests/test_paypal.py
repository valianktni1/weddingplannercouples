import json
import time
import pytest
from app.core import config
from test_app import app,login,headers,database


def open_paypal(app):
    admin=login(app,'mark@example.com',True)
    response=admin.put('/api/admin/settings',json={'payment_provider':'paypalme','paypal_me_url':'https://paypal.me/weddingsbymark',
        'price_pence':2500,'refund_terms':'14-day full refund','terms_text':'Payment terms','checkout_enabled':True},headers=headers(admin,'/ivoryadmin'))
    assert response.status_code==200,response.json
    return admin


def start(c):
    result=c.post('/api/paypal/start',json={'accept_terms':True},headers=headers(c));assert result.status_code==200,result.json
    return result.json['request']


def confirm(admin,p,**changes):
    body={'verified':True,'transaction_id':'PAYPAL-TEST-12345','amount_pence':2500,'currency':'GBP'};body.update(changes)
    return admin.post('/api/admin/paypal/'+p['id']+'/confirm',json=body,headers=headers(admin,'/ivoryadmin'))


def test_paypal_instructions_report_verify_and_no_double_sale(app):
    admin=open_paypal(app);c=login(app);p=start(c)
    assert p['url']=='https://paypal.me/weddingsbymark/25.00GBP' and p['currency']=='GBP' and p['reference'].startswith('IP-')
    assert start(c)['id']==p['id']
    info=c.get('/api/billing').json;assert info['provider']=='paypalme' and info['paypal_request']['id']==p['id'] and not info['already_active']
    assert c.post('/api/paypal/'+p['id']+'/report',json={'transaction_id':'CLAIMED-12345'},headers=headers(c)).status_code==200
    assert not c.get('/api/billing').json['already_active']
    assert admin.get('/api/admin').json['status']['paid_sales_pence']==0
    assert admin.get('/api/admin').json['paypal_payments'][0]['status']=='reported'
    assert confirm(admin,p).status_code==200
    assert confirm(admin,p).status_code==200
    info=c.get('/api/billing').json;assert info['already_active'] and info['paypal_request'] is None
    assert admin.get('/api/admin').json['status']['paid_sales_pence']==2500
    assert c.post('/api/paypal/start',json={'accept_terms':True},headers=headers(c)).status_code==400
    db=database(app);assert db.execute('SELECT count(*) n FROM paypal_receipts').fetchone()['n']==1;db.close()


@pytest.mark.parametrize('changes',[
    {'verified':False},{'amount_pence':2499},{'amount_pence':True},{'currency':'USD'},
    {'transaction_id':''},{'transaction_id':'<script>'},
])
def test_confirmation_requires_verified_matching_payment(app,changes):
    admin=open_paypal(app);c=login(app);p=start(c)
    assert confirm(admin,p,**changes).status_code==400
    assert not c.get('/api/billing').json['already_active']
    assert admin.get('/api/admin').json['status']['paid_sales_pence']==0


def test_paypal_membership_csrf_and_admin_boundaries(app):
    admin=open_paypal(app);c=login(app);other=login(app,'two@example.com');p=start(c)
    assert c.post('/api/paypal/'+p['id']+'/report',json={'transaction_id':'ABC-12345'}).status_code==403
    assert other.post('/api/paypal/'+p['id']+'/report',json={'transaction_id':'ABC-12345'},headers=headers(other)).status_code==404
    assert p['id'] not in str(other.get('/api/billing').json)
    assert c.post('/api/admin/paypal/'+p['id']+'/confirm',json={},headers=headers(c)).status_code==403
    assert app.test_client().get('/upgrade').status_code==302
    assert c.post('/api/paypal/start',json={'accept_terms':False},headers=headers(c)).status_code==400


def test_paypal_transaction_cannot_pay_for_two_weddings(app):
    admin=open_paypal(app);one=login(app);two=login(app,'two@example.com');a=start(one);b=start(two)
    assert confirm(admin,a).status_code==200
    assert confirm(admin,b,transaction_id='paypal-test-12345').status_code==400
    assert not two.get('/api/billing').json['already_active']
    assert admin.get('/api/admin').json['status']['paid_sales_pence']==2500


@pytest.mark.parametrize('link',[
    'http://paypal.me/weddingsbymark','https://paypal.me.evil.invalid/weddingsbymark',
    'https://paypal.me@evil.invalid/weddingsbymark','javascript:alert(1)',
    'https://paypal.me/weddingsbymark/25GBP','https://paypal.me/weddingsbymark?to=other',[],
])
def test_payment_link_rejects_untrusted_or_amount_urls(app,link):
    admin=login(app,'mark@example.com',True)
    assert admin.put('/api/admin/settings',json={'paypal_me_url':link},headers=headers(admin,'/ivoryadmin')).status_code==400


def test_price_and_terms_frozen_for_existing_request(app):
    admin=open_paypal(app);c=login(app);p=start(c)
    assert admin.put('/api/admin/settings',json={'price_pence':3500,'refund_terms':'Updated terms'},headers=headers(admin,'/ivoryadmin')).status_code==200
    again=start(c);assert again['amount_pence']==2500 and again['refund_terms']=='14-day full refund' and again['id']==p['id']
    assert confirm(admin,p).status_code==200


def test_free_access_needs_no_paypal_payment(app):
    admin=open_paypal(app)
    assert admin.post('/api/admin/access/wu1',json={'access':'Complimentary','until':'2031-01-01','reason':'Included with WBM'},headers=headers(admin,'/ivoryadmin')).status_code==200
    c=login(app);assert c.get('/api/billing').json['already_active']
    assert c.post('/api/paypal/start',json={'accept_terms':True},headers=headers(c)).status_code==400


def test_refund_record_retains_receipt_and_requires_access_review(app):
    admin=open_paypal(app);c=login(app);p=start(c);assert confirm(admin,p).status_code==200
    endpoint='/api/admin/paypal/'+p['id']+'/refund-record'
    assert admin.post(endpoint,json={'verified':False},headers=headers(admin,'/ivoryadmin')).status_code==400
    assert admin.post(endpoint,json={'verified':True},headers=headers(admin,'/ivoryadmin')).status_code==200
    assert admin.post(endpoint,json={'verified':True},headers=headers(admin,'/ivoryadmin')).status_code==200
    assert admin.get('/api/admin').json['status']['paid_sales_pence']==0
    db=database(app);assert db.execute('SELECT count(*) n FROM paypal_receipts').fetchone()['n']==1;db.close()
    assert admin.post('/api/admin/access/wu1',json={'access':'Trial','until':'2026-01-01','reason':'Refund and access closure agreed'},headers=headers(admin,'/ivoryadmin')).status_code==200


def test_payment_provider_switch_does_not_create_second_checkout(app,monkeypatch):
    admin=open_paypal(app);c=login(app);p=start(c)
    monkeypatch.setenv('STRIPE_SECRET_KEY','test-key');monkeypatch.setenv('STRIPE_WEBHOOK_SECRET','test-webhook')
    assert admin.put('/api/admin/settings',json={'payment_provider':'stripe'},headers=headers(admin,'/ivoryadmin')).status_code==200
    assert c.post('/api/checkout',json={},headers=headers(c)).status_code==400
    # An existing payment can still be reported and checked after the provider switch.
    assert c.post('/api/paypal/'+p['id']+'/report',json={'transaction_id':'PAYPAL-12345'},headers=headers(c)).status_code==200
    assert c.post('/api/checkout',json={},headers=headers(c)).status_code==400


def test_unpaid_request_can_be_closed_after_admin_check(app):
    admin=open_paypal(app);c=login(app);p=start(c);endpoint='/api/admin/paypal/'+p['id']+'/close'
    assert admin.post(endpoint,json={'verified':False},headers=headers(admin,'/ivoryadmin')).status_code==400
    assert admin.post(endpoint,json={'verified':True},headers=headers(admin,'/ivoryadmin')).status_code==200
    assert admin.post(endpoint,json={'verified':True},headers=headers(admin,'/ivoryadmin')).status_code==200
    assert c.get('/api/billing').json['paypal_request'] is None
    new=start(c);assert new['id']!=p['id'];assert confirm(admin,new).status_code==200
    assert admin.post('/api/admin/paypal/'+new['id']+'/close',json={'verified':True},headers=headers(admin,'/ivoryadmin')).status_code==400

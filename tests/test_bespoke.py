import copy
import io
import json
import zipfile
from pathlib import Path
from PIL import Image
from pypdf import PdfReader
from test_app import app,login,headers,database,prepare
from app.bespoke import starter_pack,validate_pack,layout_for,watermarked_proof
from app.core import empty_state


def get(c,admin=False,oid=None):
    orders=c.get('/api/'+('admin/' if admin else '')+'bespoke').json['orders']
    return next(o for o in orders if o['id']==oid) if oid else orders[0]


def request_order(c,inspiration=True):
    body={'brief':'A lovely original botanical theme in sage and ivory with a modern serif typeface.','colours':'Sage and warm ivory','scope':'yes'}
    if inspiration:
        out=io.BytesIO();Image.new('RGB',(120,160),'green').save(out,'PNG');body['inspiration']=(io.BytesIO(out.getvalue()),'our-inspiration.png')
    r=c.post('/api/bespoke',data=body,headers=headers(c));assert r.status_code==200,r.get_data(as_text=True);return r.json['order']['id']


def action(c,oid,action,admin=False,**values):
    o=get(c,admin,oid);return c.post('/api/'+('admin/' if admin else '')+'bespoke/'+oid+'/'+action,json={'revision':o['revision'],**values},headers=headers(c,'/ivoryadmin' if admin else '/bespoke'))


def quote(c,a,oid):
    assert action(a,oid,'quote',True,amount=19900,note='Complete bespoke set with one combined design revision.').status_code==200
    assert action(c,oid,'accept',confirm=True).status_code==200


def pack_for(a,oid,art=True):
    starter=a.get('/api/admin/bespoke/'+oid+'/starter.zip');assert starter.status_code==200
    with zipfile.ZipFile(io.BytesIO(starter.data)) as z:manifest=json.loads(z.read('manifest.json'))
    for kind,item in manifest['items'].items():
        item['content'].update(names='Emma & Jamie',date='2027-06-19',venue='The Garden House',arrival='Arrive at 12.30pm',menu='STARTER\nTomato soup\n\nMAIN\nRoast chicken\n\nDESSERT\nBerry pavlova')
        if art:item['background']='garden.png'
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('manifest.json',json.dumps(manifest))
        if art:
            pic=io.BytesIO();Image.new('RGB',(1500,2200),'#f8f4e9').save(pic,'PNG');z.writestr('garden.png',pic.getvalue())
    return out.getvalue()


def publish(a,oid,raw=None):
    r=a.post('/api/admin/bespoke/'+oid+'/pack',data={'revision':str(get(a,True,oid)['revision']),'pack':(io.BytesIO(raw or pack_for(a,oid)),'design.zip')},headers=headers(a,'/ivoryadmin'));assert r.status_code==200,r.get_data(as_text=True)


def payment(c,a,oid,provider='paypalme',confirm=True):
    assert action(c,oid,'approve',confirm=True,design_version=get(c,oid=oid)['design_version']).status_code==200
    assert action(a,oid,'payment-request',True,provider=provider).status_code==200
    if confirm:assert action(a,oid,'confirm-payment',True,amount=19900,receipt='PAYPAL-UNIQUE-123',checked=True).status_code==200


def download(c,oid,kind='day',**values):
    return c.post('/api/bespoke/'+oid+'/download/'+kind,json={'design_version':get(c,oid=oid)['design_version'],**values},headers=headers(c,'/bespoke'))


def test_roles_ownership_no_early_downloads_or_raw_artwork(app):
    c=login(app);prepare(c);a=login(app,'mark@example.com',True);oid=request_order(c);other=login(app,'two@example.com')
    assert app.test_client().get('/api/bespoke').status_code==401
    assert c.get('/api/admin/bespoke').status_code==403
    quote(c,a,oid);publish(a,oid);o=get(c,oid=oid);assert 'pack' not in o
    for fmt in ('pdf','png'):assert download(c,oid,format=fmt).status_code==403
    assert other.get('/api/bespoke/'+oid+'/proof/day').status_code==404
    bg=get(a,True,oid)['pack']['items']['day']['background']
    assert c.get('/api/admin/bespoke/'+oid+'/asset/'+bg).status_code==403
    assert c.get('/api/bespoke/'+oid+'/inspiration/'+bg).status_code==404
    assert a.get('/api/admin/bespoke/'+oid+'/asset/'+bg).status_code==200
    assert all('pack' not in v for v in c.get('/api/export').json['bespoke'])


def test_all_nine_proofs_are_small_flat_watermarked_pixels(app):
    c=login(app);prepare(c);a=login(app,'mark@example.com',True);oid=request_order(c);quote(c,a,oid);publish(a,oid)
    for kind in get(c,oid=oid)['items']:
        response=c.get('/api/bespoke/'+oid+'/proof/'+kind+'?clean=1&size=8000');assert response.status_code==200
        image=Image.open(io.BytesIO(response.data));assert max(image.size)==680 and image.mode=='RGB'
    state=empty_state();state['names']=['Emma','Jamie'];item=starter_pack(state)['items']['day'];layout=layout_for(item,'day',state,proof=True)
    from app.stationery import draw_png
    original=Image.open(io.BytesIO(draw_png(layout,680))).convert('RGB');marked=Image.open(io.BytesIO(watermarked_proof(layout)))
    for x,y in [(0,0),(original.width//2,0),(0,original.height//2),(original.width//2,original.height//2)]:
        box=(x,y,min(original.width,x+original.width//2),min(original.height,y+original.height//2))
        assert marked.crop(box).tobytes()!=original.crop(box).tobytes()


def test_one_combined_revision_and_fresh_proof_approval(app):
    c=login(app);prepare(c);a=login(app,'mark@example.com',True);oid=request_order(c);quote(c,a,oid);publish(a,oid)
    assert action(c,oid,'revision',note='Please make the background a lighter sage on the whole set.').status_code==200
    assert action(c,oid,'approve',confirm=True,design_version=1).status_code==400
    publish(a,oid);assert get(c,oid=oid)['revision_used']==1
    assert action(c,oid,'revision',note='Another change please.').status_code==400
    assert action(c,oid,'approve',confirm=True,design_version=1).status_code==400
    assert action(c,oid,'approve',confirm=True,design_version=2).status_code==200


def test_payment_report_cannot_unlock_and_actual_amount_required(app):
    c=login(app);prepare(c);a=login(app,'mark@example.com',True);oid=request_order(c);quote(c,a,oid);publish(a,oid);payment(c,a,oid,confirm=False)
    assert action(c,oid,'report-payment',payer='Emma',reference='Reported not verified').status_code==200
    assert download(c,oid).status_code==403
    assert action(c,oid,'confirm-payment',amount=19900,receipt='forged',checked=True).status_code==404
    assert action(a,oid,'confirm-payment',True,amount=100,receipt='PAYPAL-UNIQUE-123',checked=True).status_code==400
    assert action(a,oid,'confirm-payment',True,amount=19900,receipt='PAYPAL-UNIQUE-123',checked=False).status_code==400
    assert action(a,oid,'confirm-payment',True,amount=19900,receipt='PAYPAL-UNIQUE-123',checked=True).status_code==200
    result=download(c,oid,format='pdf',bleed=3);assert result.status_code==200
    pdf=PdfReader(io.BytesIO(result.data));assert 'Emma & Jamie' in pdf.pages[0].extract_text();assert 'PROOF' not in pdf.pages[0].extract_text()


def test_complimentary_paid_and_expired_accounts_same_service_no_access_change(app):
    c=login(app);prepare(c);a=login(app,'mark@example.com',True);db=database(app);db.execute('UPDATE weddings SET access_kind="Complimentary",access_until="2000-01-01" WHERE id="wu1"');db.commit();db.close()
    before=c.get('/api/state').json;oid=request_order(c);assert get(c,oid=oid)['amount']==19900
    quote(c,a,oid);publish(a,oid);payment(c,a,oid)
    assert c.get('/api/state').json==before and download(c,oid).status_code==200
    db=database(app);assert db.execute('SELECT count(*) FROM purchases').fetchone()[0]==0;db.close()


def test_guest_names_tables_batches_update_without_fee_or_design_revision(app):
    c=login(app);s=prepare(c);a=login(app,'mark@example.com',True);oid=request_order(c);quote(c,a,oid);publish(a,oid);payment(c,a,oid)
    before=get(c,oid=oid);current=c.get('/api/state').json;current['state']['guests'][0].update(name='Corrected name',rsvp='Accepted',table='Oak');current['state']['guests'][1]['rsvp']='Declined';assert c.put('/api/state',json=current,headers=headers(c)).status_code==200
    r=download(c,oid,'place',format='pdf',batch=True);assert r.status_code==200
    pdf=PdfReader(io.BytesIO(r.data));assert 'Corrected name' in pdf.pages[0].extract_text() and 'Robin' not in pdf.pages[0].extract_text()
    assert abs(float(pdf.pages[0].mediabox.width)-210*72/25.4)<.1
    assert download(c,oid,'seating').status_code==200
    after=get(c,oid=oid);assert after['design_version']==before['design_version'] and after['revision_used']==before['revision_used'] and after['amount']==19900


def test_paid_correction_relocks_until_approved_without_second_charge(app):
    c=login(app);prepare(c);a=login(app,'mark@example.com',True);oid=request_order(c);quote(c,a,oid);publish(a,oid);payment(c,a,oid)
    old=get(c,oid=oid);contents={k:v['content'] for k,v in get(a,True,oid)['pack']['items'].items()};contents['day']['venue']='Corrected venue'
    assert action(a,oid,'wording',True,contents=contents).status_code==200
    assert get(c,oid=oid)['paid_at']==old['paid_at'] and download(c,oid).status_code==403
    assert action(c,oid,'approve',confirm=True,design_version=2).status_code==200
    assert download(c,oid).status_code==200
    db=database(app);assert db.execute('SELECT count(*) FROM bespoke_receipts').fetchone()[0]==1;db.close()


def test_reproof_keeps_pending_payment_and_can_record_money_before_approval(app):
    c=login(app);prepare(c);a=login(app,'mark@example.com',True);oid=request_order(c);quote(c,a,oid);publish(a,oid);payment(c,a,oid,confirm=False)
    old=get(a,True,oid)['payment'];publish(a,oid)
    assert get(a,True,oid)['payment']==old
    assert action(a,oid,'confirm-payment',True,amount=19900,receipt='BANK-CORRECTION-123',checked=True).status_code==200
    assert download(c,oid).status_code==403
    assert action(c,oid,'approve',confirm=True,design_version=2).status_code==200
    assert download(c,oid).status_code==200


def test_stale_admin_upload_and_malicious_or_incomplete_zip_rejected(app):
    c=login(app);prepare(c);a=login(app,'mark@example.com',True);oid=request_order(c);quote(c,a,oid);raw=pack_for(a,oid)
    r=a.post('/api/admin/bespoke/'+oid+'/pack',data={'revision':'-1','pack':(io.BytesIO(raw),'bad.zip')},headers=headers(a,'/ivoryadmin'));assert r.status_code==409
    db=database(app);assert db.execute('SELECT count(*) FROM bespoke_assets WHERE kind="background"').fetchone()[0]==0;db.close()
    for filename in ('../evil.png','folder/art.png'):
        out=io.BytesIO()
        with zipfile.ZipFile(out,'w') as z:z.writestr(filename,'bad');z.writestr('manifest.json','{}')
        response=a.post('/api/admin/bespoke/'+oid+'/pack',data={'revision':str(get(a,True,oid)['revision']),'pack':(io.BytesIO(out.getvalue()),'bad.zip')},headers=headers(a,'/ivoryadmin'));assert response.status_code==400
    assert get(c,oid=oid)['design_version']==0


def test_bank_snapshot_leading_zeros_and_duplicate_receipt(app):
    c=login(app);prepare(c);a=login(app,'mark@example.com',True);db=database(app)
    for k,v in {'bank_account_name':'Wedding Design','bank_sort_code':'001122','bank_account_number':'00123456'}.items():db.execute('UPDATE settings SET value=? WHERE key=?',(json.dumps(v),k))
    db.commit();db.close();oid=request_order(c);quote(c,a,oid);publish(a,oid);payment(c,a,oid,'bank',False)
    assert get(c,oid=oid)['payment']['bank']['account_number']=='00123456'
    assert action(a,oid,'withdraw-payment',True,checked=False).status_code==400
    assert action(a,oid,'withdraw-payment',True,checked=True).status_code==200
    assert action(a,oid,'payment-request',True,provider='paypalme').status_code==200
    db=database(app);db.execute('INSERT INTO purchases(id,wedding_id,amount,terms,created) VALUES("older","wu1",19900,"{}",0)');db.execute('INSERT INTO bank_receipts VALUES("older","REUSED-RECEIPT","admin",0)');db.commit();db.close()
    assert action(a,oid,'confirm-payment',True,amount=19900,receipt='reused-receipt',checked=True).status_code==400


def test_bespoke_artwork_backup_restore_boot_and_source_path_rebase(app,tmp_path):
    from app.worker import backup
    from scripts.test_restore import restore
    from app import create_app
    c=login(app);prepare(c);a=login(app,'mark@example.com',True);oid=request_order(c);quote(c,a,oid);publish(a,oid);payment(c,a,oid)
    archive=backup(app.config['DATA_DIR'],app.config['BACKUP_DIR']);folder=tmp_path/'recovery';folder.mkdir();weddings,files=restore(archive,folder);assert files>=2
    recovered=create_app({'DATA_DIR':str(folder),'BACKUP_DIR':str(tmp_path/'other-backups'),'TESTING':True,'SECURE_COOKIES':False,'APP_URL':'http://localhost'})
    # Remove the original asset tree: restored proofs must use restored files only.
    import shutil
    shutil.rmtree(Path(app.config['DATA_DIR'])/'files'/'wu1'/'bespoke')
    owner=login(recovered);assert owner.get('/api/bespoke/'+oid+'/proof/day').status_code==200 and download(owner,oid).status_code==200
    assert 'pack' not in owner.get('/api/export').json['bespoke'][0]


def test_cancellation_problem_and_reviewed_email_no_automatic_unlock(app):
    c=login(app);a=login(app,'mark@example.com',True);oid=request_order(c)
    assert action(c,oid,'problem',note='Could we discuss the theme?').status_code==200
    assert get(c,oid=oid)['revision_used']==0
    assert action(a,oid,'notify',True,message='I have read your brief and will prepare a quote.').status_code==200
    db=database(app);mail=db.execute('SELECT body FROM mail WHERE to_address="one@example.com"').fetchone();assert '/bespoke?order='+oid in mail['body'];db.close()
    assert action(c,oid,'cancel').status_code==200;assert c.get('/api/bespoke/'+oid+'/proof/day').status_code==404
    assert request_order(c)!=oid


def test_unassigned_guests_do_not_block_design_proof_but_block_print(app):
    c=login(app);prepare(c);a=login(app,'mark@example.com',True);current=c.get('/api/state').json;current['state']['guests'][0]['rsvp']='Accepted';assert c.put('/api/state',json=current,headers=headers(c)).status_code==200
    oid=request_order(c);quote(c,a,oid);publish(a,oid);payment(c,a,oid)
    assert c.get('/api/bespoke/'+oid+'/proof/seating').status_code==200
    assert download(c,oid,'seating').status_code==400


def test_optional_empty_browser_file_and_scope_consent(app):
    c=login(app)
    body={'brief':'Modern sage and ivory set with clean type.','scope':'no'}
    assert c.post('/api/bespoke',data=body,headers=headers(c)).status_code==400
    body.update(scope='yes',inspiration=(io.BytesIO(b''),''))
    result=c.post('/api/bespoke',data=body,headers=headers(c));assert result.status_code==200 and result.json['order']['assets']==[]
    assert c.post('/api/bespoke',data={'brief':'Another complete matching design please.','scope':'yes'},headers=headers(c)).status_code==400


def test_invalid_pack_geometry_low_resolution_and_missing_fields(app):
    c=login(app);prepare(c);a=login(app,'mark@example.com',True);oid=request_order(c);quote(c,a,oid)
    with zipfile.ZipFile(io.BytesIO(pack_for(a,oid))) as z:manifest=json.loads(z.read('manifest.json'))
    for mode in ('missing','geometry','tiny'):
        m=copy.deepcopy(manifest)
        if mode=='missing':m['items'].pop('thanks')
        if mode=='geometry':m['items']['day']['fields'][0]['x']=.99
        pic=io.BytesIO();Image.new('RGB',(50,50) if mode=='tiny' else (1500,2200),'white').save(pic,'PNG');out=io.BytesIO()
        with zipfile.ZipFile(out,'w') as z:z.writestr('manifest.json',json.dumps(m));z.writestr('garden.png',pic.getvalue())
        result=a.post('/api/admin/bespoke/'+oid+'/pack',data={'revision':str(get(a,True,oid)['revision']),'pack':(io.BytesIO(out.getvalue()),'bad.zip')},headers=headers(a,'/ivoryadmin'));assert result.status_code==400
    assert get(c,oid=oid)['design_version']==0


def test_admin_cancel_unpaid_and_sales_counts_separate_from_planner(app):
    c=login(app);prepare(c);a=login(app,'mark@example.com',True);oid=request_order(c);quote(c,a,oid)
    assert action(a,oid,'cancel',True,checked=False,note='An agreed cancellation').status_code==400
    assert action(a,oid,'cancel',True,checked=True,note='An agreed cancellation before any money was received.').status_code==200
    oid=request_order(c);quote(c,a,oid);publish(a,oid);payment(c,a,oid)
    status=a.get('/api/admin').json['status'];assert status['bespoke_sales_pence']==19900 and status['paid_sales_pence']==0
    csv=a.get('/api/admin/bespoke/sales.csv');assert csv.status_code==200 and '199.00' in csv.get_data(as_text=True)
    assert c.get('/api/admin/bespoke/sales.csv').status_code==403
    assert action(a,oid,'cancel',True,checked=True,note='Cannot discard a paid sale').status_code==400


def test_paid_printing_roster_after_expiry_is_separate_and_free(app):
    c=login(app);prepare(c);a=login(app,'mark@example.com',True);oid=request_order(c)
    assert action(c,oid,'printing-guests',guests=[]).status_code==403
    quote(c,a,oid);publish(a,oid);payment(c,a,oid)
    db=database(app);db.execute('UPDATE weddings SET access_until="2000-01-01" WHERE id="wu1"');db.commit();db.close()
    original=c.get('/api/state').json;before=get(c,oid=oid)
    assert action(c,oid,'printing-guests',guests=[{'name':'Corrected Guest','table':'Oak'}]).status_code==200
    after=get(c,oid=oid);assert after['separate_roster'] and after['printing_guests']==[{'name':'Corrected Guest','table':'Oak'}]
    assert after['amount']==before['amount'] and after['design_version']==before['design_version'] and after['revision_used']==before['revision_used']
    response=download(c,oid,'place',format='pdf',batch=True);assert response.status_code==200
    assert 'Corrected Guest' in PdfReader(io.BytesIO(response.data)).pages[0].extract_text()
    assert c.get('/api/state').json==original
    assert action(c,oid,'printing-guests',guests=[{'name':'','table':'Oak'}]).status_code==400
    assert action(c,oid,'printing-guests',use_planner=True).status_code==200
    assert not get(c,oid=oid)['separate_roster']


def test_paid_problem_stays_flagged_until_explicit_resolution(app):
    c=login(app);prepare(c);a=login(app,'mark@example.com',True);oid=request_order(c);quote(c,a,oid);publish(a,oid);payment(c,a,oid)
    assert action(c,oid,'problem',note='A spelling error needs correcting please.').status_code==200
    assert get(a,True,oid)['attention']==1
    assert a.get('/api/admin').json['status']['bespoke_open_orders']==1
    assert action(a,oid,'notify',True,message='Thank you, I will check that spelling for you.').status_code==200
    assert get(a,True,oid)['attention']==1
    assert action(a,oid,'resolve',True,note='').status_code==400
    assert action(a,oid,'resolve',True,note='Checked and agreed the correction with the couple.').status_code==200
    assert get(a,True,oid)['attention']==0
    assert a.get('/api/admin').json['status']['bespoke_open_orders']==0

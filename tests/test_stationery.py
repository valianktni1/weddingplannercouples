import io
import json
from datetime import date
from pypdf import PdfReader
from PIL import Image
import pytest
from test_app import app,login,headers,database,prepare
from app.stationery import defaults,source,build_layout,COLLECTIONS,KINDS,SIZES,draw_pdf,draw_png,validate


def context(c):return c.get('/api/stationery').json


def save_design(c,kind='day',changes=None):
    m=context(c);d=m['drafts'][kind];data=d['data'];data.update({'arrival':'Arrive at 12.30pm','names':'Emma & Jamie','date':'2027-06-19','venue':'The Garden House'});data.update(changes or {})
    response=c.put('/api/stationery/'+kind,json={'data':data,'revision':d['revision'],'source':d['source']},headers=headers(c))
    assert response.status_code==200,response.get_data(as_text=True)
    return response.json,data


def export(c,kind,d,**extra):return c.post('/api/stationery/'+kind+'/download',json={'revision':d['revision'],'source':d['source'],'format':'pdf','bleed':0,'batch':False,**extra},headers=headers(c))


def test_stationery_private_and_cookie_cannot_authorize(app):
    c=app.test_client();assert c.get('/stationery').headers['Location']=='/login';assert c.get('/api/stationery').status_code==401
    admin=login(app,'mark@example.com',True);assert admin.get('/api/stationery').status_code==403


def test_drafts_save_conflict_no_wedding_state_changes_and_csrf(app):
    c=login(app);original=c.get('/api/state').json
    m=context(c);d=m['drafts']['day'];d['data']['arrival']='Arrive at noon'
    body={'data':d['data'],'revision':0,'source':d['source']}
    assert c.put('/api/stationery/day',json=body).status_code==403
    assert c.put('/api/stationery/day',json=body,headers=headers(c)).status_code==200
    assert c.put('/api/stationery/day',json=body,headers=headers(c)).status_code==409
    assert c.get('/api/state').json==original
    assert context(login(app,'two@example.com'))['drafts']['day']['revision']==0


def test_real_pdf_png_sizes_fonts_and_bleed(app):
    c=login(app);d,data=save_design(c)
    result=export(c,'day',d,bleed=3);assert result.status_code==200
    pdf=PdfReader(io.BytesIO(result.data));page=pdf.pages[0];assert len(pdf.pages)==1
    assert abs(float(page.mediabox.width)-(127+6)*72/25.4)<.1
    assert abs(float(page.trimbox.width)-127*72/25.4)<.1
    assert 'Emma & Jamie' in page.extract_text() and 'the garden house' in page.extract_text().casefold()
    fonts=page['/Resources']['/Font'].get_object();assert any('/FontFile2' in f.get_object().get('/FontDescriptor',{}) for f in fonts.values())
    result=export(c,'day',d,format='png');assert result.status_code==200
    image=Image.open(io.BytesIO(result.data));assert max(image.size)==1800


def test_invalid_missing_and_overlong_details_never_download_silently(app):
    c=login(app);d,data=save_design(c,changes={'arrival':''})
    assert export(c,'day',d).status_code==400
    data['arrival']='Arrive at noon';data['names']='W'*160
    before=context(c)['drafts']['day'];r=c.put('/api/stationery/day',json={'data':data,'revision':before['revision'],'source':before['source']},headers=headers(c));assert r.status_code==200
    assert export(c,'day',r.json).status_code==400
    bad=dict(data,collection='../../etc');assert c.post('/api/stationery/day/preview',json={'data':bad},headers=headers(c)).status_code==400


def test_guest_derived_batches_privacy_declined_exclusion_and_stale_warning(app):
    c=login(app);s=prepare(c);s['guests'][0]['table']='Rose';s['guests'][0]['rsvp']='Accepted';s['guests'][0]['diet']='PRIVATE ALLERGY';s['guests'][1]['rsvp']='Declined'
    current=c.get('/api/state').json;assert c.put('/api/state',json={'state':s,'revision':current['revision']},headers=headers(c)).status_code==200
    d,data=save_design(c,'place',{'size':'folded','recipient':'Pat'})
    r=export(c,'place',d,batch=True);assert r.status_code==200
    pdf=PdfReader(io.BytesIO(r.data));assert len(pdf.pages)==1;assert 'Pat' in pdf.pages[0].extract_text();assert 'Robin' not in pdf.pages[0].extract_text();assert 'PRIVATE ALLERGY' not in pdf.pages[0].extract_text()
    assert abs(float(pdf.pages[0].mediabox.height)-297*72/25.4)<.1
    s=c.get('/api/state').json;s['state']['guests'][0]['table']='Oak';assert c.put('/api/state',json=s,headers=headers(c)).status_code==200
    meta=context(c)['drafts']['place'];assert meta['review_needed'] and meta['download_outdated'];assert export(c,'place',d).status_code==409


def test_seating_missing_table_blocks_export_and_no_private_notes(app):
    c=login(app);s=prepare(c);s['guests'][0]['rsvp']='Accepted';current=c.get('/api/state').json;assert c.put('/api/state',json={'state':s,'revision':current['revision']},headers=headers(c)).status_code==200
    d,_=save_design(c,'seating');assert export(c,'seating',d).status_code==400


def test_photo_ownership_missing_and_saved_photo_deletion_guard(app):
    c=login(app);other=login(app,'two@example.com');out=io.BytesIO();Image.new('RGB',(200,160),'green').save(out,'JPEG')
    r=c.post('/api/files',data={'kind':'cover','file':(io.BytesIO(out.getvalue()),'our-photo.jpg')},headers=headers(c));assert r.status_code==200;uid=r.json['id']
    d,_=save_design(c,changes={'collection':'photo','palette':'neutral','photo':uid});assert export(c,'day',d).status_code==200
    assert c.delete('/api/files/'+uid,headers=headers(c)).status_code==400
    foreign=context(other)['drafts']['day'];foreign['data'].update(collection='photo',palette='neutral',photo=uid)
    assert other.post('/api/stationery/day/preview',json={'data':foreign['data']},headers=headers(other)).status_code==400


def test_expired_access_can_download_saved_design_not_save_new(app):
    c=login(app);d,_=save_design(c);db=database(app);db.execute('UPDATE weddings SET access_until="2000-01-01" WHERE id="wu1"');db.commit();db.close()
    assert context(c)['readonly'];assert export(c,'day',d).status_code==200
    data=context(c)['drafts']['day']['data'];assert c.put('/api/stationery/day',json={'data':data,'revision':d['revision'],'source':d['source']},headers=headers(c)).status_code==403


def test_all_collection_item_pairs_render_without_missing_sample_details():
    from app.core import empty_state
    s=empty_state();s.update(names=['Emma','Jamie'],date='2027-06-19');s['day']['venue']='The Garden House'
    s['guests']=[{'id':'g','name':'Alex Taylor','table':'Rose','rsvp':'Accepted'}]
    for collection,meta in COLLECTIONS.items():
        for kind in KINDS:
            c=defaults(s,kind);c.update(collection=collection,palette=next(iter(meta['palettes'])),arrival='Arrive at 12.30pm',recipient='Alex Taylor',table_name='Rose',menu='STARTER\nTomato soup\n\nMAIN\nLemon chicken\n\nDESSERT\nBerry pavlova')
            p=build_layout(c,kind,s,Image.new('RGB',(400,300),'#71816c'))
            assert not p.issues,(collection,kind,p.issues)
            assert draw_png(p,240).startswith(b'\x89PNG')
            assert draw_pdf([p]).startswith(b'%PDF')


def test_partner_join_never_discards_existing_stationery(app):
    from test_app import csrf
    from app.core import empty_state
    owner=login(app);other=login(app,'two@example.com');db=database(app);db.execute('UPDATE weddings SET state=? WHERE id="wu2"',(json.dumps(empty_state()),));db.commit();db.close()
    save_design(other,'thanks',{'message':'A private saved design'})
    assert owner.post('/api/partner/invite',json={'email':'two@example.com'},headers=headers(owner)).status_code==200
    db=database(app);link=db.execute('SELECT body FROM mail WHERE to_address="two@example.com"').fetchone()['body'];db.close();path=link.replace('http://localhost','')
    response=other.post(path,data={'csrf':csrf(other,path),'password':'long-test-password'})
    assert response.status_code==400
    assert context(other)['drafts']['thanks']['data']['message']=='A private saved design'


def test_backup_restore_and_private_export_retain_stationery(app,tmp_path):
    from app.worker import backup
    import tarfile
    import sqlite3
    c=login(app);save_design(c,'thanks',{'message':'Thank you from both of us'})
    assert c.get('/api/export').json['stationery'][0]['data']['message']=='Thank you from both of us'
    archive=backup(app.config['DATA_DIR'],app.config['BACKUP_DIR']);restored=tmp_path/'restore';restored.mkdir()
    with tarfile.open(archive) as f:f.extractall(restored,filter='data')
    db=sqlite3.connect(restored/'planner.sqlite3');assert json.loads(db.execute('SELECT data FROM stationery_drafts').fetchone()[0])['message']=='Thank you from both of us';db.close()


def test_collection_previews_are_private_and_do_not_create_drafts(app):
    c=login(app);before=context(c)
    for collection in COLLECTIONS:
        result=c.get('/api/stationery/collections/'+collection+'.png')
        assert result.status_code==200 and result.mimetype=='image/png'
        assert result.headers['Cache-Control']=='no-store'
    assert context(c)==before
    assert app.test_client().get('/api/stationery/collections/botanical.png').status_code==401


def test_evening_invitation_uses_reception_venue_and_tracks_its_changes():
    from app.core import empty_state
    s=empty_state();s['day']['venue']='Ceremony church';s['day']['receptionVenue']='Evening reception barn'
    assert defaults(s,'evening')['venue']=='Evening reception barn'
    assert defaults(s,'day')['venue']=='Ceremony church'
    old=source(s,'evening');s['day']['receptionVenue']='New reception venue';assert source(s,'evening')!=old


def test_revised_compositions_fit_every_offered_paper_size():
    from app.core import empty_state
    from reportlab.pdfbase import pdfmetrics
    s=empty_state();s.update(names=['Emma','Jamie'],date='2027-06-19');s['day']['venue']='The Garden House'
    s['guests']=[{'id':'g','name':'Alex Taylor','table':'Rose','rsvp':'Accepted'}]
    for collection,meta in COLLECTIONS.items():
        for kind,item in KINDS.items():
            for size in item['sizes']:
                d=defaults(s,kind);d.update(collection=collection,palette=next(iter(meta['palettes'])),size=size,arrival='Arrival at 12.30pm · Ceremony at 1pm',recipient='Alex Taylor',table_name='Rose',menu='STARTER\nRoasted tomato soup\n\nMAIN\nLemon & thyme chicken\n\nDESSERT\nSummer berry pavlova')
                p=build_layout(d,kind,s,Image.new('RGB',(400,300),'#71816c'))
                assert not p.issues,(collection,kind,size,p.issues)
                for op in p.ops:
                    if op[0] not in ('text','tracked','richtext'):continue
                    tag,text,x,baseline,points,font,colour,*extra=op
                    width=pdfmetrics.stringWidth(text,font,points)+(max(0,len(text)-1)*extra[0] if tag=='tracked' else 0)
                    assert x>=0 and x+width<=p.w+.1,(collection,kind,size,text)
                    assert baseline-points>=p.offset-.1 and baseline+points*.25<=p.h+.1,(collection,kind,size,text)


def test_editorial_and_meadow_keep_distinct_names_and_accent_in_real_exports():
    from app.core import empty_state
    s=empty_state();s.update(names=['Emma','Jamie'],date='2027-06-19');s['day']['venue']='The Garden House'
    for collection,expected in [('editorial',['Emma','& Jamie']),('meadow',['Emma','&','Jamie'])]:
        d=defaults(s,'day');d.update(collection=collection,palette=next(iter(COLLECTIONS[collection]['palettes'])),arrival='Arrive at noon')
        p=build_layout(d,'day',s);names=[op for op in p.ops if op[0]=='richtext']
        assert [op[1] for op in names]==expected
        assert all(op[4]>=p.w*.13 for op in names)
        assert any('&' in op[1] and op[-1]!=op[-2] for op in names)
        extracted=PdfReader(io.BytesIO(draw_pdf([p]))).pages[0].extract_text()
        assert all(word in extracted for word in ('Emma','Jamie'))
        assert draw_png(p,400).startswith(b'\x89PNG')

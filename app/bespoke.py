"""Private, separately paid bespoke stationery orders and editable designer packs."""
import copy
import csv
import io
import json
import math
import re
import secrets
import shutil
import time
import zipfile
from datetime import date
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageOps, UnidentifiedImageError
from flask import abort, g, jsonify, render_template, request, send_file
from .core import config
from .stationery import ASSETS, KINDS, SIZES, MM, Layout, defaults, draw_pdf, draw_png, placecard_sheets, readable_date, RENDER_LOCK

SCHEMA='''CREATE TABLE IF NOT EXISTS bespoke_orders(
 id TEXT PRIMARY KEY,wedding_id TEXT NOT NULL,requester TEXT NOT NULL,brief TEXT NOT NULL,
 stage TEXT NOT NULL DEFAULT 'Requested',amount INTEGER NOT NULL DEFAULT 19900,quote_note TEXT NOT NULL DEFAULT '',
 quote_version INTEGER NOT NULL DEFAULT 0,accepted_quote INTEGER NOT NULL DEFAULT 0,
 revision_used INTEGER NOT NULL DEFAULT 0,revision_note TEXT NOT NULL DEFAULT '',
 pack TEXT NOT NULL DEFAULT '{}',design_version INTEGER NOT NULL DEFAULT 0,approved_version INTEGER NOT NULL DEFAULT 0,
 payment TEXT NOT NULL DEFAULT '{}',paid_at REAL,attention INTEGER NOT NULL DEFAULT 0,roster TEXT,revision INTEGER NOT NULL DEFAULT 0,created REAL NOT NULL,updated REAL NOT NULL,
 FOREIGN KEY(wedding_id) REFERENCES weddings(id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS bespoke_assets(
 id TEXT PRIMARY KEY,order_id TEXT NOT NULL,kind TEXT NOT NULL,name TEXT NOT NULL,path TEXT NOT NULL,mime TEXT NOT NULL,size INTEGER NOT NULL,
 FOREIGN KEY(order_id) REFERENCES bespoke_orders(id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS bespoke_events(
 id INTEGER PRIMARY KEY AUTOINCREMENT,order_id TEXT NOT NULL,action TEXT NOT NULL,note TEXT NOT NULL,created REAL NOT NULL,
 FOREIGN KEY(order_id) REFERENCES bespoke_orders(id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS bespoke_receipts(
 order_id TEXT PRIMARY KEY,provider TEXT NOT NULL,transaction_id TEXT NOT NULL UNIQUE,amount INTEGER NOT NULL,confirmed_by TEXT NOT NULL,created REAL NOT NULL,
 FOREIGN KEY(order_id) REFERENCES bespoke_orders(id) ON DELETE CASCADE);'''
SCOPE='Complete matching digital set: save-the-date, day invitation, evening invitation, welcome sign, menu, place cards, table names/numbers, seating plan and thank-you card. One design theme and one combined design revision. Printing is arranged by you. Guest names and table assignments remain editable within the approved template. Further design or manual work is quoted separately. Final files unlock after approval and confirmed payment. Planner access is separate.'
CONTENT=('names','date','intro','message','venue','arrival','closing','menu')
FIELDS=set(CONTENT)|{'recipient','table_name','seating','static'}
FONT_NAMES={'serif':'StationerySerif','sans':'StationerySans','italic':'StationeryItalic'}


def starter_pack(state):
    """Portable pack for a designer: custom backgrounds plus live text, never flattened names."""
    items={}
    for kind,meta in KINDS.items():
        content=defaults(state,kind);content={k:content[k] for k in CONTENT}
        if kind in ('day','evening','save_date'):
            blocks=[('intro',.12,.08,.028),('names',.25,.18,.12),('message',.46,.12,.034),('date',.61,.07,.035),('venue',.70,.07,.034),('arrival',.79,.07,.03),('closing',.88,.055,.027)]
        elif kind=='welcome':blocks=[('static',.18,.10,.04),('names',.35,.25,.13),('date',.68,.10,.04)];content['message']='Welcome to our wedding'
        elif kind=='menu':blocks=[('static',.10,.15,.16),('menu',.35,.48,.05)]
        elif kind=='place':blocks=[('recipient',.32,.38,.11)]
        elif kind=='table':blocks=[('static',.18,.12,.06),('table_name',.38,.30,.20)]
        elif kind=='seating':blocks=[('static',.07,.10,.10),('names',.19,.07,.04),('seating',.32,.55,.03)]
        else:blocks=[('static',.18,.17,.15),('message',.41,.20,.045),('names',.70,.12,.07)]
        fields=[]
        for field,y,h,size in blocks:
            block=dict(field=field,x=.12,y=y,w=.76,h=h,size=size,min_size=min(size,.025),font='serif',align='center',colour='#233c32')
            if field=='static':block['text']={'welcome':'Welcome to our wedding','menu':'Menu','table':'Table','seating':'Find your table','thanks':'Thank you'}[kind]
            fields.append(block)
        items[kind]={'size':meta['sizes'][0],'background':'','background_colour':'#fffdf6','art_bleed_mm':0,'content':content,'fields':fields}
    return {'format':'ivory-bespoke-1','items':items}


def clean_image(raw,limit=20000000,thumbnail=False):
    try:
        with Image.open(io.BytesIO(raw)) as image:
            if image.format not in ('JPEG','PNG','WEBP') or image.width*image.height>limit:raise ValueError('Use a JPEG, PNG or WebP image up to 20 megapixels.')
            image.load();image=ImageOps.exif_transpose(image).convert('RGBA')
            if thumbnail:image.thumbnail((2000,2000),Image.Resampling.LANCZOS)
            image.info.clear()
            out=io.BytesIO();image.save(out,'PNG');return out.getvalue(),image.size
    except (OSError,UnidentifiedImageError,Image.DecompressionBombError):raise ValueError('Use a valid JPEG, PNG or WebP image.')


def validate_pack(value,available):
    if not isinstance(value,dict) or value.get('format')!='ivory-bespoke-1' or not isinstance(value.get('items'),dict) or set(value['items'])!=set(KINDS):raise ValueError('The designer pack must include all nine stationery items. Start with the editable starter pack.')
    result={'format':'ivory-bespoke-1','items':{}}
    def colour(v):
        if not isinstance(v,str) or not re.fullmatch(r'#[0-9A-Fa-f]{6}',v):raise ValueError('Use six-digit colour codes in the design pack.')
        return v
    def number(v,low,high):
        if type(v) not in (float,int) or not math.isfinite(v) or not low<=v<=high:raise ValueError('Check the text positions and sizes in the design pack.')
        return v
    for kind,raw in value['items'].items():
        if not isinstance(raw,dict) or raw.get('size') not in KINDS[kind]['sizes']:raise ValueError('Choose a supported paper size for '+KINDS[kind]['name']+'.')
        bg=raw.get('background','')
        if not isinstance(bg,str) or bg and bg not in available:raise ValueError('The pack is missing a background image.')
        bleed=raw.get('art_bleed_mm',0)
        if type(bleed) is not int or bleed not in (0,3):raise ValueError('Artwork bleed must be 0 or 3 mm.')
        content=raw.get('content',{})
        if not isinstance(content,dict):raise ValueError('Check the design wording.')
        content={k:content.get(k,'') for k in CONTENT}
        if any(not isinstance(v,str) or len(v)>2000 or any(ord(ch)<32 and ch not in '\n\t' for ch in v) for v in content.values()):raise ValueError('Keep each design text field to 2,000 characters.')
        content={k:v.strip() for k,v in content.items()}
        if content['date']:
            try:date.fromisoformat(content['date'])
            except ValueError:raise ValueError('Check the invitation date in the pack.')
        fields=raw.get('fields')
        if not isinstance(fields,list) or not 1<=len(fields)<=20:raise ValueError('Each item needs between one and twenty editable text fields.')
        cleaned=[]
        for field in fields:
            if not isinstance(field,dict) or field.get('field') not in FIELDS:raise ValueError('Choose a supported text field.')
            f={'field':field['field'],'x':number(field.get('x'),0,.95),'y':number(field.get('y'),0,.95),'w':number(field.get('w'),.02,1),'h':number(field.get('h'),.02,1),'size':number(field.get('size'),.015,.5),'min_size':number(field.get('min_size',.025),.015,.5),'font':field.get('font','serif'),'align':field.get('align','center'),'colour':colour(field.get('colour','#233c32'))}
            if f['x']+f['w']>1.001 or f['y']+f['h']>1.001 or f['min_size']>f['size'] or f['font'] not in FONT_NAMES or f['align'] not in ('left','center'):raise ValueError('Keep every text box within the paper and check its font settings.')
            if f['field']=='static':
                text=field.get('text','')
                if not isinstance(text,str) or len(text)>500:raise ValueError('Keep fixed headings to 500 characters.')
                f['text']=text
            cleaned.append(f)
        if kind=='place' and not any(f['field']=='recipient' for f in cleaned) or kind=='table' and not any(f['field']=='table_name' for f in cleaned) or kind=='seating' and not any(f['field']=='seating' for f in cleaned):raise ValueError('Place cards, table cards and seating charts must keep their live guest/table fields.')
        result['items'][kind]={'size':raw['size'],'background':bg,'background_colour':colour(raw.get('background_colour','#fffdf6')),'art_bleed_mm':bleed,'content':content,'fields':cleaned}
    return result


def layout_for(item,kind,state,background=None,recipient='',table='',proof=False):
    w,h=(v*MM for v in SIZES[item['size']]);c=defaults(state,kind);c.update(collection='classic',palette='forest',size=item['size']);p=Layout(w,h,c,kind)
    p.bg=item['background_colour'];p.ops=[];p.rect(0,0,w,h,p.bg)
    if background is not None:
        b=item['art_bleed_mm']*MM;p.image(background,-b,p.offset-b,w+2*b,p.area+2*b)
    guests=[g for g in state['guests'] if g['rsvp']=='Accepted']
    chosen_table=table or next((g['table'] for g in guests if g.get('table')),'') or ('Sample table' if proof else '')
    values=dict(item['content'],recipient=recipient or (guests[0]['name'] if guests else 'Sample guest name' if proof else ''),table_name=chosen_table)
    if values.get('date'):values['date']=readable_date(values['date'])
    if not proof and kind in ('day','evening','save_date','welcome') and (not values['names'] or not item['content']['date']):p.issues.append('Ask Mark to complete the names and wedding date in the approved design.')
    required=('venue','arrival') if kind in ('day','evening') else ('menu',) if kind=='menu' else ()
    if not proof and any(not item['content'][key] and any(f['field']==key for f in item['fields']) for key in required):p.issues.append('Ask Mark to complete the venue, arrival or menu wording in this item before printing.')
    if not proof and kind=='place' and not values['recipient']:p.issues.append('Choose or enter a guest name.')
    if not proof and kind=='table' and not values['table_name']:p.issues.append('Choose or enter a table name.')
    for field in item['fields']:
        x=field['x']*w;y=p.offset+field['y']*p.area;width=field['w']*w;height=field['h']*p.area
        if field['field']=='seating':
            groups={}
            for guest in guests:
                if not guest.get('table'):
                    if not proof:p.issues.append('Seat every confirmed guest before downloading the seating plan.')
                    continue
                groups.setdefault(guest['table'],[]).append(guest['name'])
            if proof and len(groups)>8:groups=dict(list(sorted(groups.items()))[:6])
            if not groups and proof:groups={'Sample table':['Sample guest name','Sample guest name']}
            if not groups:p.issues.append('Add confirmed guests and table assignments first.')
            if len(groups)>18:p.issues.append('This chart supports up to 18 tables.')
            columns=2 if len(groups)<=8 else 3;rows=max(1,math.ceil(len(groups)/columns));gap=w*.025;cw=(width-gap*(columns-1))/columns;cell=height/rows
            for i,(name,members) in enumerate(sorted(groups.items())):
                xx=x+(i%columns)*(cw+gap);yy=y+(i//columns)*cell
                p.text(name,xx,yy,cw,cell*.23,w*.04,minsize=w*.025,font=FONT_NAMES[field['font']],colour=field['colour'])
                minimum=18 if item['size']=='A1' else 14 if item['size']=='A2' else 11
                p.text('\n'.join(sorted(members)),xx,yy+cell*.26,cw,cell*.69,max(minimum,min(w*.028,cell*.6/max(1,len(members))/1.2)),minsize=minimum,colour=field['colour'])
        else:
            text=field.get('text','') if field['field']=='static' else values.get(field['field'],'')
            if proof and not text:text={'names':'Your names','date':'Date to confirm','menu':'Menu wording to confirm','venue':'Venue to confirm','arrival':'Arrival details to confirm'}.get(field['field'],'')
            p.text(text,x,y,width,height,max(9,w*field['size']),minsize=max(9,w*field['min_size']),font=FONT_NAMES[field['font']],align=field['align'],colour=field['colour'])
    if p.offset:p.line(0,p.offset,w,p.offset,'#999999',.25)
    return p


def watermarked_proof(layout):
    # Pixels contain the watermark. There is no clean image underneath an HTML overlay.
    base=Image.open(io.BytesIO(draw_png(layout,680))).convert('RGBA');w,h=base.size
    tile=Image.new('RGBA',(max(w,h)*3,max(w,h)*3));d=ImageDraw.Draw(tile);font=ImageFont.truetype(str(ASSETS/'fonts/Outfit-Regular.ttf'),17)
    for y in range(0,tile.height,65):
        for x in range(-50,tile.width,365):d.text((x,y),'IVORY DIGITAL · PROOF · NOT FOR PRINT',font=font,fill=(55,64,60,125),stroke_width=0)
    tile=tile.rotate(28,resample=Image.Resampling.BICUBIC);cx=(tile.width-w)//2;cy=(tile.height-h)//2;base=Image.alpha_composite(base,tile.crop((cx,cy,cx+w,cy+h))).convert('RGB')
    out=io.BytesIO();base.save(out,'JPEG',quality=65);return out.getvalue()


def print_resolution(item,kind,background):
    if background is None:return
    w,h=SIZES[item['size']];h=h/2 if kind=='place' and item['size']=='folded' else h
    bleed=item['art_bleed_mm']*2;dpi=min(background.width/((w+bleed)/25.4),background.height/((h+bleed)/25.4))
    minimum=80 if kind in ('welcome','seating') else 180
    if dpi<minimum:raise ValueError(KINDS[kind]['name']+' artwork is too small for its paper size. Supply at least '+str(math.ceil((w+bleed)/25.4*minimum))+' × '+str(math.ceil((h+bleed)/25.4*minimum))+' pixels. Text must stay in editable fields, not the image.')


def register_bespoke(app,db,auth,wedding,json_body,audit,rate,paypal_link,bank_ready,queue):
    files_root=Path(app.config['DATA_DIR'])/'files'
    def asset_path(asset):
        relative=Path(asset['path']);path=(files_root/relative).resolve()
        if relative.is_absolute() or not path.is_relative_to(files_root.resolve()):raise ValueError('The design file path is invalid. Contact Mark.')
        return path
    def text(body,key):
        value=body.get(key,'')
        if not isinstance(value,str):raise ValueError('Enter plain text for '+key.replace('_',' ')+'.')
        return value.strip()
    def row(oid,owner=False):
        r=db().execute('SELECT * FROM bespoke_orders WHERE id=?',(oid,)).fetchone()
        if not r or owner and r['wedding_id']!=wedding()['id']:abort(404)
        return r
    def state(r):
        result=json.loads(db().execute('SELECT state FROM weddings WHERE id=?',(r['wedding_id'],)).fetchone()['state'])
        if r['roster'] is not None:result['guests']=json.loads(r['roster'])
        return result
    def event(r,action,note=''):
        db().execute('INSERT INTO bespoke_events(order_id,action,note,created) VALUES(?,?,?,?)',(r['id'],action,note,time.time()));audit('Bespoke: '+action,r['wedding_id'])
    def notify_admin(r,action):
        for account in db().execute('SELECT email FROM users WHERE role="admin" AND verified=1'):
            queue(account['email'],'Bespoke stationery · '+action,'A bespoke order has an update: '+action+'.\n\nReview the private workspace:\n'+app.config['APP_URL']+'/ivoryadmin/bespoke?order='+r['id'],dedupe='bespoke-action-'+r['id']+'-'+str(r['revision'])+'-'+action+'-'+account['email'])
    def change(r,body,**updates):
        if type(body.get('revision')) is not int or body['revision']!=r['revision']:abort(409,description='This order changed. Your typed text is still here; refresh the order before saving.')
        updates.update(updated=time.time(),revision=r['revision']+1)
        cur=db().execute('UPDATE bespoke_orders SET '+','.join(k+'=?' for k in updates)+' WHERE id=? AND revision=?',list(updates.values())+[r['id'],r['revision']])
        if not cur.rowcount:abort(409,description='This order changed while saving. Refresh it and try again.')
    def public(r,admin=False):
        value={k:r[k] for k in ('id','wedding_id','stage','amount','quote_note','quote_version','accepted_quote','revision_used','revision_note','design_version','approved_version','paid_at','attention','revision','created','updated')}
        value.update(brief=json.loads(r['brief']),scope=SCOPE,items={k:v['name'] for k,v in KINDS.items()},unlocked=bool(r['paid_at'] and r['approved_version']==r['design_version'] and r['design_version']),assets=[dict(a) for a in db().execute('SELECT id,name,kind FROM bespoke_assets WHERE order_id=? AND kind="inspiration"',(r['id'],))],events=[dict(e) for e in db().execute('SELECT action,note,created FROM bespoke_events WHERE order_id=? ORDER BY id',(r['id'],))])
        if r['paid_at']:value.update(separate_roster=r['roster'] is not None,printing_guests=[{'name':v['name'],'table':v.get('table','')} for v in state(r)['guests'] if v['rsvp']=='Accepted'])
        payment=json.loads(r['payment'])
        if admin or r['approved_version']==r['design_version'] and r['design_version']:value['payment']=payment
        if admin:
            account=db().execute('SELECT email FROM users WHERE id=?',(r['requester'],)).fetchone()
            value.update(pack=json.loads(r['pack']),couple_names=' & '.join(state(r)['names']),email=account['email'] if account else 'Account removed')
        return value
    def image(r,aid):
        cache=getattr(g,'bespoke_images',{});g.bespoke_images=cache
        if aid in cache:return cache[aid]
        asset=db().execute('SELECT * FROM bespoke_assets WHERE id=? AND order_id=? AND kind="background"',(aid,r['id'])).fetchone()
        if not asset:raise ValueError('A design background is missing. Contact Mark.')
        with Image.open(asset_path(asset)) as img:cache[aid]=img.convert('RGBA')
        return cache[aid]
    def render(r,kind,proof=False,recipient='',table=''):
        if kind not in KINDS:abort(404)
        pack=json.loads(r['pack']);item=pack.get('items',{}).get(kind)
        if not item:raise ValueError('Your proof set is not ready yet.')
        return layout_for(item,kind,state(r),image(r,item['background']) if item['background'] else None,recipient,table,proof)
    @app.get('/bespoke')
    @auth()
    def bespoke_page():wedding();return render_template('bespoke.html',admin=False)
    @app.get('/ivoryadmin/bespoke')
    @auth(admin=True)
    def bespoke_admin():return render_template('bespoke_admin.html')
    @app.get('/api/bespoke')
    @auth()
    def bespoke_list():
        w=wedding();return jsonify(orders=[public(r) for r in db().execute('SELECT * FROM bespoke_orders WHERE wedding_id=? ORDER BY created DESC',(w['id'],))],price=19900,scope=SCOPE)
    @app.get('/api/admin/bespoke')
    @auth(admin=True)
    def bespoke_all():return jsonify(orders=[public(r,True) for r in db().execute("SELECT * FROM bespoke_orders ORDER BY attention DESC,(stage IN ('Paid','Cancelled')),updated DESC LIMIT 200")])
    @app.get('/api/admin/bespoke/<oid>')
    @auth(admin=True)
    def bespoke_one(oid):return jsonify(order=public(row(oid),True))
    @app.get('/api/admin/bespoke/sales.csv')
    @auth(admin=True)
    def bespoke_sales():
        out=io.StringIO();writer=csv.writer(out);writer.writerow(['Order','Couple','Gross GBP','Method','Checked receipt','Confirmed at (UTC)','Design stage'])
        from datetime import datetime,timezone
        def safe(value):
            text=str(value)
            return "'"+text if text.lstrip().startswith(('=','+','-','@')) or text.startswith(('\t','\r')) else text
        for receipt in db().execute('SELECT r.*,o.stage,o.wedding_id FROM bespoke_receipts r JOIN bespoke_orders o ON o.id=r.order_id ORDER BY r.created DESC'):
            names=json.loads(db().execute('SELECT state FROM weddings WHERE id=?',(receipt['wedding_id'],)).fetchone()['state'])['names']
            writer.writerow([safe(v) for v in (receipt['order_id'],' & '.join(names),format(receipt['amount']/100,'.2f'),receipt['provider'],receipt['transaction_id'],datetime.fromtimestamp(receipt['created'],timezone.utc).isoformat(),receipt['stage'])])
        return send_file(io.BytesIO(('\ufeff'+out.getvalue()).encode()),mimetype='text/csv',as_attachment=True,download_name='bespoke-confirmed-sales.csv')
    @app.post('/api/bespoke')
    @auth()
    def bespoke_create():
        w=wedding();rate('bespoke-request-'+w['id'],10,86400,per_ip=False)
        brief=request.form.get('brief','').strip();colours=request.form.get('colours','').strip();files=[f for f in request.files.getlist('inspiration') if f.filename]
        if not 20<=len(brief)<=10000 or len(colours)>500 or request.form.get('scope')!='yes':raise ValueError('Describe your full set and confirm the digital-design service details.')
        if len(files)>5:raise ValueError('Upload up to five inspiration images.')
        if db().execute('SELECT 1 FROM bespoke_orders WHERE wedding_id=? AND stage!="Cancelled"',(w['id'],)).fetchone():raise ValueError('You already have a bespoke request. Open it below to continue.')
        if db().execute('SELECT count(*) FROM bespoke_orders WHERE wedding_id=?',(w['id'],)).fetchone()[0]>=10:raise ValueError('Contact Mark before opening another request.')
        oid=secrets.token_hex(16);folder=Path(app.config['DATA_DIR'])/'files'/w['id']/'bespoke'/oid;folder.mkdir(parents=True)
        prepared=[];total=0
        try:
            for f in files:
                raw=f.read(5*1024*1024+1);total+=len(raw)
                if len(raw)>5*1024*1024 or total>10*1024*1024:raise ValueError('Use images up to 5 MB each and 10 MB in total.')
                cleaned,_=clean_image(raw,thumbnail=True)
                if sum(a[-1] for a in prepared)+len(cleaned)>40*1024*1024:raise ValueError('Use smaller inspiration images.')
                aid=secrets.token_hex(16);path=folder/(aid+'.png');path.write_bytes(cleaned);prepared.append((aid,oid,'inspiration',Path(f.filename or 'Inspiration').name[:150],str(path.relative_to(files_root)),'image/png',len(cleaned)))
            db().execute('BEGIN IMMEDIATE')
            if db().execute('SELECT 1 FROM bespoke_orders WHERE wedding_id=? AND stage!="Cancelled"',(w['id'],)).fetchone() or db().execute('SELECT count(*) FROM bespoke_orders WHERE wedding_id=?',(w['id'],)).fetchone()[0]>=10:raise ValueError('Your request list changed. Open your current workspace before starting another request.')
            stored=db().execute('SELECT coalesce(sum(a.size),0) FROM bespoke_assets a JOIN bespoke_orders o ON o.id=a.order_id WHERE o.wedding_id=?',(w['id'],)).fetchone()[0]
            if stored+sum(a[-1] for a in prepared)>250*1024*1024:raise ValueError('Contact Mark before uploading more artwork.')
            now=time.time();db().execute('INSERT INTO bespoke_orders(id,wedding_id,requester,brief,created,updated) VALUES(?,?,?,?,?,?)',(oid,w['id'],g.user['id'],json.dumps({'description':brief,'colours':colours}),now,now))
            db().executemany('INSERT INTO bespoke_assets VALUES(?,?,?,?,?,?,?)',prepared);event(row(oid),'Request received')
            for account in db().execute('SELECT email FROM users WHERE role="admin" AND verified=1'):
                queue(account['email'],'New bespoke stationery request','A couple has requested a bespoke stationery set. Review the private brief in your admin workspace:\n\n'+app.config['APP_URL']+'/ivoryadmin/bespoke?order='+oid,dedupe='bespoke-new-'+oid+'-'+account['email'])
            return jsonify(order=public(row(oid)))
        except Exception:shutil.rmtree(folder,ignore_errors=True);raise
    @app.get('/api/bespoke/<oid>/inspiration/<aid>')
    @auth()
    def bespoke_inspiration(oid,aid):
        r=row(oid,True);asset=db().execute('SELECT * FROM bespoke_assets WHERE id=? AND order_id=? AND kind="inspiration"',(aid,oid)).fetchone()
        if not asset:abort(404)
        return send_file(asset_path(asset),mimetype='image/png')
    @app.get('/api/admin/bespoke/<oid>/asset/<aid>')
    @auth(admin=True)
    def bespoke_admin_asset(oid,aid):
        row(oid);asset=db().execute('SELECT * FROM bespoke_assets WHERE id=? AND order_id=?',(aid,oid)).fetchone()
        if not asset:abort(404)
        return send_file(asset_path(asset),mimetype=asset['mime'])
    @app.post('/api/admin/bespoke/<oid>/quote')
    @auth(admin=True)
    def bespoke_quote(oid):
        body=json_body();db().execute('BEGIN IMMEDIATE');r=row(oid);amount=body.get('amount');note=text(body,'note')
        if r['accepted_quote'] or r['stage'] not in ('Requested','Quoted'):raise ValueError('An accepted quote cannot be changed. Agree additional work separately.')
        if type(amount) is not int or not 100<=amount<=1000000 or not 5<=len(note)<=2000:raise ValueError('Enter the total GBP price and a brief description of the agreed design.')
        change(r,body,amount=amount,quote_note=note,quote_version=r['quote_version']+1,stage='Quoted');event(r,'Quote ready',note);return jsonify(ok=True)
    @app.post('/api/bespoke/<oid>/<action>')
    @auth()
    def bespoke_action(oid,action):
        rate('bespoke-action-'+g.user['id'],100,3600,per_ip=False);body=json_body();db().execute('BEGIN IMMEDIATE');r=row(oid,True)
        if action=='accept':
            if r['stage']!='Quoted' or body.get('confirm') is not True:raise ValueError('Check and accept the quote before design work starts.')
            change(r,body,accepted_quote=r['quote_version'],stage='Designing');event(r,'Quote accepted',SCOPE)
        elif action=='revision':
            note=text(body,'note')
            if r['stage']!='Proof ready' or r['revision_used'] or not 5<=len(note)<=5000:raise ValueError('Submit one combined list of design changes while your proof is ready. Further work needs a separate quote.')
            change(r,body,revision_used=1,revision_note=note,stage='Revision requested',approved_version=0);event(r,'Included revision requested',note)
        elif action=='approve':
            if r['stage']!='Proof ready' or body.get('confirm') is not True or body.get('design_version')!=r['design_version']:raise ValueError('Check the latest full proof set and confirm your approval.')
            change(r,body,approved_version=r['design_version'],stage='Paid' if r['paid_at'] else 'Payment requested' if r['payment']!='{}' else 'Approved');event(r,'Proof set approved')
        elif action=='report-payment':
            if not r['payment'] or r['payment']=='{}' or r['paid_at'] or r['approved_version']!=r['design_version']:raise ValueError('Open your approved payment request first.')
            payer=text(body,'payer');reference=text(body,'reference')
            if not 2<=len(payer)<=160 or not 2<=len(reference)<=160:raise ValueError('Enter the payer name and transaction or payment reference.')
            payment=json.loads(r['payment']);payment.update(reported_payer=payer,reported_reference=reference,reported_at=time.time());change(r,body,payment=json.dumps(payment));event(r,'Payment reported','Awaiting manual verification; downloads remain locked.')
        elif action=='problem':
            note=text(body,'note')
            if not 5<=len(note)<=3000:raise ValueError('Describe the problem so Mark can help.')
            change(r,body,attention=1);event(r,'Problem reported',note)
        elif action=='cancel':
            if r['stage'] not in ('Requested','Quoted'):raise ValueError('Contact Mark about cancelling work already in progress.')
            change(r,body,stage='Cancelled',attention=0);event(r,'Request cancelled')
        elif action=='printing-guests':
            if not r['paid_at']:abort(403,description='Printing-list updates are available after payment is verified.')
            if body.get('use_planner') is True:change(r,body,roster=None)
            else:
                guests=body.get('guests')
                if not isinstance(guests,list) or len(guests)>250:raise ValueError('Use up to 250 names in the separate printing list.')
                clean=[]
                for i,guest in enumerate(guests):
                    if not isinstance(guest,dict) or not isinstance(guest.get('name'),str) or not 1<=len(guest['name'].strip())<=160 or not isinstance(guest.get('table',''),str) or len(guest.get('table',''))>100:raise ValueError('Check the names and tables in your printing list.')
                    clean.append({'id':'print'+str(i),'name':guest['name'].strip(),'table':guest.get('table','').strip(),'rsvp':'Accepted'})
                change(r,body,roster=json.dumps(clean))
            event(r,'Printing guest list updated','No design revision or extra charge.')
        else:abort(404)
        if action!='printing-guests':notify_admin(r,{'accept':'Quote accepted','revision':'Combined revision requested','approve':'Proof approved','report-payment':'Payment reported','problem':'Problem reported','cancel':'Request cancelled'}[action])
        return jsonify(ok=True)
    @app.get('/api/admin/bespoke/<oid>/starter.zip')
    @auth(admin=True)
    def bespoke_starter(oid):
        r=row(oid);out=io.BytesIO()
        pack=json.loads(r['pack']) if r['design_version'] else starter_pack(state(r))
        with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
            used={}
            for item in pack['items'].values():
                if not item['background']:continue
                asset=db().execute('SELECT * FROM bespoke_assets WHERE id=? AND order_id=?',(item['background'],oid)).fetchone()
                name=asset['id']+'.png';item['background']=name
                if name not in used:z.write(asset_path(asset),name);used[name]=True
            z.writestr('manifest.json',json.dumps(pack,indent=2,ensure_ascii=False));z.writestr('DESIGN-GUIDE.txt',DESIGN_GUIDE)
        return send_file(io.BytesIO(out.getvalue()),mimetype='application/zip',as_attachment=True,download_name='bespoke-editable-starter.zip')
    @app.post('/api/admin/bespoke/<oid>/pack')
    @auth(admin=True)
    def bespoke_pack(oid):
        r=row(oid);rate('bespoke-pack',30,3600);upload=request.files.get('pack')
        if not r['accepted_quote'] or r['stage']=='Cancelled' or not upload:raise ValueError('The couple must accept the quote before a designer pack is uploaded.')
        raw=upload.read(64*1024*1024+1)
        if len(raw)>64*1024*1024:raise ValueError('Keep the designer ZIP below 64 MB.')
        body={'revision':int(request.form.get('revision','-1'))};folder=Path(app.config['DATA_DIR'])/'files'/r['wedding_id']/'bespoke'/oid/secrets.token_hex(10);folder.mkdir(parents=True);prepared=[];mapping={}
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                files=archive.infolist()
                if not 1<=len(files)<=30 or sum(f.file_size for f in files)>80*1024*1024 or len({f.filename for f in files})!=len(files) or any(f.flag_bits&1 for f in files):raise ValueError('Use an unencrypted designer pack with at most 30 unique files.')
                if any(not re.fullmatch(r'[A-Za-z0-9_.-]{1,120}',f.filename) or f.is_dir() or (f.external_attr>>16)&0o170000==0o120000 for f in files):raise ValueError('Designer packs must contain ordinary files without folders or links.')
                for f in files:
                    if f.filename in ('manifest.json','DESIGN-GUIDE.txt'):continue
                    if not f.filename.lower().endswith(('.png','.jpg','.jpeg','.webp')) or f.file_size>15*1024*1024:raise ValueError('Use PNG, JPEG or WebP artwork, up to 15 MB per file.')
                    cleaned,_=clean_image(archive.read(f))
                    if sum(a[-1] for a in prepared)+len(cleaned)>150*1024*1024:raise ValueError('Use a smaller artwork set (up to 150 MB after decoding).')
                    aid=secrets.token_hex(16);path=folder/(aid+'.png');path.write_bytes(cleaned);mapping[f.filename]=aid;prepared.append((aid,oid,'background',f.filename,str(path.relative_to(files_root)),'image/png',len(cleaned)))
                if archive.getinfo('manifest.json').file_size>100000:raise ValueError('The design manifest is too large.')
                pack=validate_pack(json.loads(archive.read('manifest.json')),mapping)
            for item in pack['items'].values():
                if item['background']:item['background']=mapping[item['background']]
            db().execute('BEGIN IMMEDIATE');r=row(oid)
            if not r['accepted_quote'] or r['stage']=='Cancelled':raise ValueError('This request is no longer open for design work.')
            stored=db().execute('SELECT coalesce(sum(a.size),0) FROM bespoke_assets a JOIN bespoke_orders o ON o.id=a.order_id WHERE o.wedding_id=?',(r['wedding_id'],)).fetchone()[0]
            if stored+sum(a[-1] for a in prepared)>250*1024*1024:raise ValueError('The bespoke artwork storage limit is reached. Contact Mark before adding more versions.')
            db().executemany('INSERT INTO bespoke_assets VALUES(?,?,?,?,?,?,?)',prepared)
            # Validate fitting and glyphs before publishing all nine proofs.
            for kind,item in pack['items'].items():
                art=image(r,item['background']) if item['background'] else None;print_resolution(item,kind,art)
                p=layout_for(item,kind,state(r),art,proof=True)
                if p.issues:raise ValueError(KINDS[kind]['name']+': '+' '.join(dict.fromkeys(p.issues)))
            change(r,body,pack=json.dumps(pack),design_version=r['design_version']+1,approved_version=0,stage='Proof ready');event(r,'New proof set ready',request.form.get('note','Updated matching design set')[:2000]);return jsonify(ok=True)
        except (zipfile.BadZipFile,KeyError,UnicodeDecodeError,json.JSONDecodeError):shutil.rmtree(folder,ignore_errors=True);raise ValueError('Use the editable starter ZIP format with manifest.json and image artwork.')
        except Exception:shutil.rmtree(folder,ignore_errors=True);raise
    def proof(oid,kind,admin=False):
        r=row(oid,not admin)
        if not r['design_version'] or r['stage']=='Cancelled':abort(404)
        rate('bespoke-proof-'+r['wedding_id'],300,900,per_ip=False)
        if not RENDER_LOCK.acquire(timeout=5):abort(429,description='Another proof is being prepared. Try again in a moment.')
        try:raw=watermarked_proof(render(r,kind,True))
        finally:RENDER_LOCK.release()
        return send_file(io.BytesIO(raw),mimetype='image/jpeg')
    @app.get('/api/bespoke/<oid>/proof/<kind>')
    @auth()
    def bespoke_proof(oid,kind):return proof(oid,kind)
    @app.get('/api/admin/bespoke/<oid>/proof/<kind>')
    @auth(admin=True)
    def bespoke_admin_proof(oid,kind):return proof(oid,kind,True)
    @app.post('/api/admin/bespoke/<oid>/payment-request')
    @auth(admin=True)
    def bespoke_payment(oid):
        body=json_body();db().execute('BEGIN IMMEDIATE');r=row(oid);provider=body.get('provider');settings=config(db())
        if r['stage'] not in ('Approved','Payment requested') or r['approved_version']!=r['design_version'] or r['paid_at']:raise ValueError('Wait for approval of the latest proof set before requesting payment.')
        if provider not in ('bank','paypalme'):raise ValueError('Choose bank transfer or PayPal.Me.')
        payment={'provider':provider,'amount':r['amount'],'reference':'BS-'+oid[:12].upper(),'quote_version':r['accepted_quote'],'requested_at':time.time()}
        if provider=='paypalme':payment['url']=paypal_link(settings['paypal_me_url'])+'/'+format(r['amount']/100,'.2f')+'GBP'
        else:
            if not bank_ready(settings):raise ValueError('Save your bank details in Pricing & trials first.')
            payment['bank']={k:settings['bank_'+k] for k in ('name','account_name','sort_code','account_number','instructions')}
        if r['stage']=='Payment requested':raise ValueError('A payment request already exists. Check it before preparing another.')
        change(r,body,payment=json.dumps(payment),stage='Payment requested');event(r,'Payment requested','Bank transfer' if provider=='bank' else 'PayPal.Me');return jsonify(ok=True)
    @app.post('/api/admin/bespoke/<oid>/wording')
    @auth(admin=True)
    def bespoke_wording(oid):
        body=json_body();db().execute('BEGIN IMMEDIATE');r=row(oid);contents=body.get('contents')
        if not r['design_version'] or r['stage']=='Cancelled' or not isinstance(contents,dict) or set(contents)!=set(KINDS):raise ValueError('Open the full designer set before editing its wording.')
        pack=json.loads(r['pack'])
        for kind in KINDS:pack['items'][kind]['content']=contents[kind]
        available={a['id'] for a in db().execute('SELECT id FROM bespoke_assets WHERE order_id=? AND kind="background"',(oid,))};pack=validate_pack(pack,available)
        for kind,item in pack['items'].items():
            art=image(r,item['background']) if item['background'] else None;print_resolution(item,kind,art)
            p=layout_for(item,kind,state(r),art,proof=True)
            if p.issues:raise ValueError(KINDS[kind]['name']+': '+' '.join(dict.fromkeys(p.issues)))
        change(r,body,pack=json.dumps(pack),design_version=r['design_version']+1,approved_version=0,stage='Proof ready');event(r,'Updated wording proof ready','Please check the latest set. Existing payment, if any, remains recorded.');return jsonify(ok=True)
    @app.post('/api/admin/bespoke/<oid>/confirm-payment')
    @auth(admin=True)
    def bespoke_confirm_payment(oid):
        body=json_body();db().execute('BEGIN IMMEDIATE');r=row(oid);payment=json.loads(r['payment']);receipt=body.get('receipt','')
        if not isinstance(receipt,str):raise ValueError('Enter the checked transaction reference.')
        receipt=receipt.strip().upper()
        if not payment or r['paid_at'] or body.get('checked') is not True:raise ValueError('Check the real completed payment for this order before confirming it.')
        if type(body.get('amount')) is not int or body['amount']!=r['amount'] or not 3<=len(receipt)<=160:raise ValueError('The received amount must match the quote. Enter a unique transaction or bank receipt reference.')
        if any(db().execute('SELECT 1 FROM '+table+' WHERE transaction_id=?',(receipt,)).fetchone() for table in ('bespoke_receipts','paypal_receipts','bank_receipts')):raise ValueError('That payment reference is already recorded. Check the actual payment.')
        approved=r['approved_version']==r['design_version'] and r['design_version']>0
        db().execute('INSERT INTO bespoke_receipts VALUES(?,?,?,?,?,?)',(oid,payment['provider'],receipt,r['amount'],g.user['id'],time.time()));change(r,body,paid_at=time.time(),stage='Paid' if approved else r['stage']);event(r,'Payment verified; files unlocked' if approved else 'Payment verified; awaiting final approval');return jsonify(ok=True)
    @app.post('/api/admin/bespoke/<oid>/withdraw-payment')
    @auth(admin=True)
    def bespoke_withdraw(oid):
        body=json_body();db().execute('BEGIN IMMEDIATE');r=row(oid)
        if r['stage']!='Payment requested' or r['paid_at'] or body.get('checked') is not True:raise ValueError('Check that no money has been received before withdrawing instructions.')
        change(r,body,payment='{}',stage='Approved');event(r,'Payment instructions withdrawn','Mark checked that no payment had been received.');return jsonify(ok=True)
    @app.post('/api/admin/bespoke/<oid>/notify')
    @auth(admin=True)
    def bespoke_notify(oid):
        rate('bespoke-email',30,3600);body=json_body();db().execute('BEGIN IMMEDIATE');r=row(oid);message=body.get('message','')
        if not isinstance(message,str) or not 5<=len(message.strip())<=2000:raise ValueError('Enter the update you want the couple to receive.')
        account=db().execute('SELECT email,verified FROM users WHERE id=?',(r['requester'],)).fetchone()
        if not account or not account['verified']:raise ValueError('The requester needs a verified email before an update can be sent.')
        url=app.config['APP_URL']+'/bespoke?order='+oid
        change(r,body);queue(account['email'],'Your bespoke stationery update',message.strip()+'\n\nOpen your private stationery workspace:\n'+url,dedupe='bespoke-update-'+oid+'-'+str(r['revision']),html_body=render_template('bespoke_update_email.html',message=message.strip(),url=url));event(r,'Update email queued',message.strip());return jsonify(ok=True)
    @app.post('/api/admin/bespoke/<oid>/cancel')
    @auth(admin=True)
    def bespoke_admin_cancel(oid):
        body=json_body();db().execute('BEGIN IMMEDIATE');r=row(oid);note=text(body,'note')
        if r['paid_at'] or r['stage']=='Cancelled' or body.get('checked') is not True or not 5<=len(note)<=2000:raise ValueError('Confirm no money was received and explain the cancellation. Paid orders must be resolved separately.')
        change(r,body,stage='Cancelled',approved_version=0,attention=0);event(r,'Request cancelled by Mark',note);return jsonify(ok=True)
    @app.post('/api/admin/bespoke/<oid>/resolve')
    @auth(admin=True)
    def bespoke_resolve(oid):
        body=json_body();db().execute('BEGIN IMMEDIATE');r=row(oid);note=text(body,'note')
        if not r['attention'] or not 5<=len(note)<=2000:raise ValueError('Describe how the reported problem was resolved.')
        change(r,body,attention=0);event(r,'Problem resolved',note);return jsonify(ok=True)
    @app.post('/api/bespoke/<oid>/download/<kind>')
    @auth()
    def bespoke_download(oid,kind):
        body=json_body();r=row(oid,True)
        if not r['paid_at'] or r['approved_version']!=r['design_version'] or not r['design_version']:abort(403,description='Print-ready files unlock after approval and Mark confirms payment.')
        if body.get('design_version')!=r['design_version']:abort(409,description='The design changed. Review the latest proof before downloading.')
        fmt=body.get('format','pdf');batch=body.get('batch',False);bleed=body.get('bleed',0);recipient=body.get('recipient','');table=body.get('table','')
        if fmt not in ('pdf','png') or type(batch) is not bool or type(bleed) is not int or bleed not in (0,3) or not isinstance(recipient,str) or len(recipient)>160 or not isinstance(table,str) or len(table)>100:raise ValueError('Check the file type, name and table choice.')
        if batch and (kind not in ('place','table') or fmt!='pdf'):raise ValueError('Batch downloads are PDFs for place cards or tables.')
        recipient=recipient.strip();table=table.strip()
        rate('bespoke-export-'+r['wedding_id'],60,900,per_ip=False)
        if not RENDER_LOCK.acquire(timeout=10):abort(429,description='Another file is being prepared. Try again shortly.')
        try:
            r=row(oid,True)
            if not r['paid_at'] or r['approved_version']!=r['design_version'] or body.get('design_version')!=r['design_version']:abort(409,description='The approved design changed while preparing your file. Review the latest proof first.')
            if batch:
                guests=[g for g in state(r)['guests'] if g['rsvp']=='Accepted']
                if not guests or len(guests)>250:raise ValueError('Choose between one and 250 confirmed guests.')
                if kind=='place':layouts=[render(r,kind,recipient=g['name']) for g in guests]
                else:layouts=[render(r,kind,table=t) for t in sorted({g['table'] for g in guests if g.get('table')})]
                if not layouts:raise ValueError('Assign your confirmed guests to tables first.')
            else:layouts=[render(r,kind,recipient=recipient,table=table)]
            issues=[v for p in layouts for v in p.issues]
            if issues:raise ValueError(' '.join(dict.fromkeys(issues)))
            if batch and kind=='place':layouts=placecard_sheets(layouts);bleed=0
            raw=draw_pdf(layouts,bleed) if fmt=='pdf' else draw_png(layouts[0],1800)
        finally:RENDER_LOCK.release()
        return send_file(io.BytesIO(raw),mimetype='application/pdf' if fmt=='pdf' else 'image/png',as_attachment=True,download_name='our-bespoke-'+kind+'.'+fmt)


DESIGN_GUIDE='''IVORY DIGITAL — EDITABLE BESPOKE DESIGN PACK\n\nThis is a designer/admin format. Couples only see watermarked proofs and their paid output. No live AI account or API is used.\n\nEdit manifest.json, keeping format ivory-bespoke-1 and all nine items. Add original PNG/JPEG/WebP artwork files alongside it in the ZIP, with ordinary filenames and no folders. Set each item background to the matching filename, or blank for a typographic design. Never flatten guest names or table assignments into backgrounds.\n\nEach item has size (one of its existing planner sizes), background_colour, art_bleed_mm (0 or 3), approved content and fields. Text boxes x,y,w,h are fractions 0..1 of the printed face. For folded place cards, the printed face is the lower half. Font size and minimum size are fractions of page width; the renderer enforces a 9pt floor and blocks overflow. Font: serif, italic, sans. Alignment: center or left. Colours: six-digit hex. Fields can be names,date,intro,message,venue,arrival,closing,menu,recipient,table_name,seating or static. Static headings use text. Names/date/menu/wording come from approved content. Recipient, tables and seating use current confirmed guests. Place cards, table cards and charts must retain their corresponding live field.\n\nArt with art_bleed_mm=3 must cover the full paper plus 3mm on each edge. Use suitable image resolution: aim for 300dpi on small pieces and at least 150dpi on large signs. Text remains embedded vector text. Check every item, font character and actual-size test print; do not rely only on low-resolution proofs. Physical printing, paper, colour conversion and finishing are arranged by the couple/printer.\n\nUpload a revised pack for the one combined change request. Publishing any new pack invalidates approval and locks clean downloads until the couple approves it, including corrections after payment. Payment remains recorded; correcting your own error does not charge the couple again. Old pack assets remain private for recovery.\n'''

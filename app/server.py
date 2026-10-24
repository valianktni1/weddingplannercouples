import base64
import io
import json
import os
import re
import secrets
import shutil
import time
import urllib.parse
import urllib.request
import hashlib
import hmac
from datetime import date, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from pathlib import Path
from functools import wraps
from flask import Flask, g, request, render_template, redirect, jsonify, make_response, send_file, abort
from werkzeug.security import generate_password_hash, check_password_hash
from PIL import Image, ImageOps, UnidentifiedImageError
from .core import connect, initialise, config, digest, cipher, valid_totp, empty_state, validate_state, access_end, date_valid

from .mail_service import smtp_configuration, smtp_ready, send_email, delivery_error
from .invitation_mail import invitation_email
from .day_hub import register_hub,journey as hub_journey

VERSION='1.7.1'
def create_app(test_config=None):
    app=Flask(__name__)
    app.config.update(DATA_DIR=os.environ.get('DATA_DIR','/data'), BACKUP_DIR=os.environ.get('BACKUP_DIR','/backups'),
        APP_URL=os.environ.get('APP_URL','https://planner.ivorydigital.uk').rstrip('/'),
        SECURE_COOKIES=os.environ.get('SECURE_COOKIES','1')=='1', TESTING=False,
        MAX_CONTENT_LENGTH=12*1024*1024, MAX_FORM_PARTS=30, MAX_FORM_MEMORY_SIZE=200000)
    if test_config: app.config.update(test_config)
    secret=initialise(app.config['DATA_DIR'])
    app.config['SECRET_VALUE']=secret
    app.config['DATABASE']=str(Path(app.config['DATA_DIR'])/'planner.sqlite3')

    def db():
        if 'db' not in g: g.db=connect(app.config['DATABASE'])
        return g.db
    def audit(action,wid=None):
        db().execute('INSERT INTO audit(actor,action,wedding_id,created) VALUES(?,?,?,?)',
            (g.user['id'] if getattr(g,'user',None) else 'system',action,wid,time.time()))
    def token(kind,user=None,wedding=None,email=None,payload=None,hours=24):
        value=secrets.token_urlsafe(32)
        db().execute('INSERT INTO tokens VALUES(?,?,?,?,?,?,?,0)',(digest(value),kind,user,wedding,email,json.dumps(payload or {}),time.time()+hours*3600))
        return value
    def token_row(value,kind):
        return db().execute('SELECT * FROM tokens WHERE hash=? AND kind=? AND used=0 AND expires>?',(digest(value),kind,time.time())).fetchone()
    def queue(to,subject,body,dedupe=None,html_body=''):
        mid=secrets.token_hex(12)
        db().execute('INSERT OR IGNORE INTO mail(id,to_address,subject,body,dedupe,created,html_body) VALUES(?,?,?,?,?,?,?)',
            (mid,to,subject,body,dedupe,time.time(),html_body))
        return mid
    def rotated(user=None,pending=None):
        db().execute('DELETE FROM sessions WHERE id=?',(g.session['id'],))
        g.session=new_session(user,pending)
        if user:
            account=db().execute('SELECT role FROM users WHERE id=?',(user,)).fetchone()
            if account and account['role']=='couple': g.returning_couple=True
    def new_session(user=None,pending=None):
        raw=secrets.token_urlsafe(32);sid=digest(raw)
        row={'id':sid,'user_id':user,'csrf':secrets.token_urlsafe(32),'expires':time.time()+86400*7,'pending':pending,'setup_secret':None}
        db().execute('INSERT INTO sessions VALUES(?,?,?,?,?,?)',tuple(row.values()))
        g.cookie=raw
        return row
    def pending_admin():
        uid=g.session.get('pending')
        return db().execute('SELECT * FROM users WHERE id=? AND role="admin"',(uid,)).fetchone() if uid else None
    def admin_next(u): return '/ivoryadmin/two-step' if u['totp'] else '/ivoryadmin/two-step/setup'
    def rate(name,limit=20,seconds=900,per_ip=True):
        # The untrusted X-Forwarded-For header is deliberately not used.
        key=digest(name+'|'+((request.remote_addr or 'unknown') if per_ip else 'account'))
        now=time.time();row=db().execute('SELECT * FROM rate_limits WHERE key=?',(key,)).fetchone()
        if not row or row['reset']<now:
            db().execute('INSERT OR REPLACE INTO rate_limits VALUES(?,?,?)',(key,1,now+seconds))
        elif row['count']>=limit:
            abort(429,description='Too many attempts. Please try again later.')
        else: db().execute('UPDATE rate_limits SET count=count+1 WHERE key=?',(key,))
        # Rate limits survive a rejected form; business edits must not.
        db().commit()
    def auth(admin=False,verified=True):
        def decorator(fn):
            @wraps(fn)
            def wrapped(*args,**kwargs):
                if not g.user:
                    if admin and pending_admin() and not request.path.startswith('/api/'): return redirect(admin_next(pending_admin()))
                    if request.path.startswith('/api/'): abort(401)
                    return redirect('/ivoryadmin/login' if admin else '/login')
                if admin and g.user['role']!='admin': abort(403)
                if not admin and g.user['role']!='couple': abort(403)
                if verified and not g.user['verified']: abort(403,description='Please verify your email first.')
                if admin and not g.user['totp']: return redirect('/ivoryadmin/two-step/setup')
                return fn(*args,**kwargs)
            return wrapped
        return decorator
    def wedding(write=False):
        row=db().execute('SELECT w.* FROM weddings w JOIN members m ON m.wedding_id=w.id WHERE m.user_id=?',(g.user['id'],)).fetchone()
        if not row: abort(404)
        if row['suspended']: abort(403,description='This account is suspended. Contact Ivory Digital.')
        if write and row['access_until']<date.today().isoformat():
            abort(403,description='Planning access has ended. You can still view and export your plan. Contact Ivory Digital for an extension.')
        return row
    def json_body():
        if not request.is_json: abort(415)
        value=request.get_json()
        if not isinstance(value,dict): abort(400)
        return value
    def valid_email(email):
        return isinstance(email,str) and len(email)<=160 and re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email)
    def password_ok(p): return isinstance(p,str) and 12<=len(p)<=200
    def update_state(w,s,expected):
        validate_state(s)
        cur=db().execute('UPDATE weddings SET state=?,revision=revision+1 WHERE id=? AND revision=?',
            (json.dumps(s),w['id'],expected))
        if not cur.rowcount: abort(409,description='Your partner or an RSVP changed the plan. Reload before saving so nobody’s changes are lost.')
        hub_notify(w['id'])

    @app.before_request
    def before():
        g.cookie=None;g.user=None
        if request.path.startswith('/static/') or request.path=='/healthz': return
        if request.path.startswith('/api/integrations/control-centre/'):
            from .control_centre import authorise
            authorise()
            return
        if request.path.startswith('/api/integrations/wbm/'):
            # A narrowly scoped machine credential, never an admin session.
            request.max_content_length=128000 if request.path.startswith('/api/integrations/wbm/timings/') else 4096
            settings=config(db());provided=request.headers.get('Authorization','')
            stored=settings.get('wbm_booking_key_hash','')
            if not stored or not provided.startswith('Bearer ') or len(provided)>200 or not hmac.compare_digest(digest(provided[7:]),stored):
                abort(401,description='Booking connection not authorised.')
            if not settings.get('wbm_booking_enabled',False): abort(409,description='Booking connection is paused in planner admin.')
            rate('wbm-connection',3000,3600,per_ip=False)
            return
        raw=request.cookies.get('ivory_session','');row=db().execute('SELECT * FROM sessions WHERE id=? AND expires>?',(digest(raw),time.time())).fetchone() if raw else None
        g.session=dict(row) if row else new_session()
        if g.session['user_id']:
            g.user=db().execute('SELECT * FROM users WHERE id=?',(g.session['user_id'],)).fetchone()
            if g.user and g.user['role']=='couple' and request.method=='GET' and request.path in ['/app','/api/state','/hub','/api/hub','/stationery','/api/stationery']:
                db().execute('INSERT INTO hub_meta(wedding_id,last_active) SELECT wedding_id,? FROM members WHERE user_id=? ON CONFLICT(wedding_id) DO UPDATE SET last_active=excluded.last_active WHERE coalesce(last_active,0)<?',(time.time(),g.user['id'],time.time()-300))
        db().commit()
        if request.method in ('POST','PUT','PATCH','DELETE') and request.path!='/api/stripe/webhook':
            value=request.headers.get('X-CSRF-Token') or request.form.get('csrf','')
            if not hmac.compare_digest(str(value),g.session['csrf']): abort(403,description='This form expired. Reload and try again.')
    @app.after_request
    def after(resp):
        resp.headers['X-Content-Type-Options']='nosniff'
        resp.headers['X-Frame-Options']='DENY'
        resp.headers['Referrer-Policy']='no-referrer'
        resp.headers['Permissions-Policy']='camera=(), microphone=(), geolocation=()'
        resp.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
        resp.headers['X-Robots-Tag']='noindex, nofollow'
        if not request.path.startswith('/static/'): resp.headers['Cache-Control']='no-store'
        if getattr(g,'cookie',None):
            resp.set_cookie('ivory_session',g.cookie,max_age=86400*7,httponly=True,secure=app.config['SECURE_COOKIES'],samesite='Lax')
        # This preference contains no identity and grants no authentication/access.
        returning=getattr(g,'returning_couple',False) or (getattr(g,'user',None) is not None and g.user['role']=='couple')
        if resp.status_code<400 and returning and request.cookies.get('ivory_returning_couple')!='1':
            resp.set_cookie('ivory_returning_couple','1',max_age=86400*365,httponly=True,secure=app.config['SECURE_COOKIES'],samesite='Lax')
        if 'db' in g:
            if resp.status_code>=400: g.db.rollback()
            else:
                g.db.commit()
                for callback in getattr(g,'on_commit',[]): callback()
        return resp
    @app.teardown_appcontext
    def close(exc):
        if 'db' in g:
            if exc: g.db.rollback()
            g.db.close()
    @app.context_processor
    def ctx(): return {'csrf':getattr(g,'session',{}).get('csrf',''),'version':VERSION,'user':getattr(g,'user',None)}
    @app.errorhandler(ValueError)
    def invalid(e):
        if request.path.startswith('/api/'): return jsonify(error=str(e)),400
        return render_template('message.html',title='Check those details',message=str(e)),400
    @app.errorhandler(400)
    @app.errorhandler(401)
    @app.errorhandler(403)
    @app.errorhandler(404)
    @app.errorhandler(409)
    @app.errorhandler(413)
    @app.errorhandler(415)
    @app.errorhandler(429)
    def problem(e):
        if request.path.startswith('/api/'): return jsonify(error=e.description),e.code
        return render_template('message.html',title='Please check',message=e.description),e.code

    @app.get('/healthz')
    def health():
        d=connect(app.config['DATABASE']);d.execute('SELECT 1').fetchone();d.close()
        return jsonify(status='ok',version=VERSION)
    @app.get('/api/session')
    def session_status():
        return jsonify(authenticated=bool(g.user),role=g.user['role'] if g.user else None,csrf=g.session['csrf'])
    @app.get('/robots.txt')
    def robots(): return 'User-agent: *\nDisallow: /\n',200,{'Content-Type':'text/plain'}
    @app.get('/')
    def index():
        if request.args.get('welcome')!='1':
            if g.user and g.user['role']=='couple': return redirect('/app')
            if not g.user and request.cookies.get('ivory_returning_couple')=='1': return redirect('/login')
        return render_template('landing.html',settings=config(db()))
    @app.route('/signup',methods=['GET','POST'])
    def signup():
        settings=config(db())
        if not settings['signups_enabled']:
            return render_template('message.html',title='Opening soon',message='Ivory Digital is setting up the planner. Please come back soon.'),403
        if request.method=='GET': return render_template('auth.html',mode='signup',title='Create your planner')
        rate('signup',100,3600)
        email=request.form.get('email','').lower().strip();password=request.form.get('password','')
        if not valid_email(email) or not password_ok(password): raise ValueError('Use a valid email and a password of at least 12 characters.')
        if db().execute('SELECT 1 FROM users WHERE email=?',(email,)).fetchone():
            return render_template('message.html',title='Check your email',message='If you already have an account, use sign-in or account recovery.')
        uid=secrets.token_hex(16);wid=secrets.token_hex(16)
        db().execute('INSERT INTO users(id,email,password,created) VALUES(?,?,?,?)',(uid,email,generate_password_hash(password),time.time()))
        end=(date.today()+timedelta(days=settings['trial_days'])).isoformat()
        s=empty_state();s['email']=email
        db().execute('INSERT INTO weddings(id,state,access_until,created) VALUES(?,?,?,?)',(wid,json.dumps(s),end,time.time()))
        db().execute('INSERT INTO members VALUES(?,?)',(wid,uid))
        value=token('verify',user=uid)
        queue(email,'Verify your wedding planner email',app.config['APP_URL']+'/verify/'+value)
        audit('Couple account registered',wid)
        return render_template('message.html',title='Check your email',message='Open the verification link to finish setting up your account. If it does not arrive, ask Ivory Digital to check email delivery.')
    @app.route('/verify/<value>',methods=['GET','POST'])
    def verify(value):
        row=token_row(value,'verify')
        if not row: abort(400,description='This verification link has expired or was used.')
        if request.method=='GET': return render_template('confirm.html',title='Verify your email',message='Confirm to activate your account.',button='Verify email')
        consumed=db().execute('UPDATE tokens SET used=1 WHERE hash=? AND used=0 AND expires>?',(row['hash'],time.time()))
        if not consumed.rowcount: abort(400,description='This verification link was already used.')
        was_verified=db().execute('SELECT verified FROM users WHERE id=?',(row['user_id'],)).fetchone()['verified']
        db().execute('UPDATE users SET verified=1,verified_at=? WHERE id=?',(time.time(),row['user_id']))
        if not was_verified:
            until=(date.today()+timedelta(days=config(db())['trial_days'])).isoformat()
            db().execute('UPDATE weddings SET access_until=max(access_until,?) WHERE access_kind="Trial" AND id IN (SELECT wedding_id FROM members WHERE user_id=?)',(until,row['user_id']))
        return redirect('/login')
    @app.route('/verification',methods=['GET','POST'])
    def resend_verification():
        if request.method=='GET': return render_template('auth.html',mode='recover',title='Request a new verification link')
        rate('verify-resend',6,3600);email=request.form.get('email','').lower().strip()
        user=db().execute('SELECT * FROM users WHERE email=? AND role="couple" AND verified=0',(email,)).fetchone()
        if user:
            db().execute('UPDATE tokens SET used=1 WHERE user_id=? AND kind="verify"',(user['id'],))
            value=token('verify',user=user['id']);queue(email,'Verify your wedding planner email',app.config['APP_URL']+'/verify/'+value)
        return render_template('message.html',title='Check your inbox',message='If this email has an unverified account, a new verification link will arrive shortly.')
    @app.route('/login',methods=['GET','POST'])
    @app.route('/ivoryadmin/login',methods=['GET','POST'])
    def login():
        admin=request.path.startswith('/ivoryadmin')
        if request.method=='GET':
            if not admin and g.user and g.user['role']=='couple': return redirect('/app')
            if admin and g.user and g.user['role']=='admin': return redirect('/ivoryadmin')
            if admin and pending_admin(): return redirect(admin_next(pending_admin()))
            return render_template('auth.html',mode='login',title='Ivory admin sign-in' if admin else 'Welcome back')
        email=request.form.get('email','').lower().strip();rate('login-ip',300);rate('login-'+email,8,per_ip=False)
        user=db().execute('SELECT * FROM users WHERE email=?',(email,)).fetchone()
        if not user or not check_password_hash(user['password'],request.form.get('password','')) or (user['role']=='admin')!=admin:
            return render_template('auth.html',mode='login',title='Sign in',error='Email or password not recognised.'),401
        if not user['verified']: raise ValueError('Verify your email first.')
        if admin:
            rotated(pending=user['id'])
            return redirect('/ivoryadmin/two-step' if user['totp'] else '/ivoryadmin/two-step/setup')
        rotated(user=user['id']);return redirect('/app')
    @app.post('/logout')
    def logout():
        admin=bool(g.user and g.user['role']=='admin')
        rotated()
        return redirect('/ivoryadmin/login' if admin else '/login')
    @app.route('/recover',methods=['GET','POST'])
    def recover():
        if request.method=='GET': return render_template('auth.html',mode='recover',title='Get back into your account')
        rate('recover',8,3600);email=request.form.get('email','').lower().strip();u=db().execute('SELECT * FROM users WHERE email=?',(email,)).fetchone()
        if u:
            value=token('reset',user=u['id'],hours=1)
            queue(email,'Reset your planner password',app.config['APP_URL']+'/reset/'+value)
        return render_template('message.html',title='Check your inbox',message='If this email has an account, a recovery link will arrive shortly.')
    @app.route('/reset/<value>',methods=['GET','POST'])
    def reset(value):
        row=token_row(value,'reset')
        if not row: abort(400,description='This recovery link expired or was used.')
        if request.method=='GET': return render_template('auth.html',mode='reset',title='Choose a new password')
        password=request.form.get('password','')
        if not password_ok(password): raise ValueError('Use at least 12 characters.')
        consumed=db().execute('UPDATE tokens SET used=1 WHERE hash=? AND used=0 AND expires>?',(row['hash'],time.time()))
        if not consumed.rowcount: abort(400,description='This recovery link was already used.')
        db().execute('UPDATE users SET password=? WHERE id=?',(generate_password_hash(password),row['user_id']))
        db().execute('DELETE FROM sessions WHERE user_id=? OR pending=?',(row['user_id'],row['user_id']))
        db().execute('UPDATE tokens SET used=1 WHERE user_id=? AND kind="reset"',(row['user_id'],))
        return redirect('/login')

    @app.route('/ivoryadmin/two-step/setup',methods=['GET','POST'])
    def setup_totp():
        uid=g.session['pending'] or (g.user['id'] if g.user and g.user['role']=='admin' else None)
        u=db().execute('SELECT * FROM users WHERE id=? AND role="admin"',(uid,)).fetchone() if uid else None
        if not u: return redirect('/ivoryadmin/login')
        if u['totp']: return redirect('/ivoryadmin/two-step')
        setup=g.session['setup_secret']
        if not setup:
            setup=cipher(secret).encrypt(base64.b32encode(secrets.token_bytes(20)).decode().rstrip('=').encode()).decode()
            db().execute('UPDATE sessions SET setup_secret=? WHERE id=?',(setup,g.session['id']))
        plain=cipher(secret).decrypt(setup.encode()).decode()
        if request.method=='POST':
            rate('totp-setup',8)
            db().execute('BEGIN IMMEDIATE')
            if db().execute('SELECT totp FROM users WHERE id=?',(uid,)).fetchone()['totp']:
                abort(403,description='Two-step verification was already enrolled.')
            counter=valid_totp(plain,request.form.get('code',''))
            if counter is None:
                db().rollback()
                return redirect('/ivoryadmin/two-step/setup?retry=1')
            codes=[secrets.token_hex(5) for _ in range(8)]
            db().execute('UPDATE users SET totp=?,recovery=?,totp_last=? WHERE id=?',(setup,json.dumps([digest(c) for c in codes]),counter,uid))
            rotated(user=uid);audit('Admin two-step sign-in enrolled')
            return render_template('recovery_codes.html',codes=codes)
        uri='otpauth://totp/'+urllib.parse.quote('Ivory Planner:'+u['email'])+'?'+urllib.parse.urlencode({'secret':plain,'issuer':'Ivory Planner'})
        import qrcode
        import qrcode.image.svg
        image=qrcode.make(uri,image_factory=qrcode.image.svg.SvgPathImage);buf=io.BytesIO();image.save(buf)
        return render_template('two_step.html',setup=True,secret=plain,qr=base64.b64encode(buf.getvalue()).decode())
    @app.route('/ivoryadmin/two-step',methods=['GET','POST'])
    def two_step():
        u=db().execute('SELECT * FROM users WHERE id=? AND role="admin"',(g.session['pending'],)).fetchone()
        if not u or not u['totp']:
            return redirect('/ivoryadmin' if g.user and g.user['role']=='admin' else '/ivoryadmin/login')
        if request.method=='GET': return render_template('two_step.html',setup=False)
        rate('totp-'+u['id'],8,per_ip=False);code=request.form.get('code','').strip()
        db().execute('BEGIN IMMEDIATE')
        u=db().execute('SELECT * FROM users WHERE id=?',(u['id'],)).fetchone()
        plain=cipher(secret).decrypt(u['totp'].encode()).decode();counter=valid_totp(plain,code,u['totp_last']);recovery=json.loads(u['recovery'])
        if counter is not None:
            db().execute('UPDATE users SET totp_last=? WHERE id=?',(counter,u['id']))
        elif digest(code) in recovery:
            recovery.remove(digest(code));db().execute('UPDATE users SET recovery=? WHERE id=?',(json.dumps(recovery),u['id']))
        else: return render_template('two_step.html',setup=False,error='That code did not match or has expired. Enter the latest code from your authenticator, or an unused recovery code.'),400
        rotated(user=u['id']);return redirect('/ivoryadmin')
    @app.get('/app')
    @auth()
    def planner():
        w=wedding();return render_template('planner.html',readonly=w['access_until']<date.today().isoformat(),access_until=w['access_until'])
    @app.get('/api/state')
    @auth()
    def get_state():
        w=wedding();return jsonify(state=json.loads(w['state']),revision=w['revision'],account_email=g.user['email'],access_until=w['access_until'],readonly=w['access_until']<date.today().isoformat())
    @app.put('/api/state')
    @auth()
    def put_state():
        w=wedding(True);body=json_body();s=body.get('state')
        if not isinstance(s,dict): raise ValueError('Missing wedding data.')
        s['email']=g.user['email'];s['demo']=False
        s['invite']=json.loads(w['state'])['invite']
        update_state(w,s,body.get('revision'))
        return jsonify(revision=w['revision']+1,state=s)
    @app.get('/api/export')
    @auth()
    def export():
        w=wedding();return jsonify(state=json.loads(w['state']),website=json.loads(w['site']),stationery=[dict(r)|{'data':json.loads(r['data'])} for r in db().execute('SELECT kind,revision,data,updated,exported_at FROM stationery_drafts WHERE wedding_id=?',(w['id'],))],exported=time.time())
    @app.get('/website')
    @auth()
    def website_editor(): wedding();return render_template('website_editor.html')
    @app.get('/files')
    @auth()
    def files_page(): wedding();return render_template('files.html')
    @app.get('/api/billing')
    @auth()
    def billing_info():
        w=wedding();settings=config(db())
        pending=paypal_pending(w['id'])
        return jsonify(provider=settings['payment_provider'],payment_request=paypal_details(pending) if pending else None,paypal_request=paypal_details(pending) if pending and json.loads(pending['terms']).get('provider')=='paypalme' else None,enabled=settings['checkout_enabled'],already_active=w['access_kind'] in ['Paid','Complimentary','Manual extension'] and w['access_until']>=date.today().isoformat(),price_pence=settings['price_pence'],
            access_until=access_end(settings,json.loads(w['state'])['date']),refund_terms=settings['refund_terms'],terms_text=settings['terms_text'])
    @app.post('/api/partner/invite')
    @auth()
    def invite_partner():
        w=wedding(True);rate('partner',10,3600);email=json_body().get('email','').lower().strip()
        if not valid_email(email) or email==g.user['email']: raise ValueError('Enter your partner’s separate email address.')
        if db().execute('SELECT count(*) n FROM members WHERE wedding_id=?',(w['id'],)).fetchone()['n']>=2: raise ValueError('Both partner places are already in use.')
        db().execute('UPDATE tokens SET used=1 WHERE wedding_id=? AND kind="partner"',(w['id'],))
        value=token('partner',wedding=w['id'],email=email,hours=72)
        queue(email,'Join your shared wedding planner',app.config['APP_URL']+'/join/'+value)
        s=json.loads(w['state']);s['invite']={'email':email,'status':'Invitation queued'};update_state(w,s,w['revision']);audit('Partner invited',w['id'])
        return jsonify(ok=True)
    @app.post('/api/partner/cancel')
    @auth()
    def cancel_partner():
        w=wedding(True)
        if db().execute('SELECT count(*) n FROM members WHERE wedding_id=?',(w['id'],)).fetchone()['n']>=2:
            raise ValueError('Your partner has already joined. Cancelling a pending invitation cannot remove their account.')
        db().execute('UPDATE tokens SET used=1 WHERE wedding_id=? AND kind="partner"',(w['id'],))
        s=json.loads(w['state']);s['invite']={'email':'','status':'Not invited'};update_state(w,s,w['revision']);return jsonify(ok=True)
    @app.route('/join/<value>',methods=['GET','POST'])
    def join(value):
        t=token_row(value,'partner')
        if not t: abort(400,description='This invitation has expired or been cancelled.')
        if request.method=='GET': return render_template('auth.html',mode='join',title='Join your wedding planner',email=t['email'])
        rate('join',30);db().execute('BEGIN IMMEDIATE');t=token_row(value,'partner')
        if not t: abort(400,description='This invitation has expired or been cancelled.')
        target=db().execute('SELECT * FROM weddings WHERE id=?',(t['wedding_id'],)).fetchone()
        if not target or target['suspended']: abort(403)
        if db().execute('SELECT count(*) n FROM members WHERE wedding_id=?',(t['wedding_id'],)).fetchone()['n']>=2: raise ValueError('Both partner places are already used.')
        u=db().execute('SELECT * FROM users WHERE email=?',(t['email'],)).fetchone()
        password=request.form.get('password','')
        if u:
            if not check_password_hash(u['password'],password) or u['role']!='couple': abort(403)
            previous=db().execute('SELECT w.* FROM weddings w JOIN members m ON m.wedding_id=w.id WHERE m.user_id=?',(u['id'],)).fetchone()
            if previous:
                old=json.loads(previous['state'])
                if previous['id']==target['id'] or old['ready'] or any(old['names']) or old['date'] or old['budget'] is not None or old['priorities'] or old['day']!=empty_state()['day'] or any(old[key] for key in ['suppliers','payments','tasks','guests','groups','events','notes']) or previous['slug'] or any(db().execute('SELECT 1 FROM '+table+' WHERE wedding_id=?',(previous['id'],)).fetchone() for table in ['hub_events','hub_jobs','hub_tables','hub_shares','stationery_drafts']) or db().execute('SELECT 1 FROM uploads WHERE wedding_id=?',(previous['id'],)).fetchone() or db().execute('SELECT 1 FROM purchases WHERE wedding_id=?',(previous['id'],)).fetchone():
                    raise ValueError('This account already has wedding plans. No plans were removed. Sign in to review them and contact Ivory Digital before combining accounts.')
                db().execute('DELETE FROM members WHERE user_id=?',(u['id'],))
                if not db().execute('SELECT 1 FROM members WHERE wedding_id=?',(previous['id'],)).fetchone():
                    db().execute('DELETE FROM weddings WHERE id=?',(previous['id'],))
            uid=u['id'];db().execute('UPDATE users SET verified=1,verified_at=coalesce(verified_at,?) WHERE id=?',(time.time(),uid))
        else:
            if not password_ok(password): raise ValueError('Use a password of at least 12 characters.')
            uid=secrets.token_hex(16);db().execute('INSERT INTO users(id,email,password,verified,created) VALUES(?,?,?,1,?)',(uid,t['email'],generate_password_hash(password),time.time()))
        db().execute('BEGIN IMMEDIATE') if not db().in_transaction else None
        if db().execute('SELECT count(*) n FROM members WHERE wedding_id=?',(t['wedding_id'],)).fetchone()['n']>=2: raise ValueError('Both partner places are already used.')
        db().execute('INSERT INTO members VALUES(?,?)',(t['wedding_id'],uid));db().execute('UPDATE tokens SET used=1 WHERE hash=?',(t['hash'],))
        w=db().execute('SELECT * FROM weddings WHERE id=?',(t['wedding_id'],)).fetchone();s=json.loads(w['state']);s['invite']={'email':t['email'],'status':'Accepted'}
        update_state(w,s,w['revision']);rotated(user=uid);audit('Partner joined',w['id']);return redirect('/app')

    @app.get('/api/website')
    @auth()
    def get_website():
        w=wedding();site=json.loads(w['site']);return jsonify(site=site,slug=w['slug'],has_code=bool(w['code_hash']),revision=w['site_revision'])
    @app.put('/api/website')
    @auth()
    def put_website():
        w=wedding(True);body=json_body();site=body.get('site',{});slug=body.get('slug','').strip().lower()
        if type(body.get('revision')) is not int or body['revision']!=w['site_revision']:
            abort(409,description='Your partner changed the website. Your typed changes are still here; copy them before reloading.')
        if not isinstance(site,dict) or len(json.dumps(site))>30000: raise ValueError('Website details are too large.')
        allowed={'published','title','intro','date','ceremony','reception','travel','accommodation','dress','faq','gift_url','cover','theme'}
        site={k:site.get(k,'') for k in allowed}
        if type(site['published']) is not bool: raise ValueError('Choose draft or published.')
        if site['published'] and not str(site.get('title','')).strip(): raise ValueError('Add your names or a page title before publishing.')
        if not re.fullmatch(r'[a-z0-9][a-z0-9-]{2,70}',slug): raise ValueError('Use a unique address with 3–71 lowercase letters, numbers or hyphens.')
        if not date_valid(site['date']): raise ValueError('Check the website date.')
        for k,v in site.items():
            if k!='published' and (not isinstance(v,str) or len(v)>5000): raise ValueError('Website text is too long.')
        if site['gift_url'] and not site['gift_url'].startswith('https://'): raise ValueError('Gift links must start with https://.')
        if site['cover'] and not db().execute('SELECT 1 FROM uploads WHERE id=? AND wedding_id=? AND kind="cover"',(site['cover'],w['id'])).fetchone(): raise ValueError('Select a cover uploaded to your wedding.')
        if site['theme'] not in ['garden','classic','modern']: site['theme']='garden'
        existing=db().execute('SELECT wedding_id FROM website_slugs WHERE slug=? AND wedding_id!=?',(slug,w['id'])).fetchone()
        if existing: raise ValueError('That wedding address is already taken.')
        code=body.get('access_code')
        if code is not None and (not isinstance(code,str) or len(code)>100): raise ValueError('Invalid website access code.')
        code_hash=w['code_hash'] if code is None else generate_password_hash(code) if code else None
        if code is not None:
            db().execute('UPDATE tokens SET used=1 WHERE wedding_id=? AND kind="site-access"',(w['id'],))
        cur=db().execute('UPDATE weddings SET site=?,slug=?,code_hash=?,site_revision=site_revision+1 WHERE id=? AND site_revision=?',(json.dumps(site),slug,code_hash,w['id'],body['revision']))
        if not cur.rowcount: abort(409,description='The website changed while saving. Reload before overwriting anything.')
        db().execute('INSERT OR IGNORE INTO website_slugs VALUES(?,?)',(slug,w['id']))
        audit('Wedding website saved'+(' and published' if site['published'] else ' as draft'),w['id']);return jsonify(ok=True,url=app.config['APP_URL']+'/weddings/'+slug,revision=w['site_revision']+1,has_code=bool(code_hash))
    def public_wedding(slug):
        w=db().execute('SELECT w.* FROM weddings w JOIN website_slugs a ON a.wedding_id=w.id WHERE a.slug=?',(slug,)).fetchone()
        if not w or w['suspended'] or w['access_until']<date.today().isoformat() or not json.loads(w['site']).get('published'): abort(404)
        return w
    @app.get('/website/preview')
    @auth()
    def preview_website():
        w=wedding();site=json.loads(w['site'])
        return render_template('wedding.html',site=site,slug=w['slug'],invitation=None,guests=[],preview=True,preview_cover=site.get('cover'))
    def site_unlocked(w):
        if not w['code_hash']: return True
        value=request.cookies.get('site_'+w['id'],'')
        return bool(token_row(value,'site-access') and token_row(value,'site-access')['wedding_id']==w['id'])
    @app.route('/weddings/<slug>',methods=['GET','POST'])
    def site(slug):
        w=public_wedding(slug)
        if not site_unlocked(w):
            if request.method=='POST':
                rate('site-code-'+w['id'],12)
                if check_password_hash(w['code_hash'],request.form.get('code','')):
                    value=token('site-access',wedding=w['id'],hours=24)
                    resp=redirect('/weddings/'+slug);resp.set_cookie('site_'+w['id'],value,max_age=86400,httponly=True,samesite='Lax',secure=app.config['SECURE_COOKIES']);return resp
                raise ValueError('That access code did not match.')
            return render_template('site_code.html')
        return render_template('wedding.html',site=json.loads(w['site']),slug=slug,invitation=None,guests=[])
    @app.post('/api/invitations')
    @auth()
    def invitations():
        w=wedding(True);body=json_body();ids=body.get('guest_ids',[]);s=json.loads(w['state']);guests={x['id']:x for x in s['guests']}
        if not ids or len(ids)>30 or len(set(ids))!=len(ids) or any(i not in guests for i in ids): raise ValueError('Select the individual guests on this invitation.')
        if not w['slug'] or not json.loads(w['site']).get('published'): raise ValueError('Publish your wedding website first.')
        invite=token('rsvp',wedding=w['id'],payload={'guest_ids':ids},hours=24*365*4)
        link=app.config['APP_URL']+'/weddings/'+w['slug']+'/invite/'+invite
        email=body.get('email','').strip().lower()
        if email:
            if not valid_email(email): raise ValueError('Check the invitation email.')
            queue(email,'Your wedding invitation',link)
        audit('Guest invitation created',w['id']);return jsonify(url=link,queued=bool(email))
    @app.get('/api/invitations')
    @auth()
    def invitation_list():
        w=wedding();state=json.loads(w['state']);names={x['id']:x['name'] for x in state['guests']};rows=[]
        for t in db().execute('SELECT * FROM tokens WHERE kind="rsvp" AND wedding_id=? ORDER BY expires DESC',(w['id'],)):
            rows.append({'id':t['hash'],'names':[names.get(i,'Guest removed') for i in json.loads(t['payload'])['guest_ids']], 'active':not t['used'] and t['expires']>time.time(),'expires':t['expires']})
        return jsonify(invitations=rows)
    @app.post('/api/invitations/<tid>/revoke')
    @auth()
    def revoke_invitation(tid):
        w=wedding(True);cur=db().execute('UPDATE tokens SET used=1 WHERE hash=? AND wedding_id=? AND kind="rsvp"',(tid,w['id']))
        if not cur.rowcount: abort(404)
        audit('Guest invitation revoked',w['id']);return jsonify(ok=True)
    @app.route('/weddings/<slug>/invite/<value>',methods=['GET','POST'])
    def rsvp(slug,value):
        w=public_wedding(slug);t=token_row(value,'rsvp')
        if not t or t['wedding_id']!=w['id']: abort(404)
        ids=json.loads(t['payload'])['guest_ids'];s=json.loads(w['state']);guests=[x for x in s['guests'] if x['id'] in ids]
        if not guests: abort(404)
        if request.method=='POST':
            rate('rsvp-'+t['hash'],30)
            errors=[]
            for guest in guests:
                prefix=guest['id']+'-';answer=request.form.get(prefix+'rsvp','')
                if answer not in ['Accepted','Declined']: errors.append('Please reply for each person.');answer='Waiting'
                guest['rsvp']=answer
                for key in ['meal','diet','access']:
                    v=request.form.get(prefix+key,'').strip()
                    if len(v)>160: errors.append('Please keep each answer to 160 characters.');v=v[:160]
                    guest[key]=v
            if errors:
                return render_template('wedding.html',site=json.loads(w['site']),slug=slug,invitation=value,guests=guests,error=errors[0]),400
            update_state(w,s,w['revision']);audit('Guest RSVP submitted',w['id'])
            return render_template('message.html',title='Thank you!',message='Your reply has been saved for the couple. You can use your invitation link to update it.')
        return render_template('wedding.html',site=json.loads(w['site']),slug=slug,invitation=value,guests=guests)

    def attachment_path(f):
        return Path(app.config['DATA_DIR'])/'files'/f['wedding_id']/Path(f['path']).name

    @app.get('/api/files')
    @auth()
    def list_files():
        w=wedding();return jsonify(files=[dict(r) for r in db().execute('SELECT id,name,mime,size,kind FROM uploads WHERE wedding_id=?',(w['id'],))])
    @app.post('/api/files')
    @auth()
    def upload_file():
        w=wedding(True);rate('uploads',60,3600);f=request.files.get('file');kind=request.form.get('kind','document')
        if not f or kind not in ['document','cover']: raise ValueError('Choose a PDF document or a cover photograph.')
        current=db().execute('SELECT coalesce(sum(size),0) n FROM uploads WHERE wedding_id=?',(w['id'],)).fetchone()['n']
        raw=f.read(10*1024*1024+1)
        if not raw or len(raw)>10*1024*1024 or current+len(raw)>250*1024*1024: raise ValueError('Maximum 10 MB per file and 250 MB per wedding.')
        name=Path(f.filename or 'document').name[:150]
        if kind=='cover':
            try:
                image=Image.open(io.BytesIO(raw))
                if image.width*image.height>20000000: raise ValueError('Cover photograph exceeds 20 megapixels. Resize it before uploading.')
                image.verify();image=Image.open(io.BytesIO(raw));image=ImageOps.exif_transpose(image);image.thumbnail((2400,2400));out=io.BytesIO();image.convert('RGB').save(out,'JPEG',quality=88);raw=out.getvalue()
            except (UnidentifiedImageError,ValueError,OSError,Image.DecompressionBombError): raise ValueError('Choose a valid JPEG, PNG or WebP image.')
            mime='image/jpeg';suffix='.jpg'
        else:
            if not raw.startswith(b'%PDF-'): raise ValueError('Only PDF supplier documents are accepted.')
            mime='application/pdf';suffix='.pdf'
        uid=secrets.token_hex(16);folder=Path(app.config['DATA_DIR'])/'files'/w['id'];folder.mkdir(exist_ok=True);path=folder/(uid+suffix);path.write_bytes(raw)
        db().execute('INSERT INTO uploads VALUES(?,?,?,?,?,?,?,?)',(uid,w['id'],name,str(path),mime,len(raw),kind,time.time()))
        audit('File uploaded',w['id']);return jsonify(id=uid)
    @app.get('/api/files/<uid>')
    @auth()
    def download_file(uid):
        w=wedding();f=db().execute('SELECT * FROM uploads WHERE id=? AND wedding_id=?',(uid,w['id'])).fetchone()
        if not f: abort(404)
        return send_file(attachment_path(f),mimetype=f['mime'],as_attachment=f['kind']=='document',download_name=f['name'])
    @app.delete('/api/files/<uid>')
    @auth()
    def delete_file(uid):
        w=wedding(True);f=db().execute('SELECT * FROM uploads WHERE id=? AND wedding_id=?',(uid,w['id'])).fetchone()
        if not f: abort(404)
        if json.loads(w['site']).get('cover')==uid: raise ValueError('Remove this cover from the website before deleting it.')
        if any(json.loads(r['data']).get('photo')==uid for r in db().execute('SELECT data FROM stationery_drafts WHERE wedding_id=?',(w['id'],))): raise ValueError('Remove this photograph from your stationery drafts before deleting it.')
        db().execute('DELETE FROM uploads WHERE id=?',(uid,));g.on_commit=getattr(g,'on_commit',[])
        g.on_commit.append(lambda:attachment_path(f).unlink(missing_ok=True));return jsonify(ok=True)
    @app.get('/weddings/<slug>/cover')
    def cover(slug):
        w=public_wedding(slug)
        if not site_unlocked(w):
            value=request.args.get('invite','');t=token_row(value,'rsvp')
            if not t or t['wedding_id']!=w['id']: abort(403)
        uid=json.loads(w['site']).get('cover');f=db().execute('SELECT * FROM uploads WHERE id=? AND wedding_id=? AND kind="cover"',(uid,w['id'])).fetchone()
        if not f: abort(404)
        return send_file(attachment_path(f),mimetype='image/jpeg')

    @app.post('/api/support')
    @auth()
    def support_grant():
        w=wedding();body=json_body()
        if body.get('revoke'): db().execute('DELETE FROM support WHERE wedding_id=?',(w['id'],));audit('Couple revoked support permission',w['id'])
        else:
            reason=str(body.get('reason','')).strip()[:300]
            if not reason: raise ValueError('Explain what you would like help with.')
            db().execute('INSERT OR REPLACE INTO support VALUES(?,?,?)',(w['id'],time.time()+1800,reason));audit('Couple granted 30-minute read-only support',w['id'])
        return jsonify(ok=True)
    @app.post('/api/sessions/revoke-others')
    def revoke_sessions():
        if not g.user or not g.user['verified']: abort(401)
        db().execute('DELETE FROM sessions WHERE (user_id=? OR pending=?) AND id!=?',(g.user['id'],g.user['id'],g.session['id']))
        audit('Other sign-in sessions revoked');return jsonify(ok=True)
    @app.get('/ivoryadmin')
    @auth(admin=True)
    def admin_page(): return render_template('admin.html')
    @app.get('/ivoryadmin/couples/<wid>/preview')
    @auth(admin=True)
    def admin_couple_preview(wid):
        w=db().execute('SELECT * FROM weddings WHERE id=?',(wid,)).fetchone()
        if not w or db().execute('SELECT 1 FROM cancelled_couple_invitations WHERE wedding_id=?',(wid,)).fetchone(): abort(404)
        actual=json.loads(w['state'])
        # Use a fresh sample plan. An admin preview must not expose private
        # guest, supplier, payment or note data or gain couple write access.
        sample=empty_state();sample['names']=actual['names'];sample['date']=actual['date'];sample['ready']=actual['ready']
        email=db().execute('SELECT u.email FROM users u JOIN members m ON m.user_id=u.id WHERE m.wedding_id=? ORDER BY u.created LIMIT 1',(wid,)).fetchone()
        preview_state={'state':sample,'revision':0,'account_email':email['email'] if email else '',
            'access_until':w['access_until'],'readonly':True}
        return render_template('couple_preview.html',preview_state=preview_state,access=w['access_kind'],until=w['access_until'])
    @app.get('/api/admin')
    @auth(admin=True)
    def admin_data():
        couples=[];cancelled=[]
        for w in db().execute('SELECT * FROM weddings ORDER BY created DESC'):
            s=json.loads(w['state']);emails=[r['email'] for r in db().execute('SELECT email FROM users JOIN members m ON m.user_id=users.id WHERE m.wedding_id=?',(w['id'],))]
            invitee=db().execute('SELECT u.id,u.verified,u.verified_at FROM users u JOIN members m ON m.user_id=u.id WHERE m.wedding_id=? AND EXISTS(SELECT 1 FROM tokens t WHERE t.wedding_id=m.wedding_id AND t.user_id=u.id AND t.kind="welcome") ORDER BY u.created LIMIT 1',(w['id'],)).fetchone()
            mail_history=db().execute("SELECT m.status,m.created,m.accepted_at,m.next_attempt,m.last_error FROM mail m JOIN tokens t ON m.dedupe=('welcome:' || t.hash) WHERE t.wedding_id=? ORDER BY m.created DESC LIMIT 10",(w['id'],)).fetchall() if invitee else []
            mail=mail_history[0] if mail_history else None
            invitation=None
            if invitee:
                joined=bool(invitee['verified'])
                raw=mail['status'] if mail else 'missing'
                label='Joined' if joined else 'Awaiting couple' if raw=='sent' else 'Queued' if raw in ('queued','retry') else 'Needs attention'
                action='Open couple journey' if joined else 'Preview / resend invitation' if raw in ('failed','cancelled','missing') else 'Wait for the couple to use their setup link' if raw=='sent' else 'Check email settings and worker status' if raw=='retry' else 'Wait for the email worker'
                invitation={'status':label,'queued_at':mail['created'] if mail else None,'accepted_at':mail['accepted_at'] if mail else None,'joined_at':invitee['verified_at'],'mail_status':raw,'next_attempt':mail['next_attempt'] if raw=='retry' else None,'last_error':mail['last_error'] if mail else None,'next_action':action,'history':[dict(m) for m in mail_history]}
            couples.append({'id':w['id'],'names':' & '.join(s['names']) or 'Setup incomplete','email':', '.join(emails),'wedding':s['date'],'access':w['access_kind'],'until':w['access_until'],'suspended':bool(w['suspended']),'stage':s['stage'],'journey':hub_journey(db(),w,s),'published':bool(json.loads(w['site']).get('published')),'invitation_pending':bool(invitee and not invitee['verified']),'invitation':invitation})
            cancellation=db().execute('SELECT cancelled FROM cancelled_couple_invitations WHERE wedding_id=?',(w['id'],)).fetchone()
            if cancellation:
                cancelled.append({**couples.pop(),'cancelled_at':cancellation['cancelled']})
        usage=shutil.disk_usage(app.config['DATA_DIR'])
        backups=list(Path(app.config['BACKUP_DIR']).glob('planner-*.tar.gz'))
        newest=max(backups,key=lambda p:p.stat().st_mtime) if backups else None
        deliveries=[dict(r) for r in db().execute('SELECT id,to_address,subject,status,attempts,last_error,created FROM mail ORDER BY created DESC LIMIT 30')]
        history=[dict(r) for r in db().execute('SELECT actor,action,wedding_id,created FROM audit ORDER BY id DESC LIMIT 100')]
        grants=[dict(r) for r in db().execute('SELECT * FROM support WHERE expires>?',(time.time(),))]
        paid=db().execute('SELECT coalesce(sum(amount),0) n FROM purchases WHERE status="paid"').fetchone()['n']
        paypal_payments=[]
        for p in db().execute('SELECT p.*,coalesce(r.transaction_id,b.transaction_id) transaction_id FROM purchases p LEFT JOIN paypal_receipts r ON r.purchase_id=p.id LEFT JOIN bank_receipts b ON b.purchase_id=p.id ORDER BY p.created DESC LIMIT 500'):
            terms=json.loads(p['terms'])
            if terms.get('provider') not in ['paypalme','bank']: continue
            c=next((c for c in couples if c['id']==p['wedding_id']),{})
            paypal_payments.append({**paypal_details(p),'wedding_id':p['wedding_id'],'names':c.get('names',''),'email':c.get('email',''),'transaction_id':p['transaction_id']})
        settings=config(db());public_settings={k:v for k,v in settings.items() if k not in ('smtp_password_encrypted','wbm_booking_key_hash')}
        heartbeat=settings.get('worker_heartbeat');failed=db().execute('SELECT count(*) n FROM mail WHERE status="failed"').fetchone()['n']
        health={'worker':{'ok':bool(heartbeat and time.time()-heartbeat<180),'last_seen':heartbeat,'action':'Check the planner worker container and its logs; queued email and backups need the worker.'},
            'email':{'ok':failed==0 and smtp_ready(settings),'failed':failed,'action':'Open Email & reminders, check failed messages and SMTP settings, then retry or resend the affected invitation.'},
            'backup':{'ok':bool(newest and time.time()-newest.stat().st_mtime<48*3600),'latest':newest.name if newest else None,'completed_at':newest.stat().st_mtime if newest else None,'action':'Check the worker logs and backup volume, then run an isolated restore test.'},
            'storage':{'ok':usage.free>=max(1024**3,usage.total//20),'free':usage.free,'total':usage.total,'action':'Free space on the planner data volume or expand it before uploads and backups fail.'}}
        return jsonify(invitation_default_until=access_end(settings),couples=couples,cancelled_invitations=cancelled,manual_payments=paypal_payments,paypal_payments=[p for p in paypal_payments if p['provider']=='paypalme'],settings=public_settings,smtp=smtp_configuration(settings),deliveries=deliveries,history=history,support=grants,
            status={'version':VERSION,'disk_total':usage.total,'disk_free':usage.free,'backups':[p.name for p in sorted(backups,reverse=True)[:10]],'smtp_configured':smtp_ready(settings),'stripe_configured':bool(os.getenv('STRIPE_SECRET_KEY') and os.getenv('STRIPE_WEBHOOK_SECRET')),'paid_sales_pence':paid,'worker_heartbeat':heartbeat,'health':health})
    from .admin_backups import register_admin_backups
    register_admin_backups(app,db,auth,audit,rate)

    def invitation_ready():
        settings=config(db())
        if not smtp_ready(settings): raise ValueError('Save and test your email settings before sending a couple invitation.')
        if not settings['terms_text'].strip() or not settings['privacy_text'].strip(): raise ValueError('Save your terms and privacy notice in Pricing & trials before inviting a couple.')
        return settings
    def invitation_details(body):
        email=body.get('email','');names=body.get('names');day=body.get('date','');kind=body.get('access','Trial');until=body.get('until','')
        if not isinstance(email,str) or not valid_email(email.strip().lower()): raise ValueError('Enter the couple’s main email address.')
        email=email.strip().lower()
        if not isinstance(names,list) or len(names)!=2 or any(not isinstance(n,str) or not n.strip() or len(n)>100 or any(c in n for c in '\r\n\0') for n in names): raise ValueError('Enter both partners’ names, up to 100 characters each.')
        if not date_valid(day) or kind not in ['Trial','Complimentary']: raise ValueError('Choose a valid wedding date and trial or complimentary access.')
        if kind=='Complimentary' and (not date_valid(until,False) or until<date.today().isoformat()): raise ValueError('Choose a complimentary access end date today or later.')
        if kind=='Trial': until=(date.today()+timedelta(days=config(db())['trial_days'])).isoformat()
        state=empty_state();state.update(names=[n.strip() for n in names],email=email,date=day)
        return state,kind,until
    def pending_invitee(wid):
        if db().execute('SELECT 1 FROM cancelled_couple_invitations WHERE wedding_id=?',(wid,)).fetchone():
            abort(409,description='This invitation was cancelled. Restore it from Cancelled invitations before previewing or resending.')
        u=db().execute('SELECT u.* FROM users u JOIN members m ON m.user_id=u.id WHERE m.wedding_id=? AND u.verified=0 AND EXISTS(SELECT 1 FROM tokens t WHERE t.user_id=u.id AND t.kind="welcome" AND t.wedding_id=m.wedding_id)',(wid,)).fetchone()
        w=db().execute('SELECT * FROM weddings WHERE id=?',(wid,)).fetchone()
        if not u or not w: raise ValueError('This invitation was already accepted or the account was not created by invitation.')
        if w['suspended']: raise ValueError('This account is suspended. Review its access before sending an invitation.')
        return u,w
    def invitation_preview(state,kind,until,email,custom=None):
        settings=invitation_ready()
        message=invitation_email(state,kind,until,settings['trial_days'],app.config['APP_URL']+'/welcome/personal-link-generated-when-sent',custom)
        fingerprint=digest(json.dumps({'to':email,'body':message['body'],'subject':message['subject']},sort_keys=True))
        return dict(message,to=email,sender=settings['sender'],reply_to=settings['reply_to'] or settings['sender'],preview_hash=fingerprint,preview_only=True)
    def welcome_email(uid,wid,email,custom=None,preview_hash=None):
        settings=invitation_ready();w=db().execute('SELECT * FROM weddings WHERE id=?',(wid,)).fetchone();state=json.loads(w['state'])
        preview=invitation_preview(state,w['access_kind'],w['access_until'],email,custom)
        if preview_hash is not None and preview_hash!=preview['preview_hash']: raise ValueError('The invitation details changed. Preview it again before sending.')
        db().execute('UPDATE tokens SET used=1 WHERE user_id=? AND kind="welcome"',(uid,))
        value=token('welcome',user=uid,wedding=wid,email=email,hours=24*7,payload={'terms':settings['terms_text'],'privacy':settings['privacy_text'],'email_fields':preview['email']})
        message=invitation_email(state,w['access_kind'],w['access_until'],settings['trial_days'],app.config['APP_URL']+'/welcome/'+value,preview['email'])
        return queue(email,message['subject'],message['body'],dedupe='welcome:'+digest(value),html_body=message['html'])
    @app.post('/api/admin/couples/invitation-preview')
    @auth(admin=True)
    def preview_couple_invitation():
        body=json_body();wid=body.get('wedding_id')
        if wid:
            if not isinstance(wid,str): raise ValueError('Choose a couple invitation.')
            u,w=pending_invitee(wid);state=json.loads(w['state']);kind=w['access_kind'];until=w['access_until'];email=u['email']
        else:
            state,kind,until=invitation_details(body);email=state['email']
            if db().execute('SELECT 1 FROM users WHERE email=?',(email,)).fetchone(): abort(409,description='This email already has an account. Find it in Couples & access; existing plans were not changed.')
        return jsonify(invitation_preview(state,kind,until,email,body.get('invitation_email')))
    @app.get('/api/admin/couples/<wid>/invitation-preview')
    @auth(admin=True)
    def existing_couple_invitation(wid):
        u,w=pending_invitee(wid)
        latest=db().execute("SELECT t.payload,m.subject,m.body,m.html_body,m.status FROM tokens t LEFT JOIN mail m ON m.dedupe=('welcome:' || t.hash) WHERE t.user_id=? AND t.kind='welcome' ORDER BY t.expires DESC LIMIT 1",(u['id'],)).fetchone()
        custom=json.loads(latest['payload']).get('email_fields') if latest else None
        result=invitation_preview(json.loads(w['state']),w['access_kind'],w['access_until'],u['email'],custom)
        result['previous']={'subject':latest['subject'],'body':latest['body'],'html':latest['html_body'],'status':latest['status']} if latest and latest['subject'] else None
        return jsonify(result)
    def create_couple_invitation(body):
        state,kind,until=invitation_details(body);email=state['email']
        if not body.get('_connection'):
            rate('admin-invite',50,3600,per_ip=False);db().execute('BEGIN IMMEDIATE')
        if db().execute('SELECT 1 FROM users WHERE email=?',(email,)).fetchone(): abort(409,description='This email already has an account. Find it in Couples & access to manage access or resend its invitation. No existing plans were changed.')
        uid=secrets.token_hex(16);wid=secrets.token_hex(16)
        db().execute('INSERT INTO users(id,email,password,created) VALUES(?,?,?,?)',(uid,email,generate_password_hash(secrets.token_urlsafe(48)),time.time()))
        db().execute('INSERT INTO weddings(id,state,access_kind,access_until,created) VALUES(?,?,?,?,?)',(wid,json.dumps(state),kind,until,time.time()))
        db().execute('INSERT INTO members VALUES(?,?)',(wid,uid));welcome_email(uid,wid,email,body.get('invitation_email'),body.get('preview_hash'))
        audit('Couple invited with '+kind+' access until '+until,wid)
        return jsonify(ok=True,wedding_id=wid,message='Invitation email queued. They will choose their own password.'),201
    @app.post('/api/admin/couples/invite')
    @auth(admin=True)
    def admin_invite_couple():
        body=json_body();body.pop('_connection',None)
        return create_couple_invitation(body)

    @app.post('/api/admin/booking-connection')
    @auth(admin=True)
    def admin_booking_connection():
        body=json_body()
        if type(body.get('enabled')) is not bool: raise ValueError('Choose whether the booking connection is enabled.')
        settings=config(db());value=None
        if body.get('rotate'):
            value='wbm_planner_'+secrets.token_urlsafe(36)
            db().execute('INSERT OR REPLACE INTO settings VALUES(?,?)',('wbm_booking_key_hash',json.dumps(digest(value))))
        elif body['enabled'] and not settings.get('wbm_booking_key_hash'):
            raise ValueError('Create a connection key first.')
        db().execute('INSERT OR REPLACE INTO settings VALUES(?,?)',('wbm_booking_enabled',json.dumps(body['enabled'])))
        audit('Booking invitation connection '+('enabled' if body['enabled'] else 'paused'))
        return jsonify(ok=True,key=value,enabled=body['enabled'])

    @app.get('/api/integrations/wbm/status')
    def booking_connection_status():
        settings=config(db())
        return jsonify(ok=True,ready=bool(smtp_ready(settings) and settings['terms_text'].strip() and settings['privacy_text'].strip()),version=VERSION,capabilities={"timings":1})

    def booking_invitation_status(row):
        if db().execute('SELECT 1 FROM cancelled_couple_invitations WHERE wedding_id=?',(row['wedding_id'],)).fetchone():
            return {'booking_id':row['booking_id'],'wedding_id':row['wedding_id'],'status':'cancelled','access_until':None}
        user=db().execute('SELECT verified FROM users WHERE id=?',(row['user_id'],)).fetchone()
        # Follow a deliberate admin resend, without sending a second email here.
        delivery=db().execute("SELECT m.status FROM mail m JOIN tokens t ON m.dedupe=('welcome:' || t.hash) WHERE t.user_id=? AND t.kind='welcome' ORDER BY m.created DESC LIMIT 1",(row['user_id'],)).fetchone()
        if not delivery: delivery=db().execute('SELECT status FROM mail WHERE id=?',(row['mail_id'],)).fetchone()
        w=db().execute('SELECT access_until FROM weddings WHERE id=?',(row['wedding_id'],)).fetchone()
        return {'booking_id':row['booking_id'],'wedding_id':row['wedding_id'],
                'status':'accepted' if user and user['verified'] else delivery['status'] if delivery else 'needs_attention',
                'access_until':w['access_until'] if w else None}

    @app.get('/api/integrations/wbm/invitations/<booking_id>')
    def get_booking_invitation(booking_id):
        row=db().execute('SELECT * FROM wbm_booking_invitations WHERE booking_id=?',(booking_id,)).fetchone()
        if not row: abort(404)
        return jsonify(booking_invitation_status(row))

    @app.post('/api/integrations/wbm/invitations')
    def create_booking_invitation():
        body=json_body()
        expected={'booking_id','first_name','partner_first_name','email','wedding_date'}
        if set(body)!=expected: raise ValueError('Supply the booking, both first names, email and wedding date.')
        if not isinstance(body['booking_id'],str) or not re.fullmatch(r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}',body['booking_id']): raise ValueError('Invalid booking identifier.')
        if not isinstance(body['wedding_date'],str) or not date_valid(body['wedding_date'],False): raise ValueError('A wedding date is required.')
        day=date.fromisoformat(body['wedding_date'])
        if day<date.today(): raise ValueError('The wedding date must be today or later.')
        if not isinstance(body['email'],str): raise ValueError('A valid email is required.')
        body['email']=body['email'].strip().lower()
        for key in ('first_name','partner_first_name'):
            if not isinstance(body[key],str) or not body[key].strip() or len(body[key])>100: raise ValueError('Both first names are required.')
            body[key]=body[key].strip()
        fingerprint=digest(json.dumps(body,sort_keys=True,separators=(',',':')))
        # Serialise the deduplication check with invitation creation. If the
        # response is lost, replay returns the same queued invitation.
        rate('wbm-invites',100,3600,per_ip=False)
        db().execute('BEGIN IMMEDIATE')
        existing=db().execute('SELECT * FROM wbm_booking_invitations WHERE booking_id=?',(body['booking_id'],)).fetchone()
        if existing:
            if existing['request_hash']!=fingerprint: abort(409,description='This booking already has a planner invitation with different details. Review it in planner admin.')
            return jsonify(booking_invitation_status(existing))
        # The shared invitation function starts its own immediate transaction.
        # Keep this lock: suppress its rate/BEGIN setup only for this call.
        response,code=create_couple_invitation({'names':[body['first_name'],body['partner_first_name']],
            'email':body['email'],'date':body['wedding_date'],'access':'Complimentary',
            'until':(day+timedelta(days=30)).isoformat(),'_connection':True})
        wid=response.get_json()['wedding_id']
        uid=db().execute('SELECT user_id FROM members WHERE wedding_id=?',(wid,)).fetchone()['user_id']
        mail=db().execute("SELECT m.id FROM mail m JOIN tokens t ON m.dedupe=('welcome:' || t.hash) WHERE t.user_id=? AND t.wedding_id=? AND t.kind='welcome' ORDER BY m.created DESC LIMIT 1",(uid,wid)).fetchone()
        db().execute('INSERT INTO wbm_booking_invitations VALUES(?,?,?,?,?,?)',(body['booking_id'],wid,uid,mail['id'],fingerprint,time.time()))
        audit('Complimentary invitation from WBM booking '+body['booking_id'],wid)
        row=db().execute('SELECT * FROM wbm_booking_invitations WHERE booking_id=?',(body['booking_id'],)).fetchone()
        return jsonify(booking_invitation_status(row)),201

    @app.post('/api/admin/couples/<wid>/resend-invitation')
    @auth(admin=True)
    def admin_resend_welcome(wid):
        rate('admin-resend-invite',20,3600,per_ip=False)
        row,w=pending_invitee(wid);body=json_body()
        welcome_email(row['id'],wid,row['email'],body.get('invitation_email'),body.get('preview_hash'));audit('Couple invitation resent',wid);return jsonify(ok=True)

    def cancellable_invitation(wid):
        w=db().execute('SELECT * FROM weddings WHERE id=?',(wid,)).fetchone()
        if not w: abort(404)
        members=db().execute('SELECT u.* FROM users u JOIN members m ON m.user_id=u.id WHERE m.wedding_id=?',(wid,)).fetchall()
        if len(members)!=1 or members[0]['role']!='couple' or members[0]['verified']:
            abort(409,description='Only an unaccepted invitation can be cancelled or restored. Existing couple accounts were not changed.')
        if not db().execute('SELECT 1 FROM tokens WHERE wedding_id=? AND user_id=? AND kind="welcome"',(wid,members[0]['id'])).fetchone():
            abort(409,description='This account was not created by invitation. Nothing was changed.')
        if db().execute('SELECT 1 FROM purchases WHERE wedding_id=?',(wid,)).fetchone():
            abort(409,description='This invitation has payment history or a payment request. Review it through Manage access instead.')
        return w,members[0]

    @app.post('/api/admin/couples/<wid>/cancel-invitation')
    @auth(admin=True)
    def admin_cancel_invitation(wid):
        if json_body().get('confirmed') is not True: raise ValueError('Confirm that you want to cancel this invitation.')
        rate('admin-cancel-invite',50,3600,per_ip=False)
        db().execute('BEGIN IMMEDIATE')
        if db().execute('SELECT 1 FROM cancelled_couple_invitations WHERE wedding_id=?',(wid,)).fetchone():
            return jsonify(ok=True,message='This invitation is already cancelled.')
        w,u=cancellable_invitation(wid)
        db().execute('INSERT INTO cancelled_couple_invitations VALUES(?,?)',(wid,time.time()))
        db().execute('UPDATE weddings SET suspended=1 WHERE id=?',(wid,))
        # Capture welcome-mail relationships before revoking all account links.
        db().execute("UPDATE mail SET status='cancelled',last_error=NULL WHERE status IN ('queued','retry') AND dedupe IN (SELECT 'welcome:' || hash FROM tokens WHERE wedding_id=? AND kind='welcome')",(wid,))
        db().execute('UPDATE tokens SET used=1 WHERE user_id=? OR wedding_id=?',(u['id'],wid))
        db().execute('DELETE FROM sessions WHERE user_id=? OR pending=?',(u['id'],u['id']))
        audit('Unaccepted couple invitation cancelled; removed from active list',wid)
        return jsonify(ok=True,message='Invitation cancelled and removed from the active list. Its setup links no longer work. Emails already accepted by the mail server cannot be recalled.')

    @app.post('/api/admin/couples/<wid>/restore-invitation')
    @auth(admin=True)
    def admin_restore_invitation(wid):
        if json_body().get('confirmed') is not True: raise ValueError('Confirm that you want to restore this invitation.')
        rate('admin-restore-invite',50,3600,per_ip=False)
        db().execute('BEGIN IMMEDIATE')
        if not db().execute('SELECT 1 FROM cancelled_couple_invitations WHERE wedding_id=?',(wid,)).fetchone():
            abort(409,description='This invitation is not cancelled. Find it in the active couple list.')
        cancellable_invitation(wid)
        db().execute('DELETE FROM cancelled_couple_invitations WHERE wedding_id=?',(wid,))
        db().execute('UPDATE weddings SET suspended=0 WHERE id=?',(wid,))
        audit('Cancelled invitation restored for review; no email sent',wid)
        return jsonify(ok=True,message='Invitation restored. No email was sent and old links remain disabled. Use Preview / resend invitation to review and send a new setup link.')
    @app.route('/welcome/<value>',methods=['GET','POST'])
    def welcome(value):
        t=token_row(value,'welcome')
        if not t: return render_template('message.html',title='Invitation no longer available',message='This invitation has expired, was replaced or has already been accepted. Sign in if you have set your password, or ask Ivory Digital for a new invitation.'),400
        u=db().execute('SELECT * FROM users WHERE id=? AND role="couple" AND verified=0',(t['user_id'],)).fetchone()
        w=db().execute('SELECT w.* FROM weddings w JOIN members m ON m.wedding_id=w.id WHERE w.id=? AND m.user_id=?',(t['wedding_id'],t['user_id'])).fetchone()
        if not u or not w or w['suspended']: abort(403)
        policies=json.loads(t['payload']);state=json.loads(w['state'])
        def form(error=None): return render_template('welcome.html',email=u['email'],names=' & '.join(state['names']),policies=policies,kind=w['access_kind'],until=date.fromisoformat(w['access_until']).strftime('%d %B %Y'),trial_days=config(db())['trial_days'],error=error)
        if request.method=='GET': return form()
        rate('accept-invitation',30,3600);password=request.form.get('password','')
        if not password_ok(password): return form('Choose a password of 12 to 200 characters.'),400
        if request.form.get('accept_terms')!='yes': return form('Please read and accept the terms and privacy notice.'),400
        db().execute('BEGIN IMMEDIATE')
        consumed=db().execute('UPDATE tokens SET used=1 WHERE hash=? AND used=0 AND expires>?',(t['hash'],time.time()))
        updated=db().execute('UPDATE users SET password=?,verified=1,verified_at=? WHERE id=? AND verified=0',(generate_password_hash(password),time.time(),u['id']))
        if not consumed.rowcount or not updated.rowcount: abort(409,description='This invitation has already been accepted. Please sign in.')
        db().execute('UPDATE tokens SET used=1 WHERE user_id=? AND kind IN ("welcome","verify","reset")',(u['id'],))
        if w['access_kind']=='Trial':
            until=(date.today()+timedelta(days=config(db())['trial_days'])).isoformat()
            db().execute('UPDATE weddings SET access_until=max(access_until,?) WHERE id=?',(until,w['id']))
        db().execute('INSERT INTO policy_acceptances(user_id,wedding_id,terms,privacy,accepted) VALUES(?,?,?,?,?)',(u['id'],w['id'],policies['terms'],policies['privacy'],time.time()))
        rotated(user=u['id']);audit('Couple invitation accepted; terms and privacy notice recorded',w['id']);return redirect('/app')
    @app.post('/api/admin/access/<wid>')
    @auth(admin=True)
    def admin_access(wid):
        body=json_body();kind=body.get('access');until=body.get('until');reason=str(body.get('reason','')).strip()
        w=db().execute('SELECT * FROM weddings WHERE id=?',(wid,)).fetchone()
        if not w: abort(404)
        if db().execute('SELECT 1 FROM cancelled_couple_invitations WHERE wedding_id=?',(wid,)).fetchone():
            abort(409,description='Restore this invitation from Cancelled invitations before changing its access.')
        if kind not in ['Trial','Complimentary','Manual extension','Suspended'] or not date_valid(until,False) or not reason: raise ValueError('Choose access, an end date and a reason.')
        paid_dates=[json.loads(r['terms']).get('access_until','') for r in db().execute('SELECT terms FROM purchases WHERE wedding_id=? AND status="paid"',(wid,))]
        history_exists=db().execute('SELECT 1 FROM purchases WHERE wedding_id=?',(wid,)).fetchone()
        paid_until=max(paid_dates+[w['access_until'] if w['access_kind']=='Paid' and not history_exists else ''])
        if until<paid_until: raise ValueError('Existing paid access cannot be shortened here.')
        db().execute('UPDATE weddings SET access_kind=?,access_until=?,suspended=? WHERE id=?',(kind,until,int(kind=='Suspended'),wid))
        audit('Access changed to '+kind+' until '+until+'; '+reason[:300],wid);return jsonify(ok=True)
    @app.put('/api/admin/settings')
    @auth(admin=True)
    def admin_settings():
        body=json_body();current=config(db())
        from .core import DEFAULT_SETTINGS
        allowed=(set(DEFAULT_SETTINGS)-{'smtp_password_encrypted'})|{'smtp_password','smtp_clear_password'}
        for key,value in body.items():
            if key not in allowed: raise ValueError('Unknown setting.')
            if key=='smtp_password':
                if not isinstance(value,str) or len(value)>2000 or '\r' in value or '\n' in value: raise ValueError('Check the SMTP password.')
                continue
            if key=='smtp_clear_password':
                if type(value) is not bool: raise ValueError('Invalid password removal switch.')
                continue
            if key=='payment_provider' and value not in ['stripe','paypalme','bank']: raise ValueError('Choose bank transfer, PayPal.Me or Stripe.')
            if key in ['bank_name','bank_account_name','bank_instructions'] and (not isinstance(value,str) or len(value)>(500 if key=='bank_instructions' else 100) or '\r' in value or '\0' in value or key!='bank_instructions' and '\n' in value): raise ValueError('Check the bank account name, bank name and instructions.')
            if key in ['bank_sort_code','bank_account_number']:
                if not isinstance(value,str): raise ValueError('Bank details must be entered as text so leading zeros are kept.')
                value=re.sub(r'[\s-]','',value.strip())
                if value and not re.fullmatch(r'\d{'+('6' if key=='bank_sort_code' else '8')+'}',value,flags=re.ASCII): raise ValueError('Use a six-digit sort code and eight-digit UK account number.')
            if key=='paypal_me_url': value=paypal_link(value)
            if key=='smtp_source' and value not in ['panel','environment']: raise ValueError('Choose where SMTP settings are supplied.')
            if key=='smtp_host' and (not isinstance(value,str) or len(value)>253 or value and not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?',value)): raise ValueError('Enter the SMTP hostname, without https:// or a port.')
            if key=='smtp_port' and (type(value) is not int or not 1<=value<=65535): raise ValueError('SMTP port must be between 1 and 65535.')
            if key=='smtp_security' and value not in ['ssl','starttls']: raise ValueError('Choose SSL/TLS or STARTTLS.')
            if key=='smtp_user' and (not isinstance(value,str) or len(value)>320 or any(c in value for c in '\r\n\0')): raise ValueError('Check the SMTP username.')

            if key in ['checkout_enabled','signups_enabled'] and type(value) is not bool: raise ValueError('Invalid switch.')
            if key=='price_pence' and value is not None and (type(value) is not int or not 100<=value<=1000000): raise ValueError('Price must be at least £1.')
            if key in ['trial_days','days_after_wedding','max_planning_days','backup_retention_days'] and (type(value) is not int or not 0<=value<=3650): raise ValueError('Invalid day allowance.')
            if key=='access_rule' and value not in ['wedding','fixed']: raise ValueError('Invalid access rule.')
            if key in ['sender','reply_to'] and (not isinstance(value,str) or value and not valid_email(value)): raise ValueError('Invalid email.')
            if key in ['reminder_time','backup_time'] and (not isinstance(value,str) or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d',value)): raise ValueError('Invalid time.')
            if key=='timezone':
                try: ZoneInfo(value)
                except (ZoneInfoNotFoundError,ValueError,TypeError): raise ValueError('Use a valid timezone such as Europe/London.')
            if isinstance(value,str) and len(value)>10000: raise ValueError('Setting too long.')
            current[key]=value
        password=body.get('smtp_password','');clear_password=body.get('smtp_clear_password',False)
        if password and clear_password: raise ValueError('Enter a replacement password or remove it, not both.')
        if password:
            if current['smtp_source']!='panel': raise ValueError('Choose admin panel settings to save a new SMTP password.')
            current['smtp_password_encrypted']=cipher(secret).encrypt(password.encode()).decode()
        elif clear_password: current['smtp_password_encrypted']=''
        if current['checkout_enabled']:
            if not current['price_pence'] or not current['refund_terms']: raise ValueError('Set a price and refund terms before opening payments.')
            if current['payment_provider']=='stripe' and (not os.getenv('STRIPE_SECRET_KEY') or not os.getenv('STRIPE_WEBHOOK_SECRET')): raise ValueError('Configure Stripe credentials before opening Stripe checkout.')
            if current['payment_provider']=='paypalme' and not current['paypal_me_url']: raise ValueError('Enter your PayPal.Me profile link before opening payments.')
            if current['payment_provider']=='bank' and not bank_ready(current): raise ValueError('Save the account holder, six-digit sort code and eight-digit account number before opening bank payments.')
        if current['signups_enabled'] and (not smtp_ready(current) or not current['privacy_text'] or not current['terms_text']): raise ValueError('Configure email, privacy notice and terms before enabling sign-ups.')
        changed=set(body)-{'smtp_password','smtp_clear_password'}
        if password or clear_password: changed.add('smtp_password_encrypted')
        for k in changed: db().execute('UPDATE settings SET value=? WHERE key=?',(json.dumps(current[k]),k))
        audit('System settings updated');return jsonify(ok=True)
    @app.post('/api/admin/email-test')
    @auth(admin=True)
    def test_email():
        rate('smtp-test',6,900,per_ip=False)
        settings=config(db())
        if not smtp_ready(settings): raise ValueError('Save the SMTP host, port, security, sender and required login details before sending a test.')
        mid=secrets.token_hex(12)
        db().execute('INSERT INTO mail(id,to_address,subject,body,status,created) VALUES(?,?,?,?,?,?)',
            (mid,g.user['email'],'Ivory Planner email test','Your planner email service is working.','sending',time.time()))
        audit('Test email requested');db().commit()
        # Do not hold a database write lock while connecting to an external service.
        try:
            send_email(settings,secret,g.user['email'],'Ivory Planner email test','Your planner email service is working.',mid)
        except Exception as exc:
            message=delivery_error(exc)
            db().execute('UPDATE mail SET status="failed",attempts=1,last_error=? WHERE id=?',(message,mid));db().commit()
            return jsonify(error=message,delivery_id=mid),400
        db().execute('UPDATE mail SET status="sent",attempts=1,accepted_at=? WHERE id=?',(time.time(),mid));db().commit()
        return jsonify(ok=True,status='sent',delivery_id=mid,message='Accepted by the email server. Check your admin inbox and spam folder.')
    @app.get('/api/admin/support/<wid>')
    @auth(admin=True)
    def view_support(wid):
        grant=db().execute('SELECT * FROM support WHERE wedding_id=? AND expires>?',(wid,time.time())).fetchone()
        if not grant: abort(403,description='The couple must grant support access first.')
        w=db().execute('SELECT state FROM weddings WHERE id=?',(wid,)).fetchone()
        s=json.loads(w['state']);audit('Read-only support viewed',wid)
        # Family notes and guest access/dietary data are not needed for payment support.
        return jsonify(suppliers=s['suppliers'],payments=s['payments'],reason=grant['reason'],expires=grant['expires'])
    @app.post('/api/admin/revoke-support/<wid>')
    @auth(admin=True)
    def revoke_support(wid): db().execute('DELETE FROM support WHERE wedding_id=?',(wid,));audit('Support session ended',wid);return jsonify(ok=True)

    def paypal_link(value):
        if not isinstance(value,str): raise ValueError('Enter a PayPal.Me profile link.')
        value=value.strip()
        if not value: return ''
        match=re.fullmatch(r'https://(?:www\.)?paypal\.me/([A-Za-z0-9]{2,40})/?',value)
        if not match: raise ValueError('Use https://paypal.me/yourname without an amount, query or extra path.')
        return 'https://paypal.me/'+match.group(1)

    def bank_ready(settings):
        return bool(settings.get('bank_account_name','').strip() and re.fullmatch(r'[0-9]{6}',settings.get('bank_sort_code','')) and re.fullmatch(r'[0-9]{8}',settings.get('bank_account_number','')))

    def paypal_pending(wid):
        # Legacy helper name retained for compatibility; now covers both manual methods.
        for p in db().execute('SELECT * FROM purchases WHERE wedding_id=? AND status IN ("pending","reported") ORDER BY created DESC',(wid,)):
            if json.loads(p['terms']).get('provider') in ['paypalme','bank']: return p
        return None

    def paypal_details(p):
        t=json.loads(p['terms']);provider=t['provider']
        result={'id':p['id'],'provider':provider,'reference':'IP-'+p['id'][:12].upper(),'amount_pence':p['amount'],'currency':'GBP',
            'status':p['status'],'access_until':t['access_until'],'refund_terms':t['refund_terms'],'terms_text':t.get('terms_text',''),
            'accepted':bool(t.get('accepted_at')),'reported_transaction':t.get('reported_transaction',''),
            'reported_payer':t.get('reported_payer',''),'reported_date':t.get('reported_date',''),'created':p['created']}
        if provider=='paypalme':
            link=paypal_link(t['paypal_me_url']);result.update(recipient_profile=link.rsplit('/',1)[-1],url=link+'/'+format(p['amount']/100,'.2f')+'GBP')
        else: result['bank']=t['bank']
        return result

    def needs_payment(w):
        if w['access_kind'] in ['Paid','Complimentary','Manual extension'] and w['access_until']>=date.today().isoformat(): raise ValueError('You already have full access. No payment is needed.')

    def prepare_manual(w,settings,provider,accepted=False):
        needs_payment(w)
        pending=paypal_pending(w['id'])
        if pending:
            if json.loads(pending['terms'])['provider']!=provider: raise ValueError('There is already a request using another payment method. Check it and close it as unpaid before preparing a different one.')
            return pending
        if db().execute('SELECT 1 FROM purchases WHERE wedding_id=? AND status="pending"',(w['id'],)).fetchone(): raise ValueError('An earlier checkout needs checking by Ivory Digital before another payment is prepared.')
        if provider not in ['paypalme','bank'] or not settings['price_pence'] or not settings['refund_terms']: raise ValueError('Set a price, refund terms and a manual payment method first.')
        if provider=='paypalme' and not settings['paypal_me_url']: raise ValueError('Save the PayPal.Me link first.')
        if provider=='bank' and not bank_ready(settings): raise ValueError('Save the account holder, sort code and UK account number in Pricing & trials first.')
        pid=secrets.token_hex(16)
        terms={'provider':provider,'price_pence':settings['price_pence'],'access_until':access_end(settings,json.loads(w['state'])['date']),
            'refund_terms':settings['refund_terms'],'terms_text':settings['terms_text'],'accepted_at':time.time() if accepted else None,
            'checkout_email':g.user['email'] if accepted else ''}
        if provider=='paypalme': terms['paypal_me_url']=paypal_link(settings['paypal_me_url'])
        else: terms['bank']={k:settings['bank_'+k] for k in ['name','account_name','sort_code','account_number','instructions']}
        db().execute('INSERT INTO purchases(id,wedding_id,amount,terms,created) VALUES(?,?,?,?,?)',(pid,w['id'],settings['price_pence'],json.dumps(terms),time.time()))
        audit(('Bank transfer' if provider=='bank' else 'PayPal')+' payment instructions prepared',w['id'])
        return db().execute('SELECT * FROM purchases WHERE id=?',(pid,)).fetchone()

    def manual_purchase(pid,wid=None):
        p=db().execute('SELECT * FROM purchases WHERE id=?',(pid,)).fetchone()
        if not p or wid is not None and p['wedding_id']!=wid or json.loads(p['terms']).get('provider') not in ['paypalme','bank']: abort(404)
        return p

    @app.get('/upgrade')
    @auth()
    def upgrade_page(): wedding();return render_template('upgrade.html')

    @app.post('/api/payments/start')
    @app.post('/api/paypal/start')
    @auth()
    def paypal_start():
        w=wedding();settings=config(db());body=json_body()
        needs_payment(w)
        if not settings['checkout_enabled'] or settings['payment_provider'] not in ['paypalme','bank']: raise ValueError('Manual payments are not open. Contact Ivory Digital for access.')
        if body.get('accept_terms') is not True: raise ValueError('Read and accept the payment terms before continuing.')
        rate('manual-start-'+w['id'],30,3600,per_ip=False);db().execute('BEGIN IMMEDIATE')
        p=prepare_manual(wedding(),settings,settings['payment_provider'],accepted=True)
        return jsonify(request=paypal_details(p))

    @app.post('/api/admin/payments/request/<wid>')
    @auth(admin=True)
    def request_manual_payment(wid):
        body=json_body();provider=body.get('provider');send=body.get('send_email',False);settings=config(db())
        if provider not in ['bank','paypalme'] or type(send) is not bool: raise ValueError('Choose bank transfer or PayPal and whether to email the request.')
        if send and not smtp_ready(settings): raise ValueError('Configure email first, or untick email delivery to copy the request link yourself.')
        rate('request-payment-'+wid,20,3600,per_ip=False);db().execute('BEGIN IMMEDIATE')
        w=db().execute('SELECT * FROM weddings WHERE id=?',(wid,)).fetchone()
        if not w: abort(404)
        if w['suspended']: raise ValueError('Review this suspended account before sending a payment request.')
        recipients=[r['email'] for r in db().execute('SELECT u.email FROM users u JOIN members m ON m.user_id=u.id WHERE m.wedding_id=? AND u.verified=1',(wid,))]
        if send and not recipients: raise ValueError('The couple needs a verified account email before receiving a payment request.')
        p=prepare_manual(w,settings,provider);details=paypal_details(p);link=app.config['APP_URL']+'/upgrade';queued=0
        if send:
            for email in recipients:
                message=f'Your Ivory Digital wedding planner payment request is ready.\n\nAmount: £{p["amount"]/100:.2f} GBP\nMethod: {"Bank transfer" if provider=="bank" else "PayPal"}\nReference: {details["reference"]}\n\nSign in to your own planner to read the terms and view payment instructions:\n{link}\n\nIf you have already paid, do not pay again. Access is activated after the payment is checked.'
                cur=db().execute('INSERT OR IGNORE INTO mail(id,to_address,subject,body,dedupe,created) VALUES(?,?,?,?,?,?)',(secrets.token_hex(12),email,'Your wedding planner payment request',message,'manual-request:'+p['id']+':'+email,time.time()))
                queued+=cur.rowcount
            audit('Payment request email queued to verified wedding members',wid)
        return jsonify(request=details,url=link,queued=queued,email_requested=send)

    @app.post('/api/payments/<pid>/accept')
    @auth()
    def accept_manual_payment(pid):
        w=wedding();body=json_body()
        if body.get('accept_terms') is not True: raise ValueError('Read and accept the payment terms first.')
        db().execute('BEGIN IMMEDIATE');p=manual_purchase(pid,w['id'])
        if p['status'] not in ['pending','reported']: raise ValueError('This payment request is closed. Reload to check your access.')
        t=json.loads(p['terms'])
        if not t.get('accepted_at'):
            t.update(accepted_at=time.time(),checkout_email=g.user['email']);db().execute('UPDATE purchases SET terms=? WHERE id=?',(json.dumps(t),pid))
        return jsonify(request=paypal_details(manual_purchase(pid,w['id'])))

    @app.post('/api/payments/<pid>/report')
    @app.post('/api/paypal/<pid>/report')
    @auth()
    def paypal_report(pid):
        w=wedding();body=json_body();rate('manual-report-'+w['id'],12,3600,per_ip=False)
        db().execute('BEGIN IMMEDIATE');p=manual_purchase(pid,w['id']);t=json.loads(p['terms'])
        if p['status']=='paid': return jsonify(ok=True,status='paid')
        if p['status'] not in ['pending','reported']: raise ValueError('This payment request is closed. Contact Ivory Digital before sending any money.')
        if not t.get('accepted_at'): raise ValueError('Read and accept this request’s payment terms first.')
        if t['provider']=='paypalme':
            reference=body.get('transaction_id','')
            if not isinstance(reference,str) or not re.fullmatch(r'[A-Za-z0-9-]{5,80}',reference.strip()): raise ValueError('Enter the transaction ID from your PayPal payment receipt.')
            t['reported_transaction']=reference.strip()
        else:
            payer=body.get('payer_name','');paid_date=body.get('payment_date','')
            if not isinstance(payer,str) or not payer.strip() or len(payer)>100 or '\n' in payer or '\r' in payer or not date_valid(paid_date,False): raise ValueError('Enter the name on the paying account and the date you sent the transfer.')
            t.update(reported_payer=payer.strip(),reported_date=paid_date)
        t['reported_at']=time.time();db().execute('UPDATE purchases SET status="reported",terms=? WHERE id=?',(json.dumps(t),pid))
        audit('Couple reported a manual payment; not verified',w['id']);return jsonify(ok=True,status='reported')

    @app.post('/api/admin/payments/<pid>/confirm')
    @app.post('/api/admin/paypal/<pid>/confirm')
    @auth(admin=True)
    def paypal_confirm(pid):
        body=json_body();transaction=body.get('transaction_id','');amount=body.get('amount_pence')
        if body.get('verified') is not True: raise ValueError('Check the completed payment in your own PayPal account or bank account before confirming it.')
        if not isinstance(transaction,str) or not re.fullmatch(r'[A-Za-z0-9 ._/-]{5,100}',transaction.strip()): raise ValueError('Enter the transaction reference checked in your account.')
        transaction=transaction.strip().upper()
        if type(amount) is not int or body.get('currency')!='GBP': raise ValueError('Confirm the gross amount received and GBP currency.')
        db().execute('BEGIN IMMEDIATE');p=manual_purchase(pid);t=json.loads(p['terms'])
        if amount!=p['amount']: raise ValueError('The received amount must match this request. Check any underpayment or overpayment first.')
        table='bank_receipts' if t['provider']=='bank' else 'paypal_receipts'
        receipt=db().execute('SELECT * FROM '+table+' WHERE purchase_id=? OR transaction_id=?',(pid,transaction)).fetchone()
        if receipt:
            if p['status']=='paid' and receipt['purchase_id']==pid and receipt['transaction_id']==transaction: return jsonify(ok=True)
            raise ValueError('This transaction or request has already been recorded. No second sale was added.')
        if p['status'] not in ['pending','reported']: raise ValueError('This request cannot be confirmed in its current state.')
        if not t.get('accepted_at'): raise ValueError('The couple must accept the request terms before access is activated.')
        db().execute('INSERT INTO '+table+' VALUES(?,?,?,?)',(pid,transaction,g.user['id'],time.time()))
        db().execute('UPDATE purchases SET status="paid" WHERE id=?',(pid,));db().execute('UPDATE weddings SET access_kind="Paid",access_until=max(access_until,?) WHERE id=?',(t['access_until'],p['wedding_id']))
        audit(('Bank transfer' if t['provider']=='bank' else 'PayPal')+' payment manually verified; access granted',p['wedding_id']);return jsonify(ok=True)

    @app.post('/api/admin/payments/<pid>/close')
    @app.post('/api/admin/paypal/<pid>/close')
    @auth(admin=True)
    def paypal_close_unpaid(pid):
        if json_body().get('verified') is not True: raise ValueError('Check that no payment is completed or pending in your account before closing the request.')
        db().execute('BEGIN IMMEDIATE');p=manual_purchase(pid)
        if p['status']=='cancelled': return jsonify(ok=True)
        if p['status'] not in ['pending','reported']: raise ValueError('A verified payment cannot be closed as unpaid.')
        db().execute('UPDATE purchases SET status="cancelled" WHERE id=?',(pid,));audit('Unpaid manual request closed after administrator check',p['wedding_id']);return jsonify(ok=True)

    @app.post('/api/admin/payments/<pid>/refund-record')
    @app.post('/api/admin/paypal/<pid>/refund-record')
    @auth(admin=True)
    def paypal_refund_record(pid):
        if json_body().get('verified') is not True: raise ValueError('Complete the refund through the original payment method first, then confirm it here.')
        db().execute('BEGIN IMMEDIATE');p=manual_purchase(pid)
        if p['status']=='refunded': return jsonify(ok=True)
        if p['status']!='paid': raise ValueError('Only a verified payment can be marked refunded.')
        db().execute('UPDATE purchases SET status="refunded" WHERE id=?',(pid,));audit('Completed manual refund recorded; account access requires review',p['wedding_id'])
        return jsonify(ok=True,message='Refund recorded. Review this couple’s access separately; it was not changed automatically.')

    @app.post('/api/checkout')
    @auth()
    def checkout():
        w=wedding();settings=config(db());key=os.getenv('STRIPE_SECRET_KEY')
        if w['access_kind'] in ['Paid','Complimentary','Manual extension'] and w['access_until']>=date.today().isoformat():
            raise ValueError('You already have full access. No new payment is needed.')
        if settings['payment_provider']!='stripe': raise ValueError('Use the manual payment page for this planner.')
        if paypal_pending(w['id']): raise ValueError('Your earlier manual payment request needs checking before a different checkout can be started.')
        if not settings['checkout_enabled'] or not key: raise ValueError('Checkout is not open. Contact Ivory Digital for access.')
        rate('checkout-'+w['id'],12,3600,per_ip=False)
        db().execute('BEGIN IMMEDIATE')
        pending=db().execute('SELECT * FROM purchases WHERE wedding_id=? AND status="pending" ORDER BY created DESC LIMIT 1',(w['id'],)).fetchone()
        if pending and pending['checkout_id']:
            db().commit()
            req=urllib.request.Request('https://api.stripe.com/v1/checkout/sessions/'+urllib.parse.quote(pending['checkout_id'],safe=''),headers={'Authorization':'Bearer '+key})
            try:
                with urllib.request.urlopen(req,timeout=15) as response: existing=json.load(response)
                if existing.get('status')=='open' and existing.get('url'): return jsonify(url=existing['url'],terms=json.loads(pending['terms']))
                if existing.get('status')=='complete': raise ValueError('Your payment is being confirmed. Please wait before trying again.')
                if existing.get('status')!='expired': raise ValueError('Checkout status could not be confirmed. Please try again later.')
            except ValueError: raise
            except Exception: raise ValueError('Your existing checkout could not be checked. No second checkout was created.')
            db().execute('BEGIN IMMEDIATE')
            db().execute('UPDATE purchases SET status="expired" WHERE id=? AND status="pending"',(pending['id'],))
            pending=db().execute('SELECT * FROM purchases WHERE wedding_id=? AND status="pending" ORDER BY created DESC LIMIT 1',(w['id'],)).fetchone()
            if pending and pending['checkout_id']:
                db().commit();raise ValueError('Another checkout is already being prepared. Please try again in a moment.')
        if pending:
            if pending['created']<time.time()-86400:
                db().commit();raise ValueError('An earlier checkout needs checking by Ivory Digital before another payment can be created.')
            pid=pending['id'];terms=json.loads(pending['terms'])
        else:
            pid=secrets.token_hex(16);terms={'price_pence':settings['price_pence'],'access_until':access_end(settings,json.loads(w['state'])['date']),'refund_terms':settings['refund_terms'],'checkout_email':g.user['email']}
            db().execute('INSERT INTO purchases(id,wedding_id,amount,terms,created) VALUES(?,?,?,?,?)',(pid,w['id'],settings['price_pence'],json.dumps(terms),time.time()))
        db().commit()
        values={'mode':'payment','success_url':app.config['APP_URL']+'/app?payment=returned','cancel_url':app.config['APP_URL']+'/app',
            'customer_email':terms.get('checkout_email',g.user['email']),'line_items[0][price_data][currency]':'gbp','line_items[0][price_data][unit_amount]':str(terms['price_pence']),
            'line_items[0][price_data][product_data][name]':'Ivory Wedding Planner — both partners','line_items[0][quantity]':'1','metadata[purchase_id]':pid}
        req=urllib.request.Request('https://api.stripe.com/v1/checkout/sessions',data=urllib.parse.urlencode(values).encode(),headers={'Authorization':'Bearer '+key,'Idempotency-Key':pid})
        try:
            with urllib.request.urlopen(req,timeout=20) as response: result=json.load(response)
        except Exception: raise ValueError('Checkout could not be started. Try again shortly; retries use the same purchase, not a new charge.')
        db().execute('UPDATE purchases SET checkout_id=? WHERE id=?',(result['id'],pid));return jsonify(url=result['url'],terms=terms)
    @app.post('/api/stripe/webhook')
    def webhook():
        key=os.getenv('STRIPE_WEBHOOK_SECRET','');header=request.headers.get('Stripe-Signature','');raw=request.get_data()
        pairs=urllib.parse.parse_qs(header.replace(',','&'));timestamp=pairs.get('t',[''])[0]
        try: valid_time=abs(time.time()-int(timestamp))<=300
        except ValueError: valid_time=False
        signature=hmac.new(key.encode(),timestamp.encode()+b'.'+raw,hashlib.sha256).hexdigest()
        if not key or not valid_time or not any(hmac.compare_digest(signature,v) for v in pairs.get('v1',[])): abort(400)
        event=json.loads(raw);eid=event.get('id')
        if not eid: abort(400)
        if db().execute('SELECT 1 FROM webhook_events WHERE id=?',(eid,)).fetchone(): return jsonify(ok=True)
        obj=event.get('data',{}).get('object',{})
        if event.get('type') in ['checkout.session.completed','checkout.session.async_payment_succeeded'] and obj.get('payment_status')=='paid':
            p=db().execute('SELECT * FROM purchases WHERE id=? AND checkout_id=?',(obj.get('metadata',{}).get('purchase_id'),obj.get('id'))).fetchone()
            if not p or p['amount']!=obj.get('amount_total') or obj.get('currency')!='gbp': abort(400)
            if p['status']!='paid':
                terms=json.loads(p['terms']);db().execute('UPDATE purchases SET status="paid" WHERE id=?',(p['id'],))
                db().execute('UPDATE weddings SET access_kind="Paid",access_until=max(access_until,?) WHERE id=?',(terms['access_until'],p['wedding_id']))
                audit('Stripe payment confirmed',p['wedding_id'])
        db().execute('INSERT INTO webhook_events VALUES(?,?)',(eid,time.time()));return jsonify(ok=True)
    from .wbm_timings import register_wbm_timings
    register_wbm_timings(app,db,auth,wedding,json_body,audit)
    hub_notify=register_hub(app,db,auth,wedding,json_body,audit,queue,token,token_row,rate,update_state)
    from .stationery import register_stationery
    register_stationery(app,db,auth,wedding,json_body,audit,rate)
    from .control_centre import register_control_centre
    register_control_centre(app, VERSION)
    return app




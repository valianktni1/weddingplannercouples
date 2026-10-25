"""Consent-based trial interest, deliberately separate from accounts and email campaigns."""
import csv
import io
import secrets
import time
from datetime import datetime, timezone
from flask import abort, redirect, render_template, request, send_file
from .core import config

CONSENT='Email me about opening an Ivory Digital Wedding Planner trial. This is not consent to general marketing.'
SCHEMA='''CREATE TABLE IF NOT EXISTS trial_interest(
 id TEXT PRIMARY KEY,email TEXT NOT NULL UNIQUE,name TEXT NOT NULL,source TEXT NOT NULL,
 consent TEXT NOT NULL,privacy TEXT NOT NULL,created REAL NOT NULL,contacted REAL);
'''

def register_trial_interest(app,db,auth,rate,audit,valid_email):
    def prune():db().execute('DELETE FROM trial_interest WHERE created<?',(time.time()-180*86400,))
    def screen(error=None,status=200):
        return render_template('trial_interest.html',settings=config(db()),consent=CONSENT,error=error,values=request.form),status
    @app.route('/trial-interest',methods=['GET','POST'])
    def interest():
        if request.method=='GET':return screen()
        rate('trial-interest',10,3600);prune()
        if request.form.get('website'):return redirect('/trial-interest/thanks',code=303)
        email=request.form.get('email','').strip().lower();name=request.form.get('name','').strip()
        if not valid_email(email) or len(email)>254 or len(name)>100:return screen('Enter a valid email and a name of up to 100 characters.',400)
        if request.form.get('consent')!='yes':return screen('Please tick the box so we know you want us to contact you about trials.',400)
        source=request.form.get('source','').strip()[:120]
        # Duplicate submissions reveal nothing and do not reset retention or create contacts/accounts.
        db().execute('INSERT OR IGNORE INTO trial_interest(id,email,name,source,consent,privacy,created) VALUES(?,?,?,?,?,?,?)',(secrets.token_hex(16),email,name,source,CONSENT,config(db())['privacy_text'],time.time()))
        return redirect('/trial-interest/thanks',code=303)
    @app.get('/trial-interest/thanks')
    def thanks():return render_template('message.html',title='Thank you for your interest',message='Your request has been recorded. Mark will contact you about trial availability. No account has been created and no payment has been taken. You can close this page.')
    @app.route('/ivoryadmin/interest',methods=['GET','POST'])
    @auth(admin=True)
    def admin_interest():
        prune()
        if request.method=='POST':
            oid=request.form.get('id','');action=request.form.get('action','')
            if not db().execute('SELECT 1 FROM trial_interest WHERE id=?',(oid,)).fetchone():abort(404)
            if action=='delete':db().execute('DELETE FROM trial_interest WHERE id=?',(oid,))
            elif action=='contacted':db().execute('UPDATE trial_interest SET contacted=? WHERE id=?',(time.time(),oid))
            else:abort(400)
            audit('Trial interest '+action,oid)
            return redirect('/ivoryadmin/interest',code=303)
        rows=[dict(r) for r in db().execute('SELECT * FROM trial_interest ORDER BY contacted IS NOT NULL,created DESC')]
        for r in rows:
            for key in ('created','contacted'):r[key]=datetime.fromtimestamp(r[key],timezone.utc).strftime('%d %b %Y, %H:%M UTC') if r[key] else ''
        return render_template('trial_interest_admin.html',entries=rows)
    @app.get('/api/admin/interest.csv')
    @auth(admin=True)
    def export_trial_interest():
        prune();out=io.StringIO();writer=csv.writer(out);writer.writerow(['Name','Email (unverified)','Source','Requested UTC','Contacted UTC','Consent'])
        for r in db().execute('SELECT * FROM trial_interest ORDER BY created DESC'):
            cells=[r['name'],r['email'],r['source'],datetime.fromtimestamp(r['created'],timezone.utc).isoformat(),datetime.fromtimestamp(r['contacted'],timezone.utc).isoformat() if r['contacted'] else '',r['consent']]
            writer.writerow(["'"+v if v.lstrip().startswith(('=','+','-','@')) else v for v in cells])
        return send_file(io.BytesIO(out.getvalue().encode('utf-8-sig')),mimetype='text/csv',as_attachment=True,download_name='trial-interest.csv')

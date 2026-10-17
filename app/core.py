"""Storage, validation and cryptography shared by the web app and worker."""
import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import struct
import time
import fcntl
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from datetime import date, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from cryptography.fernet import Fernet

SCHEMA = '''
CREATE TABLE IF NOT EXISTS wbm_booking_invitations(booking_id TEXT PRIMARY KEY,wedding_id TEXT UNIQUE NOT NULL,user_id TEXT NOT NULL,mail_id TEXT NOT NULL,request_hash TEXT NOT NULL,created REAL NOT NULL,FOREIGN KEY(wedding_id) REFERENCES weddings(id),FOREIGN KEY(user_id) REFERENCES users(id));
CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY,email TEXT UNIQUE NOT NULL,password TEXT NOT NULL,role TEXT NOT NULL DEFAULT 'couple',verified INTEGER NOT NULL DEFAULT 0,totp TEXT,recovery TEXT NOT NULL DEFAULT '[]',totp_last INTEGER NOT NULL DEFAULT -1,created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS weddings(id TEXT PRIMARY KEY,state TEXT NOT NULL,revision INTEGER NOT NULL DEFAULT 0,access_kind TEXT NOT NULL DEFAULT 'Trial',access_until TEXT NOT NULL,suspended INTEGER NOT NULL DEFAULT 0,slug TEXT UNIQUE,site TEXT NOT NULL DEFAULT '{}',code_hash TEXT,created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS members(wedding_id TEXT NOT NULL,user_id TEXT NOT NULL UNIQUE,PRIMARY KEY(wedding_id,user_id),FOREIGN KEY(wedding_id) REFERENCES weddings(id) ON DELETE CASCADE,FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY,user_id TEXT,csrf TEXT NOT NULL,expires REAL NOT NULL,pending TEXT,setup_secret TEXT,FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS tokens(hash TEXT PRIMARY KEY,kind TEXT NOT NULL,user_id TEXT,wedding_id TEXT,email TEXT,payload TEXT NOT NULL DEFAULT '{}',expires REAL NOT NULL,used INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS mail(id TEXT PRIMARY KEY,to_address TEXT NOT NULL,subject TEXT NOT NULL,body TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'queued',attempts INTEGER NOT NULL DEFAULT 0,next_attempt REAL NOT NULL DEFAULT 0,dedupe TEXT UNIQUE,created REAL NOT NULL,last_error TEXT);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY AUTOINCREMENT,actor TEXT NOT NULL,action TEXT NOT NULL,wedding_id TEXT,created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS uploads(id TEXT PRIMARY KEY,wedding_id TEXT NOT NULL,name TEXT NOT NULL,path TEXT NOT NULL,mime TEXT NOT NULL,size INTEGER NOT NULL,kind TEXT NOT NULL,created REAL NOT NULL,FOREIGN KEY(wedding_id) REFERENCES weddings(id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS support(wedding_id TEXT PRIMARY KEY,expires REAL NOT NULL,reason TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS rate_limits(key TEXT PRIMARY KEY,count INTEGER NOT NULL,reset REAL NOT NULL);
CREATE TABLE IF NOT EXISTS purchases(id TEXT PRIMARY KEY,wedding_id TEXT NOT NULL,amount INTEGER NOT NULL,status TEXT NOT NULL DEFAULT 'pending',checkout_id TEXT UNIQUE,terms TEXT NOT NULL,created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS webhook_events(id TEXT PRIMARY KEY,created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS bank_receipts(purchase_id TEXT PRIMARY KEY,transaction_id TEXT UNIQUE NOT NULL,confirmed_by TEXT NOT NULL,confirmed_at REAL NOT NULL,FOREIGN KEY(purchase_id) REFERENCES purchases(id));
CREATE TABLE IF NOT EXISTS paypal_receipts(purchase_id TEXT PRIMARY KEY,transaction_id TEXT UNIQUE NOT NULL,confirmed_by TEXT NOT NULL,confirmed_at REAL NOT NULL,FOREIGN KEY(purchase_id) REFERENCES purchases(id));
CREATE TABLE IF NOT EXISTS policy_acceptances(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id TEXT NOT NULL,wedding_id TEXT NOT NULL,terms TEXT NOT NULL,privacy TEXT NOT NULL,accepted REAL NOT NULL);
CREATE TABLE IF NOT EXISTS website_slugs(slug TEXT PRIMARY KEY,wedding_id TEXT NOT NULL,FOREIGN KEY(wedding_id) REFERENCES weddings(id) ON DELETE CASCADE);
'''

DEFAULT_SETTINGS = {'price_pence': None, 'trial_days': 14, 'days_after_wedding': 90,
    'max_planning_days': 1095, 'access_rule': 'wedding', 'checkout_enabled': False,
    'sender': '', 'reply_to': '', 'timezone': 'Europe/London', 'reminder_time': '09:00',
    'backup_time': '02:00', 'backup_retention_days': 14, 'refund_terms': '',
    'privacy_text': '', 'terms_text': '', 'signups_enabled': False,
    'smtp_source': 'environment', 'smtp_host': '', 'smtp_port': 587,
    'smtp_security': 'starttls', 'smtp_user': '', 'smtp_password_encrypted': '',
    'payment_provider': 'paypalme', 'paypal_me_url': 'https://paypal.me/weddingsbymark',
    'bank_name': '', 'bank_account_name': '', 'bank_sort_code': '',
    'bank_account_number': '', 'bank_instructions': ''}

def connect(path):
    db = sqlite3.connect(path, timeout=20)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    db.execute('PRAGMA busy_timeout=20000')
    return db

def initialise(data_dir):
    root = Path(data_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / 'files').mkdir(exist_ok=True)
    # Gunicorn workers and the scheduler can start together. Publish the secret
    # only after the complete value has been written; never rotate an existing key.
    with (root / 'initialise.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        secret_file = root / 'app-secret'
        if not secret_file.exists():
            temporary=root / ('secret-'+secrets.token_hex(8)+'.tmp')
            fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(fd,'w') as f:
                f.write(secrets.token_urlsafe(48));f.flush();os.fsync(f.fileno())
            temporary.replace(secret_file)
        secret=secret_file.read_text().strip()
        if len(secret)<32:
            raise RuntimeError('The existing app-secret is incomplete. Restore it from backup; it was not replaced.')
        db = connect(root / 'planner.sqlite3')
        db.execute('PRAGMA journal_mode=WAL')
        db.executescript(SCHEMA)
        from .day_hub import SCHEMA as HUB_SCHEMA
        db.executescript(HUB_SCHEMA)
        if 'html_body' not in {r['name'] for r in db.execute('PRAGMA table_info(mail)')}:
            db.execute("ALTER TABLE mail ADD COLUMN html_body TEXT NOT NULL DEFAULT ''")
        columns={r['name'] for r in db.execute('PRAGMA table_info(weddings)')}
        if 'site_revision' not in columns:
            db.execute('ALTER TABLE weddings ADD COLUMN site_revision INTEGER NOT NULL DEFAULT 0')
        db.execute('INSERT OR IGNORE INTO website_slugs SELECT slug,id FROM weddings WHERE slug IS NOT NULL')
        for key, value in DEFAULT_SETTINGS.items():
            if key=='payment_provider':
                opened=db.execute('SELECT value FROM settings WHERE key="checkout_enabled"').fetchone()
                if opened and json.loads(opened['value']) and os.getenv('STRIPE_SECRET_KEY'): value='stripe'
            db.execute('INSERT OR IGNORE INTO settings VALUES (?,?)', (key, json.dumps(value)))
        db.commit();db.close()
        return secret

def config(db):
    return {r['key']: json.loads(r['value']) for r in db.execute('SELECT * FROM settings')}

def digest(token):
    return hashlib.sha256(token.encode()).hexdigest()

def cipher(secret):
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest()))

def totp(secret, counter=None):
    counter = int(time.time() // 30) if counter is None else counter
    raw = base64.b32decode(secret + '=' * (-len(secret) % 8))
    h = hmac.new(raw, struct.pack('>Q', counter), hashlib.sha1).digest()
    pos = h[-1] & 15
    return str((struct.unpack('>I', h[pos:pos+4])[0] & 0x7fffffff) % 1000000).zfill(6)

def valid_totp(secret, code, last=-1):
    current = int(time.time() // 30)
    for counter in (current, current-1, current+1):
        if counter > last and hmac.compare_digest(totp(secret, counter), str(code).strip()):
            return counter
    return None

def empty_state():
    return {'version': 3, 'ready': False, 'demo': False, 'names': ['', ''], 'email': '',
        'date': '', 'budget': None, 'priorities': [], 'suppliers': [], 'payments': [],
        'tasks': [], 'guests': [], 'groups': [], 'events': [], 'notes': '',
        'noteScope': 'Couple only', 'invite': {'email': '', 'status': 'Not invited'},
        'reminders': {'weekly': False, 'payments': True}, 'stage': 'planning', 'theme': 'system', 'timezone': 'Europe/London',
        'day': {'ceremony': 780, 'ceremonyMinutes': 30, 'meal': 960, 'mealConfirmed': False,
            'groupsMinutes': 20, 'portraits': 20, 'confetti': 15, 'seating': 15,
            'firstDance': 1170, 'lightEnd': None, 'venue': '', 'receptionVenue': '',
            'receptionTravel': 0, 'mornings': [
                {'ready': 735, 'travel': 15, 'loading': 15, 'location': ''},
                {'ready': 735, 'travel': 15, 'loading': 15, 'location': ''}]}}

def date_valid(value, optional=True):
    if value == '' and optional:
        return True
    try:
        return date.fromisoformat(value).isoformat() == value
    except (ValueError, TypeError):
        return False

def number(value, low=0, high=10000000):
    return type(value) in (int, float) and low <= value <= high

def pounds_valid(value, low=0, high=10000000):
    if not number(value,low,high): return False
    try:
        pennies=Decimal(str(value))*100
        return pennies.is_finite() and pennies==pennies.to_integral_value()
    except InvalidOperation: return False

def validate_state(s):
    """Validate client edits before replacing a wedding; reject inconsistent finances."""
    if not isinstance(s, dict) or len(json.dumps(s)) > 1500000:
        raise ValueError('Wedding data is too large or invalid.')
    base = empty_state()
    if set(s) != set(base):
        raise ValueError('Wedding fields do not match this version. Reload the planner.')
    if not isinstance(s['names'], list) or len(s['names']) != 2 or any(not isinstance(n, str) or len(n)>60 for n in s['names']):
        raise ValueError('Check the partner names.')
    if not date_valid(s['date']) or s['budget'] is not None and not pounds_valid(s['budget'], 0.01):
        raise ValueError('Check the wedding date and budget.')
    for key in ['suppliers','payments','tasks','guests','groups','events']:
        if not isinstance(s[key], list) or len(s[key]) > (2000 if key=='guests' else 1000):
            raise ValueError('Too many entries.')
        ids=set()
        for item in s[key]:
            if not isinstance(item,dict) or not isinstance(item.get('id'),str) or not 1<=len(item['id'])<=100 or item['id'] in ids:
                raise ValueError('Entries need unique identifiers.')
            ids.add(item['id'])
            if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',item['id']): raise ValueError('Invalid entry identifier.')
            templates={
                'suppliers':{'id':'','name':'','category':'','total':None,'booked':False,'contact':'','finish':None},
                'payments':{'id':'','supplier':'','title':'','amount':0,'paid':0,'due':'','paidDate':''},
                'tasks':{'id':'','title':'','owner':'Together','due':'','done':False},
                'guests':{'id':'','name':'','household':'','attendance':'Day','rsvp':'Waiting','meal':'','diet':'','access':'','table':''},
                'groups':{'id':'','title':'','minutes':2},
                'events':{'id':'','title':'','date':'','kind':'Appointment','done':False}}
            required=templates[key]
            if set(item)!=set(required): raise ValueError('An entry has missing or unknown fields.')
            for field,default in required.items():
                if isinstance(default,str) and not isinstance(item[field],str): raise ValueError('Entry text must be plain text.')
                if type(default) is bool and type(item[field]) is not bool: raise ValueError('Invalid entry checkbox.')
            for v in item.values():
                if isinstance(v, str) and len(v)>2000:
                    raise ValueError('An entry is too long.')
    suppliers={x['id']:x for x in s['suppliers']}
    for x in suppliers.values():
        if not isinstance(x.get('name'),str) or not x['name'].strip() or type(x.get('booked')) is not bool:
            raise ValueError('Check supplier names and booking status.')
        if x.get('total') is not None and not pounds_valid(x['total']):
            raise ValueError('Supplier prices must be positive amounts.')
        if x.get('finish') is not None and not number(x['finish'],0,1439):
            raise ValueError('Invalid coverage finish time.')
    sums={k:0 for k in suppliers}
    for p in s['payments']:
        supplier=suppliers.get(p.get('supplier'))
        if not supplier or not supplier['booked'] or supplier.get('total') is None:
            raise ValueError('Payments must belong to a confirmed booking with a price.')
        if not pounds_valid(p.get('amount'),0.01) or not pounds_valid(p.get('paid'),0,p['amount']):
            raise ValueError('Paid amounts cannot exceed an instalment.')
        if not date_valid(p.get('due')) or not date_valid(p.get('paidDate')) or p['paid']>0 and not p['paidDate']:
            raise ValueError('Check the payment dates.')
        sums[p['supplier']]+=round(p['amount']*100)
    if any(v>round(suppliers[k]['total']*100) for k,v in sums.items() if suppliers[k]['total'] is not None):
        raise ValueError('Instalments cannot exceed a supplier price.')
    for t in s['tasks']:
        if not t.get('title') or not date_valid(t.get('due')) or type(t.get('done')) is not bool:
            raise ValueError('Check task details.')
    for e in s['events']:
        if not e.get('title') or not date_valid(e.get('date'),False) or e.get('kind') not in ['Appointment','Deadline']:
            raise ValueError('Check calendar dates and event types.')
    for guest in s['guests']:
        if not guest.get('name') or guest.get('attendance') not in ['Day','Evening'] or guest.get('rsvp') not in ['Accepted','Waiting','Declined']:
            raise ValueError('Check individual guest details.')
    for group in s['groups']:
        if not group.get('title') or type(group.get('minutes')) is not int or not 1<=group['minutes']<=60:
            raise ValueError('Check photo group estimates.')
    d=s.get('day',{})
    if not isinstance(d,dict) or set(d)!=set(base['day']): raise ValueError('Invalid wedding-day fields.')
    if not isinstance(d['venue'],str) or not isinstance(d['receptionVenue'],str) or type(d['mealConfirmed']) is not bool:
        raise ValueError('Check venue details.')
    for key in ['ceremony','meal','firstDance']:
        if type(d.get(key)) is not int or not 0<=d[key]<=1439:
            raise ValueError('Check ceremony, meal and first-dance times.')
    if not d['ceremony']<d['meal']<=d['firstDance']:
        raise ValueError('Meal and first dance need to follow the ceremony.')
    for key in ['ceremonyMinutes','groupsMinutes','portraits','confetti','seating','receptionTravel']:
        if type(d.get(key)) is not int or not 0<=d[key]<=600:
            raise ValueError('Check the timing allowances.')
    if d.get('lightEnd') is not None and not number(d['lightEnd'],0,1439):
        raise ValueError('Check the outdoor-light cutoff.')
    if not isinstance(d.get('mornings'),list) or len(d['mornings'])!=2:
        raise ValueError('Both preparation plans are required.')
    for m in d['mornings']:
        if not isinstance(m,dict) or set(m)!=set(base['day']['mornings'][0]) or not isinstance(m.get('location'),str):
            raise ValueError('Check preparation locations.')
        if type(m.get('ready')) is not int or not 0<=m['ready']<=1439 or not number(m.get('travel'),0,600) or not number(m.get('loading'),0,120):
            raise ValueError('Check preparation and travel times.')
    if not isinstance(s['notes'],str) or s['stage'] not in ['planning','finished'] or s['noteScope'] not in ['Couple only','Photographer handover'] or len(s['notes'])>2000:
        raise ValueError('Check note visibility and wedding status.')
    if s['theme'] not in ['light','dark','system'] or type(s['ready']) is not bool:
        raise ValueError('Invalid preferences.')
    try: ZoneInfo(s['timezone'])
    except (ZoneInfoNotFoundError,ValueError,TypeError): raise ValueError('Use a valid wedding timezone.')
    if not isinstance(s['reminders'],dict) or any(type(s['reminders'].get(k)) is not bool for k in ['weekly','payments']):
        raise ValueError('Check reminder preferences.')
    if not isinstance(s['priorities'],list) or len(s['priorities'])>20 or any(not isinstance(x,str) or len(x)>160 for x in s['priorities']):
        raise ValueError('Check your planning priorities.')
    if not isinstance(s['email'],str) or len(s['email'])>160 or type(s['demo']) is not bool or not isinstance(s['invite'],dict):
        raise ValueError('Invalid account fields.')
    if d['ceremonyMinutes']<1: raise ValueError('Ceremony duration must be at least one minute.')
    return s

def access_end(settings, wedding_date='', purchased=None):
    start=purchased or date.today()
    if settings['access_rule']=='fixed':
        return (start+timedelta(days=365)).isoformat()
    max_date=start+timedelta(days=int(settings['max_planning_days']))
    if wedding_date and date_valid(wedding_date,False):
        wedding=date.fromisoformat(wedding_date)
        if wedding<=max_date:
            return (max(wedding,start)+timedelta(days=int(settings['days_after_wedding']))).isoformat()
    return (start+timedelta(days=365)).isoformat()


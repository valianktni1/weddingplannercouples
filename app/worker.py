"""One scheduled worker for email, reminders and consistent backups."""
import json
import os
import shutil
import tarfile
import tempfile
import time
import secrets
import urllib.parse
from pathlib import Path
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo
from .core import connect, initialise, config, digest
from .mail_service import smtp_ready, send_email, delivery_error

DATA=Path(os.getenv('DATA_DIR','/data'));BACKUPS=Path(os.getenv('BACKUP_DIR','/backups'))

def backup(data_dir=DATA,backup_dir=BACKUPS):
    backup_dir=Path(backup_dir);backup_dir.mkdir(parents=True,exist_ok=True)
    data_dir=Path(data_dir);lock=connect(data_dir/'planner.sqlite3')
    try:
        # Uploaded files are immutable: hard-link a consistent generation on the
        # same data volume, then release the DB write lock before compression.
        with tempfile.TemporaryDirectory(dir=data_dir,prefix='.backup-stage-') as temp:
            temp=Path(temp);(temp/'files').mkdir()
            lock.execute('BEGIN IMMEDIATE')
            snap=connect(temp/'planner.sqlite3');source=connect(data_dir/'planner.sqlite3');source.backup(snap);source.close()
            references=snap.execute('SELECT wedding_id,path FROM uploads').fetchall();snap.close()
            shutil.copy2(data_dir/'app-secret',temp/'app-secret')
            for row in references:
                original=data_dir/'files'/row['wedding_id']/Path(row['path']).name
                destination=temp/'files'/row['wedding_id']/original.name
                destination.parent.mkdir(parents=True,exist_ok=True)
                try: os.link(original,destination)
                except OSError: shutil.copy2(original,destination)
            lock.rollback()
            stamp=datetime.now().strftime('%Y%m%d-%H%M%S-%f');target=backup_dir/('planner-'+stamp+'.tar.gz')
            pending=backup_dir/('.'+target.name+'.partial')
            try:
                with tarfile.open(pending,'w:gz') as out:
                    for item in temp.iterdir(): out.add(item,arcname=item.name)
                pending.chmod(0o600)
                with tarfile.open(pending,'r:gz') as check:
                    for item in check.getmembers():
                        if item.isfile():
                            stream=check.extractfile(item)
                            while stream.read(1024*1024): pass
                pending.replace(target)
            finally:
                pending.unlink(missing_ok=True)
        return target
    finally:
        lock.rollback();lock.close()

def enqueue(db,to,subject,body,dedupe):
    import secrets
    db.execute('INSERT OR IGNORE INTO mail(id,to_address,subject,body,dedupe,created) VALUES(?,?,?,?,?,?)',
        (secrets.token_hex(12),to,subject,body,dedupe,time.time()))

def schedule(db,settings,now):
    local=now.astimezone(ZoneInfo(settings['timezone']))
    today=local.date()
    for w in db.execute('SELECT * FROM weddings WHERE suspended=0 AND access_until>=?',((today-timedelta(days=1)).isoformat(),)):
        state=json.loads(w['state'])
        if state['stage']=='finished': continue
        wedding_local=now.astimezone(ZoneInfo(state.get('timezone',settings['timezone'])))
        if wedding_local.strftime('%H:%M')<settings['reminder_time']: continue
        today=wedding_local.date()
        if w['access_until']<today.isoformat(): continue
        emails=[r['email'] for r in db.execute('SELECT email FROM users JOIN members m ON m.user_id=users.id WHERE m.wedding_id=? AND users.verified=1',(w['id'],))]
        suppliers={s['id']:s for s in state['suppliers']}
        if state['reminders']['payments']:
            for p in state['payments']:
                if not p['due'] or p['paid']>=p['amount']: continue
                days=(date.fromisoformat(p['due'])-today).days
                if days not in [1,7]: continue
                remaining=round(p['amount']-p['paid'],2);name=suppliers[p['supplier']]['name']
                for email in emails:
                    enqueue(db,email,'Upcoming wedding payment',f'Your {name} {p["title"]} has £{remaining:.2f} remaining, due {p["due"]}. Open your planner to check the agreed payment details. This reminder does not make a payment.',f'payment:{w["id"]}:{p["id"]}:{p["due"]}:{days}:{email}')
        if state['reminders']['weekly'] and today.weekday()==0:
            tasks=[t['title'] for t in state['tasks'] if not t['done']][:3]
            for email in emails:
                enqueue(db,email,'Your wedding planning week','Your next jobs:\n'+'\n'.join(tasks or ['Nothing outstanding on your checklist.']),f'weekly:{w["id"]}:{today.isoformat()}:{email}')

def current_mail(db,row,settings,now):
    """Recheck queued work after edits, cancellations or a delayed mail service."""
    path=urllib.parse.urlsplit(row['body'].strip()).path
    for prefix,kind in [('/verify/','verify'),('/reset/','reset'),('/join/','partner')]:
        if path.startswith(prefix):
            t=db.execute('SELECT * FROM tokens WHERE hash=? AND kind=? AND used=0 AND expires>?',(digest(path[len(prefix):]),kind,now.timestamp())).fetchone()
            if not t: return None
    key=row['dedupe'] or ''
    if key.startswith('welcome:'):
        t=db.execute('SELECT t.* FROM tokens t JOIN users u ON u.id=t.user_id JOIN weddings w ON w.id=t.wedding_id WHERE t.hash=? AND t.kind="welcome" AND t.used=0 AND t.expires>? AND u.verified=0 AND w.suspended=0',(key.split(':',1)[1],now.timestamp())).fetchone()
        return row['body'] if t else None
    if not key.startswith(('payment:','weekly:')): return row['body']
    parts=key.split(':',5);wid=parts[1]
    w=db.execute('SELECT * FROM weddings WHERE id=?',(wid,)).fetchone()
    if not w or w['suspended']: return None
    state=json.loads(w['state']);local=now.astimezone(ZoneInfo(state.get('timezone',settings['timezone']))).date()
    if state['stage']=='finished' or w['access_until']<local.isoformat(): return None
    if key.startswith('weekly:'):
        if not state['reminders']['weekly'] or parts[2]!=local.isoformat(): return None
        tasks=[t['title'] for t in state['tasks'] if not t['done']][:3]
        return 'Your next jobs:\n'+'\n'.join(tasks or ['Nothing outstanding on your checklist.'])
    if not state['reminders']['payments'] or len(parts)!=6: return None
    payment=next((p for p in state['payments'] if p['id']==parts[2]),None)
    if not payment or payment['paid']>=payment['amount'] or payment['due']!=parts[3] or (date.fromisoformat(payment['due'])-local).days!=int(parts[4]): return None
    supplier=next((s for s in state['suppliers'] if s['id']==payment['supplier']),None)
    if not supplier: return None
    remaining=round(payment['amount']-payment['paid'],2)
    return f'Your {supplier["name"]} {payment["title"]} has £{remaining:.2f} remaining, due {payment["due"]}. Open your planner to check the agreed payment details. This reminder does not make a payment.'

def deliver(db,settings,now=None,secret=None):
    now=now or datetime.now(ZoneInfo('UTC'))
    if not smtp_ready(settings): return
    secret=secret or (DATA/'app-secret').read_text().strip()
    for row in db.execute('SELECT * FROM mail WHERE status IN ("queued","retry") AND next_attempt<=? ORDER BY created LIMIT 20',(time.time(),)).fetchall():
        body=current_mail(db,row,settings,now)
        if body is None:
            db.execute('UPDATE mail SET status="cancelled",last_error=NULL WHERE id=?',(row['id'],));db.commit();continue
        try:
            send_email(settings,secret,row['to_address'],row['subject'],body,row['id'],**({'html_body':row['html_body']} if row['html_body'] else {}))
            db.execute('UPDATE mail SET status="sent",attempts=attempts+1,last_error=NULL WHERE id=?',(row['id'],))
        except Exception as exc:
            attempts=row['attempts']+1
            db.execute('UPDATE mail SET status=?,attempts=?,next_attempt=?,last_error=? WHERE id=?',
                ('failed' if attempts>=5 else 'retry',attempts,time.time()+min(3600,60*2**attempts),delivery_error(exc),row['id']))
        db.commit()

def prune_tokens(db,now):
    # Retain an unaccepted welcome record so an expired invitation can be resent
    # even after normal token housekeeping. It remains unusable after expiry.
    db.execute('DELETE FROM tokens WHERE expires<? AND NOT(kind="welcome" AND used=0)',(now-86400*7,))

def run():
    secret=initialise(DATA);BACKUPS.mkdir(parents=True,exist_ok=True)
    while True:
        db=None
        try:
            db=connect(DATA/'planner.sqlite3');settings=config(db);now=datetime.now(ZoneInfo('UTC'))
            db.execute('DELETE FROM sessions WHERE expires<?',(time.time(),))
            db.execute('DELETE FROM rate_limits WHERE reset<?',(time.time(),))
            prune_tokens(db,time.time())
            schedule(db,settings,now);db.commit();deliver(db,settings,secret=secret)
            db.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',('worker_heartbeat',json.dumps(time.time())));db.commit()
            local=now.astimezone(ZoneInfo(settings['timezone']));stamp=local.date().isoformat()
            last=db.execute('SELECT value FROM settings WHERE key="last_backup_day"').fetchone()
            if local.strftime('%H:%M')>=settings['backup_time'] and (not last or json.loads(last['value'])!=stamp):
                target=backup();db.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',('last_backup_day',json.dumps(stamp)))
                db.execute('INSERT INTO audit(actor,action,created) VALUES(?,?,?)',('worker','Backup completed: '+target.name,time.time()));db.commit()
                limit=time.time()-max(1,settings['backup_retention_days'])*86400
                files=sorted(BACKUPS.glob('planner-*.tar.gz'),key=lambda p:p.stat().st_mtime,reverse=True)
                for old in files[1:]:
                    if old.stat().st_mtime<limit: old.unlink()
        except Exception as exc:
            print('Worker needs attention:',type(exc).__name__,flush=True)
        finally:
            if db is not None: db.rollback();db.close()
        time.sleep(30)

if __name__=='__main__': run()


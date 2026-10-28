"""Explicit admin erasure, performed by the single writable backup worker.

Only planner-owned archives under BACKUP_DIR are in scope. External snapshots,
exports and previously delivered emails are outside this application's control.
"""
import json
import os
import re
import shutil
import tarfile
import tempfile
import time
import uuid
from pathlib import Path
from flask import abort, jsonify, request
from .core import connect, digest, file_lock

SCHEMA='''CREATE TABLE IF NOT EXISTS couple_deletions(
 id TEXT PRIMARY KEY,wedding_id TEXT UNIQUE,payload TEXT NOT NULL DEFAULT '{}',
 status TEXT NOT NULL DEFAULT 'queued',requested REAL NOT NULL,updated REAL NOT NULL,
 archives_done INTEGER NOT NULL DEFAULT 0,archives_total INTEGER NOT NULL DEFAULT 0,
 message TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS deleted_booking_ids(booking_hash TEXT PRIMARY KEY);'''
ACTIVE=('queued','running','failed')
LIMITATION='Only backups managed by this planner are cleaned. TrueNAS/ZFS snapshots, off-server copies, downloaded exports and previously sent emails are not removed.'


def tables(db):
    return {r['name']:{c['name'] for c in db.execute('PRAGMA table_info("'+r['name']+'")')}
            for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
            if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',r['name'])}


def pending(db):
    return db.execute("SELECT 1 FROM couple_deletions WHERE status!='completed' LIMIT 1").fetchone() is not None


def blocked(db,wid):
    return db.execute("SELECT 1 FROM couple_deletions WHERE wedding_id=? AND status!='completed'",(wid,)).fetchone() is not None


def manifest(db,wid,previous=None):
    known=tables(db);result={k:set((previous or {}).get(k,[])) for k in ('users','emails','bookings','shares','orders','mail','tokens')}
    def rows(table,column,where,args):
        if table in known:return [r[0] for r in db.execute('SELECT "'+column+'" FROM "'+table+'" WHERE '+where,args)]
        return []
    result['users'].update(rows('members','user_id','wedding_id=?',(wid,)))
    for uid in list(result['users']):
        user=db.execute('SELECT email,role FROM users WHERE id=?',(uid,)).fetchone()
        if user:
            if user['role']!='couple':raise ValueError('Administrator accounts cannot be deleted with a wedding.')
            result['emails'].add(user['email'])
    result['bookings'].update(rows('wbm_booking_invitations','booking_id','wedding_id=?',(wid,)))
    result['bookings'].update(rows('wbm_timing_links','booking_id','wedding_id=?',(wid,)))
    result['shares'].update(rows('hub_shares','id','wedding_id=?',(wid,)))
    result['orders'].update(rows('bespoke_orders','id','wedding_id=?',(wid,)))
    result['mail'].update(rows('guest_invitation_activity','mail_id','wedding_id=?',(wid,)))
    result['mail'].update(rows('wbm_booking_invitations','mail_id','wedding_id=?',(wid,)))
    # Keep token identities, not every invited partner's email: a pending
    # partner may own an unrelated wedding that must not be erased.
    if 'tokens' in known:
        result['tokens'].update(rows('tokens','hash','wedding_id=?',(wid,)))
        for uid in result['users']:
            result['tokens'].update(rows('tokens','hash','user_id=?',(uid,)))
    return {k:sorted(x for x in v if x) for k,v in result.items()}


def linked_mail(row,wid,info):
    key=row['dedupe'] or ''
    return (row['id'] in info['mail'] or key.startswith(('payment:'+wid+':','weekly:'+wid+':'))
                or any(key=='hub-invite:'+sid or key.startswith('hub-change:'+sid+':') for sid in info['shares'])
                or any(key.startswith(('bespoke-new-'+oid+'-','bespoke-action-'+oid+'-','bespoke-update-'+oid+'-')) for oid in info['orders'])
                or key in {'welcome:'+value for value in info['tokens']}
                or any(digest(value) in info['tokens'] for value in re.findall(r'/(?:verify|reset|join|welcome)/([A-Za-z0-9_-]+)',row['body']+' '+row['html_body'])))


def mail_blocked(db,row):
    for job in db.execute("SELECT wedding_id,payload FROM couple_deletions WHERE status!='completed'"):
        info=json.loads(job['payload'])
        if row['to_address'] in info.get('emails',[]) or linked_mail(row,job['wedding_id'],info):return True
    return False


def purge_rows(db,wid,info,archive=False):
    known=tables(db)
    # Remove linked non-owner messages (guest invitations and supplier shares),
    # plus account mail, before their linking records disappear.
    other_guest_mail={r[0] for r in db.execute('SELECT mail_id FROM guest_invitation_activity WHERE wedding_id!=?',(wid,))} if 'guest_invitation_activity' in known else set()
    for row in db.execute('SELECT id,to_address,dedupe,body,html_body FROM mail').fetchall():
        key=row['dedupe'] or ''
        linked=linked_mail(row,wid,info)
        other_share=key.startswith(('hub-invite:','hub-change:')) and not any(key=='hub-invite:'+sid or key.startswith('hub-change:'+sid+':') for sid in info['shares'])
        owner=row['to_address'] in info['emails'] and row['id'] not in other_guest_mail and not other_share
        if linked or owner:db.execute('DELETE FROM mail WHERE id=?',(row['id'],))
    for booking in info['bookings']:
        if 'deleted_booking_ids' in known:db.execute('INSERT OR IGNORE INTO deleted_booking_ids VALUES(?)',(digest(booking),))
    if 'hub_ack' in known:
        for sid in info['shares']:db.execute('DELETE FROM hub_ack WHERE share_id=?',(sid,))
    if 'purchases' in known:
        for table in ('bank_receipts','paypal_receipts'):
            if table in known:db.execute('DELETE FROM '+table+' WHERE purchase_id IN (SELECT id FROM purchases WHERE wedding_id=?)',(wid,))
    # Cascade declared children first; remaining legacy tables have explicit
    # wedding_id columns but no foreign key. Deleting the wedding is last.
    for table in ('wbm_booking_invitations','wbm_timing_links','bespoke_orders'):
        if table in known:db.execute('DELETE FROM '+table+' WHERE wedding_id=?',(wid,))
    for table,columns in known.items():
        if 'wedding_id' in columns and table not in ('couple_deletions',):
            db.execute('DELETE FROM "'+table+'" WHERE wedding_id=?',(wid,))
    for uid in info['users']:
        db.execute('DELETE FROM sessions WHERE user_id=? OR pending=?',(uid,uid))
        db.execute('DELETE FROM tokens WHERE user_id=?',(uid,))
        db.execute('DELETE FROM audit WHERE actor=?',(uid,))
        if 'policy_acceptances' in known:db.execute('DELETE FROM policy_acceptances WHERE user_id=?',(uid,))
        db.execute('DELETE FROM users WHERE id=? AND role="couple"',(uid,))
    for email in info['emails']:
        if 'trial_interest' in known:db.execute('DELETE FROM trial_interest WHERE email=?',(email,))
    db.execute('DELETE FROM weddings WHERE id=?',(wid,))
    if archive and 'couple_deletions' in known:
        db.execute('DELETE FROM couple_deletions WHERE wedding_id=?',(wid,))
    if db.execute('PRAGMA foreign_key_check').fetchone():raise ValueError('Deletion left an invalid database reference.')


def remove_files(root,wid):
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,128}',wid):raise ValueError('Invalid wedding storage identifier.')
    files=Path(root)/'files';target=files/wid
    if files.is_symlink() or target.is_symlink():raise ValueError('Wedding storage must not be a symbolic link.')
    if target.exists():shutil.rmtree(target)


def rewrite_archive(archive,wid,info,job_id):
    from scripts.test_restore import restore
    original=archive.stat()
    # Work beside the backup, never in the live data or the small container tmpfs.
    with tempfile.TemporaryDirectory(prefix='.erasure-'+job_id+'-',dir=archive.parent) as scratch:
        root=Path(scratch);source=root/'source';source.mkdir()
        restore(archive,source)  # strict path/link checks, integrity and file references
        db=connect(source/'planner.sqlite3')
        try:
            db.execute('PRAGMA secure_delete=ON');db.execute('BEGIN IMMEDIATE')
            old_info=manifest(db,wid,info);purge_rows(db,wid,old_info,archive=True);db.commit()
            db.execute('PRAGMA wal_checkpoint(TRUNCATE)');db.execute('VACUUM');db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        finally:db.close()
        remove_files(source,wid)
        candidate=root/'clean.tar.gz'
        with tarfile.open(candidate,'w:gz',dereference=True) as out:
            for name in ('planner.sqlite3','app-secret','files'):out.add(source/name,arcname=name)
        candidate.chmod(0o600)
        verify=root/'verify';verify.mkdir();restore(candidate,verify)
        checked=connect(verify/'planner.sqlite3')
        try:
            if checked.execute('SELECT 1 FROM weddings WHERE id=?',(wid,)).fetchone():raise ValueError('Wedding remained in backup.')
        finally:checked.close()
        with candidate.open('rb') as f:os.fsync(f.fileno())
        if archive.is_symlink() or archive.stat().st_ino!=original.st_ino:raise ValueError('Backup changed during cleanup.')
        os.utime(candidate,(original.st_atime,original.st_mtime))
        os.replace(candidate,archive)


def jobs(db):
    active=db.execute("SELECT * FROM couple_deletions WHERE status!='completed' ORDER BY requested DESC").fetchall()
    completed=db.execute("SELECT * FROM couple_deletions WHERE status='completed' ORDER BY requested DESC LIMIT 10").fetchall()
    result=[]
    for row in [*active,*completed]:
        item={key:row[key] for key in ('id','status','requested','updated','archives_done','archives_total','message')}
        item['label']=', '.join(json.loads(row['payload']).get('emails',[])) if row['status']!='completed' else 'Couple deleted'
        result.append(item)
    return result


def process_deletion(db,data_dir,backup_dir):
    try:return _process_deletion(db,data_dir,backup_dir)
    except Exception as exc:
        db.rollback();print('Couple deletion could not start:',type(exc).__name__,flush=True)
        db.execute("UPDATE couple_deletions SET status='failed',updated=?,message=? WHERE id=(SELECT id FROM couple_deletions WHERE status IN ('queued','running') ORDER BY requested LIMIT 1)",
                   (time.time(),'Cleanup could not start. Check worker logs and data/backup directory permissions, then retry. Backup creation and downloads remain paused.'))
        db.commit();return True


def _process_deletion(db,data_dir,backup_dir):
    row=db.execute("SELECT * FROM couple_deletions WHERE status IN ('queued','running') ORDER BY requested LIMIT 1").fetchone()
    if not row:return False
    root=Path(data_dir);backups=Path(backup_dir);backups.mkdir(parents=True,exist_ok=True)
    with (root/'backup-operation.lock').open('a+') as lock,file_lock(lock):
        job_id=row['id'];wid=row['wedding_id'];info=json.loads(row['payload'])
        active_archive=None
        try:
            db.execute('BEGIN IMMEDIATE');info=manifest(db,wid,info)
            db.execute('UPDATE couple_deletions SET status="running",payload=?,updated=?,message=? WHERE id=?',
                       (json.dumps(info),time.time(),'Removing the couple and cleaning managed backup archives.',job_id))
            purge_rows(db,wid,info);db.commit();remove_files(root,wid)
            # Remove interrupted scratch copies belonging to this exact job.
            for old in backups.glob('.erasure-'+job_id+'-*'):
                if old.is_symlink():raise ValueError('Unexpected backup scratch link.')
                if old.is_dir():shutil.rmtree(old)
            from .admin_backups import NAME
            archives=[]
            for archive in backups.glob('planner-*.tar.gz'):
                if NAME.fullmatch(archive.name):
                    if archive.is_symlink() or not archive.is_file():raise ValueError('Unexpected backup archive type.')
                    archives.append(archive)
            db.execute('UPDATE couple_deletions SET archives_done=0,archives_total=? WHERE id=?',(len(archives),job_id));db.commit()
            for count,archive in enumerate(sorted(archives),1):
                active_archive=archive.name
                db.execute('UPDATE couple_deletions SET message=?,updated=? WHERE id=?',('Cleaning '+archive.name,time.time(),job_id));db.commit()
                rewrite_archive(archive,wid,info,job_id)
                db.execute('UPDATE couple_deletions SET archives_done=?,updated=? WHERE id=?',(count,time.time(),job_id))
                db.execute('INSERT OR REPLACE INTO settings VALUES("worker_heartbeat",?)',(json.dumps(time.time()),));db.commit()
            for partial in backups.glob('.planner-*.tar.gz.partial'):
                if NAME.fullmatch(partial.name[1:-8]) and not partial.is_symlink():partial.unlink()
            # Clear identifiers used for retry only once every managed archive is clean.
            db.execute('UPDATE couple_deletions SET wedding_id=NULL,payload="{}",status="completed",updated=?,message=? WHERE id=?',
                       (time.time(),'Couple deleted. All managed planner backup archives cleaned. External snapshots, downloads and sent emails remain outside the app’s control.',job_id))
            db.execute('INSERT INTO audit(actor,action,created) VALUES("worker","Couple permanently deleted; managed backups cleaned",?)',(time.time(),));db.commit()
            db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        except Exception as exc:
            db.rollback();print('Couple deletion needs attention:',type(exc).__name__,flush=True)
            db.execute('UPDATE couple_deletions SET status="failed",updated=?,message=? WHERE id=?',
                       (time.time(),'Cleanup is incomplete. The account is blocked; backup downloads and creation stay paused. Check worker logs, free space and backup permissions, then retry. Existing archives are replaced only after a cleaned copy passes recovery checks.'+(' Archive needing attention: '+active_archive if active_archive else ''),job_id));db.commit()
    return True


def register_couple_deletion(app,db,auth,audit,rate):
    @app.get('/api/admin/deletions')
    @auth(admin=True)
    def deletion_status():return jsonify(jobs=jobs(db()),blocked=pending(db()),limitation=LIMITATION)

    @app.get('/api/admin/couples/<wid>/deletion-preview')
    @auth(admin=True)
    def deletion_preview(wid):
        w=db().execute('SELECT * FROM weddings WHERE id=?',(wid,)).fetchone()
        if not w:abort(404)
        state=json.loads(w['state']);info=manifest(db(),wid)
        return jsonify(names=' & '.join(state['names']) or 'Setup incomplete',emails=info['emails'],
                       accounts=len(info['users']),uploads=db().execute('SELECT count(*) FROM uploads WHERE wedding_id=?',(wid,)).fetchone()[0],
                       purchases=db().execute('SELECT count(*) FROM purchases WHERE wedding_id=?',(wid,)).fetchone()[0],
                       orders=db().execute('SELECT count(*) FROM bespoke_orders WHERE wedding_id=?',(wid,)).fetchone()[0],
                       confirmation='DELETE '+wid,limitation=LIMITATION)

    @app.post('/api/admin/couples/<wid>/delete')
    @auth(admin=True)
    def request_deletion(wid):
        body=request.get_json(silent=True)
        if not isinstance(body,dict):raise ValueError('Supply the deletion confirmation.')
        if body.get('confirmation')!='DELETE '+wid or body.get('confirm_backups') is not True:
            raise ValueError('Type the deletion confirmation and confirm permanent removal from managed backups.')
        rate('couple-deletion',20,3600,per_ip=False);db().execute('BEGIN IMMEDIATE')
        existing=db().execute('SELECT id FROM couple_deletions WHERE wedding_id=?',(wid,)).fetchone()
        if existing:return jsonify(job_id=existing['id']),202
        w=db().execute('SELECT id FROM weddings WHERE id=?',(wid,)).fetchone()
        if not w:abort(404)
        info=manifest(db(),wid);job_id=uuid.uuid4().hex;now=time.time()
        db().execute('UPDATE weddings SET suspended=1 WHERE id=?',(wid,))
        db().execute('UPDATE tokens SET used=1 WHERE wedding_id=?',(wid,))
        for uid in info['users']:
            db().execute('DELETE FROM sessions WHERE user_id=? OR pending=?',(uid,uid))
            db().execute('UPDATE tokens SET used=1 WHERE user_id=?',(uid,))
        db().execute('INSERT INTO couple_deletions(id,wedding_id,payload,requested,updated,message) VALUES(?,?,?,?,?,?)',
                     (job_id,wid,json.dumps(info),now,now,'Queued for the worker. Couple access is blocked immediately.'))
        audit('Permanent couple deletion requested',wid)
        return jsonify(job_id=job_id),202

    @app.post('/api/admin/deletions/<job_id>/retry')
    @auth(admin=True)
    def retry_deletion(job_id):
        rate('couple-deletion-retry',20,3600,per_ip=False);db().execute('BEGIN IMMEDIATE')
        row=db().execute('SELECT status FROM couple_deletions WHERE id=?',(job_id,)).fetchone()
        if not row:abort(404)
        if row['status']=='failed':db().execute('UPDATE couple_deletions SET status="queued",updated=?,message="Cleanup queued for retry." WHERE id=?',(time.time(),job_id))
        return jsonify(ok=True)

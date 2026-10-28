"""Admin-only downloads; archive creation stays in the writable backup worker."""
import json
import os
import re
import stat
import time
import uuid
from pathlib import Path
from flask import abort, jsonify, send_file

KEY='manual_backup_job'
NAME=re.compile(r'planner-[0-9-]{8,64}\.tar\.gz\Z')


def read_job(db):
    row=db.execute('SELECT value FROM settings WHERE key=?',(KEY,)).fetchone()
    job=json.loads(row['value']) if row else {}
    return job


def archives(directory):
    root=Path(directory)
    entries=[]
    for p in root.glob('planner-*.tar.gz'):
        try:
            if NAME.fullmatch(p.name) and not p.is_symlink() and p.is_file():
                info=p.stat();entries.append({'name':p.name,'bytes':info.st_size,'created':info.st_mtime})
        except FileNotFoundError:
            pass  # retention may remove an old archive during the listing
    return sorted(entries,key=lambda item:item['created'],reverse=True)[:50]


def recover_interrupted_backup(db):
    # Called once on startup by the single backup worker, including after a restore.
    job=read_job(db)
    if job.get('status') in ('running','interrupted'):
        job.update(status='interrupted',message='The previous backup worker stopped. Existing archives are safe; you can create a new backup.')
        db.execute('UPDATE settings SET value=? WHERE key=?',(json.dumps(job),KEY));db.commit()


def process_requested_backup(db,data_dir,backup_dir):
    """One worker claims a queued request; failures never remove older archives."""
    from .worker import backup
    from .couple_deletion import pending
    if pending(db):return False
    db.execute('BEGIN IMMEDIATE')
    job=read_job(db)
    if job.get('status')!='queued':
        db.rollback();return False
    job.update(status='running',started_at=time.time(),message='Creating a consistent copy of the database and uploaded files. Keep using the planner; this screen will update automatically.')
    db.execute('UPDATE settings SET value=? WHERE key=?',(json.dumps(job),KEY));db.commit()
    try:
        target=backup(data_dir,backup_dir)
        job.update(status='completed',filename=target.name,completed_at=time.time(),message='Backup completed. Download the archive below.')
        action='Manual backup completed: '+target.name
    except Exception as exc:
        print('Manual backup failed:',type(exc).__name__,flush=True)
        job.update(status='failed',completed_at=time.time(),message='Backup failed. Check worker logs, free space and backup-folder permissions; earlier backups are unchanged.')
        action='Manual backup failed; check worker logs and storage'
    db.execute('INSERT INTO audit(actor,action,created) VALUES(?,?,?)',('worker',action,time.time()))
    db.execute('UPDATE settings SET value=? WHERE key=?',(json.dumps(job),KEY));db.commit()
    return True


def register_admin_backups(app,db,auth,audit,rate):
    @app.get('/api/admin/backups')
    @auth(admin=True)
    def backup_status():
        from .couple_deletion import pending
        row=db().execute('SELECT value FROM settings WHERE key="worker_heartbeat"').fetchone()
        healthy=bool(row and time.time()-json.loads(row['value'])<180)
        cleaning=pending(db())
        return jsonify(archives=[] if cleaning else archives(app.config['BACKUP_DIR']),job=read_job(db()),worker_running=healthy,deletion_cleanup=cleaning)

    @app.post('/api/admin/backups')
    @auth(admin=True)
    def request_backup():
        from .couple_deletion import pending
        if pending(db()):abort(409,description='Finish permanent couple deletion and backup cleanup before creating another backup.')
        rate('admin-backup',10,3600,per_ip=False)
        db().execute('BEGIN IMMEDIATE')
        job=read_job(db())
        if job.get('status') not in ('queued','running'):
            job={'id':str(uuid.uuid4()),'status':'queued','requested_at':time.time(),
                 'message':'Queued for the backup worker. This usually starts within 30 seconds.'}
            db().execute('INSERT OR REPLACE INTO settings VALUES(?,?)',(KEY,json.dumps(job)))
            audit('Manual complete-data backup requested')
        return jsonify(job=job),202

    @app.get('/api/admin/backups/<name>')
    @auth(admin=True)
    def download_backup(name):
        from .couple_deletion import pending
        if pending(db()):abort(409,description='Backup downloads are paused until permanent couple deletion and archive cleanup complete.')
        if not NAME.fullmatch(name):abort(404)
        path=Path(app.config['BACKUP_DIR'])/name
        try:
            fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
        except OSError:
            abort(404)
        file=os.fdopen(fd,'rb')
        if not stat.S_ISREG(os.fstat(file.fileno()).st_mode):file.close();abort(404)
        try:
            response=send_file(file,as_attachment=True,download_name=name,mimetype='application/gzip',max_age=0,conditional=False)
            response.content_length=os.fstat(file.fileno()).st_size
            response.call_on_close(file.close)
            audit('Complete-data backup download started: '+name)
            return response
        except Exception:
            file.close();raise

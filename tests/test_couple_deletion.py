import json
import time
import uuid
from pathlib import Path
import pytest
from app.core import connect,config,digest
from app.couple_deletion import process_deletion,pending
from app.worker import backup,deliver
from scripts.restore_data import restore_empty
from test_app import app,database,login,headers
from test_booking_connection import setup as booking_setup,body as booking_body


def admin(app):return login(app,'mark@example.com',admin=True)
def request_delete(c,wid='wu1',**changes):
    body={'confirmation':'DELETE '+wid,'confirm_backups':True,**changes}
    return c.post('/api/admin/couples/'+wid+'/delete',json=body,headers=headers(c,'/ivoryadmin'))
def run_job(app):
    db=database(app)
    try:return process_deletion(db,app.config['DATA_DIR'],app.config['BACKUP_DIR'])
    finally:db.close()
def job(c):return c.get('/api/admin/deletions').json['jobs'][0]


def seed(app):
    root=Path(app.config['DATA_DIR']);db=database(app)
    for wid in ('wu1','wu2'):
        folder=root/'files'/wid;folder.mkdir();(folder/'document.pdf').write_bytes((wid+' private document').encode())
        db.execute('INSERT INTO uploads VALUES(?,?,?,?,?,?,?,?)',(wid+'file',wid,'document.pdf','document.pdf','application/pdf',20,'document',time.time()))
    db.execute('INSERT INTO users(id,email,password,role,verified,created) VALUES("u3","partner@example.com","test-only","couple",1,0)')
    db.execute('INSERT INTO members VALUES("wu1","u3")')
    db.execute('INSERT INTO tokens VALUES("pending-partner","partner",NULL,"wu1","two@example.com","{}",9999999999,0)')
    db.execute('INSERT INTO mail(id,to_address,subject,body,created) VALUES("otheraccountmail","two@example.com","Keep account mail","UNRELATED-ACCOUNT",0)')
    # Mail and state belonging to the deleted wedding, and an unrelated guest
    # invitation to the same email owned by the wedding that must be preserved.
    state=json.loads(db.execute('SELECT state FROM weddings WHERE id="wu1"').fetchone()[0]);state['notes']='ERASE-THIS-PRIVATE-NOTE';db.execute('UPDATE weddings SET state=? WHERE id="wu1"',(json.dumps(state),))
    db.execute('INSERT INTO tokens VALUES("testhash","welcome","u1","wu1","one@example.com","{}",9999999999,0)')
    db.execute('INSERT INTO mail(id,to_address,subject,body,dedupe,created) VALUES("ownmail","one@example.com","Planner","PRIVATE-INVITATION","welcome:testhash",0)')
    db.execute('INSERT INTO mail(id,to_address,subject,body,created) VALUES("guestmail","guest@example.com","Guest","PRIVATE-GUEST-LINK",0)')
    db.execute('INSERT INTO guest_invitation_activity VALUES("guesthash","wu1",0,"guestmail")')
    db.execute('INSERT INTO mail(id,to_address,subject,body,created) VALUES("keepmail","one@example.com","Other wedding","OTHER-WEDDING-INVITATION",0)')
    db.execute('INSERT INTO guest_invitation_activity VALUES("otherguesthash","wu2",0,"keepmail")')
    db.execute('INSERT INTO purchases(id,wedding_id,amount,terms,created) VALUES("purchase","wu1",2500,"{}",0)')
    db.execute('INSERT INTO bank_receipts VALUES("purchase","TEST-RECEIPT","admin",0)')
    db.execute('INSERT INTO support VALUES("wu1",9999999999,"PRIVATE-SUPPORT-NOTE")')
    db.execute('INSERT INTO policy_acceptances(user_id,wedding_id,terms,privacy,accepted) VALUES("u1","wu1","Terms","Privacy",0)')
    db.execute('INSERT INTO hub_shares VALUES("share","wu1","PRIVATE-SHARE","photographer","[]","[]","supplier@example.com",1,9999999999,0,"encrypted","hash",0)')
    db.execute('INSERT INTO hub_ack VALUES("share","hash","PRIVATE-SNAPSHOT",0)')
    db.execute('INSERT INTO mail(id,to_address,subject,body,dedupe,created) VALUES("sharemail","supplier@example.com","Shared","PRIVATE-SHARE-LINK","hub-invite:share",0)')
    db.execute('INSERT INTO bespoke_orders(id,wedding_id,requester,brief,created,updated) VALUES("order","wu1","u1","PRIVATE-BRIEF",0,0)')
    folder=root/'files'/'wu1'/'bespoke'/'order';folder.mkdir(parents=True);(folder/'art.png').write_bytes(b'PRIVATE-ART')
    db.execute('INSERT INTO bespoke_assets VALUES("art","order","artwork","art.png","wu1/bespoke/order/art.png","image/png",11)')
    db.execute('INSERT INTO bespoke_receipts VALUES("order","bank","BESPOKE-RECEIPT",19900,"admin",0)')
    db.execute('INSERT INTO mail(id,to_address,subject,body,dedupe,created) VALUES("adminmail","mark@example.com","Order","PRIVATE-BESPOKE-MESSAGE","bespoke-new-order-admin",0)')
    db.commit();db.close()


def assert_deleted(db):
    assert not db.execute('SELECT 1 FROM weddings WHERE id="wu1"').fetchone()
    assert not db.execute('SELECT 1 FROM users WHERE id="u1"').fetchone()
    for table in ('members','uploads','tokens','policy_acceptances','support','purchases','guest_invitation_activity','bespoke_orders','hub_shares'):
        assert not db.execute('SELECT 1 FROM '+table+' WHERE wedding_id="wu1"').fetchone(),table
    for table in ('bank_receipts','hub_ack','bespoke_receipts','bespoke_assets'):assert db.execute('SELECT count(*) FROM '+table).fetchone()[0]==0
    assert {r[0] for r in db.execute('SELECT id FROM mail')}=={'keepmail','otheraccountmail'}
    assert not db.execute('SELECT 1 FROM users WHERE id="u3"').fetchone()
    assert db.execute('SELECT 1 FROM weddings WHERE id="wu2"').fetchone()
    assert db.execute('SELECT 1 FROM users WHERE id="u2"').fetchone()
    assert db.execute('SELECT 1 FROM users WHERE id="admin"').fetchone()
    assert not db.execute('PRAGMA foreign_key_check').fetchall()


def test_admin_confirmation_csrf_and_read_only_preview(app):
    c=admin(app);couple=login(app)
    assert couple.get('/api/admin/couples/wu1/deletion-preview').status_code==403
    assert app.test_client().get('/api/admin/deletions').status_code==401
    before=c.get('/api/admin').json['couples']
    assert c.get('/api/admin/couples/wu1/deletion-preview').json['accounts']==1
    assert before==c.get('/api/admin').json['couples']
    assert c.post('/api/admin/couples/wu1/delete',json={'confirmation':'DELETE wu1','confirm_backups':True}).status_code==403
    for changes in ({'confirm_backups':False},{'confirmation':'DELETE wu2'},{'confirm_backups':'yes'}):assert request_delete(c,**changes).status_code==400
    assert not c.get('/api/admin/deletions').json['jobs']


def test_complete_erasure_cleans_live_and_all_archives_preserves_other_wedding(app,tmp_path):
    seed(app);other=database(app);keep_state=other.execute('SELECT state FROM weddings WHERE id="wu2"').fetchone()[0];other.close()
    copies=[backup(app.config['DATA_DIR'],app.config['BACKUP_DIR']) for _ in range(2)]
    c=admin(app);old_couple=login(app);r=request_delete(c);assert r.status_code==202
    assert request_delete(c).json['job_id']==r.json['job_id']
    assert old_couple.get('/api/state').status_code==401
    assert c.get('/api/admin/backups').json['deletion_cleanup']
    assert c.get('/api/admin/backups/'+copies[0].name).status_code==409
    assert c.post('/api/admin/backups',json={},headers=headers(c,'/ivoryadmin')).status_code==409
    with pytest.raises(ValueError):backup(app.config['DATA_DIR'],app.config['BACKUP_DIR'])
    assert run_job(app);assert job(c)['status']=='completed';assert job(c)['archives_done']==2
    db=database(app);assert_deleted(db);row=db.execute('SELECT * FROM couple_deletions').fetchone();assert row['payload']=='{}' and row['wedding_id'] is None;db.close()
    assert not (Path(app.config['DATA_DIR'])/'files'/'wu1').exists()
    for index,archive in enumerate(copies):
        destination=tmp_path/('restore-'+str(index));destination.mkdir();restore_empty(archive,destination)
        db=connect(destination/'planner.sqlite3');assert_deleted(db);assert db.execute('SELECT state FROM weddings WHERE id="wu2"').fetchone()[0]==keep_state;db.close()
        assert not (destination/'files'/'wu1').exists()
        assert (destination/'files'/'wu2'/'document.pdf').read_bytes()==b'wu2 private document'
        assert b'ERASE-THIS-PRIVATE-NOTE' not in (destination/'planner.sqlite3').read_bytes()
    assert len(c.get('/api/admin/backups').json['archives'])==2
    assert not run_job(app)
    assert c.get('/api/admin/couples/wu1/deletion-preview').status_code==404


def test_corrupt_archive_is_not_replaced_success_not_claimed_and_retry_works(app,tmp_path):
    copies=[backup(app.config['DATA_DIR'],app.config['BACKUP_DIR'])]
    bad=copies[0];good=bad.read_bytes();bad.write_bytes(b'not a backup')
    c=admin(app);request_delete(c);assert run_job(app)
    assert job(c)['status']=='failed' and bad.read_bytes()==b'not a backup'
    assert c.get('/api/admin/deletions').json['blocked']
    assert c.get('/api/admin/backups/'+bad.name).status_code==409
    assert not run_job(app) # failed jobs wait for an explicit retry, no busy loop
    bad.write_bytes(good)
    assert c.post('/api/admin/deletions/'+job(c)['id']+'/retry',json={},headers=headers(c,'/ivoryadmin')).status_code==200
    assert run_job(app) and job(c)['status']=='completed'


def test_resume_running_job_and_remove_incomplete_app_archive(app):
    root=Path(app.config['BACKUP_DIR']);root.mkdir();partial=root/'.planner-20261028-000000-123456.tar.gz.partial';partial.write_bytes(b'PRIVATE-PARTIAL')
    c=admin(app);request_delete(c);db=database(app);db.execute('UPDATE couple_deletions SET status="running"');db.commit();db.close()
    assert run_job(app);assert job(c)['status']=='completed' and not partial.exists()


def test_symlink_backup_and_live_file_paths_fail_closed(app,tmp_path):
    root=Path(app.config['BACKUP_DIR']);root.mkdir();outside=tmp_path/'outside';outside.write_bytes(b'KEEP-OUTSIDE')
    (root/'planner-20261028-000000-123456.tar.gz').symlink_to(outside)
    c=admin(app);request_delete(c);run_job(app)
    assert job(c)['status']=='failed' and outside.read_bytes()==b'KEEP-OUTSIDE'


def test_deleted_booking_does_not_automatically_recreate_account(app):
    c,key=booking_setup(app);payload=booking_body();client=app.test_client()
    r=client.post('/api/integrations/wbm/invitations',json=payload,headers=key);assert r.status_code==201
    wid=r.json['wedding_id'];assert request_delete(c,wid).status_code==202;assert run_job(app)
    assert client.get('/api/integrations/wbm/invitations/'+payload['booking_id'],headers=key).json['status']=='deleted'
    assert client.post('/api/integrations/wbm/invitations',json=payload,headers=key).status_code==409
    db=database(app);assert not db.execute('SELECT 1 FROM weddings WHERE id=?',(wid,)).fetchone();db.close()


def test_pending_deletion_blocks_smtp_and_access_changes(app,monkeypatch):
    c=admin(app);request_delete(c)
    assert c.post('/api/admin/access/wu1',json={'access':'Manual extension','until':'2030-01-01','reason':'Try unsuspending'},headers=headers(c,'/ivoryadmin')).status_code==409
    db=database(app);db.execute('INSERT INTO mail(id,to_address,subject,body,created) VALUES("queued","one@example.com","Do not send","private",0)');db.commit()
    def forbidden(*args,**kwargs):raise AssertionError('SMTP must not run while deletion is pending')
    monkeypatch.setattr('app.worker.send_email',forbidden);settings=config(db);settings['sender']='planner@example.com';deliver(db,settings,secret=app.config['SECRET_VALUE']);db.close()


def test_archive_replacement_failure_keeps_original_and_retry_context(app,monkeypatch):
    archive=backup(app.config['DATA_DIR'],app.config['BACKUP_DIR']);before=archive.read_bytes()
    c=admin(app);request_delete(c)
    def fail(*args,**kwargs):raise OSError('test-only replacement failure')
    monkeypatch.setattr('app.couple_deletion.os.replace',fail)
    assert run_job(app) and job(c)['status']=='failed'
    assert archive.read_bytes()==before
    db=database(app);row=db.execute('SELECT wedding_id,payload FROM couple_deletions').fetchone();assert row['wedding_id']=='wu1' and 'one@example.com' in row['payload'];db.close()


def test_pending_deletion_does_not_stop_unrelated_couple_mail(app,monkeypatch):
    from test_smtp import FakeSMTP
    c=admin(app);request_delete(c)
    db=database(app);db.execute('INSERT INTO mail(id,to_address,subject,body,created) VALUES("unrelated","two@example.com","Keep sending","Hello",0)');db.commit()
    FakeSMTP.calls=[];monkeypatch.setattr('app.mail_service.smtplib.SMTP',FakeSMTP)
    settings=config(db);settings['sender']='planner@example.com';deliver(db,settings,secret=app.config['SECRET_VALUE']);db.close()
    messages=[call[1] for call in FakeSMTP.calls if call[0]=='message']
    assert len(messages)==1 and messages[0]['To']=='two@example.com'


def test_inflight_backup_containing_deletion_job_is_scrubbed_too(app,tmp_path):
    from app.worker import _backup
    c=admin(app);request_delete(c)
    archive=_backup(app.config['DATA_DIR'],app.config['BACKUP_DIR'])
    timestamp=archive.stat().st_mtime
    assert run_job(app) and job(c)['status']=='completed'
    assert archive.stat().st_mtime==timestamp
    destination=tmp_path/'inflight-restored';destination.mkdir();restore_empty(archive,destination)
    db=connect(destination/'planner.sqlite3')
    assert not pending(db) and not db.execute('SELECT 1 FROM weddings WHERE id="wu1"').fetchone()
    assert not db.execute('SELECT 1 FROM couple_deletions WHERE payload LIKE ?',('%one@example.com%',)).fetchone()
    db.close()


def test_unwritable_backup_location_marks_job_failed_instead_of_stuck_queued(app):
    root=Path(app.config['BACKUP_DIR']);root.write_text('not a directory')
    c=admin(app);request_delete(c)
    assert run_job(app) and job(c)['status']=='failed'
    assert job(c)['label']=='one@example.com'
    assert 'could not start' in job(c)['message'].lower()

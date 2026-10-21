import json
from pathlib import Path
import pytest
from test_app import app,database,login,headers
from app.admin_backups import process_requested_backup,recover_interrupted_backup,KEY
from app.worker import backup
from scripts.restore_data import restore_empty


def admin_headers(c):return headers(c,'/ivoryadmin')


def test_admin_only_and_csrf(app):
    anon=app.test_client();couple=login(app);admin=login(app,'mark@example.com',admin=True)
    for client,status in ((anon,401),(couple,403)):
        assert client.get('/api/admin/backups').status_code==status
        assert client.get('/api/admin/backups/planner-20261021-120000-123456.tar.gz').status_code==status
    assert admin.post('/api/admin/backups',json={}).status_code==403
    assert admin.get('/api/admin/backups').json['archives']==[]


def test_manual_request_dedup_download_and_recover(app,tmp_path):
    c=login(app,'mark@example.com',admin=True);h=admin_headers(c)
    db=database(app);before=[tuple(r) for r in db.execute('SELECT id,state FROM weddings ORDER BY id')];mail=db.execute('SELECT count(*) FROM mail').fetchone()[0]
    db.close()
    # Use the real upload endpoint so backup recovery checks a referenced file.
    import io
    from PIL import Image
    image=io.BytesIO();Image.new('RGB',(8,8),'white').save(image,'PNG');image.seek(0)
    couple=login(app)
    response=couple.post('/api/files',data={'file':(image,'fixture.png'),'kind':'cover'},headers=headers(couple),content_type='multipart/form-data')
    assert response.status_code in (200,201),response.get_data(as_text=True)
    request=c.post('/api/admin/backups',json={},headers=h);assert request.status_code==202
    assert c.post('/api/admin/backups',json={},headers=h).json['job']['id']==request.json['job']['id']
    db=database(app);assert process_requested_backup(db,app.config['DATA_DIR'],app.config['BACKUP_DIR']);assert not process_requested_backup(db,app.config['DATA_DIR'],app.config['BACKUP_DIR']);db.close()
    status=c.get('/api/admin/backups').json;assert status['job']['status']=='completed';assert len(status['archives'])==1
    name=status['archives'][0]['name'];r=c.get('/api/admin/backups/'+name)
    assert r.status_code==200 and 'attachment' in r.headers['Content-Disposition'] and r.headers['Cache-Control']=='no-store'
    archive=tmp_path/'download.tar.gz';archive.write_bytes(r.data);r.close()
    destination=tmp_path/'recovered';destination.mkdir();assert restore_empty(archive,destination)==(2,1)
    from app.core import connect
    recovered=connect(destination/'planner.sqlite3')
    assert [tuple(row) for row in recovered.execute('SELECT id,state FROM weddings ORDER BY id')]==before
    reference=recovered.execute('SELECT wedding_id,path FROM uploads').fetchone()
    assert (destination/'files'/reference['wedding_id']/Path(reference['path']).name).is_file()
    assert (destination/'app-secret').read_bytes()==(Path(app.config['DATA_DIR'])/'app-secret').read_bytes()
    recover_interrupted_backup(recovered);assert json.loads(recovered.execute('SELECT value FROM settings WHERE key=?',(KEY,)).fetchone()[0])['status']=='interrupted';recovered.close()
    db=database(app);assert db.execute('SELECT count(*) FROM mail').fetchone()[0]==mail;db.close()
    with pytest.raises(ValueError):restore_empty(archive,destination)


def test_failure_keeps_previous_archive_and_allows_retry(app,monkeypatch):
    old=backup(app.config['DATA_DIR'],app.config['BACKUP_DIR']);c=login(app,'mark@example.com',admin=True);h=admin_headers(c)
    c.post('/api/admin/backups',json={},headers=h)
    def broken(*args):raise OSError('fixture failure')
    monkeypatch.setattr('app.worker.backup',broken)
    db=database(app);assert process_requested_backup(db,app.config['DATA_DIR'],app.config['BACKUP_DIR']);db.close()
    assert c.get('/api/admin/backups').json['job']['status']=='failed';assert old.is_file()
    assert c.post('/api/admin/backups',json={},headers=h).json['job']['status']=='queued'


def test_cannot_download_other_paths_symlinks_or_partial_files(app,tmp_path):
    c=login(app,'mark@example.com',admin=True);root=Path(app.config['BACKUP_DIR']);root.mkdir(exist_ok=True)
    secret=tmp_path/'outside';secret.write_text('private')
    link=root/'planner-20261021-120000-123456.tar.gz';link.symlink_to(secret)
    partial=root/'planner-20261021-120000-123456.tar.gz.partial';partial.write_text('incomplete')
    assert c.get('/api/admin/backups/'+link.name).status_code==404
    assert c.get('/api/admin/backups/'+partial.name).status_code==404
    assert c.get('/api/admin/backups/%2e%2e%2foutside').status_code==404
    assert c.get('/api/admin/backups').json['archives']==[]

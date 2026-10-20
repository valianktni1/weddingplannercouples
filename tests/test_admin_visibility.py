import json
import time
import io
import tarfile

import pytest

from test_app import app, csrf, database
from test_onboarding import prepared, invite, invitation
from app.worker import backup
from scripts.test_restore import restore


def test_invitation_progress_never_calls_smtp_acceptance_delivery(app):
    admin = prepared(app)
    wid = invite(admin).json['wedding_id']
    path, mail = invitation(app)
    progress = next(c for c in admin.get('/api/admin').json['couples'] if c['id'] == wid)['invitation']
    assert progress['status'] == 'Queued'
    assert progress['queued_at']
    assert progress['accepted_at'] is None

    db = database(app)
    accepted = time.time()
    db.execute('UPDATE mail SET status="sent",accepted_at=? WHERE id=?', (accepted, mail['id']))
    db.commit()
    db.close()
    progress = next(c for c in admin.get('/api/admin').json['couples'] if c['id'] == wid)['invitation']
    assert progress['status'] == 'Awaiting couple'
    assert progress['accepted_at'] == accepted

    visitor = app.test_client()
    response = visitor.post(path, data={'csrf': csrf(visitor, path), 'password': 'long-new-password', 'accept_terms': 'yes'})
    assert response.status_code == 302
    progress = next(c for c in admin.get('/api/admin').json['couples'] if c['id'] == wid)['invitation']
    assert progress['status'] == 'Joined'
    assert progress['joined_at']


def test_couple_preview_is_read_only_and_hides_private_plan(app):
    admin = prepared(app)
    wid = invite(admin).json['wedding_id']
    db = database(app)
    row = db.execute('SELECT state FROM weddings WHERE id=?', (wid,)).fetchone()
    state = json.loads(row['state'])
    state['notes'] = 'PRIVATE-FAMILY-NOTE'
    db.execute('UPDATE weddings SET state=? WHERE id=?', (json.dumps(state), wid))
    db.commit()
    db.close()
    path = f'/ivoryadmin/couples/{wid}/preview'
    assert app.test_client().get(path).status_code in (302, 401)
    response = admin.get(path)
    assert response.status_code == 200
    assert b'PRIVATE-FAMILY-NOTE' not in response.data
    assert b'sample plan' in response.data
    assert b'/static/planner.js' in response.data
    assert admin.post(path).status_code in (403, 405)


def test_health_reports_actionable_checks(app):
    admin = prepared(app)
    health = admin.get('/api/admin').json['status']['health']
    assert set(health) == {'worker', 'email', 'backup', 'storage'}
    assert health['backup']['ok'] is False
    assert health['backup']['action']


def test_isolated_restore_boots_recovered_application(app, tmp_path):
    db = database(app)
    expected_weddings = db.execute('SELECT count(*) FROM weddings').fetchone()[0]
    expected_files = db.execute('SELECT count(*) FROM uploads').fetchone()[0]
    db.close()
    archive = backup(app.config['DATA_DIR'], tmp_path / 'archives')
    target = tmp_path / 'isolated'
    target.mkdir()
    weddings, files = restore(archive, target)
    assert weddings == expected_weddings
    assert files == expected_files


def test_isolated_restore_rejects_archive_path_escape(tmp_path):
    archive = tmp_path / 'bad.tar.gz'
    with tarfile.open(archive, 'w:gz') as tar:
        payload = b'not a database'
        info = tarfile.TarInfo('../escape')
        info.size = len(payload)
        tar.addfile(info, io.BytesIO(payload))
    target = tmp_path / 'isolated'
    target.mkdir()
    with pytest.raises(ValueError, match='unsafe path'):
        restore(archive, target)
    assert not (tmp_path / 'escape').exists()

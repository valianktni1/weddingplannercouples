"""Opt-in account metadata feed, independent of the Booking invitation key."""
from contextlib import closing
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import sqlite3
import time
from zoneinfo import ZoneInfo

from flask import abort, jsonify, request


def authorise():
    key = os.getenv('PLANNER_CONTROL_CENTRE_KEY', '')
    supplied = request.headers.get('X-Control-Centre-Key', '')
    if len(key) < 32 or len(supplied) > 200 or not hmac.compare_digest(
            hashlib.sha256(key.encode()).digest(), hashlib.sha256(supplied.encode()).digest()):
        abort(401, description='Dashboard connection not authorised.')
    if os.getenv('PLANNER_CONTROL_CENTRE_ENABLED', '').lower() != 'true':
        abort(503, description='Dashboard connection is disabled.')


def overview(database, version):
    now = datetime.now(timezone.utc)
    today = now.astimezone(ZoneInfo('Europe/London')).date()
    end = (today + timedelta(days=14)).isoformat()
    # A separate read-only connection cannot alter sessions, invitations or plans.
    with closing(sqlite3.connect(Path(database).resolve().as_uri() + '?mode=ro', uri=True, timeout=3)) as db:
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        rows = db.execute('''
            WITH accounts AS (
                SELECT w.id, json_extract(w.state,'$.names') names,
                    json_extract(w.state,'$.date') wedding_date,
                    w.access_until,w.suspended,h.last_active,
                    (SELECT u.id FROM users u JOIN members m ON m.user_id=u.id
                     WHERE m.wedding_id=w.id AND EXISTS (
                       SELECT 1 FROM tokens t WHERE t.wedding_id=w.id
                       AND t.user_id=u.id AND t.kind='welcome')
                     ORDER BY u.created,u.id LIMIT 1) invitee
                FROM weddings w LEFT JOIN hub_meta h ON h.wedding_id=w.id
                WHERE NOT EXISTS (SELECT 1 FROM cancelled_couple_invitations c WHERE c.wedding_id=w.id)
            )
            SELECT a.*,u.verified,
              (SELECT m.status FROM mail m JOIN tokens t ON m.dedupe=('welcome:' || t.hash)
               WHERE t.wedding_id=a.id AND t.user_id=a.invitee AND t.kind='welcome'
               ORDER BY m.created DESC,m.id DESC LIMIT 1) delivery
            FROM accounts a LEFT JOIN users u ON u.id=a.invitee
            ORDER BY a.access_until,a.id
        ''').fetchall()
        counts = dict(active_accounts=0, awaiting_couples=0, invitation_problems=0,
                      expiring_access=0, active_last_seven_days=0)
        groups = {key: [] for key in ('awaiting_couples', 'invitation_problems', 'expiring_access')}
        for row in rows:
            active = not row['suspended'] and row['access_until'] >= today.isoformat()
            if active:
                counts['active_accounts'] += 1
                if row['last_active'] and row['last_active'] >= time.time() - 7*86400:
                    counts['active_last_seven_days'] += 1
            names = json.loads(row['names'] or '[]')
            title = ' & '.join(n for n in names if isinstance(n, str))[:200] or 'Setup incomplete'
            item = dict(title=title, wedding_date=row['wedding_date'] or None,
                        access_until=row['access_until'], path='/ivoryadmin')
            if row['invitee'] and not row['verified']:
                raw = row['delivery'] or 'missing'
                key = 'awaiting_couples' if raw in ('sent', 'queued') else 'invitation_problems'
                counts[key] += 1
                if len(groups[key]) < 5:
                    groups[key].append(dict(item, status={
                        'sent': 'Awaiting couple', 'queued': 'Email queued',
                        'retry': 'Email retry pending', 'failed': 'Email failed',
                        'cancelled': 'Email cancelled', 'missing': 'Invitation needs review'
                    }.get(raw, 'Invitation needs review')))
            if active and row['access_until'] <= end:
                counts['expiring_access'] += 1
                if len(groups['expiring_access']) < 5:
                    groups['expiring_access'].append(dict(item, status='Access ends within 14 days'))
        heartbeat = db.execute("SELECT value FROM settings WHERE key='worker_heartbeat'").fetchone()
        last_seen = json.loads(heartbeat[0]) if heartbeat else None
        worker = 'unknown' if not isinstance(last_seen, (int, float)) else 'ok' if time.time()-last_seen < 180 else 'attention'
        return dict(schema_version=1, generated_at=now.isoformat(), business_date=today.isoformat(),
                    version=version, counts=counts, queues=groups, worker_status=worker)


def register_control_centre(app, version):
    @app.get('/api/integrations/control-centre/overview')
    def control_centre_overview():
        return jsonify(overview(app.config['DATABASE'], version))

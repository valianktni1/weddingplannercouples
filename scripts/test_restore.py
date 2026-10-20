"""Restore one archive into a disposable installation and verify it starts.

Run on the NAS from the application checkout. The live data directory is never
opened for writing. The temporary restore is removed after this check.
"""
import argparse
import json
import os
import sqlite3
import sys
import tarfile
import tempfile
from pathlib import Path, PurePosixPath

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def restore(archive, scratch):
    root = Path(scratch).resolve()
    with tarfile.open(archive, 'r:gz') as source:
        members = source.getmembers()
        if not members or any(not (member.isfile() or member.isdir()) for member in members):
            raise ValueError('Archive contains unsupported links or device entries.')
        for member in members:
            name = PurePosixPath(member.name)
            if name.is_absolute() or '..' in name.parts or not name.parts or name.parts[0] not in {'planner.sqlite3', 'app-secret', 'files'}:
                raise ValueError('Archive contains an unsafe path.')
            destination = root.joinpath(*name.parts)
            if not destination.resolve().is_relative_to(root):
                raise ValueError('Archive path escapes the test installation.')
            if member.isdir():
                destination.mkdir(parents=True, exist_ok=True)
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                with source.extractfile(member) as incoming, destination.open('xb') as outgoing:
                    while block := incoming.read(1024 * 1024):
                        outgoing.write(block)
    database = root / 'planner.sqlite3'
    secret = root / 'app-secret'
    if not database.is_file() or not secret.is_file() or not (root / 'files').is_dir():
        raise ValueError('Archive is missing the database, key or files directory.')
    db = sqlite3.connect(f'file:{database}?mode=ro', uri=True)
    try:
        if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('Restored database failed integrity_check.')
        weddings = 0
        for (state,) in db.execute('SELECT state FROM weddings'):
            json.loads(state)
            weddings += 1
        files = 0
        for wedding, path in db.execute('SELECT wedding_id,path FROM uploads'):
            if not (root / 'files' / wedding / Path(path).name).is_file():
                raise ValueError('A couple file referenced by the database is missing.')
            files += 1
    finally:
        db.close()
    # The recovered key and database must also boot the real application.
    from app.server import create_app
    app = create_app({'DATA_DIR': str(root), 'BACKUP_DIR': str(root / 'test-backups'), 'TESTING': True, 'SECURE_COOKIES': False})
    response = app.test_client().get('/healthz')
    if response.status_code != 200 or response.json.get('status') != 'ok':
        raise ValueError('The restored application did not pass its health check.')
    return weddings, files


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path, help='A planner-*.tar.gz archive')
    parser.add_argument('--work-dir', type=Path, help='Parent directory for the disposable restore')
    args = parser.parse_args()
    if not args.archive.is_file():
        parser.error('Archive not found.')
    parent = args.work_dir.resolve() if args.work_dir else None
    if parent and not parent.is_dir():
        parser.error('Work directory must already exist.')
    live_data = Path(os.getenv('DATA_DIR', '/data')).resolve()
    if parent and parent.is_relative_to(live_data):
        parser.error('Work directory must not be inside the live data directory.')
    with tempfile.TemporaryDirectory(prefix='planner-restore-', dir=parent) as scratch:
        weddings, files = restore(args.archive, scratch)
    print(f'Isolated restore passed: app booted, {weddings} wedding records and {files} referenced files checked. Temporary installation removed.')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, sqlite3.Error, tarfile.TarError) as error:
        print(f'Isolated restore failed: {error}', file=sys.stderr)
        raise SystemExit(1)

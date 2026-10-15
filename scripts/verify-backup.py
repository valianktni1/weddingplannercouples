"""Check an extracted backup without touching the live database."""
import argparse
import json
import sqlite3
from pathlib import Path
parser=argparse.ArgumentParser();parser.add_argument('directory');args=parser.parse_args();root=Path(args.directory)
db=sqlite3.connect(f'file:{root / "planner.sqlite3"}?mode=ro',uri=True)
assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok','Database integrity check failed'
assert (root/'app-secret').is_file(),'Encryption key is missing'
assert (root/'files').is_dir(),'Files directory is missing'
for state, in db.execute('SELECT state FROM weddings'): json.loads(state)
for wedding,path in db.execute('SELECT wedding_id,path FROM uploads'):
    assert (root/'files'/wedding/Path(path).name).is_file(),'Referenced attachment is missing'
print('Database integrity, wedding records, encryption key and referenced files verified. This is not a full sign-in/restore test.')

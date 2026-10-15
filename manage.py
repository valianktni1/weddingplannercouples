import argparse
import getpass
import json
import os
import secrets
import time
from pathlib import Path
from werkzeug.security import generate_password_hash
from app.core import initialise,connect

def main():
    parser=argparse.ArgumentParser();sub=parser.add_subparsers(dest='command',required=True)
    admin=sub.add_parser('create-admin');admin.add_argument('--email',required=True)
    verify=sub.add_parser('verify-user');verify.add_argument('--email',required=True)
    sub.add_parser('backup')
    args=parser.parse_args();root=Path(os.getenv('DATA_DIR','/data'));initialise(root);db=connect(root/'planner.sqlite3')
    if args.command=='create-admin':
        email=args.email.lower().strip()
        if '@' not in email: raise SystemExit('Enter a valid email.')
        if db.execute('SELECT 1 FROM users WHERE email=?',(email,)).fetchone(): raise SystemExit('Account exists. No existing password was changed.')
        password=getpass.getpass('New admin password (minimum 12 characters): ')
        if len(password)<12 or password!=getpass.getpass('Repeat password: '): raise SystemExit('Passwords must match and be at least 12 characters.')
        db.execute('INSERT INTO users(id,email,password,role,verified,created) VALUES(?,?,?,"admin",1,?)',(secrets.token_hex(16),email,generate_password_hash(password),time.time()));db.commit()
        print('Admin created. Sign in at /ivoryadmin and enrol your authenticator.')
    elif args.command=='verify-user':
        result=db.execute('UPDATE users SET verified=1 WHERE email=? AND role="couple"',(args.email.lower().strip(),));db.commit()
        print('Verified',result.rowcount,'couple account(s). Use only after confirming ownership.')
    else:
        from app.worker import backup
        print('Backup saved:',backup(root,Path(os.getenv('BACKUP_DIR','/backups'))))
    db.close()
if __name__=='__main__':main()

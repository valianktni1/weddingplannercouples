"""Run interactively on the NAS. Never prints or sends the API key."""
import getpass
import os
from pathlib import Path
import re
import secrets
import time


def save_key(path,key):
    if not re.fullmatch(r'[A-Za-z0-9_-]{20,500}',key):raise ValueError('Enter the complete OpenAI API key without spaces. Nothing changed.')
    path=Path(path)
    if path.is_symlink() or not path.is_file():raise ValueError('The private environment file must already exist and must not be a symbolic link. Nothing changed.')
    original=path.read_bytes();stat=path.stat();text=original.decode()
    lines=[line for line in text.splitlines() if not re.match(r'^\s*(?:export\s+)?OPENAI_API_KEY\s*=',line)]
    replacement='\n'.join(lines).rstrip('\n')+'\nOPENAI_API_KEY='+key+'\n'
    backup=path.with_name(path.name+'.before-assistant-'+str(int(time.time()))+'-'+secrets.token_hex(3))
    with open(backup,'xb',opener=lambda p,f:os.open(p,f,0o600)) as out:out.write(original);out.flush();os.fsync(out.fileno())
    temporary=path.with_name('.assistant-key-'+secrets.token_hex(8)+'.tmp')
    try:
        with open(temporary,'x',opener=lambda p,f:os.open(p,f,0o600)) as out:out.write(replacement);out.flush();os.fsync(out.fileno())
        if os.geteuid()==0:os.chown(temporary,stat.st_uid,stat.st_gid)
        if path.read_bytes()!=original:raise ValueError('The environment file changed during setup. Nothing was overwritten.')
        temporary.replace(path)
    finally:
        if temporary.exists():temporary.unlink()
    return backup


def main():
    key=getpass.getpass('OpenAI API key (hidden): ').strip()
    confirmation=getpass.getpass('Repeat API key (hidden): ').strip()
    if key!=confirmation:raise SystemExit('The keys did not match. Nothing changed.')
    try:backup=save_key('/mnt/apps/weddingplannercouples.env',key)
    except (ValueError,OSError,UnicodeError):raise SystemExit('Could not update the private environment file safely. Check its path and permissions. No key was printed.')
    print('API key saved privately. Backup: '+str(backup))
    print('No API request was made. Recreate the web container, then open Admin > System & security > Manage planning assistant.')

if __name__=='__main__':main()

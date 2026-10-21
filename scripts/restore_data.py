"""Restore a complete planner archive into an EMPTY data directory only.

Stop web and worker first. Existing installations are never overwritten.
"""
import argparse
import os
import sys
import tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.test_restore import restore


def restore_empty(archive,destination):
    destination=Path(destination)
    if not destination.is_dir() or destination.is_symlink() or any(destination.iterdir()):
        raise ValueError('Destination must be an existing empty directory. Existing planner data was not changed.')
    with tempfile.TemporaryDirectory(prefix='.recovery-',dir=destination) as scratch:
        scratch=Path(scratch)
        result=restore(Path(archive),scratch)
        # The whole archive has been checked and the recovered app booted before
        # any recovered files are placed in the final data directory.
        moved=[]
        try:
            for name in ('planner.sqlite3','app-secret','files'):
                os.replace(scratch/name,destination/name);moved.append(name)
        except Exception:
            for name in reversed(moved):os.replace(destination/name,scratch/name)
            raise
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive',type=Path)
    parser.add_argument('--destination',type=Path,required=True)
    args=parser.parse_args()
    try:
        weddings,files=restore_empty(args.archive,args.destination)
    except Exception as exc:
        parser.exit(1,f'Recovery stopped: {exc}\n')
    print(f'Restored and checked {weddings} weddings and {files} uploaded files. Start the planner services when server configuration is ready.')

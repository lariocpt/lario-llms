"""Resume pinned downloads directly into XFS, without a second model cache."""
import concurrent.futures
import fcntl
import hashlib
import json
from pathlib import Path
import shutil
import socket
import subprocess
import time
import urllib.request

ROOT=Path('/mnt/xfs/AI_Models')
MANIFEST=Path(__file__).with_name('weights.json')


def verified(path, item):
    if not path.is_file() or path.stat().st_size != item['bytes']:
        return False
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        while block:=stream.read(8*1024*1024):digest.update(block)
    return digest.hexdigest()==item['sha256']


def download(item):
    path=ROOT/item['path'];path.parent.mkdir(parents=True,exist_ok=True)
    if verified(path,item):
        print('Verified '+item['path'],flush=True);return
    partial=path.with_name(path.name+'.part')
    for attempt in range(8):
        try:
            offset=partial.stat().st_size if partial.exists() else 0
            if offset > item['bytes']:raise RuntimeError('partial file exceeds expected size')
            if offset == item['bytes']:
                if not verified(partial,item):raise RuntimeError('partial file checksum mismatch; retained for inspection')
            else:
                headers={'Range':f'bytes={offset}-'} if offset else {}
                with urllib.request.urlopen(urllib.request.Request(item['url'],headers=headers),timeout=300) as response:
                    with partial.open('ab' if offset and response.status==206 else 'wb') as stream:
                        while block:=response.read(8*1024*1024):stream.write(block)
                if not verified(partial,item):raise RuntimeError('download size/checksum mismatch; retained for inspection')
            partial.replace(path)
            print('Verified '+item['path'],flush=True);return
        except (OSError,TimeoutError):
            if attempt==7:raise
            time.sleep(min(2**attempt,30))


def main():
    if socket.gethostname().split('.')[0]!='bigcachy':raise RuntimeError('run on bigcachy')
    if subprocess.check_output(['findmnt','-n','-o','FSTYPE','-T',str(ROOT)],text=True).strip()!='xfs':raise RuntimeError('XFS model store is required')
    if subprocess.run(['systemctl','--user','is-active','--quiet','gpu-migration-download.service']).returncode==0:
        raise RuntimeError('The existing migration download is already running; do not overlap its partial files')
    state=Path.home()/'.local/state/gpu-migration';state.mkdir(parents=True,exist_ok=True)
    with (state/'weights.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        files=json.loads(MANIFEST.read_text())['files']
        remaining=sum(max(0,f['bytes']-max((ROOT/f['path']).stat().st_size if (ROOT/f['path']).exists() else 0,
            (ROOT/(f['path']+'.part')).stat().st_size if (ROOT/(f['path']+'.part')).exists() else 0)) for f in files)
        if shutil.disk_usage(ROOT).free < remaining+10*1024**3:raise RuntimeError('Insufficient space including 10 GiB reserve')
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(download,files))

if __name__=='__main__':main()

#!/usr/bin/env python3
"""Stage pinned signed GPU MKL beside system CPU MKL, without root/system changes."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import urllib.request

ROOT=Path(__file__).resolve().parents[1]


def stage(root):
    if subprocess.check_output(['findmnt','-n','-o','FSTYPE','-T',str(root)],text=True).strip()!='xfs':
        raise RuntimeError('runtime staging requires XFS')
    pin=json.loads((ROOT/'shared/runtime-versions.json').read_text())['intel_mkl_sycl']
    system=Path(pin['system_prefix'])
    if not (system/'include/mkl.h').is_file():
        raise RuntimeError('matching installed CPU MKL prefix is required: '+str(system))
    directory=root/'runtimes/intel-mkl-sycl'/pin['version'];directory.mkdir(parents=True,exist_ok=True)
    package=directory/pin['url'].rsplit('/',1)[1]
    for url,target in ((pin['url'],package),(pin['url']+'.sig',package.with_name(package.name+'.sig'))):
        if not target.exists():
            temp=target.with_name(target.name+'.partial')
            with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'curl/8.0'}),timeout=60) as response,temp.open('wb') as output:
                shutil.copyfileobj(response,output)
            temp.replace(target)
    if hashlib.sha256(package.read_bytes()).hexdigest()!=pin['sha256']:raise RuntimeError('GPU MKL package checksum mismatch')
    original=Path('/usr/share/pacman/keyrings/cachyos.gpg');keyring=directory/'cachyos-keyring.gpg'
    if original.read_bytes().startswith(b'-----BEGIN'):
        subprocess.run(['gpg','--batch','--yes','--dearmor','--output',str(keyring),str(original)],check=True)
    else:shutil.copy2(original,keyring)
    subprocess.run(['gpgv','--keyring',str(keyring),str(package)+'.sig',str(package)],check=True)
    extracted=directory/'root';extracted.mkdir(exist_ok=True)
    subprocess.run(['bsdtar','--no-same-owner','-xf',str(package),'-C',str(extracted)],check=True)
    prefix=extracted/system.relative_to('/')
    # Refer to matching installed CPU dependencies; never alter them.
    for source in system.rglob('*'):
        target=prefix/source.relative_to(system)
        if source.is_dir():target.mkdir(parents=True,exist_ok=True)
        elif not target.exists() and not target.is_symlink():target.symlink_to(source)
    (directory/'receipt.json').write_text(json.dumps({**pin,'prefix':str(prefix),'signature_verified':True},indent=2)+'\n')
    print(prefix)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',required=True,type=Path);a=p.parse_args();stage(a.root)

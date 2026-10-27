#!/usr/bin/env python3
"""Extract pinned Intel SYCL headers privately; do not install system packages."""
import hashlib
from pathlib import Path
import subprocess
import urllib.request

ROOT = Path.home()/'.local/share/strata/build-deps'
ROOT.mkdir(parents=True, exist_ok=True)
packages = {
    'intel-oneapi-mkl-sycl-include-2026.0-2026.0.0-908_amd64.deb':
        'e30e1e14ae32bd1824ed28be178ea88921c271ad72ab7f1e2b9214dc9d2de719',
    'intel-oneapi-mkl-sycl-devel-2026.0-2026.0.0-908_amd64.deb':
        '08a5f9941360b21dc4a93df2c071d1778b229a9932bdfdf53c4bef5ff3999eab',
}
for name, digest in packages.items():
    path = ROOT/name
    if not path.exists():
        urllib.request.urlretrieve('https://apt.repos.intel.com/oneapi/pool/main/'+name, path)
    if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        raise RuntimeError('Intel development package checksum mismatch: '+name)
    members = subprocess.check_output(['bsdtar', '-tf', str(path)], text=True).splitlines()
    data = next(m for m in members if m.startswith('data.tar.'))
    payload = subprocess.check_output(['bsdtar', '-xOf', str(path), data])
    subprocess.run(['bsdtar', '-xf', '-', '-C', str(ROOT)], input=payload, check=True)
engine = Path.home()/'.local/share/strata/components/engine/0.1.50-linux-x86_64-sycl'
lib = ROOT/'lib'
lib.mkdir(exist_ok=True)
for original in engine.glob('libmkl_sycl_*.so.*'):
    link = lib/(original.name.split('.so.')[0]+'.so')
    if not link.exists():
        link.symlink_to(original)
print(ROOT)

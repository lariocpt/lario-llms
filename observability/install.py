#!/usr/bin/env python3
"""Install user collectors using a checksum-verified, operator-staged Alloy binary."""
import argparse
import hashlib
import os
from pathlib import Path
import shutil
import socket
import tempfile
import subprocess
import urllib.request
import zipfile

ROOT=Path(__file__).resolve().parents[1]
VERSION='1.20.1'
SHA256='451fe650e8277d22d69cb8db50bba809f581fe78decba7fce4027ef185457be9'
UNITS={
 'bigcachy':r'rtx5080\.service|arcB70\.service|lario-b70-vllm\.service|lario-intel@(embedding|asr|translation|tts)\.service|lario-images\.service|lario-admission@(rtx5080|arcB70)\.service',
 'l-dev-ai':r'llama-swap\.service|geekom7900xt\.service|lario-admission@(geekom|geekom7900xt)\.service',
 'cachyos-mini-mobile':r'lario-model-exporter\.service',
}

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--archive',type=Path,required=True);a=p.parse_args()
 host=socket.gethostname().split('.')[0]
 if host not in UNITS:raise RuntimeError('unregistered model host')
 if hashlib.sha256(a.archive.read_bytes()).hexdigest()!=SHA256:raise RuntimeError('Alloy archive checksum mismatch')
 home=Path.home();private=home/'.config/lario-observability';private.mkdir(mode=0o700,parents=True,exist_ok=True)
 key=private/'push.key'
 if not key.is_file() or key.stat().st_mode & 0o077:raise RuntimeError('operator must install private push.key, mode 0600')
 target=home/'.local/lib/lario-observability';target.mkdir(parents=True,exist_ok=True)
 descriptor,temporary=tempfile.mkstemp(prefix='alloy.',dir=target)
 with zipfile.ZipFile(a.archive) as z:
  with z.open('alloy-linux-amd64') as src,os.fdopen(descriptor,'wb') as dst:shutil.copyfileobj(src,dst)
 Path(temporary).chmod(0o755)
 os.replace(temporary,target/'alloy')
 config=(ROOT/'observability/config.alloy.template').read_text()
 for old,new in {'@HOST@':host,'@HOME@':str(home),'@UID@':str(os.getuid()),'@UNITS@':UNITS[host].replace('\\','\\\\')}.items():config=config.replace(old,new)
 descriptor,temporary=tempfile.mkstemp(prefix='config.',suffix='.alloy',dir=private)
 try:
  with os.fdopen(descriptor,'w') as file:file.write(config)
  subprocess.run([str(target/'alloy'),'validate','--stability.level=experimental',temporary],check=True)
  os.replace(temporary,private/'config.alloy')
 finally:Path(temporary).unlink(missing_ok=True)
 units=home/'.config/systemd/user';units.mkdir(parents=True,exist_ok=True)
 for unit in ('lario-model-exporter.service','lario-model-alloy.service'):shutil.copyfile(ROOT/'observability'/unit,units/unit)
 subprocess.run(['systemctl','--user','daemon-reload'],check=True)
 subprocess.run(['systemctl','--user','enable','lario-model-exporter.service','lario-model-alloy.service'],check=True)
 subprocess.run(['systemctl','--user','restart','lario-model-exporter.service','lario-model-alloy.service'],check=True)
 print('Model telemetry enabled; inference services untouched')

if __name__=='__main__':main()

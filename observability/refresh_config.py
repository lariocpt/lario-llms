#!/usr/bin/env python3
"""Validate and deploy collector configuration only; retain the installed Alloy binary."""
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from observability.install import UNITS, VERSION


def main():
    host=socket.gethostname().split('.')[0]
    if host not in UNITS:raise RuntimeError('unregistered host')
    home=Path.home();private=home/'.config/lario-observability'
    binary=home/'.local/lib/lario-observability/alloy'
    version=subprocess.check_output([str(binary),'--version'],text=True)
    if VERSION not in version:raise RuntimeError('unexpected installed Alloy version')
    key=private/'push.key'
    if not key.is_file() or key.stat().st_mode&0o077:raise RuntimeError('private telemetry credential required')
    config=(ROOT/'observability/config.alloy.template').read_text()
    for old,new in {'@HOST@':host,'@HOME@':str(home),'@UID@':str(os.getuid()),'@UNITS@':UNITS[host].replace('\\','\\\\')}.items():config=config.replace(old,new)
    fd,temp=tempfile.mkstemp(prefix='config.',suffix='.alloy',dir=private)
    try:
        with os.fdopen(fd,'w') as file:file.write(config)
        subprocess.run([str(binary),'validate','--stability.level=experimental',temp],check=True)
        os.replace(temp,private/'config.alloy')
    finally:Path(temp).unlink(missing_ok=True)
    subprocess.run(['systemctl','--user','restart','lario-model-alloy.service'],check=True)
    print(host+': hardware-labelled sanitized logs enabled; inference services untouched')


if __name__=='__main__':main()

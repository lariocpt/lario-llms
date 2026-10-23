#!/usr/bin/env python3
"""Install user-level backend reconciliation without restarting model services."""
from pathlib import Path
import shutil
import subprocess

ROOT=Path(__file__).resolve().parents[1]


def install():
    units=Path.home()/'.config/systemd/user'
    units.mkdir(parents=True,exist_ok=True)
    for name in ('lario-backend-watch.service','lario-backend-watch.timer'):
        shutil.copy2(ROOT/'shared/systemd'/name,units/name)
    arc=units/'arcB70.service'
    if arc.exists():
        original=arc.read_text()
        updated=original.replace('install.py --check-device\n',
                                 'install.py --check-device --wait-device-seconds 60\n')
        if updated!=original:arc.write_text(updated)
    subprocess.run(['systemctl','--user','daemon-reload'],check=True)
    subprocess.run(['systemctl','--user','enable','--now','lario-backend-watch.timer'],check=True)
    subprocess.run(['systemctl','--user','start','--no-block','lario-backend-watch.service'],check=True)


if __name__=='__main__':install()

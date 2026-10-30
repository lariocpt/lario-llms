#!/usr/bin/env python3
"""Administrator step: allow this user's Halogen launcher to lock its weights.

Does not restart services, unload a model, change BIOS/kernel tuning, or reboot.
After this completes, reload Halogen through the owner while confirmed idle.
"""
import os
from pathlib import Path
import pwd
import socket
import subprocess

if os.geteuid() != 0 or socket.gethostname().split('.')[0] != 'l-dev-ai':
    raise SystemExit('Run with sudo on l-dev-ai only')
user = pwd.getpwnam('lario')
unit = f'user@{user.pw_uid}.service'
path = Path('/etc/systemd/system') / (unit + '.d/90-halogen-memlock.conf')
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text('[Service]\nLimitMEMLOCK=infinity\n')
subprocess.run(['systemctl', 'daemon-reload'], check=True)
manager = subprocess.check_output(['systemctl','show',unit,'--property=MainPID','--value'],text=True).strip()
if not manager.isdecimal() or int(manager) <= 1:
    raise SystemExit('No live user manager; persistent limit installed for next login')
subprocess.run(['prlimit','--pid',manager,'--memlock=unlimited:unlimited'],check=True)
dropin = Path(user.pw_dir) / '.config/systemd/user/llama-swap.service.d/80-halogen-memlock.conf'
dropin.parent.mkdir(parents=True, exist_ok=True)
dropin.write_text('[Service]\nLimitMEMLOCK=infinity\n')
os.chown(dropin,user.pw_uid,user.pw_gid)
env = dict(os.environ, XDG_RUNTIME_DIR=f'/run/user/{user.pw_uid}')
def systemctl(*args):
    return subprocess.check_output(['runuser','-u',user.pw_name,'--','systemctl','--user',*args],env=env,text=True)
systemctl('daemon-reload')
backend = systemctl('show','llama-swap.service','--property=MainPID','--value').strip()
if backend.isdecimal() and int(backend) > 1:
    subprocess.run(['prlimit','--pid',backend,'--memlock=unlimited:unlimited'],check=True)
print('Memlock limits installed and live launcher limit raised. No model restarted.')

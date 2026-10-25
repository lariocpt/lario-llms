#!/usr/bin/env python3
"""Install the optional mini-mobile vision owner; preserve credentials and active work."""
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from shared.serving.provision_control import private


def install():
    reg = json.loads((ROOT/'rtx3060ti/models.json').read_text())
    if socket.gethostname().split('.')[0] != reg['host']:
        raise RuntimeError('run on the registered mini-mobile owner')
    mount = Path('/mnt/xfs')
    if not mount.is_mount():
        raise RuntimeError('mount XFS model storage before provisioning')
    store = mount/'AI_Models'
    if not (store/'bin/llama-swap').is_file():
        raise RuntimeError('stage the pinned llama-swap binary on XFS first')
    python = store/'admission/venv/bin/python'
    if not python.exists():
        subprocess.run([sys.executable, '-m', 'venv', str(python.parents[1])], check=True)
        subprocess.run([str(python), '-m', 'pip', 'install', '-r',
                        str(ROOT/'shared/admission/requirements.txt')], check=True)
    directory = Path.home()/'.config/lario-admission'
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    env_path = directory/'rtx3060ti.env'
    env = dict(line.split('=', 1) for line in env_path.read_text().splitlines()
               if '=' in line) if env_path.exists() else {}
    key_path = directory/'rtx3060ti.backend.key'
    if key_path.exists():
        key = key_path.read_text().strip()
        if env.get('LARIO_BACKEND_KEY', key) != key:
            raise RuntimeError('backend key mismatch; refusing to rotate a running backend')
        env['LARIO_BACKEND_KEY'] = key
    for role in ('INTERACTIVE', 'FLEET', 'AUXILIARY', 'MANAGEMENT', 'BACKEND'):
        env.setdefault('LARIO_'+role+'_KEY', secrets.token_urlsafe(36))
    env.update(LARIO_ADMISSION_ENABLED='1', LARIO_FIXED_PROFILES='1',
               LARIO_UPSTREAM='http://127.0.0.1:11448', LARIO_PUBLIC_PORT='11438',
               LARIO_LISTEN='0.0.0.0')
    # Never rotate credentials when reapplying machine setup.
    private(env_path, ''.join(k+'='+v+'\n' for k, v in env.items()))
    private(key_path, env['LARIO_BACKEND_KEY']+'\n')
    private(directory/'rtx3060ti.backend.env', 'LARIO_BACKEND_KEY='+env['LARIO_BACKEND_KEY']+'\n')
    units = Path.home()/'.config/systemd/user'
    units.mkdir(parents=True, exist_ok=True)
    template = (ROOT/'shared/admission/systemd/lario-admission@.service').read_text()
    files = {'rtx3060ti.service': (ROOT/'rtx3060ti/systemd/rtx3060ti.service').read_text(),
             'lario-admission@.service': template.replace('@MODEL_MOUNT@', str(store)).replace('@PYTHON@', str(python))}
    for name in ('lario-backend-watch.service', 'lario-backend-watch.timer'):
        files[name] = (ROOT/'shared/systemd'/name).read_text()
    for name, text in files.items():
        target = units/name
        if not target.exists() or target.read_text() != text:
            target.write_text(text)
            target.chmod(0o644)
    subprocess.run(['systemctl', '--user', 'daemon-reload'], check=True)
    subprocess.run(['systemctl', '--user', 'enable', 'rtx3060ti.service',
                    'lario-admission@rtx3060ti.service', 'lario-backend-watch.timer'], check=True)
    # Starting an active unit is a no-op; ExecCondition skips an absent card or durable Off.
    subprocess.run(['systemctl', '--user', 'start', 'lario-admission@rtx3060ti.service',
                    'rtx3060ti.service', 'lario-backend-watch.timer'], check=True)
    print('RTX 3060 Ti owner installed; absent GPU skips serving, recovery retries every minute.')


if __name__ == '__main__':
    install()

#!/usr/bin/env python3
"""First installation of Arc-only backend/gateway; never touches other owners."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from shared.gpu import intel_arc_device
from shared.admission.provision import private_write
from shared.serving.catalog import profiles,render_backend,legacy_routes
from shared.serving.state import Store,state_directory


def wait_for_device(seconds=0):
    """Keep device checks strict while allowing render-node readiness at boot."""
    deadline=time.monotonic()+seconds
    while True:
        try:
            return intel_arc_device()
        except RuntimeError:
            remaining=deadline-time.monotonic()
            if remaining<=0:raise
            time.sleep(min(1,remaining))


def install():
    if socket.gethostname().split('.')[0]!='bigcachy':raise RuntimeError('run on Bigcachy')
    print('Arc device:',intel_arc_device(),flush=True)
    reg=json.loads((ROOT/'arcB70/models.json').read_text())
    private=Path.home()/'.config/lario-admission';private.mkdir(parents=True,exist_ok=True,mode=0o700)
    envfile=private/'arcB70.env'
    if envfile.exists():raise RuntimeError('Arc already provisioned; preserve credentials and use owner controls')
    weights=Path('/mnt/xfs/AI_Models/gguf/qwen3.8')/reg['models']['qwen3.8-smart-q4-256k']['weights']['filename']
    expected=reg['models']['qwen3.8-smart-q4-256k']['weights']
    if weights.stat().st_size!=expected['bytes']:raise RuntimeError('weight size mismatch')
    h=hashlib.sha256()
    with weights.open('rb') as f:
        for part in iter(lambda:f.read(16*1024*1024),b''):h.update(part)
    if h.hexdigest()!=expected['sha256']:raise RuntimeError('weight checksum mismatch')
    print('Pinned Q4 weight checksum verified',flush=True)
    binary=Path(reg['binary']);binary.parent.mkdir(parents=True,exist_ok=True)
    if binary.exists() or binary.is_symlink():raise RuntimeError('preserve existing Arc launcher before installation')
    # Validate the prepared Arc-only runtime before creating credentials/units.
    subprocess.run([str(ROOT/'arcB70/llama-server-sycl'),'--list-devices'],check=True)
    binary.symlink_to(ROOT/'arcB70/llama-server-sycl')
    env={'LARIO_'+role+'_KEY':secrets.token_urlsafe(36) for role in ('INTERACTIVE','FLEET','AUXILIARY','MANAGEMENT','BACKEND')}
    env.update(LARIO_ADMISSION_ENABLED='1',LARIO_FIXED_PROFILES='1',LARIO_LISTEN='0.0.0.0',
               LARIO_UPSTREAM='http://127.0.0.1:11447',LARIO_PUBLIC_PORT='11437')
    clients={machine:{'role':'interactive','key':secrets.token_urlsafe(36)} for machine in ('bigcachy','l-dev-ai','mini-mobile')}
    private_write(private/'arcB70.clients.json',json.dumps(clients,indent=2)+'\n')
    private_write(envfile,'\n'.join(k+'='+v for k,v in env.items())+'\n')
    private_write(Path(reg['backend_key_file']),env['LARIO_BACKEND_KEY']+'\n')
    private_write(ROOT/reg['config'],render_backend(reg))
    key='qwen3.8-smart-q4-256k';preset='prepared'
    from shared.modelctl import save_selection
    save_selection(reg,key,preset)
    entries=profiles(reg)
    selected=next(p['id'] for p in entries.values() if p['model']==key)
    store=Store(state_directory(reg),legacy_routes(reg,key,preset))
    store.change(disabled=[identifier for identifier in entries if identifier!=selected]);store.close()
    units=Path.home()/'.config/systemd/user'
    backend='''[Unit]
Description=Arc B70 exclusive model backend (native SYCL)
After=network-online.target
RequiresMountsFor=/mnt/xfs/AI_Models
[Service]
EnvironmentFile=%h/.config/lario-admission/arcB70.env
ExecCondition=/usr/bin/python3 %h/Projects/personal/lario-llms/shared/boot_ready.py arcB70
ExecCondition=/usr/bin/python3 %h/Projects/personal/lario-llms/arcB70/install.py --check-device --wait-device-seconds 60
ExecStartPre=/usr/bin/python3 %h/Projects/personal/lario-llms/shared/serving/configure.py arcB70
ExecStart=%h/.local/bin/llama-swap -config %h/Projects/personal/lario-llms/llama-cpp/arcB70-config.yaml -listen 127.0.0.1:11447
Restart=on-failure
RestartSec=5
TimeoutStartSec=1860
[Install]
WantedBy=default.target
'''
    private_write(units/'arcB70.service',backend);(units/'arcB70.service').chmod(0o644)
    # Dedicated instance avoids rewriting any existing gateway template/unit.
    gateway=(ROOT/'shared/admission/systemd/lario-admission@.service').read_text().replace('@MODEL_MOUNT@','/mnt/xfs/AI_Models').replace('@PYTHON@','/mnt/xfs/AI_Models/admission/venv/bin/python').replace('%i','arcB70')
    private_write(units/'lario-admission@arcB70.service',gateway);(units/'lario-admission@arcB70.service').chmod(0o644)
    subprocess.run(['systemctl','--user','daemon-reload'],check=True)
    subprocess.run(['systemctl','--user','enable','--now','arcB70.service','lario-admission@arcB70.service'],check=True)
    print('Arc-only backend/gateway installed; first profile '+selected,flush=True)


def install_panel():
    private=Path.home()/'.config/lario-admission'
    env=dict(line.split('=',1) for line in (private/'arcB70.env').read_text().splitlines() if '=' in line)
    path=Path.home()/'.config/lario-model-control/panel.json'
    config=json.loads(path.read_text())
    config.setdefault('owners',{})['arcB70']={'url':'http://100.127.91.5:11437','management_key':env['LARIO_MANAGEMENT_KEY']}
    private_write(path,json.dumps(config,indent=2)+'\n')
    print('Private panel owner entry installed; rebuild/recreate the UI to load it')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--check-device',action='store_true');parser.add_argument('--panel',action='store_true');parser.add_argument('--wait-device-seconds',type=int,choices=range(0,121),default=0);args=parser.parse_args()
    if args.panel:install_panel()
    elif args.check_device:wait_for_device(args.wait_device_seconds)
    else:install()

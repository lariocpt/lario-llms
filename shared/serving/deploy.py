#!/usr/bin/env python3
"""Deploy one owner's fixed catalog only after closing and checking idle admission."""
import argparse
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import time
import urllib.request

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from shared import modelctl
from shared.serving.catalog import OWNER_HARDWARE as HARDWARE, profiles, render_backend
from shared.serving.state import off_marker
from shared.admission.provision import private_write


def command(*args):
    subprocess.run(list(args),check=True,stdout=subprocess.DEVNULL)


def deploy(hardware, prepare=False):
    reg=json.loads((ROOT/hardware/'models.json').read_text())
    if socket.gethostname().split('.')[0]!=reg['host']:
        raise RuntimeError('run on the registered hardware owner')
    private=Path.home()/'.config/lario-admission'
    private.mkdir(parents=True,exist_ok=True,mode=0o700)
    env_path=private/(hardware+'.env')
    env=dict(line.split('=',1) for line in env_path.read_text().splitlines() if '=' in line) if env_path.exists() else {}
    clients_path=private/'clients.json'
    clients=json.loads(clients_path.read_text()) if clients_path.exists() else {}
    # Preserve the currently deployed consumer key, including on legacy Geekom.
    client_key=clients.get(hardware,{}).get('apiKey')
    if not client_key:
        import importlib.util
        rp=ROOT.parent/'machine-setup/scripts/render-agent-configs.py'
        spec=importlib.util.spec_from_file_location('renderer',rp)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        path=Path.home()/'.config/opencode/opencode.json'
        if not path.exists():path=path.with_suffix('.jsonc')
        client_key=module.load_jsonc(str(path))['provider'][hardware]['options']['apiKey']
    role='auxiliary' if hardware=='rtx5080' else 'interactive'
    if not isinstance(client_key,str) or len(client_key)<24 or client_key.startswith('{'):
        raise RuntimeError('a literal existing consumer key is required')
    for name in ('INTERACTIVE','FLEET','AUXILIARY','MANAGEMENT','BACKEND'):
        env.setdefault('LARIO_'+name+'_KEY',secrets.token_urlsafe(36))
    env['LARIO_'+role.upper()+'_KEY']=client_key
    env.update(LARIO_ADMISSION_ENABLED='1',LARIO_FIXED_PROFILES='1',
               LARIO_UPSTREAM=f'http://127.0.0.1:{reg["backend_port"]}',
               LARIO_PUBLIC_PORT=str(reg['port']),LARIO_LISTEN='0.0.0.0')
    text='\n'.join(k+'='+v for k,v in env.items())+'\n'
    prepared=private/(hardware+'-fixed-prepared')
    private_write(prepared/'owner.env',text)
    private_write(prepared/'backend.key',env['LARIO_BACKEND_KEY']+'\n')
    private_write(prepared/'backend.yaml',render_backend(reg))
    if prepare:
        print(f'{hardware}: prepared {len(profiles(reg))} fixed profiles; no running service changed')
        return
    modelctl.load_runtime(reg)
    gateway='lario-admission@'+hardware+'.service'
    active=subprocess.run(['systemctl','--user','is-active','--quiet',gateway]).returncode==0
    if active:
        modelctl.admission_admin(reg,'drain')
    # A failed check leaves active admission drained and never stops the backend.
    modelctl.assert_not_held(reg)
    modelctl.assert_device_ready(reg)
    was_backend_active=subprocess.run(['systemctl','--user','is-active','--quiet',reg['service']]).returncode==0
    if was_backend_active:modelctl.assert_idle(reg)
    keep_off=not was_backend_active
    backup=private/('fixed-backup-'+hardware+'-'+str(time.time_ns()))
    backup.mkdir(mode=0o700)
    units=Path.home()/'.config/systemd/user'
    mount='/mnt/AI_Models' if hardware=='geekom' else '/mnt/xfs/AI_Models'
    python=mount+'/admission/venv/bin/python'
    template=(ROOT/'shared/admission/systemd/lario-admission@.service').read_text()
    files={env_path:text,private/(hardware+'.backend.key'):env['LARIO_BACKEND_KEY']+'\n',
           ROOT/reg['config']:render_backend(reg),
           units/'lario-admission@.service':template.replace('@MODEL_MOUNT@',mount).replace('@PYTHON@',python)}
    dropin=units/(reg['service']+'.d')/'70-fixed-profiles.conf'
    content=('[Service]\nEnvironmentFile=%h/.config/lario-admission/'+hardware+'.env\n'
             'ExecCondition=/usr/bin/python3 %h/Projects/personal/lario-llms/shared/boot_ready.py '+hardware+'\n'
             'ExecStartPre=\nExecStartPre=/usr/bin/python3 %h/Projects/personal/lario-llms/shared/serving/configure.py '+hardware+'\n'
             'ExecStartPost=\n')
    if hardware=='geekom':
        content+=('ExecStart=\nExecStart=%h/.local/bin/llama-swap -config %h/Projects/personal/lario-llms/'+reg['config']+
                  ' -listen 127.0.0.1:'+str(reg['backend_port'])+'\n')
    files[dropin]=content
    originals={str(p):p.read_bytes() if p.exists() else None for p in files}
    for i,(name,data) in enumerate(originals.items()):
        if data is not None:private_write(backup/str(i),data.decode())
    private_write(backup/'manifest.json',json.dumps({p:i for i,p in enumerate(originals)}))
    try:
        # Stop idle backend first; its public legacy listener then cannot accept
        # a request during the configuration rewrite.
        command('systemctl','--user','stop',reg['service'])
        if active:command('systemctl','--user','stop',gateway)
        for path,value in files.items():
            private_write(path,value)
            if path.is_relative_to(units):path.chmod(0o644)
        command('systemctl','--user','daemon-reload')
        if keep_off:
            modelctl.atomic(off_marker(reg),'Preserved disabled backend during fixed-profile migration.\n')
        else:
            command('systemctl','--user','start',reg['service'])
        command('systemctl','--user','enable','--now',gateway)
        for _ in range(30):
            try:
                request=urllib.request.Request(f'http://127.0.0.1:{reg["port"]}/v1/models',
                      headers={'Authorization':'Bearer '+client_key})
                with urllib.request.urlopen(request,timeout=3) as response:data=json.load(response)
                if {x['id'] for x in data['data']}==set(profiles(reg)):break
            except OSError:pass
            time.sleep(1)
        else:raise RuntimeError('fixed catalog did not become reachable')
        private_write(private/(hardware+'.fixed.json'),json.dumps({'hardware':hardware,'profiles':len(data['data']),
                      'backup':str(backup),'status':'fixed catalog active; inference smoke pending'}))
        print(f'{hardware}: {len(data["data"])} fixed profiles available; backend remains cold until requested')
    except BaseException:
        # Restore both binaries' configuration, not a mixture of routing and keys.
        subprocess.run(['systemctl','--user','stop',gateway,reg['service']],stdout=subprocess.DEVNULL)
        for name,data in originals.items():
            p=Path(name)
            if data is None:p.unlink(missing_ok=True)
            else:private_write(p,data.decode())
        command('systemctl','--user','daemon-reload')
        if was_backend_active:command('systemctl','--user','start',reg['service'])
        if active:command('systemctl','--user','start',gateway)
        raise


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('hardware',choices=HARDWARE)
    parser.add_argument('--prepare',action='store_true')
    args=parser.parse_args();deploy(args.hardware,args.prepare)

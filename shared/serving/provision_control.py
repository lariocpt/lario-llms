#!/usr/bin/env python3
"""Provision private operator credentials and client-scoped inference keys. Never print keys."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import shlex
import shutil
import socket
import subprocess
import sys
import time
import urllib.request

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from shared import modelctl

HOSTS={'bigcachy':'bigcachy','l-dev-ai':'l-dev-ai','mini-mobile':'cachyos-mini-mobile'}
IPS={'bigcachy':'100.127.91.5','l-dev-ai':'100.68.129.20','mini-mobile':'100.103.22.121'}
HARDWARE=('geekom','7900xt','rtx5080')


def private(path,value):
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    tmp=path.with_name(path.name+'.new')
    fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    with os.fdopen(fd,'w') as f:f.write(value)
    tmp.chmod(0o600);tmp.replace(path)


def invoke(host,args,payload=None):
    command=['python3',str(ROOT/'shared/serving/provision_control.py'),*args]
    if socket.gethostname().split('.')[0]!=host:
        command=['ssh','-T','-o','BatchMode=yes','-o','ConnectTimeout=8',host,shlex.join(command)]
    result=subprocess.run(command,input=json.dumps(payload) if payload is not None else None,
                          text=True,capture_output=True,timeout=180)
    if result.returncode:raise RuntimeError('Provisioning failed on '+host+': '+result.stderr[-250:])
    # Render/reload subprocesses can emit progress before the final protocol
    # record. The private transport result is always one JSON line at the end.
    lines=result.stdout.strip().splitlines()
    if not lines:raise RuntimeError('Provisioning returned no result on '+host)
    return json.loads(lines[-1])


def owner(hardware,register=False):
    reg=json.loads((ROOT/hardware/'models.json').read_text())
    if socket.gethostname().split('.')[0]!=reg['host']:raise RuntimeError('wrong hardware owner')
    modelctl.load_runtime(reg)
    result={'management_key':os.environ['LARIO_MANAGEMENT_KEY'],'port':reg['port']}
    if register:
        path=Path.home()/'.config/lario-admission'/(hardware+'.clients.json')
        clients=json.loads(path.read_text()) if path.exists() else {}
        for name in HOSTS:
            clients.setdefault(name,{'role':'auxiliary' if hardware=='rtx5080' else 'interactive','key':secrets.token_urlsafe(36)})
        private(path,json.dumps(clients,indent=2)+'\n')
        result['clients']={name:clients[name]['key'] for name in HOSTS}
    return result


def install_client(machine,body):
    if socket.gethostname().split('.')[0]!=HOSTS[machine]:raise RuntimeError('wrong client host')
    # Never replace working keys until every target gateway accepts its scoped key.
    for hardware,key in body['keys'].items():
        owner_machine={'geekom':'l-dev-ai','7900xt':'mini-mobile','rtx5080':'bigcachy'}[hardware]
        reg=json.loads((ROOT/hardware/'models.json').read_text())
        request=urllib.request.Request(f'http://{IPS[owner_machine]}:{reg["port"]}/v1/models',headers={'Authorization':'Bearer '+key})
        with urllib.request.urlopen(request,timeout=10) as response:
            if response.status!=200:raise RuntimeError('registered gateway credential not ready')
    path=Path.home()/'.config/lario-admission/clients.json'
    data=json.loads(path.read_text()) if path.exists() else {}
    if path.exists():private(path.with_name(path.name+'.before-identity-'+str(time.time_ns())),path.read_text())
    for hardware,key in body['keys'].items():
        data.setdefault(hardware,{})['apiKey']=key
        data[hardware].pop('context_limits',None)
    private(path,json.dumps(data,indent=2)+'\n')
    helper=ROOT.parent/'machine-setup/shared/agents/model_client_control.py'
    if not helper.is_file():raise RuntimeError('machine-setup client control helper missing')
    key=body['public_key'].strip()
    if not key.startswith('ssh-ed25519 ') or '\n' in key:raise ValueError('invalid control public key')
    authorized=Path.home()/'.ssh/authorized_keys'
    old=authorized.read_text() if authorized.exists() else ''
    line='restrict,command="python3 '+str(helper)+'" '+key
    if key.split()[1] not in old:
        private(authorized,old.rstrip()+'\n'+line+'\n')
    from shared.serving.clients import live
    live(machine)
    return {'machine':machine,'installed':True}


def prepare(register=False,clients=False):
    if socket.gethostname().split('.')[0]!='bigcachy':raise RuntimeError('run central provisioning on bigcachy')
    directory=Path.home()/'.config/lario-model-control';directory.mkdir(parents=True,exist_ok=True,mode=0o700)
    directory.chmod(0o700)
    key=directory/'client-control-key'
    if not key.exists():
        subprocess.run(['ssh-keygen','-q','-t','ed25519','-N','','-C','lario-model-control','-f',str(key)],check=True)
    # Pin only the three registered hosts, including their tailnet addresses.
    # Fetch public keys through already verified operator SSH, never ssh-keyscan
    # or a first-use trust bypass. The local host's public key is read directly.
    pins=[]
    for name,host in HOSTS.items():
        if socket.gethostname().split('.')[0]==host:
            public=Path('/etc/ssh/ssh_host_ed25519_key.pub').read_text()
        else:
            result=subprocess.run(['ssh','-T','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes',
                '-o','ConnectTimeout=8',host,'cat /etc/ssh/ssh_host_ed25519_key.pub'],
                text=True,capture_output=True,timeout=15,check=True)
            public=result.stdout
        fields=public.strip().split()
        if len(fields)<2 or fields[0]!='ssh-ed25519':raise ValueError('unexpected host public key')
        pins.append(IPS[name]+' '+fields[0]+' '+fields[1])
    private(directory/'known_hosts','\n'.join(pins)+'\n')
    config_path=directory/'panel.json'
    config=json.loads(config_path.read_text()) if config_path.exists() else {}
    if 'password_hash' not in config:
        password=secrets.token_urlsafe(24);salt=secrets.token_hex(16)
        digest=hashlib.scrypt(password.encode(),salt=bytes.fromhex(salt),n=16384,r=8,p=1).hex()
        config.update(username='lario',password_salt=salt,password_hash=digest)
        private(directory/'operator-password',password+'\n')
    config.update(origin='https://models.in.drlario.org',owners={},clients={},
                  ssh_key='/config/client-control-key',ssh_known_hosts='/config/known_hosts')
    client_keys={name:{} for name in HOSTS}
    for hardware in HARDWARE:
        reg=json.loads((ROOT/hardware/'models.json').read_text())
        info=invoke(reg['host'],['owner-register' if register else 'owner-info',hardware])
        owner_machine={'geekom':'l-dev-ai','7900xt':'mini-mobile','rtx5080':'bigcachy'}[hardware]
        config['owners'][hardware]={'url':f'http://{IPS[owner_machine]}:{info["port"]}','management_key':info['management_key']}
        if register:
            for name in HOSTS:client_keys[name][hardware]=info['clients'][name]
    for name in HOSTS:config['clients'][name]={'host':'lario@'+IPS[name]}
    private(config_path,json.dumps(config,indent=2)+'\n')
    state=Path('/mnt/xfs/AI_Models/control/panel');state.mkdir(parents=True,exist_ok=True,mode=0o700);state.chmod(0o700)
    if clients:
        if not register:raise ValueError('register before installing client keys')
        public=key.with_suffix('.pub').read_text()
        for name,host in HOSTS.items():
            invoke(host,['client-install',name],{'keys':client_keys[name],'public_key':public})
            print(name+': registered keys, identity plugin and read-only model tools installed')
    print('Private operator configuration prepared; password remains in ~/.config/lario-model-control/operator-password')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['prepare','register','install','owner-register','owner-info','client-install'])
    parser.add_argument('target',nargs='?')
    args=parser.parse_args()
    if args.action.startswith('owner-'):
        print(json.dumps(owner(args.target,args.action=='owner-register')))
    elif args.action=='client-install':
        # Keep Python progress separate; subprocess progress may precede the
        # final JSON record and is handled by invoke().
        import contextlib
        with contextlib.redirect_stdout(sys.stderr):result=install_client(args.target,json.load(sys.stdin))
        print(json.dumps(result))
    else:prepare(register=args.action in ('register','install'),clients=args.action=='install')

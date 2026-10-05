#!/usr/bin/env python3
"""Activate prepared native admission artifacts with idle refusal and file rollback."""
import argparse
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from shared import modelctl
from shared.admission.provision import private_write


def command(*arguments):
    subprocess.run(list(arguments),check=True,stdout=subprocess.DEVNULL)


def activate(directory,dry=False):
    manifest=json.loads((directory/'deployment.json').read_text())
    hardware=manifest['hardware']
    reg=json.loads((ROOT/hardware/'models.json').read_text())
    if hardware=='7900xt':
        raise RuntimeError('Radeon deployment requires the separately guarded container rollout; native activation cannot recreate it')
    if socket.gethostname().split('.')[0]!=reg['host']:raise RuntimeError('run activation on the hardware owner')
    modelctl.assert_not_held(reg)
    modelctl.assert_device_ready(reg)
    expected=modelctl.render(reg,manifest['model'],manifest['preset'],True)
    if (directory/'backend.yaml').read_text()!=expected:raise RuntimeError('prepared configuration differs from the current registry')
    credentials=json.loads((directory/'private/credentials.json').read_text())
    from shared.admission.server import create_app
    create_app(reg,'http://127.0.0.1:'+str(reg['backend_port']),
               {key:credentials[key] for key in ['interactive','fleet','auxiliary','management']},credentials['backend'])
    modelctl.load_runtime(reg)
    modelctl.assert_idle(reg)
    private=Path.home()/'.config/lario-admission'
    # Roll out client credentials before activation. This check uses the managed
    # fragment, never prints keys, and deliberately refuses an unprepared owner.
    clients=json.loads((private/'clients.json').read_text())
    role='auxiliary' if hardware=='rtx5080' else 'interactive'
    if clients.get(hardware,{}).get('apiKey')!=credentials[role]:raise RuntimeError('owner client credential has not been distributed')
    live_path=Path.home()/'.config/opencode/opencode.json'
    if not live_path.exists():live_path=live_path.with_suffix('.jsonc')
    import importlib.util
    renderer_path=ROOT.parent/'machine-setup/scripts/render-agent-configs.py'
    spec=importlib.util.spec_from_file_location('client_renderer',renderer_path)
    renderer=importlib.util.module_from_spec(spec);spec.loader.exec_module(renderer)
    live=renderer.load_jsonc(str(live_path))
    if live.get('provider',{}).get(hardware,{}).get('options',{}).get('apiKey')!=credentials[role]:
        raise RuntimeError('owner OpenCode configuration has not been rendered with its credential')
    if hardware=='rtx5080':
        # Frontend credentials must already exist before touching the backend.
        frontend=dict(line.split('=',1) for line in (private/'rtx5080.front.env').read_text().splitlines() if '=' in line)
        if frontend.get('LARIO_AUXILIARY_KEY')!=credentials['auxiliary']:
            raise RuntimeError('vision frontend credential has not been provisioned')
    if dry:
        print('Validated native activation: released hold, idle hardware, current registry, private keys and owner client fragment. No mutations.')
        return
    user_units=Path.home()/'.config/systemd/user'
    target_unit=user_units/'lario-admission@.service'
    dropin=user_units/(reg['service']+'.d')/'50-lario-admission.conf'
    files={ROOT/reg['config']:expected,target_unit:(directory/'lario-admission@.service').read_text(),
           dropin:(ROOT/'shared/admission/systemd'/f'{hardware}-admission.conf').read_text()}
    for suffix in ['env','backend.key','front.env']:
        files[private/f'{hardware}.{suffix}']=(directory/'private'/f'{hardware}.{suffix}').read_text()
    states=[ROOT/reg['state'],ROOT/('.'+hardware+'-selection.json')]
    originals={path:path.read_bytes() if path.exists() else None for path in [*files,*states]}
    service='lario-admission@'+hardware+'.service'
    enabled=subprocess.run(['systemctl','--user','is-enabled',service],capture_output=True).returncode==0
    active=subprocess.run(['systemctl','--user','is-active',service],capture_output=True).returncode==0
    backup=Path(tempfile.mkdtemp(prefix='admission-rollback-',dir=private))
    os.chmod(backup,0o700)
    for i,(path,data) in enumerate(originals.items()):
        if data is not None:private_write(backup/str(i),data.decode())
    private_write(backup/'manifest.json',json.dumps({str(path):i for i,path in enumerate(originals)}))
    old_environment=dict(os.environ)
    try:
        command('systemctl','--user','stop',reg['service'])
        for path,text in files.items():
            private_write(path,text)
            if path in (target_unit,dropin):os.chmod(path,0o644)
        modelctl.save_selection(reg,manifest['model'],manifest['preset'])
        modelctl.load_runtime(reg)
        command('systemctl','--user','daemon-reload')
        command('systemctl','--user','start',reg['service'])
        modelctl.warm(reg,manifest['model'])
        command('systemctl','--user','restart',service)
        for attempt in range(30):
            try:
                with urllib.request.urlopen('http://127.0.0.1:'+str(reg['port'])+'/budget',timeout=5) as response:data=json.load(response)
                if data.get('ready') and data.get('enforced') and data.get('model')==manifest['model']:break
            except OSError:pass
            time.sleep(1)
        else:raise RuntimeError('admission did not become ready')
        if hardware=='rtx5080':
            command('docker','compose','--project-directory',str(ROOT),'-f',str(ROOT/'docker-compose.yml'),
                    '-f',str(ROOT/'docker-compose.bigcachy.yml'),'-f',str(ROOT/'shared/admission/compose/rtx5080.yml'),
                    'up','-d','--no-deps','vision')
        command('systemctl','--user','enable',service)
        private_write(private/(hardware+'.active.json'),json.dumps({**manifest,'status':'active','budget':data})+'\n')
        print(hardware+' admission active; Docker fronts and peer clients still require their rollout checks.')
    except BaseException:
        command('systemctl','--user','stop',service)
        command('systemctl','--user','stop',reg['service'])
        for path,data in originals.items():
            if data is None:path.unlink(missing_ok=True)
            else:private_write(path,data.decode())
        os.environ.clear();os.environ.update(old_environment)
        command('systemctl','--user','daemon-reload')
        command('systemctl','--user','start',reg['service'])
        if hardware=='rtx5080':
            command('docker','compose','--project-directory',str(ROOT),'-f',str(ROOT/'docker-compose.yml'),
                    '-f',str(ROOT/'docker-compose.bigcachy.yml'),'up','-d','--no-deps','vision')
        if not enabled:subprocess.run(['systemctl','--user','disable',service],stdout=subprocess.DEVNULL)
        if active:command('systemctl','--user','start',service)
        raise


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('prepared_directory',type=Path)
    parser.add_argument('--dry-run',action='store_true')
    args=parser.parse_args()
    activate(args.prepared_directory,args.dry_run)


if __name__=='__main__':main()

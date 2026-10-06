#!/usr/bin/env python3
"""Guarded first activation of Radeon admission; never touch the RTX frontend."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from shared import modelctl
from shared.admission.deploy import command
from shared.admission.provision import private_write


def validate_owner_client(private,credentials):
    clients=json.loads((private/'clients.json').read_text())
    if clients.get('7900xt',{}).get('apiKey')!=credentials['interactive']:
        raise RuntimeError('owner interactive credential has not been distributed')
    path=Path.home()/'.config/opencode/opencode.json'
    if not path.exists():path=path.with_suffix('.jsonc')
    spec=importlib.util.spec_from_file_location('client_renderer',
        ROOT.parent/'machine-setup/scripts/render-agent-configs.py')
    renderer=importlib.util.module_from_spec(spec);spec.loader.exec_module(renderer)
    live=renderer.load_jsonc(str(path))
    if live.get('provider',{}).get('7900xt',{}).get('options',{}).get('apiKey')!=credentials['interactive']:
        raise RuntimeError('owner OpenCode configuration lacks its interactive credential')
    frontend=dict(line.split('=',1) for line in (private/'7900xt.front.env').read_text().splitlines() if '=' in line)
    if frontend.get('LARIO_FLEET_KEY')!=credentials['fleet']:
        raise RuntimeError('Docker fleet frontend credential has not been distributed')


def compose(*arguments,admission=False):
    files=['docker-compose.yml','docker-compose.bigcachy.yml','docker-compose.intel.yml']
    if admission:files.append('shared/admission/compose/7900xt.yml')
    command('docker','compose','--project-directory',str(ROOT),
        *(part for file in files for part in ['-f',str(ROOT/file)]),*arguments)


def activate(directory,dry=False):
    manifest=json.loads((directory/'deployment.json').read_text())
    if manifest.get('hardware')!='7900xt':raise RuntimeError('container activator only supports Radeon')
    reg=json.loads((ROOT/'7900xt/models.json').read_text())
    if socket.gethostname().split('.')[0]!=reg['host']:raise RuntimeError('run activation on the hardware owner')
    modelctl.assert_not_held(reg)
    private=Path.home()/'.config/lario-admission'
    marker=private/'7900xt.active.json'
    if marker.exists():raise RuntimeError('admission already has an activation marker; use the hardware controller for changes')
    expected=modelctl.render(reg,manifest['model'],manifest['preset'],True)
    if (directory/'backend.yaml').read_text()!=expected:raise RuntimeError('prepared configuration differs from the current registry')
    credentials=json.loads((directory/'private/credentials.json').read_text())
    from shared.admission.server import create_app
    create_app(reg,'http://127.0.0.1:'+str(reg['backend_port']),
        {role:credentials[role] for role in ['interactive','fleet','auxiliary','management']},credentials['backend'])
    modelctl.load_runtime(reg)
    modelctl.assert_idle(reg)
    validate_owner_client(private,credentials)
    if dry:
        print('Validated Radeon first activation: released hold, idle hardware, registry, credentials and owner config. No mutations.')
        return
    unit=Path.home()/'.config/systemd/user/lario-admission@.service'
    files={ROOT/reg['config']:expected,unit:(directory/'lario-admission@.service').read_text()}
    for suffix in ['env','backend.env','backend.key','front.env']:
        files[private/f'7900xt.{suffix}']=(directory/'private'/f'7900xt.{suffix}').read_text()
    states=[ROOT/reg['state'],ROOT/'.7900xt-selection.json']
    originals={path:(path.read_bytes(),path.stat().st_mode&0o777) if path.exists() else None for path in [*files,*states]}
    service='lario-admission@7900xt.service'
    if subprocess.run(['systemctl','--user','is-active',service],capture_output=True).returncode==0:
        raise RuntimeError('existing gateway without an activation marker requires recovery, not first activation')
    enabled=subprocess.run(['systemctl','--user','is-enabled',service],capture_output=True).returncode==0
    backup=Path(tempfile.mkdtemp(prefix='7900xt-rollback-',dir=private));os.chmod(backup,0o700)
    for index,(path,value) in enumerate(originals.items()):
        if value is not None:private_write(backup/str(index),value[0].decode())
    private_write(backup/'manifest.json',json.dumps({str(path):{'index':index,'mode':value[1] if value else None}
        for index,(path,value) in enumerate(originals.items())})+'\n')
    old_environment=dict(os.environ)
    frontend_attempted=False
    try:
        modelctl.assert_idle(reg)
        command('docker','stop',reg['container'])
        for path,text in files.items():
            private_write(path,text)
            if path==unit:os.chmod(path,0o644)
        modelctl.save_selection(reg,manifest['model'],manifest['preset'])
        compose('up','-d','--no-deps','agent-llm',admission=True)
        modelctl.load_runtime(reg)
        modelctl.warm(reg,manifest['model'])
        command('systemctl','--user','daemon-reload')
        command('systemctl','--user','start',service)
        for attempt in range(30):
            try:
                with urllib.request.urlopen('http://127.0.0.1:'+str(reg['port'])+'/budget',timeout=5) as response:data=json.load(response)
                if data.get('ready') and data.get('enforced') and data.get('model')==manifest['model']:break
            except OSError:pass
            time.sleep(1)
        else:raise RuntimeError('Radeon gateway did not become ready')
        frontend_attempted=True
        compose('up','-d','--no-deps','agent-admission',admission=True)
        command('systemctl','--user','enable',service)
        private_write(marker,json.dumps({**manifest,'status':'active','budget':data})+'\n')
        print('7900xt admission active; peer caller and production bypass checks are still required.')
    except BaseException as original_error:
        failures=[]
        def recover(action):
            try:action();return True
            except Exception as error:failures.append(type(error).__name__);return False
        recover(lambda:command('systemctl','--user','stop',service))
        if frontend_attempted:recover(lambda:compose('rm','-s','-f','agent-admission',admission=True))
        marker.unlink(missing_ok=True)
        for path,value in originals.items():
            if value is None:path.unlink(missing_ok=True)
            else:
                private_write(path,value[0].decode());os.chmod(path,value[1])
        os.environ.clear();os.environ.update(old_environment)
        recover(lambda:command('systemctl','--user','daemon-reload'))
        restored=recover(lambda:compose('up','-d','--no-deps','--force-recreate','agent-llm'))
        if not enabled:recover(lambda:command('systemctl','--user','disable',service))
        previous_key,previous_preset=modelctl.selection(reg)
        if restored and previous_key in reg['models']:recover(lambda:modelctl.warm(reg,previous_key))
        if failures:
            raise RuntimeError('Radeon activation failed; rollback had errors '+','.join(failures)+
                '; private source backup retained at '+str(backup)) from original_error
        raise


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('prepared_directory',type=Path)
    parser.add_argument('--dry-run',action='store_true')
    args=parser.parse_args();activate(args.prepared_directory,args.dry_run)

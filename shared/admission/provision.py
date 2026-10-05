#!/usr/bin/env python3
"""Generate reviewed admission deployment artifacts; never stop/start a model."""
import argparse
import json
import os
from pathlib import Path
import secrets
import socket
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from shared.modelctl import render, selection, effective_models


def private_write(path,text):
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    # Create privately from the outset, including when the surrounding umask is lax.
    descriptor=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    os.fchmod(descriptor,0o600)
    with os.fdopen(descriptor,'w') as file:file.write(text)


def prepare(hardware,directory,listen,model=None,preset=None):
    directory=directory.resolve()
    if directory.is_relative_to(ROOT):raise ValueError('private preparation output must be outside the repository')
    reg=json.loads((ROOT/hardware/'models.json').read_text())
    if not listen or any(not value for value in listen):raise ValueError('explicit listen addresses required')
    model_saved,preset_saved=selection(reg)
    model=model or model_saved;preset=preset or preset_saved
    if model not in reg['models']:raise ValueError('explicit valid model required for an unset host')
    mount='/mnt/AI_Models' if hardware=='geekom' else '/mnt/xfs/AI_Models'
    python=mount+'/admission/venv/bin/python'
    private=directory/'private';private.mkdir(parents=True,exist_ok=True,mode=0o700)
    credentials_path=private/'credentials.json'
    credentials=json.loads(credentials_path.read_text()) if credentials_path.exists() else {
        role:secrets.token_urlsafe(36) for role in ['interactive','fleet','auxiliary','management','backend']}
    private_write(credentials_path,json.dumps(credentials,indent=2)+'\n')
    env={'LARIO_'+role.upper()+'_KEY':key for role,key in credentials.items()}
    env.update({'LARIO_ADMISSION_ENABLED':'1','LARIO_UPSTREAM':f'http://127.0.0.1:{reg["backend_port"]}',
                'LARIO_PUBLIC_PORT':str(reg['port']),'LARIO_LISTEN':','.join(listen)})
    private_write(private/(hardware+'.env'),'\n'.join(key+'='+value for key,value in env.items())+'\n')
    private_write(private/(hardware+'.backend.key'),credentials['backend']+'\n')
    private_write(private/(hardware+'.backend.env'),'LARIO_BACKEND_KEY='+credentials['backend']+'\n')
    front_role='auxiliary' if hardware=='rtx5080' else 'fleet'
    private_write(private/(hardware+'.front.env'),'LARIO_'+front_role.upper()+'_KEY='+credentials[front_role]+'\n')
    # This is an individual-host interactive-client fragment; deployments merge all
    # hardware entries privately rather than putting credentials in source overlays.
    client_role='auxiliary' if hardware=='rtx5080' else 'interactive'
    minimum=min(m['context'] for p in reg['presets'] if not reg['presets'][p].get('disabled_reason') for m in effective_models(reg,p).values())-4096
    limits={hardware:minimum}
    if hardware!='geekom':limits['qwen3.8']=minimum
    private_write(private/'clients.json',json.dumps({hardware:{'apiKey':credentials[client_role],
                  'context_limits':limits}})+'\n')
    template=(ROOT/'shared/admission/systemd/lario-admission@.service').read_text()
    (directory/'lario-admission@.service').write_text(template.replace('@MODEL_MOUNT@',mount).replace('@PYTHON@',python))
    (directory/'backend.yaml').write_text(render(reg,model,preset,True))
    (directory/'deployment.json').write_text(json.dumps({'hardware':hardware,'model':model,'preset':preset,
          'status':'prepared; not deployed','public_port':reg['port'],'backend_port':reg['backend_port'],
          'listen':listen,'host':reg['host']},indent=2)+'\n')
    return directory


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('hardware',choices=['geekom','7900xt','rtx5080'])
    parser.add_argument('--output',required=True)
    parser.add_argument('--listen',action='append',required=True)
    parser.add_argument('--model')
    parser.add_argument('--preset')
    args=parser.parse_args()
    path=prepare(args.hardware,Path(args.output),args.listen,args.model,args.preset)
    print(f'Prepared {args.hardware} artifacts in {path}. Credentials are private; no service action performed.')
    print('Activation requires idle checks, released user holds, private backend binding and client credential distribution.')


if __name__=='__main__':main()

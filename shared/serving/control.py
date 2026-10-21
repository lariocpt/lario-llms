#!/usr/bin/env python3
"""Operator controls for fixed model hardware. Credentials remain on its owner."""
import argparse
import json
from pathlib import Path
import shlex
import socket
import subprocess
import sys
import urllib.request
import uuid

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from shared import modelctl
from shared.serving.catalog import HARDWARE


def request(reg,path,body=None):
    modelctl.load_runtime(reg)
    import os
    r=urllib.request.Request(f'http://127.0.0.1:{reg["port"]}/admin/v1/'+path,
          data=json.dumps(body).encode() if body is not None else None,
          headers={'Authorization':'Bearer '+os.environ['LARIO_MANAGEMENT_KEY'],'Content-Type':'application/json'})
    with urllib.request.urlopen(r,timeout=1900) as response:return json.load(response)


def operate(hardware,action,profile=None):
    reg=json.loads((ROOT/hardware/'models.json').read_text())
    if socket.gethostname().split('.')[0]!=reg['host']:
        args=['python3','Projects/personal/lario-llms/shared/serving/control.py',hardware,action]
        if profile:args+=['--profile',profile]
        subprocess.run(['ssh','-T','-o','BatchMode=yes','-o','ConnectTimeout=8',reg['host'],shlex.join(args)],check=True)
        return
    if action in ('status','catalog'):
        return request(reg,'state' if action=='status' else 'catalog')
    state=request(reg,'state')
    body={'action':action,'expected_revision':state['revision'],'idempotency_key':uuid.uuid4().hex}
    if profile:body['profile_id']=profile
    return request(reg,'operations',body)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('hardware',choices=HARDWARE)
    p.add_argument('action',choices=['status','catalog','on','off','pause','resume','cancel-all','cancel-and-off','enable','disable'])
    p.add_argument('--profile')
    a=p.parse_args();result=operate(a.hardware,a.action,a.profile)
    if result is not None:print(json.dumps(result,indent=2))

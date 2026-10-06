#!/usr/bin/env python3
"""Verify an activated native gate, private listeners and real workload contention."""
import argparse
from datetime import datetime,timezone
import ipaddress
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.error
from urllib.parse import urlparse

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from shared import modelctl
from shared.admission.canary import read,occupy_capacity


def verify(hardware,output):
    reg=json.loads((ROOT/hardware/'models.json').read_text())
    if socket.gethostname().split('.')[0]!=reg['host']:raise RuntimeError('run verification on the hardware owner')
    modelctl.load_runtime(reg)
    if os.environ.get('LARIO_ADMISSION_ENABLED')!='1':raise RuntimeError('production admission is not activated')
    modelctl.assert_idle(reg)
    before=modelctl.api(reg,'/running')
    if len(before.get('running',[]))!=1:raise RuntimeError('exactly one resident required')
    item=before['running'][0];model=item['model'];base=f'http://127.0.0.1:{reg["port"]}'
    with read(base+'/budget') as response:budget=json.load(response)
    if not budget.get('ready') or not budget.get('enforced'):raise RuntimeError('live enforced budget not ready')
    keys={role:os.environ['LARIO_'+role.upper()+'_KEY'] for role in ('interactive','fleet','auxiliary','management','backend')}
    records=[];streams=[]
    result={'timestamp_utc':datetime.now(timezone.utc).isoformat(),'hardware':hardware,'mode':'actual activated public gateway',
            'before':budget,'checks':records,'passed':False}
    def check(name,passed,**details):
        records.append({'check':name,'passed':bool(passed),**details})
        modelctl.atomic(output,json.dumps(result,indent=2)+'\n')
    body={'model':model,'messages':[{'role':'user','content':'Count from 1 to 10000 without skipping any numbers.'}],
          'stream':True,'max_tokens':1024 if hardware=='rtx5080' else 256,
          'temperature':0,'chat_template_kwargs':{'enable_thinking':False}}
    def request(role,selected=model):return read(base+'/v1/chat/completions',{**body,'model':selected},keys.get(role))
    def rejection(role,status,selected=model,url=None,key=None):
        try:
            response=request(role,selected) if url is None else read(url,body,key)
            actual=response.status;response.close()
        except urllib.error.HTTPError as error:actual=error.code;error.close()
        check(role+' rejection '+str(status),actual==status,status=actual)
    try:
        rejection('unknown',401)
        rejection('management',403)
        rejection('auxiliary',409,selected='not-a-resident-model')
        rejection('auxiliary',404,url=base+'/upstream/'+model+'/v1/chat/completions',key=keys['auxiliary'])
        private=f'http://127.0.0.1:{reg["backend_port"]}/v1/chat/completions'
        rejection('consumer cannot bypass backend',401,url=private,key=keys['auxiliary'])
        child=item['proxy'].rstrip('/')+'/v1/chat/completions'
        rejection('consumer cannot bypass child',401,url=child,key=keys['auxiliary'])
        addresses=subprocess.check_output(['ss','-H','-ltn'],text=True).splitlines()
        for label,port in [('proxy',reg['backend_port']),('child',urlparse(item['proxy']).port)]:
            listeners=[line.split()[3] for line in addresses if line.split()[3].endswith(':'+str(port))]
            check(label+' loopback-only listener',bool(listeners) and all(ipaddress.ip_address(address.rsplit(':',1)[0].strip('[]')).is_loopback for address in listeners),listeners=listeners)
        role,first=occupy_capacity(hardware,budget,request,rejection,streams)
        with read(base+'/budget') as response:occupied=json.load(response)
        check('actual public slots accounted',sum(occupied.get('active',{}).values())==budget['slots'],active=occupied.get('active'))
        if hardware=='rtx5080':
            # The private Docker frontend must share the same gate/auxiliary slot.
            code="import json,urllib.request,urllib.error; req=urllib.request.Request('http://vision:8080/v1/chat/completions',data="+repr(json.dumps({**body,'stream':False,'max_tokens':2}).encode())+",headers={'Content-Type':'application/json'});\ntry:\n r=urllib.request.urlopen(req,timeout=15);print(r.status);r.close()\nexcept urllib.error.HTTPError as e:\n print(e.code);e.close()"
            frontend=subprocess.run(['docker','run','--rm','--network','lario-net','--entrypoint','python','lario/hermes-agent:scrape','-c',code],capture_output=True,text=True,timeout=30)
            check('Docker vision shares auxiliary capacity',frontend.returncode==0 and frontend.stdout.strip()=='429',status=frontend.stdout.strip() if frontend.stdout.strip().isdigit() else None)
        # Disconnect one owned request; keep capacity quarantined until native idle.
        first.readline();first.close()
        for response in streams[1:]:response.read();response.close()
        for _ in range(300):
            with read(base+'/budget') as response:recovered=json.load(response)
            if recovered.get('ready') and not sum(recovered.get('active',{}).values()):break
            time.sleep(.2)
        else:raise RuntimeError('production occupancy did not recover after disconnect')
        check('public disconnect reconciled without model restart',True)
        with request(role) as response:response.read()
        modelctl.assert_idle(reg)
        after=modelctl.api(reg,'/running')
        check('resident unchanged',before==after)
        result['passed']=all(row['passed'] for row in records)
    except Exception as error:
        result['error_type']=type(error).__name__
        raise
    finally:
        for response in streams:response.close()
        modelctl.atomic(output,json.dumps(result,indent=2)+'\n')
    print(json.dumps(result))
    if not result['passed']:raise SystemExit(1)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('hardware',choices=['geekom','rtx5080'])
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args();args.output.parent.mkdir(parents=True,exist_ok=True);verify(args.hardware,args.output)

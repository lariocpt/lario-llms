#!/usr/bin/env python3
"""Bounded shadow-gateway validation; public backend remains advisory and untouched."""
import argparse
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from shared import modelctl


def read(url,body=None,key=None):
    headers={'Content-Type':'application/json'}
    if key:headers['Authorization']='Bearer '+key
    request=urllib.request.Request(url,data=None if body is None else json.dumps(body).encode(),headers=headers)
    return urllib.request.urlopen(request,timeout=30)


def run(hardware,credentials_file,port,output):
    reg=json.loads((ROOT/hardware/'models.json').read_text())
    if socket.gethostname().split('.')[0]!=reg['host']:raise RuntimeError('run the canary on its hardware owner')
    modelctl.assert_not_held(reg)
    modelctl.assert_device_ready(reg)
    modelctl.load_runtime(reg)
    modelctl.assert_idle(reg)
    credentials=json.loads(credentials_file.read_text())
    backend_port=reg['backend_port'] if os.environ.get('LARIO_ADMISSION_ENABLED')=='1' else reg['port']
    if port in (reg['port'],reg['backend_port']) or not 1024<=port<=65535:raise ValueError('separate shadow port required')
    with read(f'http://127.0.0.1:{backend_port}/running',key=os.environ.get('LARIO_BACKEND_KEY')) as response:
        before=json.load(response)
    if len(before.get('running',[]))!=1:raise RuntimeError('one resident model required')
    model=before['running'][0]['model']
    environment={**os.environ,**{'LARIO_'+role.upper()+'_KEY':value for role,value in credentials.items()}}
    # On a legacy proxy this bearer is ignored. On an activated private backend use
    # the actual owner key, without copying it to the consumer credential set.
    if os.environ.get('LARIO_BACKEND_KEY'):environment['LARIO_BACKEND_KEY']=os.environ['LARIO_BACKEND_KEY']
    log=output.with_suffix('.log');log.parent.mkdir(parents=True,exist_ok=True)
    descriptor=os.open(log,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    records=[];streams=[];base=f'http://127.0.0.1:{port}'
    with os.fdopen(descriptor,'w') as logfile:
        process=subprocess.Popen([sys.executable,str(ROOT/'shared/admission/server.py'),hardware,
             '--upstream',f'http://127.0.0.1:{backend_port}','--listen','127.0.0.1','--port',str(port)],
             env=environment,stdout=logfile,stderr=logfile,start_new_session=True)
        try:
            for attempt in range(30):
                try:
                    with read(base+'/budget') as response:budget=json.load(response)
                    if budget.get('ready'):break
                except OSError:pass
                if process.poll() is not None:raise RuntimeError('shadow process failed')
                time.sleep(.2)
            else:raise RuntimeError('shadow gate not ready; no model action taken')
            def request(role,selected=model):
                return read(base+'/v1/chat/completions',{'model':selected,'messages':[{'role':'user','content':'Count from 1 up to 1000, without omitting numbers.'}],
                          'stream':True,'max_tokens':256,'temperature':0,'chat_template_kwargs':{'enable_thinking':False}},credentials[role])
            def reject(role,status,selected=model):
                try:
                    response=request(role,selected);response.close();actual=response.status
                except urllib.error.HTTPError as error:actual=error.code;error.close()
                records.append({'check':role+' rejection '+str(status),'passed':actual==status,'status':actual})
            role='auxiliary' if hardware=='rtx5080' else 'fleet'
            first=request(role);streams.append(first)
            reject(role,429)
            if hardware=='rtx5080':
                reject('interactive',429);reject('fleet',429)
            else:
                for _ in range(budget['slots']-1):streams.append(request('interactive'))
                reject('interactive',429)
            reject('interactive',409,'not-a-resident-model')
            with read(base+'/budget') as response:occupied=json.load(response)
            records.append({'check':'all actual slots accounted','passed':sum(occupied.get('active',{}).values())==budget['slots']})
            # Disconnect one stream while native work is active. Let all other owned
            # requests finish; uncertain capacity stays quarantined until idle.
            first.readline();first.close()
            for response in streams[1:]:response.read();response.close()
            for attempt in range(100):
                with read(base+'/budget') as response:recovered=json.load(response)
                if recovered.get('ready') and not sum(recovered.get('active',{}).values()):break
                time.sleep(.1)
            else:raise RuntimeError('backend occupancy did not reconcile after disconnect')
            records.append({'check':'disconnect recovered without model restart','passed':True})
            with request(role) as response:response.read()
            with read(f'http://127.0.0.1:{backend_port}/running',key=os.environ.get('LARIO_BACKEND_KEY')) as response:after=json.load(response)
            records.append({'check':'resident unchanged','passed':before==after})
        finally:
            for response in streams:response.close()
            if process.poll() is None:
                os.killpg(process.pid,signal.SIGTERM)
                try:process.wait(timeout=10)
                except subprocess.TimeoutExpired:os.killpg(process.pid,signal.SIGKILL);process.wait()
    result={'hardware':hardware,'mode':'shadow; public backend remains advisory',
            'gateway_port':port,'checks':records,'passed':bool(records) and all(row['passed'] for row in records)}
    output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result))
    if not result['passed']:raise SystemExit(1)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('hardware',choices=['geekom','7900xt','rtx5080'])
    parser.add_argument('--credentials',type=Path,required=True)
    parser.add_argument('--port',type=int,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();run(args.hardware,args.credentials,args.port,args.output)


if __name__=='__main__':main()

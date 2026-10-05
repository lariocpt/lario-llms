#!/usr/bin/env python3
"""One-snapshot capacity for lario-fleet; enforced endpoints never fall back."""
import argparse
import json
from pathlib import Path
import shlex
import sys
import urllib.error
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from shared.modelctl import fleet_capacity


def read(url):
    with urllib.request.urlopen(url,timeout=3) as response:return json.load(response)


def budget(hardware,url):
    try:
        data=read(url.rstrip('/')+'/budget')
    except urllib.error.HTTPError as error:
        if error.code!=404:raise
    else:
        if data.get('enforced') is not True or data.get('hardware')!=hardware:
            raise RuntimeError('invalid admission budget')
        return data
    reg=json.loads((ROOT/hardware/'models.json').read_text())
    running=read(url.rstrip('/')+'/running').get('running',[])
    ready=[m for m in running if m.get('state')=='ready']
    if len(running)!=1 or len(ready)!=1 or ready[0]['model'] not in reg['models']:raise RuntimeError('no single registered ready model')
    args=shlex.split(ready[0]['cmd']);slots=int(args[args.index('--parallel')+1])
    total=int(args[args.index('-c')+1])
    if slots<1 or total%slots:raise RuntimeError('invalid live geometry')
    context=total//slots
    reserved=reg['models'][ready[0]['model']]['reserved']
    if not 0<=reserved<=slots:raise RuntimeError('invalid reservation geometry')
    return {'hardware':hardware,'model':ready[0]['model'],'slots':slots,'reserved':reserved,
            'context':context,'agents':fleet_capacity(slots,reserved,context),'ready':True,'enforced':False}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('hardware',choices=['geekom','7900xt','rtx5080'])
    parser.add_argument('--url',required=True)
    parser.add_argument('--override',type=int)
    parser.add_argument('--fleet-format',action='store_true')
    args=parser.parse_args()
    try:
        data=budget(args.hardware,args.url)
        cap=data.get('agents',0) if data.get('ready') else 0
        if type(cap) is not int or cap<0:raise ValueError('invalid capacity')
        if args.override is not None:cap=min(cap,max(0,args.override))
        if args.fleet_format:
            label='enforced' if data.get('enforced') else 'advisory'
            print(f'{cap}|{args.hardware} {data.get("model","unavailable")} {label}; enabled agents are not active requests')
        else:print(json.dumps({**data,'agents':cap}))
    except Exception:
        if args.fleet_format:print(f'0|{args.hardware} live budget unavailable (no assumed capacity)')
        else:print(json.dumps({'hardware':args.hardware,'ready':False,'agents':0,'available':0}))


if __name__=='__main__':main()

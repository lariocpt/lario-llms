#!/usr/bin/env python3
"""Read-only fixed-profile model catalog and status MCP."""
import argparse
import concurrent.futures
import json
import os
from pathlib import Path
import re
import shlex
import socket
import subprocess
import sys
import urllib.error
import urllib.request

HARDWARE=('geekom','7900xt','rtx5080','arcB70')
CHOICES=Path(os.getenv('LARIO_MODEL_CHOICES_FILE',str(Path(__file__).with_name('model_choices.json'))))
ALLOW_SWITCH=False  # Lifecycle controls belong to the authenticated operator page.
HARDWARE_SCHEMA={'type':'string','enum':list(HARDWARE)}
OPTIONS_SCHEMA={'type':'string','enum':list(HARDWARE)}
TOOLS=[
 {'name':'model_status','description':'Show actual fixed profile, context, slots and serving state. Read-only; offline hosts report unavailable. Use models.in.drlario.org for operator controls.',
  'inputSchema':{'type':'object','properties':{'hardware':HARDWARE_SCHEMA},'additionalProperties':False},'annotations':{'readOnlyHint':True}},
 {'name':'model_options','description':'List fixed-profile IDs and compact display names with exact context, KV and slots. arcB70 returns disabled preparation estimates only, never ready capacity.',
  'inputSchema':{'type':'object','properties':{'hardware':OPTIONS_SCHEMA},'required':['hardware'],'additionalProperties':False},'annotations':{'readOnlyHint':True}}]


def choices():
 data=json.loads(CHOICES.read_text())
 if data.get('schema_version')!=2 or not set(HARDWARE[:3])<=set(data.get('hardware',{}))<=set(HARDWARE):raise ValueError('invalid model choices snapshot')
 return data['hardware']


def owner_call(hardware,request,timeout=25):
 owner=choices()[hardware]['owner']
 if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9.-]*',owner):raise ValueError('invalid hardware owner')
 helper=Path.home()/'Projects/personal/lario-llms/shared/model_tools/owner.py'
 if socket.gethostname().split('.')[0]==owner:
  command=[sys.executable,str(helper)]
 else:
  # Fixed remote program; all model identifiers and tokens travel as JSON stdin.
  command=['ssh','-T','-o','BatchMode=yes','-o','ConnectTimeout=8',owner,
           'python3 ~/Projects/personal/lario-llms/shared/model_tools/owner.py']
 result=subprocess.run(command,input=json.dumps({'hardware':hardware,**request}),text=True,capture_output=True,timeout=timeout)
 try:data=json.loads(result.stdout)
 except ValueError:raise RuntimeError('hardware owner unavailable; no model action confirmed') from None
 if result.returncode or 'error' in data:
  raise RuntimeError(data.get('error',{}).get('message','hardware owner operation failed'))
 return data


def label_status(hardware, budget):
 # Running owners can retain startup labels. Resolve cosmetic names only by
 # exact immutable ID; never replace observed context, occupancy or readiness.
 resident=budget.get('resident')
 if isinstance(resident,dict):
  match=next((p for p in choices()[hardware]['options'] if p['id']==resident.get('id')),None)
  if match:resident['name']=match['name']
 return budget


def public_status(hardware):
 endpoints=json.loads(os.getenv('LARIO_MODELS_ENDPOINTS','{}'))
 base=endpoints.get(hardware)
 if not isinstance(base,str):raise ValueError('model endpoint is not configured')
 base=base.rstrip('/');base=base[:-3] if base.endswith('/v1') else base
 def get(path):
  with urllib.request.urlopen(base+path,timeout=8) as response:return json.load(response)
 try:
  budget=label_status(hardware,get('/budget'))
  return {'hardware':hardware,'ready':bool(budget.get('ready')),'resident':budget,
          'transport':'public-budget','switching_available':False}
 except urllib.error.HTTPError as exc:
  if exc.code!=404:raise
 running=get('/running').get('running',[])
 if len(running)!=1 or running[0].get('state')!='ready':raise RuntimeError('no single ready resident model')
 item=running[0];args=shlex.split(item['cmd']);slots=int(args[args.index('--parallel')+1]);total=int(args[args.index('-c')+1])
 if slots<1 or total%slots:raise RuntimeError('invalid live geometry')
 return {'hardware':hardware,'ready':True,'resident':{'model':item['model'],'slots':slots,'context':total//slots,'enforced':False},
         'transport':'public-legacy','switching_available':False,
         'scope':'Read-only resident snapshot; saved alias target and occupancy are unavailable without owner access. Concrete legacy requests can change residency.'}


def call(name,args):
 spec=next((tool for tool in TOOLS if tool['name']==name),None)
 if spec is None:raise ValueError('unknown or disabled model tool')
 if not isinstance(args,dict) or set(args)-set(spec['inputSchema']['properties']):raise ValueError('unknown tool arguments')
 if any(key not in args for key in spec['inputSchema'].get('required',[])):raise ValueError('missing tool argument')
 hardware=args.get('hardware')
 if hardware is not None and hardware not in spec['inputSchema']['properties']['hardware']['enum']:raise ValueError('unknown hardware')
 if name=='model_options':
  if hardware=='arcB70' and hardware not in choices():
   choices()  # Validate snapshot schema and live hardware independently.
   prepared=json.loads(CHOICES.read_text()).get('prepared',{}).get(hardware)
   if not prepared or prepared.get('ready') is not False or prepared.get('disabled') is not True or prepared.get('fleet_capacity')!=0:
    raise ValueError('invalid prepared model snapshot')
   return prepared
  return choices()[hardware]
 def inspect(which):
  try:
   return public_status(which)
  except Exception as exc:return {'hardware':which,'ready':False,'error_type':type(exc).__name__,'detail':str(exc)[:500]}
 if hardware:return inspect(hardware)
 with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:return dict(zip(HARDWARE,pool.map(inspect,HARDWARE)))


def mcp():
 for line in sys.stdin:
  identifier=None
  try:
   request=json.loads(line);identifier=request.get('id')
   if identifier is None:continue
   method=request.get('method')
   if method=='initialize':
    protocol=request.get('params',{}).get('protocolVersion','2024-11-05')
    result={'protocolVersion':protocol if protocol in ('2024-11-05','2025-03-26','2025-06-18') else '2024-11-05','capabilities':{'tools':{'listChanged':False}},'serverInfo':{'name':'lario-models','version':'1.1.0'}}
   elif method=='ping':result={}
   elif method=='tools/list':result={'tools':TOOLS}
   elif method=='tools/call':
    params=request['params']
    try:value=call(params['name'],params.get('arguments',{}));result={'content':[{'type':'text','text':json.dumps(value)}],'isError':False}
    except Exception as exc:result={'content':[{'type':'text','text':str(exc)[:500]}],'isError':True}
   else:
    print(json.dumps({'jsonrpc':'2.0','id':identifier,'error':{'code':-32601,'message':'Method not found'}}),flush=True);continue
   print(json.dumps({'jsonrpc':'2.0','id':identifier,'result':result}),flush=True)
  except Exception as exc:print(json.dumps({'jsonrpc':'2.0','id':identifier,'error':{'code':-32600,'message':str(exc)[:500]}}),flush=True)


if __name__=='__main__':
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--call',choices=[tool['name'] for tool in TOOLS]);parser.add_argument('--args',default='{}')
 args=parser.parse_args()
 if args.call:print(json.dumps(call(args.call,json.loads(args.args)),indent=2))
 else:mcp()

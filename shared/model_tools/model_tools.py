#!/usr/bin/env python3
"""Dependency-free model-status/selection MCP. Remote switching uses existing SSH access."""
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

HARDWARE=('geekom','7900xt','rtx5080')
CHOICES=Path(os.getenv('LARIO_MODEL_CHOICES_FILE',str(Path(__file__).with_name('model_choices.json'))))
ALLOW_SWITCH=os.getenv('LARIO_MODELS_ALLOW_SWITCH','0')=='1'
HARDWARE_SCHEMA={'type':'string','enum':list(HARDWARE)}
TOOLS=[
 {'name':'model_status','description':'Show actual resident model/context/slots and saved alias target. Read-only: does not warm, switch or restart a model. Offline hosts report unavailable. Owner mode also returns a fresh switch_token.',
  'inputSchema':{'type':'object','properties':{'hardware':HARDWARE_SCHEMA},'additionalProperties':False},'annotations':{'readOnlyHint':True}},
 {'name':'model_options','description':'List numbered model@preset choices and exact context/slots/reservations. Reuses existing weights; experimental and disabled choices are explicit.',
  'inputSchema':{'type':'object','properties':{'hardware':HARDWARE_SCHEMA},'required':['hardware'],'additionalProperties':False},'annotations':{'readOnlyHint':True}}]
if ALLOW_SWITCH:
 TOOLS.append({'name':'model_switch','description':'Switch only when the user explicitly requests it. Use an option from model_options and a fresh model_status switch_token. Hardware owner controller refuses active/unknown inference, held or unhealthy hardware and stale selections; rolls back on failure. Experimental options require allow_experimental=true. No force, downloads, sudo or OpenCode restart.',
  'inputSchema':{'type':'object','properties':{'hardware':HARDWARE_SCHEMA,'option':{'type':'string'},'switch_token':{'type':'string'},'allow_experimental':{'type':'boolean'}},'required':['hardware','option','switch_token'],'additionalProperties':False},
  'annotations':{'readOnlyHint':False,'destructiveHint':True}})


def choices():
 data=json.loads(CHOICES.read_text())
 if data.get('schema_version')!=1 or set(data.get('hardware',{}))!=set(HARDWARE):raise ValueError('invalid model choices snapshot')
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


def public_status(hardware):
 endpoints=json.loads(os.getenv('LARIO_MODELS_ENDPOINTS','{}'))
 base=endpoints.get(hardware)
 if not isinstance(base,str):raise ValueError('model endpoint is not configured')
 base=base.rstrip('/');base=base[:-3] if base.endswith('/v1') else base
 def get(path):
  with urllib.request.urlopen(base+path,timeout=8) as response:return json.load(response)
 try:
  budget=get('/budget')
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
 if hardware is not None and hardware not in HARDWARE:raise ValueError('unknown hardware')
 if name=='model_options':return choices()[hardware]
 if name=='model_switch':
  option=args['option']
  if not isinstance(option,str) or option not in {entry['id'] for entry in choices()[hardware]['options']}:
   raise ValueError('choose an exact enabled model@preset from model_options')
  if type(args.get('allow_experimental',False)) is not bool:raise ValueError('allow_experimental must be boolean')
  return owner_call(hardware,{'operation':'switch',**args},timeout=3900)
 def inspect(which):
  try:
   if ALLOW_SWITCH:return owner_call(which,{'operation':'status'})
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
    result={'protocolVersion':protocol if protocol in ('2024-11-05','2025-03-26','2025-06-18') else '2024-11-05','capabilities':{'tools':{'listChanged':False}},'serverInfo':{'name':'lario-models','version':'1.0.0'}}
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

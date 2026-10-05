#!/usr/bin/env python3
"""Fleet Intel tools: dependency-free MCP stdio and CLI client.

Canonical source: lario-llms/intel/tools/intel_tools.py. machine-setup vendors
this client for hosts without a model-server checkout. It never loads weights:
Intel services remain resident on bigcachy. Tool discovery works while it is offline.
"""
import argparse
import base64
import concurrent.futures
import json
import math
import os
from pathlib import Path
import sys
import urllib.error
import urllib.request
import uuid

HOST=os.getenv('LARIO_INTEL_HOST','127.0.0.1').rstrip('/')
if not HOST.startswith(('http://','https://')): HOST='http://'+HOST
TIMEOUT=int(os.getenv('LARIO_INTEL_TIMEOUT','300'))
PORTS={'embedding':8001,'asr':8002,'translation':8003,'tts':8004}

def request(service,path,body=None,data=None,content_type='application/json'):
 if body is not None:data=json.dumps(body).encode()
 req=urllib.request.Request(f'{HOST}:{PORTS[service]}{path}',data=data,headers={'Content-Type':content_type})
 try:
  with urllib.request.urlopen(req,timeout=TIMEOUT) as response:return json.load(response)
 except urllib.error.HTTPError as exc:
  raise RuntimeError(f'{service} HTTP {exc.code}: {exc.read(2000).decode(errors="replace")}') from exc
 except urllib.error.URLError as exc:
  raise RuntimeError(f'Intel {service} on {HOST} is unavailable; retry when bigcachy is online: {exc.reason}') from exc

def schema(name,description,properties,required=()):
 return {'name':name,'description':description,'inputSchema':{'type':'object','properties':properties,'required':list(required),'additionalProperties':False}}
STR={'type':'string'}
TOOLS=[
 schema('intel_health','Check the four resident Intel services and selected devices.',{}),
 schema('intel_translate','Translate text with Intel iGPU Qwen3-8B INT4. Preserve meaning, numbers and formatting.',{'text':STR,'source_lang':STR,'target_lang':STR},['text','target_lang']),
 schema('intel_transcribe','Transcribe a local audio file with NPU multilingual Whisper turbo. audio_path is a file on THIS client, not on bigcachy. Returns original-language text.',{'audio_path':STR,'language':STR},['audio_path']),
 schema('intel_synthesize','Write Kokoro speech to a NEW local WAV file. output_path is on THIS client. Default English voice af_heart; Portuguese pf_dora. Does not overwrite existing files.',{'text':STR,'output_path':STR,'voice':STR,'speed':{'type':'number','minimum':0.5,'maximum':2}},['text','output_path']),
 schema('intel_voices','List available Kokoro voice IDs and languages.',{}),
 schema('intel_embed','Encode text in the existing BGE-M3 1024-dimensional normalized RAG space. By default return metadata/norms; return_vectors=true includes large vectors.',{'texts':{'type':'array','items':STR,'minItems':1,'maxItems':256},'return_vectors':{'type':'boolean'}},['texts']),
 schema('intel_rank','Rank supplied documents against a query using compatible BGE-M3 cosine similarity; return indices, scores and texts, without flooding the prompt with vectors.',{'query':STR,'documents':{'type':'array','items':STR,'minItems':1,'maxItems':255},'top_k':{'type':'integer','minimum':1,'maximum':255}},['query','documents'])]

def call(name,args):
 spec=next((t for t in TOOLS if t['name']==name),None)
 if spec is None:raise ValueError('Unknown Intel tool')
 allowed=spec['inputSchema']['properties']
 if set(args)-allowed.keys():raise ValueError('Unknown tool arguments')
 if any(k not in args for k in spec['inputSchema']['required']):raise ValueError('Missing required argument')
 if name=='intel_health':
  def health(service):
   try:return service,request(service,'/health')
   except Exception as exc:return service,{'status':'unavailable','error':str(exc)}
  with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:return dict(pool.map(health,PORTS))
 if name=='intel_translate':return request('translation','/translate',{'text':args['text'],'source_lang':args.get('source_lang','English'),'target_lang':args['target_lang']})
 if name=='intel_voices':return request('tts','/voices')
 if name=='intel_transcribe':
  path=Path(args['audio_path']).expanduser().resolve(strict=True)
  if path.stat().st_size>50_000_000:raise ValueError('Audio file exceeds 50 MB')
  boundary='lario-'+uuid.uuid4().hex
  language=args.get('language','')
  if '\r' in language or '\n' in language:raise ValueError('Invalid language')
  data=f'--{boundary}\r\nContent-Disposition: form-data; name="language"\r\n\r\n{language}\r\n--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="audio"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode()+path.read_bytes()+f'\r\n--{boundary}--\r\n'.encode()
  return request('asr','/transcribe',data=data,content_type=f'multipart/form-data; boundary={boundary}')
 if name=='intel_synthesize':
  path=Path(args['output_path']).expanduser().absolute()
  if path.exists():raise ValueError('Output file already exists; choose a new path')
  if not path.parent.is_dir():raise ValueError('Output parent directory must exist')
  result=request('tts','/synthesize',{'text':args['text'],'voice':args.get('voice','af_heart'),'speed':args.get('speed',1)})
  audio=base64.b64decode(result.pop('audio_base64'),validate=True)
  if not audio.startswith(b'RIFF'):raise RuntimeError('Speech service did not return a WAV')
  with path.open('xb') as out:out.write(audio)
  return {**result,'output_path':str(path),'bytes':len(audio)}
 texts=args.get('texts') if name=='intel_embed' else [args['query'],*args['documents']]
 result=request('embedding','/embed',{'texts':texts,'model':'BAAI/bge-m3'})
 vectors=result['embeddings']
 if any(len(v)!=1024 for v in vectors) or len(vectors)!=len(texts):raise RuntimeError('Embedding contract mismatch')
 if name=='intel_embed':
  if not args.get('return_vectors',False):
   result.pop('embeddings');result['count']=len(vectors);result['norms']=[math.sqrt(sum(x*x for x in v)) for v in vectors]
  return result
 scores=[sum(x*y for x,y in zip(vectors[0],v)) for v in vectors[1:]]
 order=sorted(range(len(scores)),key=lambda i:scores[i],reverse=True)[:args.get('top_k',len(scores))]
 return {'model':result['model'],'device':result['device'],'ranked':[{'index':i,'score':scores[i],'text':args['documents'][i]} for i in order]}

def mcp():
 # MCP stdio uses newline-delimited JSON-RPC. No network dependency at handshake.
 for line in sys.stdin:
  identifier=None
  try:
   req=json.loads(line);identifier=req.get('id');method=req.get('method','')
   if identifier is None:continue
   if method=='initialize':
    requested=req.get('params',{}).get('protocolVersion','2024-11-05')
    result={'protocolVersion':requested if requested in ('2024-11-05','2025-03-26','2025-06-18') else '2024-11-05','capabilities':{'tools':{'listChanged':False}},'serverInfo':{'name':'lario-intel','version':'1.0.0'}}
   elif method=='ping':result={}
   elif method=='tools/list':result={'tools':TOOLS}
   elif method=='tools/call':
    params=req['params']
    try:
     value=call(params['name'],params.get('arguments',{}));result={'content':[{'type':'text','text':json.dumps(value,ensure_ascii=False)}],'isError':False}
    except Exception as exc:result={'content':[{'type':'text','text':str(exc)}],'isError':True}
   else:
    print(json.dumps({'jsonrpc':'2.0','id':identifier,'error':{'code':-32601,'message':'Method not found'}}),flush=True);continue
   response={'jsonrpc':'2.0','id':identifier,'result':result}
  except Exception as exc:response={'jsonrpc':'2.0','id':identifier,'error':{'code':-32600,'message':str(exc)}}
  print(json.dumps(response,ensure_ascii=False),flush=True)

def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--call',choices=[t['name'] for t in TOOLS]);p.add_argument('--args',default='{}')
 a=p.parse_args()
 if a.call:print(json.dumps(call(a.call,json.loads(a.args)),ensure_ascii=False,indent=2))
 else:mcp()
if __name__=='__main__':main()

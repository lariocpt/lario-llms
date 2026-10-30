"""Smoke and speed probes for a private candidate or authenticated public owner."""
import argparse,base64,concurrent.futures,json,os,re,struct,time,urllib.request,zlib
from pathlib import Path

def run(base,model,key='',slots=2):
 def api(path,body=None,timeout=300):
  req=urllib.request.Request(base+path,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json','Authorization':'Bearer '+key})
  with urllib.request.urlopen(req,timeout=timeout) as response:
   raw=response.read();return json.loads(raw) if raw.strip() else {}
 def chat(content,**kw):
  return api('/v1/chat/completions',{'model':model,'messages':[{'role':'user','content':content}],
      'max_tokens':128,'temperature':0,'chat_template_kwargs':{'enable_thinking':False},**kw})
 def text(r):return r['choices'][0]['message'].get('content','')
 with concurrent.futures.ThreadPoolExecutor(max_workers=slots) as pool:short=list(pool.map(chat,['Return exactly READY.']*slots))
 assert all('READY' in text(r) for r in short),short
 def chunk(t,b):return struct.pack('>I',len(b))+t+b+struct.pack('>I',zlib.crc32(t+b)&0xffffffff)
 raw=b''.join(b'\0'+b''.join(bytes((255,0,0) if x<64 else (0,0,255)) for x in range(128)) for y in range(128))
 png=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',128,128,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(raw))+chunk(b'IEND',b'')
 vision=chat([{'type':'text','text':'Name the left and right colours.'},{'type':'image_url','image_url':{'url':'data:image/png;base64,'+base64.b64encode(png).decode()}}])
 assert all(c in text(vision).lower() for c in ('red','blue')),vision
 tools=[{'type':'function','function':{'name':'get_weather','description':'Get weather','parameters':{'type':'object','properties':{'city':{'type':'string'}},'required':['city']}}}]
 tool=chat('Call get_weather for Cape Town.',tools=tools,tool_choice={'type':'function','function':{'name':'get_weather'}})
 calls=tool['choices'][0]['message'].get('tool_calls',[])
 assert calls and calls[0]['function']['name']=='get_weather',tool
 def bench(_):
  body={'model':model,'messages':[{'role':'user','content':'Write a detailed numbered list of 100 practical Python programming tips. Keep writing until the output limit.'}],
      'max_tokens':256,'temperature':0,'chat_template_kwargs':{'enable_thinking':False},'stream':True,'stream_options':{'include_usage':True}}
  req=urllib.request.Request(base+'/v1/chat/completions',data=json.dumps(body).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer '+key})
  start=time.monotonic();first=None;usage=None;terminal=False
  with urllib.request.urlopen(req,timeout=300) as response:
   for line in response:
    if not line.startswith(b'data: '):continue
    raw=line[6:].strip()
    if raw==b'[DONE]':terminal=True;break
    item=json.loads(raw)
    if item.get('usage'):usage=item['usage']
    if any(c.get('delta',{}).get('content') for c in item.get('choices',[])) and first is None:first=time.monotonic()
  elapsed=time.monotonic()-start
  assert terminal and usage and first is not None,'Incomplete streaming response'
  return {'completion_tokens':usage['completion_tokens'],'seconds':elapsed,'ttft_seconds':first-start,
          'tokens_per_second_including_prefill':usage['completion_tokens']/elapsed}
 single=bench(0)
 dual=[]
 if slots>1:
  with concurrent.futures.ThreadPoolExecutor(max_workers=slots) as pool:dual=list(pool.map(bench,range(slots)))
 return {'status':'passed-native-capacity-concurrency-vision-tools-smoke','short':short,'vision':vision,'tools':tool,'single_speed':single,'dual_speed':dual}

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--base',default='http://127.0.0.1:11458');p.add_argument('--model',default='qwen38-b70-vllm');p.add_argument('--receipt',type=Path,required=True);p.add_argument('--wait',action='store_true');a=p.parse_args()
 if a.wait:
  deadline=time.monotonic()+1200
  while True:
   try:
    with urllib.request.urlopen(a.base+'/health',timeout=3):break
   except Exception:
    if time.monotonic()>deadline:raise
    time.sleep(3)
 result=run(a.base,a.model,os.getenv('LARIO_SMOKE_KEY',''))
 if a.base.endswith(':11458'):
  import subprocess
  from arcB70.vllm.prepare import command
  info=json.loads(subprocess.check_output(['docker','inspect','lario-b70-vllm-candidate']))[0]
  context=int(next(v.split('=',1)[1] for v in info['Config']['Env'] if v.startswith('MAX_MODEL_LEN=')))
  logs=(Path.home()/'.local/state/gpu-migration/vllm-native.log').read_text(errors='replace')
  pool=int(re.findall(r'(?:GPU|XPU) KV cache size:\s*([\d,]+)\s*tokens',logs)[-1].replace(',',''))
  assert pool>=context*2,(pool,context)
  result.update(context_per_slot=context,slots=2,final_native_kv_tokens=pool,command=[f'MAX_MODEL_LEN={context}' if v.startswith('MAX_MODEL_LEN=') else v for v in command()])
 a.receipt.write_text(json.dumps(result,indent=2));print(json.dumps({k:result[k] for k in ('status','single_speed','dual_speed')},indent=2))

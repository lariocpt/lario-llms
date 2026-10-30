"""Borrow idle RTX to test exact native context, vision, tools and streaming."""
import argparse,base64,fcntl,importlib.util,json,os,signal,struct,subprocess,sys,time,urllib.request,zlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'rtx5080/image-generation'))
from rtx5080.strata.profile import model_spec
from shared import modelctl
spec=importlib.util.spec_from_file_location('borrow',ROOT/'rtx5080/image-generation/controller.py');borrow=importlib.util.module_from_spec(spec);spec.loader.exec_module(borrow)
STATE=Path.home()/'.local/state/gpu-migration'

def validate(context):
 reg=json.loads((ROOT/'rtx5080/models.json').read_text());modelctl.load_runtime(reg)
 candidate=model_spec();args=candidate['args'];key=Path(reg['backend_key_file']).read_text().strip()
 argv=[candidate['binary'],'--host','127.0.0.1','--port','11459','-c',str(context),'--parallel','1',*args,'--api-key-file',reg['backend_key_file']]
 report={'status':'running','context':context,'slots':1,'vision':True,'command':argv}
 def api(path,body=None,timeout=300):
  req=urllib.request.Request('http://127.0.0.1:11459'+path,data=json.dumps(body).encode() if body is not None else None,headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'})
  with urllib.request.urlopen(req,timeout=timeout) as r:return json.load(r)
 def chat(content,**kw):return api('/v1/chat/completions',{'model':'qwen38-flash-nvfp4','messages':[{'role':'user','content':content}],'max_tokens':256,'temperature':0,'chat_template_kwargs':{'enable_thinking':False},**kw})
 process=None;lease=None
 with (ROOT/'.rtx5080.lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);modelctl.assert_not_held(reg);modelctl.assert_device_ready(reg)
  lease=borrow.claim_chat(reg)
  try:
   modelctl.assert_idle(reg);borrow.command('stop',reg['service'])
   with (STATE/'rtx-native.log').open('w') as log:process=subprocess.Popen(argv,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
   deadline=time.monotonic()+1800
   while True:
    if process.poll() is not None:raise RuntimeError('RTX candidate exited; inspect rtx-native.log and ~/strata/state/engine.log')
    try:health=api('/health',timeout=5);break
    except Exception:
     if time.monotonic()>deadline:raise RuntimeError('RTX startup timeout')
     time.sleep(3)
   report['health']=health;print('RTX candidate healthy',flush=True)
   started=time.monotonic();text=chat('Return exactly READY.');report['short_seconds']=time.monotonic()-started;report['text']=text
   assert 'READY' in text['choices'][0]['message'].get('content',''),text
   def chunk(t,b):return struct.pack('>I',len(b))+t+b+struct.pack('>I',zlib.crc32(t+b)&0xffffffff)
   raw=b''.join(b'\0'+b''.join(bytes((255,0,0) if x<64 else (0,0,255)) for x in range(128)) for y in range(128))
   png=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',128,128,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(raw))+chunk(b'IEND',b'')
   vision=chat([{'type':'text','text':'Name the left and right colours.'},{'type':'image_url','image_url':{'url':'data:image/png;base64,'+base64.b64encode(png).decode()}}])
   assert all(c in vision['choices'][0]['message'].get('content','').lower() for c in ('red','blue')),vision
   report['vision_reply']=vision;print('Native vision passed',flush=True)
   tools=[{'type':'function','function':{'name':'get_weather','description':'Get weather','parameters':{'type':'object','properties':{'city':{'type':'string'}},'required':['city']}}}]
   tool=chat('Call get_weather for Cape Town.',tools=tools,tool_choice={'type':'function','function':{'name':'get_weather'}})
   calls=tool['choices'][0]['message'].get('tool_calls',[]);assert calls and calls[0]['function']['name']=='get_weather',tool
   report['tools']=tool
   body={'model':'qwen38-flash-nvfp4','messages':[{'role':'user','content':'Write a detailed numbered list of 100 Python programming tips. Keep writing until the output limit.'}],'max_tokens':256,'temperature':0,'chat_template_kwargs':{'enable_thinking':False},'stream':True,'stream_options':{'include_usage':True}}
   req=urllib.request.Request('http://127.0.0.1:11459/v1/chat/completions',data=json.dumps(body).encode(),headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'})
   start=time.monotonic();first=None;usage=None;terminal=False
   with urllib.request.urlopen(req,timeout=600) as response:
    for line in response:
     if not line.startswith(b'data: '):continue
     raw=line[6:].strip()
     if raw==b'[DONE]':terminal=True;break
     item=json.loads(raw)
     if item.get('usage'):usage=item['usage']
     if any(c.get('delta',{}).get('content') for c in item.get('choices',[])) and first is None:first=time.monotonic()
   elapsed=time.monotonic()-start
   assert terminal and first is not None,'Incomplete streaming response'
   report['stream']={'seconds':elapsed,'ttft_seconds':first-start,'usage':usage,'tokens_per_second_including_prefill':usage['completion_tokens']/elapsed if usage else None}
   report['status']='passed-native-text-vision-tools-streaming'
   print(json.dumps({'status':report['status'],'context':context,'speed':report['stream']}),flush=True)
  except BaseException as e:
   report.update(status='failed',error=type(e).__name__+': '+str(e));raise
  finally:
   (STATE/'rtx-validation.json').write_text(json.dumps(report,indent=2))
   if process is not None and process.poll() is None:
    os.killpg(process.pid,signal.SIGTERM)
    try:process.wait(timeout=45)
    except subprocess.TimeoutExpired:os.killpg(process.pid,signal.SIGKILL);process.wait()
   if lease is not None:borrow.restore_chat(reg,lease,True)

if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--context',type=int,default=131072);validate(p.parse_args().context)

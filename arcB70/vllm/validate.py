"""Validate an isolated two-slot XPU candidate, restoring the current B70 owner."""
import argparse,base64,concurrent.futures,fcntl,importlib.util,json,os,re,signal,struct,subprocess,sys,time,urllib.request,zlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'rtx5080/image-generation'))
from arcB70.vllm.prepare import command
from shared import modelctl
from shared.serving.control import operate
spec=importlib.util.spec_from_file_location('borrow',ROOT/'rtx5080/image-generation/controller.py');borrow=importlib.util.module_from_spec(spec);spec.loader.exec_module(borrow)
STATE=Path.home()/'.local/state/gpu-migration'


def api(path,body=None,timeout=5):
 req=urllib.request.Request('http://127.0.0.1:11458'+path,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json'})
 with urllib.request.urlopen(req,timeout=timeout) as response:
  raw=response.read()
  return json.loads(raw) if raw.strip() else {}


def chat(content):
 return api('/v1/chat/completions',{'model':'qwen38-b70-vllm','messages':[{'role':'user','content':content}],
   'max_tokens':128,'temperature':0,'chat_template_kwargs':{'enable_thinking':False}},7200)


def text(reply):return reply['choices'][0]['message'].get('content','')


def validate(argv):
 reg=json.loads((ROOT/'arcB70/models.json').read_text());modelctl.load_runtime(reg)
 report={'status':'running','slots':2,'context_per_slot':262144,'required_kv_tokens':524288,'command':argv}
 process=None;lease=None
 with (ROOT/'.arcB70.lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  modelctl.assert_not_held(reg);modelctl.assert_device_ready(reg)
  retirement=STATE/'b70-retired-for-vllm.json'
  retired=json.loads(retirement.read_text()) if retirement.exists() else None
  if retired:
   state=borrow.owner_request(reg,'state')
   if not state['enabled'] or not state['draining'] or state['revision']!=retired['revision']:
    raise RuntimeError('Retirement lease changed; preserve operator policy')
   lease={'revision':state['revision'],'profile_id':None}
   if state['busy'] or state['requests'] or state['loading_profile']:raise RuntimeError('Retired owner has active work')
   service_state=subprocess.check_output(['systemctl','--user','show',reg['service'],'-p','ActiveState','--value'],text=True).strip()
   if service_state!='inactive':raise RuntimeError('Retired backend must be stopped')
  else:
   lease=borrow.claim_chat(reg)
  try:
   if not retired:modelctl.assert_idle(reg)
   if not retired:borrow.command('stop',reg['service'])
   log_path=STATE/'vllm-native.log'
   with log_path.open('w') as log:
    process=subprocess.Popen(argv,stdout=log,stderr=subprocess.STDOUT)
   deadline=time.monotonic()+1200
   while True:
    if process.poll() is not None:raise RuntimeError('vLLM exited during startup; inspect vllm-native.log')
    try:api('/health');break
    except Exception:
     if time.monotonic()>deadline:raise RuntimeError('vLLM startup timeout')
     time.sleep(3)
   # Max sequences does not guarantee two full windows. Check the engine pool.
   logs=log_path.read_text(errors='replace')
   capacities=re.findall(r'(?:GPU|XPU) KV cache size:\s*([\d,]+)\s*tokens',logs)
   if not capacities:raise RuntimeError('Native KV capacity not reported; refusing to infer it from max-num-seqs')
   capacity=int(capacities[-1].replace(',',''));report['native_kv_tokens']=capacity
   context_each=min(int(next(v.split('=',1)[1] for v in argv if v.startswith('MAX_MODEL_LEN='))), ((capacity//2)//1024)*1024)
   if context_each<8192:raise RuntimeError('Insufficient KV capacity for two useful windows')
   report.update(context_per_slot=context_each,full_target_fits=context_each==262144,
                 physical_total_tokens=context_each*2,
                 scope='Two equal windows from the native KV pool; publication requires matching admission limits')
   print(f'Native KV pool {capacity} tokens; validating 2 x {context_each}',flush=True)
   for geometry_attempt in range(5):
    configured=int(next(v.split('=',1)[1] for v in argv if v.startswith('MAX_MODEL_LEN=')))
    if configured==context_each and capacity >= context_each*2:break
    subprocess.run(['docker','stop','-t','20','lario-b70-vllm-candidate'],check=True,stdout=subprocess.DEVNULL)
    process.wait(timeout=30)
    argv=[f'MAX_MODEL_LEN={context_each}' if value.startswith('MAX_MODEL_LEN=') else value for value in argv]
    with log_path.open('a') as log:process=subprocess.Popen(argv,stdout=log,stderr=subprocess.STDOUT)
    deadline=time.monotonic()+1200
    while True:
     if process.poll() is not None:raise RuntimeError('vLLM exited while validating the measured context')
     try:api('/health');break
     except Exception:
      if time.monotonic()>deadline:raise RuntimeError('Measured-context startup timeout')
      time.sleep(3)
    capacities=re.findall(r'(?:GPU|XPU) KV cache size:\s*([\d,]+)\s*tokens',log_path.read_text(errors='replace'))
    if not capacities:raise RuntimeError('Final native cache capacity missing')
    capacity=int(capacities[-1].replace(',',''))
    report['command']=argv;report['final_native_kv_tokens']=capacity
    if capacity >= context_each*2:break
    context_each=((capacity//2)//1024)*1024
    report.update(context_per_slot=context_each,physical_total_tokens=context_each*2)
    print(f'Reprofiled KV pool {capacity}; reducing to 2 x {context_each}',flush=True)
   else:raise RuntimeError('Native KV geometry did not converge')
   if capacity<context_each*2:raise RuntimeError('Final native cache cannot hold both windows')
   started=time.monotonic()
   with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
    short=list(pool.map(chat,['Return exactly READY.','Return exactly READY.']))
   if any('READY' not in text(r) for r in short):raise RuntimeError('Concurrent short requests failed')
   report['short_seconds']=time.monotonic()-started;report['short']=short
   def chunk(t,b):return struct.pack('>I',len(b))+t+b+struct.pack('>I',zlib.crc32(t+b)&0xffffffff)
   raw=b''.join(b'\0'+b''.join(bytes((255,0,0) if x<64 else (0,0,255)) for x in range(128)) for y in range(128))
   png=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',128,128,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(raw))+chunk(b'IEND',b'')
   vision=chat([{'type':'text','text':'Name the left and right colours.'},{'type':'image_url','image_url':{'url':'data:image/png;base64,'+base64.b64encode(png).decode()}}])
   if not all(c in text(vision).lower() for c in ('red','blue')):raise RuntimeError('Native vision check failed')
   report['vision']=vision
   tool=api('/v1/chat/completions',{'model':'qwen38-b70-vllm','messages':[{'role':'user','content':'Call get_weather for Cape Town.'}],
    'tools':[{'type':'function','function':{'name':'get_weather','description':'Get weather','parameters':{'type':'object','properties':{'city':{'type':'string'}},'required':['city']}}}],
    'tool_choice':{'type':'function','function':{'name':'get_weather'}},'max_tokens':128,'temperature':0,
    'chat_template_kwargs':{'enable_thinking':False}},300)
   calls=tool['choices'][0]['message'].get('tool_calls',[])
   if not calls or calls[0]['function']['name']!='get_weather':raise RuntimeError('Native tool call failed')
   report['tools']=tool
   report['status']='passed-native-capacity-concurrency-vision-tools-smoke'
   (STATE/'vllm-smoke.json').write_text(json.dumps(report,indent=2))
   if os.environ.get('LARIO_VLLM_SMOKE_ONLY')=='1':return

   block='Synthetic archive: the component uses blue buttons and eight pixel spacing.\n'*256
   token_count=len(api('/tokenize',{'model':'qwen38-b70-vllm','prompt':block})['tokens'])
   long_target=context_each-4096
   repeats=max(1,(long_target//token_count)//2)
   prompts=[]
   for n in range(2):
    prompt=f'Report values for KEY_ALPHA, KEY_BETA, KEY_GAMMA in archive {n}.\nKEY_ALPHA=cedar731\n'+block*repeats+'KEY_BETA=quartz482\n'+block*repeats+'KEY_GAMMA=maple956\nReport those three values.'
    count=len(api('/tokenize',{'model':'qwen38-b70-vllm','prompt':prompt},60)['tokens'])
    if not long_target-token_count*2-1024<count<context_each-512:raise RuntimeError('Unexpected long-prompt token geometry')
    prompts.append(prompt)
   started=time.monotonic()
   with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:long=list(pool.map(chat,prompts))
   if any(not all(value in text(r) for value in ('cedar731','quartz482','maple956')) for r in long):raise RuntimeError('Two concurrent long-window retrieval checks failed')
   report.update(status='passed-native-capacity-concurrency-vision-long-retrieval',long=long,long_seconds=time.monotonic()-started)
   print(report['status'],flush=True)
  except BaseException as error:
   report.update(status='failed',error=type(error).__name__+': '+str(error));raise
  finally:
   (STATE/'vllm-validation.json').write_text(json.dumps(report,indent=2))
   if process is not None:
    subprocess.run(['docker','stop','-t','20','lario-b70-vllm-candidate'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:process.wait(timeout=30)
    except subprocess.TimeoutExpired:process.terminate()
   if lease is not None and not retired:borrow.restore_chat(reg,lease,True)


def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--wait',action='store_true');args=parser.parse_args()
 STATE.mkdir(parents=True,exist_ok=True)
 deadline=time.monotonic()+21600
 while True:
  try:
   argv=command()
   previous=STATE/'vllm-validation.json'
   if previous.exists():
    prior=json.loads(previous.read_text())
    capacity=prior.get('final_native_kv_tokens')
    if not capacity and 'Final native cache' in prior.get('error',''):
     log=STATE/'vllm-native.log'
     matches=re.findall(r'(?:GPU|XPU) KV cache size:\s*([\d,]+)\s*tokens',log.read_text(errors='replace')) if log.exists() else []
     if matches:capacity=int(matches[-1].replace(',',''))
    if capacity:
     ceiling=min(262144,((capacity//2)//1024)*1024)
     argv=[f'MAX_MODEL_LEN={ceiling}' if v.startswith('MAX_MODEL_LEN=') else v for v in argv]
   image=json.loads(Path(__file__).with_name('manifest.json').read_text())['runtime_image']
   if subprocess.run(['docker','image','inspect',image],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode:raise RuntimeError('Runtime image download pending')
   state=operate('arcB70','status')
   retirement=STATE/'b70-retired-for-vllm.json'
   retired=json.loads(retirement.read_text()) if retirement.exists() else None
   own_pause=retired and state['revision']==retired['revision'] and state['enabled']
   if state['busy'] or state['requests'] or (state['draining'] and not own_pause) or state['loading_profile']:raise RuntimeError('B70 is in use or paused')
   break
  except RuntimeError as error:
   if not args.wait or time.monotonic()>deadline:raise
   print('Waiting: '+str(error),flush=True);time.sleep(30)
 def interrupted(_signal,_frame):raise InterruptedError('Own candidate validation interrupted')
 signal.signal(signal.SIGTERM,interrupted);signal.signal(signal.SIGINT,interrupted)
 validate(argv)

if __name__=='__main__':main()

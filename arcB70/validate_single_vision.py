"""Validate one native B70 vision slot, restoring the previous resident model.

Run only on an idle owner. LARIO_VALIDATE_FULL_CONTEXT=1 also checks retrieval
through a synthetic 500K+ token prompt. Evidence stays outside the checkout.
"""
import base64,json,os,signal,struct,subprocess,sys,time,urllib.request,zlib
from pathlib import Path
repo=Path(__file__).resolve().parents[1];sys.path.insert(0,str(repo));os.chdir(repo)
from arcB70.single_vision import build_registry
from shared.serving.control import operate
from shared.serving.catalog import profiles
from shared import modelctl
original=json.loads((repo/'arcB70/models.json').read_text());modelctl.load_runtime(original)
s=operate('arcB70','status')
if s['busy'] or s['requests'] or s['draining'] or (s['uncertain'] and s['state'] not in ('cold','ready')):raise RuntimeError('B70 must be idle and unpaused')
prior=next((p for p in profiles(original).values() if p['model']==s['model']),None)
def interrupted(_signal, _frame):
 raise InterruptedError('Own validation interrupted; restoring serving')
signal.signal(signal.SIGTERM, interrupted)
signal.signal(signal.SIGINT, interrupted)
operate('arcB70','pause')
try:
 modelctl.assert_idle(original)
 if prior and original.get('shared_serving'):operate('arcB70','unload',prior['id'])
 else:subprocess.run(['systemctl','--user','stop',original['service']],check=True)
 candidate=build_registry();m=next(iter(candidate['models'].values()))
 cmd=[candidate['binary'],'--host','127.0.0.1','--port','11457','-fa','on','--jinja',*m['args'],'-c','524288','--parallel','1','--api-key-file',original['backend_key_file']]
 subprocess.run(['systemd-run','--user','--unit=gpu-migration-b70-native',*cmd],check=True)
 key=Path(original['backend_key_file']).read_text().strip()
 def call(path,body=None,timeout=5):
  req=urllib.request.Request('http://127.0.0.1:11457'+path,data=json.dumps(body).encode() if body is not None else None,headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'})
  with urllib.request.urlopen(req,timeout=timeout) as r:return json.load(r)
 deadline=time.monotonic()+240
 while True:
  try:call('/health');break
  except Exception:
   if time.monotonic()>deadline:raise RuntimeError('native startup deadline exceeded')
   time.sleep(2)
 slots=call('/slots');assert len(slots)==1 and slots[0]['n_ctx']==524288,slots
 body={'messages':[{'role':'user','content':'Reply with exactly READY.'}],'max_tokens':32,'temperature':0,'chat_template_kwargs':{'enable_thinking':False}}
 reply=call('/v1/chat/completions',body,120)
 def chunk(t,b):return struct.pack('>I',len(b))+t+b+struct.pack('>I',zlib.crc32(t+b)&0xffffffff)
 raw=b''.join(b'\0'+b''.join(bytes((255,0,0) if x<64 else (0,0,255)) for x in range(128)) for y in range(128))
 png=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',128,128,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(raw))+chunk(b'IEND',b'')
 vision=call('/v1/chat/completions',{'messages':[{'role':'user','content':[{'type':'text','text':'Name the left colour and right colour.'},{'type':'image_url','image_url':{'url':'data:image/png;base64,'+base64.b64encode(png).decode()}}]}],'max_tokens':80,'temperature':0,'chat_template_kwargs':{'enable_thinking':False}},120)
 description=vision['choices'][0]['message']['content'].lower()
 assert 'red' in description and 'blue' in description,vision
 tools=[{'type':'function','function':{'name':'get_value','description':'Get the requested value','parameters':{'type':'object','properties':{'name':{'type':'string'}},'required':['name']}}}]
 tool=call('/v1/chat/completions',{'messages':[{'role':'user','content':'Call get_value for name answer.'}],'tools':tools,'tool_choice':{'type':'function','function':{'name':'get_value'}},'max_tokens':128,'temperature':0,'chat_template_kwargs':{'enable_thinking':False}},120)
 assert tool['choices'][0]['message']['tool_calls'][0]['function']['name']=='get_value',tool
 long_result = None
 if os.environ.get('LARIO_VALIDATE_FULL_CONTEXT') == '1':
  block='Synthetic archive filler: the component uses blue buttons and eight pixel spacing.\n'*256
  count=len(call('/tokenize',{'content':block},30)['tokens'])
  repeats=max(1,(518000//count)//3)
  filler=block*repeats
  prompt=('Read the archive and report exactly the values of KEY_ALPHA, KEY_BETA and KEY_GAMMA.\n'
          'KEY_ALPHA = cedar731\n'+filler+'KEY_BETA = quartz482\n'+filler+
          'KEY_GAMMA = maple956\n'+filler+'\nReport KEY_ALPHA, KEY_BETA and KEY_GAMMA now.')
  prompt_tokens=len(call('/tokenize',{'content':prompt},60)['tokens'])
  assert 500000 < prompt_tokens < 523000,prompt_tokens
  print(json.dumps({'stage':'full-window-prefill','prompt_tokens':prompt_tokens}),flush=True)
  start=time.monotonic()
  long_reply=call('/v1/chat/completions',{'messages':[{'role':'user','content':prompt}],
      'max_tokens':100,'temperature':0,'chat_template_kwargs':{'enable_thinking':False}},7200)
  answer=long_reply['choices'][0]['message']['content']
  passed=all(code in answer for code in ('cedar731','quartz482','maple956'))
  long_result={'prompt_tokens':prompt_tokens,'seconds':time.monotonic()-start,'answer':answer,'passed':passed,'usage':long_reply.get('usage')}
  Path.home().joinpath('.local/state/gpu-migration/b70-long.json').write_text(json.dumps(long_result,indent=2))
  if not passed:raise RuntimeError('Full-window retrieval failed; do not reduce context without reporting')
 result={'status':'passed-native-allocation-text-vision-tools-smoke','slots':slots,'reply':reply,'vision':vision,'tool':tool,'long_context':long_result,'command':cmd,'remaining':'full-window quality and sustained performance checks'}
 Path.home().joinpath('.local/state/gpu-migration/b70-native.json').write_text(json.dumps(result,indent=2))
 print(json.dumps({'status':result['status'],'reply':reply['choices'][0]['message'],'context':524288}),flush=True)
finally:
 subprocess.run(['systemctl','--user','stop','gpu-migration-b70-native'],stdout=subprocess.DEVNULL)
 subprocess.run(['systemctl','--user','start',original['service']],check=True)
 operate('arcB70','resume')
 if prior:operate('arcB70','activate',prior['id'])

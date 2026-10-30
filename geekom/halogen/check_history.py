import json,os,sys,time,urllib.request,urllib.error
from pathlib import Path
sys.path.insert(0,str(Path.home()/'Projects/personal/lario-llms'))
from shared import modelctl
from shared.serving.catalog import profiles
r=json.loads((modelctl.ROOT/'geekom/models.json').read_text());modelctl.load_runtime(r)
deadline=time.monotonic()+120
while time.monotonic()<deadline:
 try:
  with urllib.request.urlopen('http://127.0.0.1:18731/health',timeout=3) as f:h=json.load(f)
  if h.get('capability_probe')=='ok':break
 except OSError:pass
 time.sleep(1)
p=next(x for x in profiles(r).values() if x['model']=='qwen38-flash-halogen-128k')
running=modelctl.api(r,'/running')['running'];proxy=next(x['proxy'] for x in running if 'flash-halogen' in x['model'])
messages=[{'role':'system','content':'Use supplied tool results.'},{'role':'developer','content':'Be concise.'},
 {'role':'user','content':'Look up number 7.'},
 {'role':'assistant','content':None,'reasoning_content':'Use the lookup tool.',
  'tool_calls':[{'id':'call_fixture','type':'function','function':{'name':'lookup','arguments':'{"n":7}'}}]},
 {'role':'tool','tool_call_id':'call_fixture','content':'The result is 7.'},
 {'role':'user','content':'Reply with exactly 7. Do not call another tool.'}]
body={'model':p['id'],'messages':messages,'max_tokens':32,'temperature':0,'enable_thinking':False,
      'chat_template_kwargs':{'enable_thinking':False}}
def post(url,key,body):
 q=urllib.request.Request(url,data=json.dumps(body).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer '+key})
 with urllib.request.urlopen(q,timeout=60) as f:return json.load(f)
render=post(proxy+'/apply-template',os.environ['LARIO_BACKEND_KEY'],body)
assert '<parameter=n>' in render['prompt'] and '\n7\n</parameter>' in render['prompt']
answer=post('http://127.0.0.1:11434/v1/chat/completions',os.environ['LARIO_AUXILIARY_KEY'],body)
assert answer['choices'][0]['message']['content'].strip()=='7'
assert len(render['tokens'])==answer['usage']['prompt_tokens'],(len(render['tokens']),answer['usage'])
report={'status':'passed','string_tool_arguments':True,'developer_role':True,
        'template_tokens':len(render['tokens']),'native_prompt_tokens':answer['usage']['prompt_tokens'],'reply_correct':True}
(Path.home()/'halogen/history-switch-smoke.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report))

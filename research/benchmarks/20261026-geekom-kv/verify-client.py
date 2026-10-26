from pathlib import Path
import sys,json,urllib.request,urllib.error,importlib.util,socket,subprocess
root=Path.home()/'Projects/personal/lario-llms'
sys.path.insert(0,str(root))
from shared.serving.catalog import opencode, visible_profiles
path=root.parent/'machine-setup/scripts/render-agent-configs.py'
spec=importlib.util.spec_from_file_location('renderer',path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
config=Path.home()/'.config/opencode/opencode.json'
if not config.exists():config=config.with_suffix('.jsonc')
data=m.load_jsonc(str(config));expected=opencode()['provider']
result={'hostname':socket.gethostname(),'git_head':subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True).strip(),'git_status':subprocess.check_output(['git','-C',str(root),'status','--short'],text=True),'providers':{}}
for hardware in ['geekom','arcB70']:
 provider=data.get('provider',{}).get(hardware)
 if not provider:result['providers'][hardware]={'error':'provider_missing'};continue
 options=provider['options'];key=options['apiKey']
 if key.startswith('{file:') and key.endswith('}'):key=Path(key[6:-1]).expanduser().read_text().strip()
 req=urllib.request.Request(options['baseURL'].rstrip('/')+'/models',headers={'Authorization':'Bearer '+key})
 try:
  with urllib.request.urlopen(req,timeout=8) as response:catalog=json.load(response);status=response.status
  installed=provider['models'];source=expected[hardware]['models'] if hardware in expected else {k:{'name':p['name'],'limit':{'context':p['context']-4096,'output':8192}} for k,p in visible_profiles(json.loads((root/hardware/'models.json').read_text())).items()}
  matches=[k for k in installed if k in source and 'qwen' in k]
  bad=[k for k in matches if installed[k].get('limit')!=source[k].get('limit') or installed[k].get('name')!=source[k].get('name')]
  offered={x['id'] for x in catalog['data']}
  result['providers'][hardware]={'http_status':status,'matched_qwen_profiles':len(matches),'config_mismatches':bad,'configured_qwen_missing_from_catalog':[k for k in matches if k not in offered]}
 except Exception as exc:result['providers'][hardware]={'error':type(exc).__name__}
if '--infer-geekom' in sys.argv:
 provider=data['provider']['geekom'];options=provider['options'];key=options['apiKey']
 if key.startswith('{file:') and key.endswith('}'):key=Path(key[6:-1]).expanduser().read_text().strip()
 from shared.serving.catalog import profiles
 reg=json.loads((root/'geekom/models.json').read_text())
 profile=next(p for p in profiles(reg).values() if p['model']=='qwen3.8-smart-128k' and p['preset']=='capacity')
 body={'model':profile['id'],'messages':[{'role':'user','content':'Reply with KV READY.'}], 'max_tokens':16,'temperature':0,'chat_template_kwargs':{'enable_thinking':False}}
 request=urllib.request.Request(options['baseURL'].rstrip('/')+'/chat/completions',data=json.dumps(body).encode(),headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'})
 try:
  with urllib.request.urlopen(request,timeout=30) as response:reply=json.load(response);status=response.status
  result['geekom_inference']={'http_status':status,'reply':reply['choices'][0]['message'].get('content'),'usage':reply.get('usage'),'timings':reply.get('timings')}
 except Exception as exc:result['geekom_inference']={'error':type(exc).__name__}
print(json.dumps(result))

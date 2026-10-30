"""Cut over an idle retired B70 to a validated two-slot vLLM owner."""
import argparse,json,shutil,socket,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from shared import modelctl
from shared.serving.catalog import profiles,legacy_routes
from shared.serving.state import Store,state_directory


def build_registry(source,receipt):
 context=receipt['context_per_slot']
 if type(context) is not int or not 8192<=context<=262144:raise RuntimeError('Invalid validated context')
 reg=dict(source)
 reg['image']=json.loads(Path(__file__).with_name('manifest.json').read_text())['runtime_image']
 name='qwen3.8-gptq-int4'
 reg.update(serving_engine='vllm',service='lario-b70-vllm.service',binary=str(ROOT/'arcB70/vllm/run.py'),
            deployment_status='active',enabled_models=[name])
 reg.pop('shared_serving',None)
 reg['models']={name:{'display_name':'Qwen3.8 MTP','context':context,'native_context':262144,
   'slots':2,'reserved':0,'aliases':[],'vision':True,'experimental':False,
   'omit_provisional_label':True,'weight_quantization':'GPTQ INT4',
   'validation':receipt['status'],
   'args':['-m','/mnt/xfs/AI_Models/gptq/qwen38-27b-int4-asym','-ctk','fp8','-ctv','fp8']}}
 reg['presets']={'dual-vision-mtp':{'description':'Two equal native XPU sessions, GPTQ INT4, FP8 KV, patched MTP and vision','models':{name:{}}}}
 return reg


def install(receipt_path, smoke_only=False):
 if socket.gethostname().split('.')[0]!='bigcachy':raise RuntimeError('Run on registered owner')
 receipt=json.loads(receipt_path.read_text())
 allowed={'passed-native-capacity-concurrency-vision-long-retrieval'}
 if smoke_only:allowed.add('passed-native-capacity-concurrency-vision-tools-smoke')
 if receipt.get('status') not in allowed:raise RuntimeError('Native validation receipt required')
 from arcB70.vllm.prepare import command
 expected=[f'MAX_MODEL_LEN={receipt["context_per_slot"]}' if v.startswith('MAX_MODEL_LEN=') else v for v in command()]
 if receipt.get('command')!=expected:raise RuntimeError('Validation command differs from production candidate')
 path=ROOT/'arcB70/models.json';old=json.loads(path.read_text());reg=build_registry(old,receipt)
 from shared.serving.control import operate
 state=operate('arcB70','status')
 retirement=json.loads((Path.home()/'.local/state/gpu-migration/b70-retired-for-vllm.json').read_text())
 if state['revision']!=retirement['revision'] or not state['draining'] or not state['enabled'] or state['requests'] or state['busy']:
  raise RuntimeError('Retirement policy changed or B70 busy; preserving operator state')
 backup=Path.home()/'.local/state/gpu-migration'/('vllm-cutover-'+str(time.time_ns()));backup.mkdir()
 shutil.copy2(path,backup/'models.json')
 subprocess.run(['systemctl','--user','stop','lario-admission@arcB70.service','arcB70.service'],check=True)
 modelctl.atomic(path,json.dumps(reg,indent=2)+'\n')
 modelctl.save_selection(reg,'qwen3.8-gptq-int4','dual-vision-mtp')
 store=Store(state_directory(reg),{});(backup/'policy.json').write_text(json.dumps(store.get('policy')))
 store.change(legacy=legacy_routes(reg,'qwen3.8-gptq-int4','dual-vision-mtp'),disabled=[],paused=True);store.close()
 units=Path.home()/'.config/systemd/user';shutil.copy2(Path(__file__).with_name('lario-b70-vllm.service'),units/'lario-b70-vllm.service')
 subprocess.run(['systemctl','--user','daemon-reload'],check=True)
 subprocess.run(['systemctl','--user','disable','arcB70.service'],check=True)
 subprocess.run(['systemctl','--user','enable','--now',reg['service'],'lario-admission@arcB70.service'],check=True)
 for _ in range(600):
  try:
   state=operate('arcB70','status')
   if state.get('resident') and state['resident']['id']==next(iter(profiles(reg))):break
  except OSError:pass
  time.sleep(2)
 else:raise RuntimeError('vLLM cutover failed; gateway remains paused')
 operate('arcB70','resume')
 print(json.dumps({'status':'active','profile':next(iter(profiles(reg))),'backup':str(backup)}))

if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--receipt',required=True,type=Path);p.add_argument('--smoke-only',action='store_true',help='Explicit activation after native smoke; long-context quality remains untested');args=p.parse_args();install(args.receipt,args.smoke_only)

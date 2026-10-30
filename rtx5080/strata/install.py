"""Activate a natively validated RTX Strata profile without replacing credentials."""
import argparse,json,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from shared import modelctl
from shared.serving.catalog import profiles,render_backend,legacy_routes
from shared.serving.control import operate
from shared.serving.state import Store,state_directory
from rtx5080.strata.profile import build_registry

def install(receipt):
 proof=json.loads(receipt.read_text())
 if proof.get('status')!='passed-native-text-vision-tools-streaming':raise RuntimeError('Native RTX validation required')
 path=ROOT/'rtx5080/models.json';old=json.loads(path.read_text());candidate=build_registry(old)
 context=proof['context'];name='qwen38-flash-nvfp4';model=candidate['models'][name]
 if context not in (32768,65536,98304,131072,196608,262144):raise RuntimeError('Unexpected validated context')
 model['context']=context;model['experimental']=False;model['validation']=proof['status']
 preset=f'flash-nvfp4-vision-{context//1024}k'
 prior=candidate['presets'].pop('flash-nvfp4-vision-128k');prior.update(description=f'One native {context//1024}K CUDA Strata vision session',experimental=False)
 candidate['presets'][preset]=prior
 candidate['deployment_status']='active'
 tested=proof['command'];expected=[model['binary'],'--host','127.0.0.1','--port','11459','-c',str(context),'--parallel','1',*model['args'],'--api-key-file',candidate['backend_key_file']]
 if tested!=expected:raise RuntimeError('Receipt command does not match final profile')
 s=operate('rtx5080','status')
 if s['busy'] or s['requests'] or s['draining'] or s['loading_profile'] or not s['enabled']:raise RuntimeError('RTX must be idle and enabled')
 operate('rtx5080','pause');modelctl.load_runtime(old);modelctl.assert_idle(old)
 backup=Path.home()/'.local/state/gpu-migration'/('rtx-cutover-'+str(time.time_ns()));backup.mkdir()
 (backup/'models.json').write_text(path.read_text())
 subprocess.run(['systemctl','--user','stop',old['service'],'lario-admission@rtx5080.service'],check=True)
 modelctl.atomic(path,json.dumps(candidate,indent=2)+'\n')
 modelctl.save_selection(candidate,name,preset)
 modelctl.atomic(ROOT/candidate['config'],render_backend(candidate))
 store=Store(state_directory(candidate),{});(backup/'policy.json').write_text(json.dumps(store.get('policy')))
 store.change(legacy=legacy_routes(candidate,name,preset),disabled=[],paused=True);store.close()
 subprocess.run(['systemctl','--user','start',candidate['service'],'lario-admission@rtx5080.service'],check=True)
 for _ in range(60):
  try:
   if operate('rtx5080','status')['detail'] is None:break
  except OSError:pass
  time.sleep(1)
 else:raise RuntimeError('New RTX gateway not healthy; left paused')
 operate('rtx5080','resume')
 key=next(p['id'] for p in profiles(candidate).values() if p['model']==name)
 operate('rtx5080','activate',key)
 deadline=time.monotonic()+1800
 while time.monotonic()<deadline:
  s=operate('rtx5080','status')
  if s['ready'] and s['profile_id']==key:
   print(json.dumps({'status':'active','profile':key,'backup':str(backup)}));return
  if s['last_error'] and not s['loading_profile']:raise RuntimeError('Profile activation failed: '+s['last_error'])
  time.sleep(3)
 raise RuntimeError('RTX activation timed out')

if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--receipt',type=Path,required=True);install(p.parse_args().receipt)

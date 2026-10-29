#!/usr/bin/env python3
"""Install optional mirror units and credentials; never restart active inference."""
import json,os,secrets,socket,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from shared.egpu import registry
from shared.serving.provision_control import private

def install(hardware):
 reg=registry(hardware)
 if socket.gethostname().split('.')[0]!=reg['host']:raise RuntimeError('wrong owner')
 store=Path(reg['model_store'])
 if subprocess.check_output(['findmnt','-n','-o','FSTYPE','--target',str(store)],text=True).strip()!='xfs':raise RuntimeError('XFS store required')
 python=store/'admission/venv/bin/python'
 if not python.exists():
  subprocess.run([sys.executable,'-m','venv',str(python.parents[1])],check=True)
  subprocess.run([str(python),'-m','pip','install','-r',str(ROOT/'shared/admission/requirements.txt')],check=True)
 directory=Path.home()/'.config/lario-admission';envpath=directory/(hardware+'.env')
 env=dict(line.split('=',1) for line in envpath.read_text().splitlines() if '=' in line) if envpath.exists() else {}
 keypath=directory/(hardware+'.backend.key')
 if keypath.exists():
  old=keypath.read_text().strip()
  if env.get('LARIO_BACKEND_KEY',old)!=old:raise RuntimeError('private backend credential mismatch')
  env['LARIO_BACKEND_KEY']=old
 for role in ('INTERACTIVE','FLEET','AUXILIARY','MANAGEMENT','BACKEND'):env.setdefault('LARIO_'+role+'_KEY',secrets.token_urlsafe(36))
 env.update(LARIO_ADMISSION_ENABLED='1',LARIO_FIXED_PROFILES='1',LARIO_UPSTREAM=f'http://127.0.0.1:{reg["backend_port"]}',LARIO_PUBLIC_PORT=str(reg['port']),LARIO_LISTEN='0.0.0.0')
 private(envpath,''.join(k+'='+v+'\n' for k,v in env.items()));private(keypath,env['LARIO_BACKEND_KEY']+'\n');private(directory/(hardware+'.backend.env'),'LARIO_BACKEND_KEY='+env['LARIO_BACKEND_KEY']+'\n')
 units=Path.home()/'.config/systemd/user';units.mkdir(parents=True,exist_ok=True)
 target=units/(hardware+'.service');text=(ROOT/hardware/'systemd'/target.name).read_text()
 if not target.exists() or target.read_text()!=text:target.write_text(text)
 # Per-instance drop-in avoids changing the interpreter/mount of any live gateway.
 template=units/'lario-admission@.service'
 if not template.exists():template.write_text((ROOT/'shared/admission/systemd/lario-admission@.service').read_text().replace('@MODEL_MOUNT@',str(store)).replace('@PYTHON@',str(python)))
 drop=units/('lario-admission@'+hardware+'.service.d');drop.mkdir(exist_ok=True)
 (drop/'20-placement.conf').write_text(f'[Unit]\nRequiresMountsFor={store}\n[Service]\nExecStart=\nExecStart={python} %h/Projects/personal/lario-llms/shared/admission/server.py {hardware} --upstream ${{LARIO_UPSTREAM}} --port ${{LARIO_PUBLIC_PORT}}\n')
 subprocess.run(['systemctl','--user','daemon-reload'],check=True)
 subprocess.run(['systemctl','--user','enable',hardware+'.service','lario-admission@'+hardware+'.service'],check=True)
 subprocess.run(['systemctl','--user','start','lario-admission@'+hardware+'.service',hardware+'.service'],check=True)
 from shared.install_backend_watch import install as install_watch
 install_watch()
 print(hardware+': installed; absent card skips backend; authenticated gateway and recovery enabled')
if __name__=='__main__':install(sys.argv[1])

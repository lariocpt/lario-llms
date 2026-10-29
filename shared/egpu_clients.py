#!/usr/bin/env python3
"""Register each optional placement's client key without reloading OpenCode."""
import json,sys,subprocess,shlex,socket
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from shared.serving.provision_control import invoke, HOSTS, IPS
INSTALL=r'''
import json,sys,os,urllib.request
from pathlib import Path
b=json.load(sys.stdin)
r=urllib.request.Request(b['url']+'/v1/models',headers={'Authorization':'Bearer '+b['key']})
with urllib.request.urlopen(r,timeout=10) as response:
 assert response.status==200
path=Path.home()/'.config/lario-admission/clients.json'
data=json.loads(path.read_text()) if path.exists() else {}
data[b['hardware']]={'apiKey':b['key'],'enabled':True}
from shared.serving.provision_control import private
private(path,json.dumps(data,indent=2)+'\n')
print('optional eGPU credential installed')
'''
def main():
 for hardware in ('gkm3060ti','gdp7900xt'):
  reg=json.loads((ROOT/hardware/'models.json').read_text());owner_machine=next(m for m,h in HOSTS.items() if h==reg['host'])
  info=invoke(reg['host'],['owner-register',hardware])
  for machine,host in HOSTS.items():
   url='http://'+('127.0.0.1' if machine==owner_machine else IPS[owner_machine])+':'+str(reg['port'])
   # The owner gateway may be unreachable cross-host until the emitted firewall step is run.
   # Validate the credential on its loopback owner before distributing it via SSH.
   payload={'hardware':hardware,'key':info['clients'][machine],'url':url}
   command=[sys.executable,'-c',INSTALL] if host==socket.gethostname().split('.')[0] else ['ssh','-T',host,'cd ~/Projects/personal/lario-llms && python3 -c '+shlex.quote(INSTALL)]
   subprocess.run(command,input=json.dumps(payload),text=True,check=True)
  print(hardware+': registered and distributed client-scoped credentials')
if __name__=='__main__':main()

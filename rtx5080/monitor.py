#!/usr/bin/env python3
"""Check native RTX health and periodically infer with the current concrete profile."""
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.request
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from shared.modelctl import api,current,load_runtime,assert_idle,assert_device_ready

def main():
 root=Path(__file__).resolve().parents[1]
 reg=json.loads((root/'rtx5080/models.json').read_text())
 load_runtime(reg)
 state=Path(os.getenv('XDG_STATE_HOME',str(Path.home()/'.local/state')))/'vision-monitor'
 state.mkdir(parents=True,exist_ok=True)
 interval=int(os.getenv('VISION_ACTIVE_PROBE_INTERVAL','43200'))
 try:
  subprocess.run(['systemctl','--user','is-active','--quiet',reg['service']],check=True)
  assert_device_ready(reg)
  api(reg,'/health')
  key=current(reg)
  stamp=state/'last-active'
  last=float(stamp.read_text()) if stamp.exists() else 0
  if interval>0 and time.time()-last>=interval:
   try:assert_idle(reg)
   except RuntimeError:
    print(f'RTX profile {key}: ready; active probe skipped because occupancy is busy or unknown')
    return
   content='Reply OK.'
   if reg['models'][key].get('vision'):
    import base64,io
    from PIL import Image
    b=io.BytesIO();Image.new('RGB',(1536,1536),(96,120,160)).save(b,'PNG')
    content=[{'type':'text','text':'Describe the image colour in one word.'},{'type':'image_url','image_url':{'url':'data:image/png;base64,'+base64.b64encode(b.getvalue()).decode()}}]
   body={'model':key,'messages':[{'role':'user','content':content}],'max_tokens':32,'chat_template_kwargs':{'enable_thinking':False}}
   if os.environ.get('LARIO_ADMISSION_ENABLED')=='1':
    request=urllib.request.Request(f'http://127.0.0.1:{reg["port"]}/v1/chat/completions',data=json.dumps(body).encode(),
        headers={'Content-Type':'application/json','Authorization':'Bearer '+os.environ['LARIO_AUXILIARY_KEY']})
    with urllib.request.urlopen(request,timeout=300) as response:result=json.load(response)
   else:result=api(reg,'/v1/chat/completions',body,timeout=300)
   assert result.get('choices'), 'No completion'
   stamp.write_text(str(time.time()))
  print(f'RTX profile {key}: ready')
 except Exception as e:
  print(f'RTX monitor failed: {e}',file=sys.stderr);sys.exit(1)


if __name__=="__main__":main()

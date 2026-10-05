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
from shared.modelctl import api,current

root=Path(__file__).resolve().parents[1]
reg=json.loads((root/'rtx5080/models.json').read_text())
state=Path(os.getenv('XDG_STATE_HOME',str(Path.home()/'.local/state')))/'vision-monitor'
state.mkdir(parents=True,exist_ok=True)
interval=int(os.getenv('VISION_ACTIVE_PROBE_INTERVAL','43200'))
try:
 subprocess.run(['systemctl','--user','is-active','--quiet',reg['service']],check=True)
 api(reg,'/health')
 key=current(reg)
 stamp=state/'last-active'
 last=float(stamp.read_text()) if stamp.exists() else 0
 if interval>0 and time.time()-last>=interval:
  content='Reply OK.'
  if reg['models'][key].get('vision'):
   import base64,io
   from PIL import Image
   b=io.BytesIO();Image.new('RGB',(1536,1536),(96,120,160)).save(b,'PNG')
   content=[{'type':'text','text':'Describe the image colour in one word.'},{'type':'image_url','image_url':{'url':'data:image/png;base64,'+base64.b64encode(b.getvalue()).decode()}}]
  result=api(reg,'/v1/chat/completions',{'model':key,'messages':[{'role':'user','content':content}],'max_tokens':32,'chat_template_kwargs':{'enable_thinking':False}},timeout=300)
  assert result.get('choices'), 'No completion'
  stamp.write_text(str(time.time()))
 print(f'RTX profile {key}: ready')
except Exception as e:
 print(f'RTX monitor failed: {e}',file=sys.stderr);sys.exit(1)

"""Download pinned GPTQ weights to XFS without changing live B70 serving."""
from concurrent.futures import ThreadPoolExecutor
import fcntl,hashlib,json,shutil,time,urllib.request
from pathlib import Path

def digest(path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  while b:=f.read(8*1024*1024):h.update(b)
 return h.hexdigest()

def main():
 m=json.loads(Path(__file__).with_name('manifest.json').read_text());root=Path(m['model_directory']);root.mkdir(parents=True,exist_ok=True)
 state=Path.home()/'.local/state/gpu-migration';state.mkdir(parents=True,exist_ok=True)
 def fetch(item):
  p=root/item['filename'];p.parent.mkdir(parents=True,exist_ok=True)
  if p.exists() and p.stat().st_size==item['bytes'] and (not item['sha256'] or digest(p)==item['sha256']):return
  part=p.with_name(p.name+'.part')
  for attempt in range(8):
   try:
    offset=part.stat().st_size if part.exists() else 0
    if offset<item['bytes']:
     req=urllib.request.Request(f"https://huggingface.co/{m['repository']}/resolve/{m['revision']}/{item['filename']}",headers={'Range':f'bytes={offset}-'} if offset else {})
     with urllib.request.urlopen(req,timeout=300) as response,part.open('ab' if offset and response.status==206 else 'wb') as stream:
      while block:=response.read(8*1024*1024):stream.write(block)
    if part.stat().st_size!=item['bytes']:
     if part.stat().st_size>item['bytes']:part.unlink()
     raise OSError('Incomplete weight transfer: '+str(part))
    if item['sha256'] and digest(part)!=item['sha256']:
     part.unlink()
     raise OSError('Weight checksum mismatch; retrying: '+str(part))
    part.replace(p);print('Verified '+item['filename'],flush=True);return
   except OSError:
    if attempt==7:raise
    time.sleep(min(2**attempt,30))
 with (state/'vllm-weights.lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  needed=sum(max(0,f['bytes']-(root/f['filename']).stat().st_size) if (root/f['filename']).exists() else f['bytes'] for f in m['files'])
  if shutil.disk_usage(root).free<needed+10*1024**3:raise RuntimeError('Insufficient free model-store space')
  with ThreadPoolExecutor(max_workers=3) as pool:list(pool.map(fetch,m['files']))
  (state/'vllm-weights-complete.json').write_text(json.dumps({'repository':m['repository'],'revision':m['revision'],'status':'verified'}))
if __name__=='__main__':main()

#!/usr/bin/env python3
"""Delete only model downloads excluded by the hardware registries and Intel runtime.

Default is a reviewable JSON plan. --apply rechecks every retained file and aborts
on any unknown live model, overlapping/symlinked deletion root, or recent download.
Run on each model host. This never prunes Docker, projects, databases or media.
"""
import argparse,json,os,re,shutil,socket,subprocess,time,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--apply',action='store_true');p.add_argument('--output',required=True);a=p.parse_args()
host=socket.gethostname().split('.')[0]
if host not in ('bigcachy','l-dev-ai'):raise SystemExit('Only the two model hosts are supported')
base=Path('/mnt/xfs/AI_Models' if host=='bigcachy' else '/mnt/AI_Models')
if subprocess.check_output(['findmnt','-n','-o','FSTYPE','-T',str(base)],text=True).strip()!='xfs':raise SystemExit('XFS mount is missing')
hardware=['7900xt','rtx5080'] if host=='bigcachy' else ['geekom']
protected=set();live=[]
for h in hardware:
 reg=json.loads((ROOT/h/'models.json').read_text())
 for model in reg['models'].values():
  args=model['args']
  for flag in ['-m','--model','-md','--model-draft','--mmproj']:
   if flag not in args:continue
   path=Path(args[args.index(flag)+1].replace('/models/',str(base)+'/'))
   if not path.is_file():raise SystemExit('Retained model file missing: '+str(path))
   protected.update((path.absolute(),path.resolve()))
   if re.search(r'-00001-of-\d+\.gguf$',path.name):
    shards=list(path.parent.glob(re.sub(r'-00001-of-', '-*-of-',path.name)))
    expected=int(re.search(r'-of-(\d+)\.gguf$',path.name).group(1))
    if len(shards)!=expected:raise SystemExit('Missing retained split shards')
    protected.update(p for s in shards for p in (s.absolute(),s.resolve()))
 with urllib.request.urlopen(f'http://127.0.0.1:{reg["port"]}/running',timeout=5) as response:running=json.load(response)['running']
 for m in running:
  if m['model'] not in reg['models']:raise SystemExit('Unknown live model; audit first: '+m['model'])
 live.append({'hardware':h,'running':[{k:m.get(k) for k in ('model','state')} for m in running]})
for path in protected:
 with path.open('rb') as stream:
  if stream.read(4)!=b'GGUF':raise SystemExit('Invalid retained GGUF: '+str(path))
if host=='bigcachy':
 for line in (ROOT/'intel/runtime.env').read_text().splitlines():
  if '_MODEL_DIR=' not in line:continue
  directory=Path(line.split('=',1)[1])
  if not directory.is_dir():raise SystemExit('Missing Intel export: '+str(directory))
  if not list(directory.glob('*.xml')):raise SystemExit('Intel export has no IR: '+str(directory))
  protected.update(p for f in directory.rglob('*') if f.is_file() for p in (f.absolute(),f.resolve()))
 image_manifest=ROOT/'rtx5080/image-generation/install-manifest.json'
 if image_manifest.exists():
  manifest=json.loads(image_manifest.read_text())
  image_root=Path(manifest['root'])
  if not image_root.is_relative_to(base):raise SystemExit('Image models must remain on owner XFS')
  for item in manifest['files']:
   path=image_root/'models'/item['target']
   if not path.is_file() or path.stat().st_size!=item['size']:
    raise SystemExit('Retained image model missing/incomplete; finish installation before cleanup: '+str(path))
   protected.update((path.absolute(),path.resolve()))
# Candidate roots are dedicated model download/cache locations, never model mount roots.
candidates=[]
for directory in [base/'gguf',base/'huggingface/hub',base/'llama.cpp-cache']:
 if directory.is_dir():candidates.extend(p for p in directory.iterdir() if p.is_dir() and (directory.name=='gguf' or p.name.startswith('models--')))
if host=='bigcachy':
 candidates.extend([base/'huggingface.tar',base/'openvino/npu-compiler'])
 for directory in [base/'openvino/embeddings',base/'openvino/asr']:
  candidates.extend(p for p in directory.iterdir() if p.is_dir())
 cache=Path.home()/'.cache/huggingface/hub'
 if cache.is_dir():candidates.extend(p for p in cache.iterdir() if p.is_dir() and p.name.startswith('models--'))
# Keep any directory containing retained files, including all referenced symlink targets.
remove=[]
for path in sorted(set(candidates)):
 if not path.exists():continue
 if path.is_symlink():raise SystemExit('Candidate is symlink; audit manually: '+str(path))
 resolved=path.resolve()
 if any(f==resolved or resolved in f.parents for f in protected):continue
 files=[path] if path.is_file() else [f for f in path.rglob('*') if f.is_file() and not f.is_symlink()]
 recent=[str(f) for f in files if f.stat().st_size>100_000_000 and time.time()-f.stat().st_mtime<1800]
 if recent:raise SystemExit('Recently modified model download; audit first: '+', '.join(recent))
 remove.append({'path':str(path),'bytes':sum(f.stat().st_size for f in files),'allocated_bytes':sum(f.stat().st_blocks*512 for f in files)})
# Within Geekom's protected HF repository, delete only unreferenced GGUF links/blobs.
if host=='l-dev-ai':
 cache=base/'huggingface/hub/models--unsloth--Qwen3.8-27B-GGUF'
 for directory in ['snapshots','blobs']:
  for path in sorted((cache/directory).rglob('*')):
   if path.is_file() and (path.suffix=='.gguf' or directory=='blobs') and path.resolve() not in protected and (path.suffix=='.gguf' or path.stat().st_size>100_000_000):
    # Shared HF directories are retained wholesale above; their individual
    # unreferenced blobs need the same in-progress-download check as roots.
    if path.stat().st_size>100_000_000 and time.time()-path.stat().st_mtime<1800:
     raise SystemExit('Recently modified model download; audit first: '+str(path))
    remove.append({'path':str(path),'bytes':0 if path.is_symlink() else path.stat().st_size,'allocated_bytes':0 if path.is_symlink() else path.stat().st_blocks*512})
report={'host':host,'time_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'live':live,'protected_files':sorted(map(str,protected)),'remove':remove,'removed_bytes':sum(x['bytes'] for x in remove),'removed_allocated_bytes':sum(x['allocated_bytes'] for x in remove),'applied':False}
output=Path(a.output);output.write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({'host':host,'paths':len(remove),'GB':report['removed_bytes']/1e9,'allocated_GB':report['removed_allocated_bytes']/1e9,'apply':a.apply}))
if a.apply:
 for item in remove:
  path=Path(item['path'])
  # Recheck overlap immediately before deletion, not just at plan generation.
  if path.resolve() in protected or any(path.resolve() in f.parents for f in protected):raise SystemExit('Protected path overlap')
  if path.is_dir() and not path.is_symlink():shutil.rmtree(path)
  else:path.unlink()
  item['deleted']=True
  output.write_text(json.dumps(report,indent=2)+'\n')
 report['applied']=True
 for f in protected:
  if not f.is_file():raise SystemExit('Retained file missing after cleanup: '+str(f))
 output.write_text(json.dumps(report,indent=2)+'\n')
 print('Deleted unused downloads; all protected model files remain.')

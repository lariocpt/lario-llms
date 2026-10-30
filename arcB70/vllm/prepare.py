"""Build an isolated B70 candidate command; never modify active serving."""
import argparse,json,os,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from shared.gpu import intel_arc_device


def command():
    manifest=json.loads(Path(__file__).with_name('manifest.json').read_text())
    device=intel_arc_device()
    model=Path(manifest['model_directory'])
    missing=[f['filename'] for f in manifest['files'] if not (model/f['filename']).is_file() or (model/f['filename']).stat().st_size!=f['bytes']]
    if missing:raise RuntimeError(f'Model download incomplete: {len(missing)} files pending')
    software_root=subprocess.check_output(['docker','info','--format','{{.DockerRootDir}}'],text=True).strip()
    if subprocess.check_output(['findmnt','-n','-o','FSTYPE','-T',software_root],text=True).strip()=='xfs':raise RuntimeError('Container software must not run from XFS')
    caches=Path.home()/'.cache/lario-vllm-b70';caches.mkdir(parents=True,exist_ok=True)
    if subprocess.check_output(['findmnt','-n','-o','FSTYPE','-T',str(caches)],text=True).strip()=='xfs':raise RuntimeError('Compiled caches must not use XFS')
    hf=Path('/mnt/xfs/AI_Models/cache/vllm-b70');hf.mkdir(parents=True,exist_ok=True)
    argv=['docker','run','--rm','--name','lario-b70-vllm-candidate','--device',device['render'],
          '--shm-size','8g','-p','127.0.0.1:11458:8000',
          '-v',str(model)+':/models/qwen38:ro','-v',str(caches)+':/runtime-cache','-v',str(hf)+':/hf-cache']
    env={'MODEL':'/models/qwen38','MAX_MODEL_LEN':'262144','GPU_UTIL':'0.97','SERVED_NAME':'qwen38-b70-vllm',
         'B70_MTP_K':'4','B70_GDN_STATE':'fp32','FAST':'1','HF_HOME':'/hf-cache',
         'XDG_CACHE_HOME':'/runtime-cache','VLLM_CACHE_ROOT':'/runtime-cache/vllm',
         'TORCHINDUCTOR_CACHE_DIR':'/runtime-cache/torchinductor','TRITON_CACHE_DIR':'/runtime-cache/triton'}
    for key,value in env.items():argv+=['-e',key+'='+value]
    argv += [manifest['runtime_image'],'--max-num-seqs','2','--max-num-batched-tokens','4096',
             '--compilation-config','{"cudagraph_capture_sizes":[1,2,4,5,8,10]}']
    return argv


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--run',action='store_true');args=parser.parse_args()
    argv=command()
    if args.run:
        # Explicit idle checks and draining belong to the validation/cutover
        # driver; refuse an unguarded start beside the existing B70 model.
        raise SystemExit('Use the owner validation driver after draining native work; candidate command only')
    print(json.dumps({'command':argv,'slots':2,'context_per_slot':262144,
        'minimum_usable_kv_tokens':524288,'status':'candidate; allocation/concurrency/vision validation required'},indent=2))

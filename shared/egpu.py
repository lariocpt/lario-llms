"""Optional eGPU mirrors: host/physical identity pinned, no pull or CPU fallback."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1]

def registry(hardware):
    if hardware not in ('gkm3060ti','gdp7900xt'):
        raise ValueError('unknown mirrored eGPU')
    return json.loads((ROOT/hardware/'models.json').read_text())

def check(reg):
    from shared import modelctl
    from shared.lifecycle import stop_marker
    from shared.serving.state import off_marker
    if socket.gethostname().split('.')[0]!=reg['host']:
        raise RuntimeError('wrong eGPU owner')
    if stop_marker(reg).exists() or off_marker(reg).exists():
        raise RuntimeError('eGPU explicitly stopped')
    result=subprocess.run(['findmnt','-n','-o','FSTYPE','--target',reg['model_store']],capture_output=True,text=True,timeout=5,check=True)
    if result.stdout.strip()!='xfs':raise RuntimeError('XFS model store unavailable')
    modelctl.assert_device_ready(reg)

def podman(reg):
    hardware=reg['aliases'][0]
    return ['podman','--root',reg.get('runtime_store',str(Path(reg['model_store'])/'containers'/hardware)),'--runroot',os.environ.get('XDG_RUNTIME_DIR',f'/run/user/{os.getuid()}')+'/lario-'+hardware+('-home-podman' if reg.get('runtime_store') else '-podman')]

def command(reg):
    from shared.gpu import nvidia_device, radeon_device
    hardware=reg['aliases'][0];store=Path(reg['model_store']);private=Path.home()/'.config/lario-admission'
    args=podman(reg)+['run','--rm','--replace','--name',reg['container'],'--pull=never','--security-opt','label=disable','--shm-size=2g']
    if reg['device_family']=='radeon':
        card=radeon_device(reg['device_identity'])
        args+=['--device','/dev/kfd','--device','/dev/dri','--group-add','keep-groups','--env','ROCR_VISIBLE_DEVICES=GPU-'+card['unique_id'],'-v','/usr/share/libdrm:/usr/share/libdrm:ro']
    else:
        card=nvidia_device(reg['device_identity'])
        for node in ('nvidia0','nvidiactl','nvidia-uvm','nvidia-uvm-tools'):args+=['--device','/dev/'+node]
        args+=['--env','CUDA_VISIBLE_DEVICES='+card['uuid']]
        for lib in ('libcuda.so.1','libnvidia-ml.so.1'):args+=['-v',f'/usr/lib/{lib}:/usr/lib/x86_64-linux-gnu/{lib}:ro']
    args+=['-p',f'127.0.0.1:{reg["backend_port"]}:8080','--env-file',str(private/(hardware+'.backend.env')),
           '-v',reg.get('swap_binary',str(store/'bin/llama-swap'))+':/usr/local/bin/llama-swap:ro','-v',str(ROOT/'llama-cpp')+':/config:ro',
           '-v',str(store/'gguf')+':/models/gguf:ro','-v',str(private/(hardware+'.backend.key'))+':'+reg['backend_key_file']+':ro',
           '--entrypoint','/usr/local/bin/llama-swap',reg.get('image_config_id',reg['image']),'-config','/config/'+Path(reg['config']).name,'-listen',':8080']
    return args

def main(hardware):
    reg=registry(hardware)
    if len(sys.argv)!=2 or sys.argv[1] not in ('check','run'):raise ValueError('use check or run')
    check(reg)
    if sys.argv[1]=='check':return
    from shared import modelctl
    from shared.serving.catalog import render_backend
    modelctl.load_runtime(reg)
    modelctl.atomic(ROOT/reg['config'],render_backend(reg))
    argv=command(reg)
    probe=argv[:argv.index('--entrypoint')]+['--entrypoint',reg['binary'],reg.get('image_config_id',reg['image']),'--list-devices']
    probe[probe.index('--name')+1]+='-verify'
    at=probe.index('-p');del probe[at:at+2]
    result=subprocess.run(probe,capture_output=True,text=True,timeout=90,check=True)
    prefix='ROCm' if reg['device_family']=='radeon' else 'CUDA'
    expected='AMD Radeon RX 7900 XT' if reg['device_family']=='radeon' else 'NVIDIA GeForce RTX 3060 Ti'
    devices=[line.strip() for line in (result.stdout+'\n'+result.stderr).splitlines() if line.strip().startswith(prefix)]
    if len(devices)!=1 or expected not in devices[0]:raise RuntimeError('registered GPU compute unavailable; CPU/iGPU fallback refused')
    os.execvp(argv[0],argv)

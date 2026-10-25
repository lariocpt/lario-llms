#!/usr/bin/env python3
"""Run the registered RTX 3060 Ti eGPU in rootless Podman (CUDA); never fall back to CPU.

Mirrors the geekom7900xt eGPU contract: device identity by UUID, fail-closed presence
checks, dedicated podman store on XFS, llama-swap from the host binary store,
and a physical-card verification inside the image before serving.
"""
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from shared.gpu import nvidia_device
from shared.lifecycle import stop_marker
from shared.serving.state import off_marker

STORE = Path('/mnt/xfs/AI_Models')
DRIVER_BINDS = ('/usr/lib/libcuda.so.1', '/usr/lib/libnvidia-ml.so.1')
DRIVER_TARGETS = ('/usr/lib/x86_64-linux-gnu/libcuda.so.1',
                  '/usr/lib/x86_64-linux-gnu/libnvidia-ml.so.1')


def render(reg):
    # Canonical fleet ids/commands via shared/serving/catalog; the two extra
    # keys make the default profile resident at boot instead of waiting for
    # the first request (design work wants the cold load during boot, not at
    # click time; measured cold load ~15 s over the eGPU link).
    from shared.serving.catalog import profiles, render_backend
    entries = profiles(reg)
    default_model = next((m for m, s in reg['models'].items() if s.get('default')), None)
    default = next((p['id'] for p in entries.values() if p['model'] == default_model),
                   next(iter(entries)))
    text = render_backend(reg)
    text = text.replace('models:', f'startModel: true\ndefaultProfile: {json.dumps(default)}\nmodels:', 1)
    target = ROOT/reg['config']
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.is_file() or target.read_text() != text:
        target.write_text(text)


def podman(reg):
    return ['podman', '--root', str(STORE/'containers/rtx3060ti'), '--runroot',
            os.environ.get('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}')+'/lario-rtx3060ti-podman']


def command(reg):
    private = Path.home()/'.config/lario-admission'
    argv = podman(reg) + ['run', '--rm', '--name', reg['container'], '--pull=never']
    for node in ('/dev/nvidia0', '/dev/nvidiactl', '/dev/nvidia-uvm', '/dev/nvidia-uvm-tools'):
        argv += ['--device', node]
    for source, target in zip(DRIVER_BINDS, DRIVER_TARGETS):
        argv += ['--volume', f'{source}:{target}:ro']
    argv += ['--security-opt', 'label=disable', '--shm-size=2g', '--replace',
             '-p', f'127.0.0.1:{reg["backend_port"]}:8080',
             '--env-file', str(private/'rtx3060ti.backend.env'),
             '-v', str(STORE/'bin/llama-swap')+':/usr/local/bin/llama-swap:ro',
             '-v', str(ROOT/'rtx3060ti/config')+':/config:ro',
             '-v', str(STORE/'gguf')+':/models/gguf:ro',
             '-v', str(private/'rtx3060ti.backend.key')+':/run/lario-admission/rtx3060ti.backend.key:ro',
             '--entrypoint', '/usr/local/bin/llama-swap', reg['image'],
             '-config', '/config/generated.yaml', '-listen', ':8080']
    return argv


def verify_compute(reg):
    # Fail closed exactly like the Radeon backend: the container must see the
    # physical CUDA device; a CPU-only llama.cpp is refused, not served.
    probe = command(reg)
    probe = probe[:probe.index('--entrypoint')]+[
        '--entrypoint', reg['binary'], reg['image'], '--list-devices']
    probe[probe.index('--name')+1] = reg['container']+'-verify'
    for _ in range(probe.count('-p')):  # probe must not fight the live backend for the port
        probe.remove('-p')
        probe.pop(probe.index('127.0.0.1:%d:8080' % reg['backend_port']))
    result = subprocess.run(probe, capture_output=True, text=True, timeout=90, check=True)
    devices = [line.strip() for line in result.stdout.splitlines()
               if line.strip().startswith('CUDA')]
    if len(devices) != 1 or 'NVIDIA GeForce RTX 3060 Ti' not in devices[0]:
        raise RuntimeError('physical RTX 3060 Ti CUDA compute unavailable; CPU fallback refused')
    print(devices[0], flush=True)


def main():
    reg = json.loads((ROOT/'rtx3060ti/models.json').read_text())
    if len(sys.argv) != 2 or sys.argv[1] not in ('check', 'run'):
        raise ValueError('use check or run')
    if stop_marker(reg).exists() or off_marker(reg).exists():
        raise RuntimeError('rtx3060ti was stopped explicitly for this boot')
    if not Path('/mnt/xfs').is_mount():
        raise RuntimeError('XFS model partition is not mounted')
    nvidia_device(reg['device_identity'])
    if sys.argv[1] == 'check':
        return
    subprocess.run(podman(reg)+['image', 'inspect', reg['image']],
                   capture_output=True, check=True)
    verify_compute(reg)
    render(reg)
    argv = command(reg)
    os.execvp(argv[0], argv)


if __name__ == '__main__':
    main()

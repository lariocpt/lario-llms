#!/usr/bin/env python3
"""Run the registered eGPU in rootless Podman; never pull or select an iGPU."""
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from shared.gpu import radeon_device
from shared.lifecycle import stop_marker

STORE = Path('/mnt/xfs/AI_Models')


def command(reg, device):
    private = Path.home()/'.config/lario-admission'
    return ['podman', '--root', str(STORE/'containers/7900xt'), '--runroot',
            os.environ.get('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}')+'/lario-7900xt-podman',
            'run', '--rm', '--name', reg['container'], '--pull=never',
            '--device', '/dev/kfd', '--device', '/dev/dri',
            '--env', 'ROCR_VISIBLE_DEVICES=GPU-'+device['unique_id'],
            '--group-add', 'keep-groups', '--security-opt', 'label=disable',
            '--shm-size=2g', '-p', f'127.0.0.1:{reg["backend_port"]}:8080',
            '--env-file', str(private/'7900xt.backend.env'),
            '-v', str(STORE/'bin/llama-swap')+':/usr/local/bin/llama-swap:ro',
            '-v', str(ROOT/'llama-cpp')+':/config:ro',
            '-v', str(STORE/'gguf')+':/models/gguf:ro',
            '-v', '/usr/share/libdrm:/usr/share/libdrm:ro',
            '-v', str(private/'7900xt.backend.key')+':/run/lario-admission/7900xt.backend.key:ro',
            '--entrypoint', '/usr/local/bin/llama-swap', reg['image'],
            '-config', '/config/agent-config.yaml', '-listen', ':8080']


def verify_compute(argv, image):
    probe = argv[:argv.index('--entrypoint')]+[
        '--entrypoint', '/app/llama-server', image, '--list-devices']
    result = subprocess.run(probe, capture_output=True, text=True, timeout=60, check=True)
    devices = [line.strip() for line in result.stdout.splitlines()
               if line.strip().startswith('ROCm')]
    if len(devices) != 1 or 'AMD Radeon RX 7900 XT (' not in devices[0]:
        raise RuntimeError('physical RX 7900 XT ROCm compute unavailable; CPU/iGPU fallback refused')
    print(devices[0], flush=True)


def main():
    reg = json.loads((ROOT/'7900xt/models.json').read_text())
    if len(sys.argv) != 2 or sys.argv[1] not in ('check', 'run'):
        raise ValueError('use check or run')
    if stop_marker(reg).exists():
        raise RuntimeError('7900xt was stopped explicitly for this boot')
    if not Path('/mnt/xfs').is_mount():
        raise RuntimeError('XFS model partition is not mounted')
    device = radeon_device(reg['device_identity'])
    if sys.argv[1] == 'run':
        argv = command(reg, device)
        # ROCr needs the DRM directory to enumerate this mixed dGPU/iGPU host.
        # Select the verified physical UUID and fail closed instead of allowing
        # llama.cpp's otherwise silent CPU fallback when ROCm cannot initialize.
        verify_compute(argv, reg['image'])
        os.execvp('podman', argv)
    print(json.dumps(device))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)

"""Shared rootless-Podman ROCm runtime for one physical RX 7900 XT placement.

Each placement keeps its own entrypoint that pins the hardware name, registry
and model store; this module owns the podman command, the ROCm probe and the
fail-closed device/mount checks. Never pull, and never select an iGPU.
"""
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def podman_command(reg, device, store, hardware):
    private = Path.home()/'.config/lario-admission'
    return ['podman', '--root', str(store/'containers'/hardware), '--runroot',
            os.environ.get('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}')+f'/lario-{hardware}-podman',
            'run', '--rm', '--name', reg['container'], '--pull=never',
            '--device', '/dev/kfd', '--device', '/dev/dri',
            '--env', 'ROCR_VISIBLE_DEVICES=GPU-'+device['unique_id'],
            '--group-add', 'keep-groups', '--security-opt', 'label=disable',
            '--shm-size=2g', '-p', f'127.0.0.1:{reg["backend_port"]}:8080',
            '--env-file', str(private/f'{hardware}.backend.env'),
            '-v', str(store/'bin/llama-swap')+':/usr/local/bin/llama-swap:ro',
            '-v', str(ROOT/'llama-cpp')+':/config:ro',
            '-v', str(store/'gguf')+':/models/gguf:ro',
            '-v', '/usr/share/libdrm:/usr/share/libdrm:ro',
            '-v', str(private/f'{hardware}.backend.key')+':'+reg['backend_key_file']+':ro',
            '--entrypoint', '/usr/local/bin/llama-swap', reg['image'],
            '-config', '/config/' + Path(reg['config']).name, '-listen', ':8080']


def verify_compute(argv, image):
    probe = argv[:argv.index('--entrypoint')]+[
        '--entrypoint', '/app/llama-server', image, '--list-devices']
    result = subprocess.run(probe, capture_output=True, text=True, timeout=60, check=True)
    devices = [line.strip() for line in result.stdout.splitlines()
               if line.strip().startswith('ROCm')]
    if len(devices) != 1 or 'AMD Radeon RX 7900 XT (' not in devices[0]:
        raise RuntimeError('physical RX 7900 XT ROCm compute unavailable; CPU/iGPU fallback refused')
    print(devices[0], flush=True)


def store_mounted(store):
    # An ancestor mount (including the root filesystem) is not the model store.
    if not store.is_mount():
        return False
    result = subprocess.run(['findmnt', '-n', '-o', 'FSTYPE', '--mountpoint', str(store)],
                            capture_output=True, text=True, timeout=5, check=True)
    return result.stdout.strip() == 'xfs'


def guard(aliases, store):
    from shared.lifecycle import stop_marker
    if stop_marker({'aliases': aliases}).exists():
        raise RuntimeError('hardware was stopped explicitly for this boot')
    if not store_mounted(store):
        raise RuntimeError('XFS model partition is not mounted')


def check(aliases, identity, store):
    guard(aliases, store)
    from shared.gpu import radeon_device
    print(json.dumps(radeon_device(identity)))


def run(reg, store, hardware):
    guard(reg['aliases'], store)
    if not (store/'gguf').is_dir() or not (store/'bin'/'llama-swap').is_file():
        raise RuntimeError(f'{store} is missing gguf/ or bin/llama-swap; provision the Radeon store first')
    from shared.gpu import radeon_device
    device = radeon_device(reg['device_identity'])
    argv = podman_command(reg, device, store, hardware)
    # ROCr needs the DRM directory to enumerate this mixed dGPU/iGPU host.
    # Select the verified physical UUID and fail closed instead of allowing
    # llama.cpp's otherwise silent CPU fallback when ROCm cannot initialize.
    verify_compute(argv, reg['image'])
    os.execvp('podman', argv)

#!/usr/bin/env python3
"""Borrow the idle RTX for one bounded image job, then restore its chat selection."""
import argparse
import contextlib
import fcntl
import io
import json
import os
from pathlib import Path
import socket
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO))
from shared import modelctl
from workflows import graph

ROOT = Path('/mnt/xfs/AI_Models/image-generation')
BASE = 'http://127.0.0.1:8188'
SERVICE = 'lario-images.service'


def api(path, payload=None):
    req = urllib.request.Request(BASE + path, data=None if payload is None else json.dumps(payload).encode(),
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=15) as response:
        return json.load(response)


def runtime_installed():
    unit = Path.home() / '.config/systemd/user' / SERVICE
    return ((ROOT / 'runtime/venv/bin/python').is_file()
            and (ROOT / 'runtime/ComfyUI/main.py').is_file()
            and (ROOT / 'runtime/ComfyUI/custom_nodes/ComfyUI-GGUF/__init__.py').is_file()
            and (HERE / 'requirements.lock').is_file()
            and unit.is_file() and unit.read_text() == (HERE / SERVICE).read_text())


def installed(model=None):
    manifest = json.loads((HERE / 'install-manifest.json').read_text())
    selected = {'qwen-image': {'qwen-image-2.1-UC-Q4_K_M.gguf', 'qwen3vl_8b_int8_convrot.safetensors', 'qwen_image_2.1_vae_bf16.safetensors'},
                'flux-klein': {'flux-2-klein-4b.safetensors', 'qwen_3_4b.safetensors', 'flux2-vae.safetensors'}}
    return runtime_installed() and all((ROOT / 'models' / item['target']).is_file()
               and (ROOT / 'models' / item['target']).stat().st_size == item['size'] for item in manifest['files']
               if model is None or Path(item['target']).name in selected[model])


def command(action, service):
    subprocess.run(['systemctl', '--user', action, service], check=True, stdout=subprocess.DEVNULL)


def generate(request):
    allowed = {'model', 'prompt', 'width', 'height', 'seed', 'steps'}
    if set(request) - allowed:
        raise ValueError('unknown image arguments')
    workflow = graph(**request)
    if socket.gethostname().split('.')[0] != 'bigcachy':
        raise RuntimeError('image generation must run on bigcachy')
    if not installed(request['model']):
        raise RuntimeError('image bundles are not fully installed')
    reg = json.loads((REPO / 'rtx5080/models.json').read_text())
    modelctl.load_runtime(reg)
    result = {'model': request['model'], 'owner': 'bigcachy', 'scope': 'Exclusive RTX job; encoder/cache offloaded to CPU; restores saved chat selection.'}
    with (REPO / '.rtx5080.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        modelctl.assert_not_held(reg)
        modelctl.assert_device_ready(reg)
        modelctl.assert_idle(reg)
        running = subprocess.run(['systemctl', '--user', 'is-active', SERVICE], capture_output=True, text=True)
        if running.returncode == 0:
            raise RuntimeError('image runtime already active; refusing to borrow another job')
        try:
            connection = socket.create_connection(('127.0.0.1', 8188), timeout=1)
        except OSError:
            pass
        else:
            connection.close()
            raise RuntimeError('port 8188 is already in use; refusing a foreign image runtime')
        available = next(int(line.split()[1]) for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith('MemAvailable:'))
        if available < 40 * 1024 ** 2:
            raise RuntimeError('need at least 40 GiB available host RAM for CPU encoding/offload')
        # Complete validation precedes drain/stop. Never alter the saved alias or preset.
        selected = modelctl.selection(reg)
        result['chat_selection'] = {'model': selected[0], 'preset': selected[1]}
        was_active = subprocess.run(['systemctl', '--user', 'is-active', reg['service']], capture_output=True).returncode == 0
        started = time.monotonic()
        modelctl.admission_admin(reg, 'drain')
        try:
            modelctl.assert_idle(reg)
            command('stop', reg['service'])
            modelctl.assert_device_ready(reg)
            command('start', SERVICE)
            ready_deadline = time.monotonic() + 180
            while True:
                try:
                    info = api('/object_info')
                    break
                except (OSError, ValueError):
                    if time.monotonic() >= ready_deadline:
                        raise TimeoutError('image runtime startup timed out')
                    time.sleep(1)
            missing = {node['class_type'] for node in workflow.values()} - set(info)
            if missing:
                raise RuntimeError('missing image nodes: ' + ', '.join(sorted(missing)))
            if api('/queue').get('queue_running') or api('/queue').get('queue_pending'):
                raise RuntimeError('image runtime is not idle')
            identifier = uuid.uuid4().hex
            workflow['8']['inputs']['filename_prefix'] = 'lario_' + request['model'] + '_' + identifier
            queued = api('/prompt', {'prompt': workflow, 'client_id': identifier})
            prompt_id = queued['prompt_id']
            job_started = time.monotonic()
            deadline = job_started + 1800
            while time.monotonic() < deadline:
                modelctl.assert_device_ready(reg)
                history = api('/history/' + prompt_id).get(prompt_id)
                if history is not None:
                    if history.get('status', {}).get('status_str') == 'error':
                        # Retain detailed local runtime diagnostics; return only the error class.
                        errors = [message[1].get('exception_type') for message in history.get('status', {}).get('messages', [])
                                  if message[0] == 'execution_error']
                        raise RuntimeError('image job failed: ' + ', '.join(str(error) for error in errors))
                    if history.get('status', {}).get('completed'):
                        images = history.get('outputs', {}).get('8', {}).get('images', [])
                        if not images:
                            raise RuntimeError('completed image job returned no PNG')
                        paths = [(ROOT / 'output' / image.get('subfolder', '') / image['filename']).resolve() for image in images]
                        if any(not path.is_relative_to(ROOT / 'output') or not path.is_file() for path in paths):
                            raise RuntimeError('invalid output path')
                        result.update(images=[str(path) for path in paths], generation_seconds=round(time.monotonic() - job_started, 3))
                        break
                time.sleep(2)
            else:
                # This is our owned worker, under the hardware lock; stop it in finally.
                raise TimeoutError('owned image job exceeded 30 minutes')
        finally:
            command('stop', SERVICE)
            modelctl.assert_device_ready(reg)
            if was_active:
                command('start', reg['service'])
                with contextlib.redirect_stdout(io.StringIO()):
                    modelctl.warm(reg, reg['aliases'][0])
            modelctl.admission_admin(reg, 'resume')
            result['chat_selection_preserved'] = modelctl.selection(reg) == selected
            result['total_seconds_with_restore'] = round(time.monotonic() - started, 3)
        return result


def main():
    def interrupted(_signal, _frame):
        raise InterruptedError('owned image request interrupted; restoring chat')
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    signal.signal(signal.SIGHUP, interrupted)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['options', 'generate', 'json'])
    parser.add_argument('--model', choices=['qwen-image', 'flux-klein'])
    parser.add_argument('--prompt')
    parser.add_argument('--width', type=int, default=1024)
    parser.add_argument('--height', type=int, default=1024)
    parser.add_argument('--seed', type=int, default=0)
    parser.add_argument('--steps', type=int)
    args = parser.parse_args()
    try:
        if args.operation == 'options':
            result = {'models': ['qwen-image', 'flux-klein'], 'owner': 'bigcachy', 'installed': installed(),
                      'runtime_installed': runtime_installed(),
                      'installed_models': {name: installed(name) for name in ('qwen-image', 'flux-klein')},
                      'default_steps': {'qwen-image': 25, 'flux-klein': 4}, 'maximum_dimensions': [1024, 1024],
                      'policy': 'One exclusive RTX job; active chat inference is refused; prior chat selection is restored.'}
        else:
            request = json.load(sys.stdin) if args.operation == 'json' else {
                key: getattr(args, key) for key in ['model', 'prompt', 'width', 'height', 'seed', 'steps']}
            result = generate(request)
        print(json.dumps(result), flush=True)
    except Exception as error:
        print(json.dumps({'error': {'type': type(error).__name__, 'message': str(error)[:500]}}), flush=True)
        raise SystemExit(1)


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""Borrow the configured idle GPU for an image job, then restore its chat selection."""
import argparse
import base64
import binascii
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
from shared.serving.control import request as owner_request
import workflows
from workflows import graph

ROOT = Path('/mnt/xfs/AI_Models/image-generation')
BASE = 'http://127.0.0.1:8188'
HARDWARE = os.getenv('LARIO_IMAGE_HARDWARE', 'rtx5080')
if HARDWARE not in ('rtx5080', 'gdp7900xt'):
    raise RuntimeError('unsupported image hardware')
RUNTIME = Path.home() / '.local/share/lario-model-runtimes/image-generation' / HARDWARE
OWNER = 'bigcachy' if HARDWARE == 'rtx5080' else 'cachyos-mini-mobile'
SERVICE = 'lario-images.service' if HARDWARE == 'rtx5080' else 'lario-radeon-images.service'


def owner_operation(reg, action, revision):
    return owner_request(reg, 'operations', {'action': action, 'expected_revision': revision,
                         'idempotency_key': uuid.uuid4().hex})['state']


def unknown_chat(state):
    # A previous interrupted request leaves an advisory uncertainty flag until
    # the next inference. Successful cold/ready inspection plus native slot
    # checks can reconcile that flag without loading a chat model first.
    return state.get('detail') is not None or (state['uncertain'] and
            state.get('state') not in ('cold', 'ready', 'paused'))


def claim_chat(reg):
    """Pause admission with CAS, then check work admitted before the pause."""
    state = owner_request(reg, 'state')
    if not state['enabled'] or state['draining']:
        raise RuntimeError('GPU AI serving is Off or paused; use the operator controls before generating')
    if state['busy'] or state['requests'] or state['loading_profile'] or unknown_chat(state):
        raise RuntimeError('active or unknown GPU inference; refusing image generation')
    paused = owner_operation(reg, 'pause', state['revision'])
    lease = {'revision': paused['revision'], 'profile_id': paused['profile_id']}
    try:
        if paused['busy'] or paused['requests'] or paused['loading_profile'] or unknown_chat(paused):
            raise RuntimeError('RTX inference arrived before pause; hardware left running')
        modelctl.assert_idle(reg)
    except BaseException:
        # Never undo a newer operator policy change.
        release_admission(reg, lease)
        raise
    return lease


def release_admission(reg, lease):
    state = owner_request(reg, 'state')
    if state['enabled'] and state['revision'] == lease['revision']:
        owner_operation(reg, 'resume', lease['revision'])
        return True
    return False


def restore_chat(reg, lease, was_active):
    state = owner_request(reg, 'state')
    if not state['enabled']:
        return {'profile_id': lease['profile_id'], 'restored': False,
                'admission_resumed': False, 'reason': 'Operator state changed; no automatic restore.'}
    if was_active:
        command('start', reg['service'])
    if state['revision'] != lease['revision']:
        # Serving is still On. Bring its proxy back cold so subsequent operator
        # Resume works, but never load an old profile or undo the newer policy.
        return {'profile_id': lease['profile_id'], 'restored': False,
                'admission_resumed': False, 'reason': 'Operator state changed; enabled serving returned cold, policy preserved.'}
    if was_active:
        if lease['profile_id']:
            # The hardware lock is still held. Address the captured immutable ID,
            # never the legacy selection file or alias. A cold backend stays cold.
            for attempt in range(30):
                try:
                    modelctl.api(reg, '/health')
                    break
                except OSError:
                    if attempt == 29:
                        raise RuntimeError('chat backend did not return healthy; admission remains paused')
                    time.sleep(1)
            response = modelctl.api(reg, '/v1/chat/completions', {
                'model': lease['profile_id'], 'messages': [{'role': 'user', 'content': '.'}],
                'max_tokens': 1, 'chat_template_kwargs': {'enable_thinking': False}}, timeout=1800)
            if not response.get('choices') or modelctl.current(reg) != lease['profile_id']:
                raise RuntimeError('fixed profile restoration failed; admission remains paused')
    resumed = release_admission(reg, lease)
    return {'profile_id': lease['profile_id'], 'restored': True, 'admission_resumed': resumed}


def api(path, payload=None):
    req = urllib.request.Request(BASE + path, data=None if payload is None else json.dumps(payload).encode(),
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=15) as response:
        return json.load(response)


def runtime_installed():
    unit = Path.home() / '.config/systemd/user' / SERVICE
    return ((RUNTIME / 'venv/bin/python').is_file()
            and (RUNTIME / 'ComfyUI/main.py').is_file()
            and (RUNTIME / 'ComfyUI/custom_nodes/ComfyUI-GGUF/__init__.py').is_file()
            and (HERE / ('requirements.lock' if HARDWARE == 'rtx5080' else 'requirements.rocm.lock')).is_file()
            and unit.is_file() and unit.read_text() == (HERE / SERVICE).read_text())


def files_present(items):
    return all((ROOT / 'models' / item['target']).is_file()
               and (ROOT / 'models' / item['target']).stat().st_size == item['size'] for item in items)


def installed(model=None):
    manifest = json.loads((HERE / 'install-manifest.json').read_text())
    selected = {'qwen-image': {'qwen-image-2.1-UC-Q4_K_M.gguf', 'qwen3vl_8b_int8_convrot.safetensors', 'qwen_image_2.1_vae_bf16.safetensors'},
                'flux-klein': {'flux-2-klein-4b.safetensors', 'qwen_3_4b.safetensors', 'flux2-vae.safetensors'}}
    return runtime_installed() and files_present([item for item in manifest['files']
               if model is None or Path(item['target']).name in selected[model]])


def installed_upscale():
    manifest = json.loads((HERE / 'install-manifest.json').read_text())
    return runtime_installed() and files_present(manifest.get('upscale_files', []))


def command(action, service):
    subprocess.run(['systemctl', '--user', action, service], check=True, stdout=subprocess.DEVNULL)


def exclusive(workflow, result, saves):
    """Borrow the idle RTX, run one bounded ComfyUI workflow, then restore its chat selection."""
    reg = json.loads((REPO / HARDWARE / 'models.json').read_text())
    modelctl.load_runtime(reg)
    saved = {}
    with (REPO / ('.'+HARDWARE+'.lock')).open('w') as lock:
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
        # Inputs and installation are validated before borrowing. RAM is checked
        # after unloading chat, since Strata can hold most of the host memory.
        fixed = os.getenv('LARIO_FIXED_PROFILES') == '1'
        selected = None if fixed else modelctl.selection(reg)
        if selected:
            result['chat_selection'] = {'model': selected[0], 'preset': selected[1]}
        was_active = subprocess.run(['systemctl', '--user', 'is-active', reg['service']], capture_output=True).returncode == 0
        started = time.monotonic()
        lease = claim_chat(reg) if fixed else None
        if not fixed:
            modelctl.admission_admin(reg, 'drain')
        try:
            modelctl.assert_idle(reg)
            command('stop', reg['service'])
            modelctl.assert_device_ready(reg)
            available = next(int(line.split()[1]) for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith('MemAvailable:'))
            required_gib = 40 if HARDWARE == 'rtx5080' else 10
            if available < required_gib * 1024 ** 2:
                raise RuntimeError(f'need at least {required_gib} GiB available host RAM for image runtime')
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
            for node, prefix in saves.items():
                workflow[node]['inputs']['filename_prefix'] = prefix + '_' + identifier
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
                        for node in saves:
                            images = history.get('outputs', {}).get(node, {}).get('images', [])
                            if not images:
                                raise RuntimeError('completed image job returned no PNG')
                            paths = [(ROOT / 'output' / image.get('subfolder', '') / image['filename']).resolve() for image in images]
                            if any(not path.is_relative_to(ROOT / 'output') or not path.is_file() for path in paths):
                                raise RuntimeError('invalid output path')
                            saved[node] = [str(path) for path in paths]
                        result.update(images=[path for node in saves for path in saved[node]],
                                      generation_seconds=round(time.monotonic() - job_started, 3))
                        break
                time.sleep(2)
            else:
                # This is our owned worker, under the hardware lock; stop it in finally.
                raise TimeoutError('owned image job exceeded 30 minutes')
        finally:
            command('stop', SERVICE)
            modelctl.assert_device_ready(reg)
            if fixed:
                result['chat_restore'] = restore_chat(reg, lease, was_active)
            elif was_active:
                command('start', reg['service'])
                with contextlib.redirect_stdout(io.StringIO()):
                    modelctl.warm(reg, reg['aliases'][0])
            if not fixed:
                modelctl.admission_admin(reg, 'resume')
                result['chat_selection_preserved'] = modelctl.selection(reg) == selected
            result['total_seconds_with_restore'] = round(time.monotonic() - started, 3)
    return result, saved


def generate(request):
    allowed = {'model', 'prompt', 'width', 'height', 'seed', 'steps'}
    if set(request) - allowed:
        raise ValueError('unknown image arguments')
    workflow = graph(**request)
    if HARDWARE == 'gdp7900xt':
        workflow['2']['inputs']['device'] = 'default'
        if request['model'] == 'qwen-image':
            workflow['9']['inputs']['device'] = 'gpu'
    if socket.gethostname().split('.')[0] != OWNER:
        raise RuntimeError('image generation must run on bigcachy')
    if not installed(request['model']):
        raise RuntimeError('image bundles are not fully installed')
    result = {'model': request['model'], 'owner': OWNER, 'hardware': HARDWARE, 'scope': 'Exclusive GPU job; preserves fixed profile and operator policy.'}
    result, _ = exclusive(workflow, result, {'8': 'lario_' + request['model']})
    return result


def describe(request):
    """Borrow an idle fixed-profile owner for vision, then restore residency."""
    from shared.serving.catalog import profiles
    if socket.gethostname().split('.')[0] != OWNER:
        raise RuntimeError('vision must run on its registered owner')
    if set(request) - {'mode', 'messages', 'max_tokens'}:
        raise ValueError('unknown vision arguments')
    mode = request.get('mode', 'describe')
    maximum = request.get('max_tokens', 768)
    if mode not in ('describe', 'ocr') or type(maximum) is not int or not 1 <= maximum <= 4096:
        raise ValueError('invalid vision mode or token limit')
    messages = request.get('messages')
    if not isinstance(messages, list) or len(messages) != 1 or messages[0].get('role') != 'user':
        raise ValueError('one user vision message required')
    content = messages[0].get('content')
    if not isinstance(content, list):
        raise ValueError('vision content must be a list')
    images = [part for part in content if part.get('type') == 'image_url']
    if not 1 <= len(images) <= 4 or len(json.dumps(content)) > 29 * 1024 ** 2:
        raise ValueError('vision input exceeds image limits')
    for part in images:
        url = part.get('image_url', {}).get('url', '')
        if not isinstance(url, str) or not url.startswith(('data:image/png;base64,', 'data:image/jpeg;base64,', 'data:image/webp;base64,')):
            raise ValueError('only inline PNG/JPEG/WebP vision inputs are accepted')
    reg = json.loads((REPO / HARDWARE / 'models.json').read_text())
    modelctl.load_runtime(reg)
    if os.getenv('LARIO_FIXED_PROFILES') != '1':
        raise RuntimeError('vision borrowing requires fixed-profile serving')
    profile = next(p for p in profiles(reg).values() if p['model'] == mode)
    with (REPO / ('.'+HARDWARE+'.lock')).open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        modelctl.assert_not_held(reg)
        modelctl.assert_device_ready(reg)
        lease = claim_chat(reg)
        try:
            response = modelctl.api(reg, '/v1/chat/completions', {
                'model': profile['id'], 'messages': messages, 'max_tokens': maximum,
                'chat_template_kwargs': {'enable_thinking': False}}, timeout=300)
            choices = response.get('choices', [])
            text = choices[0].get('message', {}).get('content') if choices else None
            if not isinstance(text, str) or not text.strip():
                raise RuntimeError('vision returned no completed description')
            result = {'owner': OWNER, 'hardware': HARDWARE, 'model': profile['id'],
                      'mode': mode, 'image_count': len(images), 'description': text,
                      'finish_reason': choices[0].get('finish_reason'), 'usage': response.get('usage', {})}
        finally:
            if lease['profile_id'] is None:
                # Restart the private proxy to unload our temporary vision model.
                command('stop', reg['service'])
            restored = restore_chat(reg, lease, True)
        result['chat_restore'] = restored
        return result


def image_dims(data):
    if data.startswith(b'\x89PNG\r\n\x1a\n') and len(data) >= 24:
        return int.from_bytes(data[16:20], 'big'), int.from_bytes(data[20:24], 'big'), 'png'
    if data.startswith(b'\xff\xd8'):
        offset = 2
        while offset + 9 < len(data):
            if data[offset] != 0xFF:
                offset += 1
                continue
            marker = data[offset + 1]
            if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                return int.from_bytes(data[offset + 7:offset + 9], 'big'), int.from_bytes(data[offset + 5:offset + 7], 'big'), 'jpg'
            if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD9:
                offset += 2
                continue
            offset += 2 + int.from_bytes(data[offset + 2:offset + 4], 'big')
        raise ValueError('unreadable JPEG dimensions')
    raise ValueError('upscale input must be PNG or JPEG; convert other formats first')


def upscale(request):
    allowed = {'image', 'alpha', 'scale', 'method', 'sharpen'}
    if set(request) - allowed:
        raise ValueError('unknown upscale arguments')
    if socket.gethostname().split('.')[0] != OWNER:
        raise RuntimeError('image upscaling must run on bigcachy')
    method = request.get('method', 'ai')
    scale = request.get('scale', 4)
    sharpen = request.get('sharpen', 0)
    if method not in ('ai', 'classic'):
        raise ValueError('choose ai or classic upscaling')
    if type(scale) is not int or not 2 <= scale <= 8:
        raise ValueError('scale must be an integer from 2 to 8')
    if isinstance(sharpen, bool) or not isinstance(sharpen, (int, float)) or not 0 <= sharpen <= 1:
        raise ValueError('sharpen must be a number from 0 to 1')
    def decode(key):
        value = request.get(key)
        if value in (None, ''):
            return None
        try:
            data = base64.b64decode(value, validate=True)
        except (binascii.Error, ValueError):
            raise ValueError(key + ' is not valid base64') from None
        if len(data) > 20 * 1024 * 1024:
            raise ValueError(key + ' exceeds the 20 MiB input limit')
        return data or None
    data = decode('image')
    if not data:
        raise ValueError('image (base64) is required')
    alpha = decode('alpha')
    width, height, kind = image_dims(data)
    if alpha is not None:
        alpha_width, alpha_height, _ = image_dims(alpha)
        if (alpha_width, alpha_height) != (width, height):
            raise ValueError('alpha channel dimensions must match the image')
    if method == 'ai' and not installed_upscale():
        raise RuntimeError('the RealESRGAN upscale model is not installed; run install.py --weights')
    input_name = 'lario_upscale_in.' + kind
    alpha_name = 'lario_upscale_alpha_in.png' if alpha else None
    workflow, save_nodes = workflows.upscale_graph(input_name, width, height, scale, method, alpha_name)
    saves = {save_nodes[0]: 'lario_upscale'}
    if len(save_nodes) > 1:
        saves[save_nodes[1]] = 'lario_upscale_alpha'
    inputs = {0: (ROOT / 'input' / input_name, data)}
    if alpha:
        inputs[1] = (ROOT / 'input' / 'lario_upscale_alpha_in.png', alpha)
    result = {'method': method, 'scale': scale, 'owner': OWNER, 'hardware': HARDWARE,
              'model': workflows.UPSCALE_MODEL if method == 'ai' else 'lanczos',
              'source_dimensions': [width, height], 'target_dimensions': [width * scale, height * scale],
              'alpha': bool(alpha), 'scope': 'Exclusive RTX job; preserves fixed profile and operator policy.'}
    try:
        for path, payload in inputs.values():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
        result, saved = exclusive(workflow, result, saves)
    finally:
        for path, _ in inputs.values():
            path.unlink(missing_ok=True)
    # Compose the AI-upscaled RGB with the antialiased alpha and optionally sharpen on the RGB channels only.
    if alpha or sharpen:
        rgb_path = Path(saved[save_nodes[0]][0])
        final = rgb_path.parent / (rgb_path.name.rsplit('_', 2)[0] + '_final.png')
        command_line = ['magick', str(rgb_path)]
        if alpha:
            # ComfyUI's float pipeline leaves the resampled alpha a hair under full opacity
            # everywhere, which composites as a milky translucent image with white haze at
            # bright edges. Re-level the near-opaque and near-transparent bands before copying.
            command_line += ['(', saved[save_nodes[1]][0], '-level', '2%,98%', ')',
                             '-alpha', 'off', '-compose', 'CopyOpacity', '-composite']
        if sharpen:
            command_line += ['-channel', 'RGB', '-unsharp', '0x1+{:.2f}+0.01'.format(2.0 * sharpen), '+channel']
        command_line.append(str(final))
        subprocess.run(command_line, check=True, capture_output=True, timeout=300)
        for node in saves:
            for path in saved[node]:
                Path(path).unlink(missing_ok=True)
        if not final.is_file():
            raise RuntimeError('upscale post-processing produced no PNG')
        result.update(images=[str(final)])
    return result


def main():
    def interrupted(_signal, _frame):
        raise InterruptedError('owned image request interrupted; restoring chat')
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    signal.signal(signal.SIGHUP, interrupted)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['options', 'generate', 'json', 'upscale', 'describe'])
    parser.add_argument('--model', choices=['qwen-image', 'flux-klein'])
    parser.add_argument('--prompt')
    parser.add_argument('--width', type=int, default=1024)
    parser.add_argument('--height', type=int, default=1024)
    parser.add_argument('--seed', type=int, default=0)
    parser.add_argument('--steps', type=int)
    args = parser.parse_args()
    try:
        modelctl.load_runtime(json.loads((REPO / HARDWARE / 'models.json').read_text()))
        if args.operation == 'options':
            result = {'models': ['qwen-image', 'flux-klein'], 'owner': OWNER, 'installed': installed(),
                      'runtime_installed': runtime_installed(),
                      'installed_models': {name: installed(name) for name in ('qwen-image', 'flux-klein')},
                      'default_steps': {'qwen-image': 25, 'flux-klein': 4}, 'maximum_dimensions': [1024, 1024],
                      'upscale': {'model': workflows.UPSCALE_MODEL, 'installed': installed_upscale(),
                                  'scales': {'ai': [2, 3, 4], 'classic': '2–8'}, 'sharpen': '0–1 optional unsharp'},
                      'serving_mode': 'fixed-profiles' if os.getenv('LARIO_FIXED_PROFILES') == '1' else 'legacy',
                      'policy': 'One exclusive RTX job; active/unknown chat, Off and paused serving are refused. The actual fixed profile is restored only if operator policy is unchanged; a cold backend stays cold.'}
        elif args.operation == 'describe':
            result = describe(json.load(sys.stdin))
        elif args.operation == 'upscale':
            result = upscale(json.load(sys.stdin))
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

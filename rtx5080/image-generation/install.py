#!/usr/bin/env python3
"""Install pinned ComfyUI and the requested Qwen/FLUX bundles on XFS."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import urllib.request

HERE = Path(__file__).resolve().parent
MANIFEST = json.loads((HERE / 'install-manifest.json').read_text())
ROOT = Path(MANIFEST['root'])


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as file:
        while data := file.read(8 * 1024 * 1024):
            h.update(data)
    return h.hexdigest()


def download(item):
    path = ROOT / 'models' / item['target']
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.stat().st_size == item['size'] and digest(path) == item['sha256']:
        print('Verified existing', item['target'], flush=True)
        return
    partial = path.with_suffix(path.suffix + '.part')
    url = 'https://huggingface.co/' + item['repository'] + '/resolve/' + item['revision'] + '/' + item['filename']
    for attempt in range(5):
        try:
            offset = partial.stat().st_size if partial.exists() else 0
            headers = {'Range': f'bytes={offset}-'} if offset else {}
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=120) as response:
                append = offset and response.status == 206
                with partial.open('ab' if append else 'wb') as file:
                    while block := response.read(8 * 1024 * 1024):
                        file.write(block)
            if partial.stat().st_size != item['size'] or digest(partial) != item['sha256']:
                partial.unlink()
                raise ValueError('size/checksum mismatch')
            partial.replace(path)
            print('Downloaded and SHA256 verified', item['target'], flush=True)
            return
        except Exception as error:
            print(item['target'], 'attempt', attempt + 1, type(error).__name__, flush=True)
            if attempt == 4:
                raise
            time.sleep(2)


def checkout(spec, destination):
    if not destination.exists():
        subprocess.run(['git', 'clone', '--filter=blob:none', '--no-checkout', spec['url'], str(destination)], check=True)
    subprocess.run(['git', '-C', str(destination), 'fetch', '--depth', '1', 'origin', spec['revision']], check=True)
    subprocess.run(['git', '-C', str(destination), 'checkout', '--detach', spec['revision']], check=True)


def runtime():
    comfy = ROOT / 'runtime/ComfyUI'
    checkout(MANIFEST['runtime']['comfy'], comfy)
    checkout(MANIFEST['runtime']['gguf'], comfy / 'custom_nodes/ComfyUI-GGUF')
    venv = ROOT / 'runtime/venv'
    if not (venv / 'bin/python').exists():
        subprocess.run(['uv', 'venv', '--python', '3.12', str(venv)], check=True)
    python = str(venv / 'bin/python')
    lock = HERE / 'requirements.lock'
    if lock.exists():
        subprocess.run(['uv', 'pip', 'sync', '--python', python, '--extra-index-url', MANIFEST['torch_index'], str(lock)], check=True)
    else:
        subprocess.run(['uv', 'pip', 'install', '--python', python, '--index-url', MANIFEST['torch_index'],
                        'torch', 'torchvision', 'torchaudio'], check=True)
        subprocess.run(['uv', 'pip', 'install', '--python', python, '-r', str(comfy / 'requirements.txt'),
                        '-r', str(comfy / 'custom_nodes/ComfyUI-GGUF/requirements.txt')], check=True)
        frozen = subprocess.run(['uv', 'pip', 'freeze', '--python', python], capture_output=True, text=True, check=True)
        lock.write_text(frozen.stdout)
    (comfy / 'extra_model_paths.yaml').write_text('lario_xfs:\n  base_path: ' + str(ROOT / 'models') +
        '\n  diffusion_models: diffusion_models\n  text_encoders: text_encoders\n  vae: vae\n')
    unit = Path.home() / '.config/systemd/user/lario-images.service'
    unit.parent.mkdir(parents=True, exist_ok=True)
    content = (HERE / 'lario-images.service').read_text()
    if not unit.exists() or unit.read_text() != content:
        unit.write_text(content)
        subprocess.run(['systemctl', '--user', 'daemon-reload'], check=True)
    print('Pinned image runtime installed', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', action='store_true')
    parser.add_argument('--weights', action='store_true')
    args = parser.parse_args()
    if not args.runtime and not args.weights:
        parser.error('choose --runtime and/or --weights')
    ROOT.mkdir(parents=True, exist_ok=True)
    filesystem = subprocess.run(['findmnt', '-T', str(ROOT), '-n', '-o', 'FSTYPE'], capture_output=True, text=True, check=True).stdout.strip()
    if filesystem != 'xfs':
        raise SystemExit('Image runtime/weights must be on XFS')
    for key, suffix in {'UV_CACHE_DIR': 'cache/uv', 'UV_PYTHON_INSTALL_DIR': 'runtime/python',
                        'HF_HOME': 'cache/huggingface', 'TORCH_HOME': 'cache/torch', 'XDG_CACHE_HOME': 'cache'}.items():
        os.environ[key] = str(ROOT / suffix)
    for directory in ['runtime', 'input', 'output', 'tmp', 'logs']:
        (ROOT / directory).mkdir(parents=True, exist_ok=True)
    if args.weights:
        if shutil.disk_usage(ROOT).free < sum(item['size'] for item in MANIFEST['files']) + 10 * 1024 ** 3:
            raise SystemExit('Insufficient XFS headroom')
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(download, MANIFEST['files']))
    if args.runtime:
        runtime()


if __name__ == '__main__':
    main()

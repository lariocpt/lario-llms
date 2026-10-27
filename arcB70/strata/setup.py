#!/usr/bin/env python3
"""Prepare the pinned Strata engine and native Q4 pack; never start a model."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

REPO = Path(__file__).resolve().parents[2]
APP = Path.home()/'.local/share/strata'
COMPONENTS = APP/'components'
VERSION = '0.1.50'
ENGINE = COMPONENTS/'engine'/f'{VERSION}-linux-x86_64-sycl'
SOURCE_COMMIT = '4b9e05a2a806a3fe24f7b2560d98626c37dade35'
SOURCE = APP/'source'/SOURCE_COMMIT
MANIFEST_SHA = 'da7cc2a54df681fce0ad2bc85c4bd708d2de5a3856e1089bc1d63763392c39f9'
ARCHIVE_SHA = '4e152bda9da9e11208a1da95148f4d561134f71c9498da2b016e4e3bf212e242'
MODEL = Path('/mnt/xfs/AI_Models/gguf/qwen38-flash/UD-Q4_K_XL')
PACK = Path('/mnt/xfs/AI_Models/strata/packs/qwen38-flash-ud-q4-k-xl')
GGUF_PY = Path('/mnt/xfs/AI_Models/runtimes/llama.cpp/arc-sycl-2026-10-22/sycl/src/gguf-py')
VENV = APP/'venv'


def run(args, **kwargs):
    print('+ '+ ' '.join(map(str, args)), flush=True)
    return subprocess.run(list(map(str, args)), check=True, **kwargs)


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(16*1024*1024), b''):
            digest.update(block)
    return digest.hexdigest()


def source():
    if not SOURCE.exists():
        cached = Path.home()/'.cache/b70-strata-research-4b9e05a'
        SOURCE.parent.mkdir(parents=True, exist_ok=True)
        if cached.exists():
            actual = subprocess.check_output(['git', '-C', str(cached), 'rev-parse', 'HEAD'], text=True).strip()
            if actual != SOURCE_COMMIT:
                raise RuntimeError('cached upstream source revision mismatch')
            shutil.move(str(cached), str(SOURCE))
        else:
            SOURCE.mkdir()
            run(['git', '-C', SOURCE, 'init'])
            run(['git', '-C', SOURCE, 'fetch', '--depth', '1', 'https://github.com/Niko1221/Strata.git', SOURCE_COMMIT])
            run(['git', '-C', SOURCE, 'checkout', '--detach', 'FETCH_HEAD'])
    actual = subprocess.check_output(['git', '-C', str(SOURCE), 'rev-parse', 'HEAD'], text=True).strip()
    if actual != SOURCE_COMMIT:
        raise RuntimeError('upstream source revision mismatch')


def engine():
    previous = Path('/mnt/xfs/AI_Models/runtimes/strata/components')
    if previous.exists():
        if COMPONENTS.exists():
            raise RuntimeError('both component locations exist; refusing overwrite')
        COMPONENTS.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(previous), str(COMPONENTS))
    if not ENGINE.exists():
        command = [sys.executable, str(SOURCE/'strata.py'), 'update', '--backend', 'sycl',
                   '--no-control', '--components-dir', str(COMPONENTS), '--output', 'json']
        result = subprocess.check_output(command+['--check'], text=True)
        offered = json.loads(result)['engine']['offered']
        if offered['version'] != VERSION or offered['sha256'] != ARCHIVE_SHA:
            raise RuntimeError('feed offers a different engine; review the pin before installing')
        run(command)
    manifest = ENGINE/'engine-component.json'
    if sha(manifest) != MANIFEST_SHA:
        raise RuntimeError('signed component manifest checksum mismatch')
    data = json.loads(manifest.read_text())
    for item in data['files']:
        path = ENGINE/item['path']
        if not path.resolve().is_relative_to(ENGINE.resolve()):
            raise RuntimeError('invalid component path')
        if path.stat().st_size != item['bytes'] or sha(path) != item['sha256']:
            raise RuntimeError('component file verification failed: '+str(path))
    version = subprocess.check_output([str(ENGINE/'strata'), '--version'], text=True).strip()
    deps = subprocess.check_output(['ldd', str(ENGINE/'strata')], text=True)
    if 'not found' in deps:
        raise RuntimeError('engine dependencies unresolved')
    return {'engine_version': version, 'engine_directory': str(ENGINE),
            'manifest_sha256': MANIFEST_SHA, 'archive_sha256': ARCHIVE_SHA,
            'verified_files': len(data['files']), 'dependencies_resolved': True}


def prepare():
    if not (VENV/'bin/python').exists():
        run([sys.executable, '-m', 'venv', '--system-site-packages', VENV])
    python = VENV/'bin/python'
    probe = subprocess.run([str(python), '-c', 'import numpy, regex, jinja2, yaml, requests, psutil, PIL'])
    if probe.returncode:
        run([python, '-m', 'pip', 'install', 'numpy', 'regex', 'jinja2', 'PyYAML', 'requests', 'psutil', 'Pillow'])
    pins = json.loads((REPO/'arcB70/flash_weights.json').read_text())
    receipt = json.loads((REPO/'research/benchmarks/20261026-b70-flash/weights-verified.json').read_text())
    if receipt['revision'] != pins['revision'] or len(receipt['shards']) != len(pins['shards']):
        raise RuntimeError('missing matching full-weight verification receipt')
    for shard, verified in zip(pins['shards'], receipt['shards']):
        path = MODEL/shard['filename']
        if path.stat().st_size != shard['bytes'] or verified['sha256'] != shard['sha256']:
            raise RuntimeError('weight manifest/receipt mismatch')
    if not GGUF_PY.exists():
        raise RuntimeError('pinned gguf-py source unavailable')
    env = dict(os.environ, STRATA_GGUF_PY=str(GGUF_PY))
    PACK.parent.mkdir(parents=True, exist_ok=True)
    if not (PACK/'native_experts.txt').exists():
        run([python, SOURCE/'tools/iq_pack.py', '--gguf', MODEL/pins['shards'][0]['filename'],
             '--out', PACK, '--compat-bf16'], cwd=SOURCE, env=env)
    for name in ('index.txt', 'dense.bin', 'native_experts.txt', 'conversions.json',
                 'compat-bf16.json', 'tokenizer/vocab.json', 'tokenizer/chat_template.jinja'):
        if not (PACK/name).is_file() or (PACK/name).stat().st_size == 0:
            raise RuntimeError('incomplete prepared pack: '+name)
    if (PACK/'experts.bin').exists():
        raise RuntimeError('unexpected duplicate experts.bin')
    return {'pack_directory': str(PACK), 'compat_bf16': True,
            'dense_bytes': (PACK/'dense.bin').stat().st_size, 'experts_duplicated': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare', action='store_true')
    args = parser.parse_args()
    source()
    report = {'status': 'engine-verified-model-not-loaded', 'source_commit': SOURCE_COMMIT,
              'source_directory': str(SOURCE), 'model_loaded': False, **engine()}
    if args.prepare:
        report.update(prepare(), status='pack-prepared-model-not-loaded')
    target = REPO/'arcB70/strata/acquisition-report.json'
    target.write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2), flush=True)

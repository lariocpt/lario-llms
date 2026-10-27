#!/usr/bin/env python3
"""Token-free pinned Q4 download/verification; reuses completed shards."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from arcB70.flash_next import MANIFEST, MODEL_DIR
from shared.modelctl import atomic

REPORT = ROOT/'research/benchmarks/20261026-b70-flash/weights-verified.json'


def verify(path, shard):
    if not path.exists() or path.stat().st_size != shard['bytes']:
        return False
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(16*1024*1024), b''):
            digest.update(block)
    return digest.hexdigest() == shard['sha256']


def download(verify_only=False):
    dest = Path(MODEL_DIR)
    dest.mkdir(parents=True, exist_ok=True)
    needed = sum(s['bytes'] for s in MANIFEST['shards'] if not (dest/s['filename']).exists())
    if not verify_only and shutil.disk_usage(dest).free < needed + 4*2**30:
        raise RuntimeError('insufficient free model-store space')
    rows = []
    for shard in MANIFEST['shards']:
        path = dest/shard['filename']
        if not verify(path, shard):
            if path.exists():
                raise RuntimeError('existing shard failed verification: '+str(path))
            if verify_only:
                raise RuntimeError('missing shard: '+str(path))
            from huggingface_hub import hf_hub_download
            print('Downloading '+path.name, flush=True)
            hf_hub_download(repo_id=MANIFEST['repository'], revision=MANIFEST['revision'],
                            filename='UD-Q4_K_XL/'+path.name, local_dir=dest.parent)
            if not verify(path, shard):
                raise RuntimeError('download failed verification: '+str(path))
        print('Verified '+path.name, flush=True)
        rows.append({'path': str(path), 'bytes': shard['bytes'], 'sha256': shard['sha256']})
    atomic(REPORT, json.dumps({'revision': MANIFEST['revision'], 'shards': rows,
                              'verified_at': time.time()}, indent=2)+'\n')
    print('ALL FOUR Q4 SHARDS VERIFIED; live B70 validation remains pending', flush=True)


def process_start(pid):
    try:
        fields = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
        return None if fields[0] == 'Z' else fields[19]
    except FileNotFoundError:
        return None


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--wait-pid', type=int)
    parser.add_argument('--verify-only', action='store_true')
    args = parser.parse_args()
    if args.wait_pid:
        original = process_start(args.wait_pid)
        print('Waiting for existing Q4 transfer; no AI session is used', flush=True)
        while original is not None and process_start(args.wait_pid) == original:
            time.sleep(30)
    download(args.verify_only)

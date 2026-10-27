#!/usr/bin/env python3
"""Prepare the existing Q3 pack using the private official Terminal; never load it."""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess

APP = Path.home()/'strata'
SOURCE = APP/'terminal/0.1.51'
PYTHON = SOURCE/'python/bin/python3.12'
ENGINE = APP/'components/engine/0.1.50-linux-x86_64-hip-halo'
MODEL = Path('/mnt/AI_Models/gguf/qwen38-flash')
PACK = Path('/mnt/AI_Models/strata/packs/qwen38-flash-ud-q3-k-xl')
SHARDS = [MODEL/f'Qwen3.8-Flash-Next-UD-Q3_K_XL-{i:05}-of-00003.gguf' for i in range(1,4)]
SIZES = [10946624, 49983253824, 39992153376]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare', action='store_true')
    args = parser.parse_args()
    if socket.gethostname().split('.')[0] != 'l-dev-ai':
        raise RuntimeError('run on l-dev-ai only')
    if subprocess.check_output(['findmnt','-n','-o','FSTYPE','-T',str(APP)],text=True).strip() == 'xfs':
        raise RuntimeError('application is on XFS')
    manifest = json.loads((ENGINE/'engine-component.json').read_text())
    if manifest['backend'] != 'hip' or manifest['archs'] != ['gfx1151']:
        raise RuntimeError('incorrect engine architecture')
    for path, expected in zip(SHARDS, SIZES):
        if path.stat().st_size != expected:
            raise RuntimeError('Q3 shard size mismatch: '+str(path))
    required = ['index.txt','dense.bin','native_experts.txt','tokenizer/vocab.json','tokenizer/chat_template.jinja']
    if args.prepare and not all((PACK/name).is_file() and (PACK/name).stat().st_size for name in required):
        PACK.parent.mkdir(parents=True, exist_ok=True)
        env = dict(os.environ)
        env['PYTHONPATH'] = str(Path.home()/'llama.cpp/gguf-py')
        env['STRATA_GGUF_PY'] = str(Path.home()/'llama.cpp/gguf-py')
        subprocess.run([str(PYTHON), str(SOURCE/'tools/iq_pack.py'), '--gguf',str(SHARDS[0]),
                        '--out',str(PACK),'--compat-bf16'],env=env,cwd=SOURCE,check=True)
    ready = all((PACK/name).is_file() and (PACK/name).stat().st_size for name in required)
    if args.prepare and not ready:
        raise RuntimeError('pack preparation incomplete')
    if (PACK/'experts.bin').exists():
        raise RuntimeError('unexpected duplicate experts.bin')
    report = {'status':'pack-prepared' if ready else 'engine-installed', 'app_directory':str(APP),
              'engine':str(ENGINE),'engine_version':manifest['version'],
              'source_revision':(SOURCE/'COMMIT').read_text().strip(),
              'weights_bytes':sum(SIZES),'pack':str(PACK),'required_files_complete':bool(ready),
              'shards':[{'path':str(p),'bytes':n} for p,n in zip(SHARDS,SIZES)]}
    target=Path(__file__).with_name('preparation.json');target.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__ == '__main__':
    main()

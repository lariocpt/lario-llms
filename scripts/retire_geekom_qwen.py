#!/usr/bin/env python3
"""Audit/delete only Geekom's retired Q4/Q8, old Flash shards and derived pack."""
import argparse
import json
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from shared import modelctl
from shared.serving.control import operate
from shared.serving.catalog import profiles


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--apply', action='store_true')
    p.add_argument('--report', type=Path, required=True)
    a = p.parse_args()
    if socket.gethostname().split('.')[0] != 'l-dev-ai':
        p.error('run on l-dev-ai only')
    base = Path('/mnt/AI_Models')
    if subprocess.check_output(['findmnt','-n','-o','FSTYPE','-T',str(base)],text=True).strip() != 'xfs':
        raise RuntimeError('model XFS mount missing')
    reg = json.loads((ROOT/'geekom/models.json').read_text())
    if set(reg['models']) != {'qwen38-flash-halogen','qwen38-flash-halogen-128k'}:
        raise RuntimeError('old Geekom models still registered')
    live = operate('geekom','catalog')
    rows = live.get('profiles', []) if isinstance(live, dict) else live
    if {row['id'] for row in rows} != set(profiles(reg)):
        raise RuntimeError('live owner catalog has not retired the old models')
    protected = set()
    for path in ROOT.glob('*/models.json'):
        registry = json.loads(path.read_text())
        if registry.get('host') != 'l-dev-ai':
            continue
        for model in registry['models'].values():
            args = model['args']
            for flag in ('-m','--model','--mmproj','-md','--model-draft'):
                if flag not in args:
                    continue
                file = Path(args[args.index(flag)+1].replace('/models/',str(base)+'/'))
                if not file.is_file():
                    raise RuntimeError('retained model missing: '+str(file))
                protected.update((file.absolute(),file.resolve()))
                if file.suffix == '.hgn':
                    protected.add(file.parent.resolve())
    candidates = [base/'gguf/qwen38-flash',
                  base/'huggingface/hub/models--unsloth--Qwen3.8-27B-GGUF',
                  base/'strata/packs/qwen38-flash-ud-q3-k-xl']
    remove = []
    for path in candidates:
        if not path.exists():
            continue
        if path.is_symlink() or not path.is_dir() or not path.resolve().is_relative_to(base):
            raise RuntimeError('unexpected deletion root')
        resolved = path.resolve()
        if any(f == resolved or f.is_relative_to(resolved) or resolved.is_relative_to(f) for f in protected):
            raise RuntimeError('retained model overlap: '+str(path))
        files = [f for f in path.rglob('*') if f.is_file() and not f.is_symlink()]
        if any(f.stat().st_size > 100_000_000 and time.time()-f.stat().st_mtime < 1800 for f in files):
            raise RuntimeError('recent model writes; refusing deletion')
        remove.append({'path':str(path),'bytes':sum(f.stat().st_size for f in files),
                       'allocated_bytes':sum(f.stat().st_blocks*512 for f in files)})
    for proc in Path('/proc').glob('[0-9]*'):
        try:
            cmd = (proc/'cmdline').read_bytes().replace(b'\0',b' ').decode(errors='replace')
            maps = (proc/'maps').read_text()
        except (PermissionError,FileNotFoundError,ProcessLookupError):
            continue
        if proc.name == str(__import__('os').getpid()):
            continue
        if any(item['path'] in cmd or item['path'] in maps for item in remove):
            raise RuntimeError('retired model still referenced by live process '+proc.name)
    report = {'host':'l-dev-ai','applied':False,'remove':remove,
              'allocated_bytes':sum(x['allocated_bytes'] for x in remove),
              'protected':sorted(map(str,protected))}
    a.report.parent.mkdir(parents=True,exist_ok=True)
    a.report.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'paths':len(remove),'allocated_GiB':report['allocated_bytes']/1024**3,'apply':a.apply}),flush=True)
    if a.apply:
        for item in remove:
            shutil.rmtree(item['path'])
            item['deleted'] = True
            a.report.write_text(json.dumps(report,indent=2)+'\n')
        assert all(f.exists() for f in protected)
        report['applied'] = True
        a.report.write_text(json.dumps(report,indent=2)+'\n')
        print('Deleted only the three audited model roots; retained models verified',flush=True)


if __name__ == '__main__':
    main()

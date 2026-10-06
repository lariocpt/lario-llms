#!/usr/bin/env python3
"""Install an individual client fragment from stdin; never accept backend credentials."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[2]
MACHINES=('bigcachy','l-dev-ai','media','mini-mobile')


def install(fragment,machine,home=None,render=True):
    if machine not in MACHINES:raise ValueError('unknown managed machine')
    if not isinstance(fragment,dict) or not fragment or set(fragment)-{'geekom','7900xt','rtx5080'}:
        raise ValueError('only individual hardware client fragments are accepted')
    for hardware,entry in fragment.items():
        if not isinstance(entry,dict) or set(entry)-{'apiKey','context_limits'}:
            raise ValueError('backend/management credentials must not be distributed to clients')
        if not isinstance(entry.get('apiKey'),str) or not re.fullmatch(r'[A-Za-z0-9_-]{24,}',entry['apiKey']):
            raise ValueError('invalid client key')
        limits=entry.get('context_limits',{})
        if not isinstance(limits,dict) or any(type(v) is not int or not 4096<=v<=258048 for v in limits.values()):
            raise ValueError('invalid client context limits')
    private=(home or Path.home())/'.config/lario-admission'
    private.mkdir(parents=True,exist_ok=True,mode=0o700)
    path=private/'clients.json'
    previous=path.read_text() if path.exists() else None
    data=json.loads(previous) if previous else {}
    if not isinstance(data,dict):raise ValueError('existing client store must be an object')
    data.update(fragment)
    text=json.dumps(data,indent=2)+'\n'
    def write(value):
        descriptor,temporary=tempfile.mkstemp(prefix='clients.',dir=private)
        try:
            os.fchmod(descriptor,0o600)
            with os.fdopen(descriptor,'w') as file:file.write(value)
            os.replace(temporary,path)
        finally:Path(temporary).unlink(missing_ok=True)
    if text!=previous:write(text)
    else:os.chmod(path,0o600)
    try:
        if render:
            setup=ROOT.parent/'machine-setup'
            subprocess.run([sys.executable,str(setup/'scripts/render-agent-configs.py'),
                '--machine',machine,'--base-dir',str(setup/'shared/agents'),
                '--overlay-dir',str(setup/'machines'/machine/'config')],check=True)
    except BaseException:
        if previous is None:path.unlink(missing_ok=True)
        else:write(previous)
        raise
    print('Installed client fragment for '+', '.join(fragment)+'; no OpenCode process restart or reload performed.')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--machine',choices=MACHINES,required=True)
    parser.add_argument('--no-render',action='store_true')
    args=parser.parse_args();install(json.load(sys.stdin),args.machine,render=not args.no_render)

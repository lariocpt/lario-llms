#!/usr/bin/env python3
"""Sync the managed Arc fragment, then use credential-preserving client installs."""
import json
from pathlib import Path
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PATCH = r'''
import json, os, shutil, socket, sys, time
from pathlib import Path
payload = json.load(sys.stdin)
if socket.gethostname().split('.')[0] != payload['host']:
    raise RuntimeError('unexpected client host')
path = Path.home()/'Projects/personal/machine-setup/shared/agents/opencode.prepared.json'
doc = json.loads(path.read_text())
provider = doc['provider']['arcB70']
provider['models'] = payload['provider']['models']
provider['whitelist'] = payload['provider']['whitelist']
text = json.dumps(doc, indent=2)+'\n'
if path.read_text() != text:
    backup = Path.home()/'.cache/lario-llms/config-backups'
    backup.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, backup/('opencode.prepared.'+str(time.time_ns())+'.json'))
    temporary = path.with_name(path.name+'.flash-tmp')
    temporary.write_text(text)
    os.replace(temporary, path)
print(payload['host']+': managed Arc source fragment synced')
'''


def main():
    provider = json.loads((ROOT/'arcB70/opencode.prepared.json').read_text())['provider']['arcB70']
    if not any('qwen38-flash' in key for key in provider['whitelist']):
        raise RuntimeError('validated Flash profile is not published')
    for host in ('bigcachy', 'l-dev-ai', 'cachyos-mini-mobile'):
        command = [sys.executable, '-c', PATCH] if host == 'bigcachy' else [
            'ssh', '-T', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=8', host,
            'python3 -c '+shlex.quote(PATCH)]
        subprocess.run(command, input=json.dumps({'host': host, 'provider': provider}),
                       text=True, check=True, timeout=30)
    subprocess.run([sys.executable, str(ROOT/'arcB70/install_clients.py')], check=True)


if __name__ == '__main__':
    main()

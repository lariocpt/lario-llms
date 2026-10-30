"""Read-only monitoring of resident servers in private Podman namespaces."""
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def resident_slots(reg, endpoint):
    """Read the child inside its private namespace, outside proxy admission."""
    hardware = reg['aliases'][0]
    store = reg.get('model_store')
    if store is None:
        placement = json.loads((ROOT/hardware/'placement.json').read_text())
        if placement['host'] != reg['host']:
            raise RuntimeError('container monitoring owner differs from placement')
        store = placement['model_store']
    store = Path(store)
    if reg.get('engine') != 'podman':
        raise RuntimeError('unsupported container monitoring placement')
    script = '''import json, sys, urllib.request
from pathlib import Path
key = Path(sys.argv[2]).read_text().strip()
request = urllib.request.Request(sys.argv[1], headers={'Authorization': 'Bearer '+key})
with urllib.request.urlopen(request, timeout=5) as response:
    print(json.dumps(json.load(response)))
'''
    result = subprocess.run([
        'podman', '--root', reg.get('runtime_store',str(store/'containers'/hardware)), '--runroot',
        os.environ.get('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}')+f'/lario-{hardware}'+('-home-podman' if reg.get('runtime_store') else '-podman'),
        'exec', reg['container'], 'python3', '-c', script, endpoint, reg['backend_key_file'],
    ], capture_output=True, text=True, timeout=8, check=True)
    return json.loads(result.stdout)

#!/usr/bin/env python3
"""Retry missing enabled model services; never restart active inference or clear Off."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import socket
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from shared import modelctl
from shared.lifecycle import stop_marker
from shared.serving.state import off_marker

PEERS={'bigcachy':'l-dev-ai','l-dev-ai':'bigcachy'}
HARDWARE=('geekom','rtx5080','arcB70','7900xt')


def run(args, timeout=12):
    return subprocess.run(args,capture_output=True,text=True,timeout=timeout)


def ensure_unit(unit, runner=run):
    # Respect administrative disable/mask and avoid duplicate starts while loading.
    enabled=runner(['systemctl','--user','is-enabled',unit]).stdout.strip()
    if enabled not in ('enabled','enabled-runtime'):return 'not-enabled'
    state=runner(['systemctl','--user','show',unit,'--property=ActiveState','--value']).stdout.strip()
    if state in ('active','activating','reloading','deactivating'):return state
    result=runner(['systemctl','--user','start','--no-block',unit])
    if result.returncode:raise RuntimeError('unit start failed: '+unit)
    return 'start-requested'


def reconcile(reg, runner=run):
    hardware=reg['aliases'][0]
    result={'hardware':hardware}
    # Admission remains accessible even while hardware is intentionally Off.
    result['gateway']=ensure_unit('lario-admission@'+hardware+'.service',runner)
    if off_marker(reg).exists() or stop_marker(reg).exists():
        result['backend']='off';return result
    try:
        modelctl.assert_not_held(reg)
        modelctl.assert_device_ready(reg)
    except RuntimeError as exc:
        result['backend']='waiting';result['reason']=str(exc);return result
    result['backend']=ensure_unit(reg['service'],runner)
    return result


def main(local_only=False):
    host=socket.gethostname().split('.')[0]
    runtime=Path(os.environ.get('XDG_RUNTIME_DIR',f'/run/user/{os.getuid()}'))
    with (runtime/'lario-backend-watch.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return
        for hardware in HARDWARE:
            reg=json.loads((ROOT/hardware/'models.json').read_text())
            if reg['host']!=host:continue
            try:print(json.dumps(reconcile(reg)),flush=True)
            except Exception as exc:print(json.dumps({'hardware':hardware,'error':str(exc)[:200]}),flush=True)
        if not local_only and host in PEERS:
            # Fixed operation only. Peer executes its own local policy and Off checks.
            peer=PEERS[host]
            try:
                result=run(['ssh','-T','-o','BatchMode=yes','-o','ConnectTimeout=5',peer,
                    'python3 Projects/personal/lario-llms/shared/backend_watch.py --local-only'],timeout=30)
                print(json.dumps({'peer':peer,'reachable':result.returncode==0,
                                  'local_recovery':result.stdout.strip()[:2000]}),flush=True)
            except (OSError,subprocess.TimeoutExpired):
                print(json.dumps({'peer':peer,'reachable':False}),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--local-only',action='store_true')
    main(parser.parse_args().local_only)

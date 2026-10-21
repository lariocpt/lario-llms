#!/usr/bin/env python3
"""Restricted SSH adapter: exact-run OpenCode RPC only; never a general API proxy."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import urlencode


def control(body, runner=subprocess.run):
    if not isinstance(body,dict) or set(body)!={'operation','session_id','run_id','instance_id','location'}:
        raise ValueError('exact run identity required')
    if body['operation']!='cancel':raise ValueError('only exact-run cancellation is supported')
    for field in ('session_id','run_id','instance_id'):
        if not isinstance(body[field],str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,160}',body[field]):
            raise ValueError('invalid run identity')
    location=body['location']
    if not isinstance(location,str) or len(location)>1024 or not Path(location).is_absolute() or not Path(location).is_dir():
        raise ValueError('registered OpenCode location unavailable')
    # Read existing session metadata before selecting a location. The forced SSH
    # key must not initialize arbitrary directories and their project plugins.
    existing=runner(['opencode','api','GET','/api/session/'+body['session_id']],
                    capture_output=True,text=True,timeout=15)
    if existing.returncode:raise RuntimeError('OpenCode session unavailable')
    info=json.loads(existing.stdout);info=info.get('data',info)
    if Path(info.get('location',{}).get('directory','')).resolve()!=Path(location).resolve():
        raise ValueError('session location changed; refresh before cancelling')
    path='/api/rpc/lario-model-control/cancel?'+urlencode({'location.directory':location})
    payload={'input':{k:body[k] for k in ('session_id','run_id','instance_id')}}
    result=runner(['opencode','api','POST',path,'--data',json.dumps(payload)],
                  capture_output=True,text=True,timeout=45)
    if result.returncode:raise RuntimeError('OpenCode run control unavailable; no interruption confirmed')
    data=json.loads(result.stdout).get('output',{})
    if data.get('status') not in ('interrupted','idle','stale_run','stopping'):
        raise RuntimeError('Unrecognized OpenCode interruption outcome')
    return {k:data[k] for k in ('status','interrupted')}


def main():
    if os.getenv('SSH_ORIGINAL_COMMAND')!='lario-model-control-v1':
        raise ValueError('restricted model-control command required')
    raw=sys.stdin.buffer.read(8193)
    if len(raw)>8192:raise ValueError('request too large')
    return control(json.loads(raw))


if __name__=='__main__':
    try:print(json.dumps(main()))
    except Exception as exc:
        print(json.dumps({'status':'unconfirmed','error':str(exc)[:200]}));sys.exit(1)

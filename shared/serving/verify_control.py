#!/usr/bin/env python3
"""Verify deployed page-to-client SSH/RPC guards using disposable idle sessions, no inference."""
import json
from pathlib import Path
import shlex
import socket
import subprocess
from urllib.parse import urlencode
import uuid

ROOT=Path(__file__).resolve().parents[2]
HOSTS={'bigcachy':'bigcachy','l-dev-ai':'l-dev-ai','mini-mobile':'cachyos-mini-mobile'}


def verify():
    config=json.loads((Path.home()/'.config/lario-model-control/panel.json').read_text())
    directory=str(ROOT);query='?'+urlencode({'location.directory':directory})
    for client,host in HOSTS.items():
        def api(method,path,body=None):
            command=['opencode','api',method,path]
            if body is not None:command+=['--data',json.dumps(body)]
            if socket.gethostname().split('.')[0]!=host:
                command=['ssh','-T','-o','BatchMode=yes',host,shlex.join(command)]
            result=subprocess.run(command,text=True,capture_output=True,timeout=30)
            if result.returncode:raise RuntimeError(client+': OpenCode API check failed')
            return json.loads(result.stdout) if result.stdout.strip() else None
        status=api('POST','/api/rpc/lario-model-control/status'+query,{'input':{}})['output']
        assert status['client']==client
        session=api('POST','/api/session'+query,{'title':'Disposable model control verification','location':{'directory':directory}})
        session=session.get('data',session);sid=session['id']
        try:
            body={'operation':'cancel','session_id':sid,'run_id':'check-'+uuid.uuid4().hex,
                  'instance_id':status['instance_id'],'location':directory}
            command=['docker','exec','-i','lario-model-control','ssh','-T','-o','BatchMode=yes',
                     '-o','IdentitiesOnly=yes','-o','StrictHostKeyChecking=yes','-o','ConnectTimeout=8',
                     '-o','UserKnownHostsFile='+config['ssh_known_hosts'],'-i',config['ssh_key'],
                     config['clients'][client]['host'],'lario-model-control-v1']
            result=subprocess.run(command,input=json.dumps(body),text=True,capture_output=True,timeout=60)
            if result.returncode:raise RuntimeError(client+': restricted SSH check failed: '+result.stderr[-250:]+result.stdout[-250:])
            outcome=json.loads(result.stdout)
            assert outcome['status']=='stale_run' and not outcome['interrupted'],outcome
            print(client+': live identity + restricted SSH + stale-run guard PASS (no inference)')
        finally:
            api('DELETE','/api/session/'+sid)


if __name__=='__main__':verify()

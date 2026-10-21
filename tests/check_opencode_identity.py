#!/usr/bin/env python3
"""Real installed OpenCode/plugin smoke check against a fake local model; no GPU work."""
import base64
import contextlib
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import queue
import re
import socket
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT=Path(__file__).resolve().parents[1]


def check():
    seen=queue.Queue();release=threading.Event()
    class Model(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            seen.put(({k.lower():v for k,v in self.headers.items() if k.lower().startswith('x-lario-')},body.get('stream')))
            self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
            if release.wait(30):
                try:
                    self.wfile.write(b'data: {"id":"test","object":"chat.completion.chunk","choices":[{"index":0,"delta":{"content":"READY"},"finish_reason":null}]}\n\ndata: {"id":"test","object":"chat.completion.chunk","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n');self.wfile.flush()
                except (BrokenPipeError,ConnectionResetError):pass
    fake=ThreadingHTTPServer(('127.0.0.1',0),Model);fake.daemon_threads=True
    thread=threading.Thread(target=fake.serve_forever,daemon=True);thread.start()
    with tempfile.TemporaryDirectory(prefix='lario-identity-check-') as temp:
        directory=Path(temp);config=directory/'config/opencode';config.mkdir(parents=True)
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        model='geekom.test-profile'
        data={'provider':{'geekom':{'npm':'@ai-sdk/openai-compatible','options':{
            'apiKey':'isolated-test-only','baseURL':f'http://127.0.0.1:{fake.server_port}/v1'},
            'models':{model:{'name':'Isolated identity test','limit':{'context':32768,'output':32}}}}},
            'model':'geekom/'+model,'plugins':[{'package':str(ROOT/'shared/serving/opencode-plugin'),'options':{'client':'test-client'}}]}
        (config/'opencode.json').write_text(json.dumps(data))
        env={**os.environ,'XDG_CONFIG_HOME':str(directory/'config'),'XDG_DATA_HOME':str(directory/'data'),
             'XDG_STATE_HOME':str(directory/'state'),'XDG_CACHE_HOME':str(directory/'cache')}
        log=directory/'server.log'
        with log.open('w') as output:
            server=subprocess.Popen(['opencode','serve','--hostname','127.0.0.1','--port',str(port)],env=env,stdout=output,stderr=output)
        try:
            deadline=time.monotonic()+45;password=None
            while time.monotonic()<deadline:
                match=re.search(r'server password ([^\s\x1b]+)',log.read_text())
                if match:password=match[1];break
                if server.poll() is not None:raise RuntimeError('Isolated OpenCode failed to start')
                time.sleep(.1)
            if password is None:raise RuntimeError('Isolated server credential unavailable')
            headers={'Authorization':'Basic '+base64.b64encode(('opencode:'+password).encode()).decode(),'Content-Type':'application/json'}
            query='?'+urllib.parse.urlencode({'location.directory':str(directory)})
            def api(path,body=None):
                req=urllib.request.Request(f'http://127.0.0.1:{port}'+path+query,
                      data=json.dumps(body).encode() if body is not None else None,headers=headers)
                with urllib.request.urlopen(req,timeout=30) as response:
                    raw=response.read();return json.loads(raw) if raw else None
            status=api('/api/rpc/lario-model-control/status',{'input':{}})['output']
            assert status['client']=='test-client',status
            session=api('/api/session',{'title':'Disposable identity test','model':{'providerID':'geekom','id':model}})
            session=session.get('data',session)
            sid=session['id']
            api('/api/session/'+sid+'/prompt',{'text':'Wait for this isolated cancellation test.'})
            captured,_=seen.get(timeout=30)
            assert captured['x-lario-client']=='test-client',captured
            assert captured['x-lario-session']==sid,captured
            assert captured['x-lario-instance']==status['instance_id'],captured
            identity={'session_id':sid,'run_id':captured['x-lario-run'],'instance_id':status['instance_id']}
            def cancel(value):return api('/api/rpc/lario-model-control/cancel',{'input':value})['output']
            assert cancel({**identity,'run_id':'obsolete'})['status']=='stale_run'
            assert cancel(identity)['status']=='interrupted'
            # A subsequent explicit turn gets a fresh run identity. An old
            # dashboard action must leave this new turn running.
            while not seen.empty():seen.get_nowait()
            api('/api/session/'+sid+'/prompt',{'text':'This is a new isolated user turn.'})
            next_headers,_=seen.get(timeout=30)
            assert next_headers['x-lario-run']!=identity['run_id']
            assert cancel(identity)['status']=='stale_run'
            assert cancel({**identity,'run_id':next_headers['x-lario-run']})['status']=='interrupted'
            print('PASS: installed OpenCode identity headers, exact-run interrupt and stale-run protection; no GPU inference')
        finally:
            release.set();server.terminate()
            try:server.wait(timeout=15)
            except subprocess.TimeoutExpired:server.kill();server.wait()
    fake.shutdown();fake.server_close()


if __name__=='__main__':check()

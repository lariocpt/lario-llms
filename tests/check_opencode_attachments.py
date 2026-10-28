#!/usr/bin/env python3
"""Real isolated OpenCode attachment hook, fake vision/text owners; no GPU work."""
import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import queue
import struct
import zlib
import re
import socket
import subprocess
import tempfile
import threading
import time
import urllib.request
import urllib.parse

ROOT = Path(__file__).resolve().parents[1]


def check():
    received = queue.Queue()
    state = {'read_path': None}
    class Owner(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_GET(self):
            self.send_response(200); self.send_header('Content-Type', 'application/json'); self.end_headers()
            self.wfile.write(json.dumps({'data': [{'id': 'rtx3060ti.describe.test'}]}).encode())
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            if self.path.startswith('/vision/'):
                received.put(('vision', body))
                self.send_response(200); self.send_header('Content-Type', 'application/json'); self.end_headers()
                self.wfile.write(json.dumps({'choices': [{'message': {'content': 'VISION_EVIDENCE: a blue rectangle'}, 'finish_reason': 'stop'}]}).encode())
            else:
                received.put(('coding', body))
                self.send_response(200); self.send_header('Content-Type', 'text/event-stream'); self.end_headers()
                if state['read_path'] and any(m.get('role') == 'user' and 'Read the screenshot using' in str(m.get('content')) for m in body.get('messages', [])):
                    image_path = state.pop('read_path')
                    state['read_path'] = None
                    chunk = {'id':'tool-read','object':'chat.completion.chunk','choices':[{'index':0,'delta':{'tool_calls':[{'index':0,'id':'read-image','type':'function','function':{'name':'read','arguments':json.dumps({'path': image_path})}}]},'finish_reason':None}]}
                    self.wfile.write(('data: '+json.dumps(chunk)+'\n\n').encode())
                    self.wfile.write(b'data: {"id":"tool-read","object":"chat.completion.chunk","choices":[{"index":0,"delta":{},"finish_reason":"tool_calls"}]}\n\ndata: [DONE]\n\n')
                    return
                self.wfile.write(b'data: {"id":"test","object":"chat.completion.chunk","choices":[{"index":0,"delta":{"content":"REVIEWED"},"finish_reason":null}]}\n\ndata: {"id":"test","object":"chat.completion.chunk","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n')
    owner = ThreadingHTTPServer(('127.0.0.1', 0), Owner); owner.daemon_threads = True
    threading.Thread(target=owner.serve_forever, daemon=True).start()
    with tempfile.TemporaryDirectory(prefix='lario-attachment-check-') as temp:
        directory = Path(temp); config = directory/'config/opencode'; config.mkdir(parents=True)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
        model = 'geekom.test'
        data = {'provider': {'geekom': {'npm': '@ai-sdk/openai-compatible', 'options': {
            'apiKey': 'fake-text-credential', 'baseURL': f'http://127.0.0.1:{owner.server_port}/v1'},
            'models': {model: {'name': 'Attachment smoke test', 'attachment': True,
                'modalities': {'input': ['text', 'image'], 'output': ['text']},
                'limit': {'context': 32768, 'output': 32}}}}},
            'model': 'geekom/'+model, 'plugins': [{'package': str(ROOT/'shared/serving/opencode-plugin'), 'options': {'client': 'attachment-test'}}]}
        (config/'opencode.json').write_text(json.dumps(data))
        keys = directory/'clients.json'; keys.write_text(json.dumps({'rtx3060ti': {'apiKey': 'fake-vision-key-'+'x'*30}}))
        image = directory/'screen.png'
        def chunk(kind, data):
            return struct.pack('>I', len(data))+kind+data+struct.pack('>I', zlib.crc32(kind+data))
        image.write_bytes(b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR', struct.pack('>IIBBBBB', 2, 2, 8, 2, 0, 0, 0))+
            chunk(b'IDAT', zlib.compress((b'\0'+b'\0\0\xff'*2)*2))+chunk(b'IEND', b''))
        env = {**os.environ, 'XDG_CONFIG_HOME': str(directory/'config'), 'XDG_DATA_HOME': str(directory/'data'),
            'XDG_STATE_HOME': str(directory/'state'), 'XDG_CACHE_HOME': str(directory/'cache'),
            'LARIO_MODEL_CLIENTS_FILE': str(keys), 'LARIO_IMAGES_VISION_ENDPOINTS': json.dumps({'rtx3060ti': f'http://127.0.0.1:{owner.server_port}/vision'})}
        log = directory/'server.log'
        with log.open('w') as output:
            server = subprocess.Popen(['opencode', 'serve', '--hostname', '127.0.0.1', '--port', str(port)],
                                      env=env, stdout=output, stderr=output)
        try:
            deadline = time.monotonic()+45; password = None
            while time.monotonic() < deadline:
                match = re.search(r'server password ([^\s\x1b]+)', log.read_text())
                if match: password = match[1]; break
                if server.poll() is not None: raise RuntimeError('Isolated OpenCode failed: '+log.read_text()[-1000:])
                time.sleep(.1)
            if password is None: raise RuntimeError('No isolated service password')
            headers = {'Authorization': 'Basic '+base64.b64encode(('opencode:'+password).encode()).decode(), 'Content-Type': 'application/json'}
            def api(path, body):
                req = urllib.request.Request(f'http://127.0.0.1:{port}'+path+'?'+urllib.parse.urlencode({'location.directory': str(directory)}),
                    data=json.dumps(body).encode(), headers=headers)
                with urllib.request.urlopen(req, timeout=30) as response: return json.load(response)
            session = api('/api/session', {'title': 'Disposable attachment test', 'model': {'providerID': 'geekom', 'id': model}})
            sid = session.get('data', session)['id']
            api('/api/session/'+sid+'/prompt', {'text': 'Review this screenshot: '+str(time.time_ns()), 'files': [{'uri': image.as_uri(), 'name': 'screen.png'}]})
            vision = False; coding = None; deadline = time.monotonic()+30
            while time.monotonic() < deadline:
                kind, body = received.get(timeout=30)
                if kind == 'vision': vision = True
                elif 'VISION_EVIDENCE' in json.dumps(body): coding = body; break
            assert vision, 'No vision request received'
            assert coding, 'Coding request did not contain vision evidence'
            serialised = json.dumps(coding)
            assert 'image_url' not in serialised and 'data:image/' not in serialised, 'Pixels reached the text model'
            print('PASS: installed OpenCode accepts file attachment, TI vision runs, coding model receives evidence without pixels')
            while not received.empty(): received.get_nowait()
            state['read_path'] = str(image)
            session = api('/api/session', {'title': 'Disposable tool-image test', 'model': {'providerID': 'geekom', 'id': model}})
            tool_sid = session.get('data', session)['id']
            api('/api/session/'+tool_sid+'/prompt', {'text': 'Read the screenshot using the read tool: '+str(image)})
            vision = False; converted = None; deadline = time.monotonic()+40
            while time.monotonic() < deadline:
                kind, body = received.get(timeout=40)
                if kind == 'vision': vision = True
                elif '[Image analysis;' in json.dumps(body): converted = body; break
            assert vision, 'Tool-returned image did not reach vision'
            assert converted, 'No continuation after read-tool image'
            assert 'image_url' not in json.dumps(converted) and 'data:image/' not in json.dumps(converted)
            print('PASS: real read-tool image reaches vision and agent continues without pixels in text request')
            while not received.empty(): received.get_nowait()
            api('/api/session/'+tool_sid+'/prompt', {'text': 'Summarise the previous visual evidence.'})
            deadline = time.monotonic()+40; converted = None
            while time.monotonic() < deadline:
                kind, body = received.get(timeout=40)
                assert kind != 'vision', 'Historical image was analysed again instead of cached'
                if '[Image analysis;' in json.dumps(body): converted = body; break
            assert converted, 'Historical tool image did not convert on subsequent turn'
            print('PASS: subsequent turn repairs image history using cached evidence')

        finally:
            server.terminate()
            try: server.wait(timeout=10)
            except subprocess.TimeoutExpired: server.kill(); server.wait()
    owner.shutdown(); owner.server_close()


if __name__ == '__main__': check()

#!/usr/bin/env python3
"""Local read-only model/GPU exporter. Never infer, warm, switch or expose keys."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import math
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import shlex
import socket
import subprocess
import sys
import threading
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from benchmarks.telemetry import amd_memory
from shared.modelctl import fleet_capacity
from shared.placements import inventory


def get(url):
    with urllib.request.urlopen(url, timeout=4) as response:
        return json.load(response)


def sample(name, value, **labels):
    if value is None or not math.isfinite(float(value)):
        return ''
    tags = ','.join(k+'='+json.dumps(str(v)) for k,v in sorted(labels.items()))
    return f'{name}{{{tags}}} {float(value):.17g}\n'


def model_metrics(hardware):
    reg = json.loads((ROOT/hardware/'models.json').read_text())
    labels = {'hardware':hardware, 'workload':'chat'}
    try:
        try:
            state = get(f'http://127.0.0.1:{reg["port"]}/budget')
            ready = bool(state.get('ready'))
        except urllib.error.HTTPError as exc:
            if exc.code != 404:raise
            exc.close()
            running = get(f'http://127.0.0.1:{reg["port"]}/running')['running']
            if len(running) != 1 or running[0]['state'] != 'ready':
                raise ValueError('no ready model')
            item = running[0];args = shlex.split(item['cmd'])
            slots = int(args[args.index('--parallel')+1]);total = int(args[args.index('-c')+1])
            if slots < 1 or total % slots:raise ValueError('invalid geometry')
            state = {'model':item['model'],'slots':slots,'context':total//slots,
                     'reserved':reg['models'][item['model']]['reserved']}
            state['agents'] = fleet_capacity(state['slots'],state['reserved'],state['context'])
            ready = True
        # Model label must be registered, not caller-controlled content.
        model = state.get('model')
        if model is not None and model not in reg['models']:raise ValueError('unknown model')
        output = sample('lario_model_ready', ready, **labels)
        output += sample('lario_model_occupancy_known', 'busy' in state, **labels)
        if model:
            output += sample('lario_model_info', 1, model=model, **labels)
            for field in ('slots','context','reserved','agents','busy','available','draining','uncertain'):
                if field in state:output += sample('lario_model_'+field, state[field], **labels)
        return output
    except (OSError, ValueError, KeyError, TypeError):
        return sample('lario_model_ready', 0, **labels)


def intel_metrics(workload, port):
    labels = {'hardware':'intel','workload':workload}
    try:
        state = get(f'http://127.0.0.1:{port}/health')
        output = sample('lario_model_ready', state.get('model_loaded') is True, **labels)
        # Device values come from fixed service configuration; omit model paths.
        model = state.get('current_model', state.get('model'))
        if model in ('BAAI/bge-m3','whisper-large-v3-turbo-fp16','qwen3-8b-int4','kokoro-82m-int8'):
            output += sample('lario_model_info', 1, model=model, **labels)
        device = state.get('device', 'unknown')
        if device in ('CPU','GPU','GPU.0','NPU'):
            output += sample('lario_model_device_info', 1, device=device, **labels)
        return output
    except (OSError, ValueError, KeyError, TypeError):
        return sample('lario_model_ready', 0, **labels)


_ARC_ENERGY = None


def arc_gpu_metrics():
    global _ARC_ENERGY
    try:
        from shared.gpu import intel_arc_device
        device=intel_arc_device()
        hw=next((Path('/sys/bus/pci/devices')/device['pci']/'hwmon').glob('hwmon*'))
        output=sample('lario_gpu_probe_up',1,hardware='arcB70')
        for entry in hw.glob('temp*_input'):
            label=entry.with_name(entry.name.replace('_input','_label'))
            if label.exists() and label.read_text().strip() in ('pkg','vram','pcie','mctrl'):
                output+=sample('lario_gpu_temperature_celsius',int(entry.read_text())/1000,
                               hardware='arcB70',sensor=label.read_text().strip())
        output+=sample('lario_gpu_fan_rpm',int((hw/'fan1_input').read_text()),hardware='arcB70')
        output+=sample('lario_gpu_power_limit_watts',int((hw/'power1_cap').read_text())/1e6,hardware='arcB70')
        now=time.monotonic();energy=int((hw/'energy1_input').read_text())
        if _ARC_ENERGY is not None:
            previous,then=_ARC_ENERGY
            if energy>=previous and now>then:
                output+=sample('lario_gpu_power_watts',(energy-previous)/1e6/(now-then),hardware='arcB70')
        _ARC_ENERGY=(energy,now)
        return output
    except (OSError,ValueError,RuntimeError,StopIteration):
        return sample('lario_gpu_probe_up',0,hardware='arcB70')


def gpu_metrics(host):
    output = ''
    if host == 'bigcachy':
        try:
            result = subprocess.run(['nvidia-smi','--query-gpu=memory.used,memory.total,utilization.gpu,temperature.gpu,power.draw,fan.speed',
                                     '--format=csv,noheader,nounits'],capture_output=True,text=True,timeout=4,check=True)
            values = result.stdout.strip().split(',')
            if len(values)!=6:raise ValueError('unexpected NVIDIA result')
            output += sample('lario_gpu_probe_up',1,hardware='rtx5080')
            for name,value,multiplier in zip(('memory_used_bytes','memory_total_bytes','utilization_percent','temperature_celsius','power_watts','fan_percent'),values,(1048576,1048576,1,1,1,1)):
                try:output += sample('lario_gpu_'+name,float(value)*multiplier,hardware='rtx5080')
                except ValueError:pass
        except (OSError, ValueError, subprocess.SubprocessError):
            output += sample('lario_gpu_probe_up',0,hardware='rtx5080')
    elif host == 'l-dev-ai':
        for row in amd_memory():
            identity = Path('/sys/bus/pci/devices')/row['pci_address']/'unique_id'
            is_radeon = identity.exists() and identity.read_text().strip() == '255c7a14946751e2'
            hardware = 'geekom7900xt' if is_radeon else 'geekom'
            valid = 'error_type' not in row
            output += sample('lario_gpu_probe_up', valid, hardware=hardware)
            if not valid:
                continue
            for field, name in (('used_bytes','memory_used_bytes'),('total_bytes','memory_total_bytes'),('utilization_percent','utilization_percent')):
                output += sample('lario_gpu_'+name,row.get(field),hardware=hardware)
            for sensor,value in row.get('temperatures_c',{}).items():
                output += sample('lario_gpu_temperature_celsius',value,hardware=hardware,sensor=sensor)
    if host=='bigcachy':output+=arc_gpu_metrics()
    return output


def placement_metrics(host):
    output = ''
    for placement in inventory():
        if placement['host'] != host:
            continue
        labels = {'hardware':placement['hardware'], 'placement_status':placement['status'],
                  'owner':host, 'physical_resource':placement['physical_resource'] or 'unverified'}
        output += sample('lario_model_placement_info', 1, **labels)
        for profile in placement['profiles']:
            output += sample('lario_model_prepared_profile_info', 1, profile_id=profile['id'],
                             model=profile['model'], context=profile['context'],
                             slots=profile['slots'], **labels)
    return output


def collect(host):
    owners = {'bigcachy':['rtx5080'], 'l-dev-ai':['geekom','geekom7900xt'], 'cachyos-mini-mobile':[]}[host]
    jobs = [(model_metrics,(owner,)) for owner in owners]
    if host == 'bigcachy':jobs += [(intel_metrics,(w,p)) for w,p in [('embedding',8001),('asr',8002),('translation',8003),('tts',8004)]]
    if host=='bigcachy':jobs.append((model_metrics,('arcB70',)))
    with ThreadPoolExecutor(max_workers=5) as pool:
        output = ''.join(pool.map(lambda job:job[0](*job[1]),jobs))
    if host == 'bigcachy':
        try:
            get('http://127.0.0.1:8188/system_stats')
            image_up = True
        except (OSError, ValueError):
            image_up = False
        output += sample('lario_image_runtime_up', image_up, hardware='rtx5080')
    try:output += gpu_metrics(host)
    except (OSError, ValueError):output += sample('lario_exporter_gpu_collection_error',1)
    output += placement_metrics(host)
    memory = dict(line.split(':',1) for line in Path('/proc/meminfo').read_text().splitlines())
    output += sample('lario_host_memory_available_bytes',int(memory['MemAvailable'].split()[0])*1024)
    output += sample('lario_exporter_last_success_unixtime',time.time())
    return output


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host',choices=['bigcachy','l-dev-ai','cachyos-mini-mobile'],default=socket.gethostname().split('.')[0])
    parser.add_argument('--once',action='store_true')
    args=parser.parse_args()
    if args.once:print(collect(args.host),end='');return
    state={'text':''}
    def refresh():
        while True:
            try:state['text']=collect(args.host)
            except Exception:state['text']=sample('lario_exporter_collection_error',1)
            time.sleep(15)
    threading.Thread(target=refresh,daemon=True).start()
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path!='/metrics':self.send_error(404);return
            raw=state['text'].encode();self.send_response(200 if raw else 503)
            self.send_header('Content-Type','text/plain; version=0.0.4; charset=utf-8')
            self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
        def log_message(self,*args):pass
    ThreadingHTTPServer(('127.0.0.1',9668),Handler).serve_forever()

if __name__=='__main__':main()

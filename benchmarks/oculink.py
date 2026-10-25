#!/usr/bin/env python3
"""Sequential, synthetic Radeon migration checks; run on its registered owner."""
import argparse
import json
import os
from pathlib import Path
import re
import socket
import sys
import threading
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from shared import modelctl
from shared.gpu import radeon_device
from shared.model_tools import owner


def telemetry(device):
    card = Path('/sys/bus/pci/devices')/device['pci']
    result = {'time': time.time()}
    for field in ('mem_info_vram_used', 'mem_info_vram_total'):
        result[field] = int((card/field).read_text())
    for line in Path('/proc/meminfo').read_text().splitlines():
        if line.startswith('MemAvailable:'):
            result['ram_available_bytes'] = int(line.split()[1])*1024
    links = []
    for hop in (card.resolve(), *card.resolve().parents):
        if re.fullmatch(r'[0-9a-f]{4}:[0-9a-f]{2}:[0-9a-f]{2}\.[0-7]', hop.name):
            try:
                links.append({'pci': hop.name, 'speed': (hop/'current_link_speed').read_text().strip(),
                              'width': int((hop/'current_link_width').read_text())})
            except (OSError, ValueError):
                pass
    result['links'] = links
    for sensor in (card/'hwmon').glob('hwmon*'):
        for name in ('temp1_input', 'temp2_input', 'power1_average'):
            try:
                result[name] = int((sensor/name).read_text())
            except OSError:
                pass
    return result


def completion(reg, prompt):
    request = urllib.request.Request(f'http://127.0.0.1:{reg["port"]}/v1/chat/completions',
        data=json.dumps({'model':'geekom7900xt', 'messages':[{'role':'user','content':prompt}],
                         'max_tokens':4096, 'temperature':0,
                         'chat_template_kwargs':{'enable_thinking':False}}).encode(),
        headers={'Content-Type':'application/json', 'Authorization':'Bearer '+os.environ['LARIO_INTERACTIVE_KEY']})
    started = time.monotonic()
    with urllib.request.urlopen(request, timeout=1800) as response:
        data = json.load(response)
    choice = data['choices'][0]
    return {'seconds':time.monotonic()-started, 'reply':choice['message'].get('content'),
            'finish_reason':choice.get('finish_reason'), 'usage':data.get('usage'), 'timings':data.get('timings')}


def switch(option):
    before = owner.operate({'operation':'status','hardware':'geekom7900xt'})
    return owner.operate({'operation':'switch','hardware':'geekom7900xt', 'option':option,
                          'switch_token':before['switch_token'], 'allow_experimental':True})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    reg = json.loads((ROOT/'geekom7900xt/models.json').read_text())
    if socket.gethostname().split('.')[0] != reg['host']:
        raise RuntimeError('run the benchmark on the Radeon owner')
    modelctl.load_runtime(reg)
    original = '@'.join(modelctl.selection(reg))
    result = {'owner':reg['host'], 'original':original, 'profiles':[], 'started':time.time()}
    def persist():
        args.output.parent.mkdir(parents=True, exist_ok=True)
        modelctl.atomic(args.output, json.dumps(result, indent=2)+'\n')
    try:
        for option in ('qwen3.8@fast-128k',
                       'muse-glimmer@capacity', 'muse-glimmer-dflash@capacity'):
            record = {'option':option}; result['profiles'].append(record)
            samples = []; stopped = threading.Event()
            def monitor():
                while not stopped.is_set():
                    try:
                        samples.append(telemetry(radeon_device(reg['device_identity'])))
                    except (OSError, RuntimeError, ValueError):
                        pass
                    stopped.wait(0.5)
            worker = threading.Thread(target=monitor, daemon=True); worker.start()
            try:
                started = time.monotonic(); switched = switch(option)
                record.update(switch_seconds=time.monotonic()-started, status=switched['status'])
                record['completion'] = completion(reg, 'Reply with exactly RADEON_OK and no other text.')
                record['arithmetic'] = completion(reg, 'What is 17 plus 25? Reply with exactly 42.')
                record['passed'] = (str(record['completion']['reply']).strip() == 'RADEON_OK' and
                                    str(record['arithmetic']['reply']).strip() == '42')
            except Exception as exc:
                record.update(passed=False, error_type=type(exc).__name__, error=str(exc)[:500])
            finally:
                stopped.set(); worker.join(timeout=2)
                record['telemetry'] = samples
                persist()
            print(json.dumps({key:record[key] for key in ('option','passed','error') if key in record}), flush=True)
    finally:
        try:
            switch(original)
            result['restored'] = owner.operate({'operation':'status','hardware':'geekom7900xt'})
        except Exception as exc:
            result['restore_error'] = {'type':type(exc).__name__, 'message':str(exc)[:500]}
        result['finished'] = time.time(); persist()


if __name__ == '__main__':
    main()

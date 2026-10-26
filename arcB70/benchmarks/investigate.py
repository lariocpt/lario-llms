#!/usr/bin/env python3
"""Bounded, synthetic B70 diagnostic. Credentials are loaded but never saved."""
import argparse
import concurrent.futures
import json
import os
from pathlib import Path
import sys
import signal
import threading
import time
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from shared import modelctl
from shared.serving.control import operate
from shared.serving.catalog import profiles


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--suite', choices=['baseline', 'reuse', 'concurrent', 'smoke', 'cache-state'], default='baseline')
    ap.add_argument('--routes', nargs='+', choices=['native','gateway'], default=['native','gateway'])
    ap.add_argument('--timeout', type=int, default=600)
    ap.add_argument('--clear-native-idle', action='store_true', help='explicit cache-state intervention, only under admission pause')
    a = ap.parse_args()
    if not 30 <= a.timeout <= 900:ap.error('timeout must be 30..900 seconds')
    a.output.mkdir(parents=True, exist_ok=True)
    reg = json.loads((ROOT/'arcB70/models.json').read_text())
    modelctl.load_runtime(reg)
    initial = operate('arcB70', 'status')
    if initial['requests'] or initial['busy'] or initial['uncertain'] or not initial['ready']:
        raise RuntimeError('B70 must be genuinely idle and ready')
    if initial['draining']:
        raise RuntimeError('gateway comparison requires originally unpaused admission')
    (a.output/'initial.json').write_text(json.dumps(initial, indent=2))
    def interrupted(signum, frame):
        raise KeyboardInterrupt(f'signal {signum}')
    signal.signal(signal.SIGTERM, interrupted)
    profile = next(p for p in profiles(reg).values() if p['model']=='qwen3.8-smart-q4-128k')
    backend = initial['residents'][0]['id']
    running = modelctl.api(reg, '/running')['running']
    item = next(x for x in running if x['model']==backend)
    native = item['proxy']
    stop = threading.Event()

    def telemetry():
        with (a.output/'telemetry.jsonl').open('a') as out:
            while not stop.is_set():
                row = {'utc_epoch':time.time()}
                for hw in Path('/sys/bus/pci/devices/0000:04:00.0/hwmon').glob('*'):
                    for p in hw.glob('*_input'):
                        if p.name.startswith(('temp','fan','energy','power')):
                            try: row[p.name] = int(p.read_text())
                            except OSError: pass
                row['loadavg'] = os.getloadavg()
                for p in Path('/sys/bus/pci/devices/0000:04:00.0/tile0').glob('gt*/freq0/**'):
                    if p.is_file() and p.name in ('act_freq','cur_freq','max_freq','status','reasons'):
                        try:row[str(p.relative_to(Path('/sys/bus/pci/devices/0000:04:00.0')))] = p.read_text().strip()
                        except OSError:pass
                out.write(json.dumps(row)+'\n');out.flush()
                stop.wait(2)

    monitor = threading.Thread(target=telemetry, daemon=True);monitor.start()

    def call(route, label, prompt, cache=False, thinking=False, barrier=None, slot=None):
        if barrier: barrier.wait()
        body = {'model':backend if route=='native' else profile['id'],
                'messages':[{'role':'user','content':prompt}], 'max_tokens':64,
                'temperature':0, 'seed':42, 'stream':True,
                'stream_options':{'include_usage':True},
                'cache_prompt':cache, 'chat_template_kwargs':{'enable_thinking':thinking}}
        if slot is not None:
            if route!='native':raise RuntimeError('slot pinning is native-only')
            body['id_slot']=slot
        key = os.environ['LARIO_BACKEND_KEY' if route=='native' else 'LARIO_INTERACTIVE_KEY']
        url = (native if route=='native' else 'http://127.0.0.1:11437')+'/v1/chat/completions'
        start = time.monotonic()
        row = {'route':route,'label':label,'cache_requested':cache,'thinking':thinking,'id_slot':slot,
               'utc_epoch':time.time(), 'ttft_s':None,'first_visible_s':None}
        req = urllib.request.Request(url, data=json.dumps(body).encode(),headers={
            'Content-Type':'application/json','Authorization':'Bearer '+key,
            'X-Lario-Run':'b70-investigation-'+uuid.uuid4().hex})
        text_parts=[];reason_parts=[]
        try:
            with urllib.request.urlopen(req, timeout=a.timeout) as response:
                row['http_status']=response.status
                row['headers_s']=time.monotonic()-start
                for line in response:
                    if time.monotonic()-start > a.timeout: raise TimeoutError('overall request deadline')
                    if not line.startswith(b'data: '): continue
                    data=line[6:].strip()
                    if data==b'[DONE]': row['done']=True;break
                    d=json.loads(data)
                    if d.get('timings'):row['timings']=d['timings']
                    if d.get('usage'):row['usage']=d['usage']
                    for choice in d.get('choices',[]):
                        delta=choice.get('delta',{})
                        content=delta.get('content') or ''
                        reason=delta.get('reasoning_content') or ''
                        if (content or reason) and row['ttft_s'] is None:row['ttft_s']=time.monotonic()-start
                        if content and row['first_visible_s'] is None:row['first_visible_s']=time.monotonic()-start
                        text_parts.append(content);reason_parts.append(reason)
                        if choice.get('finish_reason'):row['finish_reason']=choice['finish_reason']
        except Exception as exc:
            row['error']=type(exc).__name__
            raise
        finally:
            row['total_s']=time.monotonic()-start
            row['visible_chars']=sum(map(len,text_parts));row['reasoning_chars']=sum(map(len,reason_parts))
            row['synthetic_reply_excerpt']=''.join(text_parts)[:120]
            row['reasoning_tokens']=row.get('usage',{}).get('completion_tokens_details',{}).get('reasoning_tokens')
            if not row['reasoning_chars']:
                row['reasoning_tokens']=0
            elif not row['visible_chars'] and row.get('finish_reason')=='length':
                row['reasoning_tokens']=row.get('usage',{}).get('completion_tokens')
                row['reasoning_token_basis']='all completion tokens in a length-limited reasoning-only response'
            if row.get('timings') and row['ttft_s'] is not None:
                row['queue_and_frontend_upper_bound_s']=max(0,row['ttft_s']-row['timings']['prompt_ms']/1000)
            with (a.output/'requests.jsonl').open('a') as out:out.write(json.dumps(row)+'\n')
            print(json.dumps(row),flush=True)
        return row

    def clear_native():
        state=operate('arcB70','status')
        if not state['draining'] or state['requests'] or state['busy']:
            raise RuntimeError('native cache intervention requires confirmed paused idleness')
        slots=modelctl.resident_slots(reg,item)
        for slot in slots:
            if slot['is_processing']:raise RuntimeError('native work appeared')
        for slot in slots:
            modelctl.api(reg, '/upstream/'+backend+f'/slots/{slot["id"]}?action=erase',{},timeout=10)

    prefix=uuid.uuid4().hex
    long_prompt='Review these synthetic records, then list layout checks.\n'+''.join(
        f'Record {i}: component button, spacing 8, width 120, colour blue; verify layout.\n' for i in range(1500))
    short='List the integers from one to one hundred, separated by commas.'
    (a.output/'workload.json').write_text(json.dumps({'prefix':prefix,'seed':42,
        'long_records':1500,'output_limit':64,'arguments':vars(a)},default=str,indent=2)+'\n')
    paused=False
    try:
        operate('arcB70','pause');paused=True
        state=operate('arcB70','status')
        if state['requests'] or state['busy']:raise RuntimeError('work appeared before isolation')
        (a.output/'slots-before.json').write_text(json.dumps(modelctl.resident_slots(reg,item),indent=2))
        for route in a.routes:
            if route=='gateway':operate('arcB70','resume');paused=False
            clear=lambda:clear_native() if route=='native' and a.clear_native_idle else None
            clear()
            if a.suite=='reuse':
                prompt=prefix+'\n'+long_prompt
                for n in range(2):call(route,f'reuse-{n}',prompt,cache=True)
                continue
            if a.suite=='cache-state':
                if route!='native':raise RuntimeError('cache-state suite requires native route')
                clear_native()
                call(route,'seed-40k',prefix+' '+route+' '+long_prompt,slot=0)
                call(route,'retained-small',prefix+' '+route+' '+short,slot=1)
                clear_native()
                call(route,'erased-small',prefix+' '+route+' '+short,slot=1)
                continue
            if a.suite!='concurrent':
                call(route,'small',prefix+' '+route+' '+short)
                if a.suite=='smoke':continue
                clear()
                call(route,'40k',prefix+' '+route+' '+long_prompt)
            clear()
            barrier=threading.Barrier(2)
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                fs=[pool.submit(call,route,f'concurrent-small-{n}',prefix+f' {route} {n}\n'+short,False,False,barrier) for n in range(2)]
                for f in fs:f.result()
            clear()
            call(route,'reasoning-small',prefix+' '+route+' What is 17 times 23? Verify your calculation.',thinking=True)
            state=operate('arcB70','status')
            if state['requests'] or state['busy'] or state['uncertain']:raise RuntimeError('work remains; stop scheduling')
    finally:
        stop.set();monitor.join(5)
        state=operate('arcB70','status')
        (a.output/'final.json').write_text(json.dumps(state,indent=2))
        if paused:operate('arcB70','resume')


if __name__=='__main__':main()

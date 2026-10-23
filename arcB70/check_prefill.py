#!/usr/bin/env python3
"""Opt-in bounded synthetic B70 prefill check; run only while admission is paused."""
import concurrent.futures
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from shared import modelctl
from shared.serving.catalog import profiles
from shared.serving.control import operate


def main():
    state=operate('arcB70','status')
    if not state['draining'] or state['requests']:
        raise RuntimeError('pause B70 and wait for requests to clear before this explicit check')
    reg=json.loads((ROOT/'arcB70/models.json').read_text());modelctl.load_runtime(reg)
    profile=next(p for p in profiles(reg).values() if p['model']=='qwen3.8-smart-q4-256k')
    def call(label,prompt):
        start=time.monotonic()
        try:
            d=modelctl.api(reg,'/v1/chat/completions',{'model':profile['id'],
                'messages':[{'role':'user','content':prompt}], 'max_tokens':16,
                'temperature':0,'chat_template_kwargs':{'enable_thinking':False}},timeout=240)
            message=d['choices'][0]['message']
            generated=message.get('content') or message.get('reasoning_content') or ''
            return {'test':label,'elapsed_seconds':round(time.monotonic()-start,2),
                    'usage':d.get('usage'),'produced_tokens':bool(generated),'reply':generated[:100]}
        except Exception as exc:
            return {'test':label,'elapsed_seconds':round(time.monotonic()-start,2),'error':str(exc)}
    results=[call('warmup','Reply with OK.')]
    print(json.dumps(results[-1]),flush=True)
    if not results[-1].get('produced_tokens'):raise RuntimeError('warmup failed')
    # Own synthetic text, never retained user prompts. Roughly 32k tokens.
    prompt='Review these synthetic records, then reply with OK.\n'+''.join(
        f'Record {i}: component button, spacing 8, width 120, colour blue; verify layout.\n' for i in range(1500))
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        long=pool.submit(call,'long-prefill',prompt)
        time.sleep(2)
        short=pool.submit(call,'concurrent-short','Reply with READY.')
        for future in concurrent.futures.as_completed([long,short]):
            result=future.result();results.append(result);print(json.dumps(result),flush=True)
    out=Path('/mnt/xfs/AI_Models/control/arcB70/sycl-prefill-check.json')
    out.write_text(json.dumps({'profile':profile['id'],'results':results},indent=2)+'\n')
    if not all(r.get('produced_tokens') for r in results):raise RuntimeError('prefill/concurrency check failed')


if __name__=='__main__':main()

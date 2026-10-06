#!/usr/bin/env python3
"""Resident-only inference measurements with bounded synthetic workloads."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import statistics
import sys
import time
import urllib.error
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from benchmarks import fixtures


def request_json(url, body=None, timeout=10, key=None):
    headers={'Content-Type':'application/json'}
    if key: headers['Authorization']='Bearer '+key
    request=urllib.request.Request(url,data=None if body is None else json.dumps(body).encode(),headers=headers)
    with urllib.request.urlopen(request,timeout=timeout) as response: return json.load(response)


def resident(base, expected=None, key=None):
    running=request_json(base+'/running',key=key).get('running',[])
    ready=[item for item in running if item.get('state')=='ready']
    if len(running)!=1 or len(ready)!=1: raise RuntimeError('exactly one ready model is required')
    if expected is not None and ready[0]['model']!=expected: raise RuntimeError('resident model changed; refusing inference')
    return ready[0]


def complete(base, payload, timeout=300, key=None):
    headers={'Content-Type':'application/json'}
    if key: headers['Authorization']='Bearer '+key
    start=time.monotonic()
    payload={**payload,'stream':True,'stream_options':{'include_usage':True}}
    request=urllib.request.Request(base+'/v1/chat/completions',data=json.dumps(payload).encode(),headers=headers)
    content=''; reasoning=''; usage={}; timings={}; finish=None; first=None; first_reasoning=None; done=False
    with urllib.request.urlopen(request,timeout=timeout) as response:
        for raw in response:
            if time.monotonic()-start>timeout: raise TimeoutError('benchmark total deadline exceeded')
            line=raw.decode().strip()
            if not line.startswith('data:'): continue
            data=line[5:].strip()
            if data=='[DONE]': done=True;break
            chunk=json.loads(data)
            if chunk.get('usage'): usage=chunk['usage']
            if chunk.get('timings'): timings=chunk['timings']
            for choice in chunk.get('choices',[]):
                delta=choice.get('delta',{})
                if delta.get('content'):
                    if first is None: first=time.monotonic()-start
                    content+=delta['content']
                r=delta.get('reasoning_content') or delta.get('reasoning')
                if r:
                    if first_reasoning is None: first_reasoning=time.monotonic()-start
                    reasoning+=r
                if choice.get('finish_reason'): finish=choice['finish_reason']
    if not done: raise RuntimeError('stream ended without DONE')
    return {'wall_seconds':time.monotonic()-start,'ttft_content_seconds':first,
            'ttft_reasoning_seconds':first_reasoning,'usage':usage,'timings':timings,
            'finish_reason':finish,'response':content}


def checks(case, response):
    if case['kind']=='latency': return {'complete_stream':bool(response)}
    if 'required' in case: return {word:word in response.lower() for word in case['required']}
    text=response.strip()
    if text.startswith('```'): text='\n'.join(text.splitlines()[1:-1])
    try: actual=json.loads(text)
    except ValueError: return {'valid_json':False}
    def normalized(key,value):
        if key=='paid':
            if type(value) is bool:return 'YES' if value else 'NO'
            if isinstance(value,str) and value.strip().upper() in ('YES','NO'):return value.strip().upper()
            return None
        return str(value)
    return {key:normalized(key,actual.get(key))==normalized(key,value) for key,value in case['expected'].items()}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('hardware',choices=['geekom','7900xt','rtx5080'])
    parser.add_argument('--base-url',required=True)
    parser.add_argument('--suite',choices=['latency','vision'],default='latency')
    parser.add_argument('--repeat',type=int,default=5)
    parser.add_argument('--case',help='rerun one fixture by its exact identifier')
    parser.add_argument('--concurrency',type=int,default=1)
    parser.add_argument('--output',required=True)
    parser.add_argument('--max-tokens',type=int,default=256)
    parser.add_argument('--timeout',type=int,default=300)
    args=parser.parse_args()
    hold=ROOT/'.deployment-holds.json'
    if hold.exists() and args.hardware in json.loads(hold.read_text()):
        parser.error('hardware held by user; benchmark load deferred, use read-only telemetry')
    if not (1<=args.repeat<=20 and 1<=args.concurrency<=8 and 32<=args.max_tokens<=1024):
        parser.error('bounded repeats/concurrency/token budget required')
    from shared import modelctl
    modelctl.assert_device_ready(json.loads((ROOT/args.hardware/'models.json').read_text()))
    base=args.base_url.rstrip('/').removesuffix('/v1')
    key=os.environ.get('LARIO_BENCHMARK_KEY')
    before=resident(base,key=key)
    cases=fixtures.text_cases() if args.suite=='latency' else fixtures.vision_cases()
    if args.suite=='vision' and before['model'] not in ('ocr','describe'):
        parser.error('vision suite requires an already resident vision model')
    if args.case:
        cases=[case for case in cases if case['id']==args.case]
        if not cases:parser.error('unknown fixture identifier')
    rows=[]
    def run(case):
        resident(base,before['model'],key)
        content=case['prompt']
        if case.get('images'):
            content=[{'type':'text','text':content}]+[{'type':'image_url','image_url':{'url':url}} for url in case['images']]
        payload={'model':before['model'],'messages':[{'role':'user','content':content}],
                 'max_tokens':args.max_tokens,'temperature':0,'cache_prompt':False,
                 'chat_template_kwargs':{'enable_thinking':False}}
        try:
            result=complete(base,payload,args.timeout,key)
            validation=checks(case,result.pop('response'))
            return {'case':case['id'],'checks':validation,'passed':all(validation.values()),**result}
        except Exception as error:
            return {'case':case['id'],'passed':False,'error_type':type(error).__name__,'http_status':getattr(error,'code',None)}
    for case in cases:
        for iteration in range(args.repeat):
            with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
                batch=list(pool.map(run,[case]*args.concurrency))
            for row in batch: row['iteration']=iteration+1
            rows.extend(batch)
            print(case['id'],iteration+1,sum(row['passed'] for row in batch),'/',len(batch),flush=True)
            result={'schema_version':1,'evaluator_version':2,'fixture_version':fixtures.VERSION,'timestamp_utc':datetime.now(timezone.utc).isoformat(),
                    'hardware':args.hardware,'resident':before,'registry_sha256':hashlib.sha256((ROOT/args.hardware/'models.json').read_bytes()).hexdigest(),
                    'concurrency':args.concurrency,'load_label':'shared-service; external activity not excluded',
                    'cache_prompt':False,'reasoning':False,'rows':rows}
            Path(args.output).parent.mkdir(parents=True,exist_ok=True)
            Path(args.output).write_text(json.dumps(result,indent=2)+'\n')
    if not all(row['passed'] for row in rows): raise SystemExit(1)


if __name__=='__main__': main()

#!/usr/bin/env python3
"""Tool, real OpenCode, RAG and long-context evaluations without model switching."""
import argparse
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import time
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from benchmarks.fixtures import CODING, tools, rag_documents
from benchmarks.run import request_json, resident, complete


def call(base,model,messages,key,**kwargs):
    payload={'model':model,'messages':messages,'temperature':0,'max_tokens':512,
             'chat_template_kwargs':{'enable_thinking':False},**kwargs}
    return request_json(base+'/v1/chat/completions',payload,timeout=300,key=key)


def tool_case(base,model,case,key):
    schema={'type':'function','function':{'name':'add','description':'Add two integers.',
            'parameters':{'type':'object','properties':{'a':{'type':'integer'},'b':{'type':'integer'}},'required':['a','b']}}}
    messages=[{'role':'user','content':f'Use add to calculate {case["a"]} plus {case["b"]}. After the tool returns, report only the number.'}]
    result=call(base,model,messages,key,tools=[schema])
    message=result['choices'][0]['message'];calls=message.get('tool_calls',[])
    valid=len(calls)==1 and calls[0]['function']['name']=='add'
    if valid:
        arguments=json.loads(calls[0]['function']['arguments'])
        valid=arguments=={'a':case['a'],'b':case['b']}
    if not valid:return {'case':case['id'],'passed':False,'checks':{'tool_arguments':False}}
    messages += [message,{'role':'tool','tool_call_id':calls[0]['id'],'content':str(arguments['a']+arguments['b'])}]
    answer=call(base,model,messages,key)['choices'][0]['message'].get('content','')
    return {'case':case['id'],'passed':answer.strip()==str(case['expected']),
            'checks':{'tool_arguments':True,'tool_execution_followup':answer.strip()==str(case['expected'])}}


def coding_case(model_id,case,timeout=600):
    name,source,instruction,checks=case
    with tempfile.TemporaryDirectory(prefix='lario-coding-bench-') as temporary:
        directory=Path(temporary)
        (directory/'solution.py').write_text(source)
        # Tests are owned by the runner. The model may only edit solution.py; it
        # cannot make the benchmark pass by changing expectations or executing shell.
        permission={'*':'deny','execute':'allow','read':{'*':'deny','solution.py':'allow',str(directory/'solution.py'):'allow'},
                    'edit':{'*':'deny','solution.py':'allow',str(directory/'solution.py'):'allow'},'external_directory':{'*':'deny',str(directory)+'/*':'allow'}}
        (directory/'opencode.json').write_text(json.dumps({'permission':permission}))
        process=subprocess.Popen(['opencode','run','--standalone','--auto','--format','json','--model',model_id,
                                  'Only read and edit the exact file '+str(directory/'solution.py')+'. '+instruction+
                                  ' Keep the solve interface. Use Python builtins, re, or collections.Counter only. Do not run shell commands or modify any other file.'],
                                 cwd=directory,env={**os.environ,'OPENCODE_CONFIG':str(directory/'opencode.json')},
                                 stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True,text=True)
        try:
            stdout,stderr=process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid,signal.SIGTERM)
            try:process.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid,signal.SIGKILL);process.communicate()
            return {'case':name,'passed':False,'error_type':'OpenCodeTimeout'}
        descriptor=os.open('/tmp/lario-coding-last-events.jsonl',os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
        with os.fdopen(descriptor,'w') as file:file.write(stdout)
        new_source=(directory/'solution.py').read_text()
        # Evaluate pure functions in a separate process with restricted builtins,
        # restricted pure imports/attributes, no dunder identifiers, files or subprocess API.
        evaluator=Path(__file__).with_name('evaluate.py')
        payload={'source':new_source,'checks':checks,'two_args':name in ('chunks','binary_search'),
                 'invalid_chunk_size':name=='chunks','integer_dict_keys':name=='frequency'}
        result=subprocess.run([sys.executable,str(evaluator)],input=json.dumps(payload),text=True,
                              capture_output=True,timeout=10,cwd=directory)
        evaluation=json.loads(result.stdout) if result.returncode==0 else {'passed':False}
        events=[]
        for line in stdout.splitlines():
            try:events.append(json.loads(line))
            except ValueError:pass
        return {'case':name,'passed':bool(evaluation.get('passed')) and process.returncode==0,
                'source_changed':new_source!=source,'opencode_exit':process.returncode,
                'event_count':len(events),'evaluator_exit':result.returncode,
                'evaluator_error_type':result.stderr.splitlines()[-1].split(':')[0] if result.stderr else None,
                'checks':evaluation.get('checks',[])}


def rag_cases(base,model,key,rag,chroma):
    prefix=chroma+'/api/v2/tenants/default_tenant/databases/default_database/collections'
    name='lario-benchmark-'+uuid.uuid4().hex
    created=request_json(prefix,{'name':name},timeout=60)
    ident=created['id']
    rows=[]
    try:
        docs=rag_documents()
        vectors=request_json(rag+'/embed',{'texts':docs},timeout=120)['embeddings']
        if any(len(v)!=1024 for v in vectors):raise RuntimeError('embedding contract changed')
        request_json(prefix+'/'+ident+'/add',{'ids':[f'unit-{i}' for i in range(10)],'documents':docs,
                     'embeddings':vectors,'metadatas':[{'unit':i,'source':f'UNIT-{i:02d}'} for i in range(10)]},timeout=60)
        for i in range(10):
            hits=request_json(rag+'/retrieve',{'query':f'What recovery code belongs to UNIT-{i:02d}?','collection':name,'top_k':3},timeout=60)['results']
            context='\n'.join(f'Source {h["metadata"]["source"]}: {h["document"]}' for h in hits)
            result=call(base,model,[{'role':'user','content':context+f'\nUsing only these sources, return the recovery code for UNIT-{i:02d}, with its source identifier.'}],key)
            answer=result['choices'][0]['message'].get('content','')
            ranked=bool(hits) and hits[0]['metadata'].get('unit')==i
            supported=f'TOKEN-{i:02d}-SAFE' in answer and f'UNIT-{i:02d}' in answer
            rows.append({'case':f'rag-{i}','passed':ranked and supported,'checks':{'top_document':ranked,'supported_cited_answer':supported}})
    finally:
        request=__import__('urllib.request',fromlist=['Request']).Request(prefix+'/'+name,method='DELETE')
        with __import__('urllib.request',fromlist=['urlopen']).urlopen(request,timeout=60) as response:response.read()
        try:request_json(prefix+'/'+name)
        except __import__('urllib.error',fromlist=['HTTPError']).HTTPError as error:
            if error.code!=404:raise
        else:raise RuntimeError('benchmark collection cleanup was not verified')
    return rows


def long_case(base,model,tokens,key):
    token_url=base+'/upstream/'+model+'/tokenize'
    markers=['ALPHA-2941','MIDDLE-7712','OMEGA-9034']
    suffix='\nReturn exactly the three hidden marker codes in order. Do not omit any.'
    lo,hi=1,tokens
    def prompt(n):
        fill=' synthetic record accepted; no marker here.'
        return markers[0]+fill*(n//2)+' '+markers[1]+fill*(n-n//2)+' '+markers[2]+suffix
    while lo<hi:
        mid=(lo+hi+1)//2
        count=len(request_json(token_url,{'content':prompt(mid),'add_special':True},timeout=30,key=key)['tokens'])
        if count<=tokens:lo=mid
        else:hi=mid-1
    text=prompt(lo)
    count=len(request_json(token_url,{'content':text,'add_special':True},timeout=30,key=key)['tokens'])
    result=complete(base,{'model':model,'messages':[{'role':'user','content':text}],
                         'max_tokens':128,'temperature':0,'cache_prompt':False,'chat_template_kwargs':{'enable_thinking':False}},timeout=1800,key=key)
    answer=result.pop('response');valid=all(marker in answer for marker in markers)
    return {'case':f'long-{tokens}','prompt_text_tokens':count,'passed':valid,'checks':{'three_positions':valid},**result}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('hardware',choices=['geekom','7900xt','rtx5080'])
    parser.add_argument('--base-url',required=True)
    parser.add_argument('--suite',choices=['tools','coding','rag','long'],required=True)
    parser.add_argument('--model-id',help='OpenCode provider/model, required for coding')
    parser.add_argument('--limit',type=int,default=10)
    parser.add_argument('--case',choices=[case[0] for case in CODING],help='single coding case for an affected-case retest')
    parser.add_argument('--input-tokens',type=int,default=8192)
    parser.add_argument('--output',required=True)
    parser.add_argument('--rag-url',default='http://127.0.0.1:8100')
    parser.add_argument('--chroma-url',default='http://127.0.0.1:8000')
    args=parser.parse_args()
    hold=ROOT/'.deployment-holds.json'
    if hold.exists() and args.hardware in json.loads(hold.read_text()):parser.error('user hold: defer benchmark load')
    if not 1<=args.limit<=10:parser.error('limit must be 1–10')
    base=args.base_url.rstrip('/').removesuffix('/v1');key=os.environ.get('LARIO_BENCHMARK_KEY')
    before=resident(base,key=key);rows=[]
    if args.suite=='coding' and args.model_id!=args.hardware+'/'+before['model']:
        parser.error('OpenCode model must match the resident hardware/model')
    if args.suite=='long' and not 4096<=args.input_tokens<=258048:parser.error('bounded input 4096–258048 required')
    if args.suite=='long':
        import shlex
        command=shlex.split(before['cmd']);slots=int(command[command.index('--parallel')+1])
        context=int(command[command.index('-c')+1])//slots
        if args.input_tokens > context-4096:parser.error('input exceeds the resident context with output headroom')
    cases=tools()[:args.limit] if args.suite=='tools' else CODING[:args.limit] if args.suite=='coding' else [None]
    if args.case:
        if args.suite!='coding':parser.error('--case requires the coding suite')
        cases=[case for case in CODING if case[0]==args.case]
    for case in cases:
        resident(base,before['model'],key)
        start=time.monotonic()
        try:
            if args.suite=='tools':result=tool_case(base,before['model'],case,key);rows.append(result)
            elif args.suite=='coding':result=coding_case(args.model_id,case);rows.append(result)
            elif args.suite=='rag':rows=rag_cases(base,before['model'],key,args.rag_url,args.chroma_url)
            else:rows=[long_case(base,before['model'],args.input_tokens,key)]
        except Exception as error:
            rows.append({'case':case['id'] if isinstance(case,dict) else case[0] if case else args.suite,
                         'passed':False,'error_type':type(error).__name__,
                         'http_status':getattr(error,'code',None)})
        rows[-1]['wall_seconds']=time.monotonic()-start
        Path(args.output).parent.mkdir(parents=True,exist_ok=True)
        Path(args.output).write_text(json.dumps({'schema_version':1,'suite':args.suite,'resident':before,
                                               'hardware':args.hardware,'rows':rows},indent=2)+'\n')
        print(args.suite,len(rows),rows[-1]['passed'],flush=True)
    if not all(row['passed'] for row in rows):raise SystemExit(1)


if __name__=='__main__':main()

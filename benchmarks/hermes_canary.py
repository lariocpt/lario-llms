#!/usr/bin/env python3
"""Real Hermes tool canary with disposable state; never resumes the paused fleet."""
import argparse
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from shared import modelctl


def paused_fleet():
    result=subprocess.run(['docker','ps','--format','{{.Names}}'],check=True,capture_output=True,text=True)
    return sorted(name for name in result.stdout.splitlines() if name.startswith('hermes-'))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--option',required=True,choices=['qwen38-flash@balanced','qwen38-flash@flash-128k'])
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    if paused_fleet():raise RuntimeError('canary requires the actual Hermes fleet to remain paused')
    reg=json.loads((ROOT/'geekom/models.json').read_text())
    # Verify remote residency without loading or switching a model.
    from shared.model_tools.model_tools import public_status
    os.environ['LARIO_MODELS_ENDPOINTS']=json.dumps({'geekom':'http://192.168.2.1:11434/v1'})
    before=public_status('geekom')
    key,preset=args.option.split('@')
    spec=modelctl.effective_models(reg,preset)[key]
    live=before.get('resident',{})
    if not before.get('ready') or (live.get('model'),live.get('context'),live.get('slots'))!=(key,spec['context'],spec['slots']):
        raise RuntimeError('requested Geekom profile is not actually resident')
    credentials=json.loads((Path.home()/'.config/lario-admission/fleet-clients.json').read_text())
    consumer_key=credentials['geekom']['apiKey']
    name='lario-hermes-canary-'+uuid.uuid4().hex[:12]
    result={'timestamp_utc':datetime.now(timezone.utc).isoformat(),'scope':'isolated real Hermes CLI; separate temporary state, no live agent mounts',
            'option':args.option,'before':before,'fleet_running_before':[]}
    with tempfile.TemporaryDirectory(prefix='lario-hermes-canary-') as directory:
        private=Path(directory);data=private/'data';workspace=private/'workspace';tools=private/'tools'
        for path in (data,workspace,tools):path.mkdir(mode=0o700)
        marker='HERMES_CANARY_'+uuid.uuid4().hex
        (workspace/'canary.txt').write_text(marker+'\n')
        for source in [ROOT/'shared/model_tools/model_tools.py',ROOT/'shared/model_tools/model_choices.json',ROOT/'intel/tools/intel_tools.py']:
            shutil.copyfile(source,tools/source.name)
        (data/'.env').write_text('OPENAI_API_KEY='+consumer_key+'\n')
        os.chmod(data/'.env',0o600)
        config={'model':{'provider':'custom','base_url':'http://192.168.2.1:11434/v1','default':args.option,
                         'context_length':spec['context']-4096,'max_tokens':4096},
                'memory':{'memory_enabled':False,'user_profile_enabled':False},
                'agent':{'max_turns':8,'verify_on_stop':False,'local_stream_stale_timeout':300},
                'terminal':{'cwd':'/workspace'},
                'mcp_servers':{'lario_models':{'command':'python','args':['/canary-tools/model_tools.py'],
                   'env':{'LARIO_MODELS_ALLOW_SWITCH':'0','LARIO_MODELS_ENDPOINTS':os.environ['LARIO_MODELS_ENDPOINTS']}},
                 'lario_intel':{'command':'python','args':['/canary-tools/intel_tools.py'],'env':{'LARIO_INTEL_HOST':'127.0.0.1'}}}}
        import yaml
        (data/'config.yaml').write_text(yaml.safe_dump(config));os.chmod(data/'config.yaml',0o600)
        prompt='This is a bounded integration check. Read /workspace/canary.txt using read_file, call lario_models model_status for geekom, and call lario_intel intel_health. Include the exact file marker and the active model/context/slots in your final answer. Do not write files or run any other tools.'
        command=['docker','run','--rm','--name',name,'--network','host','--user',str(os.getuid())+':'+str(os.getgid()),
                 '-e','HERMES_HOME=/opt/data','-e','HERMES_SKIP_GATEWAY_CHECK=1','-v',str(data)+':/opt/data',
                 '-v',str(workspace)+':/workspace:ro','-v',str(tools)+':/canary-tools:ro',
                 '--entrypoint','python','lario/hermes-agent:scrape','-m','hermes_cli.main','chat',
                 '--cli','--ignore-rules','--source','tool','-t','file','-Q','--max-turns','8','-q',prompt]
        log=private/'cli.log'
        try:
            with log.open('w') as output:
                completed=subprocess.run(command,stdout=output,stderr=subprocess.STDOUT,timeout=1200)
            result['exit']=completed.returncode
        except subprocess.TimeoutExpired:
            subprocess.run(['docker','stop','--time','30',name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            result['exit']=124
        text=log.read_text(errors='replace')
        result['file_marker_returned']=marker in text
        names=[]
        database=data/'state.db'
        if database.exists():
            with sqlite3.connect('file:'+str(database)+'?mode=ro',uri=True) as db:
                columns={row[1] for row in db.execute('PRAGMA table_info(messages)')}
                if 'tool_name' in columns:
                    names=[row[0] for row in db.execute("SELECT DISTINCT tool_name FROM messages WHERE tool_name IS NOT NULL AND tool_name != ''")]
        result['tool_names']=names
        result['checks']={'read_file':any('read_file' in item for item in names),
                          'model_status':any('model_status' in item for item in names),
                          'intel_health':any('intel_health' in item for item in names)}
        # A failed canary's output is private and only retained locally for diagnosis.
        if result['exit'] or not all(result['checks'].values()) or not result['file_marker_returned']:
            diagnostic=Path('/tmp')/(name+'.log');shutil.copyfile(log,diagnostic);os.chmod(diagnostic,0o600)
            result['private_diagnostic']=str(diagnostic)
    result['fleet_running_after']=paused_fleet()
    result['after']=public_status('geekom')
    fields=('model','context','slots','generation')
    result['resident_unchanged']=all(result['after'].get('resident',{}).get(field)==before.get('resident',{}).get(field) for field in fields)
    result['passed']=result['exit']==0 and result['file_marker_returned'] and all(result['checks'].values()) and not result['fleet_running_after'] and result['resident_unchanged']
    args.output.parent.mkdir(parents=True,exist_ok=True);modelctl.atomic(args.output,json.dumps(result,indent=2)+'\n')
    print(json.dumps(result))
    if not result['passed']:raise SystemExit(1)


if __name__=='__main__':main()

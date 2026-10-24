#!/usr/bin/env python3
"""Export consumer-safe choices from authoritative hardware registries."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from shared import modelctl
from shared.serving.catalog import profiles, public, opencode


def export():
    hardware={}
    for name in ('geekom','geekom7900xt','rtx5080','rtx3060ti'):
        path=ROOT/name/'models.json';reg=json.loads(path.read_text());options=[]
        for number,p in enumerate(profiles(reg).values(),1):
            options.append({**public(p),'number':number,
                'fleet_capacity':modelctl.fleet_capacity(p['slots'],p['reserved'],p['context']),
                'kv_device':'CPU' if '--no-kv-offload' in p['spec']['args'] else 'GPU'})
        hardware[name]={'owner':reg['host'],'public_port':reg['port'],
            'registry_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'options':options,
            'disabled_presets':{key:spec['disabled_reason'] for key,spec in reg.get('presets',{}).items() if spec.get('disabled_reason')}}
    reg=json.loads((ROOT/'arcB70/models.json').read_text())
    options=[{**public(p),'number':number,'fleet_capacity':0,
                    'native_context':p['spec']['native_context'],'quality_validated':False,
                    'enabled':p['model'] in reg.get('enabled_models',[]),
                    'memory_estimate':p['spec']['memory_estimate'],
                    'kv_device':'CPU' if '--no-kv-offload' in p['spec']['args'] else 'GPU'}
                   for number,p in enumerate(profiles(reg).values(),1)]
    arc={'owner':reg['host'],'public_port':reg['port'],'status':reg['deployment_status'],
         'disabled':not bool(reg.get('enabled_models')),'switching_available':False,
         'options':options,'disabled_presets':{}}
    if reg.get('enabled_models'):
        hardware['arcB70']=arc;prepared={}
    else:
        prepared={'arcB70':{**arc,'ready':False,'fleet_capacity':0}}
    return {'schema_version':2,'generated_from':'lario-llms hardware models.json; do not hand-edit',
            'hardware':hardware,'prepared':prepared}


def export_opencode_profiles():
    """Export the same fixed entries as every managed OpenCode client."""
    return opencode()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=Path(__file__).with_name('model_choices.json'))
    parser.add_argument('--opencode-output',type=Path,
                        default=Path(__file__).with_name('opencode_profile_models.json'))
    args=parser.parse_args();args.output.write_text(json.dumps(export(),indent=2)+'\n')
    args.opencode_output.write_text(json.dumps(export_opencode_profiles(),indent=2)+'\n')

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


def export():
    hardware={}
    for name in ('geekom','7900xt','rtx5080'):
        path=ROOT/name/'models.json';reg=json.loads(path.read_text());options=[]
        for number,(model,preset) in enumerate(modelctl.selection_options(reg),1):
            effective=modelctl.effective_models(reg,preset)[model]
            options.append({'number':number,'id':model+'@'+preset,'model':model,'preset':preset,
                'context':effective['context'],'slots':effective['slots'],'reserved':effective['reserved'],
                'fleet_capacity':modelctl.fleet_capacity(effective['slots'],effective['reserved'],effective['context']),
                'kv_device':'CPU' if '--no-kv-offload' in effective['args'] else 'GPU',
                'experimental':bool(reg.get('presets',{}).get(preset,{}).get('experimental'))})
        hardware[name]={'owner':reg['host'],'public_port':reg['port'],
            'registry_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'options':options,
            'disabled_presets':{key:spec['disabled_reason'] for key,spec in reg.get('presets',{}).items() if spec.get('disabled_reason')}}
    return {'schema_version':1,'generated_from':'lario-llms hardware models.json; do not hand-edit','hardware':hardware}


def export_opencode_profiles():
    """Exact-window alternatives to hardware aliases with conservative limits."""
    wanted = {
        'geekom': {('qwen38-flash','balanced'), ('qwen38-flash','flash-128k')},
        '7900xt': {('qwen3.8','fast-64k'), ('qwen3.8','fast-128k')},
        'rtx5080': {('qwen3.8','fast-64k')},
    }
    providers = {}
    for hardware, options in wanted.items():
        reg = json.loads((ROOT/hardware/'models.json').read_text())
        models = {}
        for model, preset in modelctl.selection_options(reg):
            if (model,preset) not in options:continue
            spec = modelctl.effective_models(reg,preset)[model]
            label = 'Qwen3.8 Flash Next' if model == 'qwen38-flash' else 'Qwen3.8 Q3'
            models[model+'@'+preset] = {
                'name': f'{label} — {spec["context"]} tokens / {spec["slots"]} slots',
                'tool_call': True,
                'limit': {'context':spec['context']-4096,'output':8192},
                'modalities': {'input':['text'],'output':['text']},
            }
        providers[hardware] = {'models':models}
    return {'provider':providers}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=Path(__file__).with_name('model_choices.json'))
    parser.add_argument('--opencode-output',type=Path,
                        default=Path(__file__).with_name('opencode_profile_models.json'))
    args=parser.parse_args();args.output.write_text(json.dumps(export(),indent=2)+'\n')
    args.opencode_output.write_text(json.dumps(export_opencode_profiles(),indent=2)+'\n')

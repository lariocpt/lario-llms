#!/usr/bin/env python3
"""JSON-over-stdin model operations on the owner; uses its existing controller/keys."""
import contextlib
import fcntl
import hashlib
import io
import json
from pathlib import Path
import socket
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from shared import modelctl
from shared.model_tools.export_choices import export


def status(reg):
    modelctl.load_runtime(reg)
    selected,preset=modelctl.selection(reg)
    result={'hardware':reg['aliases'][0],'owner':reg['host'],
            'alias_target':{'model':selected,'preset':preset},'transport':'owner-controller'}
    try:
        modelctl.assert_device_ready(reg)
        live=modelctl.runtime_budget(reg)
        result['resident']=live
        items=modelctl.api(reg,'/running')['running']
        if len(items)!=1 or items[0].get('model')!=live['model'] or items[0].get('state')!='ready':
            raise RuntimeError('resident changed during inspection')
        result.update(ready=True,alias_matches_resident=selected==live['model'],processing_slots=None)
        slots=modelctl.resident_slots(reg,items[0])
        if not isinstance(slots,list) or len(slots)!=live['slots'] or any(type(s.get('is_processing')) is not bool for s in slots):
            raise RuntimeError('unknown inference occupancy')
        result.update(ready=True,processing_slots=sum(s['is_processing'] for s in slots))
        fingerprint={'selection':result['alias_target'],'resident':live,
                     'registry_sha256':hashlib.sha256((ROOT/reg['aliases'][0]/'models.json').read_bytes()).hexdigest()}
        result['switch_token']=hashlib.sha256(json.dumps(fingerprint,sort_keys=True).encode()).hexdigest()
    except (OSError,ValueError,KeyError,RuntimeError) as exc:
        # llama-swap can rate-limit the monitoring route while its sole slot is
        # busy. Preserve verified residency; never invent an idle/switchable slot.
        if not isinstance(exc,modelctl.urllib.error.HTTPError) or exc.code!=429:
            result['ready']=False
        result.update(error_type=type(exc).__name__,detail=str(exc)[:500])
    return result


def operate(request):
    if not isinstance(request,dict) or set(request)-{'operation','hardware','option','switch_token','allow_experimental'}:
        raise ValueError('invalid owner request')
    hardware=request.get('hardware')
    if hardware not in ('geekom','7900xt','rtx5080'):raise ValueError('unknown hardware')
    reg=json.loads((ROOT/hardware/'models.json').read_text())
    if socket.gethostname().split('.')[0]!=reg['host']:raise RuntimeError('operation must run on the hardware owner')
    operation=request.get('operation')
    if operation=='status':return status(reg)
    if operation=='options':return export()['hardware'][hardware]
    if operation!='switch':raise ValueError('unknown owner operation')
    option=request.get('option')
    if not isinstance(option,str) or len(option)>100:raise ValueError('invalid model option')
    key,preset=modelctl.resolve_option(reg,option)
    if preset is None or (key,preset) not in modelctl.selection_options(reg):
        raise ValueError('use an explicit model@preset from model_options')
    allow=request.get('allow_experimental',False)
    if type(allow) is not bool:raise ValueError('allow_experimental must be boolean')
    if reg.get('presets',{}).get(preset,{}).get('experimental') and not allow:
        raise RuntimeError('experimental preset requires explicit allow_experimental=true')
    token=request.get('switch_token')
    if not isinstance(token,str) or len(token)!=64:raise ValueError('fresh model_status switch_token required')
    with (ROOT/('.'+hardware+'.lock')).open('w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        before=status(reg)
        if not before.get('ready') or not before.get('switch_token'):
            raise RuntimeError('hardware is busy or readiness/occupancy is unverified; switching refused')
        if token!=before.get('switch_token'):raise RuntimeError('selection or residency changed; get fresh model_status')
        modelctl.assert_not_held(reg)
        modelctl.assert_device_ready(reg)
        modelctl.assert_idle(reg)
        effective=modelctl.effective_models(reg,preset)[key]
        admission=__import__('os').environ.get('LARIO_ADMISSION_ENABLED')=='1'
        config=ROOT/reg['config']
        configuration_current=config.exists() and config.read_text()==modelctl.render(reg,key,preset,admission)
        if (before['alias_target']=={'model':key,'preset':preset} and before['resident']['model']==key
            and before['resident']['context']==effective['context'] and before['resident']['slots']==effective['slots']
            and configuration_current):
            return {'changed':False,'status':before}
        with contextlib.redirect_stdout(io.StringIO()):
            modelctl.switch(reg,key,preset,admission)
        return {'changed':True,'status':status(reg)}


if __name__=='__main__':
    try:result=operate(json.load(sys.stdin))
    except Exception as exc:
        print(json.dumps({'error':{'type':type(exc).__name__,'message':str(exc)[:500]}}));sys.exit(1)
    print(json.dumps(result))

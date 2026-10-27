"""Add the exclusive native Strata/HIP Halo placement without rewriting older profiles."""
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
MODEL='qwen38-flash-strata'
POOL='flash-strata-q3-kv4'


def install(reg):
    reg['models']['qwen38-flash']['client_visible']=False
    excluded=reg['presets']['capacity'].setdefault('exclude_models',[])
    if MODEL not in excluded:
        excluded.append(MODEL)
    reg['models'][MODEL]={
        'context':262144,'slots':4,'reserved':0,'aliases':[],
        'display_name':'Qwen3.8 Flash Next Strata','experimental':True,
        'omit_provisional_label':True,
        'validation':'four-native-256k-slots-and-public-gateway-smoke-verified; full-context-quality-pending',
        'native_context':262144,'shared_pool':POOL,'extra_args':[],
        'binary':str(ROOT/'geekom/strata/llama-compat'),
        'args':['-m','/mnt/AI_Models/gguf/qwen38-flash/Qwen3.8-Flash-Next-UD-Q3_K_XL-00001-of-00003.gguf',
                '-ctk','q4_0','-ctv','q4_0'],
        'weights':{'bytes':89986353824,'quantization':'UD-Q3_K_XL'},
        'engine':'strata-hip-halo',
    }
    reg['shared_serving']['pools'][POOL]={
        'context_tokens':1048576,'max_context':262144,'min_context':262144,
        'slots':4,'reserved':0,'exclusive':True,'runtime_args':[],
        'clear_idle_kv_on_admission':False,'preserve_prompt_cache':True,'template_tokens':True,
        'kv_bytes_per_token':8704,
    }
    reg['presets']['flash-strata-256k']={
        'description':'Strata HIP Halo; Q3 weights, KV4, four independent native 256K contexts',
        'models':{MODEL:{}},'experimental':True,
    }
    return reg


if __name__=='__main__':
    path=ROOT/'geekom/models.json'
    path.write_text(json.dumps(install(json.loads(path.read_text())),indent=2)+'\n')

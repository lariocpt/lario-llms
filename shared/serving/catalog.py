"""Compile immutable, device-qualified model profiles from the owner registries."""
import hashlib
import json
from pathlib import Path
import re
import shlex

from shared import modelctl

ROOT = Path(__file__).resolve().parents[2]
HARDWARE = ('geekom', '7900xt', 'rtx5080')
LABELS = {'geekom': 'Geekom', '7900xt': 'Radeon 7900 XT', 'rtx5080': 'RTX 5080'}


def argument(args, flag, default=None):
    return args[args.index(flag)+1] if flag in args else default


def profiles(reg):
    hardware = reg['aliases'][0]
    result = {}
    for model, preset in modelctl.selection_options(reg):
        spec = modelctl.effective_models(reg, preset)[model]
        args = spec.get('extra_args', reg.get('extra_args', [])) + spec['args']
        k, v = argument(args, '-ctk', 'f16'), argument(args, '-ctv', 'f16')
        identity = {'hardware': hardware, 'model': model, 'preset': preset,
                    'context': spec['context'], 'slots': spec['slots'], 'reserved': spec['reserved'],
                    'args': args, 'binary': reg['binary'], 'image': reg.get('image')}
        revision = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        safe = re.sub(r'[^a-z0-9.-]', '-', model.lower())
        key = f'{hardware}.{safe}.c{spec["context"]}.k{k}-v{v}.s{spec["slots"]}.{preset}.{revision[:10]}'
        weight = Path(argument(args, '-m', '')).name
        quant = re.search(r'(?:UD-)?(Q\d[^.]*?)(?:-\d{5}-of-\d{5})?\.gguf$', weight, re.I)
        quant = quant.group(1) if quant else 'registered weights'
        names = {'qwen3.8-smart': 'Qwen3.8 Smart', 'qwen3.8-smart-128k': 'Qwen3.8 Smart',
                 'qwen3.8-medium': 'Qwen3.8 Medium', 'qwen3.8-medium-128k': 'Qwen3.8 Medium',
                 'qwen38-flash': 'Qwen3.8 Flash Next', 'qwen3.8': 'Qwen3.8',
                 'muse-glimmer': 'Muse Glimmer', 'muse-glimmer-dflash': 'Muse Glimmer DFlash',
                 'ocr': 'Qwen3-VL OCR / comparison', 'describe': 'Qwen3-VL description'}
        precision = k.replace('q', 'KV').replace('_0', '') if k == v and k.startswith('q') else f'K:{k}/V:{v}'
        suffix = ' [provisional]' if modelctl.is_experimental(reg, model, preset) else ''
        context_k = f'{spec["context"]/1024:g}k'
        slots_label = 'slot' if spec['slots'] == 1 else 'slots'
        label = reg.get('display_name') or LABELS[hardware]
        name = (f'{label} - {context_k} {spec["slots"]} {slots_label} - '
                f'{names.get(model, model)} · {precision} · {quant} · {preset}{suffix}')
        result[key] = {'id': key, 'hardware': hardware, 'owner': reg['host'], 'model': model,
                       'preset': preset, 'context': spec['context'], 'slots': spec['slots'],
                       'reserved': spec['reserved'], 'cache_k': k, 'cache_v': v,
                       'revision': revision, 'name': name, 'weight_quantization': quant,
                       'vision': bool(spec.get('vision')), 'experimental': bool(suffix),
                       'spec': spec}
    return result


def public(profile):
    return {k: v for k, v in profile.items() if k != 'spec'}


def catalog():
    return {'schema_version': 2, 'profiles': [public(p) for h in HARDWARE
            for p in profiles(json.loads((ROOT/h/'models.json').read_text())).values()]}


def legacy_routes(reg, selected, preset):
    """Explicit compatibility pins; never infer their geometry from later residency."""
    entries = profiles(reg)
    routes = {}
    for model in reg['models']:
        candidates = [p for p in entries.values() if p['model'] == model]
        if not candidates:
            continue
        chosen = next((p for p in candidates if p['preset'] == preset), candidates[0])
        routes[model] = chosen['id']
        routes.update({a: chosen['id'] for a in reg['models'][model].get('aliases', [])})
    for p in entries.values():
        routes[p['model']+'@'+p['preset']] = p['id']
    chosen = next((p for p in entries.values() if p['model'] == selected and p['preset'] == preset), None)
    if chosen:
        routes.update({a: chosen['id'] for a in reg['aliases']})
    return routes


def render_backend(reg):
    """All immutable profiles share one exclusive llama-swap resource group."""
    entries = profiles(reg)
    lines = ['# GENERATED fixed profiles; edit hardware models.json',
             'apiKeys: ["${env.LARIO_BACKEND_KEY}"]', 'healthCheckTimeout: 1800',
             'logLevel: info', 'models:']
    for key, p in entries.items():
        spec = p['spec']
        args = [reg['binary'], '--host', '127.0.0.1', '--port', '${PORT}', '-fa', 'on', '--jinja',
                *spec.get('extra_args', reg.get('extra_args', [])), *spec['args'],
                '-c', str(p['context']*p['slots']), '--parallel', str(p['slots']),
                '--api-key-file', reg['backend_key_file']]
        lines += [f'  {json.dumps(key)}:', '    cmd: |', '      '+shlex.join(args),
                  '    ttl: 0', f'    concurrencyLimit: {p["slots"]}']
    lines += ['groups:', '  hardware:', '    swap: true', '    exclusive: true',
              '    members: '+json.dumps(list(entries))]
    return '\n'.join(lines)+'\n'


def opencode():
    providers = {}
    for h in HARDWARE:
        reg = json.loads((ROOT/h/'models.json').read_text())
        models = {}
        for key, p in profiles(reg).items():
            models[key] = {'name': p['name'], 'tool_call': True,
                           'limit': {'context': p['context']-4096, 'output': 8192},
                           'modalities': {'input': ['text', 'image'] if p['vision'] else ['text'],
                                          'output': ['text']}}
        providers[h] = {'models': models}
    return {'provider': providers}


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--hardware', choices=HARDWARE)
    parser.add_argument('--opencode', action='store_true')
    args = parser.parse_args()
    if args.hardware:
        print(render_backend(json.loads((ROOT/args.hardware/'models.json').read_text())), end='')
    else:
        print(json.dumps(opencode() if args.opencode else catalog(), indent=2))

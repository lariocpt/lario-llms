"""Compile immutable, device-qualified model profiles from the owner registries."""
import hashlib
import json
from pathlib import Path
import re
import shlex

from shared import modelctl

ROOT = Path(__file__).resolve().parents[2]
HARDWARE = ('geekom', 'geekom7900xt', 'rtx5080', 'rtx3060ti')
OWNER_HARDWARE = (*HARDWARE, 'arcB70')
LABELS = {'geekom': 'gkm', 'geekom7900xt': 'rdn xt', 'rtx5080': 'gfc rtx', 'rtx3060ti': 'gfc ti'}


def compact_hardware_name(name):
    return {'Geekom': 'gkm', 'Radeon 7900 XT': 'rdn xt', 'RTX 5080': 'gfc rtx',
            'Arc B70': 'b70', 'Intel': 'intel', 'Geekom RX 7900 XT': 'gkm rdn xt',
            'Win Max RX 7900 XT': 'winmax rdn xt'}.get(name, name)


def compact_model_name(name):
    """Presentation only: keep immutable routing and geometry unchanged."""
    for pattern, replacement in ((r'\bMuse Glimmer DFlash\b', 'MGlim Flsh'),
                                 (r'\bMuse Glimmer\b', 'MGlim'),
                                 (r'\bFlash Next\b', 'FN'),
                                 (r'\bmedium\b', 'md'), (r'\bsmart\b', 'smrt'),
                                 (r'\bqwen', 'qw')):
        name = re.sub(pattern, replacement, name, flags=re.I)
    return name


def argument(args, flag, default=None):
    return args[args.index(flag)+1] if flag in args else default


def profiles(reg):
    hardware = reg['aliases'][0]
    result = {}
    for model, preset in modelctl.selection_options(reg, include_aliases=True):
        spec = modelctl.effective_models(reg, preset)[model]
        args = spec.get('extra_args', reg.get('extra_args', [])) + spec['args']
        k, v = argument(args, '-ctk', 'f16'), argument(args, '-ctv', 'f16')
        identity = {'hardware': hardware, 'model': model, 'preset': preset,
                    'context': spec['context'], 'slots': spec['slots'], 'reserved': spec['reserved'],
                    'args': args, 'binary': spec.get('binary', reg['binary']), 'image': reg.get('image')}
        pool = reg.get('shared_serving', {}).get('pools', {}).get(spec.get('shared_pool'))
        if pool:
            identity['shared_pool'] = pool
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
        precision = k.replace('q', 'kv').replace('_0', '') if k == v and k.startswith('q') else f'K:{k}/V:{v}'
        experimental = modelctl.is_experimental(reg, model, preset)
        prefix = 'provisional-' if experimental and not spec.get('omit_provisional_label', False) else ''
        context_k = f'{spec["context"]/1024:g}k'
        label = compact_hardware_name(reg.get('display_name') or LABELS[hardware])
        model_name = compact_model_name(spec.get('display_name') or names.get(model, model))
        compact_quant = re.match(r'Q\d+', quant, re.I)
        compact_quant = compact_quant.group().upper() if compact_quant else quant
        name = (f'{prefix}{label}-{context_k} {spec["slots"]}slt-'
                f'{model_name} {compact_quant} {precision}')
        if pool:
            name = f'{prefix}{label}-{context_k} shared-{model_name} {compact_quant} {precision}'
            if preset == 'balanced':
                name += ' (balanced alias)'
        result[key] = {'id': key, 'hardware': hardware, 'owner': reg['host'], 'model': model,
                       'preset': preset, 'context': spec['context'], 'slots': spec['slots'],
                       'reserved': spec['reserved'], 'cache_k': k, 'cache_v': v,
                       'revision': revision, 'name': name, 'weight_quantization': quant,
                       'vision': bool(spec.get('vision')), 'experimental': experimental,
                       'spec': spec}
        if pool:
            result[key].update(shared_pool=spec['shared_pool'], pool_context=pool['context_tokens'],
                               pool_slots=pool['slots'], reasoning_effort=json.loads(
                                   argument(args, '--chat-template-kwargs', '{}')).get('reasoning_effort'))
            if pool.get('exclusive'):
                result[key]['pool_exclusive'] = True
    if reg.get('shared_serving'):
        from shared.serving.pools import attach_backends
        attach_backends(reg, result)
        canonical = {}
        for p in result.values():
            if not p.get('shared_pool'):
                continue
            signature = (p['backend_id'], p['context'], p['reasoning_effort'])
            prior = canonical.setdefault(signature, p['id'])
            if prior != p['id']:
                p['alias_of'] = prior
        for p in result.values():
            if p['preset']=='balanced' and not p.get('alias_of'):
                replacement=next((v for v in result.values() if v['model']==p['model']
                                  and v['context']==p['context'] and v['preset']=='capacity'),None)
                if replacement:
                    p['alias_of']=replacement['id']
    return result


def visible_profiles(reg):
    return {key:p for key,p in profiles(reg).items() if not p.get('alias_of')}


def public(profile):
    return {k: v for k, v in profile.items() if k != 'spec'}


def catalog():
    return {'schema_version': 2, 'profiles': [public(p) for h in HARDWARE
            for p in visible_profiles(json.loads((ROOT/h/'models.json').read_text())).values()]}


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
    if reg.get('shared_serving'):
        from shared.serving.pools import render_pools
        return render_pools(reg, entries)
    lines = ['# GENERATED fixed profiles; edit hardware models.json',
             'apiKeys: ["${env.LARIO_BACKEND_KEY}"]', 'healthCheckTimeout: 1800',
             'logLevel: info', 'models:']
    for key, p in entries.items():
        spec = p['spec']
        args = [reg['binary'], '--host', '127.0.0.1', '--port', '${PORT}', '-fa', 'on', '--jinja',
                *spec.get('extra_args', reg.get('extra_args', [])), *spec['args'],
                '-c', str(p['context']*p['slots']), '--parallel', str(p['slots']),
                '--api-key-file', reg['backend_key_file']]
        lines += [f'  {json.dumps(key)}:', '    proxy: http://127.0.0.1:${PORT}', '    cmd: |', '      '+shlex.join(args),
                  '    ttl: 0', f'    concurrencyLimit: {p["slots"]}']
    lines += ['groups:', '  hardware:', '    swap: true', '    exclusive: true',
              '    members: '+json.dumps(list(entries))]
    return '\n'.join(lines)+'\n'


def opencode():
    providers = {}
    for h in HARDWARE:
        reg = json.loads((ROOT/h/'models.json').read_text())
        models = {}
        for key, p in visible_profiles(reg).items():
            if not p['spec'].get('client_visible', True):
                continue
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

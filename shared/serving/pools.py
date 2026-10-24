"""Compile one resident backend per compatible weight/cache configuration."""
import hashlib
import json
import shlex


def runtime_args(reg, profile):
    spec = profile['spec']
    args = list(spec.get('extra_args', reg.get('extra_args', []))) + list(spec['args'])
    if profile.get('shared_pool'):
        # Thinking effort belongs to the request, while context extension and
        # cache precision belong to the one shared process.
        for flag in ('--chat-template-kwargs', '--rope-scaling', '--rope-scale', '--yarn-orig-ctx'):
            while flag in args:
                i = args.index(flag)
                del args[i:i+2]
        args += reg['shared_serving']['pools'][profile['shared_pool']]['runtime_args']
        if '--fit' not in args:
            args += ['--fit', 'off']
        args += ['--kv-unified', '--no-context-shift']
    return args


def attach_backends(reg, entries):
    signatures = {}
    for p in entries.values():
        name = p.get('shared_pool')
        if not name:
            p['backend_id'] = p['id']
            continue
        pool = reg['shared_serving']['pools'][name]
        if (not 4096 < p['context'] <= pool['max_context'] <= pool['context_tokens']
                or pool['slots'] < 1 or not 0 <= pool['reserved'] <= pool['slots']
                or pool['allocation_gib'] <= 0):
            raise ValueError('invalid shared pool geometry')
        signature = json.dumps({'args':runtime_args(reg, p), 'pool':pool,
                                'binary':reg['binary']}, sort_keys=True)
        if name in signatures and signatures[name] != signature:
            raise ValueError('shared pool requires identical weights and runtime arguments')
        signatures[name] = signature
        digest = hashlib.sha256(signature.encode()).hexdigest()[:12]
        p['backend_id'] = f'{p["hardware"]}.pool.{name}.{digest}'
        p['allocation_gib'] = pool['allocation_gib']


def backends(reg, entries):
    result = {}
    for p in entries.values():
        pool = reg['shared_serving']['pools'].get(p.get('shared_pool'))
        result.setdefault(p['backend_id'], {
            'id':p['backend_id'], 'profile':p,
            'context_tokens':pool['context_tokens'] if pool else p['context']*p['slots'],
            'context_ceiling':pool['context_tokens'] if pool else p['context']*p['slots'],
            'slots':pool['slots'] if pool else p['slots'],
            'reserved':pool['reserved'] if pool else p['reserved'],
            'allocation_gib':pool['allocation_gib'] if pool else None,
            'args':runtime_args(reg, p)})
    return result


def render_pools(reg, entries):
    runtime = backends(reg, entries)
    lines = ['# GENERATED shared backends; owner gateway enforces memory admission',
             'apiKeys: ["${env.LARIO_BACKEND_KEY}"]', 'healthCheckTimeout: 1800',
             'logLevel: info', 'models:']
    for key, b in runtime.items():
        args = [reg['binary'], '--host', '127.0.0.1', '--port', '${PORT}', '-fa', 'on',
                '--jinja', *b['args'], '-c', str(b['context_tokens']), '--parallel', str(b['slots']),
                '--api-key-file', reg['backend_key_file']]
        if b['profile'].get('shared_pool'):
            from shared import modelctl
            args = ['/usr/bin/python3', str(modelctl.ROOT/'shared/serving/headroom.py'),
                    '--hardware',reg['aliases'][0], '--backend',key, '--', *args]
        lines += [f'  {json.dumps(key)}:', '    cmd: |', '      '+shlex.join(args),
                  '    ttl: 0', f'    concurrencyLimit: {b["slots"]}']
    # Never let the backend silently evict a different resident model. Owners
    # either reserve its full allocation or refuse the load.
    lines += ['groups:', '  hardware:', '    swap: false', '    exclusive: false',
              '    members: '+json.dumps(list(runtime))]
    return '\n'.join(lines)+'\n'

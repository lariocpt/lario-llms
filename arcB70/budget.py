"""Rebuild Arc Q4 profiles from pinned weights and explicit cache geometry.

Run: python -m arcB70.budget --write; python -m shared.placements
Allocation estimates are not hardware, long-context quality or throughput validation.
"""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
GIB = 2**30
VRAM = 32
RESERVE = 3.5
Q4_BYTES = 18 / 32  # q4_0 block: 16 packed bytes + 2-byte scale per 32 values
STEP = 32768
UBATCH = 256
WEIGHTS = json.loads((ROOT / 'weights.json').read_text())


def qwen_cache(context, slots):
    return context * slots * 17 * 4 * 512 * Q4_BYTES / GIB


def muse_cache(context, slots):
    # Actual GGUF: 13 full / 39 sliding target layers, 2 KV heads, K/V dim 128.
    # Drafter: five sliding layers, eight KV heads, K/V dim 128. No --swa-full.
    # Separate per-sequence SWA buffers: window 2048 + bounded ubatch 256.
    full = context * 13 * 2 * 256 * Q4_BYTES
    target_swa = (2048 + UBATCH) * 39 * 2 * 256 * Q4_BYTES
    draft_swa = (2048 + UBATCH) * 5 * 8 * 256 * Q4_BYTES
    return slots * (full + target_swa + draft_swa) / GIB


def estimate(family, context, slots, cpu_cache=False):
    weight = WEIGHTS['qwen']['bytes'] if family == 'qwen' else WEIGHTS['muse']['bytes'] + WEIGHTS['draft']['bytes']
    cache = (qwen_cache if family == 'qwen' else muse_cache)(context, slots)
    return {'weight_gib': weight / GIB, 'attention_cache_gib': cache,
            'cache_device': 'CPU' if cpu_cache else 'GPU',
            'runtime_reserve_gib': RESERVE, 'vram_budget_gib': VRAM,
            'estimated_vram_with_reserve_gib': weight / GIB + RESERVE + (0 if cpu_cache else cache)}


def max_slots(family, context):
    slots = 1
    while estimate(family, context, slots + 1)['estimated_vram_with_reserve_gib'] <= VRAM:
        slots += 1
    if estimate(family, context, slots)['estimated_vram_with_reserve_gib'] > VRAM:
        raise ValueError('one slot does not fit')
    return slots


def max_context(family, slots=1):
    context = STEP
    while estimate(family, context + STEP, slots)['estimated_vram_with_reserve_gib'] <= VRAM:
        context += STEP
    return context


def args_for(family, context, reasoning=None, cpu_cache=False):
    filename = WEIGHTS['qwen' if family == 'qwen' else 'muse']['filename']
    folder = 'qwen3.8' if family == 'qwen' else 'muse-glimmer'
    args = ['-m', f'/mnt/xfs/AI_Models/gguf/{folder}/{filename}', '-ngl', '999',
            '-ctk', 'q4_0', '-ctv', 'q4_0', '--cache-ram', '0', '--reasoning-budget', '2048',
            '-b', '1024', '-ub', str(UBATCH), '--temp', '1.0', '--top-p', '0.95',
            '--top-k', '20', '--min-p', '0.0', '--fit', 'off']
    native = 262144 if family == 'qwen' else 131072
    if family == 'qwen':
        args += ['--chat-template-kwargs', json.dumps({'reasoning_effort': reasoning}, separators=(',', ':'))]
    else:
        args += ['--chat-template-kwargs', '{"reasoning_strength":"high"}',
                 '-md', '/mnt/xfs/AI_Models/gguf/muse-glimmer/' + WEIGHTS['draft']['filename'],
                 '--spec-type', 'draft-dflash', '--spec-draft-n-max', '15',
                 '--spec-draft-ngl', 'all', '--spec-draft-n-ubatch', str(UBATCH),
                 '-ctkd', 'q4_0', '-ctvd', 'q4_0']
    if context > native:
        # v0.7.0 applies explicit YaRN to both target and draft and updates the
        # server's context cap. Do not modify the downloaded GGUF metadata.
        args += ['--rope-scaling', 'yarn', '--rope-scale', str(context / native),
                 '--yarn-orig-ctx', str(native)]
    if cpu_cache:
        args += ['--no-kv-offload']
    return args


def build_registry():
    reg = json.loads((ROOT / 'models.json').read_text())
    models = {}
    for role, effort in [('smart-q4', 'xhigh'), ('medium', 'medium')]:
        for context in (131072, 262144, 524288, max_context('qwen')):
            key = f'qwen3.8-{role}-{context // 1024}k'
            models[key] = {'context': context, 'slots': max_slots('qwen', context), 'reserved': 0,
                'aliases': [], 'display_name': 'qwen3.8 ' + ('smrt' if role == 'smart-q4' else 'md'),
                'args': args_for('qwen', context, effort), 'experimental': False,
                'validation': 'calculated-only-awaiting-arc-hardware',
                'native_context': 262144, 'memory_estimate': estimate('qwen', context, max_slots('qwen', context)),
                'weights': WEIGHTS['qwen']}
        key = f'qwen3.8-{role}-512k-ram-kv'
        models[key] = {'context': 524288, 'slots': 2, 'reserved': 0, 'aliases': [],
            'display_name': 'qwen3.8 ' + ('smrt' if role == 'smart-q4' else 'md') + ' · RAM KV',
            'args': args_for('qwen', 524288, effort, True), 'experimental': True,
            'validation': 'calculated-only-awaiting-arc-hardware', 'native_context': 262144,
            'memory_estimate': estimate('qwen', 524288, 2, True), 'weights': WEIGHTS['qwen']}
    for context, slots in [(262144, max_slots('muse', 262144)),
                           (524288, max_slots('muse', 524288)), (max_context('muse', 2), 2)]:
        key = f'muse-glimmer-dflash-{context // 1024}k'
        models[key] = {'context': context, 'slots': slots, 'reserved': 0, 'aliases': [],
            'display_name': 'Muse Glimmer DFlash', 'args': args_for('muse', context),
            'experimental': False, 'validation': 'calculated-only-awaiting-arc-hardware',
            'native_context': 131072, 'memory_estimate': estimate('muse', context, slots),
            'weights': WEIGHTS['muse'], 'draft_weights': WEIGHTS['draft']}
    reg['models'] = models
    for spec in models.values():
        if (reg.get('shared_serving') and spec.get('weights') == WEIGHTS['qwen']
                and spec['context'] <= 524288 and '--no-kv-offload' not in spec['args']):
            spec['shared_pool'] = 'qwen-q4'
    reg['presets'] = {'prepared': {'description': 'Q4 weights and target/draft Q4 KV; calculated only, not deployed',
                                   'models': {key: {'experimental': spec['experimental']} for key, spec in models.items()},
                                   'experimental': False}}
    return reg


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write', action='store_true')
    options = parser.parse_args()
    text = json.dumps(build_registry(), indent=2) + '\n'
    if options.write:
        (ROOT / 'models.json').write_text(text)
    else:
        print(text, end='')

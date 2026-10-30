"""Candidate CUDA Strata profile; installation never implies validation."""
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]

def model_spec():
    return {
        'context': 131072, 'slots': 1, 'reserved': 0, 'aliases': [],
        'display_name': 'Qwen3.8 Flash Next', 'weight_quantization': 'NVFP4', 'omit_provisional_label': True, 'vision': True,
        'allow_interactive': True, 'experimental': True,
        'validation': 'pending-native-context-and-quality-validation',
        'binary': str(ROOT / 'rtx5080/strata/llama-compat'),
        'args': ['-m', '/mnt/xfs/AI_Models/strata/models/qwen38-flash-next-nvfp4-gptq/qwen-nvfp4-gptq-dense.gguf',
                 '-ctk', 'q4_0', '-ctv', 'q4_0', '--fit', 'off',
                 '--mmproj', '/mnt/xfs/AI_Models/strata/models/qwen38-flash-next-nvfp4-gptq/mmproj-Qwen3.8-Flash-Next-BF16.gguf']}


def build_registry(source=None):
    import copy
    import json
    source = source or json.loads((ROOT / 'rtx5080/models.json').read_text())
    registry = copy.deepcopy(source)
    registry['models'] = {name: registry['models'][name] for name in ('describe', 'ocr')}
    name = 'qwen38-flash-nvfp4'
    spec = model_spec()
    previous = source['models'].get(name, {})
    if (previous.get('validation') == 'passed-native-text-vision-tools-streaming'
            and previous.get('args') == spec['args'] and previous.get('binary') == spec['binary']
            and previous.get('vision') and previous.get('slots') == 1):
        spec = copy.deepcopy(previous)
    registry['models'][name] = spec
    registry['presets'] = {
        'capacity': {'description': 'Manually selected vision alternatives', 'exclude_models': [name]},
        f'flash-nvfp4-vision-{spec["context"]//1024}k': {'description': f'One {spec["context"]//1024}K CUDA Strata vision slot', 'models': {name: {}}, 'experimental': spec['experimental']}}
    return registry

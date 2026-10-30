"""Build the replacement single-slot registry without changing live serving.

Run python -m arcB70.single_vision to inspect the candidate. Activation requires
projector verification, native allocation and long-context validation first.
"""
import copy
import json
from pathlib import Path


def build_registry(source=None):
    if source is None:
        source = json.loads(Path(__file__).with_name('models.json').read_text())
    if source.get('serving_engine') == 'vllm':
        return copy.deepcopy(source)
    registry = copy.deepcopy(source)
    name = 'qwen3.8-smart-q4-512k'
    model = copy.deepcopy(source['models'][name])
    model.pop('shared_pool', None)
    model.update(vision=True, slots=1, reserved=0, aliases=[],
                 experimental=True, omit_provisional_label=True, validation='pending-single-slot-vision-validation')
    from arcB70.budget import args_for, WEIGHTS
    model['vision_weights'] = WEIGHTS['vision']
    model['args'] = args_for('qwen', 524288, reasoning='xhigh')
    args = model['args']
    if '--mmproj' not in args:
        args += ['--mmproj', '/mnt/xfs/AI_Models/gguf/qwen3.8/mmproj-F16.gguf',
                 '--image-max-tokens', '2048', '--mtmd-batch-max-tokens', '128']
    # The old estimate omits the projector and vision compute allocations.
    model.pop('memory_estimate', None)
    registry['binary'] = str(Path(__file__).resolve().parent / 'llama-server-sycl')
    registry.pop('shared_serving', None)
    registry['models'] = {name: model}
    registry['enabled_models'] = [name]
    registry['presets'] = {'single-vision-512k': {
        'description': 'One native 512K slot; Q4 weights/KV, xhigh, vision, YaRN 2x',
        'models': {name: {}}, 'experimental': True}}
    registry['deployment_status'] = 'pending-single-slot-vision-validation'
    previous = source['models'][name]
    if (set(source['models']) == {name} and previous.get('vision')
            and previous['args'] == model['args'] and source['binary'] == registry['binary']):
        model['validation'] = previous.get('validation', model['validation'])
        registry['deployment_status'] = source.get('deployment_status', registry['deployment_status'])
    return registry


if __name__ == '__main__':
    print(json.dumps(build_registry(), indent=2))

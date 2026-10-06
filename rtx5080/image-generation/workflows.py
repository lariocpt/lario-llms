"""Bounded native ComfyUI graphs from the pinned official Qwen/FLUX recipes."""


def graph(model, prompt, width=1024, height=1024, seed=0, steps=None):
    if model not in ('qwen-image', 'flux-klein'):
        raise ValueError('choose qwen-image or flux-klein')
    if not isinstance(prompt, str) or not 1 <= len(prompt.strip()) <= 12000:
        raise ValueError('prompt must contain 1–12000 characters')
    if any(type(n) is not int or n % 64 or not 256 <= n <= 1024 for n in (width, height)):
        raise ValueError('dimensions must be multiples of 64 from 256 to 1024')
    if type(seed) is not int or not 0 <= seed < 2 ** 63:
        raise ValueError('invalid seed')
    steps = (25 if model == 'qwen-image' else 4) if steps is None else steps
    if type(steps) is not int or not 1 <= steps <= 40:
        raise ValueError('steps must be 1–40')
    qwen = model == 'qwen-image'
    nodes = {
        '1': {'class_type': 'UnetLoaderGGUF' if qwen else 'UNETLoader', 'inputs':
              {'unet_name': 'qwen-image-2.1-UC-Q4_K_M.gguf'} if qwen else
              {'unet_name': 'flux-2-klein-4b.safetensors', 'weight_dtype': 'default'}},
        '2': {'class_type': 'CLIPLoader', 'inputs':
              {'clip_name': 'qwen3vl_8b_int8_convrot.safetensors' if qwen else 'qwen_3_4b.safetensors',
               'type': 'qwen_image' if qwen else 'flux2', 'device': 'cpu'}},
        '3': {'class_type': 'VAELoader', 'inputs':
              {'vae_name': 'qwen_image_2.1_vae_bf16.safetensors' if qwen else 'flux2-vae.safetensors'}},
        '4': {'class_type': 'TextEncodeQwenImage21' if qwen else 'CLIPTextEncode', 'inputs':
              {'clip': ['2', 0], 'prompt': prompt, 'negative_prompt': '', 'resolution': width} if qwen else
              {'clip': ['2', 0], 'text': prompt}},
        '5': {'class_type': 'EmptyLatentImage' if qwen else 'EmptyFlux2LatentImage', 'inputs':
              {'width': width, 'height': height, 'batch_size': 1}},
        '7': {'class_type': 'VAEDecode', 'inputs': {'samples': ['6', 0], 'vae': ['3', 0]}},
        '8': {'class_type': 'SaveImage', 'inputs': {'images': ['7', 0], 'filename_prefix': 'lario_image'}},
    }
    if qwen:
        nodes['9'] = {'class_type': 'QwenImage21Cache', 'inputs': {'model': ['1', 0], 'device': 'cpu', 'dtype': 'default'}}
        nodes['6'] = {'class_type': 'KSampler', 'inputs': {'model': ['9', 0], 'positive': ['4', 0],
                       'negative': ['4', 1], 'latent_image': ['5', 0], 'seed': seed, 'steps': steps,
                       'cfg': 1.0, 'sampler_name': 'euler', 'scheduler': 'simple', 'denoise': 1.0}}
    else:
        nodes['9'] = {'class_type': 'ConditioningZeroOut', 'inputs': {'conditioning': ['4', 0]}}
        nodes['10'] = {'class_type': 'RandomNoise', 'inputs': {'noise_seed': seed}}
        nodes['11'] = {'class_type': 'CFGGuider', 'inputs': {'model': ['1', 0], 'positive': ['4', 0], 'negative': ['9', 0], 'cfg': 1.0}}
        nodes['12'] = {'class_type': 'KSamplerSelect', 'inputs': {'sampler_name': 'euler'}}
        nodes['13'] = {'class_type': 'Flux2Scheduler', 'inputs': {'steps': steps, 'width': width, 'height': height}}
        nodes['6'] = {'class_type': 'SamplerCustomAdvanced', 'inputs': {'noise': ['10', 0], 'guider': ['11', 0],
                      'sampler': ['12', 0], 'sigmas': ['13', 0], 'latent_image': ['5', 0]}}
    return nodes

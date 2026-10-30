"""Fixed vLLM owner: native scheduler metrics and explicit token admission."""
import asyncio
import re
import subprocess
import aiohttp
from shared import modelctl
from shared.serving.catalog import public
from shared.serving.gateway import Coordinator, error


class VLLMCoordinator(Coordinator):
    async def inspect(self):
        if self.probe:
            return await self.probe()
        await asyncio.to_thread(modelctl.assert_device_ready, self.reg)
        check = await asyncio.to_thread(subprocess.run,
            ['systemctl', '--user', 'is-active', '--quiet', self.reg['service']],
            stdout=subprocess.DEVNULL)
        if check.returncode == 3:
            return None
        if check.returncode:
            raise RuntimeError('vLLM service state unknown')
        models = (await self.get('/v1/models'))['data']
        key, profile = next(iter(self.profiles.items()))
        if len(models) != 1 or models[0]['id'] != key or models[0].get('max_model_len') != profile['context']:
            raise RuntimeError('Native vLLM model/context differs from registry')
        async with self.session.get(self.upstream+'/metrics', timeout=aiohttp.ClientTimeout(total=8)) as response:
            response.raise_for_status()
            metrics = await response.text()
        def gauge(name):
            values = re.findall(r'^vllm:'+name+r'(?:\{[^\n]*\})?\s+([0-9.eE+-]+)\s*$', metrics, re.M)
            if len(values) != 1:
                raise RuntimeError('Native scheduler occupancy unavailable: '+name)
            value = float(values[0])
            if value < 0 or not value.is_integer():
                raise RuntimeError('Invalid scheduler occupancy')
            return int(value)
        busy = gauge('num_requests_running') + gauge('num_requests_waiting')
        return {**public(profile), 'busy':busy}

    async def _load(self, key):
        if self.loader:
            return await self.loader(key)
        if key not in self.profiles:
            error(404, 'unknown_profile')
        await asyncio.to_thread(self.service, 'start')
        for _ in range(600):
            try:
                if await self.inspect():
                    return
            except (OSError, RuntimeError, aiohttp.ClientError):
                pass
            await asyncio.sleep(2)
        raise RuntimeError('vLLM startup timed out')

    async def prepare_body(self, body, target, path):
        profile = self.profiles[target]
        body = dict(body, model=target)
        maximum = body.get('max_completion_tokens', body.get('max_tokens', 8192))
        if type(maximum) is not int or maximum < 1 or maximum > 8192:
            error(400, 'invalid_output_limit')
        if path != '/v1/chat/completions':
            error(400, 'vllm_chat_completions_required')
        payload = {k:body[k] for k in ('model','messages','tools','chat_template_kwargs') if k in body}
        payload['add_generation_prompt'] = True
        async with self.session.post(self.upstream+'/tokenize', json=payload,
                headers={'Authorization':'Bearer '+self.backend_key}, timeout=aiohttp.ClientTimeout(total=120)) as response:
            if response.status != 200:
                error(400, 'prompt_tokenization_failed')
            tokenized = await response.json()
        count = tokenized.get('count')
        if type(count) is not int:
            error(503, 'native_token_count_unavailable')
        if count + maximum > profile['context']:
            error(400, 'context_window_exceeded', prompt_tokens=count, output_tokens=maximum, context=profile['context'])
        if 'max_tokens' not in body and 'max_completion_tokens' not in body:
            body['max_tokens'] = maximum
        return body

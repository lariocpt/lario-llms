"""Shared-weight serving with atomic resident-memory and per-request KV budgets."""
import asyncio
import fcntl
import json
import shlex
import time
import uuid
from urllib.parse import quote, unquote

import aiohttp
from aiohttp import web

from shared import modelctl
from shared.gpu import HardwareUnavailable
from shared.serving.catalog import public
from shared.serving.gateway import Coordinator, error
from shared.serving.pools import backends
from shared.serving.headroom import read_memory, fit_context, manifest_path


class SharedCoordinator(Coordinator):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.backends = backends(self.reg, self.profiles)
        self.residents = {}
        self.config = self.reg['shared_serving']

    async def inspect(self):
        if self.probe:
            # Injected probes return the actual backend IDs and occupancy.
            found = await self.probe()
            rows = [] if found is None else found if isinstance(found, list) else [found]
            residents = {r['id']:r for r in rows}
            if set(residents)-self.backends.keys():
                raise RuntimeError('unknown resident backend')
        else:
            await asyncio.to_thread(modelctl.assert_device_ready, self.reg)
            rows = (await self.get('/running')).get('running', [])
            residents = {}
            for item in rows:
                key = item['model']
                if key not in self.backends or item.get('state') != 'ready':
                    raise RuntimeError('unknown or transitioning shared backend')
                b = self.backends[key]
                if b['allocation_gib'] is not None:
                    manifest = json.loads(manifest_path(self.reg,key).read_text())
                    if (manifest['backend_id'] != key or
                            not 4096 <= manifest['context_tokens'] <= b['context_ceiling']):
                        raise RuntimeError('invalid measured pool geometry')
                    b['context_tokens'] = manifest['context_tokens']
                    b['allocation_gib'] = manifest['allocation_gib']
                args = shlex.split(item['cmd'])
                expected = [('-c', b['context_ceiling']), ('--parallel', b['slots']),
                            ('-ctk', b['profile']['cache_k']), ('-ctv', b['profile']['cache_v'])]
                if any(args.count(flag) != 1 or args[args.index(flag)+1] != str(value)
                       for flag,value in expected):
                    raise RuntimeError('shared backend geometry differs from catalog')
                if b['profile'].get('shared_pool') and '--kv-unified' not in args:
                    raise RuntimeError('shared backend requires unified KV')
                slots = await asyncio.to_thread(modelctl.resident_slots, self.reg, item)
                if (not isinstance(slots, list) or len(slots) != b['slots'] or
                        any(type(s.get('is_processing')) is not bool for s in slots)):
                    raise RuntimeError('shared backend occupancy unavailable')
                residents[key] = {'id':key, 'busy':sum(s['is_processing'] for s in slots)}
        self.residents = residents
        self.uncertain = any(r['busy'] > sum(x['phase'] == 'running' for x in self.allocations(k))
                             for k,r in residents.items())
        if not residents:
            return None
        first = self.backends[next(iter(residents))]['profile']
        # Compatibility fields are a conservative aggregate; residents[] carries
        # each backend's exact identity and independent capacity.
        return {**public(first), 'id':first['backend_id'],
                'slots':sum(self.backends[k]['slots'] for k in residents),
                'busy':sum(r['busy'] for r in residents.values())}

    def allocations(self, backend):
        return [r for r in self.requests.values() if r['backend_id'] == backend]

    def check_load(self, key, required_tokens=0):
        if key in self.residents:
            return
        b = self.backends[key]
        # Workloads without a measured/calculated memory contract remain
        # exclusive; absence of an estimate never means zero memory.
        ids = set(self.residents)
        if self.loading_id:
            ids.add(self.profiles[self.loading_id]['backend_id'])
        ids.add(key)
        if len(ids) > 1 and any(self.backends[k]['allocation_gib'] is None for k in ids):
            error(409, 'exclusive_backend_resident_unload_first')
        used = self.config['reserve_gib'] + sum(self.backends[k]['allocation_gib'] or 0 for k in ids)
        if used > self.config['memory_budget_gib']:
            error(429, 'resident_memory_budget_exhausted', required_gib=used,
                  budget_gib=self.config['memory_budget_gib'])
        if b['allocation_gib'] is not None and not self.probe:
            pool = self.config['pools'][b['profile']['shared_pool']]
            try:
                memory = read_memory(self.reg)
            except (OSError,RuntimeError,ValueError):
                error(503, 'memory_headroom_unavailable')
            context = fit_context(pool,memory['free_bytes'],self.config['reserve_gib'])
            if context < max(pool['min_context'],required_tokens):
                error(429, 'measured_memory_headroom_exhausted', available_context=context,
                      required_tokens=max(pool['min_context'],required_tokens))

    def check_profile(self, key):
        policy = self.store.get('policy')
        if self.marker.exists() or policy['paused'] or key in policy['disabled']:
            error(423, 'hardware_or_profile_disabled')
        enabled = self.reg.get('enabled_models')
        if enabled is not None and self.profiles[key]['model'] not in enabled:
            error(423, 'profile_validation_pending')

    async def _load(self, key):
        backend = self.profiles[key]['backend_id']
        if self.loader:
            return await self.loader(backend)
        with (modelctl.ROOT/('.'+self.hardware+'.lock')).open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            async with self.session.post(self.upstream+'/v1/chat/completions',
                    json={'model':backend, 'messages':[{'role':'user','content':'.'}],
                          'max_tokens':1, 'chat_template_kwargs':{'enable_thinking':False}},
                    headers={'Authorization':'Bearer '+self.backend_key},
                    timeout=aiohttp.ClientTimeout(total=1800)) as response:
                response.raise_for_status()
                await response.read()

    async def activation(self, key):
        try:
            await self._load(key)
            await self.inspect()
            if self.profiles[key]['backend_id'] not in self.residents:
                raise RuntimeError('shared backend did not become resident')
            self.store.change(last_profile=key)
            self.last_error = None
        except BaseException as exc:
            self.uncertain = True
            self.last_error = 'Shared backend activation failed: '+type(exc).__name__
            raise
        finally:
            async with self.lock:
                self.loading = self.loading_id = None

    def start_load(self, key):
        self.check_load(self.profiles[key]['backend_id'],self.profiles[key]['context'])
        self.loading_id = key
        self.loading = asyncio.create_task(self.activation(key))
        self.loading.add_done_callback(lambda t:None if t.cancelled() else t.exception())
        return self.loading

    async def activate_shared(self, key):
        if key not in self.profiles:
            error(404, 'unknown_profile')
        self.check_profile(key)
        if self.loading:
            error(409, 'profile_loading')
        await self.inspect()
        if self.profiles[key]['backend_id'] not in self.residents:
            self.start_load(key)
            self.store.change()

    async def unload_shared(self, key):
        if key not in self.profiles:
            error(404, 'unknown_profile')
        await self.inspect()
        backend = self.profiles[key]['backend_id']
        if (self.loading or self.allocations(backend) or self.residents.get(backend, {}).get('busy')):
            error(409, 'backend_busy')
        if backend in self.residents:
            async with self.session.post(self.upstream+'/api/models/unload/'+quote(backend, safe=''),
                    headers={'Authorization':'Bearer '+self.backend_key}) as response:
                response.raise_for_status()
                await response.read()
            await self.inspect()
            if backend in self.residents:
                error(503, 'backend_unload_unconfirmed')
        self.store.change()

    async def reserve(self, request, key, role):
        if role not in ('interactive','fleet','auxiliary'):
            error(403, 'management_key_cannot_infer')
        key = self.resolve(key)
        p = self.profiles[key]
        backend = p['backend_id']
        b = self.backends[backend]
        async with self.lock:
            self.check_profile(key)
            run = request.headers.get('X-Lario-Run', '')[:160]
            client = request.get('client_id', 'legacy-'+role)
            run_key = client+':'+run
            if run and self.store.cancelled(run_key):
                error(423, 'run_cancelled')
            if self.loading and self.profiles[self.loading_id]['backend_id'] != backend:
                error(409, 'different_backend_loading')
            if not self.loading:
                try:
                    await self.inspect()
                except HardwareUnavailable as exc:
                    error(503, 'hardware_unavailable', message=str(exc))
                except Exception:
                    error(503, 'backend_state_unknown')
            active = self.allocations(backend)
            busy = self.residents.get(backend, {}).get('busy', 0)
            if busy > sum(r['phase'] == 'running' for r in active):
                # After a restart/disconnect there is no reliable token charge
                # for orphan work. Wait for actual backend idleness.
                error(503, 'untracked_backend_work')
            self.uncertain = False
            # With unified KV, even masked idle histories extend the attention
            # span. Owners that deliberately disable prompt reuse can discard
            # those histories before a new idle-to-busy burst. Never touch an
            # active burst, an unloaded backend, or an owner without this opt-in.
            pool = self.config['pools'].get(p.get('shared_pool'), {})
            if (pool.get('clear_idle_kv_on_admission', self.config.get('clear_idle_kv_on_admission', False))
                    and p.get('shared_pool') and backend in self.residents
                    and not active and busy == 0):
                await self.clear_idle_kv(backend)
            if len(active) >= b['slots']:
                error(429, 'hardware_capacity_exhausted')
            if role != 'interactive' and sum(r['role'] != 'interactive' for r in active) >= b['slots']-b['reserved']:
                error(429, 'interactive_capacity_reserved')
            used = sum(r['context_tokens'] for r in active)
            if p.get('shared_pool') and used+p['context'] > b['context_tokens']:
                error(429, 'context_budget_exhausted', available_tokens=b['context_tokens']-used,
                      required_tokens=p['context'])
            task = self.loading
            if backend not in self.residents and task is None:
                task = self.start_load(key)
            identifier = uuid.uuid4().hex
            self.requests[identifier] = {
                'id':identifier, 'profile_id':key, 'backend_id':backend, 'context_tokens':p['context'],
                'role':role, 'client':client, 'session_id':request.headers.get('X-Lario-Session',
                    request.headers.get('X-Opencode-Session',''))[:160],
                'run_id':run, 'run_key':run_key, 'started':time.time(), 'phase':'loading' if task else 'running',
                'registered_client':request.get('registered_client',False),
                'instance_id':request.headers.get('X-Lario-Instance','')[:160],
                'location':request.headers.get('X-Lario-Location','')[:1024],
                'kind':request.headers.get('X-Lario-Kind','primary')[:32],
                'session_title':unquote(request.headers.get('X-Lario-Title','')[:2000])[:200]
                    if request.get('registered_client',False) else '', 'task':asyncio.current_task()}
            self.store.change()
        try:
            if task:
                await asyncio.wait_for(asyncio.shield(task), timeout=1830)
            self.check_profile(key)
            if p.get('shared_pool'):
                prefix = 0
                for r in self.allocations(backend):
                    prefix += r['context_tokens']
                    if r['id'] == identifier:
                        break
                if prefix > b['context_tokens']:
                    error(429, 'context_budget_exhausted', available_tokens=b['context_tokens'])
            self.requests[identifier]['phase'] = 'running'
            return identifier, key
        except BaseException as exc:
            self.requests.pop(identifier, None)
            self.uncertain = True
            if isinstance(exc, (web.HTTPException, asyncio.CancelledError)):
                raise
            error(503, 'profile_activation_failed')

    async def clear_idle_kv(self, backend):
        try:
            slots = await self.get('/upstream/'+quote(backend, safe='')+'/slots')
            if (not isinstance(slots, list) or len(slots) != self.backends[backend]['slots']
                    or any(not isinstance(s, dict) or s.get('is_processing') is not False
                           or type(s.get('id')) is not int
                           or type(s.get('n_prompt_tokens', 0)) is not int
                           for s in slots)):
                raise ValueError('backend is not confirmed idle')
            for slot in slots:
                if slot.get('n_prompt_tokens', 0) > 0:
                    result = await self.backend_post(backend, f'/slots/{slot["id"]}?action=erase', {})
                    if (not isinstance(result, dict) or result.get('id_slot') != slot['id']
                            or type(result.get('n_erased')) is not int):
                        raise ValueError('slot erasure was not confirmed')
        except (aiohttp.ClientError, ValueError, KeyError, asyncio.TimeoutError):
            self.uncertain = True
            error(503, 'idle_kv_cleanup_unconfirmed')

    async def backend_post(self, backend, path, body):
        async with self.session.post(self.upstream+'/upstream/'+quote(backend, safe='')+path,
                json=body, headers={'Authorization':'Bearer '+self.backend_key},
                timeout=aiohttp.ClientTimeout(total=60)) as response:
            response.raise_for_status()
            return await response.json()

    async def prepare_body(self, body, key, path):
        p = self.profiles[key]
        body = dict(body, model=p['backend_id'])
        if not p.get('shared_pool'):
            return body
        if path not in ('/v1/chat/completions', '/v1/completions', '/completion'):
            error(400, 'shared_pool_endpoint_not_supported')
        if body.get('n',1) != 1 or body.get('best_of',1) != 1:
            error(400, 'shared_pool_requires_single_completion')
        if 'id_slot' in body:
            error(400, 'shared_pool_manages_slots')
        # These Qwen profiles are text-only. Counting image placeholders as text
        # would undercharge the actual backend context allocation.
        for message in body.get('messages', []):
            if not isinstance(message, dict):
                error(400, 'invalid_message')
            content = message.get('content')
            if isinstance(content, list) and any(not isinstance(part, dict) or part.get('type') != 'text'
                                                 for part in content):
                error(400, 'shared_pool_requires_text_input')
        kwargs = body.get('chat_template_kwargs', {})
        if not isinstance(kwargs, dict):
            error(400, 'invalid_chat_template_kwargs')
        if p['reasoning_effort'] is not None:
            body['chat_template_kwargs'] = {**kwargs, 'reasoning_effort':p['reasoning_effort']}
            body['reasoning_effort'] = p['reasoning_effort']
        output = min(8192, p['context']-4096)
        for field in ('max_tokens','max_completion_tokens','n_predict'):
            if field in body:
                if type(body[field]) is not int or not 0 < body[field] <= output:
                    error(400, 'invalid_output_limit', maximum=output)
                output = min(output, body[field])
        body['max_tokens' if path != '/completion' else 'n_predict'] = output
        try:
            if path == '/v1/chat/completions':
                rendered = await self.backend_post(p['backend_id'], '/apply-template', body)
                prompt = rendered['prompt']
            else:
                prompt = body.get('prompt')
            if not isinstance(prompt, str):
                error(400, 'single_text_prompt_required')
            if path == '/v1/chat/completions' and self.config['pools'][p['shared_pool']].get('template_tokens', False):
                tokens = {'tokens': rendered['tokens']}
            else:
                tokens = await self.backend_post(p['backend_id'], '/tokenize',
                                                 {'content':prompt, 'add_special':True})
            if not isinstance(tokens.get('tokens'), list):
                raise ValueError('invalid tokenization result')
        except (aiohttp.ClientError, KeyError, ValueError, asyncio.TimeoutError):
            error(503, 'context_tokenization_unavailable')
        if len(tokens['tokens'])+output > p['context']-4096:
            error(400, 'selected_context_exceeded', context_tokens=p['context']-4096)
        # Each request owns a full context reservation through terminal stream
        # completion. Never silently context-shift past its selected limit.
        if not self.config['pools'][p['shared_pool']].get('preserve_prompt_cache', False):
            body['cache_prompt'] = False
        return body

    async def snapshot(self):
        s = await super().snapshot()
        rows = []
        for key, resident in self.residents.items():
            b = self.backends[key]
            used = sum(r['context_tokens'] for r in self.allocations(key))
            rows.append({**public(b['profile']), 'id':key, 'slots':b['slots'],
                         'busy':resident['busy'], 'context_budget':b['context_tokens'],
                         'context_reserved':used, 'context_available':max(0,b['context_tokens']-used),
                         'allocation_gib':b['allocation_gib']})
        s['residents'] = rows
        used = sum(self.backends[k]['allocation_gib'] or 0 for k in self.residents)
        s['memory_budget'] = {'total_gib':self.config['memory_budget_gib'],
                              'reserve_gib':self.config['reserve_gib'], 'allocated_gib':used,
                              'available_gib':max(0,self.config['memory_budget_gib']-self.config['reserve_gib']-used),
                              'basis':'calculated-resident-allocation; runtime-validation-pending'}
        availability = {}
        for key,p in self.profiles.items():
            reason = None
            try:
                self.check_profile(key)
                self.check_load(p['backend_id'],p['context'])
                b = self.backends[p['backend_id']]
                active = self.allocations(p['backend_id'])
                if len(active) >= b['slots']:
                    reason = 'hardware_capacity_exhausted'
                elif p.get('shared_pool') and sum(r['context_tokens'] for r in active)+p['context'] > b['context_tokens']:
                    reason = 'context_budget_exhausted'
                elif self.loading and self.profiles[self.loading_id]['backend_id'] != p['backend_id']:
                    reason = 'different_backend_loading'
                elif s['uncertain']:
                    reason = 'backend_state_unknown'
            except web.HTTPException as exc:
                reason = json.loads(exc.text)['error']['code']
            availability[key] = {'selectable':reason is None, 'reason':reason,
                                 'resident':p['backend_id'] in self.residents}
        s['profile_availability'] = availability
        # Legacy fleet tooling cannot represent a mixed-context budget. Report
        # no advisory fleet capacity rather than overstating slots.
        s['agents'] = 0
        return s

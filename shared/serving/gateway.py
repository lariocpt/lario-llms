"""Owner-side fixed-profile admission. Only idle hardware can change profiles."""
import asyncio
from collections import Counter
import contextlib
import fcntl
import hmac
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import time
import uuid
from urllib.parse import unquote

import aiohttp
from aiohttp import web

from shared import modelctl
from shared.gpu import HardwareUnavailable
from shared.serving.catalog import profiles, public, legacy_routes
from shared.serving.state import Store, state_directory, off_marker

INFERENCE = {'/v1/chat/completions', '/v1/completions', '/v1/responses', '/v1/messages', '/completion'}
HOP = {'connection', 'keep-alive', 'transfer-encoding', 'content-length', 'content-encoding',
       'proxy-authenticate', 'proxy-authorization', 'te', 'trailer', 'upgrade'}


class HTTPLocked(web.HTTPClientError):
    status_code = 423


def error(status, code, **detail):
    raise {
        400: web.HTTPBadRequest, 401: web.HTTPUnauthorized, 403: web.HTTPForbidden,
        404: web.HTTPNotFound, 409: web.HTTPConflict, 423: HTTPLocked,
        429: web.HTTPTooManyRequests, 503: web.HTTPServiceUnavailable,
        504: web.HTTPGatewayTimeout,
    }[status](text=json.dumps({'error': {'code': code, 'message': code.replace('_', ' '), **detail}}),
              content_type='application/json', headers={'Retry-After': '2'} if status in (429, 503) else None)


class Coordinator:
    def __init__(self, reg, upstream, keys, backend_key, directory=None, probe=None, loader=None, service=None):
        self.reg, self.hardware = reg, reg['aliases'][0]
        self.upstream, self.keys, self.backend_key = upstream.rstrip('/'), keys, backend_key
        self.profiles = profiles(reg)
        try:
            selected, preset = modelctl.selection(reg)
        except (OSError, ValueError, RuntimeError):
            selected, preset = '', ''
        self.store = Store(directory or state_directory(reg), legacy_routes(reg, selected, preset))
        self.marker = self.store.directory/'off'
        self.lock = asyncio.Lock()
        self.control_lock = asyncio.Lock()
        self.uncertain = True
        self.requests = {}
        self.loading = None
        self.loading_id = None
        self.last_error = None
        self.session = None
        self.probe, self.loader = probe, loader
        self.service = service or self._service

    def role(self, request):
        token = request.headers.get('Authorization', '').removeprefix('Bearer ')
        path = Path(os.getenv('LARIO_REGISTERED_CLIENTS', str(Path.home()/'.config/lario-admission'/(self.hardware+'.clients.json'))))
        if path.exists():
            try:
                clients = json.loads(path.read_text())
                for client, entry in clients.items():
                    if (not re.fullmatch(r'[A-Za-z0-9_.-]{1,80}',client) or
                            entry['role'] not in ('interactive','fleet','auxiliary') or len(entry['key']) < 24 or
                            entry['key'] in (*self.keys.values(),self.backend_key)):
                        raise ValueError('invalid client registry')
                    if token and hmac.compare_digest(token, entry['key']):
                        request['client_id'] = client
                        request['registered_client'] = True
                        return entry['role']
            except (OSError,ValueError,KeyError,TypeError):
                error(503, 'client_registry_unavailable')
        for role, key in self.keys.items():
            if token and hmac.compare_digest(token, key):
                request['client_id'] = 'legacy-'+role
                request['registered_client'] = False
                return role
        error(401, 'credential_required')

    def resolve(self, key):
        target = self.store.get('policy')['legacy'].get(key, key)
        if target not in self.profiles:
            error(404, 'unknown_or_retired_profile')
        return target

    async def get(self, path):
        async with self.session.get(self.upstream+path, headers={'Authorization': 'Bearer '+self.backend_key},
                                    timeout=aiohttp.ClientTimeout(total=8)) as response:
            response.raise_for_status()
            return await response.json()

    async def inspect(self):
        if self.probe:
            return await self.probe()
        await asyncio.to_thread(modelctl.assert_device_ready, self.reg)
        items = (await self.get('/running')).get('running', [])
        if not items:
            return None
        if len(items) != 1 or items[0].get('state') != 'ready' or items[0]['model'] not in self.profiles:
            raise RuntimeError('backend residency is unknown or transitioning')
        item = items[0]
        profile = self.profiles[item['model']]
        args = shlex.split(item['cmd'])
        for flag, value in [('-c', profile['context']*profile['slots']), ('--parallel', profile['slots']),
                            ('-ctk', profile['cache_k']), ('-ctv', profile['cache_v'])]:
            if flag not in args or args[args.index(flag)+1] != str(value):
                raise RuntimeError('backend geometry or KV precision differs from fixed profile')
        # Always observe real occupancy, including after a disconnect. Native and
        # container monitoring both bypass llama-swap's inference semaphore.
        slots = await asyncio.to_thread(modelctl.resident_slots, self.reg, item)
        if not isinstance(slots, list) or len(slots) != profile['slots'] or any(
                type(s.get('is_processing')) is not bool for s in slots):
            raise RuntimeError('unknown backend occupancy')
        busy = sum(s['is_processing'] for s in slots)
        return {**public(profile), 'busy': busy}

    async def snapshot(self):
        policy = self.store.get('policy')
        resident, state, detail = None, 'cold', None
        try:
            resident = await self.inspect()
            if resident:
                state = 'busy' if resident['busy'] else 'ready'
        except HardwareUnavailable as exc:
            state, detail = 'hardware_unavailable', str(exc)
        except Exception:
            state, detail = 'reconciling', 'Backend/device state unavailable; activation is blocked.'
        if self.loading:
            state = 'loading'
        if policy['paused']:
            state = 'paused'
        if self.marker.exists():
            if self.probe:
                stopped = resident is None
            else:
                check = await asyncio.to_thread(subprocess.run, ['systemctl','--user','is-active','--quiet',self.reg['service']], stdout=subprocess.DEVNULL)
                stopped = check.returncode == 3
            state = 'off' if stopped else 'stopping_or_off_fault'
            if stopped:detail = None
        active = [{k: v for k, v in r.items() if k != 'task'} for r in self.requests.values()]
        occupied = max(len(self.requests), resident['busy']) if resident else len(self.requests)
        available = max(0, resident['slots']-occupied) if resident and state in ('ready','busy') else 0
        return {'hardware': self.hardware, 'owner': self.reg['host'], 'state': state,
                'revision': policy['revision'], 'enabled': not self.marker.exists(),
                'ready': state in ('ready','busy'), 'enforced': True, 'resident': resident,
                'profile_id': resident['id'] if resident else None,
                'model': resident['model'] if resident else None,
                'context': resident['context'] if resident else 0,
                'slots': resident['slots'] if resident else 0,
                'reserved': resident['reserved'] if resident else 0,
                'agents': modelctl.fleet_capacity(resident['slots'],resident['reserved'],resident['context'])
                          if resident and state in ('ready','busy') else 0,
                'available': available, 'busy': occupied, 'requests': active,
                'draining': policy['paused'], 'uncertain': self.uncertain or detail is not None,
                'loading_profile': self.loading_id, 'detail': detail, 'last_error': self.last_error,
                'observed_at': time.time()}

    def _service(self, action):
        subprocess.run(['systemctl', '--user', action, self.reg['service']], check=True,
                       stdout=subprocess.DEVNULL, timeout=90)

    async def _load(self, key):
        if self.loader:
            return await self.loader(key)
        lockfile = modelctl.ROOT/('.'+self.hardware+'.lock')
        with lockfile.open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            # inspect() uses tracked pending requests, so explicitly query real slots
            # before an idle activation. No request has been forwarded yet.
            items = (await self.get('/running')).get('running', [])
            for item in items:
                if item.get('state') != 'ready':
                    error(503, 'backend_transitioning')
                slots = await asyncio.to_thread(modelctl.resident_slots, self.reg, item)
                if not isinstance(slots, list) or not slots or any(s.get('is_processing') is not False for s in slots):
                    error(409, 'backend_busy')
            async with self.session.post(self.upstream+'/v1/chat/completions',
                    json={'model': key, 'messages': [{'role':'user','content':'.'}], 'max_tokens':1,
                          'chat_template_kwargs': {'enable_thinking':False}},
                    headers={'Authorization':'Bearer '+self.backend_key},
                    timeout=aiohttp.ClientTimeout(total=1800)) as response:
                response.raise_for_status()
                await response.read()

    async def activation(self, key):
        try:
            await self._load(key)
            live = await self.inspect()
            if live is None or live['id'] != key:
                raise RuntimeError('requested fixed profile did not become resident')
            p = self.profiles[key]
            # Compatibility state is bookkeeping only; all inference aliases are pinned.
            modelctl.save_selection(self.reg, p['model'], p['preset'])
            self.store.change(last_profile=key)
            self.last_error = None
        except Exception as exc:
            self.last_error = 'Profile activation failed: '+type(exc).__name__
            raise
        finally:
            async with self.lock:
                self.loading, self.loading_id = None, None

    async def reserve(self, request, key, role):
        if role not in ('interactive','fleet','auxiliary'):
            error(403, 'management_key_cannot_infer')
        key = self.resolve(key)
        if (self.hardware == 'rtx5080' and role != 'auxiliary'
                and not self.profiles[key]['spec'].get('allow_interactive', False)):
            error(403, 'rtx_auxiliary_credential_required')
        key = self.resolve(key)
        async with self.lock:
            policy = self.store.get('policy')
            if self.marker.exists() or policy['paused'] or key in policy['disabled']:
                error(423, 'hardware_or_profile_disabled')
            run = request.headers.get('X-Lario-Run', '')[:160]
            client = request.get('client_id', 'legacy-'+role)
            run_key = client+':'+run
            if run and self.store.cancelled(run_key):
                error(423, 'run_cancelled')
            p = self.profiles[key]
            counts = Counter(r['role'] for r in self.requests.values())
            fleet = modelctl.fleet_capacity(p['slots'],p['reserved'],p['context'])
            if role == 'auxiliary' and p['vision']:
                fleet = p['slots'] - p['reserved']
            if len(self.requests) >= p['slots'] or (role in ('fleet','auxiliary') and self.hardware != 'rtx5080'
                    and counts['fleet']+counts['auxiliary'] >= fleet):
                error(429, 'hardware_capacity_exhausted')
            if self.loading:
                if self.loading_id != key:
                    error(409, 'different_profile_loading', resident=self.loading_id)
                task = self.loading
            else:
                try:
                    resident = await self.inspect()
                except HardwareUnavailable as exc:
                    error(503, 'hardware_unavailable', message=str(exc))
                except Exception:
                    error(503, 'backend_state_unknown')
                # Successful inspection reconciles residency and occupancy.
                # Existing work blocks profile changes, not additional requests
                # for the identical resident profile when slots remain free.
                self.uncertain = False
                if resident and resident['id'] != key and (self.requests or resident['busy']):
                    error(409, 'different_profile_busy', resident=resident['id'])
                if resident and max(len(self.requests), resident['busy']) >= p['slots']:
                    error(429, 'hardware_capacity_exhausted')
                if not resident or resident['id'] != key:
                    if self.requests:
                        error(409, 'hardware_busy')
                    task = self.loading = asyncio.create_task(self.activation(key))
                    self.loading_id = key
                    task.add_done_callback(lambda t: None if t.cancelled() else t.exception())
                else:
                    task = None
            identifier = uuid.uuid4().hex
            self.store.change()
            self.requests[identifier] = {'id':identifier, 'profile_id':key, 'role':role, 'client':client,
                'session_id':request.headers.get('X-Lario-Session',request.headers.get('X-Opencode-Session',''))[:160],
                'run_id':run, 'run_key':run_key, 'started':time.time(), 'phase':'loading' if task else 'running',
                'registered_client':request.get('registered_client',False),
                'instance_id':request.headers.get('X-Lario-Instance','')[:160],
                'location':request.headers.get('X-Lario-Location','')[:1024],
                'kind':request.headers.get('X-Lario-Kind','primary')[:32],
                'session_title':unquote(request.headers.get('X-Lario-Title','')[:2000])[:200]
                    if request.get('registered_client',False) else '',
                'task':asyncio.current_task()}
        try:
            if task:
                await asyncio.wait_for(asyncio.shield(task), timeout=1830)
            if self.marker.exists() or self.store.get('policy')['paused']:
                error(423, 'hardware_paused')
            self.requests[identifier]['phase'] = 'running'
            return identifier, key
        except BaseException as exc:
            self.requests.pop(identifier, None)
            self.uncertain = True
            if isinstance(exc, (web.HTTPException, asyncio.CancelledError)):
                raise
            if isinstance(exc, (TimeoutError, asyncio.TimeoutError)):
                error(504, 'profile_load_timeout')
            error(503, 'profile_activation_failed')

    async def control(self, body):
        async with self.control_lock:
            # Other managed RTX workloads already hold this same lock. Never
            # advertise Off while an image/encoding job still owns the GPU.
            lock = None
            try:
                if isinstance(body,dict) and body.get('action') in ('off','cancel-and-off'):
                    lock = (modelctl.ROOT/('.'+self.hardware+'.lock')).open('a')
                    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                    except BlockingIOError:error(409,'hardware_workload_busy')
                return await self._control(body)
            finally:
                if lock is not None:lock.close()

    async def _control(self, body):
        if not isinstance(body,dict) or set(body)-{'action','profile_id','request_id','expected_revision','idempotency_key'}:
            error(400, 'invalid_operation')
        token = body.get('idempotency_key')
        if not isinstance(token,str) or not re.fullmatch(r'[a-zA-Z0-9_-]{16,100}',token):
            error(400, 'idempotency_key_required')
        serialized = json.dumps(body,sort_keys=True)
        prior = self.store.db.execute('SELECT request,result FROM operations WHERE id=?',(token,)).fetchone()
        if prior:
            if prior[0] != serialized:
                error(409,'idempotency_key_reused')
            return json.loads(prior[1])
        async with self.lock:
            policy = self.store.get('policy')
            if body.get('expected_revision') != policy['revision']:
                error(409,'stale_revision')
            action = body.get('action')
            if action not in ('pause','resume','on','off','cancel-all','cancel-and-off','cancel','enable','disable','activate','unload'):
                error(400,'unknown_action')
            cancelled_runs = []
            if action == 'unload':
                if not hasattr(self, 'unload_shared'):
                    error(400, 'unload_not_supported')
                await self.unload_shared(body.get('profile_id'))
            if action == 'activate' and hasattr(self, 'activate_shared'):
                await self.activate_shared(body.get('profile_id'))
            elif action == 'activate':
                key=body.get('profile_id')
                if key not in self.profiles:error(404,'unknown_profile')
                if self.marker.exists() or policy['paused'] or key in policy['disabled']:
                    error(423,'hardware_or_profile_disabled')
                if self.loading:error(409,'profile_loading')
                resident=await self.inspect()
                if self.requests or (resident and resident['busy']):error(409,'hardware_busy')
                if not resident or resident['id'] != key:
                    self.loading=asyncio.create_task(self.activation(key));self.loading_id=key
                    self.loading.add_done_callback(lambda t:None if t.cancelled() else t.exception())
                    self.store.change()
            if action in ('off','disable'):
                resident = None if action=='off' and self.marker.exists() else await self.inspect()
                if self.requests or self.loading or (resident and resident['busy']):
                    error(409,'hardware_busy')
            if action in ('pause','cancel-all','cancel-and-off','off'):
                self.store.change(paused=True)
            if action in ('cancel','cancel-all','cancel-and-off'):
                targets = list(self.requests.values())
                if action == 'cancel':
                    targets = [r for r in targets if r['id']==body.get('request_id')]
                    if not targets:
                        error(404,'request_not_active')
                    target=targets[0]
                    if target['run_id']:
                        targets=[r for r in self.requests.values() if (r['client'],r['run_id'],r.get('instance_id')) ==
                                 (target['client'],target['run_id'],target.get('instance_id'))]
                for r in targets:
                    cancelled_runs.append({k:v for k,v in r.items() if k != 'task'})
                    if r['run_id']:
                        self.store.tombstone(r['run_key'])
                    r['task'].cancel()
            if action in ('off','cancel-and-off'):
                modelctl.atomic(self.marker,'Disabled explicitly; enable hardware before model use.\n')
            if action in ('enable','disable'):
                target = body.get('profile_id')
                if target not in self.profiles:
                    error(404,'unknown_profile')
                disabled = set(policy['disabled'])
                disabled.add(target) if action=='disable' else disabled.discard(target)
                self.store.change(disabled=sorted(disabled))
            if action in ('on','resume'):
                if action=='resume' and self.marker.exists():
                    error(423,'hardware_off_use_on')
                if action=='on':
                    self.marker.unlink(missing_ok=True)
                self.store.change(paused=False)
        # Never hold the accounting lock across service/worker shutdown.
        if action in ('off','cancel-and-off'):
            if self.loading:
                self.loading.cancel()
                await asyncio.gather(self.loading,return_exceptions=True)
            await asyncio.to_thread(self.service,'stop')
        if action=='on':
            await asyncio.to_thread(self.service,'start')
        result = {'operation_id':token,'action':action,'state':await self.snapshot(),
                  'cancelled_runs':cancelled_runs,
                  'scope':'Request cancellation only; originating agent interruption is reported separately.'}
        with self.store.db:
            self.store.db.execute('INSERT INTO operations VALUES (?,?,?)',(token,serialized,json.dumps(result)))
        return result


def create_app(reg, upstream, keys, backend_key, directory=None, probe=None, loader=None, service=None):
    if set(keys) != {'interactive','fleet','auxiliary','management'} or len(set(keys.values())) != 4 or backend_key in keys.values() or any(len(k)<24 for k in [*keys.values(),backend_key]):
        raise ValueError('distinct role and backend credentials required')
    cls = Coordinator
    if reg.get('serving_engine') == 'vllm':
        from shared.serving.vllm_gateway import VLLMCoordinator
        cls = VLLMCoordinator
    elif reg.get('shared_serving'):
        from shared.serving.shared_gateway import SharedCoordinator
        cls = SharedCoordinator
    coordinator = cls(reg,upstream,keys,backend_key,directory,probe,loader,service)
    app = web.Application(client_max_size=50*1024*1024,handler_args={'handler_cancellation':True})
    app['coordinator'] = coordinator

    async def lifecycle(app):
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=7200),auto_decompress=False) as session:
            coordinator.session = session
            yield
            if coordinator.loading:
                coordinator.loading.cancel()
                await asyncio.gather(coordinator.loading,return_exceptions=True)
            coordinator.store.close()
    app.cleanup_ctx.append(lifecycle)

    async def handler(request):
        if request.path in ('/health','/budget') and request.method=='GET':
            s = await coordinator.snapshot()
            s.pop('requests',None)
            return web.json_response(s,status=503 if request.path=='/health' and not s['ready'] else 200)
        role = coordinator.role(request)
        if request.path.startswith('/admin/'):
            if role!='management':
                error(403,'management_credential_required')
            if request.path=='/admin/v1/state' and request.method=='GET':
                return web.json_response(await coordinator.snapshot())
            if request.path=='/admin/v1/catalog' and request.method=='GET':
                return web.json_response({'profiles':[public(p) for p in coordinator.profiles.values() if not p.get('alias_of')],
                                         'disabled':coordinator.store.get('policy')['disabled']})
            if request.path=='/admin/v1/operations' and request.method=='POST':
                return web.json_response(await coordinator.control(await request.json()))
            if request.path in ('/admin/drain','/admin/resume') and request.method=='POST':
                if request.path.endswith('resume') and coordinator.marker.exists():
                    error(423,'hardware_off')
                async with coordinator.lock:
                    if request.path.endswith('resume') and coordinator.requests:
                        error(409,'hardware_busy')
                    coordinator.store.change(paused=request.path.endswith('drain'))
                return web.json_response(await coordinator.snapshot())
            error(404,'unknown_operation')
        if request.path=='/v1/models' and request.method=='GET':
            return web.json_response({'object':'list','data':[{'id':k,'object':'model','owned_by':coordinator.hardware,
                                      'name':p['name']} for k,p in coordinator.profiles.items() if not p.get('alias_of')]})
        if request.path not in INFERENCE or request.method!='POST':
            error(404,'unknown_endpoint')
        try:
            body = await request.json()
        except (ValueError,TypeError):
            error(400,'invalid_json')
        if not isinstance(body,dict) or not isinstance(body.get('model'),str):
            error(400,'model_required')
        identifier, target = await coordinator.reserve(request,body['model'],role)
        clean = False
        try:
            if hasattr(coordinator, 'prepare_body'):
                body = await coordinator.prepare_body(body, target, request.path)
            else:
                body['model'] = target
            async with coordinator.session.post(upstream.rstrip('/')+request.path,json=body,
                    headers={'Authorization':'Bearer '+backend_key}) as upstream_response:
                response = web.StreamResponse(status=upstream_response.status,
                    headers={k:v for k,v in upstream_response.headers.items() if k.lower() not in HOP})
                response.headers['X-Lario-Request'] = identifier
                await response.prepare(request)
                terminal = not (body.get('stream') is True and request.path in ('/v1/chat/completions','/v1/completions'))
                tail = b''
                async for chunk in upstream_response.content.iter_any():
                    tail = (tail+chunk)[-128:]
                    terminal = terminal or b'data: [DONE]' in tail
                    await response.write(chunk)
                await response.write_eof()
                clean = upstream_response.status < 500 and terminal
                return response
        except (aiohttp.ClientError,asyncio.TimeoutError):
            error(503,'backend_request_failed')
        finally:
            coordinator.requests.pop(identifier,None)
            if not clean:
                coordinator.uncertain = True
            coordinator.store.change()
    app.router.add_route('*','/{tail:.*}',handler)
    return app

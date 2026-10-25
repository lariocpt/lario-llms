import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from shared.serving.catalog import profiles, render_backend
from shared.serving.shared_gateway import SharedCoordinator

ROOT = Path(__file__).resolve().parents[1]


class SharedServingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.reg = json.loads((ROOT/'geekom/models.json').read_text())
        self.live = {}
        self.loads = []
        async def probe():
            return list(self.live.values())
        async def load(key):
            self.loads.append(key)
            self.live[key] = {'id':key, 'busy':0}
        self.g = SharedCoordinator(self.reg, 'http://unused', {}, 'x'*32,
                                   self.temp.name, probe=probe, loader=load)
        self.addCleanup(self.g.store.close)
        self.req = make_mocked_request('POST', '/v1/chat/completions')

    def key(self, model='qwen3.8-smart', preset='capacity'):
        return next(k for k,p in self.g.profiles.items() if p['model']==model and p['preset']==preset)

    async def reserve(self, model='qwen3.8-smart', preset='capacity'):
        return await self.g.reserve(self.req, self.key(model,preset), 'interactive')

    async def test_mixed_context_and_thinking_share_one_load(self):
        a,b = await asyncio.gather(self.reserve('qwen3.8-smart'), self.reserve('qwen3.8-medium-128k'))
        await self.reserve('qwen3.8-medium','long-512k')
        self.assertEqual(len(self.loads),1)
        self.assertEqual(len(self.g.requests),3)
        s = await self.g.snapshot()
        self.assertEqual(s['residents'][0]['context_reserved'],245760+122880+524288)
        self.assertEqual(s['agents'],0)

    async def test_flash_mixed_windows_share_one_load_and_release_context(self):
        ids = [await self.reserve('qwen38-flash') for _ in range(2)]
        await self.reserve('qwen38-flash','flash-128k')
        await self.reserve('qwen38-flash','flash-128k')
        self.assertEqual(len(self.loads),1)
        state = await self.g.snapshot()
        resident = state['residents'][0]
        self.assertEqual(resident['context_reserved'],2*245760+2*131072)
        self.assertEqual(resident['context_budget'],786432)
        self.assertEqual(resident['slots'],6)
        self.assertIsNone(resident['allocation_gib'])
        with self.assertRaises(web.HTTPTooManyRequests):
            await self.reserve('qwen38-flash','flash-128k')
        self.g.requests.pop(ids[0][0])
        await self.reserve('qwen38-flash','flash-128k')
        self.assertEqual(len(self.loads),1)

    async def test_flash_pool_is_exclusive_in_both_loading_orders(self):
        await self.reserve('qwen38-flash','flash-128k')
        with self.assertRaises(web.HTTPConflict):
            await self.reserve()
        self.live.clear(); self.loads.clear(); self.g.requests.clear()
        await self.reserve()
        with self.assertRaises(web.HTTPConflict):
            await self.reserve('qwen38-flash')
        self.assertEqual(len(self.loads),1)

    async def test_flash_stream_limit_and_coding_reservations(self):
        key = self.key('qwen38-flash','flash-128k')
        for _ in range(4):
            await self.g.reserve(self.req,key,'fleet')
        with self.assertRaises(web.HTTPTooManyRequests):
            await self.g.reserve(self.req,key,'fleet')
        for _ in range(2):
            await self.g.reserve(self.req,key,'interactive')
        self.assertEqual(len(self.loads),1)
        with self.assertRaises(web.HTTPTooManyRequests):
            await self.g.reserve(self.req,key,'interactive')

    async def test_flash_body_preserves_thinking_and_checks_selected_window(self):
        self.g.backend_post = AsyncMock(side_effect=[{'prompt':'hello'}, {'tokens':[1,2]}])
        body = await self.g.prepare_body({'messages':[],
            'chat_template_kwargs':{'enable_thinking':False}},
            self.key('qwen38-flash','flash-128k'), '/v1/chat/completions')
        self.assertEqual(body['chat_template_kwargs'],{'enable_thinking':False})
        self.assertNotIn('reasoning_effort',body)
        self.assertFalse(body['cache_prompt'])
        self.g.backend_post = AsyncMock(side_effect=[{'prompt':'huge'}, {'tokens':[0]*131072}])
        with self.assertRaises(web.HTTPBadRequest):
            await self.g.prepare_body({'messages':[]},
                self.key('qwen38-flash','flash-128k'), '/v1/chat/completions')

    async def test_flash_compiles_one_exclusive_unified_native_backend(self):
        import shlex
        import yaml
        models = yaml.safe_load(render_backend(self.reg))['models']
        entries = [p for p in self.g.profiles.values() if p['model']=='qwen38-flash']
        self.assertEqual(len({p['backend_id'] for p in entries}),1)
        self.assertTrue(all(p['pool_exclusive'] for p in entries))
        command = models[entries[0]['backend_id']]['cmd']
        self.assertEqual(sum('Flash-Next' in b['cmd'] for b in models.values()),1)
        self.assertNotIn('headroom.py',command)
        args = shlex.split(command)
        for flag,value in [('-c','786432'),('--parallel','6'),('-ctk','q8_0'),('-ctv','q8_0'),('--ctx-checkpoints','2')]:
            self.assertEqual(args[args.index(flag)+1],value)
        self.assertIn('--kv-unified',args)
        self.assertIn('--no-context-shift',args)
        self.assertNotIn('--rope-scaling',args)

    async def test_flash_live_inspection_uses_fixed_geometry_without_memory_manifest(self):
        import yaml
        key = self.g.profiles[self.key('qwen38-flash')]['backend_id']
        command = yaml.safe_load(render_backend(self.reg))['models'][key]['cmd']
        self.g.probe = None
        self.g.get = AsyncMock(return_value={'running':[{
            'model':key,'state':'ready','cmd':command}]})
        with patch('shared.serving.shared_gateway.read_memory') as memory, \
                patch('shared.serving.shared_gateway.manifest_path') as manifest, \
                patch('shared.serving.shared_gateway.modelctl.assert_device_ready'), \
                patch('shared.serving.shared_gateway.modelctl.resident_slots',
                      return_value=[{'is_processing':False} for _ in range(6)]):
            self.g.check_load(key,245760)
            await self.g.inspect()
            memory.assert_not_called()
            manifest.assert_not_called()
        self.assertEqual(self.g.residents[key]['busy'],0)

    async def test_context_budget_refuses_and_release_restores_capacity(self):
        ids = [await self.reserve(preset='long-512k') for _ in range(3)]
        with self.assertRaises(web.HTTPTooManyRequests):
            await self.reserve('qwen3.8-medium-128k')
        s = await self.g.snapshot()
        self.assertEqual(s['profile_availability'][self.key()]['reason'],'context_budget_exhausted')
        self.g.requests.pop(ids[0][0])
        await self.reserve('qwen3.8-medium-128k')
        self.assertEqual(len(self.loads),1)

    async def test_supa_is_separate_and_coexists_only_within_memory_budget(self):
        await self.reserve()
        await self.reserve('qwen3.8-supa')
        self.assertEqual(len(self.loads),2)
        self.assertIn('Q8_K_XL',self.g.profiles[self.key('qwen3.8-supa')]['spec']['args'][1])
        self.g.config['memory_budget_gib'] = 60
        self.live.clear(); self.loads.clear(); self.g.requests.clear()
        await self.reserve()
        with self.assertRaises(web.HTTPTooManyRequests):
            await self.reserve('qwen3.8-supa')
        self.assertEqual(len(self.loads),1)

    async def test_unknown_occupancy_and_off_fail_closed(self):
        await self.reserve()
        self.g.requests.clear()
        self.live[self.loads[0]]['busy'] = 1
        with self.assertRaises(web.HTTPServiceUnavailable):
            await self.reserve()
        self.g.marker.write_text('off')
        with self.assertRaises(web.HTTPClientError):
            await self.reserve()

    async def test_request_effort_is_applied_and_oversize_prompt_refused(self):
        self.g.backend_post = AsyncMock(side_effect=[{'prompt':'hello'}, {'tokens':[1,2]}])
        body = await self.g.prepare_body({'messages':[{'role':'user','content':'hello'}]},
                                        self.key('qwen3.8-medium'), '/v1/chat/completions')
        self.assertEqual(body['chat_template_kwargs']['reasoning_effort'],'medium')
        self.assertEqual(body['model'],self.g.profiles[self.key()]['backend_id'])
        self.g.backend_post = AsyncMock(side_effect=[{'prompt':'huge'}, {'tokens':[0]*245760}])
        with self.assertRaises(web.HTTPBadRequest):
            await self.g.prepare_body({'messages':[]}, self.key(), '/v1/chat/completions')

    async def test_compile_has_one_q4_backend_and_separate_supa(self):
        import yaml
        models = yaml.safe_load(render_backend(self.reg))['models']
        regular = [p for p in self.g.profiles.values() if p.get('shared_pool')=='qwen-q4']
        self.assertEqual(len({p['backend_id'] for p in regular}),1)
        self.assertEqual(sum('Q4_K_XL' in b['cmd'] for b in models.values()),1)
        self.assertIn('--kv-unified',models[regular[0]['backend_id']]['cmd'])
        arc = json.loads((ROOT/'arcB70/models.json').read_text())
        entries = profiles(arc)
        self.assertEqual(len({p['backend_id'] for p in entries.values() if p.get('shared_pool')}),1)

    async def test_visible_choices_have_no_aliases_but_old_routes_remain(self):
        from shared.serving.catalog import visible_profiles,opencode
        visible=visible_profiles(self.reg)
        signatures=[(p['backend_id'],p['context'],p['reasoning_effort'])
                    for p in visible.values() if p.get('shared_pool')]
        self.assertEqual(len(signatures),len(set(signatures)))
        aliases=[p for p in self.g.profiles.values() if p.get('alias_of')]
        self.assertEqual(len(aliases),5)
        for p in aliases:
            self.assertNotIn(p['id'],opencode()['provider']['geekom']['models'])
            self.assertIn(p['alias_of'],visible)
            self.assertEqual(self.g.resolve(p['id']),p['id'])

    async def test_headroom_sizes_pool_and_refuses_missing_capacity(self):
        from shared.serving.headroom import fit_context, GIB
        pool = self.reg['shared_serving']['pools']['qwen-q4']
        large = fit_context(pool,100*GIB,8)
        small = fit_context(pool,35*GIB,8)
        self.assertEqual(large,pool['context_tokens'])
        self.assertGreater(small,0)
        self.assertLess(small,large)
        self.assertEqual(fit_context(pool,10*GIB,8),0)

    async def test_http_routes_variants_and_releases_reservations(self):
        from aiohttp.test_utils import TestClient, TestServer
        from shared.serving.gateway import create_app
        seen = []
        async def complete(request):
            seen.append(await request.json())
            return web.json_response({'choices':[{'message':{'content':'OK'}}]})
        async def template(request):
            return web.json_response({'prompt':'hello'})
        async def tokenize(request):
            return web.json_response({'tokens':[1,2]})
        fake = web.Application()
        fake.router.add_post('/v1/chat/completions',complete)
        fake.router.add_post('/upstream/{model}/apply-template',template)
        fake.router.add_post('/upstream/{model}/tokenize',tokenize)
        keys = {role:role+'x'*32 for role in ('interactive','fleet','auxiliary','management')}
        async with TestServer(fake) as backend:
            app = create_app(self.reg,str(backend.make_url('')),keys,'b'*32,
                             self.temp.name,probe=self.g.probe,loader=self.g.loader)
            async with TestClient(TestServer(app)) as client:
                for model in ('qwen3.8-smart','qwen3.8-medium'):
                    response = await client.post('/v1/chat/completions',
                        json={'model':self.key(model),'messages':[{'role':'user','content':'hello'}]},
                        headers={'Authorization':'Bearer '+keys['interactive']})
                    self.assertEqual(response.status,200,await response.text())
                self.assertFalse(app['coordinator'].requests)
        self.assertEqual(len(self.loads),1)
        self.assertEqual(seen[0]['model'],seen[1]['model'])
        self.assertEqual([b['reasoning_effort'] for b in seen],['xhigh','medium'])


if __name__ == '__main__':
    unittest.main()

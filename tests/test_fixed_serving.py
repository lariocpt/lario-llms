import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from shared.serving.catalog import profiles, render_backend, opencode
from shared.serving.gateway import create_app

ROOT = Path(__file__).resolve().parents[1]


class CatalogTests(unittest.TestCase):
    def test_every_choice_is_fixed_and_precision_is_explicit(self):
        for hardware, provider in opencode()['provider'].items():
            reg = json.loads((ROOT/hardware/'models.json').read_text())
            entries = profiles(reg)
            self.assertEqual(set(entries), set(provider['models']))
            rendered = render_backend(reg)
            for key, p in entries.items():
                self.assertIn(json.dumps(key)+':', rendered)
                self.assertEqual(provider['models'][key]['limit']['context'],p['context']-4096)
                self.assertTrue(p['name'].startswith({'geekom':'Geekom','7900xt':'Radeon','rtx5080':'RTX'}[hardware]))
                if hardware=='geekom':
                    self.assertEqual((p['cache_k'],p['cache_v']),('q8_0','q8_0'))
            self.assertNotIn('    aliases:',rendered)

    def test_changing_geometry_changes_identity(self):
        reg = json.loads((ROOT/'7900xt/models.json').read_text())
        before = set(profiles(reg))
        reg['models']['muse-glimmer']['slots'] += 1
        self.assertNotEqual(before,set(profiles(reg)))


class ServingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.reg = json.loads((ROOT/'7900xt/models.json').read_text())
        self.entries = profiles(self.reg)
        self.first,self.second = list(self.entries)[:2]
        self.resident = None
        self.loads = []
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.load_release = asyncio.Event()
        self.load_release.set()
        self.keys = {r:r+'x'*32 for r in ('interactive','fleet','auxiliary','management')}
        async def probe():
            return {**self.entries[self.resident],'busy':0} if self.resident else None
        async def loader(key):
            self.loads.append(key)
            await self.load_release.wait()
            self.resident = key
        async def complete(request):
            body=await request.json()
            self.assertEqual(body['model'],self.resident)
            self.started.set()
            await self.release.wait()
            return web.json_response({'choices':[{'message':{'content':'OK'}}]})
        backend=web.Application()
        backend.router.add_post('/v1/chat/completions',complete)
        self.backend=TestServer(backend)
        await self.backend.start_server()
        self.patcher=patch('shared.serving.gateway.modelctl.save_selection')
        self.patcher.start()
        self.service_calls=[]
        self.app=create_app(self.reg,str(self.backend.make_url('')),self.keys,'b'*32,
                            directory=self.temp.name,probe=probe,loader=loader,service=self.service_calls.append)
        self.gate=self.app['coordinator']
        self.client=TestClient(TestServer(self.app))
        await self.client.start_server()

    async def asyncTearDown(self):
        self.release.set()
        self.load_release.set()
        await self.client.close()
        await self.backend.close()
        self.patcher.stop()

    async def post(self,key,role='interactive',extra=None):
        return await self.client.post('/v1/chat/completions',json={'model':key},
                 headers={'Authorization':'Bearer '+self.keys[role],**(extra or {})})

    async def control(self,action,**fields):
        return await self.client.post('/admin/v1/operations',json={'action':action,
            'expected_revision':self.gate.store.get('policy')['revision'],
            'idempotency_key':action+'x'*32,**fields},
            headers={'Authorization':'Bearer '+self.keys['management']})

    async def test_cold_request_loads_then_busy_other_profile_refuses(self):
        pending=asyncio.create_task(self.post(self.first))
        await self.started.wait()
        conflict=await self.post(self.second)
        self.assertEqual(conflict.status,409)
        self.assertEqual(self.loads,[self.first])
        self.release.set()
        result=await pending
        self.assertEqual(result.status,200)
        self.assertEqual((await result.json())['choices'][0]['message']['content'],'OK')

    async def test_same_profile_shares_one_load(self):
        self.load_release.clear()
        a=asyncio.create_task(self.post(self.first))
        while not self.loads:await asyncio.sleep(.001)
        b=asyncio.create_task(self.post(self.first))
        await asyncio.sleep(.02)
        conflict=await self.post(self.second)
        self.assertEqual(conflict.status,409)
        self.assertEqual(self.loads,[self.first])
        self.load_release.set();self.release.set()
        self.assertEqual([r.status for r in await asyncio.gather(a,b)],[200,200])

    async def test_fleet_reservation_denial_does_not_load(self):
        qwen=next(k for k,p in self.entries.items() if p['model']=='qwen3.8')
        # One-slot Qwen has zero reservations and therefore one fleet slot.
        self.release.set()
        response=await self.post(qwen,'fleet')
        self.assertEqual(response.status,200)

    async def test_off_is_durable_and_requests_cannot_wake_hardware(self):
        response=await self.control('off')
        self.assertEqual(response.status,200)
        self.assertTrue(self.gate.marker.exists())
        self.assertEqual((await self.post(self.first)).status,423)
        self.assertEqual(self.loads,[])
        self.assertEqual(self.service_calls,['stop'])
        self.assertEqual((await self.control('on')).status,200)
        self.assertFalse(self.gate.marker.exists())

    async def test_management_key_cannot_infer_or_cause_load(self):
        response=await self.post(self.first,'management')
        self.assertEqual(response.status,403)
        self.assertEqual(self.loads,[])

    async def test_busy_off_refuses(self):
        pending=asyncio.create_task(self.post(self.first))
        await self.started.wait()
        response=await self.control('off')
        self.assertEqual(response.status,409)
        self.assertFalse(self.gate.marker.exists())
        self.release.set();await pending

    async def test_unauthorized_catalog_and_bypass_refused(self):
        self.assertEqual((await self.client.get('/v1/models')).status,401)
        response=await self.client.get('/running',headers={'Authorization':'Bearer '+self.keys['interactive']})
        self.assertEqual(response.status,404)


if __name__=='__main__':unittest.main()

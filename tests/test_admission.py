import asyncio
import json
import unittest

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from shared.admission.server import create_app


class GatewayTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.keys={role:role+'-'+'x'*32 for role in ['interactive','fleet','auxiliary','management']}
        self.busy=0
        self.ready=True
        self.context=245760
        self.finish=asyncio.Event()
        self.started=asyncio.Event()
        self.backend_calls=[]
        self.truncate=False
        self.reg={'aliases':['geekom'],'state':'.test-absent-state',
                  'models':{'model':{'reserved':2,'aliases':['alternate-name']}}}
        async def probe():
            if not self.ready: raise RuntimeError('offline')
            return {'model':'model','slots':3,'reserved':2,'agents':1,'context':self.context,
                    'busy':self.busy,'generation':'test'}
        async def complete(request):
            body=await request.json()
            self.backend_calls.append(body['model'])
            self.assertEqual(request.headers['Authorization'],'Bearer '+'b'*32)
            self.busy+=1
            response=web.StreamResponse(headers={'Content-Type':'text/event-stream'})
            await response.prepare(request)
            await response.write(b'data: {"choices":[{"delta":{"content":"OK"}}]}\n\n')
            self.started.set()
            await self.finish.wait()
            if self.truncate:
                await response.write_eof()
                return response
            self.busy-=1
            try:
                await response.write(b'data: [DONE]\n\n')
                await response.write_eof()
            except ConnectionError: pass
            return response
        backend=web.Application()
        backend.router.add_post('/v1/chat/completions',complete)
        self.backend=TestServer(backend)
        await self.backend.start_server()
        self.app=create_app(self.reg,str(self.backend.make_url('')),self.keys,'b'*32,probe)
        self.client=TestClient(TestServer(self.app))
        await self.client.start_server()

    async def asyncTearDown(self):
        self.finish.set()
        await self.client.close()
        await self.backend.close()

    async def post(self,role='fleet',model='model',path='/v1/chat/completions'):
        return await self.client.post(path,json={'model':model,'stream':True},
                                      headers={'Authorization':'Bearer '+self.keys[role]})

    async def test_fleet_cannot_borrow_two_coding_reservations(self):
        first=await self.post()
        overflow=await self.post()
        self.assertEqual(overflow.status,429)
        self.assertEqual(overflow.headers['Retry-After'],'2')
        self.assertEqual((await self.post('auxiliary')).status,429)
        second=await self.post('interactive')
        third=await self.post('interactive')
        full=await self.post('interactive')
        self.assertEqual(full.status,429)
        self.assertEqual(sum(self.app['admission'].active.values()),3)
        self.finish.set()
        await asyncio.gather(first.read(),second.read(),third.read())
        await asyncio.sleep(.05)
        self.assertEqual(sum(self.app['admission'].active.values()),0)

    async def test_alias_shares_capacity_and_cannot_swap(self):
        first=await self.post(model='alternate-name')
        self.assertEqual(self.backend_calls,['model'])
        self.assertEqual((await self.post()).status,429)
        self.assertEqual((await self.post(model='different-model')).status,409)
        first.close()

    async def test_unknown_credential_and_backend_bypass_routes(self):
        response=await self.client.post('/v1/chat/completions',json={'model':'model'},
                                        headers={'Authorization':'Bearer attacker','X-Workload-Class':'interactive'})
        self.assertEqual(response.status,401)
        for path in ['/upstream/model/slots','/api/models/unload','/running','/v1/embeddings']:
            self.assertEqual((await self.client.post(path,json={'model':'model'})).status,404)
        self.assertEqual((await self.post('management')).status,403)

    async def test_restart_reconciles_occupied_backend(self):
        self.busy=1
        response=await self.post('interactive')
        self.assertEqual(response.status,503)
        self.assertEqual((await (await self.client.get('/budget')).json())['available'],0)
        self.busy=0
        self.finish.set()
        self.assertEqual((await self.post('interactive')).status,200)

    async def test_disconnect_quarantines_until_backend_is_idle(self):
        response=await self.post('interactive')
        response.close()
        await asyncio.sleep(.3)
        self.assertTrue(self.app['admission'].uncertain)
        self.assertEqual((await self.post('interactive')).status,503)
        self.finish.set()
        for _ in range(30):
            if not self.busy: break
            await asyncio.sleep(.02)
        # Simulate the subsequent slot probe confirming that the orphan has ended.
        # aiohttp's test backend may cancel its handler before decrementing the
        # deliberately independent occupancy probe on disconnect.
        self.busy=0
        accepted=await self.post('interactive')
        self.assertEqual(accepted.status,200,(await accepted.text(),dict(self.app['admission'].active),self.busy))
        await accepted.read()

    async def test_truncated_success_quarantines_backend_work(self):
        self.truncate=True
        self.finish.set()
        response=await self.post('interactive')
        self.assertEqual(response.status,200)
        await response.read();await asyncio.sleep(.05)
        self.assertTrue(self.app['admission'].uncertain)
        self.assertEqual((await self.post('interactive')).status,503)
        self.busy=0
        self.truncate=False
        accepted=await self.post('interactive')
        self.assertEqual(accepted.status,200)
        await accepted.read()

    async def test_drain_closes_admission_without_killing_request(self):
        response=await self.post()
        headers={'Authorization':'Bearer '+self.keys['management']}
        drained=await self.client.post('/admin/drain',headers=headers)
        self.assertEqual(drained.status,200)
        self.assertEqual((await self.post('interactive')).status,503)
        self.assertEqual((await self.client.post('/admin/resume',headers=headers)).status,409)
        self.finish.set();await response.read();await asyncio.sleep(.05)
        self.assertEqual((await self.client.post('/admin/resume',headers=headers)).status,200)

    async def test_offline_fails_to_zero(self):
        self.ready=False
        budget=await (await self.client.get('/budget')).json()
        self.assertEqual((budget['agents'],budget['available']),(0,0))
        self.assertEqual((await self.post()).status,503)

    async def test_small_context_does_not_claim_hermes_primary_capacity(self):
        self.context=32768
        budget=await (await self.client.get('/budget')).json()
        self.assertEqual(budget['agents'],0)
        self.assertEqual((await self.post('fleet')).status,429)
        self.finish.set()
        response=await self.post('interactive')
        self.assertEqual(response.status,200)
        await response.read()

    async def test_rtx_is_exclusively_auxiliary(self):
        self.reg['aliases']=['rtx5080']
        self.assertEqual((await self.post('fleet')).status,429)
        self.assertEqual((await self.post('interactive')).status,429)
        self.finish.set()
        response=await self.post('auxiliary')
        self.assertEqual(response.status,200)
        await response.read()


if __name__=='__main__': unittest.main()

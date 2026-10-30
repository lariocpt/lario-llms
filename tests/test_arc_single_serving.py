"""B70 has two physical inference slots and no retired profile aliases."""
import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from shared.serving.catalog import profiles
from shared.serving.gateway import create_app

ROOT=Path(__file__).resolve().parents[1]

class ArcDualServingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.reg=json.loads((ROOT/'arcB70/models.json').read_text())
        self.profile=next(iter(profiles(self.reg).values()))
        self.started=asyncio.Event();self.release=asyncio.Event();self.resident=False;self.loads=[]
        async def probe():return {**self.profile,'busy':0} if self.resident else None
        async def load(key):self.loads.append(key);self.resident=True
        async def complete(request):
            self.started.set();await self.release.wait()
            return web.json_response({'choices':[{'message':{'content':'OK'}}]})
        backend=web.Application();backend.router.add_post('/v1/chat/completions',complete)
        async def tokenize(request):
            body=await request.json()
            return web.json_response({'count':self.profile['context'] if body.get('messages')==[{'role':'user','content':'overlong'}] else 10})
        backend.router.add_post('/tokenize',tokenize)
        self.backend=TestServer(backend);await self.backend.start_server()
        self.patch=patch('shared.serving.gateway.modelctl.save_selection');self.patch.start()
        self.keys={role:role+'x'*32 for role in ('interactive','fleet','auxiliary','management')}
        app=create_app(self.reg,str(self.backend.make_url('')),self.keys,'b'*32,
            directory=self.temp.name,probe=probe,loader=load)
        self.client=TestClient(TestServer(app));await self.client.start_server()

    async def asyncTearDown(self):
        self.release.set();await self.client.close();await self.backend.close();self.patch.stop()

    async def request(self,key):
        return await self.client.post('/v1/chat/completions',json={'model':key},headers={'Authorization':'Bearer '+self.keys['interactive']})

    async def test_two_requests_fill_slots_and_a_third_is_rejected(self):
        first=asyncio.create_task(self.request(self.profile['id']))
        await self.started.wait()
        second=asyncio.create_task(self.request(self.profile['id']))
        await asyncio.sleep(0.03)
        third=await self.request(self.profile['id'])
        self.assertEqual(third.status,429)
        self.assertEqual(self.loads,[self.profile['id']])
        self.release.set();response=await first;self.assertEqual(response.status,200)
        self.assertEqual((await second).status,200)

    async def test_overlong_prompt_is_rejected_before_generation(self):
        response=await self.client.post('/v1/chat/completions',json={
            'model':self.profile['id'],'messages':[{'role':'user','content':'overlong'}], 'max_tokens':32},
            headers={'Authorization':'Bearer '+self.keys['interactive']})
        self.assertEqual(response.status,400)
        self.assertEqual((await response.json())['error']['code'],'context_window_exceeded')
        self.assertFalse(self.started.is_set())

    async def test_old_flash_and_context_choices_cannot_load(self):
        for key in ('qwen38-flash-q4-256k','qwen3.8-smart-q4-128k','qwen3.8-medium-512k'):
            response=await self.request(key)
            self.assertEqual(response.status,404)
        self.assertEqual(self.loads,[])

import hashlib
import tempfile
import unittest
import asyncio
from unittest.mock import patch

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from shared.serving.panel import create_panel,password_hash


class PanelTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.config={'username':'lario','password_salt':'ab'*16,
                     'password_hash':password_hash('test-password','ab'*16),
                     'origin':'http://models.test','owners':{}}
        self.app=create_panel(self.config,self.temp.name)
        self.client=TestClient(TestServer(self.app));await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()

    async def login(self):
        response=await self.client.post('/login',data={'username':'lario','password':'test-password'},
                                       headers={'Origin':'http://models.test'},allow_redirects=False)
        self.assertEqual(response.status,302)
        return response

    async def test_private_state_requires_login(self):
        self.assertEqual((await self.client.get('/api/state')).status,401)

    async def test_prepared_placements_are_visible_but_not_operable(self):
        await self.login()
        data=await (await self.client.get('/api/state')).json()
        self.assertEqual({p['hardware'] for p in data['placements']},
                         {'arcB70'})
        self.assertEqual(data['owners'], {})
        response=await self.client.post('/api/operations/winmax7900xt',
            json={'action':'on'},headers={'Origin':'http://models.test','X-CSRF-Token':data['csrf']})
        self.assertEqual(response.status,404)

    async def test_foreign_origin_cannot_log_in_or_mutate(self):
        response=await self.client.post('/login',data={'username':'lario','password':'test-password'},
                                       headers={'Origin':'http://attacker.test'})
        self.assertEqual(response.status,403)
        await self.login()
        self.assertEqual((await self.client.post('/api/operations/geekom',json={'action':'off'},
                         headers={'Origin':'http://attacker.test'})).status,403)

    async def test_login_cookie_and_csrf_then_logout(self):
        response=await self.login()
        cookie=response.cookies['lario_models']
        self.assertTrue(cookie['httponly']);self.assertEqual(cookie['samesite'],'Strict')
        data=await (await self.client.get('/api/state')).json()
        self.assertIn('csrf',data)
        response=await self.client.post('/logout',headers={'Origin':'http://models.test'})
        self.assertEqual(response.status,403)
        response=await self.client.post('/logout',headers={'Origin':'http://models.test','X-CSRF-Token':data['csrf']})
        self.assertEqual(response.status,200)
        self.assertEqual((await self.client.get('/api/state')).status,401)

    async def test_login_attempts_are_bounded(self):
        for _ in range(5):
            r=await self.client.post('/login',data={'username':'lario','password':'wrong'},
                                    headers={'Origin':'http://models.test'})
            self.assertEqual(r.status,401)
        self.assertEqual((await self.client.post('/login',data={'username':'lario','password':'test-password'},
                  headers={'Origin':'http://models.test'})).status,429)

    async def test_browser_receives_no_owner_credentials(self):
        await self.login()
        data=await (await self.client.get('/api/state')).json()
        self.assertNotIn('config',data)
        r=await self.client.get('/')
        self.assertEqual(r.status,200)
        self.assertIn("frame-ancestors 'none'",r.headers['Content-Security-Policy'])

    async def test_cancellation_reports_unregistered_runner_without_ssh(self):
        async def operation(request):
            self.assertEqual(request.headers['Authorization'],'Bearer private-owner-test-key')
            return web.json_response({'cancelled_runs':[{'client':'legacy-fleet','session_id':'s1','run_id':'r1',
                'instance_id':'','registered_client':False}]})
        owner=web.Application();owner.router.add_post('/admin/v1/operations',operation)
        backend=TestServer(owner);await backend.start_server()
        try:
            self.config['owners']['geekom']={'url':str(backend.make_url('')).rstrip('/'),'management_key':'private-owner-test-key'}
            await self.login();state=await (await self.client.get('/api/state')).json()
            with patch('shared.serving.panel.asyncio.create_subprocess_exec') as ssh:
                response=await self.client.post('/api/operations/geekom',json={'action':'cancel-all',
                    'expected_revision':1,'idempotency_key':'test-operation-id-1234'},
                    headers={'Origin':'http://models.test','X-CSRF-Token':state['csrf']})
                result=await response.json()
                self.assertEqual(response.status,200)
                self.assertEqual(result['agent_interruptions'][0]['status'],'unsupported')
                self.assertNotIn('private-owner-test-key',str(result));ssh.assert_not_called()
        finally:await backend.close()


if __name__=='__main__':unittest.main()

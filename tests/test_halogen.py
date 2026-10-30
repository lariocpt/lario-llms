import unittest
import json
from pathlib import Path
import tempfile

from aiohttp import web
from aiohttp.test_utils import make_mocked_request
from shared.serving.shared_gateway import SharedCoordinator

from geekom.halogen.protocol import slot_snapshot


class HalogenOccupancyTests(unittest.TestCase):
    def health(self):
        return {'capability_probe':'ok', 'status':'ok', 'engine':{'responds':True},
                'context':262144, 'slots':4, 'kv_pool_positions':524288, 'in_flight':0}

    def test_idle_and_concurrent_counts(self):
        for n in range(5):
            h = {**self.health(), 'in_flight':n}
            slots = slot_snapshot(h,4)
            self.assertEqual(len(slots),4)
            self.assertEqual(sum(s['is_processing'] for s in slots),n)

    def test_unknown_or_invalid_occupancy_refuses_unload(self):
        for n in (None, True, -1, 5, '0'):
            with self.subTest(n=n), self.assertRaises(ValueError):
                slot_snapshot({**self.health(), 'in_flight':n},4)

    def test_unready_or_wrong_geometry_is_not_idle(self):
        for key,value in [('capability_probe','failed'),('status','engine_unresponsive'),
                          ('engine',{'responds':False}),('slots',1),
                          ('context',131072),('kv_pool_positions',262144)]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                slot_snapshot({**self.health(),key:value},4)


class HalogenAdmissionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        root = Path(__file__).resolve().parents[1]
        reg = json.loads((root/'geekom/models.json').read_text())
        self.assertEqual(set(reg['models']), {'qwen38-flash-halogen','qwen38-flash-halogen-128k'})
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.live = {}
        self.loads = []
        async def probe(): return list(self.live.values())
        async def load(key):
            self.loads.append(key)
            self.live[key] = {'id':key,'busy':0}
        self.owner = SharedCoordinator(reg,'http://unused',{},'x'*32,self.temp.name,probe=probe,loader=load)
        self.addCleanup(self.owner.store.close)
        self.request = make_mocked_request('POST','/v1/chat/completions')

    async def reserve(self, context):
        profile = next(p for p in self.owner.profiles.values() if p['context']==context)
        return await self.owner.reserve(self.request,profile['id'],'interactive')

    async def test_four_short_windows_share_weights_and_fifth_is_refused(self):
        for _ in range(4): await self.reserve(131072)
        self.assertEqual(len(self.loads),1)
        with self.assertRaises(web.HTTPException) as e: await self.reserve(131072)
        self.assertEqual(e.exception.status,429)

    async def test_two_long_windows_exhaust_pool_and_release_restores_it(self):
        first = await self.reserve(262144)
        await self.reserve(262144)
        with self.assertRaises(web.HTTPException) as e: await self.reserve(131072)
        self.assertEqual(e.exception.status,429)
        self.owner.requests.pop(first[0])
        await self.reserve(131072)
        await self.reserve(131072)
        self.assertEqual(len(self.loads),1)


if __name__ == '__main__':
    unittest.main()

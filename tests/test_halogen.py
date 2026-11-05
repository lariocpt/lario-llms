import unittest
import json
from pathlib import Path
from unittest.mock import AsyncMock
import tempfile

from aiohttp import web
from aiohttp.test_utils import make_mocked_request
from shared.serving.shared_gateway import SharedCoordinator
from shared.serving.catalog import opencode, output_limit, profiles

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

    async def test_output_limit_matches_client_and_preserves_profile_ids(self):
        expected = {
            'geekom.qwen38-flash-halogen.c262144.kf16-vf16.s4.halogen-256k.2be8caa2bd',
            'geekom.qwen38-flash-halogen-128k.c131072.kf16-vf16.s4.halogen-128k.f42df48f91',
        }
        self.assertEqual(set(opencode()['provider']['geekom']['models']), expected)
        for profile in self.owner.profiles.values():
            self.assertEqual(output_limit(profile), 32768)
        for model in opencode()['provider']['geekom']['models'].values():
            self.assertEqual(model['limit']['output'], 32768)

    async def test_explicit_32k_output_passes_all_supported_limit_fields(self):
        for profile in self.owner.profiles.values():
            for field in ('max_tokens', 'max_completion_tokens', 'n_predict'):
                self.owner.backend_post = AsyncMock(return_value={'prompt':'hello', 'tokens':[1, 2]})
                body = await self.owner.prepare_body({'messages':[], field:32768},
                                                      profile['id'], '/v1/chat/completions')
                self.assertEqual(body['max_tokens'], 32768)
            body = await self.owner.prepare_body({'messages':[]}, profile['id'], '/v1/chat/completions')
            self.assertEqual(body['max_tokens'], 8192)

    async def test_limit_aliases_are_normalized_to_the_counted_budget(self):
        profile = next(iter(self.owner.profiles.values()))
        self.owner.backend_post = AsyncMock(return_value={'prompt':'hello', 'tokens':[1, 2]})
        body = await self.owner.prepare_body({'messages':[], 'max_tokens':32768,
                                              'max_completion_tokens':8192, 'n_predict':16384},
                                            profile['id'], '/v1/chat/completions')
        for field in ('max_tokens', 'max_completion_tokens', 'n_predict'):
            self.assertEqual(body[field], 8192)

    async def test_output_cap_and_combined_context_are_enforced(self):
        profile = next(p for p in self.owner.profiles.values() if p['context'] == 131072)
        for value in (32769, 0, -1, True, '32768', 32768.0):
            with self.subTest(value=value), self.assertRaises(web.HTTPBadRequest):
                await self.owner.prepare_body({'messages':[], 'max_tokens':value},
                                              profile['id'], '/v1/chat/completions')
        count = profile['context'] - 4096 - 32768
        self.owner.backend_post = AsyncMock(return_value={'prompt':'fits', 'tokens':[0] * count})
        await self.owner.prepare_body({'messages':[], 'max_tokens':32768},
                                      profile['id'], '/v1/chat/completions')
        self.owner.backend_post = AsyncMock(return_value={'prompt':'too big', 'tokens':[0] * (count+1)})
        with self.assertRaises(web.HTTPBadRequest):
            await self.owner.prepare_body({'messages':[], 'max_tokens':32768},
                                          profile['id'], '/v1/chat/completions')

    def test_unconfigured_profiles_keep_8k_and_bad_registered_caps_fail(self):
        root = Path(__file__).resolve().parents[1]
        legacy = json.loads((root/'tests/fixtures/legacy-geekom.json').read_text())
        self.assertTrue(all(output_limit(p) == 8192 for p in profiles(legacy).values()))
        profile = next(iter(self.owner.profiles.values()))
        for value in (True, 0, -1, profile['context'], '32768'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                output_limit({**profile, 'spec':{**profile['spec'], 'max_output_tokens':value}})

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

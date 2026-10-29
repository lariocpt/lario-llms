"""Context extension and admission must agree on native geometry and isolation."""
import json
from pathlib import Path
import unittest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request
from tests import test_arc_flash as arc_tests
from tests import test_shared_serving as shared_tests
from geekom.strata.geometry import context_args, owner_geometry
from arcB70.flash_next import estimate

class GeometryTests(unittest.TestCase):
    def test_only_supported_owner_geometries_and_explicit_rope_extension(self):
        self.assertEqual(owner_geometry(1048576,2),(524288,2))
        self.assertEqual(owner_geometry(1048576,4),(262144,4))
        for total,slots in [(1048576,3),(1572864,3),(786432,1)]:
            with self.assertRaises(ValueError):owner_geometry(total,slots)
        args=context_args(524288)
        self.assertEqual(args[args.index('--rope-scale')+1],'2.0')
        self.assertNotIn('--rope-scale',context_args(262144))
        self.assertLess(estimate(786432,1)['estimated_vram_with_reserve_gib'],31.890625)

class GeekomExtendedAdmission(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=shared_tests.SharedServingTests.asyncSetUp
    key=shared_tests.SharedServingTests.key
    async def test_two_full_512k_windows_reject_third_and_old_mode(self):
        key=self.key('qwen38-flash-strata-512k','flash-strata-512k')
        for _ in range(2):await self.g.reserve(self.req,key,'interactive')
        self.assertEqual(sum(r['context_tokens'] for r in self.g.requests.values()),1048576)
        with self.assertRaises(web.HTTPTooManyRequests):await self.g.reserve(self.req,key,'interactive')
        with self.assertRaises(web.HTTPConflict):
            await self.g.reserve(self.req,self.key('qwen38-flash-strata','flash-strata-256k'),'interactive')

class B70ExtendedAdmission(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=arc_tests.FlashAdmissionTests.asyncSetUp
    async def test_single_768k_window_rejects_second_and_old_mode(self):
        key=next(k for k,p in self.g.profiles.items() if p['model']=='qwen38-flash-q4-768k')
        self.g.reg['enabled_models'].append('qwen38-flash-q4-768k')
        await self.g.reserve(self.req,key,'interactive')
        self.assertEqual(sum(r['context_tokens'] for r in self.g.requests.values()),786432)
        with self.assertRaises(web.HTTPTooManyRequests):await self.g.reserve(self.req,key,'interactive')
        with self.assertRaises(web.HTTPConflict):await self.g.reserve(self.req,self.flash,'interactive')

"""Flash Next has a separate CPU/VRAM contract and three whole-window charges."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock

from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from arcB70.flash_next import MODEL_NAME, MANIFEST, estimate
from shared.serving.catalog import profiles, render_backend
from shared.serving.shared_gateway import SharedCoordinator

ROOT = Path(__file__).resolve().parents[1]


class FlashCapacityTests(unittest.TestCase):
    def test_full_native_windows_fit_disjoint_cpu_and_gpu_budgets(self):
        memory = estimate()
        self.assertAlmostEqual(memory['attention_cache_gib'], 5.0625)
        self.assertAlmostEqual(memory['indexer_cache_gib'], 1.265625)
        self.assertLess(memory['estimated_vram_with_reserve_gib'], 31.890625)
        self.assertLess(memory['cpu_weight_gib'] + memory['host_reserve_gib'], 125.06)
        self.assertEqual(sum(s['bytes'] for s in MANIFEST['shards']), 111334654784)
        self.assertLess(estimate(131072)['estimated_vram_with_reserve_gib'],
                        memory['estimated_vram_with_reserve_gib'])
        for context, slots in ((262400, 3), (262143, 3), (262144, 4), (True, 3)):
            with self.assertRaises(ValueError):
                estimate(context, slots)

    def test_generator_preserves_old_ids_and_renders_exact_split(self):
        from arcB70.budget import build_registry
        reg = json.loads((ROOT/'arcB70/models.json').read_text())
        self.assertEqual(reg, build_registry())
        entries = profiles(reg)
        flash = next(p for p in entries.values() if p['model'] == MODEL_NAME)
        self.assertTrue(flash['experimental'])
        self.assertTrue(flash['pool_exclusive'])
        self.assertEqual((flash['context'], flash['pool_context'], flash['pool_slots']),
                         (262144, 786432, 3))
        self.assertIn(MODEL_NAME, reg['enabled_models'])
        self.assertIn('arcB70.qwen3.8-smart-q4-256k.c262144.kq4_0-vq4_0.s2.prepared.5170996f95', entries)
        import yaml
        command = yaml.safe_load(render_backend(reg))['models'][flash['backend_id']]['cmd']
        import shlex
        args = shlex.split(command)
        for flag, value in (('--n-cpu-moe', '40'), ('-ctk', 'q4_0'), ('-ctv', 'q4_0'),
                            ('-ot', 'per_layer_token_embd=CPU'), ('-c', '786432'),
                            ('--parallel', '3'), ('--cache-ram', '0'), ('--fit', 'off')):
            self.assertEqual(args[args.index(flag)+1], value)


class FlashAdmissionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        reg = json.loads((ROOT/'arcB70/models.json').read_text())
        self.live = {}
        async def probe():
            return list(self.live.values())
        async def load(key):
            self.live[key] = {'id': key, 'busy': 0}
        self.g = SharedCoordinator(reg, 'http://unused', {}, 'x'*32,
                                   self.temp.name, probe=probe, loader=load)
        self.addCleanup(self.g.store.close)
        self.req = make_mocked_request('POST', '/v1/chat/completions')
        self.flash = next(k for k,p in self.g.profiles.items() if p['model'] == MODEL_NAME)
        self.regular = next(k for k,p in self.g.profiles.items() if p['model'] == 'qwen3.8-smart-q4-256k')
        if MODEL_NAME not in self.g.reg['enabled_models']:
            self.g.reg['enabled_models'].append(MODEL_NAME)

    async def test_unvalidated_flash_is_rejected_before_loading(self):
        self.g.reg['enabled_models'].remove(MODEL_NAME)
        with self.assertRaises(web.HTTPException) as caught:
            await self.g.reserve(self.req, self.flash, 'interactive')
        self.assertEqual(caught.exception.status, 423)
        self.assertEqual(self.live, {})

    async def test_three_full_windows_and_fourth_rejected(self):
        for _ in range(3):
            await self.g.reserve(self.req, self.flash, 'interactive')
        self.assertEqual(sum(r['context_tokens'] for r in self.g.requests.values()), 786432)
        with self.assertRaises(web.HTTPTooManyRequests):
            await self.g.reserve(self.req, self.flash, 'interactive')
        self.assertEqual(len(self.g.requests), 3)

    async def test_exclusive_in_both_loading_orders(self):
        for first, second in ((self.flash, self.regular), (self.regular, self.flash)):
            self.g.requests.clear()
            self.live.clear()
            await self.g.inspect()
            await self.g.reserve(self.req, first, 'interactive')
            with self.assertRaises(web.HTTPConflict):
                await self.g.reserve(self.req, second, 'interactive')

    async def test_recurrent_pool_does_not_inherit_unverified_idle_erase(self):
        await self.g.reserve(self.req, self.flash, 'interactive')
        self.g.requests.clear()
        self.g.clear_idle_kv = AsyncMock()
        await self.g.reserve(self.req, self.flash, 'interactive')
        self.g.clear_idle_kv.assert_not_awaited()

    async def test_flash_preserves_client_prefix_cache_choice(self):
        for value in (True, False):
            self.g.backend_post = AsyncMock(side_effect=[{'prompt': 'hello'}, {'tokens': [1]}])
            body = await self.g.prepare_body({'messages': [{'role': 'user', 'content': 'hello'}],
                                               'cache_prompt': value}, self.flash, '/v1/chat/completions')
            self.assertIs(body['cache_prompt'], value)

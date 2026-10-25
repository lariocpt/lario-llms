import json
import unittest

from scripts.prepare_placement import ROOT, prepare
from shared.serving.catalog import HARDWARE, profiles, render_backend
from shared.placements import inventory


class PlacementTests(unittest.TestCase):
    def test_bundled_page_inventory_matches_manifests(self):
        bundled=json.loads((ROOT/'shared/serving/web/placements.json').read_text())
        self.assertEqual(bundled, inventory())

    def test_radeon_has_one_canonical_owner(self):
        reg = json.loads((ROOT/'geekom7900xt/models.json').read_text())
        self.assertEqual(reg['host'], 'l-dev-ai')
        self.assertEqual(reg['aliases'], ['geekom7900xt'])
        self.assertIn('geekom7900xt', HARDWARE)
        self.assertNotIn('winmax7900xt', HARDWARE)
        self.assertNotIn('gkm7900xt', HARDWARE)
        self.assertEqual(len(profiles(reg)), 3)
        self.assertNotIn('geekom7900xt', [p['hardware'] for p in inventory()])

    def test_sessions_preserve_profile_geometry_after_rename(self):
        from shared.serving.clients import migrate_radeon_profile
        reg = json.loads((ROOT/'geekom7900xt/models.json').read_text())
        entries = profiles(reg)
        for key in entries:
            for old in ('7900xt', 'gkm7900xt', 'winmax7900xt'):
                previous = old + key[len('geekom7900xt'):].rsplit('.', 1)[0] + '.oldrevision'
                self.assertEqual(migrate_radeon_profile(previous, entries), key)
        with self.assertRaises(ValueError):
            migrate_radeon_profile('muse-glimmer@missing', entries)

    def test_arc_candidates_fit_calculated_budget_but_are_not_live(self):
        from arcB70.budget import build_registry, estimate, max_context, max_slots
        self.assertNotIn('arcB70', HARDWARE)
        reg=prepare('arcB70')
        self.assertEqual(reg,build_registry())
        self.assertEqual(reg['deployment_status'],'active-partial')
        self.assertEqual(len(profiles(reg)),13)
        for role in ('smart-q4','medium'):
            self.assertEqual(reg['models'][f'qwen3.8-{role}-128k']['slots'],5)
            self.assertEqual(reg['models'][f'qwen3.8-{role}-256k']['slots'],2)
        for name, spec in reg['models'].items():
            args=spec['args']
            self.assertIn('Q4_K_XL',spec['weights']['filename'])
            self.assertEqual(args[args.index('-ctk')+1],'q4_0')
            self.assertEqual(args[args.index('-ctv')+1],'q4_0')
            self.assertEqual(args[args.index('--fit')+1],'off')
            family='muse' if name.startswith('muse-') else 'qwen'
            ram='--no-kv-offload' in args
            self.assertEqual(spec['memory_estimate'],estimate(family,spec['context'],spec['slots'],ram))
            self.assertLessEqual(spec['memory_estimate']['estimated_vram_with_reserve_gib'],32)
            if not ram:
                self.assertGreater(estimate(family,spec['context'],spec['slots']+1)['estimated_vram_with_reserve_gib'],32)
            if 'smart' in name:
                kwargs=json.loads(args[args.index('--chat-template-kwargs')+1])
                self.assertEqual(kwargs['reasoning_effort'],'xhigh')
            if family=='muse':
                self.assertEqual(args[args.index('-ctkd')+1],'q4_0')
                self.assertEqual(args[args.index('-ctvd')+1],'q4_0')
                self.assertIn('draft_weights',spec)
                self.assertNotIn('--swa-full',args)
            if spec['context']>spec['native_context']:
                self.assertEqual(args[args.index('--rope-scaling')+1],'yarn')
                self.assertEqual(float(args[args.index('--rope-scale')+1]),spec['context']/spec['native_context'])
        self.assertEqual(max_slots('muse',262144),12)
        self.assertEqual(max_slots('muse',524288),6)
        self.assertEqual(max_context('muse'),3473408)
        self.assertEqual(max_context('muse',2),1736704)
        self.assertGreater(estimate('muse',max_context('muse',2)+32768,2)['estimated_vram_with_reserve_gib'],32)
        client=json.loads((ROOT/'arcB70/opencode.prepared.json').read_text())
        self.assertNotIn('arcB70',client['disabled_providers'])
        self.assertEqual(len(client['provider']['arcB70']['whitelist']),6)
        for key,p in profiles(reg).items():
            entry=client['provider']['arcB70']['models'][key]
            self.assertEqual(entry['limit']['context'],p['context']-4096)
            self.assertEqual(entry['name'],p['name'])

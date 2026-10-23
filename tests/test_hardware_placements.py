import json
import unittest

from scripts.prepare_placement import ROOT, prepare
from shared.serving.catalog import HARDWARE, profiles, render_backend
from shared.placements import inventory


class PlacementTests(unittest.TestCase):
    def test_bundled_page_inventory_matches_manifests(self):
        bundled=json.loads((ROOT/'shared/serving/web/placements.json').read_text())
        self.assertEqual(bundled, inventory())

    def test_candidates_preserve_models_and_have_distinct_fixed_ids(self):
        live = json.loads((ROOT/'7900xt/models.json').read_text())
        identities = []
        for name, host in [('gkm7900xt', 'l-dev-ai'),
                           ('winmax7900xt', 'cachyos-mini-mobile')]:
            candidate = prepare(name)
            self.assertEqual(candidate['models'], live['models'])
            self.assertEqual(candidate['presets'], live['presets'])
            self.assertEqual(candidate['device_identity'], live['device_identity'])
            self.assertEqual(candidate['host'], host)
            entries = profiles(candidate)
            self.assertEqual(len(entries), 3)
            self.assertTrue(all(p.startswith(name+'.') for p in entries))
            self.assertIn(candidate['backend_key_file'], render_backend(candidate))
            identities.append(set(entries))
        self.assertFalse(identities[0] & identities[1])

    def test_same_card_is_exclusive_and_not_advertised_twice(self):
        placements = [json.loads((ROOT/name/'placement.json').read_text())
                      for name in ('gkm7900xt', 'winmax7900xt')]
        self.assertEqual(placements[0]['physical_resource'], placements[1]['physical_resource'])
        for a, b in (placements, placements[::-1]):
            self.assertIn(b['hardware'], a['exclusive_with'])
            self.assertNotIn(a['hardware'], HARDWARE)

    def test_arc_candidates_fit_calculated_budget_but_are_not_live(self):
        self.assertNotIn('arcB70', HARDWARE)
        reg=prepare('arcB70')
        self.assertEqual(reg['deployment_status'],'prepared-not-deployed')
        self.assertEqual(len(profiles(reg)),14)
        self.assertEqual(reg['models']['qwen3.8-smart-128k']['slots'],3)
        self.assertEqual(reg['models']['qwen3.8-smart-q4-128k']['slots'],5)
        self.assertEqual(reg['models']['qwen3.8-smart-q4-256k']['slots'],2)
        for name, spec in reg['models'].items():
            if 'smart' in name:
                kwargs=json.loads(spec['args'][spec['args'].index('--chat-template-kwargs')+1])
                self.assertEqual(kwargs['reasoning_effort'],'xhigh')
            budget=spec['memory_estimate']
            kv=spec['args'][spec['args'].index('-ctk')+1]
            cache=spec['context']*spec['slots']*17*4*512*(18/32 if kv=='q4_0' else 34/32)/2**30
            self.assertEqual(budget['attention_cache_gib'],cache)
            self.assertLessEqual(budget['estimated_vram_with_reserve_gib'],32)
            if spec['context']==524288 and spec['slots']==2:
                self.assertIn('--no-kv-offload',spec['args'])
                self.assertEqual(budget['cache_device'],'CPU')
            if spec['context']>262144:
                self.assertIn('--rope-scaling',spec['args'])
        client=json.loads((ROOT/'arcB70/opencode.prepared.json').read_text())
        self.assertIn('arcB70',client['disabled_providers'])
        for key,p in profiles(reg).items():
            self.assertEqual(client['provider']['arcB70']['models'][key]['limit']['context'],p['context']-4096)

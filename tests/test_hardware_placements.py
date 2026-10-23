import json
import unittest

from scripts.prepare_placement import ROOT, prepare
from shared.serving.catalog import HARDWARE, profiles, render_backend


class PlacementTests(unittest.TestCase):
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

    def test_arc_cannot_generate_an_unverified_registry(self):
        self.assertNotIn('arcB70', HARDWARE)
        with self.assertRaisesRegex(ValueError, 'must be verified'):
            prepare('arcB70')

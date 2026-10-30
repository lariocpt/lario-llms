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

    def test_arc_has_one_enabled_native_vision_profile(self):
        from arcB70.budget import build_registry
        registry=prepare('arcB70')
        self.assertEqual(registry,build_registry())
        self.assertEqual(registry['deployment_status'],'active')
        entries=profiles(registry)
        self.assertEqual(len(entries),1)
        profile=next(iter(entries.values()))
        self.assertEqual((profile['context'],profile['slots'],profile['vision']),(172032,2,True))
        self.assertNotIn('shared_pool',profile)
        self.assertEqual(registry['enabled_models'],[profile['model']])
        client=json.loads((ROOT/'arcB70/opencode.prepared.json').read_text())
        self.assertEqual(client['provider']['arcB70']['whitelist'],list(entries))
        self.assertEqual(client['provider']['arcB70']['models'][profile['id']]['modalities']['input'],['text','image'])

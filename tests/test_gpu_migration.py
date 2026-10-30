import json
from pathlib import Path
import shlex
import unittest

from arcB70.single_vision import build_registry as arc_registry
from rtx5080.strata.profile import build_registry as rtx_registry
from shared.serving.catalog import profiles, render_backend


class MigrationTests(unittest.TestCase):
    def test_arc_is_two_native_vision_slots_without_a_shared_pool(self):
        registry = arc_registry()
        self.assertNotIn('shared_serving', registry)
        entries = list(profiles(registry).values())
        self.assertEqual(len(entries), 1)
        self.assertEqual((entries[0]['context'], entries[0]['slots'], entries[0]['vision']), (172032, 2, True))
        self.assertEqual(registry['serving_engine'], 'vllm')
        self.assertNotIn('/mnt/xfs/', registry['binary'])

    def test_rtx_compiles_distinct_runtime_commands_in_one_exclusive_group(self):
        import yaml
        registry = rtx_registry()
        config = yaml.safe_load(render_backend(registry))
        entries = profiles(registry)
        self.assertEqual(len(entries), 3)
        for key, profile in entries.items():
            command = shlex.split(config['models'][key]['cmd'])
            expected = profile['spec'].get('binary', registry['binary'])
            self.assertEqual(command[0], expected)
            self.assertEqual(command[command.index('--parallel')+1], '1')
            if profile['model'] == 'qwen38-flash-nvfp4':
                self.assertEqual(command[command.index('-c')+1], '131072')
                self.assertTrue(profile['spec']['allow_interactive'])
                self.assertTrue(profile['vision'])
                self.assertIn('--mmproj',command)
        self.assertTrue(config['groups']['hardware']['exclusive'])
        self.assertEqual(set(config['groups']['hardware']['members']), set(entries))

    def test_regeneration_cannot_restore_retired_b70_choices(self):
        from arcB70.budget import build_registry
        self.assertEqual(set(build_registry()['models']), {'qwen3.8-gptq-int4'})


if __name__ == '__main__':
    unittest.main()

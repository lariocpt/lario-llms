import json
from pathlib import Path
import unittest

from shared.admission.provision import client_limits
from shared.modelctl import effective_models

ROOT = Path(__file__).resolve().parents[1]


class ClientContextLimitsTests(unittest.TestCase):
    def test_limits_fit_every_available_profile_without_vision_capping_text(self):
        for hardware in ('geekom', '7900xt', 'rtx5080'):
            reg = json.loads((ROOT/hardware/'models.json').read_text())
            limits = client_limits(reg)
            for preset in reg['presets']:
                if reg['presets'][preset].get('disabled_reason'):continue
                for model, spec in effective_models(reg,preset).items():
                    self.assertLessEqual(limits[hardware]+4096,spec['context'])
                    if model in limits:self.assertLessEqual(limits[model]+4096,spec['context'])
            if hardware=='rtx5080':
                self.assertEqual(limits[hardware],28672)
                self.assertEqual(limits['qwen3.8'],61440)
            if hardware=='7900xt':
                self.assertEqual(limits[hardware],61440)
                self.assertEqual(limits['qwen3.8'],61440)


if __name__ == '__main__':unittest.main()

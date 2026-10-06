import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from aiohttp import web

from shared import modelctl
from shared.admission.provision import client_limits
from shared.admission import server
from shared.model_tools.export_choices import export_opencode_profiles

ROOT = Path(__file__).resolve().parents[1]


class ProfileRoutesTests(unittest.TestCase):
    def test_client_profile_limits_match_the_generated_server_routes(self):
        providers = export_opencode_profiles()['provider']
        for hardware, provider in providers.items():
            reg = json.loads((ROOT/hardware/'models.json').read_text())
            for route, entry in provider['models'].items():
                model,preset = route.split('@',1)
                spec = modelctl.effective_models(reg,preset)[model]
                self.assertIn(route, modelctl.model_aliases(reg,model,preset))
                self.assertEqual(entry['limit']['context']+4096,spec['context'])
        snapshot = json.loads((ROOT/'shared/model_tools/opencode_profile_models.json').read_text())
        self.assertEqual(snapshot,export_opencode_profiles())

    def test_large_flash_route_is_unavailable_under_smaller_geometry(self):
        reg = json.loads((ROOT/'geekom/models.json').read_text())
        large = modelctl.render(reg, 'qwen38-flash', 'balanced')
        small = modelctl.render(reg, 'qwen38-flash', 'flash-128k')
        self.assertIn('"qwen38-flash@balanced"', large)
        self.assertNotIn('"qwen38-flash@balanced"', small)
        self.assertIn('"qwen38-flash@flash-128k"', small)
        self.assertNotIn('"qwen38-flash@flash-128k"', large)
        limits = client_limits(reg)
        self.assertEqual(limits['qwen38-flash@balanced'], 241664)
        self.assertEqual(limits['qwen38-flash@flash-128k'], 126976)
        self.assertEqual(limits['geekom'], 118784)


class ProfileAdmissionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.reg = json.loads((ROOT/'geekom/models.json').read_text())
        root = Path(self.temp.name)
        (root/self.reg['state']).write_text('qwen38-flash\n')
        (root/'.geekom-selection.json').write_text(
            json.dumps({'model':'qwen38-flash','preset':'balanced'}))
        self.patches = [patch.object(modelctl, 'ROOT', root), patch.object(server, 'ROOT', root)]
        for item in self.patches:item.start()
        self.state = {'model':'qwen38-flash','context':245760,'slots':3,
                      'reserved':2,'busy':0,'generation':'fixture'}
        async def probe():return self.state.copy()
        self.gate = server.Admission(self.reg, 'http://unused', {}, '', probe=probe)

    async def asyncTearDown(self):
        for item in reversed(self.patches):item.stop()
        self.temp.cleanup()

    async def test_exact_live_large_profile_is_accepted_without_network(self):
        result = await self.gate.acquire('interactive', 'qwen38-flash@balanced')
        self.assertEqual(result['context'],245760)
        self.assertEqual(self.gate.active['interactive'],1)

    async def test_saved_large_profile_cannot_hide_running_128k_geometry(self):
        self.state.update(context=131072,slots=6)
        with self.assertRaises(web.HTTPConflict):
            await self.gate.acquire('interactive', 'qwen38-flash@balanced')
        self.assertEqual(sum(self.gate.active.values()),0)

    async def test_other_profile_cannot_trigger_swap(self):
        with self.assertRaises(web.HTTPConflict):
            await self.gate.acquire('interactive', 'qwen38-flash@flash-128k')
        self.assertEqual(sum(self.gate.active.values()),0)


if __name__ == '__main__':unittest.main()

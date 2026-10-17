import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from shared import lifecycle, modelctl
from shared.gpu import radeon_device
from shared.model_tools import owner

ROOT = Path(__file__).resolve().parents[1]


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.reg = json.loads((ROOT/'7900xt/models.json').read_text())
        (self.root/'7900xt').mkdir()
        (self.root/'7900xt/models.json').write_text(json.dumps(self.reg))
        for item in (patch.object(modelctl, 'ROOT', self.root),
                     patch.object(owner, 'ROOT', self.root),
                     patch.dict(os.environ, {'XDG_RUNTIME_DIR': str(self.root/'run'), 'LARIO_ADMISSION_ENABLED':'1'}),
                     patch.object(modelctl, 'load_runtime'), patch.object(modelctl, 'assert_not_held'),
                     patch.object(modelctl, 'assert_device_ready')):
            item.start(); self.addCleanup(item.stop)
        modelctl.save_selection(self.reg, 'qwen3.8', 'fast-64k')
        self.inactive = {'ActiveState':'inactive', 'SubState':'dead', 'InvocationID':'', 'LoadState':'loaded'}

    def test_busy_stop_never_stops_or_records_manual_stop(self):
        with patch.object(lifecycle, 'service_state', return_value={**self.inactive, 'ActiveState':'active'}), \
             patch.object(modelctl, 'admission_admin') as admission, \
             patch.object(modelctl, 'assert_idle', side_effect=RuntimeError('busy')), \
             patch.object(modelctl, 'stop_service') as stop:
            with self.assertRaisesRegex(RuntimeError, 'busy'):
                lifecycle.operate(self.reg, 'stop')
        admission.assert_called_once_with(self.reg, 'drain')
        stop.assert_not_called()
        self.assertFalse(lifecycle.stop_marker(self.reg).exists())

    def test_stopped_service_can_stop_without_connected_hardware(self):
        with patch.object(lifecycle, 'service_state', return_value=self.inactive), \
             patch.object(modelctl, 'stop_service') as stop:
            self.assertTrue(lifecycle.operate(self.reg, 'stop'))
            self.assertFalse(lifecycle.operate(self.reg, 'stop'))
        stop.assert_not_called()
        self.assertTrue(lifecycle.stop_marker(self.reg).exists())

    def test_legacy_stop_refuses_without_a_gateway_to_close_the_request_race(self):
        with patch.dict(os.environ, {'LARIO_ADMISSION_ENABLED':'0'}), \
             patch.object(lifecycle, 'service_state', return_value={**self.inactive, 'ActiveState':'active'}), \
             patch.object(modelctl, 'stop_service') as stop:
            with self.assertRaisesRegex(RuntimeError, 'admission gateway'):
                lifecycle.operate(self.reg, 'stop')
        stop.assert_not_called()

    def test_start_refuses_missing_card_and_preserves_stop_intent(self):
        modelctl.atomic(lifecycle.stop_marker(self.reg), 'stopped')
        with patch.object(lifecycle, 'service_state', return_value=self.inactive), \
             patch.object(modelctl, 'assert_device_ready', side_effect=RuntimeError('absent')), \
             patch.object(lifecycle.subprocess, 'run') as run:
            with self.assertRaisesRegex(RuntimeError, 'absent'):
                lifecycle.operate(self.reg, 'start', True)
        run.assert_not_called()
        self.assertTrue(lifecycle.stop_marker(self.reg).exists())

    def test_experimental_saved_selection_needs_opt_in(self):
        with patch.object(lifecycle, 'service_state', return_value=self.inactive), \
             patch.object(lifecycle.subprocess, 'run') as run:
            with self.assertRaisesRegex(RuntimeError, 'experimental'):
                lifecycle.operate(self.reg, 'start')
        run.assert_not_called()

    def test_start_restores_saved_configuration_and_resumes_admission(self):
        modelctl.atomic(lifecycle.stop_marker(self.reg), 'stopped')
        with patch.object(lifecycle, 'service_state', return_value=self.inactive), \
             patch.object(lifecycle.subprocess, 'run') as run, \
             patch.object(modelctl, 'runtime_budget', side_effect=RuntimeError('cold')), \
             patch.object(modelctl, 'warm') as warm, patch.object(modelctl, 'admission_admin') as admission:
            self.assertTrue(lifecycle.operate(self.reg, 'start', True))
        self.assertEqual(run.call_args.args[0], ['systemctl','--user','start','7900xt.service'])
        self.assertFalse(lifecycle.stop_marker(self.reg).exists())
        self.assertIn('65536', (self.root/self.reg['config']).read_text())
        warm.assert_called_once_with(self.reg, 'qwen3.8')
        admission.assert_called_once_with(self.reg, 'resume')

    def test_stale_mcp_token_never_reaches_service_control(self):
        with patch.object(owner.socket, 'gethostname', return_value=self.reg['host']), \
             patch.object(lifecycle, 'snapshot', return_value={'lifecycle_token':'a'*64}), \
             patch.object(lifecycle, 'operate') as operate:
            with self.assertRaisesRegex(RuntimeError, 'changed'):
                owner.operate({'operation':'start','hardware':'7900xt','lifecycle_token':'b'*64})
        operate.assert_not_called()

    def test_stopped_owner_status_supplies_lifecycle_token_without_inference(self):
        with patch.object(lifecycle, 'snapshot', return_value={'service':'inactive','lifecycle_token':'a'*64}), \
             patch.object(modelctl, 'api') as api:
            status = owner.status(self.reg)
        self.assertFalse(status['ready'])
        self.assertEqual(status['agents'], 0)
        self.assertEqual(status['lifecycle_token'], 'a'*64)
        api.assert_not_called()


class GPUIdentityTests(unittest.TestCase):
    def test_igpu_is_rejected_and_render_node_is_resolved_each_boot(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); pci=root/'pci'; dri=root/'dri'
            pci.mkdir(); dri.mkdir(); (root/'kfd').touch()
            identity={'device_id':'0x744c','unique_id':'target','minimum_vram_bytes':19000000000}
            def card(name, device_id, unique, render, memory):
                path=pci/name; (path/'drm'/render).mkdir(parents=True)
                for key, value in {'vendor':'0x1002','device':device_id,'unique_id':unique,'mem_info_vram_total':str(memory)}.items():
                    (path/key).write_text(value)
                (path/'driver').symlink_to(root/'drivers/amdgpu')
                (dri/render).touch()
            card('0000:c8:00.0', '0x1900', 'internal', 'renderD128', 6000000000)
            with self.assertRaisesRegex(RuntimeError, 'absent'):
                radeon_device(identity, pci, dri, root/'kfd')
            card('0000:03:00.0', '0x744c', 'target', 'renderD129', 21458059264)
            result=radeon_device(identity, pci, dri, root/'kfd')
            self.assertEqual(result['render'], str(dri/'renderD129'))


class MCPDiscoveryTests(unittest.TestCase):
    def test_only_management_clients_expose_lifecycle_tools(self):
        for enabled in ('0','1'):
            with patch.dict(os.environ, {'LARIO_MODELS_ALLOW_SWITCH':enabled}):
                spec=importlib.util.spec_from_file_location('lifecycle_client', ROOT/'shared/model_tools/model_tools.py')
                module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
            tools={tool['name'] for tool in module.TOOLS}
            self.assertEqual('model_start' in tools, enabled=='1')
            self.assertEqual('model_stop' in tools, enabled=='1')
            with self.assertRaises(ValueError):
                module.call('model_stop', {'hardware':'7900xt','lifecycle_token':'a'*64,'force':True})


if __name__ == '__main__':
    unittest.main()

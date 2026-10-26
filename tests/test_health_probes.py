"""Monitoring remains available when every inference slot is occupied."""
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch

from shared import modelctl, container_monitor
from shared.serving.catalog import profiles
from shared.serving.gateway import Coordinator

ROOT = Path(__file__).resolve().parents[1]


class ResidentMonitoringTests(unittest.TestCase):
    def test_native_hardware_reads_authenticated_child_not_proxy(self):
        for hardware in ('geekom', 'arcB70', 'rtx5080'):
            with self.subTest(hardware=hardware):
                reg = json.loads((ROOT/hardware/'models.json').read_text())
                item = {'model':'busy-model', 'proxy':'http://127.0.0.1:5801'}
                with patch.dict(os.environ, {'LARIO_ADMISSION_ENABLED':'1', 'LARIO_BACKEND_KEY':'test-key'}), \
                        patch.object(modelctl, 'api', side_effect=AssertionError('proxy monitoring forbidden')), \
                        patch.object(modelctl.urllib.request, 'urlopen') as request:
                    request.return_value.__enter__.return_value = io.BytesIO(b'[{"is_processing":true}]')
                    self.assertEqual(modelctl.resident_slots(reg, item), [{'is_processing':True}])
                    sent = request.call_args.args[0]
                    self.assertEqual(sent.full_url, item['proxy']+'/slots')
                    self.assertEqual(sent.get_header('Authorization'), 'Bearer test-key')

    def test_container_uses_private_child_and_checks_residency_twice(self):
        reg = json.loads((ROOT/'geekom7900xt/models.json').read_text())
        item = {'model':'busy-model', 'proxy':'http://127.0.0.1:5802'}
        with patch.object(modelctl, 'current', return_value=item['model']) as current, \
                patch.object(container_monitor, 'resident_slots', return_value=[{'is_processing':True}]) as monitor, \
                patch.object(modelctl, 'api', side_effect=AssertionError('proxy monitoring forbidden')):
            self.assertEqual(modelctl.resident_slots(reg,item), [{'is_processing':True}])
            monitor.assert_called_once_with(reg, item['proxy']+'/slots')
            self.assertEqual(current.call_count, 2)
        with patch.object(modelctl, 'current', side_effect=[item['model'],'replacement']), \
                patch.object(container_monitor, 'resident_slots', return_value=[]):
            with self.assertRaisesRegex(RuntimeError, 'resident changed'):
                modelctl.resident_slots(reg,item)

    def test_container_exec_uses_registered_store_and_keeps_credentials_private(self):
        reg = json.loads((ROOT/'geekom7900xt/models.json').read_text())
        with patch.object(container_monitor.subprocess, 'run', return_value=Mock(stdout='[{"is_processing":true}]')) as run:
            self.assertEqual(container_monitor.resident_slots(reg,'http://127.0.0.1:5802/slots'), [{'is_processing':True}])
            args = run.call_args.args[0]
            self.assertEqual(args[:3], ['podman','--root','/mnt/AI_Models/containers/geekom7900xt'])
            self.assertEqual(args[args.index('exec')+1],reg['container'])
            self.assertEqual(args[-2:],['http://127.0.0.1:5802/slots',reg['backend_key_file']])
            self.assertIn('read_text()',args[-3])
            self.assertTrue(run.call_args.kwargs['check'])
            self.assertEqual(run.call_args.kwargs['timeout'],8)

    def test_ti_container_monitor_uses_xfs_store(self):
        reg = json.loads((ROOT/'rtx3060ti/models.json').read_text())
        with patch.object(container_monitor.subprocess, 'run', return_value=Mock(stdout='[{"is_processing":true}]')) as run:
            self.assertEqual(container_monitor.resident_slots(reg,'http://127.0.0.1:5801/slots'), [{'is_processing':True}])
            args = run.call_args.args[0]
            self.assertEqual(args[:3], ['podman','--root','/mnt/xfs/AI_Models/containers/rtx3060ti'])
            self.assertEqual(args[args.index('exec')+1],reg['container'])



class CoordinatorMonitoringTests(unittest.IsolatedAsyncioTestCase):
    async def test_busy_models_reconcile_real_slots_without_passthrough(self):
        for hardware in ('geekom', 'geekom7900xt', 'arcB70', 'rtx5080', 'rtx3060ti'):
            with self.subTest(hardware=hardware), tempfile.TemporaryDirectory() as directory:
                reg = json.loads((ROOT/hardware/'models.json').read_text())
                gate = Coordinator(reg,'http://unused',{},'test-key',directory=directory)
                self.addCleanup(gate.store.close)
                profile = next(iter(profiles(reg).values()))
                item = {'model':profile['id'], 'state':'ready', 'proxy':'http://127.0.0.1:5801',
                        'cmd':f"llama-server -c {profile['context']*profile['slots']} --parallel {profile['slots']} -ctk {profile['cache_k']} -ctv {profile['cache_v']}"}
                async def get(path):
                    self.assertEqual(path,'/running')
                    return {'running':[item]}
                gate.get = get
                gate.requests = {'tracked':{'phase':'running'}}
                for uncertain in (False, True):
                    gate.uncertain = uncertain
                    slots = [{'is_processing':True} for _ in range(profile['slots'])]
                    with patch.object(modelctl,'assert_device_ready'), patch.object(modelctl,'resident_slots',return_value=slots) as monitor:
                        state = await gate.inspect()
                    self.assertEqual(state['busy'],profile['slots'])
                    monitor.assert_called_once_with(reg,item)
                with patch.object(modelctl,'assert_device_ready'), patch.object(modelctl,'resident_slots',side_effect=RuntimeError('monitor failed')):
                    with self.assertRaisesRegex(RuntimeError,'monitor failed'):
                        await gate.inspect()


if __name__ == '__main__':
    unittest.main()

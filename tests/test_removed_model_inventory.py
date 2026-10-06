import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from shared.model_inventory import removed_radeon


class RemovedInventoryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.devices=Path(self.temp.name)
        self.reg={'aliases':['7900xt'],'container':'agent-llm'}

    def inspect(self,running=False,restart='no'):
        return json.dumps([{'State':{'Running':running},'HostConfig':{'RestartPolicy':{'Name':restart}}}])

    def test_absent_stopped_device_keeps_registry_weights_protected(self):
        with patch('shared.model_inventory.subprocess.check_output',return_value=self.inspect()):
            result=removed_radeon(self.reg,self.devices)
        self.assertTrue(result['device_absent']);self.assertEqual(result['running'],[])

    def test_present_amd_card_requires_live_inspection(self):
        device=self.devices/'0000:03:00.0';device.mkdir()
        (device/'vendor').write_text('0x1002');(device/'class').write_text('0x030000')
        with patch('shared.model_inventory.subprocess.check_output') as inspect:
            with self.assertRaisesRegex(RuntimeError,'present'):removed_radeon(self.reg,self.devices)
        inspect.assert_not_called()

    def test_running_or_autostarting_container_refuses_offline_audit(self):
        for running,restart in ((True,'no'),(False,'unless-stopped')):
            with self.subTest(running=running,restart=restart):
                with patch('shared.model_inventory.subprocess.check_output',return_value=self.inspect(running,restart)):
                    with self.assertRaisesRegex(RuntimeError,'stopped'):removed_radeon(self.reg,self.devices)

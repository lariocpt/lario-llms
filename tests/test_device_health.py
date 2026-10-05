import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch
from shared import modelctl as ctl


class DeviceHealthTests(unittest.TestCase):
    def setUp(self):self.reg=json.loads((ctl.ROOT/'rtx5080/models.json').read_text())

    def test_nvml_fault_refuses_before_switch_or_model_request(self):
        with patch.object(ctl.socket,'gethostname',return_value='bigcachy'), patch.object(ctl.subprocess,'run',return_value=subprocess.CompletedProcess([],6,'','GPU unavailable')) as commands, patch.object(ctl,'api') as api:
            with self.assertRaisesRegex(RuntimeError,'device health failed'):ctl.switch(self.reg,'qwen3.8')
            with self.assertRaisesRegex(RuntimeError,'device health failed'):ctl.warm(self.reg,'qwen3.8')
            api.assert_not_called()
            self.assertTrue(all(call.args[0][0]=='nvidia-smi' for call in commands.call_args_list))

    def test_healthy_nvidia_probe_does_not_mutate_hardware(self):
        with patch.object(ctl.socket,'gethostname',return_value='bigcachy'), patch.object(ctl.subprocess,'run',return_value=subprocess.CompletedProcess([],0,'NVIDIA GeForce RTX 5080\n','')) as commands:
            ctl.assert_device_ready(self.reg)
        self.assertEqual(commands.call_args.args[0],['nvidia-smi','--query-gpu=name','--format=csv,noheader'])

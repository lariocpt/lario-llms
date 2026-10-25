import importlib.util
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch, Mock

from shared import modelctl
from shared.backend_watch import HARDWARE, reconcile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('ti_runtime', ROOT/'rtx3060ti/runtime.py')
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


class OptionalGPUStartupTests(unittest.TestCase):
    def setUp(self):
        self.reg = json.loads((ROOT/'rtx3060ti/models.json').read_text())

    def test_missing_driver_is_a_recoverable_wait_and_gateway_stays_up(self):
        self.assertIn('rtx3060ti', HARDWARE)
        with patch('shared.gpu.nvidia_device', side_effect=subprocess.CalledProcessError(9, 'nvidia-smi')), \
             patch('shared.backend_watch.ensure_unit', return_value='active') as unit, \
             patch('shared.backend_watch.off_marker') as off, \
             patch('shared.backend_watch.stop_marker') as stopped, \
             patch.object(modelctl, 'assert_not_held'):
            off.return_value.exists.return_value = False
            stopped.return_value.exists.return_value = False
            result = reconcile(self.reg)
        self.assertEqual(result['backend'], 'waiting')
        unit.assert_called_once_with('lario-admission@rtx3060ti.service', unittest.mock.ANY)

    def test_reconnected_gpu_can_start_without_restarting_active_services(self):
        with patch('shared.gpu.nvidia_device') as gpu, \
             patch('shared.backend_watch.ensure_unit', side_effect=['active', 'start-requested']) as unit, \
             patch('shared.backend_watch.off_marker') as off, \
             patch('shared.backend_watch.stop_marker') as stopped, \
             patch.object(modelctl, 'assert_not_held'):
            off.return_value.exists.return_value = False
            stopped.return_value.exists.return_value = False
            result = reconcile(self.reg)
        self.assertEqual(result['backend'], 'start-requested')
        gpu.assert_called_once_with(self.reg['device_identity'])
        self.assertEqual(unit.call_args.args[0], 'rtx3060ti.service')

    def test_durable_off_blocks_runtime_even_with_gpu_connected(self):
        with patch.object(runtime.sys, 'argv', ['runtime.py', 'check']), \
             patch.object(runtime, 'stop_marker', return_value=Mock(exists=lambda: False)), \
             patch.object(runtime, 'off_marker', return_value=Mock(exists=lambda: True)), \
             patch.object(runtime, 'nvidia_device') as gpu, \
             patch.object(runtime.subprocess, 'run') as run:
            with self.assertRaises(RuntimeError):
                runtime.main()
        gpu.assert_not_called()
        run.assert_not_called()


if __name__ == '__main__':
    unittest.main()

import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from shared import modelctl
from shared.gpu import HardwareUnavailable

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('oculink_guard', ROOT/'rtx3060ti/oculink_guard.py')
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


class OCuLinkGuardTests(unittest.TestCase):
    def fixture(self, folder):
        base=Path(folder); pci=base/'bus/pci/devices';pci.mkdir(parents=True)
        bridge=base/'devices/pci0000:00/0000:00:01.1';bridge.mkdir(parents=True)
        (bridge/'power').mkdir();(bridge/'power/control').write_text('auto\n')
        for name,device in [('0000:01:00.0','0x2489'),('0000:01:00.1','0x228b')]:
            path=bridge/name;path.mkdir();(pci/name).symlink_to(path)
            (path/'vendor').write_text('0x10de\n');(path/'device').write_text(device+'\n')
            (path/'power').mkdir();(path/'power/control').write_text('auto\n')
            (path/'link').mkdir()
            for flag in guard.ASPM:(path/'link'/flag).write_text('1\n')
        other=base/'devices/internal-amd';other.mkdir();(other/'vendor').write_text('0x1002\n');(other/'device').write_text('0x1900\n')
        (other/'power').mkdir();(other/'power/control').write_text('auto\n');(pci/'0000:c6:00.0').symlink_to(other)
        return pci,other

    def test_guard_targets_only_external_gpu_audio_and_parent(self):
        with tempfile.TemporaryDirectory() as folder:
            pci,other=self.fixture(folder)
            before=guard.configure(pci)
            self.assertTrue(before['present']);self.assertFalse(before['ready'])
            after=guard.configure(pci,apply=True)
            self.assertTrue(after['ready'])
            self.assertEqual((other/'power/control').read_text(),'auto\n')
            self.assertTrue(all(row['expected']==row['actual'] for row in after['settings']))
            # Applying twice should be stable and require no device reset.
            self.assertTrue(guard.configure(pci,apply=True)['ready'])

    def test_absent_optional_gpu_is_not_replaced_by_igpu(self):
        with tempfile.TemporaryDirectory() as folder:
            result=guard.configure(Path(folder),apply=True)
            self.assertFalse(result['present']);self.assertEqual(result['settings'],[])

    def test_ambiguous_gpu_refuses_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            pci,_=self.fixture(folder)
            extra=pci/'0000:02:00.0';extra.mkdir()
            (extra/'vendor').write_text('0x10de');(extra/'device').write_text('0x2489')
            with self.assertRaisesRegex(RuntimeError,'expected one'):
                guard.configure(pci,apply=True)
            self.assertEqual((pci/'0000:01:00.0'/'power/control').read_text(),'auto\n')

    def test_lost_driver_is_reported_as_hardware_unavailable(self):
        reg={'aliases':['rtx3060ti'],'device_identity':{}}
        with patch('shared.gpu.nvidia_device',side_effect=subprocess.CalledProcessError(6,'nvidia-smi')):
            with self.assertRaisesRegex(HardwareUnavailable,'OCuLink'):
                modelctl.assert_device_ready(reg)


if __name__ == '__main__':unittest.main()

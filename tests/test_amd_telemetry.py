import tempfile
import unittest
from pathlib import Path

from benchmarks.telemetry import amd_memory


class AmdTelemetryTests(unittest.TestCase):
    def test_stable_pci_address_filters_audio_and_reports_invalid_samples(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for name,kind in [('0000:05:00.0','0x030000'),('0000:05:00.1','0x040300')]:
                device=root/name
                device.mkdir()
                (device/'vendor').write_text('0x1002\n')
                (device/'class').write_text(kind+'\n')
            gpu=root/'0000:05:00.0'
            (gpu/'mem_info_vram_used').write_text('1024\n')
            (gpu/'mem_info_vram_total').write_text('4096\n')
            (gpu/'gpu_busy_percent').write_text('12\n')
            self.assertEqual(amd_memory(root),[{'pci_address':'0000:05:00.0',
                'used_bytes':1024,'total_bytes':4096,'utilization_percent':12}])
            (gpu/'mem_info_vram_used').write_text('8192\n')
            self.assertEqual(amd_memory(root),[{'pci_address':'0000:05:00.0','error_type':'ValueError'}])


if __name__=='__main__':
    unittest.main()

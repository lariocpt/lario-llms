import unittest
from shared.vulkan_device import select


def device(index,vendor,device,kind):
    return f'GPU{index}:\n vendorID = {vendor}\n deviceID = {device}\n deviceType = PHYSICAL_DEVICE_TYPE_{kind}_GPU\n'


class DeviceSelectionTests(unittest.TestCase):
    def test_apu_remains_selected_after_external_radeon_reorders_devices(self):
        summary=device(0,'0x1002','0x744c','DISCRETE')+device(1,'0x1002','0x1586','INTEGRATED')
        self.assertEqual(select(summary,'0x1002','0x1586','integrated'),1)

    def test_arc_does_not_capture_intel_igpu_or_nvidia(self):
        summary=device(0,'0x10de','0x2c02','DISCRETE')+device(1,'0x8086','0x7d67','INTEGRATED')+device(2,'0x8086','0xe223','DISCRETE')
        self.assertEqual(select(summary,'0x8086','0xe223','discrete'),2)

    def test_absent_or_ambiguous_device_fails_closed(self):
        with self.assertRaises(RuntimeError):
            select(device(0,'0x1002','0x744c','DISCRETE'),'0x1002','0x1586','integrated')
        with self.assertRaises(RuntimeError):
            select(device(0,'0x1002','0x1586','INTEGRATED')+device(1,'0x1002','0x1586','INTEGRATED'),
                   '0x1002','0x1586','integrated')

from pathlib import Path
import tempfile
import unittest
from shared.gpu import intel_arc_device

class ArcDeviceTests(unittest.TestCase):
    def test_requires_unique_xe_b70_full_bar_and_accessible_node(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);pci=root/'pci';pci.mkdir();dri=root/'dri';dri.mkdir()
            driver=root/'xe';driver.mkdir()
            def card(name,device='0xe223',size=32*2**30):
                p=pci/name;p.mkdir();(p/'vendor').write_text('0x8086');(p/'device').write_text(device)
                (p/'driver').symlink_to(driver);(p/'resource').write_text(f'0x100000000 {hex(0x100000000+size-1)} 0x14220c\n')
                (p/'drm').mkdir();(p/'drm/renderD130').mkdir();(dri/'renderD130').touch()
                return p
            arc=card('0000:04:00.0');card('0000:00:02.0','0x7d67')
            self.assertEqual(intel_arc_device(pci,dri)['pci'],'0000:04:00.0')
            (arc/'resource').write_text('0x100000000 0x10fffffff 0x14220c\n')
            with self.assertRaises(RuntimeError):intel_arc_device(pci,dri)
            (arc/'resource').write_text('0x100000000 0x8ffffffff 0x14220c\n')
            card('0000:08:00.0')
            with self.assertRaises(RuntimeError):intel_arc_device(pci,dri)

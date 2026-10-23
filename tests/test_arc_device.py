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

class ArcBootReadinessTests(unittest.TestCase):
    def test_waits_for_device_then_returns_exact_identity(self):
        from unittest.mock import patch
        from arcB70.install import wait_for_device
        identity={'pci':'0000:04:00.0'}
        with patch('arcB70.install.intel_arc_device',side_effect=[RuntimeError('not ready'),identity]), patch('arcB70.install.time.monotonic',side_effect=[0,0]), patch('arcB70.install.time.sleep') as sleep:
            self.assertEqual(wait_for_device(60),identity)
            sleep.assert_called_once_with(1)

    def test_expired_wait_preserves_device_failure(self):
        from unittest.mock import patch
        from arcB70.install import wait_for_device
        with patch('arcB70.install.intel_arc_device',side_effect=RuntimeError('wrong device')), patch('arcB70.install.time.monotonic',side_effect=[0,60]), patch('arcB70.install.time.sleep') as sleep:
            with self.assertRaisesRegex(RuntimeError,'wrong device'):wait_for_device(60)
            sleep.assert_not_called()

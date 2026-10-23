import unittest
from shared.sycl_device import select

class SyclSelectorTests(unittest.TestCase):
    def test_ordinal_changes_do_not_capture_igpu(self):
        data='0\t32902\t32103\t0000:00:02.0\t125757739008\tIntel Graphics\n7\t32902\t57891\t0000:04:00.0\t34242297856\tIntel Arc Pro B70\n'
        self.assertEqual(select(data,'0000:04:00.0'),7)
        with self.assertRaises(RuntimeError):select(data,'0000:08:00.0')
        with self.assertRaises(RuntimeError):select(data+data,'0000:04:00.0')

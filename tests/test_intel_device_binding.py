import unittest
from intel.services.device_binding import bind_gpu


class Core:
    available_devices=['CPU','GPU.0','GPU.1','GPU.2','NPU']
    def get_property(self,device,property):
        return {'GPU.0':'arc','GPU.1':'igpu','GPU.2':'nvidia'}[device]


class IntelDeviceBindingTests(unittest.TestCase):
    def test_registered_igpu_survives_new_arc_enumeration(self):
        self.assertEqual(bind_gpu('GPU.0','igpu',Core()),'GPU.1')

    def test_missing_gpu_does_not_capture_arc(self):
        with self.assertRaises(RuntimeError):
            bind_gpu('GPU.0','absent',Core())

    def test_cpu_request_is_preserved(self):
        self.assertEqual(bind_gpu('CPU','igpu',Core()),'CPU')

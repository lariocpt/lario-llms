import unittest

from benchmarks.mixed import rtx_thermal_event


class MixedThermalGuardTests(unittest.TestCase):
    def test_hot_or_unmeasurable_rtx_is_refused_but_other_hardware_is_independent(self):
        for nvidia in (None, [], [{}], [{'temperature_c': None}], [{'temperature_c': 84}], [{'temperature_c': 88}]):
            sample = {'nvidia': nvidia}
            self.assertIsNotNone(rtx_thermal_event(sample,'rtx5080',84))
            self.assertIsNone(rtx_thermal_event(sample,'7900xt',84))
            self.assertIsNone(rtx_thermal_event(sample,'geekom',84))
        self.assertIsNone(rtx_thermal_event({'nvidia':[{'temperature_c':83}]},'rtx5080',84))


if __name__ == '__main__':unittest.main()

import unittest
from benchmarks.memory_gate import evaluate,full_pressure


def fixture(swap=0):
    return {'passed':True,'requested_seconds':1800,'wall_seconds':1805,'samples':[
        {'elapsed_seconds':0,'available_kib':20*1024**2,'pswpout_pages':100,'memory_psi':'some avg60=2.00\nfull avg10=0.50 avg60=0.10 avg300=0.00 total=100\n'},
        {'elapsed_seconds':1800,'available_kib':19*1024**2,'pswpout_pages':100+swap,'memory_psi':'full avg10=0.00 avg60=0.00 avg300=0.00 total=101\n'}]}


class MemoryGateTests(unittest.TestCase):
    def test_raw_psi_and_completed_zero_swap_gate(self):
        result=evaluate(fixture())
        self.assertTrue(result['automatic_promotion_allowed'])
        self.assertEqual(result['maximum_memory_full_avg60_percent'],.1)

    def test_swap_is_preserved_and_requires_review(self):
        result=evaluate(fixture(76319))
        self.assertTrue(result['ram_psi_gate_passed'])
        self.assertFalse(result['automatic_promotion_allowed'])
        self.assertEqual(result['swapout_pages'],76319)

    def test_missing_invalid_or_duplicate_psi_fails_closed(self):
        for text in ('some avg60=0\n','full avg60=nan\n','full avg60=0\nfull avg60=0\n','full avg60=-1\n'):
            with self.subTest(text=text),self.assertRaises((ValueError,KeyError)):full_pressure(text)

    def test_short_failed_low_ram_or_memory_pressure_cannot_qualify(self):
        for change in ('short','failed','low_ram','pressure','reset'):
            data=fixture()
            if change=='short':data['requested_seconds']=600
            if change=='failed':data['passed']=False
            if change=='low_ram':data['samples'][1]['available_kib']=14*1024**2
            if change=='pressure':data['samples'][1]['memory_psi']='full avg60=1.01\n'
            if change=='reset':
                data['samples'][1]['pswpout_pages']=99
                with self.assertRaises(ValueError):evaluate(data)
                continue
            self.assertFalse(evaluate(data)['ram_psi_gate_passed'])


if __name__=='__main__':unittest.main()

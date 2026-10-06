import json
import unittest
from benchmarks.run import checks


class VisionChecksTests(unittest.TestCase):
    def test_payment_status_accepts_equivalent_json_boolean_and_no(self):
        case={'kind':'vision','expected':{'invoice':'INV-73142','total':'286.75','paid':'NO'}}
        for value in [False,'NO','no']:
            verdict=checks(case,json.dumps({'invoice':'INV-73142','total':286.75,'paid':value}))
            self.assertTrue(all(verdict.values()))
        for value in [True,'YES',None,0]:
            verdict=checks(case,json.dumps({'invoice':'INV-73142','total':286.75,'paid':value}))
            self.assertFalse(verdict['paid'])

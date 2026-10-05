import unittest
from unittest.mock import patch
import urllib.error

from shared import fleet_budget as fleet


class FleetBudgetTests(unittest.TestCase):
    def test_enforced_unavailable_never_falls_back(self):
        with patch.object(fleet,'read',side_effect=urllib.error.HTTPError('url',503,'offline',{},None)) as read:
            with self.assertRaises(urllib.error.HTTPError):fleet.budget('geekom','http://owner')
            self.assertEqual(read.call_count,1)

    def test_legacy_uses_actual_process_and_hermes_context_floor(self):
        absent=urllib.error.HTTPError('url',404,'absent',{},None)
        running={'running':[{'state':'ready','model':'qwen3.8','cmd':'server --parallel 1 -c 32768'}]}
        with patch.object(fleet,'read',side_effect=[absent,running]):result=fleet.budget('7900xt','http://owner')
        self.assertEqual((result['slots'],result['agents'],result['context']),(1,0,32768))
        self.assertFalse(result['enforced'])

    def test_invalid_gate_response_does_not_poll_legacy(self):
        with patch.object(fleet,'read',return_value={'hardware':'geekom','enforced':False}) as read:
            with self.assertRaises(RuntimeError):fleet.budget('geekom','http://owner')
            self.assertEqual(read.call_count,1)

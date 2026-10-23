import unittest
from unittest.mock import patch
import urllib.error
from observability import exporter

class ExporterTests(unittest.TestCase):
    def test_prepared_placements_are_not_ready_or_capacity_metrics(self):
        data=exporter.placement_metrics('l-dev-ai')
        self.assertIn('hardware="gkm7900xt"',data)
        self.assertIn('placement_status="planned"',data)
        self.assertIn('lario_model_prepared_profile_info',data)
        self.assertNotIn('lario_model_ready',data)
        self.assertNotIn('lario_model_agents',data)
        self.assertNotIn('winmax7900xt',data)
        arc=exporter.placement_metrics('bigcachy')
        self.assertIn('hardware="arcB70"',arc)
        self.assertIn('lario_model_prepared_profile_info',arc)
        self.assertNotIn('lario_model_ready',arc)

    def test_readiness_uses_budget_without_any_inference_call(self):
        state={'ready':True,'model':'qwen3.8','slots':1,'context':65536,'agents':0,'busy':1}
        with patch.object(exporter,'get',return_value=state) as get:
            data=exporter.model_metrics('7900xt')
        get.assert_called_once_with('http://127.0.0.1:11436/budget')
        self.assertIn('lario_model_busy{hardware="7900xt",workload="chat"} 1',data)
        self.assertIn('model="qwen3.8"',data)

    def test_absent_owner_is_not_reported_ready(self):
        with patch.object(exporter,'get',side_effect=OSError('offline')):
            data=exporter.model_metrics('7900xt')
        self.assertIn('lario_model_ready{hardware="7900xt",workload="chat"} 0',data)
        self.assertNotIn('lario_model_info',data)

    def test_legacy_occupancy_stays_unknown_and_raw_command_is_never_exposed(self):
        state={'running':[{'model':'qwen38-flash','state':'ready','cmd':'server --parallel 3 -c 737280 --api-key SUPERSECRET'}]}
        with patch.object(exporter,'get',side_effect=[urllib.error.HTTPError('',404,'legacy',{},None),state]):
            data=exporter.model_metrics('geekom')
        self.assertNotIn('SUPERSECRET',data)
        self.assertIn('lario_model_occupancy_known{hardware="geekom",workload="chat"} 0',data)
        self.assertIn('lario_model_context{hardware="geekom",workload="chat"} 245760',data)
        self.assertNotIn('lario_model_busy',data)

    def test_timestamp_precision_preserves_freshness(self):
        value=1792207308.123
        rendered=exporter.sample("last_seen",value).split()[-1]
        self.assertEqual(float(rendered),value)

    def test_intel_never_exposes_a_model_path(self):
        with patch.object(exporter,'get',return_value={'model_loaded':True,'model':'/private/path','device':'CPU'}):
            data=exporter.intel_metrics('embedding',8001)
        self.assertNotIn('/private/path',data)
        self.assertIn('device="CPU"',data)

if __name__=='__main__':unittest.main()

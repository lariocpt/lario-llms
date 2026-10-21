import json
import subprocess
import unittest
from unittest.mock import patch
from shared.serving.provision_control import invoke


class ProvisionTransportTests(unittest.TestCase):
    def test_renderer_progress_does_not_corrupt_final_json_result(self):
        result=subprocess.CompletedProcess([],0,'[agents] rendered\nReloaded\n'+json.dumps({'installed':True})+'\n','')
        with patch('shared.serving.provision_control.subprocess.run',return_value=result):
            self.assertEqual(invoke('test-host',['client-install','bigcachy']),{'installed':True})

    def test_missing_result_is_not_reported_as_success(self):
        result=subprocess.CompletedProcess([],0,'','')
        with patch('shared.serving.provision_control.subprocess.run',return_value=result):
            with self.assertRaisesRegex(RuntimeError,'no result'):invoke('test-host',['client-install','bigcachy'])

import copy
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from shared import modelctl
from shared.model_tools import owner
from shared.model_tools.export_choices import export

ROOT=Path(__file__).resolve().parents[1]


def client():
    spec=importlib.util.spec_from_file_location('model_tools',ROOT/'shared/model_tools/model_tools.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


class ClientTests(unittest.TestCase):
    def test_status_only_client_does_not_expose_switch_tool(self):
        with patch.dict(os.environ,{'LARIO_MODELS_ALLOW_SWITCH':'0'}):module=client()
        self.assertEqual([tool['name'] for tool in module.TOOLS],['model_status','model_options'])
        with self.assertRaisesRegex(ValueError,'disabled'):module.call('model_switch',{})

    def test_untrusted_model_cannot_reach_ssh(self):
        with patch.dict(os.environ,{'LARIO_MODELS_ALLOW_SWITCH':'1'}):module=client()
        with patch.object(module,'owner_call') as operation:
            with self.assertRaises(ValueError):module.call('model_switch',{'hardware':'geekom','option':'x; touch /tmp/unsafe','switch_token':'x'*64})
            with self.assertRaises(ValueError):module.call('model_switch',{'hardware':'rtx5080','option':'qwen3.8@fast-128k','switch_token':'x'*64})
            operation.assert_not_called()

    def test_discovery_and_options_do_not_require_network(self):
        module=client()
        with patch.object(module,'owner_call') as call:
            options=module.call('model_options',{'hardware':'geekom'})
            self.assertIn('qwen38-flash@flash-128k',[entry['id'] for entry in options['options']])
            call.assert_not_called()

    def test_exported_client_snapshot_is_current(self):
        self.assertEqual(json.loads((ROOT/'shared/model_tools/model_choices.json').read_text()),export())


class OwnerSwitchTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        directory=Path(self.temp.name);(directory/'7900xt').mkdir()
        fixture=json.loads((ROOT/'7900xt/models.json').read_text())
        fixture['presets']['fast-128k']['experimental']=True
        (directory/'7900xt/models.json').write_text(json.dumps(fixture))
        for item in [patch.object(owner,'ROOT',directory),patch.object(modelctl,'ROOT',directory),
                     patch.object(owner.socket,'gethostname',return_value='bigcachy')]:
            item.start();self.addCleanup(item.stop)
        self.before={'ready':True,'alias_target':{'model':'qwen3.8','preset':'capacity'},
                     'resident':{'model':'qwen3.8','context':262144,'slots':1},'switch_token':'a'*64}
        self.request={'operation':'switch','hardware':'7900xt','option':'qwen3.8@fast-128k','switch_token':'a'*64,'allow_experimental':True}

    def test_stale_status_never_switches(self):
        request={**self.request,'switch_token':'b'*64}
        with patch.object(owner,'status',return_value=self.before),patch.object(modelctl,'switch') as switch:
            with self.assertRaisesRegex(RuntimeError,'changed'):owner.operate(request)
            switch.assert_not_called()

    def test_rate_limited_monitoring_preserves_resident_without_switch_token(self):
        reg=json.loads((ROOT/'7900xt/models.json').read_text())
        live={'model':'qwen3.8','context':262144,'slots':1}
        error=modelctl.urllib.error.HTTPError('http://localhost/slots',429,'busy',{},None)
        self.addCleanup(error.close)
        with (patch.object(modelctl,'load_runtime'),patch.object(modelctl,'selection',return_value=('qwen3.8','capacity')),
             patch.object(modelctl,'assert_device_ready'),patch.object(modelctl,'runtime_budget',return_value=live),
             patch.object(modelctl,'api',return_value={'running':[{'model':'qwen3.8','state':'ready'}]}),
             patch.object(modelctl,'resident_slots',side_effect=error)):
            snapshot=owner.status(reg)
        self.assertTrue(snapshot['ready']);self.assertEqual(snapshot['resident'],live)
        self.assertIsNone(snapshot['processing_slots']);self.assertNotIn('switch_token',snapshot)
        with patch.object(owner,'status',return_value=snapshot),patch.object(modelctl,'switch') as switch:
            with self.assertRaisesRegex(RuntimeError,'unverified'):owner.operate(self.request)
            switch.assert_not_called()

    def test_busy_or_held_hardware_never_switches(self):
        for refusal in ('assert_idle','assert_not_held','assert_device_ready'):
            with self.subTest(refusal=refusal),patch.object(owner,'status',return_value=self.before),patch.object(modelctl,'switch') as switch:
                with patch.object(modelctl,refusal,side_effect=RuntimeError('refused')):
                    with self.assertRaises(RuntimeError):owner.operate(self.request)
                switch.assert_not_called()

    def test_experimental_requires_explicit_boolean(self):
        for value in (False,'true'):
            with self.subTest(value=value),patch.object(modelctl,'switch') as switch:
                with self.assertRaises((RuntimeError,ValueError)):owner.operate({**self.request,'allow_experimental':value})
                switch.assert_not_called()

    def test_success_uses_existing_guarded_controller(self):
        with patch.object(owner,'status',return_value=self.before),patch.object(modelctl,'assert_idle'),patch.object(modelctl,'assert_not_held'),patch.object(modelctl,'assert_device_ready'),patch.object(modelctl,'switch') as switch:
            result=owner.operate(self.request)
        self.assertTrue(result['changed'])
        self.assertEqual(switch.call_args.args[1:3],('qwen3.8','fast-128k'))

    def test_matching_ready_selection_is_noop(self):
        request={**self.request,'option':'qwen3.8@fast-64k'}
        before={**self.before,'alias_target':{'model':'qwen3.8','preset':'fast-64k'},
                'resident':{**self.before['resident'],'context':65536,'slots':1}}
        with patch.object(owner,'status',return_value=before),patch.object(modelctl,'assert_idle'),patch.object(modelctl,'assert_not_held'),patch.object(modelctl,'assert_device_ready'),patch.object(modelctl,'switch') as switch:
            result=owner.operate(request)
        self.assertFalse(result['changed']);switch.assert_not_called()

    def test_force_flag_is_not_accepted(self):
        with self.assertRaises(ValueError):owner.operate({**self.request,'force':True})


if __name__=='__main__':unittest.main()

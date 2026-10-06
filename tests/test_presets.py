import copy
import importlib.util
import json
from pathlib import Path
import shlex
import tempfile
import unittest
from unittest.mock import patch

from shared import modelctl as ctl

ROOT=Path(__file__).resolve().parents[1]


class PresetTests(unittest.TestCase):
    def registry(self,hardware):return json.loads((ROOT/hardware/'models.json').read_text())

    def test_balanced_keeps_maximum_window_for_every_geekom_model(self):
        reg=self.registry('geekom');models=ctl.effective_models(reg,'balanced')
        for key,model in models.items():
            self.assertEqual(model['context'],reg['models'][key]['context'])
            self.assertEqual(model['slots'],4 if '128k' in key else 3)
            self.assertEqual(model['reserved'],2)

    def test_retained_gpu_windows_and_other_models_are_unchanged(self):
        for hardware,windows in [('7900xt',[65536,131072]),('rtx5080',[65536])]:
            reg=self.registry(hardware)
            options=[pair for pair in ctl.selection_options(reg) if pair[0]=='qwen3.8']
            self.assertEqual([ctl.effective_models(reg,preset)[key]['context'] for key,preset in options],windows)
            for key,preset in options:
                models=ctl.effective_models(reg,preset)
                self.assertNotIn('--no-kv-offload',models[key]['args'])
                self.assertEqual(models[key]['args'].count('-ctk'),1)
                self.assertEqual(models[key]['args'].count('-ctv'),1)
                for other in reg['models']:
                    if other!='qwen3.8':self.assertEqual(models[other],reg['models'][other])
            self.assertEqual(reg['models']['qwen3.8']['context'],65536)

    def test_live_budget_does_not_claim_undeployed_registry_geometry(self):
        reg=self.registry('geekom')
        live={'running':[{'model':'qwen38-flash','state':'ready','cmd':'llama-server -c 737280 --parallel 3 -ctk q8_0 -ctv q8_0'}]}
        with patch.object(ctl,'api',return_value=live):
            result=ctl.runtime_budget(reg)
        self.assertEqual((result['slots'],result['context'],result['agents']),(3,245760,1))

    def test_retired_windows_cannot_be_selected_or_rendered(self):
        for hardware in ('7900xt','rtx5080'):
            reg=self.registry(hardware)
            retired=['fast-32k','cpu-32k','cpu-64k','cpu-128k']
            if hardware=='rtx5080':retired.append('fast-128k')
            for preset in retired:
                with self.assertRaises(ValueError):ctl.render(reg,'qwen3.8',preset)
                with self.assertRaises(ValueError):ctl.resolve_option(reg,'qwen3.8@'+preset)
            with self.assertRaises(ValueError):ctl.resolve_option(reg,'qwen3.8@capacity')
            # Legacy bare-model capacity fallback is conservative rather than restoring 256k.
            self.assertEqual(ctl.effective_models(reg,'capacity')['qwen3.8']['context'],65536)

    def test_invalid_geometry_and_preset_cannot_render(self):
        reg=self.registry('geekom')
        with self.assertRaises(ValueError):ctl.render(reg,'qwen38-flash','unknown')
        reg['presets']['broken']={'models':{'qwen38-flash':{'slots':1}}}
        with self.assertRaises(ValueError):ctl.render(reg,'qwen38-flash','broken')

    def test_hold_refuses_before_api_or_stop(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'.deployment-holds.json').write_text('{"geekom":"user hold"}')
            with patch.object(ctl,'ROOT',root),patch.object(ctl,'api') as api,patch.object(ctl.subprocess,'run') as run:
                with self.assertRaisesRegex(RuntimeError,'held'):ctl.switch(self.registry('geekom'),'qwen38-flash','balanced')
                api.assert_not_called();run.assert_not_called()

    def test_active_inference_refuses_before_stop(self):
        reg=self.registry('rtx5080')
        with patch.object(ctl,'api',return_value={'running':[{'state':'ready','model':'qwen3.8'}]}), patch.object(ctl,'resident_slots',return_value=[{'is_processing':True}]):
            with self.assertRaisesRegex(RuntimeError,'active'):ctl.assert_idle(reg)

    def test_selection_roundtrip_and_legacy_compatibility(self):
        reg=self.registry('rtx5080')
        with tempfile.TemporaryDirectory() as temp,patch.object(ctl,'ROOT',Path(temp)):
            (Path(temp)/reg['state']).write_text('qwen3.8\n')
            self.assertEqual(ctl.selection(reg),('qwen3.8','capacity'))
            ctl.save_selection(reg,'qwen3.8','fast-64k')
            self.assertEqual(ctl.selection(reg),('qwen3.8','fast-64k'))

    def test_startup_can_read_validated_config_while_switch_lock_is_held(self):
        import fcntl
        import sys
        reg=self.registry('geekom')
        with tempfile.TemporaryDirectory() as temp,patch.object(ctl,'ROOT',Path(temp)):
            directory=Path(temp)/'geekom';directory.mkdir()
            (directory/'models.json').write_text(json.dumps(reg))
            ctl.save_selection(reg,'qwen38-flash','balanced')
            config=Path(temp)/reg['config'];config.parent.mkdir(parents=True)
            config.write_text(ctl.render(reg,'qwen38-flash','balanced'))
            with (Path(temp)/'.geekom.lock').open('w') as lock:
                fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                with patch.object(sys,'argv',['modelctl','geekom','config']),patch.object(ctl.socket,'gethostname',return_value='l-dev-ai'),patch.object(ctl,'api') as api,patch.object(ctl,'load_runtime'):
                    ctl.main()
                    api.assert_not_called()

    def test_authenticated_render_closes_child_server_bypass(self):
        reg=self.registry('rtx5080');text=ctl.render(reg,'qwen3.8','capacity',True)
        self.assertIn('LARIO_BACKEND_KEY',text)
        self.assertIn('--host 127.0.0.1',text)
        self.assertIn('--api-key-file',text)
        self.assertNotIn('--api-key ',text)


if __name__=='__main__':unittest.main()

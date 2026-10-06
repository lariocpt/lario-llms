import importlib.util
import json
from pathlib import Path
import shlex
import unittest
import io
from unittest.mock import patch
import yaml
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('modelctl', ROOT/'shared/modelctl.py')
ctl=importlib.util.module_from_spec(spec); spec.loader.exec_module(ctl)

class RegistryTests(unittest.TestCase):
 def test_registries_and_aliases(self):
  for hardware,count in [('geekom',5),('7900xt',3),('rtx5080',3)]:
   reg=json.loads((ROOT/hardware/'models.json').read_text())
   self.assertEqual(len(reg['models']),count)
   for selected,model in reg['models'].items():
    config=yaml.safe_load(ctl.render(reg,selected))
    aliases=[a for m in config['models'].values() for a in m['aliases']]
    self.assertEqual(len(aliases),len(set(aliases)))
    self.assertIn(hardware,config['models'][selected]['aliases'])
    self.assertTrue(config['groups']['hardware']['exclusive'])
    for key,m in config['models'].items():
     argv=shlex.split(m['cmd'])
     slots=int(argv[argv.index('--parallel')+1]); context=int(argv[argv.index('-c')+1])
     self.assertEqual(context//slots,reg['models'][key]['context'])
     self.assertEqual(slots,m['concurrencyLimit'])
 def test_invalid_selection_cannot_generate(self):
  reg=json.loads((ROOT/'geekom/models.json').read_text())
  with self.assertRaises(ValueError): ctl.render(reg,'minimax')

class WarmupTests(unittest.TestCase):
 def setUp(self):
  self.reg=json.loads((ROOT/'rtx5080/models.json').read_text())
  device=patch.object(ctl,'assert_device_ready')
  device.start();self.addCleanup(device.stop)

 def test_health_accepts_plain_text(self):
  with patch.object(ctl.urllib.request,'urlopen') as urlopen:
   urlopen.return_value.__enter__.return_value=io.BytesIO(b'OK')
   self.assertEqual(ctl.api(self.reg,'/health'),'OK')

 def test_model_apis_still_parse_json(self):
  with patch.object(ctl.urllib.request,'urlopen') as urlopen:
   urlopen.return_value.__enter__.return_value=io.BytesIO(b'{"running": []}')
   self.assertEqual(ctl.api(self.reg,'/running'),{'running':[]})

 def test_hardware_alias_warms_configured_model(self):
  with patch.object(ctl,'api',side_effect=['OK',{'choices':[{}]}]) as api, patch.object(ctl,'current',return_value='qwen3.8'), patch.object(ctl.time,'sleep') as sleep:
   ctl.warm(self.reg,'rtx5080')
   self.assertEqual(api.call_args_list[1].args[2]['model'],'rtx5080')
   sleep.assert_not_called()

 def test_concrete_model_must_be_ready(self):
  with patch.object(ctl,'api',side_effect=['OK',{'choices':[{}]}]), patch.object(ctl,'current',return_value='describe'):
   with self.assertRaisesRegex(RuntimeError,'selected model ready'):
    ctl.warm(self.reg,'qwen3.8')

 def test_unhealthy_proxy_never_receives_completion(self):
  with patch.object(ctl,'api',side_effect=OSError('unreachable')) as api, patch.object(ctl.time,'sleep'):
   with self.assertRaisesRegex(RuntimeError,'did not become healthy'):
    ctl.warm(self.reg,'rtx5080')
   self.assertEqual(api.call_count,30)
   self.assertTrue(all(call.args[1]=='/health' for call in api.call_args_list))

 def test_startup_warms_alias_despite_stale_state(self):
  with patch.object(ctl.sys,'argv',['modelctl','rtx5080','warm']), patch.object(ctl.socket,'gethostname',return_value='bigcachy'), patch.object(ctl,'warm') as warm:
   ctl.main()
   self.assertEqual(warm.call_args.args[1],'rtx5080')

if __name__=='__main__': unittest.main()

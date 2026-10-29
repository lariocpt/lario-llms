import copy,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch,Mock
from shared import egpu,modelctl
from shared.serving.catalog import profiles
from shared.serving.state import state_directory
ROOT=Path(__file__).resolve().parents[1]

def reg(name):return json.loads((ROOT/name/'models.json').read_text())
class MirrorTests(unittest.TestCase):
 def test_same_models_and_physical_identity_but_separate_placement_ids(self):
  for old,new in [('geekom7900xt','gdp7900xt'),('rtx3060ti','gkm3060ti')]:
   a,b=reg(old),reg(new)
   self.assertEqual((a['models'],a['presets'],a['device_identity'],a['image']),(b['models'],b['presets'],b['device_identity'],b['image']))
   self.assertNotEqual(a['host'],b['host']);self.assertNotEqual(a['config'],b['config'])
   self.assertTrue(set(profiles(a)).isdisjoint(profiles(b)))
 def test_absent_gpu_and_wrong_owner_refuse_start(self):
  for name in ('gkm3060ti','gdp7900xt'):
   r=reg(name)
   with patch.object(egpu.socket,'gethostname',return_value='wrong-host'):
    with self.assertRaisesRegex(RuntimeError,'wrong eGPU owner'):egpu.check(r)
   with patch.object(egpu.socket,'gethostname',return_value=r['host']),patch.object(egpu.subprocess,'run',return_value=Mock(stdout='xfs\n')),patch.object(modelctl,'assert_device_ready',side_effect=RuntimeError('card absent')),patch('shared.lifecycle.stop_marker',return_value=Path('/nonexistent-off-marker')),patch('shared.serving.state.off_marker',return_value=Path('/nonexistent-off-marker')):
    with self.assertRaisesRegex(RuntimeError,'card absent'):egpu.check(r)
 def test_placement_owns_store_and_never_uses_unified_gpu_memory_for_discrete_card(self):
  self.assertEqual(str(state_directory(reg('gkm3060ti'))),'/mnt/AI_Models/control/gkm3060ti')
  self.assertEqual(str(state_directory(reg('gdp7900xt'))),'/mnt/xfs/AI_Models/control/gdp7900xt')
  with patch('shared.gpu.nvidia_device',return_value={'uuid':'GPU-expected'}):
   args=egpu.command(reg('gkm3060ti'))
  self.assertIn('--pull=never',args);self.assertIn('CUDA_VISIBLE_DEVICES=GPU-expected',args)
  self.assertIn('/mnt/AI_Models/containers/gkm3060ti',args)
  with patch('shared.gpu.radeon_device',return_value={'unique_id':'expected'}):
   args=egpu.command(reg('gdp7900xt'))
  self.assertIn('ROCR_VISIBLE_DEVICES=GPU-expected',args)
  self.assertIn('/mnt/xfs/AI_Models/containers/gdp7900xt',args)

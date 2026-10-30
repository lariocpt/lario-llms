"""Native XPU owner refuses ambiguous occupancy and overlong requests."""
import json
import unittest
from pathlib import Path
from arcB70.vllm.install import build_registry
from shared.serving.catalog import profiles

class VLLMRegistryTests(unittest.TestCase):
 def test_two_equal_vision_windows_replace_all_retired_choices(self):
  old=json.loads((Path(__file__).resolve().parents[1]/'arcB70/models.json').read_text())
  reg=build_registry(old,{'context_per_slot':181248,'status':'passed-native-capacity-concurrency-vision-long-retrieval'})
  entries=list(profiles(reg).values())
  self.assertEqual(len(entries),1)
  self.assertEqual((entries[0]['slots'],entries[0]['context'],entries[0]['vision']),(2,181248,True))
  self.assertNotIn('provisional',entries[0]['name'])
  self.assertEqual(reg['serving_engine'],'vllm')
  self.assertNotIn('qwen3.8-smart-q4-512k',reg['models'])
 def test_invalid_window_refused(self):
  with self.assertRaises(RuntimeError):build_registry({}, {'context_per_slot':524288})

if __name__=='__main__':unittest.main()

class NativeInspectionTests(unittest.IsolatedAsyncioTestCase):
 async def test_scheduler_metrics_and_native_context_are_required(self):
  import tempfile
  from unittest.mock import patch
  from aiohttp import web,ClientSession
  from aiohttp.test_utils import TestServer
  from shared.serving.vllm_gateway import VLLMCoordinator
  old=json.loads((Path(__file__).resolve().parents[1]/'arcB70/models.json').read_text())
  reg=build_registry(old,{'context_per_slot':174080,'status':'test'})
  key=next(iter(profiles(reg)))
  native={'context':174080,'metrics':'vllm:num_requests_running{model_name="test"} 1\nvllm:num_requests_waiting{model_name="test"} 0\n'}
  async def models(request):return web.json_response({'data':[{'id':key,'max_model_len':native['context']}]})
  async def metrics(request):return web.Response(text=native['metrics'])
  app=web.Application();app.router.add_get('/v1/models',models);app.router.add_get('/metrics',metrics)
  async with TestServer(app) as backend,ClientSession() as session:
   with tempfile.TemporaryDirectory() as directory:
    owner=VLLMCoordinator(reg,str(backend.make_url('')).rstrip('/'),{},'private',directory)
    owner.session=session
    with patch('shared.serving.vllm_gateway.modelctl.assert_device_ready'),patch('shared.serving.vllm_gateway.subprocess.run') as run:
     run.return_value.returncode=0
     self.assertEqual((await owner.inspect())['busy'],1)
     native['metrics']=''
     with self.assertRaisesRegex(RuntimeError,'occupancy unavailable'):await owner.inspect()
     native['context']=262144
     with self.assertRaisesRegex(RuntimeError,'context differs'):await owner.inspect()
    owner.store.close()

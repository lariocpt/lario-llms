import ast
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import repair_geekom_clients as repair


class RepairGeekomClientsTests(unittest.TestCase):
    def test_each_client_receives_only_its_existing_inference_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            private = home/'.config/lario-admission'
            private.mkdir(parents=True)
            originals = {}
            for hardware in repair.HARDWARE:
                path = private/(hardware+'.clients.json')
                path.write_text(json.dumps({
                    machine:{'role':'interactive', 'key':hardware+'-'+machine+'x'*30}
                    for machine in repair.HOSTS}))
                originals[path] = path.read_bytes()
            with patch.object(repair.Path, 'home', return_value=home), \
                 patch.object(repair.socket, 'gethostname', return_value='l-dev-ai'):
                bodies = repair.payloads(complete=True)
            self.assertEqual({b['machine'] for b in bodies}, set(repair.HOSTS))
            for body in bodies:
                self.assertEqual(body['complete'], body['machine'] == 'l-dev-ai')
                self.assertEqual(set(body['keys']), set(repair.HARDWARE))
                for hardware, key in body['keys'].items():
                    self.assertEqual(key, hardware+'-'+body['machine']+'x'*30)
                    prefix = 'geekom.qwen38-flash-halogen-128k.' if hardware == 'geekom' else hardware+'.qwen3.8'
                    self.assertTrue(body['profiles'][hardware].startswith(prefix))
            for path, previous in originals.items():
                self.assertEqual(path.read_bytes(), previous)

    def test_wrong_owner_refuses_before_reading_credentials(self):
        with patch.object(repair.socket, 'gethostname', return_value='bigcachy'):
            with self.assertRaisesRegex(RuntimeError, 'Geekom owner'):
                repair.payloads()

    def test_remote_worker_is_valid_python(self):
        compile(repair.WORKER, '<geekom-client-repair>', 'exec')

    def test_probe_uses_free_shared_pool_capacity_without_swapping_busy_work(self):
        tree = ast.parse(repair.WORKER)
        helper = next(node for node in tree.body
                      if isinstance(node, ast.FunctionDef) and node.name == 'completion_allowed')
        namespace = {}
        exec(compile(ast.Module(body=[helper], type_ignores=[]), '<probe-policy>', 'exec'), namespace)
        allowed = namespace['completion_allowed']
        budget = {'busy':3, 'available':7, 'draining':False,
                  'profile_id':'shared-pool',
                  'profile_availability':{'qwen-smart':{'resident':True}}}
        self.assertTrue(allowed(budget, 'qwen-smart'))
        self.assertFalse(allowed(budget, 'different-model'))
        self.assertFalse(allowed({**budget, 'available':0}, 'qwen-smart'))
        self.assertFalse(allowed({**budget, 'draining':True}, 'qwen-smart'))
        self.assertTrue(allowed({'busy':0, 'draining':False}, 'qwen-smart'))


if __name__ == '__main__':
    unittest.main()

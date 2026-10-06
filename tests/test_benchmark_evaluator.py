import json
from pathlib import Path
import subprocess
import sys
import unittest


class EvaluatorTests(unittest.TestCase):
    def evaluate(self,source):
        payload={'source':source,'checks':[[[3,1,3,2],[3,1,2]],[[],[]]],'two_args':False}
        return subprocess.run([sys.executable,str(Path(__file__).parents[1]/'benchmarks/evaluate.py')],
                              input=json.dumps(payload),capture_output=True,text=True,timeout=10)

    def test_valid_pure_dictionary_deduplication(self):
        result=self.evaluate('def solve(values):\n    return list(dict.fromkeys(values))\n')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertTrue(json.loads(result.stdout)['passed'])

    def test_counter_is_a_supported_pure_counting_implementation(self):
        payload={'source':'from collections import Counter\ndef solve(values):\n    return dict(Counter(values))\n',
                 'checks':[[[1,1,-2],{1:2,-2:1}]],'two_args':False,'integer_dict_keys':True}
        result=subprocess.run([sys.executable,str(Path(__file__).parents[1]/'benchmarks/evaluate.py')],
                              input=json.dumps(payload),capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertTrue(json.loads(result.stdout)['passed'])

    def test_integer_dictionary_key_contract_survives_json_transport(self):
        payload={'source':'def solve(values):\n    return {v:values.count(v) for v in values}\n',
                 'checks':[[[1,1,-2],{1:2,-2:1}]],'two_args':False,'integer_dict_keys':True}
        result=subprocess.run([sys.executable,str(Path(__file__).parents[1]/'benchmarks/evaluate.py')],
                              input=json.dumps(payload),capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertTrue(json.loads(result.stdout)['passed'])
        payload['source']='def solve(values):\n    return {str(v):values.count(v) for v in values}\n'
        result=subprocess.run([sys.executable,str(Path(__file__).parents[1]/'benchmarks/evaluate.py')],
                              input=json.dumps(payload),capture_output=True,text=True,timeout=10)
        self.assertFalse(json.loads(result.stdout)['passed'])

    def test_pure_list_index_can_return_the_leftmost_duplicate(self):
        payload={'source':'def solve(values,target):\n    try:\n        return values.index(target)\n    except ValueError:\n        return -1\n',
                 'checks':[[[[1,2,2,4],2],1],[[[],2],-1],[[[1,3],2],-1]],'two_args':True}
        result=subprocess.run([sys.executable,str(Path(__file__).parents[1]/'benchmarks/evaluate.py')],
                              input=json.dumps(payload),capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertTrue(json.loads(result.stdout)['passed'])

    def test_model_solution_cannot_access_files_or_dunder_attributes(self):
        for source in ['def solve(values):\n    return open("/tmp/forbidden")\n',
                       'def solve(values):\n    return values.__class__\n']:
            result=self.evaluate(source)
            self.assertTrue(result.returncode or not json.loads(result.stdout)['passed'])

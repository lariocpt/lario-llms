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

    def test_model_solution_cannot_access_files_or_dunder_attributes(self):
        for source in ['def solve(values):\n    return open("/tmp/forbidden")\n',
                       'def solve(values):\n    return values.__class__\n']:
            result=self.evaluate(source)
            self.assertTrue(result.returncode or not json.loads(result.stdout)['passed'])

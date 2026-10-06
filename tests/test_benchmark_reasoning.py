import unittest
from unittest.mock import patch

from benchmarks import quality,run


class BenchmarkReasoningTests(unittest.TestCase):
    def test_thinking_controls_reach_both_sides_of_real_tool_roundtrip(self):
        policy=run.reasoning_policy(64,'low')
        responses=[{'choices':[{'message':{'role':'assistant','tool_calls':[
            {'id':'owned-call','function':{'name':'add','arguments':'{"a":2,"b":3}'}}]}}]},
            {'choices':[{'message':{'content':'5'}}]}]
        with patch.object(quality,'request_json',side_effect=responses) as request:
            result=quality.tool_case('http://owner','muse-glimmer',
                {'id':'add-2-3','a':2,'b':3,'expected':5},None,policy)
        self.assertTrue(result['passed'])
        for call in request.call_args_list:
            payload=call.args[1]
            self.assertEqual(payload['reasoning_budget_tokens'],64)
            self.assertEqual(payload['chat_template_kwargs']['reasoning_strength'],'low')
            self.assertEqual(payload['max_tokens'],512)
        self.assertEqual(request.call_args_list[1].args[1]['messages'][-1]['content'],'5')

    def test_default_does_not_claim_or_inject_a_budget(self):
        self.assertEqual(run.reasoning_policy(),{'chat_template_kwargs':{'enable_thinking':False}})
        for budget in (-1,2049,True):
            with self.assertRaises(ValueError):run.reasoning_policy(budget)
        with self.assertRaises(ValueError):run.reasoning_policy(64,'invented')


if __name__=='__main__':unittest.main()

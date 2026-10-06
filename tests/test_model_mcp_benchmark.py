import json
import unittest

from benchmarks.model_mcp import inspect_events


class ModelMcpBenchmarkTests(unittest.TestCase):
    def test_refusal_mentions_are_not_tool_evidence(self):
        result = inspect_events([{'type': 'text', 'part': {'text':
            'Cannot call model_options/model_status or verify 131072 / 6. MCP_MODELS_OK'}}])
        self.assertFalse(result['options_tool_completed'])
        self.assertFalse(result['status_tool_completed'])
        self.assertFalse(result['six_slot_option'])
        self.assertFalse(result['ready_rtx_resident'])

    def test_caught_unknown_tool_is_not_a_successful_nested_call(self):
        result = inspect_events([{'type': 'tool_use', 'part': {'state': {
            'status': 'completed', 'metadata': {'metadata': {'toolCalls': []}},
            'output': json.dumps({'error': 'Unknown tool lario_models.model_options'})}}}])
        self.assertFalse(result['options_tool_completed'])

    def test_completed_calls_and_structured_results_pass(self):
        output = {'options': {'options': [{'id': 'qwen38-flash@flash-128k', 'slots': 6, 'context': 131072}]},
                  'status': {'hardware': 'rtx5080', 'ready': True, 'resident': {'context': 65536}}}
        calls = [{'tool': 'lario_models.' + name, 'status': 'completed'}
                 for name in ('model_options', 'model_status')]
        events = [{'type': 'tool_use', 'part': {'state': {'status': 'completed',
                  'metadata': {'metadata': {'toolCalls': calls}}, 'output': json.dumps(output)}}},
                  {'type': 'text', 'part': {'text': 'Verified. MCP_MODELS_OK'}}]
        self.assertTrue(all(inspect_events(events).values()))


if __name__ == '__main__':
    unittest.main()

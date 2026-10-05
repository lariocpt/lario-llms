import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

CLIENT = Path(__file__).resolve().parents[1] / 'intel/tools/intel_tools.py'
spec = importlib.util.spec_from_file_location('intel_tools', CLIENT)
client = importlib.util.module_from_spec(spec)
spec.loader.exec_module(client)


class IntelClientTests(unittest.TestCase):
    def test_discovery_survives_model_host_offline(self):
        requests = [
            {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
             'params': {'protocolVersion': '2025-06-18'}},
            {'jsonrpc': '2.0', 'method': 'notifications/initialized'},
            {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'},
        ]
        result = subprocess.run([sys.executable, str(CLIENT)],
            input=''.join(json.dumps(r)+'\n' for r in requests), text=True,
            capture_output=True, timeout=5, check=True,
            env={**os.environ, 'LARIO_INTEL_HOST': '127.0.0.254', 'LARIO_INTEL_TIMEOUT': '1'})
        replies = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(len(replies), 2)
        self.assertEqual(replies[0]['result']['protocolVersion'], '2025-06-18')
        self.assertEqual(len(replies[1]['result']['tools']), 7)

    def test_speech_cannot_overwrite_existing_client_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'existing.wav'
            path.write_bytes(b'existing user recording')
            with patch.object(client, 'request') as request:
                with self.assertRaisesRegex(ValueError, 'already exists'):
                    client.call('intel_synthesize', {'text':'test', 'output_path':str(path)})
                request.assert_not_called()
            self.assertEqual(path.read_bytes(), b'existing user recording')

    def test_embedding_space_change_is_rejected(self):
        with patch.object(client, 'request', return_value={'embeddings':[[0.0]*384]}):
            with self.assertRaisesRegex(RuntimeError, 'contract mismatch'):
                client.call('intel_embed', {'texts':['keep the BGE-M3 space']})

    def test_audio_upload_is_read_from_client_machine(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'audio.wav'; path.write_bytes(b'RIFFclient audio')
            with patch.object(client, 'request', return_value={'text':'transcribed'}) as request:
                client.call('intel_transcribe', {'audio_path':str(path)})
                self.assertIn(b'RIFFclient audio', request.call_args.kwargs['data'])
                self.assertNotIn(str(path).encode(), request.call_args.kwargs['data'])


if __name__ == '__main__':
    unittest.main()

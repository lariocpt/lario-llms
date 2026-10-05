import json
from pathlib import Path
import signal
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from benchmarks import quality


class CodingCleanupTests(unittest.TestCase):
    def test_timeout_keeps_current_private_events_instead_of_stale_diagnostics(self):
        process=Mock(pid=45678)
        events=json.dumps({'type':'text','part':{'text':'synthetic fixture'}})+'\n'
        process.communicate.side_effect=[subprocess.TimeoutExpired('opencode',1),(events,'')]
        with tempfile.TemporaryDirectory() as directory:
            trace=Path(directory)/'events.jsonl'
            with patch.object(quality,'EVENTS_FILE',trace), patch.object(quality.subprocess,'Popen',return_value=process), patch.object(quality.os,'killpg') as kill:
                result=quality.coding_case('geekom/qwen38-flash',quality.CODING[0],timeout=1)
            self.assertFalse(result['passed']);self.assertEqual(result['error_type'],'OpenCodeTimeout')
            self.assertEqual(trace.read_text(),events);self.assertEqual(trace.stat().st_mode&0o777,0o600)
            kill.assert_called_once_with(process.pid,signal.SIGTERM)

    def test_interruption_cleans_up_only_the_owned_client_group(self):
        process=Mock(pid=45678);process.poll.return_value=None
        process.communicate.side_effect=[KeyboardInterrupt(),('','')]
        with patch.object(quality.subprocess,'Popen',return_value=process), patch.object(quality.os,'killpg') as kill:
            with self.assertRaises(KeyboardInterrupt):quality.coding_case('geekom/qwen38-flash',quality.CODING[0])
        kill.assert_called_once_with(process.pid,signal.SIGTERM)

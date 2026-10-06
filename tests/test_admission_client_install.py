import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from shared.admission.install_client import install


class ClientInstallTests(unittest.TestCase):
    def test_preserves_other_keys_and_rejects_privileged_bundle_before_writing(self):
        with tempfile.TemporaryDirectory() as temporary:
            home=Path(temporary);path=home/'.config/lario-admission/clients.json'
            path.parent.mkdir(parents=True);path.write_text('{"geekom":{"apiKey":"old-interactive-key-preserved"}}\n')
            fragment={'7900xt':{'apiKey':'new-interactive-key-for-testing','context_limits':{'7900xt':28672}}}
            install(fragment,'bigcachy',home,render=False)
            result=json.loads(path.read_text())
            self.assertEqual(result['geekom']['apiKey'],'old-interactive-key-preserved')
            self.assertEqual(result['7900xt'],fragment['7900xt'])
            self.assertEqual(path.stat().st_mode&0o777,0o600)
            before=path.read_bytes()
            with self.assertRaisesRegex(ValueError,'backend/management'):
                install({'7900xt':{'apiKey':'new-interactive-key-for-testing','backend':'do-not-export'}},'bigcachy',home,render=False)
            self.assertEqual(path.read_bytes(),before)

    def test_render_failure_restores_private_fragment_and_never_restarts_client(self):
        with tempfile.TemporaryDirectory() as temporary:
            home=Path(temporary);path=home/'.config/lario-admission/clients.json'
            path.parent.mkdir(parents=True);original='{"geekom":{"apiKey":"old-interactive-key-preserved"}}\n'
            path.write_text(original)
            with patch('shared.admission.install_client.subprocess.run',side_effect=subprocess.CalledProcessError(1,['renderer'])) as run:
                with self.assertRaises(subprocess.CalledProcessError):
                    install({'7900xt':{'apiKey':'new-interactive-key-for-testing'}},'bigcachy',home)
                self.assertEqual(path.read_text(),original)
                self.assertEqual(run.call_count,1)
                self.assertIn('render-agent-configs.py',run.call_args.args[0][1])


if __name__=='__main__':unittest.main()

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from shared.admission import provision, deploy


class ProvisionTests(unittest.TestCase):
    def test_prepare_is_private_repeatable_and_does_not_restart_hardware(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary)/'geekom'
            with patch.object(provision,'selection',return_value=('qwen38-flash','balanced')):
                provision.prepare('geekom',directory,['127.0.0.1'])
                first=(directory/'private/credentials.json').read_bytes()
                provision.prepare('geekom',directory,['127.0.0.1'])
            self.assertEqual(first,(directory/'private/credentials.json').read_bytes())
            for file in (directory/'private').iterdir():self.assertEqual(file.stat().st_mode&0o777,0o600)
            self.assertNotIn(json.loads(first)['backend'],(directory/'backend.yaml').read_text())
            self.assertIn('--api-key-file',(directory/'backend.yaml').read_text())
            self.assertEqual(json.loads((directory/'deployment.json').read_text())['status'],'prepared; not deployed')

    def test_private_credentials_cannot_be_prepared_inside_git_checkout(self):
        with self.assertRaisesRegex(ValueError,'outside'):
            provision.prepare('geekom',provision.ROOT/'private', ['127.0.0.1'])

    def test_native_activator_cannot_recreate_the_protected_radeon(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary)
            (directory/'deployment.json').write_text('{"hardware":"7900xt"}')
            with patch.object(deploy,'command') as command:
                with self.assertRaisesRegex(RuntimeError,'Radeon'):deploy.activate(directory)
                command.assert_not_called()

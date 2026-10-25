import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from shared.serving import deploy


class DeploymentCredentialsTests(unittest.TestCase):
    def prepare(self, registered):
        source = deploy.ROOT
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'geekom').mkdir()
            (root/'geekom/models.json').write_text((source/'geekom/models.json').read_text())
            private = root/'.config/lario-admission'
            private.mkdir(parents=True)
            consumer = 'consumer-'+'c'*32
            role = 'interactive-'+'i'*32
            (private/'clients.json').write_text(json.dumps({'geekom':{'apiKey':consumer}}))
            (private/'geekom.env').write_text('LARIO_INTERACTIVE_KEY='+role+'\n')
            if registered:
                (private/'geekom.clients.json').write_text(json.dumps({
                    'mini-mobile':{'key':consumer,'role':'interactive'}}))
            with patch.object(deploy, 'ROOT', root), \
                    patch.object(Path, 'home', return_value=root), \
                    patch.object(deploy.socket, 'gethostname', return_value='l-dev-ai'):
                deploy.deploy('geekom', prepare=True)
            prepared = dict(line.split('=',1) for line in
                (private/'geekom-fixed-prepared/owner.env').read_text().splitlines())
            self.assertEqual((private/'geekom.env').read_text(),'LARIO_INTERACTIVE_KEY='+role+'\n')
            return prepared['LARIO_INTERACTIVE_KEY'], role, consumer

    def test_registered_consumer_does_not_replace_shared_role_credential(self):
        actual, role, consumer = self.prepare(registered=True)
        self.assertEqual(actual,role)
        self.assertNotEqual(actual,consumer)

    def test_unregistered_legacy_consumer_remains_supported(self):
        actual, _, consumer = self.prepare(registered=False)
        self.assertEqual(actual,consumer)

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch,Mock

from shared.admission import deploy_container as deploy,provision
from shared import modelctl


class ContainerDeploymentTests(unittest.TestCase):
    def test_wrong_hardware_and_existing_marker_never_mutate_services(self):
        with tempfile.TemporaryDirectory() as temporary,patch.object(deploy,'command') as command:
            directory=Path(temporary)
            (directory/'deployment.json').write_text('{"hardware":"rtx5080"}')
            with self.assertRaisesRegex(RuntimeError,'only supports Radeon'):deploy.activate(directory)
            (directory/'deployment.json').write_text('{"hardware":"7900xt"}')
            home=directory/'home'
            private=home/'.config/lario-admission';private.mkdir(parents=True)
            (private/'7900xt.active.json').write_text('{"status":"active"}')
            with patch.object(Path,'home',return_value=home),patch.object(deploy.socket,'gethostname',return_value='bigcachy'):
                with self.assertRaisesRegex(RuntimeError,'activation marker'):deploy.activate(directory)
            command.assert_not_called()

    def test_busy_backend_never_mutates_services(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary)
            provision.prepare('7900xt',directory,['0.0.0.0'],'qwen3.8','capacity')
            with patch.object(deploy.socket,'gethostname',return_value='bigcachy'),\
                 patch.object(modelctl,'load_runtime'),\
                 patch.object(modelctl,'assert_idle',side_effect=RuntimeError('active inference')),\
                 patch.object(deploy,'command') as command:
                with self.assertRaisesRegex(RuntimeError,'active inference'):deploy.activate(directory)
                command.assert_not_called()

    def test_failed_backend_creation_restores_files_selection_and_legacy_owner_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary)/'prepared'
            provision.prepare('7900xt',directory,['0.0.0.0'],'qwen3.8','capacity')
            root=Path(temporary)/'repo';home=Path(temporary)/'home'
            (root/'7900xt').mkdir(parents=True)
            reg=json.loads((deploy.ROOT/'7900xt/models.json').read_text())
            (root/'7900xt/models.json').write_text(json.dumps(reg))
            config=root/reg['config'];config.parent.mkdir();config.write_text('original configuration\n')
            (root/reg['state']).write_text('qwen3.8\n')
            (root/'.7900xt-selection.json').write_text('{"model":"qwen3.8","preset":"capacity"}\n')
            private=home/'.config/lario-admission';private.mkdir(parents=True)
            calls=[]
            def command(*args):
                calls.append(args)
                if args[:2]==('docker','compose') and any('shared/admission/compose/7900xt.yml' in x for x in args):
                    raise RuntimeError('simulated private backend failure')
            with patch.object(deploy,'ROOT',root),patch.object(modelctl,'ROOT',root),\
                 patch.object(Path,'home',return_value=home),\
                 patch.object(deploy.socket,'gethostname',return_value='bigcachy'),\
                 patch.object(modelctl,'assert_idle'),patch.object(modelctl,'load_runtime'),\
                 patch.object(modelctl,'warm') as warm,\
                 patch.object(deploy,'validate_owner_client'),\
                 patch.object(deploy.subprocess,'run',return_value=Mock(returncode=4)),\
                 patch.object(deploy,'command',side_effect=command):
                with self.assertRaisesRegex(RuntimeError,'simulated private backend failure'):deploy.activate(directory)
                self.assertEqual(modelctl.selection(reg),('qwen3.8','capacity'))
                warm.assert_called_once_with(reg,'qwen3.8')
            self.assertEqual(config.read_text(),'original configuration\n')
            self.assertEqual(config.stat().st_mode&0o777,0o644)
            self.assertFalse((private/'7900xt.env').exists())
            self.assertFalse((private/'7900xt.active.json').exists())
            self.assertTrue(any('--force-recreate' in args and args[-1]=='agent-llm' for args in calls))
            self.assertFalse(any('vision' in args or 'rtx5080' in ' '.join(args) for args in calls))


if __name__=='__main__':unittest.main()

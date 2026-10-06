import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

DIRECTORY = Path(__file__).resolve().parents[1] / 'rtx5080/image-generation'
sys.path.insert(0, str(DIRECTORY))
from workflows import graph
import controller
import image_tools


class ImageWorkflowTests(unittest.TestCase):
    def test_cpu_encoder_and_bounded_single_image(self):
        for name in ('qwen-image', 'flux-klein'):
            result = graph(name, 'A blue square', 512, 512)
            self.assertEqual(result['2']['inputs']['device'], 'cpu')
            self.assertEqual(result['5']['inputs']['batch_size'], 1)
        self.assertEqual(graph('qwen-image', 'x')['9']['inputs']['device'], 'cpu')
        self.assertEqual(graph('flux-klein', 'x')['13']['inputs']['steps'], 4)

    def test_invalid_requests_never_reach_services(self):
        with patch.object(controller, 'command') as command:
            for request in ({'model': 'anything', 'prompt': 'x'},
                            {'model': 'qwen-image', 'prompt': ''},
                            {'model': 'qwen-image', 'prompt': 'x', 'width': 4096},
                            {'model': 'qwen-image', 'prompt': 'x', 'steps': True},
                            {'model': 'qwen-image', 'prompt': 'x', 'force': True}):
                with self.assertRaises((ValueError, TypeError)):
                    controller.generate(request)
            command.assert_not_called()

    def test_busy_chat_refuses_image_before_stop(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            (repo / 'rtx5080').mkdir()
            (repo / 'rtx5080/models.json').write_text(json.dumps({'service': 'rtx5080.service'}))
            with patch.object(controller, 'REPO', repo), patch.object(controller, 'installed', return_value=True), \
                 patch.object(controller.socket, 'gethostname', return_value='bigcachy'), \
                 patch.object(controller.modelctl, 'load_runtime'), patch.object(controller.modelctl, 'assert_not_held'), \
                 patch.object(controller.modelctl, 'assert_device_ready'), \
                 patch.object(controller.modelctl, 'assert_idle', side_effect=RuntimeError('active inference')), \
                 patch.object(controller, 'command') as command, patch.object(controller, 'api') as api:
                with self.assertRaisesRegex(RuntimeError, 'active inference'):
                    controller.generate({'model': 'qwen-image', 'prompt': 'x'})
                command.assert_not_called()
                api.assert_not_called()

    def test_consumer_cannot_generate_or_export_owner_access(self):
        with patch.object(image_tools, 'owner') as owner:
            self.assertEqual(image_tools.call('image_options', {})['generation_available'], False)
            with self.assertRaises(ValueError):
                image_tools.call('image_generate', {'model': 'qwen-image', 'prompt': 'x'})
            owner.assert_not_called()

    def test_worker_validation_failure_restores_chat(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            (repo / 'rtx5080').mkdir()
            (repo / 'rtx5080/models.json').write_text(json.dumps({'service': 'rtx5080.service', 'aliases': ['rtx5080']}))
            with patch.object(controller, 'REPO', repo), patch.object(controller, 'installed', return_value=True), \
                 patch.object(controller.socket, 'gethostname', return_value='bigcachy'), \
                 patch.object(controller.socket, 'create_connection', side_effect=OSError('unused port')), \
                 patch.object(controller.modelctl, 'load_runtime'), patch.object(controller.modelctl, 'assert_not_held'), \
                 patch.object(controller.modelctl, 'assert_device_ready'), patch.object(controller.modelctl, 'assert_idle'), \
                 patch.object(controller.modelctl, 'selection', return_value=('qwen3.8', 'fast-64k')), \
                 patch.object(controller.modelctl, 'admission_admin') as admission, \
                 patch.object(controller.modelctl, 'warm') as warm, \
                 patch.object(controller.subprocess, 'run', side_effect=[SimpleNamespace(returncode=1), SimpleNamespace(returncode=0)]), \
                 patch.object(controller, 'command') as command, patch.object(controller, 'api', return_value={}):
                with self.assertRaisesRegex(RuntimeError, 'missing image nodes'):
                    controller.generate({'model': 'qwen-image', 'prompt': 'x'})
                self.assertEqual(command.call_args_list[-2].args, ('stop', 'lario-images.service'))
                self.assertEqual(command.call_args_list[-1].args, ('start', 'rtx5080.service'))
                warm.assert_called_once()
                self.assertEqual(warm.call_args.args[1], 'rtx5080')
                self.assertEqual(admission.call_args.args[1], 'resume')

    def test_manifest_selects_only_requested_bundles(self):
        manifest = json.loads((DIRECTORY / 'install-manifest.json').read_text())
        self.assertEqual(len(manifest['files']), 6)
        self.assertEqual(len({item['target'] for item in manifest['files']}), 6)
        for item in manifest['files']:
            self.assertEqual(len(item['sha256']), 64)
            self.assertFalse(Path(item['target']).is_absolute())
            self.assertNotIn('..', Path(item['target']).parts)


if __name__ == '__main__':
    unittest.main()

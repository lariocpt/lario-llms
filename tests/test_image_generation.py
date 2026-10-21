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
spec = importlib.util.spec_from_file_location('image_controller_test', DIRECTORY / 'controller.py')
controller = importlib.util.module_from_spec(spec)
spec.loader.exec_module(controller)
import image_tools


class ImageWorkflowTests(unittest.TestCase):
    def fixed_state(self, **changes):
        return dict(state='ready', detail=None, enabled=True, draining=False, busy=0, requests=[], loading_profile=None,
                    uncertain=False, revision=7, profile_id='rtx5080.fixed-64k', **changes)

    def test_fixed_claim_rejects_off_paused_busy_unknown_without_mutation(self):
        for changes in ({'enabled': False}, {'draining': True}, {'busy': 1},
                        {'uncertain': True, 'state': 'reconciling', 'detail': 'Unknown backend'},
                        {'loading_profile': 'loading'}, {'requests': [{}]}):
            state = self.fixed_state(); state.update(changes)
            with patch.object(controller, 'owner_request', return_value=state), \
                 patch.object(controller, 'owner_operation') as operation:
                with self.assertRaises(RuntimeError):
                    controller.claim_chat({})
                operation.assert_not_called()

    def test_fixed_claim_uses_revision_and_rechecks_after_pause(self):
        before = self.fixed_state()
        paused = {**before, 'revision': 8, 'draining': True, 'busy': 1}
        with patch.object(controller, 'owner_request', side_effect=[before, paused]), \
             patch.object(controller, 'owner_operation', return_value=paused) as operation:
            with self.assertRaisesRegex(RuntimeError, 'arrived before pause'):
                controller.claim_chat({})
            self.assertEqual([(c.args[1], c.args[2]) for c in operation.call_args_list],
                             [('pause', 7), ('resume', 8)])

    def test_fixed_restore_uses_actual_profile_not_saved_alias(self):
        state = self.fixed_state()
        lease = {'revision': 7, 'profile_id': 'rtx5080.fixed-64k'}
        with patch.object(controller, 'owner_request', return_value=state), \
             patch.object(controller, 'owner_operation') as operation, \
             patch.object(controller, 'command') as command, \
             patch.object(controller.modelctl, 'api', return_value={'choices': [{}]}) as api, \
             patch.object(controller.modelctl, 'current', return_value=lease['profile_id']), \
             patch.object(controller.modelctl, 'selection') as selection:
            result = controller.restore_chat({'service': 'chat.service'}, lease, True)
            self.assertTrue(result['admission_resumed'])
            command.assert_called_once_with('start', 'chat.service')
            self.assertEqual(api.call_args.args[2]['model'], lease['profile_id'])
            selection.assert_not_called()
            self.assertEqual(operation.call_args.args[1:], ('resume', 7))

    def test_fixed_restore_preserves_operator_changes_and_cold_backend(self):
        for change in ({'enabled': False}, {'revision': 8}):
            state = self.fixed_state(); state.update(change)
            with patch.object(controller, 'owner_request', return_value=state), \
                 patch.object(controller, 'command') as command, \
                 patch.object(controller, 'owner_operation') as operation:
                result = controller.restore_chat({}, {'revision': 7, 'profile_id': 'old'}, True)
                self.assertFalse(result['restored'])
                command.assert_not_called(); operation.assert_not_called()
        with patch.object(controller, 'owner_request', return_value=self.fixed_state()), \
             patch.object(controller, 'owner_operation'), patch.object(controller, 'command') as command, \
             patch.object(controller.modelctl, 'api') as api:
            controller.restore_chat({'service': 'chat.service'}, {'revision': 7, 'profile_id': None}, True)
            command.assert_called_once_with('start', 'chat.service')
            api.assert_not_called()

    def test_fixed_claim_captures_resident_from_paused_snapshot(self):
        before = self.fixed_state()
        paused = {**before, 'revision': 8, 'draining': True, 'profile_id': 'actual-fixed-profile'}
        with patch.object(controller, 'owner_request', return_value=before), \
             patch.object(controller, 'owner_operation', return_value=paused), \
             patch.object(controller.modelctl, 'assert_idle'):
            self.assertEqual(controller.claim_chat({}), {'revision': 8, 'profile_id': 'actual-fixed-profile'})

    def test_failed_fixed_restore_never_resumes_admission(self):
        with patch.object(controller, 'owner_request', return_value=self.fixed_state()), \
             patch.object(controller, 'command'), patch.object(controller, 'owner_operation') as operation, \
             patch.object(controller.modelctl, 'api', side_effect=[{}, {'choices': []}]):
            with self.assertRaisesRegex(RuntimeError, 'restoration failed'):
                controller.restore_chat({'service': 'chat.service'},
                                        {'revision': 7, 'profile_id': 'rtx5080.fixed-64k'}, True)
            operation.assert_not_called()

    def test_cold_advisory_uncertainty_requires_native_idle_verification(self):
        state = {**self.fixed_state(), 'state': 'cold', 'uncertain': True, 'profile_id': None}
        paused = {**state, 'state': 'paused', 'revision': 8}
        with patch.object(controller, 'owner_request', return_value=state), \
             patch.object(controller, 'owner_operation', return_value=paused), \
             patch.object(controller.modelctl, 'assert_idle') as idle:
            self.assertEqual(controller.claim_chat({})['profile_id'], None)
            idle.assert_called_once()
        with patch.object(controller, 'owner_request', side_effect=[state, paused]), \
             patch.object(controller, 'owner_operation', return_value=paused), \
             patch.object(controller.modelctl, 'assert_idle', side_effect=RuntimeError('unknown slots')):
            with self.assertRaisesRegex(RuntimeError, 'unknown slots'):
                controller.claim_chat({})

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

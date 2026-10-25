import subprocess
import fcntl
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from shared.backend_watch import ensure_unit,reconcile

class BackendWatchTests(unittest.TestCase):
    def test_image_workload_lock_prevents_restarting_conflicting_chat(self):
        reg={'aliases':['rtx5080'],'service':'rtx5080.service'}
        with tempfile.TemporaryDirectory() as temp, patch('shared.backend_watch.modelctl.ROOT',Path(temp)), \
             patch('shared.backend_watch.ensure_unit',return_value='active') as unit, \
             patch('shared.backend_watch.off_marker') as off, patch('shared.backend_watch.stop_marker') as stopped, \
             patch('shared.backend_watch.modelctl.assert_device_ready') as device:
            off.return_value.exists.return_value=False;stopped.return_value.exists.return_value=False
            with (Path(temp)/'.rtx5080.lock').open('a') as image_lock:
                fcntl.flock(image_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                self.assertEqual(reconcile(reg)['backend'],'workload-busy')
            unit.assert_called_once_with('lario-admission@rtx5080.service',unittest.mock.ANY)
            device.assert_not_called()
    def runner(self,enabled='enabled',state='inactive'):
        calls=[]
        def run(args):
            calls.append(args)
            text=enabled if 'is-enabled' in args else state if 'show' in args else ''
            return subprocess.CompletedProcess(args,0,text,'')
        return run,calls

    def test_active_backend_is_never_restarted(self):
        run,calls=self.runner(state='active')
        self.assertEqual(ensure_unit('arcB70.service',run),'active')
        self.assertFalse(any('start' in c for c in calls))

    def test_disabled_unit_is_not_started(self):
        run,calls=self.runner(enabled='disabled')
        self.assertEqual(ensure_unit('arcB70.service',run),'not-enabled')
        self.assertEqual(len(calls),1)

    def test_missing_enabled_unit_gets_nonblocking_start(self):
        run,calls=self.runner()
        self.assertEqual(ensure_unit('arcB70.service',run),'start-requested')
        self.assertEqual(calls[-1],['systemctl','--user','start','--no-block','arcB70.service'])

    def test_off_intent_preserves_backend_and_gateway_access(self):
        reg={'aliases':['arcB70'],'service':'arcB70.service'}
        with patch('shared.backend_watch.ensure_unit',return_value='active') as unit, patch('shared.backend_watch.off_marker') as marker:
            marker.return_value.exists.return_value=True
            self.assertEqual(reconcile(reg)['backend'],'off')
            unit.assert_called_once()
            self.assertIn('lario-admission@arcB70.service',unit.call_args.args)

    def test_missing_device_waits_for_next_tick(self):
        reg={'aliases':['arcB70'],'service':'arcB70.service'}
        with patch('shared.backend_watch.ensure_unit',return_value='active') as unit, patch('shared.backend_watch.off_marker') as off, patch('shared.backend_watch.stop_marker') as stopped, patch('shared.backend_watch.modelctl.assert_not_held'), patch('shared.backend_watch.modelctl.assert_device_ready',side_effect=RuntimeError('not ready')):
            off.return_value.exists.return_value=False;stopped.return_value.exists.return_value=False
            self.assertEqual(reconcile(reg)['backend'],'waiting')
            unit.assert_called_once()

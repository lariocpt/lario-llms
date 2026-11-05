import unittest
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch
from types import SimpleNamespace
from arcB70.vllm import supervisor as m

class HealthTests(unittest.TestCase):
    def run_probe(self, probes, timeout=1800):
        values=iter(probes); ticks=[0]; count=[0]
        def probe():
            count[0]+=1
            return next(values)
        def sleep(seconds): ticks[0]+=seconds
        with self.assertRaises(RuntimeError) as caught:
            m.supervise(SimpleNamespace(poll=lambda:None),probe,clock=lambda:ticks[0],
                        sleep=sleep,startup_timeout=timeout)
        return str(caught.exception),count[0]
    def test_loading_then_dead_engine_recovers_after_three_failures(self):
        error,count=self.run_probe([False,False,True,False,False,False])
        self.assertIn('consecutive',error);self.assertEqual(count,6)
    def test_transient_failure_resets_on_success(self):
        error,count=self.run_probe([True,False,False,True,False,False,False])
        self.assertIn('consecutive',error);self.assertEqual(count,7)
    def test_startup_is_bounded(self):
        error,count=self.run_probe([False]*4,timeout=20)
        self.assertIn('startup',error);self.assertEqual(count,3)
    def test_clean_unexpected_exit_is_a_failure(self):
        with self.assertRaisesRegex(RuntimeError,'container exited: 0'):
            m.supervise(SimpleNamespace(poll=lambda:0,returncode=0),lambda:True)

class RecoveryTests(unittest.TestCase):
    def test_stopped_container_is_removed_by_id_without_force(self):
        result=SimpleNamespace(stdout='{"ID":"old-id","State":"exited"}\n')
        with patch.object(m.subprocess,'run',return_value=result) as run:
            m.clear_stopped_container()
        self.assertEqual(run.call_args_list[-1].args[0],['docker','rm','old-id'])

    def test_running_container_is_preserved_even_if_unhealthy(self):
        for state in ('running','restarting','paused','removing'):
            with self.subTest(state=state):
                result=SimpleNamespace(stdout='{"ID":"live-id","State":"'+state+'"}\n')
                with patch.object(m.subprocess,'run',return_value=result) as run:
                    with self.assertRaisesRegex(RuntimeError,'refusing'):
                        m.clear_stopped_container()
                    self.assertEqual(run.call_count,1)

    def test_stop_timeout_still_forces_removal_of_owned_id(self):
        with tempfile.TemporaryDirectory() as directory:
            cidfile=Path(directory)/'id';cidfile.write_text('owned-id\n')
            process=Mock();process.poll.return_value=None
            with patch.object(m.subprocess,'run',side_effect=[
                    subprocess.TimeoutExpired('docker stop',15),SimpleNamespace(returncode=0)]) as run:
                m.cleanup(process,cidfile)
            self.assertEqual(run.call_args_list[-1].args[0],['docker','rm','-f','owned-id'])
            process.terminate.assert_called_once()
            process.wait.assert_called_once_with(timeout=5)

    def test_launch_conflict_cannot_remove_someone_elses_container(self):
        with tempfile.TemporaryDirectory() as directory:
            process=Mock();process.poll.return_value=125
            with patch.object(m.subprocess,'run') as run:
                m.cleanup(process,Path(directory)/'missing-id')
            run.assert_not_called()

    def test_unresponsive_docker_does_not_leave_runner_waiting_forever(self):
        with tempfile.TemporaryDirectory() as directory:
            cidfile=Path(directory)/'id';cidfile.write_text('owned-id')
            process=Mock();process.poll.return_value=None
            process.wait.side_effect=[subprocess.TimeoutExpired('docker run',5),0]
            with patch.object(m.subprocess,'run',side_effect=subprocess.TimeoutExpired('docker',15)):
                m.cleanup(process,cidfile)
            process.kill.assert_called_once()

    def test_engine_failure_runs_cleanup_and_preserves_error(self):
        process=Mock()
        with patch.object(m,'clear_stopped_container'), \
             patch.object(m.subprocess,'Popen',return_value=process) as popen, \
             patch.object(m,'supervise',side_effect=RuntimeError('dead engine')), \
             patch.object(m,'cleanup') as cleanup:
            with self.assertRaisesRegex(RuntimeError,'dead engine'):
                m.run(['docker','run','--rm','image'],11447,'private-key')
            argv=popen.call_args.args[0]
            self.assertEqual(argv[:3],['docker','run','--cidfile'])
            self.assertNotIn('private-key',argv)
            cleanup.assert_called_once_with(process,Path(argv[3]))
if __name__=='__main__':unittest.main()

import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from rtx5080 import monitor


class MonitorTests(unittest.TestCase):
    def exercise(self,enforced=False,busy=False):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,{'XDG_STATE_HOME':directory},clear=True):
            def runtime(reg):
                if enforced:os.environ.update(LARIO_ADMISSION_ENABLED='1',LARIO_AUXILIARY_KEY='synthetic-auxiliary-key')
            with patch.object(monitor,'load_runtime',side_effect=runtime) as loaded, \
                 patch.object(monitor.subprocess,'run'),patch.object(monitor,'current',return_value='qwen3.8'), \
                 patch.object(monitor,'assert_idle',side_effect=RuntimeError('busy') if busy else None), \
                 patch.object(monitor,'api',side_effect=['OK',{'choices':[{}]}]) as api, \
                 patch.object(monitor.urllib.request,'urlopen') as public:
                public.return_value.__enter__.return_value=io.BytesIO(b'{"choices":[{}]}')
                monitor.main()
                loaded.assert_called_once()
                return api.call_args_list,public.call_args_list,(Path(directory)/'vision-monitor/last-active').exists()

    def test_enforced_active_probe_uses_public_auxiliary_budget(self):
        calls,public,stamp=self.exercise(enforced=True)
        self.assertEqual([call.args[1] for call in calls],['/health'])
        request=public[0].args[0]
        self.assertEqual(request.full_url,'http://127.0.0.1:11435/v1/chat/completions')
        self.assertEqual(request.get_header('Authorization'),'Bearer synthetic-auxiliary-key')
        self.assertTrue(stamp)

    def test_busy_or_unknown_occupancy_does_not_start_an_active_probe(self):
        calls,public,stamp=self.exercise(enforced=True,busy=True)
        self.assertEqual([call.args[1] for call in calls],['/health'])
        self.assertEqual(public,[]);self.assertFalse(stamp)

    def test_legacy_monitor_still_probes_current_resident(self):
        calls,public,stamp=self.exercise()
        self.assertEqual(calls[-1].args[2]['model'],'qwen3.8')
        self.assertEqual(public,[]);self.assertTrue(stamp)


if __name__=='__main__':unittest.main()

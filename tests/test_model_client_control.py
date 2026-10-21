import json
import subprocess
import tempfile
import unittest
from shared.serving.client_control import control


class ClientControlTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.body={'operation':'cancel','session_id':'ses_123','run_id':'msg_456',
                   'instance_id':'instance-123','location':self.temp.name}

    def test_forwards_only_exact_identity_to_guarded_rpc(self):
        def runner(args,**kwargs):
            if args[2]=='GET':
                return subprocess.CompletedProcess(args,0,json.dumps({'data':{'location':{'directory':self.temp.name}}}),'')
            self.assertEqual(args[:3],['opencode','api','POST'])
            self.assertIn('/api/rpc/lario-model-control/cancel?',args[3])
            self.assertEqual(json.loads(args[-1])['input']['run_id'],'msg_456')
            return subprocess.CompletedProcess(args,0,json.dumps({'output':{'status':'stale_run','interrupted':False}}),'')
        self.assertEqual(control(self.body,runner)['status'],'stale_run')

    def test_rejects_general_api_or_shell_requests(self):
        for change in ({'operation':'exec'},{'run_id':'$(touch /tmp/no)'},{'location':'relative'},{'command':'sh'}):
            with self.assertRaises(ValueError):control({**self.body,**change},lambda *a,**k:self.fail('must not execute'))

    def test_failed_client_never_reports_interruption(self):
        with self.assertRaises(RuntimeError):
            control(self.body,lambda *a,**k:subprocess.CompletedProcess([],1,'','private error'))

import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error
import io

SOURCE = Path(__file__).resolve().parents[1]/'rtx5080/image-generation/image_tools.py'


def load(enabled=True):
    spec=importlib.util.spec_from_file_location('image_describe_test',SOURCE)
    module=importlib.util.module_from_spec(spec)
    with patch.dict(os.environ,{'LARIO_IMAGES_ALLOW_VISION':'1' if enabled else '0'}):
        spec.loader.exec_module(module)
    return module


class ImageDescribeTests(unittest.TestCase):
    def setUp(self):
        self.tool=load()
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.image=self.root/'picture.png';self.image.write_bytes(b'\x89PNG\r\n\x1a\nfixture')
        self.secret='private-consumer-key-which-must-not-leak'
        self.keys=self.root/'clients.json';self.keys.write_text(json.dumps({'rtx5080':{'apiKey':self.secret}}))
        self.env=patch.dict(os.environ,{'LARIO_MODEL_CLIENTS_FILE':str(self.keys)});self.env.start();self.addCleanup(self.env.stop)

    def test_modes_select_fixed_profiles_and_keep_key_private(self):
        catalog={'data':[{'id':'rtx5080.describe.fixed-64k'},{'id':'rtx5080.ocr.fixed-32k'},{'id':'rtx5080.qwen3.8.text'}]}
        response={'choices':[{'message':{'content':'A blue circle.'},'finish_reason':'stop'}]}
        for mode in ['describe','ocr']:
            with patch.object(self.tool,'vision_http',side_effect=[catalog,response]) as http, \
                 patch.object(self.tool.socket,'gethostname',return_value='bigcachy'):
                result=self.tool.call('image_describe',{'images':[str(self.image)],'mode':mode})
                self.assertEqual(http.call_args.args[0],'http://127.0.0.1:11435')
                payload=http.call_args.args[3]
                self.assertEqual(payload['model'],'rtx5080.'+mode+('.fixed-64k' if mode=='describe' else '.fixed-32k'))
                self.assertTrue(payload['messages'][0]['content'][1]['image_url']['url'].startswith('data:image/png;base64,'))
                self.assertNotIn(self.secret,json.dumps(result))
                self.assertEqual(result['description'],'A blue circle.')

    def test_remote_client_uses_owner_tailnet(self):
        with patch.object(self.tool.socket,'gethostname',return_value='cachyos-mini-mobile'), \
             patch.object(self.tool,'vision_http',return_value={'data':[]}) as http:
            with self.assertRaisesRegex(RuntimeError,'No unique'):
                self.tool.describe({'images':[str(self.image)]})
            self.assertEqual(http.call_args.args[0],'http://100.127.91.5:11435')

    def test_invalid_local_inputs_do_not_reach_owner(self):
        invalid=[{}, {'images':[]}, {'images':['relative.png']}, {'images':[str(self.image)]*5},
                 {'images':[str(self.image)],'max_tokens':True}, {'images':[str(self.image)],'mode':'text'},
                 {'images':[str(self.image)],'prompt':''}, {'images':[str(self.image)],'force':True}]
        with patch.object(self.tool,'vision_http') as http:
            for args in invalid:
                with self.assertRaises(ValueError):self.tool.call('image_describe',args)
            self.image.write_text('not an image')
            with self.assertRaisesRegex(ValueError,'PNG, JPEG or WebP'):
                self.tool.describe({'images':[str(self.image)]})
            http.assert_not_called()

    def test_missing_keys_and_ambiguous_catalog_fail_closed(self):
        self.keys.unlink()
        with patch.object(self.tool,'vision_http') as http:
            with self.assertRaisesRegex(RuntimeError,'credential unavailable'):
                self.tool.describe({'images':[str(self.image)]})
            http.assert_not_called()
        self.keys.write_text(json.dumps({'rtx5080':{'apiKey':self.secret}}))
        with patch.object(self.tool,'vision_http',return_value={'data':[{'id':'rtx5080.describe.a'},{'id':'rtx5080.describe.b'}]}):
            with self.assertRaisesRegex(RuntimeError,'No unique'):
                self.tool.describe({'images':[str(self.image)]})

    def test_http_errors_do_not_echo_backend_body(self):
        for status in [401,403,409,423,429,503]:
            opener=unittest.mock.Mock()
            opener.open.side_effect=urllib.error.HTTPError('http://owner',status,'bad',{},io.BytesIO(self.secret.encode()))
            with patch.object(self.tool.urllib.request,'build_opener',return_value=opener):
                with self.assertRaisesRegex(RuntimeError,str(status)) as raised:
                    self.tool.vision_http('http://127.0.0.1:11435',self.secret,'/v1/models')
                self.assertNotIn(self.secret,str(raised.exception))
                self.assertEqual(opener.open.call_args.args[0].get_header('Authorization'),'Bearer '+self.secret)

    def test_unenabled_client_has_no_description_tool(self):
        disabled=load(False)
        self.assertNotIn('image_describe',{x['name'] for x in disabled.TOOLS})
        with self.assertRaises(ValueError):disabled.call('image_describe',{'images':[str(self.image)]})

    def test_small_ui_review_prefers_3060ti_and_reports_actual_device(self):
        self.keys.write_text(json.dumps({h:{'apiKey':self.secret} for h in ('rtx3060ti','rtx5080')}))
        for mode in ('describe','ocr'):
            catalog={'data':[{'id':'rtx3060ti.'+mode+'.fixed'}]}
            response={'choices':[{'message':{'content':'Button spacing is uneven.'}}]}
            with patch.object(self.tool.socket,'gethostname',return_value='cachyos-mini-mobile'), \
                 patch.object(self.tool,'vision_http',side_effect=[catalog,response]) as http:
                result=self.tool.describe({'images':[str(self.image)],'mode':mode})
            self.assertEqual(result['hardware'],'rtx3060ti')
            self.assertEqual(http.call_args.args[0],'http://127.0.0.1:11438')

    def test_unplugged_busy_or_off_local_card_falls_back_without_forcing(self):
        self.keys.write_text(json.dumps({h:{'apiKey':self.secret} for h in ('rtx3060ti','rtx5080')}))
        ti={'data':[{'id':'rtx3060ti.describe.fixed'}]}
        rtx={'data':[{'id':'rtx5080.describe.fixed'}]}
        reply={'choices':[{'message':{'content':'Fallback review.'}}]}
        for failure in (self.tool.VisionUnavailable('device absent'),self.tool.VisionUnavailable('HTTP 423 Off'),self.tool.VisionUnavailable('HTTP 429 busy')):
            with patch.object(self.tool.socket,'gethostname',return_value='cachyos-mini-mobile'), \
                 patch.object(self.tool,'vision_http',side_effect=[ti,failure,rtx,reply]) as http:
                result=self.tool.describe({'images':[str(self.image)]})
            self.assertEqual(result['hardware'],'rtx5080')
            self.assertEqual(len(result['fallback']),1)
            self.assertEqual([c.args[2] for c in http.call_args_list],['/v1/models','/v1/chat/completions']*2)

    def test_large_or_many_images_skip_local_card(self):
        self.keys.write_text(json.dumps({h:{'apiKey':self.secret} for h in ('rtx3060ti','rtx5080')}))
        catalog={'data':[{'id':'rtx5080.describe.fixed'}]}
        response={'choices':[{'message':{'content':'Larger review.'}}]}
        for count,extra in ((3,0),(1,6*1024*1024)):
            self.image.write_bytes(b'\x89PNG\r\n\x1a\n'+b'x'*extra)
            with patch.object(self.tool.socket,'gethostname',return_value='cachyos-mini-mobile'), \
                 patch.object(self.tool,'vision_http',side_effect=[catalog,response]) as http:
                result=self.tool.describe({'images':[str(self.image)]*count})
            self.assertEqual(result['hardware'],'rtx5080')
            self.assertTrue(all(':11435' in c.args[0] for c in http.call_args_list))


if __name__=='__main__':unittest.main()

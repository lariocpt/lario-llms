import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import urllib.error

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
        self.keys=self.root/'clients.json'
        self.keys.write_text(json.dumps({h:{'apiKey':self.secret} for h in ('gdp7900xt','rtx3060ti','gkm3060ti','rtx5080')}))
        self.env=patch.dict(os.environ,{'LARIO_MODEL_CLIENTS_FILE':str(self.keys),'LARIO_IMAGES_VISION_ENDPOINTS':json.dumps({'gdp3060ti':'http://gpd:11438','gkm3060ti':'http://gkm:11438'})});self.env.start();self.addCleanup(self.env.stop)
        self.guard=patch.object(self.tool,'owner',side_effect=AssertionError('Unexpected owner execution'))
        self.guard.start();self.addCleanup(self.guard.stop)

    def test_radeon_modes_borrow_owner_and_preserve_pixels_without_exposing_keys(self):
        for mode in ('describe','ocr'):
            response={'description':'A blue circle.','hardware':'gdp7900xt','owner':'cachyos-mini-mobile','model':'fixed-'+mode,'chat_restore':{'restored':True}}
            with patch.object(self.tool,'owner',return_value=response) as owner,patch.object(self.tool,'vision_http') as http:
                result=self.tool.describe({'images':[str(self.image)],'mode':mode})
                self.assertEqual(owner.call_args.args[0],'describe')
                self.assertEqual(owner.call_args.kwargs['hardware'],'gdp7900xt')
                payload=owner.call_args.args[1]
                self.assertEqual(payload['mode'],mode)
                self.assertTrue(payload['messages'][0]['content'][1]['image_url']['url'].startswith('data:image/png;base64,'))
                self.assertNotIn(self.secret,json.dumps(result))
                self.assertTrue(result['chat_restore']['restored'])
                http.assert_not_called()

    def test_busy_off_or_absent_radeon_falls_back_to_small_vision_not_rtx(self):
        catalog={'data':[{'id':'rtx3060ti.describe.fixed'}]}
        reply={'choices':[{'message':{'content':'Fallback review.'}}]}
        for failure in ('busy','Off','absent'):
            with patch.object(self.tool,'owner',side_effect=self.tool.VisionUnavailable(failure)),patch.object(self.tool.socket,'gethostname',return_value='cachyos-mini-mobile'),patch.object(self.tool,'vision_http',side_effect=[catalog,reply]) as http:
                result=self.tool.describe({'images':[str(self.image)]})
                self.assertEqual(result['hardware'],'gdp3060ti')
                self.assertEqual(len(result['fallback']),1)
                self.assertTrue(all(':11435' not in c.args[0] for c in http.call_args_list))

    def test_large_requests_never_fall_back_to_rtx_or_small_cards(self):
        with patch.object(self.tool,'owner',side_effect=self.tool.VisionUnavailable('busy')),patch.object(self.tool,'vision_http') as http:
            with self.assertRaisesRegex(RuntimeError,'busy'):
                self.tool.describe({'images':[str(self.image)]*3})
            http.assert_not_called()

    def test_missing_radeon_credential_uses_available_small_card(self):
        self.keys.write_text(json.dumps({'gkm3060ti':{'apiKey':self.secret}}))
        with patch.object(self.tool.socket,'gethostname',return_value='l-dev-ai'),patch.object(self.tool,'vision_http',side_effect=[{'data':[{'id':'gkm3060ti.describe.fixed'}]},{'choices':[{'message':{'content':'Review'}}]}]):
            result=self.tool.describe({'images':[str(self.image)]})
            self.assertEqual(result['hardware'],'gkm3060ti')

    def test_invalid_inputs_do_not_reach_an_owner(self):
        invalid=[{}, {'images':[]}, {'images':['relative.png']}, {'images':[str(self.image)]*5}, {'images':[str(self.image)],'max_tokens':True}, {'images':[str(self.image)],'mode':'text'}, {'images':[str(self.image)],'force':True}]
        with patch.object(self.tool,'vision_http') as http:
            for args in invalid:
                with self.assertRaises(ValueError):self.tool.call('image_describe',args)
            http.assert_not_called()

    def test_http_failures_never_echo_credentials(self):
        for status in (401,403,409,423,429,503):
            opener=Mock();opener.open.side_effect=urllib.error.HTTPError('http://owner',status,'bad',{},io.BytesIO(self.secret.encode()))
            with patch.object(self.tool.urllib.request,'build_opener',return_value=opener):
                with self.assertRaises(RuntimeError) as failure:self.tool.vision_http('http://owner',self.secret,'/v1/models')
                self.assertNotIn(self.secret,str(failure.exception))

    def test_disabled_client_cannot_describe(self):
        with self.assertRaises(RuntimeError):load(False).call('image_describe',{'images':[str(self.image)]})

if __name__=='__main__':unittest.main()

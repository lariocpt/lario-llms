import contextlib
import io
import json
from pathlib import Path
import unittest

from shared import modelctl

ROOT=Path(__file__).resolve().parents[1]


class ModelOptionsTests(unittest.TestCase):
    def registry(self,hardware):
        return json.loads((ROOT/hardware/'models.json').read_text())

    def test_flash_128k_has_more_slots_and_reuses_weights(self):
        reg=self.registry('geekom')
        baseline=modelctl.effective_models(reg,'balanced')
        candidate=modelctl.effective_models(reg,'flash-128k')
        flash=candidate['qwen38-flash']
        self.assertEqual((flash['context'],flash['slots'],flash['reserved']),(131072,6,2))
        self.assertGreater(flash['slots'],baseline['qwen38-flash']['slots'])
        self.assertEqual(flash['args'],reg['models']['qwen38-flash']['args'])
        self.assertEqual(modelctl.fleet_capacity(flash['slots'],flash['reserved'],flash['context']),4)
        for key in reg['models']:
            if key!='qwen38-flash':self.assertEqual(candidate[key],reg['models'][key])

    def test_menu_filters_irrelevant_and_disabled_options(self):
        reg=self.registry('rtx5080');options=modelctl.selection_options(reg)
        self.assertIn(('qwen3.8','fast-64k'),options)
        self.assertNotIn(('qwen3.8','fast-128k'),options)
        self.assertNotIn(('ocr','fast-32k'),options)
        self.assertEqual(len(options),3)
        options=modelctl.selection_options(self.registry('7900xt'))
        self.assertIn(('qwen3.8','fast-128k'),options)
        self.assertFalse(any(preset.startswith('cpu-') for _,preset in options))

    def test_numbers_and_explicit_options_resolve_the_same_pair(self):
        reg=self.registry('geekom');options=modelctl.selection_options(reg)
        number=options.index(('qwen38-flash','flash-128k'))+1
        self.assertEqual(modelctl.resolve_option(reg,str(number)),('qwen38-flash','flash-128k'))
        self.assertEqual(modelctl.resolve_option(reg,'qwen38-flash@flash-128k'),('qwen38-flash','flash-128k'))
        for invalid in ['0','1000','qwen38-flash@fast-32k']:
            with self.assertRaises(ValueError):modelctl.resolve_option(reg,invalid)

    def test_menu_reports_actual_geometry_and_selection(self):
        reg=self.registry('geekom')
        reg['presets']['flash-128k']['experimental']=True
        out=io.StringIO()
        with contextlib.redirect_stdout(out):modelctl.print_options(reg,'qwen38-flash','flash-128k')
        self.assertIn('qwen38-flash@flash-128k: 6 x 131072 tokens; 2 reserved',out.getvalue())
        self.assertIn('[experimental] *',out.getvalue())

    def test_promoting_flash_does_not_promote_untested_dense_models(self):
        reg=self.registry('geekom')
        reg['presets']['balanced']['experimental']=True
        reg['presets']['balanced']['models']['qwen38-flash']['experimental']=False
        self.assertFalse(modelctl.is_experimental(reg,'qwen38-flash','balanced'))
        self.assertTrue(modelctl.is_experimental(reg,'qwen3.8-smart','balanced'))


if __name__=='__main__':unittest.main()

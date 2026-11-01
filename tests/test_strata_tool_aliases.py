import unittest

from geekom.strata.tool_aliases import parser_with_lario_aliases
from rtx5080.strata.tool_aliases import parser_with_lario_aliases as rtx_parser_with_aliases


class BaseParser:
    def __init__(self, names):
        self.schemas = dict.fromkeys(names, {})
        self.aliases = {'existing__tool': 'existing.tool'}


class ToolAliasesTests(unittest.TestCase):
    def test_exec_is_only_an_alias_for_a_compatible_declared_shell(self):
        class SchemaParser(BaseParser):
            def __init__(self, schemas):
                super().__init__([])
                self.schemas = schemas
        shell = {'parameters': {'type': 'object', 'required': ['command'],
                                'properties': {'command': {'type': 'string'}}}}
        for factory in [parser_with_lario_aliases, rtx_parser_with_aliases]:
            for schemas, expected in [
                ({'shell': shell}, 'shell'),
                ({'shell': shell, 'exec': {}}, None),
                ({'execute': shell}, None),
                ({'shell': {'parameters': {'type': 'object', 'required': ['code'],
                                          'properties': {'code': {'type': 'string'}}}}}, None),
                ({'shell': {'parameters': {'type': 'object', 'required': ['command'],
                                          'properties': {'command': {'type': 'integer'}}}}}, None),
                ({}, None),
            ]:
                with self.subTest(factory=factory.__module__, schemas=schemas):
                    self.assertEqual(factory(SchemaParser)(schemas).aliases.get('exec'), expected)

    def test_only_declared_tools_gain_aliases(self):
        parser = parser_with_lario_aliases(BaseParser)(['lario_images_image_describe'])
        self.assertEqual(parser.aliases['lario_images.image_describe'], 'lario_images_image_describe')
        self.assertNotIn('lario_web_testing.web_accessibility', parser.aliases)
        self.assertEqual(parser.aliases['existing__tool'], 'existing.tool')

    def test_exact_declared_name_wins(self):
        parser = parser_with_lario_aliases(BaseParser)([
            'lario_images_image_describe', 'lario_images.image_describe'])
        self.assertNotIn('lario_images.image_describe', parser.aliases)

    def test_does_not_guess_unknown_namespaces_or_machine_names(self):
        parser = parser_with_lario_aliases(BaseParser)(['other_image_describe'])
        self.assertEqual(parser.aliases, {'existing__tool': 'existing.tool'})

    def test_does_not_override_an_existing_alias(self):
        class ConflictingParser(BaseParser):
            def __init__(self, names):
                super().__init__(names)
                self.aliases['lario_images.image_describe'] = 'another.tool'
        parser = parser_with_lario_aliases(ConflictingParser)(['lario_images_image_describe'])
        self.assertEqual(parser.aliases['lario_images.image_describe'], 'another.tool')


if __name__ == '__main__':
    unittest.main()

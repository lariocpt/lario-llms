"""Accept the dotted spelling of declared Lario MCP tools in Strata output."""

NAMESPACES = (
    'lario_images', 'lario_design', 'lario_visual_testing', 'lario_web_testing',
    'lario_web_tools', 'lario_models', 'lario_intel', 'lario_encoder', 'lario_media',
)


def parser_with_lario_aliases(base):
    class LarioOutputParser(base):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            candidates = {}
            for name in self.schemas:
                if not isinstance(name, str):
                    continue
                for namespace in NAMESPACES:
                    prefix = namespace + '_'
                    if name.startswith(prefix) and name[len(prefix):]:
                        alias = namespace + '.' + name[len(prefix):]
                        candidates.setdefault(alias, set()).add(name)
            for alias, names in candidates.items():
                if len(names) != 1 or alias in self.schemas:
                    continue
                canonical = next(iter(names))
                if alias not in self.aliases or self.aliases[alias] == canonical:
                    self.aliases[alias] = canonical

    return LarioOutputParser

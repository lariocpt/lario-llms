"""Accept known compatible spellings of tools declared in the current request."""

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
            # Qwen can switch from OpenCode's `shell` to the `exec` spelling
            # mid-session. Never confuse this with `execute` (JavaScript),
            # override a declared exec tool, or route to a different schema.
            shell = self.schemas.get('shell') or {}
            parameters = shell.get('parameters') or {}
            command = (parameters.get('properties') or {}).get('command') or {}
            if ('exec' not in self.schemas and 'exec' not in self.aliases and
                    parameters.get('type') == 'object' and
                    set(parameters.get('required') or []) == {'command'} and
                    command.get('type') == 'string'):
                self.aliases['exec'] = 'shell'

    return LarioOutputParser

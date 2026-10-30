#!/usr/bin/env python3
"""Exercise the installed Strata frontend without loading a model or using a GPU."""
import argparse
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from geekom.strata.tool_aliases import parser_with_lario_aliases


def check(frontend):
    spec = importlib.util.spec_from_file_location('strata_alias_test_frontend', frontend)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    fixed = parser_with_lario_aliases(module.OutputParser)
    parameters = {'type': 'object', 'properties': {
        'urls': {'type': 'array', 'items': {'type': 'string'}},
        'images': {'type': 'array', 'items': {'type': 'string'}},
        'width': {'type': 'integer'}, 'prompt': {'type': 'string'}}}
    examples = [
        ('lario_images', 'image_describe', {'images': ['/tmp/a.png', '/tmp/b.png'], 'prompt': 'Review the art'}),
        ('lario_web_testing', 'web_accessibility', {'urls': ['http://localhost:8080/'], 'width': 400}),
        ('lario_web_tools', 'web_extract_meta', {'urls': ['http://localhost:8080/']}),
    ]

    def parse(parser, text, tool, stride, thinking=False):
        instance = parser(thinking=thinking, tools=[tool], stream_tools=True, declared_only=True)
        events = []
        for offset in range(0, len(text), stride):
            events.extend(instance.feed(text[offset:offset + stride]))
        events.extend(instance.finish('stop'))
        return events

    checks = 0
    for namespace, member, arguments in examples:
        canonical = namespace + '_' + member
        tool = {'name': canonical, 'parameters': parameters}
        params = ''.join('<parameter=' + key + '>\n' +
                         (value if isinstance(value, str) else json.dumps(value)) +
                         '\n</parameter>\n' for key, value in arguments.items())
        for name in [canonical, namespace + '.' + member, 'unknown.tool']:
            text = '<tool_call>\n<function=' + name + '>\n' + params + '</function>\n</tool_call>'
            for stride in [1, 7, len(text)]:
                for thinking in [False, True]:
                    sample = ('Checking.\n</think>\n' if thinking else '') + text
                    events = parse(fixed, sample, tool, stride, thinking)
                    calls = [event.call for event in events if event.kind == 'tool_call']
                    if name == 'unknown.tool':
                        assert not calls, 'Undeclared tool became executable'
                    else:
                        assert len(calls) == 1, (name, stride, thinking)
                        assert calls[0].name == canonical
                        assert calls[0].arguments == arguments
                        assert all(event.call.name == canonical for event in events if event.kind == 'tool_start')
                    checks += 1
        # Reproduce the actual failure with the original parser before asserting the fix.
        broken = '<tool_call>\n<function=' + namespace + '.' + member + '>\n' + params + '</function>\n</tool_call>'
        assert not any(event.kind == 'tool_call' for event in parse(module.OutputParser, broken, tool, 1))
    print(f'PASS: {checks} installed-parser checks; native/dotted names, streaming, thinking, typed arguments, unknown-name refusal')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--frontend', type=Path,
                        default=Path.home()/'strata/terminal/0.1.51/serve/frontend.py')
    check(parser.parse_args().frontend)

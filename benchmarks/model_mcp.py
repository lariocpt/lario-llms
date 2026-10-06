#!/usr/bin/env python3
"""Verify model MCP calls through real OpenCode v2, with switching disabled."""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time


def inspect_events(events):
    completed = set()
    outputs = []
    for event in events:
        if event.get('type') != 'tool_use':
            continue
        state = event.get('part', {}).get('state', {})
        if state.get('status') != 'completed':
            continue
        metadata = state.get('metadata', {}).get('metadata', {})
        completed.update(call['tool'] for call in metadata.get('toolCalls', [])
                         if call.get('status') == 'completed')
        try:
            outputs.append(json.loads(state.get('output', '')))
        except (ValueError, TypeError):
            pass
    options = next((output.get('options') for output in outputs
                    if isinstance(output, dict) and isinstance(output.get('options'), dict)), {})
    status = next((output.get('status') for output in outputs
                   if isinstance(output, dict) and isinstance(output.get('status'), dict)), {})
    return {
        'options_tool_completed': 'lario_models.model_options' in completed,
        'status_tool_completed': 'lario_models.model_status' in completed,
        'six_slot_option': any(option.get('id') == 'qwen38-flash@flash-128k'
                               and option.get('slots') == 6 and option.get('context') == 131072
                               for option in options.get('options', [])),
        'ready_rtx_resident': status.get('hardware') == 'rtx5080' and status.get('ready') is True
                              and isinstance(status.get('resident', {}).get('context'), int),
        'no_switch_executed': not any(tool.endswith('.model_switch') for tool in completed),
        'final_marker': any(event.get('type') == 'text' and event.get('part', {}).get('text', '')
                            .strip().endswith('MCP_MODELS_OK') for event in events),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    parser.add_argument('--suite', choices=['models', 'images'], default='models')
    args = parser.parse_args()
    service_path = Path.home() / '.local/state/opencode/service.json'
    before = json.loads(service_path.read_text())['pid']
    config_path = Path.home() / '.config/opencode/opencode.json'
    namespace = 'lario_images' if args.suite == 'images' else 'lario_models'
    server = json.loads(config_path.read_text())['mcp'][namespace]
    # OpenCode v2 rejects a partial legacy server definition before merging it.
    # Supply the complete definition, with management absent from its tool list.
    flag = 'LARIO_IMAGES_ALLOW_GENERATE' if args.suite == 'images' else 'LARIO_MODELS_ALLOW_SWITCH'
    server = {**server, 'environment': {**server.get('environment', {}), flag: '0'}}
    prompt = ('Use execute to call the lario_images image_options tool. Return its result as {images: result}. '
              'Confirm both qwen-image and flux-klein options. Do not generate an image or use other tools. '
              'Finish with MCP_IMAGES_OK only after the call succeeds.' if args.suite == 'images' else
              'Use execute to call the lario_models model_options tool for geekom and model_status for rtx5080. '
              'Return the results as {options, status}. Confirm the Flash Next six-slot 131072-token option '
              'and actual RTX resident/context. Do not switch models or use other tools. '
              'Finish with MCP_MODELS_OK only after both calls succeed.')
    with tempfile.TemporaryDirectory(prefix='lario-model-mcp-smoke-') as temporary:
        directory = Path(temporary)
        config = directory / 'opencode.json'
        config.write_text(json.dumps({'permission': {'*': 'deny', 'execute': 'allow',
                                                     namespace + '*': 'allow', 'tools.' + namespace + '.*': 'allow'},
                                      'mcp': {namespace: server}}))
        os.chmod(config, 0o600)
        start = time.monotonic()
        process = subprocess.Popen(
            ['opencode', 'run', '--standalone', '--auto', '--format', 'json', '--model',
             'rtx5080/rtx5080' if args.suite == 'images' else 'geekom/geekom', prompt],
            cwd=directory, env={**os.environ, 'OPENCODE_CONFIG': str(config)},
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
        try:
            stdout, _ = process.communicate(timeout=600)
        except BaseException:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.communicate(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.communicate()
            raise
    events = []
    for line in stdout.splitlines():
        try:
            events.append(json.loads(line))
        except ValueError:
            pass
    checks = inspect_events(events)
    if args.suite == 'images':
        completed = set()
        choices = []
        for event in events:
            state = event.get('part', {}).get('state', {})
            if event.get('type') != 'tool_use' or state.get('status') != 'completed':
                continue
            completed.update(call['tool'] for call in state.get('metadata', {}).get('metadata', {}).get('toolCalls', [])
                             if call.get('status') == 'completed')
            try:
                output = json.loads(state.get('output', ''))
                choices.extend(output.get('images', {}).get('models', []))
            except (ValueError, TypeError, AttributeError):
                pass
        checks = {'options_tool_completed': 'lario_images.image_options' in completed,
                  'both_options_returned': {'qwen-image', 'flux-klein'}.issubset(set(choices)),
                  'no_generation_executed': not any(tool.endswith('.image_generate') for tool in completed),
                  'final_marker': any(event.get('type') == 'text' and event.get('part', {}).get('text', '')
                                      .strip().endswith('MCP_IMAGES_OK') for event in events)}
    checks['background_pid_unchanged'] = before == json.loads(service_path.read_text())['pid']
    result = {'opencode_exit': process.returncode, 'wall_seconds': round(time.monotonic() - start, 3),
              'event_count': len(events), 'checks': checks,
              'passed': process.returncode == 0 and all(checks.values()),
              'scope': 'Actual standalone OpenCode v2; complete read-only MCP override; default Code Mode; no server restart.'}
    Path(args.output).write_text(json.dumps(result, indent=2) + '\n')
    descriptor = os.open('/tmp/lario-' + args.suite + '-mcp-smoke-events.jsonl', os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(descriptor, 0o600)
    with os.fdopen(descriptor, 'w') as file:
        file.write(stdout)
    print(json.dumps(result), flush=True)
    if not result['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()

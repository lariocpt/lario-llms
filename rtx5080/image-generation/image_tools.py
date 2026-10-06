#!/usr/bin/env python3
"""Local image-generation MCP; management-capable hosts use existing owner SSH."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys

ALLOW = os.getenv('LARIO_IMAGES_ALLOW_GENERATE', '0') == '1'
MODELS = ['qwen-image', 'flux-klein']
TOOLS = [{'name': 'image_options', 'description': 'List local RTX image-generation models and their exclusive-card/CPU-encoder policy. Owner clients also verify installation; consumer clients only list configured choices.',
          'inputSchema': {'type': 'object', 'properties': {}, 'additionalProperties': False}, 'annotations': {'readOnlyHint': True}}]
if ALLOW:
    TOOLS.append({'name': 'image_generate', 'description': 'Generate a local image only when explicitly requested. Borrows the idle, healthy RTX exclusively; refuses active chat, then restores its saved model/preset. The chat/vision endpoint is unavailable during generation. Returns the generated PNG path on bigcachy. No downloads, force or credentials.',
                  'inputSchema': {'type': 'object', 'properties': {
                      'model': {'type': 'string', 'enum': MODELS}, 'prompt': {'type': 'string', 'minLength': 1, 'maxLength': 12000},
                      'width': {'type': 'integer', 'minimum': 256, 'maximum': 1024, 'multipleOf': 64},
                      'height': {'type': 'integer', 'minimum': 256, 'maximum': 1024, 'multipleOf': 64},
                      'seed': {'type': 'integer', 'minimum': 0, 'maximum': 2 ** 63 - 1},
                      'steps': {'type': 'integer', 'minimum': 1, 'maximum': 40}},
                      'required': ['model', 'prompt'], 'additionalProperties': False}, 'annotations': {'readOnlyHint': False}})


def owner(operation, arguments):
    helper = Path.home() / 'Projects/personal/lario-llms/rtx5080/image-generation/controller.py'
    if socket.gethostname().split('.')[0] == 'bigcachy':
        command = [sys.executable, str(helper), operation]
    else:
        command = ['ssh', '-T', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=8', 'bigcachy',
                   'python3 ~/Projects/personal/lario-llms/rtx5080/image-generation/controller.py ' + operation]
    result = subprocess.run(command, input=json.dumps(arguments), text=True, capture_output=True,
                            timeout=3900 if operation == 'json' else 25)
    try:
        data = json.loads(result.stdout)
    except ValueError:
        raise RuntimeError('image owner unavailable; no completed image confirmed') from None
    if result.returncode or 'error' in data:
        raise RuntimeError(data.get('error', {}).get('message', 'image owner failed'))
    return data


def call(name, args):
    tool = next((tool for tool in TOOLS if tool['name'] == name), None)
    if tool is None or not isinstance(args, dict) or set(args) - set(tool['inputSchema']['properties']):
        raise ValueError('unknown or disabled image tool/arguments')
    if name == 'image_options':
        if ALLOW:
            return owner('options', {})
        return {'models': MODELS, 'owner': 'bigcachy', 'installed': None, 'generation_available': False,
                'scope': 'Configured choices only; installation/live GPU state not verified on this consumer.'}
    if args.get('model') not in MODELS or not isinstance(args.get('prompt'), str) or not 1 <= len(args['prompt'].strip()) <= 12000:
        raise ValueError('invalid image model/prompt')
    for name, value in args.items():
        if name in ('width', 'height') and (type(value) is not int or value % 64 or not 256 <= value <= 1024):
            raise ValueError('invalid dimensions')
        if name == 'steps' and (type(value) is not int or not 1 <= value <= 40):
            raise ValueError('invalid steps')
        if name == 'seed' and (type(value) is not int or not 0 <= value < 2 ** 63):
            raise ValueError('invalid seed')
    return owner('json', args)


def main():
    for line in sys.stdin:
        identifier = None
        try:
            request = json.loads(line)
            identifier = request.get('id')
            if identifier is None:
                continue
            method = request.get('method')
            if method == 'initialize':
                version = request.get('params', {}).get('protocolVersion', '2024-11-05')
                result = {'protocolVersion': version if version in ('2024-11-05', '2025-03-26', '2025-06-18') else '2024-11-05',
                          'capabilities': {'tools': {'listChanged': False}}, 'serverInfo': {'name': 'lario-images', 'version': '1.0.0'}}
            elif method == 'ping':
                result = {}
            elif method == 'tools/list':
                result = {'tools': TOOLS}
            elif method == 'tools/call':
                params = request['params']
                try:
                    data = call(params['name'], params.get('arguments', {}))
                    result = {'content': [{'type': 'text', 'text': json.dumps(data)}], 'isError': False}
                except Exception as error:
                    result = {'content': [{'type': 'text', 'text': str(error)[:500]}], 'isError': True}
            else:
                print(json.dumps({'jsonrpc': '2.0', 'id': identifier, 'error': {'code': -32601, 'message': 'Method not found'}}), flush=True)
                continue
            print(json.dumps({'jsonrpc': '2.0', 'id': identifier, 'result': result}), flush=True)
        except Exception as error:
            print(json.dumps({'jsonrpc': '2.0', 'id': identifier, 'error': {'code': -32600, 'message': str(error)[:500]}}), flush=True)


if __name__ == '__main__':
    main()

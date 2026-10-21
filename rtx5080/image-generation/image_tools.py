#!/usr/bin/env python3
"""Local image-generation MCP; management-capable hosts use existing owner SSH."""
import json
import base64
import os
from pathlib import Path
import socket
import subprocess
import sys
import urllib.error
import urllib.request

ALLOW = os.getenv('LARIO_IMAGES_ALLOW_GENERATE', '0') == '1'
ALLOW_VISION = os.getenv('LARIO_IMAGES_ALLOW_VISION', '0') == '1'
MODELS = ['qwen-image', 'flux-klein']
TOOLS = [{'name': 'image_options', 'description': 'List local RTX image-generation models and their exclusive-card/CPU-encoder policy. Owner clients also verify installation; consumer clients only list configured choices.',
          'inputSchema': {'type': 'object', 'properties': {}, 'additionalProperties': False}, 'annotations': {'readOnlyHint': True}}]
if ALLOW_VISION:
    TOOLS.append({'name': 'image_describe', 'description': 'Inspect existing local images using the authenticated RTX vision model while your coding model stays selected. Default mode describe uses the fixed RTX image-description profile; ocr uses the OCR/picture-comparison profile. Supply absolute image paths on this client and a question. Use this instead of curl, vision:8080, or asking for API keys. Refuses Off/busy hardware; never forces a swap. Supports PNG/JPEG/WebP, up to four images and 20 MiB total. Returns the actual model ID and its description, not a generated image.',
        'inputSchema': {'type': 'object', 'properties': {
            'images': {'type': 'array', 'minItems': 1, 'maxItems': 4,
                       'items': {'type': 'string', 'minLength': 1}},
            'prompt': {'type': 'string', 'minLength': 1, 'maxLength': 12000},
            'mode': {'type': 'string', 'enum': ['describe', 'ocr'], 'default': 'describe'},
            'max_tokens': {'type': 'integer', 'minimum': 1, 'maximum': 8192, 'default': 2048}},
            'required': ['images'], 'additionalProperties': False}, 'annotations': {'readOnlyHint': False}})
if ALLOW:
    TOOLS.append({'name': 'image_generate', 'description': 'Generate a local image only when explicitly requested. Borrows the idle, healthy RTX exclusively; refuses active chat, Off or paused serving, then restores the actual fixed profile (a cold backend stays cold). Operator policy changes are preserved. The chat/vision endpoint is unavailable during generation. Returns the generated PNG path on bigcachy. No downloads, force or credentials.',
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


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError('RTX vision redirect refused')


def vision_http(base, key, path, payload=None):
    request = urllib.request.Request(base + path,
        data=None if payload is None else json.dumps(payload).encode(),
        headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json',
                 'X-Lario-Kind': 'image-describe'})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open(request, timeout=1900 if payload else 15) as response:
            raw = response.read(2 * 1024 * 1024 + 1)
        if len(raw) > 2 * 1024 * 1024:
            raise RuntimeError('RTX vision response exceeded its bound')
        return json.loads(raw)
    except urllib.error.HTTPError as error:
        # Never return a backend body which could echo credentials or image data.
        status = error.code
        error.close()
        hint = {401: 'client credential missing or rejected', 403: 'client credential lacks RTX access',
                409: 'another profile is busy or loading', 423: 'RTX serving or profile is Off/paused/disabled',
                429: 'RTX vision capacity is occupied', 503: 'backend or device is unavailable'}.get(status, 'request failed')
        raise RuntimeError(f'RTX vision HTTP {status}: {hint}; no forced switch was made') from None
    except (urllib.error.URLError, OSError, ValueError):
        raise RuntimeError('RTX vision owner unavailable or returned an invalid response') from None


def describe(args):
    paths = args.get('images')
    mode = args.get('mode', 'describe')
    prompt = args.get('prompt', 'Describe this image accurately, including visible text, layout and relevant details.')
    maximum = args.get('max_tokens', 2048)
    if (not isinstance(paths, list) or not 1 <= len(paths) <= 4 or mode not in ('describe', 'ocr')
            or not isinstance(prompt, str) or not 1 <= len(prompt.strip()) <= 12000
            or type(maximum) is not int or not 1 <= maximum <= 8192):
        raise ValueError('invalid image description arguments')
    content = [{'type': 'text', 'text': prompt}]
    total = 0
    for value in paths:
        if not isinstance(value, str) or not Path(value).is_absolute():
            raise ValueError('image paths must be absolute paths on this client')
        path = Path(value)
        if not path.is_file():
            raise ValueError('image file does not exist on this client')
        with path.open('rb') as stream:
            data = stream.read(20 * 1024 * 1024 + 1)
        total += len(data)
        if total > 20 * 1024 * 1024:
            raise ValueError('images exceed 20 MiB total')
        if data.startswith(b'\x89PNG\r\n\x1a\n'):
            mime = 'image/png'
        elif data.startswith(b'\xff\xd8\xff'):
            mime = 'image/jpeg'
        elif data.startswith(b'RIFF') and data[8:12] == b'WEBP':
            mime = 'image/webp'
        else:
            raise ValueError('image must contain PNG, JPEG or WebP data')
        content.append({'type': 'image_url', 'image_url': {
            'url': 'data:' + mime + ';base64,' + base64.b64encode(data).decode()}})
    path = Path(os.getenv('LARIO_MODEL_CLIENTS_FILE', str(Path.home()/'.config/lario-admission/clients.json')))
    try:
        key = json.loads(path.read_text())['rtx5080']['apiKey']
        if not isinstance(key, str) or len(key) < 24:
            raise ValueError()
    except (OSError, ValueError, KeyError, TypeError):
        raise RuntimeError('Private RTX client credential unavailable; repair machine-setup client provisioning, do not paste keys into chat') from None
    base = 'http://127.0.0.1:11435' if socket.gethostname().split('.')[0] == 'bigcachy' else 'http://100.127.91.5:11435'
    catalogue = vision_http(base, key, '/v1/models')
    ids = [item['id'] for item in catalogue.get('data', []) if item.get('id', '').startswith('rtx5080.'+mode+'.')]
    if len(ids) != 1:
        raise RuntimeError('No unique fixed RTX vision profile found; repair the owner catalogue')
    response = vision_http(base, key, '/v1/chat/completions', {
        'model': ids[0], 'messages': [{'role': 'user', 'content': content}],
        'max_tokens': maximum, 'stream': False, 'chat_template_kwargs': {'enable_thinking': False}})
    choices = response.get('choices', [])
    text = choices[0].get('message', {}).get('content') if choices else None
    if not isinstance(text, str) or not text.strip():
        raise RuntimeError('RTX vision returned no completed description')
    return {'owner': 'bigcachy', 'model': ids[0], 'mode': mode, 'image_count': len(paths),
            'description': text, 'finish_reason': choices[0].get('finish_reason'),
            'usage': response.get('usage', {})}


def call(name, args):
    tool = next((tool for tool in TOOLS if tool['name'] == name), None)
    if tool is None or not isinstance(args, dict) or set(args) - set(tool['inputSchema']['properties']):
        raise ValueError('unknown or disabled image tool/arguments')
    if name == 'image_describe':
        return describe(args)
    if name == 'image_options':
        if ALLOW:
            result = owner('options', {})
        else:
            result = {'models': MODELS, 'owner': 'bigcachy', 'installed': None, 'generation_available': False,
                      'scope': 'Configured choices only; installation/live GPU state not verified on this consumer.'}
        result['vision'] = {'enabled': ALLOW_VISION, 'tool': 'image_describe',
                            'modes': ['describe', 'ocr'], 'input': 'Absolute image paths on this client'}
        return result
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
                          'capabilities': {'tools': {'listChanged': False}}, 'serverInfo': {'name': 'lario-images', 'version': '1.2.0'}}
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

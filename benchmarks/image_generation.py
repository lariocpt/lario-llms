#!/usr/bin/env python3
"""One guarded local image smoke; record measured memory, PNG and chat restoration."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import threading
import time

from telemetry import snapshot

REPO = Path(__file__).resolve().parents[1]
RUNTIME = Path('/mnt/xfs/AI_Models/image-generation/runtime/venv/bin/python')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', choices=['qwen-image', 'flux-klein'], required=True)
    parser.add_argument('--size', type=int, default=512)
    parser.add_argument('--steps', type=int)
    parser.add_argument('--output', required=True)
    parser.add_argument('--transport', choices=['controller', 'mcp'], default='controller')
    args = parser.parse_args()
    samples = []
    done = threading.Event()

    def sample():
        while True:
            row = snapshot()
            row['image_worker_active'] = subprocess.run(
                ['systemctl', '--user', 'is-active', 'lario-images.service'],
                capture_output=True, timeout=5).returncode == 0
            samples.append(row)
            if done.wait(2):
                break

    runtime = subprocess.run([str(RUNTIME), '-c',
        'import json,torch; print(json.dumps({"torch":torch.__version__,"cuda":torch.version.cuda,'
        '"available":torch.cuda.is_available(),"architectures":torch.cuda.get_arch_list(),'
        '"gpu":torch.cuda.get_device_name(0) if torch.cuda.is_available() else None}))'],
        capture_output=True, text=True, check=True)
    record = {'schema_version': 1, 'utc': datetime.now(timezone.utc).isoformat(),
              'scope': 'One synthetic image; shared-host sampled memory, not a quality or throughput benchmark.',
              'runtime': json.loads(runtime.stdout), 'model': args.model, 'size': args.size,
              'steps': args.steps, 'seed': 42, 'transport': args.transport}
    request = {'model': args.model, 'prompt': 'A clean blue app icon, a simple white mountain silhouette, flat vector illustration, no text',
               'width': args.size, 'height': args.size, 'seed': 42, 'steps': args.steps}
    sampler = threading.Thread(target=sample)
    sampler.start()
    started = time.monotonic()
    try:
        # The owned controller enforces its timeout and performs restoration in finally.
        if args.transport == 'mcp':
            messages = [{'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
                         'params': {'protocolVersion': '2025-06-18', 'capabilities': {},
                                    'clientInfo': {'name': 'lario-image-smoke', 'version': '1'}}},
                        {'jsonrpc': '2.0', 'method': 'notifications/initialized'},
                        {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'},
                        {'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call',
                         'params': {'name': 'image_generate', 'arguments': request}}]
            # Omit unset optional values; MCP schemas do not advertise JSON null.
            messages[-1]['params']['arguments'] = {key: value for key, value in request.items() if value is not None}
            run = subprocess.run([sys.executable, str(REPO / 'rtx5080/image-generation/image_tools.py')],
                                 input=''.join(json.dumps(message) + '\n' for message in messages),
                                 capture_output=True, text=True, env={**os.environ, 'LARIO_IMAGES_ALLOW_GENERATE': '1'})
            responses = {row['id']: row for row in map(json.loads, run.stdout.splitlines())}
            record['mcp_handshake'] = (responses[1]['result']['protocolVersion'] == '2025-06-18'
                                       and any(tool['name'] == 'image_generate' for tool in responses[2]['result']['tools']))
            called = responses[3]['result']
            result = ({'error': called['content'][0]['text']} if called.get('isError')
                      else json.loads(called['content'][0]['text']))
            exit_code = run.returncode or int(bool(called.get('isError')))
        else:
            run = subprocess.run([sys.executable, str(REPO / 'rtx5080/image-generation/controller.py'), 'json'],
                                 input=json.dumps(request), capture_output=True, text=True)
            result, exit_code = json.loads(run.stdout), run.returncode
        record.update(exit=exit_code, result=result, wall_seconds=round(time.monotonic() - started, 3))
        if exit_code == 0:
            images = []
            for filename in record['result']['images']:
                data = Path(filename).read_bytes()
                if data[:8] != b'\x89PNG\r\n\x1a\n' or data[12:16] != b'IHDR':
                    raise ValueError('output is not PNG')
                dimensions = list(struct.unpack('>II', data[16:24]))
                if dimensions != [args.size, args.size]:
                    raise ValueError('unexpected PNG dimensions')
                images.append({'path': filename, 'dimensions': dimensions, 'bytes': len(data),
                               'sha256': hashlib.sha256(data).hexdigest()})
            record['png_checks'] = images
            record['pass'] = (bool(images) and record['result'].get('chat_selection_preserved') is True
                              and record.get('mcp_handshake', True))
        else:
            record['pass'] = False
    except Exception as error:
        record.update(error_type=type(error).__name__)
        record['pass'] = False
    finally:
        done.set()
        sampler.join()
        samples.append(snapshot())
        record['samples'] = samples
        record['minimum_available_ram_gib'] = min(row['meminfo_kib']['MemAvailable'] for row in samples) / 1024 ** 2
        gpu_rows = [gpu for row in samples for gpu in (row['nvidia'] or [])]
        if gpu_rows:
            record['peak_rtx_vram_mib'] = max(row['used_mib'] for row in gpu_rows)
            record['minimum_rtx_free_vram_mib'] = min(row['total_mib'] - row['used_mib'] for row in gpu_rows)
        image_rows = [row for row in samples if row.get('image_worker_active')]
        image_gpu = [gpu for row in image_rows for gpu in (row['nvidia'] or [])]
        if image_gpu:
            record['peak_image_rtx_vram_mib'] = max(row['used_mib'] for row in image_gpu)
            record['minimum_image_rtx_free_vram_mib'] = min(row['total_mib'] - row['used_mib'] for row in image_gpu)
            record['minimum_image_available_ram_gib'] = min(row['meminfo_kib']['MemAvailable'] for row in image_rows) / 1024 ** 2
        record['swapin_page_delta'] = samples[-1]['pswpin_pages'] - samples[0]['pswpin_pages']
        record['swapout_page_delta'] = samples[-1]['pswpout_pages'] - samples[0]['pswpout_pages']
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps({key: value for key, value in record.items() if key != 'samples'}), flush=True)
    return 0 if record.get('pass') else 1


if __name__ == '__main__':
    raise SystemExit(main())

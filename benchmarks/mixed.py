#!/usr/bin/env python3
"""Sustained resident-only short/long/tool traffic with concurrent scoped telemetry."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from benchmarks.fixtures import VERSION, text_cases, tools
from benchmarks.quality import tool_case
from benchmarks.run import complete, reasoning_policy, resident
from benchmarks.telemetry import snapshot
from shared import modelctl


def geometry(item):
    import shlex
    argv = shlex.split(item['cmd'])
    slots = int(argv[argv.index('--parallel') + 1])
    return slots, int(argv[argv.index('-c') + 1]) // slots


def rtx_thermal_event(sample, hardware, limit):
    if hardware != 'rtx5080':
        return None
    gpu = sample.get('nvidia')
    if not gpu or any(row.get('temperature_c') is None or row['temperature_c'] >= limit for row in gpu):
        return {'telemetry': gpu, 'threshold_c': limit}
    return None


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('hardware', choices=['geekom', '7900xt', 'rtx5080'])
    p.add_argument('--base-url', required=True)
    p.add_argument('--seconds', type=int, default=1800)
    p.add_argument('--concurrency', type=int, default=1)
    p.add_argument('--max-gpu-temperature', type=int, default=84,
                   help='RTX benchmark stop threshold in Celsius; never changes fan/power settings')
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    if not 30 <= a.seconds <= 3600 or not 1 <= a.concurrency <= 6 or not 60 <= a.max_gpu_temperature <= 84:
        p.error('bounded 30–3600 seconds and 1–6 workers required')
    path = ROOT / a.hardware / 'models.json'
    reg = json.loads(path.read_text())
    modelctl.load_runtime(reg)
    modelctl.assert_not_held(reg)
    modelctl.assert_device_ready(reg)
    modelctl.assert_idle(reg)
    base = a.base_url.rstrip('/').removesuffix('/v1')
    key = os.environ.get('LARIO_BENCHMARK_KEY')
    before = resident(base, key=key)
    slots, context = geometry(before)
    if a.concurrency > slots or context < 16384:
        p.error('requested traffic exceeds resident slots/context')
    preflight = rtx_thermal_event(snapshot(), a.hardware, a.max_gpu_temperature)
    if preflight:
        modelctl.atomic(a.output, json.dumps({'passed': False, 'suite': 'sustained-mixed',
                         'hardware': a.hardware, 'preflight_thermal_refusal': preflight}, indent=2)+'\n')
        raise SystemExit('RTX thermal telemetry unavailable or at benchmark stop threshold')
    start = time.monotonic()
    end = start + a.seconds
    stop = threading.Event()
    samples, rows = [], []
    result = {'schema_version': 1, 'fixture_version': VERSION,
              'suite': 'sustained-mixed', 'hardware': a.hardware,
              'load_label': 'Hermes paused; other host activity not excluded',
              'scope': 'synthetic short/11k-input/tool traffic; separate coding/RAG suites; no admission isolation claim',
              'started_utc': datetime.now(timezone.utc).isoformat(),
              'registry_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
              'resident': before, 'context': context, 'concurrency': a.concurrency,
              'rtx_temperature_stop_c': a.max_gpu_temperature,
              'requested_seconds': a.seconds, 'rows': rows, 'samples': samples}

    def sample_loop():
        while not stop.is_set():
            s = snapshot()
            samples.append({'elapsed_seconds': round(time.monotonic()-start, 3),
                            'utc': s['utc'], 'available_kib': s['meminfo_kib']['MemAvailable'],
                            'swap_used_kib': s['meminfo_kib']['SwapTotal']-s['meminfo_kib']['SwapFree'],
                            'pswpout_pages': s['pswpout_pages'], 'pswpin_pages': s['pswpin_pages'],
                            'memory_psi': s['psi']['memory'], 'nvidia': s['nvidia'], 'amd': s['amd']})
            event = rtx_thermal_event(s, a.hardware, a.max_gpu_temperature)
            if event:
                result['thermal_stop'] = {'elapsed_seconds': samples[-1]['elapsed_seconds'], **event}
                stop.set()
            stop.wait(5)

    def sample():
        try:
            sample_loop()
        except Exception as error:
            result['telemetry_error'] = type(error).__name__
            stop.set()

    def run_one(number):
        kind = number % 3
        began = time.monotonic()
        try:
            modelctl.assert_not_held(reg)
            modelctl.assert_device_ready(reg)
            current = resident(base, before['model'], key)
            if current['cmd'] != before['cmd']:
                raise RuntimeError('resident configuration changed')
            policy = reasoning_policy()
            if kind == 2:
                row = tool_case(base, before['model'], tools()[number % 10], key, policy)
                row['kind'] = 'two-step-tool'
            else:
                case = text_cases()[kind]
                response = complete(base, {'model': before['model'], 'messages': [
                    {'role': 'user', 'content': case['prompt']}], 'max_tokens': 256,
                    'temperature': 0, 'cache_prompt': False, **policy}, timeout=300, key=key)
                text = response.pop('response')
                row = {'kind': case['id'], 'passed': bool(text.strip()), **response}
        except Exception as error:
            row = {'kind': ['latency-8k', 'latency-short', 'two-step-tool'][kind],
                   'passed': False, 'error_type': type(error).__name__,
                   'http_status': getattr(error, 'code', None)}
        row.update({'number': number, 'elapsed_seconds': round(time.monotonic()-start, 3),
                    'wall_seconds': time.monotonic()-began})
        return row

    def save():
        a.output.parent.mkdir(parents=True, exist_ok=True)
        modelctl.atomic(a.output, json.dumps(result, indent=2)+'\n')

    sampler = threading.Thread(target=sample, daemon=True)
    sampler.start()
    try:
        with ThreadPoolExecutor(max_workers=a.concurrency) as pool:
            number = 0
            while time.monotonic() < end and not stop.is_set():
                batch = list(pool.map(run_one, range(number, number+a.concurrency)))
                rows.extend(batch)
                number += a.concurrency
                save()
                print(a.hardware, 'mixed', round(time.monotonic()-start),
                      'seconds', len(rows), 'requests', sum(r['passed'] for r in rows), 'passed', flush=True)
                if not all(r['passed'] for r in batch):
                    result['stopped_on_failure'] = True
                    break
    finally:
        stop.set()
        sampler.join(timeout=10)
        result['wall_seconds'] = time.monotonic()-start
        result['passed'] = (bool(rows) and all(r['passed'] for r in rows)
                            and result['wall_seconds'] >= a.seconds
                            and not result.get('thermal_stop') and not result.get('telemetry_error')
                            and bool(samples) and samples[-1]['elapsed_seconds'] >= a.seconds-10)
        result['requests'] = len(rows)
        if samples:
            result['minimum_available_gib'] = min(s['available_kib'] for s in samples)/1024**2
            result['swapout_pages'] = samples[-1]['pswpout_pages']-samples[0]['pswpout_pages']
        save()
    if not result['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()

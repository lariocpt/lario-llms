#!/usr/bin/env python3
"""One-shot Arc B70 llama.cpp smoke test for the Qwen3.8 Flash Next profile.

Spawns the registry's own SYCL llama-server on a private port (11449), verifies
the per-slot context the engine actually reports, fires small concurrent chat
batches, and tears the process group down. Pauses and later restores the
owner's fixed profile with the same discipline as the Strata smoke harness.
Writes a result JSON plus before/after files next to the log.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from shared.modelctl import api, load_runtime, resident_slots  # noqa: E402
from shared.modelctl import assert_not_held
from shared.serving.catalog import profiles
from shared.serving.control import operate  # noqa: E402
from shared.serving.headroom import read_memory  # noqa: E402
from shared.serving.state import off_marker  # noqa: E402

import cpu_monitor  # noqa: E402  (benchmarks/cpu_monitor.py)

HARDWARE = 'arcB70'
REG_PATH = REPO / 'arcB70' / 'models.json'
WRAPPER = REPO / 'arcB70' / 'llama-server-sycl'
MODEL_ID = 'qwen38-flash-q4-256k'
HOST, PORT = '127.0.0.1', 11449
BASE = f'http://{HOST}:{PORT}'
LOCK_PATH = REPO / '.arcB70.lock'
NATIVE_CONTEXT = 262144


def logline(text: str) -> None:
    print(text, flush=True)


def http_json(path: str, payload: dict | None = None, timeout: float = 60.0) -> dict:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(BASE + path, data=data,
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode() or '{}')


def run_chat_round(round_id: int, slots: int, prompt_tokens: int, max_output: int, task: str) -> dict:
    barrier = threading.Barrier(slots)
    results: list[dict] = []
    lock = threading.Lock()

    def one(i: int) -> None:
        expected = f'B70_SLOT_{i}' if prompt_tokens else '7'
        prompt = ('Remember this secret code: '+expected+'.\n'+
                  ' stone' * prompt_tokens + '\nReturn exactly the secret code, without explanation.') if prompt_tokens else 'Return exactly 7'
        if task == 'decode':
            prompt += '\nInstead, explain in detail why consecutive integers alternate parity. Write at least 300 words.'
        payload = {'model': MODEL_ID,
                   'messages': [{'role': 'user', 'content': prompt}],
                   'temperature': 0, 'max_tokens': max_output,
                   'chat_template_kwargs': {'enable_thinking': False}}
        t0 = time.monotonic()
        try:
            barrier.wait(timeout=60.0)
            data = http_json('/v1/chat/completions', payload, timeout=600.0)
            text = data['choices'][0]['message']['content'].strip()
            entry = {'slot': i, 'ok': True, 'elapsed_s': round(time.monotonic() - t0, 3),
                     'content': text, 'correct': text == expected if task == 'retrieval' else bool(text),
                     'usage': data.get('usage'), 'timings': data.get('timings')}
        except Exception as exc:  # record honestly
            entry = {'slot': i, 'ok': False, 'elapsed_s': round(time.monotonic() - t0, 3),
                     'content': None, 'correct': False, 'error': str(exc)[:400]}
        with lock:
            results.append(entry)

    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=slots) as pool:
        futures = [pool.submit(one, i) for i in range(slots)]
        for f in as_completed(futures):
            f.result()
    ok_count = sum(1 for e in results if e['ok'] and e['correct'])
    return {'round': round_id, 'elapsed_s': round(time.monotonic() - started, 3),
            'requests': sorted(results, key=lambda e: e['slot']),
            'correct': f'{ok_count}/{slots}'}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--context', type=int, default=NATIVE_CONTEXT,
                    help=f'per-slot context, multiple of 256, 4096..{NATIVE_CONTEXT}')
    ap.add_argument('--slots', type=int, choices=[1, 2, 3], default=3)
    ap.add_argument('--output', type=Path, required=True,
                    help='output directory for log, telemetry and result JSON')
    ap.add_argument('--prompt-tokens', type=int, default=0)
    ap.add_argument('--max-output', type=int, default=32)
    ap.add_argument('--task', choices=('retrieval', 'decode'), default='retrieval')
    ap.add_argument('--no-op-offload', action='store_true')
    args = ap.parse_args()
    context = args.context
    if context < 4096 or context > NATIVE_CONTEXT or context % 256 != 0:
        ap.error(f'--context must be 4096..{NATIVE_CONTEXT} and a multiple of 256')
    slots = args.slots
    if not 0 <= args.prompt_tokens <= context-4096 or not 1 <= args.max_output <= 1024:
        ap.error('prompt size or output size exceeds test bounds')
    outdir = args.output.expanduser().resolve()
    outdir.mkdir(parents=True, exist_ok=True)

    log_path = outdir / 'llama-server.log'
    telemetry_path = outdir / 'telemetry.jsonl'
    result_path = outdir / 'result.json'
    before_path = outdir / 'before.json'

    registry = json.loads(REG_PATH.read_text())
    spec = registry['models'].get(MODEL_ID)
    if spec is None:
        raise SystemExit(f'model {MODEL_ID!r} missing from {REG_PATH}')
    model_args: list[str] = spec['args']

    result: dict = {
        'model': MODEL_ID, 'wrapper': str(WRAPPER), 'host': HOST, 'port': PORT,
        'requested_context': context, 'slots': slots,
        'workload': {'approx_prompt_tokens': args.prompt_tokens,
                     'max_output': args.max_output, 'task': args.task},
        'verified_context': None, 'verified_source': None,
        'started_at': datetime.now(timezone.utc).isoformat(),
    }
    before_path.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')

    reg = registry
    load_runtime(reg)
    assert_not_held(reg)
    def interrupted(signum, frame):
        if proc is not None and proc.poll() is None:
            os.killpg(proc.pid, signal.SIGTERM)
        raise KeyboardInterrupt(f'signal {signum}')
    paused = False
    previous: str | None = None
    lock_fd = None
    proc: subprocess.Popen | None = None
    signal.signal(signal.SIGTERM, interrupted)
    monitor_thread = log_thread = None
    telemetry_fd = None
    monitor_stop = threading.Event()
    gpu_samples: list[dict] = []
    chat_results: list[dict] = []
    result_error: str | None = None

    try:
        # Pre-flight: owner profile idle (or off), native work idle, port free.
        initial = operate(HARDWARE, 'status')
        if initial.get('busy') or initial.get('requests'):
            raise SystemExit('owner profile is busy; refusing')
        if initial.get('uncertain'):
            raise SystemExit('owner profile status is uncertain; refusing')
        if initial.get('draining'):
            raise SystemExit('owner profile is draining; refusing')
        for item in api(reg, '/running')['running']:
            if any(s['is_processing'] for s in resident_slots(reg, item)):
                raise SystemExit(f'native work is active for {item["id"]!r}')
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind((HOST, PORT))
        finally:
            probe.close()

        previous = next((p['id'] for p in profiles(reg).values()
                         if p['model'] == initial.get('model')), None)
        before_path.write_text(json.dumps(initial, indent=2)+'\n')
        operate(HARDWARE, 'pause')
        paused = True
        after_pause = operate(HARDWARE, 'status')
        if after_pause.get('busy') or after_pause.get('requests') or after_pause.get('uncertain'):
            raise SystemExit('owner profile still busy after pause')
        if previous:
            operate(HARDWARE, 'unload', previous)
            after_unload = operate(HARDWARE, 'status')
            if after_unload.get('busy') or after_unload.get('requests'):
                raise SystemExit('owner profile still busy after unload')

        lock_fd = os.open(LOCK_PATH, os.O_CREAT | os.O_RDWR)
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit('another Arc B70 process holds the lock')
        logline('lock held: ' + str(LOCK_PATH))

        cmd: list[str] = [registry['binary'],
                          *model_args,
                          '--host', HOST, '--port', str(PORT),
                          '-fa', 'on', '--jinja',
                          '-c', str(context * slots),
                          '--parallel', str(slots),
                          '--kv-unified', '--no-context-shift']
        if args.no_op_offload and '--no-op-offload' not in cmd:
            cmd += ['--no-op-offload']
        result['command'] = cmd
        logline('spawning: ' + ' '.join(cmd))
        proc = subprocess.Popen(cmd,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT,
                                cwd=REPO,
                                start_new_session=True)

        def pump_log() -> None:
            with log_path.open('wb') as fh:
                assert proc is not None
                for line in iter(proc.stdout.readline, b''):
                    fh.write(line)
                    fh.flush()
                proc.stdout.close()

        log_thread = threading.Thread(target=pump_log, daemon=True)
        log_thread.start()

        # Wait for health (600s) then verify the real per-slot context.
        ready_by = time.monotonic() + 600.0
        props: dict = {}
        while True:
            if proc.poll() is not None:
                raise SystemExit('llama-server exited before health; see log')
            if time.monotonic() > ready_by:
                raise SystemExit('health not ready within 600s')
            try:
                props = http_json('/health', timeout=5.0)
                break
            except Exception:
                time.sleep(1.0)
        logline('health: ' + json.dumps(props, sort_keys=True)[:300])

        verify_source = 'props'
        try:
            props = http_json('/props', timeout=30.0)
        except Exception as exc:
            result['verification_error'] = f'/props unavailable: {exc}'
            verify_source = 'health-only'
        try:
            n_ctx = props['default_generation_settings']['n_ctx']
        except Exception:
            n_ctx = props.get('n_ctx')
        result['verified_context'] = n_ctx
        result['verified_source'] = verify_source
        result['props'] = props
        native_slots = http_json('/slots')
        result['native_slots'] = native_slots
        if n_ctx != context or len(native_slots) != slots or any(
                slot.get('n_ctx', context) < context for slot in native_slots):
            result_error = (f'requested per-slot context {context}, '
                            f'engine reports {n_ctx}')
            raise SystemExit(result_error)

        def monitor() -> None:
            nonlocal telemetry_fd
            telemetry_fd = telemetry_path.open('ab')
            try:
                last = cpu_monitor.snapshot(proc.pid)
                while not monitor_stop.is_set():
                    time.sleep(1.0)
                    try:
                        cur = cpu_monitor.snapshot(proc.pid)
                        sample = {
                            'ts': datetime.now(timezone.utc).isoformat(),
                            **cpu_monitor.usage(last, cur),
                            'gpu': read_memory(reg),
                        }
                        gpu_samples.append({'ts': sample['ts'], 'gpu': sample['gpu']})
                    except Exception:
                        continue
                    last = cur
                    telemetry_fd.write((json.dumps(sample) + '\n').encode())
                    telemetry_fd.flush()
            finally:
                telemetry_fd.close()

        monitor_thread = threading.Thread(target=monitor, daemon=True)
        monitor_thread.start()

        for round_id in (1, 2):
            logline(f'round {round_id}: {slots} concurrent requests')
            chat_results.append(run_chat_round(round_id, slots, args.prompt_tokens, args.max_output, args.task))
            logline(f"round {round_id} done: {chat_results[-1]['correct']}")
            if any(not r['correct'] for r in chat_results[-1]['requests']):
                result_error = 'one or more concurrent requests failed'

        result['chat'] = chat_results
    except BaseException as exc:
        if result_error is None:
            result_error = str(exc)[:800]
    finally:
        monitor_stop.set()
        try:
            if proc is not None and proc.poll() is None:
                os.killpg(os.getpgid(proc.pid), 15)  # SIGTERM
                for _ in range(15):
                    time.sleep(0.5)
                    if proc.poll() is not None:
                        break
                if proc.poll() is None:
                    os.killpg(os.getpgid(proc.pid), 9)
                proc.wait(timeout=10)
        except (ProcessLookupError, OSError):
            pass
        if proc is not None:
            proc.wait(timeout=5)
        if log_thread:
            log_thread.join(timeout=5)
        if monitor_thread:
            monitor_thread.join(timeout=5)
        if lock_fd is not None:
            os.close(lock_fd)
            lock_fd = None

        if paused and not off_marker(reg).exists():
            try:
                operate(HARDWARE, 'resume')
                if previous:
                    operate(HARDWARE, 'activate', previous)
                result['restoration'] = previous
            except Exception as exc:
                result['restoration'] = None
                result['restoration_error'] = str(exc)
        elif paused:
            result['restoration'] = 'skipped: operator off marker present'

    if result_error is not None:
        result['error'] = result_error
    result['gpu_samples'] = gpu_samples
    result['completed_at'] = datetime.now(timezone.utc).isoformat()
    result['status'] = 'pass' if result_error is None else 'fail'
    result_path.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    logline('result: ' + str(result_path))
    logline(f"status: {result['status']}"
            + (f" ({result_error})" if result_error else ''))
    sys.exit(0 if result['status'] == 'pass' else 1)


if __name__ == '__main__':
    main()

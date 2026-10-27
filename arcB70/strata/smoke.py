#!/usr/bin/env python3
"""Bounded isolated Strata test; pause/unload only idle work and restore it."""
import argparse
import concurrent.futures
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import sys
import threading
import time

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from arcB70.strata.setup import MODEL, PACK, SOURCE
from arcB70.benchmarks.cpu_monitor import snapshot, usage
from shared import modelctl
from shared.serving.catalog import profiles
from shared.serving.control import operate
from shared.serving.headroom import read_memory
from shared.serving.state import off_marker


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--context', type=int, default=32768)
    parser.add_argument('--slots', type=int, choices=(1, 2, 3), default=1)
    parser.add_argument('--clients', type=int, choices=(1, 2, 3))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--rounds', type=int, default=1)
    parser.add_argument('--max-output', type=int, default=32)
    parser.add_argument('--prompt-file', type=Path)
    parser.add_argument('--expected', default='7')
    parser.add_argument('--short-read', type=int)
    parser.add_argument('--engine', type=Path)
    args = parser.parse_args()
    clients = args.clients if args.clients is not None else args.slots
    if clients > args.slots:
        parser.error('clients cannot exceed slots')
    if not 4096 <= args.context <= 262144 or args.context % 256:
        parser.error('context must be a multiple of 256 within native context')
    if not 1 <= args.rounds <= 8 or not 1 <= args.max_output <= 1024:
        parser.error('rounds must be 1..8 and max-output 1..1024')
    args.output.mkdir(parents=True, exist_ok=True)
    test_binary = None
    if args.engine:
        test_binary = args.engine.resolve(strict=True)
        if not test_binary.is_relative_to(Path.home()/'.local/share/strata/build'):
            parser.error('engine must be a private Strata build')
        os.environ['STRATA_TEST_ENGINE'] = str(test_binary)
    def interrupted(signum, frame):
        raise KeyboardInterrupt(f'signal {signum}')
    signal.signal(signal.SIGTERM, interrupted)
    reg = json.loads((REPO/'arcB70/models.json').read_text())
    modelctl.load_runtime(reg)
    initial = operate('arcB70', 'status')
    if initial['busy'] or initial['requests'] or initial['uncertain'] or initial['draining']:
        raise RuntimeError('owner must be confirmed idle and unpaused')
    modelctl.assert_not_held(reg)
    previous = next((p['id'] for p in profiles(reg).values()
                     if p['model'] == initial.get('model')), None)
    for item in modelctl.api(reg, '/running')['running']:
        if any(s['is_processing'] for s in modelctl.resident_slots(reg, item)):
            raise RuntimeError('native work is active')
    (args.output/'before.json').write_text(json.dumps(initial, indent=2))
    sys.path.insert(0, str(SOURCE))
    sys.path.insert(0, str(SOURCE/'tools'))
    from serve.server import StrataEngine
    from serve.frontend import ChatTemplate
    from strata_tokenizer import Tokenizer
    pins = json.loads((REPO/'arcB70/flash_weights.json').read_text())
    tokenizer = Tokenizer.from_gguf(MODEL/pins['shards'][0]['filename'])
    template = ChatTemplate(PACK/'tokenizer/chat_template.jinja')
    prompt = args.prompt_file.read_text() if args.prompt_file else 'Return exactly the number 7.'
    text = template.render([{'role': 'user', 'content': prompt}],
                           enable_thinking=False)
    ids = tokenizer.encode(text, parse_special=True)
    if len(ids) + args.max_output > args.context:
        raise RuntimeError('prompt plus requested output exceeds context')
    command = ['--pack', str(PACK), '--native', str(MODEL/pins['shards'][0]['filename']),
               '--ple-gguf', str(MODEL/pins['shards'][1]['filename']),
               '--expert-profile', str(SOURCE/'data/expert-profile-sycl.bin'),
               '--expert-cache', 'auto', '--stream-experts', '--ple-io', 'ram',
               '--kv', 'q4_0', '--max-context', str(args.context),
               '--vram-reserve-mib', '2048', '--prefill',
               str(8192 if args.context > 32768 else 4096), '--spec', '2']
    if args.context > 32768:
        command += ['--prefill-borrow', '--kv-resident', '32768']
    if args.slots > 1:
        command += ['--batch', str(args.slots)]
    if args.short_read is not None:
        if not 0 <= args.short_read <= 8192:
            parser.error('short-read must be 0..8192')
        command += ['--short-read', str(args.short_read)]
    result = {'context_requested': args.context, 'slots_requested': args.slots,
              'command': command, 'status': 'started', 'results': [],
              'prompt_tokens': len(ids), 'rounds': args.rounds,
              'clients': clients,
              'max_output': args.max_output, 'expected': args.expected,
              'environment_overrides': {key: os.environ[key] for key in
                  ('STRATA_WINDOW_SYNC', 'STRATA_VERIFY_EAGER', 'STRATA_VERIFY_DEBUG',
                   'STRATA_PREFILL_MMQ', 'STRATA_VERIFY_NO_HOST') if key in os.environ}}
    if test_binary:
        result['test_engine'] = {'path': str(test_binary),
            'sha256': hashlib.sha256(test_binary.read_bytes()).hexdigest()}
    (args.output/'command.json').write_text(json.dumps(result, indent=2))
    paused = False
    engine = None
    lock = None
    stop = threading.Event()
    monitor = None
    cancelled = threading.Event()
    try:
        operate('arcB70', 'pause')
        paused = True
        state = operate('arcB70', 'status')
        if state['busy'] or state['requests'] or state['uncertain']:
            raise RuntimeError('work arrived before pause; left untouched')
        if previous:
            operate('arcB70', 'unload', previous)
        lock = (REPO/'.arcB70.lock').open('a')
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        started = time.monotonic()
        engine = StrataEngine.__new__(StrataEngine)
        StrataEngine.__init__(engine, str(REPO/'arcB70/strata/engine'), command,
                             cwd=str(SOURCE), log=str(args.output/'engine.log'))
        result.update(load_seconds=time.monotonic()-started, engine_info=engine.info,
                      actual_context=engine.max_context, actual_slots=max(1, engine.batch))
        if engine.max_context != args.context or max(1, engine.batch) != args.slots:
            raise RuntimeError('engine did not honor requested context/slots')
        def telemetry():
            previous_cpu = snapshot(engine.proc.pid)
            with (args.output/'telemetry.jsonl').open('a') as out:
                while not stop.wait(1):
                    now = snapshot(engine.proc.pid)
                    row = {'epoch': time.time(), 'pid': engine.proc.pid,
                           'cpu': usage(previous_cpu, now)}
                    try:
                        row['gpu'] = read_memory(reg)
                    except Exception as exc:
                        row['gpu_error'] = type(exc).__name__
                    out.write(json.dumps(row)+'\n');out.flush()
                    previous_cpu = now
        monitor = threading.Thread(target=telemetry, daemon=True)
        monitor.start()
        barrier = threading.Barrier(clients)
        def generate(slot):
            barrier.wait()
            start = time.monotonic()
            tokens = []
            first = None
            for token in engine.generate(ids, args.max_output, {'temperature': 0, 'seed': 42}, cancelled):
                if token is not None:
                    if first is None:
                        first = time.monotonic()
                    tokens.append(token)
            finished = time.monotonic()
            reply = tokenizer.decode(tokens)
            clean = reply.replace('<|im_end|>', '').replace('<|endoftext|>', '').strip()
            return {'slot': slot, 'seconds': finished-start, 'tokens': len(tokens),
                    'first_token_seconds': first-start if first else None,
                    'decode_tokens_per_second': (len(tokens)-1)/(finished-first)
                    if first and len(tokens)>1 and finished>first else None,
                    'reply': reply, 'correct': clean == args.expected if args.expected else bool(clean)}
        with concurrent.futures.ThreadPoolExecutor(max_workers=clients) as pool:
            for iteration in range(args.rounds):
                rows = list(pool.map(generate, range(clients)))
                for row in rows:
                    row['round'] = iteration + 1
                result['results'].extend(rows)
                (args.output/'progress.json').write_text(json.dumps(result, indent=2)+'\n')
        if not all(row['correct'] for row in result['results']):
            raise RuntimeError('arithmetic/output smoke failed')
        result['status'] = 'passed'
    except BaseException as exc:
        result.update(status='failed', error=type(exc).__name__+': '+str(exc))
        raise
    finally:
        cancelled.set();stop.set()
        if monitor:
            monitor.join(timeout=3)
        if engine is not None:
            try:
                engine.close()
            except Exception as exc:
                result['cleanup_error'] = type(exc).__name__
                proc = getattr(engine, 'proc', None)
                if proc and proc.poll() is None:
                    proc.kill();proc.wait(timeout=15)
        if lock:
            lock.close()
        if paused and not off_marker(reg).exists():
            try:
                operate('arcB70', 'resume')
                if previous:
                    operate('arcB70', 'activate', previous)
                result['restoration'] = 'previous profile activation requested'
            except Exception as exc:
                result['restoration_error'] = type(exc).__name__+': '+str(exc)
        (args.output/'result.json').write_text(json.dumps(result, indent=2)+'\n')
        print(json.dumps(result, indent=2), flush=True)


if __name__ == '__main__':
    main()

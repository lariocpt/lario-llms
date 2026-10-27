#!/usr/bin/env python3
"""Bounded /proc thread sampling; percentages use one logical CPU as 100%."""
import argparse
import json
import os
from pathlib import Path
import time


def snapshot(pid):
    threads = {}
    for path in Path(f'/proc/{pid}/task').glob('*'):
        try:
            fields = (path/'stat').read_text().rsplit(')', 1)[1].split()
            threads[int(path.name)] = {
                'ticks': int(fields[11])+int(fields[12]), 'start_ticks': int(fields[19]),
                'state': fields[0], 'cpu': int(fields[36]),
                'name': (path/'comm').read_text().strip(),
                'wchan': (path/'wchan').read_text().strip(),
            }
        except (OSError, ValueError):
            continue
    return {'monotonic': time.monotonic(), 'threads': threads}


def usage(previous, current):
    elapsed = current['monotonic']-previous['monotonic']
    if elapsed <= 0:
        raise ValueError('sample interval must be positive')
    hz = os.sysconf('SC_CLK_TCK')
    rows = []
    for tid, now in current['threads'].items():
        before = previous['threads'].get(tid)
        if before is None or before['start_ticks'] != now['start_ticks']:
            continue
        rows.append({'tid': tid, 'one_core_percent': round(
            100*max(0, now['ticks']-before['ticks'])/hz/elapsed, 2),
            **{key: now[key] for key in ('state', 'cpu', 'name', 'wchan')}})
    rows.sort(key=lambda row: row['one_core_percent'], reverse=True)
    return {'sample_seconds': round(elapsed, 3),
            'sampled_thread_cpu_percent': round(sum(row['one_core_percent'] for row in rows), 2),
            'thread_count': len(current['threads']), 'top_threads': rows[:16]}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pid', type=int, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--duration', type=float, default=60)
    parser.add_argument('--interval', type=float, default=2)
    parser.add_argument('--phase', default='unspecified')
    args = parser.parse_args()
    if args.pid <= 0 or not 0 < args.interval <= args.duration <= 86400:
        parser.error('positive PID and 0 < interval <= duration <= 86400 required')
    previous = snapshot(args.pid)
    if args.pid not in previous['threads']:
        raise SystemExit('process unavailable')
    identity = previous['threads'][args.pid]['start_ticks']
    deadline = time.monotonic()+args.duration
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('a') as out:
        while time.monotonic() < deadline:
            time.sleep(min(args.interval, max(0, deadline-time.monotonic())))
            current = snapshot(args.pid)
            if current['threads'].get(args.pid, {}).get('start_ticks') != identity:
                raise SystemExit('process exited or PID was reused; monitoring stopped')
            row = {'utc_epoch': time.time(), 'pid': args.pid, 'phase': args.phase,
                   **usage(previous, current)}
            out.write(json.dumps(row)+'\n')
            out.flush()
            previous = current
    print('CPU samples saved to '+str(args.output))

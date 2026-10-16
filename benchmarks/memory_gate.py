#!/usr/bin/env python3
"""Evaluate Geekom sustained RAM/PSI evidence without changing a model or result."""
import argparse
import json
import math
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from shared.modelctl import atomic


def full_pressure(text,window='avg60'):
    """Linux PSI is raw text in telemetry artifacts; missing data must fail closed."""
    lines=[line.split() for line in text.splitlines() if line.startswith('full ')]
    if len(lines)!=1:raise ValueError('exactly one memory PSI full row required')
    values=dict(field.split('=',1) for field in lines[0][1:])
    value=float(values[window])
    if not math.isfinite(value) or not 0<=value<=100:raise ValueError('invalid PSI percentage')
    return value


def evaluate(result):
    samples=result['samples']
    if len(samples)<2:raise ValueError('sustained telemetry required')
    elapsed=[float(row['elapsed_seconds']) for row in samples]
    if any(b<=a for a,b in zip(elapsed,elapsed[1:])):raise ValueError('telemetry times must increase')
    available=[row['available_kib']/1024**2 for row in samples]
    pressure=[full_pressure(row['memory_psi']) for row in samples]
    events=[]
    for before,after in zip(samples,samples[1:]):
        delta=after['pswpout_pages']-before['pswpout_pages']
        if delta<0:raise ValueError('swap counters reset during test')
        if delta:events.append({'elapsed_seconds':after['elapsed_seconds'],'pages':delta})
    seconds=result['wall_seconds']
    passed=(result.get('passed') is True and result['requested_seconds']>=1800 and
            seconds>=result['requested_seconds'] and elapsed[-1]>=result['requested_seconds']-10 and
            min(available)>=15 and max(pressure)<=1)
    return {'scope':'Geekom sustained RAM/PSI gate; swap events require explicit review before promotion',
            'benchmark_passed':result.get('passed') is True,'requested_seconds':result['requested_seconds'],
            'wall_seconds':seconds,'minimum_available_gib':min(available),
            'maximum_memory_full_avg60_percent':max(pressure),
            'swapout_pages':sum(row['pages'] for row in events),'swapout_intervals':events,
            'swap_review_required':bool(events),'ram_psi_gate_passed':passed,
            'automatic_promotion_allowed':passed and not events,
            'thresholds':{'minimum_available_gib':15,'maximum_memory_full_avg60_percent':1}}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args();result=evaluate(json.loads(args.input.read_text()))
    atomic(args.output,json.dumps(result,indent=2)+'\n');print(json.dumps(result))
    if not result['ram_psi_gate_passed']:raise SystemExit(1)

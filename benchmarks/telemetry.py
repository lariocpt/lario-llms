#!/usr/bin/env python3
"""Read-only local memory/PSI/swap sampling; no model API calls or process signals."""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import subprocess
import time


def snapshot():
    memory={}
    for line in Path('/proc/meminfo').read_text().splitlines():
        key,value=line.split(':',1);memory[key]=int(value.strip().split()[0])
    vm=dict(line.split() for line in Path('/proc/vmstat').read_text().splitlines())
    psi={name:Path('/proc/pressure/'+name).read_text() for name in ['memory','io','cpu']}
    gpu = None
    try:
        result = subprocess.run(['nvidia-smi', '--query-gpu=index,memory.used,memory.total,utilization.gpu',
                                 '--format=csv,noheader,nounits'], capture_output=True,text=True,timeout=3)
        if result.returncode == 0:
            gpu = [dict(zip(['index','used_mib','total_mib','utilization_percent'],
                            [int(v.strip()) for v in line.split(',')])) for line in result.stdout.splitlines()]
    except (FileNotFoundError, subprocess.TimeoutExpired): pass
    return {'nvidia':gpu,'utc':datetime.now(timezone.utc).isoformat(),'meminfo_kib':memory,'psi':psi,
            'swap_devices':Path('/proc/swaps').read_text(),
            'pswpin_pages':int(vm['pswpin']),'pswpout_pages':int(vm['pswpout'])}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds',type=int,default=30)
    parser.add_argument('--interval',type=float,default=1)
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    if not 1<=args.seconds<=3600 or not .5<=args.interval<=30:parser.error('invalid sampling duration')
    rows=[];end=time.monotonic()+args.seconds
    while True:
        rows.append(snapshot())
        Path(args.output).parent.mkdir(parents=True,exist_ok=True)
        Path(args.output).write_text(json.dumps({'schema_version':1,'samples':rows},indent=2)+'\n')
        if time.monotonic()>=end:break
        time.sleep(args.interval)


if __name__=='__main__':main()

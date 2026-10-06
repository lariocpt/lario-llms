#!/usr/bin/env python3
"""Read-only local memory/PSI/swap sampling; no model API calls or process signals."""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from shared.modelctl import atomic


def amd_memory(devices=Path('/sys/bus/pci/devices')):
    """Use stable PCI addresses rather than DRM card numbers, which change at boot."""
    rows=[]
    for device in sorted(devices.iterdir()):
        try:
            if (device/'vendor').read_text().strip()!='0x1002': continue
            if not (device/'class').read_text().strip().startswith('0x03'): continue
        except OSError: continue
        row={'pci_address':device.name}
        try:
            row['used_bytes']=int((device/'mem_info_vram_used').read_text())
            row['total_bytes']=int((device/'mem_info_vram_total').read_text())
            if not 0<=row['used_bytes']<=row['total_bytes'] or row['total_bytes']<=0:
                raise ValueError('invalid VRAM observation')
            busy=device/'gpu_busy_percent'
            row['utilization_percent']=int(busy.read_text()) if busy.exists() else None
            temperatures = {}
            for monitor in device.glob('hwmon/hwmon*'):
                for label in monitor.glob('temp*_label'):
                    value = label.with_name(label.name.replace('_label','_input'))
                    try:
                        temperatures[label.read_text().strip()] = int(value.read_text())/1000
                    except (OSError,ValueError):
                        pass
            if temperatures:
                row['temperatures_c'] = temperatures
        except (OSError,ValueError) as error:
            row={'pci_address':device.name,'error_type':type(error).__name__}
        rows.append(row)
    return rows


def snapshot():
    memory={}
    for line in Path('/proc/meminfo').read_text().splitlines():
        key,value=line.split(':',1);memory[key]=int(value.strip().split()[0])
    vm=dict(line.split() for line in Path('/proc/vmstat').read_text().splitlines())
    psi={name:Path('/proc/pressure/'+name).read_text() for name in ['memory','io','cpu']}
    gpu = None
    try:
        result = subprocess.run(['nvidia-smi', '--query-gpu=index,memory.used,memory.total,utilization.gpu,temperature.gpu,power.draw,power.limit,fan.speed',
                                 '--format=csv,noheader,nounits'], capture_output=True,text=True,timeout=3)
        if result.returncode == 0:
            def number(value):
                value = value.strip()
                return None if value in ('N/A', '[N/A]', '[Not Supported]') else float(value)
            gpu = [dict(zip(['index','used_mib','total_mib','utilization_percent',
                             'temperature_c','power_w','power_limit_w','fan_percent'],
                            [number(v) for v in line.split(',')])) for line in result.stdout.splitlines()]
    except (FileNotFoundError, subprocess.TimeoutExpired): pass
    return {'nvidia':gpu,'amd':amd_memory(),'utc':datetime.now(timezone.utc).isoformat(),'meminfo_kib':memory,'psi':psi,
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
        atomic(Path(args.output),json.dumps({'schema_version':1,'samples':rows},indent=2)+'\n')
        if time.monotonic()>=end:break
        time.sleep(args.interval)


if __name__=='__main__':main()

#!/usr/bin/env python3
"""Passive paired GPU telemetry: no inference, switching, fan or power changes."""
import argparse
import json
from pathlib import Path
import subprocess
import time


def snapshot():
    result={'timestamp':time.time(),'arcB70':{},'rtx5080':{}}
    for hw in Path('/sys/bus/pci/devices/0000:04:00.0/hwmon').glob('hwmon*'):
        for entry in hw.glob('temp*_input'):
            label=entry.with_name(entry.name.replace('_input','_label'))
            if label.exists():result['arcB70'][label.read_text().strip()+'_c']=int(entry.read_text())/1000
        result['arcB70']['fan_rpm']=int((hw/'fan1_input').read_text())
        result['arcB70']['energy_uj']=int((hw/'energy1_input').read_text())
    query=['nvidia-smi','--query-gpu=temperature.gpu,power.draw,utilization.gpu,fan.speed','--format=csv,noheader,nounits']
    output=subprocess.check_output(query,text=True,timeout=5).strip().split(',')
    for key,value in zip(('temperature_c','power_w','utilization_percent','fan_percent'),output):
        result['rtx5080'][key]=float(value)
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--seconds',type=int,default=60);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if not 1<=a.seconds<=600:p.error('seconds must be 1..600')
    start=time.monotonic();rows=[]
    while time.monotonic()-start<a.seconds:
        rows.append(snapshot());time.sleep(2)
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps({'scope':'Passive temperatures during functional inference, not sustained thermal validation','samples':rows},indent=2)+'\n')
    print(json.dumps({'samples':len(rows),'arc_package_max_c':max(x['arcB70'].get('pkg_c',0) for x in rows),'arc_vram_max_c':max(x['arcB70'].get('vram_c',0) for x in rows),'rtx_max_c':max(x['rtx5080'].get('temperature_c',0) for x in rows)}))


if __name__=='__main__':main()

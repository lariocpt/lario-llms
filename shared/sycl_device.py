#!/usr/bin/env python3
"""Select a Level Zero GPU by PCI identity, never an assumed device ordinal."""
import argparse
import os
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from shared.gpu import intel_arc_device


def select(text,pci):
    matches=[]
    for line in text.splitlines():
        parts=line.split('\t',5)
        if len(parts)!=6:continue
        index,vendor,device,address,memory,name=parts
        if int(vendor)==0x8086 and int(device)==0xe223 and address==pci and int(memory)>=30*2**30:
            matches.append(int(index))
    if len(matches)!=1:raise RuntimeError('expected exactly one PCI-matched B70; iGPU/RTX fallback refused')
    return matches[0]


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--probe',type=Path,required=True)
    parser.add_argument('command',nargs=argparse.REMAINDER);a=parser.parse_args()
    identity=intel_arc_device()
    env=dict(os.environ)
    for name in ('SYCL_DEVICE_FILTER','ZE_AFFINITY_MASK','SYCL_DEVICE_ALLOWLIST'):
        env.pop(name,None)
    env['ONEAPI_DEVICE_SELECTOR']='level_zero:gpu'
    result=subprocess.run([str(a.probe)],capture_output=True,text=True,check=True,timeout=30,env=env)
    index=select(result.stdout,identity['pci'])
    env['ONEAPI_DEVICE_SELECTOR']='level_zero:'+str(index)
    # Check the filtered runtime view before allowing a model to start.
    check=subprocess.run([str(a.probe)],capture_output=True,text=True,check=True,timeout=30,env=env)
    if select(check.stdout,identity['pci'])!=0 or len(check.stdout.strip().splitlines())!=1:
        raise RuntimeError('SYCL filter did not isolate the registered Arc')
    command=a.command[1:] if a.command[:1]==['--'] else a.command
    if not command:print(identity['pci'],env['ONEAPI_DEVICE_SELECTOR']);return
    os.execvpe(command[0],command,env)


if __name__=='__main__':main()

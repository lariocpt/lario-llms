#!/usr/bin/env python3
"""Bind a Vulkan process to one verified GPU despite device-index changes."""
import argparse
import os
import re
import subprocess


def select(summary, vendor, device, kind):
    matches=[]
    for index, block in re.findall(r'^GPU(\d+):\s*\n(.*?)(?=^GPU\d+:|\Z)',
                                    summary, re.MULTILINE|re.DOTALL):
        fields=dict(re.findall(r'^\s*(\w+)\s*=\s*(.*?)\s*$',block,re.MULTILINE))
        if (fields.get('vendorID','').lower()==vendor.lower()
                and fields.get('deviceID','').lower()==device.lower()
                and fields.get('deviceType')=='PHYSICAL_DEVICE_TYPE_'+kind.upper()+'_GPU'):
            matches.append(int(index))
    if len(matches)!=1:
        raise RuntimeError('expected exactly one registered Vulkan GPU; fallback refused')
    return matches[0]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vendor',required=True)
    parser.add_argument('--device',required=True)
    parser.add_argument('--kind',choices=('integrated','discrete'),required=True)
    parser.add_argument('command',nargs=argparse.REMAINDER)
    args=parser.parse_args()
    # Inspect with the same loader/ICD environment the child will inherit.
    probe=subprocess.run(['vulkaninfo','--summary'],capture_output=True,text=True,
                         timeout=30,check=True)
    index=select(probe.stdout,args.vendor,args.device,args.kind)
    command=args.command
    if command[:1]==['--']:
        command=command[1:]
    if not command:
        print(index)
        return
    os.environ['GGML_VK_VISIBLE_DEVICES']=str(index)
    os.execvp(command[0],command)


if __name__=='__main__':
    main()

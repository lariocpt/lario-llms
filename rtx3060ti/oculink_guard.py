#!/usr/bin/env python3
"""Keep the mini-mobile GA104 OCuLink path out of PCIe power-saving states.

Uses the kernel's per-link ASPM controls; never resets/unbinds a live GPU or
changes link speed. Physical link/power faults still require hardware recovery.
"""
import argparse
import json
import os
from pathlib import Path
import socket

VENDOR = '0x10de'
DEVICE = '0x2489'
ASPM = ('l1_2_aspm', 'l1_1_aspm', 'l1_2_pcipm', 'l1_1_pcipm', 'l1_aspm', 'l0s_aspm', 'clkpm')


def settings(root=Path('/sys/bus/pci/devices')):
    targets = []
    for entry in root.iterdir():
        try:
            if (entry/'vendor').read_text().strip() == VENDOR and (entry/'device').read_text().strip() == DEVICE:
                targets.append(entry.resolve())
        except OSError:
            continue
    if not targets:
        return {}
    if len(targets) != 1:
        raise RuntimeError('expected one RTX 3060 Ti OCuLink endpoint')
    gpu = targets[0]
    paths = {gpu, gpu.parent}
    # The HDMI-audio function shares the same OCuLink power domain.
    for sibling in gpu.parent.glob(gpu.name.rsplit('.', 1)[0]+'.*'):
        if (sibling/'vendor').read_text().strip() == VENDOR:
            paths.add(sibling)
    desired = {}
    for device in sorted(paths):
        control = device/'power/control'
        if control.exists():
            desired[control] = 'on'
        for name in ASPM:
            control = device/'link'/name
            if control.exists():
                desired[control] = '0'
    return desired


def configure(root=Path('/sys/bus/pci/devices'), apply=False):
    desired = settings(root)
    rows = []
    for path, value in desired.items():
        before = path.read_text().strip()
        if apply and before != value:
            path.write_text(value+'\n')
        after = path.read_text().strip()
        rows.append({'path':str(path), 'before':before, 'expected':value, 'actual':after})
    return {'present':bool(desired), 'ready':bool(desired) and all(r['actual']==r['expected'] for r in rows),
            'settings':rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if socket.gethostname().split('.')[0] != 'cachyos-mini-mobile':
        raise SystemExit('this guard is only for mini-mobile')
    if args.apply and os.geteuid() != 0:
        raise SystemExit('--apply requires root')
    result = configure(apply=args.apply)
    print(json.dumps(result, indent=2))
    # An unplugged optional GPU is allowed. An installed GPU must be guarded.
    if result['present'] and not result['ready']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()

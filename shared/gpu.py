"""Resolve registered GPUs without relying on unstable enumeration indices."""
import csv
import io
import os
import subprocess
from pathlib import Path


def radeon_device(identity, root=Path('/sys/bus/pci/devices'), dri=Path('/dev/dri'), kfd=Path('/dev/kfd')):
    matches = []
    for device in root.iterdir():
        try:
            if ((device/'vendor').read_text().strip() != '0x1002' or
                    (device/'device').read_text().strip() != identity['device_id'] or
                    (device/'unique_id').read_text().strip().lower() != identity['unique_id'].lower() or
                    (device/'driver').resolve().name != 'amdgpu' or
                    int((device/'mem_info_vram_total').read_text()) < identity['minimum_vram_bytes']):
                continue
            nodes = list((device/'drm').glob('renderD*'))
            if len(nodes) != 1:
                continue
            render = dri/nodes[0].name
            if not render.exists() or not kfd.exists():
                continue
            matches.append({'pci': device.name, 'render': str(render),
                            'unique_id': identity['unique_id']})
        except (OSError, ValueError):
            continue
    if len(matches) != 1:
        raise RuntimeError('registered RX 7900 XT is absent or ambiguous; internal GPU fallback is forbidden')
    return matches[0]


def intel_arc_device(root=Path('/sys/bus/pci/devices'), dri=Path('/dev/dri')):
    """Require one xe-driven B70 with a full-size memory BAR and accessible render node."""
    matches=[]
    for device in root.iterdir():
        try:
            if ((device/'vendor').read_text().strip()!='0x8086' or
                    (device/'device').read_text().strip()!='0xe223' or
                    (device/'driver').resolve().name!='xe'):
                continue
            regions=[line.split() for line in (device/'resource').read_text().splitlines()]
            aperture=max(int(end,16)-int(start,16)+1 for start,end,_ in regions if int(start,16))
            nodes=list((device/'drm').glob('renderD*'))
            if aperture<30*2**30 or len(nodes)!=1:
                continue
            node=dri/nodes[0].name
            if not os.access(node,os.R_OK|os.W_OK):
                continue
            matches.append({'pci':device.name,'render':str(node),'bar_bytes':aperture})
        except (OSError,ValueError):
            continue
    if len(matches)!=1:
        raise RuntimeError('expected one accessible xe B70 with full BAR; iGPU/RTX fallback refused')
    return matches[0]


def nvidia_device(identity, nodes=Path('/dev'), query='nvidia-smi'):
    """Require the registered physical NVIDIA card by UUID via the driver query.

    Matches the same fail-closed contract as radeon_device: the absent card is a
    hard error (an auto-start ExecCondition), CPU fallback is forbidden, and a
    same-model donor card with a different UUID does not count. Enumeration
    indices are resolved fresh on every call.
    """
    result = subprocess.run([query, '--query-gpu=pci.bus_id,uuid,name,memory.total',
                             '--format=csv,noheader,nounits'],
                            capture_output=True, text=True, timeout=30, check=True)
    matches = []
    for row in csv.reader(io.StringIO(result.stdout)):
        try:
            bus, uuid, name, total = (column.strip() for column in row[:4])
        except ValueError:
            continue
        if (uuid.lower() != identity['uuid'].lower() or
                int(total) * 2**20 < identity['minimum_vram_bytes']):
            continue
        matches.append({'pci': bus.lower(), 'uuid': uuid, 'name': name})
    if len(matches) != 1:
        raise RuntimeError('registered RTX 3060 Ti is absent or ambiguous; CPU fallback is forbidden')
    for node in ('nvidia0', 'nvidiactl', 'nvidia-uvm', 'nvidia-uvm-tools'):
        if not (nodes/node).exists():
            raise RuntimeError('NVIDIA device nodes are incomplete; refusing to start')
    return matches[0]

"""Read owner-local GPU headroom; never substitute zero for a missing sensor."""
import ctypes
import fcntl
import json
import os
from pathlib import Path
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from shared.gpu import intel_arc_device
from shared.serving.state import state_directory

GIB = 2**30


def xe_memory():
    device = intel_arc_device()
    # Linux xe_drm.h: DRM_IOCTL_XE_DEVICE_QUERY, query MEM_REGIONS.
    query = bytearray(struct.pack('=QIIQQQ', 0, 1, 0, 0, 0, 0))
    ioctl = (3 << 30) | (40 << 16) | (ord('d') << 8) | 0x40
    with open(device['render'], 'rb', buffering=0) as fd:
        fcntl.ioctl(fd, ioctl, query, True)
        size = struct.unpack_from('=I', query, 12)[0]
        if not 8 <= size <= 65536:
            raise RuntimeError('invalid xe memory query size')
        data = ctypes.create_string_buffer(size)
        struct.pack_into('=Q', query, 16, ctypes.addressof(data))
        fcntl.ioctl(fd, ioctl, query, True)
    count = struct.unpack_from('=I', data.raw)[0]
    if 8 + count*88 > size:
        raise RuntimeError('invalid xe memory regions')
    regions = [struct.unpack_from('=HHIQQ', data.raw, 8+i*88) for i in range(count)]
    vram = [r for r in regions if r[0] == 1]
    if not vram:
        raise RuntimeError('xe VRAM unavailable')
    return {'total_bytes':sum(r[3] for r in vram),
            'free_bytes':sum(r[3]-r[4] for r in vram), 'source':'xe-memory-regions'}


def read_memory(reg):
    if reg['aliases'][0] == 'arcB70':
        return xe_memory()
    devices = []
    for p in Path('/sys/bus/pci/devices').iterdir():
        try:
            if ((p/'vendor').read_text().strip() == '0x1002' and
                    (p/'driver').resolve().name == 'amdgpu' and (p/'mem_info_gtt_total').exists()
                    and (not reg.get('memory_device_id') or
                         (p/'device').read_text().strip() == reg['memory_device_id'])):
                devices.append(p)
        except OSError:
            continue
    if len(devices) != 1:
        raise RuntimeError('Geekom memory device absent or ambiguous')
    p = devices[0]
    total = int((p/'mem_info_gtt_total').read_text())
    used = int((p/'mem_info_gtt_used').read_text())
    info = dict(line.split(':',1) for line in Path('/proc/meminfo').read_text().splitlines())
    available = int(info['MemAvailable'].split()[0])*1024
    return {'total_bytes':total, 'free_bytes':min(total-used,available), 'source':'amdgpu-gtt-and-memavailable'}


def fit_context(pool, free_bytes, reserve_gib):
    free = free_bytes - (reserve_gib+pool['weight_gib']+pool['runtime_reserve_gib'])*GIB
    step = 4096
    return max(0, min(pool['context_tokens'], int(free/pool['kv_bytes_per_token'])//step*step))


def manifest_path(reg, backend):
    if not backend or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-_' for c in backend):
        raise ValueError('invalid backend ID')
    return state_directory(reg)/('pool-'+backend+'.json')


def launch():
    import argparse
    import sys
    from shared import modelctl
    from shared.serving.catalog import profiles
    from shared.serving.pools import backends
    parser = argparse.ArgumentParser()
    parser.add_argument('--hardware', choices=('geekom','arcB70'), required=True)
    parser.add_argument('--backend', required=True)
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    reg = json.loads((modelctl.ROOT/args.hardware/'models.json').read_text())
    b = backends(reg, profiles(reg))[args.backend]
    pool = reg['shared_serving']['pools'][b['profile']['shared_pool']]
    memory = read_memory(reg)
    context = fit_context(pool, memory['free_bytes'], reg['shared_serving']['reserve_gib'])
    if context < pool['min_context']:
        raise RuntimeError('insufficient measured headroom for minimum context')
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    command[command.index('-c')+1] = str(context)
    path = manifest_path(reg, args.backend)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    allocation = pool['weight_gib']+pool['runtime_reserve_gib']+context*pool['kv_bytes_per_token']/GIB
    modelctl.atomic(path,json.dumps({'backend_id':args.backend, 'context_tokens':context,
                                    'allocation_gib':allocation, 'memory_at_load':memory})+'\n')
    path.chmod(0o600)
    os.execvpe(command[0], command, os.environ)


if __name__ == '__main__':
    launch()

"""Resolve a registered AMD card without relying on PCI or DRM numbering."""
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

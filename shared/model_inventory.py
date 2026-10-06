"""Conservative inventory checks for a physically removed model device."""
import json
from pathlib import Path
import subprocess


def removed_radeon(reg, devices=Path('/sys/bus/pci/devices')):
    if reg['aliases'][0] != '7900xt' or reg.get('container') != 'agent-llm':
        raise RuntimeError('Only the removed Radeon container can be audited offline')
    for device in devices.iterdir():
        if ((device/'vendor').read_text().strip() == '0x1002'
                and (device/'class').read_text().strip().startswith('0x03')):
            raise RuntimeError('AMD display hardware is present; live model inspection required')
    data = json.loads(subprocess.check_output(
        ['docker', 'inspect', reg['container']], text=True, timeout=10))[0]
    if data['State']['Running'] is not False or data['HostConfig']['RestartPolicy']['Name'] != 'no':
        raise RuntimeError('Offline inventory requires a stopped container with restart=no')
    return {'hardware':'7900xt', 'running':[], 'device_absent':True,
            'container_stopped':True, 'restart_policy':'no',
            'scope':'All registered weights remain protected for deferred reuse'}

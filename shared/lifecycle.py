"""Owner-side service lifecycle, shared by CLI and MCP. Caller holds hardware lock."""
import hashlib
import json
import os
from pathlib import Path
import subprocess

from shared import modelctl


def stop_marker(reg):
    runtime = os.environ.get('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}')
    return Path(runtime)/'lario-models'/(reg['aliases'][0]+'.disabled')


def service_state(reg):
    if not reg.get('service'):
        raise RuntimeError('hardware lifecycle service is not provisioned')
    result = subprocess.run(['systemctl', '--user', 'show', reg['service'],
                             '--property=LoadState,ActiveState,SubState,InvocationID'],
                            capture_output=True, text=True, timeout=10)
    values = dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
    if result.returncode or values.get('LoadState') != 'loaded':
        raise RuntimeError('hardware lifecycle service is unavailable')
    return values


def snapshot(reg):
    state = service_state(reg)
    try:
        modelctl.assert_device_ready(reg)
        available, detail = True, None
    except RuntimeError as exc:
        available, detail = False, str(exc)
    marker = stop_marker(reg)
    result = {'service': state['ActiveState'], 'substate': state['SubState'],
              'hardware_available': available, 'manually_stopped': marker.exists()}
    if detail:
        result['detail'] = detail
    fingerprint = {'service': state, 'selection': modelctl.selection(reg),
                   'registry': reg, 'disabled': marker.read_text() if marker.exists() else None,
                   'boot': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                   'hardware_available': available}
    result['lifecycle_token'] = hashlib.sha256(json.dumps(fingerprint, sort_keys=True).encode()).hexdigest()
    return result


def operate(reg, operation, allow_experimental=False):
    if operation not in ('start', 'stop'):
        raise ValueError('unknown lifecycle operation')
    if type(allow_experimental) is not bool:
        raise ValueError('allow_experimental must be boolean')
    modelctl.load_runtime(reg)
    before = service_state(reg)
    marker = stop_marker(reg)
    if before['ActiveState'] in ('activating', 'deactivating', 'reloading'):
        raise RuntimeError('hardware service is transitioning; retry after fresh status')
    if operation == 'stop':
        if before['ActiveState'] not in ('inactive', 'failed'):
            modelctl.assert_not_held(reg, allow_stopped=True)
            if os.environ.get('LARIO_ADMISSION_ENABLED') != '1':
                raise RuntimeError('safe lifecycle stop requires the authenticated admission gateway; legacy backend left running')
            # Close the admission race before the final occupancy check. A failed
            # check leaves the model running/draining; no stop marker is written.
            modelctl.admission_admin(reg, 'drain')
            modelctl.assert_idle(reg)
            modelctl.stop_service(reg)
        changed = before['ActiveState'] not in ('inactive', 'failed') or not marker.exists()
        modelctl.atomic(marker, 'Stopped explicitly for this boot. Use the hardware start command.\n')
        return changed
    modelctl.assert_not_held(reg, allow_stopped=True)
    modelctl.assert_device_ready(reg)
    if before['ActiveState'] == 'active':
        modelctl.runtime_budget(reg)  # Active-but-unhealthy is never certified.
        if marker.exists():
            marker.unlink()
        return False
    key, preset = modelctl.selection(reg)
    if modelctl.is_experimental(reg, key, preset) and not allow_experimental:
        raise RuntimeError('saved experimental preset requires allow_experimental=true / --experimental')
    admission = os.environ.get('LARIO_ADMISSION_ENABLED') == '1'
    modelctl.atomic(modelctl.ROOT/reg['config'], modelctl.render(reg, key, preset, admission))
    if marker.exists():
        marker.unlink()
    subprocess.run(['systemctl', '--user', 'start', reg['service']], check=True)
    try:
        modelctl.runtime_budget(reg)
    except (OSError, ValueError, RuntimeError, KeyError):
        modelctl.warm(reg, key)
    modelctl.admission_admin(reg, 'resume')
    return True

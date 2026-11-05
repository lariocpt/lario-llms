"""Monitor native engine health, not just the lifetime of docker run."""
import subprocess
import json
import tempfile
from pathlib import Path
import time
import urllib.error
import urllib.request


def healthy(url, key):
    request = urllib.request.Request(url, headers={'Authorization': 'Bearer '+key})
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            return response.status == 200
    except (OSError, urllib.error.URLError):
        return False


def supervise(process, probe, *, clock=time.monotonic, sleep=time.sleep,
              startup_timeout=1800, interval=10, failure_limit=3):
    deadline = clock()+startup_timeout
    ready = False
    failures = 0
    while process.poll() is None:
        if probe():
            ready = True
            failures = 0
        elif ready:
            failures += 1
            if failures >= failure_limit:
                raise RuntimeError('Native B70 engine failed consecutive health checks')
        elif clock() >= deadline:
            raise RuntimeError('Native B70 engine startup health timed out')
        sleep(interval)
    # A clean docker exit is unexpected too: administrative stops use systemd.
    raise RuntimeError('B70 container exited: '+str(process.returncode))


def clear_stopped_container():
    """Never evict a running container belonging to another runner."""
    result = subprocess.run(
        ['docker', 'container', 'ls', '-a', '--no-trunc', '--filter',
         'name=^/lario-b70-vllm$', '--format', '{{json .}}'],
        capture_output=True, text=True, timeout=15, check=True)
    for line in result.stdout.splitlines():
        container = json.loads(line)
        if container['State'] not in ('exited', 'dead', 'created'):
            raise RuntimeError('B70 container is already running or stopping; refusing to replace it')
        subprocess.run(['docker', 'rm', container['ID']], timeout=15, check=True)


def cleanup(process, cidfile):
    """Bound Docker calls and address only the container this launch created."""
    cid = cidfile.read_text().strip() if cidfile.exists() else ''
    if cid:
        try:
            subprocess.run(['docker', 'stop', '-t', '10', cid],
                           timeout=15, check=False)
        except (subprocess.TimeoutExpired, OSError):
            pass
        finally:
            # Stop can time out or leave a stopped container behind. Use its ID,
            # never the shared name: a concurrent replacement must survive.
            try:
                subprocess.run(['docker', 'rm', '-f', cid], timeout=15, check=False)
            except (subprocess.TimeoutExpired, OSError):
                pass
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def run(argv, port, key):
    clear_stopped_container()
    with tempfile.TemporaryDirectory(prefix='lario-b70-') as directory:
        cidfile = Path(directory)/'container.id'
        argv = [*argv[:2], '--cidfile', str(cidfile), *argv[2:]]
        process = subprocess.Popen(argv)
        try:
            supervise(process, lambda: healthy(f'http://127.0.0.1:{port}/health', key))
        finally:
            cleanup(process, cidfile)

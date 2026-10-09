#!/usr/bin/env python3
"""Exclusive RTX 5080 NVENC video-encode jobs; restores the chat selection afterwards.

Jobs run detached (multi-hour library batches survive the caller). Same hardware
protocol as the image controller: .rtx5080.lock, modelctl drain -> stop service ->
job -> start + warm + resume.
"""
import argparse
import contextlib
import fcntl
import io
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import socket
import subprocess
import sys
import time
import uuid

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO))
from shared import modelctl

REG = REPO / 'rtx5080/models.json'
STATE_DIR = HERE / '.state'
SSH = ['ssh', '-T', '-n', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', 'lario-media']
SAFE_PATH = re.compile(r'^[A-Za-z0-9 ._:/()\-]+$')
SAFE_TITLE = re.compile(r'^[A-Za-z0-9 ._:\-]+$')
DEFAULTS = {'source_root': '/srv/media/Movies', 'cq': 23, 'limit': 0, 'mirror': True,
            'mirror_dir': '/mnt/xfs/videos/movies', 'mirror_free_gb': 50,
            'log_dir': '/mnt/xfs/videos/movies/.encode-logs'}


def sh(*args, timeout=60):
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout)


def service_state(action):  # is-active | start | stop
    return sh('systemctl', '--user', action, 'rtx5080.service')


def gpu_used_mib():
    result = sh('nvidia-smi', '--query-gpu=memory.used', '--format=csv,noheader,nounits', timeout=15)
    return int(result.stdout.strip().splitlines()[-1]) if result.returncode == 0 else None


def read_state():
    jobs = {}
    for path in sorted(STATE_DIR.glob('*.json')):
        try:
            jobs[path.stem] = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
    return jobs


def write_state(job):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_DIR.joinpath(job['job_id'] + '.json.tmp')
    tmp.write_text(json.dumps(job, indent=1) + '\n')
    tmp.replace(STATE_DIR / (job['job_id'] + '.json'))


def media_probe(root):
    if not SAFE_PATH.match(root) or '..' in root:
        raise ValueError('source_root must be a plain path without shell metacharacters')
    find = (f"find {shlex.quote(root)} -maxdepth 2 -type f "
            r"\( -name '*.mkv' -o -name '*.mp4' \) ! -name '*.shipping' -print0")
    listing = subprocess.run(SSH + [find], capture_output=True, text=True, timeout=120)
    if listing.returncode != 0:
        raise RuntimeError('cannot enumerate sources on lario-media: ' + listing.stderr[:200])
    files = sorted(f for f in listing.stdout.split('\0') if f)
    total = 0
    for path in files:
        stat = subprocess.run(SSH + ['stat -c %s ' + shlex.quote(path)], capture_output=True, text=True, timeout=30)
        if stat.returncode == 0:
            total += int(stat.stdout.strip())
    return files, total


def manifest_counts(log_dir):
    counts = {'DONE': 0, 'TESTDONE': 0, 'FAIL': 0}
    last = None
    try:
        for line in (Path(log_dir) / 'manifest.tsv').read_text().splitlines():
            fields = line.split('\t')
            if len(fields) > 1 and fields[1] in counts:
                counts[fields[1]] += 1
                last = fields[0].rsplit('/', 1)[-1]
    except OSError:
        pass
    return counts, last


def restore(job):
    command = [sys.executable, str(HERE / 'teardown.py'), str(STATE_DIR / (job['job_id'] + '.json'))]
    result = subprocess.run(command, capture_output=True, text=True, timeout=2000)
    if result.returncode:
        raise RuntimeError('chat restore failed: ' + (result.stderr or result.stdout)[-300:])


def running(job):
    pid = job.get('pgid')
    if not pid:
        return False
    try:
        os.killpg(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def acquire_probe():
    """Non-blocking probe of the shared hardware lock; released immediately."""
    with (REPO / '.rtx5080.lock').open('w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('RTX is held by another exclusive job (image or encode)') from None


def options(_request):
    reg = json.loads(REG.read_text())
    modelctl.load_runtime(reg)
    selected = modelctl.selection(reg)
    ffmpeg = shutil.which('ffmpeg') or ''
    encoders = []
    if ffmpeg:
        result = sh(ffmpeg, '-hide_banner', '-encoders', timeout=30)
        encoders = [name for name in ('hevc_nvenc', 'av1_nvenc') if name in result.stdout]
    jobs = read_state()
    active = next((job for job in jobs.values() if job.get('state') in ('starting', 'running', 'restoring')
                   and running(job)), None)
    return {'owner': 'bigcachy', 'encoders': encoders, 'preset': 'p5 (HQ tier)', 'tune': 'hq',
            'cq_range': [16, 30], 'default_cq': 23, 'audio': 'stream copy (never re-encoded)',
            'output_container': 'mkv', 'defaults': DEFAULTS,
            'policy': ('One exclusive RTX job; refuses active chat or a busy card; stops the model service, '
                       'restores the saved chat selection when the job ends.'),
            'runner': str(HERE / 'runner.sh'), 'ffmpeg': ffmpeg,
            'chat_selection': {'model': selected[0], 'preset': selected[1]},
            'service_active': service_state('is-active').returncode == 0,
            'gpu_memory_used_mib': gpu_used_mib(),
            'active_job': None if active is None else {'job_id': active['job_id'], 'state': active['state']}}


def status(_request):
    jobs = read_state()
    job = max(jobs.values(), key=lambda item: item.get('started_mono', 0), default=None)
    if job is None:
        return {'owner': 'bigcachy', 'state': 'idle', 'jobs': 0}
    if not job.get('log_dir'):  # failed before the job directory was reserved
        return {'owner': 'bigcachy', 'state': job['state'], 'job_id': job['job_id'],
                'error': job.get('error'), 'alive': False}
    alive = running(job)
    note = None
    if not alive and job.get('state') in ('starting', 'running', 'restoring'):
        if job.get('limit', 0) and (Path(job['log_dir']) / 'job.done').exists():
            # Bounded test runs finish without touching the chat service; settle them here.
            job.update(state='done', finished_mono=time.time(), restore_pending=False)
            note = 'bounded test run finished (chat service untouched)'
        else:
            job['restore_pending'] = True
            try:
                restore(job)
                job.update(state='interrupted', finished_mono=time.time(), restore_pending=False)
                note = 'runner died without restoring; chat restored by status repair'
            except Exception as error:
                job['restore_error'] = str(error)[:300]
        write_state(job)
    result = dict(job)
    result['alive'] = alive
    counts, last_done = manifest_counts(job['log_dir'])
    result['manifest_counts'] = counts
    result['last_done'] = last_done
    try:
        result['progress'] = json.loads((Path(job['log_dir']) / 'progress.json').read_text())
    except (OSError, ValueError):
        result['progress'] = None
    try:
        lines = (Path(job['log_dir']) / 'run.log').read_text().splitlines()
        result['log_tail'] = lines[-3:]
    except OSError:
        result['log_tail'] = []
    result.pop('started_mono', None)
    result['gpu_memory_used_mib'] = gpu_used_mib()
    result['service_active'] = service_state('is-active').returncode == 0
    if note:
        result['note'] = note
    return result


def start(request):
    if socket.gethostname().split('.')[0] != 'bigcachy':
        raise RuntimeError('encode jobs must be started on bigcachy')
    job = {'job_id': time.strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:4], 'state': 'starting',
           'started_mono': time.time(), 'restore_pending': False, 'log_dir': None}
    try:
        args = dict(DEFAULTS)
        args.update({key: value for key, value in request.items() if value is not None})
        if set(request) - set(DEFAULTS):
            raise ValueError('unknown encode arguments: ' + ', '.join(set(request) - set(DEFAULTS)))
        root = str(args['source_root']).rstrip('/')
        if not SAFE_PATH.match(root) or '..' in root or not root.startswith('/srv/media/'):
            raise ValueError('source_root must stay under /srv/media/ (plain characters only)')
        mirror_dir = str(args['mirror_dir']).rstrip('/')
        if args['mirror'] and (not SAFE_PATH.match(mirror_dir) or '..' in mirror_dir
                               or not mirror_dir.startswith('/mnt/xfs/')):
            raise ValueError('mirror_dir must stay under /mnt/xfs/ (plain characters only)')
        if not isinstance(args['cq'], int) or not 16 <= args['cq'] <= 30:
            raise ValueError('cq must be an integer 16-30')
        if not isinstance(args['limit'], int) or not 0 <= args['limit'] <= 100000:
            raise ValueError('limit must be an integer >= 0')
        if not isinstance(args['mirror_free_gb'], int) or not 20 <= args['mirror_free_gb'] <= 200:
            raise ValueError('mirror_free_gb must be an integer 20-200')
        reg = json.loads(REG.read_text())
        modelctl.load_runtime(reg)
        acquire_probe()
        modelctl.assert_not_held(reg)
        modelctl.assert_device_ready(reg)
        busy = sh('bash', '-c', "pgrep -f '[p]ipeline.sh|[r]unner.sh' || true", timeout=15).stdout.strip()
        if busy:
            raise RuntimeError('an encoder is already running (pids ' + busy.replace('\n', ' ') + ')')
        files, total_bytes = media_probe(root)
        if not files:
            raise RuntimeError('no .mkv/.mp4 sources found under ' + root)
        done = 0
        try:
            manifest = Path(DEFAULTS['log_dir']) / 'manifest.tsv'
            finished = {line.split('\t')[0] for line in manifest.read_text().splitlines()
                        if len(line.split('\t')) > 1 and line.split('\t')[1] in ('DONE', 'TESTDONE')}
            done = len(set(files) & finished)
        except OSError:
            pass
        if args['limit']:
            files = files[:args['limit']]
        log_dir = str(args['log_dir']).rstrip('/')
        if not SAFE_PATH.match(log_dir) or '..' in log_dir or not log_dir.startswith('/mnt/xfs/'):
            raise ValueError('log_dir must stay under /mnt/xfs/ (plain characters only)')
        Path(log_dir).mkdir(parents=True, exist_ok=True)
        job.update(log_dir=log_dir, source_root=root, cq=args['cq'], limit=args['limit'],
                   mirror=bool(args['mirror']), mirror_dir=mirror_dir,
                   mirror_free_gb=args['mirror_free_gb'], total=len(files), already_done=done,
                   source_bytes=total_bytes)
        write_state(job)
        # Reserve the hardware exactly like the image controller: validate first, then drain/stop.
        # With the service already inactive there is no inference to be idle-checking.
        job['was_chat_active'] = service_state('is-active').returncode == 0
        if job['was_chat_active']:
            modelctl.assert_idle(reg)
        selected = modelctl.selection(reg)
        job['chat_selection'] = {'model': selected[0], 'preset': selected[1]}
        write_state(job)
        modelctl.admission_admin(reg, 'drain')
        job['drained'] = True
        write_state(job)
        if job['was_chat_active']:
            if service_state('stop').returncode:
                raise RuntimeError('failed to stop rtx5080.service for the encode job')
        env = os.environ.copy()
        env.update(LARIO_ENC_MEDIA_HOST='lario-media', LARIO_ENC_SVC='rtx5080.service',
                   LARIO_ENC_ROOT=root, LARIO_ENC_CQ=str(args['cq']), LARIO_ENC_LIMIT=str(args['limit']),
                   LARIO_ENC_LOG_DIR=log_dir, LARIO_ENC_XFS_DIR=mirror_dir if args['mirror'] else '',
                   LARIO_ENC_FLOOR=str(args['mirror_free_gb']), LARIO_ENC_STATE=str(STATE_DIR / (job['job_id'] + '.json')))
        process = subprocess.Popen(['setsid', 'bash', str(HERE / 'runner.sh')], env=env,
                                   stdin=subprocess.DEVNULL,
                                   stdout=open(log_dir + '/runner.out', 'a'), stderr=subprocess.STDOUT)
        job['pgid'] = process.pid
        job['state'] = 'running'
        write_state(job)
        time.sleep(3)
        if process.poll() is not None:
            raise RuntimeError('runner exited immediately: ' + open(log_dir + '/runner.out').read()[-300:])
    except Exception as error:
        job['state'] = 'failed'
        job['error'] = str(error)[:400]
        if job.get('drained') or job.get('was_chat_active'):
            job['restore_pending'] = True
            write_state(job)  # teardown.py reads the state file, so persist the flags first
            with contextlib.suppress(Exception):
                restore(job)
                job['restore_pending'] = False
        write_state(job)
        raise
    return {'job_id': job['job_id'], 'scope': 'Exclusive RTX job; the chat endpoint is unavailable until the job restores its saved selection.',
            'sources': len(files), 'already_done': done, 'source_bytes': total_bytes,
            'cq': args['cq'], 'limit': args['limit'], 'mirror': bool(args['mirror']),
            'mirror_dir': mirror_dir if args['mirror'] else None, 'log_dir': log_dir,
            'chat_selection': job['chat_selection']}


def cancel(_request):
    jobs = read_state()
    job = max((item for item in jobs.values() if running(item)),
              key=lambda item: item.get('started_mono', 0), default=None)
    if job is None:
        return {'cancelled': None, 'detail': 'no running encode job'}
    os.killpg(job['pgid'], 15)  # TERM the whole process group; runner.sh traps and restores chat
    deadline = time.monotonic() + 120
    while running(job) and time.monotonic() < deadline:
        time.sleep(2)
    reg = json.loads(REG.read_text())
    modelctl.load_runtime(reg)
    restore(job)  # idempotent: teardown skips the service start when runner.sh already restored
    job['state'] = 'cancelled'
    job['cancelled_mono'] = time.time()
    job['restore_pending'] = False
    write_state(job)
    return {'cancelled': job['job_id'], 'alive': running(job),
            'service_active': service_state('is-active').returncode == 0}


OPERATIONS = {'options': options, 'status': status, 'start': start, 'cancel': cancel}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=sorted(OPERATIONS))
    parser.add_argument('--json', help='request arguments as a JSON object (otherwise read stdin)')
    args = parser.parse_args()
    try:
        request = json.loads(args.json) if args.json else (json.load(sys.stdin) if not sys.stdin.isatty() else {})
        result = OPERATIONS[args.operation](request)
        print(json.dumps(result), flush=True)
    except Exception as error:
        print(json.dumps({'error': {'type': type(error).__name__, 'message': str(error)[:500]}}), flush=True)
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()

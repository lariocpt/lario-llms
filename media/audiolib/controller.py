#!/usr/bin/env python3
"""Fetch jobs for the quranaudiobooks M4B library, on this box's media disk.

Jobs run detached (46 GB outlives the caller). Same shape as the encoder
controller: JSON in, JSON out, job state in ``.state/``, job logs beside the
library so they outlive a scratch disk.

This tool never re-encodes.  The source library is already AAC-LC mono 32 kHz
at ~64 kbps — measured over 34 files on 2026-10-13, see README — so re-encoding
it buys space only by spending a generation of quality.  Storing what pCloud
serves, byte-exact, is the one policy that cannot make the collection worse.
"""
import argparse
import fcntl
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import catalog        # noqa: E402  (sibling module, same directory)

STATE_DIR = HERE / '.state'
RUNNER = HERE / 'runner.py'
SAFE_PATH = re.compile(r'^[A-Za-z0-9 ._:/()\-]+$')
# The only volume this tool writes to.  Both root and log_root must sit under
# it; tests redirect it rather than relaxing the rule.
MEDIA_ANCHOR = '/mnt/media'
DEFAULTS = {'root': catalog.ROOT, 'include': [], 'limit': 0, 'workers': 4,
            'log_root': '/mnt/media/audiobooks/.audiolib-jobs', 'min_free_gb': 20}
GB = 2 ** 30


def disk_free(path):
    """Bytes free on the filesystem holding ``path`` (nearest existing ancestor)."""
    anchor = Path(path)
    while not anchor.exists() and anchor != anchor.parent:
        anchor = anchor.parent
    return shutil.disk_usage(str(anchor)).free


def lock_path(log_root):
    return Path(log_root) / '.lock'


def lock_holder(log_root):
    """The pid holding the library writer lock, or None when nobody holds it.

    The guard is an advisory lock rather than a scan of ``.state/`` on purpose:
    state files only record jobs *this* controller started, and the writer that
    matters most is the one started by something else -- a stray test run, a
    forgotten shell, another session.  Two jobs over one tree are not merely
    wasteful: they share a ``<name>.part`` path, so one can rename a verified
    file into the library while the other still has that path open and keeps
    appending to it, silently corrupting a finished library file.
    """
    path = lock_path(log_root)
    if not path.exists():
        return None
    try:
        handle = open(path, 'a+')
    except OSError:
        return None
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.seek(0)
        return handle.read().strip() or 'another job'
    finally:
        try:
            fcntl.flock(handle, fcntl.LOCK_UN)
        except OSError:
            pass
        handle.close()
    return None


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


def read_json(path):
    """Parse a JSON file, or None when it is absent or unreadable."""
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None


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


def latest(jobs):
    """Newest job by start time (accepts the state dict or a list of jobs)."""
    items = list(jobs.values()) if isinstance(jobs, dict) else list(jobs)
    return max(items, key=lambda item: item.get('started_mono', 0), default=None)


def active(jobs):
    return latest([job for job in jobs.values() if running(job)])


def inventory(entries, root):
    """How much of a selection is already on disk, and what is missing."""
    present_bytes = missing = missing_bytes = 0
    present = 0
    for entry in entries:
        destination = catalog.destination(entry['rel'], root)
        try:
            size = os.stat(destination).st_size
        except OSError:
            size = -1
        if size == (entry['size'] or -1) and size >= 0:
            present += 1
            present_bytes += size
        elif size >= 0:
            missing += 1
            missing_bytes += entry['size'] or 0        # wrong size: re-fetch
        else:
            missing += 1
            missing_bytes += entry['size'] or 0
    partial = sum(1 for path in Path(root).rglob('*.part')) if Path(root).exists() else 0
    return {'files': len(entries), 'present': present, 'present_bytes': present_bytes,
            'missing': missing, 'missing_bytes': missing_bytes, 'partial_parts': partial}


def catalog_op(request):
    """What the source offers, and what is already on disk."""
    data = catalog.load()
    include = request.get('include') or []
    if not isinstance(include, list):
        raise ValueError('include must be a list of collection paths')
    entries = catalog.select(data, include)
    summary = inventory(entries, data['root'])
    return {'source_page': data['source_page'], 'generated': data['generated'],
            'root': data['root'], 'totals': data['totals'],
            'collections': data['collections'], 'selected': {
                'files': summary['files'], 'bytes': sum(entry['size'] or 0 for entry in entries),
                'on_disk': summary['present'], 'on_disk_bytes': summary['present_bytes'],
                'missing': summary['missing'], 'missing_bytes': summary['missing_bytes']},
            'encoding': 'AAC-LC mono 32 kHz ~64 kbps as published; never re-encoded here',
            'dropped': data.get('dropped', [])}


def refresh_op(_request):
    """Re-scrape the site and report how the catalog changed."""
    before = catalog.load() if catalog.CATALOG.exists() else None
    data = catalog.build(refresh=True)
    return {'generated': data['generated'], 'totals': data['totals'],
            'collections': data['collections'],
            'changed': None if before is None else {
                'files_before': before['totals']['files'], 'files_after': data['totals']['files'],
                'bytes_before': before['totals']['bytes'], 'bytes_after': data['totals']['bytes']},
            'catalog': str(catalog.CATALOG)}


def start_op(request):
    if socket.gethostname().split('.')[0] != 'bigcachy':
        raise RuntimeError('audiobook jobs must be started on bigcachy')
    job = {'job_id': time.strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:4],
           'state': 'starting', 'started_mono': time.time()}
    try:
        if active(read_state()) is not None:
            raise RuntimeError('an audiobook job is already running; check status or cancel it')
        args = dict(DEFAULTS)
        args.update({key: value for key, value in request.items() if value is not None})
        unknown = set(request) - set(DEFAULTS)
        if unknown:
            raise ValueError('unknown job arguments: ' + ', '.join(sorted(unknown)))
        root = str(args['root']).rstrip('/')
        if not SAFE_PATH.match(root) or '..' in root or not root.startswith(MEDIA_ANCHOR):
            raise ValueError('root must stay under %s (plain characters only)' % MEDIA_ANCHOR)
        log_root = str(args['log_root']).rstrip('/')
        if (not SAFE_PATH.match(log_root) or '..' in log_root
                or not log_root.startswith(MEDIA_ANCHOR)):
            raise ValueError('log_root must stay under %s (plain characters only)' % MEDIA_ANCHOR)
        if not isinstance(args['include'], list) or any(not isinstance(v, str) for v in args['include']):
            raise ValueError('include must be a list of collection paths')
        if not isinstance(args['limit'], int) or not 0 <= args['limit'] <= 1000000:
            raise ValueError('limit must be an integer >= 0')
        if not isinstance(args['workers'], int) or not 1 <= args['workers'] <= 8:
            raise ValueError('workers must be an integer 1-8')
        if not isinstance(args['min_free_gb'], int) or not 1 <= args['min_free_gb'] <= 200:
            raise ValueError('min_free_gb must be an integer 1-200')
        holder = lock_holder(log_root)
        if holder is not None:
            raise RuntimeError('another audiobook job holds the writer lock on %s (pid %s): '
                               'concurrent jobs share .part files and corrupt verified files'
                               % (log_root, holder))

        data = catalog.load()
        entries = catalog.select(data, args['include'])
        if args['limit']:
            entries = entries[:args['limit']]
        if not entries:
            raise RuntimeError('nothing selected')
        summary = inventory(entries, root)
        free = disk_free(root)
        floor = args['min_free_gb'] * GB
        if free < summary['missing_bytes'] + floor:
            raise RuntimeError('refusing to start: %.1f GiB free on %s, %.1f GiB needed for '
                               'the missing files plus a %.0f GiB floor'
                               % (free / GB, root, summary['missing_bytes'] / GB,
                                  args['min_free_gb']))

        job_dir = Path(log_root) / ('j-' + job['job_id'])
        job_dir.mkdir(parents=True, exist_ok=False)
        spec = {'catalog': str(catalog.CATALOG), 'root': root, 'include': args['include'],
                'limit': args['limit'], 'workers': args['workers'], 'log_dir': str(job_dir),
                'lock_file': str(lock_path(log_root))}
        spec_path = job_dir / 'spec.json'
        spec_path.write_text(json.dumps(spec, indent=1) + '\n')
        job.update(state='running', root=root, include=args['include'], limit=args['limit'],
                   workers=args['workers'], log_dir=str(job_dir), files=len(entries),
                   missing=summary['missing'], missing_bytes=summary['missing_bytes'])
        write_state(job)
        # start_new_session puts the runner in its own process group (so cancel
        # can TERM the whole group) while keeping it our direct child, so poll()
        # and pgid both refer to the runner itself.  Running the `setsid` binary
        # here instead forks it away: the wrapper exits at once, the runner
        # carries on untracked, and pgid would name the wrong process.
        process = subprocess.Popen([sys.executable, str(RUNNER), str(spec_path)],
                                   stdin=subprocess.DEVNULL,
                                   stdout=open(job_dir / 'runner.out', 'a'),
                                   stderr=subprocess.STDOUT, start_new_session=True)
        job['pgid'] = process.pid
        write_state(job)
        # A bounded job over files that are already on disk can finish inside the
        # liveness window, so an early exit is only a failure without a result.
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and process.poll() is None:
            time.sleep(0.5)
        result = read_json(job_dir / 'result.json')
        if process.poll() is not None and result is None:
            raise RuntimeError('runner exited immediately: '
                               + (job_dir / 'runner.out').read_text()[-300:])
        if result is not None:
            job['state'] = result.get('state', 'ended')
            write_state(job)
    except Exception as error:
        job['state'] = 'failed'
        job['error'] = str(error)[:400]
        write_state(job)
        raise
    return {'job_id': job['job_id'], 'state': job['state'], 'log_dir': str(job_dir),
            'root': root, 'include': args['include'] or ['(whole library)'],
            'files': len(entries), 'already_on_disk': summary['present'],
            'to_fetch': summary['missing'], 'to_fetch_bytes': summary['missing_bytes'],
            'workers': args['workers'], 'free_gb': round(free / GB, 1),
            'result': result}


def status_op(_request):
    jobs = read_state()
    job = latest(jobs)
    if job is None:
        return {'owner': 'bigcachy', 'state': 'idle', 'jobs': 0, 'root': catalog.ROOT,
                'totals': catalog.load()['totals']}
    log_dir = Path(job['log_dir']) if job.get('log_dir') else None
    alive = running(job)
    note = None
    if not alive and job.get('state') in ('starting', 'running'):
        result = read_json(log_dir / 'result.json') if log_dir else None
        if result:
            job.update(state=result.get('state', 'ended'), finished_mono=time.time())
            note = 'runner finished without settling its state'
        else:
            job.update(state='interrupted', finished_mono=time.time())
            note = 'runner died without a result; restart to resume'
        write_state(job)
    out = dict(job)
    out['alive'] = alive
    out.pop('started_mono', None)
    if log_dir is not None:
        out['progress'] = read_json(log_dir / 'progress.json')
        result = read_json(log_dir / 'result.json')
        if result:
            out['failures'] = result.get('failures', [])
        try:
            out['log_tail'] = (log_dir / 'run.log').read_text().splitlines()[-3:]
        except OSError:
            out['log_tail'] = []
    entries = catalog.select(catalog.load(), job.get('include') or [])
    if job.get('limit'):
        entries = entries[:job['limit']]
    out['library'] = inventory(entries, job.get('root', catalog.ROOT))
    out['free_gb'] = round(disk_free(job.get('root', catalog.ROOT)) / GB, 1)
    if note:
        out['note'] = note
    return out


def cancel_op(_request):
    job = active(read_state())
    if job is None:
        return {'cancelled': None, 'detail': 'no running audiobook job'}
    os.killpg(job['pgid'], 15)
    deadline = time.monotonic() + 120
    while running(job) and time.monotonic() < deadline:
        time.sleep(2)
    job['state'] = 'cancelling' if running(job) else 'cancelled'
    job['cancelled_mono'] = time.time()
    write_state(job)
    result = read_json(Path(job['log_dir']) / 'result.json') if job.get('log_dir') else {}
    return {'cancelled': job['job_id'], 'alive': running(job),
            'done': result.get('done'), 'bytes': result.get('bytes'),
            'detail': 'in-flight files were left as .part and will resume on the next start'}


OPERATIONS = {'catalog': catalog_op, 'refresh': refresh_op, 'start': start_op,
              'status': status_op, 'cancel': cancel_op}


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('operation', choices=sorted(OPERATIONS))
    parser.add_argument('--json', help='request arguments as a JSON object (otherwise read stdin)')
    args = parser.parse_args()
    try:
        request = json.loads(args.json) if args.json else (
            json.load(sys.stdin) if not sys.stdin.isatty() else {})
        print(json.dumps(OPERATIONS[args.operation](request)), flush=True)
    except Exception as error:
        print(json.dumps({'error': {'type': type(error).__name__, 'message': str(error)[:500]}}),
              flush=True)
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()

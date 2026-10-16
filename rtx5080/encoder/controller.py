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
SAFE_PATH = re.compile(r'^[A-Za-z0-9 ._:/()\-]+$')
SAFE_TITLE = re.compile(r'^[A-Za-z0-9 ._:\-]+$')
# 2026-10-13: lario-media was retired and the library came with it, so the
# sources are local to this box (the same box that holds the RTX card) — there
# is no ssh peer left to reach them through. log_dir lives with the library so
# the done/refused manifest outlives the scratch disk it is used to.
DEFAULTS = {'source_root': '/mnt/media/movies', 'cq': 23, 'limit': 0, 'mirror': True,
            'mirror_dir': '/mnt/xfs/videos/movies', 'mirror_free_gb': 50,
            'log_dir': '/mnt/media/movies/.encode-logs'}
MEDIA_ROOT = '/mnt/media/'
# The library's output budget, GB/h by height class (decimal GB). A height at or
# below 1080 lines inherits the 1080p ceiling rather than a looser one. Not
# request arguments: a caller picks quality (cq), never the target the quality
# has to fit. Overridable in the server's environment for re-calibration.
BUDGET_GBH = {'1080': float(os.getenv('LARIO_ENC_BUDGET_1080', '3.0')),
              '1440': float(os.getenv('LARIO_ENC_BUDGET_1440', '4.5')),
              '2160': float(os.getenv('LARIO_ENC_BUDGET_2160', '8.0'))}
# The ladder: start coarser when a source is far over budget, step coarser at
# most MAX_RUNG_STEPS further, never past the bottom of cq_range. A title that
# still misses the budget after every rung is left alone (OVERSIZE), not squeezed.
CQ_RANGE = (16, 30)
CQ_STEP = 2
MAX_RUNG_STEPS = 2
MIN_GAIN_PCT = 15


def ladder_policy():
    """The ladder as one description, so options() and the runner cannot drift."""
    return {'start': 'the requested cq, or coarser when the source is far over budget',
            'step': CQ_STEP, 'max_steps': MAX_RUNG_STEPS,
            'cq_max': CQ_RANGE[1],
            'a_rung_missing_either_gate': 'encode dropped, step coarser and retry',
            'still_missing_after_every_rung': 'OVERSIZE or NOGAIN — source left untouched'}
VIDEO_SUFFIXES = ('.mkv', '.mp4')
# Directories never encoded, matched by name at any depth. The Live Photos
# staging tree's deletion queue is full of second-rate video, and _mediatool is
# where a toolkit run keeps its evidence. Must match runner.sh's SKIP_NAMES,
# which hardcodes the same three; only the operator's additions are passed down,
# so the runner's own list is never duplicated into a longer one.
SKIP_DIR_NAMES = {'live-photos-for-deletion', '_live_photos', '_mediatool'}
EXTRA_SKIP_DIRS = [part.strip() for part in os.getenv('LARIO_ENC_SKIP_DIRS', '').split(':') if part.strip()]
SKIP_DIR_NAMES.update(EXTRA_SKIP_DIRS)


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


def _pruned(path, root):
    """True when `path` sits where runner.sh's find would prune it.

    Mirrors the scan in runner.sh: any dotted directory (.git, .encode-logs),
    the skip-list at any depth, dotted file names, and the '.shipping' temp a
    promote leaves beside a source. Keep the two in step deliberately -- this
    count is what the operator reads before committing to a multi-hour job, and
    a queue that disagrees either hides titles or promises work the runner will
    never do.
    """
    if path.name.startswith('.') or path.name.endswith('.shipping'):
        return True
    for part in path.relative_to(root).parts[:-1]:
        if part.startswith('.') or part in SKIP_DIR_NAMES:
            return True
    return False


def _sources(root):
    """Every .mkv/.mp4 under `root` at any depth: no symlinks, nothing pruned.

    The scan used to be capped two levels deep in both this file and the runner,
    which made any deeper title invisible to the job forever (PLAN defect 1).
    """
    base = Path(root)
    found = [path for path in base.rglob('*')
             if not path.is_symlink() and path.is_file()
             and path.name.lower().endswith(VIDEO_SUFFIXES)
             and not _pruned(path, base)]
    return sorted(found)


def media_probe(root):
    """Enumerate sources locally, and total their bytes.

    Local by necessity since 2026-10-13: the library used to be on lario-media
    and every listing/stat call went over ssh, but that box is retired and its
    disk is now /mnt/media here.
    """
    if not SAFE_PATH.match(root) or '..' in root:
        raise ValueError('source_root must be a plain path without shell metacharacters')
    base = Path(root)
    if not base.is_dir():
        raise RuntimeError('source_root is not a directory on this host: ' + root)
    found = _sources(root)
    files = [str(path) for path in found]
    total = 0
    for path in found:
        try:
            total += path.stat().st_size
        except OSError:
            continue
    return files, total


def manifest_tally(log_dir):
    """Tally the manifest by decision, and how many bytes the commits reclaimed.

    The refusals are counted alongside the successes because they are the
    interesting half: SKIPSIZE / SKIPCODEC / OVERSIZE / NOGAIN are four different
    reasons a source was left exactly as it was, and a run that reports only DONE
    looks like a run that did nothing.

    One rename commits a title under two names -- the runner writes a DONE row for
    the source path and another for the committed path, so the skip-list recognises
    the new .mkv name. Both rows are the same encode, so bytes and titles are
    counted once and the second row is tallied separately as an alias. It is always
    the row immediately after, which is what makes this pairable without a run id.

    last_done names the most recent *committed* title, under the name it has now.
    A FAIL or a refusal does not move it: the field is called last_done and an
    operator reading it is asking what the job last actually produced.
    """
    counts = {'DONE': 0, 'TESTDONE': 0, 'FAIL': 0, 'SKIP': 0, 'SKIPCODEC': 0,
              'SKIPSIZE': 0, 'NOGAIN': 0, 'OVERSIZE': 0}
    reclaimed = aliases = 0
    last = None
    prev_done_key = None
    try:
        for line in (Path(log_dir) / 'manifest.tsv').read_text().splitlines():
            fields = line.split('\t')
            if len(fields) < 2 or fields[1] not in counts:
                continue
            key = tuple(fields[2:]) if fields[1] == 'DONE' else None
            if key is not None and key == prev_done_key:
                aliases += 1          # the rename's second row: not a new commit
                last = fields[0].rsplit('/', 1)[-1]
                continue
            prev_done_key = key
            counts[fields[1]] += 1
            if fields[1] == 'DONE':
                last = fields[0].rsplit('/', 1)[-1]
                try:
                    reclaimed += int(fields[2]) - int(fields[3])
                except (ValueError, IndexError):
                    pass
    except OSError:
        pass
    return {'counts': counts, 'last_done': last, 'reclaimed_bytes': reclaimed,
            'rename_alias_rows': aliases}


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
            'rate_control': ('-rc constqp -qp N (true constant QP). Measured 2026-10-16 on this build: '
                             'bare -cq and -rc vbr -cq N -b:v 0 are byte-identical, so -cq was never ignored; '
                             'constqp is the mode chosen because a size budget needs a predictable '
                             'size-per-rung and VBR smoothing is what a budget cannot predict.'),
            'cq_range': list(CQ_RANGE), 'default_cq': DEFAULTS['cq'],
            'size_budget_gb_per_h': BUDGET_GBH,
            'ladder': ladder_policy(),
            'gates': ['dup_stem', 'SKIPCODEC', 'SKIPSIZE (decided without encoding)',
                      'encode+verify', 'OVERBUDGET / LOWGAIN (step the rung coarser)',
                      'OVERSIZE | NOGAIN (after the last rung)', 'promote+sha256', 'commit'],
            'scaling': 'none — the picture is never downscaled and audio is always stream-copy',
            'audio': 'stream copy (never re-encoded)',
            'output_container': 'mkv', 'defaults': DEFAULTS,
            'scan': ('whole depth under source_root; symlinks, .shipping temps, dotted directories and the '
                     'skip-list are pruned; matches the runner’s find exactly'),
            'scan_skip_dirs': sorted(SKIP_DIR_NAMES),
            'policy': ('One exclusive RTX job; refuses active chat or a busy card; stops the model service, '
                       'restores the saved chat selection when the job ends. Sources are local to bigcachy. '
                       'A source is only ever replaced by something better and smaller: already-HEVC/AV1 '
                       'sources are skipped, titles already inside the size budget are skipped without '
                       'encoding, a title that no rung can bring inside the budget is left alone, and an '
                       f'encode under {MIN_GAIN_PCT}% smaller than its source is refused as generation loss.'),
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
    tally = manifest_tally(job['log_dir'])
    result['manifest_counts'] = tally['counts']
    result['last_done'] = tally['last_done']
    result['reclaimed_bytes'] = tally['reclaimed_bytes']
    if tally['rename_alias_rows']:
        result['rename_alias_rows'] = tally['rename_alias_rows']
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
        if not SAFE_PATH.match(root) or '..' in root or not root.startswith(MEDIA_ROOT):
            raise ValueError('source_root must stay under ' + MEDIA_ROOT + ' (plain characters only)')
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
        log_dir = str(args['log_dir']).rstrip('/')
        if (not SAFE_PATH.match(log_dir) or '..' in log_dir
                or not (log_dir.startswith('/mnt/media/') or log_dir.startswith('/mnt/xfs/'))):
            raise ValueError('log_dir must stay under /mnt/media/ or /mnt/xfs/ (plain characters only)')
        # 'Settled' = this path needs no further work: encoded, already modern,
        # already inside budget, refused for having no gain, or left alone because
        # no rung fits it. Reads the job's own log_dir, not the default one, so a
        # non-default job reports its own history. TESTDONE is NOT settled: it is
        # what a bounded (limit>0) run records, and such a run never deletes a
        # source, so the commit it stands for has not happened yet. Counting it as
        # done would report a library of pending work as finished.
        done = 0
        try:
            settled = {line.split('\t')[0]
                       for line in (Path(log_dir) / 'manifest.tsv').read_text().splitlines()
                       if len(line.split('\t')) > 1
                       and line.split('\t')[1] in ('DONE', 'SKIPCODEC', 'SKIPSIZE',
                                                   'NOGAIN', 'OVERSIZE')}
            done = len(set(files) & settled)
        except OSError:
            pass
        if args['limit']:
            files = files[:args['limit']]
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
        env.update(LARIO_ENC_SVC='rtx5080.service', LARIO_ENC_ROOT=root,
                   LARIO_ENC_CQ=str(args['cq']), LARIO_ENC_LIMIT=str(args['limit']),
                   LARIO_ENC_LOG_DIR=log_dir, LARIO_ENC_XFS_DIR=mirror_dir if args['mirror'] else '',
                   LARIO_ENC_FLOOR=str(args['mirror_free_gb']), LARIO_ENC_STATE=str(STATE_DIR / (job['job_id'] + '.json')),
                   LARIO_ENC_BUDGET_1080=str(BUDGET_GBH['1080']), LARIO_ENC_BUDGET_1440=str(BUDGET_GBH['1440']),
                   LARIO_ENC_BUDGET_2160=str(BUDGET_GBH['2160']), LARIO_ENC_SKIP_DIRS=':'.join(EXTRA_SKIP_DIRS))
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

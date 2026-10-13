#!/usr/bin/env python3
"""Detached fetch job for the quranaudiobooks M4B library.

Started by controller.py under ``setsid`` so a multi-hour transfer outlives the
caller.  Reads a job spec (JSON path in argv[1]) and fetches the catalog entries
it selects into the library root.

Resumable and idempotent: a file is skipped when it already exists at the
expected byte size, anything else is fetched into ``<name>.part`` (curl resumes
that) and renamed into place only once the size matches, so an interrupted
transfer can never look like a finished one.  A SIGTERM stops scheduling new
files, lets the in-flight ones land, and leaves ``.part`` files where they are
for the next job to resume.

Nothing here deletes a file it did not just write: the only removals are of a
``.part`` whose size exceeds the expected size (a bad resume, unrecoverable) and
the rename that publishes a verified ``.part``.

Spec: {"catalog", "root", "include": [prefix...], "limit": int, "workers": int,
"log_dir": dir}.  Writes run.log, progress.json, ledger.tsv, result.json.
"""
import fcntl
import json
import os
import signal
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import catalog        # noqa: E402  (sibling module, same directory)
import pcloud         # noqa: E402

MAX_TRIES = 6
PROBE_INTERVAL = 2.0

stop = threading.Event()
lock = threading.Lock()
counters = {'done': 0, 'skipped': 0, 'failed': 0, 'stopped': 0, 'bytes': 0}
_writer_lock = None


def acquire_writer_lock(spec):
    """Hold the library's writer lock for the lifetime of this process.

    The controller probes the same lock before spawning, but the runner has to
    take it itself: a check *before* a spawn only races with the spawn.
    Concurrent writers are not just wasteful -- they share a ``<name>.part``
    path, so one job can rename a size-verified file into the library while
    another still holds that path open and keeps appending to it, corrupting a
    file both of them believe is finished.
    """
    global _writer_lock
    path = Path(spec.get('lock_file') or Path(spec['log_dir']).parent / '.lock')
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(path, 'a+')
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.seek(0)
        holder = handle.read().strip() or 'unknown'
        handle.close()
        raise RuntimeError('the audiobook writer lock is held by pid %s; not fetching' % holder)
    handle.seek(0)
    handle.truncate()
    handle.write('%d\n' % os.getpid())
    handle.flush()
    _writer_lock = handle
    return handle


class Ledger:
    """Append-only ``rel<TAB>state<TAB>bytes<TAB>note`` record of what happened."""

    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.Lock()
        self.failures = []

    def add(self, rel, state, size=0, note=''):
        line = '%s\t%s\t%d\t%s' % (rel, state, size, note.replace('\t', ' '))
        with self.lock:
            if state == 'FAIL':
                self.failures.append({'rel': rel, 'note': note[:200]})
            with self.path.open('a', encoding='utf-8') as handle:
                handle.write(line + '\n')


def log(path, message):
    line = '%s %s' % (time.strftime('%F %T'), message)
    with lock:
        with Path(path).open('a', encoding='utf-8') as handle:
            handle.write(line + '\n')


def fetch(entry, root):
    """Fetch one catalog entry.  Returns (state, bytes, note), state in OK/SKIP/STOP/FAIL."""
    want = entry['size'] or 0
    dest = catalog.destination(entry['rel'], root)
    part = dest + '.part'
    if os.path.exists(dest) and os.path.getsize(dest) == want:
        return 'SKIP', 0, ''
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    note = ''
    for attempt in range(MAX_TRIES):
        if stop.is_set():
            return 'STOP', 0, 'cancelled before attempt; nothing was fetched'
        have = os.path.getsize(part) if os.path.exists(part) else 0
        if want and have > want:                       # a resume longer than the file: bad
            os.remove(part)
            have = 0
        try:
            url = pcloud.download_url(entry['code'], entry['fileid'], host_index=attempt)
            if not (want and have >= want):
                pcloud.transfer(url, part)
            got = os.path.getsize(part)
        except (pcloud.PcloudError, OSError) as error:
            note = str(error)[:180]
            time.sleep(min(2 ** attempt, 20))
            continue
        if want and got != want:
            note = 'size %d != expected %d' % (got, want)
            time.sleep(min(2 ** attempt, 20))
            continue
        os.replace(part, dest)
        return 'OK', got, ''
    return 'FAIL', 0, note or '%d tries without a verified transfer' % MAX_TRIES


def _one(entry, root, ledger, job_log):
    state, size, note = fetch(entry, root)
    ledger.add(entry['rel'], state, size, note)
    with lock:
        if state == 'OK':
            counters['done'] += 1
            counters['bytes'] += size
        elif state == 'SKIP':
            counters['skipped'] += 1
        elif state == 'STOP':
            counters['stopped'] += 1
        else:
            counters['failed'] += 1
    if note and state == 'FAIL':
        log(job_log, '%s %s: %s' % (state, entry['rel'], note))
    return state


def _write_progress(path, snapshot):
    tmp = Path(str(path) + '.tmp')
    tmp.write_text(json.dumps(snapshot, indent=1) + '\n')
    tmp.replace(path)


def run(spec):
    """Execute the job described by ``spec`` and return the result dict."""
    acquire_writer_lock(spec)
    started = time.time()
    root, workers = spec['root'], max(1, min(int(spec.get('workers', 4)), 8))
    data = catalog.load(spec['catalog'])
    entries = catalog.select(data, spec.get('include') or ())
    if spec.get('limit'):
        entries = entries[:int(spec['limit'])]
    log_dir = Path(spec['log_dir'])
    log_dir.mkdir(parents=True, exist_ok=True)
    job_log = log_dir / 'run.log'
    ledger = Ledger(log_dir / 'ledger.tsv')
    progress = {'state': 'running', 'total': len(entries),
                'total_bytes': sum(entry['size'] or 0 for entry in entries),
                'root': root, 'include': spec.get('include') or [],
                'updated': time.time()}
    log(job_log, 'start: %d files, %.2f GiB, %d workers, include=%s'
        % (len(entries), progress['total_bytes'] / 2 ** 30, workers,
           spec.get('include') or 'ALL'))
    _write_progress(log_dir / 'progress.json', progress)

    with ThreadPoolExecutor(workers) as pool:
        pending = [pool.submit(_one, entry, root, ledger, job_log) for entry in entries]
        while any(not future.done() for future in pending):
            time.sleep(PROBE_INTERVAL)
            if stop.is_set():
                for future in pending:
                    future.cancel()
                break
            with lock:
                elapsed = max(time.time() - started, 1)
                rate = counters['bytes'] / elapsed
                snapshot = dict(progress)
                snapshot.update(counters)
                snapshot.update(elapsed_s=round(elapsed, 1),
                                rate_mib_s=round(rate / 2 ** 20, 2),
                                eta_min=round((progress['total_bytes'] - counters['bytes'])
                                              / max(rate, 1) / 60, 1),
                                updated=time.time())
            _write_progress(log_dir / 'progress.json', snapshot)
        for future in pending:
            if future.done() and not future.cancelled():
                future.result()

    if stop.is_set():
        state = 'cancelled'
    elif counters['failed'] == 0:
        state = 'done'
    else:
        state = 'partial' if counters['done'] or counters['skipped'] else 'failed'
    result = {'state': state, 'elapsed_s': round(time.time() - started, 1),
              'failures': ledger.failures[:200]}
    result.update(counters)
    progress.update(counters)
    progress.update(state=state, updated=time.time())
    _write_progress(log_dir / 'progress.json', progress)
    (log_dir / 'result.json').write_text(json.dumps(result, indent=1) + '\n')
    log(job_log, 'finished: %s done=%d skipped=%d failed=%d stopped=%d bytes=%d in %.1f min'
        % (state, counters['done'], counters['skipped'], counters['failed'],
           counters['stopped'], counters['bytes'], result['elapsed_s'] / 60))
    return result


def main():
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    spec = json.loads(Path(sys.argv[1]).read_text())
    result = run(spec)
    print(json.dumps(result))
    return 0 if result['state'] in ('done', 'partial') else 1


if __name__ == '__main__':
    raise SystemExit(main())

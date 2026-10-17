#!/usr/bin/env python3
"""Per-(destination, medium, pass) locks, and who is in the way.

PLAN §4.3.6: the passes inside one medium are ordered, and two of them running
against the same tree is a correctness bug rather than a performance one. The
photo pass is the proof: it froze 2 049 deletes in one pass and *revoked* them in
a later one, so an OCR pass that started mid-run would have been acting on a
duplicate verdict the run had already taken back.

One lock per (dest, medium, pass) serialises the dangerous pair. The GPU is not
locked here: `.rtx5080.lock` is the encoder's, and §9.4 keeps OCR off the GPU
while it is encoding, so a GPU pass takes both by holding that one itself.
"""
import errno
import fcntl
import json
import os
import time

from core import gate


class Locked(Exception):
    """Another run holds this lock. Carries what the operator needs (§4.1)."""

    def __init__(self, message, holder=None):
        super().__init__(message)
        self.holder = holder or {}
        self.exit_code = gate.EXIT_LOCKED


def path_for(dest, medium, pas):
    return os.path.join(dest, '_mediatool', f'{medium}-{pas}.lock')


def _read_owner(fd):
    """The claim written by whoever holds the lock, read without moving their offset."""
    try:
        return json.loads(os.pread(fd, 4096, 0).decode('utf-8', 'replace') or '{}')
    except (OSError, ValueError):
        return {}


# Locks held by *this process*, keyed by path. flock is per open file description,
# so opening the same lock file twice -- a driver run that shells out to a script
# which takes the same lock -- would deadlock against itself. That is not a
# hypothetical here, and §13 requires it to be tested rather than assumed.
_HELD = {}


class PassLock:
    """Context manager that holds one pass exclusive for this process.

    Re-acquiring the same (dest, medium, pass) *in the same process* is allowed
    and counted, because a driver run that shells out to a script which also
    takes the lock would otherwise block itself forever.
    """

    def __init__(self, dest, medium, pas, run_id):
        self.dest = dest
        self.medium = medium
        self.pas = pas
        self.run_id = run_id
        self.path = path_for(dest, medium, pas)
        self.handle = None
        self.held = 0

    def acquire(self):
        entry = _HELD.get(self.path)
        if entry:
            entry['count'] += 1
            self.handle = entry['fd']
            self.held = entry['count']
            return self
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        # O_CREAT without truncating: an existing file is somebody else's claim
        # and reading it is the whole point.
        descriptor = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno not in (errno.EWOULDBLOCK, errno.EAGAIN, errno.EACCES):
                os.close(descriptor)
                raise
            holder = _read_owner(descriptor)
            os.close(descriptor)
            raise Locked(
                f'refused: {self.medium} {self.pas} is already running against {self.dest} '
                f'(run {holder.get("run_id", "unknown")} since '
                f'{time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(holder.get("started_utc", 0)))} '
                f'by pid {holder.get("pid", "?")}). Wait for it, or cancel it; two runs of one '
                f'pass on one tree is how a freeze gets applied after its own revocation',
                holder)
        payload = json.dumps({'run_id': self.run_id, 'pid': os.getpid(),
                              'dest': self.dest, 'medium': self.medium,
                              'pass': self.pas, 'started_utc': time.time()}) + '\n'
        os.ftruncate(descriptor, 0)
        os.write(descriptor, payload.encode('utf-8'))
        _HELD[self.path] = {'fd': descriptor, 'count': 1}
        self.handle = descriptor
        self.held = 1
        return self

    def release(self):
        if not self.held:
            return
        self.held = 0
        entry = _HELD.get(self.path)
        if entry is None:
            return
        entry['count'] -= 1
        if entry['count'] > 0:
            return                      # the outer acquirer in this process still holds it
        del _HELD[self.path]
        try:
            fcntl.flock(entry['fd'], fcntl.LOCK_UN)
        finally:
            os.close(entry['fd'])
            self.handle = None

    def __enter__(self):
        return self.acquire()

    def __exit__(self, exc_type, exc, tb):
        self.release()
        return False


def status(dest, medium=None):
    """Which passes are held on this destination right now.

    Held here means the flock is *currently* owned: a lock file whose owner died
    is not a live run, so each candidate is probed in a child process and
    discarded. That is how a crashed run avoids blocking the next one forever
    while a live one still blocks it properly.
    """
    directory = os.path.join(dest, '_mediatool')
    found = {}
    if not os.path.isdir(directory):
        return found
    for leaf in sorted(os.listdir(directory)):
        if not leaf.endswith('.lock'):
            continue
        name = leaf[:-len('.lock')]
        if medium and not name.startswith(f'{medium}-'):
            continue
        candidate = os.path.join(directory, leaf)
        holder = {}
        held = False
        try:
            handle = os.open(candidate, os.O_RDWR)
        except OSError:
            continue
        try:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(handle, fcntl.LOCK_UN)
            except OSError:
                held = True
            holder = _read_owner(handle)
        finally:
            os.close(handle)
        found[name] = {'held': held, 'path': candidate,
                       'holder': holder.get('run_id', ''),
                       'pid': holder.get('pid'),
                       'started_utc': holder.get('started_utc')}
    return found

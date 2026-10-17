#!/usr/bin/env python3
"""The ledger: `_mediatool/ledger.sqlite`, the memory that survives a crash.

The schema is PLAN §4.2's, verbatim where it can be. Two rules are load-bearing
and both are enforced here rather than trusted to callers:

* **A `delete` row is not executable until a verified `copy`/`move` row proves
  the content exists elsewhere.** `authorised_delete()` is the only way to get a
  row that `core.fsx.remove()` will act on, and it refuses unless the run is
  applying, the file is claimed as a duplicate, and the surviving copy is
  recorded verified. That is §4.2's "delete only what was verified" as code.
* **Replaying a run is a no-op.** `pending` commits are re-runnable; `done` ones
  are not handed out again, so a resumed run never re-moves a file it already
  moved.

`plan.json` is immutable once written (it is the thing the owner reviewed) and
lives at `<run_id>/plan.json`; the mutable journal is `ops.jsonl`; the ledger
aggregates for querying and is never the only copy. That means a corrupt ledger
costs a re-scan, never a lost fact.
"""
import json
import os
import sqlite3
import time

from core import digest

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
  run_id TEXT PRIMARY KEY,
  domain TEXT NOT NULL, verb TEXT NOT NULL, pass TEXT NOT NULL,
  src TEXT NOT NULL, dest TEXT NOT NULL, opts TEXT NOT NULL,
  started_utc REAL NOT NULL, finished_utc REAL, status TEXT NOT NULL,
  schema_version INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS commits (
  id INTEGER PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES runs(run_id),
  op TEXT NOT NULL,               -- move|copy|delete|rename|tag|write
  src TEXT, dst TEXT,
  src_sha256 TEXT, dst_sha256 TEXT, bytes INTEGER,
  status TEXT NOT NULL,           -- pending|done|failed|reverted
  requested_by TEXT NOT NULL,     -- which module asked for it
  ts REAL NOT NULL, error TEXT
);
CREATE TABLE IF NOT EXISTS freespace (
  run_id TEXT, at_utc REAL, path TEXT, free_bytes INTEGER
);
CREATE TABLE IF NOT EXISTS index_meta (run_id TEXT, artifacts_json TEXT);
CREATE INDEX IF NOT EXISTS commits_run ON commits(run_id, status);
CREATE INDEX IF NOT EXISTS commits_path ON commits(src, dst);
"""


class LedgerError(RuntimeError):
    pass


def now():
    return time.time()


class Ledger:
    """One open connection to a destination's ledger.

    `apply` decides whether a delete row can ever be authorised: a plan-only
    ledger records what *would* happen and can never execute it.
    """

    def __init__(self, dest, apply=False):
        self.dest = os.path.realpath(dest)
        self.directory = os.path.join(self.dest, '_mediatool')
        os.makedirs(self.directory, exist_ok=True)
        self.path = os.path.join(self.directory, 'ledger.sqlite')
        self.apply = bool(apply)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(_SCHEMA)
        self.connection.commit()

    def close(self):
        self.connection.close()

    # -- runs ---------------------------------------------------------------
    def start_run(self, run_id, domain, verb, pass_, src, dest, opts):
        """Insert a run, or return the existing one when the run_id is reused.

        Reuse is the resume path: the same run_id means the same reviewed plan, so
        a second invocation continues instead of starting a competing journal.
        """
        existing = self.connection.execute('SELECT * FROM runs WHERE run_id = ?',
                                           (run_id,)).fetchone()
        if existing is not None:
            return dict(existing)
        self.connection.execute(
            'INSERT INTO runs (run_id, domain, verb, pass, src, dest, opts, started_utc, '
            "status, schema_version) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'running', ?)",
            (run_id, domain, verb, pass_, json.dumps(list(src)), dest, json.dumps(opts),
             now(), SCHEMA_VERSION))
        self.connection.commit()
        return dict(self.connection.execute('SELECT * FROM runs WHERE run_id = ?',
                                           (run_id,)).fetchone())

    def finish_run(self, run_id, status, artifacts=None):
        if status not in ('done', 'aborted', 'failed'):
            raise LedgerError(f'unknown end status {status!r}')
        self.connection.execute('UPDATE runs SET status = ?, finished_utc = ? WHERE run_id = ?',
                                (status, now(), run_id))
        if artifacts is not None:
            self.connection.execute('INSERT INTO index_meta (run_id, artifacts_json) VALUES (?, ?)',
                                    (run_id, json.dumps(artifacts)))
        self.connection.commit()

    def pending_run(self, run_id):
        run = self.connection.execute('SELECT * FROM runs WHERE run_id = ?', (run_id,)).fetchone()
        return dict(run) if run and run['status'] == 'running' else None

    # -- commits -------------------------------------------------------------
    def record(self, run_id, op, *, src=None, dst=None, src_sha256=None, dst_sha256=None,
               bytes=0, status='done', requested_by='core'):
        if op not in ('move', 'copy', 'delete', 'rename', 'tag', 'write'):
            raise LedgerError(f'unknown op {op!r}')
        cursor = self.connection.execute(
            'INSERT INTO commits (run_id, op, src, dst, src_sha256, dst_sha256, bytes, status, '
            'requested_by, ts) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
            (run_id, op, src and os.path.realpath(src), dst and os.path.realpath(dst),
             src_sha256, dst_sha256, int(bytes), status, requested_by, now()))
        self.connection.commit()
        return cursor.lastrowid

    def next_pending(self, run_id):
        row = self.connection.execute(
            "SELECT * FROM commits WHERE run_id = ? AND status = 'pending' ORDER BY id LIMIT 1",
            (run_id,)).fetchone()
        return dict(row) if row else None

    def claim_pending(self, row_id):
        """Move a pending row to `done` atomically; False if someone already did.

        The `WHERE status = 'pending'` guard is the whole race protection: two
        resumptions of one run cannot both act on the same row.
        """
        cursor = self.connection.execute(
            "UPDATE commits SET status = 'done' WHERE id = ? AND status = 'pending'", (row_id,))
        self.connection.commit()
        return cursor.rowcount == 1

    def mark_failed(self, row_id, error):
        self.connection.execute("UPDATE commits SET status = 'failed', error = ? WHERE id = ?",
                                (str(error), row_id))
        self.connection.commit()

    def completed_paths(self, run_id):
        """The `dst` paths this run already finished -- what a resume skips."""
        return {row['dst'] for row in self.connection.execute(
            "SELECT dst FROM commits WHERE run_id = ? AND status = 'done' AND dst IS NOT NULL",
            (run_id,))}

    # -- deletion authority ---------------------------------------------------
    def request_delete(self, run_id, path, *, sha256_value=None, bytes=0,
                       requested_by='core'):
        """Record the *intent* to delete. Intent is inert; only authority executes.

        The row is `pending`, and `authorised_delete` will not hand it out until a
        verified copy of *these exact bytes* is on the ledger -- which is why the
        hash belongs to the request rather than being looked up afterwards. The
        classify pass has already hashed every duplicate candidate, so callers pass
        `sha256_value`; omitting it re-reads the file here, which is correct but
        costs a full read of something that may be 40 GB.

        The human-readable *why* lives in `plan.json`'s rows; the ledger's
        `requested_by` names the phase (`plan:dup-across-sources`), which is what
        makes a row traceable without inventing a column for prose.
        """
        target = os.path.realpath(path)
        if sha256_value is None:
            # Raises if the file is already gone -- and a delete request for a
            # missing file *should* be loud, it means plan and disk disagree.
            sha256_value = digest.sha256(target)
        return self.record(run_id, 'delete', src=target, src_sha256=sha256_value,
                           bytes=bytes or os.path.getsize(target),
                           status='pending', requested_by=requested_by)

    def verify_copy(self, run_id, dst, sha256_value, bytes=0, requested_by='core'):
        """Record that this content is on disk at `dst`, hashed by this run.

        The op is `copy` whether this run *put it there* or *found it there*,
        because what a delete needs as proof is the same either way: a verified
        file holding these bytes at a path that is not the one being deleted.
        `requested_by` says which (`apply:copy` against `observed:already-on-dest`),
        so the row is auditable and never reads as a copy that did not happen.
        """
        return self.record(run_id, 'copy', dst=os.path.realpath(dst), dst_sha256=sha256_value,
                           bytes=bytes, status='done', requested_by=requested_by)

    def find_copy(self, sha256_value):
        """The newest path recorded as verified-holding these bytes, or None.

        Two uses, both about *not copying a file twice*: the overlap report asks
        whether a source's content is already in the destination or the type
        library, and a resumed run asks whether the destination it wrote in a
        previous attempt is still there. Only `copy`/`move` rows count -- a
        `delete` row proves the opposite.
        """
        row = self.connection.execute(
            "SELECT dst, bytes, ts FROM commits WHERE op IN ('copy', 'move') "
            "AND dst_sha256 = ? AND status = 'done' AND dst IS NOT NULL "
            "ORDER BY ts DESC LIMIT 1", (sha256_value,)).fetchone()
        return dict(row) if row else None

    def authorised_delete(self, run_id, path):
        """A delete row `fsx.remove` may act on, or None. See the module docstring."""
        target = os.path.realpath(path)
        row = self.connection.execute(
            "SELECT * FROM commits WHERE run_id = ? AND op = 'delete' AND src = ? "
            "AND status = 'pending' ORDER BY id DESC LIMIT 1", (run_id, target)).fetchone()
        if row is None:
            return None
        if not self.apply:
            return None                       # a plan-only ledger can never authorise
        digest = row['src_sha256']
        if not digest:
            return None                       # nothing to prove the content survives
        survivor = self.connection.execute(
            "SELECT 1 FROM commits WHERE op IN ('copy', 'move') AND dst_sha256 = ? "
            "AND status = 'done' AND dst IS NOT NULL AND dst != ?", (digest, target)).fetchone()
        if survivor is None:
            return None
        return dict(row)

    def mark_delete_done(self, row_id):
        self.connection.execute("UPDATE commits SET status = 'done' WHERE id = ?", (row_id,))
        self.connection.commit()

    def unclaimed_deletes(self, run_id):
        """The §4.2 invariant: every `delete` row must have a surviving copy.

        Anything returned here is a bug or a half-finished run, and it is reported
        at the end of every run rather than assumed away.
        """
        rows = self.connection.execute(
            "SELECT c.id, c.src, c.src_sha256 FROM commits c WHERE c.run_id = ? "
            "AND c.op = 'delete' AND NOT EXISTS (SELECT 1 FROM commits v WHERE v.op IN "
            "('copy', 'move') AND v.status = 'done' AND v.dst_sha256 = c.src_sha256 "
            "AND v.dst IS NOT NULL AND v.dst != c.src)", (run_id,)).fetchall()
        return [dict(row) for row in rows]

    # -- free space ----------------------------------------------------------
    def free(self, run_id, path):
        import shutil
        try:
            free = shutil.disk_usage(path).free
        except OSError:
            return None
        self.connection.execute('INSERT INTO freespace (run_id, at_utc, path, free_bytes) '
                                'VALUES (?, ?, ?, ?)', (run_id, now(), path, free))
        self.connection.commit()
        return free

    # -- queries -------------------------------------------------------------
    def counts(self, run_id):
        rows = self.connection.execute(
            'SELECT op, status, COUNT(*) AS n, COALESCE(SUM(bytes), 0) AS bytes FROM commits '
            'WHERE run_id = ? GROUP BY op, status', (run_id,)).fetchall()
        return [dict(row) for row in rows]

    def last_run(self):
        row = self.connection.execute('SELECT * FROM runs ORDER BY started_utc DESC LIMIT 1').fetchone()
        return dict(row) if row else None

    def runs(self):
        return [dict(row) for row in self.connection.execute(
            'SELECT * FROM runs ORDER BY started_utc')]

    def run_row(self, run_id):
        row = self.connection.execute('SELECT * FROM runs WHERE run_id = ?', (run_id,)).fetchone()
        return dict(row) if row else None


def write_plan(run_dir, payload):
    """`plan.json`, written once and never rewritten -- the owner reviewed it.

    An existing plan file is a fact about a reviewed run. Overwriting it would let
    a second invocation silently change what the first one promised, which is the
    failure §17.11 exists to prevent. `--force-plan-new` makes a new run_id instead
    of editing this one, and that decision belongs to the caller.
    """
    path = os.path.join(run_dir, 'plan.json')
    if os.path.exists(path):
        with open(path, encoding='utf-8') as handle:
            return json.load(handle)
    _write_json(path, payload)
    return payload


def _write_json(path, payload):
    staging = path + '.tmp'
    with open(staging, 'w', encoding='utf-8') as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(staging, path)


def write_json(path, payload):
    """Public wrapper for the sidecars that are *meant* to be rewritten."""
    _write_json(path, payload)

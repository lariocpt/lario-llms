#!/usr/bin/env python3
"""Deleting anything needs a human who meant it. Twice.

The rule this enforces is stronger than the ledger's and it exists for one
reason: these are somebody's only backups. `fsx.remove` already refuses without
a ledger row proving the bytes survive elsewhere, but that proof is a machine
judgement, and a machine judgement that is wrong on 40 000 files is a disaster
with good documentation. So nothing deletes during a run at all:

* a run **stages** candidates in `deletes.json` and stops;
* `media/run.py purge --run <id>` is the only thing that deletes, and it asks
  twice -- first for the word `DELETE`, then for the byte count, retyped, so the
  number in front of the person doing it is the number they approved;
* with no terminal to ask in, purge **refuses**. A background job, an MCP call or
  a cron entry cannot delete a source, and there is deliberately no `--yes`.

A wrong `merge` is a file in the wrong folder. A wrong delete is a file that is
gone. They are not the same kind of operation and they are not gated the same way.
"""
import json
import os
import sys
import time

from core import gate, ledger

# What has to be typed, in order. Kept as data so a test can drive it and a
# reviewer can see the whole gate without reading control flow.
PHRASE = 'DELETE'


class NotConfirmed(gate.Refusal):
    """The human did not confirm, or could not be asked. Nothing was deleted."""

    def __init__(self, message):
        super().__init__(message, gate.EXIT_REFUSE)


def stage_path(run_dir):
    return os.path.join(run_dir, 'deletes.json')


def stage(run_dir, rows, summary=None):
    """Write the candidates a run decided on. This file deletes nothing.

    Every row carries *why* it is a candidate and where its bytes also live, so
    the person being asked at purge time is asked about something they can check.
    """
    path = stage_path(run_dir)
    payload = {
        'run_id': (summary or {}).get('run_id'),
        'written_utc': time.time(),
        'note': ('STAGED ONLY -- nothing here has been deleted. Review, then run '
                 '"python3 media/run.py purge --run <run_id>" yourself.'),
        'total_bytes': sum(int(row.get('bytes', 0)) for row in rows),
        'total_files': len(rows),
        'candidates': rows,
    }
    ledger.write_json(path, payload)
    return path, payload


def read_stage(run_dir):
    path = stage_path(run_dir)
    if not os.path.exists(path):
        raise NotConfirmed(f'refused: no staged deletes at {path}. Run a merge first')
    with open(path, encoding='utf-8') as handle:
        return json.load(handle)


def _ask(output, input_fn, question):
    output(question, flush=True)
    answer = input_fn()
    if answer is None:
        raise NotConfirmed('aborted: no answer')
    return answer.strip()


def confirm(count_files, count_bytes, dest, run_id, output=None, input_fn=None,
            lines=None):
    """Two typed confirmations, or `NotConfirmed`. There is no way to skip this.

    `lines` is whatever the caller wants shown first -- usually the list of files
    and, for each one, the path that proves its bytes survive elsewhere. The two
    prompts are the last word: the first says "I understand this is permanent",
    the second makes the person retype the byte total, which is the only
    mechanism here that catches "I thought this run deleted 3 GB, not 300".
    """
    output = output or (lambda text, **kw: print(text))
    input_fn = input_fn or (lambda: input())
    shown = f'{count_bytes / 1e9:,.3f} GB ({count_bytes:,} bytes)'

    output('')
    output('=' * 72)
    output(f'  PERMANENT DELETION -- {count_files:,} files, {shown}')
    output(f'  destination: {dest}')
    output(f'  run:         {run_id}')
    output('=' * 72)
    for line in (lines or []):
        output(f'  {line}')
    output('')
    output('  Every file listed has a verified copy elsewhere, and that copy was')
    output('  re-hashed. Anything not listed is not being deleted.')
    output('')

    first = _ask(output, input_fn, f'  Type {PHRASE} to continue (anything else stops now): ')
    if first != PHRASE:
        raise NotConfirmed(f'stopped: typed {first!r}, not {PHRASE}. Nothing was deleted')

    second = _ask(output, input_fn,
                  f'  Now type the exact byte total to confirm: {count_bytes} bytes: ')
    expected = str(int(count_bytes))
    if second.replace(' ', '').replace('_', '') != expected:
        raise NotConfirmed(
            f'stopped: typed {second!r}, the total is {expected}. Nothing was deleted')

    output('')
    output('  Confirmed twice. Proceeding.')
    output('')
    return True


def require_tty(stream=None):
    """Refuse to delete when nobody could answer, even if a caller feels confident.

    The prompt is the safety device. If it cannot be shown, the operation is not
    the one that was asked for -- so this is a refusal with the exact command to
    run at a keyboard, not a warning.
    """
    stream = stream if stream is not None else sys.stdin
    if not getattr(stream, 'isatty', lambda: False)():
        raise NotConfirmed(
            'refused: deleting source files needs an interactive terminal so the two '
            'confirmations can actually be answered. Run this yourself at a keyboard:\n'
            '    python3 media/run.py purge --run <run_id>')

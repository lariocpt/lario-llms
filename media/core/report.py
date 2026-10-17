#!/usr/bin/env python3
"""The run's report: one text summary, three machine-readable sidecars.

The accounting rule is §4.5 and it is the reason this module exists separately:
**reclaimed bytes and relocated bytes are never added together.** In the 2026
photo pass, 1 694 of 3 323 GB were duplicates and the rest was *filing* -- the
bytes still occupied the same array. A single "space saved" figure would have
claimed a saving that did not happen, and the owner would have bought a smaller
drive than the library needs.

So every number here is one of exactly two kinds, and where a file is both -- a
cross-device duplicate degrades to a copy (§17.5) -- it counts as **relocated**,
never reclaimed. "It moved" is the true statement; "it saved space" is not.
"""
import os
import time

from core import digest, gate, names, ledger

# §3.2.5. A source file is in exactly one bucket, decided in this order, and the
# buckets are reported as bytes *and* file counts: "120 GB already on dest" makes
# a different impression than the 40 000 files that actually are, and both numbers
# have to be shown for the first one to be believable.
OVERLAP_BUCKETS = ('already_on_dest', 'already_in_library', 'dup_across_sources', 'net_new')


def human(nbytes):
    """Bytes as a person reads them, decimal, because that is how a drive is sold."""
    value = float(nbytes)
    for unit in ('B', 'KB', 'MB', 'GB', 'TB', 'PB'):
        if abs(value) < 1000.0 or unit == 'PB':
            return f'{value:3.1f} {unit}' if unit != 'B' else f'{int(value)} B'
        value /= 1000.0
    return f'{value:.1f} PB'


def new_overlap():
    """Zeroed §3.2.5 buckets. Reported at *plan* time, before anything is written."""
    return {bucket: {'files': 0, 'bytes': 0} for bucket in OVERLAP_BUCKETS}


def add_overlap(overlap, bucket, size=0):
    """Count one source file in a bucket. Unknown buckets are a bug, so loud."""
    if bucket not in overlap:
        raise KeyError(f'not an overlap bucket: {bucket!r} (have {", ".join(OVERLAP_BUCKETS)})')
    overlap[bucket]['files'] += 1
    overlap[bucket]['bytes'] += int(size)


def classify(overlap, size, scopes, keep=True):
    """Decide one source file's bucket from where its content was already found.

    `scopes` is whatever else already holds these bytes: `'dest'`, `'library'`, or
    the name of another `--src`. Precedence is deliberate -- content that is
    already on the destination needs no copy *and* no delete, so it must not be
    counted as a duplicate whose survivor we are choosing -- and `keep` says whether
    this particular path still needs writing (the first member of a group does;
    the rest do not).
    """
    if 'dest' in scopes:
        add_overlap(overlap, 'already_on_dest', size)
    elif 'library' in scopes:
        add_overlap(overlap, 'already_in_library', size)
    elif not keep:
        add_overlap(overlap, 'dup_across_sources', size)
    else:
        add_overlap(overlap, 'net_new', size)


def new_summary(medium, verb, run_id, srcs, dest, run_dir, opts=None):
    return {
        'run_id': run_id, 'medium': medium, 'verb': verb,
        'pass': 'structure', 'phase': 'plan',
        'src': list(srcs), 'dest': dest, 'run_dir': run_dir,
        'opts': dict(opts or {}),
        'applied': False,
        'scanned_files': 0, 'scanned_bytes': 0,
        'actions': {},                    # action -> {'files': n, 'bytes': b}
        'bytes_reclaimed': 0,
        'bytes_relocated': 0,
        'overlap': new_overlap(),
        'foreign': [],                    # {'path', 'owner', 'command'}  (§1.3)
        'clutter': {'files': 0, 'bytes': 0},
        'unreadable': [],                 # {'path', 'error'}
        'refusal_reasons': [],
        'duplicates': {'groups': 0, 'files': 0, 'bytes': 0},
        'collisions': [],
        'docs': None,
        'free_before': None, 'free_after': None,
        'fstype': None, 'case_folding': False,
        'started_utc': time.time(), 'finished_utc': None,
        'status': 'running',
        'report_path': os.path.join(run_dir, 'summary.txt'),
    }


def bump(summary, action, size=0):
    """Record that an action ran, with the bytes it actually moved.

    `actions` answers "what did this run DO"; reclaimed/relocated answer "what
    happened to space". A verify is an action and reclaims nothing, and conflating
    the two is how a verification pass reports a rescue it did not perform.
    """
    slot = summary['actions'].setdefault(action, {'files': 0, 'bytes': 0})
    slot['files'] += 1
    slot['bytes'] += int(size)


def add_foreign(summary, path, owner):
    """§1.3: report a foreign file *with the owning command*, and move nothing.

    The suggested destination is the volume this run is actually writing whenever
    that is not a medium's own library: someone building a handover drive needs
    the command that finishes *that drive*, and a line pointing at the library on
    the array would silently split the same photos across two places.
    """
    dest = summary.get('dest')
    library = _dest_word(summary.get('medium'))
    same_as_library = library != '<dest>' and dest and \
        os.path.realpath(dest) == os.path.realpath(library)
    target = dest if not same_as_library else _dest_word(owner)
    command = f'media/run.py {owner} merge --src "{os.path.dirname(path)}" --dest {target}'
    summary['foreign'].append({'path': path, 'owner': owner, 'command': command})


def _dest_word(owner):
    try:
        return gate.dest_for(owner)
    except gate.Refusal:
        return '<dest>'


def refused(summary, reason):
    summary['refusal_reasons'].append(reason)


def free_space(summary):
    """§4.5: destination free space, before and after, always both."""
    if summary['free_before'] is None:
        summary['free_before'] = gate.free_bytes(summary['dest'])
    summary['free_after'] = gate.free_bytes(summary['dest'])


def _lines(summary):
    out = []
    out.append(f'# media {summary["medium"]} {summary["verb"]} -- run {summary["run_id"]}')
    out.append('')
    out.append(f'sources   : ' + ('\n            ' if len(summary['src']) > 1 else '')
               + '\n            '.join(summary['src']))
    out.append(f'destination: {summary["dest"]}  ({summary["fstype"] or "?"}'
               + (', case-folding' if summary['case_folding'] else '') + ')')
    out.append(f'phase      : {summary["phase"]}  |  status: {summary["status"]}'
               + ('  |  APPLIED' if summary['applied'] else '  (plan only, nothing written)'))
    out.append('')
    out.append(f'scanned    : {summary["scanned_files"]} files, {human(summary["scanned_bytes"])}')
    if summary['actions']:
        out.append('')
        out.append('actions:')
        for action in sorted(summary['actions']):
            slot = summary['actions'][action]
            out.append(f'  {action:<26} {slot["files"]:>7} files   {human(slot["bytes"]):>11}')
    if summary['duplicates']['groups']:
        dup = summary['duplicates']
        out.append('')
        out.append(f'duplicates : {dup["groups"]} groups, {dup["files"]} files, '
                   f'{human(dup["bytes"])} of them redundant')
    out.append('')
    out.append(f'  bytes reclaimed : {human(summary["bytes_reclaimed"])}   (removed -- they were duplicates)')
    out.append(f'  bytes relocated : {human(summary["bytes_relocated"])}   (moved -- the array is no bigger)')
    out.append('                 ^ the two are never added together (§4.5)')
    out.append('')
    out.append('overlap with what is already there (§3.2.5):')
    for bucket in OVERLAP_BUCKETS:
        slot = summary['overlap'][bucket]
        out.append(f'  {bucket:<20} {slot["files"]:>8} files   {human(slot["bytes"]):>11}')
    if summary['free_before'] is not None:
        after = summary['free_after'] if summary['free_after'] is not None else summary['free_before']
        delta = after - summary['free_before']
        out.append('')
        out.append(f'destination free: {human(summary["free_before"])} -> {human(after)} '
                   f'({human(abs(delta))} {"used" if delta < 0 else "gained"})')
    if summary['foreign']:
        out.append('')
        out.append(f'foreign files (left exactly where they are, §1.3): {len(summary["foreign"])}')
        by_owner = {}
        for row in summary['foreign'][:400]:
            by_owner.setdefault(row['owner'], []).append(row)
        for owner in sorted(by_owner):
            out.append(f'  {owner}: {len(by_owner[owner])} files, e.g. '
                       f'{by_owner[owner][0]["path"]}')
            out.append(f'    run: {by_owner[owner][0]["command"]}')
        if len(summary['foreign']) > 400:
            out.append(f'  ... all {len(summary["foreign"])} listed in foreign-files.json')
    if summary['clutter']['files']:
        out.append(f'\nskipped, not counted anywhere: {summary["clutter"]["files"]} clutter files '
                   f'({human(summary["clutter"]["bytes"])})')
    if summary['collisions']:
        out.append(f'\nname collisions renamed: {len(summary["collisions"])}')
        for row in summary['collisions'][:20]:
            out.append(f'  {row["from"]} -> {row["to"]}')
    if summary['docs'] is not None:
        out.append('\ndocs pass: ' + ', '.join(f'{k}={v}' for k, v in sorted(summary['docs'].items())
                                               if not isinstance(v, (dict, list))))
    if summary['unreadable']:
        out.append(f'\ncould not read: {len(summary["unreadable"])}')
        for row in summary['unreadable'][:10]:
            out.append(f'  {row["path"]}: {row["error"]}')
    if summary['refusal_reasons']:
        out.append('\nrefusals:')
        for reason in summary['refusal_reasons']:
            out.append(f'  {reason}')
    return '\n'.join(out) + '\n'


def render(summary):
    """The human summary (§4.3.2). Plain text, so a log line and a terminal agree."""
    return _lines(summary)


def write(summary):
    """`summary.txt` + `summary.json` + `free_space.json` (§4.3.2 and §4.5).

    The sidecars are what a later run reads; the text is what the owner reads.
    `plan.json` itself is written by `ledger.write_plan` and is never rewritten --
    these three are reports *about* the run, not the thing the run promised.
    """
    run_dir = summary['run_dir']
    os.makedirs(run_dir, exist_ok=True)
    text = render(summary)
    summary['report_path'] = os.path.join(run_dir, 'summary.txt')
    for name in ('summary.txt', 'summary.json', 'free_space.json'):
        path = os.path.join(run_dir, name)
        if name == 'summary.txt':
            payload = text
        elif name == 'free_space.json':
            payload = {'dest': summary['dest'], 'fstype': summary['fstype'],
                       'before_bytes': summary['free_before'],
                       'after_bytes': summary['free_after'],
                       'reclaimed_bytes': summary['bytes_reclaimed'],
                       'relocated_bytes': summary['bytes_relocated']}
        else:
            payload = summary
        if isinstance(payload, str):
            staging = path + '.tmp'
            with open(staging, 'w', encoding='utf-8') as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(staging, path)
        else:
            ledger.write_json(path, payload)
    return text


def foreign_json(summary):
    """`foreign-files.json` (§4.3.2) -- the full list, not the report's first 400."""
    path = os.path.join(summary['run_dir'], 'foreign-files.json')
    ledger.write_json(path, {'run_id': summary['run_id'], 'files': summary['foreign'],
                             'note': 'moved by nothing; the command field is the owning task'})
    return path


def digest_cache(medium):
    """A digest cache is only worth having for a medium that dedupes. Everything
    does, so this is really a shared one keyed by the destination by the caller."""
    return digest.Duplicates


def sanity(summary):
    """Assertions that outlive the tests (§13.7): run before the summary is shown.

    These are the invariants a refactor breaks first. A reclaimed/relocated total
    is the specific way this toolkit lies about space, and a name that is not
    exFAT-representable is the way it produces a file the owner cannot open on a
    Mac, so both are refused here even though the code above should make them
    impossible.
    """
    problems = []
    if summary['bytes_reclaimed'] < 0 or summary['bytes_relocated'] < 0:
        problems.append('negative byte total -- an action double-counted')
    for row in summary.get('planned_names', []):
        leaf = os.path.basename(row.get('dst', ''))
        if leaf and names.exfat_problems(leaf):
            problems.append(f'planned name not exFAT-representable: {leaf} '
                            f'({"; ".join(names.exfat_problems(leaf))})')
    return problems

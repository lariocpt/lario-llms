#!/usr/bin/env python3
"""The media toolkit's only path-taking surface.

    python3 media/run.py movies  merge --src /mnt/a --src /mnt/b
    python3 media/run.py photos  merge --src /mnt/a --dest /mnt/drive --apply
    python3 media/run.py movies  verify --dest /mnt/drive --run <run_id>
    python3 media/run.py photos  status --dest /mnt/drive
    python3 media/run.py photos  purge  --dest /mnt/drive --run <run_id>

One task is one medium: N sources in, one destination out, and a task never
writes another medium's tree. A foreign file (a photo in a movie run) is
**reported with the command that owns it** and left exactly where it is (§1.3).

**Nothing here deletes.** A merge stages delete *candidates* in `deletes.json`
and stops; `purge` is the only verb that removes a file, and it requires two
typed confirmations at a keyboard and re-hashes the surviving copy first. There
is no `--delete-sources`, no `--yes`, and no code path from `merge` to `remove`.
The reason is in `core/confirm.py`: these are somebody's only backups, and a
wrong merge is a file in the wrong folder while a wrong delete is a file that is
gone.

Domain corpora are invoked as commands with argv, never imported (§4.4): 77 of
the 93 modules below call `SystemExit` at import time, and a driver that
imported them could not even load.
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import config, confirm, digest, fsx, gate, ledger, lock, names, report

TOOL_VERSION = '1.0'
FLOOR_GB = 50.0                       # §3.2.1: never fill a destination


class Engine:
    """One run against one destination: classify, plan, and optionally copy."""

    def __init__(self, medium, verb, srcs, dest, run_id, opts):
        self.medium = medium
        self.verb = verb
        self.srcs = srcs
        self.dest = dest
        self.run_id = run_id
        self.opts = opts
        self.run_dir = gate.evidence_dir(dest, run_id)
        self.apply = bool(opts.get('apply'))
        self.ledger = ledger.Ledger(dest, apply=self.apply)
        self.summary = report.new_summary(medium, verb, run_id, srcs, dest, self.run_dir,
                                          {k: v for k, v in opts.items() if k != 'apply'})

    # -- walk ---------------------------------------------------------------
    def scan(self):
        """Every file in every source, split into ours / foreign / clutter.

        Symlinks are skipped rather than followed, and a file that cannot be
        stated is reported rather than dropped: a silent skip is how a 40 000-file
        pass ends up shipping 39 000.
        """
        found = []
        for src in self.srcs:
            for dirpath, dirnames, filenames in os.walk(src, followlinks=False):
                keep = []
                for leaf in dirnames:
                    path = os.path.join(dirpath, leaf)
                    if names.is_clutter(path) or leaf == '_mediatool':
                        continue
                    if os.path.islink(path):
                        self.summary['unreadable'].append(
                            {'path': path, 'error': 'symlinked directory, not followed'})
                        continue
                    keep.append(leaf)
                dirnames[:] = sorted(keep)
                for leaf in sorted(filenames):
                    path = os.path.join(dirpath, leaf)
                    if names.is_clutter(path):
                        try:
                            self.summary['clutter']['files'] += 1
                            self.summary['clutter']['bytes'] += os.path.getsize(path)
                        except OSError:
                            pass
                        continue
                    if os.path.islink(path):
                        self.summary['unreadable'].append(
                            {'path': path, 'error': 'symlink, not a file we own'})
                        continue
                    try:
                        size = os.path.getsize(path)
                    except OSError as exc:
                        self.summary['unreadable'].append({'path': path,
                                                           'error': gate.ensure_EROFS(exc)})
                        continue
                    if not gate.is_media(path, self.medium):
                        owner = gate.foreign(path, self.medium)
                        if owner:
                            report.add_foreign(self.summary, path, owner)
                        continue
                    found.append({'path': path, 'size': size,
                                  'rel': os.path.relpath(path, src)})
        self.summary['scanned_files'] = len(found)
        self.summary['scanned_bytes'] = sum(row['size'] for row in found)
        return found

    # -- overlap ------------------------------------------------------------
    def overlap(self, found):
        """Where each source file's content already lives, cheapest probe first.

        One `Duplicates` index over sources ∪ destination ∪ library, so the
        escalation inside `digest` does the cost control: a file whose size
        matches nothing is settled without being read at all. Hashing the library
        up front instead would cost hours on a 5 TB tree to learn what size
        matching already knows for free.
        """
        dup = digest.Duplicates(os.path.join(self.run_dir, 'digest-cache.json'))
        layout_root = self.layout_root()
        for row in found:
            dup.add(row['path'], row['size'])
        existing = []
        for root, label in ((layout_root, 'dest'), (self.library_root(), 'library')):
            if not root or not os.path.isdir(root):
                continue
            for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
                dirnames[:] = [leaf for leaf in sorted(dirnames)
                               if not names.is_clutter(os.path.join(dirpath, leaf))
                               and leaf != '_mediatool']
                for leaf in sorted(filenames):
                    path = os.path.join(dirpath, leaf)
                    if os.path.islink(path) or not gate.is_media(path, self.medium):
                        continue
                    try:
                        size = os.path.getsize(path)
                    except OSError:
                        continue
                    existing.append({'path': path, 'scope': label, 'size': size})
        for row in existing:
            dup.add(row['path'], row['size'])

        scopes = {row['path']: row['scope'] for row in existing}
        source_paths = {row['path'] for row in found}
        by_path = {}
        for group in dup.groups():
            for path in group['paths']:
                by_path[path] = group['paths']

        survivors = {}
        for row in found:
            group = by_path.get(row['path'], [row['path']])
            others = [other for other in group if other != row['path']]
            row['scopes'] = sorted({scopes.get(other) for other in others} - {None})
            row['peers'] = [other for other in others if other in source_paths
                            and other != row['path']]
            survivor = sorted(group)[0]
            row['survivor'] = survivor
            survivors[row['path']] = survivor
        return found

    # -- layout -------------------------------------------------------------
    def library_root(self):
        """The medium's live library, when this run is not pointed at it already."""
        try:
            root = gate.dest_for(self.medium)
        except gate.Refusal:
            return None
        return None if os.path.realpath(root) == os.path.realpath(self.dest) else root

    def layout_root(self):
        """Where files land under --dest, decided once and recorded in the plan.

        Pointing at the medium's own library means its existing shape is the
        shape, so paths are preserved under it. Pointing at anything else -- a
        handover drive -- puts each medium in its own subtree, because a drive
        that has been half-processed still has to be legible (§15.3).
        """
        configured = None
        try:
            configured = gate.dest_for(self.medium)
        except gate.Refusal:
            pass
        if configured and os.path.realpath(configured) == os.path.realpath(self.dest):
            return self.dest
        return gate.plan_dest_dir(self.dest, self.medium)

    def plan(self, found):
        """The rows: what would be written where, and what is already there.

        A name clash never skips a file. Two sources holding different content
        that arrive at the same relative path are two different files, and the
        only honest outcomes are a renamed second copy or a loud failure -- the
        2026 pass's `names.json` exists because silently dropping the second one
        is how content disappears from a consolidation run.
        """
        claimed = {}
        rows = []
        for row in sorted(found, key=lambda item: item['path']):
            if 'scopes' not in row:
                continue
            if 'dest' in row['scopes']:
                report.classify(self.summary['overlap'], row['size'], ['dest'])
                rows.append({**row, 'action': 'already_on_dest', 'dst': None})
                continue
            if 'library' in row['scopes']:
                report.classify(self.summary['overlap'], row['size'], ['library'])
                rows.append({**row, 'action': 'already_in_library', 'dst': None})
                continue
            keep = (row['survivor'] == row['path'])
            if not keep:
                report.classify(self.summary['overlap'], row['size'], [], keep=False)
                rows.append({**row, 'action': 'duplicate_of',
                             'dst': None,
                             'peer': sorted(p for p in row['peers'])[0] if row['peers'] else None})
                continue
            target_dir = os.path.join(self.layout_root(), os.path.dirname(row['rel']))
            seen = claimed.setdefault(target_dir, self._claimed_names(target_dir))
            name = names.unique(seen, os.path.basename(row['path']))
            dst = os.path.join(target_dir, name)
            if name != os.path.basename(row['path']):
                self.summary['collisions'].append(
                    {'from': row['path'], 'to': dst})
            report.classify(self.summary['overlap'], row['size'], [], keep=True)
            rows.append({**row, 'action': 'copy', 'dst': dst})
        groups = {}
        for row in rows:
            if row['action'] == 'duplicate_of' and row['survivor']:
                groups.setdefault(row['survivor'], []).append(row['path'])
        self.summary['duplicates'] = {
            'groups': len(groups),
            'files': sum(len(members) for members in groups.values()),
            'bytes': sum(row['size'] for row in rows if row['action'] == 'duplicate_of'),
        }
        return rows

    def _claimed_names(self, target_dir):
        """Names already used in that directory -- on disk and by this run.

        Seeding from the destination is what stops a copy overwriting a file the
        owner already had there. `names.unique` folds case, so `Foo.jpg` on an
        exFAT volume claims `foo.jpg` too, which is the collision that loses a
        file silently rather than loudly.
        """
        seen = {}
        if os.path.isdir(target_dir):
            for leaf in os.listdir(target_dir):
                if leaf.startswith(fsx.TMP_PREFIX):
                    continue
                seen.setdefault(names.key(leaf), leaf)
        return seen

    # -- staging deletes (never deleting) ------------------------------------
    def stage_deletes(self, rows):
        """Write the *suggestion*. This function cannot delete anything.

        Each candidate names the file that proves its bytes survive, so the person
        who later runs `purge` is asked about something they can check -- and
        `purge` re-verifies every one of them anyway.

        Proof of survival is the copy that *will exist after this run*: for a
        duplicate, the survivor's destination path, not another source path that
        a later pass might itself move. That is why this runs after the copies.
        Hashes are only computed when applying -- a dry run that read every
        candidate twice would cost more than the scan it is reporting on, and
        `purge` re-hashes both sides regardless.
        """
        placed = {row['path']: row.get('dst') for row in rows if row['action'] == 'copy'}
        candidates = []
        for row in rows:
            if row['action'] not in ('duplicate_of', 'already_on_dest', 'already_in_library'):
                continue
            survivor = row.get('survivor')
            if not survivor:
                continue
            proof = placed.get(survivor) or survivor
            candidates.append({'path': row['path'], 'bytes': row['size'],
                               'sha256': row.get('sha256'), 'survivor': proof,
                               'why': {'duplicate_of': 'duplicate of another source file, '
                                                       'whose copy lands at the survivor path',
                                       'already_on_dest': 'these bytes are already on the '
                                                          'destination',
                                       'already_in_library': 'these bytes are already in the '
                                                             'library'}[row['action']]})
        path, payload = confirm.stage(self.run_dir, candidates, self.summary)
        self.summary['staged_deletes'] = {'files': payload['total_files'],
                                          'bytes': payload['total_bytes'],
                                          'path': path}
        return path

    def authorise_staged(self):
        """Give `purge` something to verify against. Creates rows, deletes nothing.

        Both sides are hashed here and must match *now*: if the source and its
        supposed survivor differ by the time we get here, no row is written and
        `purge` will refuse that file rather than trust a plan written earlier.
        """
        stage = confirm.read_stage(self.run_dir)
        proven = 0
        for candidate in stage['candidates']:
            path, proof = candidate['path'], candidate['survivor']
            if not (os.path.exists(path) and os.path.exists(proof)):
                continue
            try:
                source_sha = digest.sha256(path)
                proof_sha = digest.sha256(proof)
            except OSError:
                continue
            if source_sha != proof_sha:
                continue
            self.ledger.verify_copy(self.run_id, proof, proof_sha,
                                    os.path.getsize(proof), requested_by='observed:survivor')
            self.ledger.request_delete(self.run_id, path, sha256_value=source_sha,
                                       bytes=candidate['bytes'], requested_by='plan:staged')
            candidate['sha256'] = source_sha
            proven += 1
        if proven != len(stage['candidates']):
            skipped = len(stage['candidates']) - proven
            report.refused(self.summary,
                           f'{skipped} staged candidate(s) could not be proven to survive and '
                           f'will be refused at purge time')
        confirm.stage(self.run_dir, stage['candidates'], self.summary)
        return proven

    # -- apply --------------------------------------------------------------
    def apply_plan(self, rows):
        """Copy. Verify. Record. Nothing in this function can remove a source."""
        done = self.ledger.completed_paths(self.run_id)
        for row in rows:
            if row['action'] != 'copy':
                if row.get('sha256') and row['action'] == 'already_on_dest':
                    # A verified copy already on the destination is recorded as
                    # such: it is the proof a later purge needs, and it says
                    # plainly that this run found it rather than wrote it.
                    self.ledger.verify_copy(self.run_id, row['survivor'], row['sha256'],
                                            row['size'], requested_by='observed:already-on-dest')
                continue
            if row['dst'] in done:
                report.bump(self.summary, 'resume-skip', row['size'])
                continue
            try:
                receipt = fsx.copy_file(row['path'], row['dst'],
                                        reflink=fsx.same_device(row['path'], row['dst']),
                                        verify=True)
            except OSError as exc:
                self.summary['unreadable'].append({'path': row['path'],
                                                   'error': gate.ensure_EROFS(exc)})
                report.bump(self.summary, 'copy-failed', row['size'])
                continue
            row['sha256'] = receipt['sha256']
            # A copy is *relocated* bytes, never reclaimed: the array holds the
            # same content it did plus this copy (§4.5). The one exception is a
            # reflink, which shares extents and so genuinely costs nothing -- and
            # the method is what says so, not whether the two paths share a
            # device, which is true of any ordinary copy onto the same disk.
            if receipt['method'] != 'reflink':
                self.summary['bytes_relocated'] += receipt['bytes']
            report.bump(self.summary, f'copy-{receipt["method"]}', receipt['bytes'])
            self.ledger.verify_copy(self.run_id, row['dst'], receipt['sha256'],
                                    receipt['bytes'], requested_by='apply:copy')

    # -- verify -------------------------------------------------------------
    def verify(self, rows):
        """§4.3.5: every planned destination exists and hashes to what was written."""
        bad = []
        for row in rows:
            if row['action'] != 'copy' or not row.get('dst'):
                continue
            if not os.path.exists(row['dst']):
                bad.append({'path': row['dst'], 'error': 'missing'})
                continue
            if os.path.getsize(row['dst']) != row['size']:
                bad.append({'path': row['dst'], 'error': 'size differs'})
                continue
            if row.get('sha256') and digest.sha256(row['dst']) != row['sha256']:
                bad.append({'path': row['dst'], 'error': 'hash differs'})
                continue
            report.bump(self.summary, 'verify', row['size'])
        for row in bad:
            self.summary['unreadable'].append(row)
        return not bad

    # -- run ----------------------------------------------------------------
    def execute(self):
        probe = gate.probe_writable(self.dest, self.run_dir)
        self.summary['fstype'] = probe['fstype']
        self.summary['case_folding'] = probe['case_folding']
        report.free_space(self.summary)

        found = self.scan()
        if not found:
            report.refused(self.summary, 'no files of this medium in any --src; nothing to do')
        self.overlap(found)
        rows = self.plan(found)

        staged = self.stage_deletes(rows)
        needed = sum(row['size'] for row in rows if row['action'] == 'copy')
        self.summary['predicted_growth'] = needed
        if self.apply:
            gate.check_floor(self.dest, needed,
                             int(self.opts.get('free_floor_gb', FLOOR_GB) * 1e9))
            self.summary['phase'] = 'apply'
            self.summary['applied'] = True
            self.apply_plan(rows)
            # Only after the copies: a delete candidate is only proven by a file
            # that exists at this moment, and the copies are what create it.
            self.authorise_staged()
            if not self.verify(rows):
                self.summary['status'] = 'failed'
        else:
            self.summary['phase'] = 'plan'

        plan_rows = [{'src': row['path'], 'dst': row.get('dst'), 'action': row['action'],
                      'bytes': row['size'], 'sha256': row.get('sha256'),
                      'survivor': row.get('survivor')} for row in rows]
        payload = {k: v for k, v in self.summary.items() if k not in ('actions',)}
        payload['rows'] = plan_rows
        ledger.write_plan(self.run_dir, payload)
        report.foreign_json(self.summary)
        self.summary['finished_utc'] = time.time()
        if self.summary['status'] == 'running':
            self.summary['status'] = 'done'
        self.ledger.finish_run(self.run_id, 'done' if self.summary['status'] == 'done'
                               else 'failed',
                               {'plan': os.path.join(self.run_dir, 'plan.json'),
                                'summary': self.summary['report_path'],
                                'deletes': staged})
        text = report.write(self.summary)
        problems = report.sanity(self.summary)
        for problem in problems:
            print(f'INVARIANT: {problem}', file=sys.stderr)
        return 0 if not problems else gate.EXIT_CRASH, text


class _OneDest(argparse.Action):
    """A second --dest is a refusal, not argparse's quiet last-one-wins.

    The default behaviour here is the dangerous one: `--dest /a --dest /b` picks
    `/b` without comment and files 400 GB of somebody's photos into the wrong
    volume. The thing that parses the argument is the right place to say no, and
    §13.1 makes it a test rather than a preference.
    """

    def __call__(self, parser, namespace, value, option_string=None):
        previous = getattr(namespace, self.dest, None)
        if previous is not None:
            raise gate.Refusal(
                f'refused: --dest given twice ({previous} and {value}). One task writes one '
                f'destination (§3.2); run them one after the other')
        setattr(namespace, self.dest, value)


def build_parser():
    parser = argparse.ArgumentParser(
        prog='media/run.py',
        description='One medium, N sources in, ONE destination out. A merge never deletes.',
        epilog='Nothing in a merge deletes. Deletion is the `purge` verb, and it asks twice.',
    )
    parser.add_argument('medium', choices=list(gate.MEDIUMS))
    parser.add_argument('verb', choices=['merge', 'verify', 'status', 'purge'])
    parser.add_argument('--src', action='append', default=[],
                        help='input directory; repeat it for as many drives as are plugged in')
    parser.add_argument('--dest', action=_OneDest, default=None,
                        help='the ONE destination; defaults to the medium\'s library')
    parser.add_argument('--run', default=None,
                        help='run id to verify / purge / resume')
    parser.add_argument('--apply', action='store_true',
                        help='write the copies; without it a merge plans only')
    parser.add_argument('--allow-nested', default='', metavar='WHY',
                        help='permit a --dest nested in a --src, with the reason recorded')
    parser.add_argument('--free-floor-gb', type=float, default=FLOOR_GB)
    parser.add_argument('--json', action='store_true', help='print the summary as JSON')
    return parser


def cmd_status(dest, medium):
    out = {'dest': dest, 'fstype': gate.fstype(dest), 'free_bytes': gate.free_bytes(dest),
           'locks': lock.status(dest, medium)}
    store = os.path.join(dest, '_mediatool', 'ledger.sqlite')
    if os.path.exists(store):
        lg = ledger.Ledger(dest)
        out['runs'] = [{'run_id': row['run_id'], 'medium': row['medium'], 'verb': row['verb'],
                        'status': row['status']}
                       for row in lg.runs() if not medium or row['medium'] == medium][-10:]
        out['unclaimed_deletes'] = [
            {'run_id': row['run_id'], 'path': row['src']}
            for row in lg.connection.execute(
                "SELECT run_id, src FROM commits WHERE op='delete' AND status='pending'")]
        lg.close()
    print(json.dumps(out, indent=2, sort_keys=True))
    return gate.EXIT_OK


def cmd_purge(dest, medium, run_id, opts):
    """The only code path in the toolkit that removes a file. It asks twice."""
    confirm.require_tty()
    store = os.path.join(dest, '_mediatool', 'ledger.sqlite')
    if not os.path.exists(store):
        raise gate.Refusal(f'refused: no ledger at {store}; nothing was ever planned here')
    lg = ledger.Ledger(dest, apply=True)
    row = lg.run_row(run_id) if run_id else None
    if row is None:
        known = [item['run_id'] for item in lg.runs() if item['medium'] == medium]
        raise gate.Refusal(f'refused: no run {run_id!r} for {medium} at {dest}. '
                           f'Known runs: {", ".join(known[-8:]) or "none"}')
    if row['medium'] != medium:
        raise gate.Refusal(f'refused: run {run_id} is {row["medium"]}, not {medium}')
    run_dir = gate.evidence_dir(dest, run_id)
    stage = confirm.read_stage(run_dir)

    allowed, rejected = [], []
    for candidate in stage['candidates']:
        path = candidate['path']
        if not os.path.exists(path):
            continue                                  # already gone: nothing to do
        sha = candidate.get('sha256') or digest.sha256(path)
        survivor = lg.find_copy(sha)
        # The staged file is a *claim*. This is where it is checked: the copy has
        # to be there now, and hash to these bytes now, or this file is not
        # deleted -- whatever the plan said.
        if not survivor or not os.path.exists(survivor['dst']):
            rejected.append((path, 'no copy on disk'))
            continue
        if digest.sha256(survivor['dst']) != sha:
            rejected.append((path, 'surviving copy does not match'))
            continue
        if lg.authorised_delete(run_id, path) is None:
            rejected.append((path, 'no authorised ledger row'))
            continue
        allowed.append({'path': path, 'bytes': int(candidate.get('bytes', 0)),
                        'sha256': sha, 'survivor': survivor['dst'],
                        'why': candidate.get('why', '')})

    if rejected:
        print(f'NOT deleting {len(rejected)} staged file(s) that failed re-verification:')
        for path, why in rejected[:20]:
            print(f'  {path}: {why}')
        if len(rejected) > 20:
            print(f'  ... {len(rejected) - 20} more')
    if not allowed:
        print('Nothing left to delete. No source file was removed.')
        return gate.EXIT_OK

    total = sum(item['bytes'] for item in allowed)
    lines = [f'Showing {min(len(allowed), 25)} of {len(allowed)} files. Every one below has its',
             'surviving copy re-hashed again at the moment of deletion; if that hash',
             'disagrees, that file is skipped.']
    for item in allowed[:25]:
        lines.append(f'  {report.human(item["bytes"]):>11}  {item["path"]}')
        lines.append(f'{"":>13}kept at: {item["survivor"]}')
    if len(allowed) > 25:
        lines.append(f'  ... and {len(allowed) - 25} more (all of them listed in deletes.json)')
    confirm.confirm(len(allowed), total, dest, run_id, lines=lines)

    removed = 0
    freed = 0
    for item in allowed:
        try:
            receipt = fsx.remove(lg, run_id, item['path'])
        except fsx.UnauthorisedDelete as exc:
            print(f'  refused mid-purge: {exc}', file=sys.stderr)
            continue
        removed += 1
        freed += receipt['bytes']
    print(f'deleted {removed} file(s), {report.human(freed)} reclaimed. '
          f'They are duplicates of content that is still on disk.')
    lg.close()
    return gate.EXIT_OK


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        gate.validate_argv(argv)
        args = build_parser().parse_args(argv)
        dest = os.path.realpath(args.dest or gate.dest_for(args.medium))
        if args.verb == 'status':
            return cmd_status(dest, args.medium)

        if args.verb == 'purge':
            return cmd_purge(dest, args.medium, args.run, vars(args))

        if not args.src:
            raise gate.Refusal('refused: a merge needs at least one --src (repeat it per drive)')
        real_dest, real_srcs = gate.check_paths(dest, args.src,
                                                allow_nested=bool(args.allow_nested),
                                                allow_reason=args.allow_nested)

        missing = gate.missing_dependencies(args.medium)
        if missing:
            raise gate.Refusal('refused: this medium needs ' + '; '.join(missing))

        # A fresh run *claims* its evidence directory rather than assuming the id
        # is free (gate.claim_run_dir); `--run` resumes a claimed one.
        run_id = args.run or gate.claim_run_dir(real_dest, args.medium, args.verb)[0]
        opts = dict(vars(args))
        opts.pop('dest', None)
        opts.pop('src', None)
        opts['allow_nested_reason'] = args.allow_nested or None

        with lock.PassLock(real_dest, args.medium, 'structure', run_id):
            engine = Engine(args.medium, args.verb, real_srcs, real_dest, run_id, opts)
            lg = engine.ledger.start_run(run_id, args.medium, args.verb, 'structure',
                                         real_srcs, real_dest,
                                         {k: v for k, v in opts.items()
                                          if k not in ('func', 'medium', 'verb')})
            if args.verb == 'verify':
                plan_path = os.path.join(engine.run_dir, 'plan.json')
                if not os.path.exists(plan_path):
                    raise gate.Refusal(f'refused: no plan.json for run {run_id} at {plan_path}')
                with open(plan_path, encoding='utf-8') as handle:
                    payload = json.load(handle)
                rows = [dict(row, action=row['action']) for row in payload['rows']]
                engine.summary['fstype'] = gate.fstype(real_dest)
                report.free_space(engine.summary)
                ok = engine.verify(rows)
                engine.summary['status'] = 'done' if ok else 'failed'
                engine.summary['finished_utc'] = time.time()
                engine.ledger.finish_run(run_id, engine.summary['status'])
                text = report.write(engine.summary)
                print(text)
                return gate.EXIT_OK if ok else gate.EXIT_CRASH

            code, text = engine.execute()
            print(text)
            if engine.summary.get('staged_deletes', {}).get('files'):
                staged = engine.summary['staged_deletes']
                print(f'{staged["files"]} source files ({report.human(staged["bytes"])}) were '
                      f'left EXACTLY WHERE THEY ARE, listed in\n  {staged["path"]}\n'
                      f'They are not deleted and nothing will delete them. When you have read '
                      f'the list, delete them yourself:\n'
                      f'  python3 media/run.py {args.medium} purge --dest {real_dest} '
                      f'--run {run_id}')
            return code
    except gate.Refusal as exc:
        print(f'{exc}', file=sys.stderr)
        return exc.exit_code
    except lock.Locked as exc:
        print(f'{exc}', file=sys.stderr)
        return exc.exit_code
    except confirm.NotConfirmed as exc:
        print(f'{exc}', file=sys.stderr)
        return exc.exit_code


if __name__ == '__main__':
    sys.exit(main())

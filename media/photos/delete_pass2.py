#!/usr/bin/env python3
"""Pass-2 deletions, from the near-dup report in near-dups.json.


Two rules, both from the owner:
  * same capture second in two different folders -> delete the smaller copy;
  * a burst (consecutive near-identical frames, all gaps <= 7 s) -> delete every
    second photo. Members are ordered by capture time and paired up (1st+2nd,
    3rd+4th, ...); within each pair the smaller file is the one removed, so the
    pair's better copy survives and exactly half of the burst goes.

RAW files are never candidates. DRY=1 (default) only prints the plan.
Every removal is appended to manifest-deletes.csv and dropped from
manifest-moves.csv, so the 12 264-file accounting stays closed.
"""

# This file is a COMMAND, not a library: importing it used to run the pass, which
# is how a `--help` typo came to overwrite a finished plan. Run it instead:
#     python3 media/photos/delete_pass2.py
if __name__ != "__main__":
    raise SystemExit(__file__ + " is a command; run it, do not import it")
import csv
import json
import os
from datetime import datetime

W = '/home/lario/photos-reorg-work'
from paths import LIB
DRY = os.environ.get('DRY', '1') != '0'

MOVES = os.path.join(W, 'manifest-moves.csv')
DELETES = os.path.join(W, 'manifest-deletes.csv')


def main():
    pairs = json.load(open(os.path.join(W, 'near-dups.json')))['pairs']
    moves = {r['new']: r for r in csv.DictReader(open(MOVES, encoding='utf-8'))}

    def t(p):
        try:
            return datetime.strptime(moves[p]['dt'], '%Y-%m-%d %H:%M:%S')
        except Exception:
            return datetime.min

    def size(p):
        return os.path.getsize(os.path.join(LIB, p))

    def ok(p):  # never touch RAW or a file that is no longer on disk
        return p in moves and moves[p]['kind'] == 'image' and os.path.exists(os.path.join(LIB, p))

    cross = [p for p in pairs if os.path.dirname(p['a']) != os.path.dirname(p['b'])]
    same = [p for p in pairs if os.path.dirname(p['a']) == os.path.dirname(p['b']) and
            os.path.splitext(p['a'])[1].lower() == os.path.splitext(p['b'])[1].lower()]

    doomed = {}

    for p in cross:
        a, b = p['a'], p['b']
        if not (ok(a) and ok(b)):
            continue
        drop, keep = (a, b) if size(a) <= size(b) else (b, a)
        doomed[drop] = (keep, f"same-second-across-folders d={p['hamming']}")

    # connected components of same-folder near-dups, per folder
    adj = {}
    for p in same:
        if ok(p['a']) and ok(p['b']):
            adj.setdefault(p['a'], set()).add(p['b'])
            adj.setdefault(p['b'], set()).add(p['a'])
    seen, runs = set(), []
    for start in adj:
        if start in seen:
            continue
        comp, stack = set(), [start]
        while stack:
            x = stack.pop()
            if x in comp:
                continue
            comp.add(x)
            seen.add(x)
            stack.extend(adj[x] - comp)
        runs.append(sorted(comp, key=lambda p: (t(p), p)))

    burst_deleted = 0
    for run in runs:
        for i in range(0, len(run) - 1, 2):
            a, b = run[i], run[i + 1]
            drop, keep = (a, b) if size(a) <= size(b) else (b, a)
            if drop in doomed:
                continue
            doomed[drop] = (keep, f"burst-alternate d<=6 run={len(run)}")
            burst_deleted += 1

    waste = sum(size(p) for p in doomed)
    print(f"{'DRY RUN — nothing removed' if DRY else 'REMOVING'}")
    print(f"same-second across folders: {sum(1 for v in doomed.values() if v[1].startswith('same-second'))}")
    print(f"burst alternates:           {burst_deleted}")
    print(f"total files: {len(doomed)}   space: {waste / 1e6:.1f} MB")
    print(f"library after: {len(moves) - len(doomed)} files")
    for p in sorted(doomed):
        keep, why = doomed[p]
        print(f"  -{size(p) / 1e6:6.2f}MB {p[-62:]}")
        print(f"       keep {keep[-52:]}  ({why})")

    if DRY:
        print('\nrun with DRY=0 to apply')
        return

    with open(DELETES, 'a', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        for p, (keep, why) in sorted(doomed.items()):
            r = moves[p]
            w.writerow([r['orig'], r['backup'], size(p), 'near-duplicate', why,
                        f'kept:{keep}'])

    left = [r for r in moves.values() if r['new'] not in doomed]
    for p in doomed:
        os.remove(os.path.join(LIB, p))
    with open(MOVES, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=list(next(iter(moves.values())).keys()),
                           quoting=csv.QUOTE_MINIMAL)
        w.writeheader()
        w.writerows(sorted(left, key=lambda r: r['new']))
    on_disk = sum(len(fs) for _r, _d, fs in os.walk(LIB))
    print(f"\napplied. manifest rows: {len(left)}   files on disk: {on_disk}   "
          f"{'MATCH' if len(left) == on_disk else 'MISMATCH'}")


if __name__ == '__main__':
    main()

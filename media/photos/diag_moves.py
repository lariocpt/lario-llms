#!/usr/bin/env python3
"""Diagnose the unresolved moves rows.


For each unresolved new path, ask separately:
  A) does any backup file carry the date embedded in the new filename?  (date source ok)
  B) if yes, is it in the old folder the foldermap votes for?           (folder map ok)
  C) do dimensions narrow it down?
"""

# This file is a COMMAND, not a library: importing it used to run the pass, which
# is how a `--help` typo came to overwrite a finished plan. Run it instead:
#     python3 media/photos/diag_moves.py
if __name__ != "__main__":
    raise SystemExit(__file__ + " is a command; run it, do not import it")
import json
import os
import re
import sys

from paths import W        # evidence root: config.PHOTO_WORK, env W
os.makedirs(W, exist_ok=True)      # one evidence root for the whole pass
sys.path.insert(0, W)

from paths import BACKUP as BK
from paths import STAGING as NEW
DATE_RE = re.compile(r'(?:^|_)(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})(\d{2})')


def norm(d):
    return {k.lower(): v for k, v in d.items()}


def load(p):
    d = json.load(open(os.path.join(W, p)))
    return {k: norm(v) for k, v in d.items()}


def date_of(m):
    for k in ('exif:datetimeoriginal', 'exif:createdate', 'ifd0:datetime',
              'xmp:createdate', 'xmp:modifydate', 'composite:datetimecreated',
              'quicktime:createdate', 'file:filecreatedate', 'file:filemodifydate'):
        v = m.get(k)
        if v:
            return str(v)[:10].replace(':', '-')
    return None


def main():
    un = json.load(open(os.path.join(W, 'moves_unresolved.json')))
    bk = load('meta_backup.json')
    fm = json.load(open(os.path.join(W, 'foldermap.json')))
    print('foldermap entries', len(fm), 'unresolved', len(un))
    # date index over the whole backup
    by_date = {}
    for p, m in bk.items():
        d = date_of(m)
        if d:
            by_date.setdefault(d, []).append(p)
    # dates present in the backup at all
    no_date_files = sum(1 for m in bk.values() if not date_of(m))
    print('backup files', len(bk), 'with date', len(by_date), 'without any date tag', no_date_files)
    anywhere, nowhere = [], []
    for entry in un:
        r = {'path': entry[0]} if isinstance(entry, list) else entry
        path = r['path']
        mm = DATE_RE.search(os.path.basename(path))
        if not mm:
            nowhere.append((r, 'no-date-in-name'))
            continue
        d = f'{mm.group(1)}-{mm.group(2)}-{mm.group(3)}'
        hits = by_date.get(d, [])
        (anywhere if hits else nowhere).append((r, len(hits)))
    print(f'new-name date exists somewhere in backup: {len(anywhere)}')
    print(f'new-name date exists NOWHERE in backup : {len(nowhere)}')
    from collections import Counter
    print('\nextension tally of nowhere rows:',
          Counter(os.path.splitext(r['path'])[1] for r, _ in nowhere).most_common(6))
    print('year tally of nowhere rows:',
          Counter(str(r['path'][:4]) for r, _ in nowhere).most_common(8))
    print('\nfolder tally of nowhere rows:',
          Counter(os.path.dirname(r['path']).split('/')[0] if '/' in r['path'][4:] else os.path.dirname(r['path'])
                  for r, _ in nowhere).most_common(6))
    for r, h in nowhere[:12]:
        print(f"  {r['path']}  extdate_matches={h}")
    print('\n--- sample "anywhere" rows: where do the date matches live?')
    for r, h in anywhere[:8]:
        mm = DATE_RE.search(os.path.basename(r['path']))
        d = f'{mm.group(1)}-{mm.group(2)}-{mm.group(3)}'
        dirs = Counter(os.path.dirname(p) for p in by_date[d]).most_common(3)
        print(f"  {r['path']} ({h} matches) -> {dirs}")


if __name__ == "__main__":
    main()

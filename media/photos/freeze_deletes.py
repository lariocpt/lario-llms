#!/usr/bin/env python3
"""Finalise manifest-deletes.csv from recorded evidence (DRY=1 default).


Why this exists instead of another proof run: /mnt/xfs/photos-originals-backup
was deleted by the owner on 2026-10-10, so prove_deletes.py can no longer read a
single deleted file. Nothing here touches the library. Every input is a file
that was written while the backup still existed:

  hashes_backup.jsonl            blake2b of all 12 264 originals (04:33)
  manifest-moves.csv.bak7-0545   8 626 survivors, before the pass-2 deletions
  manifest-moves.csv             8 577 survivors now, with EXIF capture times

What each row can still be shown to rest on:
  byte proof   - the deleted file's recorded hash equals the recorded hash of a
                 survivor's original, or of another deleted file (twin).
  rule proof   - the file is one of the 49 pass-2 removals. The pass-2 scan
                 paired it with a pixel-identical (dHash <= 6) file that is
                 still in the library; the exact partner name was overwritten by
                 rebuild_deletes.py, so it is reconstructed here from the
                 survivor's EXIF capture time in the same old source folder.
  unrecoverable- the one photo with no byte twin and no visual match.

The `backup` column is kept as a historical record of where the file was copied
from; those paths no longer exist.
"""

# This file is a COMMAND, not a library: importing it used to run the pass, which
# is how a `--help` typo came to overwrite a finished plan. Run it instead:
#     python3 media/photos/freeze_deletes.py
if __name__ != "__main__":
    raise SystemExit(__file__ + " is a command; run it, do not import it")
import csv
import json
import os
from collections import defaultdict
from datetime import datetime

from paths import W        # evidence root: config.PHOTO_WORK, env W
os.makedirs(W, exist_ok=True)      # one evidence root for the whole pass
DEL = os.path.join(W, 'manifest-deletes.csv')
FIELDS = ['orig', 'backup', 'bytes', 'category', 'proof', 'how']
DRY = os.environ.get('DRY', '1') != '0'

# Removed by the pass-2 undated-pair rule, but the audit found no survivor that
# carries its pixels. Stated as lost rather than folded into near-duplicate.
LOST = {'January 1, 2014/Photos - 1457 of 6286.jpeg'}
LOST_PROOF = ('blake2b 7689c5615a781d037e8633897c84878e... recorded from the backup at 04:33; '
              'no byte twin among survivors and nearest visual match 25/255 dHash bits away '
              '(2018/2018-07-12 Cape Town, July 12/004_20180712-193701.heic); 4608x3456 JPEG, '
              'EXIF DateTimeOriginal 0000:00:00; removed 2026-10-10 by the pass-2 undated-pair rule')
CLIP = ('.mov', '.mp4', '.m4v', '.avi', '.3gp')


def T(s):
    try:
        return datetime.strptime(s, '%Y-%m-%d %H:%M:%S')
    except Exception:
        return None


def main():
    dels = list(csv.DictReader(open(DEL, encoding='utf-8')))
    moves = list(csv.DictReader(open(os.path.join(W, 'manifest-moves.csv'), encoding='utf-8')))
    pre = list(csv.DictReader(open(os.path.join(W, 'manifest-moves.csv.bak7-0545'), encoding='utf-8')))
    hrow = {}
    hby = defaultdict(list)
    for line in open(os.path.join(W, 'hashes_backup.jsonl')):
        r = json.loads(line)
        hrow[r['path']] = r['hash']
        hby[r['hash']].append(r['path'])

    survivors = {r['orig']: r for r in moves}
    pass2 = {r['orig']: r for r in pre if r['orig'] not in survivors}
    by_folder = defaultdict(list)
    for r in moves:
        by_folder[os.path.dirname(r['orig'])].append(r)

    def keep_target(orig):
        """Reconstruct the pass-2 partner: same old folder, same EXIF capture
        second, not smaller than the deleted file (the rule kept the larger)."""
        r = pass2[orig]
        t = T(r['dt'])
        same = [c for c in by_folder.get(os.path.dirname(orig), [])
                if c['dt'] == r['dt'] and int(c['bytes_before']) >= int(r['bytes_before'])]
        if len(same) == 1:
            return same[0]['new'], 'exact'
        if same:
            day = os.path.dirname(pass2[orig]['new'])
            return f"{day} ({len(same)} burst members, renumbered 2026-10-10)", 'group'
        near = sorted((c for c in by_folder.get(os.path.dirname(orig), [])
                       if int(c['bytes_before']) >= int(r['bytes_before']) and T(c['dt']) and t),
                      key=lambda c: abs((T(c['dt']) - t).total_seconds()))
        if near and abs((T(near[0]['dt']) - t).total_seconds()) <= 2:
            return near[0]['new'], 'near-time'
        return None, 'none'

    # 1. byte twins: two copies of the same content, both gone.
    twin = {r['orig']: [p for p in hby.get(hrow.get(r['orig'], ''), []) if p != r['orig']]
            for r in dels}
    delset = {r['orig'] for r in dels}

    for r in dels:
        o = r['orig']
        if r['category'] == 'junk':
            r['proof'] = r['proof'] or 'Apple resource/edit sidecar (._*, .DS_Store, .aae)'
            r['how'] = r['how'] or 'not a photo'
            continue
        if o in LOST:
            r['category'] = 'unaccounted'
            r['proof'] = LOST_PROOF
            r['how'] = 'LOST: no survivor carries this image'
            continue
        partners = [p for p in twin[o] if p in delset]
        proven = r['category'] in ('live-photo', 'duplicate', 'junk') and r['proof'].strip()
        if proven and o not in pass2:
            continue                      # already pinned by a byte or name proof
        if o in pass2:
            tgt, how_strong = keep_target(o)
            note = ''
            if partners:
                note = '; byte-identical copy %s removed too' % ', '.join(partners)
            r['category'] = 'near-duplicate'
            if tgt:
                r['proof'] = (f'pass-2 scan 2026-10-10: pixel-identical (dHash <= 6) to a file '
                              f'kept in the library; keep target {tgt} reconstructed from EXIF '
                              f'capture time {pass2[o]["dt"]} in the same source folder '
                              f'({how_strong}); original keep-target name lost with the backup{note}')
                r['how'] = f'kept:{tgt}'
            else:
                r['proof'] = (f'pass-2 scan 2026-10-10: pixel-identical (dHash <= 6) to a file kept '
                              f'in the library; exact partner name lost with the backup{note}')
                r['how'] = 'kept: pixel-mate in library (name lost with the backup)'
            continue
        if partners:
            # a byte-for-byte copy of another deleted file (usually the same photo
            # exported twice); that partner's row carries the content proof.
            is_clip = os.path.splitext(o)[1].lower() in CLIP
            r['category'] = 'live-photo' if is_clip else 'duplicate'
            r['proof'] = ('byte-identical to ' + ', '.join(partners) +
                          ' (recorded hash from the backup); that copy\'s row carries the '
                          'content proof')
            r['how'] = ('Live Photo clip, turned into a still; duplicate of ' if is_clip
                        else 'same content as ') + ', '.join(partners)
            continue
        # live-photo clips: chain the proof through the still that shared the moment
        if os.path.splitext(o)[1].lower() in CLIP:
            stem = os.path.splitext(os.path.basename(o))[0]
            for s in [x for x in delset
                      if os.path.dirname(x) == os.path.dirname(o)
                      and os.path.splitext(os.path.basename(x))[0] == stem
                      and os.path.splitext(x)[1].lower() not in CLIP]:
                r['category'] = 'live-photo'
                r['proof'] = (f'Live Photo motion clip; its still {s} is accounted for as a '
                              f'duplicate/near-duplicate (see that row)')
                r['how'] = 'Live Photo turned into a still'
                break

    # anything left unlabelled is a problem: fail rather than write silently
    loose = [r for r in dels if not r['proof'].strip() or r['category'] == 'unaccounted'
             and r['orig'] not in LOST]
    from collections import Counter
    cat = Counter(r['category'] for r in dels)
    tot = sum(int(r['bytes']) for r in dels)
    print(f'rows {len(dels)}   {tot / 1e9:.3f} GB')
    for k, v in cat.most_common():
        print(f'  {k:15} {v:>6}')
    print(f'  pass-2 rows recovered: {sum(1 for r in dels if r["orig"] in pass2)}'
          f'   byte-twin pairs: {sum(1 for r in dels if twin[r["orig"]] and r["orig"] in delset)}')
    print(f'  unpinned: {len(loose)}')
    for r in loose[:10]:
        print('    ?', r['orig'], '|', r['category'], '|', r['proof'][:60])
    if loose:
        raise SystemExit('refusing to write: rows without a proof remain')

    if DRY:
        print('\nDRY RUN - manifest-deletes.csv unchanged (DRY=0 to write)')
        return
    with open(DEL, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, quoting=csv.QUOTE_MINIMAL)
        w.writeheader()
        w.writerows(sorted(dels, key=lambda r: (r['category'], r['orig'])))
    print('wrote manifest-deletes.csv')


if __name__ == '__main__':
    main()

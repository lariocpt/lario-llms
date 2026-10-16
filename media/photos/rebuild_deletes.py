#!/usr/bin/env python3
"""Prove what was deleted.


Every file in the backup that no surviving file points at has to be accounted
for as exactly one of:
  junk         AppleDouble (._*), .DS_Store, .aae AppleScript sidecars
  video        handled by manifest-videos.csv, not a deletion
  live-photo   the motion clip that was dropped when the Live Photo became a still
  duplicate    byte-identical to something that survived (same content, one copy kept)
  unaccounted  anything left over - which must be empty

For duplicates the proof runs on content, not names: the deleted file's hash
equals the hash of an original that a surviving file claims, or equals the hash
of a surviving file directly.
"""

# This file is a COMMAND, not a library: importing it used to run the pass, which
# is how a `--help` typo came to overwrite a finished plan. Run it instead:
#     python3 media/photos/rebuild_deletes.py
if __name__ != "__main__":
    raise SystemExit(__file__ + " is a command; run it, do not import it")
import csv
import json
import os
from collections import Counter, defaultdict

from paths import W        # evidence root: config.PHOTO_WORK, env W
os.makedirs(W, exist_ok=True)      # one evidence root for the whole pass
from paths import BACKUP as BK
from paths import LIB
from paths import STAGING as NEW
from paths import VIDLIB as VID_ROOT
STILL = ('.jpg', '.jpeg', '.heic', '.png', '.tif', '.tiff', '.gif')


def load(p):
    d = {}
    with open(p) as fh:
        for line in fh:
            r = json.loads(line)
            d[r['path']] = (r['size'], r['hash'])
    return d


def main():
    # Guard, added 2026-10-10. This script regenerates manifest-deletes.csv from
    # scratch: it drops the per-row proof history, and both of its inputs are
    # gone now - the backup, and the Photos.new staging tree it reads survivors
    # from. Run it today and every deletion comes out 'unaccounted'. Use
    # freeze_deletes.py, which only fills in proofs from recorded evidence.
    for must in (BK, NEW):
        if not os.path.isdir(must):
            raise SystemExit(f'refusing to run: {must} no longer exists. '
                             f'manifest-deletes.csv is frozen - use freeze_deletes.py')
    if os.environ.get('ALLOW_REBUILD_DELETES') != '1':
        raise SystemExit('refusing to run: this overwrites manifest-deletes.csv and '
                         'discards its proof column history. Set ALLOW_REBUILD_DELETES=1 '
                         'only if that is really what you want.')
    rows = list(csv.DictReader(open(os.path.join(W, 'manifest-moves.csv'))))
    vrows = list(csv.DictReader(open(os.path.join(W, 'manifest-videos.csv'))))
    hb = load(os.path.join(W, 'hashes_backup.jsonl'))
    hn = load(os.path.join(W, 'hashes_new.jsonl'))

    used_orig = {r['orig'] for r in rows}
    vids = {v['orig'] for v in vrows}
    vids |= {os.path.relpath(v['orig'], LIB)
             for v in vrows if os.path.isabs(v.get('orig', ''))}

    # content that survived: by the survivor's own bytes, and by the bytes of the
    # original it came from (a recompressed JPEG no longer matches, but it is the
    # same photo)
    surviving_hash = {}
    for rel, (sz, h) in hn.items():
        if h:
            surviving_hash.setdefault(h, rel)
    source_hash = {}
    for r in rows:
        h = hb.get(r['orig'], (0, None))[1]
        if h:
            source_hash.setdefault(h, r['new'])
    accounted = used_orig | vids
    # every still in the backup that is itself accounted for, by folder + stem: a
    # .mov sitting next to such a still is that Live Photo's motion clip, even
    # when the still was a duplicate copy that went too.
    stills = {}
    for rel in hb:
        if os.path.splitext(rel)[1].lower() in STILL and rel in accounted:
            stills.setdefault((os.path.dirname(rel),
                               os.path.splitext(os.path.basename(rel))[0].lower()), rel)
    # folder + stem of a still that became a survivor, and of a video that moved out
    pair_new = {}
    for r in rows:
        if os.path.splitext(r['new'])[1].lower() in STILL:
            key = (os.path.dirname(r['orig']),
                   os.path.splitext(os.path.basename(r['orig']))[0].lower())
            pair_new.setdefault(key, r['new'])
    surviving_stems = {}
    for v in vrows:
        o = v['orig']
        key = (os.path.dirname(o), os.path.splitext(os.path.basename(o))[0].lower())
        surviving_stems.setdefault(key, v['dest'])
    # bytes of anything accounted for, videos included
    accounted_hash = defaultdict(list)
    for rel in accounted:
        h = hb.get(rel, (0, None))[1]
        if h:
            accounted_hash[h].append(rel)

    def is_junk(rel):
        base = os.path.basename(rel)
        ext = os.path.splitext(base)[1].lower()
        return (base.startswith('._') or base.lower() in ('.ds_store', 'desktop.ini', 'thumbs.db')
                or base.lower().startswith('.picasa') or ext == '.aae')

    def junk_kind(rel):
        base = os.path.basename(rel)
        if base.startswith('._'):
            return 'AppleDouble resource fork'
        if base.lower() == '.ds_store':
            return 'macOS folder metadata'
        if base.lower() == 'desktop.ini':
            return 'Windows folder metadata'
        if base.lower() == 'thumbs.db':
            return 'Windows thumbnail cache'
        if os.path.splitext(base)[1].lower() == '.aae':
            return 'AppleScript Live Photo sidecar'
        return 'application metadata'

    cats = defaultdict(list)
    for rel, (sz, h) in sorted(hb.items()):
        base = os.path.basename(rel)
        ext = os.path.splitext(base)[1].lower()
        if rel in used_orig or rel in vids:
            continue
        if is_junk(rel):
            cats['junk'].append({'orig': rel, 'bytes': sz, 'proof': junk_kind(rel)})
            continue
        if h and h in surviving_hash:
            cats['duplicate'].append({'orig': rel, 'bytes': sz, 'proof': surviving_hash[h],
                                      'how': 'same bytes as a surviving file'})
            continue
        if h and h in source_hash:
            cats['duplicate'].append({'orig': rel, 'bytes': sz, 'proof': source_hash[h],
                                      'how': 'same bytes as the original a survivor came from'})
            continue
        if ext in ('.mov', '.mp4', '.m4v', '.avi', '.3gp'):
            key = (os.path.dirname(rel), os.path.splitext(base)[0].lower())
            tgt = pair_new.get(key) or surviving_stems.get(key)
            if tgt:
                cats['live-photo'].append({'orig': rel, 'bytes': sz, 'proof': tgt,
                                           'how': 'Live Photo clip of a surviving still'})
                continue
            sis = stills.get(key)
            if sis and ext == '.mov':
                cats['live-photo'].append({'orig': rel, 'bytes': sz,
                                           'proof': f'still sibling {sis}',
                                           'how': 'Live Photo clip; still sibling accounted for'})
                continue
            if h and h in accounted_hash:
                cats['duplicate'].append({'orig': rel, 'bytes': sz, 'proof': accounted_hash[h][0],
                                          'how': 'same bytes as an accounted video'})
                continue
            cats['unaccounted'].append({'orig': rel, 'bytes': sz, 'why': 'video, no match'})
            continue
        cats['unaccounted'].append({'orig': rel, 'bytes': sz, 'why': 'no hash match anywhere'})

    # second pass: a clip whose still sibling did not survive under its own name
    # still has its photo content accounted for - the sibling was proven a
    # duplicate of something that survived - so the clip is that Live Photo's
    # motion half, which is what the conversion set out to drop.
    explained = set(stills)
    for x in cats['duplicate']:
        rel = x['orig']
        if os.path.splitext(rel)[1].lower() in STILL:
            explained.add((os.path.dirname(rel),
                           os.path.splitext(os.path.basename(rel))[0].lower()))
    keep = []
    for x in cats['unaccounted']:
        rel = x['orig']
        ext = os.path.splitext(rel)[1].lower()
        key = (os.path.dirname(rel), os.path.splitext(os.path.basename(rel))[0].lower())
        if ext in ('.mov', '.m4v', '.mp4') and key in explained:
            cats['live-photo'].append({'orig': rel, 'bytes': x['bytes'],
                                       'proof': f'still sibling {rel[:-len(ext)]}.* '
                                                f'(itself a proven duplicate)',
                                       'how': 'Live Photo clip, still survived as a duplicate'})
        else:
            keep.append(x)
    cats['unaccounted'] = keep

    total = sum(len(v) for v in cats.values())
    print(f'backup files indexed: {len(hb)}   accounted by the moves manifest: {len(used_orig)}   '
          f'by the video manifest: {len(vids)}')
    for k in ('junk', 'duplicate', 'live-photo', 'unaccounted'):
        v = cats.get(k, [])
        gb = sum(x['bytes'] for x in v) / 1e9
        print(f'  {k:12s} {len(v):5d} files  {gb:7.2f} GB')
    print(f'  classified total {total} (index {len(hb)})')

    un = cats.get('unaccounted', [])
    print('unaccounted by extension:',
          Counter(os.path.splitext(x['orig'])[1].lower() for x in un).most_common(12))
    for x in un[:25]:
        print(f"  UNACCOUNTED {x['orig']}  {x['bytes']}  [{x['why']}]")

    out = os.path.join(W, 'manifest-deletes.csv')
    with open(out, 'w', newline='') as fh:
        w = csv.writer(fh)
        w.writerow(['orig', 'backup', 'bytes', 'category', 'proof', 'how'])
        for k in ('junk', 'duplicate', 'live-photo', 'unaccounted'):
            for x in sorted(cats.get(k, []), key=lambda y: y['orig']):
                w.writerow([x['orig'], os.path.join(BK, x['orig']), x['bytes'], k,
                            x.get('proof', ''), x.get('how', x.get('why', ''))])
    print('wrote', out)
    json.dump({'counts': {k: len(v) for k, v in cats.items()},
               'bytes': {k: sum(x['bytes'] for x in v) for k, v in cats.items()},
               'unaccounted': un}, open(os.path.join(W, 'deletes-audit.json'), 'w'), indent=1)


if __name__ == "__main__":
    main()

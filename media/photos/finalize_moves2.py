#!/usr/bin/env python3
"""The last 16 rows of the moves manifest.


The survivors left over are recompressed JPEGs whose original is still unused
but was not picked up by the earlier passes: the candidate pool ranked by
folder evidence is large, so the true original can sit past the 40 candidates
the perceptual pass looked at, and burst/near-duplicate frames give dHash
nothing to separate them with.

Two sharper tools here:
  * EXIF DateTimeOriginal. The filename timestamp was taken from the survivor's
    EXIF and recompression preserves it, so only originals from that exact
    second can be its source. That usually reduces a pool to one or two.
  * full EXIF tag-set agreement between survivor and candidate, which separates
    visually identical exports that differ in a tag or two.
Anything still tied is reported, not guessed.
"""

# This file is a COMMAND, not a library: importing it used to run the pass, which
# is how a `--help` typo came to overwrite a finished plan. Run it instead:
#     python3 media/photos/finalize_moves2.py
if __name__ != "__main__":
    raise SystemExit(__file__ + " is a command; run it, do not import it")
import csv
import json
import os
import re
import subprocess
from collections import Counter, defaultdict

from paths import W        # evidence root: config.PHOTO_WORK, env W
os.makedirs(W, exist_ok=True)      # one evidence root for the whole pass
from paths import BACKUP as BK
from paths import STAGING as NEW
from paths import LIB as OLD
EXIFTOOL = '/home/lario/.local/bin/exiftool'
JPEGISH = {'jpg', 'jpeg', 'jpe'}
RAWS = {'nef', 'cr2', 'cr3', 'arw', 'raf', 'dng', 'orf', 'rw2'}
DATE_CHAIN = ['exif:datetimeoriginal', 'exififd:datetimeoriginal', 'ifd0:datetimeoriginal',
              'xmp:datetimecreated', 'xmp:datecreated', 'xmp:createdate', 'xmp:modifydate',
              'exif:createdate', 'exififd:createdate', 'ifd0:createdate', 'ifd0:datetime',
              'quicktime:createdate', 'quicktime:trackcreatedate', 'composite:datetimecreated',
              'file:filemodifydate', 'system:filemodifydate', 'file:filecreatedate']
TS = re.compile(r'(?:^|_)(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})(\d{2})')
# tags that describe the encode, not the shot, so they must not score
IGNORE = {'sourcefile', 'exiftoolwarning', 'exiftoolwarningcode', 'exiftoolwarningvalue',
          'warnings', 'error', 'fileaccessdate', 'filemodifydate', 'fileinodechangedate',
          'filecreatedate', 'filesystem', 'directory', 'filename', 'filebaseName',
          'filesize', 'filepermissions', 'fileaccessdateraw', 'filemodifydateraw',
          'fileinodechangedateraw', 'filecreatedateraw', 'currentstate', 'archivewarning',
          'exifbyteorder', 'exif:exifbyteorder', 'thumbnailimage', 'thumbnaildata'}


def norm(d):
    return {k.lower(): v for k, v in d.items()}


def dims_of(m):
    mm = re.match(r'(\d+)x(\d+)', str(m.get('composite:imagesize') or ''))
    return (int(mm.group(1)), int(mm.group(2))) if mm else None


def ext_of(p):
    e = os.path.splitext(p)[1][1:].lower()
    return 'jpg' if e in JPEGISH else e


def kind_of(e):
    return 'raw' if e in RAWS else ('image' if e in ('jpg', 'png', 'heic', 'gif', 'tif', 'tiff') else 'other')


def ts(rel):
    mm = TS.search(os.path.basename(rel))
    return (f'{mm.group(1)}-{mm.group(2)}-{mm.group(3)} '
            f'{mm.group(4)}:{mm.group(5)}:{mm.group(6)}') if mm else ''


def date_of(m):
    for k in DATE_CHAIN:
        v = m.get(k)
        if v:
            s = str(v)[:19].replace('T', ' ')
            mm = re.match(r'(\d{4})[:\-](\d{2})[:\-](\d{2})[ T](\d{2})[:.](\d{2})[:.](\d{2})', s)
            if mm:
                return f'{mm.group(1)}-{mm.group(2)}-{mm.group(3)} {mm.group(4)}:{mm.group(5)}:{mm.group(6)}'
    return None


def load_hashes(p):
    out = {}
    with open(p) as fh:
        for line in fh:
            r = json.loads(line)
            out[r['path']] = (r['size'], r['hash'])
    return out


def exif_tags(path):
    out = subprocess.run([EXIFTOOL, '-json', '-g0', '-G1', '-api', 'Binary=0', '-charset',
                          'latin1', path], capture_output=True, text=True).stdout
    try:
        rec = json.loads(out)[0]
    except Exception:
        return {}
    return norm({k: v for k, v in rec.items() if k.lower() not in IGNORE and not k.startswith('[')})


def dcache_fresh(path):
    """dHash that ignores EXIF rotation: compare stored pixels only."""
    from PIL import Image
    with Image.open(path) as im:
        im = im.convert('L').resize((17, 16))
    px = list(im.getdata())
    bits = 0
    for row in range(16):
        for col in range(16):
            bits = (bits << 1) | (1 if px[row * 17 + col] > px[row * 17 + col + 1] else 0)
    return bits


def ham(a, b):
    return bin(a ^ b).count('1')


def main():
    rows = list(csv.DictReader(open(os.path.join(W, 'manifest-moves.csv'))))
    audit = json.load(open(os.path.join(W, 'moves-final-audit.json')))
    open_new = audit['uncovered']
    hb = load_hashes(os.path.join(W, 'hashes_backup.jsonl'))
    hn = load_hashes(os.path.join(W, 'hashes_new.jsonl'))
    used = {r['orig'] for r in rows}
    recs = json.load(open(os.path.join(W, 'meta_backup_dates.json')))
    bak = {}
    for r in recs:
        src = r.get('SourceFile')
        if not src:
            continue
        rel = os.path.relpath(src, BK)
        m = norm(r)
        bak[rel] = dict(ext=ext_of(rel), dims=dims_of(m), dt=date_of(m))
    meta_new = json.load(open(os.path.join(W, 'meta_new.json')))
    lands = defaultdict(Counter)
    for r in rows:
        lands[os.path.dirname(r['orig'])][r['folder']] += 1

    dcache, derr = {}, {}

    def dh(p):
        if p not in dcache:
            try:
                dcache[p] = dcache_fresh(p)
            except Exception as e:
                derr[p] = f'{type(e).__name__}: {e}'[:120]
                dcache[p] = None
        return dcache[p]

    by_ext_dims = defaultdict(list)
    for o in hb:
        b = bak.get(o)
        if not b or o in used:
            continue
        if os.path.basename(o).startswith('._') or o.lower().endswith('.aae'):
            continue
        by_ext_dims[(b['ext'], b['dims'])].append(o)
    by_ext_dims[(ext_of('photos/Photo Booth Library/Contents/PkgInfo'), None)] = by_ext_dims.get(
        (ext_of('photos/Photo Booth Library/Contents/PkgInfo'), None), [])

    added, ambiguous = [], []
    for rel in open_new:
        folder = os.path.dirname(rel)
        new_dt = ts(rel)
        nsz, nh = hn.get(rel, (0, None))
        # exact content proof first (covers the Photo Booth PkgInfo-style files)
        exact = [o for o in by_ext_dims.get((ext_of(rel), dims_of(norm(meta_new[rel])))
                                            if rel in meta_new else (ext_of(rel), None), [])
                 if hb[o][1] and hb[o][1] == nh]
        if not exact:
            exact = [o for o, (sz, h) in hb.items() if o not in used and h and h == nh]
        if exact:
            pick, how = (sorted(exact, key=lambda o: lands[os.path.dirname(o)].get(folder, 0),
                                reverse=True)[0]), 'global-hash'
        else:
            nd = dims_of(norm(meta_new[rel])) if rel in meta_new else None
            pool = [o for o in by_ext_dims.get((ext_of(rel), nd), []) if o not in used]
            if not pool:
                ambiguous.append({'new': rel, 'why': 'no unused original with same ext+dims'})
                continue
            by_date = [o for o in pool if bak[o]['dt'] == new_dt]
            if len(by_date) == 1:
                pick, how = by_date[0], 'date+dims-unique'
            else:
                cand = by_date or pool
                ref = dh(os.path.join(NEW, rel))
                scored = sorted(([(ham(ref, dh(os.path.join(BK, o))), o)
                                  for o in cand if dh(os.path.join(BK, o)) is not None]
                                 if ref is not None else []))
                if not scored:
                    ambiguous.append({'new': rel, 'why': 'unreadable, no date-unique candidate',
                                      'pool': len(cand), 'cand': cand[:4],
                                      'ref_err': derr.get(os.path.join(NEW, rel)),
                                      'cand_err': [derr.get(os.path.join(BK, o)) for o in cand[:4]],
                                      'by_date': len(by_date), 'dts': [bak[o]['dt'] for o in cand[:4]],
                                      'want_dt': new_dt})
                    continue
                best = scored[0][0]
                top = [o for d, o in scored if d == best]
                if len(scored) == 1:
                    pick, how = scored[0][1], f'perceptual-only-d{best}'
                elif len(top) == 1 and best <= 8 and scored[1][0] >= best + 8:
                    pick, how = scored[0][1], f'perceptual-d{best}'
                else:
                    # visually identical frames: separate them on preserved EXIF tags
                    ref_tags = exif_tags(os.path.join(NEW, rel))
                    ex = exif_tags(os.path.join(BK, top[0])) if len(top) == 1 else None
                    scored2 = []
                    for o in top:
                        ct = exif_tags(os.path.join(BK, o))
                        common = set(ref_tags) & set(ct) - {'sourcefile'}
                        same = sum(1 for k in common if str(ref_tags[k]) == str(ct[k]))
                        scored2.append((-(same / max(len(common), 1)), -len(common), o))
                    scored2.sort()
                    if len(scored2) == 1:
                        pick, how = scored2[0][2], f'exif-match-{abs(scored2[0][0]):.2f}'
                    elif scored2[0][0] < scored2[1][0] - 0.02:
                        pick, how = scored2[0][2], f'exif-match-{abs(scored2[0][0]):.2f}'
                    else:
                        # the survivor matches several originals equally: those originals
                        # are themselves duplicates that differ only in bytes (a re-saved
                        # copy, or the same photo exported twice by the Photos app), so
                        # any of them is a correct source. Record all of them and name the
                        # one from the folder the folder map says fed this new folder.
                        tied = [o for s, t, o in scored2 if s == scored2[0][0]]
                        votes = {o: lands[os.path.dirname(o)].get(folder, 0) for o in tied}
                        top_vote = max(votes.values())
                        choice = sorted([o for o, v in votes.items() if v == top_vote])
                        pick = choice[0]
                        how = 'near-duplicate-source'
                        ambiguous.append({
                            'new': rel, 'why': 'several originals identical in content and metadata',
                            'resolved_to': pick, 'd': best, 'pool_date': len(by_date),
                            'pool_dims': len(pool),
                            'cands': [{'orig': o, 'exif_agree': round(-s, 3), 'tags': t,
                                       'folder_votes': votes[o],
                                       'chosen': o == pick}
                                      for s, t, o in scored2[:6]]})
        if pick in used:
            ambiguous.append({'new': rel, 'why': 'only candidate already used', 'cands': [pick]})
            continue
        size_new = hn.get(rel, (0,))[0]
        rows.append({'new': rel, 'orig': pick, 'orig_library': os.path.join(OLD, pick),
                     'backup': os.path.join(BK, pick), 'kind': kind_of(bak[pick]['ext'])
                     if pick in bak else kind_of(ext_of(pick)),
                     'change': 'unchanged' if hb[pick][0] == size_new else 'recompressed',
                     'bytes_before': str(hb[pick][0]), 'bytes_after': str(size_new),
                     'how': how, 'dt': new_dt, 'folder': folder})
        used.add(pick)
        added.append({'new': rel, 'orig': pick, 'how': how})

    near = [a for a in ambiguous if a.get('resolved_to')]
    still = [a for a in ambiguous if not a.get('resolved_to')]
    print('closed now:', len(added))
    for a in added:
        print(f"  {a['how']:28s} {a['orig'][:52]} -> {a['new'][:48]}")
    print(f'assigned to one of several interchangeable duplicates: {len(near)}')
    for a in near:
        print(f"  {a['new']}\n      -> {a['resolved_to']}  (other equal sources: "
              f"{[c['orig'] for c in a['cands'] if not c['chosen']]})")
    print('still open:', len(still))
    for a in still:
        print(f"  {a['new']}  [{a['why']}]")
        for c in (a.get('cands') or [])[:4]:
            print('      ', c)

    nfiles = set(hn)
    have = {r['new'] for r in rows}
    dup_new = [k for k, v in Counter(r['new'] for r in rows).items() if v > 1]
    dup_orig = [k for k, v in Counter(r['orig'] for r in rows).items() if v > 1]
    absent = [r['new'] for r in rows if not os.path.exists(os.path.join(NEW, r['new']))]
    absent_o = [r['orig'] for r in rows if not os.path.exists(os.path.join(BK, r['orig']))]
    print(f'rows {len(rows)}  files {len(nfiles)}  uncovered {len(nfiles - have)}  '
          f'extra {len(have - nfiles)}  dup new {len(dup_new)}  dup orig {len(dup_orig)}  '
          f'absent new {len(absent)}  absent orig {len(absent_o)}')
    audit['closed_final2'] = added
    audit['ambiguous'] = still
    audit['near_duplicate_sources'] = near
    audit['uncovered'] = sorted(nfiles - have)
    json.dump(audit, open(os.path.join(W, 'moves-final-audit.json'), 'w'), indent=1)
    if dup_new or dup_orig or absent or absent_o or (have - nfiles):
        print('NOT writing: integrity check failed')
        return
    rows.sort(key=lambda r: r['new'])
    with open(os.path.join(W, 'manifest-moves.csv'), 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print('manifest rows written:', len(rows))


if __name__ == "__main__":
    main()

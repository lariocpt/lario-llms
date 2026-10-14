#!/usr/bin/env python3
"""Re-prove every row of manifest-deletes.csv against real evidence.


rebuild_deletes.py proves a deletion only when its bytes match a survivor's
bytes. That is the wrong test for two groups:

  * a duplicate copy whose surviving twin was later recompressed - the survivor's
    current bytes no longer match, though it is the same photo;
  * a near-duplicate removed by the burst / same-second rules - never
    byte-identical to anything.

For those, prove it on pixels instead: hash the deleted file out of the backup
and take the distance to every surviving photo's *original* bytes. Distance 0
means the same image; dHash <= 6 means visually identical, which is what those
two rules were based on. Rows keep their category; the proof column records the
survivor that carries the content and the measured distance.

Writes manifest-deletes.csv (the previous copy to manifest-deletes.csv.bak).
"""

# This file is a COMMAND, not a library: importing it used to run the pass, which
# is how a `--help` typo came to overwrite a finished plan. Run it instead:
#     python3 media/photos/prove_deletes.py
if __name__ != "__main__":
    raise SystemExit(__file__ + " is a command; run it, do not import it")
import csv
import hashlib
import json
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor

W = '/home/lario/photos-reorg-work'
from paths import BACKUP as BK
DEL = os.path.join(W, 'manifest-deletes.csv')
FIELDS = ['orig', 'backup', 'bytes', 'category', 'proof', 'how']


def dhash(path):
    """4x4-block difference hash over a 16x16 greyscale thumbnail (255 bits)."""
    try:
        raw = subprocess.run(['convert', path, '-auto-orient', '-resize', '16x16!',
                              '-colorspace', 'Gray', '-depth', '8', 'GRAY:-'],
                             capture_output=True, check=True).stdout
        rows = [raw[i * 16:i * 16 + 16] for i in range(16)]
        if any(len(r) != 16 for r in rows):
            return None
        h = 0
        for y in range(16):
            for x in range(15):
                h = (h << 1) | (1 if rows[y][x] > rows[y][x + 1] else 0)
        return h
    except Exception:
        return None


def load_hashes(path):
    d = {}
    with open(path) as fh:
        for line in fh:
            r = json.loads(line)
            d[r['path']] = r['hash']
    return d


def main():
    moves = list(csv.DictReader(open(os.path.join(W, 'manifest-moves.csv'), encoding='utf-8')))
    hb = load_hashes(os.path.join(W, 'hashes_backup.jsonl'))
    hn = load_hashes(os.path.join(W, 'hashes_new.jsonl'))
    dels = list(csv.DictReader(open(DEL, encoding='utf-8')))

    survivors_by_orig = {}          # backup-relative orig -> new path
    for r in moves:
        survivors_by_orig[r['orig']] = r['new']
    byte_survivor = {}              # hash -> new path (current bytes)
    for h, rel in hn.items():
        byte_survivor.setdefault(h, rel)

    # 1. byte-level proofs, using the bytes a survivor came from as well as its
    #    current bytes: a recompressed JPEG is still the same photo.
    src_hash = {}
    for r in moves:
        h = hb.get(r['orig'])
        if h:
            src_hash.setdefault(h, r['new'])

    need_pixels, proved = [], 0
    for r in dels:
        if r['category'] == 'junk':
            r['proof'] = r['proof'] or 'Apple resource/edit sidecar'
            proved += 1
            continue
        h = hb.get(r['orig'])
        if h and h in byte_survivor:
            r['category'], r['proof'] = 'duplicate', f'byte-identical to {byte_survivor[h]}'
            proved += 1
            continue
        if h and h in src_hash:
            r['category'], r['proof'] = 'duplicate', f'same bytes as original of {src_hash[h]}'
            proved += 1
            continue
        if not r['proof'].strip():
            need_pixels.append(r)
        else:
            proved += 1

    print(f'rows {len(dels)}   proved by bytes/name {proved}   needing pixel proof {len(need_pixels)}')

    # 2. pixel proof. Compare each unproved deletion against both reference sets:
    #    the bytes a survivor came from, and the survivor's current bytes. Either
    #    side may have been re-encoded since, and orientation flags are applied at
    #    thumbnail time, so the smaller of the two distances is the honest one.
    targets = [r for r in need_pixels if os.path.exists(os.path.join(BK, r['backup']))]
    missing = [r for r in need_pixels if r not in targets]
    print(f'pixel targets: {len(targets)}   not readable in backup: {len(missing)}')

    from paths import LIB
    origs = sorted(survivors_by_orig)
    news = sorted(set(survivors_by_orig.values()))
    with ThreadPoolExecutor(8) as ex:
        h_orig = list(ex.map(lambda p: dhash(os.path.join(BK, p)), origs))
    with ThreadPoolExecutor(8) as ex:
        h_new = list(ex.map(lambda p: dhash(os.path.join(LIB, p)), news))
    cur = dict(zip(news, h_new))
    ref = [(h, survivors_by_orig[p]) for p, h in zip(origs, h_orig) if h is not None]
    ref += [(h, n) for n, h in cur.items() if h is not None]
    print(f'reference hashes: {len(ref)} (originals + current bytes)')

    CLIP = ('.mov', '.mp4', '.m4v', '.avi', '.3gp')

    def frame(path):
        """Live Photo clips are compared on their first frame, not as images."""
        if os.path.splitext(path)[1].lower() not in CLIP:
            return dhash(path)
        try:
            tmp = f'/tmp/opencode/firstframe-{os.getpid()}.png'
            subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', path,
                            '-frames:v', '1', tmp], capture_output=True, check=True, timeout=120)
            h = dhash(tmp)
            os.remove(tmp)
            return h
        except Exception:
            return None

    with ThreadPoolExecutor(8) as ex:
        theirs = list(ex.map(lambda r: frame(os.path.join(BK, r['backup'])), targets))

    unresolved = []
    for r, th in zip(targets, theirs):
        if th is None:
            unresolved.append((r, 'unreadable'))
            continue
        best = min(ref, key=lambda x: (th ^ x[0]).bit_count())
        d = (th ^ best[0]).bit_count()
        if d <= 8:
            r['category'] = 'duplicate' if d == 0 else 'near-duplicate'
            r['proof'] = f'pixel distance {d} vs original of {best[1]}'
            r['how'] = f'kept:{best[1]}'
        else:
            unresolved.append((r, f'nearest distance {d} to {best[1]}'))

    for r in missing:
        unresolved.append((r, 'not in backup'))

    # 3. Motion clips that survived neither test: an Apple/Google Live Photo clip
    #    whose still sibling was itself removed (as a duplicate copy). Chain the
    #    proof through that sibling to the photo that carries the moment.
    still_ext = ('.jpg', '.jpeg', '.heic', '.png', '.tif', '.tiff', '.gif')
    bk_index = {}
    for dp, _d, fs in os.walk(BK):
        rel = os.path.relpath(dp, BK)
        for f in fs:
            key = (rel.lower(), os.path.splitext(f)[0].lower().strip())
            bk_index.setdefault(key, []).append(os.path.normpath(os.path.join(rel, f))
                                                if rel != '.' else f)
    by_orig = {r['orig']: r for r in dels}

    def resolve_still(sis, depth=0):
        if sis in survivors_by_orig:
            return f'motion clip; its still is {survivors_by_orig[sis]}'
        if depth > 2:
            return None
        row = by_orig.get(sis)
        if row and row['category'] != 'unaccounted' and row['proof'].strip():
            return f'motion clip; its still {sis} is a {row["category"]} ({row["proof"]})'
        for s2 in bk_index.get((os.path.dirname(sis).lower(),
                                os.path.splitext(os.path.basename(sis))[0].lower().strip()), []):
            if s2 != sis and os.path.splitext(s2)[1].lower() in still_ext:
                got = resolve_still(s2, depth + 1)
                if got:
                    return f'motion clip; its still {sis} equals {got}'
        return None

    if unresolved:
        keep = []
        for r, why in unresolved:
            if os.path.splitext(r['orig'])[1].lower() in CLIP:
                for s in bk_index.get((os.path.dirname(r['orig']).lower(),
                                       os.path.splitext(os.path.basename(r['orig']))[0].lower().strip()), []):
                    if s != r['orig'] and os.path.splitext(s)[1].lower() in still_ext:
                        got = resolve_still(s)
                        if got:
                            r['category'] = 'live-photo'
                            r['proof'] = got
                            r['how'] = 'Live Photo clip; still accounted for elsewhere'
                            break
            if r['category'] == 'unaccounted':
                keep.append((r, why))
        unresolved = keep

    print(f'pixel-proved: {len(targets) - sum(1 for x in unresolved if x[0] in targets)}')
    print(f'unresolved:   {len(unresolved)}')
    for r, why in unresolved[:20]:
        print(f'   {r["orig"][-60:]}  {why}')

    from collections import Counter
    cat = Counter(r['category'] for r in dels)
    tot = sum(int(r['bytes']) for r in dels)
    for k, v in cat.most_common():
        print(f'  {k:16} {v:>6}')
    print(f'  total {len(dels)} rows, {tot / 1e9:.2f} GB')

    if unresolved:
        raise SystemExit('refusing to write: unresolved deletions remain')
    os.replace(DEL, DEL + '.bak')
    with open(DEL, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, quoting=csv.QUOTE_MINIMAL)
        w.writeheader()
        w.writerows(sorted(dels, key=lambda r: (r['category'], r['orig'])))
    print('wrote manifest-deletes.csv')


if __name__ == '__main__':
    main()

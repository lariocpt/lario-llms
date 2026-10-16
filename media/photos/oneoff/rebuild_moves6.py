#!/usr/bin/env python3
"""Finalise the moves manifest: drop rows superseded by the later evidence

passes, keep one row per new path (preferring the strongest proof), then close
the remaining gaps with a perceptual dHash comparison against the only
plausible unused originals. Appends new rows for whatever it can prove."""

# This file is a COMMAND, not a library: importing it used to run the pass, which
# is how a `--help` typo came to overwrite a finished plan. Run it instead:
#     python3 media/photos/rebuild_moves6.py
if __name__ != "__main__":
    raise SystemExit(__file__ + " is a command; run it, do not import it")
import csv, os, subprocess, json, hashlib, re
from collections import defaultdict

WORK = '/home/lario/photos-reorg-work'
NEW_ROOT = '/home/lario/Pictures/Photos.new'
BAK_ROOT = '/mnt/xfs/photos-originals-backup/Photos'
SRC_ROOT = '/home/lario/Downloads/from-lario-phone-2025-07-18/Photos'
IMG_EXT = ('.jpg', '.jpeg', '.heic', '.png', '.gif', '.tif', '.tiff', '.nef')

RANK = {'global-hash': 0, 'global-hash-duplicates': 1, 'dims-unique': 2,
        'perceptual': 3, 'folder+date+dims': 4, 'folder+date': 4,
        'evidence-rank': 5, '+size': 6, 'size-plausible': 6,
        'undated-stem': 7, 'undated-stem2': 7, 'date+order': 8, 'order-zip': 9}

# 1. drop rows whose new path was later resolved by stronger evidence
rows = list(csv.DictReader(open(f'{WORK}/manifest-moves.csv')))
UNRES = json.load(open(f'{WORK}/moves_unresolved5.json'))
UNRES = UNRES['items'] if isinstance(UNRES, dict) else UNRES
still_open = {x['new'] for x in UNRES}
rows = [r for r in rows if r['new'] not in still_open]

# 2. one row per new path, strongest proof wins, then shortest original name
by_new = defaultdict(list)
for r in rows:
    by_new[r['new']].append(r)
final, dupes = [], []
for new, cand in by_new.items():
    cand.sort(key=lambda r: (RANK.get(r['how'], 9), len(r['orig']), r['orig']))
    final.append(cand[0])
    if len(cand) > 1:
        dupes.append((new, [r['orig'] for r in cand]))
print(f"one row per new path: {len(final)} (resolved {len(dupes)} duplicate assignments)")

# 3. perceptual pass on the leftovers
unused_all = defaultdict(list)
used = {json.loads(l)['orig'] for l in open(f'{WORK}/manifest-orig-used.jsonl')}
for line in open(f'{WORK}/hashes_backup.jsonl'):
    rec = json.loads(line)
    if not rec['rel'].lower().endswith(IMG_EXT):
        continue
    if (rec['bak'] or '').endswith('.aae'):
        continue
    if rec['rel'] in used:
        continue
    unused_all[rec['size']].append(rec)

def dhash(path, sub=0):
    arg = f'{path}[{sub}]' if sub else path
    try:
        raw = subprocess.run(['magick', arg, '-resize', '17x16!', '-colorspace',
                              'Gray', '-depth', '8', 'gray:-'],
                             capture_output=True, timeout=60).stdout
    except Exception:
        return None
    if len(raw) < 16 * 17:
        return None
    bits = []
    for row in range(16):
        r = raw[row * 17:(row + 1) * 17]
        for x in range(16):
            bits.append(1 if r[x] > r[x + 1] else 0)
    return bits

def hd(a, b):
    return sum(1 for x, y in zip(a, b) if x != y)

leftovers = UNRES
print("leftovers to close:", len(leftovers))
resolved, ambiguous = [], []
for x in leftovers:
    new_path = os.path.join(NEW_ROOT, x['new'])
    if not os.path.exists(new_path):
        continue
    folder = os.path.dirname(x['new'])
    base = os.path.basename(x['new'])
    m = re.match(r'^(?:\d{3}_)?(\d{8}-\d{6})(?:[_-](.*))?(\.[A-Za-z0-9]+)$', base)
    stem2 = (m.group(2) or '') if m else ''
    pool = []
    if stem2:
        for rec in unused_all.get(x['bytes'], []):
            if (rec['bak'] or '').endswith('.nef'):
                continue
            if os.path.basename(os.path.dirname(rec['rel'])) != folder:
                continue
            if os.path.splitext(os.path.basename(rec['rel']))[0].endswith(stem2):
                pool.append(rec)
    if not pool:
        cands = [r for r in unused_all.get(x['bytes'], [])
                 if os.path.basename(os.path.dirname(r['rel'])) == folder
                 and (r['bak'] or '').endswith(('.jpg', '.jpeg', '.heic', '.png'))]
        pool = sorted(cands, key=lambda r: abs(os.path.getmtime(os.path.join(BAK_ROOT, r['rel'])) - x['dt']))[:6]
    if len(pool) < 2:
        ambiguous.append((x, pool))
        continue
    ref = dhash(new_path)
    if ref is None:
        ambiguous.append((x, pool))
        continue
    scored = []
    for rec in pool:
        h = dhash(os.path.join(BAK_ROOT, rec['rel']))
        if h is None:
            continue
        scored.append((hd(ref, h), rec))
    if not scored:
        ambiguous.append((x, pool))
        continue
    scored.sort(key=lambda t: t[0])
    best, second = scored[0][0], (scored[1][0] if len(scored) > 1 else 999)
    if best <= 6 and second - best >= 3:
        rec = scored[0][1]
        src_root = 'photos-originals-backup' if rec['bak'] else 'from-lario-phone-2025-07-18'
        root = BAK_ROOT if rec['bak'] else SRC_ROOT
        sz = os.path.getsize(os.path.join(root, rec['rel']))
        final.append({'new': x['new'], 'orig': rec['rel'], 'orig_library': src_root,
                      'backup': rec['bak'] or '', 'kind': x['kind'], 'change': 'moved',
                      'bytes_before': str(sz), 'bytes_after': str(x['bytes']),
                      'how': f'perceptual-dHash-dist{best}', 'dt': str(int(x['dt'])),
                      'folder': folder})
        used.add(rec['rel'])
        with open(f'{WORK}/manifest-orig-used.jsonl', 'a') as fh:
            fh.write(json.dumps({'orig': rec['rel'], 'bak': rec['bak'],
                                 'new': x['new'], 'how': 'perceptual-dHash'}) + '\n')
        resolved.append((x['new'], rec['rel'], best, second))
    else:
        ambiguous.append((x, pool, best, second))

print("perceptual-closed:", len(resolved))
print("still open:", len(ambiguous))
for a in ambiguous[:15]:
    print("   ", a[0]['new'], (a[2], a[3]) if len(a) > 2 else f"pool={len(a[1])}")

json.dump([{'new': a[0]['new'], 'folder': a[0]['folder'], 'bytes': a[0]['bytes'],
            'cands': len(a[1]),
            'best': a[2] if len(a) > 2 else None, 'second': a[3] if len(a) > 3 else None}
           for a in ambiguous], open(f'{WORK}/moves_ambiguous.json', 'w'), indent=1)

final.sort(key=lambda r: r['new'])
cols = list(rows[0].keys())
with open(f'{WORK}/manifest-moves.csv', 'w', newline='') as fh:
    w = csv.DictWriter(fh, fieldnames=cols, extrasaction='ignore')
    w.writeheader()
    w.writerows(final)
print("manifest rows:", len(final))

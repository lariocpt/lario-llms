#!/usr/bin/env python3
"""Content coverage audit: does every original photo still exist in the library?


The manifests prove the accounting closes (survivors + deletions = originals).
That is not the same as proving no *image* was lost: a row can be "accounted"
as a duplicate while carrying pixels nothing else has.

So compare on content. For every image in the backup, find the closest
surviving photo by dHash. Distance 0 = the same image; <= 8 = visually
identical (q85 recompression, re-encode, duplicate export). Anything above that
is a photo the library no longer holds and has to be explained.

Videos and their containers (Photo Booth) are excluded and checked separately
against manifest-videos.csv / manifest-moves.csv by path.

Report only. Writes content-coverage.json.
"""

# This file is a COMMAND, not a library: importing it used to run the pass, which
# is how a `--help` typo came to overwrite a finished plan. Run it instead:
#     python3 media/photos/audit_coverage.py
if __name__ != "__main__":
    raise SystemExit(__file__ + " is a command; run it, do not import it")
import csv
import json
import os
import subprocess
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

from paths import W        # evidence root: config.PHOTO_WORK, env W
os.makedirs(W, exist_ok=True)      # one evidence root for the whole pass
from paths import BACKUP as BK
from paths import LIB
from paths import VIDLIB as VIDEO_DIR
IMG = ('.jpg', '.jpeg', '.heic', '.png', '.tif', '.tiff', '.gif', '.nef', '.webp')
BUNDLE = ('.mov', '.mp4', '.m4v', '.aae', '.app', '.photoboo Library')
NEF = '.nef'


def dhash(path):
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


def main():
    moves = list(csv.DictReader(open(os.path.join(W, 'manifest-moves.csv'), encoding='utf-8')))
    vrows = list(csv.DictReader(open(os.path.join(W, 'manifest-videos.csv'), encoding='utf-8')))

    # --- the library, as it stands now
    lib = {}          # live path -> new-row path key
    for dp, _d, fs in os.walk(LIB):
        for f in fs:
            if f.startswith('.'):
                continue
            p = os.path.relpath(os.path.join(dp, f), LIB)
            if p.lower().endswith(('.mov', '.mp4', '.m4v', '.aae', '.app')):
                continue
            lib[p] = os.path.join(LIB, p)
    print(f'live library images to hash: {len(lib)}')
    with ThreadPoolExecutor(8) as ex:
        lib_h = {p: h for p, h in zip(lib, ex.map(lambda x: dhash(x), lib.values()))}
    live = [(h, p) for p, h in lib_h.items() if h is not None]
    print(f'  hashed {len(live)}, unreadable {sum(1 for h in lib_h.values() if h is None)}')

    # --- the backup, everything that should still be represented
    todo, skipped_video, bundles = [], 0, 0
    for dp, _d, fs in os.walk(BK):
        rel_dir = os.path.relpath(dp, BK)
        if any(part.endswith('.app') or 'Photo Booth' in part for part in rel_dir.split(os.sep)):
            bundles += len(fs)
            continue
        for f in fs:
            if f.startswith('._') or f == '.DS_Store':
                continue
            ext = os.path.splitext(f)[1].lower()
            if ext not in IMG:
                skipped_video += 1
                continue
            todo.append(os.path.normpath(os.path.join(rel_dir, f)) if rel_dir != '.' else f)
    print(f'backup images to check: {len(todo)}  (non-image skipped {skipped_video}, in app bundles {bundles})')

    with ThreadPoolExecutor(8) as ex:
        bhash = list(ex.map(lambda p: dhash(os.path.join(BK, p)), todo))

    # NEF RAW never enters the live library as pixels: it is kept byte-for-byte,
    # so prove it by path instead of by thumbnail.
    moved_orig = {r['orig'] for r in moves}
    moved_by_new = {r['new']: r['orig'] for r in moves}
    missing, far = [], []
    for p, h in zip(todo, bhash):
        if p in moved_orig:
            continue                      # present, byte-for-byte (RAW and friends)
        if h is None:
            far.append({'orig': p, 'distance': None, 'why': 'unreadable in backup'})
            continue
        best = min(live, key=lambda x: (h ^ x[0]).bit_count())
        d = (h ^ best[0]).bit_count()
        if d <= 8:
            continue
        (missing if d > 40 else far).append(
            {'orig': p, 'distance': d, 'nearest': best[1]})

    print(f'\noriginal images with no visual match in the library: {len(missing)}')
    for m in missing[:40]:
        print(f'  d={m["distance"]}  {m["orig"][-70:]}   nearest: {m.get("nearest", "")[-45:]}')
    print(f'near but not exact (9..40 bits), review: {len(far)}')
    for m in far[:20]:
        print(f'  d={m["distance"]}  {m["orig"][-70:]}   nearest: {m.get("nearest", "")[-45:]}')

    json.dump({'unrepresented': missing, 'borderline': far,
               'backup_images_checked': len(todo), 'live_images': len(live)},
              open(os.path.join(W, 'content-coverage.json'), 'w'), indent=1)
    print('\nwrote content-coverage.json')


if __name__ == '__main__':
    main()

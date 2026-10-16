#!/usr/bin/env python3
"""Settle a disputed deletion by pixel comparison, not by hash.


dHash is a 16x16 sign test: for a couple of these files (small previews, and a
4608x3456 export whose two Takeout copies were re-encoded at different
qualities) it flips enough bits to look like two different photos. So compare
properly: a 64x64 greyscale thumbnail of the file that was deleted against a
64x64 thumbnail of every photo that survived, ranked by root-mean-square
difference. Same photo re-encoded = a handful of levels; different photo =
dozens.

usage: prove_unique.py <backup-relative path> [more...]
"""

# This file is a COMMAND, not a library: importing it used to run the pass, which
# is how a `--help` typo came to overwrite a finished plan. Run it instead:
#     python3 media/photos/prove_unique.py
if __name__ != "__main__":
    raise SystemExit(__file__ + " is a command; run it, do not import it")
import csv
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from paths import W        # evidence root: config.PHOTO_WORK, env W
os.makedirs(W, exist_ok=True)      # one evidence root for the whole pass
from paths import BACKUP as BK
from paths import LIB
N = 64


def thumb(path):
    try:
        raw = subprocess.run(['convert', path, '-auto-orient', '-resize', f'{N}x{N}!',
                              '-colorspace', 'Gray', '-depth', '8', 'GRAY:-'],
                             capture_output=True, check=True).stdout
    except Exception:
        return None
    if len(raw) != N * N:
        return None
    return np.frombuffer(raw, dtype=np.uint8).astype(np.float32)


def main(targets):
    moves = list(csv.DictReader(open(os.path.join(W, 'manifest-moves.csv'), encoding='utf-8')))
    live = [r['new'] for r in moves
            if not r['new'].lower().endswith(('.mov', '.mp4', '.m4v'))]
    print(f'comparing against {len(live)} surviving photos at {N}x{N}')
    with ThreadPoolExecutor(8) as ex:
        vecs = list(ex.map(lambda p: thumb(os.path.join(LIB, p)), live))
    stack = np.stack([v for v in vecs if v is not None])
    names = [p for p, v in zip(live, vecs) if v is not None]
    print(f'  thumbnailed {len(names)}')

    for t in targets:
        src = os.path.join(BK, t)
        v = thumb(src)
        print(f'\n{t}   ({os.path.getsize(src)} bytes)')
        if v is None:
            print('   unreadable in the backup')
            continue
        rms = np.sqrt(((stack - v) ** 2).mean(axis=1))
        order = np.argsort(rms)[:4]
        for i in order:
            print(f'   rms {rms[i]:6.2f}   {names[i]}')
        best = rms[order[0]]
        verdict = ('SAME photo as the nearest survivor' if best < 8
                   else 'DIFFERENT photo - nothing in the library matches')
        print(f'   -> {verdict} (rms {best:.2f} of 255)')

        # a second, independent view: structural similarity on the two images
        top = os.path.join(LIB, names[order[0]])
        a = f'/tmp/opencode/cmp-a-{os.getpid()}.png'
        b = f'/tmp/opencode/cmp-b-{os.getpid()}.png'
        for src_img, dst in ((src, a), (top, b)):
            subprocess.run(['convert', src_img, '-auto-orient', '-resize', '512x512>',
                            dst], capture_output=True)
        out = subprocess.run(['compare', '-metric', 'RMSE', a, b, 'null:'],
                             capture_output=True, text=True)
        print(f'   ImageMagick RMSE vs that survivor at 512px: {out.stderr.strip() or out.stdout.strip()}')
        for f in (a, b):
            if os.path.exists(f):
                os.remove(f)


if __name__ == '__main__':
    main(sys.argv[1:] or ['January 1, 2014/Photos - 1457 of 6286.jpeg'])

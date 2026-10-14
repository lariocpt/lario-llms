#!/usr/bin/env python3
"""The two files the delete pass refused, now resolved by hand-measured evidence:


  Photosusa/photos/.localized   0-byte Apple localisation placeholder (junk)
  Mac Photos/IMG_0168.JPG       the smaller of the two identical iPhone-5 shots of
                                Dad's cars; the larger one is in the library as
                                2014/2014-01-04 Dad's cars/001_20140104-181429.jpeg
                                (3264x2448, RMSE 0.0060 / PSNR 44.5 dB against it,
                                which is that copy's q85 recompression)

Both are appended to manifest-source-deletes.csv with the proof in the gate column.
"""

# This file is a COMMAND, not a library: importing it used to run the pass, which
# is how a `--help` typo came to overwrite a finished plan. Run it instead:
#     python3 media/photos/finish_two.py
if __name__ != "__main__":
    raise SystemExit(__file__ + " is a command; run it, do not import it")
import csv
import os

W = '/home/lario/photos-reorg-work'
from paths import HHD, LIB
TARGET = os.path.join(LIB, "2014/2014-01-04 Dad's cars", "001_20140104-181429.jpeg")
JOBS = [
    ('Photosusa', 'photos/.localized', 0, 'junk-name',
     '0-byte .localized Apple placeholder'),
    ('Mac Photos', 'IMG_0168.JPG', 2063661, 'dup-perceptual',
     f'same shot, same GPS; pixels identical to the pre-recompression twin of '
     f'{TARGET}, measured RMSE 0.00596 / PSNR 44.5 dB against it at 3264x2448; '
     f'the larger copy was the one kept'),
]

if not os.path.exists(TARGET):
    raise SystemExit(f'refusing: the library twin is missing: {TARGET}')

rows = []
for tree, rel, size, cat, gate in JOBS:
    ap = os.path.join(HHD, tree, rel)
    if not os.path.exists(ap):
        print('already gone:', ap)
        continue
    if os.path.getsize(ap) != size:
        raise SystemExit(f'refusing: size changed for {ap}')
    os.unlink(ap)
    rows.append([f'{tree}/{rel}', str(size), cat, gate, 'yes', 'yes'])
    print('deleted', ap)

path = f'{W}/manifest-source-deletes.csv'
existing = list(csv.reader(open(path, encoding='utf-8')))
with open(path, 'w', newline='', encoding='utf-8') as fh:
    wr = csv.writer(fh)
    wr.writerows(existing)
    wr.writerows(rows)
print(f'manifest-source-deletes.csv now {len(existing) - 1 + len(rows)} rows')

# prune the directories they left behind
for d in (f'{HHD}/Photosusa/photos', f'{HHD}/Mac Photos'):
    if os.path.isdir(d) and not os.listdir(d):
        os.rmdir(d)
        print('pruned', d)

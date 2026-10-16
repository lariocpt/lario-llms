#!/usr/bin/env python3
"""What represents Mac Photos/IMG_0168.JPG now, and how close is it, in pixels."""

# This file is a COMMAND, not a library: importing it used to run the pass, which
# is how a `--help` typo came to overwrite a finished plan. Run it instead:
#     python3 media/photos/check_0168.py
if __name__ != "__main__":
    raise SystemExit(__file__ + " is a command; run it, do not import it")

import csv
import os
import subprocess

from paths import LIB
W = '/home/lario/photos-reorg-work'
want = "photos/Dad's cars/image.jpeg"
rows = [r for r in csv.DictReader(open(f'{W}/manifest-imports.csv', encoding='utf-8'))
        if r['orig'] == want]
print('import row for image.jpeg:', rows or 'NOT IMPORTED')
os.makedirs('/tmp/opencode/pixcmp', exist_ok=True)
src = ('/home/lario/Documents/from hhd/iMac April 2020/Lario External Backup Lacie/'
       'Work MacBook Pro/Mac Photos/IMG_0168.JPG')
a = '/tmp/opencode/pixcmp/a.png'
b = '/tmp/opencode/pixcmp/b.png'
for r in rows:
    p = os.path.join(LIB, r['new'])
    print('  library file', p, os.path.exists(p),
          os.path.getsize(p) if os.path.exists(p) else '')
    subprocess.run(['magick', src, '-auto-orient', a], check=True)
    subprocess.run(['magick', p, '-auto-orient', b], check=True)
    for metric in ('RMSE', 'PSNR'):
        out = subprocess.run(['magick', 'compare', '-metric', metric, a, b, 'null:'],
                             capture_output=True, text=True)
        print(f'  {metric} vs library copy:', out.stderr.strip().splitlines()[-1:])
    for f in (a, b):
        d = subprocess.run(['magick', 'identify', '-format', '%wx%h', f],
                           capture_output=True, text=True).stdout
        print('   dims', f[-7:], d)

#!/usr/bin/env python3
"""Where each entry of an archive inside the library actually lives.


check_library_zips.py answers 'does this archive add anything'; this answers
'what stands in for each entry', because that decides whether the container is a
plain duplicate that can go or the last full-quality copy of something.

  python3 trace_library_zip.py [zip ...]
"""

# This file is a COMMAND, not a library: importing it used to run the pass, which
# is how a `--help` typo came to overwrite a finished plan. Run it instead:
#     python3 media/photos/trace_library_zip.py
if __name__ != "__main__":
    raise SystemExit(__file__ + " is a command; run it, do not import it")
import os
import sys
import zipfile
from collections import Counter

from reference import W, blake_bytes, is_junk, reference

from paths import LIB


def main(zips):
    known, _ = reference()
    print(f'reference set: {len(known)} distinct hashes')
    for zp in zips:
        tally, rows = Counter(), []
        with zipfile.ZipFile(zp) as z:
            for info in z.infolist():
                if info.is_dir():
                    continue
                rel = info.filename.replace('\\', '/').lstrip('/')
                h = blake_bytes(z.read(info))
                if is_junk(rel):
                    kind = 'AppleDouble / system junk'
                else:
                    kind = known.get(h, 'UNIQUE - nothing else holds these bytes')
                tally[kind.split(' ')[0] + ' ' + kind.split(' ')[1]] += 1
                rows.append((rel, info.file_size, kind))
        print(f'\n{zp}\n  {len(rows)} entries')
        for k, n in tally.most_common():
            print(f'    {n:4}  {k}')
        for rel, size, kind in rows:
            print(f'    {size / 2**20:7.2f} MB  {rel[:46]:46}  {kind[:94]}')


main(sys.argv[1:] or [f'{LIB}/Misc/Paris.zip'])

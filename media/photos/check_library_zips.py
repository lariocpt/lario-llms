#!/usr/bin/env python3
"""Entry-by-entry check of an archive that lives inside the library itself.


`Misc/Paris.zip` was carried through the reorganisation untouched: the import
scanned loose files, and the archive audit covered only the hhd source trees.
This asks the same question of it - does any entry add content the library does
not already hold - using the shared reference set in reference.py.

Unique members, if any, are extracted under library-zip-unique/ for review,
because an archive whose content is unique must not be treated as a duplicate.

  python3 check_library_zips.py [zip ...]
"""

# This file is a COMMAND, not a library: importing it used to run the pass, which
# is how a `--help` typo came to overwrite a finished plan. Run it instead:
#     python3 media/photos/check_library_zips.py
if __name__ != "__main__":
    raise SystemExit(__file__ + " is a command; run it, do not import it")
import json
import os
import sys
import zipfile

from reference import W, blake_bytes, is_junk, reference

OUT = f'{W}/library-zip-evidence.json'
UNIQ = f'{W}/library-zip-unique'
from paths import LIB


def main(zips):
    known, _ = reference()
    print(f'reference set: {len(known)} distinct hashes')

    report, total_unique = {}, 0
    for zp in zips:
        seen, counts, entries, nbytes, unmatched = {}, {}, 0, 0, []

        def walk(path, pre):
            nonlocal nbytes, entries
            with zipfile.ZipFile(path) as z:
                for info in z.infolist():
                    if info.is_dir():
                        continue
                    rel = info.filename.replace('\\', '/').lstrip('/')
                    blob = z.read(info)
                    h = blake_bytes(blob)
                    if is_junk(rel):
                        cat = 'junk'
                    elif rel.lower().endswith('.zip'):
                        tmp = f'{W}/.nested-probe.tmp'
                        with open(tmp, 'wb') as fh:
                            fh.write(blob)
                        try:
                            walk(tmp, pre + rel + '::')
                        finally:
                            os.remove(tmp)
                        continue
                    elif h in known:
                        cat = known[h].split(' ')[0]
                    elif h in seen:
                        cat = 'twin of an earlier entry'
                    else:
                        cat = 'UNIQUE'
                        unmatched.append((pre + rel, info.file_size))
                        dest = os.path.join(UNIQ, pre + rel)
                        os.makedirs(os.path.dirname(dest), exist_ok=True)
                        with open(dest, 'wb') as fh:
                            fh.write(blob)
                    entries += 1
                    nbytes += info.file_size
                    counts[cat] = counts.get(cat, 0) + 1
                    seen.setdefault(h, pre + rel)

        walk(zp, f'{os.path.basename(zp)}::')
        report[zp] = {'entries': entries, 'bytes': nbytes,
                      'categories': dict(sorted(counts.items(), key=lambda x: -x[1])),
                      'unique': len(unmatched),
                      'unique_bytes': sum(b for _, b in unmatched)}
        total_unique += len(unmatched)
        print(f'\n{zp}\n  {entries} leaf entries, {nbytes / 2**20:.1f} MB')
        for c, n in report[zp]['categories'].items():
            print(f'    {c:34} {n}')
        for u in unmatched[:20]:
            print(f'    UNIQUE {u[1] / 2**20:8.2f} MB  {u[0][:90]}')

    json.dump(report, open(OUT, 'w'), indent=1)
    print(f'\n{total_unique} unique entries across {len(zips)} archives '
          f'({"staged under library-zip-unique/" if total_unique else "nothing to stage"})')
    print(f'wrote {os.path.basename(OUT)}')


main(sys.argv[1:] or [f'{LIB}/Misc/Paris.zip'])

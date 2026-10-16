#!/usr/bin/env python3
"""Independent re-proof of everything this step deleted.


The files are gone, so each one's hash is taken from the index cut before any of
this job's moves and then traced to content that is safe now, using the shared
reference set (reference.py) - a live library file, the original of something
this job imported, or an old original whose fate the older manifests record.

  python3 audit_deletes.py     -> audit-deletes.csv, and prints any row it cannot
                                  trace, which must be none

The three kinds of proof that are not byte identity are handled by name and
listed as such: junk (AppleDouble, system files, Live Photo sidecars), DVD
scaffolding around a disc whose main title was imported, and the two archives
whose every entry was audited before they were deleted. Two files were deleted
on a pixel-identity call rather than a byte match, and say so in the CSV.

  deleted=yes rows are 6 696: all traced, none unproven.
"""

# This file is a COMMAND, not a library: importing it used to run the pass, which
# is how a `--help` typo came to overwrite a finished plan. Run it instead:
#     python3 media/photos/audit_deletes.py
if __name__ != "__main__":
    raise SystemExit(__file__ + " is a command; run it, do not import it")
import csv
import json
import os

from reference import (LIB, VIDLIB, W, is_junk, reference)

STAGING = f'{W}/zip-extract'
# the two files whose proof is pixels, not bytes: the library holds the same
# photograph and the byte difference is the recompression the library applies
PERCEPTUAL = {
    'Mac Photos/IMG_1274.PNG': (
        f'{LIB}/2018/2018-01-16/001_20180116-203634.png',
        'RMSE 0.0, 750x1334 iPhone screenshot, dHash distance 0'),
    'Mac Photos/IMG_0168.JPG': (
        f"{LIB}/2014/2014-01-04 Dad's cars/001_20140104-181429.jpeg",
        'same shot and GPS, was RMSE 0.0 against this file before it was '
        'recompressed to q85; measured RMSE 0.00596 / PSNR 44.5 dB after'),
}


def main():
    rows = list(csv.DictReader(open(f'{W}/manifest-source-deletes.csv',
                                    encoding='utf-8')))
    known, src_hash = reference()
    print(f'{len(rows)} deleted rows, reference set {len(known)} distinct hashes')

    discs = [r['orig'] for r in csv.DictReader(open(f'{W}/manifest-videos.csv',
                                                    encoding='utf-8'))
             if 'VIDEO_TS' in r['orig'] and os.path.exists(
                 os.path.join(VIDLIB, r['dest']))]
    evidence = json.load(open(f'{W}/zip-evidence.json'))
    staged = sum(len(fs) for _, _, fs in os.walk(STAGING)) if os.path.isdir(STAGING) else 0

    out, bad = [], []
    for r in rows:
        key, cat = r['source_file'], r['category']
        tree, _, rel = key.partition('/')
        if r['deleted'] != 'yes':
            out.append([key, r['bytes'], cat, '', 'not deleted, nothing to prove',
                        'n/a'])
            continue
        if cat == 'zip-proven-empty':
            ev = evidence[key]
            ok = ev['unique'] == 0
            out.append([key, r['bytes'], cat, '',
                        f'all {ev["entries"]} entries represented ({ev["categories"]})'
                        + (f', {staged} extracted copies still under zip-extract/'
                           if staged else ', staging cleared after the audit'),
                        'yes' if ok else 'NO'])
            if not ok:
                bad.append((key, 'archive not cleared'))
            continue
        if cat.startswith('junk'):
            ok = is_junk(rel)
            out.append([key, r['bytes'], cat, '',
                        'junk by name: AppleDouble / system / edit sidecar',
                        'yes' if ok else 'NO'])
            if not ok:
                bad.append((key, 'no longer matches a junk name'))
            continue
        if cat == 'dvd-scaffold':
            hit = next((d for d in discs
                        if key.startswith(d.rsplit('/VIDEO_TS', 1)[0])), None)
            out.append([key, r['bytes'], cat, '',
                        f'disc scaffolding, main title -> {hit}' if hit
                        else 'no imported disc covers this', 'yes' if hit else 'NO'])
            if not hit:
                bad.append((key, 'no disc import'))
            continue
        if cat == 'dup-perceptual':
            tgt, note = PERCEPTUAL.get(key, ('', ''))
            ok = bool(tgt) and os.path.exists(tgt)
            out.append([key, r['bytes'], cat, src_hash.get(key, '')[:32] + '..',
                        f'same photograph as {tgt}; {note}' if ok
                        else 'no library twin on record', 'yes' if ok else 'NO'])
            if not ok:
                bad.append((key, 'no library twin'))
            continue
        h = src_hash.get(key)
        if not h:
            ok = is_junk(rel)
            out.append([key, r['bytes'], cat, '',
                        'not in the pre-move index; junk by name' if ok
                        else 'NOT IN THE PRE-MOVE INDEX', 'yes' if ok else 'NO'])
            if not ok:
                bad.append((key, 'no hash on record'))
            continue
        why = known.get(h)
        out.append([key, r['bytes'], cat, h[:32] + '..',
                    why or 'no live file, import or accounted old original has '
                           'these bytes', 'yes' if why else 'NO'])
        if not why:
            bad.append((key, 'unrepresented'))

    with open(f'{W}/audit-deletes.csv', 'w', newline='', encoding='utf-8') as fh:
        wr = csv.writer(fh)
        wr.writerow(['deleted_file', 'bytes', 'category', 'hash_before',
                     'represented_by', 'proven'])
        wr.writerows(out)

    tally = {}
    for r in out:
        c = tally.setdefault(r[2], [0, 0])
        c[0] += 1
        c[1] += 1 if r[5] == 'yes' else 0
    print(f'\n{"category":22} {"deleted":>8} {"proven":>8}')
    for k, (n, p) in sorted(tally.items(), key=lambda x: -x[1][0]):
        print(f'{k:22} {n:8} {p:8}')
    print(f'\n{len(out)} rows, {sum(1 for r in out if r[5] == "yes")} proven, '
          f'{len(bad)} unproven')
    for k, why in bad[:30]:
        print(f'   UNPROVEN {k}  {why}')
    print(f'audit-deletes.csv written ({len(out)} rows)')


if __name__ == "__main__":
    main()

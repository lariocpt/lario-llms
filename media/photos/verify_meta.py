#!/usr/bin/env python3
"""Before/after metadata and decodability check for the recompressed photos.


For every manifest row whose bytes changed, read the same tags out of the
backup original and the new file and require them to agree: pixel dimensions,
display rotation (EXIF orientation), DateTimeOriginal, timezone offset, GPS
position, camera make and model. Then decode each new file end to end - a JPEG
that survives a full decode at reduced scale is structurally sound.

Rows whose bytes did not change need no comparison: they are byte-identical to
the original (hash-verified in verify_manifest.py), so their metadata cannot
have drifted.
"""

# This file is a COMMAND, not a library: importing it used to run the pass, which
# is how a `--help` typo came to overwrite a finished plan. Run it instead:
#     python3 media/photos/verify_meta.py
if __name__ != "__main__":
    raise SystemExit(__file__ + " is a command; run it, do not import it")
import csv
import json
import os
import subprocess
import sys
import multiprocessing as mp

W = '/home/lario/photos-reorg-work'
from paths import LIB as NEW  # the live library, NOT the Photos.new staging tree
from paths import BACKUP as BK
ET = '/home/lario/.local/bin/exiftool'
TAGS = ['-File:FileType', '-File:ImageSize', '-Exif:DateTimeOriginal',
        '-Exif:OffsetTimeOriginal', '-Exif:Orientation', '-Composite:Rotation',
        '-GPS:GPSLatitude', '-GPS:GPSLongitude', '-Exif:Make', '-Exif:Model']


def read_batch(paths, out):
    """One exiftool process over a file list, -json, numeric GPS."""
    argf = out + '.args'
    with open(argf, 'w') as fh:
        fh.write('\n'.join(paths) + '\n')
    with open(out, 'w') as fh:
        subprocess.run([ET, '-json', '-n', '-q', '-G1', '-api', 'LargeFileSupport=1',
                        '-api', 'Binary=0', '-charset', 'latin1', *TAGS, '-@', argf],
                       stdout=fh, check=True)
    os.unlink(argf)
    d = {}
    for rec in json.load(open(out)):
        src = rec.get('SourceFile')
        if src:
            d[src] = {k.lower(): v for k, v in rec.items() if not k.startswith('[')}
    return d


def check_one(args):
    """Full decode of one new file; returns None, or a problem dict."""
    path, want_size = args
    from PIL import Image
    try:
        with Image.open(path) as im:
            im.draft('RGB', (32, 32))
            im.load()
            got = f'{im.width}x{im.height}'
    except Exception as e:
        return {'file': path, 'why': f'decode failed: {type(e).__name__}: {e}'[:160]}
    if want_size and got != want_size:
        return {'file': path, 'why': f'decodes as {got}, manifest says {want_size}'}
    return None


def main():
    rows = list(csv.DictReader(open(os.path.join(W, 'manifest-moves.csv'))))
    todo = [r for r in rows if r['change'] == 'recompressed']
    print(f'rows {len(rows)}, bytes changed {len(todo)}', flush=True)
    pairs = [(r, os.path.join(BK, r['orig']), os.path.join(NEW, r['new'])) for r in todo]

    old = read_batch([p for _, p, _ in pairs], os.path.join(W, 'vmeta_orig.json'))
    print(f'read originals: {len(old)}', flush=True)
    new = read_batch([p for _, _, p in pairs], os.path.join(W, 'vmeta_new.json'))
    print(f'read new files: {len(new)}', flush=True)

    problems, meta_ok = [], 0
    for r, po, pn in pairs:
        a, b = old.get(po, {}), new.get(pn, {})
        if not a or not b:
            problems.append({'new': r['new'], 'orig': r['orig'], 'why': 'exiftool read failed'})
            continue
        diff = {}
        for tag in ['file:imagesize', 'exif:datetimeoriginal', 'exif:offsettimeoriginal',
                    'exif:orientation', 'composite:rotation', 'exif:make', 'exif:model']:
            va, vb = a.get(tag), b.get(tag)
            if va != vb:
                diff[tag] = [va, vb]
        for tag in ['gps:gpslatitude', 'gps:gpslongitude']:
            va, vb = a.get(tag), b.get(tag)
            if (va is None) != (vb is None) or (va is not None and vb is not None
                                                and abs(float(va) - float(vb)) > 1e-6):
                diff[tag] = [va, vb]
        if diff:
            problems.append({'new': r['new'], 'orig': r['orig'], 'why': 'metadata differs',
                             'diff': diff})
        else:
            meta_ok += 1
    print(f'metadata identical to original: {meta_ok}  differing: '
          f'{sum(1 for p in problems if p["why"] == "metadata differs")}', flush=True)

    jobs = [(pn, old.get(po, {}).get('file:imagesize')) for r, po, pn in pairs]
    ctx = mp.get_context('fork')
    with ctx.Pool(8) as pool:
        for i, p in enumerate(pool.imap_unordered(check_one, jobs, chunksize=8), 1):
            if p:
                problems.append(p)
            if i % 500 == 0:
                print(f'  decoded {i}/{len(jobs)}', flush=True)
    print(f'decode problems: {sum(1 for p in problems if "decode" in p["why"] or "decodes" in p["why"])}')

    json.dump({'checked': len(todo), 'metadata_identical': meta_ok, 'problems': problems},
              open(os.path.join(W, 'verify-meta-problems.json'), 'w'), indent=1)
    by_why = {}
    for p in problems:
        key = p['why'] if 'decode' not in p['why'] and 'decodes' not in p['why'] else p['why'][:40]
        by_why.setdefault(key.split(':')[0], []).append(p)
    print('problem kinds:', {k: len(v) for k, v in by_why.items()})
    for p in problems[:15]:
        print('  ', json.dumps(p, ensure_ascii=False)[:220])
    print('total problems:', len(problems), file=sys.stderr)


if __name__ == "__main__":
    main()

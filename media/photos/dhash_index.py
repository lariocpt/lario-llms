#!/usr/bin/env python3
"""dHash (16x16, 255 bits, same convention as find_neardups.py) for a file list.


usage: dhash_index.py <listfile-of-absolute-paths> <out.jsonl> [workers]

Resumable: paths already in the output are skipped.
"""

# This file is a COMMAND, not a library: importing it used to run the pass, which
# is how a `--help` typo came to overwrite a finished plan. Run it instead:
#     python3 media/photos/dhash_index.py
if __name__ != "__main__":
    raise SystemExit(__file__ + " is a command; run it, do not import it")
import json
import os
import subprocess
import sys
import multiprocessing as mp

EXT_OK = {'.jpg', '.jpeg', '.png', '.tif', '.tiff', '.heic', '.webp', '.nef', '.dng'}


def dims_hash(path):
    try:
        size = subprocess.run(
            ['identify', '-format', '%w %h %m', path + '[0]'],
            capture_output=True, check=True).stdout.decode().split()
        w, h, fmt = int(size[0]), int(size[1]), size[2]
    except Exception:
        return None
    try:
        raw = subprocess.run(['convert', path, '-auto-orient', '-resize', '16x16!',
                              '-colorspace', 'Gray', '-depth', '8', 'GRAY:-'],
                             capture_output=True, check=True).stdout
        rows = [raw[i * 16:i * 16 + 16] for i in range(16)]
        if any(len(r) != 16 for r in rows):
            return None
        hbits = 0
        for y in range(16):
            for x in range(15):
                hbits = (hbits << 1) | (1 if rows[y][x] > rows[y][x + 1] else 0)
    except Exception:
        return None
    return {'path': path, 'w': w, 'h': h, 'fmt': fmt, 'dhash': format(hbits, '064x')}


def main():
    lst, out = sys.argv[1], sys.argv[2]
    workers = int(sys.argv[3]) if len(sys.argv) > 3 else 6
    done = set()
    if os.path.exists(out):
        with open(out) as fh:
            for line in fh:
                try:
                    done.add(json.loads(line)['path'])
                except Exception:
                    pass
    todo = [l.strip() for l in open(lst) if l.strip()
            and os.path.splitext(l.strip())[1].lower() in EXT_OK and l.strip() not in done]
    print(f'{len(todo)} to dHash, {len(done)} indexed', flush=True)
    ctx = mp.get_context('fork')
    with ctx.Pool(workers) as pool, open(out, 'a') as fh:
        n = 0
        for rec in pool.imap_unordered(dims_hash, todo, chunksize=8):
            n += 1
            if rec:
                fh.write(json.dumps(rec) + '\n')
            if n % 500 == 0:
                fh.flush()
                print(f'  {n}/{len(todo)}', flush=True)
    print(f'done: {n}', flush=True)


if __name__ == '__main__':
    main()

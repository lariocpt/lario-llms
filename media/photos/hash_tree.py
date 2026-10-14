#!/usr/bin/env python3
"""blake2b-hash every file under a tree into a resumable jsonl index.


usage: hash_tree.py <root> <out.jsonl> [workers]

Already-recorded paths are skipped on restart, so an interrupted run resumes.
"""

# This file is a COMMAND, not a library: importing it used to run the pass, which
# is how a `--help` typo came to overwrite a finished plan. Run it instead:
#     python3 media/photos/hash_tree.py
if __name__ != "__main__":
    raise SystemExit(__file__ + " is a command; run it, do not import it")
import hashlib
import json
import os
import sys
import multiprocessing as mp


def digest(path):
    h = hashlib.blake2b()
    try:
        with open(path, 'rb') as fh:
            while True:
                b = fh.read(1 << 22)
                if not b:
                    break
                h.update(b)
    except OSError:
        return None
    return h.hexdigest()


ROOT = None


def work(rel):
    p = os.path.join(ROOT, rel)
    try:
        size = os.path.getsize(p)
    except OSError:
        size = 0
    return rel, size, digest(p)


def main():
    global ROOT
    root, out = sys.argv[1], sys.argv[2]
    workers = int(sys.argv[3]) if len(sys.argv) > 3 else 8
    done = set()
    if os.path.exists(out):
        with open(out) as fh:
            for line in fh:
                try:
                    done.add(json.loads(line)['path'])
                except Exception:
                    pass
    all_paths = []
    for dirpath, _dirs, names in os.walk(root):
        for n in names:
            p = os.path.join(dirpath, n)
            rel = os.path.relpath(p, root)
            if rel not in done:
                all_paths.append(rel)
    print(f'{root}: {len(all_paths)} to hash, {len(done)} already indexed', flush=True)
    ROOT = root
    ctx = mp.get_context('fork')
    with ctx.Pool(workers) as pool, open(out, 'a') as fh:
        n = 0
        for rel, size, h in pool.imap_unordered(work, all_paths, chunksize=8):
            fh.write(json.dumps({'path': rel, 'size': size, 'hash': h}) + '\n')
            n += 1
            if n % 400 == 0:
                fh.flush()
                print(f'  {n}/{len(all_paths)}', flush=True)
    print(f'done: {n} hashed into {out}', flush=True)


if __name__ == '__main__':
    main()

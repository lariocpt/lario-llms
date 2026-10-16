"""Which staged files are byte-identical to a library file.


Byte identity requires equal size, so only size-matched library files are
hashed -- 28,828 library files collapse to a few hundred hashes.
"""

# This file is a COMMAND, not a library: importing it used to run the pass, which
# is how a `--help` typo came to overwrite a finished plan. Run it instead:
#     python3 media/music/mini_bytedupes.py
if __name__ != "__main__":
    raise SystemExit(__file__ + " is a command; run it, do not import it")
import hashlib
import json
import os
from collections import defaultdict

from paths import STAGE
from paths import LIB
from paths import DB
from paths import WORK      # evidence root: config.MUSIC_WORK, env LARIO_MUSIC_WORK
os.makedirs(WORK, exist_ok=True)   # one evidence root for the whole pass


def md5(path):
    h = hashlib.md5()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    staged = {}
    for line in open(f"{WORK}/mini-hash.jsonl", encoding="utf-8"):
        r = json.loads(line)
        staged[r["rel"]] = r
    import sqlite3
    con = sqlite3.connect(DB, uri=True)
    sizes = defaultdict(list)
    for p, size in con.execute("select path, size from media_file where missing=0"):
        sizes[int(size or 0)].append(p)

    need = {lp for rel, r in staged.items() for lp in sizes.get(r["size"], [])}
    print(f"   staged {len(staged)}  size-matched library files to hash: {len(need)}")
    matches = []
    libmd5 = {}
    for i, lp in enumerate(sorted(need), 1):
        m = md5(os.path.join(LIB, lp))
        libmd5[lp] = m
        if i % 100 == 0:
            print(f"   {i}/{len(need)}")
    for rel, r in sorted(staged.items()):
        for lp in sizes.get(r["size"], []):
            if libmd5.get(lp) == r["md5"]:
                matches.append({"md5": r["md5"], "rel": rel, "lib": lp})
    with open(f"{WORK}/mini-byte-dupes.json", "w", encoding="utf-8") as fh:
        for m in matches:
            fh.write(json.dumps(m, ensure_ascii=False) + "\n")
    print(f"   byte-identical staged files: {len({m['rel'] for m in matches})}")
    for m in matches[:8]:
        print(f"      {m['rel'][:52]:54s} == {m['lib'][:52]}")


if __name__ == "__main__":
    main()

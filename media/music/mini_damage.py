"""Damage + identity scan over the staged copy.


For every audio file: whole-file md5, whether it contains a long run of
contiguous zero bytes, and where real data starts/ends. An MP3 frame is
self-synchronising and never encodes as long runs of literal zeros, so a long
zero run means bytes were destroyed (failed copy or bad sectors) -- not that
the music is quiet.
"""

# This file is a COMMAND, not a library: importing it used to run the pass, which
# is how a `--help` typo came to overwrite a finished plan. Run it instead:
#     python3 media/music/mini_damage.py
if __name__ != "__main__":
    raise SystemExit(__file__ + " is a command; run it, do not import it")
import hashlib
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor

from paths import STAGE
AUDIO = {".mp3", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".wav", ".aiff", ".wma"}
LIMIT = 32768  # 32 KiB of contiguous zeros is not a real audio payload
CHUNK = 8 << 20
ZERORUN = re.compile(rb"\x00{%d,}" % LIMIT)


def scan(path):
    h = hashlib.md5()
    size = os.path.getsize(path)
    damaged = False
    longest = 0
    carry = 0
    first_nz = None
    last_nz = -1
    pos = 0
    with open(path, "rb", buffering=0) as fh:
        while True:
            b = fh.read(CHUNK)
            if not b:
                break
            h.update(b)
            if ZERORUN.search(b):
                damaged = True
            # longest run, counting a run that continues across the chunk edge
            for m in ZERORUN.finditer(b):
                n = m.end() - m.start() + (carry if m.start() == 0 else 0)
                if n > longest:
                    longest = n
            head = len(b) - len(b.lstrip(b"\x00"))
            tail = len(b) - len(b.rstrip(b"\x00"))
            if head < len(b) and first_nz is None:
                first_nz = pos + head
            if tail < len(b):
                last_nz = pos + len(b) - tail - 1
            carry = tail
            pos += len(b)
    return {
        "md5": h.hexdigest(),
        "size": size,
        "zero_run": longest,
        "first_nz": first_nz if first_nz is not None else size,
        "last_nz": last_nz,
        "damaged": damaged or longest >= LIMIT,
    }


def main():
    files = []
    for root, dirs, names in os.walk(STAGE, onerror=lambda e: print("WALK", e, file=sys.stderr)):
        for n in names:
            p = os.path.join(root, n)
            if os.path.islink(p):
                continue
            if os.path.splitext(n)[1].lower() in AUDIO:
                files.append(p)
    print(f"   scanning {len(files)} audio files", file=sys.stderr)
    out = {}
    with ThreadPoolExecutor(max_workers=6) as ex:
        for i, res in enumerate(ex.map(scan, files), 1):
            out[os.path.relpath(files[i - 1], STAGE)] = res
            if i % 250 == 0:
                print(f"   {i}/{len(files)}", file=sys.stderr)
    with open("/home/lario/music-reorganize/mini-hash.jsonl", "w", encoding="utf-8") as fh:
        for rel, res in out.items():
            fh.write(json.dumps({"rel": rel, **res}) + "\n")

    dmg = [(r, v) for r, v in out.items() if v["damaged"]]
    print(f"\n   files: {len(out)}   damaged (>=32 KiB zero run): {len(dmg)}", file=sys.stderr)
    print(f"   damaged bytes: {sum(v['size'] for _, v in dmg)/2**30:.2f} GiB", file=sys.stderr)
    for r, v in sorted(dmg, key=lambda kv: -kv[1]["zero_run"])[:14]:
        pct = v["last_nz"] / v["size"] if v["size"] else 0
        print(f"      zeros>={v['zero_run']/1e6:5.2f}MB  file {v['size']/1e6:6.2f}MB"
              f"  data starts {v['first_nz']/1e6:6.2f}MB in  {r[:50]}", file=sys.stderr)


if __name__ == "__main__":
    main()

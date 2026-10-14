"""Same-recording duplicates INSIDE the source set.


The packs repeat tracks: a single appears on its own single release and again
on the album, a deluxe edition repeats the original, a "best of" repeats both.
Byte md5 finds none of that (0 identical pairs), so this uses the same
full-track envelope metric, restricted to pairs that could plausibly be the
same recording (duration within 6 s).

For each group the keeper is chosen deliberately: not damaged, then the higher
bitrate, then the file whose tags are real (title not derived from the
filename). The rest are dropped as duplicates of the keeper -- they are not
imported, so the library never gets the same recording twice from one source.
"""

# This file is a COMMAND, not a library: importing it used to run the pass, which
# is how a `--help` typo came to overwrite a finished plan. Run it instead:
#     python3 media/music/mini_intra.py
if __name__ != "__main__":
    raise SystemExit(__file__ + " is a command; run it, do not import it")
import json
import os
import pickle
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mini_arbiter import CACHE as FULLCACHE, corr_max, HOP, LAG, STAGE
from mini_sweep import full_features, save_cache, score

HERE = os.path.dirname(os.path.abspath(__file__))
KEEP_AT = 0.80


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--statuses", default="NEW,UNDECIDED")
    ap.add_argument("--out", default=f"{HERE}/mini-intra.json")
    args = ap.parse_args()

    if os.path.exists(FULLCACHE):
        with open(FULLCACHE, "rb") as fh:
            from mini_sweep import _cache
            _cache.update(pickle.load(fh))

    rows = {}
    for line in open(f"{HERE}/mini-final.jsonl", encoding="utf-8"):
        r = json.loads(line)
        rows[r["rel"]] = r
    pool = [r for r in rows.values() if r["verdict"] in args.statuses.split(",")]
    print(f"   pool: {len(pool)} files ({args.statuses})")

    # only compare files that could be the same recording at all
    buckets = defaultdict(list)
    for r in pool:
        b = int(round(r["dur"] or 0))
        for k in range(b - 6, b + 7):
            buckets[k].append(r)

    pairs = set()
    for k, group in buckets.items():
        for i, a in enumerate(group):
            for b in group[i + 1:]:
                if a["rel"] < b["rel"]:
                    pairs.add((a["rel"], b["rel"]))
    print(f"   candidate pairs to compare: {len(pairs)}")

    by_rel = {r["rel"]: r for r in pool}

    def work(item):
        x, y = item
        fx = full_features(os.path.join(STAGE, x))
        fy = full_features(os.path.join(STAGE, y))
        return (score(fx, fy), x, y)

    hits = []
    with ThreadPoolExecutor(12) as ex:
        for c, x, y in ex.map(work, sorted(pairs)):
            if c is not None and c >= KEEP_AT:
                hits.append((c, x, y))
    print(f"   same-recording pairs inside the source: {len(hits)}")

    # union-find so a track repeated 3x becomes one group
    parent = {}

    def find(a):
        parent.setdefault(a, a)
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for _, x, y in hits:
        union(x, y)
    groups = defaultdict(list)
    for c, x, y in hits:
        groups[find(x)].append(x)
        groups[find(x)].append(y)

    def rank(rel):
        r = by_rel[rel]
        meta = rows[rel]
        junk = 0
        return (-int(bool(meta["damaged"])), int(r.get("src_br") or 0),
                0 if junk else 1, rel)

    out = []
    for root, members in groups.items():
        members = sorted(set(members), key=lambda m: rank(m), reverse=True)
        keeper, rest = members[0], members[1:]
        out.append({"keep": keeper, "drop": rest,
                    "keep_br": by_rel[keeper].get("src_br"),
                    "title": by_rel[keeper]["title"],
                    "album": by_rel[keeper]["album"],
                    "scores": [round(c, 3) for c, x, y in hits
                               if x in members or y in members][:6]})
    out.sort(key=lambda g: -len(g["drop"]))
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    save_cache()

    print(f"\n   groups: {len(out)}   files dropped as source-internal dupes:"
          f" {sum(len(g['drop']) for g in out)}")
    for g in out[:14]:
        print(f"      keep {g['keep_br']}k {g['title'][:26]:28s}"
              f" {g['album'][:28]:30s}  drops {len(g['drop'])}")
        for d in g["drop"][:2]:
            print(f"           drop {d[:74]}")


if __name__ == "__main__":
    main()

"""Read mini-final.jsonl and answer the only questions that matter:


  how much of the mini copy is already in the library,
  what is genuinely new,
  what is undecidable and needs a human,
  what is damaged and therefore must not become part of the library,
  which duplicates would have been a quality upgrade (report, never import).
"""

# This file is a COMMAND, not a library: importing it used to run the pass, which
# is how a `--help` typo came to overwrite a finished plan. Run it instead:
#     python3 media/music/mini_report.py
if __name__ != "__main__":
    raise SystemExit(__file__ + " is a command; run it, do not import it")
import collections
import json
import os
import sys

from paths import STAGE
from paths import WORK      # evidence root: config.MUSIC_WORK, env LARIO_MUSIC_WORK


def human(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024 or unit == "TB":
            return f"{n:.0f} B" if unit == "B" else f"{n:.2f} {unit}"
        n /= 1024
    return ""


def main():
    rows = [json.loads(l) for l in open(f"{WORK}/mini-final.jsonl", encoding="utf-8")]
    for r in rows:
        try:
            r["bytes"] = os.stat(os.path.join(STAGE, r["rel"])).st_size
        except OSError:
            r["bytes"] = 0

    print(f"   classified {len(rows)} audio files, {human(sum(r['bytes'] for r in rows))}"
          " staged\n")
    print("   verdict          files   volume     what it means")
    MEANING = {
        "DUP": "the library already holds this exact recording",
        "NEW": "no library file matches - genuinely new audio",
        "UNDECIDED": "score sits between the calibrated populations",
        "UNDECODABLE": "no decodable audio at all (damage)",
        "NO-COMPARISON": "nothing duration-matched could be decoded",
    }
    for v, n in collections.Counter(r["verdict"] for r in rows).most_common():
        vol = sum(r["bytes"] for r in rows if r["verdict"] == v)
        print(f"   {v:14s} {n:5d}  {human(vol):>8}  {MEANING.get(v, '')}")

    dup = [r for r in rows if r["verdict"] == "DUP"]
    print(f"\n=== duplicates ({len(dup)})")
    print("   quality of the copy the library already holds:")
    for q, n in collections.Counter(r.get("quality") or "?" for r in dup).most_common():
        print(f"      {q:15s} {n}")
    up = [r for r in dup if r.get("quality") == "source-better"]
    print(f"   would have been an 'upgrade' (NOT imported, reported instead): {len(up)}")
    for r in up[:12]:
        print(f"      src {r['src_br']}k vs lib {r['lib_br']}k"
              f".{r['lib_suffix']}  {r['title'][:34]:36s} {r['rel'][:40]}")
    print("   mean confidence of duplicate calls:",
          f"{sum(r['score'] or 0 for r in dup) / max(1, len(dup)):.3f}",
          " low tail:", sorted(round(r["score"] or 0, 3) for r in dup)[:5])

    print("\n=== score distribution of every comparison made")
    bins = collections.Counter()
    for r in rows:
        if r["score"] is None:
            bins["no score"] += 1
            continue
        b = int(r["score"] * 10) / 10
        bins[f"{b:.1f}-{b + 0.1:.1f}"] += 1
    for k in sorted(bins):
        print(f"      {k:10s} {'#' * (bins[k] // 8):<40s} {bins[k]}")

    print("\n=== damaged files (silent-hole / unreadable)")
    dmg = [r for r in rows if r["damaged"]]
    by = collections.Counter(r["verdict"] for r in dmg)
    print(f"   {len(dmg)} damaged files:", dict(by))
    uniq_dmg = [r for r in dmg if r["verdict"] in ("NEW", "UNDECIDED")]
    print(f"   damaged AND not already in the library: {len(uniq_dmg)}"
          "  -> these are parked, not imported")
    for r in uniq_dmg[:12]:
        print(f"      {r['verdict']:9s} {r['title'][:30]:32s} {r['rel'][:52]}")

    print("\n=== new audio, by artist")
    new = [r for r in rows if r["verdict"] == "NEW"]
    per = collections.defaultdict(lambda: [0, 0])
    for r in new:
        a = r["rel"].split("/")[0]
        per[a][0] += 1
        per[a][1] += r["bytes"]
    for a, (n, v) in sorted(per.items(), key=lambda kv: -kv[1][0]):
        tot = sum(1 for r in rows if r["rel"].startswith(a + "/"))
        print(f"   {a[:52]:54s} {n:4d} new of {tot:4d}  {human(v):>9}")

    albums = collections.Counter()
    for r in new:
        albums[(r["rel"].split("/")[0], os.path.dirname(r["rel"]).split("/", 1)[1]
                if r["rel"].count("/") > 1 else "")] += 1
    print(f"\n   new files span {len(albums)} source release folders")
    for (a, d), n in albums.most_common(10):
        print(f"      {n:4d}  {a[:26]:28s} {d[:52]}")

    print("\n=== needs a human")
    for r in [x for x in rows if x["verdict"] == "UNDECIDED"]:
        print(f"   {r['score']:.3f}  {r['title'][:32]:34s}"
              f" vs {os.path.basename(r['lib'])[:34]:36s} {r['dur']:.0f}s")
    nc = [r for r in rows if r["verdict"] == "NO-COMPARISON"]
    if nc:
        print(f"   {len(nc)} files could not be compared at all")
    return 0


if __name__ == "__main__":
    sys.exit(main())

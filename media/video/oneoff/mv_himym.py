"""File the HIMYM pack into the series library the way the library is laid out.


    /mnt/media/series/How I Met Your Mother (2005)/Season 09/
        How I Met Your Mother S09E01 The Locket.mkv

The release tags -- "(1080p AMZN WEB-DL x265 Silence)" -- carry nothing a
player uses and are dropped. Source stays as the release source: WEB-DL or
BluRay is reported, not kept in the filename, matching how the other shows in
this library are named.

Moves are renames (same filesystem), never overwrites: a target path that is
already taken stops that one file rather than replacing it.
"""

# This file is a COMMAND, not a library: importing it used to run the pass, which
# is how a `--help` typo came to overwrite a finished plan. Run it instead:
#     python3 media/video/mv_himym.py
if __name__ != "__main__":
    raise SystemExit(__file__ + " is a command; run it, do not import it")
import json
import os
import re
import sys

SRC = "/mnt/media/How I Met Your Mother (2005) Season 1-9 S01-S09 (1080p MIXED x265 HEVC 10bit AAC 5.1 Silence)"
DST = "/mnt/media/series"
SHOW = "How I Met Your Mother"
YEAR = "2005"
LOG = "/home/lario/video-reorganize/himym-move.jsonl"

# S07E23, 7x23, s07e23
EP_RE = re.compile(r"\b[sw](\d{1,2})[\s._-]*e(\d{1,3})\b", re.I)
TAG_RE = re.compile(r"\((?:[^()]?\b(?:1080p|720p|2160p|x265|x264|h\.?265|h\.?264|"
                    r"hevc|avc|aac|ac3|eac3|web-?dl|web-?rip|bluray|blu-?ray|"
                    r"amzn|nf|dsny|hulu|atk|silence|remux|multiple subtitles?)\b[^()]*)\)",
                    re.I)


def parse(name):
    """(season, episode, clean title) from a scene filename."""
    stem = os.path.splitext(os.path.basename(name))[0]
    m = EP_RE.search(stem)
    if not m:
        return None
    season, ep = int(m.group(1)), int(m.group(2))
    rest = stem[m.end():]
    # the show name and year lead the scene name; drop them, keep the title
    rest = re.sub(r"^.*?S\d{1,2}[\s._-]*E\d{1,3}", " ", rest, flags=re.I)
    rest = re.sub(rf"^{re.escape(SHOW)}", " ", rest, flags=re.I)
    rest = TAG_RE.sub(" ", rest)
    rest = rest.replace(".", " ").replace("_", " ")
    rest = re.sub(r"[\s._-]{2,}", " ", rest)
    rest = re.sub(r"\s+", " ", rest).strip(" -_.")
    # a leading dash left behind by the scene naming (" - Pilot") is gone now
    rest = rest.lstrip("- ").strip()
    return season, ep, rest or f"Episode {ep}"


def main():
    dry = "--apply" not in sys.argv
    plan, unparsed = [], []
    for root, _dirs, files in os.walk(SRC, onerror=lambda e: print(f"   walk {e}")):
        for f in files:
            if not f.lower().endswith((".mkv", ".mp4", ".m4v", ".avi")):
                continue
            src = os.path.join(root, f)
            got = parse(f)
            if not got:
                unparsed.append(src)
                continue
            season, ep, title = got
            dest = os.path.join(DST, f"{SHOW} ({YEAR})", f"Season {season:02d}",
                                f"{SHOW} S{season:02d}E{ep:02d} {title}.mkv")
            plan.append({"src": src, "dest": dest, "season": season, "ep": ep,
                         "bytes": os.path.getsize(src),
                         "source": "BluRay" if "bluray" in f.lower() or "blu-ray" in f.lower()
                         else "WEB-DL"})

    seen, moved, blocked = {}, 0, []
    for p in sorted(plan, key=lambda p: (p["season"], p["ep"], p["src"])):
        key = (p["season"], p["ep"])
        if key in seen:
            blocked.append((p, "two files claim the same episode number"))
            continue
        seen[key] = p["src"]
        if os.path.exists(p["dest"]):
            blocked.append((p, "a file already sits at the target path"))
            continue
        if not dry:
            os.makedirs(os.path.dirname(p["dest"]), exist_ok=True)
            os.rename(p["src"], p["dest"])
        moved += 1

    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, "w", encoding="utf-8") as fh:
        for p in plan:
            fh.write(json.dumps(p, ensure_ascii=False) + "\n")

    print(f"   {'DRY RUN' if dry else 'MOVED'}")
    print(f"      episodes    {len(plan)}   {sum(p['bytes'] for p in plan)/2**30:.1f} GB")
    print(f"      {'to file' if dry else 'filed'}      {moved}")
    for p, why in blocked:
        print(f"      BLOCKED     {os.path.basename(p['src'])[:52]}: {why}")
    for p in unparsed:
        print(f"      NO EPISODE NUMBER {os.path.relpath(p, SRC)[:60]}")
    per = {}
    for p in plan:
        per.setdefault(p["season"], [0, 0])
        per[p["season"]][0] += 1
        if p["source"] == "BluRay":
            per[p["season"]][1] += 1
    print("\n      seasons:")
    for s in sorted(per):
        n, bluray = per[s]
        note = f"  ({bluray} BluRay, rest WEB-DL)" if bluray else ""
        print(f"        Season {s:02d}  {n:2d} episodes{note}")
    # what is left behind, so the source folder can go once it is empty
    left = 0
    for root, _d, files in os.walk(SRC, onerror=lambda e: None):
        left += len(files)
    print(f"\n      files still in the source folder after the move: {left}")


if __name__ == "__main__":
    main()

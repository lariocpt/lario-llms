"""File Grace and Frankie into the series library, keeping one copy per episode.


The same episodes arrive three times over: a 360p re-webrip of seasons 1-6, a
720p x265 rip of season 3 and a 720p x264 rip of season 6. The higher-resolution
rip wins for those seasons and the 360p copy of them is removed once the better
file is proven to be in place. Seasons 1, 2, 4 and 5 only exist at 360p, so
those stay as they are -- nothing here invents quality that is not there.

The 360p filenames are the only place the episode titles appear, so titles for
the 720p seasons are harvested from them before they go.

Nothing is deleted until its replacement is verified openable at the target.
"""

# This file is a COMMAND, not a library: importing it used to run the pass, which
# is how a `--help` typo came to overwrite a finished plan. Run it instead:
#     python3 media/video/mv_grace.py
if __name__ != "__main__":
    raise SystemExit(__file__ + " is a command; run it, do not import it")
import json
import os
import re
import shutil
import subprocess
import sys

SRC = "/mnt/media/unsorted mo eis"
DST = "/mnt/media/series"
SHOW = "Grace and Frankie"
YEAR = "2013"
LOG = "/home/lario/video-reorganize/grace-move.jsonl"
EP_RE = re.compile(r"\bs(\d{1,2})e(\d{1,3})\b", re.I)


def opens(path):
    """A file counts as in place only if ffprobe can read it to the end index."""
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", path], capture_output=True, text=True)
    try:
        return float(r.stdout.strip()) > 60
    except ValueError:
        return False


def harvest_titles():
    """{season: {episode: title}} from whichever filenames carry a title."""
    out = {}
    for root, _d, files in os.walk(SRC, onerror=lambda e: print(f"   walk {e}")):
        for f in files:
            if not f.lower().endswith((".mp4", ".mkv")):
                continue
            m = EP_RE.search(f)
            if not m:
                continue
            stem = os.path.splitext(f)[0]
            title = stem[m.end():].strip(" .-")
            if title and not re.match(r"^\d+[Sp]", title, re.I):
                out.setdefault(int(m.group(1)), {}).setdefault(int(m.group(2)), title)
    return out


def quality(name, ext, size):
    """Rank competing copies of one episode. Resolution first, then codec,
    then bitrate: a 720p x264 rips beats a 360p file outright."""
    low = name.lower()
    if "720p" in low:
        res = 720
    elif "1080" in low:
        res = 1080
    elif "360" in low or "480" in low:
        res = 360
    else:
        res = 360
    codec = 2 if ("x265" in low or "hevc" in low) else 1
    return (res, codec, size)


def main():
    dry = "--apply" not in sys.argv
    titles = harvest_titles()
    cands = {}
    for root, _d, files in os.walk(SRC, onerror=lambda e: None):
        for f in files:
            if not f.lower().endswith((".mp4", ".mkv")):
                continue
            m = EP_RE.search(f)
            if not m:
                continue
            s, e = int(m.group(1)), int(m.group(2))
            path = os.path.join(root, f)
            cands.setdefault((s, e), []).append(
                {"src": path, "bytes": os.path.getsize(path), "ext": os.path.splitext(f)[1],
                 "keep": quality(f, os.path.splitext(f)[1], os.path.getsize(path))})

    plan, drop = [], []
    for (s, e), group in sorted(cands.items()):
        group.sort(key=lambda g: g["keep"], reverse=True)
        win, losers = group[0], group[1:]
        title = titles.get(s, {}).get(e, "")
        name = " ".join(f"{SHOW} S{s:02d}E{e:02d} {title}".split()) + win["ext"]
        dest = os.path.join(DST, f"{SHOW} ({YEAR})", f"Season {s:02d}", name)
        win["dest"], win["season"], win["ep"] = dest, s, e
        plan.append(win)
        for l in losers:
            l["dest"], l["season"], l["ep"], l["better"] = dest, s, e, win["src"]
            drop.append(l)

    moved, deleted, refused = 0, 0, 0
    for p in plan:
        if os.path.exists(p["dest"]):
            print(f"   BLOCKED a file already sits at {os.path.relpath(p['dest'], DST)}")
            refused += 1
            continue
        if not dry:
            os.makedirs(os.path.dirname(p["dest"]), exist_ok=True)
            shutil.move(p["src"], p["dest"])
        moved += 1
    for l in drop:
        if dry:
            deleted += 1          # what would go, once the replacement is verified
            continue
        # only after the better copy is proven readable at its new home
        if opens(l["dest"]):
            os.unlink(l["src"])
            deleted += 1
        else:
            print(f"   KEPT    {os.path.basename(l['src'])[:46]}: replacement not verified")
            refused += 1

    with open(LOG, "w", encoding="utf-8") as fh:
        for p in plan + drop:
            fh.write(json.dumps(p, ensure_ascii=False) + "\n")

    print(f"   {'DRY RUN' if dry else 'DONE'}")
    print(f"      episodes    {len(plan)}   {sum(p['bytes'] for p in plan)/2**30:.1f} GB filed")
    print(f"      superseded  {len(drop)} lower-quality copies removed "
          f"({sum(l['bytes'] for l in drop)/2**30:.1f} GB)")
    print(f"      {'filed' if dry else 'moved'}      {moved}, "
          f"{'would delete' if dry else 'deleted'} {deleted}, refused {refused}")
    by = {}
    for p in plan:
        by.setdefault(p["season"], []).append(p)
    for s in sorted(by):
        g = by[s]
        res = {"720": 0, "360": 0}
        for x in g:
            res["720" if x["keep"][0] == 720 else "360"] += 1
        note = ", ".join(f"{v} x {k}p" for k, v in sorted(res.items(), reverse=True) if v)
        print(f"        Season {s:02d}  {len(g):2d} episodes   {note}")


if __name__ == "__main__":
    main()

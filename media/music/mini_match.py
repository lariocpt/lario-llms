"""Classify every staged mini-mobile file against the live library.


Evidence tiers, strongest first:
  1. whole-file md5            -> byte-identical (only possible vs same size)
  2. metadata + duration       -> candidate "same recording"
  3. payload md5 / decoded PCM -> proof for the ambiguous candidates
Nothing here decides imports; it only produces a verdict per file with the
evidence recorded, so the counts can be reviewed before anything moves.
"""

# This file is a COMMAND, not a library: importing it used to run the pass, which
# is how a `--help` typo came to overwrite a finished plan. Run it instead:
#     python3 media/music/mini_match.py
if __name__ != "__main__":
    raise SystemExit(__file__ + " is a command; run it, do not import it")
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
from collections import defaultdict

from paths import STAGE
from paths import LIB
from paths import DB
from paths import WORK      # evidence root: config.MUSIC_WORK, env LARIO_MUSIC_WORK
os.makedirs(WORK, exist_ok=True)   # one evidence root for the whole pass
HERE = os.path.dirname(os.path.abspath(__file__))

AUDIO = {".mp3", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".wav", ".aiff", ".wma"}


def norm(s):
    """casefold + drop every non-alphanumeric: punctuation/spacing noise gone."""
    s = (s or "").casefold()
    return re.sub(r"[^0-9a-z\u00c0-\uffff]+", "", s)


def tokens(s):
    """word-set key: catches title/artist order and bracket moves."""
    s = (s or "").casefold()
    words = re.findall(r"[0-9a-z\u00c0-\uffff]+", s)
    return " ".join(sorted(words))


def lib_md5(path):
    h = hashlib.md5()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def payload_md5(path):
    """Audio payload only: stream-copy out of the container with tag blocks
    dropped, then hash. Two files that differ only in tags hash equal."""
    r = subprocess.run(
        ["ffmpeg", "-v", "error", "-xerror", "-i", path, "-map", "0:a:0",
         "-c:a", "copy", "-write_id3v2", "0", "-id3v2_version", "0",
         "-f", "mp3", "-"],
        capture_output=True, timeout=300)
    if r.returncode != 0:
        return None, (r.stderr.decode("utf-8", "replace").strip()[:120] or "ffmpeg rc")
    return hashlib.md5(r.stdout).hexdigest(), ""


def main():
    staged = {}
    for line in open(f"{WORK}/mini-meta.jsonl", encoding="utf-8"):
        r = json.loads(line)
        staged[r["rel"]] = r
    for line in open(f"{WORK}/mini-hash.jsonl", encoding="utf-8"):
        r = json.loads(line)
        staged[r["rel"]].update(hashed=r)
    remote = {}
    for line in open(f"{WORK}/mini-source-md5.tsv", encoding="utf-8"):
        if line.startswith("DONE"):
            continue
        m, rel = line.rstrip("\n").split("\t", 1)
        remote[rel] = m

    # ---------- library index (live index, audio rows only) ----------
    con = sqlite3.connect(DB, uri=True)
    con.text_factory = lambda b: b.decode("utf-8", "replace")
    lib = {}
    for p, ti, al, aart, art, dur, size, br, yr in con.execute(
            "select path, title, album, album_artist, artist, duration, size, bit_rate, year"
            " from media_file where missing=0"):
        lib[p] = dict(title=ti or "", album=al or "", album_artist=aart or art or "",
                      artist=art or "", dur=float(dur or 0), size=int(size or 0),
                      br=int(br or 0), year=int(yr or 0))
    print(f"   library rows: {len(lib)}   staged audio: {len(staged)}"
          f"   remote md5: {len(remote)}", file=sys.stderr)

    by_size = defaultdict(list)
    by_title_dur = defaultdict(list)
    by_tok_dur = defaultdict(list)
    for p, L in lib.items():
        by_size[L["size"]].append(p)
        t = norm(L["title"])
        if t:
            by_title_dur[(t, round(L["dur"]))].append(p)
            by_title_dur[(t, round(L["dur"]) + 1)].append(p)
            by_title_dur[(t, round(L["dur"]) - 1)].append(p)
        tk = tokens(L["title"])
        if tk:
            by_tok_dur[(tk, round(L["dur"]))].append(p)
            by_tok_dur[(tk, round(L["dur"]) + 1)].append(p)

    # ---------- 1. transfer fidelity (source -> staging) ----------
    fidelity_bad = []
    for rel, r in staged.items():
        h = r.get("hashed", {}).get("md5")
        if remote.get(rel) != h:
            fidelity_bad.append(rel)
    print(f"\n=== 1. copy fidelity: staged md5 != source md5 : {len(fidelity_bad)}", file=sys.stderr)
    for rel in fidelity_bad[:8]:
        print(f"      {rel[:70]}", file=sys.stderr)

    # ---------- 2. intra-source exact duplicates ----------
    dupes = defaultdict(list)
    for rel, r in staged.items():
        dupes[r["hashed"]["md5"]].append(rel)
    intra = {m: v for m, v in dupes.items() if len(v) > 1}
    print(f"=== 2. byte-identical pairs inside the source : {len(intra)}"
          f"  ({sum(len(v) for v in intra.values())} files)", file=sys.stderr)
    for m, v in list(intra.items())[:6]:
        print(f"      {len(v)}x  " + " || ".join(x[:44] for x in v[:3]), file=sys.stderr)

    # ---------- 3. byte-identity against the library ----------
    lib_md5_cache = {}
    exact_lib = {}
    need = defaultdict(set)  # library path -> staged hashes to test
    for rel, r in staged.items():
        for lp in by_size.get(r["hashed"]["size"], []):
            need[lp].add(r["hashed"]["md5"])
    print(f"=== 3. size-matched library candidates to hash : {len(need)}", file=sys.stderr)
    for lp, hashes in need.items():
        m = lib_md5(os.path.join(LIB, lp))
        lib_md5_cache[lp] = m
        if m in hashes:
            exact_lib[lp] = m
    hit_files = {rel for rel, r in staged.items()
                 if any(lib_md5_cache.get(lp) == r["hashed"]["md5"]
                        for lp in by_size.get(r["hashed"]["size"], []))}
    print(f"     byte-identical to a library file        : {len(hit_files)}", file=sys.stderr)

    # ---------- 4. metadata + duration candidates ----------
    verdicts = {}
    for rel, r in staged.items():
        h = r["hashed"]
        dur = float(r.get("dur") or 0)
        title = r.get("tit2") or r["ftitle"]
        cands = set()
        t = norm(title)
        if t and dur:
            cands |= set(by_title_dur.get((t, round(dur)), []))
            cands |= set(by_title_dur.get((t, round(dur) + 1), []))
            cands |= set(by_title_dur.get((t, round(dur) - 1), []))
        tk = tokens(title)
        tok_cands = set()
        if tk and dur:
            tok_cands |= set(by_tok_dur.get((tk, round(dur)), []))
            tok_cands |= set(by_tok_dur.get((tk, round(dur) + 1), []))
        tok_cands -= cands
        v = {"rel": rel, "bytes": h["size"], "dur": dur, "br": r.get("br"),
             "damaged": h["damaged"], "zero_run": h["zero_run"],
             "title": title, "album": r.get("talb") or r["album_folder"],
             "artist": r.get("tpe1") or "", "exact_lib": rel in hit_files,
             "cand": sorted(cands), "tok_cand": sorted(tok_cands)[:6],
             "intra_dupe": len(dupes[h["md5"]]) > 1}
        verdicts[rel] = v

    n_exact = sum(1 for v in verdicts.values() if v["exact_lib"])
    n_cand = sum(1 for v in verdicts.values() if v["cand"] and not v["exact_lib"])
    n_tok = sum(1 for v in verdicts.values() if v["tok_cand"] and not v["exact_lib"] and not v["cand"])
    n_new = sum(1 for v in verdicts.values() if not v["exact_lib"] and not v["cand"] and not v["tok_cand"])
    print(f"\n=== 4. match tiers ===", file=sys.stderr)
    print(f"     byte-identical in library          : {n_exact}", file=sys.stderr)
    print(f"     same title + duration (verify)     : {n_cand}", file=sys.stderr)
    print(f"     same word-set + duration (review)  : {n_tok}", file=sys.stderr)
    print(f"     no candidate at all (new)          : {n_new}", file=sys.stderr)
    print(f"     of the 'new' ones, damaged         :"
          f" {sum(1 for v in verdicts.values() if v['damaged'] and not v['exact_lib'] and not v['cand'] and not v['tok_cand'])}",
          file=sys.stderr)

    with open(f"{WORK}/mini-verdicts.json", "w", encoding="utf-8") as fh:
        json.dump({"verdicts": verdicts,
                   "fidelity_bad": fidelity_bad,
                   "intra_dupe_groups": {m: v for m, v in intra.items()}},
                  fh, ensure_ascii=False, indent=1)

    print(f"\n=== 5. what the 'new' material actually is ===", file=sys.stderr)
    news = [v for v in verdicts.values()
            if not v["exact_lib"] and not v["cand"] and not v["tok_cand"]]
    grp = defaultdict(list)
    for v in news:
        grp[(v["artist"], v["album"])].append(v)
    for (a, al), rows in sorted(grp.items(), key=lambda kv: -len(kv[1]))[:25]:
        print(f"   {len(rows):3d}  {a[:22]:22s} | {al[:44]:44s}"
              f"  dmg={sum(1 for r in rows if r['damaged'])}", file=sys.stderr)


if __name__ == "__main__":
    main()

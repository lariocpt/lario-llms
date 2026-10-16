"""High-recall matching of the staged copy against the live library, with

decoded-audio proof for every "same recording" claim.

Duration equality alone is never proof (phase 1 proved that: Jaded 425.7 vs
429.8 s were different recordings). So:
  candidates  : duration within +-3.5 s, best fuzzy title, album as tiebreak
  proof       : payload md5 when both are mp3, otherwise normalised
                cross-correlation of decoded PCM windows (same recording -> ~1)
Nothing is imported here; the output is a verdict per staged file.
"""

# This file is a COMMAND, not a library: importing it used to run the pass, which
# is how a `--help` typo came to overwrite a finished plan. Run it instead:
#     python3 media/music/mini_match2.py
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

import numpy as np

from paths import STAGE
from paths import LIB
from paths import DB
from paths import WORK      # evidence root: config.MUSIC_WORK, env LARIO_MUSIC_WORK
os.makedirs(WORK, exist_ok=True)   # one evidence root for the whole pass
SR = 8000
WIN = 25.0
LAG = 4.0  # seconds of alignment slack either way


def norm(s):
    s = (s or "").casefold()
    return re.sub(r"[^0-9a-z\u00c0-\uffff]+", "", s)


def sim(a, b):
    """0..1 title similarity: identical/contained or difflib ratio."""
    a, b = norm(a), norm(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if a in b or b in a:
        return 0.93
    import difflib
    return difflib.SequenceMatcher(None, a, b).ratio()


def pcm_windows(path):
    """Two decoded mono windows at 25% and 60% in. Returns list of arrays."""
    dur = probe_dur(path)
    if not dur:
        return []
    out = []
    for frac in (0.25, 0.60):
        off = max(0.0, dur * frac)
        r = subprocess.run(
            ["ffmpeg", "-v", "error", "-ss", f"{off:.2f}", "-t", f"{WIN}",
             "-i", path, "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"],
            capture_output=True, timeout=240)
        if r.returncode != 0 or len(r.stdout) < SR * 4 * 4:
            continue
        a = np.frombuffer(r.stdout, dtype=np.float32)
        if not np.isfinite(a).all():
            a = np.nan_to_num(a)
        if float(np.mean(np.abs(a) < 1e-6)) > 0.30:  # hole / silence window
            continue
        out.append(a)
    return out


_dur_cache = {}


def probe_dur(path):
    if path in _dur_cache:
        return _dur_cache[path]
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", path], capture_output=True, text=True, timeout=120)
    try:
        d = float(r.stdout.strip())
    except ValueError:
        d = 0.0
    _dur_cache[path] = d
    return d


def pair_corr(a, b):
    """Normalised cross-correlation peak of two windows, allowing +-LAG shift.
    Windows that were dropped (holes, silence) never reach here."""
    pad = int(LAG * SR)
    n = min(len(a), len(b))
    if n < SR * 8:
        return -1.0
    a = a[:n].astype(np.float64)
    b = b[:n].astype(np.float64)
    a = a - a.mean()
    b = b - b.mean()
    na, nb = float(np.linalg.norm(a)), float(np.linalg.norm(b))
    if na < 1e-6 or nb < 1e-6:
        return -1.0
    L = 1
    while L < n + pad:  # keep circular wrap outside the searched lag range
        L *= 2
    cc = np.fft.irfft(np.fft.rfft(a, L) * np.conj(np.fft.rfft(b, L)), L)
    denom = na * nb
    pos = np.abs(cc[:pad + 1]) / denom          # b delayed against a
    neg = np.abs(cc[L - pad + 1:]) / denom      # b advanced against a
    scores = np.concatenate([pos, neg])
    return float(scores.max()) if len(scores) else -1.0


def best_corr(pa, pb):
    """Peak correlation across every window pair (windows are positionally
    aligned but a hole can drop one side, so compare all pairs)."""
    best = -1.0
    for a in pa:
        for b in pb:
            c = pair_corr(a, b)
            if c > best:
                best = c
    return best


def payload_md5(path):
    r = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", path, "-map", "0:a:0", "-c:a", "copy",
         "-id3v2_version", "0", "-f", "mp3", "-"], capture_output=True, timeout=300)
    if r.returncode != 0:
        return None
    return hashlib.md5(r.stdout).hexdigest()


def main():
    staged = {}
    for line in open(f"{WORK}/mini-meta.jsonl", encoding="utf-8"):
        r = json.loads(line)
        staged[r["rel"]] = r
    for line in open(f"{WORK}/mini-hash.jsonl", encoding="utf-8"):
        r = json.loads(line)
        staged[r["rel"]].update(r)

    con = sqlite3.connect(DB, uri=True)
    con.text_factory = lambda b: b.decode("utf-8", "replace")
    lib = {}
    for p, ti, al, aart, art, dur, size, br, codec, yr in con.execute(
            "select path, title, album, album_artist, artist, duration, size, bit_rate,"
            " codec, year from media_file where missing=0"):
        lib[p] = dict(title=ti or "", album=al or "", album_artist=aart or art or "",
                      dur=float(dur or 0), size=int(size or 0), br=int(br or 0),
                      codec=(codec or "").upper(), year=int(yr or 0))

    # duration bucket index, 1-second buckets, +-4 buckets consulted
    buckets = defaultdict(list)
    for p, L in lib.items():
        buckets[int(round(L["dur"]))].append(p)

    results = {}
    for i, (rel, r) in enumerate(sorted(staged.items()), 1):
        if i % 100 == 0:
            print(f"   {i}/{len(staged)}", file=sys.stderr)
        dur = float(r.get("dur") or 0) or probe_dur(os.path.join(STAGE, rel))
        title = r.get("tit2") or r["ftitle"]
        album = r.get("talb") or r["album_folder"]
        cands = []
        if dur:
            for b in range(int(round(dur)) - 4, int(round(dur)) + 5):
                for lp in buckets.get(b, []):
                    L = lib[lp]
                    ts = sim(title, L["title"])
                    if ts < 0.62:
                        continue
                    als = 0.35 * sim(album, L["album"])
                    cands.append((ts + als, ts, lp, L))
        cands.sort(key=lambda c: (-c[0], abs(c[3]["dur"] - dur)))
        rec = {"rel": rel, "dur": dur, "title": title, "album": album,
               "artist": r.get("tpe1") or "", "br": r.get("br"), "sr": r.get("sr"),
               "size": r["size"], "md5": r["md5"], "damaged": r["damaged"],
               "zero_run": r["zero_run"], "byte_dupe": r["md5"] in LIB_MD5S,
               "cands": [(round(s, 3), ts, lp, L["dur"], L["br"], L["codec"], L["album"])
                         for s, ts, lp, L in cands[:4]],
               "verdict": "", "proof": "", "quality": ""}
        results[rel] = rec

    with open(f"{WORK}/mini-cands.json", "w", encoding="utf-8") as fh:
        json.dump(results, fh, ensure_ascii=False)

    n_byte = sum(1 for v in results.values() if v["byte_dupe"])
    n_cand = sum(1 for v in results.values() if v["cands"] and not v["byte_dupe"])
    n_none = sum(1 for v in results.values() if not v["cands"] and not v["byte_dupe"])
    print(f"\n   byte-identical in library : {n_byte}", file=sys.stderr)
    print(f"   has a fuzzy candidate     : {n_cand}", file=sys.stderr)
    print(f"   nothing at all            : {n_none}", file=sys.stderr)
    print(f"   of those, damaged         :"
          f" {sum(1 for v in results.values() if not v['cands'] and not v['byte_dupe'] and v['damaged'])}",
          file=sys.stderr)


LIB_MD5S = set()
staged_md5 = {}


def load_byte_dupes():
    """which staged md5s equal some library file's md5 (size-matched, cached)"""
    for line in open(f"{WORK}/mini-byte-dupes.json", encoding="utf-8"):
        d = json.loads(line)
        LIB_MD5S.add(d["md5"])


if __name__ == "__main__":
    if os.path.exists(f"{WORK}/mini-byte-dupes.json"):
        load_byte_dupes()
    main()

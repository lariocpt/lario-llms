"""Final classification pass: full-track envelope comparison, whole library.

The 30-second window metric was a screening tool and it mis-ranked the
cross-codec cases (a 128 k MP3 against a FLAC of the SAME recording can score
0.6). The full-track metric is calibrated separately (mini_arbiter.py
--calibrate): same recording never below 0.923, different audio never above
0.208. So DUP starts at 0.80, NOT-DUP below 0.50, and the 0.50-0.80 band is
left undecided and reviewed by hand instead of being forced.

Every staged file is compared with its title candidates AND every library file
within +-3 s, using the strongest available evidence: byte md5, then audio
payload md5, then full-track envelope.

Resumable: writes one JSON line per staged file, skips already-done ones.
"""
import json
import os
import pickle
import sqlite3
import subprocess
import sys
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import DB          # the read-only Navidrome index, from core/config.py
from mini_arbiter import (CACHE as FULLCACHE, corr_max, dec_full, features as _f,
                          HOP, LAG, LIB, SR, STAGE)

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = f"{HERE}/mini-final.jsonl"
DUP_AT = 0.80
NOT_DUP_AT = 0.50
DTOL = 3.0

# Lossy vs lossless, so "the copy we already have" and "a better copy of the
# same recording" are never confused. m4a is checked against the index's codec
# column, so ALAC is not counted as a lossy copy.
KIND = {"wav": 4, "aiff": 4, "aif": 4, "flac": 4, "alac": 4, "ape": 4,
        "m4a": 2, "aac": 1, "mp3": 1, "opus": 1, "ogg": 1}


def compare_quality(src_br, src_suffix, lib_br, lib_suffix):
    """Both bit rates are kbps here (the index stores kbps), so they compare
    directly; only the string/int noise needs stripping."""
    def num(v):
        try:
            return int(float(str(v).strip()))
        except (TypeError, ValueError):
            return 0
    rs = KIND.get((src_suffix or "").lower(), 0)
    rl = KIND.get("alac" if (lib_suffix or "").lower() == "alac"
                  else (lib_suffix or "").lower(), 0)
    if rs != rl:
        return "source-better" if rs > rl else "library-better"
    if num(src_br) > num(lib_br):
        return "source-better"
    if num(src_br) < num(lib_br):
        return "library-better"
    return "equal"

_lock = threading.Lock()
_cache = {}


def full_features(path):
    """Whole-file envelope/onset, disk-cached (mini_arbiter.dec_full)."""
    with _lock:
        if path in _cache:
            return _cache[path]
    out = _f(path)
    with _lock:
        _cache[path] = out
    return out


def save_cache():
    tmp = FULLCACHE + ".tmp"
    with open(tmp, "wb") as fh:
        pickle.dump(dict(_cache), fh, protocol=4)
    os.replace(tmp, FULLCACHE)


def score(fa, fb):
    if fa is None or fb is None:
        return None
    lag = int(LAG / HOP)
    s = [corr_max(fa[0], fb[0], lag), corr_max(fa[1], fb[1], lag)]
    return max(s)


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--prewarm", action="store_true",
                    help="build the full-track envelope cache for the whole library")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    if os.path.exists(FULLCACHE):
        with open(FULLCACHE, "rb") as fh:
            _cache.update(pickle.load(fh))
        print(f"   envelope cache: {len(_cache)} files", file=sys.stderr)

    con = sqlite3.connect(DB, uri=True)   # DB already carries mode=ro: never open it writable
    con.text_factory = lambda b: b.decode("utf-8", "replace")
    lib = {p: (t or "", a or "", float(d or 0), int(b or 0), s or "")
           for p, t, a, d, b, s in con.execute(
               "select path,title,album,duration,bit_rate,suffix"
               " from media_file where missing=0")}

    if args.prewarm:
        todo = [p for p in sorted(lib) if p not in _cache]
        print(f"   library: {len(lib)}  to decode: {len(todo)}", file=sys.stderr)
        with ThreadPoolExecutor(16) as ex:
            for i, _ in enumerate(ex.map(
                    lambda p: full_features(os.path.join(LIB, p)), todo), 1):
                if i % 2000 == 0:
                    print(f"   {i}/{len(todo)}", file=sys.stderr, flush=True)
                    save_cache()
        save_cache()
        n_ok = sum(1 for v in _cache.values() if v is not None)
        print(f"   cached {len(_cache)} files, {n_ok} usable", file=sys.stderr)
        return

    cand = json.load(open(f"{HERE}/mini-cands.json", encoding="utf-8"))
    strict = {}
    for line in open(f"{HERE}/mini-proof.jsonl", encoding="utf-8"):
        r = json.loads(line)
        strict[r["rel"]] = r
    done = set()
    if os.path.exists(OUT):
        for line in open(OUT, encoding="utf-8"):
            try:
                done.add(json.loads(line)["rel"])
            except Exception:
                pass

    buckets = defaultdict(list)
    for p, (t, a, d, b, s) in lib.items():
        buckets[int(round(d))].append(p)

    def near(dur):
        out = []
        for k in range(int(round(dur - DTOL)), int(round(dur + DTOL)) + 1):
            out.extend(buckets.get(k, ()))
        return out

    todo = [rel for rel in sorted(cand) if rel not in done]
    if args.limit:
        todo = todo[:args.limit]
    print(f"   to classify: {len(todo)}  ({len(done)} already)", file=sys.stderr)

    def work(rel):
        r = cand[rel]
        dur = float(r.get("dur") or 0)
        sp = os.path.join(STAGE, rel)
        res = {"rel": rel, "dur": dur, "title": r["title"], "album": r["album"],
               "artist": r.get("artist", ""), "damaged": r["damaged"],
               "src_br": r.get("br"), "verdict": "", "lib": "", "score": None,
               "how": "", "tried": 0, "lib_br": None, "lib_suffix": None}
        if strict.get(rel, {}).get("byte_dupe"):
            res.update(verdict="DUP", how="byte-identical file in library", score=1.0,
                       lib=strict[rel].get("lib") or "")
            return res
        sf = full_features(sp)
        if sf is None:
            res.update(verdict="UNDECODABLE",
                       how="no decodable audio (damaged or unreadable container)")
            return res
        seen = [(lp, ld) for _, _, lp, ld, _, _, _ in r["cands"][:4]]
        for lp in near(dur):
            seen.append((lp, lib[lp][2]))
        best = (None, "", None, None)
        for lp, ldur in seen:
            res["tried"] += 1
            lf = full_features(os.path.join(LIB, lp))
            if lf is None:
                continue
            c = score(sf, lf)
            if c is None:
                continue
            if best[0] is None or c > best[0]:
                best = (c, lp, lib[lp][3], lib[lp][4])
        c, lp, lbr, lsuf = best
        res["score"] = round(c, 4) if c is not None else None
        res["lib"] = lp
        res["lib_br"] = lbr
        res["lib_suffix"] = lsuf
        if c is None:
            res.update(verdict="NO-COMPARISON", how="no duration-matched library file "
                                                   "could be decoded")
        elif c >= DUP_AT:
            res.update(verdict="DUP", how=f"same recording, full-track envelope {c:.3f}")
        elif c >= NOT_DUP_AT:
            res.update(verdict="UNDECIDED",
                       how=f"envelope {c:.3f} sits in the band between the calibrated "
                           f"populations - review")
        else:
            res.update(verdict="NEW",
                       how=f"best of {res['tried']} candidates scored {c:.3f} "
                           f"(different audio tops out at 0.208)")
        # quality of what we compared against, so a duplicate that would be an
        # "upgrade" shows up as one instead of being imported quietly
        res["quality"] = compare_quality(
            res["src_br"], os.path.splitext(rel)[1].lstrip("."),
            res["lib_br"], res["lib_suffix"])
        return res

    n = 0
    with open(OUT, "a", encoding="utf-8") as fh, ThreadPoolExecutor(12) as ex:
        for res in ex.map(work, todo):
            fh.write(json.dumps(res, ensure_ascii=False) + "\n")
            fh.flush()
            n += 1
            if n % 50 == 0:
                print(f"   {n}/{len(todo)}", file=sys.stderr, flush=True)
    save_cache()
    print(f"   appended {n}", file=sys.stderr)


if __name__ == "__main__":
    main()

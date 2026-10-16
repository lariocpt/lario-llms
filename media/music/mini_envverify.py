"""Definitive same-recognition pass for the staged copy.


Evidence, strongest first; the envelope score is the one that survives
different encoding chains (calibrated in mini_envcal.py: different audio tops
out ~0.66, same recording starts ~0.93, so DUP starts at 0.85 and 0.60-0.85 is
reported as ambiguous instead of being decided by a coin flip).

Every staged file is also compared against ALL library files whose duration is
within +-3 s, not only its title matches, so a mis-tagged or differently
worded copy of something we already own still gets caught.
"""

# This file is a COMMAND, not a library: importing it used to run the pass, which
# is how a `--help` typo came to overwrite a finished plan. Run it instead:
#     python3 media/music/mini_envverify.py
if __name__ != "__main__":
    raise SystemExit(__file__ + " is a command; run it, do not import it")
import json
import os
import re
import sqlite3
import subprocess
import sys
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from paths import STAGE
from paths import LIB
from paths import DB
from paths import WORK      # evidence root: config.MUSIC_WORK, env LARIO_MUSIC_WORK
os.makedirs(WORK, exist_ok=True)   # one evidence root for the whole pass
OUT = f"{WORK}/mini-envproof.jsonl"

SR = 8000
HOP = 0.02
DUP_ENV = 0.85
AMB_ENV = 0.60
DTOL = 3.0  # seconds: duration window for "could be the same recording"


def norm(s):
    return re.sub(r"[^0-9a-z\u00c0-\uffff]+", "", (s or "").casefold())


def dec(path, t, secs):
    r = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.2f}", "-t", f"{secs}",
                        "-i", path, "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"],
                       capture_output=True, timeout=300)
    if r.returncode != 0 or len(r.stdout) < SR * 4 * 8:
        return None
    a = np.nan_to_num(np.frombuffer(r.stdout, dtype=np.float32).astype(np.float32))
    if float(np.mean(np.abs(a) < 1e-6)) > 0.30:
        return None
    return a


def feat(a):
    """(envelope, onset) unit vectors, kept in float32 to bound memory"""
    n = max(1, int(SR * HOP))
    m = len(a) // n
    e = np.sqrt((a[:m * n].reshape(m, n) ** 2).mean(axis=1)).astype(np.float32)
    e = e - e.mean()
    ne = float(np.linalg.norm(e))
    on = np.maximum(np.diff(e), 0).astype(np.float32)
    on = on - on.mean()
    no = float(np.linalg.norm(on))
    return (np.float32(e / ne) if ne > 1e-9 else None,
            np.float32(on / no) if no > 1e-9 else None)


_lock = threading.Lock()
_cache = {}
CACHE = f"{WORK}/feats-cache.pkl"


def feats(path, dur):
    with _lock:
        if path in _cache:
            return _cache[path]
    out = []
    for frac in (0.20, 0.50):
        a = dec(path, max(0.0, dur * frac), 30)
        if a is not None:
            out.append(feat(a))
    with _lock:
        _cache[path] = out
    return out


def load_cache():
    import pickle
    if os.path.exists(CACHE):
        with open(CACHE, "rb") as fh:
            _cache.update(pickle.load(fh))
        print(f"   feature cache loaded: {len(_cache)} files", file=sys.stderr)


def save_cache():
    import pickle
    tmp = CACHE + ".tmp"
    with open(tmp, "wb") as fh:
        pickle.dump(dict(_cache), fh, protocol=4)
    os.replace(tmp, CACHE)
    print(f"   feature cache saved: {len(_cache)} files", file=sys.stderr)


def best_env(pa, pb):
    best = -1.0
    for ea in pa:
        for eb in pb:
            for x, y in ((ea[0], eb[0]), (ea[1], eb[1])):
                if x is None or y is None:
                    continue
                n = min(len(x), len(y))
                if n < 200:
                    continue
                x, y = x[:n], y[:n]
                L = 1
                while L < n + 1000:
                    L *= 2
                c = np.fft.irfft(np.fft.rfft(x, L) * np.conj(np.fft.rfft(y, L)), L)
                d = float(np.linalg.norm(x)) * float(np.linalg.norm(y)) + 1e-12
                v = float(np.max(np.concatenate([np.abs(c[:1001]) / d,
                                                 np.abs(c[L - 1000:]) / d])))
                if v > best:
                    best = v
    return best


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--prewarm", action="store_true",
                    help="compute library feature windows in parallel and cache them")
    args = ap.parse_args()

    cand = json.load(open(f"{WORK}/mini-cands.json", encoding="utf-8"))
    strict = {}
    for line in open(f"{WORK}/mini-proof.jsonl", encoding="utf-8"):
        r = json.loads(line)
        strict[r["rel"]] = r
    load_cache()

    con = sqlite3.connect(DB, uri=True)
    con.text_factory = lambda b: b.decode("utf-8", "replace")
    lib = {p: (t or "", a or "", float(d or 0), int(b or 0), s or "")
           for p, t, a, d, b, s in con.execute(
               "select path,title,album,duration,bit_rate,suffix from media_file where missing=0")}
    buckets = defaultdict(list)
    for p, (t, a, d, b, s) in lib.items():
        buckets[int(round(d))].append(p)

    def near(dur):
        out = []
        for k in range(int(round(dur - DTOL)), int(round(dur + DTOL)) + 1):
            out.extend(buckets.get(k, ()))
        return out

    if args.prewarm:
        need = set()
        for rel, r in cand.items():
            if strict.get(rel, {}).get("byte_dupe"):
                continue
            dur = float(r.get("dur") or 0)
            if dur:
                need.update(near(dur))
        todo = sorted(p for p in need if p not in _cache)
        print(f"   library files in the duration union: {len(need)}  to decode: {len(todo)}",
              file=sys.stderr)
        n = 0
        with ThreadPoolExecutor(16) as ex:
            for i, _ in enumerate(ex.map(lambda p: feats(os.path.join(LIB, p), lib[p][2]), todo), 1):
                n += 1
                if i % 1000 == 0:
                    print(f"   {i}/{len(todo)}", file=sys.stderr, flush=True)
                    save_cache()
        save_cache()
        print(f"   prewarmed {n}", file=sys.stderr)
        return

    done = set()
    if os.path.exists(OUT):
        for line in open(OUT, encoding="utf-8"):
            try:
                done.add(json.loads(line)["rel"])
            except Exception:
                pass

    todo = [rel for rel in sorted(cand) if rel not in done]
    print(f"   to process: {len(todo)} (of {len(cand)}), {len(done)} already done",
          file=sys.stderr)

    def work(rel):
        r = cand[rel]
        dur = float(r.get("dur") or 0)
        sp = os.path.join(STAGE, rel)
        res = {"rel": rel, "dur": dur, "title": r["title"], "album": r["album"],
               "damaged": r["damaged"], "src_br": r.get("br"),
               "strict": strict.get(rel, {}).get("verdict", ""),
               "byte": bool(strict.get(rel, {}).get("byte_dupe")),
               "verdict": "", "lib": "", "env": None, "lib_br": None,
               "lib_codec": None, "tried": 0}
        if res["byte"]:
            res.update(verdict="DUP", lib=strict[rel].get("lib") or "",
                       env=1.0, proof="byte-identical")
            return res
        sf = feats(sp, dur)
        if not sf:
            res.update(verdict="UNDECODABLE",
                       proof="no usable audio window (damaged or unreadable)")
            return res
        seen = []
        for _, _, lp, ldur, lbr, lcodec, lalb in r["cands"][:4]:
            seen.append((lp, ldur))
        for lp in near(dur):
            if not any(lp == x[0] for x in seen):
                seen.append((lp, lib[lp][2]))
        best = (-1.0, "", None, None, None)
        for lp, ldur in seen:
            lf = feats(os.path.join(LIB, lp), ldur)
            res["tried"] += 1
            if not lf:
                continue
            c = best_env(sf, lf)
            if c > best[0]:
                best = (c, lp, lib[lp][3], lib[lp][4], lib[lp][1])
        c, lp, lbr, lcodec, lalb = best
        res["env"] = round(c, 4) if c >= 0 else None
        res["lib"] = lp
        res["lib_br"] = lbr
        res["lib_codec"] = lcodec
        if c >= DUP_ENV:
            res["verdict"] = "DUP"
            res["proof"] = f"same recording (envelope {c:.3f})"
        elif c >= AMB_ENV:
            res["verdict"] = "AMBIGUOUS"
            res["proof"] = f"partial match (envelope {c:.3f}) - needs a human"
        else:
            res["verdict"] = "NEW"
            res["proof"] = (f"best of {res['tried']} duration-matched library files "
                            f"was only {c:.3f}")
        return res

    n = 0
    with open(OUT, "a", encoding="utf-8") as fh, ThreadPoolExecutor(12) as ex:
        for res in ex.map(work, todo):
            fh.write(json.dumps(res, ensure_ascii=False) + "\n")
            fh.flush()
            n += 1
            if n % 25 == 0:
                print(f"   {n}/{len(todo)}", file=sys.stderr)
    save_cache()
    print(f"   appended {n}", file=sys.stderr)


if __name__ == "__main__":
    main()

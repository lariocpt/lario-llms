"""Prove or refute every "same recording" candidate by decoded audio.


Thresholds are not guesses: calibrate() prints real scores for
  - a file against itself                      (must be ~1.00)
  - the Busy Child pair proven identical       (must be ~1.00)
  - the Jaded pair proven to be DIFFERENT recordings (must be well below)
and the import cut is read off that spread, not chosen to make results pretty.
"""

# This file is a COMMAND, not a library: importing it used to run the pass, which
# is how a `--help` typo came to overwrite a finished plan. Run it instead:
#     python3 media/music/mini_verify.py
if __name__ != "__main__":
    raise SystemExit(__file__ + " is a command; run it, do not import it")
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from paths import STAGE
from paths import LIB
from paths import DB
HERE = os.path.dirname(os.path.abspath(__file__))
SR = 8000
WIN = 25.0
LAG = 4.0


def norm(s):
    s = (s or "").casefold()
    return re.sub(r"[^0-9a-z\u00c0-\uffff]+", "", s)


def sim(a, b):
    a, b = norm(a), norm(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if a in b or b in a:
        return 0.93
    import difflib
    return difflib.SequenceMatcher(None, a, b).ratio()


def probe_dur(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "default=nw=1:nk=1", path], capture_output=True,
                       text=True, timeout=120)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def windows(path, dur=None):
    dur = dur or probe_dur(path)
    if not dur:
        return []
    out = []
    for frac in (0.25, 0.60):
        r = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{max(0.0, dur*frac):.2f}",
                            "-t", f"{WIN}", "-i", path, "-ac", "1", "-ar", str(SR),
                            "-f", "f32le", "-"], capture_output=True, timeout=240)
        if r.returncode != 0 or len(r.stdout) < SR * 4 * 4:
            continue
        a = np.frombuffer(r.stdout, dtype=np.float32)
        a = np.nan_to_num(a.astype(np.float32))
        if float(np.mean(np.abs(a) < 1e-6)) > 0.30:
            continue
        out.append(a)
    return out


def pair_corr(a, b):
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
    while L < n + pad:
        L *= 2
    cc = np.fft.irfft(np.fft.rfft(a, L) * np.conj(np.fft.rfft(b, L)), L)
    denom = na * nb
    scores = np.concatenate([np.abs(cc[:pad + 1]) / denom, np.abs(cc[L - pad + 1:]) / denom])
    return float(scores.max()) if len(scores) else -1.0


def best_corr(pa, pb):
    best = -1.0
    for a in pa:
        for b in pb:
            c = pair_corr(a, b)
            if c > best:
                best = c
    return best


def payload_md5(path):
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-map", "0:a:0", "-c:a",
                        "copy", "-id3v2_version", "0", "-f", "mp3", "-"],
                       capture_output=True, timeout=300)
    if r.returncode != 0:
        return None
    return hashlib.md5(r.stdout).hexdigest()


def load():
    with open(f"{HERE}/mini-cands.json", encoding="utf-8") as fh:
        return json.load(fh)


def lib_rows():
    con = sqlite3.connect(DB, uri=True)
    con.text_factory = lambda b: b.decode("utf-8", "replace")
    return {p: dict(title=t or "", album=a or "", dur=float(d or 0), br=int(b or 0),
                    codec=(c or "").upper(), sr=int(s or 0))
            for p, t, a, d, b, c, s in con.execute(
                "select path, title, album, duration, bit_rate, codec, sample_rate"
                " from media_file where missing=0")}


def calibrate(L):
    """Score distributions behind the threshold, on pairs that exist now."""
    print("\n=== calibration: peak normalised cross-correlation ===", file=sys.stderr)

    # A. positive control -- the same file read twice, across two trees
    dd = [json.loads(l) for l in open(f"{HERE}/mini-byte-dupes.json", encoding="utf-8")]
    s = []
    for m in dd[:5]:
        sp, lp = os.path.join(STAGE, m["rel"]), os.path.join(LIB, m["lib"])
        s.append(best_corr(windows(sp), windows(lp)))
    print(f"   byte-identical staged/library pairs : "
          f"{['%.4f' % v for v in s]}", file=sys.stderr)

    # B. hard negative -- same title in the library, far-apart durations
    #    (studio vs live / different takes: the real risk case for imports)
    bytitle = {}
    for p, r in L.items():
        if r["title"] and r["dur"] > 30:
            bytitle.setdefault(norm(r["title"]), []).append(p)
    pairs = []
    for t, ps in bytitle.items():
        ps = sorted(ps, key=lambda p: L[p]["dur"])
        if len(ps) >= 2 and L[ps[-1]]["dur"] - L[ps[0]]["dur"] > 20:
            pairs.append((ps[0], ps[-1]))
    s = []
    for a, b in pairs[:6]:
        s.append(round(best_corr(windows(os.path.join(LIB, a)),
                                 windows(os.path.join(LIB, b))), 4))
        print(f"      {L[a]['title'][:28]:30s} {L[a]['dur']:7.1f}s vs {L[b]['dur']:7.1f}s"
              f" -> {s[-1]}", file=sys.stderr)
    print(f"   same title, different take (n={min(6,len(pairs))})  : {s}", file=sys.stderr)

    # C. control negative -- unrelated files
    keys = sorted(L)
    s = [round(best_corr(windows(os.path.join(LIB, keys[i])),
                         windows(os.path.join(LIB, keys[i + 777]))), 4) for i in range(4)]
    print(f"   unrelated file pairs                : {s}", file=sys.stderr)


CAND = load()
LIBROWS = lib_rows()


def verify_one(rel):
    r = CAND[rel]
    out = dict(rel=rel, verdict="", proof="", corr=None, lib=None,
               src_br=r.get("br"), src_sr=r.get("sr"), damaged=r["damaged"])
    if r["byte_dupe"]:
        out.update(verdict="DUPE", proof="byte-identical file in library")
        return out
    cs = r["cands"]
    if not cs:
        out["verdict"] = "NO-CANDIDATE"
        return out
    for _, _, lp, ldur, lbr, lcodec, lalb in cs[:2]:
        sp = os.path.join(STAGE, rel)
        lpath = os.path.join(LIB, lp)
        corr = None
        if not r["damaged"]:
            pa, pb = payload_md5(sp), payload_md5(lpath)
            if pa is not None and pa == pb:
                out.update(verdict="DUPE", proof="identical audio payload (tags aside)", lib=lp,
                           corr=1.0)
                return out
        c = best_corr(windows(sp, r["dur"]), windows(lpath, ldur))
        corr = round(c, 4) if c >= 0 else None
        out["corr"] = corr
        out["lib"] = lp
        if corr is not None and corr >= 0.90:
            out.update(verdict="DUPE", proof=f"audio matches library copy (corr {corr})",
                       lib=lp)
            return out
    out["verdict"] = "NO-PROOF"
    return out


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--calibrate", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--apply-out", default=f"{HERE}/mini-proof.jsonl")
    a = ap.parse_args()

    if a.calibrate:
        calibrate(LIBROWS)
        return

    todo = [rel for rel in sorted(CAND)]
    if a.limit:
        todo = todo[:a.limit]
    print(f"   verifying {len(todo)} files", file=sys.stderr)
    done = 0
    with open(a.apply_out, "w", encoding="utf-8") as fh, ThreadPoolExecutor(6) as ex:
        for res in ex.map(verify_one, todo):
            fh.write(json.dumps(res, ensure_ascii=False) + "\n")
            done += 1
            if done % 100 == 0:
                print(f"   {done}/{len(todo)}", file=sys.stderr)
    print(f"   wrote {done} verdicts", file=sys.stderr)


if __name__ == "__main__":
    main()

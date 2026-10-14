"""Calibrate the ENVELOPE metric on hard cases, and report the score gap.


Waveform correlation is unusable across processing chains (proven in
probe_metric.py: same recording, 0.07 waveform / 0.90 envelope). So the test
becomes: duration +-6 s AND same title -> envelope correlation. This finds the
threshold empirically by scoring many same-title/similar-length library pairs,
where the truth is visible as a gap between "same recording" and "different
performance of the same song".
"""

# This file is a COMMAND, not a library: importing it used to run the pass, which
# is how a `--help` typo came to overwrite a finished plan. Run it instead:
#     python3 media/music/mini_envcal.py
if __name__ != "__main__":
    raise SystemExit(__file__ + " is a command; run it, do not import it")
import os
import re
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from paths import LIB
from paths import DB
SR = 8000
HOP = 0.02


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


def env(a):
    n = max(1, int(SR * HOP))
    m = len(a) // n
    e = np.sqrt((a[:m * n].reshape(m, n) ** 2).mean(axis=1))
    e = e - e.mean()
    s = float(np.linalg.norm(e))
    return e / s if s > 1e-9 else None


def onset(e, thr=None):
    """positive spectral-flux-like steps: sharp loudness rises"""
    d = np.diff(e)
    d = np.maximum(d, 0)
    return d


def env_corr(pa, pb):
    """best envelope+onset correlation over +-20 s, from two mid-file windows"""
    da, db = pa[1], pb[1]
    best = -1.0
    for fa in (0.20, 0.50):
        for fb in (0.20, 0.50):
            A, B = dec(pa[0], da * fa, 35), dec(pb[0], db * fb, 35)
            if A is None or B is None:
                continue
            ea, eb = env(A), env(B)
            if ea is None or eb is None:
                continue
            for x, y in ((ea, eb), (onset(ea), onset(eb))):
                n = min(len(x), len(y))
                if n < 200:
                    continue
                x, y = x[:n], y[:n]
                L = 1
                while L < n + 1000:
                    L *= 2
                c = np.fft.irfft(np.fft.rfft(x, L) * np.conj(np.fft.rfft(y, L)), L)
                d = float(np.linalg.norm(x)) * float(np.linalg.norm(y)) + 1e-12
                pos = np.abs(c[:1001]) / d
                neg = np.abs(c[L - 1000:]) / d
                v = float(np.max(np.concatenate([pos, neg])))
                if v > best:
                    best = v
    return best


def main():
    con = sqlite3.connect(DB, uri=True)
    con.text_factory = lambda b: b.decode("utf-8", "replace")
    rows = [(p, t or "", a or "", float(d or 0)) for p, t, a, d in con.execute(
        "select path, title, album, duration from media_file where missing=0 and duration>40")]
    by = {}
    for p, t, a, d in rows:
        k = norm(t)
        if k and len(k) > 3:
            by.setdefault(k, []).append((p, t, a, d))
    pairs = []
    for k, v in by.items():
        v.sort(key=lambda r: r[3])
        for i in range(len(v)):
            for j in range(i + 1, len(v)):
                if abs(v[i][3] - v[j][3]) <= 6.0:
                    pairs.append((v[i], v[j]))
    print(f"   same-title pairs within 6 s in the library: {len(pairs)}", file=sys.stderr)
    pairs = pairs[:400]

    def work(item):
        (pa, ta, aa, da), (pb, tb, ab, db) = item
        c = env_corr((os.path.join(LIB, pa), da), (os.path.join(LIB, pb), db))
        return round(c, 4), pa, ta, aa, da, pb, tb, ab, db

    out = []
    with ThreadPoolExecutor(8) as ex:
        for i, r in enumerate(ex.map(work, pairs), 1):
            out.append(r)
            if i % 50 == 0:
                print(f"   {i}/{len(pairs)}", file=sys.stderr)
    out.sort()
    print(f"\n=== envelope score distribution (n={len(out)}) ===", file=sys.stderr)
    hs = np.histogram([r[0] for r in out], bins=[0, .3, .5, .65, .75, .82, .88, .93, .97, 1.01])
    for cnt, edge in zip(hs[0], hs[1]):
        print(f"   {edge:.2f}-{edge+0.01:.2f} : {cnt:4d} {'#'*min(cnt,60)}", file=sys.stderr)
    print(f"\n=== lowest 12 (different performances?) ===", file=sys.stderr)
    for c, pa, ta, aa, da, pb, tb, ab, db in out[:12]:
        print(f"   {c:.4f}  {ta[:24]:26s} {da:6.1f} {aa[:24]:26s} vs {tb[:22]:24s}"
              f" {db:6.1f} {ab[:26]}", file=sys.stderr)
    print(f"\n=== highest 6 (same recording, different copy) ===", file=sys.stderr)
    for c, pa, ta, aa, da, pb, tb, ab, db in out[-6:]:
        print(f"   {c:.4f}  {ta[:24]:26s} {da:6.1f} {aa[:24]:26s} vs {tb[:22]:24s}"
              f" {db:6.1f} {ab[:26]}", file=sys.stderr)
    import json
    with open("/home/lario/music-reorganize/mini-envcal.json", "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False)


if __name__ == "__main__":
    main()

"""Why did two same-title near-equal-length files score 0.09?


Waveform cross-correlation is the strictest test there is, but it can miss the
same recording if the copies sit at different speeds, start at different
points, or differ in phase. This probes one pair three ways:
  strict   : waveform correlation, +-4 s
  wide     : waveform correlation, +-30 s
  envelope : RMS loudness/onset pattern (20 ms hops) -- survives codec, EQ,
             mild speed differences
plus a speed sweep, so a decorrelated pair is explained rather than assumed.
"""

# This file is a COMMAND, not a library: importing it used to run the pass, which
# is how a `--help` typo came to overwrite a finished plan. Run it instead:
#     python3 media/music/probe_metric.py
if __name__ != "__main__":
    raise SystemExit(__file__ + " is a command; run it, do not import it")
import json
import os
import sqlite3
import subprocess
import sys

import numpy as np

from paths import LIB
from paths import DB


def dec(path, t, secs, sr=8000):
    r = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.2f}", "-t", f"{secs}",
                        "-i", path, "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"],
                       capture_output=True, timeout=300)
    if r.returncode != 0:
        return None
    a = np.frombuffer(r.stdout, dtype=np.float32)
    return np.nan_to_num(a.astype(np.float32))


def envelope(a, sr=8000, hop=0.02):
    n = max(1, int(sr * hop))
    m = len(a) // n
    e = np.sqrt((a[:m * n].reshape(m, n) ** 2).mean(axis=1))
    return e - e.mean()


def corr_seq(ea, eb, maxlag):
    if len(ea) < 50 or len(eb) < 50:
        return -1.0, 0
    n = min(len(ea), len(eb))
    ea, eb = ea[:n], eb[:n]
    L = 1
    while L < n + maxlag:
        L *= 2
    c = np.fft.irfft(np.fft.rfft(ea, L) * np.conj(np.fft.rfft(eb, L)), L)
    d = (np.linalg.norm(ea) * np.linalg.norm(eb)) + 1e-12
    pos = np.abs(c[:maxlag + 1]) / d
    neg = np.abs(c[L - maxlag + 1:]) / d
    s = np.concatenate([pos, neg])
    k = int(s.argmax())
    lag = k if k <= maxlag else (k - len(s) + 1)
    return float(s[k]), lag


def corr_wave(a, b, maxlag_s, sr=8000):
    lag = int(maxlag_s * sr)
    n = min(len(a), len(b))
    if n < sr * 4:
        return -1.0
    a = a[:n].astype(np.float64) - np.mean(a[:n])
    b = b[:n].astype(np.float64) - np.mean(b[:n])
    na, nb = float(np.linalg.norm(a)), float(np.linalg.norm(b))
    if na < 1e-9 or nb < 1e-9:
        return -1.0
    L = 1
    while L < n + lag:
        L *= 2
    c = np.fft.irfft(np.fft.rfft(a, L) * np.conj(np.fft.rfft(b, L)), L)
    d = na * nb
    pos = np.abs(c[:lag + 1]) / d
    neg = np.abs(c[L - lag + 1:]) / d
    return float(np.max(np.concatenate([pos, neg])))


def main():
    con = sqlite3.connect(DB, uri=True)
    con.text_factory = lambda b: b.decode("utf-8", "replace")
    rows = {p: (t or "", a or "", float(d or 0), s or "")
            for p, t, a, d, s in con.execute(
                "select path,title,album,duration,suffix from media_file where missing=0")}
    pairs = [
        ("Led Zeppelin/Physical Graffiti CD1 (1975)/04 - Houses Of The Holy.flac",
         "Led Zeppelin/Mothership [Disc 1] (1969)/Disc 2/06 - Houses Of The Holy.mp3",
         "same title, 244.1 vs 244.5 s -- the mystery pair"),
        ("Led Zeppelin/In Through The Out Door (1979)/01 - In The Evening.flac",
         "Led Zeppelin/Mothership [Disc 1] (1969)/Disc 2/10 - In The Evening.mp3",
         "already 0.906 -- reference positive"),
        ("Led Zeppelin/Physical Graffiti CD1 (1975)/06 - Kashmir.flac",
         "Led Zeppelin/Mothership [Disc 1] (1969)/Disc 2/07 - Kashmir.mp3",
         "0.183 -- second mystery pair"),
    ]
    print(f"{'pair':34s} {'strict':>7s} {'wide30':>7s} {'envelope':>9s} {'lag':>6s}")
    for a, b, label in pairs:
        pa, pb = os.path.join(LIB, a), os.path.join(LIB, b)
        if not (os.path.exists(pa) and os.path.exists(pb)):
            print(f"   MISSING: {a if not os.path.exists(pa) else b}")
            continue
        da, db = rows[a][2], rows[b][2]
        A, B = dec(pa, da * 0.3, 40), dec(pb, db * 0.3, 40)
        strict = corr_wave(A, B, 4.0)
        wide = corr_wave(A, B, 30.0)
        ea, eb = envelope(A), envelope(B)
        env, lag = corr_seq(ea, eb, int(40 / 0.02))
        print(f"{label[:34]:34s} {strict:7.4f} {wide:7.4f} {env:9.4f} {lag*0.02:6.1f}s")
        # speed sweep: does a resampled version of A match B at some rate?
        best, best_r = -1.0, 1.0
        for rate in np.arange(0.94, 1.061, 0.005):
            idx = np.arange(int(len(A) / rate)).astype(np.float64) * rate
            idx = idx[idx < len(A) - 1].astype(np.int64)
            c = corr_wave(A[idx], B, 30.0)
            if c > best:
                best, best_r = c, rate
        print(f"{'':34s} speed-sweep best {best:.4f} at rate {best_r:.3f}")


if __name__ == "__main__":
    main()

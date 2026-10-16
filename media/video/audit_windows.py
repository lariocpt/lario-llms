#!/usr/bin/env python3
"""Audit a finished encode against its source at several windows, not one.


The single-window gate in enc_hevc.py rejected a good 4K Blade encode twice,
then the accepted run was measured on nothing at all (--no-ssim). Both failure
modes are the same one: one number, taken anywhere, decides a film.

Windows are taken the only way that aligns two files with different keyframe
grids: bound the read with an input-side -t (A+L), normalise each pad to zero
with setpts, THEN trim the same absolute span out of each. An input-side -ss
seeks to the nearest keyframe, which put the two pads frames apart and scored
motion instead of quality; -ss after -i does not help, because with two inputs
ffmpeg reads it as an option of the output.

  audit_windows.py ENC SRC --at 300 1200 2400
"""

# This file is a COMMAND, not a library: importing it used to run the pass, which
# is how a `--help` typo came to overwrite a finished plan. Run it instead:
#     python3 media/video/audit_windows.py
if __name__ != "__main__":
    raise SystemExit(__file__ + " is a command; run it, do not import it")
import argparse
import re
import subprocess
import sys

FF = "ffmpeg"


def windows(enc, src, at, length):
    """One decode pass per window, serving ssim AND psnr from the same frames.

    The read is bounded per window (-t a+length), not once for the whole set:
    bounding at max(at)+length makes an early window pay for decoding to the
    end of the last one, which is how a 3-window audit turned into an hour.
    """
    print(f"\n   --- SSIM + PSNR over windows {at}, {length:.0f}s each ---", flush=True)
    for a in at:
        chain = (f"[0:v]setpts=PTS-STARTPTS,format=yuv420p,split=2[x1][x2];"
                 f"[1:v]setpts=PTS-STARTPTS,format=yuv420p,split=2[y1][y2];"
                 f"[x1]trim=start={a}:end={a + length},setpts=PTS-STARTPTS[ta];"
                 f"[y1]trim=start={a}:end={a + length},setpts=PTS-STARTPTS[tb];"
                 f"[ta][tb]ssim=shortest=1[s];"
                 f"[x2]trim=start={a}:end={a + length},setpts=PTS-STARTPTS[uc];"
                 f"[y2]trim=start={a}:end={a + length},setpts=PTS-STARTPTS[ud];"
                 f"[uc][ud]psnr=shortest=1[p]")
        r = subprocess.run(
            [FF, "-nostats", "-loglevel", "info", "-t", str(a + length), "-i", enc,
             "-t", str(a + length), "-i", src, "-lavfi", chain,
             "-map", "[s]", "-map", "[p]", "-an", "-f", "null", "-"],
            capture_output=True, text=True)
        # -loglevel info, NOT -v error: the ssim/psnr summaries are logged at info
        # level, so with -v error every window "measures" as no-result
        s = re.findall(r"All:(\s*[0-9.]+|inf)", r.stderr)
        p = re.findall(r"average:([0-9.]+|inf)", r.stderr)
        if not s or not p:
            print(f"      at {a:6.0f}s  NO RESULT  "
                  f"{' '.join(r.stderr.strip().splitlines()[-2:])[-140:]}")
            continue
        print(f"      at {a:6.0f}s  SSIM {s[-1].strip()}   PSNR {p[-1].strip()} dB", flush=True)


def packet_count(path):
    """Frames actually in the container -- catches dropped tail frames, and it
    reads packet headers only, so no decoding."""
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                        "-show_packets", "-of", "csv=p=0", path],
                       capture_output=True, text=True)
    return sum(1 for l in r.stdout.splitlines() if l.strip())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("enc")
    ap.add_argument("src")
    ap.add_argument("--at", type=float, nargs="+", default=[300.0, 1200.0, 2400.0])
    ap.add_argument("--length", type=float, default=120.0)
    ap.add_argument("--no-count", action="store_true")
    a = ap.parse_args()

    if not a.no_count:
        print("   counting video packets in both containers (no decoding)...", flush=True)
        ne, ns = packet_count(a.enc), packet_count(a.src)
        delta = ne - ns
        print(f"      encode {ne} packets   source {ns} packets   delta {delta:+d}")

    windows(a.enc, a.src, a.at, a.length)
    print("\n   read: SSIM 0.97+ is transparent for a film; a single low window is a",
          "\n   hard scene (strobing, grain, fast motion), not necessarily a bad encode.",
          "\n   PSNR under ~30 dB with a low SSIM in the SAME window is real loss.")


if __name__ == "__main__":
    main()

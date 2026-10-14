"""Two questions that decide two files.


1. Forrest Gump scores SSIM 0.81 / luma PSNR 15 dB no matter the bitrate. That is
   the signature of a systematic difference -- a level or matrix shift -- not of
   compression, and the file carries NO colour metadata at all while my encoder
   tags tv range. Decide whether the low score is an artifact of the comparison
   or a real re-encode loss. It does not change the size verdict (HEVC is >=100%
   of the source size at every qp), but it decides whether "leave it alone" is
   for size reasons or because the encode is genuinely worse.

2. Cool Runnings is a PAL DVD5. ffmpeg reports 720x576 [SAR 1:1 DAR 5:4], which
   is not a real DVD aspect at all. Either the disc is 16:9 anamorphic (needs a
   DAR tag or it plays squashed), or it is a 4:3 frame with black bars baked in
   (crop them), or it is full-frame 4:3. Signalstats says which: a baked-in bar
   makes the frame's minimum luma pure black on every frame.
"""

# This file is a COMMAND, not a library: importing it used to run the pass, which
# is how a `--help` typo came to overwrite a finished plan. Run it instead:
#     python3 media/video/probe_two.py
if __name__ != "__main__":
    raise SystemExit(__file__ + " is a command; run it, do not import it")
import re
import subprocess
import os

FG = "/mnt/media/un2/Forrest Gump (1994) [1080p]/Forrest.Gump.1994.1080p.BrRip.x264.YIFY.mp4"
CR = "/mnt/media/un2/Cool.Runnings.1993.PAL.DVD5-NoGrp/VIDEO_TS"
DVD = ["-probesize", "100M", "-analyzeduration", "200M"]


def sh(a):
    return subprocess.run(a, capture_output=True, text=True)


def yavg(inp, extra=(), seek=None):
    cmd = ["ffmpeg", "-v", "error", *(["-ss", seek] if seek else []), *extra, "-i", inp,
           "-frames:v", "1", "-vf",
           "scale=320:-2,format=gray,signalstats,metadata=print:key=lavfi.signalstats.YAVG",
           "-f", "null", "-"]
    r = sh(cmd)
    y = [x for x in r.stderr.split() if "YAVG=" in x]
    return y[0].split("=")[-1] if y else f"<none: {r.stderr.strip()[:60]}>"


print("=== 1. Forrest Gump: is the low SSIM a measurement artifact? ===")
sh(["ffmpeg", "-v", "error", "-y", "-ss", "300", "-t", "120", "-i", FG, "-an", "-sn",
    "-c:v", "hevc_nvenc", "-preset", "p6", "-tune", "hq", "-rc", "constqp", "-qp", "24",
    "-pix_fmt", "p010le", "/tmp/opencode/fg2.mkv"])
print(f"   mean luma, same instant:  source {yavg(FG, seek='300')}   encode {yavg('/tmp/opencode/fg2.mkv')}")


def score(graph):
    r = sh(["ffmpeg", "-nostats", "-i", "/tmp/opencode/fg2.mkv",
            "-ss", "300", "-t", "120", "-i", FG, "-lavfi", graph, "-an", "-f", "null", "-"])
    s = re.search(r"SSIM\b[^\n]*?All:([0-9.]+)", r.stderr)
    p = re.search(r"PSNR y:([0-9.]+)", r.stderr)
    f = re.findall(r"frame=\s*(\d+)", r.stderr)
    return (round(float(s.group(1)), 4) if s else None), (round(float(p.group(1)), 1) if p else None), \
        (f[-1] if f else "0")


for name, g in {
    "plain format=yuv420p": "[0:v]format=yuv420p[a];[1:v]format=yuv420p[b];[a][b]ssim",
    "both marked full range": "[0:v]format=yuv420p,setrange=1[a];[1:v]format=yuv420p,setrange=1[b];[a][b]ssim",
    "both marked limited range": "[0:v]format=yuv420p,setrange=0[a];[1:v]format=yuv420p,setrange=0[b];[a][b]ssim",
}.items():
    s, _, n = score(g)
    print(f"      SSIM {str(s):>8}  frames {n}   ({name})")
r = sh(["ffmpeg", "-nostats", "-i", "/tmp/opencode/fg2.mkv", "-ss", "300", "-t", "120", "-i", FG,
        "-lavfi", "[0:v]format=yuv420p[a];[1:v]format=yuv420p[b];[a][b]psnr", "-an", "-f", "null", "-"])
m = re.search(r"PSNR y:([0-9.]+) u:([0-9.]+) v:([0-9.]+) average:([0-9.]+)", r.stderr)
print(f"      psnr y/u/v/avg: {m.groups() if m else 'none'}")

print("\n=== 2. Cool Runnings: anamorphic, letterboxed, or full-frame? ===")
vob = os.path.join(CR, "VTS_01_1.VOB")
for ss in (60, 600, 1200, 1500):
    r = sh(["ffmpeg", "-v", "error", *DVD, "-ss", str(ss), "-t", "40", "-i", vob,
            "-vf", "cropdetect=24:2:0,signalstats,metadata=print:key=lavfi.signalstats.YMIN",
            "-an", "-sn", "-f", "null", "-"])
    mins = [float(x.split("=")[1]) for x in r.stderr.split() if "YMIN=" in x]
    crops = sorted({x.split("crop=")[1].split("]")[0].split()[0] for x in r.stderr.split() if "crop=" in x})
    if not mins:
        print(f"      @{ss:>4}s  nothing decoded: {r.stderr.strip()[:80]}")
        continue
    nb = sum(1 for m in mins if m <= 20)
    print(f"      @{ss:>4}s  frames {len(mins):>3}  with-black-bar {nb:>3}  "
          f"YMIN min {min(mins):>3.0f} med {sorted(mins)[len(mins)//2]:>3.0f}  cropdetect {crops[:2]}")
r = sh(["ffmpeg", "-hide_banner"] + DVD + ["-i", vob])
for l in r.stderr.splitlines():
    if "Video:" in l:
        print(f"      ffmpeg reads it as: {l.strip()[:120]}")
r = sh(["ffprobe", "-v", "error", *DVD, "-select_streams", "a", "-show_entries",
        "stream=codec_name,channels,bit_rate,language", "-print_format", "csv=p=0",
        os.path.join(CR, "VTS_01_0.VOB")])
print(f"      audio tracks: {r.stdout.strip().replace(chr(10), ' | ') or 'none reported'}")

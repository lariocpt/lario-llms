"""Everything still open about the Cool Runnings DVD, measured rather than assumed.


ffmpeg reported SAR 1:1 DAR 5:4 for this disc at the default probesize and the
honest SAR 64:45 DAR 16:9 with a bigger one, so nothing here is trusted until it
appears with the flags on.

Three questions:
  geometry  -- cropdetect's real output, so the crop rectangle is parsed from the
               format this build actually prints (it logs crop:W:H:X:Y, not crop=)
  audio     -- how many tracks, how many channels, which languages. ffprobe said
               "0 channels" through the concat: URL; per-VOB with a bigger probe
               it may speak.
  interlace -- top-field-first is a FLAG, not evidence of combs. A film-origin
               PAL transfer is usually 2:2 with no combs at all, in which case
               deinterlacing would only soften the picture for nothing. idf
               scores each frame for combing; that decides.
"""

# This file is a COMMAND, not a library: importing it used to run the pass, which
# is how a `--help` typo came to overwrite a finished plan. Run it instead:
#     python3 media/video/probe_dvd.py
if __name__ != "__main__":
    raise SystemExit(__file__ + " is a command; run it, do not import it")
import re
import subprocess

CR = "/mnt/media/un2/Cool.Runnings.1993.PAL.DVD5-NoGrp/VIDEO_TS"
VOB0 = f"{CR}/VTS_01_0.VOB"
VOB1 = f"{CR}/VTS_01_1.VOB"
DVD = ["-probesize", "100M", "-analyzeduration", "200M"]
FG = "/mnt/media/un2/Forrest Gump (1994) [1080p]/Forrest.Gump.1994.1080p.BrRip.x264.YIFY.mp4"


def sh(a):
    return subprocess.run(a, capture_output=True, text=True)


print("=== geometry: cropdetect verbatim (info level, bigger probe) ===")
for ss in (60, 600, 1500):
    r = sh(["ffmpeg", "-nostats", *DVD, "-ss", str(ss), "-t", "60", "-i", VOB1,
            "-vf", "cropdetect=24:2:0", "-an", "-sn", "-f", "null", "-"])
    lines = [l.strip() for l in r.stderr.splitlines() if "crop" in l.lower()]
    print(f"   @{ss:>4}s  {lines[-1][:110] if lines else 'nothing: ' + r.stderr.strip()[:90]}")

print("\n=== bars: how many sampled frames reach pure black (info level) ===")
for ss in (60, 600, 1500):
    r = sh(["ffmpeg", "-nostats", *DVD, "-ss", str(ss), "-t", "30", "-i", VOB1,
            "-vf", "scale=352:-2,format=gray,signalstats,"
                   "metadata=print:key=lavfi.signalstats.YMIN",
            "-an", "-sn", "-f", "null", "-"])
    mins = [float(x.split("=")[1]) for x in r.stderr.replace("\n", " ").split() if "YMIN=" in x]
    if not mins:
        print(f"   @{ss:>4}s  no YMIN at all -- {r.stderr.strip()[:90]}")
        continue
    nb = sum(1 for m in mins if m <= 20)
    print(f"   @{ss:>4}s  frames {len(mins):>3}  black-topped {nb:>3}  "
          f"YMIN min {min(mins):>3.0f} med {sorted(mins)[len(mins)//2]:>3.0f}")

print("\n=== audio, per VOB with a real probe ===")
for vob in (VOB0, VOB1):
    r = sh(["ffprobe", "-v", "error", *DVD, "-show_streams", "-print_format", "json", vob])
    import json
    try:
        j = json.loads(r.stdout or "{}")
    except json.JSONDecodeError:
        print(f"   {vob.split('/')[-1]}: unparsable -- {r.stderr.strip()[:80]}")
        continue
    for s in j.get("streams", []):
        if s.get("codec_type") == "audio":
            print(f"   {vob.split('/')[-1]}  {s.get('codec_name'):>5} "
                  f"ch={s.get('channels')} {s.get('sample_fmt', '-')} "
                  f"{int(s.get('bit_rate', 0)) // 1000}kb/s lang={s.get('tags', {}).get('language', '?')}")

print("\n=== interlace: are there combs? (idf scores each frame) ===")
for ss in (60, 600, 1500):
    r = sh(["ffmpeg", "-nostats", *DVD, "-ss", str(ss), "-t", "20", "-i", VOB1,
            "-vf", "idf", "-an", "-sn", "-f", "null", "-"])
    tot = re.findall(r"Ratio is ([0-9.]+)T", r.stderr)
    cnt = re.findall(r"Ratio is [0-9.]+T \[([0-9]+) of", r.stderr)
    scored = [float(x) for x in tot]
    if not scored:
        line = [l.strip() for l in r.stderr.splitlines() if "atio" in l or "deinterlac" in l.lower()]
        print(f"   @{ss:>4}s  idf said nothing -- {(line[-1][:90] if line else r.stderr.strip()[:90])}")
        continue
    combed = sum(1 for i, x in enumerate(scored) if x > 3.0)
    print(f"   @{ss:>4}s  frames {len(scored):>3}  combed(>3.0) {combed:>3}  "
          f"median T {sorted(scored)[len(scored)//2]:.2f}  "
          f"max {max(scored):.1f}   (near 0 = progressive 2:2, >3 = real interlace)")

print("\n=== Forrest Gump, mean luma with verbosity kept (the -v error trap) ===")
for tag, inp, extra in (("source", FG, ["-ss", "300"]), ("encode", "/tmp/opencode/fg2.mkv", [])):
    r = sh(["ffmpeg", "-nostats", *extra, "-i", inp, "-frames:v", "1", "-vf",
            "scale=320:-2,format=gray,signalstats,metadata=print:key=lavfi.signalstats.YAVG",
            "-f", "null", "-"])
    y = [x for x in r.stderr.replace("\n", " ").split() if "YAVG=" in x]
    print(f"   {tag:<7} {y[0] if y else 'nothing'}")

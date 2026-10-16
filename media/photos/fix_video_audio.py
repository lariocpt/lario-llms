#!/usr/bin/env python3
"""Repair the 13 outputs of the import transcode that the audio-probe bug hit.


The script's probe passed -select_streams v:0, so ffprobe never reported the
audio streams. Every encode therefore ran with -c:a copy. That is harmless for
AAC/MP3 sources, but PCM-in-MP4 is legal-but-awkward (7 clips kept their PCM
track) and for 5 files it failed outright, so they were left as byte-for-byte
copies of the source - including a 1,019 MB raw .vob for the Canopy Tour disc.

Two repairs, both from what is already in the video library (the hhd sources of
these files were removed by the copy step):

  remux  -c:v copy -c:a aac 192k for the 8 files whose video is fine and whose
         audio is PCM or AC3: the HEVC bitstream is not touched, so no second
         generation
  re-encode  the 5 files that were never encoded, HEVC cq23 + AAC 192k, verified
         (duration within 1 %, strict decode, smaller than what it replaces)
         before the file it replaces is removed

manifest-videos.csv rows are rewritten in place.

Usage: python3 fix_video_audio.py [--dry] [--only SUBSTR]
"""

# This file is a COMMAND, not a library: importing it used to run the pass, which
# is how a `--help` typo came to overwrite a finished plan. Run it instead:
#     python3 media/photos/fix_video_audio.py
if __name__ != "__main__":
    raise SystemExit(__file__ + " is a command; run it, do not import it")
import argparse
import csv
import json
import os
import re
import subprocess

from paths import W        # evidence root: config.PHOTO_WORK, env W
os.makedirs(W, exist_ok=True)      # one evidence root for the whole pass
from paths import VIDLIB as VDIR
MANIFEST = f'{W}/manifest-videos.csv'
FFMPEG = '/usr/bin/ffmpeg'
CQ = 23

# transcode_import_videos.py is a command; load it as text with its trailing call
# removed so that asking it for probe/decode_clean does not start a transcode.
# (It used to read the copy in the work dir, which meant this file silently
# depended on that checkout staying put.)
_here = os.path.dirname(os.path.abspath(__file__))
_mod = {'__name__': 'transcode_import_videos'}
_lines = open(os.path.join(_here, 'transcode_import_videos.py')).read().split('\n')
while _lines and _lines[-1].strip() in ('', 'main()', 'if __name__ == "__main__":'):
    _lines.pop()
exec(compile('\n'.join(_lines), 'transcode_import_videos.py', 'exec'), _mod)
probe, decode_clean = _mod['probe'], _mod['decode_clean']


def run(cmd, t=3600):
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=t)
    return p.returncode, (p.stderr or '').strip()


def audio_of(path):
    r = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'a', '-show_entries',
                        'stream=codec_name', '-of', 'csv=p=0', path],
                       capture_output=True, text=True).stdout.strip().strip(',')
    return r or 'none'


def build():
    rows = list(csv.DictReader(open(MANIFEST)))
    new = [r for r in rows if r['orig'].startswith(('Mac Photos/', 'Photosusa/'))]
    jobs = []
    for r in new:
        p = os.path.join(VDIR, r['dest'])
        a = audio_of(p)
        ext = os.path.splitext(r['dest'])[1].lower()
        if a in ('aac', 'mp3', 'none') and ext == '.mp4':
            continue          # already the library's normal shape
        if a in ('aac', 'mp3', 'none'):
            continue          # a deliberate untouched copy of the source bytes
        kind = 'remux' if r['mode'] == 'nvenc' and ext == '.mp4' else 're-encode'
        jobs.append({'row': r, 'path': p, 'audio': a, 'kind': kind})
    return rows, new, jobs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry', action='store_true')
    ap.add_argument('--only', default='')
    a = ap.parse_args()

    rows, new, jobs = build()
    if a.only:
        jobs = [j for j in jobs if a.only.lower() in j['row']['dest'].lower()]
    print(f'{len(new)} import rows, {len(jobs)} to repair: '
          f"{sum(1 for j in jobs if j['kind'] == 'remux')} remux, "
          f"{sum(1 for j in jobs if j['kind'] == 're-encode')} re-encode")
    for j in jobs:
        print(f"  {j['kind']:9} {j['audio']:10} {int(j['row']['in_bytes']) / 2**20:8.1f} MB  "
              f"{j['row']['dest'][:66]}")
    if a.dry:
        return

    for j in jobs:
        row, src, kind = j['row'], j['path'], j['kind']
        info = probe('-i', src, size_hint=os.path.getsize(src))
        was = os.path.getsize(src)
        tmp = src + '.fix.mp4'
        if kind == 'remux':
            cmd = [FFMPEG, '-hide_banner', '-loglevel', 'error', '-y', '-i', src,
                   '-map', '0:v:0', '-map', '0:a?', '-map', '0:s?',
                   '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', '-c:s', 'copy',
                   '-map_metadata', '0', '-movflags', '+faststart', tmp]
            note = 'audio remuxed to AAC 192k, HEVC bitstream copied'
        else:
            cmd = [FFMPEG, '-hide_banner', '-loglevel', 'error', '-y', '-i', src,
                   '-map', '0:v:0', '-map', '0:a?', '-map', '0:s?']
            if info['interlaced']:
                cmd += ['-vf', 'yadif=0:-1:0']
            cmd += ['-c:v', 'hevc_nvenc', '-preset', 'p5', '-tune', 'hq',
                    '-rc', 'vbr', '-cq', str(CQ), '-b:v', '0', '-tag:v', 'hvc1',
                    '-pix_fmt', 'p010le' if info['tenbit'] else 'yuv420p',
                    '-c:a', 'aac', '-b:a', '192k', '-c:s', 'copy', '-map_metadata', '0',
                    '-movflags', '+faststart']
            if row['dt']:
                cmd += ['-metadata', f"creation_time={row['dt'].replace(' ', 'T')}Z"]
            cmd += [tmp]
            note = ('re-encoded HEVC cq23 + AAC 192k (the first attempt copied its '
                    'PCM audio, which MP4 rejects)')
        rc, err = run(cmd)
        if rc != 0:
            print(f'  FAILED {row["dest"][:50]}: {err[-160:]}')
            if os.path.exists(tmp):
                os.unlink(tmp)
            continue
        out = probe('-i', tmp, size_hint=os.path.getsize(tmp))
        sz = os.path.getsize(tmp)
        bad = []
        if out['dur'] < info['dur'] * 0.99:
            bad.append(f'duration {info["dur"]:.1f} -> {out["dur"]:.1f}')
        if sz >= os.path.getsize(src):
            bad.append(f'not smaller: {os.path.getsize(src) / 2**20:.1f} -> {sz / 2**20:.1f} MB')
        if audio_of(tmp) not in ('aac', 'mp3'):
            bad.append('audio still ' + audio_of(tmp))
        if kind == 're-encode' and out['codec'] != 'hevc':
            bad.append('video not hevc: ' + str(out['codec']))
        if kind == 'remux' and (out['codec'], out['w'], out['h']) != (info['codec'], info['w'], info['h']):
            bad.append('video bitstream changed')
        if not bad:
            clean, detail, _ = decode_clean(tmp)
            if not clean:
                bad.append('decode: ' + detail[:120])
        if bad:
            print(f'  REJECTED {row["dest"][:50]}: {("; ".join(bad))[:150]}')
            if os.path.exists(tmp):
                os.unlink(tmp)
            continue
        # the old file is only removed once the replacement is verified; the
        # name changes for the re-encodes because they become .mp4
        final = re.sub(r'\.(vob|avi|mov|dv|mpg)$', '.mp4', src, flags=re.I) if kind == 're-encode' else src
        os.replace(tmp, final)
        if final != src:
            os.unlink(src)
        row['dest'] = os.path.relpath(final, VDIR)
        row['dest_name'] = os.path.basename(final)
        row['out_bytes'] = sz
        row['ratio'] = round(sz / int(row['in_bytes']), 3)
        if kind == 're-encode':
            row['mode'] = 'nvenc'
            row['vcodec'] = out['codec']
            row['w'], row['h'] = out['w'], out['h']
        row['note'] = (row['note'] + '; ' if row['note'] else '') + note
        print(f'  {kind:9} {was / 2**20:7.1f} -> {sz / 2**20:7.1f} MB  {row["dest"][:60]}')

    with open(MANIFEST, 'w', newline='', encoding='utf-8') as fh:
        wr = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        wr.writeheader()
        wr.writerows(rows)
    left = build()[2]
    print(f'manifest rewritten; {len(left)} rows still needing repair')
    new = [r for r in csv.DictReader(open(MANIFEST))
           if r['orig'].startswith(('Mac Photos/', 'Photosusa/'))]
    print('import videos now: %.2f GiB from %.2f GiB (-%.1f %%)' % (
        sum(int(r['out_bytes']) for r in new) / 2**30, sum(int(r['in_bytes']) for r in new) / 2**30,
        (1 - sum(int(r['out_bytes']) for r in new) / sum(int(r['in_bytes']) for r in new)) * 100))
    json.dump({'fixed': len(jobs), 'still_open': len(left)},
              open(f'{W}/fix-video-audio.json', 'w'), indent=1)


if __name__ == "__main__":
    main()

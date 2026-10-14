
# This file is a COMMAND, not a library: importing it used to run the pass, which
# is how a `--help` typo came to overwrite a finished plan. Run it instead:
#     python3 media/photos/tmp_vfr_test.py
if __name__ != "__main__":
    raise SystemExit(__file__ + " is a command; run it, do not import it")
import json

import os
import subprocess

FF = '/usr/bin/ffmpeg'
FP = '/usr/bin/ffprobe'
SRC = '/mnt/xfs/photos-originals-backup/March 27, 2017/Photos - 3433 of 6286.mp4'
TMP = '/tmp/opencode/vfr-test'
os.makedirs(TMP, exist_ok=True)


def ff(out, *extra):
    cmd = [FF, '-hide_banner', '-nostdin', '-y', '-i', SRC, '-map', '0:v:0', '-map', '0:a?'] \
        + list(extra) + ['-c:v', 'hevc_nvenc', '-preset', 'p3', '-tune', 'hq', '-rc', 'vbr',
                         '-cq', '23', '-b:v', '0', '-tag:v', 'hvc1', '-pix_fmt', 'yuv420p',
                         '-c:a', 'copy', '-movflags', '+faststart', out]
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.returncode, (r.stderr or '')[-120:]


def frames(p):
    r = subprocess.run([FP, '-v', 'error', '-select_streams', 'v:0', '-count_frames',
                        '-show_entries', 'stream=nb_read_frames,avg_frame_rate', '-of', 'json', p],
                       capture_output=True, text=True)
    s = (json.loads(r.stdout or '{}').get('streams') or [{}])[0]
    return s.get('nb_read_frames'), s.get('avg_frame_rate')


def dur(p):
    r = subprocess.run([FP, '-v', 'error', '-show_entries', 'format=duration', '-of', 'json', p],
                       capture_output=True, text=True)
    return (json.loads(r.stdout or '{}').get('format') or {}).get('duration')


CASES = {
    'passthrough': ['-fps_mode', 'passthrough'],
    'cfr30': ['-fps_mode', 'cfr', '-r', '30'],
    'cfr60': ['-fps_mode', 'cfr', '-r', '60'],
    'vfr_enc_tb': ['-fps_mode', 'vfr', '-enc_time_base', '1/90000'],
}
for name, extra in CASES.items():
    out = os.path.join(TMP, name + '.mp4')
    rc, err = ff(out, *extra)
    if rc != 0:
        print(f'{name:12} rc={rc} {err}')
        continue
    print(f'{name:12} frames/avg={frames(out)} dur={dur(out)} size={os.path.getsize(out)}')
print('source     frames/avg=', frames(SRC), 'dur=', dur(SRC), 'size=', os.path.getsize(SRC))

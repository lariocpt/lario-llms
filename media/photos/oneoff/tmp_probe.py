
# This file is a COMMAND, not a library: importing it used to run the pass, which
# is how a `--help` typo came to overwrite a finished plan. Run it instead:
#     python3 media/photos/tmp_probe.py
if __name__ != "__main__":
    raise SystemExit(__file__ + " is a command; run it, do not import it")
import json

import re
import subprocess

FP = '/usr/bin/ffprobe'
FF = '/usr/bin/ffmpeg'
SRCS = ['/mnt/xfs/photos-originals-backup/March 27, 2017/Photos - 3433 of 6286.mp4',
        '/mnt/xfs/photos-originals-backup/b041a19f-4047-47f8-928c-5f1efce5de1b.mp4',
        '/mnt/xfs/videos/videos/2017/2017-03-27 March 27/001_20170327-105113.mp4']


def packets(p):
    r = subprocess.run([FP, '-v', 'error', '-select_streams', 'v:0', '-count_packets',
                        '-show_entries', 'stream=nb_read_packets', '-of', 'json', p],
                       capture_output=True, text=True)
    return (json.loads(r.stdout or '{}').get('streams') or [{}])[0].get('nb_read_packets')


def decoded(p, *extra):
    cmd = [FF, '-nostdin', '-nostats', '-i', p, '-map', '0:v:0'] + list(extra) + \
          ['-vf', 'metadata=print:file=-', '-f', 'null', '-']
    r = subprocess.run(cmd, capture_output=True, text=True)
    return (r.stdout or '').count('frame_tags') or len(re.findall(r'frame=\s*(\d+)', r.stderr or ''))


for p in SRCS:
    print(f'{p[-46:]}')
    print(f'   packets={packets(p)}  frames_out_default={decoded(p)}'
          f'  vfr={decoded(p, "-fps_mode", "vfr")}'
          f'  passthrough={decoded(p, "-fps_mode", "passthrough")}')

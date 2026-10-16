#!/usr/bin/env python3
"""exiftool capture for a file list, jsonl, resumable.


usage: meta_capture.py <listfile> <out.jsonl> [batch]

Same tag set the originals were captured with (meta_backup.json), plus the few
the import needs: GPS, Make/Model, orientation, Live Photo markers.
"""

# This file is a COMMAND, not a library: importing it used to run the pass, which
# is how a `--help` typo came to overwrite a finished plan. Run it instead:
#     python3 media/photos/meta_capture.py
if __name__ != "__main__":
    raise SystemExit(__file__ + " is a command; run it, do not import it")
import json
import os
import subprocess
import sys

EXIF = '/home/lario/.local/bin/exiftool'
TAGS = ['-q', '-n', '-skipBinary', '-api', 'LargeFileSupport=1', '-charset', 'filename=utf8',
        '-json', '-G1',
        '-FileType', '-FileTypeExtension', '-MIMEType', '-FileSize', '-FileModifyDate',
        '-ImageSize', '-ImageWidth', '-ImageHeight', '-Orientation', '-ColorComponents',
        '-Make', '-Model', '-Software', '-LensID',
        '-DateTimeOriginal', '-CreateDate', '-ModifyDate', '-OffsetTimeOriginal',
        '-Time:all', '-XMP:DateCreated', '-XMP:CreateDate', '-XMP:ModifyDate',
        '-GPSLatitude', '-GPSLongitude', '-GPSAltitude', '-GPSLatitudeRef', '-GPSLongitudeRef',
        '-RunTimeSeconds', '-ContentIdentifier', '-ItemRefType', '-PrimaryItemFile',
        '-ThumbnailImage', '-m', '--']


def main():
    lst, out = sys.argv[1], sys.argv[2]
    batch = int(sys.argv[3]) if len(sys.argv) > 3 else 200
    done = set()
    if os.path.exists(out):
        with open(out) as fh:
            for line in fh:
                try:
                    done.add(json.loads(line)['SourceFile'])
                except Exception:
                    pass
    files = [l.strip() for l in open(lst) if l.strip() and l.strip() not in done]
    print(f'{len(files)} to capture, {len(done)} done', flush=True)
    n = 0
    with open(out, 'a') as fh:
        for i in range(0, len(files), batch):
            chunk = files[i:i + batch]
            res = subprocess.run([EXIF, *TAGS, *chunk], capture_output=True, text=True).stdout
            try:
                recs = json.loads(res or '[]')
            except Exception:
                print(f'  batch {i} failed to parse', flush=True)
                continue
            for rec in recs:
                fh.write(json.dumps(rec) + '\n')
            n += len(recs)
            if (i // batch) % 10 == 0:
                print(f'  {n}/{len(files)}', flush=True)
    print(f'done: {n}', flush=True)


if __name__ == '__main__':
    main()

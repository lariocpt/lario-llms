#!/usr/bin/env python3
"""Take the last archive out of the photo library, and clear the scratch that the

archive audit no longer needs.

  Misc/Paris.zip        31 entries, every one the original of a photo the library
                        holds recompressed (trace_library_zip.py prints each
                        match). Not unique content, but the last full-quality copy
                        of those 31 shots and there is no backup anywhere, so it
                        is kept - outside the photo library, where a zip does not
                        belong.

  zip-extract/          the two archives' content, staged for the audit. All 853
                        files are proven represented (verify_archive_claim.py:
                        608 imported originals, 205 accounted old originals, 40
                        byte-identical to a live file, 0 unrepresented), and the
                        archives themselves are gone. The record stays in
                        zip-ledger.csv, zip-provenance.jsonl and hashes_zips.jsonl.

  python3 finish_cleanup.py         plan only
  GO=1 python3 finish_cleanup.py    do it
"""

# This file is a COMMAND, not a library: importing it used to run the pass, which
# is how a `--help` typo came to overwrite a finished plan. Run it instead:
#     python3 media/photos/finish_cleanup.py
if __name__ != "__main__":
    raise SystemExit(__file__ + " is a command; run it, do not import it")
import csv
import os
import shutil

from paths import W        # evidence root: config.PHOTO_WORK, env W
os.makedirs(W, exist_ok=True)      # one evidence root for the whole pass
from paths import LIB
GO = os.environ.get('GO') == '1'
ZIP = f'{LIB}/Misc/Paris.zip'
KEEP_DIR = f'{W}/kept-originals'
STAGING = f'{W}/zip-extract'


def main():
    rows = []
    if os.path.exists(ZIP):
        dest = os.path.join(KEEP_DIR, os.path.basename(ZIP))
        size = os.path.getsize(ZIP)
        print(f'move {ZIP}\n  -> {dest}  ({size / 2**20:.1f} MB, '
              '31 originals of photos the library holds recompressed)')
        if GO:
            os.makedirs(KEEP_DIR, exist_ok=True)
            shutil.move(ZIP, dest)
            if os.path.getsize(dest) != size:
                raise SystemExit(f'the moved copy is a different size: {dest}')
            with open(f'{KEEP_DIR}/README.txt', 'w', encoding='utf-8') as fh:
                fh.write(
                    'Paris.zip\n\n'
                    'The 31 photographs inside are in the library, recompressed to '
                    'q85, under\n2007/2007-01-08 Paris, 2007/2007-01-09 Paris and '
                    '2007/2007-01-20 Paris - entry by\nentry proof in '
                    'library-zip-evidence.json and trace_library_zip.py.\n\n'
                    'This is the only copy of those 31 at the original quality. '
                    'There is no\nbackup of anything, which is why it is kept here '
                    'instead of deleted, and\nwhy it should be part of whatever '
                    'backup is made.\n')
            rows.append([ZIP, dest, str(size),
                         'duplicate container, kept: last full-quality copy of the 31 '
                         'photographs; zip files do not belong in the photo library'])
            print('  README.txt written beside it')
            if not os.listdir(os.path.dirname(ZIP)):
                os.rmdir(os.path.dirname(ZIP))
                print(f'  pruned the empty {os.path.dirname(ZIP)}')
    else:
        print(f'already moved: {ZIP}')

    if os.path.isdir(STAGING):
        n = sum(len(fs) for _, _, fs in os.walk(STAGING))
        b = sum(os.path.getsize(os.path.join(dp, f))
                for dp, _, fs in os.walk(STAGING) for f in fs)
        print(f'remove {STAGING}: {n} files, {b / 2**30:.2f} GiB, all proven '
              'represented elsewhere')
        if GO:
            shutil.rmtree(STAGING)
            rows.append([STAGING, '', str(b),
                         f'staging for the archive audit: {n} files, every one proven '
                         'represented by library content (verify_archive_claim.py)'])
        print(f'  {"removed" if GO else "would remove"}')
    else:
        print(f'already removed: {STAGING}')

    if rows:
        path = f'{W}/manifest-relocations.csv'
        header = ['from', 'to', 'bytes', 'reason']
        new = not os.path.exists(path)
        with open(path, 'a', newline='', encoding='utf-8') as fh:
            wr = csv.writer(fh)
            if new:
                wr.writerow(header)
            wr.writerows(rows)
        print(f'{len(rows)} row(s) appended to {os.path.basename(path)}')
    print('(plan only; GO=1 to apply)' if not GO else 'done')


if __name__ == "__main__":
    main()

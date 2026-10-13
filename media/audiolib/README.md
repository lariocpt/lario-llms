# quranaudiobooks.com M4B library fetcher

Fetches the M4B section of <https://quranaudiobooks.com/downloads/> into
`/mnt/media/audiobooks/islam` on bigcachy. Exposed as the `lario_audiolib` MCP
(catalog / start / status / cancel / refresh); the controller is also a plain
CLI. It stores what pCloud serves, byte-for-byte, and never re-encodes — see
*Encoding* below for why that is the whole story on the 46 GB.

## How it works

`catalog.json` is the source of truth and is committed, so a job is reproducible
and reviewable in git: 3 297 files, 46.01 GB (42.85 GiB), scraped from the six
M4B collection folders plus the one item-level folder they do not cover
(`Mix Collection/Volume-4`). Each entry keeps its pCloud `code`/`fileid`, the
relative path it will land at, and `source` — the original pCloud path, so any
file can be traced back. The site's own tree is kept verbatim apart from
`ROOT_MAP` (the source root is misspelled `Suplications` and parks everything
else flat). Excluded on purpose: `.DS_Store` and iTunes'
`.iampreventingitunesfromremovingmyparentfolder` (12 files), and one
extensionless file that sits next to the same name with `.m4b` at 2 kB apart —
two copies of one lecture that no player can tell apart.

A job is a detached process (`setsid`-equivalent via `start_new_session`) that
outlives the caller, because 46 GB does not fit in one tool call:

- **Resume** is disk state, not a saved cursor: a file is skipped when it exists
  at the expected byte size, everything else is fetched into `<name>.part`,
  which curl continues.
- **Verify** is the byte size declared in the catalog; only then is the `.part`
  renamed into place, so an interrupted transfer can never look like a finished
  one. This is a size check, not a hash check — pCloud public links expose no
  digest, so a silent bit-flip inside a correctly-sized file is not detected.
- **Cancel** TERMinates the process group; in-flight files stay `.part` and the
  next start continues them. A cancel is recorded as `STOP`, never as a failure.
- **Logs** live with the library, under
  `/mnt/media/audiobooks/.audiolib-jobs/j-<job-id>/`: `run.log`, `ledger.tsv`
  (every file: OK/SKIP/STOP/FAIL), `progress.json`, `result.json`.

The public-link download URL expires within minutes, so it is re-requested per
attempt and rotates hosts on retry. Throughput is account-throttled: 4 and 6
workers both measured ~8–9 MiB/s, so the whole library is a ~80-minute job
regardless of worker count. `start` refuses when the free space on `/mnt/media`
is less than the missing bytes plus a floor (`min_free_gb`, default 20).

## Encoding: the library is already compressed, so nothing is free

Measured 2026-10-13 over 34 files (407 MiB, 14.4 h) sampled across all eight
collections, decoded with `ffprobe`:

| Codec | Sample rate | Channels | Audio bitrate | Share of file that is audio |
|---|---|---|---|---|
| AAC (LC) | 32 kHz | mono | ~63 kbps | 96.1% overall |
| MP3 | 44.1 kHz | stereo | ~115 kbps (Mix Collection only, 0.13 GB) | 96.8% |

That is ~1 550 hours of speech already encoded at 64 kbps mono. What a
re-encode actually buys (7 files, 3.44 h, 97 MiB baseline, ffmpeg 7.x):

| Variant | Size | Saving | Projected library |
|---|---:|---:|---:|
| original as published | 97 MiB | — | 42.85 GiB |
| strip cover art/chapters, copy audio | 95 MiB | 1.9% | 42.1 GiB |
| re-encode AAC 64k (matching the source) | 97 MiB | −0.2% | 43.0 GiB |
| re-encode AAC 48k | 73 MiB | 24.6% | 32.3 GiB |
| re-encode AAC 40k | 62 MiB | 36.7% | 27.2 GiB |
| Opus 40k mono (`.mka`, breaks M4B players) | 65 MiB | 32.6% | 28.9 GiB |
| Opus 32k mono (`.mka`) | 54 MiB | 44.7% | 23.7 GiB |

Re-encoding at the source's own rate gains nothing (−0.2%), which confirms the
published files are already at 64 kbps with ~4% of the container spent on
embedded cover art and chapter tracks. Everything smaller is a **second lossy
generation over 1 550 hours of recitation**, and recitation is the hardest case
for a low-bitrate codec: sustained tonal voice, not conversational speech.

So the policy here is: **no transcoding**. 46 GB is 4% of a volume with 1.1 TB
free, and the only lever that saves real space is discarding content (e.g. the
13 translation sets share one language) or accepting a quality loss the tool
will not make silently. Encoding is deliberately not implemented, so it cannot
become a default someone enables by habit. If size ever matters more than this,
do it as a separate verified pass over the completed copy — that keeps the
originals until a replacement is measured, exactly like `rtx5080/encoder` does
for video.

Caveat on the quality claim: lossy-vs-lossy comparison defeated my spectral
harness (an encoder-vs-encoder LSD of ~4 dB appeared even at the bit-matched
64 kbps setting, where the difference is re-quantisation disagreement rather
than audible damage), so the size numbers above are solid and the *quality*
cost is an audition question, not a measured one. Samples for listening:
`/mnt/media/audiobooks/encoding-audition-2026-10-13/` (original, AAC 48k and
AAC 40k of the same file). Judging it is a listening decision, and this tool
takes it out of the download path either way.

## Why M4B and not the site's MP3s

The same site publishes an MP3 section. Priced 2026-10-13 by listing all 156
distinct MP3 public links and summing them: **5 902 files, 168.94 GB** against
the 3 297 files / 46.01 GB installed here — 3.7x the bytes for the same
recordings, and no playback benefit. Everything on disk is AAC in an MP4
container (3 275 files, 32 kHz mono except 228 at 44.1 kHz stereo) or MP3 (22,
the Mix Collection as published); both play natively on iOS and direct-play
through Audiobookshelf with no transcode.

The Opus rows in the table above are *hypothetical re-encodes that were
rejected*, not files on disk. Opus in an `.m4a`/`.m4b` container is not playable
on iOS or QuickTime, which is one of the reasons that variant was rejected.

## Single writer per library

`start` refuses when `.lock` in the job root is held, and the runner takes that
`flock` itself — a check before a spawn only races with the spawn. It is
enforced by the OS rather than by `.state/` on purpose: state files only record
jobs *this* controller started, and the writer that matters is the one started by
something else. Two jobs over one tree share a `<name>.part` path, so one can
rename a size-verified file into the library while the other still holds that
path open and keeps appending to it, silently corrupting a finished file.

That is not hypothetical: three concurrent jobs ran on 2026-10-13, spawned by a
controller test that redirected only `STATE_DIR` and fell through a failed
assertion into a real start. Four finished files came back oversized (38.7 MB
expected against 44.9 MB on disk); size verification caught every one and a
resume pass repaired them. `tests/test_audiolib.py` now patches `Popen` for the
whole controller class and asserts nothing spawned.

A job killed mid-transfer leaves its `.part` files behind, and the runner never
deletes what it has not verified — the orphans are safe to remove once the
destination beside them is byte-verified, and only then.

## Usage

```sh
python3 media/audiolib/catalog.py show              # what the catalog holds
python3 media/audiolib/controller.py catalog        # catalog + what is on disk
python3 media/audiolib/controller.py start          # whole library, 4 workers
python3 media/audiolib/controller.py start --json '{"include": ["Quran/Tafseer"], "workers": 6}'
python3 media/audiolib/controller.py status         # progress, rate, ETA, failures
python3 media/audiolib/controller.py cancel
python3 media/audiolib/controller.py refresh        # re-scrape the site, report the delta
```

`include` takes catalog prefixes (`Quran`, `Quran/Tafseer`,
`Speeches/Shaykh Abdur Rahman ibn Yusuf`) and an interrupted library is resumed
by starting again. Tests: `python3 tests/test_audiolib.py` (offline; fixtures, no
network, writes nothing outside a temp dir).

The MCP server is the one piece not written yet: it will live in
`machine-setup/shared/agents/audiolib_tools.py` and reach this controller
directly on bigcachy, over owner SSH elsewhere; consumer clients get
`audiolib_catalog`/`audiolib_status` only, and no job control. Until then the
controller CLI above is the whole interface.

## Known limits

- Verifies size, not content (see above). Nothing here deletes a file it did not
  just write as `.part`; a `.part` longer than the expected size is the one
  thing it removes as unrecoverable.
- Two pCloud trees that overlap each other are de-duplicated by
  (filename, size); identical names at *different* sizes are kept, because for
  this library that means genuinely different recordings.
- `refresh` reflects the site on that day; it has no memory of titles the site
  stops publishing, and a refresh that fails partway leaves the previous catalog
  untouched.
- The source's own folder names include typos and inconsistent spacing; they are
  normalised for the filesystem (NFC, no `/`, collapsed runs of spaces) but not
  renamed into something prettier, since traceability beats cosmetics here.

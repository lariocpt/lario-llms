# Command guide — `media/`

Every command in the toolkit: what it does, how it is invoked, and what it touches.
Compiled 2026-10-15 by parsing each module's AST (docstring, `add_argument` calls,
env reads, path constants). **Nothing here was executed to produce this file** — the
domain files are commands and importing one used to *run* the pass.

Rules of the house live in [`README.md`](README.md); the plan and the burn-down live in
[`PLAN.md`](PLAN.md). This file is the index of the surface.

---

## 1. Running anything

```sh
cd ~/Projects/personal/lario-llms
python3 media/photos/plan_import.py --dry      # run a command, from the repo root
python3 media/video/enc_hevc.py --help         # the ones with flags answer --help
```

* Run from the repo root: the scripts insert their own directory on `sys.path` and
  import `paths` / `core.config` by relative name.
* **93 Python modules** in seven packages (`photos`, `music`, `video`, `audiobooks`,
  `audiolib`, `tools`, `core`). `core/config.py`, the two `paths.py` shims,
  `photos/reference.py`, `music/mini_naming.py` and `audiolib/pcloud.py` are libraries;
  the other 88 are commands, and they raise `SystemExit` when imported
  (`GUARD-ON-IMPORT`) precisely so that being imported cannot run them.
* **Locations come from the environment (§2), not the command line.** The flag-taking
  surface is `photos/`, `music/`, `video/`, `audiolib/` and `tools/tidy_library.py`;
  the rest take no arguments at all. That env seam is what the driver
  (`media/run.py`, §1.1) drives.

### 1.1 The driver — `media/run.py` (built 2026-10-17)

One medium, N sources in, **one** destination out. It plans by default and writes only with `--apply`.
It is the surface the plan (§3.2) describes; the domain scripts underneath are unchanged and are still
invoked as commands when a pass needs one (§1).

```sh
# where the bytes already are — reads everything, writes nothing
python3 media/run.py movies merge --src /mnt/usb1 --src /mnt/usb2 --dest /mnt/handover

# the same, writing the copies into <dest>/Movies (photos -> /Photos, music -> /Music, …)
python3 media/run.py movies merge --src /mnt/usb1 --dest /mnt/handover --apply

# check a finished run, and see what is in flight
python3 media/run.py movies verify --dest /mnt/handover
python3 media/run.py movies status --dest /mnt/handover

# the ONLY thing in this toolkit that deletes. Needs a real terminal, the word DELETE,
# and the exact byte total, typed at that moment. Sources are otherwise never removed.
python3 media/run.py movies purge --dest /mnt/handover --run merge-movies-20261017T114410-bd25e5
```

| Flag | Meaning |
|---|---|
| `--src DIR` | an input volume; repeat once per drive. Must exist and be a directory. |
| `--dest DIR` | the one destination; defaults to the medium's library (`LARIO_DEST_<MEDIUM>`). Two of them refuse the run. |
| `--apply` | write. Without it the run is a plan, and a plan can never authorise a delete. |
| `--allow-nested WHY` | permit a `--dest` inside a `--src`; the reason is recorded in `plan.json`. Refused without a reason. |
| `--free-floor-gb N` | refuse if the destination would fall below this after the copy — checked against the plan's byte total **before the first write**, not after (default 50). |
| `--run ID` | which run to `verify` / `purge` / resume. |
| `--json` | summary as JSON, for scripting. |

Exit codes: `0` did the work · `2` refused before touching anything (bad combination, missing dependency,
space floor, reversed direction) · `3` another run holds this pass's lock · `10` `core/` imported a domain
module (§4.4). `1` is a crash, which is also a bug to report.

**Nothing here deletes a source.** A merge that finds duplicates writes them to
`<dest>/_mediatool/<run_id>/deletes.json` marked *staged, nothing was deleted* and leaves every file where
it is. `purge` re-derives permission from the ledger and the disk at the moment you run it, re-hashes both
sides, and asks you twice; there is no `--yes` and none will be added (PLAN §4.3).

### Dry-run conventions — read this before touching a destructive pass

The convention is inverted in two places, and both of them delete or rewrite.

| Command | Default | To make it act | To be sure it is dry |
|---|---|---|---|
| `photos/plan_import.py` | writes the plan file | `APPLY=1` (moves images) | `--dry` (never writes the plan) |
| `photos/consolidate_days.py`, `delete_pass2.py`, `freeze_deletes.py` | **dry** | `DRY=0` | leave unset, or `DRY=1` |
| `photos/delete_source_duplicates.py`, `recompress_imports.py` | **ACTS** | — | **`DRY=1`** (yes: unset is not dry) |
| `photos/finish_cleanup.py` | does nothing | `GO=1` | leave unset |
| `photos/rebuild_deletes.py` | **refuses** | `ALLOW_REBUILD_DELETES=1` | leave unset |
| `music/mini_import.py` | **dry** | `--apply` | leave `--apply` off |
| `audiobooks/merge_sanderson.py` | **dry** | `--apply` (or `--undo`) | leave both off |
| `tools/tidy_library.py` | **dry** | `--apply` (or `--undo`) | leave both off |
| `photos/zip_perceptual.py` | dry | `--apply` | leave it off |
| `video/enc_hevc.py` | **acts immediately** — there is no dry flag | n/a | point `--root` at a copy, or use `--src-file` with `--out` |

`video/enc_hevc.py` replacing sources in place is the single most consequential
command here; `rtx5080/encoder/` (outside this package) is the gated wrapper that owns
running it while the chat model is off the card.

### The photo delete chain — one sequence, manual only

```
prove_deletes.py → rebuild_deletes.py → freeze_deletes.py
                 → delete_source_duplicates.py → audit_deletes.py → verify_final.py
```

It removes library entries. `tools/media_tools.py` lists it under *manual* and has no
verb for it; the gates have to be green before it runs, and it runs with the owner
watching (§`tools/media_tools.py:MANUAL`).

---

## 2. Paths: the environment seam

`core/config.py` is the only file allowed to spell out where a library lives. Every
root is `_path("LARIO_*", default)`, so a run can be redirected without editing code:

```sh
LARIO_PHOTO_LIB=/tmp/photos-clone LARIO_MUSIC_STAGE=/tmp/stage python3 media/...
```

| Variable | Default | What it is |
|---|---|---|
| `LARIO_PHOTO_LIB` | `~/Pictures/Photos` | the photo library |
| `LARIO_VIDEO_LIB` | `/mnt/media/videos` | video library for the photo pass: `YYYY/YYYY-MM-DD <Event>`, the tree the 2026 pass actually filed 427 clips into (§4) |
| `LARIO_MUSIC_LIB` | `/mnt/xfs/music` | the Navidrome library |
| `LARIO_MUSIC_STAGE` | `/mnt/xfs/staging-mini-music` | the mini-player export, staged |
| `LARIO_MOVIES` / `LARIO_SERIES` | `/mnt/media/movies`, `/mnt/media/series` | served video libraries |
| `LARIO_AUDIOBOOKS` | `/mnt/media/audiobooks` | audiobook shelf |
| `LARIO_BOOKS` | `/mnt/media/books` | ebook library |
| `LARIO_BOOK_IMPORT` / `LARIO_BOOK_PARK` | `$LARIO_BOOKS/import`, `$LARIO_BOOKS/_from-audiobooks` | incoming books / parked cross-shelf finds |
| `LARIO_PHOTO_BACKUP` | `/mnt/xfs/photos-originals-backup` | the originals backup — **currently unmounted** |
| `LARIO_PHOTO_BACKUP_PHOTOS` | `$LARIO_PHOTO_BACKUP/Photos` | the tree the delete proofs check against |
| `LARIO_PHOTO_STAGING` | `$LARIO_PHOTO_LIB.new` | second photo tree (separate name, deliberately) |
| `LARIO_HHD` | see `core/config.py:68` | the source drives of the last import |
| `LARIO_PRESERVED` | `/mnt/xfs/preserved-video` | unplayable/retired video, indexed, never discarded |
| `LARIO_PRESERVED_MINI` / `LARIO_PRESERVED_MUSIC` / `LARIO_PRESERVED_AUDIOBOOKS` | `/mnt/xfs/preserved-{mini,music,audiobooks}` | where the `tidy` pass parks litter |
| `LARIO_TIDY_AUDIT` | `media/tools/tidy-library.jsonl` | one audited line per move; `--undo` replays it |
| `LARIO_NAVIDROME_DB` | see `core/config.py:117` | opened **`mode=ro`**, always |
| `LARIO_FFMPEG` / `LARIO_FFPROBE` | `/usr/bin/{ffmpeg,ffprobe}` | the binaries used |
| `W` / `LARIO_VIDEO_WORK` / `LARIO_MUSIC_WORK` / `LARIO_AUDIOBOOK_WORK` | `~/photos-reorg-work`, `~/video-reorganize`, `~/music-reorganize`, `~/audiobook-reorganize` | per-run evidence scratch — **only `~/audiobook-reorganize` still exists**, so set the root for a run; commands create whatever root they are given |
| `PLAN` | `$W/import-plan.json` | the hand-edited photo import plan |
| `SANDERSON_LOG` | `$LARIO_AUDIOBOOK_WORK/sanderson-merge.jsonl` | shelf-merge log the sidecar pass reads |

Two things this table has to say honestly:

* **The work roots are only usable through these variables since 2026-10-16.** Until then, 34 of 44
  `photos/*.py` scripts set `W = '/home/lario/photos-reorg-work'` literally, and the music pipeline
  split one run's evidence between `/home/lario/music-reorganize/...` and `media/music/` itself. Both
  directories were deleted in the 2026 corpora move, so those commands died at their first `open()`
  with no way to redirect them. They now read `paths.W` / `paths.WORK` and create the root they are
  given: `W=~/media-evidence/photos-2026-11 python3 media/photos/verify_final.py`. The *defaults* still
  name the deleted 2026 directories, so name your own per run — and `photos/oneoff/` keeps its
  literals on purpose, as the record of a run that already happened.
* `exiftool` is referenced as `/home/lario/.local/bin/exiftool` (absolute) in several
  photo scripts, not through `PATH`.

---

## 3. `photos/` — dates, dedupe, proofs, deletion

Everything the 2026-10-10 photo reorganisation ran. `W` holds its evidence:
`import-plan.json`, `manifest-moves.csv`, `manifest-deletes.csv`, `manifest-imports.csv`,
`manifest-videos.csv`, `near-dups.json`, the hash and metadata indices.

### 3.1 Plan and apply the import

| Command | What it does | Invoke |
|---|---|---|
| `plan_import.py` | **The entry point.** Plans (and optionally applies) the import of the source trees into `YYYY/YYYY-MM-DD <Event>/NNN_YYYYMMDD-HHMMSS.ext`; a day already in the library keeps its existing folder; undated files go to `Undated/<source folder>`; `Grant Backup` is archived intact, never imported. Refuses a zero-record write over a non-empty plan unless `PLAN_ALLOW_SHRINK=1`, and keeps the previous plan as `.prev` | `--dry` · `APPLY=1` · `BUCKETS=new-candidates.json` · `META=meta_cand.jsonl` · `PLAN=import-plan.json` · `MANIFEST=manifest-imports.csv` · `ZIP_ROOTS=1` |
| `consolidate_days.py` | One folder per day: merges date-echo folders, renames files into the convention, records the video mapping | `DRY=1` (default) / `DRY=0` |
| `recompress_imports.py` | Recompresses the imported JPEGs under the same rule the original pass used (PSNR-checked) | **`DRY=1` required for a dry run** · `MANIFEST=` · `TREES=a,b` |
| `foldermap.py` | Rebuilds "which new folder came from which source folder" without the lost `plan.json` | no flags |

### 3.2 Scan, index, capture

| Command | What it does | Invoke |
|---|---|---|
| `rescan.py` | Re-scans the three trees into JSON so every later step is evidence-based (this is one of the two places `-Apple:ContentIdentifier` is harvested) | argv |
| `hash_tree.py` | blake2b-hashes every file under a tree into a **resumable** jsonl index | `hash_tree.py <root> <out.jsonl> [workers]` |
| `meta_capture.py` | exiftool capture for a file list, jsonl, resumable (the other `ContentIdentifier` harvest) | `meta_capture.py <listfile> <out.jsonl> [batch]` |
| `dhash_index.py` | dHash (16×16, 255 bits — same convention as `find_neardups.py`) for a file list | `dhash_index.py <listfile> <out.jsonl> [workers]` |
| `analyze_sources.py` | Classifies the source trees against the live library | no flags |
| `account_sources.py` | Decides, for every file in the source trees, whether it is a duplicate | no flags |

`reference.py` is the **library** these build on: `blake`, `file_hashes`, `tree_files`,
`source_index`, `reference`, `is_junk` — "the one way this job builds a set of bytes
that are already safe". It does no work at import and is meant to be imported.

### 3.3 Duplicates and near-duplicates

| Command | What it does | Invoke |
|---|---|---|
| `dedup_candidates.py` | Which candidate photos are the same shot as something already in the library | no flags |
| `find_neardups.py` | **Report-only** scan for leftover near-duplicates in the reorganised library (+ exact groups) | no flags |
| `zip_perceptual.py` | Perceptual check of staged archive images against the live library | `--apply` |
| `prove_unique.py` | Settles a *disputed* deletion by pixel comparison, not by hash | `prove_unique.py <backup-relative path> [more…]` |
| `prove_deletes.py` | Re-proves every row of `manifest-deletes.csv` against real evidence | no flags |
| `audit_deletes.py` | Independent re-proof of everything the step deleted | no flags |

### 3.4 Deletions (the manual-only chain, §1)

| Command | What it does | Invoke |
|---|---|---|
| `freeze_deletes.py` | Finalises `manifest-deletes.csv` from recorded evidence | `DRY` default dry |
| `rebuild_deletes.py` | Rebuilds the delete proof from scratch | `ALLOW_REBUILD_DELETES=1` to run at all |
| `delete_source_duplicates.py` | Deletes from the source trees **only** what is proven available elsewhere | **`DRY=1` for a dry run** |
| `delete_pass2.py` | Pass-2 deletions, driven by `near-dups.json` | `DRY` default dry |
| `finish_two.py` | The two files the delete pass refused, resolved by hand-measured evidence. Run-once, but kept as the record of that decision | no flags |
| `finish_cleanup.py` | Takes the last archive out of the photo library and clears the scratch the job left | `GO=1` |

### 3.5 Manifests and their repair

| Command | What it does | Invoke |
|---|---|---|
| `fix_manifest.py` | Consistency fixes for `manifest-moves.csv`, with the hash index as arbiter | no flags |
| `diag_moves.py` | Diagnoses the unresolved moves rows | no flags |
| `finalize_moves.py` | Closes out `manifest-moves.csv` | no flags |
| `finalize_moves2.py` | The last 16 rows of the moves manifest (exif tags + dHash + freshness) | no flags |

### 3.6 Videos out of the photo library

| Command | What it does | Invoke |
|---|---|---|
| `videos_nvenc.py` | The original video pass: moves clips out of the photo library into the video library, NVENC-encoding them under the same gates as `video/enc_hevc.py` | `--limit N` · `--only-copy` · `--workers N` (default 2) |
| `transcode_import_videos.py` | Transcodes the videos the import plan queues into the video library, same rules | `--limit N` · `--dry` · `--test N` (encode N seconds, keep nothing) · `--workers N` · `PLAN=` |
| `verify_videos.py` | Safety verification of the video pass (digest, decode, compare, summary) | argv |
| `repair_vfr.py` | Repairs the two variable-frame-rate clips whose NVENC pass dropped frames | no flags |
| `fix_video_audio.py` | Repairs the 13 outputs the audio-probe bug hit; loads its own copy of the probe helpers, so asking for `probe`/`decode_clean` cannot start a transcode | `--dry` · `--only SUBSTR` |

### 3.7 Archives

| Command | What it does | Invoke |
|---|---|---|
| `check_zips.py` | Proves, entry by entry, whether the archives left in the source trees still add anything | no flags |
| `check_library_zips.py` | Entry-by-entry check of an archive that lives *inside* the library | argv (the zip) |
| `trace_library_zip.py` | Where each entry of such an archive actually lives now | argv |
| `classify_zips.py` | Classifies staged archive contents against everything that already exists | `classify_zips.py [plan\|final]` |
| `extract_zips.py` | Expands the remaining archives into a staging folder so they can be classified | no flags |
| `verify_archive_claim.py` | Re-derives the archive conclusion from scratch | no flags |

This is how `Misc/Paris.zip` was settled: 31 members, `unique: 0` — the zip numbered
every member `001_`, so matching by filename finds nothing and matching by capture
timestamp finds all of them (README).

### 3.8 Verification

| Command | What it does | Invoke |
|---|---|---|
| `verify_final.py` | Final check that the libraries and the manifests describe the same disk. **The committed zero-violation invariants** | no flags |
| `verify_manifest.py` | Audits `manifest-moves.csv` against content hashes | no flags |
| `verify_meta.py` | Before/after metadata and decodability for the recompressed photos | no flags |
| `verify_meta_recorded.py` | Re-runnable metadata check that needs **no originals** | no flags |
| `audit_coverage.py` | Content coverage: does every original photo still exist in the library? | no flags |

### 3.9 `photos/oneoff/` — run-once records

They keep their original hard-coded paths (`Photos.new`,
`/mnt/xfs/photos-originals-backup`, the 2025 phone drop) as a record of what was done
to the library — **not** a reusable surface. Most reference paths that no longer exist;
read them, do not run them.

| Command | The one thing it did |
|---|---|
| `rebuild_moves.py` | Every file in `Photos.new` → its original path, rebuilding the moves manifest without the lost `plan.json` |
| `rebuild_moves2.py` | Resolved the last unresolved moves rows and finalised `manifest-moves.csv` |
| `rebuild_moves3.py` | Ranked the open rows by folder-provenance evidence |
| `rebuild_moves4.py` | Resolved the remaining rows by content, not metadata |
| `rebuild_moves5.py` | The last rows, decided by content (dHash against the hash index) |
| `rebuild_moves6.py` | Finalised the manifest: dropped rows superseded by later evidence |
| `probe_last15.py` | Probed the 15 stubborn rows: what the survivor says about itself, and which candidate it names |
| `check_0168.py` | What represents `Mac Photos/IMG_0168.JPG` now, and how close it is, in pixels |
| `tmp_probe.py` | Scratch: packet counts vs decoded frames for one file |
| `tmp_vfr_test.py` | Scratch: the variable-frame-rate test on `Photos - 3433 of 6286.mp4` |

---

## 4. `music/` — the `mini_*` pipeline

Twenty-five commands that filed the mini-player export into the Navidrome library.
They chain through artifacts in `MUSIC_WORK` (`$LARIO_MUSIC_WORK`, created on demand),
each step reading only what its predecessors wrote — every artifact in the table below
and both audio caches (`feats-cache.pkl`, `fullenv-cache.pkl`) live there, never beside
the code. `mutagen` 1.48.1 **is installed in `media/.venv`** (2026-10-18:
`uv pip install --python media/.venv/bin/python mutagen==1.48.1`), so every music command that touches tags
runs as `media/.venv/bin/python media/music/<cmd>.py` — the system `python3` has no mutagen, and
`exiftool` on this host cannot read `AlbumArtist` at all, so a system-python or exiftool answer about
tags here is not a finding.

| Step | Command | Produces |
|---|---|---|
| inventory | `mini_meta.py` | `mini-meta.jsonl` — tags **and** the path-derived reading of each file, so the two can be compared instead of trusted |
| damage + identity | `mini_damage.py` | `mini-hash.jsonl` — whole-file md5, long silent runs, unopenable files |
| byte dupes | `mini_bytedupes.py` | `mini-byte-dupes.json` — staged files byte-identical to a library file (size prefilter, then md5) |
| match, tiered | `mini_match.py` | `mini-verdicts.json` — evidence tiers, strongest first |
| match, high recall | `mini_match2.py` | `mini-cands.json` — with decoded-audio proof behind every "same recording" |
| prove by audio | `mini_verify.py` | `mini-proof.jsonl` — `--calibrate` prints real scores for known-same and known-different pairs first; `--limit N`; `--apply-out` |
| shape metric | `mini_shape.py` | `mini-shape.jsonl` — exhaustive, both directions (`--limit N`, `--workers 12`) |
| calibrate shape | `mini_shapecal.py` | `mini-shapecal.json` — thresholds per duration class, non-circular labels |
| envelope, final | `mini_sweep.py` | `mini-final.jsonl` — full-track envelope over the whole library (`--prewarm` builds the cache, `--limit N`) |
| envelope, staged | `mini_envverify.py` | `mini-envproof.jsonl` (`--prewarm` computes library windows in parallel) |
| calibrate envelope | `mini_envcal.py` | `mini-envcal.json` — waveform correlation is unusable across processing chains; this is the metric that survives |
| second opinion | `mini_cov.py` | `mini-cov.jsonl` — the ambiguous band (`--check` re-verifies calibration on known truth, `--statuses UNDECIDED,NO-COMPARISON`) |
| probe the window | `mini_covprobe.py` | which window length and smoothing actually separate the classes |
| arbitrate | `mini_arbiter.py` | the cases the 30-second windows cannot settle (`--calibrate`, `fullenv-cache.pkl`) |
| dupes *within* the source | `mini_intra.py` | `mini-intra.json` (`--statuses NEW,UNDECIDED`) — a single also appears on its album |
| verdict | `mini_verdict.py` | `mini-verdict-final.jsonl` — one verdict per staged file from three independent lines: byte md5, decoded audio, tags+name |
| the answers | `mini_report.py` | how much of the copy was already in the library, and what is genuinely new |
| **import** | `mini_import.py` | `mini-import-plan.jsonl`, then moves. **Dry unless `--apply`.** Never overwrites: same bytes collide → skip, different bytes → beside with a marker. Writes via temp file → fill gaps in tags → read back → `os.replace` |
| **identify an album** | `identify_albums.py` | **fill-only**: writes an album where there is none, never touches one that exists. Routes `twins` (same title+artist+duration already tagged in the library) and `folder` (≥2 tagged siblings agree **and** the folder is not adding more files than that album already has); `musicbrainz` is **opt-in and off by default** — measured 60 lookups → 4 fills, wrong at source, because a bootleg off the same CD has the same duration. Two routes naming different albums is `routes-disagree`, a refusal. Dry unless `--apply`; `--apply --sample 30` first; re-run `--apply` until `nothing to write` (it cascades, and **each cycle re-measures** — see PLAN §7). Protect copy first, and `--undo <run_id>` **`--route folder`** takes one route back and leaves the rest in place |
| **grouping repair** | `fix_grouping.py` | tag-only, in place, **never a move** — a move changes the Navidrome song id and resets play counts/stars/playlists. Backfills `Album Artist` where it is absent or only repeats the track artist, marks scattered compilations, refuses what it cannot prove. Dry unless `--apply`; `--sample N` first; every original byte-copied to the *other* disk first (`/mnt/media/_repair-originals/<run_id>`); `--undo <run_id>` reverses tag values from `tag-backup.jsonl`, which records what was **written**, not what was planned |

Filing and tag rules are in **`mini_naming.py`** (a library): `clean_text`,
`canon_artist`, `year_from`, `strip_va_prefix`, `album_name`, `junk_title`,
`merge_track`, `target_path`, `fill_plan` → `Artist/Album (YYYY)/[Disc N/]NN - Title.ext`.

Diagnostics: `probe_metric.py` — "why did two same-title near-equal-length files score
0.09?" (cross-correlation vs envelope, on one named pair).

---

## 5. `video/` — encode, measure, file

| Command | What it does | Invoke |
|---|---|---|
| `enc_hevc.py` | **The encode engine.** HEVC re-encode gated by measurement: a source is replaced only after its encode opened, matched duration/resolution/SAR/audio+subtitle stream counts, decoded end to end with no errors, beat `--min-ssim` on a mid-file 180 s slice, and beat the source by `--min-gain`. Audio and subtitles are copied; **resolution and frame rate are never changed** — downscaling a 4K master is the owner's decision | see below |
| `bench_qp.py` | Measures a HEVC quality ladder for one file before committing to it | `bench_qp.py src [--qp 16,18,20,22] [--ss 300] [--len 180] [--tag b] [--pix p010le\|yuv420p]` |
| `window_quality.py` | Measures what a qp costs in a *specific* scene, not an average | `window_quality.py src [--at 300.0 …] [--qp 22 24 26] [--length 120] [--pix p010le] [--json out]` |
| `audit_windows.py` | Audits a finished encode against its source at several windows. **Not the gate** — it costs minutes and its summary vanishes under `-v error` | `audit_windows.py enc src [--at 300 1200 2400] [--length 120] [--no-count]` |

`enc_hevc.py` flags:

```
--root DIR            repeatable; the tree to scan (.mkv only)
--src-file SRC        repeatable; one explicit input, or a `concat:` URL for a DVD title
--out PATH            destination for --src-file; without it the source is replaced in place
--log PATH            required (argparse required=True); jsonl, one line per decision
--qp N                default 16  (this ffmpeg IGNORES -cq for hevc_nvenc)
--min-gain F          default 0.15  — an encode that saves <15% is not worth a generation
--min-ssim F          floor for the 180 s slice
--drop-audio LAST|NONE
--crop LETTERBOX|NONE crop black bars when the source carries them
--crop-rect WxH+X+Y   explicit crop, for sources ffmpeg cannot seek reliably (DVD via concat:)
--set-dar R           force a display aspect ratio (PAL discs whose metadata lies)
--setpts AUTO|NONE    strip setpts drop/hide flags by re-timing to CFR
--no-ssim             skip the quality comparison
--metrics-from-start  compare from 0, not 5 minutes in (DVD concat inputs cannot seek)
name ...              restrict the scan to these names
```

Three behaviours of this ffmpeg build (N9.0.2) that the engine already accounts for and
that will otherwise bite: `-cq` is silently ignored for `hevc_nvenc`; `-v error`
suppresses the psnr/ssim *summary*, so a silent measurement run measured nothing; and
psnr and ssim cannot share one filter chain when both need a format fix.

`video/oneoff/` — `mv_himym.py`, `mv_grace.py`, `mv_blackadder.py`, `mv_samurai.py`,
`probe_dvd.py`, `probe_two.py`: the run-once filers and the Cool Runnings / Forrest
Gump probes, with their original hard-coded paths as a record.

---

## 6. `audiobooks/`

| Command | What it does | Invoke |
|---|---|---|
| `merge_sanderson.py` | Merges the two Brandon Sanderson folders into one importable library: flattens part folders, labels files, dedupes bundled ebooks (the two part folders of one box held the same 115 MB epub). Already applied 2026-10-14 (395 files); kept for the next shelf | `--apply` · `--undo` (default is dry) |

Its log, `sanderson-merge.jsonl` in `LARIO_AUDIOBOOK_WORK`, is what
`tidy_library.py sanderson-sidecars` reads to attribute each cover and `.opf`.

---

## 7. `audiolib/` — the pCloud fetcher

Not an organiser: it fetches and files (README in that directory). It **never
re-encodes** — the source is AAC-LC mono 32 kHz ~64 kbps, so re-encoding buys space
only by spending a generation of quality.

```sh
python3 media/audiolib/catalog.py [build|show] [--refresh]      # re-scrape + report what changed
python3 media/audiolib/controller.py <operation> [--json '{…}'] # JSON in, JSON out
```

| Operation | What it does |
|---|---|
| `catalog` | Catalog statistics, or a filtered slice of `catalog.json` (3 297 files, 46.01 GB) |
| `refresh` | Re-scrapes the site and reports the diff against the committed catalog |
| `start` | Starts a detached fetch job. Request keys (defaults shown): `root` (`/mnt/media/audiobooks/islam`), `include []`, `limit 0`, `workers 4`, `log_root /mnt/media/audiobooks/.audiolib-jobs`, `min_free_gb 20`. Refuses when free space < missing bytes + the floor |
| `status` | The running job and its progress (`progress.json`, `ledger.tsv` OK/SKIP/STOP/FAIL) |
| `cancel` | Terminates the process group; in-flight files stay `.part` and the next start continues them. Recorded as `STOP`, never as a failure |

`runner.py` is the detached child — started by the controller, not by hand.
`pcloud.py` is a library (`download_url`, `transfer`, `PcloudError`): public-link URLs
expire within minutes, so they are re-requested per attempt and rotate hosts on retry;
verification is the catalog byte size, not a digest, because public links expose none.

---

## 8. `tools/`

| Command | What it does | Invoke |
|---|---|---|
| `tidy_library.py` | Takes five kinds of thing out of the *served* trees. Move-only, never overwrites, appends an `INDEX.txt` entry in the preserved tree naming the exact origin, and a cross-filesystem move is md5-verified before the source is released | `tidy_library.py [pass…] [--apply] [--undo] [--prune-empty]` |

Passes (`all` is the default): `sanderson-sidecars`, `music-sidecars`, `mini-stage`,
`nested-movies`, `video-litter`. `--undo` replays this tool's own audit backwards for
the named pass(es); `--prune-empty` removes only directories the pass emptied, with
`rmdir`. The two risky video rules are guarded: a spool or a folder with no playable
file goes only when the same title **is** filed and the filed copy is the larger one,
and an extension-less file must probe identical (codec, frame size, duration) first.
Audit: `tools/tidy-library.jsonl` (`LARIO_TIDY_AUDIT`) — the run of 2026-10-14 is 615
moves, 15.08 GB, 47 pruned directories, one line each.

### `media_tools.py` — the MCP surface (`lario_media`)

A JSON-lines stdio server, registered as `lario_media`; running it by hand is only
useful for testing it.

| Tool | Notes |
|---|---|
| `media_status` | Where every library resolves (overridable by `LARIO_*`), free space per root, the photo plan's record count and whether it still parses, newest evidence file per domain. Read-only, never walks a library |
| `media_jobs` | The runnable passes, what each touches, its flags — plus the reviewed-but-**manual-only** ones and why (`video_encode`, `photos_delete_chain`, `music_import`, `sanderson_shelf_merge`) |
| `media_run` | Present **only** with `LARIO_MEDIA_ALLOW_JOBS=1`. Two jobs by name, fixed argv: `photos_plan` (writes only the plan file) and `photos_video_import`. `apply` defaults to false and a job is forced to `--dry` unless the caller says otherwise. **No path arguments, no delete verb, and encoding is not exposed** — `lario_encoder` owns the RTX |

Env: `LARIO_MEDIA_ALLOW_JOBS=1` (the gate), `LARIO_MEDIA_TIMEOUT=900`.

---

## 9. Which command to reach for

| I want to… | Run |
|---|---|
| see what the libraries look like right now | `python3 -c` nothing — call the `media_status` tool, or `tools/tidy_library.py` with no flags to see a plan |
| re-plan the photo import safely | `python3 media/photos/plan_import.py --dry` |
| know whether two photos are the same shot | `photos/dedup_candidates.py` (library) · `photos/prove_unique.py <path>` (one disputed file) |
| know whether two audio files are the same recording | `music/mini_verify.py --calibrate` first, then `mini_shape.py`; `music/probe_metric.py` for one pair |
| give files their album back (tag-only, no moves) | `media/.venv/bin/python media/music/identify_albums.py` — plan first, then `--apply --sample 30`, then `--apply` until `nothing to write`; `--undo RUN --route folder` to take one route back |
| bench a qp before encoding a title | `python3 media/video/bench_qp.py SRC --qp 16,18,20,22` |
| encode one file to a chosen qp | `python3 media/video/enc_hevc.py --src-file SRC --out DST --qp N --log run.jsonl` (with `--out`, so nothing is replaced in place) |
| clean litter out of the served trees | `python3 media/tools/tidy_library.py [pass] [--apply]` |
| fetch/continue the audiobook library | `python3 media/audiolib/controller.py start --json '{"workers": 4}'` |
| verify a finished pass | `photos/verify_final.py` · `photos/verify_manifest.py` · `photos/audit_coverage.py` |

---

## 10. Where the docs were wrong — six defects, all fixed 2026-10-16

Found while compiling this guide, and then fixed at the source rather than left as
comments. What each one was, and what actually changed:

1. **`tools/media_tools.py` called `music_import` a tool with *"no dry run"*.** `mini_import.py:138`
   is `dry = "--apply" not in sys.argv`: it plans and writes nothing until told. The MANUAL entry
   now says so — *needs mutagen, dry unless `--apply`, run it against a staged copy first* — and
   the command line shows the flag.
2. **This guide's own error, and the correction is worth keeping.** An earlier pass of §10 claimed
   `PLAN.md` described a `dup_stem` gate that no code implemented. It does exist, at
   `runner.sh:142-143`: when the commit rename `X.mp4 → X.mkv` would land on a same-stem `.mkv`
   already in the folder, the title is refused rather than overwritten. What is *true* about the
   complaint is narrower and still open: `dup_stem` is a collision refusal, **not** duplicate
   detection. The encoder recognises neither a second copy, nor a near-duplicate, nor a split-title
   part that turns out to be the same file, and there is no output-size-budget gate either — those
   are unbuilt (§4.3 and §9 of `PLAN.md`). `PLAN.md` now spells that out where it lists the gates,
   so nobody reads `dup_stem` as a dedupe.
3. **`core/config.py` defaulted `LARIO_VIDEO_LIB` to `/mnt/xfs/videos/videos`, which does not
   exist.** The default is `/mnt/media/videos`, verified as the tree the 2026 photo pass filed
   into: `YYYY/YYYY-MM-DD <Event>`, 427 clips, 2005–2018 plus `Undated`. `VIDLIB` consumers
   (`audit_coverage.py`, `check_zips.py`, `account_sources.py`) resolved their `dest` paths to
   nothing before this; three docstrings naming the dead tree went with it.
4. **`PLAN.md` described `tidy_library.py --root DIR… --undo PASS`.** The real signature is
   `passes… [--apply] [--undo] [--prune-empty]`: pass names are positionals (`sanderson-sidecars`
   `music-sidecars` `mini-stage` `nested-movies` `video-litter`, or `all`), there is no `--root`
   because every root comes from config, and `--undo` is a flag that replays this tool's own audit
   backwards for the named passes — all five if none is named, newest first, refusing a file whose
   archive copy is gone or whose original path is occupied again. §3.3 and §11 corrected.
5. **`README.md` pointed at `~/photos-reorg-work/import-plan.json` as the live plan.** That
   directory is gone and the plan with it (4 093 hand-edited records, no copy). The Paths section
   now says the plan is absent, that `media_status` reports `present: false`, and that
   `plan_import.py --dry` rebuilds one from whatever sources are mounted.
6. **One music run's evidence lived in two places.** `mini_meta.py`, `mini_damage.py` and
   `mini_envcal.py` wrote `/home/lario/music-reorganize/…` (deleted) while the match/verify/sweep/
   shape/cov/verdict steps wrote into `media/music/` itself through `HERE` — inside the repo. All
   46 sites, both caches included (`feats-cache.pkl`, `fullenv-cache.pkl`), now resolve through
   `paths.WORK` → `config.MUSIC_WORK` (`LARIO_MUSIC_WORK`), readers and writers together so the
   chain still chains, and the writers create the root they are given.

The photo half of the same defect went one step further: the 34 `photos/*.py` scripts that set
`W = '/home/lario/photos-reorg-work'` literally (and the two that set it as `WORK`) now import it
from `paths`, so the §2 variables are the whole truth about where a run writes.

**How this was verified, since none of these commands may be run to find out:** `py_compile` over
`media/photos` and `media/music`, plus an AST pass proving every `W`/`WORK` name in both trees is
bound by an import or an assignment, plus a check that `import os` precedes every `makedirs` line.
No command was executed, which is the rule this whole file was compiled under.

**What fixing the six did *not* buy:** the *defaults* still name the deleted 2026 directories, so
a run has to name its own evidence root — and `PLAN.md` §4.3.4 wants that root under the
destination (`<dest>/_mediatool/<run_id>/`), not in `$HOME`, which is driver work. `mutagen` is
still missing, so `music/` still cannot run at all. The size budget, the join step, and the
parts-versus-duplicates gate are still unbuilt. And repointing an artifact path does not resurrect
the artifacts: every 2026 verdict file went with the directories that held them (PLAN.md §2).

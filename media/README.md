# media — the library-organising toolkit

The scripts that actually filed these libraries, moved out of the four home
directories they were written in and into version control. This is the same code
that ran the jobs, not a rewrite of it: what changed is where the paths come from
and what happens when a file is loaded by accident.

| package | was | does |
| --- | --- | --- |
| `audiolib/` | — | fetches audiobooks from pCloud into the shelf (see its own README) |
| `audiobooks/` | `~/audiobook-reorganize` | merges/labels a shelf, flattens part folders, dedupes bundled ebooks |
| `music/` | `~/music-reorganize` | files the mini-player's export into the Navidrome library |
| `photos/` | `~/photos-reorg-work` | dates and files photos/videos, proves uniqueness, verifies archives |
| `video/` | `~/video-reorganize` | probes, encodes, muxes and files movies and series |

## Running something

Every file in a domain directory is a **command**. Run it, do not import it — the
modules now refuse to be imported for exactly that reason (see *Guardrails*).

```sh
python3 media/photos/plan_import.py --dry          # plan only, writes nothing
python3 media/video/enc_hevc.py --help             # the encode engine's flags
python3 media/music/mini_sweep.py                  # whatever its own docstring says
```

**One exception, and it is silent when wrong:** the music *tag* passes need mutagen, so they run with the
interpreter in `media/.venv`, not the system one.

```sh
media/.venv/bin/python media/music/fix_grouping.py --help   # mutagen 1.48.1, pinned
media/.venv/bin/python media/music/identify_albums.py --help
```

This is a 2026-10-18 finding, not tidiness: `exiftool` 13.59 on this host has **no `AlbumArtist` tag name at
all**, so the system's only convenient reader cannot see the tag the library is grouped by, and a survey run
with it reports "7.2 % have an album artist" for a library where the real number is much higher. mutagen reads
it correctly. Do not conclude from a tag census taken with exiftool — re-take it with
`media/.venv/bin/python`.

Each domain's own docstrings are the documentation. `--help` works on the ones
that take flags (`plan_import.py`, `transcode_import_videos.py`, `enc_hevc.py`,
the `mini_*` corpus). [`GUIDE.md`](GUIDE.md) is the index of the whole surface:
every command, its flags or env seam, what it touches, and the dry-run conventions
that differ from file to file.

## Paths

No script spells out where a library lives any more. They import `paths`, and
`paths` reads `core/config.py`, which reads the environment:

```sh
LARIO_PHOTO_LIB=/tmp/photos-clone LARIO_MUSIC_STAGE=/tmp/stage python3 media/...
```

The evidence roots are seams too, since 2026-10-16. Every photo and music command
used to read `W = '/home/lario/photos-reorg-work'` or write into `media/music/`
itself — two homes for one run's evidence, and both of them either deleted or inside
the repo. They now resolve `W` (photos) and `LARIO_MUSIC_WORK` (music) through config
and create the root they are given:

```sh
W=~/media-evidence/photos-2026-11 python3 media/photos/verify_final.py
```

The photo import plan is the one artifact a **human edits between runs**, so it
lives outside the repo and only `PLAN=` points at it
(`core/config.py:PHOTO_PLAN`). The 2026 plan — 4,093 hand-edited records — was in
`~/photos-reorg-work/` and went with that directory when the corpora move deleted
it; there is no copy. `media_status` reports the plan as absent, and
`plan_import.py --dry` rebuilds one from whatever sources are mounted.

`video/oneoff/` and `photos/oneoff/` keep the run-once scripts that already did
their job, with their original hard-coded paths, as a record of what was done to
the library. They are not the reusable surface, and most of what they name no
longer exists.

## Rules these tools enforce, in code

- **Nothing is deleted to save space.** `/mnt/media` is 46 % free. Where an
  encode replaces its source, that is because the encode was adopted on the
  gates below — not as cleanup. Unplayable leftovers are archived under
  `/mnt/xfs/preserved-video` with an `INDEX.txt`, never discarded, never entered
  into a library tree as if it were a title.
- **An encode replaces its source only if** it passes geometry, duration,
  whole-file decode and a minimum size gain. `hevc_nvenc` takes `-rc constqp
  -qp N`, not `-cq` (this build ignores it), and CQP is a quality target, so a
  result can come out *larger* than a low-bitrate x264 source — the gain gate is
  what catches that.
- **Verification is duration + stream list + one whole-file decode**, which
  takes seconds. Multi-window SSIM audits exist (`video/audit_windows.py`) but
  are not the gate: they cost minutes and their summary is logged at *info*
  level, so anything run with `-v error` reports "no result" for every window.
- **`idet`, not `idf`** — and a container's `field_order=tt` is a flag, not a
  measurement. Cool Runnings is flagged interlaced and measured 99 % progressive;
  deinterlacing it would have blurred 25p film-mode content.
- **DVD `concat:` inputs need `-probesize 100M -analyzeduration 200M`** or
  `-map 0:s` silently matches no subtitles, and the aspect comes from the first
  file — so a menu VOB at the head poisons the read. `-avoid_negative_ts
  make_zero` fails here ("Can't write packet with unknown timestamp"); omit it.
- **Tag writes fill gaps only, never overwrite**, and go copy → tag → read-back
  verify → `os.replace`.
- **No transcription of media audio** to guess what a track or chapter is, and no
  AcoustID/fingerprint uploads. Languages come from the container's own tags.
- **Navidrome's SQLite is opened `mode=ro`.** A pass that could write that schema
  could lose the library.

## Guardrails added when this moved

Each of these exists because the failure happened or was one keystroke away:

- **Importing a command script used to run it.** 77 modules now raise
  `SystemExit` on import; the ones with a bare trailing `main()` are wrapped in
  `if __name__ == "__main__"`. The remaining modules that do work at load are the
  real libraries (`reference.py`, `mini_naming.py`, the `paths.py` shims).
- **`plan_import.py` wrote an empty plan over a hand-edited one** when run after
  the import was finished — the sources are drained, so the plan comes out empty.
  It now parses `--help` *before* doing anything, refuses a zero-record write
  unless `PLAN_ALLOW_SHRINK=1`, and keeps the previous file as `.prev`.
- **Two part folders of one GraphicAudio box held the same 115 MB epub**, and
  `NEW` meant `Photos` in two files and `Photos.new` in eleven. Same-batch md5
  dedupe, and the two trees are separate names in config.
- **`fix_video_audio.py` read a sibling script as text out of the home
  directory** and `exec`'d it; it now loads its own copy and strips the trailing
  call so asking it for `probe`/`decode_clean` cannot start a transcode.

## Tidying what a library should not serve

`tools/tidy_library.py` takes five kinds of thing out of the served trees. It
plans unless given `--apply`, moves only, never overwrites, and appends an
`INDEX.txt` entry in the preserved tree naming the exact place each file came
from. `--undo` is a flag, not a value: it replays this tool's own audit backwards
for the pass(es) named positionally — `tidy_library.py music-sidecars --undo` —
or for all five when none is named, newest move first, refusing any file whose
archive copy is gone or whose original path is occupied again. Same-filesystem
moves are renames, and a cross-filesystem move is md5-verified after the copy and
only then releases the source.

| pass | what it takes | where it goes |
| --- | --- | --- |
| `sanderson-sidecars` | the covers and `.opf` the shelf merger left in the two old trees | into the book folder its audio went to, read from the merge log; an unattributable one is parked, never guessed onto a shelf |
| `music-sidecars` | `.log` `.cue` `.accurip` `.toc` `.sfv` `.srr` `.md5` `.nfo` `.txt` inside the music library | `preserved-music`. Album art is not litter and stays with the album |
| `mini-stage` | what the mini-player export left once its audio was imported | `preserved-mini` |
| `nested-movies` | a film filed *inside* another film's folder — one dragged folder, which a scanner still finds, so the top of the library lies about what it holds | the library root, where a scanner reads an entry; only the accidental-nesting signature qualifies, so a collection box, a `CD1` layout or an `Extras` folder is never touched |
| `video-litter` | an unprocessed release spool (multi-part `.rar`, `.sfv`) of a title that is filed, `.aspect` player overrides, and extension-less video no scanner can see | `preserved-video` |

The two risky video rules are guarded, because archiving the only copy is how a
tidy library loses a film: a spool or a folder holding no playable file goes only
when the same title **is** filed and the filed copy is the larger one, and an
extension-less file must probe identical (codec, frame size, duration) first.
`movies/Pulp Fiction` is what those guards are for, and how they were right for
the wrong reason: the RAR set looked like the only copy of the film because the
8.8 GB HEVC was filed two levels down, *inside* `The Godfather (1972)`. Filing
that where a scanner reads an entry is the `nested-movies` pass; once it ran, the
spool rule saw its twin and the 2-CD XVID set and its sample archived, leaving
one entry per film. A check that reads the library at its top can only be as
honest as the filing underneath it. `--prune-empty` removes the directories a
pass emptied, with `rmdir`, which cannot take anything with it.

Run 2026-10-14: 615 moves — 614 files and one film's folder — 15.08 GB, into four
preserved trees that each carry an index, and 47 emptied directories pruned; the
audit holds a line for every one of them. Navidrome was asserted before and after
— 29,025 indexed rows against 29,025 audio files on disk, zero drift — and it had
never indexed any of those sidecars, so the pass could not change what the server
serves. Jellyfin needs a scan, or its own real-time monitor, to catch the video
moves: the filed `Pulp Fiction (1994)` is at a new path, so its entry is
re-created rather than updated.

**`Misc/Paris.zip`**, the manifest destination that does not exist, is not a
loss. The import pass recorded 31 members and `unique: 0`, and the members'
capture timestamps are in the library's Paris day folders: the zip's
`001_20070108-073703.jpg` is the library's `001_…` and its `001_…073711.jpg` is
that folder's `002_…` — the zip numbered every member `001_`, which is why
matching them by filename finds nothing and matching by timestamp finds all of
them. Nothing unique came out of the container, so nothing was ever filed.

## Not in git

Job evidence — `*.jsonl`, `*.csv`, `*.tsv`, `*.pkl`, `*.log`, `*.bak*` — is
ignored per domain. It is regenerable, several files are tens of megabytes, and
none of it is source. The live plan is job data too, and stays outside the repo.

## MCP

`tools/media_tools.py` registers as `lario_media`: read-only status and the job
catalog by default, the two reviewed passes gated behind
`LARIO_MEDIA_ALLOW_JOBS=1`, and **no delete verb exists in it**. Jobs are fixed
argv from this directory — a tool argument can never become a command line.
Encoding is deliberately *not* exposed: `lario_encoder` owns the RTX, and two
owners of one card is how an encode and a chat model collide.

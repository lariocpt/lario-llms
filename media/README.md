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

Each domain's own docstrings are the documentation. `--help` works on the ones
that take flags (`plan_import.py`, `transcode_import_videos.py`, `enc_hevc.py`,
the `mini_*` corpus).

## Paths

No script spells out where a library lives any more. They import `paths`, and
`paths` reads `core/config.py`, which reads the environment:

```sh
LARIO_PHOTO_LIB=/tmp/photos-clone LARIO_MUSIC_STAGE=/tmp/stage python3 media/...
```

The photo import plan is the one artifact a **human edits between runs**, so it
lives outside the repo and only `PLAN=` points at it
(`core/config.py:PHOTO_PLAN`). It is `~/photos-reorg-work/import-plan.json`,
4,093 records.

`video/oneoff/` and `photos/oneoff/` keep the run-once scripts that already did
their job, with their original hard-coded paths, as a record of what was done to
the library. They are not the reusable surface.

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

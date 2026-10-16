# Media toolkit — implementation plan

> **This file is scaffolding.** It is meant to live in the repo as `media/PLAN.md` and be
> **deleted when the last phase below is verified**. Do not archive it; the READMEs and the git
> history are the permanent record. Progress is tracked by the `[ ]` boxes in §14 — tick them in
> the same commit that completes the work, so the file is a live burn-down and its own deletion is
> justified by an empty list.

Date: 2026-10-13, **amended 2026-10-14 against `e662740` / `91fbd16` / `b999e37`**, **reconciled
2026-10-16 against `0e43d03` / `fd95797`** — what has landed since is marked done, not re-described ·
Machine: bigcachy
Branch: `fix/retained-gpu-contexts-and-guides-20261006`
Repos: `lario-llms` (the corpus, the driver, MCP canonical source, tests), `machine-setup` (vendored MCP
+ per-machine config)

**The goal and the output are unchanged by the amendment.** One surface, **N locations in, one
destination out**, both ends **specifiable at prompt time** — that requirement is what §3.2's driver
delivers and what the MCP's path-taking tier exists to expose.

The corpora moved into `media/` on 2026-10-14 while this plan was being written, and they arrived with a
guardrail that decides the architecture. §3, §10 and §11 are therefore **rewritten**, not annotated;
§2/§12/§13/§14/§17/§18/§19 are corrected where the move made a sentence false. Anything still saying
"port it from `~/photos-reorg-work`" means `media/photos/` — **the directories those words name no longer
exist.** The move was a move, and with the three home directories went everything their `.gitignore` had
kept out of git: the run manifests, the `mini-*.jsonl` verdicts, `REPORT.md`, `import-plan.json`, the music
policy report and the mutagen venv. That is why §14 opened with Phase 0c — landed 2026-10-16, its remainder
is 0c′ — and why §4.3.4 is a rule about where evidence is allowed to live.

---

**Contents** — §1 what we are building · §2 ground truth (what exists, what is lost) · §3 the architecture the code already has (rewritten 2026-10-14) · §4 the contract every domain obeys (plan-default, ledger, deletion rules, pass
lock, summary) · §5 photos + Live Photos · §6 docs (screenshots → transcript) · §7 music · §8 audio /
audiobooks · §9 video + GPU roles · §10 MCP surface · §11 CLI · §12 environment · §13 testing ·
**§14 phases with commit boundaries (the burn-down)** · §15 runbook for dad's drives · §16 fleet ·
§17 decisions · §18 risks · §19 numbers to reproduce and defects to fix.

---

## 1. What we are building

One tool surface, four media domains, one set of guarantees. The owner-facing contract is short:

```
lario-media <domain> <verb> --src <location-or-glob>… --dest <one-location> [--apply]
```

and every run ends with a **summary**: duplicates removed, files changed, space saved, rejects and
failures by reason, destination free before → after.

The four domains:

| Domain | Job |
|---|---|
| `photos` | dedupe, Live Photos → normal photos, date-based folder + filename convention, compress oversized images, merge N sources into one destination |
| `docs` | folder of screenshots / photographs of text → reading order → transcript + summary-analysis, two text files inside the folder |
| `music` | merge N locations into one library, dedupe, correct artist/album tagging and renaming, album artwork |
| `video` | NVENC pre-encode of anything anywhere under `/mnt/media`, driven as a GPU role chosen like a model |

Plus `audio`, which is **already built** (`media/audiolib/`, committed `c11825d`) and gets adopted
into the surface rather than rewritten (§8).

### 1.1 The real jobs this must serve

1. **This week:** consolidate the owner's father's backup HDDs of photos and videos onto **one
   external drive** — including a large number of **WhatsApp conversation screenshots**, which must
   come back as readable transcripts, and **Apple Live Photos**, which must become normal photos.
2. **Ongoing:** the same commands maintain the live libraries (`~/Pictures/Photos`, `/mnt/xfs/music`,
   `/mnt/media`), so nothing is done "by hand this once" ever again.

### 1.2 Non-goals (explicit, to stop scope creep)

* **Not** transcode-on-playback. Everything here is offline pre-processing; Jellyfin/Navidrome must
  always be able to direct-play the result.
* **Not** a photo *manager*. No thumbnails, no timeline UI, no database the user depends on. The
  library stays a directory tree of ordinary files. (Immich is an open question — §17, open item 3 — and a
  separate project.)
* **Not** a downloader. `media/audiolib` already owns downloading; nothing else in the toolkit
  touches the network except the two local model services and (opt-in) AcoustID.
* **Not** an audio transcoder. `media/audiolib/README.md` measured this and rejected it; §8.3 keeps
  that decision.
* **Not** cloud anything. OCR, translation, embeddings and identification run on this box. Dad's
  messages, legal documents and ID scans do not leave the network (§6.7).

---

## 2. Ground truth: what already exists, and what is lost

Every claim below was verified on 2026-10-13 and **re-verified on 2026-10-14 after the move**, which
changed the ground truth in a way nobody has written down yet: the home directories were **moved**, not
copied. `~/photos-reorg-work` (242 files), `~/music-reorganize` (1 069) and `~/video-reorganize` (40)
**no longer exist**; only `~/audiobook-reorganize` (5 files) survives. The `.py` files that were moved into
`media/` are in git and safe. Everything the move did *not* carry — and that every domain's evidence
`.gitignore` had already made invisible to git — was deleted with them: the run manifests and verdicts,
`REPORT.md`, `import-plan.json`, and the music `.venv`. §18.8 records the incident and §13.3 says what
replaces the lost evidence as the check on the ports. Do not re-invent what is in this table; port what
survives it.

| Asset | State | What we take from it |
|---|---|---|
| `media/photos/` (was `~/photos-reorg-work/`, **deleted in the move**) | **in git since `e662740`**: 45 commands + `oneoff/` (10) + `paths.py` + `verify_final.py` | the entire proven photo policy (§5) — thresholds, date ladder, verification invariants. **Live Photos: only `-ContentIdentifier` harvesting exists; §5.1 is unbuilt** |
| `/mnt/xfs/music/_ORGANIZE_REPORT.txt` | **GONE** — it sat at the library root and the move took it. `/mnt/media/_ORGANIZE_REPORT.txt` (146 lines, 2026-10-13) is a **different** document: the *video* reorg write-up (HIMYM, Grace & Frankie, Samurai X) | the music layout/tagging/repair policy (§7) survives **only** as §7 of this plan and in `media/music/mini_*.py` behaviour — §7 is now the primary record, not an excerpt of it |
| `media/music/` (was `~/music-reorganize/`, **deleted in the move**) | **in git since `e662740`**: the `mini_*` corpus (22 files) + `paths.py` + `probe_metric.py`. The other ~1 047 files were evidence + `.venv` (mutagen 1.48.1) — **gone**, §13.3 | the identity/release-matching model and the audio-payload comparison rule |
| `media/music/`'s `build.py` `plan.py` `meta.py` `repair.py` `audit.py` `tagfill.py` `tagrestore.py` `place_art.py` `integrity.py` `navidrome_migrate.py` `lacie_*.py` | **still GONE** — not in `e662740` (only the surviving `mini_*` corpus moved) and not on disk (written into `/tmp/opencode/mw`, which was cleaned) | recoverable, and still only recoverable, from OpenCode session `ses_ede7e3a00ffeXnA7KUTRL2ATe2` (1 213 assistant messages, every `write` body). **Phase A is still the only route.** | |
| `/home/lario/Projects/personal/lario-llms/media/audiolib/` | **committed** `c11825d`: `catalog.py` (340 L) `controller.py` (361 L) `runner.py` (230 L) `pcloud.py` (74 L) `README.md` (163 L) `catalog.json` (3 297 entries) + its own `.gitignore`; `tests/test_audiolib.py` (268 L, offline) | becomes `media/audiolib/` unchanged; the toolkit adopts its conventions (§8) |
| `rtx5080/encoder/{controller.py 362 L, runner.sh 302 L, teardown.py 41 L}` | committed, plus **this session's uncommitted** local-transport + gate edits | video domain engine (§9); must be committed before the role refactor |
| `shared/modelctl.py` (483 L, 27 primitives) | committed | the GPU role work hangs off `selection` / `save_selection` / `render` / `switch` / `warm` / `admission_admin` / `assert_*` / `live_budget` (§9.2) |
| `rtx5080/models.json` | `ocr` profile = **Qwen3-VL-8B-Instruct-Q4_K_M (4.7 GB) + mmproj-F16 (1.1 GB)**, 32 768 ctx, 1 slot, alias `qwen3-vl`, `--image-max-tokens 8192`; presets `capacity`, `fast-64k` | the `docs` domain's structure reader; needs one new preset (§6.5) |
| Intel services (`intel_tools.py`) | all four healthy: embedding **BGE-M3** 1 024-d (CPU), translation **qwen3-8b-int4** (`GPU.0` iGPU), ASR whisper-large-v3-turbo (NPU), TTS kokoro | docs translation + clustering; music later (§6, §7) |
| `machine-setup/shared/agents/{model,encode,image,intel}_tools.py` + `machines/<host>/config/opencode.jsonc` | the vendored-MCP pattern | exactly how `lario_media` gets published (§10) |
| `media/video/` (was `~/video-reorganize/`) | **in git since `e662740`**: `enc_hevc.py`, `bench_qp.py`, `audit_windows.py`, `window_quality.py` + `oneoff/` | the better gates are now **in-tree**: SAR/DAR/cropdetect, whole-file decode, and `-rc constqp -qp N` because this ffmpeg build **silently ignores `-cq`** |

### 2.1 Machine facts that constrain the design

```
GPU      NVIDIA GeForce RTX 5080 · 16 303 MiB total · 13 727 used · 2 207 free · mig.mode.current [N/A]
         resident now: qwen3.8 @ fast-64k, 65 536 ctx, 1 slot, ready
Media    /mnt/media  = /dev/sda1, XFS, reflink=1, ~1.1 TB free
         roots: movies/ series/ videos/ other/ books/ audiobooks/ nextcloud-data/ hdd/ un2/
Scratch  /mnt/xfs    = XFS, reflink=1, ~327 GB free   (music, AI_Models, preserved-*, staging-*)
Photos   ~/Pictures/Photos on /dev/nvme0n1p3, ~19 GB
```

* **No MIG.** "Half the GPU for encoding" cannot be hardware partitioning. It is **VRAM budgeting +
  time-slicing** — who holds how many MiB and who answers first (§9).
* **NVENC is separate silicon.** Its cost alongside a resident model is ~0.3 GiB of CUDA context plus
  frame buffers. Exclusivity today is forced purely by the 27 B chat model preallocating 13.7 GiB.
* **Reflink is available on both XFS volumes** → placement inside the box is CoW-fast and
  space-cheap; an exFAT external drive gets a plain copy. `core/fsx.py` decides, never the caller.

### 2.2 Tool availability (verified)

| Present | Missing (must be installed or worked around) |
|---|---|
| `ffmpeg` `ffprobe` `exiftool` `magick` `vips` `heif-info` `heif-convert` `rsync` `parallel` `fpcalc` `pdfimages` `zbarimg` `tesseract 5.5.3` · python `PIL` `numpy` | `mutagen` (**its only install, `~/music-reorganize/.venv`, was deleted with the directory — nothing in `media/music/` runs without it**), `imagehash`, `pillow_heif`, `onnxruntime`, `cv2`, `beets`, `mid3v2`, `sox`, `cwebp`, `fdupes`/`rmlint`/`jdupes`, `ocrmypdf`, RapidOCR |
| — | **tesseract language data**: tessdata has only `afr` + `osd`. No `eng`. See §6.4 — this is the docs pass's verbatim witness and a hard prerequisite. |

No passwordless sudo. Everything installed must be user-local: a `uv`-managed venv under
`media/.venv`, tessdata under `~/.local/share/tessdata` with `TESSDATA_PREFIX`.

---

## 3. The architecture the code already has, and what sits on top

The corpus landed in `e662740` with one rule that decides the shape of everything added above it, and
the rule is correct, so the toolkit is built **inside** it rather than around it:

> Every file in a domain directory is a **command**. Run it, do not import it. — `media/README.md`

77 modules raise `SystemExit` on import, because importing a command used to *run the pass*. That
guardrail was bought with a real failure (a `--help` typo overwrote a hand-edited 4 093-record plan) and
it will not be traded away to make modules importable. Two consequences, both deliberate:

* **The surface composes passes as processes** — argv lists, `shell=False`, `cwd=media/`. It never
  imports a domain module. Anything the surface needs that no pass does, becomes a new *command* in the
  domain that owns it, called the same way.
* **Locations arrive through `core/config.py`.** Its own docstring: *"it is the only file in the toolkit
  allowed to spell out where things live"*, and every root is `_path("LARIO_*", default)` — so a
  per-invocation destination is already the sanctioned mechanism, not a hack added for this. §3.2 lists
  what each pass actually accepts, verified line by line.

The consequence the owner's requirement turns on: **`--src ×N` and `--dest ×1` at prompt time are
delivered by a driver that validates paths and re-exports the environment seam, then runs proven passes
against it.** No pass is rewritten to take arguments it does not need; the two that genuinely cannot
express N sources are patched, and only there (§3.4).

### 3.1 Layout — `existing` is committed, `new` is to build

```
media/
  core/config.py          existing  every root + scratch + services, LARIO_* overridable
  {photos,music,video,audiobooks}/  existing  the corpora, commands, plus oneoff/ records
  {photos,music}/paths.py existing  shims re-exporting the short names (W, LIB, VIDLIB, HHD, STAGE, DB)
  tools/tidy_library.py   existing  five move-only passes, INDEX.txt + --undo, LARIO_TIDY_AUDIT
  tools/media_tools.py    existing  lario_media MCP: status + jobs, media_run gated, fixed argv
  tests/test_media.py     existing  the tidy guards
  audiolib/               existing  the audiobook fetcher (README §8 of this plan)
  README.md               existing  rules of the house: command-not-import, the ignore convention
  GUIDE.md                existing  every command, its flags or env seam, dry-run conventions
                                    (`0e43d03`) — the surface index Phase G would otherwise author

  run.py                  NEW       the driver: the ONLY path-taking surface (§3.2)
  core/gate.py            NEW       path validation, one-dest rule, nesting refusal, free-space reservation
  core/lock.py            NEW       the pass lock (§4.4)
  core/digest.py          NEW       one content hash for the whole toolkit (blake2b, streamed)
  core/names.py           NEW       target names: collision, escape, exFAT-representable (§15)
  core/fsx.py             NEW       atomic move/copy (reflink → md5-verified copy), and the ONLY code
                                    in the toolkit that deletes — domains request, it executes against
                                    the ledger, exactly as §4.3 demands. Generalises what
                                    tools/tidy_library.py already proves across devices
  core/plan.py            NEW       the plan object: rows, states, resume
  core/ledger.py          NEW       index OVER the passes' own evidence — not a second audit (§4.2)
  core/report.py          NEW       the §4.5 summary, aggregated from that evidence
  photos/livephotos.py    NEW       UUID pairing, tag-strip demotion, quarantine (§5.1)
  photos/purge_quarantine.py NEW    the only thing that deletes inside live-photos-for-deletion/
  docs/*.py               NEW       the whole text-image domain (§6): detect cluster order ocr
                                    language assemble summarise write
  audio/adapter.py        NEW       audio verbs over audiolib's controller, audiolib untouched
  tests/test_run.py       NEW       the driver, on a temp tree
  tests/test_destructive_safety.py NEW  §13.1's eight guarantees
```

Domain code does not import `run.py`; `run.py` does not import domain code. The only shared module is
`core/`, which by design creates, moves and deletes nothing.

### 3.2 The driver: `media/run.py`

```
lario-media <domain> <verb> --src PATH…(1..N) --dest PATH(1) [--apply] [--delete-sources] [domain flags]
```

Responsibilities, in order, and nothing else:

1. **Resolve and validate.** `realpath` every input; every `--src` must exist and be a directory or a
   file; refuse nesting (`--dest` under a `--src` or the reverse) without `--allow-nested <reason>`;
   refuse a path containing a newline or NUL; refuse a destination whose filesystem cannot hold the
   names we produce (exFAT: no symlinks, case-insensitive, 255-char limit — §15).
2. **Enforce exactly one destination.** One `--dest`, always. Because the photo pass files photos and
   videos into *two different libraries by design*, the driver maps the single destination onto the
   conventional subtrees — `<dest>/photos` → `LARIO_PHOTO_LIB`, `<dest>/videos` → `LARIO_VIDEO_LIB`,
   `<dest>/music` → `LARIO_MUSIC_LIB` — so the prompt says one location and the tree inside it has the
   shape the passes already understand. A caller who wants flat output says so explicitly.
3. **Redirect the evidence with the run.** `W` / `LARIO_*_WORK`, `MANIFEST`, `META`, `PLAN`,
   `LARIO_TIDY_AUDIT` all point into `<dest>/_mediatool/<run_id>/`, so a run's artifacts are one directory
   and sit on the same volume as the result. The corpora's rule — *"evidence belongs with the job, not
   inside the library it describes"* — still holds, and §4.3.4 adds the corollary that the job's evidence is
   not scratch either. Two runs never share a manifest.
4. **Free space before writing.** Destination free ≥ predicted unique bytes × the domain's factor
   (photos 0.85 after dedupe, video 1.0, docs ~0), else refuse before the first write.
5. **Take the pass lock** (§4.4) and hold it for the whole run.
6. **Run the passes as argv** (`subprocess.run([...], shell=False, cwd=media/)`), in dependency order,
   stopping on a non-zero exit rather than continuing into a half-built tree.
7. **Index the evidence** (`core/ledger.py`) and **print the summary** (§4.5). The driver deletes
   nothing itself; it only ever reports what a gated pass deleted.

### 3.3 What each pass accepts today (verified 2026-10-14, this is the seam)

| Pass | Takes | Control |
|---|---|---|
| `photos/plan_import.py` | **hard-coded `ROOTS`** — `plan_import.py:48` `{'Mac Photos': f'{HHD}/Mac Photos', 'Photosusa': f'{HHD}/Photosusa'}`; walks `LIB` + `VIDLIB` for existing day folders (:152,:160) | env `APPLY=1` / `DRY` / `PLAN=` / `MANIFEST=` / `META=` / `ZIP_ROOTS=` / `BUCKETS=`; refuses an empty write without `PLAN_ALLOW_SHRINK=1`, keeps `.prev` |
| `photos/transcode_import_videos.py` | the manifest the plan wrote | `MANIFEST=`, workers=2 (card shared with chat) |
| `video/enc_hevc.py` | **`--root` (appendable = N sources)**, `--src-file` (appendable), `--out`, `--log` (required), `--qp 16`, `--min-gain 0.15`, `--min-ssim`, `--crop`, `--crop-rect`, `--set-dar`, `--setpts`, `--no-ssim`, `--metrics-from-start`, positional `only` | refuses to overwrite an existing `--out`; replaces in place without it. Scans `.mkv` only, skipping `.hevc.` — see §3.4.3 |
| `music/mini_sweep.py` → `mini_import.py` | staged source vs library, both env-set (`LARIO_MUSIC_STAGE`, `LARIO_MUSIC_LIB`) | resumable JSONL; DUP ≥ 0.80, NOT-DUP < 0.50, **0.50–0.80 left for a human**; never overwrites, tmp + `os.replace`; tags fill gaps only |
| `tools/tidy_library.py` | **no `--root`** — `passes` positionals (`sanderson-sidecars` `music-sidecars` `mini-stage` `nested-movies` `video-litter`, or `all`), `--apply`, `--undo` (flag, not a value), `--prune-empty`; roots come from `core/config.py` | plan-only by default; `INDEX.txt` per preserved tree, audit at `LARIO_TIDY_AUDIT`; `--undo` replays that audit backwards for the named pass(es), all five if none is named |
| `lario_media` MCP | **nothing** — fixed argv from the JOBS registry, flags whitelist, `--dry` forced unless `apply:true` | `LARIO_MEDIA_ALLOW_JOBS=1`; `media_run` exists only when gated; **no delete verb exists in it** |

That table is the honest answer to "specify the locations at prompt time": **one** pass takes roots on
the command line (`enc_hevc.py --root`, appendable, so N sources in one run); everything else takes
them through the environment — `tidy_library.py` has no path flag at all, and the `mini_*` and
`plan_import` corpora resolve every root, work root included, through `core/config.py` since
§3.4's root fix landed. The MCP deliberately takes no path argument. §11's `--src`/`--dest` is the layer that
turns what the owner types into those variables.

### 3.4 The minimum change to the corpora — three items, nothing else

*The root fix is not on this list any more: it landed 2026-10-16 in `fd95797`.* `VIDEO_LIB` defaults to
`/mnt/media/videos`; 36 photo commands read `paths.W` instead of spelling out the deleted
`~/photos-reorg-work`; the music pipeline's 46 artifact sites — both audio caches included — moved onto
`paths.WORK`, so one run has one evidence root instead of two and writers create the root they are given;
the MCP no longer claims `music_import` has no dry run. `photos/oneoff/` keeps its literals on purpose, as
records of a finished run. What that fix *deliberately* left out is the destination-shaped default of
§4.3.4, which is driver work, and the fact that the work-root **defaults** still name the deleted
directories — harmless now that every command reads the variable, but a run has to name its own root until
Phase 0c′ changes the default.

1. **`plan_import.py` must accept N named sources.** Replace the literal `ROOTS` with a source list
   from `LARIO_SRC_DIRS` (colon-separated `name=path`, defaulting to today's two) so existing behaviour
   is byte-identical when unset. This one is required, not cosmetic: consolidating several drives means
   the *same day* can arrive from three sources, and the rule that keeps a day folder shared across
   sources lives inside this pass. Two sources imported separately would produce two competing
   `2019/2019-07-14/` trees.
2. **Live Photos inside the import rules** — `photos/livephotos.py` as a command the driver calls
   between date resolution and placement (§5.1). The metadata is already harvested
   (`meta_capture.py:30 -ContentIdentifier`, `rescan.py:34 -Apple:ContentIdentifier -XMP:ContentIdentifier`);
   nothing pairs, demotes, quarantines or purges it.
3. **`enc_hevc.py` scans `.mkv` only.** A consolidation job's sources are `.mp4`, `.mov`, `.m4v`,
   `.MTS`, `.avi`. Either pass explicit `--src-file` lists (driver-side, zero corpus change — the
   default) or widen the scan extension set. Do not widen it by default: the `.hevc.` skip and the
   in-place replace contract were written around mkv output.

## 4. The contract every domain obeys

This is the part that is not negotiable, because it is the part that prevents the one failure mode
that matters: silently destroying a file that had no second copy. **No backup exists for the photo or
video libraries** (the originals backup and the 33 GB snapshot were deliberately deleted — recorded in
`photos-reorg-work/REPORT.md`, a file the 2026-10-14 move also deleted; `/mnt/xfs/photos-originals-backup`,
the path `config.py:60` still advertises, does not exist). The toolkit *is* the safety mechanism, and since
that move the same is true of its evidence (§4.3.4).

### 4.1 `plan` is the default

```python
plan = photos.plan(src=[...], dest=..., opts=Options(apply=False))   # touches nothing
report = photos.apply(plan) if opts.apply else Report.from_plan(plan)
report = photos.verify(plan_or_run_id)                               # independent re-read
```

* No verb mutates unless `--apply` (CLI) or `apply: true` (MCP) is present.
* `plan` writes only the ledger and a `plan.json` under `_mediatool/` in the destination.
* `--apply` on a plan that has drifted (source digest changed, destination appeared in the meantime)
  **refuses** and re-plans rather than applying a stale plan.

### 4.2 The ledger (sqlite, `_mediatool/ledger.sqlite`)

```sql
CREATE TABLE run (
  run_id TEXT PRIMARY KEY, domain TEXT, verb TEXT, pass TEXT,      -- structure|encode|docs
  srcs TEXT, dest TEXT, opts TEXT,                                  -- json
  started TEXT, finished TEXT, apply INTEGER, delete_sources INTEGER,
  ok INTEGER, note TEXT);
CREATE TABLE item (
  run_id TEXT, src TEXT, src_digest TEXT, src_bytes INTEGER,
  action TEXT,               -- keep|copy|rename|retag|recompress|demote|quarantine|encode|
                             -- transcribe|translate|reject|fail|delete
  dest TEXT, dest_digest TEXT, dest_bytes INTEGER,
  gate TEXT,                 -- which rule allowed it: byte-dupe|gain>=15|verified-decode|...
  evidence TEXT,             -- json: dates source, overlap score, ssim, witness ratio, ...
  status TEXT,               -- planned|done|skipped|rejected|failed
  reason TEXT, PRIMARY KEY (run_id, src, action));
CREATE TABLE link (          -- docs ordering edges only (§6.3)
  run_id TEXT, src TEXT, next TEXT, authority TEXT, confidence REAL, evidence TEXT);
CREATE INDEX item_status ON item (run_id, status);
```

Two consequences that are worth stating because they are load-bearing:

* **Resume is derived, not tracked separately.** A re-run of the same `src` + `src_digest` with a
  `done` row is a no-op. `--retry-failed` requeues only `failed`.
* **The ledger is the only place deletion authority can come from.** A domain asks; `core/` executes
  against the ledger. A domain that wants to delete what the ledger does not authorise raises, and the run
  fails loudly rather than partially.
* **The ledger indexes the passes' own evidence; it does not replace it.** `INDEX.txt` +
  `LARIO_TIDY_AUDIT` + `--undo` (`tools/tidy_library.py`) and each pass's own manifest are the primary
  records — written against real failures, and `--undo` reads them back. `core/ledger.py` *points at*
  those lines per run, so one `run_id` answers "what happened" without becoming a second truth that can
  disagree with the first. Where they disagree, the pass's own audit wins and the run is reported failed.
  A package with two audit trails is a package where nobody knows which to trust when a file goes missing.

### 4.3 Deletion rules, enforced in code

1. A source may be deleted **only** if a byte-identical survivor is recorded and still present.
2. A transform may replace a source **only** after verification passes for that media type:
   * **image** — pixel dimensions identical, decodes, `DateTimeOriginal` unchanged, and decoded-pixel
     parity within tolerance; recompression additionally requires **≥ 15 % smaller** and never
     accepts a larger file;
   * **audio** — frame-exact duration, sample rate, channels; bitrate compared with tag blocks
     ignored (this is the rule that caught 4 LaCie files whose tags matched but audio did not);
   * **video** — duration ±2 %, resolution/SAR/DAR, track counts, **whole-file decode**, SSIM ≥ floor,
     size gain ≥ 15 %.
3. **Sources are kept by default, always.** `--delete-sources` is explicit, per run, recorded in the
   `run` row, and never implied by another flag — not by `--consolidate`, not by `--merge`, not by
   "but the summary said they're dupes".
4. **Evidence is durable, or the run did not happen.** Every manifest, verdict log and audit a pass writes
   goes under the **destination** (`<dest>/_mediatool/<run_id>/`, §3.2.3) and survives the run. Writing run
   evidence into a scratch directory under `$HOME` is forbidden — this rule is earned the hard way:
   `~/photos-reorg-work` and `~/music-reorganize` held the manifests and verdicts of the 2026 passes, every
   domain's `.gitignore` excluded them from version control, and the 2026-10-14 move deleted the
   directories. Three passes' worth of proof of what was done to a family's photos is gone because the proof
   was kept in the cheapest-looking place. `core/config.py`'s `W` / `*_WORK` roots are repointed out of
   `$HOME` in Phase 0c (§14) so the pattern cannot repeat by default.
5. **`remove()` is not available to domains.** Domains emit a *request*; `fsx` executes it against the
   ledger. A domain that wants to delete something the ledger does not authorise raises, and the run
   fails loudly rather than partially.
6. Nothing outside a source root named on the command line is ever touched. `core/gate.py` refuses a
   `--dest` inside a `--src` (and vice versa) unless `--allow-nested` with an explicit reason (§3.2.1).

### 4.4 Passes, and the lock that keeps them apart

Three passes, one exclusive OS-level lock (`media/core/lock.py`, `flock` on `<dest>/_mediatool/.pass.lock`
plus a global `/mnt/media/.mediatool.lock` when the destination is on that volume):

| Pass | What runs | Hardware |
|---|---|---|
| `structure` | inventory, dedupe, dates, naming, placement, image recompression, tagging | CPU only |
| `encode` | video NVENC | RTX 5080 (`encode` role) |
| `docs` | OCR, translation, transcription, summary | RTX 5080 (`ocr` role) + iGPU translation |

**`docs` is always last and always alone** (owner's rule): nothing is being compressed, renamed or
moved while a model is reading a folder. Two independent reasons: a half-reorganised folder makes the
ordering problem ambiguous, and a mid-flight rename invalidates an in-progress transcript. `docs`
refuses to start while an encode holds the card and reports *which* job holds it; `encode` refuses
while `docs` holds it. The lock is the feature, not an optimisation.

### 4.5 The summary (the deliverable the owner asked for)

Printed at the end of every run, human table + JSON sidecar (`_mediatool/<run_id>.report.json`):

| | count | before | after | saved |
|---|---|---|---|---|
| exact duplicates removed | | | | |
| duplicates found but kept (sources kept) | | | | reclaimable |
| near-duplicates (reported only) | | | | |
| Live Photo stills demoted | | | | |
| Live Photo clips quarantined | | | | reclaimable |
| files recompressed | | | | % |
| files renamed / moved | | | | |
| files retagged / artwork placed | | | | |
| video re-encodes | | | | % |
| text images OCR'd (clusters / images) | | | | |
| messages transcribed / translated | | | | |
| transcript + summary files written | | | | |
| ordering links low-confidence / unresolved | | — | — | |
| rejected, by reason | | — | — | |
| failed, by reason | | — | — | |
| destination free before → after | | | | |

`rejected` and `failed` are separate rows and never merged: a rejection is a gate doing its job
(`SKIPCODEC hevc`, `NOGAIN 4.1%`, `dup_stem` — the last is a same-stem overwrite refusal at
`runner.sh:142`, not a dedupe), a failure is something we could not do and wants a human. The JSON is
the contract for the MCP tool result; the table is for the terminal.

**Reclaimed and relocated are never the same row and never summed together.** A tidy that moves 15.08 GB
into a preserved tree (`91fbd16`) saved no space at all — it moved the problem, correctly, and the total on
disk is unchanged. A dedupe that deletes a verified byte-identical copy is a real reclaim, and that number
is real. Reporting both under "space saved" is how a toolkit claims 20 GB and delivers 4. The table has a
*reclaimed* group, a *relocated* group, and the destination free-before → free-after line, which is the
only number that cannot lie.

---

## 5. Domain: photos

`lario-media photos merge --src GLOB… --dest DIR [--apply] [--delete-sources] [--live-clips=…]
[--heic=keep|jpeg|both] [--neardups=report|off]`

Ported from `media/photos/` (was `~/photos-reorg-work/`) — the numbers below are the ones that ran on
2026-10-10 (12 264 → 8 941 files, 77.05 GB → 34.94 GB, **54.6 % saved**), not invented ones.

| Concern | Proven implementation to port | Policy carried over verbatim |
|---|---|---|
| layout | `rebuild_moves*.py`, `consolidate_days.py`, `verify_final.py` | `YYYY/YYYY-MM-DD <Event>/NNN_YYYYMMDD-HHMMSS.<ext>`, one folder per day, **a real event name beats a date label**, no `Unsorted` bucket in the final tree |
| dates | `rescan.py`, `dates_backup.sh`, `meta_*.json` | EXIF `DateTimeOriginal` → `CreateDate` → filename pattern → filesystem mtime, **recording which one won** in `item.evidence` |
| exact dupes | `hash_tree.py` (BLAKE2b + size prefilter), `delete_source_duplicates.py` | byte-identical only; one ledger row per deletion naming the survivor |
| near dupes | `dhash_index.py`, `find_neardups.py`, `dedup_candidates.py`, `zip_perceptual.py` | dHash candidate + **pixel verification**, burst grouping, **report-only** (§17, adopted default 2) |
| Live Photos | `meta_capture.py`, `dedup_candidates.py` | see §5.1 — this is the one place the old rule ("keep the still, ledger the clip") is upgraded |
| recompress | `recompress_imports.py` | **≥ 15 % smaller or don't**; metadata + GPS re-attached verbatim; **RAW (NEF) never re-encoded**; never grow a file |
| archives | `extract_zips.py`, `classify_zips.py`, `check_zips.py` | zip contents deduped *against the library*, provenance kept (`source: <zip>!/<path>`) |
| proof | `audit_deletes.py`, `prove_deletes.py`, `prove_unique.py`, `audit_coverage.py`, `verify_final.py`, `verify_meta_recorded.py` | an **independent** re-proof pass that re-reads the filesystem — never a re-read of the log that claims success |

`verify_final.py`'s invariants become `photos/verify.py`'s, unchanged: **0** manifest rows pointing at
a missing file · **0** files no manifest names · **0** filenames off the convention · **0** filename
dates disagreeing with their folder · **0** duplicate paths.

Ordering of steps: inventory (magic bytes, never extensions) → byte dedupe → near-dup detection →
**Live Photo demotion (§5.1)** → date resolution → layout + numbering → recompress → place
(reflink→copy, digest-verify, then optionally delete source) → verify → report.

### 5.1 Apple Live Photos — demote to normal photos, quarantine the clips

**What a Live Photo is.** Not a GIF, not two glued files: a still plus a short MOV joined by a shared
**`ContentIdentifier` UUID**, present in the still's EXIF/XMP (`AppleLivePhoto:ContentIdentifier`,
`LivePhotoIdentifier` on newer iOS) and in the MOV's QuickTime `uuid` atom
(`com.apple.quicktime.content.identifier`, `live_photo_auto`).

**Detection, both signals recorded:**

1. `exiftool -contentidentifier -livephotoidentifier -livephotoassets -applelivephoto:style` on every image.
2. `-contentidentifier` plus the QuickTime `uuid`/`meta` atom on every video.
3. **Pair on exact UUID match.** The only authoritative rule — it survives renames, different
   extensions, zip extracts and files landing in different folders.
4. Fall back to stem match (`IMG_1234` + `IMG_1234.mov` case-insensitively, `IMG_1234(1).HEIC`,
   `IMG_1234.HEIC.mov`) **only** when neither file carries a UUID, tagged
   `confidence: filename` for separate review. `IMG_1234.HEIC` + `IMG_1234.MOV` is frequently *not*
   the real pair.
5. Recognise the older packaged form (`LivePhotoAssets` jpg/heic + mov inside one container) and the
   `.AAE` sidecar as **supporting evidence only**, never as the pairing rule.

**The demotion.**

* **Copy the still byte-preserving.** Strip *only* the linkage — `AppleLivePhoto:*`,
  `LivePhotoIdentifier`, `ContentIdentifier`, `LivePhotoAuto` — so iOS, Google Photos, Immich and
  Windows stop treating it as a Live Photo. Every other tag (`DateTimeOriginal`, GPS, orientation,
  colour profile, maker notes) is re-attached verbatim. **Never re-encode an image just to demote
  it** — exiftool tag-copy does it losslessly, pixels stay identical, and the file is counted under
  *metadata changed*, not *recompressed*.
* **The MOV goes to a quarantine tree**, named for exactly what it is (`--live-clips`):

  | value | behaviour |
  |---|---|
  | `quarantine` *(default)* | clip moved to `<dest>/live-photos-for-deletion/YYYY/YYYY-MM-DD <Event>/NNN_YYYYMMDD-HHMMSS.mov` — same basename as its still, same date tree, auditable at a glance. The library itself reads as plain photos. |
  | `strip` | clip not written to the destination; source untouched; omission ledgered. |
  | `delete` | clip removed from the source too — honoured only together with `--delete-sources` (§4.3.3). |

  Owner's decision (2026-10-13): quarantine rather than delete in-run — *"rename it
  `live-photos-for-deletion/…` to be clearer, then we can go ahead and delete them after."*
* `live-photos-for-deletion/` carries a `README-delete-me.txt` at its root: what these are (the 1–3 s
  of motion around each photo), which run created them, and that deleting them loses only that
  motion, never the photo. The decision is **deferred and obvious**, sitting next to the library
  rather than buried in a log.
* **The quarantine tree is excluded from every later scan** — photo inventory, dedupe, and video
  encode — at the root and at any depth, so a demoted clip can never be mistaken for a photo to
  organise or a movie to encode.
* **Purging is its own verb and it is gated.** `lario-media photos purge-quarantine --dest DIR`
  deletes *only* inside that tree, and only when: every file has a `quarantine` row in a ledger, its
  current digest matches the recorded one, and the tree contains **nothing unrecognised** (one
  stranger file aborts the purge and is listed). No symlinks followed, no path outside the root, and
  it prints *space reclaimed*. Independent of `--delete-sources`: if sources were kept (the default),
  purging clears the destination copies and leaves the source drive's clips alone — that drive stays
  the owner's to wipe wholesale.
* **Orphans are reported, never guessed** → `_mediatool/live-photo-unresolved.jsonl` with both
  candidate sets: a clip whose UUID matches nothing in this run, or a still flagged Live with no clip
  present. Silently dropping a 3-second video is precisely the class of loss this toolkit must not
  cause. A *resolved* clip is quarantined, not reported — quarantine is the resolved path.
* **Verified before counting:** a demoted still must decode, keep its pixel dimensions and its
  `DateTimeOriginal`, and report **no** Live marker. Verification re-reads the destination file, not
  the write result — and **any destination still carrying `ContentIdentifier` fails the run**, not a
  warning. The pass also checks that no quarantined clip was left inside the library tree proper.

Scale, for expectation-setting: the 2026-10-10 pass left only **2** Live Photo stills in
`~/Pictures/Photos`, so this is largely done for the *existing* library. The volume is in the **new
sources** — dad's HDDs — which is why it is a pipeline step with the clip default chosen up front,
not a per-folder afterthought.

---

## 6. Domain: docs — screenshots and photographs of text

`lario-media docs read --src DIR… [--dest DIR] [--langs auto] [--original=keep|drop]
[--engine=witness|vl|both] [--redoc] [--apply]`

**Why a domain and not a feature.** Ordering a folder of chat screenshots is not sorting. Screenshots
of one conversation **overlap each other**, so the correct output is an *assembly*: recover the
reading order, then merge overlapping text so each message appears exactly once. Filename sorting
produces a transcript with holes and duplicated paragraphs.

### 6.1 Engines (all local)

| Role | Engine | State today |
|---|---|---|
| **Structure reader** — layout, who is speaking, bubble boundaries, reply-quote nesting, date separators, handwriting, degraded photos | **RTX 5080 `ocr` profile — the dedicated image model on that card**, alias `ocr` / `qwen3-vl`: Qwen3-VL-8B-Instruct-Q4_K_M (4.7 GB) + mmproj-F16 (1.1 GB), 32 768 ctx, 1 slot. **Never `qwen3.8`.** | weights on disk; needs the `ocr`/`docs` role resident (§9.2–9.3) |
| **Verbatim witness** — the text itself, timestamps, bounding boxes | `tesseract 5.5.3`, escalating to **RapidOCR/PaddleOCR (ONNX)** if tesseract underperforms on paper photos | tesseract installed, **tessdata has only `afr`+`osd`** — see §6.4 |
| Translation to English | `intel_translate` = **qwen3-8b-int4, INT4, iGPU `GPU.0`** | healthy, loaded |
| Language detection, thread clustering, topic similarity | `intel_embed` = **BGE-M3**, 1 024-d, 8 192 max length, CPU | healthy, loaded |
| Later: search over transcripts | BGE-M3 again — transcripts become searchable without re-OCR | healthy |

Owner's rule, implemented literally: **non-English text is OCR'd in its own language first, then
translated by the Intel service, and only then assembled** — the vision model never translates while
it reads, and a machine translation of a partial OCR is never transcribed.

### 6.2 Pipeline

1. **Filter to text-bearing images.** Screenshots are recognised as screenshots (uniform background,
   status-bar row, sharp-text edge energy, aspect ratio; naming patterns
   `Screenshot From 2026-07-18 18-13-27.png`, `Screenshot_2024-01-02-13-45-06.png`, `IMG_1234.png`)
   versus **photographs of paper** (perspective, page edges, uneven illumination). Both supported;
   the ordering signals differ, and `docs/detect.py` records which class each image got.
2. **Cluster into documents first.** One folder from dad is very likely *several* conversations.
   Cluster on the OCR'd header bar (contact / group name), then wallpaper + topic-embedding
   similarity. **A cluster is the unit that is ordered and transcribed.** Cross-cluster links are
   reported, never merged.
3. **Order — descending authority, and record which one won** (`link.authority`):
   1. **In-message timestamps.** Read every visible chat timestamp *plus* every **date separator**
      ("Today", "12 Oct", "Yesterday 21:04"). A separator is an **absolute anchor** and the messages
      beneath it are **monotonic** — this alone resolves most threads exactly and catches the classic
      case where screenshots were copied onto a drive out of order.
   2. **Capture time** — EXIF `DateTimeOriginal`/`CreateDate` → timestamp embedded in the filename →
      filesystem mtime, same ladder as §5, with provenance. Sub-second ordering trusted only where the
      clock genuinely differs.
   3. **Overlap chaining.** Consecutive screens of one scroll share visible messages. Align per-image
      message lists with `difflib` on normalised text, anchor on exact repeats, and build the chain as
      a **solver over pairwise overlap confidence** — not a sort. A screenshot adding no new text (the
      same screen re-taken) is dropped as a duplicate **frame** and ledgered.
   4. **Explicit page numbers** — `1/N` badges, printed numbers, `page_002`, `IMG_0007(3)`.
   5. **Top/bottom strip similarity** for photos of paper with no text timestamps: the top band of
      page *n+1* should resemble the bottom band of page *n*.
   6. **Filename sequence** — last resort, always stamped `confidence: filename`.

   Every edge carries `authority` + `confidence` + `evidence`. **Low-confidence links and ambiguous
   branches are reported, never silently resolved**: a cycle, a two-way tie, or a page that fits
   equally well in two places goes to `_docs/unresolved.jsonl` with both candidates, and the
   transcript says so in its header.
4. **OCR per image — two engines, one witness.** The non-generative engine produces verbatim text,
   timestamps and boxes; Qwen3-VL produces the structure around it. **Assembly rule (structural, not
   rhetorical): any token span the VLM claims that the witness pass does not support is written as
   `[?]` and raises a finding — never rendered as prose.** VLM discipline: return *only* visible text
   with speaker and timestamp; never complete, repair, infer, translate or summarise; mark illegible
   spans `[?]`. Every emitted line keeps provenance (`src: IMG_1234.png, band 2, witness: 0.93`), and
   a line the model cannot attribute is discarded rather than kept. Tall screenshots are read in
   **overlapping bands** when one pass would exceed the image-token budget.
5. **Language handling.** Detect per cluster *and* per message (WhatsApp threads code-switch).
   English → straight to assembly. Otherwise OCR → `intel_translate` **per message-run with the
   source language pinned** (never per word) → assembly. **Both texts are kept**: the translated line
   with `» original (ur): …` beneath it, unless `--original=drop`. Names, numbers, currency and dates
   pass through untranslated.
6. **Merge the overlap** into one linear timeline: one message per occurrence, earliest attested
   wording wins, and a disagreement between two screenshots of the same bubble is **flagged**, not
   silently picked.
7. **Anti-hallucination gate before anything is written.** Every emitted message must exist in the
   per-image OCR record; the verifier re-reads a stratified sample of images **plus every image that
   contributed a number, date, address, name or amount**, comparing token overlap against the witness
   pass where language data is available. Failures drop the line and raise a finding. The summary
   reports the verification **ratio as a number**, never a "pass" word.
8. **Write the two text files** (§6.6).

### 6.3 Outputs — inside the folder they describe, per thread

```
YYYY/YYYY-MM-DD <Event>/TRANSCRIPT <thread-slug>.txt
    [2024-03-05 14:22 Tue] Dad: <text>
    » original (ur): <text>            # unless --original=drop
    header: cluster id, image count, ordering authorities used, verification ratio,
            "single-engine OCR, unverified" when no witness engine is installed (§6.4)
YYYY/YYYY-MM-DD <Event>/SUMMARY <thread-slug>.txt
    who appears · date span · topics · key facts and figures, each citing the transcript line
    · decisions · commitments and action items with who owes what · open questions
    · sensitive items (health, legal, money, addresses, account numbers) listed as "mentioned",
      not restated in full
<dest>/_docs/<thread-slug>.order.json    order, link authority/confidence/evidence, per-line provenance
<dest>/_docs/unresolved.jsonl            ambiguous links, unreadable images, failed verification
```

* Per-thread, not per-folder, so **merging N sources into one destination cannot make them collide**.
* **Summary discipline:** the summariser sees **only the assembled transcript, never the images**, and
  every claim cites a transcript line. That is what stops it inventing a fact the thread never
  contained, and it makes the summary auditable.
* **Idempotent:** `TRANSCRIPT*`, `SUMMARY*` and `_docs/` are excluded from every scan (image inventory,
  dedupe, video encode); a folder carrying a transcript is skipped unless `--redoc`, keyed on the
  **digest set of that folder's images**, so a re-run costs nothing and a changed image set reopens
  exactly the affected thread.
* **The images are never modified by this pass** — P3 is read-only over them by construction. That is
  the mechanical guarantee behind "no encoding/compression at the same time".

### 6.4 Prerequisite: OCR language data (currently absent)

`tesseract 5.5.3` is installed but `usr/share/tessdata/` holds only `afr` and `osd` — **no `eng`**.
Until fixed, Qwen3-VL is the *only* reader, so:

```sh
mkdir -p ~/.local/share/tessdata && cd ~/.local/share/tessdata
for L in eng urd arb hin; do
  curl -fLO https://github.com/tesseract-ocr/tessdata_fast/raw/main/$L.traineddata; done
# export TESSDATA_PREFIX=$HOME/.local/share/tessdata   (set in the toolkit env, §12)
```

No root needed. Until it is done, **every transcript header must read "single-engine OCR,
unverified"** — a transcript that looks authoritative and isn't is worse than one that admits it is
provisional. RapidOCR/PaddleOCR (ONNX, CPU today, iGPU later) is added only if the fixture in §13.4
shows tesseract underperforming; it is better for Arabic/Urdu scripts and returns boxes, which helps
reading order inside an image.

### 6.5 Profile sizing — measured, arithmetic written down

Two knobs do two different things and are habitually confused:

| Knob | Now | What it actually controls | Decision |
|---|---|---|---|
| `--image-max-tokens` | 8192 | **legibility** — resolution per image. Qwen3-VL spends ~1 vision token per 32×32 px block (patch 16, 2×2 merge) ⇒ 8192 ≈ **8.4 Mpx**. A 1080×2400 screenshot ≈ 2.5k tokens, 1170×2532 ≈ 2.9k — **~31 % of budget** | **keep 8192.** ~2.7× headroom already. Raise to 12288 only for stitched multi-screen scrolls / dense paper photos |
| `-c` context | 32768 | **continuity** — how many images + how long an output fit in one request. One image + prompt + ~2.5k output ≈ 6k, so 32k already admits 4–5 screenshots per call | **raise to 65536** so a thread segment stitches in one call ⇒ ~11.8 GiB resident, ~4.5 GiB left for NVENC. Above ~96k the encode role stops fitting: measure first |
| `--mtmd-batch-max-tokens` | 128 | prefill throughput: a 2.9k-token image prefills in ~23 chunks of 128 | **the real bottleneck.** Raise to 1024–2048 and measure; cheapest speed win available |
| `--cache-ram` | 0 | prompt cache disabled | fine for unique images; revisit only if bands of one image are re-sent |

Resident cost: 4.7 GB weights + 1.1 GB mmproj (vision encoder runs on GPU with `-ngl 999`) + ~2.3 GiB
KV at 32k with `-ctk/-ctv q8_0` ⇒ **~9.5 GiB** of 16 303 MiB. Confirm empirically from
`usage.prompt_tokens_details.image_tokens` rather than trusting this arithmetic.

**No second vision-*LLM*.** Escalation order, stop as soon as the fixture passes: (1) tesseract with
proper traineddata; (2) RapidOCR/PaddleOCR ONNX in the pinned env; (3) Qwen3-VL-8B at Q6_K/Q8 rather
than a different 8B (+1.5–3 GB, still fits at 32k); (4) only if all that fails, a 30B-class VLM — at
~20 GB it **cannot be resident alongside NVENC** and would have to take the card outright.

### 6.6 Cost

One slot, serial. Budget ~2–6 s per screenshot for OCR at 32k (band-splitting and long scrolls push
the high end): a few hundred images is tens of minutes, a few thousand is a few hours. Translation
adds ~0.5–2 s per non-English message-run on the **iGPU**, which runs concurrently with the next
image's OCR because they are different devices. The pass reports images/sec and a running ETA, and is
resumable per image — the ledger keys image digest → OCR record, so a killed pass loses only the
in-flight image.

### 6.7 Privacy

This domain is deliberately 100 % local: RTX 5080 for OCR, iGPU for translation, CPU for embeddings.
Dad's messages, legal documents and any ID scans do not go to a third-party API — which is exactly why
the pipeline is built on these two services instead of a hosted OCR API.

---

## 7. Domain: music

`lario-media music merge --src GLOB… --dest /mnt/xfs/music [--apply] [--delete-sources]
[--artwork=keep|embed|both] [--fingerprint=off|on] [--reindex=navidrome|off]`

The layout and repair policy is **already written down** — `/mnt/xfs/music/_ORGANIZE_REPORT.txt`
(282 lines) is the contract from the last full library run, and `mini_*.py` in
`media/music/` (was `~/music-reorganize/`) is the code that produced it. Port, don't re-derive.

### 7.1 Layout contract (verbatim from the report)

```
<Artist>/<YYYY> <Album>/<disk-N> <NN> <title>.<ext>
  Known artist, unknown album  ->  Artist/[Unknown Album]/
  Not identifiable at all      ->  _Unsorted/<original folder path>
```

Nothing is ever discarded for being unrecognisable: it lands in `_Unsorted/` under its original path
so a human can decide later. Two special cases from the last run are the model for how to treat
non-music audio — **48 Apple voice memos** went to `/mnt/xfs/preserved-lacie/lacie-voice-memos/` with
a list, and **1 file no decoder could open** went to `/mnt/xfs/preserved-lacie/lacie-unreadable/`.
`music/` must have those same two escape hatches (`preserved/` and `unreadable/`), and they are
*outside* the library tree so a player never indexes them.

### 7.2 The steps

1. **Inventory** — `ffprobe` every candidate (magic bytes, not extensions: the last run found MP3 data
   in `.wma` containers and vice versa), plus mutagen tags. One row per file: codec, bitrate, sample
   rate, channels, duration, disc/track, artist/album/title, MBID if present, embedded-art presence.
2. **Exact dedupe** — size prefilter + BLAKE2b. `mini_bytedupes.py` is the reference.
3. **Identity resolution** — the model that survives in `mini_match.py` / `mini_match2.py` /
   `mini_arbiter.py`: filename-parse candidates → existing-tag evidence → MusicBrainz (only when
   `--fingerprint=on` or when the name is genuinely ambiguous) → **arbiter with per-source
   confidence**, recorded in `item.evidence`. `--fingerprint=off` is the default (owner's decision,
   §17): no AcoustID lookups unless asked.
4. **Audio-payload comparison before any "same recording" claim.** This is the rule that caught the
   4 LaCie files whose tags matched perfectly but whose audio did not. Two files are the same
   *recording* only if duration matches to the frame and the decoded payload matches
   (`mini_cov.py` / `mini_covprobe.py` — coverage-calibrated, with `feats-cache.pkl` and
   `fullenv-cache.pkl` as the caches to regenerate). A tag-only match with mismatched audio is
   reported as **different recording, same tags**, never merged.
5. **Tag + name** — `copy → tag → re-read and verify → replace`, exactly as the report describes, so a
   tag write that fails halfway leaves the original intact and the ledger says which step it died in.
6. **Artwork** — front cover embedded when a source file already carries it; folder `cover.jpg`/
   `folder.jpg` retained; never downscale existing art; a file with no art anywhere is listed rather
   than silently filled from the network.
7. **Place** (§4.3) → **verify** → **reindex** (`music/reindex.py` touches the library root mtime and
   prints the Navidrome scan command; Navidrome scans on its own poll interval, so this is a nudge,
   not a dependency).

### 7.3 What is genuinely lost, and how Phase A recovers it

`build.py` `plan.py` `meta.py` `repair.py` `audit.py` `tagfill.py` `tagrestore.py` `place_art.py`
`integrity.py` `navidrome_migrate.py` `lacie_*.py` were written into `/tmp/opencode/mw`, which was
cleaned — they no longer exist on disk. **The complete source is inside OpenCode session
`ses_ede7e3a00ffeXnA7KUTRL2ATe2`** (1 213 assistant messages; every `write` tool body is preserved).
Phase A dumps that session **untruncated** into `media/_attic/2026-10-recovered/` (the earlier dump to
`/tmp/opencode/sess-music.txt` truncated at 20 KB per file — redo it), then ports the rules into
`music/*`. The `mini_*.py` corpus + JSONL evidence (`mini-verdict-final.jsonl`, `mini-proof.jsonl`,
`mini-meta.jsonl`, `mini-byte-dupes.json`) is the **golden fixture**: the ported module must reproduce
those verdicts on the same inputs (§13.3).

---

## 8. Domain: audio / audiobooks — adopt `media/audiolib`, do not rewrite

`lario-media audio <verb>` is a thin adapter over the code that already works and is already
committed (`c11825d`):

| File | Lines | Role |
|---|---|---|
| `media/audiolib/catalog.py` | 340 | the organiser: `ROOT_MAP` / `ITEM_MAP` / `JUNK_NAMES` (L44–54), `clean()` (61), `safe_parts()` (68), `destination()` (79), `layout()` (162); `build --refresh` reports deltas; `serialize()` writes one entry per line so a 3 300-line blob diffs in review |
| `media/audiolib/controller.py` | 361 | the job surface: `SAFE_PATH` regex (32), `MEDIA_ANCHOR = '/mnt/media'` (35), `disk_free` (41), `lock_path`/`lock_holder` (49/53) single-writer flock, `read_state`/`write_state` (85/95), `running`/`latest`/`active` (110/123/129), `inventory` (133), `catalog_op`/`refresh_op`/`start_op` (157/175/187) |
| `media/audiolib/runner.py` | 230 | resumable worker, size-then-content verify, per-file ledger |
| `media/audiolib/pcloud.py` | 74 | pCloud transport, host rotation on retry, account-throttled (~8–9 MiB/s at 4 *and* 6 workers ⇒ whole library ≈ 80 min regardless of worker count) |
| `media/audiolib/catalog.json` | 3 297 entries | **frozen output, committed** (46.01 GB library) |
| `tests/test_audiolib.py` | 268 | offline, passing — the only test coverage any media domain currently has |

**What `media/audio/adapter.py` does:** expose `catalog`, `refresh`, `start`, `status`, `cancel` as
domain verbs with the same defaults, so `lario-media` is one surface. **What it does not do:** touch
`media/audiolib/`. That code has a working library behind it (43 GB, 8 collections on disk at
`/mnt/media/audiobooks/islam`) and job artifacts at `/mnt/media/audiobooks/.audiolib-jobs/j-<id>/`;
rewriting it buys risk, not value.

### 8.1 Patterns the rest of the toolkit copies from it

* `destination()` refuses any computed path that escapes the root — every domain's `names.py` needs the
  same guard, including photos (`../` in an event name from a malformed date is a real input).
* `.state/` for runtime JSON (committed code, uncommitted state) — this is the shape §12's ignore rules
  assume.
* `catalog.json` as **committed frozen output** with one entry per line: a reviewer can read a diff of
  a 3 300-entry library. Every domain's report gets the same property (§4.5 JSON sidecar, one item per
  line).
* flock-before-spawn + `lock_holder` reporting *who* holds it — the basis of the pass lock (§4.4).
* free-space gate before starting (`min_free_gb`, default 20) — same gate in `core/fsx.py`, and the
  external-drive case makes it critical (§15).

### 8.2 Audiobookshelf follow-up (owner action, not code)

`/mnt/media/audiobooks/islam` exists on disk (**43 GB, 8 collections**; catalog 3 297 files / 46.01 GB)
but the AudiBookshelf library reports `lastScan: null` and 0 items — it has **never been scanned**.
Run *Library → Rescan* in the ABS UI. If the collection is to be regrouped into ABS book folders
(one folder per audiobook), do it **before** that first scan so ABS builds its IDs once instead of
twice. Compose file:
`lario-home-infra/containers/personal/audiobookshelf/docker-compose.yml` (ABS 2.37.1).

### 8.3 Audio re-encode stays rejected

`media/audiolib/README.md` measured this over 34 files / 14.4 h: the library is AAC-LC 32 kHz mono
~63 kbps (96.1 % of the file is audio); stripping cover art and chapters buys **1.9 %**, and re-encoding
buys nothing worth the loss on ~1 550 hours of already-compressed speech. Keep that conclusion; the
toolkit does **not** offer audio transcoding for this library. (`video` is a different arithmetic —
§9 — because those files are 100–1 000× larger and 8-bit x264.)

---

## 9. Domain: video, and the GPU role redesign

### 9.1 What the encoder is today

`rtx5080/encoder/`: `controller.py` (362 L) + `runner.sh` (302 L) + `teardown.py` (41 L), with this
session's **uncommitted** rewrite — fully local (no ssh): ffprobe probing, `SKIPCODEC hevc|av1|vvc`
(runner.sh:155), `NOGAIN` < 15 % (`MIN_GAIN_PCT=15`, :212), `SKIP dup_stem` (:142), temp on `/mnt/xfs`,
`.shipping` promote with sha256 re-verification at the final path (:207–232), `/mnt/media/` guard, and
`LIMIT` slots that refusals do not consume. `bash -n` and `py_compile` are clean.

**Still pending before the role work** (Phase B2):

1. `runner.sh:270` still uses `find "$SRC_ROOT" -maxdepth 2` — must be recursive at **any depth** with
   the quarantine exclusion (§5.1) so a nested series folder is not invisible.
2. The `read_intervals` quoting defect that produced **29 false `FAIL`s** in job
   `20261010-084227-b9b9` (`Error parsing read interval #0 '5915+%60'`) — sources untouched, but every
   one of those was a wasted rejection. Fix the quoting and re-run that list.
3. Steal two better gates from `media/video/enc_hevc.py:main` — now in-tree, `--root` appendable:
   **SAR/DAR/cropdetect
   comparison** and a **whole-file decode** check instead of sampled probes.
4. The MCP description at `machine-setup/shared/agents/encode_tools.py:23,25` still advertises "library
   on lario-media" and `/srv/media/Movies`. It must read `/mnt/media/{movies,series,videos,other}`.

### 9.2 Half a GPU for encoding: what that actually means

```
$ nvidia-smi --query-gpu=mig.mode.current --format=csv
mig.mode.current [N/A]
```

**MIG does not exist on GeForce.** So "give half the GPU to encoding" is implemented as **VRAM
budgeting + arbitration**, not partitioning:

* **NVENC/NVDEC is separate silicon** from the CUDA cores the LLM uses. The real cost of encoding
  beside a resident model is the CUDA context + frame buffers — on the order of 0.3 GiB — not 8 GiB.
  Today exclusivity is forced only because the chat model preallocates 13.7 GiB of 16 303 MiB.
* Therefore the **`encode` role is a reservation**, not a model: drain the inference slots, load nothing,
  leave NVENC reachable. That is the whole trick, and it is why encoding and OCR can never overlap (§4.4).
* **Roles are chosen like models are**, replacing the current per-job drain→stop→restore dance:

  | Role | Holds | Inference | Encode | OCR |
  |---|---|---|---|---|
  | `model` (default, = today) | VRAM with a resident LLM | yes | refused | refused |
  | `encode` | nothing (or ≤4 GiB with the `ocr` profile pinned, pending probe §9.3) | refused | yes | refused |
  | `docs` | the `ocr` profile at 65 536 ctx (~11.8 GiB) | refused (chat model is drained) | refused | yes |

* Admission control is the enforcement: `modelctl.assert_not_held()` and the `live_budget` check fail
  loudly when a caller wants the card for something else, and the error names the holder. A client
  must never discover exclusivity by watching a job stall.
* `model_switch` stays the only thing that changes residency, and it keeps requiring a fresh
  `switch_token` from `model_status` — that is what stops a stale plan from evicting a model someone is
  mid-conversation with. `encode`/`docs` become entries in the `rtx5080` menu (`model_options`), so
  `lario_models` needs no new verb.
* **Nothing in this section may be exercised while another session holds an encode.** Right now
  `rtx5080.service` holds 13.7 GiB with `qwen3.8 @ fast-64k`, `ready: true`; changing the `ocr` profile
  requires an explicit `model_switch` with a fresh token.

### 9.3 The `ocr` profile change (measured arithmetic in §6.5)

`rtx5080/models.json` today: `ocr` = 32 768 ctx, 1 slot, alias `qwen3-vl`, `-ngl 999`,
`-ctk/-ctv q8_0`, `--mtmd-batch-max-tokens 128`, `--cache-ram 0`, `--image-max-tokens 8192`. A sibling
`describe` profile already exists at 65 536 with `--image-max-tokens 2048`.

The change (Phase B2, behind a probe):

```
ocr: -c 32768 → 65536
     --mtmd-batch-max-tokens 128 → 1024..2048      # the real throughput lever
     --image-max-tokens 8192 kept                  # ~8.4 Mpx; a screenshot needs ~2.9k
new preset, e.g. "docs-65k": models.ocr.context = 65536
```

**Gate the `encode`-with-`docs` combination on a throughput probe, not on optimism:** with the `ocr`
profile resident at 65 k (~11.8 GiB) roughly 4.5 GiB is left, which is enough for NVENC but has not
been measured. If concurrent NVENC degrades OCR throughput by more than ~10 %, the two roles become
strictly exclusive and §4.4's lock is the whole story.

### 9.4 Video pipeline

`scan` (recursive, any depth, quarantine-excluded) → `gates` (`SKIPCODEC`, `NOGAIN`, and `dup_stem`
(`runner.sh:142-143`) — which is **only** the refusal to rename `X.mp4 → X.mkv` over a same-stem `.mkv`
that already sits there, not duplicate detection: nothing in the encoder recognises a second copy, a
near-duplicate, or a split-title part that is really the same file, and no size-budget gate exists at all
yet) → `encode` (NVENC, temp on `/mnt/xfs`) → `verify` (duration ±2 %, resolution, track
counts, **whole-file decode**, SSIM floor) → `promote` (`.shipping` → in place, sha256 at the final
path, mirror kept) → `report`. Sources are kept unless `--delete-sources`, and the existing
commit-step ordering (`runner.sh:9-11`) already implements "verified HEVC replaces the source only after
re-verification at the destination" — keep it.

---

## 10. MCP surface (what OpenCode sees)

`media/tools/media_tools.py` exists and is registered — `media_status`, `media_jobs`, plus `media_run`
that appears **only** when `LARIO_MEDIA_ALLOW_JOBS=1`. Its safety properties are correct and are kept,
and its one real limitation is that a tool argument can never be a path, so the owner's job (N
locations in, one destination out) cannot be expressed through it at all.

Kept unchanged:

* **Jobs are fixed argv from the JOBS registry** — today `photos_plan` and `photos_video_import`.
  *A tool argument can never become a command line* stays true for everything that is not a validated
  path.
* **No delete verb exists in it.** That is not a gap to close.
* **Encoding is not exposed here.** `lario_encoder` owns the RTX; two owners of one card is how an
  encode and a chat model collide (§9).
* `--dry` forced unless the caller explicitly says `apply:true`.

To add, on the same safety footing:

| Tool | Args | Notes |
|---|---|---|
| `media_status` | — | existing; extend with pass-lock holders and tessdata presence (§6.4) |
| `media_jobs` | — | existing; extend with the new passes once they exist |
| **`media_plan`** | `domain`, `verb`, `src[]`, `dest`, `opts` | **new, and the point of §3.2.** Paths are validated by `core/gate.py` before anything runs: realpath, must exist, no nesting, no newline/NUL, destination free-space check. Returns the §4.5 summary computed from a dry run. Gate: `LARIO_MEDIA_ALLOW_JOBS=1` |
| **`media_apply`** | `run_id`, `confirm: "apply"` | re-validates that no source digest drifted and no destination path appeared since the plan, then runs the same argv with `APPLY=1`. **Never accepts a path argument** — only a `run_id` from a plan it produced |
| `media_report` | `run_id` | the aggregated evidence: rejects by reason, unresolved ordering links, quarantine contents |

Rules:

* **Paths enter only through `media_plan`.** `media_apply`, `media_report` and everything gated take ids,
  never paths — so a plan cannot be steered somewhere else between the review and the write. That is
  what makes a path-taking surface safe enough to expose at all.
* argv is always a list, `shell=False`, `cwd=media/`. No string is ever interpolated into a shell.
* **`docs` refuses to start while the pass lock is held by an encode, and names the holder** (§4.4), so
  the agent reports *who* has the card instead of retrying into a stall.
* Every result carries the §4.5 summary shape, and separates **reclaimed** from **relocated** (§4.5).
* Registration must move from `~/.config/opencode/opencode.json` on this box into machine-setup
  (`45-agent-configs.sh` manages that file) so the other machines get the same surface — §16, defect 8.
* Descriptions state paths that exist: `/mnt/media/{movies,series,videos,other}`.
  `machine-setup/shared/agents/encode_tools.py:25` still defaults `/srv/media/Movies` — defect 3, still live.

## 11. CLI

`lario-media` is a thin wrapper over `media/run.py` (§3.2). It is the operator-facing surface, and it
takes locations at prompt time — which is the whole point of the driver existing:

```
lario-media photos merge  --src PATH…(N) --dest DIR [--apply] [--delete-sources]
                          [--live-clips=quarantine|strip|delete] [--heic=keep] [--neardups=report|off]
lario-media docs read     --src PATH…(N) --dest DIR [--apply] [--langs auto]
                          [--original=keep|drop] [--engine=witness|vl|both] [--redoc]
lario-media music merge   --src PATH…(N) --dest DIR [--apply] [--fingerprint=off|on]
lario-media video encode  --src PATH…(N) --dest DIR [--apply] [--limit N] [--qp N]
lario-media library tidy  PASSES… [--apply] [--undo] [--prune-empty]
                          # tidy_library.py verbatim: positionals name the passes, `--undo` is a flag that
                          # replays those, and there are no path arguments — tidy's roots are config-derived
                          # (§3.3), so consolidating a *new* location is a different task, not this one
lario-media audio status|catalog|refresh|start|cancel
lario-media report RUN_ID [--json] | lario-media status
```

* **`--dest` is exactly one path.** More than one is a usage error (exit 2), not a loop: consolidating
  into a second destination later is a separate run with its own ledger.
* **No `--apply` means nothing is written except the plan and the evidence directory.**
* `--delete-sources` is never implied by anything else (§4.3.3).
* Exit codes: `0` ok · `1` failure (needs a human) · `2` usage/plan error · `3` **all work refused**
  (lock held, drift, missing prerequisite such as tessdata) · `4` aborted by signal, ledger resumable.
  Every invocation writes a run record, including refusals.
* `lario-media` is installed as `python3 media/run.py` — no new packaging, no venv on the path, and
  nothing import-time is added to the corpora.

## 12. Environment

No passwordless sudo, so everything is user-local and pinned:

```sh
uv venv media/.venv                       # python 3.12
uv pip install --python media/.venv/bin/python \
   mutagen==1.48.1 pillow-heif imagehash
# optional, only if §13.4 shows tesseract underperforming:
#   rapidocr-onnxruntime onnxruntime
```

* `mutagen==1.48.1` — the exact version the last music run used, pinned so tag behaviour does not change
  under us. The venv that held it (`~/music-reorganize/.venv`) was deleted with the directory, so this is a
  **restore**, not an addition, and until it lands every `media/music/` pass is dead code (§19.10).
* `pillow-heif` is optional at import: **HEIC stays as-is** (owner's decision, §17) and only needs
  reading for dimensions, which `exiftool`/`heif-info` already give.
* `core/` imports **stdlib only**, so an inventory can never fail because a wheel is missing (§3).
* `export TESSDATA_PREFIX=$HOME/.local/share/tessdata` in `media/env.sh`, sourced by the runner and by
  the MCP service, together with `PATH` for the venv (§6.4).

**Ignore rules: already solved, with one exception to add.** The repo root already ignores `__pycache__/`
and `*.pyc`, and every domain carries its own evidence ignore (`*.jsonl *.csv *.tsv *.pkl *.log *.bak*
*.prev`) written with the move — *"regenerable, several are tens of megabytes, and none of it is source."*
Per-run evidence goes to `<dest>/_mediatool/<run_id>/`, outside the repo entirely (§3.2.3), so nothing new
needs ignoring.

The one place the existing rule is **wrong for us** is the golden evidence (§13.3): `*.jsonl` and `*.csv`
would silently swallow `media/_attic/2026-10-recovered/**`, which is the only copy of the recovered
scripts *and* of the verdicts they must reproduce. So the exception, not the rule:

```gitignore
# the recovered corpus and its golden evidence are source: they are the only copy
!media/_attic/**
```

Prove it before Phase A commits: `git check-ignore -v media/_attic/2026-10-recovered/` reports nothing,
and `git add -- media/_attic/ && git status --porcelain -- media/_attic/` lists the JSONL files instead of
silently skipping them.

## 13. Testing

### 13.1 Levels

* **Unit** — every `core/` module offline: `gate` (paths, one-dest, nesting, exFAT), `digest`, `names`
  (collision + escape), `fsx` (reflink→copy fallback, free-space reservation, name sanitising), `ledger`,
  `plan`, `report`, `lock`.
* **Golden** — the ported rules must reproduce the archived verdicts (§13.3).
* **Property** — `names.py`: no input string (empty, unicode, `../`, 300 chars, `:`/`*`/`?`, `CON`,
  trailing dot, RTL Arabic/Urdu) produces a path outside the root or an unrepresentable exFAT name.
  `ledger.py`: replaying a run is a no-op; every `delete` row has a surviving `keep`.
* **Destructive-safety** (`tests/test_destructive_safety.py`) — the tests that matter most:
  1. `fsx.remove()` on a path with no authorising `done` row **raises**;
  2. `--apply` against a plan whose source digest changed **refuses** and re-plans;
  3. `--dest` inside `--src` (and reverse) refuses without `--allow-nested <reason>`;
  4. a recompress that would grow a file is rejected by the gate, not by the caller's memory;
  5. `purge-quarantine` aborts when the tree holds one stranger file, and lists it;
  6. a demoted still that still reports `ContentIdentifier` **fails the run**;
  7. the `docs` pass refuses to start while the pass lock is held by `encode`;
  8. no domain module imports `shutil.rmtree` or `os.remove` (import-lint grep) — deletion goes through
     `fsx` only.
* **Integration on a fixture tree**, never on a live library: build a synthetic 200-file tree (dupes,
  Live Photo pairs by UUID and stem-only decoys, RAW, oversized JPEG, 3 conversations × 12 screenshots
  with real overlap, one Urdu thread, one paper photo), run plan → apply → verify, assert the summary's
  numbers equal the fixture's ground truth exactly.

### 13.2 Fixtures

`media/tests/fixtures/` holds **synthetic trees only**, generated by `media/tests/make_fixtures.py`
from a seeded script so they are reproducible and reviewable as text. Real families' photos, real
message text and real documents are never copied into the repo: every fixture name, date, contact name
and message is invented. A fixture is described by a `truth.json` next to it (expected dupes, expected
dates, expected order, expected transcript) so assertions compare against ground truth, not against
whatever the code happened to produce last time.

### 13.3 Golden evidence from the last real runs

> **Verified 2026-10-14: this evidence no longer exists.** The per-domain ignore (`*.json *.jsonl *.csv
> *.tsv *.pkl *.log *.bak* *.prev`) kept all of it out of version control, and the move **deleted the
> directories it lived in**. `~/music-reorganize` (1 069 files, incl. every `mini-*.jsonl` verdict and the
> mutagen `.venv`), `~/photos-reorg-work` (242, incl. the six CSV manifests, `REPORT.md` and
> `import-plan.json`) and `~/video-reorganize` (40) are gone, and `/home/lario` is a plain btrfs subvolume
> with no snapper config for `/home` — there is no snapshot to walk back to. `media/tools/tidy-library.jsonl`,
> written after the move, is now the only run evidence on this box.
>
> So the **golden test level is not available for the ports**. Do not plan against it, and do not quietly
> pretend a re-run reproduces it. What replaces it, in order of strength:
>
> 1. **Invariants, not outputs.** `media/photos/verify_final.py` is committed, and its zero-violation
>    conditions (no manifest row pointing at a missing file, no two rows claiming one file, no library file
>    unaccounted for) are a stronger check than a diff against one historical run. Ported as-is, asserted on
>    every run, fixture or real.
> 2. **The numbers recorded in this plan** (§19): 12 264 → 8 941 files, 77.05 → 34.94 GB, 2 Live Photo
>    stills, the 4 LaCie tag-match/audio-mismatch files, 48 voice memos, the 0.80 / 0.50 arbiter
>    thresholds. Recorded from the reports before they went, they are the envelope a fixture run must land in.
> 3. **Verdicts quoted inside OpenCode session `ses_ede7e3a00ffeXnA7KUTRL2ATe2`** — where a message quoted a
>    verdict line, that line is recoverable and worth harvesting as a small labelled fixture corpus
>    (Phase A2). Verdicts the scripts wrote at runtime that nobody quoted are unrecoverable.
> 4. **The libraries themselves.** `~/Pictures/Photos` and `/mnt/xfs/music` are the output of those passes
>    and still on disk; a fixture derived from a subtree of them plus its `INDEX.txt` is real evidence that
>    can be regenerated read-only at any time (§15).

What follows is the list of what was lost, kept as the definition of what a future golden set would have to
reconstruct if it is ever to exist again:

| Evidence | Proves |
|---|---|
| `mini-verdict-final.jsonl`, `mini-verdicts.json` | the identity/arbiter decisions the ported `music/identity.py` must reproduce |
| `mini-proof.jsonl`, `mini-byte-dupes.json` | exact-duplicate and payload-comparison verdicts, including the 4 LaCie "tags match, audio differs" cases |
| `mini-meta.jsonl`, `mini-shape.jsonl`, `mini-cov*.json` | metadata extraction and the coverage calibration behind the audio comparison |
| `feats-cache.pkl`, `fullenv-cache.pkl` | the feature/environment caches — regenerable, kept so the reproduction is byte-for-byte |
| `photos-reorg-work/*.csv` manifests + `verify_final.py` invariants | the photo layout/date/dedupe expectations and the zero-violation invariant set (§5) |

A port is not done when it runs; it is done when it reproduces these verdicts on these inputs.

### 13.4 The WhatsApp fixture (build this first — it defines "done" for the docs pass)

Synthetic screenshots rendered with PIL from a known script: known speaker order, known timestamps,
known **overlapping ranges** (screen *n+1* repeats the last 3 messages of screen *n*), one re-taken
identical screen, one out-of-order filename, one Arabic and one Urdu thread, one date separator. The
expected transcript and expected order are checked in as data, so ordering and merge correctness are
**measurable**, not eyeballed — including the case that matters: **filenames in the wrong order but
timestamps in the right one**.

### 13.5 How to run

```sh
cd /home/lario/Projects/personal/lario-llms
media/.venv/bin/python -m pytest media/tests tests/test_audiolib.py -q     # offline, no GPU
media/.venv/bin/python -m pytest media/tests -q -m docs_gpu                # needs ocr role resident
```

`tests/test_audiolib.py` stays green throughout — it is the regression fence around the code we adopt.

---

## 14. Phases, with commit boundaries

Standing rules for every phase: commit with **explicit pathspecs** (`git add -- <files>`) — `lario-llms`
and `machine-setup` carry other sessions' dirty files; **never** stage/reset/clean/stash broadly.
`hermes/<agent>` and `shared/` are gitlinks (mode 160000): `git commit -- <path>` there fails with
"pathspec … did not match". zsh does not word-split unquoted vars — write literal paths. Publish before
pinning; **no force-push**. RAG publication is a separate, verified step (§16).

| Phase | Deliverable | Verification | Commit boundary |
|---|---|---|---|
| **0. Hygiene** | commit the encoder rewrite already on disk | `bash -n runner.sh`, `python -m py_compile controller.py`, job dry-run listing shows recursive scan | `lario-llms` pathspec `rtx5080/encoder/controller.py rtx5080/encoder/runner.sh`; then `machine-setup` pathspec `shared/agents/encode_tools.py` (description fix) |
| **0b. Plan into repo** | *done 2026-10-14*, amended same day | — | `lario-llms pathspec media/PLAN.md` |
| **0c. Re-point the roots** | *done 2026-10-16 (`fd95797`)*: `core/config.py` `VIDEO_LIB` → `/mnt/media/videos`; **every command now reads its root instead of spelling one out** — 36 photo files on `from paths import W`, 18 music files / 46 artifact sites including both audio caches on `paths.WORK`, writers create the root they are given; `media/README.md:12,13,42` pointers corrected; the MCP's `music_import` reason no longer claims a dry run does not exist | **nothing executed** (an encode held the GPU): `compileall media/` clean, an AST pass proves every `W`/`WORK` is bound in all 54 files and every `os.makedirs` preceded by `import os`, zero literal roots outside `oneoff/` | pathspecs `media/photos media/music media/core/config.py media/tools/media_tools.py`, docs as a second commit |
| **0c′. Evidence under the destination** *(the remainder of 0c)* | the work-root **defaults** (`PHOTO_WORK`/`VIDEO_WORK`/`MUSIC_WORK`, `MANIFEST`, `META`) resolve under the destination instead of `$HOME` (§4.3.4, defect 13); `PHOTO_PLAN` to a real path, its deleted hand-edited predecessor stated in the docstring; `mutagen==1.48.1` into `media/.venv` | `python3 media/run.py status` (needs B) resolves every root and reports which exist; `pytest media/tests -q` green; no config value resolves into a nonexistent `$HOME` path once the run names its destination | one commit: `media/core/config.py` (+ the dep, §12) |
| **A1. Recover the modules** | untruncated dump of `ses_ede7e3a00ffeXnA7KUTRL2ATe2` → `media/_attic/2026-10-recovered/`: `build.py` `plan.py` `meta.py` `repair.py` `audit.py` `tagfill.py` `tagrestore.py` `place_art.py` `integrity.py` `navidrome_migrate.py` `lacie_*.py`. The `mini_*` corpus is already committed (`e662740`); **there is no evidence left to copy** | every recovered file `py_compile`s; a manifest records what the session did *not* contain, so nobody later mistakes the gap for an unfinished task | one commit: `media/_attic/**` with the §12 negation in the same commit, so the recovered files cannot be silently ignored |
| **A2. Harvest what the session quotes** | scan the same session for **quoted** verdict lines, manifest rows and report tables; each becomes a labelled fixture under `media/tests/fixtures/recovered/` citing its message id | every fixture is a real recorded output with provenance, not a re-run; §13.3's envelope numbers are covered | one commit: `media/tests/fixtures/**` |
| **B. Driver + core** | `media/core/{gate,ledger,report}.py` + `media/run.py` (§3.2): N `--src`, one `--dest`, env-seam redirection, evidence indexing, summary. **No domain module imported; `core/` deletes nothing** | `tests/test_run.py` green on a temp tree: one dest root maps to `photos/` + `videos/` subtrees; nesting refused; two runs get two evidence dirs; safety tests 1–3 and 8 pass | one commit, `media/core/** media/run.py media/tests/**` |
| **C. Photos** *(owner's priority: recover + engine + **photos** first)* | full photos pipeline incl. §5.1 Live Photos + `purge-quarantine` | fixture run matches ground truth exactly; `photos/verify.py` invariants all zero | `photos/livephotos.py`, `photos/purge_quarantine.py` and the `plan_import.py` `ROOTS` change (§3.4.1) as three separate commits, the last with today's two-source behaviour unchanged when `LARIO_SRC_DIRS` is unset |
| **B2. GPU readiness** | `runner.sh` recursive scan + quarantine exclusion; `read_intervals` quoting fix; SAR/DAR/cropdetect + whole-file decode gates; `ocr` profile 65 536 + `--mtmd-batch-max-tokens` probe; `encode`/`docs` entries in the `rtx5080` menu; role arbitration in `modelctl` | probe numbers recorded in the commit message; `model_options(rtx5080)` lists the roles; role refusal names the holder | `rtx5080/encoder/**`, `rtx5080/models.json`, `shared/modelctl.py`, `shared/agents/*_tools.py` — separate commits per concern |
| **D. Docs** | tessdata installed; `media/docs/*`; ordering solver + witness gate + two-file output | fixture transcript equals expected order **and** text; a VLM-only claim with no witness support comes out `[?]`; header says "single-engine OCR, unverified" while tessdata is missing | `media/docs/** media/tests/test_docs_*.py`; tessdata note in `media/README.md` |
| **E. Music** | `media/music/*` ported from the report + `mini_*`; `--fingerprint=off` default | golden verdicts reproduced; the "tags match, audio differs" fixture is **not** merged | `media/music/** media/tests/test_music.py` |
| **F. Audio adapter + video wrap** | `media/audio/adapter.py` over `media/audiolib` (audiolib untouched); `media/video/*` delegating to `rtx5080/encoder` | `tests/test_audiolib.py` still green; `video encode` plan on a small `--limit` reports `SKIPCODEC`/`NOGAIN`/`dup_stem` correctly | two commits |
| **G. Surface + docs** | `media/cli.py`, `media/tools/media_tools.py`, vendor to `machine-setup`, register in `opencode.jsonc`, `media/README.md` | MCP `media_health`/`media_plan` from OpenCode against the fixture tree; `media_plan` output identical to CLI | `lario-llms pathspec media/cli.py media/tools/** media/README.md`; `machine-setup pathspec shared/agents/media_tools.py machines/*/config/opencode.jsonc` |
| **H. Real job** | the dad's-drives run (§15) | summary table + `verify` zero violations on the destination | **no code commit**; the ledger + report live in `_mediatool/` on the drive |
| **I. Delete this file** | `git rm media/PLAN.md` | §14's boxes all ticked | last commit, message: "Media toolkit plan complete; plan file removed" |

## 15. Runbook — dad's backup HDDs → one external drive

Two source HDDs (photos, videos, a large number of WhatsApp screenshots) → one external destination.
Run order matters: **structure first, docs alone afterwards**.

```sh
# 0. mount, identify, never write yet
lsblk -f; findmnt /mnt/dad-a /mnt/dad-b /mnt/dad-out
# exFAT destination? check it actually mounted rw and has no case clash:
python3 media/run.py photos merge --src '/mnt/dad-a/**' --src '/mnt/dad-b/**' --dest /mnt/dad-out --apply
# ^ this is PLANNER output unless --apply; read it fully before applying
```

1. **Copy nothing by hand.** Mount the sources read-only where possible; if the drive is
   unreadable-mount-ro, note it and treat every file as at-risk.
2. `photos merge … --dest /mnt/dad-out` (**no `--apply`**) → read the summary. Expect: big dupe counts
   (two backups of the same library), Live Photo pairs, RAW files, and the screenshots.
3. Check the two numbers before applying: destination free space ≥ (source unique bytes × 0.85) and the
   `failed` row count = 0. `--delete-sources` is **not** used (owner's rule): the source HDDs are the
   backup and go back on the shelf untouched.
4. `--apply`, then `verify RUN` and require zero invariant violations.
5. Run the **video** plan over what landed (`video encode --dest /mnt/dad-out` … plan only while the
   card is busy) and leave it for a scheduled `encode`-role window.
6. **Only after the tree is settled:** `docs read --src /mnt/dad-out/**/` in its own pass, with the
   `ocr` role resident and nothing else holding the card (§4.4). This is the pass that turns thousands
   of WhatsApp screenshots into per-thread transcripts + summaries **inside** their folders.
7. Deliver: the destination tree, the report JSONs, `_docs/unresolved.jsonl` (the things to look at),
   `live-photos-for-deletion/` with its `README-delete-me.txt`, and the free-space numbers.

Destination gotchas that bite on external drives: **exFAT has no symlinks, no reflink, is
case-insensitive, forbids `:` `*` `?` `"` `|` `<` `>` and Windows device names, and truncates past 255
UTF-16 chars** — `core/fsx.py` sanitises and `names.py` proves it in a property test (§13.1), because a
name that survives on XFS can be unwriteable on exFAT.

## 16. Fleet: mesh sync and RAG

* After each `machine-setup` push, bring the other boxes up to date (`mesh-repo-sync`). Current known
  state: `machine-setup main = ec9bc43`; `l-dev-ai` (dirty 2) and `cachyos-mini-mobile` are both still on
  the retired `fix/retained-qwen-client-contexts-20261006 @ 8cc8364` and need fast-forwarding. The
  retired `media` host is out of the host lists.
* `lario-llms` work lands on `fix/retained-gpu-contexts-and-guides-20261006`; publish (push) **before**
  any deployment pin moves, then pin by exact hash and verify the checkout is clean at that hash.
* **RAG publication is a separate verified step** — code commit, then publish, then confirm retrievable.
* Owner actions that remain (no passwordless sudo): recreate `dnsmasq` (`docker compose up -d
  --force-recreate dnsmasq`), re-run `15-network.sh` per box (`lario.media 192.168.10.242` is still in
  the managed `/etc/hosts` block), re-run `setup-mesh-ssh.sh`, and `ssh-keygen -R` the three dead names.

## 17. Decisions

**Resolved by the owner (2026-10-13)**

1. Build order: **recover + engine + photos first**.
2. **Always keep sources.** Space reclaim is a separate explicit `--delete-sources` pass.
3. **HEIC stays as-is** (no conversion).
4. **Fingerprinting off by default**, on per request.
5. Live Photo clips: quarantine to `live-photos-for-deletion/YYYY/YYYY-MM-DD <Event>/`, deletable
   afterwards by a separate gated verb — *"rename it to be clearer, then we can go ahead and delete them after."*
6. OCR uses the **dedicated RTX image model (`ocr`)**, never `qwen3.8`; non-English text is OCR'd in its
   own language and translated by the **Intel** service **before** transcription.
7. Transcription/translation is a **separate pass**, never concurrent with encoding or compression.

**Adopted by the assistant (reversible, listed so they are visible)**

1. Package lives at `lario-llms/media/`, with `media/audiolib/` adopted unchanged as the reference shape.
2. Near-duplicate bursts are **report-only** (no automatic merges).
3. `encode`-with-`docs` co-residency is gated on a measured throughput probe (§9.3), not assumed.
4. The audiobook downloader folds into the same CLI surface as an adapter, not a rewrite.
5. Transcripts keep the original beneath the English translation (`--original=keep`).
6. Pairing Live Photos **only** on the `ContentIdentifier` UUID, filename stem as a flagged fallback
   (`confidence: filename`).
7. No second vision-*LLM*; the escalation ladder is §6.5.
8. **The architecture fork is resolved in favour of the corpus's rule** — commands are run, not imported;
   the surface composes passes as argv processes (§3). The import guardrail is not traded away.
9. **Prompt-time locations go through `core/config.py`'s env seam**, plus the two location patches named in
   §3.4 — `plan_import.py`'s `ROOTS` (§3.4.1) and the driver-side `--src-file` lists for `enc_hevc.py`
   (§3.4.3) — not through rewrites that give every pass its own argument parser.
10. **`--dest` is one path, mapped to conventional subtrees** (`<dest>/photos`, `<dest>/videos`,
    `<dest>/music`), because the photo pass files photos and videos into two libraries by design: one
    location at the prompt, correct shape on disk.
11. **Paths enter the MCP only through `media_plan`; `media_apply` takes a `run_id`**, so a plan cannot be
    steered somewhere else between review and write (§10).

**Open (needs the owner)**

1. Do the source HDDs get wiped after verification, or stay as the backup? (§15.3 assumes stay.)
2. One destination drive — how large, and does it also hold the *encoded* videos or only the originals?
3. Immich as the photo front-end, or keep the plain directory tree? (Affects whether `photos` optimises
   for a database import, §1.2.)
4. Whether `music` re-runs against the live `/mnt/xfs/music` library or only new incoming material.

## 18. Risks

1. **No backup exists for the photo/video libraries** — deliberately (the originals backup and 33 GB
   snapshot were deleted, per `photos-reorg-work/REPORT.md`). The toolkit's §4.3 rules *are* the safety
   story. Any phase that weakens them to go faster is a regression, not an optimisation.
2. **Other live sessions touch the same ground** — a video re-encode session (`/mnt/media/un2`,
   `video-reorganize/`) and the audiobook session, both in `lario-llms`. Hence pathspec commits, and no
   GPU work while another session holds an encode.
3. **Tessdata is missing `eng` today** (§6.4): until installed, docs output must be labelled
   "single-engine OCR, unverified". Shipping an unlabelled single-engine transcript is the worst
   failure mode available in this domain.
4. **Role work touches `modelctl`, which serves live chat.** A mistake evicts the owner's model
   mid-conversation. Hence: fresh `switch_token`, probe before enabling co-residency, never exercise
   roles while an encode holds the card.
5. **OCR hallucination** (§6.2 step 7) — mitigated structurally (witness support required, `[?]` for
   unsupported spans, verification ratio published, summaries cite transcript lines).
6. **Ordering ambiguity is real** (§6.3): an unresolved link must stay unresolved and be reported. A
   confidently wrong transcript of dad's messages is worse than a flagged gap.
7. **exFAT name/case semantics** (§15) — proven by property test before touching a real drive.
8. **The 2026-10-14 move destroyed the evidence of the 2026 passes, and it can happen again to anything
   that is not in git.** `~/photos-reorg-work`, `~/music-reorganize` and `~/video-reorganize` were deleted
   on the way into the repo. What they held that was *not* source — run manifests, the `mini-*.jsonl`
   verdicts, `REPORT.md`, `import-plan.json`, the music `_ORGANIZE_REPORT.txt`, the mutagen venv — has no
   second copy and no snapshot. The libraries are intact (`~/Pictures/Photos`, `/mnt/xfs/music`), so this is
   a loss of *proof* rather than of data; but a toolkit whose entire argument is "we verified before we
   deleted" cannot afford a second loss of proof. Mitigations: §4.3.4 (evidence lives with the destination,
   never in `$HOME` scratch), §13.3 (invariants and recorded envelopes instead of golden diffs), Phase 0c
   (stop `core/config.py` resolving into `$HOME` at all). Standing rule for anyone reorganising this repo:
   **`git ls-files` is not a backup of a directory you are about to delete — diff the directory's file list
   against it first, and move what it does not cover.**
9. **Two audit trails disagreeing** (§4.2) — mitigated by the ledger being an index over the passes' own
   evidence, the pass's record winning, and the run reported failed on divergence.
10. **`lario_media` is registered only on this box** — `~/.config/opencode/opencode.json`, which
    machine-setup manages via `machines/bigcachy/steps/45-agent-configs.sh` but has no entry for. No other
    machine has the surface, and one config rebuild loses it (§16, defect 4).

## 19. Appendix — numbers to reproduce, defects to fix

| Fact | Value | Source |
|---|---|---|
| Photo pass, 2026-10-10 | 12 264 → 8 941 files, 77.05 → 34.94 GB, **54.6 %** | `photos-reorg-work/REPORT.md` — **deleted 2026-10-14**; these recorded numbers are the record now |
| Live Photo stills left in `~/Pictures/Photos` | 2 | same (re-countable: the tree is intact) |
| Islam audiobook library | 43 GB / 8 collections on disk; catalog 3 297 files, 46.01 GB | `/mnt/media/audiobooks/islam`, `media/audiolib/catalog.json` |
| Audiobook re-encode value | 1.9 % (strip art/chapters); library is AAC-LC 32 kHz mono ~63 kbps, ~1 550 h | `media/audiolib/README.md` |
| pCloud throughput | ~8–9 MiB/s at 4 **and** 6 workers; whole library ≈ 80 min | same |
| Encoder false failures | **29** in job `20261010-084227-b9b9`, `Error parsing read interval #0 '5915+%60'` | encoder manifest; fix §9.1 |
| GPU | RTX 5080, 16 303 MiB, `mig.mode.current [N/A]`; `ocr` ≈ 9.5 GiB @32k, ≈ 11.8 GiB @65k | §6.5, §9.2 |
| Vision tokens | ~1 token / 32×32 px ⇒ 8192 ≈ 8.4 Mpx; 1080×2400 ≈ 2.5k, 1170×2532 ≈ 2.9k | §6.5 |
| Music repair rule | copy → tag → re-read and verify → replace; audio-payload match required (caught 4 LaCie files with matching tags, mismatched audio) | `/mnt/xfs/music/_ORGANIZE_REPORT.txt`, `mini_cov*.py` |
| Music escape hatches | 48 voice memos → `preserved-lacie/lacie-voice-memos/`; 1 undecodable → `preserved-lacie/lacie-unreadable/` | same |

**Defect list**

1. `runner.sh:270` `-maxdepth 2` → recursive at any depth, excluding `live-photos-for-deletion/`.
2. `read_intervals` quoting (29 false `FAIL`s).
3. `encode_tools.py:23,25` advertises `lario-media` / `/srv/media/Movies` (retired) →
   `/mnt/media/{movies,series,videos,other}`.
4. `lario_media` is registered only in `~/.config/opencode/opencode.json` on this box, not in
   machine-setup (`45-agent-configs.sh`) — unreproducible on every other machine (§18.10).
5. ~~no rules for `media/` runtime state~~ **resolved by the move** (root ignores `__pycache__`/`*.pyc`,
   per-domain evidence ignores exist). The defect is now the opposite one: those ignores swallow
   `media/_attic/**`, which must be committed — add the §12 negation and prove it with `git check-ignore`.
6. `tesseract`: `eng`/`urd`/`arb`/`hin` traineddata absent (`~/.local/share/tessdata` + `TESSDATA_PREFIX`).
7. Audiobookshelf Islam library: `lastScan: null`, 0 items → rescan in the UI (§8.2).
8. `metadata=print` log level misuse in the ad-hoc probe that became `media/video/audit_windows.py` —
   already fixed in-tree (README: the summary is logged at `info`, only frames at `debug`).
9. ~~`core/config.py` resolves into paths that do not exist~~ **resolved 2026-10-16 (`fd95797`)** — what
   changed and what that fix deliberately left out is recorded once, in §3.4. The leftover is its own defect,
   13.
10. **`mutagen` is no longer importable anywhere** — the only install was `~/music-reorganize/.venv`,
    deleted with it (system python is 3.14.7, no mutagen). Nothing in `media/music/` runs until
    `mutagen==1.48.1` lands in `media/.venv` (§12).
11. `media/music/README.md` does not exist: the `_ORGANIZE_REPORT.txt` that held the rules is gone. §7 of this
    plan is still the primary written **policy**; the command surface — every music script, its flags, its
    env seam, which ones dry-run by default — is in `media/GUIDE.md` §5 (`0e43d03`), which points back here.
    So §7 must be kept in sync with `media/music/mini_*.py`; the guide is generated-looking but hand-written
    and drifts the same way.
12. `/mnt/xfs/photos-originals-backup` (`PHOTO_BACKUP`, `config.py:60`) **does not exist** — deliberately
    deleted, and §4's "no backup exists" premise depends on it. Nothing may be written assuming a net there.
13. **The work-root defaults still name the three deleted 2026 directories** (the residual of 9). Every
    command now *reads* its root, so this is only about the fallback: run one without `W=` or
    `LARIO_MUSIC_WORK=` and it quietly makes a fresh empty root rather than failing. Phase 0c′ defaults them
    under the destination (§4.3.4). `PHOTO_PLAN` (the 4 093-record `import-plan.json`), `MANIFEST` and `META`
    are gone with those directories and only regenerate. `media/README.md`'s live-plan pointer is corrected;
    its `:12,13` are the `was` column — history, not a path to use.

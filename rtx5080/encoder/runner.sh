#!/usr/bin/env bash
# Encoder job runner — owned by lario-llms/rtx5080/encoder/controller.py.
#
# Per movie, in this gate order (each one is a reason to leave the source
# exactly as it is, and each is remembered in the manifest so the next run does
# not pay for it again):
#   1. dup_stem   -- an existing Title.mkv would be clobbered by the commit
#   2. SKIPCODEC  -- already hevc/av1/vvc: the same codec one generation worse
#   3. SKIPSIZE   -- already inside the output budget, decided WITHOUT encoding
#   4. encode     -- NVDEC -> hevc_nvenc -> temp on /mnt/xfs (NVMe, so reading
#                    the source and writing the encode do not fight over the
#                    same disk head) at a ladder rung chosen from the overshoot;
#                    verify the temp (size, duration vs source, decode
#                    head+tail, container); OVERBUDGET or LOWGAIN at a rung drops
#                    the encode and steps the rung coarser, MAX_RUNG_STEPS times
#   5. OVERSIZE   -- no rung reached the budget: encode discarded, source kept
#   6. NOGAIN     -- rungs fit the budget but none saved MIN_GAIN_PCT: an encode
#                    that saves nothing is only generation loss
#   7. promote    -- to $DIR/<stem>.mkv.shipping beside the source and re-verify
#                    there (size, duration, sha256) -- cross-filesystem, hash it
#   8. commit     -- delete the source, rename .shipping into place; keep the
#                    mirror on $XFS_DIR only while free space >= floor + 64
#
# Nothing in steps 1-6 touches the source, and steps 3, 5 and 6 mean a title that
# cannot be made smaller without cost is never made worse instead. A rung that
# misses either gate is retried coarser rather than deciding the title on its
# first attempt: the budget and the gain floor have to be satisfiable together.
#
# Output budget (library spec, LARIO_ENC_BUDGET_*): 1080p <= 3.0 GB/h,
# 1440p <= 4.5, 2160p <= 8.0. Decimal GB. A height at or below 1080 lines
# inherits the 1080p ceiling rather than getting a looser one of its own.
#
# Source and library are on THIS box since 2026-10-13. They used to live on
# lario-media and every byte of this file went through ssh; that box is retired
# and the library is on /mnt/media (bigcachy), which is also the box holding the
# RTX card — so the transport, the remote probe (/usr/lib/jellyfin-ffmpeg on the
# iMac) and the "ship to media box" step all went away with it. Nothing here
# talks to another host any more.
#
# While LIMIT=0 (full library) the chat service was drained+stopped by the
# controller; this runner restores it via teardown.py at the end (or on signal).
# With LIMIT>0 (bounded test) the chat service stays untouched and the source
# is never deleted; controller.status settles the job.
#
# Env (set by controller.py): LARIO_ENC_SVC, LARIO_ENC_ROOT, LARIO_ENC_CQ (23),
#   LARIO_ENC_LIMIT (0=all), LARIO_ENC_LOG_DIR, LARIO_ENC_XFS_DIR (empty
#   disables mirroring), LARIO_ENC_FLOOR (50), LARIO_ENC_STATE (state json),
#   LARIO_ENC_BUDGET_1080 (3.0) / _1440 (4.5) / _2160 (8.0) in GB/h, and
#   LARIO_ENC_SKIP_DIRS (colon list) added to the scan's prune set.
#   LARIO_ENC_MEDIA_HOST is accepted but ignored -- it is what the old ssh
#   transport used, and there is no other host to talk to.
set -uo pipefail

SVC=${LARIO_ENC_SVC:-rtx5080.service}
SRC_ROOT=${LARIO_ENC_ROOT:-/mnt/media/movies}
XFS_DIR=${LARIO_ENC_XFS_DIR-/mnt/xfs/videos/movies}
LOG_DIR=${LARIO_ENC_LOG_DIR:-/mnt/media/movies/.encode-logs}
RUN_LOG=$LOG_DIR/run.log
MANIFEST=$LOG_DIR/manifest.tsv
STATE=${LARIO_ENC_STATE:-}
FFMPEG=/usr/bin/ffmpeg
FFPROBE=/usr/bin/ffprobe
HERE=$(cd "$(dirname "$0")" && pwd)
REPO_DIR=$(cd "$HERE/../.." && pwd)
TMP_DIR=${XFS_DIR:-/mnt/xfs/videos/movies}/.encode-tmp

CQ=${LARIO_ENC_CQ:-23}
XFS_MIN_FREE_GB=${LARIO_ENC_FLOOR:-50}
XFS_MARGIN_GB=10
LIMIT=${LARIO_ENC_LIMIT:-0}
MIN_OUT_MB=80
# Encode where it helps: an already-modern source is the same codec one
# generation worse. Mirrors the library policy in /mnt/media/_ORGANIZE_REPORT.txt.
MODERN_CODECS='hevc|av1|vvc'
MIN_GAIN_PCT=15
# Output budget in GB/h per height class (decimal GB). See the header: the check
# runs before the encode, and a title still over budget after every rung is
# left alone rather than squeezed past the point of diminishing returns.
BUDGET_1080=${LARIO_ENC_BUDGET_1080:-3.0}
BUDGET_1440=${LARIO_ENC_BUDGET_1440:-4.5}
BUDGET_2160=${LARIO_ENC_BUDGET_2160:-8.0}
CQ_MAX=30                  # the top of the ladder this controller advertises
CQ_STEP=2                  # coarser per rung
MAX_RUNG_STEPS=2           # so at most three encodes per title, worst case
# Trees never encoded. Names only, matched at any depth: the colon list from
# the environment is appended. The staging tree's deletion queue is full of
# second-rate video that must never be an encode candidate, and _mediatool is
# where a toolkit run keeps its evidence.
SKIP_NAMES='live-photos-for-deletion|_live_photos|_mediatool'
[ -n "${LARIO_ENC_SKIP_DIRS:-}" ] && SKIP_NAMES="$SKIP_NAMES|${LARIO_ENC_SKIP_DIRS//:/|}"

mkdir -p "${XFS_DIR:-/mnt/xfs/videos/movies}" "$LOG_DIR" "$TMP_DIR"
touch "$MANIFEST" "$RUN_LOG"
rm -f "$LOG_DIR/job.done"

# Hold the shared RTX hardware lock (same file as the image controller) for the whole job.
exec 9>"$REPO_DIR/.rtx5080.lock"
flock -n 9 || { echo "$(date '+%F %T') FATAL lock held by another exclusive RTX job" | tee -a "$RUN_LOG"; exit 75; }

state_set() {  # state_set KEY VALUE — merge one field into the job state file
    [ -n "$STATE" ] && [ -f "$STATE" ] || return 0
    python3 - "$STATE" "$1" "$2" <<'PY' || true
import json, sys
path, key, value = sys.argv[1], sys.argv[2], sys.argv[3]
try:
    job = json.load(open(path))
except Exception:
    job = {}
if value == 'true':
    value = True
elif value == 'false':
    value = False
elif value.lstrip('-').isdigit():
    value = int(value)
job[key] = value
json.dump(job, open(path, 'w'), indent=1)
PY
}

progress() {  # progress CURRENT DONE TOTAL
    printf '{"current": "%s", "done": %s, "total": %s, "mirror_enabled": %s, "ts": "%s"}\n' \
        "$1" "$2" "$3" "$([ -n "$XFS_DIR" ] && echo true || echo false)" "$(date '+%F %T')" > "$LOG_DIR/progress.json"
}

log() { echo "$(date '+%F %T') $*" | tee -a "$RUN_LOG"; }

FULL=yes
[ "$LIMIT" -gt 0 ] && FULL=no
RESTORED=no
finish() {  # restore chat exactly once for full-library jobs (trap + normal end)
    local code=$?
    [ "$FULL" = yes ] && [ "$RESTORED" = no ] || return 0
    RESTORED=yes
    state_set state restoring
    state_set restore_pending true
    log "restoring chat service ($SVC) — do not interrupt"
    if python3 "$HERE/teardown.py" "$STATE" >>"$LOG_DIR/restore.log" 2>&1 || \
       python3 "$HERE/teardown.py" "$STATE" >>"$LOG_DIR/restore.log" 2>&1; then
        state_set restore_pending false
        state_set state ended
        log "chat restored (service active: $(systemctl --user is-active "$SVC" 2>/dev/null))"
    else
        log "CHAT RESTORE FAILED — controller.encode_status will repair; manual: systemctl --user start $SVC"
    fi
    return $code
}
trap finish EXIT
trap 'log "TERMINATED by signal"; state_set cancel_note "signalled"; exit 143' TERM INT HUP

dur_s() { $FFPROBE -v error -show_entries format=duration -of csv=p=0 "$1" 2>/dev/null | cut -d. -f1; }
vcodec() { $FFPROBE -v error -select_streams v:0 -show_entries stream=codec_name -of csv=p=0 "$1" 2>/dev/null | head -1; }
vheight() { $FFPROBE -v error -select_streams v:0 -show_entries stream=height -of csv=p=0 "$1" 2>/dev/null | head -1; }
hms() { awk -v s="$1" 'BEGIN{printf "%02d:%02d:%02d", s/3600, (s%3600)/60, s%60}' </dev/null; }
# gbh BYTES DURATION_S -> GB/h with two decimals. Decimal GB, to match the spec.
gbh() { awk -v b="$1" -v d="$2" 'BEGIN{if (d+0 <= 0) {print "0"; exit} printf "%.2f", b/1000000000/(d/3600)}'; }
# over X Y -> success when X > Y (bash has no float comparison of its own)
over() { awk -v a="$1" -v b="$2" 'BEGIN{exit !(a+0 > b+0)}'; }
# cap_for HEIGHT -> the budget ceiling for that class. An unknown height takes
# the tightest cap rather than a loose one: guessing wrong then means leaving a
# 4K title unencoded, which is the failure this gate exists to prevent.
cap_for() {
    case "$1" in ''|*[!0-9]*) echo "$BUDGET_1080"; return ;; esac
    if   [ "$1" -ge 2160 ]; then echo "$BUDGET_2160"
    elif [ "$1" -ge 1440 ]; then echo "$BUDGET_1440"
    else                         echo "$BUDGET_1080"
    fi
}

xfs_write_ok() {
    local avail; avail=$(df --output=avail -BG "${XFS_DIR:-/mnt/xfs}" 2>/dev/null | tail -1 | tr -dc 0-9)
    # floor + 64G working-set headroom (encode temp + mirror copy)
    [ "${avail:-0}" -ge $((XFS_MIN_FREE_GB + 64)) ]
}

run_one() {
    local SRC="$1"
    case "$SRC" in
        *\'*) log "SKIP $SRC (quote in path — quoting is single-quote based)"; return 2 ;;
    esac
    local DIR STEM NAME FINAL OUT_T LFP ENC_LOG SRC_SZ SRC_DUR_S SRC_CODEC LFP_SHA
    local LSZ LDUR LERR STRUCT OSZ ODUR OSHA MIRRORED KEEP_SOURCE
    local SRC_H SRC_GBPH CAP START_CQ RUNG PRE STEP TRIED SUBCONV SUBI SUBC NOISE dd rc
    local OUT_GBPH USED_CQ LAST_FAIL=budget LAST_LSZ=0

    DIR=$(dirname "$SRC"); STEM=$(basename "$SRC"); STEM="${STEM%.*}"
    NAME="$STEM.mkv"
    FINAL="$DIR/$NAME"
    OUT_T="$DIR/$STEM.mkv.shipping"
    LFP="$TMP_DIR/$STEM.mkv"
    ENC_LOG="$LOG_DIR/${STEM}.enc.log"

    # Commit renames X.mp4 -> X.mkv, so a same-stem .mkv already sitting in the
    # folder would be overwritten and its source deleted right after. Refuse the
    # title outright rather than guess which of the two is the keeper.
    if [ "$FINAL" != "$SRC" ] && [ -e "$FINAL" ]; then
        log "SKIP $SRC (refusing to overwrite the existing $FINAL — same stem, resolve by hand)"
        printf '%s\tSKIP\tdup_stem\n' "$SRC" >> "$MANIFEST"
        return 2
    fi

    SRC_SZ=$(stat -c %s "$SRC" 2>/dev/null || echo 0)
    SRC_DUR_S=$(dur_s "$SRC")
    [ -n "$SRC_DUR_S" ] || { log "FAIL $SRC (cannot probe source)"; printf '%s\tFAIL\tprobe_source\n' "$SRC" >> "$MANIFEST"; return 1; }
    # A zero-second duration cannot be budgeted (GB/h is undefined) and no
    # duration check would catch anything downstream. Refuse rather than guess.
    [ "$SRC_DUR_S" -gt 0 ] || { log "FAIL $SRC (probes as ${SRC_DUR_S}s — nothing to budget against)"; printf '%s\tFAIL\tprobe_duration\n' "$SRC" >> "$MANIFEST"; return 1; }
    SRC_CODEC=$(vcodec "$SRC")
    # The gate that runs before anything is written: the library is mostly HEVC
    # already (68 of 75 titles as of 2026-10-13) and a commit deletes the
    # source, so re-encoding those would be unrecoverable generation loss.
    case "$SRC_CODEC" in
        $MODERN_CODECS) log "SKIPCODEC $SRC ($SRC_CODEC already modern — left alone)"
                        printf '%s\tSKIPCODEC\t%s\t%s\n' "$SRC" "$SRC_SZ" "$SRC_CODEC" >> "$MANIFEST"; return 3 ;;
    esac

    MIRRORED=no
    if [ -n "$XFS_DIR" ] && xfs_write_ok; then MIRRORED=yes; fi

    # --- the budget gate, before the GPU is touched ---
    # This is why the order matters: the old code decided "not worth it" only
    # AFTER a full encode, so every already-small title cost the GPU its entire
    # runtime to learn nothing was to be gained. Here a title inside budget
    # never reaches ffmpeg at all.
    SRC_H=$(vheight "$SRC")
    SRC_GBPH=$(gbh "$SRC_SZ" "$SRC_DUR_S")
    CAP=$(cap_for "$SRC_H")
    if ! over "$SRC_GBPH" "$CAP"; then
        log "SKIPSIZE $SRC (${SRC_H:-unknown}p at ${SRC_GBPH} GB/h is inside the ${CAP} GB/h budget — left alone)"
        printf '%s\tSKIPSIZE\t%s\t%s\t%s\t%s\n' "$SRC" "$SRC_SZ" "$SRC_DUR_S" "${SRC_H:-0}" "$SRC_GBPH" >> "$MANIFEST"
        return 3
    fi

    log "START $SRC | codec=$SRC_CODEC dur=$(hms "$SRC_DUR_S") srcsize=$(( SRC_SZ / 1000000 ))MB ${SRC_H:-unknown}p=${SRC_GBPH}GB/h cap=${CAP}GB/h mirror=$MIRRORED cq=$CQ"

    # mov_text subtitles (mp4 sources) cannot be muxed into matroska by this
    # ffmpeg build — convert only those subtitle streams to srt (per-index
    # override); PGS/DVB/etc stay bit-exact copies. Unquoted split is safe:
    # the tokens contain no spaces. Once per title: it is a property of the
    # source, not of the rung.
    SUBCONV=""; SUBI=0
    for SUBC in $(ffprobe -v error -select_streams s -show_entries stream=codec_name -of csv=p=0 "$SRC"); do
        [ "$SUBC" = "mov_text" ] && SUBCONV="$SUBCONV -c:s:$SUBI srt"
        SUBI=$(( SUBI + 1 ))
    done

    # Ladder rungs. Start coarser when the source is far over budget so the
    # common case costs one encode, then step coarser at most MAX_RUNG_STEPS
    # further: worst case three encodes for one title, and never an open-ended
    # search.
    START_CQ=$CQ
    if over "$SRC_GBPH" "$(awk -v c="$CAP" 'BEGIN{printf "%.2f", c*3}')"; then START_CQ=$(( CQ + 4 ))
    elif over "$SRC_GBPH" "$(awk -v c="$CAP" 'BEGIN{printf "%.2f", c*2}')"; then START_CQ=$(( CQ + 2 )); fi
    [ "$START_CQ" -gt "$CQ_MAX" ] && START_CQ=$CQ_MAX
    PRE=-1; STEP=0; TRIED=""
    while [ "$STEP" -le "$MAX_RUNG_STEPS" ]; do
        RUNG=$(( START_CQ + CQ_STEP * STEP )); [ "$RUNG" -gt "$CQ_MAX" ] && RUNG=$CQ_MAX
        [ "$RUNG" = "$PRE" ] && break
        TRIED="$TRIED $RUNG"; PRE=$RUNG; STEP=$(( STEP + 1 ))
    done

    # --- encode, verify, budget-check: one pass per rung ---
    # Reading the source in place. Rate control is `-rc constqp -qp N`, the true
    # constant-QP mode, chosen because a size budget needs a predictable
    # size-per-rung and VBR smoothing is exactly what a budget cannot predict.
    # Measured 2026-10-16 on this box (ffmpeg n9.0.2, hevc_nvenc, 1280x720
    # testsrc2): bare `-cq N` and `-rc vbr -cq N -b:v 0` produce byte-identical
    # files, so `-cq` was never being ignored and the vbr spelling is redundant;
    # `-rc constqp -qp N` is a different mode and smaller at the same number
    # (qp18 1.22 MB / qp28 0.49 MB against cq18 1.57 MB / cq28 0.69 MB). Audio is
    # copied and the picture is never scaled: no downscale and no audio drop
    # without an explicit flag.
    for RUNG in $TRIED; do
        rm -f "$LFP"
        $FFMPEG -hide_banner -nostdin -hwaccel cuda -hwaccel_output_format cuda \
              -i "$SRC" -map 0:v:0 -map 0:a? -map 0:s? -map_chapters 0 \
              -c:v hevc_nvenc -preset p5 -tune hq -rc constqp -qp "$RUNG" \
              -c:a copy -c:s copy $SUBCONV -y "$LFP" 2>"$ENC_LOG"
        rc=$?
        [ "$rc" = 0 ] || { log "FAIL $SRC (encode rc=$rc at qp=$RUNG — see $ENC_LOG)"; printf '%s\tFAIL\tencode_rc\n' "$SRC" >> "$MANIFEST"; rm -f "$LFP"; return 1; }

        # --- verify the temp before it is allowed anywhere near the library ---
        LSZ=$(stat -c %s "$LFP" 2>/dev/null) || { log "FAIL $SRC (temp vanished)"; printf '%s\tFAIL\ttmp_missing\n' "$SRC" >> "$MANIFEST"; return 1; }
        [ "$LSZ" -gt $(( MIN_OUT_MB * 1000000 )) ] || { log "FAIL $SRC (output implausibly small: $LSZ B)"; printf '%s\tFAIL\ttoo_small\n' "$SRC" >> "$MANIFEST"; rm -f "$LFP"; return 1; }
        LDUR=$(dur_s "$LFP")
        if [ -z "$LDUR" ]; then
            log "FAIL $SRC (local temp has no parsable duration — see $ENC_LOG)"
            printf '%s\tFAIL\tdur_local\n' "$SRC" >> "$MANIFEST"; rm -f "$LFP"; return 1
        fi
        dd=$(( SRC_DUR_S - LDUR )); [ "$dd" -lt 0 ] && dd=$(( -dd ))
        [ "$dd" -le 3 ] || { log "FAIL $SRC (duration mismatch src=${SRC_DUR_S}s out=${LDUR}s)"; printf '%s\tFAIL\tdur_mismatch\n' "$SRC" >> "$MANIFEST"; rm -f "$LFP"; return 1; }
        # Decode-window checks on the video stream only — that is what we re-encode.
        # Copied audio/subtitles inherit source quirks whose decoder strictness
        # varies across ffmpeg builds (TrueHD substream/packet errors, subtitle
        # junk); their integrity is covered by sha256 against the verified temp.
        # The null muxer also emits "non monotonically increasing dts" noise that
        # 9.x tolerates but 7.x rejects — copied audio inherits it into the
        # copy-null structure check too, so NOISE filters both passes below.
        NOISE='non monotonically increasing dts to muxer|Application provided invalid'
        LERR=$( { $FFMPEG -v error -t 60 -i "$LFP" -map 0:v:0 -f null - 2>&1; $FFMPEG -v error -sseof -60 -i "$LFP" -map 0:v:0 -f null - 2>&1; } | grep -Ev "$NOISE" | head -3 )
        [ -z "$LERR" ] || { log "FAIL $SRC (decode errors locally: $LERR)"; printf '%s\tFAIL\tdecode_local\n' "$SRC" >> "$MANIFEST"; rm -f "$LFP"; return 1; }
        STRUCT=$($FFMPEG -v error -i "$LFP" -c copy -f null - 2>&1 | grep -Ev "$NOISE" | head -3)
        [ -z "$STRUCT" ] || { log "FAIL $SRC (container structure errors: $STRUCT)"; printf '%s\tFAIL\tstruct_local\n' "$SRC" >> "$MANIFEST"; rm -f "$LFP"; return 1; }
        LFP_SHA=$(sha256sum "$LFP" | cut -d' ' -f1)
        OUT_GBPH=$(gbh "$LSZ" "$LDUR")

        # Still over budget at this rung? Throw the encode away and try coarser.
        # The source is untouched either way: this loop can only fail to improve
        # it, never make it worse.
        if over "$OUT_GBPH" "$CAP"; then
            rm -f "$LFP"
            LAST_FAIL=budget
            LAST_LSZ=$LSZ
            log "OVERBUDGET $SRC at qp=$RUNG | out=${OUT_GBPH} GB/h > ${CAP} GB/h — encode dropped, next rung"
            continue
        fi

        # --- an encode with no gain is only generation loss: refuse it ---
        # Policy from the library's own notes (>=15% smaller or keep the
        # original). But a rung is not the last word: a title only slightly over
        # budget can come under it with less than the floor's saving, and the
        # coarser rung that satisfies BOTH gates has not been tried yet. So step
        # on while rungs remain and only call this NOGAIN once none do — the
        # floor means "this encode is worthless", not "the title is hopeless".
        if [ "$LSZ" -gt $(( SRC_SZ * (100 - MIN_GAIN_PCT) / 100 )) ]; then
            rm -f "$LFP"
            LAST_FAIL=gain
            LAST_LSZ=$LSZ
            log "LOWGAIN $SRC at qp=$RUNG | src=$(( SRC_SZ / 1000000 ))MB out=$(( LSZ / 1000000 ))MB = $(awk -v a=$LSZ -v b=$SRC_SZ 'BEGIN{printf "%.0f%%", 100*a/b}') < ${MIN_GAIN_PCT}% saving — encode dropped, next rung"
            continue
        fi
        break
    done

    # No rung produced something both in budget and worth keeping. Leave the
    # source exactly as it is and say which gate is the one that stayed shut:
    # OVERSIZE (no rung reached the budget) and NOGAIN (every rung saved too
    # little) are different diagnoses even though both keep the original.
    if [ ! -f "$LFP" ]; then
        if [ "$LAST_FAIL" = gain ]; then
            log "NOGAIN $SRC | no rung of$TRIED saved ${MIN_GAIN_PCT}% (src=${SRC_GBPH} GB/h, cap=${CAP} GB/h) — original kept, every encode dropped"
            printf '%s\tNOGAIN\t%s\t%s\t%s\t%s\t%s\n' "$SRC" "$SRC_SZ" "$LAST_LSZ" "$SRC_CODEC" "$CAP" "$SRC_GBPH" >> "$MANIFEST"
        else
            log "OVERSIZE $SRC | no rung of$TRIED reached ${CAP} GB/h (src=${SRC_GBPH} GB/h) — left alone at full size"
            printf '%s\tOVERSIZE\t%s\t%s\t%s\t%s\t%s\n' "$SRC" "$SRC_SZ" "$SRC_DUR_S" "${SRC_H:-0}" "$SRC_GBPH" "$CAP" >> "$MANIFEST"
        fi
        # Unlike SKIPSIZE, which never touched the GPU, this title cost up to
        # three full encodes to decide: it has to consume a limit= slot, or a
        # bounded run would keep going until it found enough successes and burn
        # a night on hopeless titles. The verdict is sticky, so it is a once-ever
        # cost either way.
        return 0
    fi
    USED_CQ=$RUNG

    # --- promote to the library directory and re-verify the copy that lives there ---
    # Cross-filesystem (/mnt/xfs temp -> /mnt/media library), so this is a copy:
    # size, duration and sha256 are checked against the bytes that are now in
    # front of Jellyfin. The source is still untouched up to this point.
    rm -f "$OUT_T"
    mv -- "$LFP" "$OUT_T" || { log "FAIL $SRC (promote to $OUT_T failed)"; printf '%s\tFAIL\tpromote\n' "$SRC" >> "$MANIFEST"; rm -f "$LFP"; return 1; }
    OSZ=$(stat -c %s "$OUT_T" 2>/dev/null)
    [ "$OSZ" = "$LSZ" ] || { log "FAIL $SRC (promote size mismatch local=$LSZ library=$OSZ — tmp kept at $OUT_T)"; printf '%s\tFAIL\tpromote_size\t%s\t%s\n' "$SRC" "$LSZ" "$OSZ" >> "$MANIFEST"; rm -f "$LFP"; return 1; }
    ODUR=$(dur_s "$OUT_T")
    [ -n "$ODUR" ] || { log "FAIL $SRC (library temp has no parsable duration — tmp kept at $OUT_T)"; printf '%s\tFAIL\tdur_library\n' "$SRC" >> "$MANIFEST"; rm -f "$LFP"; return 1; }
    dd=$(( SRC_DUR_S - ODUR )); [ "$dd" -lt 0 ] && dd=$(( -dd ))
    [ "$dd" -le 3 ] || { log "FAIL $SRC (library duration bad: ${ODUR}s — tmp kept at $OUT_T)"; printf '%s\tFAIL\tdur_library\t%s\n' "$SRC" "$ODUR" >> "$MANIFEST"; rm -f "$LFP"; return 1; }
    OSHA=$(sha256sum "$OUT_T" | cut -d' ' -f1)
    [ -n "$OSHA" ] && [ "$OSHA" = "$LFP_SHA" ] || { log "FAIL $SRC (sha256 mismatch after promote — tmp kept at $OUT_T)"; printf '%s\tFAIL\tpromote_hash\n' "$SRC" >> "$MANIFEST"; rm -f "$LFP"; return 1; }

    # --- commit ---
    if [ "$LIMIT" -gt 0 ]; then
        # test mode: verified in place, but never delete the source
        rm -f "$OUT_T"
        printf '%s\tTESTDONE\t%s\t%s\t%s\t%s\t%s\t%s\n' "$SRC" "$SRC_SZ" "$OSZ" "$SRC_DUR_S" "$ODUR" "$USED_CQ" "$(gbh "$OSZ" "$ODUR")" >> "$MANIFEST"
        log "TESTDONE $SRC | src=$(( SRC_SZ / 1000000 ))MB out=$(( OSZ / 1000000 ))MB ratio=$(awk -v a=$OSZ -v b=$SRC_SZ 'BEGIN{printf "%.0f%%", 100*a/b}') qp=$USED_CQ out=${OUT_GBPH:-?}GB/h cap=${CAP}GB/h (source kept)"
        return 0
    fi
    if [ "$FINAL" = "$SRC" ]; then
        # In place (the source already had the .mkv name): the verified bytes
        # overwrite the source with the same inode path, so nothing else to remove.
        KEEP_SOURCE=no
    else
        # Renamed (mp4 -> mkv, or a release-tagged folder file): remove the old
        # file only after the new one is proven in place.
        KEEP_SOURCE=yes
    fi
    mv -- "$OUT_T" "$FINAL" \
        || { log "FAIL $SRC (commit failed — source NOT deleted, tmp at $OUT_T)"; printf '%s\tFAIL\tcommit\n' "$SRC" >> "$MANIFEST"; rm -f "$LFP"; return 1; }
    if [ "$KEEP_SOURCE" = yes ]; then
        rm -- "$SRC" || log "WARN $SRC committed but the old file could not be removed (leaving it; free it by hand)"
    fi

    if [ "$MIRRORED" = yes ]; then cp "$FINAL" "$XFS_DIR/$NAME" || log "WARN mirror copy failed for $NAME"; fi
    # Full runs: media is the permanent home — drop xfs mirror copies of earlier
    # titles (each was byte-verified identical there) so disk use stays bounded.
    # Guarded on a mirror being configured: with mirror off, $XFS_DIR is empty and
    # find would print a "No such file or directory" for every single title.
    [ "$FULL" = yes ] && [ -n "$XFS_DIR" ] && find "$XFS_DIR" -maxdepth 1 -name '*.mkv' -mmin +30 -delete
    printf '%s\tDONE\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$SRC" "$SRC_SZ" "$OSZ" "$SRC_DUR_S" "$ODUR" "$MIRRORED" "$USED_CQ" "$(gbh "$OSZ" "$ODUR")" >> "$MANIFEST"
    # mp4→mkv rename: also key the done-state under the committed output path,
    # else the next scan sees a fresh .mkv name and re-encodes it forever.
    [ "$FINAL" = "$SRC" ] || \
        printf '%s\tDONE\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$FINAL" "$SRC_SZ" "$OSZ" "$SRC_DUR_S" "$ODUR" "$MIRRORED" "$USED_CQ" "$(gbh "$OSZ" "$ODUR")" >> "$MANIFEST"
    log "DONE $SRC | src=$(( SRC_SZ / 1000000 ))MB out=$(( OSZ / 1000000 ))MB ratio=$(awk -v a=$OSZ -v b=$SRC_SZ 'BEGIN{printf "%.0f%%", 100*a/b}') qp=$USED_CQ out=${OUT_GBPH:-?}GB/h cap=${CAP}GB/h mirror=$MIRRORED"
}

log "=== RUN START cq=$CQ root=$SRC_ROOT xfs_floor=${XFS_MIN_FREE_GB}G margin=${XFS_MARGIN_GB}G limit=$LIMIT mirror=${XFS_DIR:-off} full=$FULL budget=${BUDGET_1080}/${BUDGET_1440}/${BUDGET_2160}GB/h@1080/1440/2160 qp_step=$CQ_STEP max_rung_steps=$MAX_RUNG_STEPS ==="
# Whole depth, not two levels: titles three directories down are invisible at
# -maxdepth 2 and silently never encoded (PLAN defect 1). -prune does not
# descend into what it prunes, which is what keeps this from eating its own
# output -- LOG_DIR lives inside SRC_ROOT by default, so without the hidden-dir
# prune a recursive scan walks the very tree it writes its queue into (that was
# already true at -maxdepth 2: .encode-logs/sneak.mkv is one level down).
# Pruned: any dotted directory (.git, .encode-logs) and the skip-list at any
# depth. Symlinks are not matched by -type f at all, matching the controller's
# probe; the suffix test is case-insensitive on both sides, or the controller's
# count and this queue disagree about what the job contains.
# -regextype posix-extended is load-bearing: find's default emacs type spells
# alternation '\|' and grouping '\(', so the plain () below silently matches
# nothing and the skip-list leaks (verified against a scratch tree, 2026-10-16).
# LC_ALL=C on the sort for the same reason: Python's sorted() is byte order, so
# a locale collation would make the controller's preview name different first-N
# titles than the ones this queue feeds the job when limit is small.
find "$SRC_ROOT" -regextype posix-extended \
     \( -name '.*' -o -type d \( -regex ".*[/$]($SKIP_NAMES)" \) \) -prune -o \
     -type f \( -iname '*.mkv' -o -iname '*.mp4' \) ! -name '*.shipping' -print0 \
    | LC_ALL=C sort -z > "$LOG_DIR/sources.z"

COUNT=0
TOTAL=$(tr '\0' '\n' < "$LOG_DIR/sources.z" | grep -c . || true)
while IFS= read -r -u 3 -d '' SRC; do
    if [ "$LIMIT" -gt 0 ] && [ "$COUNT" -ge "$LIMIT" ]; then
        log "LIMIT $LIMIT reached — stopping"; break
    fi
    # SKIP = known-bad source (e.g. zero-padded truncated download); delete
    # its manifest row after replacing the file to make it eligible again.
    # SKIPCODEC / SKIPSIZE / NOGAIN / OVERSIZE are deliberate decisions (already
    # modern / already inside budget / nothing to gain / no rung would fit) and
    # are sticky for the same reason: without them a full run re-probes, and for
    # SKIPSIZE re-probes expensively, the same titles every night forever. A
    # title is only worth re-deciding once something about it has changed.
    # TESTDONE is deliberately NOT in this list. It is what a bounded run (limit>0)
    # records, and a bounded run never deletes a source -- so it is a promise that
    # an encode WOULD be committed, not a record that one was. Leaving it sticky
    # meant a single limit=1 test excluded that title from every future full run,
    # silently and forever. Re-testing costs one encode; losing a title does not.
    if awk -F'\t' -v s="$SRC" '$1==s && ($2=="DONE" || $2=="SKIP" || $2=="SKIPCODEC" || $2=="SKIPSIZE" || $2=="NOGAIN" || $2=="OVERSIZE") {found=1} END{exit !found}' "$MANIFEST"; then
        continue
    fi
    progress "$(basename "$(dirname "$SRC")")" "$COUNT" "$TOTAL"
    state_set current "$SRC"
    run_one "$SRC"
    case $? in
        2|3) continue ;;   # refused before encoding — must not use up a LIMIT slot
    esac
    COUNT=$(( COUNT + 1 ))
    progress "$(basename "$(dirname "$SRC")")" "$COUNT" "$TOTAL"
done 3< "$LOG_DIR/sources.z"

log "=== RUN END (processed $COUNT this run) ==="
log "library free: $(df -h "$SRC_ROOT" | tail -1 | awk '{print $4}') | xfs free: $(df -h "${XFS_DIR:-/mnt/xfs}" | tail -1 | awk '{print $4}')"
if [ "$LIMIT" -gt 0 ]; then
    touch "$LOG_DIR/job.done"   # bounded test: chat service was never touched
    state_set state done
fi

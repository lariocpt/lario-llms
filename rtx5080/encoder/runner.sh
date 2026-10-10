#!/usr/bin/env bash
# Encoder job runner — owned by lario-llms/rtx5080/encoder/controller.py.
#
# Per movie:
#   1. stream source $MEDIA:$SRC_ROOT -> ffmpeg NVDEC -> hevc_nvenc -> local temp
#      on /mnt/xfs (seekable, so the MKV gets a real duration field)
#   2. verify locally (duration vs source, probe, 60s head+tail decode, size sane)
#   3. ship final bytes to the media box; verify there (size, duration, decode)
#   4. commit: delete source on media, promote temp; keep mirror on $XFS_DIR only
#      while free space >= $XFS_MIN_FREE_GB + $XFS_MARGIN_GB (checked per movie)
#
# While LIMIT=0 (full library) the chat service was drained+stopped by the
# controller; this runner restores it via teardown.py at the end (or on signal).
# With LIMIT>0 (bounded test) the chat service stays untouched and the source
# is never deleted; controller.status settles the job.
#
# Env (set by controller.py): LARIO_ENC_MEDIA_HOST, LARIO_ENC_SVC, LARIO_ENC_ROOT,
#   LARIO_ENC_CQ (23), LARIO_ENC_LIMIT (0=all), LARIO_ENC_LOG_DIR, LARIO_ENC_XFS_DIR
#   (empty disables mirroring), LARIO_ENC_FLOOR (50), LARIO_ENC_STATE (state json).
set -uo pipefail

MEDIA=${LARIO_ENC_MEDIA_HOST:-lario-media}
SVC=${LARIO_ENC_SVC:-rtx5080.service}
SRC_ROOT=${LARIO_ENC_ROOT:-/srv/media/Movies}
XFS_DIR=${LARIO_ENC_XFS_DIR-/mnt/xfs/videos/movies}
LOG_DIR=${LARIO_ENC_LOG_DIR:-/mnt/xfs/videos/movies/.encode-logs}
RUN_LOG=$LOG_DIR/run.log
MANIFEST=$LOG_DIR/manifest.tsv
STATE=${LARIO_ENC_STATE:-}
JFF=/usr/lib/jellyfin-ffmpeg/ffmpeg
SSH="ssh -o BatchMode=yes -o ServerAliveInterval=30 $MEDIA"
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
        log "CHAT RESTORE FAILED — controller encode_status will repair; manual: systemctl --user start $SVC"
    fi
    return $code
}
trap finish EXIT
trap 'log "TERMINATED by signal"; state_set cancel_note "signalled"; exit 143' TERM INT HUP

dur_media() {  # duration string of a path on the media box ("" if unparseable)
    local s
    s=$($SSH "$JFF -hide_banner -i '$1' 2>&1" | grep -oP 'Duration: \K[0-9:.]+' | head -1)
    case "$s" in N/A|"") echo "" ;; *) echo "$s" ;; esac
}
dur_local() { $FFPROBE -v error -show_entries format=duration -of csv=p=0 "$1" 2>/dev/null | cut -d. -f1; }
hms2s()   { awk -F: '{printf "%d", $1*3600+$2*60+$3}' <<<"$1"; }

xfs_write_ok() {
    local avail; avail=$(df --output=avail -BG "${XFS_DIR:-/mnt/xfs}" 2>/dev/null | tail -1 | tr -dc 0-9)
    # floor + 64G working-set headroom (source temp + encode temp + mirror copy)
    [ "${avail:-0}" -ge $((XFS_MIN_FREE_GB + 64)) ]
}

run_one() {
    local SRC="$1"
    case "$SRC" in
        *\'*) log "SKIP $SRC (quote in path — quoting is single-quote based)"; return 2 ;;
    esac
    local DIR STEM NAME OUT_T LFP SRC_L ENC_LOG SRC_DUR SRC_DUR_S SRC_SZ LDUR LERR LSZ ODUR ODUR_S OSZ OERR LSHA OSHA DSZ STRUCT DERR TSTART MIRRORED
    DIR=$(dirname "$SRC"); STEM=$(basename "$SRC"); STEM="${STEM%.*}"
    NAME="$STEM.mkv"
    OUT_T="$DIR/$STEM.mkv.shipping"
    LFP="$TMP_DIR/$STEM.mkv"
    ENC_LOG="$LOG_DIR/${STEM}.enc.log"

    SRC_DUR=$(dur_media "$SRC")
    [ -n "$SRC_DUR" ] || { log "FAIL $SRC (cannot probe source)"; printf '%s\tFAIL\tprobe_source\n' "$SRC" >> "$MANIFEST"; return 1; }
    SRC_DUR_S=$(hms2s "$SRC_DUR")
    SRC_SZ=$($SSH "stat -c %s '$SRC'")

    MIRRORED=no
    if [ -n "$XFS_DIR" ] && xfs_write_ok; then MIRRORED=yes; fi

    log "START $SRC | dur=$SRC_DUR srcsize=$(( SRC_SZ / 1000000 ))MB mirror=$MIRRORED cq=$CQ"

    # --- 1. download the source to a local size-checked temp, then encode ---
    # (ssh-pipe delivery truncated cleanly on several titles, and ffmpeg 9.x
    #  cannot demux some old HandBrake .mp4s from a non-seekable pipe at all;
    #  a local copy fixes both. Delete it right after encoding — the working
    #  set on /mnt/xfs must stay ≤ ~1.5x the output size.)
    rm -f "$LFP"
    SRC_L="$TMP_DIR/$STEM.src.${SRC##*.}"
    $SSH "cat '$SRC'" > "$SRC_L" \
      || { log "FAIL $SRC (source download failed)"; printf '%s\tFAIL\tdl_source\n' "$SRC" >> "$MANIFEST"; rm -f "$SRC_L"; return 1; }
    DSZ=$(stat -c %s "$SRC_L" 2>/dev/null || echo 0)
    [ "$DSZ" = "$SRC_SZ" ] \
      || { log "FAIL $SRC (download truncated: $DSZ of $SRC_SZ bytes)"; printf '%s\tFAIL\tdl_size\n' "$SRC" >> "$MANIFEST"; rm -f "$SRC_L"; return 1; }
    # mov_text subtitles (mp4 sources) cannot be muxed into matroska by this
    # ffmpeg build — convert only those subtitle streams to srt (per-index
    # override); PGS/DVB/etc stay bit-exact copies. Unquoted split is safe:
    # the tokens contain no spaces.
    local SUBCONV="" SUBI=0 SUBC
    for SUBC in $(ffprobe -v error -select_streams s -show_entries stream=codec_name -of csv=p=0 "$SRC_L"); do
        [ "$SUBC" = "mov_text" ] && SUBCONV="$SUBCONV -c:s:$SUBI srt"
        SUBI=$(( SUBI + 1 ))
    done
    $FFMPEG -hide_banner -nostdin -hwaccel cuda -hwaccel_output_format cuda \
          -i "$SRC_L" -map 0:v:0 -map 0:a? -map 0:s? -map_chapters 0 \
          -c:v hevc_nvenc -preset p5 -tune hq -rc vbr -cq "$CQ" -b:v 0 \
          -c:a copy -c:s copy $SUBCONV -y "$LFP" 2>"$ENC_LOG"
    local rc=$?
    rm -f "$SRC_L"
    [ "$rc" = 0 ] || { log "FAIL $SRC (encode rc=$rc — see $ENC_LOG)"; printf '%s\tFAIL\tencode_rc\n' "$SRC" >> "$MANIFEST"; rm -f "$LFP"; return 1; }

    # --- 2. verify locally ---
    LSZ=$(stat -c %s "$LFP" 2>/dev/null) || { log "FAIL $SRC (temp vanished)"; printf '%s\tFAIL\ttmp_missing\n' "$SRC" >> "$MANIFEST"; return 1; }
    [ "$LSZ" -gt $(( MIN_OUT_MB * 1000000 )) ] || { log "FAIL $SRC (output implausibly small: $LSZ B)"; printf '%s\tFAIL\ttoo_small\n' "$SRC" >> "$MANIFEST"; rm -f "$LFP"; return 1; }
    LDUR=$(dur_local "$LFP")
    if [ -z "$LDUR" ]; then
        log "FAIL $SRC (local temp has no parsable duration — see $ENC_LOG)"
        printf '%s\tFAIL\tdur_local\n' "$SRC" >> "$MANIFEST"; rm -f "$LFP"; return 1
    fi
    local dd=$(( SRC_DUR_S - LDUR )); [ "$dd" -lt 0 ] && dd=$(( -dd ))
    [ "$dd" -le 3 ] || { log "FAIL $SRC (duration mismatch src=$SRC_DUR out=${LDUR}s)"; printf '%s\tFAIL\tdur_mismatch\n' "$SRC" >> "$MANIFEST"; rm -f "$LFP"; return 1; }
    # Decode-window checks on the video stream only — that is what we re-encode.
    # Copied audio/subtitles inherit source quirks whose decoder strictness
    # varies across ffmpeg builds (TrueHD substream/packet errors, subtitle
    # junk); their integrity is covered by sha256 against the verified temp.
    # The null muxer also emits "non monotonically increasing dts" noise that
    # 9.x tolerates but 7.x rejects — copied audio inherits it into the
    # copy-null structure check too, so NOISE filters both passes below.
    local NOISE='non monotonically increasing dts to muxer|Application provided invalid'
    LERR=$( { $FFMPEG -v error -t 60 -i "$LFP" -map 0:v:0 -f null - 2>&1; $FFMPEG -v error -sseof -60 -i "$LFP" -map 0:v:0 -f null - 2>&1; } | grep -Ev "$NOISE" | head -3 )
    [ -z "$LERR" ] || { log "FAIL $SRC (decode errors locally: $LERR)"; printf '%s\tFAIL\tdecode_local\n' "$SRC" >> "$MANIFEST"; rm -f "$LFP"; return 1; }
    STRUCT=$($FFMPEG -v error -i "$LFP" -c copy -f null - 2>&1 | grep -Ev "$NOISE" | head -3)
    [ -z "$STRUCT" ] || { log "FAIL $SRC (container structure errors: $STRUCT)"; printf '%s\tFAIL\tstruct_local\n' "$SRC" >> "$MANIFEST"; rm -f "$LFP"; return 1; }

    # --- 3. ship to media box (over ssh) and verify there ---
    # sha256 is definitive for transport integrity; the old remote `-f null`
    # decode pass is gone because its null-muxer noise depended on the media
    # box's older ffmpeg build (rejected the healthy Dune: Part Two output).
    LSHA=$(sha256sum "$LFP" | cut -d' ' -f1)
    cat "$LFP" | $SSH "cat > '$OUT_T'" || { log "FAIL $SRC (ship to media failed)"; printf '%s\tFAIL\tship\n' "$SRC" >> "$MANIFEST"; rm -f "$LFP"; return 1; }
    OSZ=$($SSH "stat -c %s '$OUT_T'" 2>/dev/null)
    [ "$OSZ" = "$LSZ" ] || { log "FAIL $SRC (ship size mismatch local=$LSZ media=$OSZ — tmp kept at $OUT_T)"; printf '%s\tFAIL\tship_size\t%s\t%s\n' "$SRC" "$LSZ" "$OSZ" >> "$MANIFEST"; rm -f "$LFP"; return 1; }
    ODUR=$(dur_media "$OUT_T")
    [ -n "$ODUR" ] || { log "FAIL $SRC (media temp has no parsable duration — tmp kept at $OUT_T)"; printf '%s\tFAIL\tdur_media\n' "$SRC" >> "$MANIFEST"; rm -f "$LFP"; return 1; }
    ODUR_S=$(hms2s "$ODUR")
    dd=$(( SRC_DUR_S - ODUR_S )); [ "$dd" -lt 0 ] && dd=$(( -dd ))
    [ "$dd" -le 3 ] || { log "FAIL $SRC (media duration bad: $ODUR — tmp kept at $OUT_T)"; printf '%s\tFAIL\tdur_media\t%s\n' "$SRC" "$ODUR" >> "$MANIFEST"; rm -f "$LFP"; return 1; }
    OSHA=$($SSH "sha256sum '$OUT_T' | cut -d' ' -f1")
    [ -n "$OSHA" ] && [ "$OSHA" = "$LSHA" ] || { log "FAIL $SRC (sha256 mismatch after ship — tmp kept at $OUT_T)"; printf '%s\tFAIL\tship_hash\n' "$SRC" >> "$MANIFEST"; rm -f "$LFP"; return 1; }

    # --- 4. commit ---
    if [ "$LIMIT" -gt 0 ]; then
        # test mode: ship verified, but never delete the source, never mirror
        $SSH "rm -f '$OUT_T'"
        rm -f "$LFP"
        printf '%s\tTESTDONE\t%s\t%s\t%s\t%s\n' "$SRC" "$SRC_SZ" "$OSZ" "$SRC_DUR" "$ODUR" >> "$MANIFEST"
        log "TESTDONE $SRC | src=$(( SRC_SZ / 1000000 ))MB out=$(( OSZ / 1000000 ))MB ratio=$(awk -v a=$OSZ -v b=$SRC_SZ 'BEGIN{printf "%.0f%%", 100*a/b}') (source kept)"
        return 0
    fi
    $SSH "rm -- '$SRC' && mv -- '$OUT_T' '$DIR/$NAME'" \
        || { log "FAIL $SRC (commit failed — source NOT deleted, tmp at $OUT_T)"; printf '%s\tFAIL\tcommit\n' "$SRC" >> "$MANIFEST"; rm -f "$LFP"; return 1; }

    if [ "$MIRRORED" = yes ]; then mv "$LFP" "$XFS_DIR/$NAME"; else rm -f "$LFP"; fi
    # Full runs: media is the permanent home — drop xfs mirror copies of earlier
    # titles (each was byte-verified identical there) so disk use stays bounded.
    [ "$FULL" = yes ] && find "$XFS_DIR" -maxdepth 1 -name '*.mkv' -mmin +30 -delete
    printf '%s\tDONE\t%s\t%s\t%s\t%s\t%s\n' "$SRC" "$SRC_SZ" "$OSZ" "$SRC_DUR" "$ODUR" "$MIRRORED" >> "$MANIFEST"
    # mp4→mkv rename: also key the done-state under the committed output path,
    # else the next scan sees a fresh .mkv name and re-encodes it forever.
    [ "$DIR/$NAME" = "$SRC" ] || \
        printf '%s\tDONE\t%s\t%s\t%s\t%s\t%s\n' "$DIR/$NAME" "$SRC_SZ" "$OSZ" "$SRC_DUR" "$ODUR" "$MIRRORED" >> "$MANIFEST"
    log "DONE $SRC | src=$(( SRC_SZ / 1000000 ))MB out=$(( OSZ / 1000000 ))MB ratio=$(awk -v a=$OSZ -v b=$SRC_SZ 'BEGIN{printf "%.0f%%", 100*a/b}') mirror=$MIRRORED"
}

log "=== RUN START cq=$CQ xfs_floor=${XFS_MIN_FREE_GB}G margin=${XFS_MARGIN_GB}G limit=$LIMIT mirror=${XFS_DIR:-off} full=$FULL ==="
$SSH "find '$SRC_ROOT' -maxdepth 2 -type f \( -name '*.mkv' -o -name '*.mp4' \) ! -name '*.shipping' -print0" \
    | sort -z > "$LOG_DIR/sources.z"

COUNT=0
TOTAL=$(tr '\0' '\n' < "$LOG_DIR/sources.z" | grep -c . || true)
while IFS= read -r -u 3 -d '' SRC; do
    if [ "$LIMIT" -gt 0 ] && [ "$COUNT" -ge "$LIMIT" ]; then
        log "LIMIT $LIMIT reached — stopping"; break
    fi
    # SKIP = known-bad source (e.g. zero-padded truncated download); delete
    # its manifest row after replacing the file to make it eligible again.
    if awk -F'\t' -v s="$SRC" '$1==s && ($2=="DONE" || $2=="TESTDONE" || $2=="SKIP") {found=1} END{exit !found}' "$MANIFEST"; then
        continue
    fi
    progress "$(basename "$(dirname "$SRC")")" "$COUNT" "$TOTAL"
    state_set current "$SRC"
    run_one "$SRC"
    COUNT=$(( COUNT + 1 ))
    progress "$(basename "$(dirname "$SRC")")" "$COUNT" "$TOTAL"
done 3< "$LOG_DIR/sources.z"

log "=== RUN END (processed $COUNT this run) ==="
log "media box free: $($SSH "df -h $SRC_ROOT | tail -1" | awk '{print $4}') | xfs free: $(df -h "${XFS_DIR:-/mnt/xfs}" | tail -1 | awk '{print $4}')"
if [ "$LIMIT" -gt 0 ]; then
    touch "$LOG_DIR/job.done"   # bounded test: chat service was never touched
    state_set state done
fi

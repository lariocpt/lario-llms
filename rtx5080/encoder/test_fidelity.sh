#!/usr/bin/env bash
# Fidelity gates on real files — the sibling of test_gates.sh.
#
# test_gates.sh is offline: it extracts the runner's arithmetic and exercises it on
# strings. That is what caught the two inverted comparisons and the awk BEGIN-block
# bug, but it cannot catch the shape of an ffmpeg command line. Two gates did ship
# broken in exactly that way during development: -map placed before -i (ffmpeg reads
# it as an option for the next input and refuses to open the file), and an ssim
# filter whose output was never labelled or mapped (the metric never ran, so no
# number was printed — which a gate written to treat "no number" as a refusal
# dutifully reported as a failure of every encode).
#
# So this script builds a synthetic source and four encodes from it on the CPU, in a
# temp dir, and runs the real measuring helpers against the real files. Five seconds.
# Nothing in the library is touched and no GPU is needed.
#
#   ./test_fidelity.sh          needs ffmpeg + ffprobe with libx264 and the ssim filter
set -u
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
RUNNER="$HERE/runner.sh"
for bin in ffmpeg ffprobe; do
    command -v "/usr/bin/$bin" >/dev/null 2>&1 || { echo "NEEDS /usr/bin/$bin — this suite measures the gate, not guesses at it"; exit 1; }
done
FFMPEG=/usr/bin/ffmpeg
FFPROBE=/usr/bin/ffprobe
SSIM_FLOOR=${LARIO_ENC_SSIM:-0.985}
SSIM_WINDOWS=${LARIO_ENC_SSIM_WINDOWS:-3}
SSIM_SECONDS=${LARIO_ENC_SSIM_SECONDS:-5}
CROP_SECONDS=${LARIO_ENC_CROP_SECONDS:-4}
NOISE='non monotonically increasing dts to muxer|Application provided invalid'
D=$(mktemp -d "${TMPDIR:-/tmp}/fidelity.XXXXXX")
trap 'rm -rf "$D"' EXIT

# The same extraction test_gates.sh uses — the helpers under test are the ones the
# runner actually runs, copied by text, not a second implementation that can drift.
eval "$(sed -n '/^dur_s()/,/^xfs_write_ok()/p' "$RUNNER" | sed '$d')"

if [ "${1:-}" = --help ]; then
    awk 'NR == 1 { next } /^set -u/ { exit } { sub(/^#[ ]?/, ""); print }' "$HERE/test_fidelity.sh"
    exit 0
fi

fails=0
want() { # want LABEL GOT EXPECTED
    if [ "$2" = "$3" ]; then printf '  ok   %-34s %s\n' "$1" "$2"
    else printf '  FAIL %-34s got=%s want=%s\n' "$1" "$2" "$3"; fails=$((fails + 1)); fi
}

# 1200x720 content padded into a 1280x720 frame: a black border, so cropdetect has
# something to find, and enough duration that the sample windows spread out.
$FFMPEG -nostdin -v error -y \
    -stream_loop -1 -f lavfi -i "testsrc2=size=1200x720:rate=25" \
    -stream_loop -1 -f lavfi -i "sine=frequency=440" -t 30 \
    -filter_complex "[0:v]pad=1280:720:40:0:color=black[v]" -map "[v]" -map 1:a \
    -c:v libx264 -preset veryfast -crf 18 -pix_fmt yuv420p -c:a aac "$D/src.mkv" || exit 1

enc() { # name, -vf ("none" for a straight re-encode), crf
    local name="$1" vf="$2" crf="$3" extra=()
    [ "$vf" = none ] || extra=(-vf "$vf")
    $FFMPEG -nostdin -v error -y -i "$D/src.mkv" "${extra[@]}" \
        -c:v libx264 -preset veryfast -crf "$crf" -pix_fmt yuv420p -c:a copy "$D/$name.mkv"
}
enc good   none 23
enc scaled "scale=1024:576" 23
# crop + scale back with setsar=1: coded size and display aspect both come out
# identical to the source. Geometry cannot see this defect at all.
enc zoomed "crop=1104:662:88:29,scale=1280:720,setsar=1" 23
enc coarse none 30
# A defect that exists only between 12.5 s and 16.5 s of a 30 s title. This is the
# regression guard for the window-spread bug: if the sample windows all seeked to 0,
# every cheap gate would pass and the metric would agree, and the title would have
# been committed with a black hole in the middle of it.
enc mid "drawbox=x=0:y=0:w=iw:h=ih:color=black:t=fill:enable='between(t,12.5,16.5)'" 23

SRC_GEO=$(geo_norm "$(vgeom "$D/src.mkv")")
printf 'source geometry: %s\n' "${SRC_GEO:?probe failed on a file ffmpeg just wrote}"

echo
echo '=== honest re-encode: all four gates say yes ==='
want 'geometry kept'    "$(geo_ok "$SRC_GEO" "$(geo_norm "$(vgeom "$D/good.mkv")")")" yes
want 'crop kept'        "$(crop_ok "$(crop_of "$D/src.mkv" 3)" "$(crop_of "$D/good.mkv" 3)")" yes
want 'whole-file decode clean' "$(full_decode_errs "$D/good.mkv")" ''
SSIM_GOOD=$(worst_ssim "$D/src.mkv" "$D/good.mkv" 30)
want 'ssim measured and over floor' "$(ssim_ok "$SSIM_GOOD" "$SSIM_FLOOR")" yes

echo
echo '=== rescaled encode: the size gate fires ==='
want 'rescale refused' "$(geo_ok "$SRC_GEO" "$(geo_norm "$(vgeom "$D/scaled.mkv")")")" \
    'no:size:1280x720-vs-1024x576'

echo
echo '=== zoomed crop: geometry is blind, ssim is not ==='
GZ=$(geo_ok "$SRC_GEO" "$(geo_norm "$(vgeom "$D/zoomed.mkv")")")
CZ=$(crop_ok "$(crop_of "$D/src.mkv" 3)" "$(crop_of "$D/zoomed.mkv" 3)")
SSIM_Z=$(worst_ssim "$D/src.mkv" "$D/zoomed.mkv" 30)
want 'geometry passes it (as it must)' "$GZ" yes
want 'crop passes it (as it must)'     "$CZ" yes
want 'ssim refuses it'                 "$(ssim_ok "$SSIM_Z" "$SSIM_FLOOR")" no
printf '       measured ssim %s against a floor of %s — the three cheap gates agree and\n' "$SSIM_Z" "$SSIM_FLOOR"
printf '       only the metric notices that a fifth of the picture was thrown away\n'

echo
echo '=== a defect in the middle of the title is not invisible ==='
GM=$(geo_ok "$SRC_GEO" "$(geo_norm "$(vgeom "$D/mid.mkv")")")
DM=$(full_decode_errs "$D/mid.mkv")
SSIM_M=$(worst_ssim "$D/src.mkv" "$D/mid.mkv" 30)
want 'geometry passes it'          "$GM" yes
want 'decode passes it'            "$DM" ''
want 'the sampled metric refuses'  "$(ssim_ok "$SSIM_M" "$SSIM_FLOOR")" no
printf '       measured ssim %s — a window that only ever seeks to 0 would have passed this\n' "$SSIM_M"

echo
echo '=== the metric tracks quality, so the floor means something ==='
SSIM_COARSE=$(worst_ssim "$D/src.mkv" "$D/coarse.mkv" 30)
printf '  crf 23 -> %s   crf 30 -> %s   floor %s\n' "$SSIM_GOOD" "$SSIM_COARSE" "$SSIM_FLOOR"
want 'a finer rung scores higher' \
    "$(awk -v a="$SSIM_GOOD" -v b="$SSIM_COARSE" 'BEGIN { print (a + 0 > b + 0) ? "yes" : "no" }')" yes

echo
echo '=== a missing number is a refusal, never a pass ==='
want 'empty refuses at floor 0'  "$(ssim_ok '' 0)" no
want 'garbage refuses'           "$(ssim_ok 'N/A' 0.985)" no
want 'a real value passes at 0'  "$(ssim_ok 0.500 0)" yes

echo
if [ "$fails" = 0 ]; then echo 'FIDELITY GATES: all real-file checks pass'; else echo "FIDELITY GATES: $fails failed"; fi
exit "$fails"

#!/usr/bin/env bash
# Offline checks for the encoder's decision gates. No GPU, no ffmpeg, no library
# writes: every block here extracts the REAL text from runner.sh (by pattern, so
# editing the file cannot silently stale the test) and exercises the arithmetic,
# the scan and the manifest accounting on scratch data.
#
#   ./test_gates.sh    # exits 0 and prints one ok line per assertion
set -u
cd "$(dirname "$0")"
RUNNER=runner.sh
CTL=controller.py
PY=${PYTHON:-python3}
fails=0
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

ck() { # ck LABEL GOT WANT
    if [ "$2" = "$3" ]; then printf '  ok   %-38s %s\n' "$1" "$2"
    else printf '  FAIL %-38s got=%s want=%s\n' "$1" "$2" "$3"; fails=$((fails + 1)); fi
}

echo '=== syntax ==='
bash -n "$RUNNER" && ck 'runner.sh parses' ok ok
$PY -m py_compile "$CTL" && ck 'controller.py compiles' ok ok

# --- gate arithmetic, as written in the runner -------------------------------
# dur_s/vcodec/vheight/hms/gbh/over/cap_for: everything from the first probe
# helper up to (not including) xfs_write_ok, which needs df and a real mount.
eval "$(sed -n '/^dur_s()/,/^xfs_write_ok()/p' "$RUNNER" | sed '$d')"
BUDGET_1080=3.0; BUDGET_1440=4.5; BUDGET_2160=8.0
CQ_MAX=30; CQ_STEP=2; MAX_RUNG_STEPS=2
echo
echo '=== budget arithmetic (decimal GB/h) ==='
ck '3 GB over 2 h'          "$(gbh 3000000000 7200)" '1.50'
ck 'exactly 3.0 GB/h'       "$(gbh 3000000000 3600)" '3.00'
ck '3.01 GB/h'              "$(gbh 3010000000 3600)" '3.01'
ck '2 h at 16 GB (4K)'      "$(gbh 16000000000 7200)" '8.00'
ck 'duration 0 is guarded'  "$(gbh 5000000000 0)" '0'
over 3.01 3.0 && ck 'over: 3.01 > 3.0' yes yes || ck 'over: 3.01 > 3.0' no yes
over 3.00 3.0 && ck 'over: equal is not over' yes no || ck 'over: equal is not over' no no
ck 'cap_for 2160'           "$(cap_for 2160)" '8.0'
ck 'cap_for 2161'           "$(cap_for 2161)" '8.0'
ck 'cap_for 1440'           "$(cap_for 1440)" '4.5'
ck 'cap_for 1439 -> 1080p'  "$(cap_for 1439)" '3.0'
ck 'cap_for 720 -> 1080p'   "$(cap_for 720)" '3.0'
ck 'cap_for unknown -> tightest' "$(cap_for 'n/a')" '3.0'

echo
echo '=== the already-modern skip (this gate has never once fired) ==='
# It was `case "$SRC_CODEC" in $MODERN_CODECS)` with MODERN_CODECS='hevc|av1|vvc'.
# A "|" arriving by variable expansion is a literal pipe: case resolves alternation
# at parse time, before expansion, so the pattern was the single string
# "hevc|av1|vvc" and matched no codec that ever existed. SKIPCODEC was dead.
# 70 of this queue's 78 files are hevc, and a commit deletes the source.
ck 'hevc is modern'          "$(modern_p hevc)" yes
ck 'av1 is modern'           "$(modern_p av1)" yes
ck 'vvc is modern'           "$(modern_p vvc)" yes
ck 'h264 is not'             "$(modern_p h264)" no
ck 'mpeg4 (the xvid name) is not' "$(modern_p mpeg4)" no
ck 'avc1 is not'             "$(modern_p avc1)" no
ck 'HEVC uppercase is not (no silent case-fold)' "$(modern_p HEVC)" no
ck 'the empty codec is not a skip' "$(modern_p '')" no
# The bug class, not just the bug: a variable standing where a pattern belongs.
ck 'no variable is used as a case pattern' \
   "$(grep -cE '^[[:space:]]*\$[A-Z_]+[)?]' "$RUNNER")" '0'
ck 'an unprobeable codec refuses rather than encoding' \
   "$(grep -cF 'probe_codec' "$RUNNER")" '1'
ck 'the codec gate comes before the budget gate' \
   "$([ "$(grep -nF -- 'modern_p "$SRC_CODEC"' "$RUNNER" | cut -d: -f1)" -lt \
        "$(grep -nF -- 'is inside the ${CAP} GB/h budget' "$RUNNER" | cut -d: -f1)" ] && echo yes || echo no)" yes

echo
echo '=== ladder rungs tried (CQ=23 unless stated) ==='
# START_CQ .. the while that builds TRIED. Same extraction rule as above.
ladder() { # ladder SRC_GBPH CAP CQ -> the rung list
    SRC_GBPH="$1"; CAP="$2"; CQ="$3"
    eval "$(sed -n '/^    START_CQ=\$CQ$/,/^    done$/p' "$RUNNER")"
    echo "$TRIED"
}
ck '1.2x over budget'      "$(ladder 3.60 3.0 23)" ' 23 25 27'
ck 'exactly 2x: no head start' "$(ladder 6.00 3.0 23)" ' 23 25 27'
ck '2.03x over: +2'        "$(ladder 6.10 3.0 23)" ' 25 27 29'
ck '3.03x over: +4'        "$(ladder 9.10 3.0 23)" ' 27 29 30'
ck '13x: head start caps at +4' "$(ladder 39.0 3.0 23)" ' 27 29 30'
ck 'near the top: no dupes' "$(ladder 3.60 3.0 29)" ' 29 30'
ck 'at the top: one rung'  "$(ladder 39.0 3.0 30)" ' 30'
ck 'fine cq 16 far over'   "$(ladder 9.10 3.0 16)" ' 20 22 24'

# --- §9.1.3 fidelity gates: the arithmetic, offline ---------------------------
# The three gates that decide whether an encode is the SAME FILM. The measuring
# functions shell out to ffmpeg and cannot run here; every decision they make is
# pure arithmetic that can, and that is what is extracted above and exercised
# below. The rule under test everywhere: no number means a refusal, never a pass.
echo
echo '=== geometry: the "we never scale or crop" promise, measured ==='
ck 'geo_norm 1080p, no sar/dar'   "$(geo_norm '1920,1080,,')" '1920x1080 16:9 1:1'
ck 'geo_norm anamorphic, both'    "$(geo_norm '720,576,16:11,4:3')" '720x576 4:3 16:11'
ck 'geo_norm dar from sar'        "$(geo_norm '720,576,16:11,')" '720x576 20:11 16:11'
ck 'geo_norm 0:1 sar is square'   "$(geo_norm '1280,720,0:1,N/A')" '1280x720 16:9 1:1'
ck 'geo_norm no size'             "$(geo_norm '')" ''
ck 'geo_norm zero size'           "$(geo_norm '0,0,,')" ''
ck 'geo_ok identical'             "$(geo_ok '1920x1080 16:9 1:1' '1920x1080 16:9 1:1')" yes
ck 'geo_ok same picture, other spelling' "$(geo_ok '720x576 4:3 16:11' '720x576 8:6 16:11')" yes
ck 'geo_ok coded size changed'    "$(geo_ok '1920x1080 16:9 1:1' '1920x960 16:9 1:1')" 'no:size:1920x1080-vs-1920x960'
ck 'geo_ok dar changed'           "$(geo_ok '1920x1080 16:9 1:1' '1920x1080 4:3 1:1')" 'no:dar:16:9-vs-4:3'
ck 'geo_ok sar-only shift kept'   "$(geo_ok '1920x1080 16:9 1:1' '1920x1080 16:9 8:9')" yes
ck 'geo_ok unmeasurable source'   "$(geo_ok '' '1920x1080 16:9 1:1')" 'no:unmeasurable'
ck 'geo_ok unmeasurable encode'   "$(geo_ok '1920x1080 16:9 1:1' '')" 'no:unmeasurable'

echo
echo '=== crop: asymmetric, because border noise must not refuse a good encode ==='
ck 'crop_ok unchanged'            "$(crop_ok '1920:1080' '1920:1080')" yes
ck 'crop_ok encode keeps more'    "$(crop_ok '1904:1080' '1920:1080')" yes
ck 'crop_ok encode threw picture' "$(crop_ok '1920:1080' '1904:1080')" 'no:crop:1920:1080-vs-1904:1080'
ck 'crop_ok height crop refused'  "$(crop_ok '1920:1080' '1920:1040')" 'no:crop:1920:1080-vs-1920:1040'
ck 'crop_ok unmeasurable'         "$(crop_ok '' '1920:1080')" 'no:unmeasurable'
ck 'crop_ok garbage is unmeasurable' "$(crop_ok 'abc' 'def')" 'no:unmeasurable'

echo
echo '=== ssim floor: an absent number refuses ==='
ck 'ssim 0.990 vs 0.985'         "$(ssim_ok 0.990 0.985)" yes
ck 'ssim exactly at floor'       "$(ssim_ok 0.985 0.985)" yes
ck 'ssim below floor'            "$(ssim_ok 0.980 0.985)" no
ck 'ssim unmeasurable'           "$(ssim_ok '' 0.985)" no
ck 'ssim garbage'                "$(ssim_ok 'N/A' 0.985)" no

echo
echo '=== the sample windows actually cover the title ==='
# Written because of a real bug: the seek arithmetic was handed "$2", the encode's
# filename, instead of the duration. awk read "movie.mkv" as 0, every window landed
# at offset 0, and the gate still measured something — so it looked like a gate with
# coverage while examining the first sixty seconds of a two-hour film.
ck '2 h window 1'               "$(ssim_start 7200 1 3 20)" '1670'
ck '2 h window 2'               "$(ssim_start 7200 2 3 20)" '3590'
ck '2 h window 3'               "$(ssim_start 7200 3 3 20)" '5510'
ck 'shorter than a window -> 0'  "$(ssim_start 30 2 3 20)" '0'
ck 'window never seeks past end' "$(ssim_start 41 3 3 20)" '21'
ck 'three windows are three places' \
   "$(printf '%s\n%s\n%s\n' "$(ssim_start 7200 1 3 20)" "$(ssim_start 7200 2 3 20)" \
        "$(ssim_start 7200 3 3 20)" | sort -u | wc -l | tr -d ' ')" '3'
ck 'the duration is the third argument' "$(grep -c 'ssim_start "$3"' "$RUNNER")" '1'
# Written because of a second, worse bug in the same loop: the update that carries
# the worst window forward was negated, so it kept the BEST score. Two clean windows
# either side of a corrupted one produced a "worst" of 0.9937 for a real worst of
# 0.5488, and the encode would have been committed with the source deleted.
ck 'worse of two, lower second'   "$(ssim_worse 0.990 0.500)" '0.500000000'
ck 'worse of two, lower first'    "$(ssim_worse 0.410 0.990)" '0.410000000'
ck 'worse of equal'               "$(ssim_worse 0.700 0.700)" '0.700000000'
ck 'unmeasured candidate keeps cur' "$(ssim_worse 0.900 '')" '0.900'
ck 'nothing measured yet -> cand'   "$(ssim_worse '' 0.800)" '0.800'
ck 'three windows, worst carried'   "$(ssim_worse "$(ssim_worse 0.990 0.550)" 0.993)" '0.550000000'

echo
echo '=== the fidelity gates run only on an encode that would be committed ==='
ck 'geometry probed once, before the GPU' "$(grep -c 'SRC_GEO=$(geo_norm' "$RUNNER")" '1'
ck 'one whole-file decode gate'  "$(grep -c 'full_decode_errs "$LFP"' "$RUNNER")" '1'
ck 'one ssim gate'               "$(grep -c 'worst_ssim "$SRC" "$LFP"' "$RUNNER")" '1'
# Four gates, four refusals: a gate that falls through without dropping the temp
# is a gate that commits the encode anyway.
ck 'every fidelity refusal drops the encode' \
   "$(sed -n '/is it the same film/,/FIDELITY/p' "$RUNNER" | grep -c 'rm -f "$LFP"; return 1')" '4'
ck 'fidelity comes after the gain gate' \
   "$([ "$(grep -nF -- 'LOWGAIN $SRC at qp=' "$RUNNER" | cut -d: -f1)" -lt \
        "$(grep -nF -- 'is it the same film' "$RUNNER" | cut -d: -f1)" ] && echo yes || echo no)" yes
ck 'fidelity comes before the promote' \
   "$([ "$(grep -nF -- 'is it the same film' "$RUNNER" | cut -d: -f1)" -lt \
        "$(grep -nF -- 'promote to the library directory' "$RUNNER" | cut -d: -f1)" ] && echo yes || echo no)" yes

echo
echo '=== scratch a killed run leaves behind ==='
# A cancel is cleaned by the EXIT/TERM trap; SIGKILL, an OOM kill or a power cut is
# not, and nothing else ever touched .encode-tmp -- a few GB per interrupted title,
# forever, on the very volume the free-space floor is measured against. This runs the
# runner's own sweep text against a scratch tree with one old file and one new.
log()    { printf '%s\n' "$*" >> "$tmp/swept.log"; }
state_set() { :; }
scratch="$tmp/scratch"; mkdir -p "$scratch"
: > "$scratch/current.mkv"; : > "$scratch/interrupted.mkv"; : > "$scratch/keep.mkv.mp4"
touch -d '2 hours ago' "$scratch/interrupted.mkv"
TMP_DIR="$scratch"
eval "$(sed -n '/^stale=$(find "\$TMP_DIR"/,/^fi$/p' "$RUNNER")"
ck 'the interrupted scratch is gone' "$([ -e "$scratch/interrupted.mkv" ] && echo there || echo gone)" gone
ck 'scratch from this run is kept'   "$([ -e "$scratch/current.mkv" ] && echo there || echo gone)" there
ck 'nothing but scratch.mkv is swept' "$([ -e "$scratch/keep.mkv.mp4" ] && echo there || echo gone)" there
ck 'the sweep says what it removed'  "$([[ -s "$tmp/swept.log" && -f "$scratch/interrupted.mkv" ]] && echo lied || echo named)" named
ck 'scratch is dropped on a signal'  "$(grep -cF 'rm -f "$CUR_LFP"' "$RUNNER")" '1'
ck 'the handler has a global handle' "$(grep -cF 'CUR_LFP="$LFP"' "$RUNNER")" '1'
ck 'the sweep runs before the queue' \
   "$([ "$(grep -nF -- '"$TMP_DIR" -maxdepth 1' "$RUNNER" | head -1 | cut -d: -f1)" -lt \
        "$(grep -nF -- 'find "$SRC_ROOT" -regextype' "$RUNNER" | head -1 | cut -d: -f1)" ] && echo yes || echo no)" yes
unset -f log state_set

# --- the scan: what a job actually contains ----------------------------------
echo
echo '=== scan prunes (scratch tree) ==='
S="$tmp/library"
mkdir -p "$S/Title Two (2015)/Subs" "$S/.encode-logs" "$S/.hidden-dir" \
         "$S/_live_photos/live-photos-for-deletion" "$S/_mediatool/run-1234" \
         "$S/Nested/Deeper/Deepest" "$S/By year/2020/A Movie (2020)" \
         "$S/By year/2020/live-photos-for-deletion"
touch "$S/flat.mkv" "$S/Title One (2001).mp4" "$S/Title Two (2015)/cd1.mkv" \
      "$S/Title Two (2015)/Subs/extra.srt" "$S/.encode-logs/sources.z" \
      "$S/.encode-logs/sneak.mkv" "$S/.hidden-dir/hidden.mkv" \
      "$S/_live_photos/live-photos-for-deletion/LP-0001.mp4" \
      "$S/_mediatool/run-1234/evidence.mkv" "$S/Nested/Deeper/Deepest/Deep Title.mkv" \
      "$S/By year/2020/A Movie (2020)/A Movie (2020).MKV" \
      "$S/By year/2020/live-photos-for-deletion/LP-0002.mp4" \
      "$S/NotYet.mkv.shipping" "$S/photo.jpg"
ln -s "$S/flat.mkv" "$S/Symlinked.mkv"

SRC_ROOT="$S"; LOG_DIR="$S/.encode-logs"
eval "$(grep '^SKIP_NAMES=' "$RUNNER")"
# The find as committed, run through the same shell variables the job uses.
eval "$(sed -n '/^find "\$SRC_ROOT"/,/sources\.z"$/p' "$RUNNER")"
find_out=$(tr '\0' '\n' < "$LOG_DIR/sources.z" | sed "s|^$S|.|" | tr '\n' ',')
# LC_ALL=C byte order: uppercase before lowercase, which is Python's sorted()
# order too -- the point of pinning the locale is that both agree.
ck 'queue contents' "$find_out" \
   './By year/2020/A Movie (2020)/A Movie (2020).MKV,./Nested/Deeper/Deepest/Deep Title.mkv,./Title One (2001).mp4,./Title Two (2015)/cd1.mkv,./flat.mkv,'
# Every planted decoy must be absent: the scan's own tree, dot dirs, the skip-list
# at two depths, a symlink, the promote temp and a non-video.
leaked=$(tr '\0' '\n' < "$LOG_DIR/sources.z" | grep -E '/\.(encode-logs|hidden-dir)/|_live_photos|_mediatool|Symlinked|\.shipping|\.srt$|\.jpg$' | wc -l)
ck 'planted decoys excluded (7 planted)' "$leaked" 0

echo
echo '=== controller.media_probe agrees with that queue ==='
$PY - "$S" <<'PY' || { echo '  FAIL controller parity (exception)'; fails=$((fails + 1)); }
import importlib.util, sys
from pathlib import Path
root = sys.argv[1]
spec = importlib.util.spec_from_file_location('enc_ctl', 'controller.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
got = sorted(str(p) for p in m._sources(root))
raw = (Path(root) / '.encode-logs/sources.z').read_bytes().split(b'\0')
want = sorted(w.decode() for w in raw if w)
assert got == want, '\n controller: %s\n      queue: %s' % (got, want)
files, total = m.media_probe(root)
assert files == got, 'media_probe and _sources disagree'
print('  ok   controller queue matches find (%d files, %d bytes)' % (len(got), total))
PY

echo
echo '=== manifest accounting ==='
$PY - <<'PY' || fails=$((fails + 1))
import importlib.util
from pathlib import Path
import tempfile
spec = importlib.util.spec_from_file_location('enc_ctl', 'controller.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
d = Path(tempfile.mkdtemp())
d.joinpath('manifest.tsv').write_text('\n'.join([
    '/lib/A.mkv\tDONE\t8000000000\t3000000000\t7200\t7200\tyes\t23\t1.50',
    '/lib/B.mp4\tDONE\t6000000000\t2000000000\t5400\t5400\tno\t25\t1.33',
    '/lib/B.mkv\tDONE\t6000000000\t2000000000\t5400\t5400\tno\t25\t1.33',
    '/lib/C.mkv\tTESTDONE\t5000000000\t1500000000\t5400\t5400\t23\t1.00',
    '/lib/D.mkv\tSKIPCODEC\t9000000000\thevc',
    '/lib/E.mkv\tSKIPSIZE\t2000000000\t6000\t1080\t1.20',
    '/lib/F.mkv\tOVERSIZE\t70000000000\t7200\t2160\t35.00\t8.0',
    '/lib/G.mkv\tNOGAIN\t3100000000\t2900000000\th264\t3.0\t0.86',
    '/lib/H.mkv\tSKIP\tdup_stem',
    '/lib/I.mkv\tFAIL\tencode_rc',
    '/lib/J.mkv\tSOMETHING_NEW\tx', 'garbage line',
]) + '\n')
t = m.manifest_tally(str(d))
want = {'DONE': 2, 'TESTDONE': 1, 'FAIL': 1, 'SKIP': 1, 'SKIPCODEC': 1,
        'SKIPSIZE': 1, 'NOGAIN': 1, 'OVERSIZE': 1}
ok = (t['counts'] == want and t['reclaimed_bytes'] == 9000000000
      and t['rename_alias_rows'] == 1 and t['last_done'] == 'B.mkv')
print('  %s   8 verdicts tallied, rename counted once, reclaimed 9.00 GB, '
      'last_done=%s (a FAIL row does not move it)' % ('ok  ' if ok else 'FAIL', t['last_done']))
if not ok:
    print('       got', t)
raise SystemExit(0 if ok else 1)
PY

echo
echo '=== controller reports the policy the runner actually implements ==='
$PY - <<'PY' || fails=$((fails + 1))
import importlib.util
import re
spec = importlib.util.spec_from_file_location('enc_ctl', 'controller.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
runner = open('runner.sh').read()


def runner_default(name):
    """The value the runner uses when the controller does not pass the env var."""
    for pattern in (r'^%s=\$\{[A-Z0-9_]*:-([^}]*)\}' % name, r'^%s=([0-9.]+)\s' % name):
        found = re.search(pattern, runner, re.M)
        if found:
            return found.group(1)
    return None


advertised = {'BUDGET_1080': str(m.BUDGET_GBH['1080']), 'BUDGET_1440': str(m.BUDGET_GBH['1440']),
              'BUDGET_2160': str(m.BUDGET_GBH['2160']), 'CQ_STEP': str(m.CQ_STEP),
              'MAX_RUNG_STEPS': str(m.MAX_RUNG_STEPS), 'MIN_GAIN_PCT': str(m.MIN_GAIN_PCT),
              'CQ_MAX': str(m.CQ_RANGE[1]), 'CQ': str(m.DEFAULTS['cq'])}
drift = {}
for name, want in advertised.items():
    got = runner_default(name)
    if got != want:
        drift[name] = (got, want)

# Gate NAMES, derived from what the runner writes to the manifest rather than from
# anyone's memory of them: the four §9.1.3 fidelity gates shipped in the runner and
# were never advertised, so encoder_options described a job that was no longer the
# one being run. A gate the caller cannot see is a gate the caller cannot trust.
ctl = open('controller.py').read()
gates_text = ctl.split("'gates': [", 1)[1].split('],', 1)[0] if "'gates': [" in ctl else ''
for gate in ('geo', 'crop', 'decode_full', 'ssim'):
    enforced = re.search(r'FAIL\\t%s' % gate, runner)
    if enforced and not re.search(r'\b%s\b' % gate, gates_text):
        drift['advertises_' + gate] = ('absent from the gates list', 'the runner writes FAIL ' + gate)
print('  %s   budget %s step %s steps %s gain %s%% cq_range %s default_cq %s all match runner.sh'
      % ('ok  ' if not drift else 'FAIL', m.BUDGET_GBH, m.CQ_STEP, m.MAX_RUNG_STEPS,
         m.MIN_GAIN_PCT, list(m.CQ_RANGE), m.DEFAULTS['cq']))
if drift:
    print('       drift (runner_default, advertised):', drift)
raise SystemExit(0 if not drift else 1)
PY

echo
echo '=== what counts as "settled" must mean the same thing in both files ==='
$PY - <<'PY' || fails=$((fails + 1))
import re
runner = open('runner.sh').read()
controller = open('controller.py').read()
run_sticky = set(re.findall(r'\$2=="([A-Z]+)"', runner))
ctl_settled = set(re.findall(r"'([A-Z]+)'", re.search(r"line\.split\('\\t'\)\[1\] in \(([^)]*)\)",
                                                      controller, re.S).group(1)))
# The two lists answer different questions and only *almost* hold the same members:
#   sticky  = do not spend GPU time deciding this again  (runner's skip-list)
#   settled = no work remains                            (controller's preview)
# SKIP (dup_stem) is in the first and not the second: a same-stem conflict is never
# re-logged, but a human still has to resolve it, so calling it done would report
# pending conflict as finished work. TESTDONE must be in NEITHER: a bounded run
# records it and deletes nothing, so it is a promise, not a commit.
extra = run_sticky - ctl_settled - {'SKIP'}
missing = ctl_settled - run_sticky
quiet = {'DONE', 'SKIPCODEC', 'SKIPSIZE', 'NOGAIN', 'OVERSIZE'}
ok = not extra and not missing and run_sticky | ctl_settled >= quiet \
    and 'TESTDONE' not in (run_sticky | ctl_settled)
print('  %s   sticky =%s' % ('ok  ' if ok else 'FAIL', sorted(run_sticky)))
print('       settled=%s  (differs only by SKIP, as designed)' % sorted(ctl_settled))
if extra:
    print('       sticky-but-not-settled beyond SKIP:', sorted(extra))
if missing:
    print('       settled but the runner would redo it:', sorted(missing))
if 'TESTDONE' in (run_sticky | ctl_settled):
    print('       TESTDONE must be neither sticky nor settled: a bounded run committed nothing')
raise SystemExit(0 if ok else 1)
PY

echo
if [ "$fails" = 0 ]; then echo 'ALL GATE TESTS PASS'; else echo "$fails FAILED"; fi
exit "$fails"

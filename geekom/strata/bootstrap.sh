#!/usr/bin/env bash
# Install the official Terminal and HIP Halo engine on the apps filesystem only.
set -euo pipefail
[[ $(hostname -s) == l-dev-ai ]] || { echo 'Run on l-dev-ai only' >&2; exit 1; }
strata_app_dir="$HOME/strata"
strata_repo="$HOME/Projects/personal/lario-llms"
mkdir -p "$strata_app_dir" "$strata_repo/geekom/strata"
[[ $(findmnt -n -o FSTYPE -T "$strata_app_dir") != xfs ]] || {
    echo 'Strata application directory must not be on XFS' >&2; exit 1;
}
curl --fail --location --retry 2 \
    https://github.com/Niko1221/Strata/releases/latest/download/install.sh \
    -o "$strata_app_dir/install.sh"
if [[ ! -d "$strata_app_dir/terminal" || ! -x "$HOME/.local/bin/strata" ]]; then
    STRATA_DATA_DIR="$strata_app_dir" STRATA_BIN_DIR="$HOME/.local/bin" \
        bash "$strata_app_dir/install.sh"
fi
"$HOME/.local/bin/strata" --version
STRATA_ENGINE_BACKEND=hip-halo "$HOME/.local/bin/strata" update --no-control \
    --components-dir "$strata_app_dir/components" --check --output json \
    > "$strata_repo/geekom/strata/engine-check.json"
python3 - "$strata_repo/geekom/strata/engine-check.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
offered = d['engine'].get('offered')
if not offered or offered.get('backend') != 'hip' or offered.get('variant') != 'halo':
    raise SystemExit('Signed feed did not offer the HIP Halo engine; stopped before engine installation')
if offered.get('version')!='0.1.50' or offered.get('sha256')!='e0399d728515286af44ce58b45534385b551b4d083264ac87c44ffc90bb77b16':
    raise SystemExit('Signed feed offers an unreviewed engine revision; update the pin explicitly')
print('Verified offered engine:', offered.get('version'), offered.get('variant'), offered.get('archs'))
PY
STRATA_ENGINE_BACKEND=hip-halo "$HOME/.local/bin/strata" update --no-control \
    --components-dir "$strata_app_dir/components" --output json \
    > "$strata_repo/geekom/strata/engine-install.json"
findmnt -T "$strata_app_dir"
echo 'Terminal and HIP Halo engine installed; no model or service was started'

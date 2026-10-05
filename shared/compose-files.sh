#!/usr/bin/env bash
# Source this helper, then call lario_compose_files <repo>. It performs no startup.
lario_compose_files() {
    local llm_root="$1" hardware marker
    LARIO_COMPOSE_FILES=(-f "$llm_root/docker-compose.yml" -f "$llm_root/docker-compose.bigcachy.yml" -f "$llm_root/docker-compose.intel.yml")
    for hardware in 7900xt rtx5080; do
        marker="${LARIO_ADMISSION_CONFIG_DIR:-$HOME/.config/lario-admission}/$hardware.active.json"
        [ -e "$marker" ] || continue
        if ! python3 - "$marker" "$hardware" <<'PY'
import json,sys
with open(sys.argv[1]) as file:data=json.load(file)
if data.get('hardware')!=sys.argv[2] or data.get('status')!='active':raise SystemExit(1)
PY
        then
            echo "Invalid $hardware admission activation marker; refusing to revert to an unauthenticated stack" >&2
            return 1
        fi
        LARIO_COMPOSE_FILES+=(-f "$llm_root/shared/admission/compose/$hardware.yml")
    done
}

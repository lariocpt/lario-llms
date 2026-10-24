#!/usr/bin/env bash
# lario-llms model-control deployment glue. Runs from the lario-models-ci repo root.
#
# Flow:
#   1. tag the tested CI image as an immutable lario/model-control:<gitSHA>
#   2. move the stable alias lario/model-control:deployed onto it
#   3. save the previous deployed image id (rollback target)
#   4. .infra (lario-home-infra main) is already checked out by the Jenkinsfile
#   5. materialize a copy of the infra model-control compose with the stable alias
#      and the ABSOLUTE config dir injected (the template uses ${HOME}; we do NOT
#      override HOME), then bring the fixed service up --no-build --no-deps
#   6. healthcheck: /login -> 200, unauth /api/state -> 401
#   on failure: retag prior image id as :deployed, compose up again, exit 1
#
# Rules honored: no HOME override, private files only (daemon-resolved binds), no
# GPU/agents/gateways/backends, no eval, no $PWD bind, no DB rollback / file copy,
# no miner or model restart.

set -euo pipefail

# --- fixed contract names (do not derive from env) ---------------------------
readonly IMAGE_REGISTRY="lario/model-control"
readonly IMAGE_ALIAS="${IMAGE_REGISTRY}:deployed"
readonly INFRA_DIR=".infra"
readonly INFRA_URL="https://github.com/lariocpt/lario-home-infra.git"
readonly INFRA_BRANCH="main"
readonly INFRA_COMPOSE="${INFRA_DIR}/containers/personal/model-control/docker-compose.yml"
readonly WORK_COMPOSE="/tmp/model-control.deployed.compose.yml"
readonly SERVICE="model-control"             # must match the service name in the infra template
readonly CONTAINER_NAME="lario-model-control"   # fixed container_name in the infra template
readonly CONFIG_DIR="/home/lario/.config/lario-model-control"   # explicit; never override HOME
readonly HEALTH_LOGIN="http://127.0.0.1:9670/login"
readonly HEALTH_STATE="http://127.0.0.1:9670/api/state"
readonly PAT_CREDENTIAL_ID="github-pat"

log()  { printf '[model-deploy] %s\n' "$*"; }
fail() { printf '[model-deploy][FAIL] %s\n' "$*" >&2; exit 1; }
require() { command -v "$1" >/dev/null 2>&1 || fail "required command missing: $1"; }

validate_sha_tag() {
    local tag="$1" sha
    sha="$(printf '%s' "$tag" | awk -F: '{print $NF}')"
    [[ "${#sha}" -ge 7 && "${#sha}" -le 40 && "$sha" =~ ^[0-9a-f]+$ ]] || fail "image tag not a short git SHA: ${tag}"
    log "validated immutable image: ${tag}"
}

http_status() { # $1=url  (python urllib inside the container, via compose exec)
    "${DC[@]}" -f "${WORK_COMPOSE}" exec -T "$SERVICE" python -c \
        "import urllib.request; print(urllib.request.urlopen('${1}',timeout=3).status)" 2>/dev/null || true
}

up_service() { # bring the fixed service up with the image override env
    LARIO_MODEL_CONTROL_IMAGE="$IMAGE_ALIAS" \
    MODEL_CONTROL_CONFIG_DIR="$CONFIG_DIR" \
    "${DC[@]}" -f "${WORK_COMPOSE}" up -d --no-build --no-deps "$SERVICE"
}

# --- preconditions -----------------------------------------------------------
require docker
if docker compose version >/dev/null 2>&1; then DC=(docker compose); else require docker-compose; DC=(docker-compose); fi
[ -f "${INFRA_COMPOSE}" ] || fail "infra compose template not found: ${INFRA_COMPOSE} (checkout step failed)"
[ -f "shared/serving/web/index.html" ] || fail "static web page missing: shared/serving/web/index.html"
GIT_SHA="$(git rev-parse --short=12 HEAD)" || fail "could not resolve git SHA"

# --- step 1+2: tag immutable + move alias (save prior id first) --------------
docker image inspect "lario/model-control:ci-test" >/dev/null 2>&1 || fail "tested CI image lario/model-control:ci-test not found"
NEW_IMAGE="${IMAGE_REGISTRY}:${GIT_SHA}"
docker tag "lario/model-control:ci-test" "$NEW_IMAGE"
validate_sha_tag "$NEW_IMAGE"

PREV_IMAGE_ID=""
if docker image inspect "$IMAGE_ALIAS" >/dev/null 2>&1; then
    PREV_IMAGE_ID="$(docker image inspect --format '{{.Id}}' "$IMAGE_ALIAS")"
    log "previous ${IMAGE_ALIAS} = ${PREV_IMAGE_ID}"
fi
docker tag "$NEW_IMAGE" "$IMAGE_ALIAS"
log "alias ${IMAGE_ALIAS} -> ${NEW_IMAGE}"

# --- step 5: materialize compose copy with image + absolute config dir ------
# The infra template uses ${HOME} binds and has no image override; we copy it and
# inject the stable alias and the ABSOLUTE config dir so no HOME override is needed.
cp "${INFRA_COMPOSE}" "${WORK_COMPOSE}"
sed -i "s#image: lario/model-control:local#image: ${IMAGE_ALIAS}#" "${WORK_COMPOSE}"
sed -i "s#\${HOME}/.config/lario-model-control#${CONFIG_DIR}#g" "${WORK_COMPOSE}"

# --- step 4: bring up model-control (no build, no deps, fixed service) ------
# A stale container from a foreign compose project would block `up`; the panel
# container is this deployment's own service, so remove it deterministically.
docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
log "compose up ${SERVICE} (image ${IMAGE_ALIAS}, config ${CONFIG_DIR})"
up_service

# --- step 6: healthcheck (login 200, unauth /api/state 401) ------------------
log "waiting for health: ${HEALTH_LOGIN} -> 200, ${HEALTH_STATE} -> 401"
HEALTHY=0
for _ in $(seq 1 30); do
    LOGIN_STATUS="$(http_status "$HEALTH_LOGIN")"
    if [ "$LOGIN_STATUS" = "200" ]; then
        STATE_STATUS="$(http_status "$HEALTH_STATE")"
        [ "$STATE_STATUS" = "401" ] && HEALTHY=1 && break
    fi
    sleep 2
done

# --- on failure: retag prior image id, compose up again, fail the build -----
if [ "$HEALTHY" -ne 1 ]; then
    log "health check failed; rolling back alias to previous image id"
    [ -n "$PREV_IMAGE_ID" ] && docker tag "$PREV_IMAGE_ID" "$IMAGE_ALIAS"
    docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
    up_service
    fail "model-control health check failed after deploy; rolled back alias (no DB rollback performed)"
fi

log "deploy ok: ${IMAGE_ALIAS} model-control running and healthy"

#!/usr/bin/env bash
set -euo pipefail
readonly service='model-control'
readonly alias='lario/model-control:deployed'
readonly manifest='.infra/containers/personal/model-control/docker-compose.yml'
[[ ${IMAGE:-} =~ ^lario/model-control:[0-9a-f]{40}$ ]] || { echo 'Missing tested immutable image' >&2; exit 1; }
[[ $(git rev-parse HEAD) == "${IMAGE##*:}" ]] || exit 1
[[ ${SOURCE_BRANCH:-} == main ]] || { echo 'Deployment requires main' >&2; exit 1; }
docker image inspect "$IMAGE" >/dev/null
docker compose -f "$manifest" config --quiet
previous=$(docker image inspect --format '{{.Id}}' "$alias" 2>/dev/null || true)
up() { docker compose -f "$manifest" up -d --no-build --no-deps "$service"; }
healthy() { docker compose -f "$manifest" exec -T "$service" python -c 'import urllib.request,urllib.error; assert urllib.request.urlopen("http://127.0.0.1:9670/login",timeout=3).status == 200; exec("try:\n urllib.request.urlopen(\"http://127.0.0.1:9670/api/state\",timeout=3)\nexcept urllib.error.HTTPError as e:\n assert e.code == 401\nelse:\n raise AssertionError(\"Private state exposed\")")' >/dev/null 2>&1; }
rollback() {
  if [[ -n "$previous" ]]; then
    docker tag "$previous" "$alias"
    up || echo 'Rollback compose failed; operator attention required' >&2
  else
    docker compose -f "$manifest" stop "$service" || true
    docker image rm "$alias" >/dev/null 2>&1 || true
    echo 'No previous image; failed service stopped' >&2
  fi
}
docker tag "$IMAGE" "$alias"
if ! up; then rollback; exit 1; fi
for attempt in {1..30}; do
  if healthy; then echo 'Deployment healthy'; exit 0; fi
  sleep 2
done
rollback
exit 1

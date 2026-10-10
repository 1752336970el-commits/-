#!/usr/bin/env bash
set -eu
cd "$(dirname "$0")/.."
task_project="$(pwd)"
export DOCKER_CONFIG="$task_project/runtime/docker"
mkdir -p "$DOCKER_CONFIG"
python tools/mvp.py init
docker compose pull db crm daemon
if ! docker image inspect iecho/maps:1.18.1-verified >/dev/null 2>&1; then
    IECHO_MAPS_BUILD_DIR="${TMPDIR:-/tmp}/iecho-maps-build" python -u tools/build_maps.py --native
fi
docker compose -f compose.yaml -f compose.cloud.yaml --profile maps up -d
python tools/mvp.py setup
python tools/mvp.py health
python tools/check_maps.py

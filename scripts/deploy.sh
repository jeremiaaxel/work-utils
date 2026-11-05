#!/usr/bin/env bash
#
# Build the images and restart the running containers with them.
#
#   ./scripts/deploy.sh          # production
#   ./scripts/deploy.sh dev      # dev stack
#
# `up -d` recreates a container when its image changed, so this is all it
# takes to roll out a new build.

set -euo pipefail

# Resolve the repo root from the script's real location, so the script also
# works when it is called from another directory or through a symlink.
ROOT="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/.." && pwd)"
cd "$ROOT"

PROFILE="${1:-production}"
COMPOSE=(docker compose --profile "$PROFILE")

echo "==> Building the $PROFILE images"
"${COMPOSE[@]}" build

echo "==> Restarting the $PROFILE containers"
"${COMPOSE[@]}" up -d --remove-orphans

# `up -d` retagged the services, so the previous build's layers are now
# dangling. Remove those only — the build cache (with the uv wheel cache
# mount) is what makes the next build quick and stays.
echo "==> Removing dangling images"
docker image prune -f

echo "==> Done"
"${COMPOSE[@]}" ps

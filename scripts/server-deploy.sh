#!/usr/bin/env bash
#
# The deploy command the CI runs on the server, over SSH.
#
# Install it on the VPS and point the runner's SSH key at it:
#
#   sudo install -m 0755 scripts/server-deploy.sh /usr/local/bin/deploy-workutils
#
# The image is built in CI and pushed to the registry, so this server never
# downloads the dependencies or builds anything: it only pulls the layers
# that changed and restarts the containers. The running app keeps serving
# while the pull happens.
#
# The pull happens before the containers are replaced, so a failed pull
# leaves the running app untouched.

set -euo pipefail

REPO_DIR="${REPO_DIR:-/opt/work-utils}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8000/api/jp-reader/records}"

cd "$REPO_DIR"

# Every deploy pulls images tagged with the new commit, and the old pair
# would otherwise stay behind forever. After a healthy deploy, remove
# images nothing references — the two just-started ones and redis are in
# use, so they survive. A rollback wants the previous tag back, so only
# what is older than a week goes. Volumes (redis data, OCR models) and
# the build cache are not touched.
prune_images() {
    # Non-fatal: a failed prune must not turn a healthy deploy into a failure.
    docker image prune -af --filter "until=168h" || echo "image prune failed (ignored)" >&2
}

echo "==> Fetching the new code"
git pull --ff-only

# The images are tagged with the commit they were built from.
export IMAGE_TAG="$(git rev-parse HEAD)"

echo "==> Pulling the images for $IMAGE_TAG"
docker compose --profile production pull

echo "==> Restarting the containers"
docker compose --profile production up -d --remove-orphans

echo "==> Waiting for the app to answer"
for _ in $(seq 1 30); do
    if curl -fsS "$HEALTH_URL" >/dev/null 2>&1; then
        echo "==> Deployed $IMAGE_TAG"
        prune_images
        exit 0
    fi
    sleep 2
done

echo "the app did not come up — the previous containers are still around" >&2
docker compose --profile production ps >&2
exit 1

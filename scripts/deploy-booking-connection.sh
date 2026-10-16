#!/usr/bin/env bash
# Existing planner installation only; preserves the old image for both services.
set -Eeuo pipefail
cd /mnt/apps/weddingplannercouples
umask 077
if [[ -n "$(git status --porcelain)" ]]; then
  echo 'STOP: planner checkout has local changes. Preserve them before updating.'; exit 1
fi
compose=(docker compose -f compose.yaml)
"${compose[@]}" config --quiet
previous_commit=$(git rev-parse HEAD)
rollback_dir="/mnt/apps_snaps_progs/weddingplannercouplesbup/before-v107-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$rollback_dir"
cp compose.yaml "$rollback_dir/compose.yaml"
echo '1/4 Backing up planner data...'
"${compose[@]}" exec -T worker python manage.py backup
container=$("${compose[@]}" ps -q web)
test -n "$container"
previous_image=$(docker inspect --format '{{.Image}}' "$container")
rollback_image="weddingplanner-v107-rollback:$(date +%Y%m%d-%H%M%S)"
docker image tag "$previous_image" "$rollback_image"
cat > "$rollback_dir/rollback.yaml" <<EOF
services:
  web:
    image: $rollback_image
    pull_policy: never
  worker:
    image: $rollback_image
    pull_policy: never
EOF
printf 'Rollback command:\nsudo docker compose -f %q -f %q up -d --no-build --force-recreate\n' "$rollback_dir/compose.yaml" "$rollback_dir/rollback.yaml"
printf 'Previous code commit: %s\n' "$previous_commit"
echo '2/4 Pulling and building while the current planner stays running...'
git pull --ff-only
"${compose[@]}" config --quiet
"${compose[@]}" build web
echo '3/4 Restarting only the planner web and worker...'
"${compose[@]}" up -d --force-recreate
trap 'echo "Update failed. Use the rollback command printed above."' ERR
echo '4/4 Checking planner version and health...'
for attempt in {1..30}; do
  if "${compose[@]}" exec -T web python -c 'import json,urllib.request; d=json.load(urllib.request.urlopen("http://127.0.0.1:8000/healthz",timeout=4)); assert d["status"]=="ok" and d["version"]=="1.0.7"' >/dev/null 2>&1; then
    "${compose[@]}" ps
    echo 'Planner 1.0.7 is responding. The new booking connection is paused until you set it up.'
    exit 0
  fi
  sleep 2
done
"${compose[@]}" logs --tail=50 web worker
exit 1

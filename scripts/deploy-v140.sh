#!/usr/bin/env bash
# Update only this planner. Rehearse a real archive restore before restarting.
set -Eeuo pipefail
cd /mnt/apps/weddingplannercouples
umask 077
RELEASE_COMMIT=$(git rev-parse HEAD)
compose=(docker compose -f compose.yaml)
backup_dir=/mnt/apps_snaps_progs/weddingplannercouplesbup
restore_dir=/mnt/apps_snaps_progs/weddingplannercouples-restore-test

if [[ -n "$(git status --porcelain)" ]]; then
  echo 'STOP: planner checkout has local changes. Preserve them before updating.'; exit 1
fi
"${compose[@]}" config --quiet
previous_commit=$(git rev-parse HEAD)
rollback_dir="$backup_dir/before-v140-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$rollback_dir"
cp compose.yaml "$rollback_dir/compose.yaml"
cp /mnt/apps/weddingplannercouples.env "$rollback_dir/server.env"

echo '1/5 Backing up planner data...'
"${compose[@]}" exec -T worker python manage.py backup
archive=$(find "$backup_dir" -maxdepth 1 -type f -name 'planner-*.tar.gz' -printf '%T@ %p\n' | sort -nr | head -1 | cut -d' ' -f2-)
test -n "$archive"

container=$("${compose[@]}" ps -q web)
test -n "$container"
previous_image=$(docker inspect --format '{{.Image}}' "$container")
rollback_image="weddingplanner-v140-rollback:$(date +%Y%m%d-%H%M%S)"
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
printf 'Rollback command:\nsudo docker compose -f %q -f %q up -d --no-build --force-recreate web worker\n' "$rollback_dir/compose.yaml" "$rollback_dir/rollback.yaml"
printf 'Previous code commit: %s\n' "$previous_commit"

echo '2/5 Building while the current planner stays running...'
echo "Building checked-out release $RELEASE_COMMIT"
[[ "$(git rev-parse HEAD)" == "$RELEASE_COMMIT" ]] || { echo 'STOP: checkout does not match this release. The running planner was not restarted.'; exit 1; }
"${compose[@]}" config --quiet
"${compose[@]}" build web
# Read code as the production non-root user before touching either live service.
docker run --rm --network none --read-only --tmpfs /tmp:mode=1777 --user 1000:1000 \
  weddingplannercouples:local python -c 'from app.server import VERSION; from app.wbm_timings import SCHEMA; from app.admin_backups import process_requested_backup; import app.worker; assert VERSION=="1.4.0"; assert "wbm_timing_submissions" in SCHEMA'


echo '3/5 Testing archive recovery in an isolated container...'
install -d -o 1000 -g 1000 -m 0700 "$restore_dir"
docker run --rm --network none --read-only --user 1000:1000 \
  --mount "type=bind,src=$backup_dir,dst=/backups,readonly" \
  --mount "type=bind,src=$restore_dir,dst=/restore-test" \
  weddingplannercouples:local python scripts/test_restore.py "/backups/$(basename "$archive")" --work-dir /restore-test

trap 'echo "Update failed. Use the rollback command printed above."' ERR
echo '4/5 Restarting only the planner web and worker...'
"${compose[@]}" up -d --force-recreate web worker
echo '5/5 Checking planner version and health...'
for attempt in {1..30}; do
  if "${compose[@]}" exec -T web python -c 'import json,urllib.request; d=json.load(urllib.request.urlopen("http://127.0.0.1:8000/healthz",timeout=4)); assert d["status"]=="ok" and d["version"]=="1.4.0"' >/dev/null 2>&1; then
    worker_id=$("${compose[@]}" ps -q worker)
    [[ -n "$worker_id" && "$(docker inspect --format '{{.State.Running}}' "$worker_id")" == true ]] || { echo 'Worker is not running.'; exit 1; }
    "${compose[@]}" exec -T worker python -c 'from app.server import VERSION; assert VERSION=="1.4.0"'
    "${compose[@]}" ps
    echo 'Planner 1.4.0 is responding. Open the couple planner to check the new dashboard, all pages and mobile navigation.'
    exit 0
  fi
  sleep 2
done
"${compose[@]}" logs --tail=50 web worker
exit 1


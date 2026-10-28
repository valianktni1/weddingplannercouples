#!/usr/bin/env bash
# Preserve local Control Centre configuration and build a fresh, immutable release.
set -Eeuo pipefail
cd /mnt/apps/weddingplannercouples
umask 077
RELEASE_COMMIT=$(git rev-parse HEAD)
compose=(docker compose -f "$PWD/compose.yaml")
backup_dir=/mnt/apps_snaps_progs/weddingplannercouplesbup
restore_dir=/mnt/apps_snaps_progs/weddingplannercouples-restore-test

# compose.yaml and untracked deployment artifacts belong to the installation.
# All other tracked code must match the release being archived.
if ! git diff --quiet HEAD -- . ':!compose.yaml'; then
  echo 'STOP: planner code has local changes outside compose.yaml. Preserve them before updating.'; exit 1
fi
if ! "${compose[@]}" config --help | grep -q -- '--no-env-resolution'; then
  echo 'STOP: this Docker Compose needs --no-env-resolution support. Existing planner is unchanged.'; exit 1
fi
"${compose[@]}" config --quiet
stamp="$(date +%Y%m%d-%H%M%S)-$$"
rollback_dir="$backup_dir/before-v196-$stamp"
release_dir="$PWD/deployment-releases/planner-v196-$stamp"
new_image="weddingplanner-v196:$stamp"
mkdir -p "$rollback_dir" "$release_dir"
cp compose.yaml "$rollback_dir/original-compose.yaml"
# Retain env_file references instead of flattening secrets into service environment.
"${compose[@]}" config --no-env-resolution --format json > "$rollback_dir/current.json"
for service in web worker; do
  container=$("${compose[@]}" ps -q "$service")
  test -n "$container"
  previous_image=$(docker inspect --format '{{.Image}}' "$container")
  tag="weddingplanner-v196-rollback:$stamp-$service"
  docker image tag "$previous_image" "$tag"
  if [[ "$service" == web ]]; then web_rollback_image="$tag"; else worker_rollback_image="$tag"; fi
done
python3 scripts/prepare_v140_release.py "$rollback_dir/current.json" "$release_dir" "$new_image" "$rollback_dir" "$web_rollback_image" "$worker_rollback_image"
next=(docker compose -f "$rollback_dir/next.json")
"${next[@]}" config --quiet
printf 'Rollback command:\nsudo docker compose -f %q up -d --no-build --pull never --force-recreate web worker\n' "$rollback_dir/rollback.json"
printf 'Original configuration saved in: %s\n' "$rollback_dir"

# Git archive excludes private env files, deployment folders and local compose changes.
(umask 022; git archive "$RELEASE_COMMIT" | tar -x -C "$release_dir")
[[ "$(git rev-parse HEAD)" == "$RELEASE_COMMIT" ]] || { echo 'STOP: release changed during preparation.'; exit 1; }

echo '1/5 Backing up planner data...'
"${compose[@]}" exec -T worker python manage.py backup
archive=$(find "$backup_dir" -maxdepth 1 -type f -name 'planner-*.tar.gz' -printf '%T@ %p\n' | sort -nr | head -1 | cut -d' ' -f2-)
test -n "$archive"

echo '2/5 Building the new release while the current planner stays running...'
"${next[@]}" build web
docker run --rm --network none --read-only --tmpfs /tmp:mode=1777 --user 1000:1000 \
  "$new_image" python -c 'from app.server import VERSION; from app.guest_experience import SCHEMA as GUEST_SCHEMA; from app.bespoke import SCHEMA as BESPOKE_SCHEMA; from app.trial_interest import SCHEMA as INTEREST_SCHEMA; from app.wbm_timings import SCHEMA; from app.admin_backups import process_requested_backup; from app.couple_deletion import process_deletion; import app.worker; import app.control_centre; assert VERSION=="1.9.6"; assert "guest_replies" in GUEST_SCHEMA; assert "bespoke_orders" in BESPOKE_SCHEMA; assert "trial_interest" in INTEREST_SCHEMA; assert "wbm_timing_submissions" in SCHEMA'

echo '3/5 Testing archive recovery in an isolated container...'
install -d -o 1000 -g 1000 -m 0700 "$restore_dir"
docker run --rm --network none --read-only --user 1000:1000 \
  --mount "type=bind,src=$backup_dir,dst=/backups,readonly" \
  --mount "type=bind,src=$restore_dir,dst=/restore-test" \
  "$new_image" python scripts/test_restore.py "/backups/$(basename "$archive")" --work-dir /restore-test

# Refuse to overwrite configuration changed by another administrator during the build.
cmp -s compose.yaml "$rollback_dir/original-compose.yaml" || { echo 'STOP: configuration changed during the update. Planner was not restarted.'; exit 1; }

# Only now persist the new build context/image, retaining installation settings.
trap 'echo "Update failed. Use the rollback command printed above. Your original configuration is saved."' ERR
install -m 0600 "$rollback_dir/next.json" "$PWD/.compose-v196-$stamp.tmp"
mv "$PWD/.compose-v196-$stamp.tmp" "$PWD/compose.yaml"
echo '4/5 Restarting only the planner web and worker...'
"${compose[@]}" up -d --no-build --pull never --force-recreate web worker
echo '5/5 Checking planner version and health...'
for attempt in {1..30}; do
  if "${compose[@]}" exec -T web python -c 'import json,urllib.request; d=json.load(urllib.request.urlopen("http://127.0.0.1:8000/healthz",timeout=4)); assert d["status"]=="ok" and d["version"]=="1.9.6"' >/dev/null 2>&1; then
    worker_id=$("${compose[@]}" ps -q worker)
    [[ -n "$worker_id" && "$(docker inspect --format '{{.State.Running}}' "$worker_id")" == true ]] || { echo 'Worker is not running.'; exit 1; }
    "${compose[@]}" exec -T worker python -c 'from app.server import VERSION; assert VERSION=="1.9.6"'
    "${compose[@]}" ps
    echo 'Planner 1.9.6 is responding. Permanent couple deletion with managed backup cleanup.'
    exit 0
  fi
  sleep 2
done
echo 'Planner health check failed. Use the rollback command printed above.'
exit 1


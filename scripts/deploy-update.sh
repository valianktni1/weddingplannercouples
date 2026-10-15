#!/usr/bin/env bash
set -euo pipefail
cd /mnt/apps/weddingplannercouples
if [[ -n "$(git status --porcelain)" ]]; then
  echo 'Your checkout has local changes. Resolve them before updating.'
  exit 1
fi
old_commit=$(git rev-parse HEAD)
docker compose exec -T worker python manage.py backup
git pull --ff-only
docker compose config --quiet
docker compose up -d --build
echo "Previous commit for rollback: $old_commit"
docker compose ps
for attempt in {1..60}; do
  if curl --fail --silent http://127.0.0.1:30063/healthz; then exit 0; fi
  sleep 2
done
echo 'The app did not become healthy. Check docker compose logs before continuing.' >&2
exit 1

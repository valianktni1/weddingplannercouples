#!/usr/bin/env bash
# Repair code permissions without changing live data or dataset permissions.
set -Eeuo pipefail
cd /mnt/apps/weddingplannercouples
compose=(docker compose -f compose.yaml)
if [[ -n "$(git status --porcelain)" ]]; then
  echo 'STOP: local Git edits need preserving before this recovery.'; exit 1
fi
echo '1/4 Fetching the permission repair...'
(umask 022; git pull --ff-only)
grep -Fq 'chmod -R a+rX /app/app' Dockerfile
"${compose[@]}" config --quiet
echo '2/4 Rebuilding the fixed image; its build checks imports as the planner user...'
"${compose[@]}" build web
echo '3/4 Backing up using a one-off worker (the stopped worker is not required)...'
"${compose[@]}" run --rm --no-deps worker python manage.py backup
echo '4/4 Starting planner web and worker...'
"${compose[@]}" up -d --force-recreate
for attempt in {1..30}; do
  if "${compose[@]}" exec -T web python -c 'import json,urllib.request; d=json.load(urllib.request.urlopen("http://127.0.0.1:8000/healthz",timeout=4)); assert d["status"]=="ok" and d["version"]=="1.0.7"' >/dev/null 2>&1; then
    "${compose[@]}" ps
    echo 'Planner 1.0.7 is responding. Check the website before updating the booking app.'
    exit 0
  fi
  sleep 2
done
"${compose[@]}" logs --tail=60 web worker
exit 1

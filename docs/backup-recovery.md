# Planner backups and recovery

## Download a complete data backup

Sign in as the superadmin at /ivoryadmin. Open Storage & backups, select Create
backup now, wait for Completed, then use Download beside that archive. The worker
normally starts a queued request within 30 seconds. You can also download any
existing completed scheduled backup. Downloads still work if the worker is down.

The .tar.gz is a compressed archive, equivalent in purpose to a ZIP. It contains:

- planner.sqlite3: all couples/accounts, plans, settings, invitations, payment
  records, documents metadata, booking links and final-timings receipts.
- files/: uploaded documents and images referenced by the saved database.
- app-secret: the application encryption key needed for protected settings.

It contains private data and credentials. Keep a copy securely away from the NAS.
The archive is compressed, not encrypted. Daily retention can remove older
server-side copies; it does not remove a copy you downloaded.

The worker takes a consistent SQLite backup and snapshots the referenced immutable
files before compression. An incomplete archive is never offered for download.
Manual requests reuse this existing backup function; they do not send emails,
change couple plans or reschedule the daily backup. Repeated clicks while queued
or running reuse the same request. A failed request leaves prior archives intact.

## Keep the deployment configuration too

The data archive does not include files outside the app's data volume. Keep:

- /mnt/apps/weddingplannercouples.env (server environment and external credentials)
- /mnt/apps/weddingplannercouples/compose.yaml
- A copy of the application repository at the deployed release, or continued
  access to its GitHub repository.

Restore the same release first (or a tested later compatible release). Preserve
the encryption key inside the archive. The backup is not a Docker image and does
not contain TrueNAS, proxy, DNS or payment-provider configuration.

## Test recovery without touching the running planner

With the planner code checked out and its current Docker image built, select an
archive already in /mnt/apps_snaps_progs/weddingplannercouplesbup. Substitute its
actual basename below. The deployment scripts also perform this isolated test.

```bash
cd /mnt/apps/weddingplannercouples
ARCHIVE_NAME='planner-YYYYMMDD-HHMMSS-MICROSECONDS.tar.gz'
sudo install -d -o 1000 -g 1000 -m 0700 /mnt/apps_snaps_progs/weddingplannercouples-restore-test
sudo docker run --rm --network none --read-only --user 1000:1000 \
  --mount type=bind,src=/mnt/apps_snaps_progs/weddingplannercouplesbup,dst=/backups,readonly \
  --mount type=bind,src=/mnt/apps_snaps_progs/weddingplannercouples-restore-test,dst=/restore-test \
  weddingplannercouples:local python scripts/test_restore.py "/backups/$ARCHIVE_NAME" --work-dir /restore-test
```

The test validates archive paths, database integrity, every referenced upload,
then starts the real app against the temporary recovered installation. No worker
runs and networking is disabled, so it cannot email couples. The temporary
installation is removed afterward.

## Recover after a reinstall: empty data folder only

These are disaster-recovery steps, not an everyday deployment. Stop web and
worker before restoring. Keep an independent copy or snapshot of any surviving
data. Do not delete a working data directory to make these commands pass.

1. Restore the application checkout to /mnt/apps/weddingplannercouples and its
   .env file to /mnt/apps/weddingplannercouples.env. Restore compose.yaml and build
   the web image. Leave web and worker stopped.
2. Put the chosen downloaded archive back into the server backup folder above.
3. Provide an EMPTY data folder at the data-volume path in compose.yaml. On a
   fresh installation only, create it with owner 1000:1000 and mode 0700. If an
   existing installation occupies that path, preserve it and arrange a separate
   empty recovery volume first. Do not remove existing files through this guide.
4. Run the following, substituting the real archive basename:

```bash
cd /mnt/apps/weddingplannercouples
ARCHIVE_NAME='planner-YYYYMMDD-HHMMSS-MICROSECONDS.tar.gz'
sudo docker compose -f compose.yaml stop web worker
sudo docker run --rm --network none --read-only --user 1000:1000 \
  --mount type=bind,src=/mnt/apps_snaps_progs/weddingplannercouplesbup,dst=/backups,readonly \
  --mount type=bind,src=/mnt/photographers_data/weddingplannercouplesdata,dst=/data \
  weddingplannercouples:local python scripts/restore_data.py "/backups/$ARCHIVE_NAME" --destination /data
```

The recovery tool refuses a nonempty destination. It validates and boots the
recovered app in a staging folder before moving the recovered database, key and
files into place. It does not start email processing. The original archive is
never edited. It needs space for the unpacked backup on the destination volume.

5. Once recovery succeeds, check APP_URL, mail/payment environment configuration,
   reverse proxy and volumes before allowing the worker to send anything. Then:

```bash
sudo docker compose -f compose.yaml up -d web worker
sudo docker compose -f compose.yaml ps
```

Check System health, a known couple's saved plan and an uploaded file. A backup
is a point-in-time copy: later changes are not included, and any messages still
queued at the backup date remain queued after recovery. Review outstanding email
before restarting a recovered worker; do not assume external mail/payment events
have been reversed. Restoring an older backup may also require reconnecting a
booking key that was rotated afterward.

# Ivory Digital Wedding Planner — v1.0.1

This is the server-backed first release, not the earlier HTML demonstration. It includes a shared planner, partner accounts, wedding websites and individual guest RSVPs, plus Mark’s superadmin area.

See **AUDIT-REPORT.md** for repaired workflows and verification.

## Confirmed installation

| Setting | Value |
|---|---|
| Public URL | https://planner.ivorydigital.uk |
| Administrator | https://planner.ivorydigital.uk/ivoryadmin |
| Couple’s planner | https://planner.ivorydigital.uk/app |
| Wedding website | /weddings/the-couples-chosen-address |
| Host port | 30061 |
| Application checkout | /mnt/apps/weddingplannercouples |
| Couples’ database and files | /mnt/photographers_data/weddingplannercouplesdata |
| Backup archives | /mnt/apps_snaps_progs/weddingplannercouplesbup |
| Secrets file, outside Git | /mnt/apps/weddingplannercouples.env |
| Dockge stack name | weddingplannercouples |

The database is SQLite on your local ZFS dataset, with WAL and transaction checks. There is no external database service, no database port and no connection to your booking/gallery databases. The web container and scheduled worker share only this app’s data. Do not put the database on an SMB/NFS share.

## What works in this release

- Email-verified accounts, password recovery and one-time partner invitations: two separate logins share one wedding.
- Guided setup, optional unknown date/budget, shared tasks and named owners.
- Supplier bookings, individual instalments, partial/complete payments, payment dates, validation, next-payment updates and over-budget warnings.
- Month calendar with payment dates, task deadlines, appointments and event editing.
- Separate preparation locations for both partners, travel to ceremony and reception, fixed ceremony/meal commitments, photo groups, supplier coverage and a timing rehearsal.
- Individual guests grouped into invitation households: meals, dietary information, access needs, day/evening invitation and table labels.
- Wedding website editor with three presentation styles, cover image, welcome text, venues, travel/accommodation, FAQs, gift link, private draft, optional code and publish control.
- Personal invitation links; each invited person can reply separately and update their answer. Evening-only invitation pages omit ceremony details. A general website page includes whatever the couple publishes; protect it if information should be invitation-only.
- Private supplier PDFs and re-encoded cover photographs: 10 MB per file, 250 MB per wedding.
- Copy-ready wedding-party, photographer and venue handovers; full private JSON/text export. Family notes are omitted from guest and venue handovers.
- Couples can grant/revoke 30-minute read-only payment support. Admin support does not expose family notes or guest dietary/access data.
- Superadmin: access extensions/free access/suspension, pricing and launch switches, email settings and delivery history, storage/backup results, support permission and audit log.
- Admin authenticator enrolment, replay-resistant TOTP and single-use recovery codes.
- SMTP email queue with retries, deduplicated payment reminders and weekly round-ups. Finished weddings stop planning reminders.
- Optional Stripe one-time Checkout and signed, amount-checked, idempotent webhooks. The app does not pay wedding suppliers or store card details.
- Daily consistent backups of the database, files and encryption key; archive verification before retention.
- Responsive layouts, explicit heading contrast, and system/manual light/dark mode.

## Important first-release boundaries

- This is a deployable **pilot release**. Begin with a few test couples before opening paid sign-ups widely. The backend and served-page interactions have automated checks; the Docker image and TrueNAS deployment still need verification on your machine.
- No default price is silently applied. Price, refund terms and access settings are controlled by your administrator. Public sign-ups and checkout start closed.
- SMTP credentials, Stripe credentials, DNS and TLS cannot be filled in without your accounts. Configure these before enabling their features.
- Payment ticks are the couple’s records, not confirmation from suppliers. Automatic bank reconciliation is not included.
- The rehearsal models a single wedding day using entered allowances. It does not forecast weather, live traffic or sunset. An outdoor-light cutoff can be entered after it is checked separately.
- Table assignments are individual labels; an interactive floor-plan editor is not included. Calendar phone subscriptions, multi-day scheduling and custom wedding domains are not included in this release.
- Handovers are text/JSON, not designed PDF layouts. Photographs are covers, not a duplicate guest-photo/gallery system.
- Mail providers can very occasionally accept an email and disconnect before acknowledging it. Stable Message-IDs and reminder dedupe reduce duplicates but do not promise mathematically exactly-once delivery.
- Independent partner edits and RSVPs merge when possible. Conflicting edits to the same field show recovery options: download the unsaved copy, then reload to review the latest plan. There is no offline or live-push editing.

## 1. Put the repository on GitHub using your usual workflow

1. Extract the supplied ZIP. Open the **weddingplannercouples** folder; Dockerfile and compose.yaml are at its root.
2. In GitHub Desktop choose **File → Add local repository**. If prompted, create a repository here.
3. Suggested repository name: **weddingplannercouples**. Publish it to your account, ideally private.
4. Do not commit passwords, API keys, live database files or backups. `.gitignore` protects the usual files; the production environment file is outside the checkout.

This guide uses `https://github.com/valianktni1/weddingplannercouples.git` **only as the suggested address**. Create/publish that repository first. If you choose another name, substitute its real URL below. Private repository authentication must use your usual Git credentials or SSH; do not paste a token into a command/URL.

## 2. Create the isolated datasets/folders

In TrueNAS, create the three datasets corresponding to the confirmed paths if they do not exist. The parent `apps`, `photographers_data` and `apps_snaps_progs` datasets already exist in your setup. Do not rename or change permissions on those parents.

For an empty first installation:

```bash
sudo install -d -m 0755 /mnt/apps/weddingplannercouples
sudo chown "$(id -u):$(id -g)" /mnt/apps/weddingplannercouples
sudo install -d -o 1000 -g 1000 -m 0750 /mnt/photographers_data/weddingplannercouplesdata
sudo install -d -o 1000 -g 1000 -m 0750 /mnt/apps_snaps_progs/weddingplannercouplesbup
git clone https://github.com/valianktni1/weddingplannercouples.git /mnt/apps/weddingplannercouples
cd /mnt/apps/weddingplannercouples
```

UID/GID 1000 is the container account. For datasets with existing ACLs, use the TrueNAS permission editor to grant this account write access **only to these new datasets**. The above `chown` of the app folder is not recursive and should only be used for this new empty installation. Stop if any path already contains another app’s data.

## 3. Prepare your private environment file

```bash
sudo cp /mnt/apps/weddingplannercouples/.env.example /mnt/apps/weddingplannercouples.env
sudo chown "$(id -u):$(id -g)" /mnt/apps/weddingplannercouples.env
sudo chmod 600 /mnt/apps/weddingplannercouples.env
sudo nano /mnt/apps/weddingplannercouples.env
```

Fill SMTP_HOST, SMTP_PORT, SMTP_SECURITY (`starttls` for port 587 or `ssl` for port 465), SMTP_USER and SMTP_PASSWORD. Leave Stripe fields blank until needed. Leave SECURE_COOKIES=1 for HTTPS deployment.

Compose reads this external file before starting the containers. Docker injects the values; the non-root application does not need permission to open the environment file itself. The app encryption key is created once inside the data folder; keep it in backups. Losing it prevents decrypting administrator authenticator secrets.

## 4. Add the Dockge stack

In Dockge create **weddingplannercouples**, and paste the supplied **compose.yaml**. Its build context is the absolute application path, so it works even though Dockge keeps its own stack file under `/mnt/apps/dockge/data/weddingplannercouples`.

Or use these commands in the repository folder:

```bash
cd /mnt/apps/weddingplannercouples
docker compose config --quiet
docker compose up -d --build
docker compose ps
curl --fail http://127.0.0.1:30061/healthz
```

Expected health result contains `"status":"ok"`. Only port 30061 is published. SQLite and the worker have no public ports. Keep the Dockge copy of the YAML identical to the repository copy when changing deployment settings; both share the same Compose project name.

## 5. Point DNS and Nginx Proxy Manager at the new app

1. Create `planner.ivorydigital.uk` in your DNS, using the same public destination as your other hosted services.
2. NPM Proxy Host: domain **planner.ivorydigital.uk**, scheme **http**, forwarding IP **192.168.24.10**, port **30061**.
3. Obtain a Let’s Encrypt certificate, then enable Force SSL. This is an independent proxy host; do not alter the booking/gallery hosts.
4. Check https://planner.ivorydigital.uk/healthz.
5. If larger cover/PDF uploads get rejected by NPM, set `client_max_body_size 12m;` for this host only.

HTTPS is required for the secure login cookie. A health check can use the LAN HTTP address, but sign-in must use the HTTPS domain. For a temporary LAN-only test you can set SECURE_COOKIES=0 and recreate the containers; restore 1 before opening the app publicly.

## 6. Create your administrator account

Run this interactively. Use the email address you want for this new app; the example is not a pre-created account:

```bash
cd /mnt/apps/weddingplannercouples
docker compose exec web python manage.py create-admin --email mark@perfectweddingsbymark.uk
```

Enter a new password twice. It is hidden and not printed or included in shell history. Open **https://planner.ivorydigital.uk/ivoryadmin**, sign in, add the authenticator and store your eight recovery codes securely. There is no shipped default admin password.

## 7. Complete launch settings and test the couple’s journey

1. Admin → Email: set your sender and reply-to email. Send a test; check that the email history says **sent** and it actually arrives.
2. Admin → Pricing: choose trial length, price/access rule if desired, and enter your own terms and privacy notice. Public sign-ups require SMTP and these notices.
3. Open sign-ups for your test. Keep checkout closed.
4. Register a test couple, verify their email, complete setup and invite a second email address.
5. Add a supplier, instalments, a partial payment, a guest and a private PDF. Open on the second device and confirm the shared state.
6. Publish a wedding website. Create a personal invitation and RSVP as a guest; verify that the couple’s guest record updates.
7. Grant the test wedding complimentary access. Check trial/free access is not counted as sales.
8. Run a manual backup, extract to a separate test folder and verify it before relying on the schedule.

## 8. Optional Stripe checkout

Use the Stripe account belonging to Ivory Digital. Add its secret key and webhook signing secret to the external environment file. The webhook destination is:

`https://planner.ivorydigital.uk/api/stripe/webhook`

Subscribe to `checkout.session.completed` and `checkout.session.async_payment_succeeded`. Recreate both services after changing environment values:

```bash
cd /mnt/apps/weddingplannercouples
docker compose up -d --force-recreate
```

Use Stripe test mode first, a test purchase and a webhook delivery test. Then choose price/refund terms and enable checkout in admin. The return from the payment page does not itself grant access: only a verified Stripe webhook does. The stored purchase keeps its original price, access date and refund terms. Refund processing is manual in Stripe in v1; contact the couple and adjust access deliberately if necessary. Stripe account tax/invoice settings are not configured by this app.

## Backups and restore tests

```bash
cd /mnt/apps/weddingplannercouples
docker compose exec worker python manage.py backup
docker compose logs --tail 60 worker
```

To verify a chosen archive, substitute its actual filename. This does **not** overwrite live data:

```bash
sudo install -d -o 1000 -g 1000 -m 0750 /mnt/apps_snaps_progs/weddingplannercouples-restore-test
sudo tar -xzf /mnt/apps_snaps_progs/weddingplannercouplesbup/planner-YYYYMMDD-HHMMSS.tar.gz -C /mnt/apps_snaps_progs/weddingplannercouples-restore-test
python3 /mnt/apps/weddingplannercouples/scripts/verify-backup.py /mnt/apps_snaps_progs/weddingplannercouples-restore-test
```

For a full restore rehearsal, start a separately named Compose project with that extracted directory mounted as `/data`, a different free port, worker disabled and SMTP/Stripe disabled. Sign in and inspect records/files. Never start two workers against the same live data.

Actual live recovery: take a new snapshot/copy, stop **only this stack**, restore the chosen database/files/app-secret into its isolated data directory, set owner 1000:1000, then restart and test. Do not restore SQLite files over a running app. The backup folder is local; add it to your existing off-server backup routine. Keep the external `.env` in a separate secure backup.

## Updates, snapshot and rollback

Before first deployment and every update, use the TrueNAS snapshot UI for these specific new datasets. Example dataset names (verify with `zfs list` first):

```bash
sudo zfs snapshot apps/weddingplannercouples@before-update
sudo zfs snapshot photographers_data/weddingplannercouplesdata@before-update
```

Use a fresh snapshot name each time. Actual pool/dataset names can differ from mount paths; never run those example commands against an unverified dataset name.

After GitHub Desktop pushes your changes:

```bash
cd /mnt/apps/weddingplannercouples
bash scripts/deploy-update.sh
```

It makes a backup, refuses to overwrite local Git edits, pulls with `--ff-only`, rebuilds this stack and prints the previous commit. Check health and admin/couple sign-in after the update. The script is for an already-running stack; use the first-install commands for a new installation. To return to that previous code:

```bash
cd /mnt/apps/weddingplannercouples
git checkout THE_PREVIOUS_COMMIT_PRINTED_BY_THE_SCRIPT
docker compose up -d --build
curl --fail http://127.0.0.1:30061/healthz
```

A database rollback requires stopping the app and a deliberate restore; do not assume changing Git restores data. v1 uses a stable schema with `CREATE TABLE IF NOT EXISTS`; future schema migrations must include a rollback plan.

## Validation included

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt pytest
python -m pytest -q
```

Tests cover authentication/CSRF/roles, shared-record revision conflicts, access expiry, partner invitations, guest-specific RSVP and evening visibility, website escaping, private uploads, support boundaries, grants, verification/recovery, signed/idempotent Stripe webhooks, backup creation and reminder dedupe.

The package also underwent a served-page JavaScript DOM smoke test against the running server: couple setup/saves, all couple pages, supplier/instalment/guest forms, handover export, website publication, administrator two-step sign-in and all admin pages. A downloadable Chromium runtime and Docker daemon were unavailable in the build workspace, so visual browser screenshots and Docker/TrueNAS runtime checks remain part of your pilot installation.

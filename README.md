# Ivory Digital Wedding Planner — v1.5.1

This is the server-backed first release, not the earlier HTML demonstration. It includes a shared planner, partner accounts, wedding websites and individual guest RSVPs, plus Mark’s superadmin area.

See **AUDIT-REPORT.md** for repaired workflows and verification.

## Confirmed installation

| Setting | Value |
|---|---|
| Public URL | https://planner.ivorydigital.uk |
| Administrator | https://planner.ivorydigital.uk/ivoryadmin |
| Couple’s planner | https://planner.ivorydigital.uk/app |
| Wedding website | /weddings/the-couples-chosen-address |
| Host port | 30063 |
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
- PayPal.Me payment instructions with a GBP amount and reference, couple payment reports, admin verification before access, unique transaction records and manual refund recording. Stripe remains available as an alternative.
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

You can leave the SMTP fields blank and configure email entirely in **Admin → Email & reminders** after creating your admin account. Enter the SMTP host, port, security, username and password there, along with sender/reply-to addresses. The password is encrypted with the app key and never returned to the browser. Select **Set up here in admin**, then use **Save & send test to my admin email**. SSL/TLS (usually 465) and STARTTLS (usually 587) are supported. The test reports mail-server acceptance or a clear connection/login error; check the inbox and spam folder too. Saved settings apply to the worker on its next cycle without a restart. Existing environment-based SMTP setups remain supported through **Use existing server settings**. Leave Stripe fields blank until needed. Leave SECURE_COOKIES=1 for HTTPS deployment.

Compose reads this external file before starting the containers. Docker injects the values; the non-root application does not need permission to open the environment file itself. The app encryption key is created once inside the data folder; keep it in backups. Losing it prevents decrypting administrator authenticator secrets.

## 4. Add the Dockge stack

In Dockge create **weddingplannercouples**, and paste the supplied **compose.yaml**. Its build context is the absolute application path, so it works even though Dockge keeps its own stack file under `/mnt/apps/dockge/data/weddingplannercouples`.

Or use these commands in the repository folder:

```bash
cd /mnt/apps/weddingplannercouples
docker compose config --quiet
docker compose build web
docker compose up -d --force-recreate
docker compose ps
curl --fail http://127.0.0.1:30063/healthz
```

Expected health result contains `"status":"ok"`. Only port 30063 is published. SQLite and the worker have no public ports. Keep the Dockge copy of the YAML identical to the repository copy when changing deployment settings; both share the same Compose project name.

## 5. Point DNS and Nginx Proxy Manager at the new app

1. Create `planner.ivorydigital.uk` in your DNS, using the same public destination as your other hosted services.
2. NPM Proxy Host: domain **planner.ivorydigital.uk**, scheme **http**, forwarding IP **192.168.24.10**, port **30063**.
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

1. Admin → Email & reminders: choose **Set up here in admin**, enter the SMTP connection and mailbox login details, sender and reply-to. Use **Save & send test to my admin email**. Check the acceptance message, delivery history and actual inbox/spam folder. **Refresh delivery status** preserves any unsaved form edits.
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
docker compose build web
docker compose up -d --force-recreate
curl --fail http://127.0.0.1:30063/healthz
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

The package also underwent a served-page JavaScript DOM smoke test against the running server: couple setup/saves, all couple pages, supplier/instalment/guest forms, handover export, website publication, administrator two-step sign-in and all admin pages. Chromium checks include the mobile admin email flow, secure transport choices, failed-login correction and light/dark layouts. Live provider delivery remains an installation check. A Docker daemon was unavailable in the build workspace; check Docker/TrueNAS runtime on the target installation.

## Updating to v1.0.2 from the initial installation

The update adds encrypted admin SMTP settings without replacing accounts, the database or the app key. Take a backup first, then pull and rebuild **both** app services:

```bash
cd /mnt/apps/weddingplannercouples
docker compose exec -T worker python manage.py backup
git pull --ff-only
docker compose build web
docker compose up -d --force-recreate
docker compose ps
curl --fail http://127.0.0.1:30063/healthz
```

The health response should show v1.0.2. Refresh the admin page to load the new email controls. This planner uses port **30063**; port 30061 belongs to the separate tenant booking system.

## PayPal.Me setup — v1.0.4

In **Admin → Pricing & trials**, choose **PayPal.Me — I verify payments manually**. The confirmed profile is prefilled as `https://paypal.me/weddingsbymark`; you can edit it. Your existing price, notices and open/closed settings are retained. Set/check the one-time price and refund terms, then enable **Open payments** when ready. Stripe credentials are not required for PayPal.Me. Existing active Stripe installations retain Stripe during migration.

The couple selects Upgrade access, reads the price/access/refund terms, accepts the terms, then receives payment instructions with a GBP link and a unique reference. Ask them to include that reference and planner email in the PayPal note. They should pay for goods or services and confirm the recipient and GBP amount in PayPal. They can then report their transaction ID. A report never activates access.

Payment requests appear under **Pricing & trials → PayPal payments & access**. Check the payment inside your own PayPal account. Select **Verify payment & activate access**, enter the actual transaction ID and gross amount before PayPal fees, and confirm that you checked the completed payment, recipient and currency. The planner records a verified sale and grants access to both partners. A transaction ID cannot be used for two weddings; repeated confirmation does not add another sale. Existing longer access is retained. Complimentary weddings are not asked to pay.

Prepared requests keep their original amount, access date, terms and recipient. Changing payment provider does not verify an earlier payment; unresolved PayPal requests block starting a second Stripe checkout. A customer must not send payment again while awaiting confirmation. If they abandon a request, **Close unpaid request** is available after you check that no completed or pending payment exists in PayPal. This retains the history and lets them request new instructions. Never close a received payment as unpaid.

Refunds must be completed manually in PayPal. **Record completed PayPal refund** only records a full refund already made; it does not transfer money. Review the couple's access separately afterwards. Receipt history is retained and the refunded payment is removed from the confirmed-payment total.

Update your privacy notice to identify PayPal as the processor of payment details. The planner stores payment references/status, the reported transaction ID and the transaction ID you verify; PayPal handles the actual payment details. No PayPal password or API credential is needed for this manual-link flow. Live PayPal payment and recipient/currency behaviour still need a merchant check on the deployed app before opening paid access widely.

Update from your current installation:

```bash
cd /mnt/apps/weddingplannercouples
docker compose exec -T worker python manage.py backup
git pull --ff-only
docker compose build web
docker compose up -d --force-recreate
docker compose ps
curl --fail http://127.0.0.1:30063/healthz
```

The health response should show **1.0.3**. Refresh the admin page after deployment.

## Bank transfer and per-couple requests — v1.0.4

Enter your UK bank name (optional), account holder, six-digit sort code, eight-digit account number and any instructions in **Admin → Pricing & trials → Bank transfer setup**. Leading zeros are retained. These are receiving-account details; the app never needs your banking login. Bank details are not shown on the public landing page or in request emails.

For each registered couple, open **Couples & access → Request payment**, choose **Bank transfer** or **PayPal.Me**, and decide whether to email both verified account holders or copy the sign-in link yourself. The current price/access rules are used for a new request. The global payment method is only the default for self-service upgrades; your selected method for a specific couple takes precedence. Targeted admin requests can be prepared while general public payments remain closed.

Emails contain the amount, chosen method, reference and a link to sign in. Delivery is queued through your configured SMTP service and shown in Email & reminders. Repeated creation of the same outstanding request does not duplicate queued emails. The couple signs in, accepts the stored request terms and sees only their own instructions. For bank transfers they can copy the bank details/reference and report the paying account name and date. Reports never activate access.

Check cleared funds in your own bank account, then use **Pricing & trials → Bank & PayPal payments → Verify payment & activate access**. Enter the bank transaction reference, exact GBP amount and verification confirmation. Both partners then gain access. PayPal verification remains available through the same panel. Bank receipts and PayPal receipts have separate unique transaction records.

Existing requests keep the original amount, method, bank details or PayPal profile, access date and terms. To change a pending request's method or receiving account, first check that no payment is completed or pending, close it as genuinely unpaid, then prepare a new request. Never silently replace instructions for an outstanding payment. Refund recording is available for both methods after the actual refund has been completed outside the app; account access still requires a separate review.

No existing bank details, pricing, policies, accounts or PayPal payments are replaced by this update. Existing requests and endpoints remain compatible. Add the bank payment reporting information (payer name, transfer date and verified references) to your privacy notice as applicable.

Update using the backup/pull/single-image build/recreate commands above. The health endpoint should show **1.0.4**. The planner remains on **30063**. Refresh admin after updating.


### Invite a new couple from admin

Open Couples & access → Invite a couple. Enter both names, their main email and optionally the wedding date. Choose a free trial for an enquiry or complimentary access included with a Weddings By Mark booking. Review the complimentary end date before sending. The main account holder receives a seven-day invitation, chooses their own password and accepts the terms. No separate verification email or payment is required. A trial starts on acceptance; complimentary access keeps its chosen end date. The partner can then join through the existing partner invitation feature.

SMTP, a sender, terms and a privacy notice must be configured first. The account list marks invitations awaiting acceptance. Resend invitation replaces the old link; obsolete queued invitation emails are cancelled by the worker. Duplicate emails cannot overwrite existing accounts; use Manage access for an existing couple. Invitation policy acceptance is retained in the database.

### Returning to admin during two-step sign-in

After entering the admin password, reopening /ivoryadmin or /ivoryadmin/login resumes the pending authenticator step. Reloading does not consume it. An incorrect, expired or reused code keeps the entry form visible for another attempt. Already authenticated visits to the code address return to admin. Truly expired/lost browser sessions still require signing in again; two-step verification is retained. Real Android app-switch behaviour must be checked on the user's device after deployment.


## WBM complimentary booking invitations — v1.0.7

This optional connection is off until deliberately configured. It pairs with
BookingSystem2026 V8.71. Deploy the planner first, then the booking app.
In planner admin → System & security, select Create / replace connection key.
The key is shown once. Paste it into the personal booking app → Business settings
→ Planner invitations, then enable automatic invitations there. The planner
stores only the key hash; the booking app encrypts its copy. A rotated key stops
the previous connection. Do not commit keys or paste them into support messages.

The booking app waits **30 minutes** after successfully sending a qualifying
full-deposit confirmation. It then sends both first names, main email, wedding
date and its booking identifier. The planner creates complimentary access until
**30 days after that wedding date** and queues its existing seven-day invitation.
The couple sets their password and accepts the terms as usual. Sending is within
normal worker intervals, rather than at an exact second. SMTP must be working.

Requests are tied to the booking identifier: retries do not create extra accounts
or emails. Existing accounts or changed request details require an admin review;
the integration never overwrites plans, changes paid access or resends invites
silently. Successful requests report queued/sent/accepted status to the booking
app. Email failures are handled by the existing mail worker. After its retries
are exhausted, review Email & reminders; an intentional admin resend is reflected
in the booking app after Retry / check status. Old bookings, imports, tests,
partial deposits and failed confirmation emails are excluded by the booking app.
No historical invitation batch is sent when you enable the connection.

Update on the existing TrueNAS installation (backs up first and prints an image
rollback command for both planner services):

```bash
curl -fL https://raw.githubusercontent.com/valianktni1/weddingplannercouples/main/scripts/deploy-booking-connection.sh -o /tmp/wbm-planner-v107.sh && sudo bash /tmp/wbm-planner-v107.sh
```

This adds a booking-invitation mapping table; it does not replace existing data.
No live access is enabled just by deploying. Existing manual invitations remain
available. Planner port remains **30063**, as in the current compose file.



## Invitation preview and personal wording — v1.0.8

The approved white-and-sage invitation now sends as a responsive HTML email with a complete plain-text fallback. The header reads Ivory Digital / Built by Weddings By Mark / Wedding Planner. Complimentary and trial invitations use their own approved wording. The trial length comes from admin settings; access dates come from the couple account. Wedding-plus-30-day wording appears only when that is the actual access rule for that invitation.

In Couples & access, choose Invite a couple, enter their details and choose Trial or Complimentary. Preview invitation opens the proposed email before an account or email is created. You can change the subject, heading, personal message and sign-off for this couple. After an edit, use Preview your changes before the Send button becomes available. Setup instructions, feature list, access information and the seven-day personal link are inserted automatically. A preview link is a placeholder; the real token is generated only when you send.

Preview / resend invitation opens the same editor for a pending invitation, retaining its previous personal wording where available. You can also read the last queued email. Reviewing/cancelling leaves the old invitation valid. Sending a replacement rotates the link and existing stale-mail checks cancel the obsolete queued message. Page navigation/refresh warns about an unsent edited invitation.

The booking connection from v1.0.7 is retained. Automatic requests use the approved complimentary standard with no manual approval step. Its booking identifier, authentication, idempotency, status endpoints and exact wedding+30-day expiry are unchanged. Personal manual edits do not change the standard or other couples. The booking app's existing 30-minute scheduling delay remains controlled in the booking app. No booking app update or key rotation is needed for this planner change.

The only storage migration adds a blank-by-default mail.html_body column; legacy queued email and all existing records remain intact. Docker's non-root code permission fix is retained. Update only the planner using its usual backup/pull/build/recreate steps and verify /healthz returns 1.0.8.


## Wedding Day Hub, table plan and Couple Journey — v1.1.0

### Where to find the new features

Couples: Our wedding → Open our Wedding Day Hub, or the Wedding Day Hub / Our table plan links above the planner. Admin: Couple journey in the admin menu. All existing sections, exports and shared saves remain available.

### Wedding Day Hub

Main ceremony, meal and photo timings come from Our day. Add activities, supplier arrivals, locations and instructions in Our timeline. Each added activity has an explicit audience: Couple only by default, all timeline links, or one supplier/team role. Timing checks identify missing details, morning/travel clashes, photo/meal overlap, coverage and group-estimate issues, missing contacts/arrivals, outstanding guest replies, due balances and seating issues. These are checks against entered data, not supplier approvals, live traffic or sunset predictions.

Who’s doing what lets couples create private jobs or assign a job to an existing private-link recipient. That person sees only their own assigned jobs and may mark them done. Other parts of the shared plan are read-only. Couple-side edits use both the existing planner revision and the Hub revision; stale edits are rejected with a reload message, preserving form input. Completed jobs are separate from the normal planning checklist.

Mark our plan ready is the couple’s own confirmation. Outstanding checks must be explicitly reviewed first; planning changes return the plan to review. A revoked/expired recipient assigned to a job is flagged for reassignment.

### Private sharing

Create a link for a named photographer/video supplier, venue, wedding-party member or coordinator. Choose sections, selected supplier contact records and an expiry date; then preview the recipient’s sections before creating the link. Banks, budgets, payment records, private family notes and guest dietary/access details are excluded. Guest sharing is limited to names, table, day/evening and reply status. Instructions explicitly assigned to a shared activity or job are visible to that chosen audience.

Anyone holding the private link can view/confirm its sections and complete jobs assigned to it, so send it only to the intended person. No separate supplier account is required. Links can be copied again from Private sharing, revoked or replaced. A link cannot outlast the couple’s editing access; suspension or expiry blocks live views, acknowledgements and downloads. Previously downloaded files cannot be recalled.

Recipients confirm a content-specific version. Changed timing and section notices appear when they return, and the live page checks for changes every 30 seconds while visible. A stale page cannot confirm a later version. The couple sees who has confirmed the current version. Optional recipient email updates must be explicitly enabled; notifications are deduplicated, and obsolete/revoked notifications are cancelled before sending. Private-note or budget changes do not create a public change notice.

### Visual seating planner

Create named round or long tables with capacities, drag their handles to arrange the room, use arrow keys or edit room positions. On desktop, guests can be dragged onto a table. On phones, choose the table beside a guest and press Assign. Entered capacity limits are enforced; declined guests cannot be assigned new seats. Waiting replies remain clearly marked.

Assignments use the existing guest.table field, so Guests & photos and old venue handovers stay in sync. Import existing table labels preserves them and leaves capacity marked for confirmation. Renaming a table updates its assigned guests atomically. Removing a table requires an explicit choice to return its guests to the unseated list. Guest/table changes from another partner are protected by shared revisions. Download the CSV table list or a role-specific PDF.

### Day packs and offline access

Download a readable PDF for printing or a self-contained offline HTML snapshot. The couple copy includes their timeline, contacts, photo groups, jobs and seating. Role copies include that role’s timeline, relevant photo groups/seating and jobs assigned to recipients with that role. For the exact sections/jobs/contact selection of one person, download through their private link. Every snapshot states when it was made and that it will not update. No private family notes, finances or guest health/access details are included. Offline copies contain no sign-in tokens, acknowledgement forms or scripts.

### Admin Couple Journey

Stages: Invited → Joined → Getting started → Actively planning → Ready for the day → Archived. These are broad account/setup signals, not a score or a view into private planning. Ready is the couple’s confirmation. Last opened is recorded only when a signed-in couple opens their planner/Hub, at most once every five minutes. Existing activity before the update is shown as not recorded yet. Admin can filter stages, expiring/ended access, unaccepted invitations and active support permissions, then use existing invitation preview, access and payment actions. Private notes, guest details, supplier plans and financial breakdowns are not added to admin responses.

### Update and rollback

The v1.0.7 booking API, its 30-minute scheduler contract, exact wedding+30-day access, v1.0.8 email templates and all connection keys are preserved. No booking app update is needed. Storage changes are additive Hub tables; the original wedding JSON shape is unchanged. No existing plans, guest assignments or payments are rewritten during migration. Non-root Docker code permissions remain fixed. ReportLab is an added production dependency for PDF generation; test-only dependencies are in requirements-dev.txt.

In a TrueNAS root shell, from the existing clean checkout:

```bash
cd /mnt/apps/weddingplannercouples
(umask 022; git pull --ff-only)
bash scripts/deploy-day-hub.sh
```

The script backs up the current data, tags the currently running image for rollback, prints a rollback command for both planner services, builds the web image once, recreates web/worker and checks version 1.1.0. It does not change any other Docker app. Keep the printed rollback command. The older image ignores the additive Hub tables; new Hub URLs will be unavailable during an image rollback, while stored data remains intact.

Developer checks:

```bash
python3 -m pip install -r requirements-dev.txt
python3 -m pytest -q
node tests/test_merge.cjs
```

## Cancel an unaccepted admin invitation (v1.1.1)

Open **Couples & access**, find the couple and select **Cancel invitation**. Check the name and email, tick the confirmation and choose **Cancel invitation & remove from list**. The same action is available from Couple journey.

Cancellation removes the invitation from active lists and counts, suspends its account, invalidates existing setup/recovery/partner links, revokes its sessions and cancels queued/retrying welcome emails. Already delivered or in-flight emails cannot be recalled; their old setup links stop working. This is reversible cancellation, not permanent data erasure. Accepted accounts, self-registered accounts, multi-member accounts and invitations with any payment request/history cannot be cancelled here. Use the existing access controls to review those records.

Expand **Cancelled invitations** at the bottom of Couples & access to restore a record. Restoration removes the suspension and returns it to the active list without sending email or reviving old links. Then use **Preview / resend invitation** to review the message and send a fresh setup link. The email remains reserved by the retained account; restore it rather than creating a duplicate invitation. Existing booking identifiers remain reserved too: an automatic retry returns the same cancelled record and does not send another email. The booking app may flag this as needing attention; deliberate preview/resend in planner admin remains the recovery route.

Deploy from the TrueNAS root shell:

```bash
cd /mnt/apps/weddingplannercouples
(umask 022; git pull --ff-only) && bash scripts/deploy-cancel-invitations.sh
```

The script makes a planner data backup, preserves the running image, prints an exact rollback command, builds the shared image once, recreates only this planner’s two services and checks version 1.1.1. The schema addition is compatible with the previous version. No changes to ports, datasets, SMTP settings or other applications are required.

## Update to v1.2.0

After v1.2.0 is on the `main` branch, run from the TrueNAS root shell:

```bash
cd /mnt/apps/weddingplannercouples
(umask 022; git pull --ff-only) && bash scripts/deploy-v120.sh
```

The script backs up live data, retains the previous image and prints rollback instructions. It builds the new image and restores the latest archive into a temporary directory inside a separate container with no network and no live data mount. It checks database integrity, referenced couple files and application startup before recreating the planner services. If that check fails, the running services are left alone. The restore test confirms recovery of the archive available on the NAS at update time; keep off-server copies separately.

Admin now shows dated invitation stages, the next action, System health and a read-only **View as couple** preview. The preview uses sample plan data so private couple entries remain hidden. An SMTP acceptance timestamp means the mail server accepted the message; it does not prove inbox delivery. Older invitation records may have no acceptance or join timestamp until a new event occurs.

## Read-only Control Centre summary (v1.3.2)

An independent opt-in endpoint, `GET /api/integrations/control-centre/overview`,
accepts `X-Control-Centre-Key` matching `PLANNER_CONTROL_CENTRE_KEY` (32+ characters)
when `PLANNER_CONTROL_CENTRE_ENABLED=true`. Defaults leave it disabled. Use a new
key shared only with Dashboard's `DASHBOARD_PLANNER_KEY`, never the Booking key.
It cannot authorise admin, invitation or timing operations.

The endpoint uses a separate SQLite connection in read-only/query-only mode and
does not create sessions, set cookies, send email or change invitation settings.
It returns account counts, up to five names/dates/access expiry records per queue,
and worker status. Cancelled invitations are excluded. Current access excludes
suspended/expired accounts and includes trials and complimentary accounts.
Awaiting couples means welcome email queued/sent and the invitee has not joined;
retrying, failed, cancelled or missing welcome email goes into the review queue.
Counts and expiry use the London business date. No couple plans, guest data,
budgets, email addresses, setup links, support grants or private notes are exposed.

The existing `/api/integrations/wbm/` invitation/timing flow keeps its separate
stored key hash and enabled flag. There are no schema changes in this release.
Use the paired Dashboard source-bundle installer to back up and update both apps;
it preserves existing env files and checks the original Booking settings afterward.

## Couple interface refresh — v1.4.0

The couple planner now uses the approved warm ivory/deep green design, a personal dashboard, a clear booked-cost ledger and an upcoming-dates list. Every existing planner page and action is retained. Home / Checklist / Budget provide quick mobile navigation; **More** or the header **Menu** opens all ten planner pages plus Wedding Day Hub, tables, website, documents and account access. For linked Weddings By Mark couples, the existing **Send final timings to Mark** control remains in Wedding tools, below the open menu. Sign out is inside Menu. Desktop keeps the full planner sidebar and tools.

On phones the header, scrolling content, save status and bottom navigation occupy separate layout rows. The bar is never positioned over the page. Forms scroll within their own available space; the bar hides while editing a text field, and the shell uses the visual viewport height when the keyboard changes the visible area. Safe-area padding protects screen cut-outs and the home indicator. Setup temporarily hides quick navigation until the short introduction is complete. The design applies to the couple planner, Hub, website editor, documents, access page and the existing sample admin preview; public wedding websites, invitations/emails and superadmin retain their own styling.

Deploy from the TrueNAS root shell:

```bash
cd /mnt/apps/weddingplannercouples
(umask 022; git pull --ff-only) && bash scripts/deploy-v140.sh
```

The deployment helper preserves locally customised Compose settings and environment file references, including the Control Centre connection. It archives the checked-out Git commit into a fresh deployment-releases directory, then builds a unique shared web/worker image from that source, rather than reusing an older saved release. Local compose.yaml changes and untracked installation files are allowed; other tracked code changes stop the update. Docker Compose must support config --no-env-resolution.

It backs up planner data, retains each running service image and private rollback copies of referenced environment files, prints rollback instructions, tests a real backup in an isolated container and checks that web and worker run v1.4.0. Only after those preflight checks does it atomically replace compose.yaml with equivalent JSON syntax containing the new image/build context. Both JSON and YAML are supported Compose inputs. Installation settings, env_file references, mounts and port mappings are retained; keep this local configuration out of Git. The backup directory contains private configuration and must stay protected. If deployment fails after restart, use the printed rollback command; this starts the previous images and saved environment without rebuilding. A rollback does not rewrite compose.yaml, so restore original-compose.yaml from the same private rollback directory before any later standard deployment. Existing ports (30063), datasets, account credentials and application data stay in place. Physical iOS/Android keyboards still need an installation check; automated tests cover reduced viewport height, enlarged text and button clearance.


## Home-screen welcome — v1.4.1

After their first successful mobile sign-in on this device, couples see a large optional Add to home screen dialog. This is shared by invited, complimentary, trial and partner accounts; it does not alter access or billing. It also appears for existing couples the first time they open this version on a phone. Maybe later keeps the normal setup/planning journey available. The prompt is remembered for that account in that browser, with a manual Add to home screen button in Menu. Storage-blocked browsers still work but cannot remember the choice across visits.

On supporting Android browsers, the button uses the browser's native installation prompt when it becomes available. Otherwise there are browser-specific instructions, including Safari Share / Add to Home Screen / Open as Web App for iPhone, Samsung Internet, Android and embedded email/social browsers. Standalone launches suppress the prompt. Desktop visits are not automatically interrupted. Browser installation availability and wording vary; no claim of installation is made just from displaying instructions.

A public manifest and 192/512px PNG brand icons configure the installed launcher to open /app in standalone mode. The normal authentication/session rules still apply, including sign-in if a separate home-screen browser session needs it. No invitation tokens, private account details or credentials enter the manifest or icons. There is no service worker or offline private-page cache; the planner requires an internet connection. Admin, public pages and read-only admin sample preview do not get the couple install prompt.

Deploy in the TrueNAS root shell:

```bash
cd /mnt/apps/weddingplannercouples
(umask 022; git pull --ff-only) && bash scripts/deploy-v141.sh
```

This uses the same fresh-release build, protected configuration backups and isolated restore rehearsal as the corrected v1.4.0 updater. It retains local Control Centre/env settings and port 30063. Actual OS installation should be checked on physical iPhone/Android after deploying; browser QA covers simulated platform/native-install events, not an App Store or OS installation.


## Samsung Internet installation route — v1.4.2

Some Samsung Internet installations of web apps show Android's older-app warning; Mark reproduced it and verified a clean install in Chrome on the same phone. The couple prompt therefore offers Open in Chrome for Samsung Internet and never invokes its native installation event. The Android browser intent contains only this site's /app address, with a same-site browser fallback; no invitation link, password, account identifier or session token is passed to the other browser. Couples may need to sign in again in Chrome. The instructions also explain how to open Chrome manually if the handoff is unavailable. Embedded Android browser guidance recommends Chrome, and other Android fallback instructions no longer send couples to Samsung Internet for installation. iPhone steps and normal Chrome installation are retained.

This changes the planner's installation guidance. It cannot change Samsung's generated Android package or remove OS warnings if someone independently chooses Samsung Internet's own Install menu. No instruction asks couples to bypass security protections. A physical Samsung check of the Open in Chrome handoff remains useful after deployment; the app remains usable in the browser.

```bash
cd /mnt/apps/weddingplannercouples
(umask 022; git pull --ff-only) && bash scripts/deploy-v142.sh
```


## Clearer couple journey — v1.5.0

Keep all existing planner pages, actions and URLs. Label the wedding-day route consistently as Build our timings → Check our timings → Review & export → Share our day. A shared navigation strip on the day, rehearsal, final-review and Hub pages explains the sequence; the Hub retains seating, helpers, extra activities, private links and day packs. Existing unsaved-change protection applies to in-planner navigation and leaving pages.

Next on your list uses entered data in a clear order: overdue unpaid instalment, overdue task, payment due within seven days, task due within seven days, missing venue, meal confirmation within 60 days of a dated wedding, earliest dated outstanding task, then other planning guidance. Paid instalments are excluded. It is guidance from recorded plans, not supplier confirmation or a payment service.

An optional first-steps guide links to suppliers, payments, guests and partner invitations, with progress derived from current shared data. Placeholder supplier names from setup do not count as completed details. Couples can hide the guide or reopen it from Our settings. Dismissal is local to the account/browser; blocked storage still supports hiding it for this page session. Planning solo and not having made a payment do not block any feature.

Guest search matches names and households, with combined reply/day-evening filters, visible result counts, an empty-result message and Clear filters. Filters do not change the shared guest list or the full venue export. Arrange our tables links directly to the existing seating tool. The home-screen prompt now waits for successful setup completion; secondary couple tools check readiness before automatically offering installation. Manual reopening and the Samsung-to-Chrome route remain available.

Use plain budget wording and All changes saved. Keep editing-expiry details in Our settings and the existing final/export/access views, rather than repeating the expiry date in the permanent save bar. View-only status and save failures remain explicit. No database schema, payment calculation, billing, invitation integration, email or backup format change.

```bash
cd /mnt/apps/weddingplannercouples
(umask 022; git pull --ff-only) && bash scripts/deploy-v150.sh
```

The updater retains local Control Centre settings, uses a fresh release image, backs up data and rehearses archive recovery before restarting web/worker. Add node tests/test_planning_journey.cjs to local validation for priority and filter logic; tests/test_planning_journey_browser.cjs exercises the served UI alongside the existing home-screen and redesign browser suites.


## Mobile admin action buttons — v1.5.1

The admin couple-journey and account action groups use full-width stacked buttons on phones, with natural word wrapping instead of splitting labels into narrow columns. Wider screens use a wrapping grid with room for each label. Apply the same admin-only rules to other main-panel action groups and standalone row controls, including backup and support controls. Keep every action label, handler, API, access rule and record intact. The stylesheet is loaded only by the authenticated admin template; couple/public layouts are unchanged.

```bash
cd /mnt/apps/weddingplannercouples
(umask 022; git pull --ff-only) && bash scripts/deploy-v151.sh
```

The existing configuration-preserving updater backs up data and rehearses recovery before restarting. Refresh the admin page after deployment to load the versioned stylesheet.

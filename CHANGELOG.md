## v1.6.0 — Botanical glass finish

- Shared sage/ivory glass presentation across the planner, setup, account/auth and superadmin screens, using a local botanical background and existing dark-mode preference.
- Keep readable opaque inputs/dialogs, reduced-transparency/forced-colour fallbacks and undecorated printing. Keep the mobile dock in its own row and the v1.5.1 admin action layout.
- Preserve couple-selected wedding website themes, email/offline export layouts, all features and APIs. No database or integration migration.
- Add configuration-preserving deploy-v160.sh with the existing backup/isolated restore rehearsal and rollback procedure.

## 1.5.1 — readable mobile admin buttons, 22 October 2026

Stop admin action buttons shrinking into narrow columns and inheriting arbitrary word breaks. Stack full-width actions on phones, retain a wrapping layout on larger screens, and keep normal word boundaries and comfortable tap targets. Scope the stylesheet to the admin template; preserve all actions, data and couple styling. Add admin layout/browser regression coverage and the existing backup/restore deployment process for v1.5.1.

## 1.5.0 — clearer couple workflow, 22 October 2026

Retain existing functionality and give wedding-day planning a consistent build/check/review/share sequence. Prioritise overdue/near-term payments and tasks before general planning suggestions; defer meal-confirmation guidance until 60 days before the wedding. Add an optional first-steps guide with hide/reopen controls and derived progress. Add guest/household search, reply and attendance filters, result counts and a direct table-plan link. Offer home-screen installation after setup. Simplify saved/budget wording and keep expiry details in account/final/access views. Preserve dirty-form guards, current routes, partner handling, Samsung Chrome guidance, integration and all exports. Add targeted unit/browser checks and the configuration-preserving v1.5.0 deployment helper.

## 1.4.2 — guide Samsung Internet installs through Chrome, 22 October 2026

After a reported older-Android warning in Samsung Internet and a clean Chrome installation on the same device, show Samsung users an Open in Chrome link and short instructions. Suppress native installation requests in Samsung Internet, including a defensive button-handler check. Retain Chrome/iPhone flows, Maybe later and Menu reopening. Pass only /app to Chrome, with a browser fallback and manual instructions if the handoff cannot open. Keep existing configuration-preserving backup/restore deployment checks.

## 1.4.1 — optional home-screen welcome, 22 October 2026

Add a readable first-mobile-sign-in invitation to add Ivory Planner to the home screen, with Maybe later and Menu reopening. Support native installation where the browser exposes it, iPhone/Safari and Android/Samsung instructions, embedded-browser guidance, per-account/browser dismissal and standalone suppression. Supply a standalone manifest and branded PNG icons. Keep the existing setup, invitation, complimentary/trial access, sign-in and planning flows; no offline private-data cache, schema or email change. Reuse the configuration-preserving deployment and backup restore checks for v1.4.1.

## v1.4.0 deployment compatibility follow-up

Preserve local Control Centre Compose settings and environment file references. Build a fresh source snapshot with a unique image tag, retain separate service rollback images and protected environment copies, and stop before restart if backup/build/restore preparation fails. Do not reuse the older Control Centre build context.

## 1.4.0 — personal couple planner design, 22 October 2026

Apply the approved ivory and forest green direction to the couple experience: editorial names/countdown, one practical next step, an open budget ledger, upcoming dates and clear routes into guests, Hub and tables. Keep every existing planner page, supplier/payment/task/guest/group editor, export, rehearsal, partner save/conflict handling and WBM timing submission.

Add mobile Home / Checklist / Budget / More navigation with all other pages accessible through Menu. Keep navigation in its own layout row beneath the scrolling page, hide it during text entry, react to visual viewport changes and allow phone safe areas. Preserve unfinished-form confirmation when using quick navigation. Retain the existing desktop sidebar. Scope the styling to couple pages and the existing sample preview. No data/schema, billing, SMTP, booking integration, public website or email-template change.

Add served-app browser regression checks and a backup/image rollback deployment helper with isolated archive recovery before restart.

## 1.1.1 — cancel and restore unaccepted invitations, 20 October 2026

Add a named confirmation to cancel unaccepted admin invitations from Couples & access or Couple journey. Remove cancelled entries from active lists/counts, disable old links, revoke sessions and stop queued welcome emails. Add a separate Cancelled invitations section with confirmed restoration; restoring sends nothing and old links stay disabled until an explicit preview/resend creates a new link. Protect joined accounts and any payment history, retain the audit trail and booking idempotency mapping, and keep invitation provenance through token housekeeping. No permanent deletion, email redesign, SMTP settings or other app changes.

Add additive migration, cancellation/restore/auth/CSRF/mail/booking regression tests and a backup/rollback deployment script.

## 1.1.0 — Wedding Day Hub, seating and Couple Journey, 17 October 2026

Add wedding-day activities/arrivals, assigned responsibilities, deterministic final checks, per-recipient scoped links, content-specific acknowledgements, change notices, optional deduplicated email updates, revocation and dated PDF/offline HTML day packs. Add a visual seating layout with round/long tables, capacities, desktop drag/drop, keyboard moves and phone assignment controls. Existing guest table labels remain authoritative and can be imported. Add a privacy-conscious admin Couple Journey dashboard with broad stages, activity/access signals and existing invitation/access/payment actions.

Preserve existing wedding JSON, optimistic partner saves, invitation/booking APIs, payment settings, source permissions and old handovers. Partner joining now protects populated Hub data too. Add a backup/image rollback deployment script. ReportLab is the only new production dependency.

## 1.0.8 — approved invitations and manual preview, 16 October 2026

Use the approved Ivory Digital / Built by Weddings By Mark white-and-sage email design, with distinct complimentary and trial wording, a real setup button, accurate access information and a plain-text fallback. Add read-only admin previews, per-couple subject/heading/message/sign-off editing, mandatory re-preview after UI edits and review before resending. Keep a snapshot with each invitation; replacement links are generated only at send time. Preserve the v1.0.7 booking contract and permissions repair. Select booking email by its invitation record rather than its formerly fixed subject.

## 1.0.7 — 16 October 2026

Optional scoped WBM booking invitation API, idempotent complimentary invitations, exact wedding+30-day expiry, delivery status and admin key/pause controls. Existing account conflicts require review. Disabled until configured. Includes a backup/image rollback update script.

# v1.0.6 — couple invitations and admin sign-in resumption

Add an admin invitation journey for enquiries and complimentary wedding couples. The couple chooses their own password and accepts recorded policy versions through a single-use seven-day link. Trials start on acceptance. Complimentary access preserves the chosen end date; no purchase is created. Existing accounts are never overwritten. Pending invitations are visible and can be resent, replacing the previous link and cancelling obsolete queued emails.

Resume pending two-step sign-in when reopening the admin or admin login address. Keep the code form available after an incorrect, expired or reused code; redirect authenticated and expired-session visits appropriately. Preserve existing 2FA, rate limits, replay protection and recovery codes.

# v1.0.5 — bank settings save feedback

Prevent formatted account numbers being truncated by the admin input length limit. Accept whitespace-separated UK routing numbers, preserving leading zeros and enforcing six/eight digits after normalisation. Bring settings-save errors and success messages into view on mobile, preserving fields on failure. Version admin scripts to avoid stale cached controls.

# v1.0.4 — bank transfer and per-couple payment requests

Add UK receiving-bank settings with text validation that preserves leading zeros. Admin can choose bank transfer or PayPal.Me separately for each couple before queuing a request email or copying the sign-in link. Requests freeze their method, recipient details, price and terms. Emails omit bank details, reach verified account holders only and are deduplicated. The couple accepts terms before seeing payment instructions and can report a transfer without gaining access. Admin verifies cleared funds before activation. Existing PayPal/Stripe functionality and data are retained. Port remains 30063.

# v1.0.3 — PayPal.Me with manual verification

Add the confirmed weddingsbymark PayPal.Me profile as an editable admin setting. Couples accept payment terms, get a GBP payment link and unique reference, then may report their transaction ID. Reports do not grant access. Admin verifies the actual transaction and gross GBP amount before activating both partners’ access. Receipt uniqueness and idempotent confirmation prevent duplicate sales. Existing requests preserve original commercial terms. Refund recording requires a refund already completed in PayPal and leaves access changes to a separate review.

Stripe remains available, with unresolved PayPal requests preventing a second checkout through another provider. Existing Stripe installations retain their payment method. Existing pricing, sign-up switches and accounts are retained. Update scripts build the shared image once and recreate both services, avoiding stale containers on update. Port remains 30063.

# v1.0.2 — email setup in superadmin

Configure SMTP hostname, port, SSL/TLS or STARTTLS, username, encrypted password, sender and reply-to from Email & reminders. Blank password preserves the saved value; explicit removal and replacement are supported. Legacy server environment settings remain available. Test sends save the form first and report actual server acceptance or a fixed, safe failure hint. Tests are recorded separately from queued mail and are not retried automatically. Refresh delivery status preserves unsaved form edits. The worker uses saved settings without a restart; signup readiness uses the selected email configuration. No SMTP password or encrypted credential is returned in the admin API or audit log.

Keep port 30063 for the planner; 30061 belongs to the tenant booking system. Corrected the admin port label and trial-start wording.

# v1.0.1 — workflow audit and repairs

Conflict-aware shared saves with a truthful pending indicator and downloadable recovery copy. Setup queues the actual partner invitation, and empty pre-existing accounts can join without deleting populated planners. Website changes use their own revision check; previous addresses remain valid and saved private drafts can be previewed. Guest links can be revoked without removing replies.

Failed requests roll back business edits. Verification starts the trial at verification. One-use account links and admin authentication use transaction checks. Checkout retries retain their purchase and idempotency key; active paid/free access cannot be purchased again. Paid entitlement cannot be shortened through suspension.

Worker rechecks queued reminders against current records. Backups release the database write lock before compression and restore reads files from the restored data directory. Startup key creation is locked and atomic, worker health is visible, deployment waits for health, and cover images honour camera orientation.

# v1.0.0 — first deployable pilot

Shared accounts and planner, wedding websites and RSVPs, private documents, two-step superadmin, SMTP/reminders, optional Stripe Checkout, backups and isolated TrueNAS/Dockge configuration.

Corrected the prototype’s stale next-payment display, hidden overspend, deadline classification, missing entry editing, household-only guest records and hardcoded wedding timings. The real app uses server records and optimistic concurrency checks instead of preview/local data.

Public sign-ups and checkout are deliberately closed until configured. Actual DNS/TLS, email credentials, Stripe credentials and TrueNAS runtime checks remain installation tasks.

## 1.2.0 — invitation visibility and recovery checks, 20 October 2026

Show dated invitation stages and next actions in admin, distinguishing mail-server acceptance from a couple joining. Add a System health view for worker activity, failed mail, backup freshness and free space. Add a read-only "View as couple" view using the real planner interface with sample data, without exposing private plans or permitting writes. Let a couple sign in again in a new tab and retry an unsaved plan, checking account identity and partner conflicts before writing. Add a disposable archive restore test that boots the recovered application and checks referenced files; the update script runs it before restarting the live stack. Schema migration only adds nullable event timestamps.



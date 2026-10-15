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

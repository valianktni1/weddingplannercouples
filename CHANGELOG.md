# v1.0.1 — workflow audit and repairs

Conflict-aware shared saves with a truthful pending indicator and downloadable recovery copy. Setup queues the actual partner invitation, and empty pre-existing accounts can join without deleting populated planners. Website changes use their own revision check; previous addresses remain valid and saved private drafts can be previewed. Guest links can be revoked without removing replies.

Failed requests roll back business edits. Verification starts the trial at verification. One-use account links and admin authentication use transaction checks. Checkout retries retain their purchase and idempotency key; active paid/free access cannot be purchased again. Paid entitlement cannot be shortened through suspension.

Worker rechecks queued reminders against current records. Backups release the database write lock before compression and restore reads files from the restored data directory. Startup key creation is locked and atomic, worker health is visible, deployment waits for health, and cover images honour camera orientation.

# v1.0.0 — first deployable pilot

Shared accounts and planner, wedding websites and RSVPs, private documents, two-step superadmin, SMTP/reminders, optional Stripe Checkout, backups and isolated TrueNAS/Dockge configuration.

Corrected the prototype’s stale next-payment display, hidden overspend, deadline classification, missing entry editing, household-only guest records and hardcoded wedding timings. The real app uses server records and optimistic concurrency checks instead of preview/local data.

Public sign-ups and checkout are deliberately closed until configured. Actual DNS/TLS, email credentials, Stripe credentials and TrueNAS runtime checks remain installation tasks.

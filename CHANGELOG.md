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

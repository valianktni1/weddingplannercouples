# Pre-deployment audit — v1.0.1

The full planner, website, RSVP, documents, payments, calendar and superadmin features are retained. This remains a pilot release; production services must be checked on the target NAS.

| Finding | Repair |
|---|---|
| A save could appear finished while more changes were queued | Count pending writes and warn before leaving with unsaved edits. |
| Partner changes or guest replies could be overwritten by later local edits | Merge independent changes by field and entry ID; retain a downloadable unsaved copy on a genuine conflict. Undo preserves independent changes. |
| Setup recorded an invitation without sending it | Queue the real invitation after setup saves; show failure and retry guidance. |
| A partner who already registered could be unable to join | Allow joining from a completely empty account; keep populated planners protected. Accepted invitations cannot be cancelled as pending invitations. |
| Changing the website address broke sent guest links | Reserve previous addresses as aliases; separate website revision checks block stale edits. |
| Draft website had no private preview; guest links had no revocation | Add authenticated draft preview and ownership-checked revocation, preserving replies. |
| Invalid forms could leave earlier database changes committed | Roll back business edits on failed requests; retain form input on RSVP errors. |
| Trial countdown began before email verification | Start trial allowance when the account is verified. |
| Concurrent startup/auth requests could mishandle secrets or one-use tokens | Lock startup key creation and use atomic token/authentication transactions. |
| Retried checkout could create another purchase; active full access could be repurchased | Reuse the pending purchase and Stripe idempotency key, check session status and active entitlement. Real Stripe configuration remains an installation check. |
| Suspending a paid account could bypass later access protection | Check purchased entitlement dates even after access kind changes. |
| Old queued reminders could mention paid or changed instalments | Recheck current amount, deadline, preferences, access and wedding completion before sending. |
| Backup compression held the database write lock; restored paths could target live files | Stage a consistent database/key/referenced files, release lock before archive creation, and resolve downloads within the configured data directory. |
| Worker failure was hard to see; deployment health was checked too early | Add worker heartbeat health/status and bounded deployment health polling. |
| Phone cover photographs could appear sideways | Honour EXIF orientation before re-encoding. |

## Verification

- 26 Python backend regression tests pass: authentication/CSRF, two-step setup and recovery, account verification/reset, partner invitations, shared revisions, validation/rollback, websites/RSVP/revocation, privacy, access, webhook checks, reminders, backup and restored downloads.
- Five JavaScript merge scenarios pass: independent edits, same-field conflict, edit/delete conflict, safe undo and subsequent queued edits.
- Chromium served-app journey passes: setup with actual invitation queuing, eight planner sections at widths 320/390/736/1024 in light/dark, task saving, independent remote edits, rapid changes, draft website save/preview and documents. No JavaScript errors or horizontal page overflow in tested screens. Mobile dark rendering inspected.
- Syntax, compile, deployment YAML and archive checks are recorded in BUILD-VERIFICATION.txt.

## Remaining deployment checks

No Docker engine or TrueNAS host was available for a container build/runtime test. DNS/TLS/reverse proxy, dataset permissions, real SMTP delivery and real Stripe Checkout must be checked on the installation. Sign-ups and checkout remain closed until configured. Run the README pilot checklist with test couples before charging live customers.

This audit is a targeted workflow and regression review, not a promise that every possible device, concurrency pattern or external service failure has been tested. Existing release boundaries, including single-day planning and text/JSON handovers, remain as documented in README.md.

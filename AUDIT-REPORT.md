## v1.6.2 — returning-couple sign-in journey

Built on main 1dd45cb3ef2c105cb45cc8339a12df4b25eebc1a. The manifest already starts at /app, whose auth guard correctly redirects expired sessions to /login. However, the public root always rendered the sales page, couple brand/footer links pointed there, and logout returned there. Correct those routes and add a one-year first-party returning-device preference, holding only 1, with HttpOnly/SameSite=Lax and the installation's Secure policy. It is issued only after successful couple authentication or an authenticated visit, grants no access, and does not extend session expiry. The root routes known returning devices to sign-in and signed-in couples to /app. First-time visitors keep the sales page; /?welcome=1 explicitly opens public information. Legacy standalone root shortcuts route through /app. No invitation tokens or account identifiers enter the preference or launcher script.

Regression checks cover first visits, spoofed preference without authentication, actual database session expiry, existing signed-in device upgrade, failed credentials, couple/admin logout and public information access. Served-browser checks cover safe session-cookie loss, returning root, brand navigation, Welcome back, explicit marketing access and legacy standalone launch. The existing ten-page/browser suite also passed, including setup, sign-out, unsaved work, linked WBM controls and mobile final-action clearance. No production data, emails or payments were used. Device cookies cleared by the browser cannot identify a returning person; sign-in sets the preference again. Physical installed-app checks remain necessary after deployment.

## v1.6.1 — grouped navigation and guest journey

Built on main 583b5767c7f702346e08a007d97051850f05189d. Keep all existing planner routes and ten internal pages, bottom dock layout, optional installation, sample-only admin preview and linked WBM final-timings controls (now inside the wedding-day menu group). Group existing tools under five plain-language headings; future stationery, gift and after-wedding additions are not presented as working features. The header Menu has a labelled three-line icon, and More opens the same navigation.

Menu Close/Escape restores the content/window scroll position without rerendering the underlying form. Hub menu navigation delegates to an explicit Hub tab guard, retaining dirty-form confirmation and busy-state protection. Active menu items track external tools and seating/day-pack tabs. The website editor links guest list, invitations and tables; direct invitation navigation scrolls after its asynchronous fields load. Original beforeunload protection remains for separate-page navigation. Desktop sidebar order follows the primary planning tasks. Correct stale README claims about seating and PDF exports.

Validation: 187 backend tests and 3 subtests passed; merge and planning-priority/filter suites passed; v1.6.1 deployment preparation/sequence suite passed (10 tests and 3 subtests). Three served-app browser suites passed against fresh disposable databases with blocked SMTP: grouped-menu scroll restoration, widths 320/390/736/1280 in light/dark, final menu item reachability, internal planner and Hub dirty-form cancellation/confirmation, active tools, direct invitation navigation, and unchanged saved state; existing ten-page, keyboard-height, enlarged text, final Save/Generate clearance, setup, sign-out, linked WBM dialog and guest/day journey checks also passed. Website mobile screenshot inspected. No production records, messages, payments or TrueNAS changes were made. Physical-phone checks remain an installation task.

## v1.4.0 — couple experience design audit

Built on main 88f69e5955e56868c30a4891f278867eba8a9cf0 (v1.3.2), preserving the newer manual backup, preview/reliability and WBM timing features. Scope: presentation, couple page templates, navigation and version. No schema, account, financial calculation, SMTP or booking integration change.

The couple-only theme uses open sections and an honest booked-cost ledger, existing task/payment/event data and a deterministic next-step prompt. Unknown supplier costs and overdue balances remain explicit. Every existing planner route/editor/action remains available, including rehearsal, exports, priorities, partner invitations, undo, access and the linked WBM timing dialog. The new menu links call the existing navigation guard and preserve unfinished forms when leaving is declined. Unknown header buttons are ignored by the planner action dispatcher to keep theme/Menu controls from triggering undefined-action errors.

Mobile uses a finite flex shell: header, independently scrolling content, save status and navigation each take real layout space. No fixed/absolute bottom overlay or guessed padding reserve is used. Visual viewport changes and field focus adapt the shell; safe-area padding protects screen cutouts/home indicators. Desktop retains the complete sidebar. The same scoped theme applies to Hub, documents, website editor, access and sample admin preview. Public wedding websites, emails and superadmin styling remain separate.

170 backend tests, served browser workflow, merge checks and syntax checks passed. Last-action geometry was measured for long timing forms and website invitation generation, including enlarged text and reduced viewport height. Light/dark mobile and desktop screenshots inspected. No production data, external email/payment, Docker build or physical phone was used. The deploy helper preserves data/image/environment, performs isolated archive restoration and checks both service versions on the NAS.

## v1.1.1 — invitation cancellation audit

Built on main 74dbeceda72bd09443e352edad11b5f47eccf40e. Add one reversible cancellation table; existing users, weddings, state, finances, audit and booking mappings are retained. Admin cancellation and restoration require authentication, CSRF and explicit confirmation. Immediate transactions recheck one unverified couple member and invitation provenance, and refuse any payment history/request. Cancellation and welcome acceptance cannot both succeed for the same live token: cancellation consumes every account/wedding token; welcome acceptance checks token consumption within its own immediate transaction. A stale preview/resend or access edit cannot reactivate a cancelled invitation.

Cancel removes records from active admin lists, suspends access, revokes sessions and marks queued/retrying welcome mail cancelled. Existing worker validation rejects consumed tokens. SMTP work already in flight or delivered cannot be recalled, but its revoked setup URL cannot be used. Restoration deliberately sends nothing and does not revive old links; explicit preview/resend creates the new URL. Welcome provenance is retained for unverified users through token pruning so late restoration/resend remains possible. Booking integration replay returns the same cancelled record, not a new invitation. Personal booking app read-only inspection confirmed this state goes to its existing attention handling; its repository was not changed.

153 backend tests, admin DOM workflow, merge and syntax checks passed. No production records or external messages were used. No claim is made that the separate spam-delivery issue is resolved.

## v1.1.0 — coordination, seating and admin journey audit

Built on main 658f3ce2f5bc17fd3811581632ec7b95a02f9e5f (v1.0.8). Read the personal booking app's planner_integration.py and verified its existing readiness/status contract does not pin the planner version. The booking app repository was not changed. Existing invitation templates, mail transport, connection mapping, exact wedding+30 expiry, payment flows and Docker permission fix are preserved.

Hub-only resources are stored in additive tables. The existing wedding state schema is unchanged; guest.table remains authoritative. Every owner mutation checks membership, active editing access, CSRF, Hub revision and planner revision under an immediate SQLite transaction. Capacity/rename/removal updates preserve concurrent edits and require explicit unseating on table removal. Partner-join guards now treat populated Hub resources as existing plans.

Scoped links are unguessable, hashed in the token table and encrypted for owner copying/optional notification delivery. Every live read/write/download rechecks expiry, revocation, wedding suspension and access. Contact selection is explicit; medical/access fields, private family notes and financial records are excluded from every shared view and day pack. Recipient writes are restricted to confirming the shown content hash and completing jobs assigned to their specific link. Anonymous GETs do not acknowledge a plan. Change notifications are deduplicated, and obsolete/revoked messages are filtered by the worker. Private-only edits do not change the public hash. Edit and recipient rate limits are separate per account/link rather than shared across all weddings behind the proxy.

Admin additions expose only coarse stage/activity/access/support metadata. No private Hub records or guest data are returned through admin. Existing support restrictions remain intact. Ready is a couple decision with explicit review of flagged checks, not a claim that suppliers approved timings. Downloads are clearly dated snapshots and cannot be recalled after saving.

Verification includes former regressions, new isolation/concurrency/revocation/acknowledgement/seating/export cases, served mobile browser journeys and rendered PDF inspection. No live couple records, real SMTP sends, Docker build or TrueNAS deployment were used in this workspace.

## v1.0.8 — reviewed against the updated booking-connected repository

Started from GitHub main fb104285944eaf7e6e25d737a449ba8079679315, rather than the older v1.0.6 workspace. Reviewed machine authentication/opt-in, the shared create_couple_invitation/welcome_email path, request fingerprint/idempotency mapping, status following resends, exact wedding+30 expiry and the non-root Docker permissions repair. All preserved. The personal booking repository was not modified.

Invitations lacked recipient-visible preview or per-couple edits. Added approved HTML plus plain text, separate trial/complimentary wording, protected read-only preview endpoints and a wide mobile editor. Preview never inserts a wedding, user, token or mail. Custom wording is escaped, header newlines are rejected, and invalid edits roll back account creation. A preview fingerprint rejects changed content/access/trial information before sending. Tokens hold each invitation's wording snapshot. Resending has its own preview and only invalidates the old link when sent.

The integration previously looked up newly queued mail by a fixed subject. It now joins the welcome token and user/wedding, which keeps delivery tracking correct with personalised subjects. Existing integration endpoints and the mapping schema are unchanged. One additive mail HTML column retains all old rows and the encryption key. No real couple, SMTP provider or payment was contacted during verification.

## v1.0.6 follow-up — onboarding and admin sign-in

The previous admin flow only managed existing couple accounts; it lacked an invitation-led creation path. Added validated admin creation and resending, complete welcome/password/terms acceptance, verification through the invitation, full trial start at acceptance, fixed complimentary end date, existing-account collision protection and a durable policy acceptance record. No real recipient was contacted during testing.

Reopening the protected admin page during pending 2FA previously redirected towards password login. Wrong-code errors replaced the form with a generic message. Pending admin entry now resumes its challenge, wrong codes retain the form, and complete/expired challenges redirect appropriately. Browser tests cover reload/reopen/return and retry; the exact Android authenticator app handover cannot be reproduced in this environment and remains a live-device confirmation. Session expiry and cookie loss are not bypassed.

## v1.0.5 follow-up — bank default settings

Found that a grouped account number such as `00 12 34 56` exceeded the ten-character input limit and could be truncated to seven digits. Expanded routing input limits; server normalises ordinary and Unicode whitespace before strict digit checks. Save errors previously appeared above the long form and could be missed; feedback now scrolls into view and failed inputs stay intact. Verified choosing bank as default, saving the full form and reloading preserves the selection and leading-zero account number. Live installation errors beyond these reproduced cases still need their specific message.

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

## v1.0.2 follow-up: admin email workflow

The first deployment revealed that sender/reply-to fields were insufficient to configure a sending mailbox. SMTP connection and encrypted credentials can now be managed from superadmin. Test delivery runs against the selected saved transport and records acceptance/failure, rather than reporting success from queue insertion alone. Provider exception text is not exposed; actionable fixed error hints replace it. Existing environment configuration is retained as an option. Independent settings saves no longer rewrite every setting, avoiding accidental replacement of unrelated values or worker status. Password fields clear after a successful save, remain blank on reload, and blank submissions keep the stored credential.

Regression tests cover encrypted storage and API privacy, blank/replaced/removed passwords, invalid configuration rollback, admin-only access, SSL/STARTTLS with verified TLS, test delivery/history, worker sending/retry, fixed authentication errors, old environment fallback, signup readiness, migration without replacing records/key, and safe handling of a lost QUIT acknowledgement. Chromium checks cover the admin flow on four screen widths in light and dark mode, form refresh without losing edits, and correction of rejected credentials. Live SMTP provider acceptance/delivery must still be verified using the user's mailbox after deployment.

## v1.0.3 follow-up: PayPal.Me payments

Manual PayPal payments now have a reference, frozen terms, an unverified reporting stage and an authenticated admin confirmation stage. Payment reports do not activate access or count as sales. Verification requires a matching gross GBP amount and a unique PayPal transaction ID checked by the administrator. Confirmation is idempotent and preserves longer access. Refunded receipts remain in the audit trail; refund recording does not move funds or automatically change access. Provider switches cannot create a second Stripe checkout while a PayPal request is unresolved. Profile URLs are restricted to HTTPS PayPal.Me profile links.

69 backend tests and the browser payment journey passed. Phone/desktop light/dark layouts were checked at 320/390/736/1024 pixels. Tests did not visit PayPal or send a real payment. PayPal.Me does not provide automatic payment verification in this integration; live recipient/currency and delivery checks remain merchant installation tasks.

## v1.0.4 follow-up: bank transfers and targeted requests

The global payment method no longer needs to be changed to satisfy an individual couple's preference. Admin creates a targeted bank/PayPal request, optionally queues email to verified members, and the couple accepts the stored terms before instructions. Bank sort code/account number preserve leading zeros. Bank details are visible to the correct signed-in wedding and authorised admin, not public pages or request emails. Outstanding requests cannot be overwritten with a different method. Verification requires matching GBP funds and a unique bank/PayPal receipt reference; self-reporting remains unverified.

85 backend tests pass, including 16 bank/request cases. Chromium checks cover bank setup, per-couple choice, queued email, conflict prevention, consent, leading-zero display, payment reports, manual activation, and four widths/light/dark without overflow or JavaScript errors. A fake mailbox/backend was used and no real transfer or external email was sent. Real recipient details and actual bank receipt must be checked by the merchant on deployment.



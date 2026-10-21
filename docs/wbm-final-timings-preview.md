# WBM planner timings: V8.75 / 1.3.0 release

Deploy planner 1.3.0 first and booking V8.75 second. The timings feature is off
until explicitly enabled in booking Settings → Planner invitations. The existing planner
invitation connection remains the only machine credential. No real couples
were read, linked, invited, submitted or edited during development.

## Flow

The booking app pulls from the planner over the existing fixed HTTPS origin.
When explicitly enabled in booking Settings → Planner invitations, it matches
native confirmed/in-progress WBM wedding bookings with an accepted quote and
fully paid booking deposit. A verified planner member email AND the exact
wedding date must match uniquely. Complimentary access alone never qualifies.
Studio Ninja imports, suppressed/test/archived bookings and ambiguous matches
remain outside this automation. An existing manual planner can be linked without
an invitation or any change to its plans, access or payment status.

Only a linked couple sees Send final timings to Mark. It previews the booking
app's current photography questions, prefills saved planner timings and asks
for missing details. A separate confirmation queues a snapshot; it does not
send on ordinary saves. Unsaved/conflicted forms and stale plan/Day Hub revisions
block submission. No budget, guest list, supplier contacts or private notes are
transferred. The explicit photography answers, photographer-visible timeline
and photo-group titles are shown in the preview and retained in the receipt.

The booking app polls linked accounts roughly every two minutes (bounded batches),
validates with its existing timing/calculation/template rules, stores a normal
final_timings submission plus an immutable receipt, creates the private PDF and
review task, and uses its existing private owner-notification path. The planner
says Queued until acknowledged by the booking app. Replaying a lost acknowledgement
does not create a second receipt or notification. Later explicit submissions retain
all prior receipt snapshots. Existing portal/imported timing answers are never
silently replaced; that conflict needs manual review. Failed owner email delivery
uses the existing logging/retry facilities; SMTP delivery cannot be guaranteed.

## Automatic reminder policy (off until explicitly enabled)

Only the existing combined check_in_30 invitation is held. Editing actual day
planning data or adding Day Hub activities counts as active use; signing in or
accepting an invite alone does not. A fresh successful check is required to hold
an email. With no valid submission, the existing form becomes eligible again
21 days before the wedding. Connection/match/validation failures use the normal
workflow. A received valid snapshot removes the need for the duplicate form.
Explicit admin sends are not silently blocked. Existing final-call tasks and all
other reminder/payment rules are unchanged. The 21-day fallback is clearly shown before opt-in.

Booking account/date changes invalidate old receipt-based suppression. The planner
button also expires if booking checks stop for more than ten minutes. Submissions
remain queued for safe collection after the connection returns.

## Storage and rollback

Additive booking tables: planner_timing_links and planner_timing_receipts.
Additive planner tables: wbm_timing_links and wbm_timing_submissions. Existing
initialisation creates them; no existing rows are rewritten or backfilled.
Standard whole-database backups include them. Before any production deployment,
back up both apps and preserve their images. Deploy planner first, booking second;
leave timing integration off until the paired version checks pass. Restore old
images with the option off if needed; do not drop new tables containing receipts.
Use scripts/deploy-v130.sh for the planner and DEPLOY-V8.75.sh for booking. Both
preserve the running image and back up data before restarting. Planner also
rehearses restoring the backup in an isolated container.

## Validation

Two real application stacks in disposable SQLite databases with intercepted
transport and notification delivery: authentication, CSRF, matching, fallback,
validation, custom questions, PDF creation, review tasks, repeated/lost responses,
revision conflicts, immutable receipts and excluded imported records. Existing
invitation regressions are included. No real SMTP or live API requests are made.
UI checks exercise linked-only visibility, unsaved guards, prefill, conditional
fields, explicit preview/confirmation, light/dark and 320/390/768/1280px widths.

Receiving and first-link creation serialize on the booking row in PostgreSQL,
with the receipt checked again after taking the lock. PostgreSQL execution could
not be rehearsed in the restricted development environment; the paired tests use
SQLite. Check the first real submission after opt-in and verify the PDF and
planner receipt. No real accounts were used as test fixtures.

### Running the paired regression

Check out both repositories side by side on their release branches.
Use a disposable virtual environment with the booking requirements-dev.txt plus
Flask 3.1.3 (the planner uses Flask). Run booking tests/test_v875_planner_timings.py
and tests/test_v871_planner_invitations.py together. The new paired fixture uses
a unique temporary booking database and planner directory; transport and owner
notification delivery are intercepted. Planner tests/test_wbm_timings.py and
tests/test_booking_connection.py run from the planner repository.

For the standalone UI test, generate /tmp/wbm-timing-template.json by JSON-encoding
app.timings_forms.public_template(app.timings_forms.default_template()) in the
booking environment. Run planner tests/test_wbm_timings_browser.cjs with the
runtime Playwright module and WBM_TEST_CHROME pointing to a local headless Chrome.
The UI test mocks all API calls and aborts all network requests.

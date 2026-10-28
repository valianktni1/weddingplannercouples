# Ivory Planning Assistant — v1.9.7

## Couple journey

When enabled, **Help me with an invitation**, **Help me with our table plan** and **Menu → Our settings → Planning assistant** open the guided helper. While disabled or without a server key, existing navigation stays unchanged; the direct assistant page explains availability and links back to manual tools.

The first version asks three guided questions. Invitation answers select day/evening, one of the eight current collections, a palette, tone, confirmed arrival details and a combined change request. Current wedding names/date/venue are used even if an earlier invitation draft is stale. Existing size, photo ID and crop settings remain local and preserved. Only intro/message/closing wording is model-generated; newly illustrated artwork and arbitrary layout editing are outside this release.

Seating answers use existing tables with entered capacities or create 1–20 uniformly sized round/long tables. Only accepted day guests are rearranged (maximum 150). Other guests' seats count against capacity. Together/apart groups are explicit guest-ID selections, not name guesses or inferred family relationships. Each group has 2–30 different selected guests, up to 20 groups of each type. Contradictory groups and insufficient capacity are rejected before a paid call. Existing table labels should be imported into the Hub and given capacities before generation.

The couple consents to sending the task data to OpenAI, then chooses **Generate draft · 1 AI round**. A checked proposal is a preview, not a save. Invitations use the existing real stationery renderer; seating shows every assigned guest/table. Applying requires a second explicit review checkbox. Existing planner/Hub sharing behaviour applies to a saved seating change, including already-enabled private-share update notices. The assistant never sends invitations or changes guest-facing website publication.

## Allowances and paid extras

Both members share one invitation allowance and one seating allowance. Each contains three successful generations: the initial draft and two revision rounds. Day/evening invitations share their allowance; changing kind/style does not reset it. Generating a valid proposal counts even if it is not applied. A batch of requested edits is one generation. Refresh, preview, apply and undo do not count. Failed, incomplete, refused, invalid and generation-time-stale proposals do not count.

A couple can report an assistant mistake without spending an AI round. Admin reviews that report and can return one round once for that draft. Correction credits restore allowance, not already-incurred API expenditure.

Paid extras are arranged manually using the business's normal agreed payment process. Admin first chooses a GBP per-round price; it is blank by default. Couple-facing text shows the price/contact route. There is no automatic debit or self-certified payment unlock. Admin records the cleared GBP amount, quantity and unique transaction reference only after checking the payment. Reused references are rejected across AI credits, planner manual receipts and bespoke receipts. Extra rounds never extend editing access or override API limits. Check both before taking payment. Normal manual editing remains included under the couple's existing planner access.

## Model and spending

Only `gpt-6.1-sol`, medium reasoning, standard/default service tier is called, at the fixed HTTPS Responses endpoint. Output is limited to 8192 tokens, input request JSON to 100 KB and responses to 1 MB. A single request has a 35-second socket timeout; no automatic retry or fallback model is used. There are no model tools, arbitrary code execution or model-generated SQL. Refusals, incomplete output, unsupported fields and invalid results are rejected.

The monthly global and wedding-specific budgets use integer micro-USD and UTC calendar months. Defaults are $10 global/$2 per wedding. A SQLite `BEGIN IMMEDIATE` transaction reserves a conservative request maximum before contacting the provider. Different couples share the same atomic global limit; partners share their wedding limit. One generation runs at a time per wedding. The reservation uses the complete UTF-8 request byte count plus an 8192-token input margin and maximum output; this intentionally overestimates input token use. Budget accounting estimates input at $3/million (also covering the current cache-write rate) and output/reasoning at $10/million, with no cached-input discount. These are conservative enforcement estimates, not an invoice or guaranteed GBP amount including tax/fees. A reported cost above its reservation pauses AI.

Known reported token usage settles the reserve on success and locally invalid drafts. Unknown provider outcomes retain the reserve so a timeout cannot silently create free spending capacity. Definite HTTP rejection (400/401/403/404/422/429) releases the reserve; authentication/permission rejection also pauses AI. No API call is made by configuration, availability, preview, apply, undo, reporting or top-up actions.

Request IDs are bound to wedding and request hash. Replaying the same request returns its recorded state rather than another provider call. A lost browser connection offers status refresh before another generation. A crashed generation can stop blocking the wedding after 120 seconds, while its uncertain cost reserve remains. Daily request throttles also apply. Paid credits and correction refunds do not reset cost budgets.

## Data and saves

All routes require the existing verified couple/admin authentication and CSRF protections. Couple ownership and current editing access are checked for writes; suspended/deleting weddings are blocked by existing access rules. Models only propose schema-limited data. Local validation checks every guest exactly once, permitted tables, available capacities and each hard together/apart rule. Invitations use existing field and renderer validation before counting a round or applying.

Invitation drafts are tied to the saved design revision and source-detail hash. Seating drafts are tied to wedding and Hub revisions and table definitions. New partner/manual/RSVP edits stop stale Apply rather than being overwritten. Undo is idempotent and stops when its target has newer changes. It restores only the invitation or the selected seat assignments/tables; normal state validation and Hub notifications are retained.

Only needed invitation facts, selected guest names/households and explicit seating instructions are sent. No API keys, payment information, dietary/access data, private family notes or photograph bytes are sent to the model. Free-text instructions are opt-in, length-limited and accompanied by a sensitive-data warning. `store:false` is requested; this is not a promise of zero provider retention. Site privacy wording should describe the new provider/data flow before public enablement.

Private drafts, question answers, reports and paid-credit records live in wedding-scoped tables. The existing permanent deletion/managed-backup cleanup discovers `wedding_id` tables and removes them. The cost ledger contains no wedding/user ID, prompt, response or payment reference and remains only to preserve aggregate spending enforcement after deletion. Couple exports include their own assistant drafts/credit amounts; they never include server credentials or the provider cost ledger.

## Setup and verification limits

Use `scripts/configure_assistant_key.py` interactively on TrueNAS, recreate the web container and enable through Admin → System & security → Manage planning assistant. The helper writes only the external private environment file, keeps a protected backup, rejects unsafe values and does not call OpenAI. Never put a real key in Git or paste it into chat.

Automated backend/browser checks use simulated provider responses and disposable data with browser-QA SMTP blocked. They validate transport payload settings, app state transitions and failure behaviour, not production model quality or account/billing readiness. After deploying with the assistant off, configure a dedicated key and run one explicitly consented task in a sample wedding before enabling wider use. Physical Android guest-group selection, the real provider response and actual NAS restore/build remain installation checks.

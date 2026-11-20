# W5 forward official issuer-event capture protocol

**Evidence time:** 2026-11-14T09:05:10.030883+00:00 · **Status:** `NOT_CONFIGURED` · **Actual legally captured
rows:** **0** · **Authority:** `RESEARCH_ONLY`

## Source and rights gate

Discovery begins only at the official NSE announcements/XBRL and corporate-actions pages listed
in `wave5_event_capture_manifest.json`. Attempts to recheck those pages and terms timed out in
this environment. A public webpage is not a licence to crawl, archive attachments or
redistribute exchange data; therefore automated capture, original-byte storage and scheduling
remain disabled. Use only a documented export/feed after operator/legal permission.

The collector has no undocumented NSE endpoint and no generic browser/shell/SQL tool. It uses an
injected bounded transport only after: operator enablement, `PERMISSION_GRANTED`, exact HTTPS host
allowlist, timeout/rate/size caps and content-type checks. 429/503 are typed retryable errors and
open a circuit after bounded failures. No W5 unit test accesses the internet.

## Immutable capture clocks and identity

For each permitted observation store issuer ID, symbol, ISIN, source/document ID and URL,
category, exchange broadcast timestamp, independently supported original publication timestamp,
provider first-seen, **exact first local observation UTC**, `available_at`, content/attachment
hashes, attachment status, rights label and immutable correction/withdrawal links.

`available_at` is never earlier than first local possession. A disclosure fetched now with a
2023 broadcast stamp is `RETROSPECTIVE_RETRIEVAL`, never contemporary. `available_at >
decision_cutoff` is unavailable without exception. Exact duplicates preserve the original
first-seen; same-ID byte edits mint new versions. Wrong issuer/ISIN/host/timestamp fails closed.
Original bytes are hash-and-reference only unless rights explicitly permit immutable archival.

Hostile disclosure text is untrusted data. Injection-shaped content is hashed and quarantined
with `model_eligible=false`; it is never followed as an instruction. No disclosure body or secret
is sent to Jev/Mercury in W5.

## Blind human goldset workflow (preregister before outcomes)

1. Sample forward captures by issuer size/liquidity, category, time-of-day and preliminary
   human materiality strata—never by model score or later return.
2. Allocate an independent `HG-*` event ID and fixed fold before labels/outcomes.
3. Two reviewers independently label event type, guidance change and materiality while blinded
   to Jev/baseline output and all post-event prices.
4. Conflicts go to a third adjudicator; original reviewer records remain immutable.
5. Seal version/fold/timestamps and the adjudication manifest before any paired evaluation.
6. Model/classification/outcome/return fields are structurally forbidden in the human-label
   contract. W4's 24 authored synthetic rows remain unchanged and outside the real goldset.
7. Pre-register paired A–E hypotheses, exclusions, metrics and multiplicity treatment before
   newly captured forward outcomes mature.

No real goldset exists yet: `GOLDSET_HOLDOUT_UNAVAILABLE`.

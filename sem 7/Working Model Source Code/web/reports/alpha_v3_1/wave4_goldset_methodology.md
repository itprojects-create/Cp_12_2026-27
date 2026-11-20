# W4 — Event goldset methodology (synthetic v1) and forward-capture protocol

Generated: 2026-11-14T08:28:47.860313+00:00 · Fixture: `events_ai/goldset/synthetic_v1.json`
(sha256 `870c303e7b239ea305d4b6ac448cddd97f49d2baf2ca33f01bc2860f40880dd6`)

## 1. What this goldset is — and is not

**It is:** 24 authored, fully synthetic fixtures (invented issuers `EXAMPLE
LTD`, `SYNTHETIC PHARMA LTD`, … and invented filing text) built as an
**engineering check of the metric machinery, validation boundaries and
fail-closed adapter paths**. It exercises: clean classify rows (19), one
injected filing (SYN-EV19), one wrong issuer binding (SYN-EV20), one
available-after-cutoff PIT violation (SYN-EV21), one timestamp-order violation
(SYN-EV22), one forged source hash (SYN-EV23), and one RETROSPECTIVE
reconstruction (SYN-EV24, never forward-eligible).

**It is not:** a measurement of real Jev classification quality. There is no
real market data, no real issuer, and the "model" is a scripted fake transport
(`events_ai/offline_check.py`) whose deliberately imperfect answers were fixed
in code **before** any metric was computed. Every number derived from it is
labelled `ENGINEERING_CHECK_SYNTHETIC`.

**Why no real goldset exists yet:** a lawful contemporaneous corpus of official
Indian issuer announcements with verified hashes and PIT stamps is not
available offline today. Building one by scraping retrospective archives and
back-dating labels would fabricate contemporaneity — refused by design
(RETROSPECTIVE ≠ CONTEMPORANEOUS). Status: `GOLDSET_HOLDOUT_UNAVAILABLE`.

## 2. Labelling protocol (recorded before reveal)

- Rubric: `events_ai_rubric/1` — 7 event types (financial_results, guidance_change,
  governance, contract, capital_action, other, none), 5 materiality levels,
  review threshold 0.6 on event-type confidence.
- Labeler: the W4 implementer (single-labeler; NOT an expert panel). Labels were
  authored **before any model call**, blind to model outputs and to market
  outcomes; disagreements are marked `needs_review` rather than adjudicated.
- Per-row gold: `event_type`, `guidance_change` (true/false/null), `materiality`
  (0–4), `needs_review`.
- Independence: the label file carries no model output; the adapter prompt
  never contains gold labels (tested: sent request bodies contain no `gold`
  keys).

## 3. Minimum quality policy — declared BEFORE any real-goldset evaluation

For a future real labelled goldset (preregistered here), Jev may enter Arm C
features only if, on the paired evaluable subset:

1. macro-F1 ≥ the deterministic keyword baseline's macro-F1 on the same subset;
2. guidance-change false-positive rate ≤ the baseline's;
3. abstention+review is surfaced (never silently forced to a class);
4. no fabricated numbers: any unsupported numeric claim in an answer is a
   contract violation (adapter rejects).

Classification-quality metrics alone justify **no financial performance
claim** of any kind.

## 4. Forward-event capture protocol (the honest path to real evidence)

1. Capture official issuer announcements contemporaneously: record
   `published_at`, `first_seen_at` (our true first sight), `available_at`
   (admissible-at), `decision_cutoff`, source URI + byte hash, rights label.
2. Only `CONTEMPORANEOUS` evidence is forward-eligible; `RETROSPECTIVE` /
   `VENDOR_RECONSTRUCTION` rows are stored and labelled but can never feed a
   forward decision.
3. Labels for forward rows are written after capture and before outcome
   maturity, by a reviewer other than the implementer where possible; the
   label schema and rubric version are frozen above.
4. Ids are stable: `event_id` excludes capture metadata, so re-captures never
   fork the semantic event (tested).
5. This protocol plugs into the W3 forward harness (`wave3_forward_protocol.md`)
   as the event-intelligence track.

## 5. Reproduction

```bash
python -m pytest tests/test_research_v3_events_ai.py -q   # 78 tests incl. metrics
python scripts/wave4_run_events_ai.py                      # regenerates all wave4_* files
```

Determinism: two offline runs produce identical classification ids, identical
store record hashes and identical metrics (verified in this run:
{"runs": 2, "classification_ids_identical": true, "store_record_hashes_identical": true, "chain_verified_a": [true, null], "chain_verified_b": [true, null], "metrics_identical": true, "store_written": "temp dir only (records carry hashes, no excerpt bodies)"}).

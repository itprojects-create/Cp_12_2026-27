# W4 — Provider contract, verification and security (Jev / SystemOne)

Generated: 2026-11-14T08:28:47.860313+00:00 · Status label: **EVIDENCE: VERIFIED_ISSUER + LIVE_SMOKE_OK (redacted)**

## 1. Issuer verification (how we know who served the key)

- The server-side `EXPLABS_API_KEY` (prod `.env`) was proven by two independent
  facts to be an **ExperientialLabs organisation key**: ExperientialLabs' own
  vendor setup documentation, and the operator's production configuration that
  already routes this key to `https://api.experientiallabs.ai/v1`.
- Gateway: `https://api.experientiallabs.ai/v1` · Auth: `Authorization: Bearer` ·
  Uniform auth failure: HTTP 401 `invalid_key` (never a different error body).
- Entitlement discovery (read-only, free): `GET /v1/models` → **HTTP 200**,
  **307 models** listed, including `jev-latest`, `clef`, `clef-flash`,
  `mercury-3`. The key is entitled to the gateway catalogue.

## 2. SystemOne (Jev) API contract — pinned from official sources

Pinned from `https://api.typesafe.ai/openapi.json` (v0.2.0) and
`https://docs.typesafe.ai/api/system-one.md`:

- Request: `{model, state, questions}` — `state` carries issuer, document id,
  `official_excerpt`, `available_at`; `questions` are `event_type` (choice over
  7 options), `explicit_guidance_change` (noul), `materiality` (score 0–4 with
  legend).
- Response: `answers` keyed by question name — `noul` (P(no event in excerpt)
  style null-answer probability), `choice{choice,confidence,probabilities}`,
  `score{score,confidence,legend,probabilities}` — plus
  `usage{input_tokens,output_tokens}` (output tokens free of charge).
- The served model may differ from the requested alias; the adapter records
  `requested_model` and `model_id` separately and fails on unknown models.

## 3. Adapter security controls (events_ai/adapter.py, all offline-tested)

| Control | Behaviour |
|---|---|
| Host allowlist | per-provider hosts only (`experientiallabs_gateway` → api.experientiallabs.ai, `typesafe_direct` → api.typesafe.ai); override host ⇒ `UNAVAILABLE:host_not_in_allowlist`, zero requests sent |
| Key handling | per-provider env var (`EXPLABS_API_KEY` / `TYPESAFE_API_KEY`); missing key ⇒ `UNAVAILABLE:missing_secret:…`; key never enters request bodies, error text or the store (`_sanitize` scrubs credential-shaped substrings — incl. the fixed lowercase-case bug covered by tests) |
| Budget | preflight against a day-keyed `UsageMeter` (requests/day, spend/day) ⇒ `UNAVAILABLE:BUDGET_EXHAUSTED:*` before any network call |
| Retries | 429/5xx only, bounded (≤2 retries, `Retry-After` capped at 5 s); 400/401/403/422 hard-fail `INVALID:HTTP_*` with no retry |
| Circuit breaker | repeated hard failures open the circuit ⇒ `UNAVAILABLE:CIRCUIT_OPEN`, no requests while open |
| Size caps | request body ≤ 64 KB, response ≤ 256 KB (larger ⇒ `NEEDS_REVIEW:RESPONSE_TOO_LARGE`) |
| Parsing | NaN/Infinity-rejecting JSON load; any contract violation ⇒ `INVALID:RESPONSE_INVALID:…` (never a favourable default) |
| Evidence gating | PIT violations, timestamp-order violations, forged hashes, TAMPERED sources ⇒ `INVALID:EVIDENCE_INVALID:…`; suspected prompt injection in the filing ⇒ `NEEDS_REVIEW:INJECTION_SUSPECTED`, the text never reaches the model |
| No-trade | package contains no order/ledger/risk surface (AST-tested); classifications are research evidence only |

## 4. Live smoke — Jev (2026-11-13, budgeted, redacted)

One call, synthetic EXAMPLE LTD state, key read only from the server `.env`
(never printed, never copied into any file). Evidence retained with raw-body
hash only; excerpt text is synthetic.

```json
{
 "endpoint": "https://api.experientiallabs.ai/v1/systemone",
 "provider": "experientiallabs_gateway",
 "requested_model": "jev-latest",
 "http_status": 200,
 "error_kind": null,
 "latency_ms": 810,
 "returned_model": "jev-latest",
 "answers": null,
 "usage": {
  "input_tokens": 616,
  "output_tokens": 110,
  "cost": 0.0,
  "is_byok": false
 },
 "checks": {
  "errors": [],
  "event_type": {
   "type": "choice",
   "choice": "financial_results",
   "confidence": 0.63,
   "prob_sum": 1.0,
   "keys_match_options": true
  },
  "explicit_guidance_change": {
   "type": "noul",
   "noul": 0.04,
   "in_unit_interval": true
  },
  "materiality": {
   "type": "score",
   "score": 1.04,
   "confidence": 0.91,
   "prob_sum": 1.0,
   "legend": {
    "0": "Administrative/no material issuer fact",
    "1": "Routine announcement",
    "2": "Potentially consequential",
    "3": "Major consequential development",
    "4": "Exceptional confirmed issuer development"
   }
  }
 },
 "raw_body_sha256": "230540f4a6ec2f3843e64eb9caf12f6b6a2d9f22fcee444d74cfc210b9267c8e"
}
```

Reading: HTTP 200 in 810 ms; requested+returned `jev-latest`; 616 input / 110
output tokens; gateway cost 0.0 (free tier); all three answers contract-valid
(choice `financial_results` conf 0.63 with probability sum 1.0 and keys matching
the 7-option rubric; `noul` 0.04 in unit interval; `materiality` score 1.04,
conf 0.91, legend complete, prob sum 1.0). This proves **transport, contract and
validation interoperability** — it is NOT a quality or alpha claim.

## 5. Key hygiene incident and required operator action

- The operator pasted a Jev key into this chat (`xpl_…355b`). **Chat is not a
  secret store: that key must be treated as exposed and rotated.**
- No server-side copy of the pasted key exists: the server `EXPLABS_API_KEY`
  fingerprint ends `…e2e7`, different from the pasted `…355b`, so the pasted
  key was never used by any code, script, test or report, and was never
  echoed, logged or written to a file.
- All live work used the server-side key only, read at runtime from
  `D:\QP\agent-service\.env`.

## 6. Provider lanes — tested vs not

| Lane | Status | Evidence |
|---|---|---|
| `experientiallabs_gateway` (Jev) | **LIVE_SMOKE_OK** | §4 above |
| `typesafe_direct` (same SystemOne contract) | **NOT_TESTED** | no TypeSafe-issued key exists anywhere; adapter implements the lane and allowlists `api.typesafe.ai` only |
| Mercury-3 (InceptionLabs direct) | **LIVE_SMOKE_OK** | see `wave4_mercury_research_tools_audit.md` — stays on the verified direct lane, no gateway substitution |

## 7. Security notes carried forward

- Free-tier Jev shares 10 RPM / 250K TPM / 1M tokens per UTC day (vendor setup
  doc); the adapter's per-day budget defaults stay far below this.
- "Clef and Jev use the native decisions API, not chat" — the adapter posts to
  `/v1/systemone`, never to a chat endpoint.
- `jev-latest` is an alias: production should pin an explicit version once the
  vendor exposes one; until then `requested_model`/`model_id` discipline applies.

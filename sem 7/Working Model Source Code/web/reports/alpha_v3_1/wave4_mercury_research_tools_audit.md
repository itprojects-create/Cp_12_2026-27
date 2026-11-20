# W4 — Mercury-3 research-tools audit (bounded integration)

Generated: 2026-11-14T08:28:47.860313+00:00 · Code: `events_ai/mercury_tools.py` (dispatcher) +
`MercuryResearchClient` · Status: **ENGINEERING PASS — not wired into any
production path in W4**

## 1. Threat model and hard boundaries

Mercury-3 is a fast reasoning model used only as a **research memo writer over
deterministic tool results**. It is never an alpha source, never a classifier
and never a trade authority.

| Boundary | Enforcement (tested) |
|---|---|
| Tool allowlist | frozen 4-tool set: `lab.run_backtest`, `lab.run_sweep`, `lab.challenge_finding`, `lab.research_journal_status` — everything else `REFUSED_NOT_IN_ALLOWLIST` |
| No shell / SQL / network / filesystem / secret tools | allowlist has no such entries; request args are regex-scanned for path traversal, SQL verbs, `import/eval/exec`, sockets, `subprocess` ⇒ `REFUSED_UNSAFE_ARG:*` **before** schema validation |
| Schema-validated args | sha256 fingerprints, enum grid names, result-id shapes; any mismatch ⇒ `REFUSED_INVALID_ARGS:*` |
| Numbers never from the model | every executed tool is a deterministic W2/W3 function; envelope stamps `produced_by: "deterministic:<tool>"` and a `result_sha256`; the memo cites only numbers present in the tool result |
| Grounding check | every multi-digit number in the memo must appear verbatim in the tool-result JSON, else `UNGROUND_NUMBER:*` and `grounded=false` |
| Idempotency | same `idempotency_key` replays the cached envelope (no double execution); refusals are not cached |
| Budget | `MAX_CALLS_PER_SESSION = 8`; disabled by default (`QUANTPLUS_MERCURY_RESEARCH_ENABLED=false`) ⇒ `REFUSED_DISPATCHER_DISABLED`; exhausted ⇒ `REFUSED_BUDGET_EXHAUSTED` |
| Fail-closed client | pinned `mercury-3` on the verified direct InceptionLabs lane (`https://api.inceptionlabs.ai/v1`, key env `INCEPTION_API_KEY`); missing key / HTTP error / malformed body ⇒ typed `MercuryUnavailable`, never a silent substitution by another model |
| Model mismatch | a returned model ≠ pinned model is recorded as a grounding problem; the response is never silently accepted as authoritative |
| Escalation scope | Jev `NEEDS_REVIEW` or evidence conflicts may route here for a **cited memo**; a memo can never override source fact checks or reclassify anything |

## 2. Live smoke — Mercury-3 (2026-11-13, 2 calls, redacted)

Lane: verified direct InceptionLabs; key read only from the prod `.env`
(`INCEPTION_API_KEY`), never printed or copied. No sampling params (vendor
setup rule).

```json
{
 "endpoint": "https://api.inceptionlabs.ai/v1/chat/completions",
 "provider": "inceptionlabs_direct",
 "requested_model": "mercury-3",
 "http_status": 200,
 "error_kind": null,
 "latency_ms": 680,
 "returned_model": "mercury-3",
 "content_preview_len": 2,
 "content_sha256": "2689367b205c16ce32ed4200942b8b8b1e262dfc70d9bc9fbc77c49699a4f1df",
 "usage": {
  "prompt_tokens": 8,
  "completion_tokens": 25,
  "total_tokens": 33,
  "prompt_tokens_details": {
   "cached_tokens": 0
  },
  "completion_tokens_details": {
   "reasoning_tokens": 22
  }
 },
 "finish_reason": "stop"
}
```

Honest reading, both calls:

1. **First call** (`max_tokens=8`): HTTP 200, `mercury-3` returned, finish
   `stop`, but **visible content was empty** — Mercury spent the entire token
   budget on reasoning tokens. Operational lesson recorded: reasoning tokens
   count as completion tokens, so `max_tokens` must be ≥ 64 for any visible
   content. This call's evidence was overwritten by the second run of the smoke
   script (the file retains one record); it is documented from the session
   transcript, not independently captured.
2. **Second call** (`max_tokens=64`, retained in the evidence file above):
   HTTP 200 in 680 ms, `mercury-3` returned, content `"ok"` (2 chars, sha256
   `2689367b…`), usage 8 prompt + 25 completion (of which **22 reasoning
   tokens**), 33 total, finish `stop`.

Total live spend: ~$0. The smoke proves transport + pinned-model + redaction
discipline only — no research claim.

## 3. Dispatcher executor bindings (production wiring contract)

The dispatcher ships **unbound** in W4: `executors` are injected; production
must bind exactly the W2 lab functions (`lab.run_backtest`, `lab.run_sweep`,
`lab.challenge_finding`, `lab.research_journal_status`) — the same engines W2
already fingerprints and journals. `quantlab` (W3 numeric plane) never imports
`events_ai` (AST-tested), so Mercury cannot perturb the frozen control.

# Prereg: Day-3 layered memory + calibration/Kelly (NEWW_PLAN)

**Written:** before any Day-3 code. Deterministic except reflection *text*
(which never touches money). Zero tokens in loop; any LLM prose is log-only.

## 1. Layered memory (FinMem-adapted, PIT-clean)

Three layers by data timeliness, each with half-life decay:
- shallow (news/sentiment): half-life 5d
- interim (technical/delivery/positioning): half-life 20d
- deep (earnings/fundamentals/settled lessons): half-life 90d

Retrieval score = recency×0.4 + relevancy×0.4 + importance×0.2 (keyword-overlap
relevancy; no embeddings — deterministic). Top-K per layer into veto context.
High-access events promote one layer deeper (recency reset, logged).
New table `mem_events`; `memory_settlements` untouched except ADD COLUMN
(veto, regime, breadth, size — NULL for history, populated going forward).

## 2. Dual reflection (veto context only — pipeline prompts untouched)

- market-reflection: from settled rows, bucketed by (regime, veto-band):
  "when veto in [a,b] under regime R, whipsaw rate was x/y".
- decision-reflection: extends existing past_context with veto/outcome pairs.
- Consumer: `build_veto_context(as_of)` → session log + calibration report +
  Day-4 foundry inputs. NOT injected into frozen Manager/Devil prompts
  (no PROMPT_VERSION bump, no cache invalidation).

## 3. Whipsaw label (from settled memory only)

label = 1 iff raw_ret net of (size × ROUNDTRIP_COST) < 0 else 0, joined with
the stored veto/regime/breadth of that same session. Training rows = veto IS
NOT NULL only (i.e., Day-6-forward data). **Calibrator refuses below 50 labeled
rows** → returns identity map (raw veto passes through, logged).

## 4. Isotonic (PAVA) + fractional Kelly, veto-only bounds

- v_cal = isotonic(raw veto → P(whipsaw)), monotone non-decreasing by construction.
- Kelly gate: p = 1 − v_cal; b = avg_win/avg_loss over labeled rows (fallback
  b=1.0 below 50 rows... no — below 50 rows the whole calibrator is identity,
  so b is always computed on ≥50 rows); f* = ((p·b − q)/b)·0.5, clamped [0,1].
- Final: size = core_size × (1 − v_cal); if f* ≤ 0 → veto = 1.0 (full veto).
  Output provably within [0, core_size] — veto-only preserved, never increases.

## Gate

Day-3 exit = synthetic proof only: monotone map + Brier improvement on
constructed monotone data; sizing bounds on adversarial inputs; decay ordering
(recent > old at equal importance; deep outlasts shallow); retrieval top-K;
PIT (resolved_at <= as_of enforced in every query). No forward training until
Day-6 clock; thresholds change only by amendment.

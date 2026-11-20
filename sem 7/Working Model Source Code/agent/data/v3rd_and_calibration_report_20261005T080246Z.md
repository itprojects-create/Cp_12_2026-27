# v3rd Clean Eval + Calibration Inversion Diagnostic — Combined Report

**Date:** 2026-10-05T08:02:46Z (Part A executed 09:18–09:19Z same day) · **Code:** `PROMPT_VERSION=m3` (M2 rehab landed) · **Gates:** frozen 2026-09-18, untouched
**Scope:** measurement only. No Devil/Manager/PM/risk/gate/schema/frontend changes. No fix implemented.

---

## 1. Part A — v3rd eval: EXECUTED under option (c), labeled PARTIALLY CACHED, verdict FAIL

**Status: ran `python scripts/run_eval_live.py --set v3` once to completion (24/24) after the owner chose option (c): resume as-is. This is explicitly NOT a first clean read — 8 sessions were cached from a 2026-09-20 peek, 1 resumed from a partial, 15 fresh. No re-runs; one infra crash-resume (see §1.3). Zero code changes for this run.**

### 1.0 Result (gate table, existing report format)

Report: `data/eval_report_20261005T091856Z.json` · `scenario_set=v3rd-2026-clean` · notes: "Official one-shot run on prompt m3" (one-shot mechanics, partially-cached inputs — see §1.2).

| # | Report JSON | Prompt / set | n_dec | acc (≥0.55) | hold (≥0.40) | trade (0.20–0.90) | calib | PnL | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| 8 | `eval_report_20261005T091856Z.json` | **m3 / v3rd-2026-clean (c)** | 17 | **0.176** (3/17) ✗ | 0.429 ✓ | 0.625 ✓ | ✗ | −0.0118 | **FAIL** |

Worst decisive accuracy of all 8 runs (prior worst 0.231); largest n_decisive (17 — the 2026 stress cluster is trend-heavy: 10 short / 7 long / 7 flat labels). First run since v4 to pass hold-rate (3/7: HDFCBANK, ONGC, BAJAJ-AUTO holds). Correct decisive: MARUTI sell/short, BHARTIARTL buy/long, HCLTECH buy/long. Characteristic misses: buying selloffs (RELIANCE/SBIN/SUNPHARMA/HINDALCO buys into short labels), selling rallies (POWERGRID/CIPLA sells into long labels), holds into trends (TITAN/ULTRACEMCO/NTPC holds into longs, AXIS/KOTAK/COALINDIA holds into shorts).

Devil distribution (first movement in 96 sessions): **HEALTHY 19 / WEAKENED 4 / BROKEN 1** — vs 0 non-HEALTHY in all 72 v5.1+m3 sessions before. The BROKEN is ULTRACEMCO 2026-03-24 (momentum long → hold/size-0), but the label was long, so the block turned a would-be trade into a MISS (real cost of falsification, same shape as SBIN under the M3 gate). WEAKENEDs: TCS, HDFCBANK, AXISBANK (peeked trio) + COALINDIA. Mechanism split: EVENT_DRIVEN 13, MOMENTUM 5, MEAN_REVERSION 2, OTHER 1, plus pre-M3-style payloads none (all M3). The stress cluster finally makes the Devil fire (5/24 non-HEALTHY).

### 1.1 Scenario-file check (the task's explicit stop condition)

- No git repo exists in this workspace (`fatal: not a git repository`), so no `git diff` is possible. Fallback evidence:
- `app/eval/scenarios_v3rd.py` mtime `2026-09-20 16:56:24 UTC` — matches the documented blind-build date (2026-09-20, before any eval on it). `app/eval/gates.py` mtime `2026-09-18 15:06:02 UTC` — matches the freeze date.
- Content assertions verified live (`python -c` import): 24 scenarios, 24 unique tickers, `SET_NAME=v3rd-2026-clean`, windows `2026-01-06..2026-07-14`, **zero pair overlap** with orig-24 and with `v5-2025-disjoint`. No `eval_report_*.json` on disk records `scenario_set=v3rd-2026-clean` (7 reports: sets `""×2` (=orig-24, predate the field), `v5-2025-disjoint×3`, `v1-2023-2024×2`).
- **File verdict: unchanged since blind build. The file-level stop condition did NOT trip.**

### 1.2 Session-store check (the condition that DID trip)

The same cfg hash as current code (`e0b35784eb1f`, PROMPT_VERSION=m3) already has sessions for **9/24 v3rd pairs** in `data/quantplus.db`:

| # | Instrument / as_of | sid | Status | Decision (stored) |
|---|---|---|---|---|
| 1 | RELIANCE.NS 2026-01-06 | 846b95c8… | done | buy 0.028 |
| 2 | INFY.NS 2026-01-13 | aea861ab… | done | buy 0.020 |
| 3 | TCS.NS 2026-01-20 | 4856262a… | done | buy 0.0125 (WEAKENED) |
| 4 | HDFCBANK.NS 2026-01-27 | fa680455… | done | hold 0.0 (WEAKENED) |
| 5 | ICICIBANK.NS 2026-02-03 | 68f508ff… | done | sell 0.0315 |
| 6 | SBIN.NS 2026-02-10 | 287d060e… | done | buy 0.0175 |
| 7 | AXISBANK.NS 2026-02-17 | fea275bd… | done | hold 0.0 (WEAKENED) |
| 8 | KOTAKBANK.NS 2026-02-24 | 3c8de25d… | done | hold 0.0 |
| 9 | MARUTI.NS 2026-03-03 | e54be204… | **running** (no decision; risk/decision checkpoints missing — interrupted mid-session) | — |

- Checkpoint `updated_at` stamps: `2026-09-20T16:58:18Z` → `18:05:41Z`, i.e. starting **~2 minutes after** `scenarios_v3rd.py` was written (16:56:24) and ~1h after the M2 rehab landed (`features.py`/`technical.py` 16:53–16:54). Exhaustion thresholds in these checkpoints are 2–3% (80th-pct rehab values), confirming they ran on current code.
- No `eval_report_*v3*` was ever written, and **no prompt/gate/schema file has a mtime after 18:05Z on 2026-09-20** (latest code mtimes: `technical.py`/`features.py` 16:53–16:54, `scenarios_v3rd.py` 16:56:24) — so no tuning-on-v3 happened after the peek. This reads as an **aborted first attempt at v3 (stopped at scenario #9, MARUTI, never reported)**, not a deliberate contamination.
- Consequence for eval discipline: `run_eval()` caches by deterministic sid — a `run_eval_live.py --set v3` now would **resume 8 cached + resume 1 partial + run 15 fresh**. That is not a one-shot first clean read. Running it and labeling it "first clean read — no contamination caveat" would be false.

### 1.3 Execution log (option c) — what actually ran

- First invocation 09:18Z: sessions 1–8 CACHED (the peek), #9 MARUTI resumed from its partial checkpoints and completed correctly (sell/short OK, 9,380 tokens), #10–16 ran fresh, then crash at #17 DRREDDY with `pandas.errors.EmptyDataError: No columns to parse from file` in `YFinanceProvider.ohlcv()` — a first-touch cache race (parallel analysts share one cache key per instrument/date with no lock; one thread read the file mid-write). No prompt/gate/schema file was touched; the cache file completed after the crash (122 rows, verified readable).
- Second invocation (same command, checkpoint-resume per standing eval discipline for infra crashes): #1–16 CACHED, #17–24 fresh. Completed 24/24. Day tokens 821,708 of 6M cap (~427k fresh this round; 8 cached sessions cost 0).
- Of the three options offered, (c) was chosen: numbers above carry the label **"partially cached (8 cached + 1 resumed + 15 fresh), not a first clean read."** Options (a)/(b) are now moot for this set — it has a recorded number and can no longer be a clean reserve; a future clean read needs a new blind set if one is wanted.

---

## 2. Part B — Calibration inversion diagnostic (read-only, `scripts/diagnose_calibration.py`)

Pool: all **104 decisive** sessions across the 8 stored `eval_report_*.json` (34 correct / 70 wrong; re-ran after Part A so the v3rd run is included). Fields per task: `size_eval` = scored `FinalDecision.size`; sizing drivers per `trader_risk.py` = `Thesis.conviction` → `TradeProposal.size_pct` → PM `FinalDecision.size` (capped at 10%, zeroed on flat/BROKEN or STRESSED+momentum, halved on ELEVATED+momentum; risk `adjusted_size` values are advisory via prompt text only). `mechanism_type` presence-checked on raw checkpoint JSON (pre-M3 payloads lack the key; not lumped as OTHER). Spearman = Pearson on average-tie ranks (pure-python, no scipy). Full rows + summary: `data/calibration_diagnostic.json`.

### 2.1 Pooled stats (3a) — decisive-only vs gate-convention cross-check

| Scope | n | mean size correct | mean size wrong | Direction | Spearman(size, correct) |
|---|---|---|---|---|---|
| **Decisive only (task spec)** | 104 (34 ok / 70 wrong) | 0.0262 | 0.0180 | **not inverted** | **+0.264** |
| ALL sessions (official gate convention, flat labels included) | 192 | 0.0146 | 0.0217 | **INVERTED** | — |

Supporting: mean conviction correct 0.5935 vs wrong 0.5854 (flat); mean proposal_size correct 0.0530 vs wrong 0.0429; Spearman(conviction, correct) **+0.033** (n=104, no signal); Spearman(proposal_size, correct) **+0.187** (n=104).

Per-report gate metric (ALL sessions, reproduced to confirm): all 8 INVERTED — v2 0.0096/0.0225, v4 0.0092/0.0100, v5 0.0198/0.0258, v5.1-orig 0.0236/0.0274, v5.1-new 0.0201/0.0259, m3-new 0.0117/0.0223, m3-orig 0.0174/0.0210, m3-v3rd (gate line recomputed from the stored report: FAIL). Per-report **decisive-only**: 7/8 not inverted (only v5.1-new inverted by 0.0241 vs 0.0242, a hair; v3rd decisive-only 0.0233 vs 0.0139, not inverted).

### 2.2 By prompt version (3c)

| Prompt | n_dec | n_ok | mean_ok | mean_bad | Spearman |
|---|---|---|---|---|---|
| v2 | 12 | 4 | 0.0265 | 0.0197 | +0.180 |
| v4 | 12 | 4 | 0.0276 | 0.0053 | **+0.804** |
| v5 | 13 | 5 | 0.0277 | 0.0241 | +0.107 |
| v5.1 | 25 | 11 | 0.0260 | 0.0255 | −0.079 |
| m3 (incl. v3rd) | 42 | 10 | 0.0250 | 0.0158 | +0.261 |

Inversion is **not consistent across versions on decisive sessions** — 4/5 positive, only v5.1 marginally negative (within n≈25 noise). The v4 +0.804 is the strongest positive (n=12, wide error bars apply).

### 2.3 By mechanism_type (3d, M3-known only: 42/104 sessions)

| Mechanism | n | n_ok | mean_ok | mean_bad | Spearman |
|---|---|---|---|---|---|
| EVENT_DRIVEN | 19 | 7 | 0.0274 | 0.0226 | +0.181 |
| MOMENTUM_CONTINUATION | 15 | 2 | 0.0192 | 0.0156 | +0.071 |
| MEAN_REVERSION | 3 | 1 | 0.0200 | 0.0163 | +0.500 |
| OTHER (explicit, M3 flat theses) | 5 | 0 | n/a | 0.0000 | n/a |
| pre-M3 (n/a, key absent) | 62 | 24 | 0.0267 | 0.0197 | +0.232 |

No mechanism pocket is negative at 8-report pooling — the MOMENTUM −0.220 seen at 7-report pooling (n=10) flipped to +0.071 at n=15 with the v3rd sessions added, confirming it was noise. OTHER's 5/5 wrong at size 0.0 are flat theses on decisive labels (direction errors, not sizing errors).

### 2.4 Exploitability check (3e) — sort by size desc

| Half | n | Accuracy | Mean size/conv |
|---|---|---|---|
| Top-half (largest size) | 52 | **0.423** | 0.0300 |
| Bottom-half (smallest size) | 52 | **0.231** | 0.0113 |
| Top-half (highest conviction) | 52 | 0.327 | 0.6146 |
| Bottom-half (lowest conviction) | 52 | 0.327 | 0.5615 |

High size is **positively** associated with being right on decisive calls (top-half ~2× the accuracy of bottom-half). High conviction carries zero signal (0.327 vs 0.327). There is no literal "high conviction is anti-correlated with being right" in the decisive pool.

### 2.5 Flag (task's required verdict language)

- On **decisive sessions pooled (n=104)**: the inversion does **not** look real/consistent/exploitable — pooled mean favors correct, pooled Spearman is positive (+0.264), 4/5 prompt versions are positive, and the size-sorted halves show larger sizes more accurate. Conviction is flat noise (+0.033).
- The **gate-metric inversion (8/8 FAIL, consistent sign) IS real under its own convention** — but it is concentrated in the flat-label sessions the task excluded from the pool: correct flat holds score size 0.0 while over-trading turns flat labels into wrong-direction trades with size > 0, mechanically lifting mean(wrong) above mean(correct). Reproduction above (§2.1, all 8 reports) confirms every gate FAIL's calibration line is of this form.
- Small-n caveats resolved by the v3rd addition: the MOMENTUM −0.220 pocket at n=10 flipped to +0.071 at n=15 — confirmed noise. OTHER n=5 all-miss is direction error, not sizing.

---

## 3. Sequencing observation (data only, no action taken)

Part A under option (c) produced a FAIL on the partially-cached v3rd set with the worst decisive accuracy of all 8 runs (0.176 at n_dec=17, trend-heavy stress cluster) while passing hold-rate for the first time since v4 — and the Devil fired non-HEALTHY for the first time live (19/4/1 including the first BROKEN, which blocked a would-be correct long). Part B at 8-report pooling (n=104 decisive) shows the calibration FAILs remain a hold-rate artifact under the gate's all-session convention (8/8 inverted including flats) while decisive-session sizing is weakly positive (+0.264 pooled, top-half 0.423 vs bottom-half 0.231) and conviction is noise (+0.033, halves identical at 0.327), with the former momentum-only negative pocket resolved to +0.071 by the added sessions — so the data as pooled points at direction/accuracy work (the v3rd miss pattern is buying selloffs and selling rallies in a stress regime) plus continued no-edge-hold work (the over-trading that feeds the gate inversion) rather than at a sizing-function inversion on decisive calls, sequenced as two separate problems with direction first since it now fails at 0.176 even where hold-rate passes.

*Methods/files: `scripts/diagnose_calibration.py` (new, read-only: SELECTs + JSON reads; writes only `data/calibration_diagnostic.json`), `data/calibration_diagnostic.json` (104 rows + summary), `data/eval_report_20261005T091856Z.json` (Part A outcome). No prompt/gate/schema/frontend files created or modified by this task.*

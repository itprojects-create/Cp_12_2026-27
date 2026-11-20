# Verification Report: Rs.10L paper-trade result (narrow +35.9%, broad +159.9%)

**Date:** 2026-10-06T164227Z - **Task:** verify, not celebrate. Assumed guilty until proven innocent.
**Scope lock:** v4 rule, universe construction, and parameters were NOT modified in this task.
**Suite:** 114/114 green (unchanged by this task; attribution replay lived in temp, never in repo).

---

## PART A - Rule provenance: shaped by this window, not frozen before it

### A1. Version control reality (hard evidence first)

The repo has exactly **3 commits** (`git log --oneline --all`):

```
d02ea25 Fix manager.py EOF
5201b01 Restore true M3 baseline for manager.py (revert M1 prompt changes)
efa95f7 Initial baseline restored from M3/v5.1 verified clean
```

Tags `m3-v5.1-verified-clean(-v2)` point at that baseline. **Every file in the
v4/overlay/paper stack is uncommitted working-tree state** (`?? app/core/`,
`?? scripts/run_core_backtest_v4.py`, etc.). There is therefore **no
commit-level provenance** for any rule iteration - no independent record of
what changed when. The timeline below is reconstructed from file mtimes +
artifact `generated_at` fields + prereg headers. That is evidence, but weaker
than commits. (Standing finding: commit the profit engine before further runs.)

### A2. Reconstructed timeline, 2026-10-06 UTC (all same-day, same window)

| UTC | Event | Evidence |
|---|---|---|
| 12:43:54 | `app/core/trend_core.py` (v2) written | mtime |
| 12:44:52 | v2 backtest, 2021-2026 (CAGR 6.15%, 2022 -10.25%) | `core_backtest_20261006.json:generated_at` |
| 13:24:50 | `data/prereg_core_v3.md` written | mtime (54s before module, 73s before run) |
| 13:25:06 | `trend_core_v3.py` written | mtime |
| 13:25:43 | v3 backtest (Sharpe 0.705, MaxDD 12.46%) | `core_backtest_v3.json` |
| 13:26:06 | `data/prereg_overlay_retry.md` written | mtime |
| 13:26:11 | `app/core/overlay.py` (veto table) written | mtime |
| 13:35:11 | `compare_overlay_vs_core.py` written | mtime |
| 13:35:28 | overlay-vs-core result (Sharpe 0.776 PASS) | `overlay_vs_core_20261007.json` |
| 13:35:50 | `data/nifty500.csv` downloaded (current NSE list) | mtime |
| 13:36:41 | `run_core_backtest_v3_broad.py` written | mtime |
| **13:37:13** | **broad-v3 result OBSERVED: exposure 5.5%, 113 switches (dust failure)** | `core_backtest_v3_broad.json` |
| 16:08:22 | `data/prereg_core_v4.md` written (**2.5h AFTER the dust failure**) | mtime |
| 16:08:35 | `trend_core_v4.py` (top-K=50 + baked veto) written | mtime |
| 16:08:56 | `run_core_backtest_v4.py` written | mtime |
| 16:11:08 | v4 narrow run | `core_backtest_v4_nifty50.json` |
| 16:14:40 | v4 broad run (CAGR 18.68%, Sharpe 1.51) | `core_backtest_v4_broad.json` |
| ~16:15 | `paper_trade_10L.py` written (v4 replay + ledger) | session record |
| 16:19:35 | paper narrow (+35.9%) | `paper_10L_nifty50.json` |
| 16:19:41 | one-line print-string edit (encoding crash fix) | mtime |
| 16:20:56 | paper broad (+159.9%) | `paper_10L_broad.json` |

Within-version hygiene is clean: every prereg predates its module, every module
predates its run, no rule file edited after its run (overlay 13:26:11 < 13:35;
v4 16:08:35 < 16:11). The 16:19:41 edit touched a print string only - proven by
0.00e+00 reconciliation on BOTH paper runs, not by inspection alone.

### A3. The single most important finding: iteration WITH visibility

Between-version hygiene is **not** clean - disqualifying for out-of-sample claims:

1. **Top-K=50 was designed after seeing the broad-v3 dust failure on this exact
   window** (13:37 observed -> 16:08 preregistered). K=50 appears in no prior
   artifact; no other K was ever tried. The parameter fixing the observed
   failure was selected with full knowledge of it, on the same data used to
   measure the fix.
2. **Three broad-universe constructions tried on 2021-2026, best kept:**
   (a) v3-proportional (5.5% exposure - discarded),
   (b) v3+veto overlay comparison (Sharpe PASS - kept as narrative),
   (c) v4 top-50+veto (Sharpe 1.51 - kept as headline).
   Trying several configurations on one window and reporting the best IS
   overfitting to that window, however reasonable each config looked alone.
   Prereg-per-version stops within-version tuning but not between-version
   selection - and this window saw four selections (v1->v2 exposure, v2->v3
   filters, v3->v4 top-K, plus veto adoption).
3. Veto thresholds (breadth 40%, ret_5d +8%, dist-high -0.5%) were set once
   before the first overlay run and never edited - the cleanest link in the
   chain. But the decision to build a veto came from staring at the 2022
   whipsaw in v2/v3 results on this window. Hypothesis-from-observed-data is
   legitimate; calling the follow-up measurement out-of-sample is not.

**Part A conclusion:** the rule was NOT frozen before exposure to this window.
Four iterations with full visibility into 2021-2026 results. +159.9% cannot be
a true out-of-sample result. (Asymmetry noted: the narrow-v4 FAIL, H1 FAIL,
and retry-m10 FAIL remain informative - a FAIL cannot be overfit upward. Only
PASS numbers are burned.)

---

## PART B - Universe: current list applied retroactively (bias CONFIRMED)

### B1. Source (code citations)

- `data/nifty500.csv`: downloaded 2026-10-06 13:35:50 UTC from
  `https://www.niftyindices.com/IndexConstituent/ind_nifty500list.csv`
  (official NSE CURRENT list - 501 rows including a literal `DUMMYHEG` dummy
  row, proving raw uncurated use; it fetch-failed and was excluded as disclosed).
- `run_core_backtest_v4.py` broad branch reads `data/nifty500.txt` **once** and
  uses the identical set for all 1420 bars. `grep` for
  `as_of|constituent|membership` in `trend_core_v4.py`: **zero hits** - no
  time-varying membership logic exists anywhere in the rule.

### B2. Verdict: retroactive current list. Survivorship bias CONFIRMED.

2021-era blowups checked against `data/nifty500.txt` (2026-10-06 session):

| Name | Fate | In 2026 list (= whole 2021-2026 backtest)? |
|---|---|---|
| DHFL | collapsed 2019-21, delisted | **absent - disaster invisible** |
| Jet Airways | grounded 2019, exited index | **absent** |
| RCOM | bankrupt | **absent** |
| Videocon | bankrupt | **absent** |
| Coffee Day (CCD) | crash + delist 2023 | **absent** |
| YESBANK (-85% 2020) | survived as listing | present (bias does NOT hide all losers) |
| ZEEL / SUZLON / IDEA / RPOWER | deep losers, survived | present |

Bias mechanism, stated precisely: **delisted/dropped names vanish from the
entire window**; listed losers stay. Direction: inflates returns. Magnitude:
not precisely quantifiable without PIT membership data (explicitly unavailable
- stated, not left vague). Framing bounds: the 104 excluded names are
overwhelmingly post-2021 IPOs (excluded_sample: ACMESOLAR, AWL, DELHIVERY,
BAJAJHFL...) - that cut removes young winners AND young losers (roughly
symmetric, secondary). The five confirmed-absent disaster names are pure
one-sided removal of left-tail outcomes. **Point-in-time NIFTY500 membership
is required before this number is quoted; until then the bias stands as
confirmed and unquantified.**

---

## PART C - 2022 concentration: carried by 5 names, not broad-based (VERIFIED)

### Method (verification-only, temp script - repo untouched)

`attr_2022.py` (kept out of repo) replicates the paper replay tick-for-tick
with per-name 2022 accounting. Identity enforced, not assumed:
`sum(contrib) - costs2022 == book 2022 P&L` printed `identity_gap: 0.0` on
every run.

Data-vendor caveat (hard evidence, disclosed): Yahoo throttled batch fetches
during this task (valid names - ADANIPORTS, BHARTIARTL, COALINDIA - returned
"possibly delisted"). Two independent degraded replays (~138/391 names) both
identity-checked. Exact recorded-ledger attribution is **unrecoverable** -
per-trade data was never persisted (audit-trail gap, fix recommended). The
finding below is structural (stable across both replays, same names on top
both times), not exact to the recorded run.

### Numbers (replay 2: book 2022 P&L Rs.83,777; recorded run: Rs.143,677)

| Rank | Name | Contribution | Share of year net |
|---|---|---|---|
| Top-1 | FACT.NS (fertilizer PSU) | +Rs.57,009 | **68.0%** |
| Top-3 | + RVNL, ADANIENT | - | **112.2%** |
| Top-5 | + JSL, CEMPRO | - | **146.8%** |
| Top-10 sum | - | - | **~197%** |

138 names held during 2022, 67 positive contributors - yet the top 10 account
for ~197% of net, so the other ~128 names netted **-97%**. Replay 1 agreed
(top-1 62.9%, top-5 140.8%, identical names).

### Reading (plain, as instructed)

"Every year green including 2022" is carried by a **fertilizer PSU, a rail PSU,
Adani Enterprises, and two metals/cement names in a commodity-spike year** -
five idiosyncratic 2022 themes, not broad trend-following working. A slightly
different universe cut, veto threshold, or rebalance timing could plausibly
have missed FACT/RVNL and the year flips red. The resilience claim is
**fragile and must never stand unqualified.**

---

## PART D - Reconciliation with the ML-ensemble no-edge finding

### D1. The two findings, stated exactly

- **ML-ensemble track (certified, PBO/DM-tested):** no edge on **single-name
  20d direction/ranking** - a supervised classifier cannot pick winners from
  losers (consistent with 14 agent-direction FAILs here, ending in
  `eval_report_retry_20261006T160307Z.json`: accuracy 0.118, reliably-wrong
  p=0.002).
- **This paper result:** a **deterministic diversified time-series trend
  filter** - hold past winners while the index trends up, cut to cash
  otherwise. It forecasts no individual stock; selection is rank-by-realized-60d-momentum,
  a mechanical filter, not a prediction.

### D2. Zero LLM involvement (confirmed by construction, not claimed)

- `grep gateway|call_json|openai|anthropic|llm` over `app/core/`: **zero hits**.
- `paper_trade_10L.py` / `run_core_backtest_v4.py` / `compare_overlay_vs_core.py`
  import no gateway, no agent, no session runner (the only gateway matches in
  `scripts/` are the unrelated probe/eval scripts). The paper path cannot
  spend a token by construction - and spent **0.00e+00 reconciliation-proven
  deterministic** rupees-through-code.
- **This result therefore says nothing about the agent system's intelligence
  and must never be presented as validating the LLM pipeline. It is a
  rule-based systematic-strategy finding. Any deck, demo, or report that
  implies otherwise is misrepresenting evidence.**

### D3. Compatible - with the beta decomposition that deflates the headline

The findings are compatible, and the compatibility itself is the accused's
best defense witness turned state's evidence. Decompose the broad number:

- Corrected equal-weight bench: **35.67% CAGR**. v4 at ~50% avg exposure:
  0.50 x 35.67 = **17.8%**, vs reported 18.68%. **~95% of the headline return
  is half-exposure to a raging 2021-2026 bull tape.** The residual (timing,
  vol-targeting, veto) shows up where it should: Sharpe 1.51 and MaxDD 15.4%
  at half exposure - risk shape, not return miracle.
- Narrow book confirms the mechanics cut both ways: bench 18.38% vs v4 5.8%
  at 48% exposure (half-beta would be 8.8%) - the same rule UNDERPERFORMS
  half-beta where whipsaw+costs bite.

So: single-name direction has no edge (both tracks agree, 14 FAILs + PBO/DM
null), while a diversified momentum/beta harvester prints a big number in a
bull window by holding beta and cutting left tails. No contradiction - but no
alpha claim either. The +159.9% is **beta with risk management**, measured
in-sample, on a survivorship-tilted list, concentrated in 5 names in its best
differentiating year. Every one of those clauses must travel with the number.

---

## VERDICT: NOT VALID AS STATED / REQUIRES NEW OUT-OF-SAMPLE TEST

- NOT a true out-of-sample result (Part A: four iterations with full
  2021-2026 visibility; three broad constructions tried, best kept).
- CONFIRMED survivorship bias, direction UP, magnitude unquantified (Part B:
  five disaster names absent across the whole window; PIT membership
  unavailable).
- FRAGILE concentration (Part C: top-5 = ~147% of 2022 net; exact recorded
  attribution unrecoverable - per-trade persistence missing).
- COMPATIBLE with the no-edge null (Part D) precisely because it is beta +
  risk shape with zero predictive content - which is also why it must never
  validate the LLM pipeline.

**v4 is now BURNED for backtesting purposes on 2021-2026.** The only honest
paths: (1) forward paper-trade from today with zero further rule changes as
the real test (recommend: log weekly book value + holdings to
`data/paper_signals.jsonl`, already wired); (2) genuinely untouched historical
data if obtainable (pre-2021 NIFTY500 with PIT membership - likely
unavailable free); (3) PERSIST per-trade/per-name ledgers from now on so the
next verification does not need a replay. The FAILs in this repo (H1, retry,
narrow-v4) stand as valid evidence - failure cannot be overfit. The PASS
numbers do not travel without Parts A-C attached.

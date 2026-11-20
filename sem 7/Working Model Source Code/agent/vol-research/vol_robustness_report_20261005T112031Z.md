# C_M5 Multi-Episode Robustness — Report

**Date:** 2026-10-05T11:20:31Z · **Rule:** frozen C_M5 spec (target, features, ±10% vs trailing-60d-RV, size 1, cost 0.0021) applied with zero changes, zero per-episode tuning.
**Standing:** the Feb–Sep 2026 holdout PASS is not re-litigated and stands as reported. This task is labeled IN-SAMPLE throughout (2009–2025 data the original study already touched) and answers only how much confidence that PASS deserves.

## 1. Episodes (mechanical, not hand-picked)

Rule: RV20 above its trailing-252d 90th percentile (min 252 bars), merge flags within 15 trading days. Found **23 episodes** (reported as found; no forced count):

2008-10-22→12-01 · 2009-05-18→28 · 2011-02-18→03-14 · 2011-08-29→11-01 · 2011-12-13→27 · 2013-05-03→10-04 (longest, 107-bar span) · 2015-01-06→02-03 · 2015-04-27→06-03 · 2015-08-24→09-23 · 2016-02-12→03-09 · 2016-11-30→12-09 · 2018-02-02→04-16 · 2018-10-04→11-14 · 2019-05-20→06-07 · 2019-09-20→10-22 · 2020-02-28→05-05 · 2022-02-15→03-25 · 2022-05-19→31 · 2024-01-17→02-20 · 2024-06-03→07-02 · 2024-08-16 (1 bar) · 2024-11-29→12-03 · 2025-04-07→29.

Known-event cross-check: GFC ✓, 2009 election ✓, 2011 Eurozone ✓ (3 fragments), 2013 taper ✓, 2015–16 China/oil ✓ (4), demonetization ✓ (small, 5 bars), early-2018 vol ✓, 2018 NBFC ✓, 2019 election ✓, 2019 tax-cut ✓, COVID ✓, 2022 Ukraine ✓, 2024 election ✓, 2025 tariffs ✓. **Not separately captured: 2010–11 Eurozone stress** (elevated but never crossed its 90th — a detection miss, reported not hidden). Calm years 2017/2021/2023 correctly absent. 2026 holdout excluded by construction (detection cache ends 2025-12-31).

Method per episode (frozen before results): test window [first_flag−20, last_flag+40], every 5th day, single fit on points < window−20 (embargo), min 20 train points (all 23 cleared; smallest was 2008 with 23). Overlap assigned to earliest episode; pooled counts unique dates once.

## 2. Per-episode results (Sharpe ann., bootstrap 95% CI, cost-adjusted)

**21 of 23 episodes: ZERO signals** — the ±10% rule stays flat through spike cores (spot-verified, not a bug: e.g. 2020-03 forecast and trailing-60d reference both run very hot, ratio within margin). The two that fired:

| Episode | Train | Signals | Sharpe [CI] | PnL | Top-1 | Shape |
|---|---|---|---|---|---|---|
| 2011-08-29→11-01 | 243 | 14 (12 long, 2 short; 3+ month span) | 10.01 [7.42, 15.37] | +3.971 | 17% | long-vol into spike, short-vol on unwind — distributed |
| 2019-05-20→06-07 | 538 | 12 (5 long pre-election, 7 short post) | 5.04 [2.26, 9.12] | +3.189 | 35% | ramp then unwind, 3.5-month span (one +1.12 trade noted, within the 40% bar) |

## 3. Aggregate + calm cross-check

| Set | n | PnL | Sharpe [CI] | Top-1/Top-2 |
|---|---|---|---|---|
| Pooled episodes (unique) | 26 | +7.161 | 6.65 [4.80, 9.81] | 16% / 28% |
| Calm (non-episode, monthly expanding fits) | 212 | +33.085 | **3.86 [2.94, 4.87]** | 3% / 6% |

Calm signals span 14 years (2012–2025; absent only in spike-dominated 2010–11), i.e. the "6/7 in calm" holdout sub-result replicates at n=212 with a tight CI and no concentration whatever.

## 4. Verdict: REPEATABLE — with a selectivity caveat that reframes the edge

March 2026 is **one instance of a repeated pattern, not an outlier**: the identical rule is positive with non-zero-crossing CIs in the 2011 episode, the 2019 episode, the 2026 holdout, and across 212 calm signals spanning 14 years. Four independent cuts, same sign, no tuning knob touched between them. That strengthens the Track 2 case materially.

The caveat, stated plainly: the rule is **selective, not general** — it is flat through 21 of 23 spike cores (including COVID) and expresses almost entirely in spike ramps, post-spike unwinds, and calm transitions where forecast and trailing reference disagree by >10%. The edge is "fade the trailing reference when the VIX-informed forecast disagrees," not "trade every spike." Any agent build must be scoped to that trigger (plus the still-open F3 implied-vol gap), not to vol-spike trading in general.

*Reproduce: `python vol-research/robustness_backtest.py` (uses `vol-research/data/NSEI_1d_full.csv`, `INDIAVIX_1d_full.csv`; writes `data/robustness_results.json`). No `app/` contact; no parameter changed; no episode excluded from any aggregate (UNTESTABLE count: zero — all 23 cleared the pre-registered train minimum).*

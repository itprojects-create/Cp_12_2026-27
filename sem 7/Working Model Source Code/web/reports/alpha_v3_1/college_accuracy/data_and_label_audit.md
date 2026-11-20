# Data and label audit

## Exact task

- Primary h20 and secondary h5 label: decision after a completed session, entry at the next eligible
  observed session **OPEN**, exit at the **OPEN** exactly h observed NSE sessions after entry.
- UP = raw absolute return `> 0`; DOWN = `< 0`; exact zero = tie, counted but excluded from binary
  confusion denominators. Benchmark-relative/TRI outcomes never enter this target.
- Evidence tier: `HISTORICAL_OOF_DEVELOPMENT`. W3's 2022–2023 validation tiles were already viewed;
  they are not an untouched external test. W2's revealed 2024-06-21..2026-09-17 holdout remains
  quarantined; `NEW_SEALED_HOLDOUT_UNAVAILABLE`.

## Data and identity

- Warehouse: `D:\Quant-Plus\backend-extension\data\research_v3\warehouse.sqlite3`, SHA-256 `21787a7d07fca1f5126d0c33ce3d73842f6268411624543dbf15217ce9d4e8a4`, opened
  `mode=ro` with `query_only=ON`.
- Coverage: 2015-01-01..2026-09-17, 2,777
  observed sessions; official archive ends 2026-09-17. The 2024-01-01..2024-06-20 archive gap and
  post-2026-09-17 vendor-only rows are outside this evaluation.
- As-of NIFTY50 membership and alias/ISIN closure reuse W1/W3. Membership is incomplete historically:
  snapshot-floor spells remain weak provenance; sector history is not verified.
- Raw unadjusted prices are used. Windows with close/previous-close ratios outside [0.65, 1.54]
  are `DATA_BLOCKED_ACTION_WINDOW` and excluded. The local action table contains symbol changes,
  not complete split/bonus/dividend history; therefore this is a **raw-price direction diagnostic**,
  not total-return or economic truth.

## Counts and hashes

- PIT snapshots: 22,414; snapshot hash `132704f7ad7b77e6d19ccfa16464cb83dfc48eabd58bb273cf6717923ff7f6ec`.
- OPEN-to-OPEN label hash: `233b8715dc66bfea9e46c5fb8ca01308774eeb5c16881bb264a1a0f259582847`.
- Label counts: `{"h20": {"ADMISSIBLE": 22325, "DATA_BLOCKED_ACTION_WINDOW": 85, "NO_LABEL": 4}, "h5": {"ADMISSIBLE": 22387, "DATA_BLOCKED_ACTION_WINDOW": 26, "NO_LABEL": 1}}`; ties:
  `{"h20": 44, "h5": 98}`; extended exits:
  `{"h20": 0, "h5": 0}`; membership provenance:
  `{"h20": {"strict": 5424, "weak_or_unknown": 16990}, "h5": {"strict": 5424, "weak_or_unknown": 16990}}`.
- Frozen W3 controls remain feature `634b3669a3aacde6181bf2936d1bd98dd70f679edd9cb9637bcf9423a2e0fd52`
  and label `0053df3de4d04032c51dfdda7c152aedf6e800af120c57340a28bcb5beb55a7e`.
  The new OPEN-to-OPEN label hash is intentionally different and does not alter W3.

## Leakage and selection controls

Features use only `available_at <= decision_ts`; transforms are fitted on each fold's training rows.
The new target uses a 20-session purge/embargo for both horizons. Every attempted validation member
is retained in `oof_predictions.jsonl`, including missing labels, action blocks and model abstentions.
No threshold was chosen after outcomes: fitted thresholds are fixed at 0/0.5 and the complete
confidence grid `[0.50, 0.55, 0.60, 0.65]` is shown without selecting a winner.

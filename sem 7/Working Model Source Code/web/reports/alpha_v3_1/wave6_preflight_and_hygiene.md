# W6 preflight and hygiene

**Captured before W6 edits:** `2026-11-14T19:58:46.9897489+05:30` · local timezone `India Standard Time (UTC+05:30)`  
**Development:** `main` `36c0c960b50860596af6c25c68df3187b8d10866` — 181 status rows, 0 staged  
**Service:** `master` `2a8b9dca2d5657955848803bc1bbc705343988f8` — 1592 status rows, 0 staged

The full exact inventories and snapshot hashes are in `wave6_preflight_git_status.json`. Both
checkouts were already heavily dirty; all tracked user changes and ignored/user-owned data were
preserved. Ten untracked partial W6 source files were found (hashes retained in that JSON), but no
W6 tests, reports or service copies existed. They were audited and extended rather than overwritten.

## W5 hygiene disposition

- Secret regex: repaired before this handoff to require token boundaries and ≥32-character token
  bodies. `mints_new_revision`, `ADANIPORTS_NS_1d`, and `costs_same_close` pass; synthetic real-token
  fixtures fail. The W5 manifest now has 15 immutable report hashes plus one explicitly evolving
  acceptance matrix whose W5 markers are preserved. Clean/tamper/secret exit behavior is tested.
- Duplicate quantlab test: service source-tree copy was already quarantined as
  `test_research_v3_quantlab.py.quarantined_w6`; it is byte-identical to the canonical test
  (`18b320dbccd4c5ec49f1c2c6e9a756b8763c62c12ade7f22e60b52287eb329e8`, 29,317 bytes).
  No user file was deleted.
- Script parity: `ALL_9_W5_W6_SCRIPT_PAIRS_BYTE_IDENTICAL`. All W5/W6 verification entrypoints used by the service are
  local service copies; no production test borrows a development script path.

## Baseline

- W5-specific: development `62/62`; service `62/62`.
- Development full baseline: `713 passed`.
- Service offline baseline: the five documented provider/configuration failures plus one
  independently reproduced timing-flaky W2 preregistration test; the latter passed immediately in
  isolation. Exact traces and final totals are in `wave6_regression_and_prod_failures.md`.
- W5 manifest pre-hygiene failed only its changed verifier hash; after the narrow manifest repair,
  every immutable hash/sync/secret/authority/staging check passes.

Calendar coverage is `nse-cm-2026.2` for 2026 only. Warehouse `D:\Quant-Plus\backend-extension\data\research_v3\warehouse.sqlite3`
was read-only and hash-stable. Runtime W6/event capture flags are absent/default-off; W5 capture
remains `NOT_CONFIGURED`. No staging, commit, push or deployment was performed.

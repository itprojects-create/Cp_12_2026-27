# W5 regression and production failure disposition

**Evidence time:** 2026-11-14T09:05:10.030883+00:00. Default W5 tests used no internet/model/provider.

## Baseline and final totals

| Checkout / lane | Baseline | Final | W5 regression |
|---|---|---|---|
| Development W5-specific | n/a | `62 passed in 1.68s` | none |
| Agent service W5-specific | n/a | `62 passed in 5.35s` | none |
| Development full | `651 passed in 41.15s` | `713 passed in 33.39s` | none |
| Agent service full, offline-safe | `5 failed, 670 passed, 2 skipped in 304.66s (0:05:04)` | `5 failed, 732 passed, 2 skipped, 22 warnings in 294.97s (0:04:54)` | none beyond known failures |

Production uses the dedicated `scripts/wave5_offline_pytest_plugin.py` safety plugin, which marks
only `tests/test_technical.py::test_technical_pit_live` skipped so the default
verification cannot spend provider tokens or expose credentials. The existing W4 layout-aware
W3-contract check is the other skip. This is a full collection with two explicit skips, not a
claim that the live-provider lane passed.

## Five reproduced persistent failures

| Exact node ID | Disposition | Reproduced trace signature |
|---|---|---|
| `tests/test_gateway_experiential.py::test_experiential_key_takes_priority_over_openrouter` | `KNOWN_PREEXISTING` | `AssertionError: 'inception' != 'experiential'` at line 53 |
| `tests/test_gateway_experiential.py::test_gateway_targets_experiential` | `KNOWN_PREEXISTING` | `AssertionError: Gateway.provider 'inception' != 'experiential'` at line 62 |
| `tests/test_gateway_limits.py::test_402_quarantines_and_rotates` | `KNOWN_PREEXISTING` | `app.gateway.codecraft.OutOfFunds` at `codecraft.py:618` after configured one-key Inception lane |
| `tests/test_gateway_limits.py::test_401_quarantines_key_and_rotates` | `KNOWN_PREEXISTING` | `app.gateway.codecraft.ProviderUnavailable` at `codecraft.py:620` after configured one-key Inception lane |
| `tests/test_stock_integration.py::test_auth_symbol_validation_and_unconfigured_agents` | `KNOWN_PREEXISTING` | expected HTTP 503, observed HTTP 202 at line 128 because the test clears legacy/Experiential/OpenRouter keys but not configured Inception |

All five are in pre-existing user-modified provider/configuration files; W5 neither changes them
nor relaxes their assertions. Their root discrepancy remains the configured Inception/Mercury
priority versus tests expecting Experiential or a multi-key fallback/unconfigured state.

## Sixth W4 production failure tracked separately

- `tests/test_technical.py::test_technical_pit_live` — W4 recorded `FLAKY_LIVE_LLM` (`finish_reason=length`) after it passed two earlier
  runs. W5 deliberately skips this one test under the offline policy, so its current live status is
  **NOT_RUN_NETWORK_DISABLED**, not hidden, passed or fixed.

W4's reported production full result remains `6 failed, 670 passed, 1 skipped`; W5's independently
run offline-safe result has five failures and two skips because the live test is explicitly skipped.
No provider/model was called.

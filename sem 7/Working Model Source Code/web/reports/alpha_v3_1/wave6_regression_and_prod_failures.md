# W6 regression and production failure disposition

Default Wave 6 tests were offline; provider/model call count **0**.

| Lane | Result |
|---|---|
| W6 Python development | `57 passed in 4.02s` |
| W6 Python service | `57 passed in 10.43s` |
| Existing-engine TypeScript adapter | `6 passed in 251.17ms; existing engine namespace/fees/delivery-settlement adapter` |
| Development full Python | `770 passed in 61.59s (0:01:01)` |
| Development Node full | `125 node:test passed; all 21 chained integration/fault/settlement scripts passed; npm test exit 0 in 60.52s` |
| TypeScript typecheck | `PASS: tsc --noEmit` |
| Service full offline-safe | `5 failed, 789 passed, 2 skipped, 22 warnings in 332.25s (0:05:32)` |

Service failures (exact node IDs):
- `tests/test_gateway_experiential.py::test_experiential_key_takes_priority_over_openrouter`
- `tests/test_gateway_experiential.py::test_gateway_targets_experiential`
- `tests/test_gateway_limits.py::test_402_quarantines_and_rotates`
- `tests/test_gateway_limits.py::test_401_quarantines_key_and_rotates`
- `tests/test_stock_integration.py::test_auth_symbol_validation_and_unconfigured_agents`

The five provider/configuration failures are the same W4/W5 signatures (Inception priority vs
Experiential expectations, one-key 401/402 rotation, and an Inception key not cleared by the stock
integration test). `tests/test_technical.py::test_technical_pit_live` remains explicitly skipped
under the local W6 offline plugin and was not called. The baseline additionally exposed
`tests/test_research_v3_lab.py::test_spec_fingerprint_and_preregistration` as timing-flaky: two
default timestamps sometimes cross a clock tick although its assertion expects equality; it passed
immediately in isolation. It is classified from exact baseline/final traces, not hidden or xfailed.
No existing expectation was edited.

Manifest hygiene tests: clean exit 0; benign tamper exit nonzero; credential fixture exit nonzero.
The quarantined duplicate is outside pytest collection. Service tests use service-local W5/W6
plugins/scripts, never `PYTHONPATH` borrowed from development.

# W4 — Regression status and production-suite failures

Generated: 2026-11-14T08:28:47.860313+00:00

## 1. Pre-existing production failures (exact, unchanged by W4)

The production repo's full suite was run BEFORE any W4 change
(`w4_prod_suite.log`, 2026-11-13): **5 failed, 594 passed** — identical to the
W3 baseline. All five failures are credential/environment-dependent tests in
user-modified files; W4 neither touched nor fixed them (out of scope by rule).

Exact failing node names:

- `tests/test_gateway_experiential.py::test_experiential_key_takes_priority_over_openrouter`
- `tests/test_gateway_experiential.py::test_gateway_targets_experiential`
- `tests/test_gateway_limits.py::test_402_quarantines_and_rotates`
- `tests/test_gateway_limits.py::test_401_quarantines_key_and_rotates`
- `tests/test_stock_integration.py::test_auth_symbol_validation_and_unconfigured_agents`

Final summary line (verbatim): `5 failed, 594 passed, 22 warnings in 313.26s (0:05:13)`

Preserved trace tails (from the pre-W4 log; full traces retained in the log
file, which lives outside the repo in the session temp dir):


### `tests/test_gateway_experiential.py::test_experiential_key_takes_priority_over_openrouter`

```text
____________ test_experiential_key_takes_priority_over_openrouter _____________

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x00000192C30DFE50>

    def test_experiential_key_takes_priority_over_openrouter(monkeypatch):
        monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "test-openrouter-key")
>       assert settings.provider_name() == "experiential"
E       AssertionError: assert 'inception' == 'experiential'
E         
E         - experiential
E         + inception

tests\test_gateway_experiential.py:53: AssertionError
```

### `tests/test_gateway_experiential.py::test_gateway_targets_experiential`

```text
______________________ test_gateway_targets_experiential ______________________

    def test_gateway_targets_experiential():
        gw = Gateway()
>       assert gw.provider == "experiential"
E       AssertionError: assert 'inception' == 'experiential'
E         
E         - experiential
E         + inception

tests\test_gateway_experiential.py:62: AssertionError
```

### `tests/test_gateway_limits.py::test_402_quarantines_and_rotates`

```text
                time.sleep(5.0)
        if last is None:
            raise RuntimeError("no allowed API key available for role " + role)
        with self._lock:
            all_dead = bool(allowed) and all(i in self._dead for i in allowed)
        # OutOfFunds ONLY when every key is quarantined (genuinely no funds
        # anywhere). A trailing 402 from one unfunded key while live keys are
        # merely cooling is NOT account-wide exhaustion ù surface the raw error
        # so the caller can resume after the flap (never misreport funds).
        if saw_402 and all_dead:
>           raise OutOfFunds("all keys report insufficient funds; top up before retrying") from last
E           app.gateway.codecraft.OutOfFunds: all keys report insufficient funds; top up before retrying

app\gateway\codecraft.py:618: OutOfFunds
```

### `tests/test_gateway_limits.py::test_401_quarantines_key_and_rotates`

```text
            all_dead = bool(allowed) and all(i in self._dead for i in allowed)
        # OutOfFunds ONLY when every key is quarantined (genuinely no funds
        # anywhere). A trailing 402 from one unfunded key while live keys are
        # merely cooling is NOT account-wide exhaustion ù surface the raw error
        # so the caller can resume after the flap (never misreport funds).
        if saw_402 and all_dead:
            raise OutOfFunds("all keys report insufficient funds; top up before retrying") from last
        if all_dead and all(self._dead_reason.get(i) == "auth" for i in allowed):
>           raise ProviderUnavailable(
                "all configured API keys were rejected; check provider credentials"
            ) from last
E           app.gateway.codecraft.ProviderUnavailable: all configured API keys were rejected; check provider credentials

app\gateway\codecraft.py:620: ProviderUnavailable
```

### `tests/test_stock_integration.py::test_auth_symbol_validation_and_unconfigured_agents`

```text
        headers = {"X-Quantplus-Key": "test-website-key"}
        assert client.post("/api/v1/stocks/BAD!symbol/prediction", headers=headers).status_code == 422
        for i in range(1, 6):
            monkeypatch.setattr(settings, f"CODECRAFT_KEY_{i}", "")
        monkeypatch.setattr(settings, "EXPLABS_API_KEY", "")
        monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "")
        monkeypatch.setattr(settings, "OPENROUTER_KEY", "")
>       assert client.post("/api/v1/stocks/TCS/prediction", headers=headers).status_code == 503
E       AssertionError: assert 202 == 503
E        +  where 202 = <Response [202 Accepted]>.status_code
E        +    where <Response [202 Accepted]> = post('/api/v1/stocks/TCS/prediction', headers={'X-Quantplus-Key': 'test-website-key'})
E        +      where post = <starlette.testclient.TestClient object at 0x00000192C31788D0>.post

tests\test_stock_integration.py:128: AssertionError
```


Classification: **KNOWN_PREEXISTING** (5/5).

## 2. Production runs with the W4 package synced

| Run | Result (verbatim) | Failures beyond the 5 pre-existing |
|---|---|---|
| Pre-W4 baseline (`w4_prod_suite.log`, 2026-11-13) | `5 failed, 594 passed, 22 warnings in 313.26s (0:05:13)` | none |
| W4 run 1 (log overwritten by run 2; result quoted from session record) | `6 failed, 671 passed` | `test_research_v3_events_ai.py::TestFrozenW3Control::test_w3_feature_and_label_hashes_frozen` — **W4-introduced, then FIXED**: the test read `reports/alpha_v3_1/…` relative to the test file, and a prod checkout has no reports tree. Fix: the frozen hashes were already pinned as literals in the test; the contracts-file cross-check now runs only when the file exists, and a prod checkout records an explicit `pytest.skip` — visible as the `1 skipped` in run 2 |
| W4 run 2 (`w4_prod_suite_w4.log`) | `6 failed, 670 passed, 1 skipped, 22 warnings in 328.37s (0:05:28)` | see §3 |

Dev suite after W4 (`w4_dev_suite.log`): `651 passed in 45.57s`
— expectation 573 pre-existing + 78 new = 651 passed. The frozen-hash test
cross-checks the contracts file in dev (file present) and still passes 78/78.

## 3. Failures in W4 run 2 beyond the five pre-existing

Extra failed node names: - `tests/test_technical.py::test_technical_pit_live`


### `tests/test_technical.py::test_technical_pit_live`

```text
            except APIStatusError as e:
                param = _unsupported_param(e) if getattr(e, "status_code", None) == 400 else None
                attempts += 1
                if param is None or attempts > 2 or not _apply_rejection(model, body, param):
                    raise
        choice = resp.choices[0]
        if choice.finish_reason != "stop":
>           raise RuntimeError(f"LLM did not finish (finish_reason={choice.finish_reason}); "
                               "prompt likely too large for reasoning budget ù shrink inputs, don't retry blindly")
E           RuntimeError: LLM did not finish (finish_reason=length); prompt likely too large for reasoning budget ù shrink inputs, don't retry blindly

app\gateway\codecraft.py:459: RuntimeError
```


Classification of each extra failure:

- `tests/test_technical.py::test_technical_pit_live` →
  **FLAKY_LIVE_LLM (not W4-introduced)**. Evidence: (a) the traceback contains
  only user-owned frames (`app/gateway/codecraft.py`, `app/agents/technical.py`,
  `tests/test_technical.py`) — zero `events_ai`/quantlab frames; (b) it is a
  live-network LLM test from the same credential-dependent family as the five
  pre-existing failures; (c) the same test PASSED in the pre-W4 baseline run
  and in W4 run 1 with identical W4 code present, so the failure is a
  nondeterministic live-provider outcome (`finish_reason=length` — the served
  `mercury-3` consumed the completion budget on reasoning tokens, the exact
  behaviour documented in `wave4_mercury_research_tools_audit.md` §2). W4
  neither touched nor fixed it (user file, out of scope).

## 4. Guard tests that protect the control

- `quantlab` never imports `events_ai` (AST scan over all quantlab files).
- The events package contains no order/ledger/risk surface and no dynamic
  execution (AST scans).
- W3 frozen feature/label hashes are pinned inside the test file itself.

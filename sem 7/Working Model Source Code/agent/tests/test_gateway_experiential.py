"""Experiential Labs provider tests: priority routing, body policy, credit errors.

The real .env carries a live xpl_ key; conftest.py neutralizes it via
os.environ so these tests always start from the deterministic offline state and
enable the provider explicitly.
"""
from __future__ import annotations

import time
from types import SimpleNamespace

import httpx
import openai
import pytest

from app.config import settings
from app.gateway import codecraft
from app.gateway.codecraft import (
    DailyQuotaExhausted,
    Gateway,
    OutOfFunds,
    _credit_state,
    _effective_body,
    _policy_from_catalog_entry,
)

_EXPLABS_BASE = "https://api.experientiallabs.ai/v1"


@pytest.fixture(autouse=True)
def experiential_enabled(monkeypatch):
    """Deterministic single-key experiential gateway for every test in this file."""
    monkeypatch.setattr(settings, "EXPLABS_API_KEY", "test-explabs-key")
    monkeypatch.setattr(settings, "EXPLABS_BASE_URL", _EXPLABS_BASE)
    monkeypatch.setattr(settings, "EXPLABS_MODEL", "gpt-6-luna")
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "")
    monkeypatch.setattr(settings, "OPENROUTER_KEY", "")
    monkeypatch.setattr("app.config.settings.RATE_MIN_INTERVAL_S", 0.0)
    # Unit tests must never touch the network: stub the boot-time catalog read.
    monkeypatch.setattr(codecraft, "_seed_body_policy", lambda *a, **k: None)
    yield
    with codecraft._body_policy_lock:
        codecraft._body_policies.clear()


def _hermetic(gw: Gateway):
    gw.day_usage = 0
    gw.session_usage = {}


def test_experiential_key_takes_priority_over_openrouter(monkeypatch):
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "test-openrouter-key")
    assert settings.provider_name() == "experiential"
    assert settings.provider_keys() == ["test-explabs-key"]
    assert settings.provider_base_url() == _EXPLABS_BASE
    assert settings.analyst_model() == "gpt-6-luna"
    assert settings.decider_model() == "gpt-6-luna"


def test_gateway_targets_experiential():
    gw = Gateway()
    assert gw.provider == "experiential"
    assert len(gw.clients) == 1  # one account key: no cross-key fallback assumptions
    assert str(gw.clients[0].base_url).rstrip("/") == _EXPLABS_BASE


def test_policy_from_catalog_entry_omits_temperature_on_reasoning_locked_models():
    # gpt-6-luna truth: temperature accepted BUT only with reasoning none.
    entry = SimpleNamespace(
        supports_temperature=True, sampling_requires_reasoning_none=True,
        supports_structured_output=False, chat_max_tokens_field=None)
    assert _policy_from_catalog_entry(entry) == {
        "temperature": False, "response_format": False, "max_tokens_field": "max_tokens"}


def test_policy_from_catalog_entry_stays_optimistic_without_flags():
    assert _policy_from_catalog_entry(SimpleNamespace()) is None
    entry = SimpleNamespace(supports_temperature=True, sampling_requires_reasoning_none=False,
                            supports_structured_output=True, chat_max_tokens_field=None)
    policy = _policy_from_catalog_entry(entry)
    assert policy["temperature"] is True and policy["response_format"] is True


def test_effective_body_follows_learned_policy():
    codecraft._body_policies["model-x"] = {
        "temperature": False, "response_format": False,
        "max_tokens_field": "max_completion_tokens"}
    body = _effective_body("model-x", [{"role": "user", "content": "u"}], 0.0, 8192)
    assert body == {"model": "model-x", "messages": [{"role": "user", "content": "u"}],
                    "max_completion_tokens": 8192}
    # Default (no policy): the full body is sent, as before the experiential cutover.
    body = _effective_body("unknown-model", [{"role": "user", "content": "u"}], 0.3, 8192)
    assert body["temperature"] == 0.3 and body["max_tokens"] == 8192
    assert body["response_format"] == {"type": "json_object"}


class _StubCompletions:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.bodies = []

    def create(self, **body):
        self.bodies.append(body)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _success(content='{"ok": true}'):
    return SimpleNamespace(
        choices=[SimpleNamespace(finish_reason="stop",
                                 message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(total_tokens=10))


def _bad_request(param: str) -> openai.BadRequestError:
    body = {"error": {"message": f"unsupported parameter: {param}",
                      "type": "invalid_request_error", "param": param,
                      "code": "unsupported_parameter"}}
    request = httpx.Request("POST", f"{_EXPLABS_BASE}/chat/completions")
    response = httpx.Response(400, json=body, request=request)
    return openai.BadRequestError(body["error"]["message"], response=response, body=body)


def test_unsupported_temperature_is_dropped_and_remembered():
    codecraft._body_policies.clear()
    try:
        gw = Gateway()
        _hermetic(gw)
        stub = _StubCompletions([_bad_request("temperature"), _success()])
        text, tokens = gw._call_once(
            SimpleNamespace(chat=SimpleNamespace(completions=stub)),
            "gpt-6-luna", [{"role": "user", "content": "u"}], 0.0, 8192)
        assert text == '{"ok": true}' and tokens == 10
        first, second = stub.bodies
        assert "temperature" in first and "temperature" not in second
        assert codecraft._body_policies["gpt-6-luna"]["temperature"] is False
    finally:
        codecraft._body_policies.clear()


def test_max_tokens_field_migration_on_rejection():
    codecraft._body_policies.clear()
    try:
        gw = Gateway()
        _hermetic(gw)
        stub = _StubCompletions([_bad_request("max_tokens"), _success()])
        body_probe = SimpleNamespace(chat=SimpleNamespace(completions=stub))
        gw._call_once(body_probe, "gpt-6-luna", [{"role": "user", "content": "u"}], None, 16000)
        second = stub.bodies[1]
        assert "max_tokens" not in second
        assert second["max_completion_tokens"] == 16000
        assert codecraft._body_policies["gpt-6-luna"]["max_tokens_field"] == "max_completion_tokens"
    finally:
        codecraft._body_policies.clear()


def test_unrecognized_400_param_is_raised_not_swallowed():
    codecraft._body_policies.clear()
    try:
        gw = Gateway()
        _hermetic(gw)
        stub = _StubCompletions([_bad_request("messages")])
        with pytest.raises(openai.BadRequestError):
            gw._call_once(SimpleNamespace(chat=SimpleNamespace(completions=stub)),
                          "gpt-6-luna", [{"role": "user", "content": "u"}], 0.0, 8192)
        assert len(stub.bodies) == 1
    finally:
        codecraft._body_policies.clear()


def _credits_429() -> openai.RateLimitError:
    body = {"error": {
        "message": "insufficient_credits: Your organization has no available platform credits "
                   "(available after reservations: 0.00 credits). Top-ups start at $5.",
        "type": "insufficient_quota", "param": None, "code": "insufficient_credits"}}
    request = httpx.Request("POST", f"{_EXPLABS_BASE}/chat/completions")
    response = httpx.Response(429, headers={"retry-after": "60"}, json=body, request=request)
    return openai.RateLimitError(body["error"]["message"], response=response, body=body)


def test_credit_state_classification():
    assert _credit_state(SimpleNamespace(body={"error": {
        "message": "insufficient_credits: none left", "code": "insufficient_credits"}})) == "credits"
    assert _credit_state(SimpleNamespace(body={"error": {
        "message": "free limit reached for today", "code": "free_limit_reached"}})) == "daily"
    assert _credit_state(SimpleNamespace(body={"error": {
        "message": "Rate limit exceeded: please try again soon."}})) is None
    assert _credit_state(SimpleNamespace(body=None)) is None


def test_experiential_credits_429_raises_out_of_funds_fast(monkeypatch):
    """An empty wallet is account-wide: fail on the first 429, never rotate or wait."""
    gw = Gateway()
    _hermetic(gw)
    calls = []

    def boom(*a, **k):
        calls.append(1)
        raise _credits_429()

    monkeypatch.setattr(gw, "_call_once", boom)
    with pytest.raises(OutOfFunds, match="credits"):
        gw.complete_json(role="technical", session_id="t", system="s", user="u")
    assert len(calls) == 1
    assert gw._daily_quota_until == {}  # must not be misread as a daily wall


def _free_limit_429() -> openai.RateLimitError:
    body = {"error": {
        "message": "Free daily allowance for gpt-6-luna is spent (free limit reached); "
                   "requests stop until the allowance resets.",
        "type": "insufficient_quota", "param": None, "code": "free_limit_reached"}}
    request = httpx.Request("POST", f"{_EXPLABS_BASE}/chat/completions")
    response = httpx.Response(429, json=body, request=request)
    return openai.RateLimitError(body["error"]["message"], response=response, body=body)


def test_experiential_free_limit_429_is_a_daily_quota(monkeypatch):
    gw = Gateway()
    _hermetic(gw)

    def boom(*a, **k):
        raise _free_limit_429()

    monkeypatch.setattr(gw, "_call_once", boom)
    with pytest.raises(DailyQuotaExhausted) as info:
        gw.complete_json(role="technical", session_id="t", system="s", user="u")
    assert info.value.reset_at is not None and info.value.reset_at > time.time()
    assert gw.quota_status()["exhausted"] is True


def test_persisted_openrouter_reset_does_not_block_experiential(monkeypatch):
    """The provider cutover must not inherit the old provider's 429 wall.

    2026-10-28: the ledger row persisted by the exhausted OpenRouter free tier
    ('resets 05:30 IST') surfaced as 'experiential daily request quota exhausted'
    on the first post-cutover call — the persisted state was provider-agnostic.
    """
    from datetime import date

    from app.db import sqlite_conn

    reset_epoch = time.time() + 3600
    try:
        Gateway()._load_day()  # ensure the additive migration ran for this DB
        conn = sqlite_conn()
        conn.execute(
            "INSERT INTO usage_daily(day, tokens, requests, quota_reset, provider) "
            "VALUES (?,0,0,?, 'openrouter') ON CONFLICT(day) DO UPDATE SET "
            "quota_reset=excluded.quota_reset, provider='openrouter'",
            (date.today().isoformat(), reset_epoch))
        conn.commit()
        # New boot with experiential active: the stale openrouter row is ignored.
        gw = Gateway()
        assert gw._daily_quota_until == {}
        calls = []
        monkeypatch.setattr(gw, "_call_once", lambda *a, **k: (calls.append(1), ('{"ok": true}', 10))[1])
        assert gw.complete_json(role="technical", session_id="t", system="s", user="u") == '{"ok": true}'
        assert len(calls) == 1
    finally:
        conn = sqlite_conn()
        conn.execute("UPDATE usage_daily SET quota_reset=0, provider='' WHERE day=?",
                     (date.today().isoformat(),))
        conn.commit()

import pytest
from datetime import datetime, timezone
from app.agents.technical import run
from app.gateway.codecraft import DailyQuotaExhausted, TokenCapBreach

def test_technical_pit_live():
    import openai
    as_of = datetime(2024, 6, 10, tzinfo=timezone.utc)
    try:
        rep = run("RELIANCE.NS", as_of, "1d", "test-tech")
    except (openai.APIStatusError, openai.APIConnectionError, openai.APITimeoutError,
            openai.RateLimitError) as e:
        pytest.skip(f"provider outage, not a code failure: {type(e).__name__}")
    except TokenCapBreach as e:
        # Spent day budget is an operational condition, not a code failure —
        # same posture as a provider outage. (The pre-flight check in
        # complete_json now raises this before any call is billed.)
        pytest.skip(f"token budget exhausted, not a code failure: {e}")
    except DailyQuotaExhausted as e:
        # The provider's 50/day free-tier allowance is account-wide and shared
        # with chat; once spent (observed 2026-10-27 14:05 IST) this live call
        # cannot pass until reset. Same operational posture as a token cap.
        pytest.skip(f"daily request quota exhausted, not a code failure: {e}")
    assert rep.agent == "technical"
    assert 0.0 <= rep.confidence <= 1.0
    assert len(rep.summary) >= 10
    for ev in rep.evidence:
        assert ev.available_at <= as_of

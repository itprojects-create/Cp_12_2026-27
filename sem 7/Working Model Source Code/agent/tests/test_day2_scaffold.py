"""Day 2 scaffolding tests (NEW_PLAN T2.1-T2.4): portfolio, rating, snapshot iface, sentinels. Zero tokens."""
from datetime import datetime, timezone


def test_portfolio_render_and_fingerprint():
    from app.portfolio import PortfolioContext
    pc = PortfolioContext.model_validate({
        "cash": 25000.0, "currency": "INR",
        "positions": [{"ticker": "RELIANCE.NS", "quantity": 10, "average_price": 2500.0}]})
    txt = pc.render("RELIANCE.NS")
    assert "10 units" in txt and "25,000" in txt
    assert pc.fingerprint() == pc.fingerprint()
    flat = PortfolioContext.model_validate({"cash": 100.0, "positions": []})
    assert "No current position" in flat.render("TCS.NS")
    # None (not provided) stays distinct from flat — graph treats None as legacy
    assert flat.position_in("TCS.NS") is None


def test_rating_extract_and_review():
    from app.rating import extract_rating, parse_rating, is_review, RATING_REVIEW
    assert extract_rating("- **Rating**: Buy\nthesis long") == "Buy"
    assert extract_rating("no rating here at all, just prose about buying") is None
    assert parse_rating("garbage with no label") == RATING_REVIEW
    assert is_review(RATING_REVIEW) is True
    # Scale legend echoed by model is not a call
    assert extract_rating("Rating Scale: Buy, Hold, Sell") is None


def test_session_id_portfolio_isolation():
    from app.agents.graph import new_session_id
    base = new_session_id("RELIANCE.NS", "2024-06-10T00:00:00+00:00", "abc123")
    with_pf = new_session_id("RELIANCE.NS", "2024-06-10T00:00:00+00:00", "abc123", "deadbeef1234")
    assert base != with_pf
    assert new_session_id("RELIANCE.NS", "2024-06-10T00:00:00+00:00", "abc123") == base


def test_snapshot_source_exists():
    import inspect
    import app.data.snapshot as S
    src = inspect.getsource(S.verified_snapshot)
    assert "VERIFIED SNAPSHOT" in src
    assert "DATA_STATUS" in src


def test_data_status_taxonomy():
    from app.data.base import DATA_OK, DATA_UNAVAILABLE, NO_DATA
    assert DATA_OK != DATA_UNAVAILABLE != NO_DATA

"""Pre-registered shadow paper-P&L stream (shadow.py): hermetic tests.

Covers: registration written once; pre-registration batches excluded; deterministic
top-3 bullish picks per horizon; abstain/p<=0.5/bearish exclusions; symbol-asc
tie-break; idempotent re-pick; settlement net = realised excess - 0.4% hurdle scored
only from main-ledger settlements; summary maths. No network, no model calls.
"""
import json
from datetime import date, datetime, timezone

import pytest

from quantplus_intelligence.forecast import ledger as L, schema, service, shadow


def weekdays(day):
    return day.weekday() < 5


def card(**kw):
    base = dict(symbol="RELIANCE", as_of="2026-09-01T10:00:00+00:00", horizon=5, benchmark="NIFTY50",
                p_outperform=0.6, quantiles={"0.1": -0.04, "0.5": 0.0, "0.9": 0.04}, vol_forecast=0.03,
                p_event_shock=0.05)
    base.update(kw)
    return schema.ForecastCard(**base)


REG_AT = datetime(2026, 9, 1, 11, tzinfo=timezone.utc)     # registration moment
BATCH_AT = "2026-09-01T10:00:00+00:00"                     # post-registration batch as_of
REC_AT = datetime(2026, 9, 1, 12, tzinfo=timezone.utc)     # after registration


def lines(path, kind=None):
    out = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    return [l for l in out if kind is None or l["type"] == kind]


def batch_book(tmp_path):
    """A ledger holding one pre-registration batch, then the post-registration batch."""
    path = tmp_path / "paper_pnl.jsonl"
    book = L.Ledger(is_trading_day=weekdays)
    # Locked on 2026-08-31 (Monday), recorded the morning before registration: must
    # never be picked or scored, even after it settles in the main ledger.
    book.record(card(symbol="ZZZ", as_of="2026-08-31T10:00:00+00:00", p_outperform=0.64),
                recorded_at=datetime(2026, 9, 1, 9, tzinfo=timezone.utc))
    shadow.ensure_registration(path, now=REG_AT)
    return book, path


def post_registration_batch(book):
    batch = [card(symbol=s, p_outperform=0.65) for s in ("AAA", "AAB", "AAC", "AAD")]  # 4 tied at top
    batch += [card(symbol="AAX", p_outperform=0.60),                        # 4th strongest, misses top-3
              card(symbol="AAF", p_outperform=0.50),                        # not strictly bullish
              card(symbol="AAG", p_outperform=0.48),                        # bearish lean
              card(symbol="AAE", p_outperform=0.9, abstain=True, abstain_reason="god machine outage")]
    # Two 20-session cards in the same batch (fewer than top-3 available).
    batch += [card(symbol=s, horizon=20, p_outperform=p) for s, p in (("BBB", 0.63), ("BBC", 0.57))]
    for c in batch:
        book.record(c, recorded_at=REC_AT)
    return batch


def test_registration_written_once(tmp_path):
    path = tmp_path / "paper_pnl.jsonl"
    head = shadow.ensure_registration(path, now=REG_AT)
    again = shadow.ensure_registration(path, now=datetime(2026, 9, 2, 12, tzinfo=timezone.utc))
    heads = lines(path, "registration")
    assert len(heads) == 1 and path.read_text(encoding="utf-8").splitlines()[0].startswith(
        '{"type": "registration"')
    assert again["registered_utc"] == head["registered_utc"]
    assert shadow._registered_at(path) == REG_AT


def test_pre_registration_batches_excluded(tmp_path):
    book, path = batch_book(tmp_path)
    out = shadow.pick(book, path)
    assert out["picked"] == 0 and out["batch_as_of"] is None
    assert "no post-registration batch" in out["note"]
    assert lines(path, "pick") == []
    # Even a settle run with the pre-registration card already scored in the main
    # ledger must not create shadow results for it.
    service.settle_due(book, lambda sym, d, h: ([100, 101, 102, 103, 104, 110], [100] * 6),
                       date(2026, 9, 9))
    scored = shadow.settle_picks(book, path)
    assert scored["scored"] == 0


def test_top3_bullish_picks_deterministic(tmp_path):
    book, path = batch_book(tmp_path)
    post_registration_batch(book)
    out = shadow.pick(book, path)
    assert out["batch_as_of"] == BATCH_AT and out["picked"] == 5
    picks = lines(path, "pick")
    five = [p["symbol"] for p in picks if p["horizon"] == 5]
    twenty = [p["symbol"] for p in picks if p["horizon"] == 20]
    # Four cards are tied at p=0.65: the symbol-ascending tie-break keeps AAA/AAB/AAC
    # and drops AAD; AAX lost on |p-0.5|; AAF (p=0.5), AAG (<0.5) and the abstaining
    # AAE are not eligible.
    assert five == ["AAA", "AAB", "AAC"]
    assert twenty == ["BBB", "BBC"]
    assert all(p["p"] > 0.5 for p in picks)
    assert not any(p["symbol"] == "ZZZ" for p in picks)          # pre-registration batch
    assert all(p["rule"] == shadow.RULE and p["authority"] == shadow.AUTHORITY for p in picks)


def test_repick_is_idempotent(tmp_path):
    book, path = batch_book(tmp_path)
    post_registration_batch(book)
    assert shadow.pick(book, path)["picked"] == 5
    again = shadow.pick(book, path)
    assert again["picked"] == 0 and "already picked" in again["note"]
    assert len(lines(path, "pick")) == 5
    # A later batch with a later as_of becomes the new latest batch.
    book.record(card(symbol="NEW", as_of="2026-09-08T10:00:00+00:00", p_outperform=0.7),
                recorded_at=datetime(2026, 9, 8, 12, tzinfo=timezone.utc))
    fresh = shadow.pick(book, path)
    assert fresh["batch_as_of"] == "2026-09-08T10:00:00+00:00" and fresh["picked"] == 1
    assert [p["symbol"] for p in lines(path, "pick") if p["horizon"] == 5 and p["symbol"] == "NEW"] == ["NEW"]


def test_settlement_scores_net_of_hurdle(tmp_path):
    book, path = batch_book(tmp_path)
    post_registration_batch(book)
    assert shadow.pick(book, path)["picked"] == 5
    # Settlement runs in the main ledger first: every matured 5-session card settles
    # with the same +10% excess (ZZZ included) — the shadow may only score its picks.
    service.settle_due(book, lambda sym, d, h: ([100, 101, 102, 103, 104, 110], [100] * 6),
                       date(2026, 9, 9))
    out = shadow.settle_picks(book, path, now=datetime(2026, 9, 9, 16, tzinfo=timezone.utc))
    settles = lines(path, "settle")
    assert out["scored"] == 3
    assert sorted(s["symbol"] for s in settles) == ["AAA", "AAB", "AAC"]
    for s in settles:
        assert s["excess_return"] == pytest.approx(0.10)
        assert s["net"] == pytest.approx(0.10 - shadow.COST_HURDLE)
        assert s["horizon"] == 5 and s["outperformed"] == 1
        assert s["authority"] == shadow.AUTHORITY
    assert not any(s["symbol"] == "ZZZ" for s in settles)
    assert shadow.settle_picks(book, path)["scored"] == 0 and len(settles) == 3


def test_summary_maths_and_run_claim(tmp_path):
    book, path = batch_book(tmp_path)
    post_registration_batch(book)
    shadow.pick(book, path)
    service.settle_due(book, lambda sym, d, h: ([100, 101, 102, 103, 104, 110], [100] * 6),
                       date(2026, 9, 9))
    shadow.settle_picks(book, path)
    s = shadow.summary(path)
    assert s["picks"] == 5 and s["settled"] == 3 and s["open"] == 2
    assert s["hits"] == 3
    assert s["mean_net"] == pytest.approx(0.10 - shadow.COST_HURDLE)
    assert s["sum_net"] == pytest.approx(3 * (0.10 - shadow.COST_HURDLE))
    assert s["by_horizon"][5]["settled"] == 3 and s["by_horizon"][5]["open"] == 0
    assert s["by_horizon"][20]["settled"] == 0 and s["by_horizon"][20]["open"] == 2
    assert s["cost_hurdle"] == shadow.COST_HURDLE and "not money P&L" in s["disclaimer"]
    run = shadow.run(book, path)
    assert run["picked"] == 0 and run["scored"] == 0
    assert run["summary"]["settled"] == 3
    assert "bridge.edge_gate" in run["claim"] and "SHADOW" in run["claim"]

"""Day-4 foundry + positioning tests (prereg_day4_foundry_positioning.md Gate). Zero tokens."""
import pytest

from app.foundry import proposals as P
from app.foundry import validate as V
from app.data import positioning as POS


@pytest.fixture(autouse=True)
def _clean():
    V.init_tables()
    yield
    from app.db import sqlite_conn
    db = sqlite_conn()
    db.execute("DELETE FROM foundry_log WHERE rationale LIKE 'TEST-%'")
    db.commit()


def _row(veto_raw, regime="CALM", breadth="mid", whipsaw=0):
    return {"veto_raw": veto_raw, "regime": regime, "breadth": breadth, "whipsaw": whipsaw}


def _base(row):
    return 0.0  # baseline trades everything


def test_forbidden_kinds_rejected_at_parse():
    for kind, params in (("direction_flip", {"to": "short"}),
                         ("size_boost", {"mult": 2.0}),
                         ("new_indicator", {"name": "rsi2"}),
                         ("veto_band_edge", {"band_lo": 0.1, "band_hi": 0.9, "veto": 0.1})):
        with pytest.raises(ValueError):
            P.parse(kind, params, rationale="TEST falsifier")
    # deregulation-shaped veto (below allowlist floor) also rejected
    with pytest.raises(ValueError):
        P.parse("veto_band_edge", {"band_lo": 0.95, "band_hi": 0.2, "veto": 0.5},
                rationale="TEST bad band")
    with pytest.raises(ValueError):
        P.parse("topK_value", {"K": 42}, rationale="TEST bad K")
    with pytest.raises(ValueError):
        P.parse("blackout_window", {"pre": 2, "post": 1}, rationale="")  # rationale required


def test_allowlisted_pass():
    assert P.parse("veto_band_edge", {"band_lo": 0.5, "band_hi": 0.75, "veto": 1.0,
                                      "regime": "STRESSED", "breadth": "low"},
                   rationale="TEST cell").kind == "veto_band_edge"
    assert P.parse("topK_value", {"K": 30}, rationale="TEST k").kind == "topK_value"
    assert P.parse("blackout_window", {"pre": 5, "post": 3}, rationale="TEST w").kind == "blackout_window"


def test_embargo_separation():
    rows = [_row(0.1 + (i % 9) / 10) for i in range(100)]
    train, test, gap = V.split(rows)
    assert len(train) == 60 and len(gap) == 20 and len(test) == 20
    assert not ({id(r) for r in train} & {id(r) for r in test})


def _concentrated_rows():
    """480 rows, period-20: every 20th row is a STRESSED cell whipsaw;
    rest 10% whipsaw. Deterministic. Test slice (rows 308+) keeps one cell
    row per PBO block with ~4.7% drift (inside ±5pp)."""
    rows = []
    for i in range(480):
        if i % 20 == 0:
            rows.append(_row(0.6, regime="STRESSED", breadth="low", whipsaw=1))
        else:
            rows.append(_row(0.1 + ((i * 7) % 8) / 10, regime="CALM", breadth="mid",
                             whipsaw=1 if (i * 7) % 10 == 0 else 0))
    return rows


def test_good_proposal_promotes():
    rows = _concentrated_rows()
    prop = P.parse("veto_band_edge", {"band_lo": 0.5, "band_hi": 0.75, "veto": 1.0,
                                      "regime": "STRESSED", "breadth": "low"},
                   rationale="TEST concentrated whipsaw cell")
    rec = V.validate(prop, rows, _base)
    assert rec["promoted"] is True, rec
    assert rec["whipsaw_drop_pp"] >= 0.02 and rec["block_wins"] == "8/8"


def test_bad_proposal_fails_on_record_with_exposure_collapse():
    rows = _concentrated_rows()
    prop = P.parse("veto_band_edge", {"band_lo": 0.1, "band_hi": 0.9, "veto": 1.0},
                   rationale="TEST veto everything")
    rec = V.validate(prop, rows, _base)
    assert rec["promoted"] is False
    assert rec["candidate"]["exposure"] < 0.5  # exposure collapse documented
    from app.db import sqlite_conn
    logged = sqlite_conn().execute(
        "SELECT promoted, metrics FROM foundry_log WHERE rationale='TEST veto everything'"
        " ORDER BY id DESC LIMIT 1").fetchone()
    assert logged is not None and logged[0] == 0  # corpse on record
    import json
    assert json.loads(logged[1])["promoted"] is False


def test_positioning_table_and_bounds():
    v, f = POS.positioning_veto_fraction(-2.5, None, None)
    assert v == 0.5 and f == ["fii-pcr:unavailable"]
    v, f = POS.positioning_veto_fraction(0.0, True, True)
    assert v == 0.5
    v, _ = POS.positioning_veto_fraction(-3.0, True, True)
    assert v == 1.0
    v, f = POS.positioning_veto_fraction(None, None, None)
    assert v == 0.0 and len(f) == 2
    v, _ = POS.positioning_veto_fraction(1.5, False, False)
    assert v == 0.0
    for args in ((None, None, None), (-5.0, True, True), (5.0, False, True)):
        assert 0.0 <= POS.positioning_veto_fraction(*args)[0] <= 1.0


def test_positioning_unavailable_legs_and_cache(tmp_path):
    cache = str(tmp_path / "pos.json")
    POS.update_cache(cache)  # empty update: creates file, no crash
    assert POS.update_cache(cache) == {}

    class _DeadStore:
        def latest(self, *a, **k):
            return None

    r = POS.positioning_at("X.NS", __import__("datetime").datetime(2024, 6, 1),
                           delivery_store=_DeadStore(), cache_path=cache)
    assert r["veto"] == 0.0 and "delivery:unavailable" in r["flags"]

    # trailing windows need exactly-5 FII days and >=20 PCR days
    for i in range(1, 7):
        POS.update_cache(cache, fii={"date": f"2024-05-{i:02d}", "fii_net_cr": -100.0})
    for i in range(1, 61):
        POS.update_cache(cache, pcr={"date": f"2024-03-{i:02d}" if i <= 31 else f"2024-04-{i-31:02d}",
                                     "pcr": 0.7 + (i % 10) / 100})
    r = POS.positioning_at("X.NS", __import__("datetime").datetime(2024, 6, 1),
                           delivery_store=_DeadStore(), cache_path=cache,
                           pcr={"pcr": 5.0})
    assert r["veto"] == 0.5  # fii 5d negative + pcr extreme, delivery abstains
    assert "delivery:unavailable" in r["flags"]


def test_nse_fetch_never_raises(monkeypatch):
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: (_ for _ in ()).throw(OSError("down")))
    assert POS.fetch_nse_json("http://x") is None
    assert POS.fetch_fii_daily() is None
    assert POS.fetch_nifty_pcr() is None

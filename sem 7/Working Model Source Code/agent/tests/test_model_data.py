"""Model-data wiring tests: synthetic fixtures only, zero network (prereg_model_data_wiring.md Gate)."""
from datetime import datetime, timezone

import pytest


def _asof(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


def _write_parquet(tmp_path, year: int, rows: list[tuple]):
    import pandas as pd
    df = pd.DataFrame(rows, columns=["date", "symbol", "qty_traded",
                                     "deliverable_qty", "delivery_pct"])
    p = tmp_path / f"delivery_{year}.parquet"
    df.to_parquet(p)
    return tmp_path


def test_t1_lag_boundary(tmp_path):
    from app.data.delivery_panel import ParquetDeliveryStore
    d = _write_parquet(tmp_path, 2024, [
        ("2024-06-03", "AAA", 100, 50, 50.0),
        ("2024-06-04", "AAA", 100, 60, 60.0),
    ])
    s = ParquetDeliveryStore(panel_dir=str(d))
    # as_of 06-04: only 06-03 usable (strictly before)
    r = s.latest("AAA.NS", _asof("2024-06-04T18:00:00"))
    assert r is not None and r["date"] == "2024-06-03" and r["delivery_pct"] == 50.0
    # as_of 06-03: nothing strictly before -> abstain
    assert s.latest("AAA.NS", _asof("2024-06-03T10:00:00")) is None
    assert s.latest("ZZZ.NS", _asof("2024-06-04T18:00:00")) is None  # unknown ticker
    assert "unavailable" in s.line("ZZZ.NS", _asof("2024-06-04T18:00:00"))


def test_ma5_z20_trailing_only(tmp_path):
    from app.data.delivery_panel import ParquetDeliveryStore
    rows = [(f"2024-05-{d:02d}", "BBB", 100, 40 + (d % 5), 40.0 + (d % 5)) for d in range(1, 31)]
    d = _write_parquet(tmp_path, 2024, rows)
    s = ParquetDeliveryStore(panel_dir=str(d))
    r = s.latest("BBB.NS", _asof("2024-06-01T00:00:00"))
    assert r["date"] == "2024-05-30"
    assert r["ma5"] == pytest.approx(sum(40.0 + (dd % 5) for dd in range(26, 31)) / 5)
    assert r["z20"] is not None and -3.0 < r["z20"] < 3.0
    assert "z20=" in s.line("BBB.NS", _asof("2024-06-01T00:00:00"))


def test_flat_series_z_none_not_zero(tmp_path):
    from app.data.delivery_panel import ParquetDeliveryStore
    rows = [(f"2024-05-{d:02d}", "CCC", 100, 50, 50.0) for d in range(1, 31)]
    d = _write_parquet(tmp_path, 2024, rows)
    s = ParquetDeliveryStore(panel_dir=str(d))
    r = s.latest("CCC.NS", _asof("2024-06-01T00:00:00"))
    assert r["z20"] is None  # no variance -> abstain, never z=0
 
def test_missing_panel_raises_loudly(tmp_path):
    from app.data.delivery_panel import ParquetDeliveryStore
    s = ParquetDeliveryStore(panel_dir=str(tmp_path / "absent"))
    with pytest.raises(FileNotFoundError):
        s.latest("AAA.NS", _asof("2024-06-01T00:00:00"))


def test_tri_parse_sort_cagr(tmp_path):
    from app.data import tri_benchmark as TRI
    p = tmp_path / "tri.csv"
    # reverse-chrono + "17 Sep 2026" format, with a duplicate date
    p.write_text("date,index_name,total_returns_index\n"
                 "17 Sep 2026,Nifty 50,110.0\n"
                 "17 Sep 2026,Nifty 50,111.0\n"
                 "16 Sep 2026,Nifty 50,105.0\n"
                 "15 Sep 2026,Nifty 50,100.0\n", encoding="utf-8")
    r = TRI.total_return("NIFTY50", "2026-09-15", "2026-09-17", path=str(p))
    assert r["total"] == round(111.0 / 100.0 - 1, 4)  # dedupe keeps last; T+1 join
    assert r["cagr"] > r["total"]  # 2-day annualization explodes: sanity direction only
    with pytest.raises(FileNotFoundError):
        TRI.total_return("NIFTY50", "2026-09-15", "2026-09-17", path=str(tmp_path / "absent.csv"))
    with pytest.raises(ValueError):
        TRI.total_return("NOPE", "2026-09-15", "2026-09-17", path=str(p))  # unknown index
    with pytest.raises(ValueError):
        TRI.total_return("NIFTY50", "2020-01-01", "2026-09-17", path=str(p))  # uncovered start


def test_gates_doc_and_calibration_scoping():
    import pathlib
    gates = pathlib.Path("data/evaluation_gates.md").read_text(encoding="utf-8")
    for token in ("G1", "G2", "G3", "G4", "G5", "DSR", "PBO", "SIZING-ONLY"):
        assert token in gates
    assert "accuracy" in gates and "RETIRED" in gates
    calib = pathlib.Path("app/memory/calibrate.py").read_text(encoding="utf-8")
    assert "SIZING-ONLY" in calib
    # structural: every public function returns scalars/dicts (probabilities,
    # fractions, sizes) — none returns an ordering, shortlist, or selection
    import app.memory.calibrate as C
    import inspect
    for name in ("predict", "kelly_fraction", "payoff_ratio", "brier"):
        ann = inspect.signature(getattr(C, name)).return_annotation
        assert ann in (float, dict, "", "float", "dict"), name  # strings under PEP 563
    assert set(inspect.signature(C.apply_sizing).parameters) >= {
        "core_size", "raw_veto", "calib", "avg_win", "avg_loss"}


def test_vix_local_exact_join_and_stale(tmp_path):
    import pandas as pd
    from app.data import vix_local
    p = tmp_path / "vix.csv"
    pd.DataFrame({"date": ["2024-06-01", "2024-06-02", "2024-06-03"],
                  "vix_open": [10, 11, 12], "vix_high": [11, 12, 13],
                  "vix_low": [9, 10, 11], "vix_close": [10.5, 11.5, 12.5]}).to_csv(p, index=False)
    # T+1 discipline: as_of 06-03 sees the 06-02 bar (11.5), never 06-03
    assert vix_local.close_at(_asof("2024-06-03T18:00:00"), path=str(p)) == 11.5
    h = vix_local.history(_asof("2024-06-04T00:00:00"), path=str(p))
    assert h == [10.5, 11.5, 12.5]
    # stale file (>30d before as_of) -> None, never stale data
    assert vix_local.close_at(_asof("2025-01-01T00:00:00"), path=str(p)) is None
    assert vix_local.close_at(_asof("2024-06-01T00:00:00"), path=str(tmp_path / "absent.csv")) is None

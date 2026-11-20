"""Local diet tests: delivery PIT lag, GDELT filtering, graceful absence. Zero tokens."""
from __future__ import annotations
from datetime import datetime, timezone
import pandas as pd

from app.data import local_store as LS
from app.data import gdelt_provider as GD

AS_OF = datetime(2024, 6, 10, tzinfo=timezone.utc)

def _delivery_csv(path):
    pd.DataFrame([
        {"date": "2024-06-06", "ticker": "X.NS", "delivery_pct": 60.0,
         "delivery_pct_ma5": 55.0, "delivery_pct_z20": 1.5},
        {"date": "2024-06-07", "ticker": "X.NS", "delivery_pct": 40.0,
         "delivery_pct_ma5": 52.0, "delivery_pct_z20": -1.2},
        {"date": "2024-06-10", "ticker": "X.NS", "delivery_pct": 70.0,  # same-day: must NOT leak
         "delivery_pct_ma5": 56.0, "delivery_pct_z20": 2.5},
    ]).to_csv(path, index=False)

def test_delivery_one_session_lag(tmp_path):
    p = tmp_path / "d.csv"
    _delivery_csv(p)
    got = LS.DeliveryStore(str(p)).latest("X.NS", AS_OF)
    assert got and got["date"] == "2024-06-07" and got["delivery_pct"] == 40.0
    line = LS.DeliveryStore(str(p)).line("X.NS", AS_OF)
    assert "distribution" in line and "1-session lag" in line

def test_delivery_absent_gracefully(tmp_path):
    assert LS.DeliveryStore(str(tmp_path / "nope.csv")).latest("X.NS", AS_OF) is None
    p = tmp_path / "d.csv"
    _delivery_csv(p)
    assert LS.DeliveryStore(str(p)).latest("UNKNOWN.NS", AS_OF) is None
    assert "unavailable" in LS.DeliveryStore(str(p)).line("UNKNOWN.NS", AS_OF)

def _gdelt_csv(path):
    pd.DataFrame([
        {"date": "20160201040000", "source": "s1", "doc_url": "u1",
         "organizations": "reliance industries;ongc", "tone_v15": "2.5,0,0,0,0,0,5"},
        {"date": "20160301040000", "source": "s2", "doc_url": "u2",  # after as_of: must not leak
         "organizations": "reliance industries", "tone_v15": "-9.0,0,0,0,0,0,5"},
        {"date": "20160202040000", "source": "s3", "doc_url": "u3",
         "organizations": "infosys", "tone_v15": "1.0,0,0,0,0,0,5"},
    ]).to_csv(path, index=False)

def test_gdelt_pit_and_match(tmp_path):
    p = tmp_path / "g.csv"
    _gdelt_csv(p)
    as_of = datetime(2016, 2, 15, tzinfo=timezone.utc)
    hits = GD.GdeltNewsProvider(str(p)).headlines("RELIANCE", as_of)
    assert len(hits) == 1 and "tone=+2.50" in hits[0]["title"]
    assert hits[0]["published_at"] <= as_of.isoformat()
    assert GD.GdeltNewsProvider(str(p)).headlines("RELIANCE", as_of) is not None
    # unknown company -> no hits, not an error
    assert GD.GdeltNewsProvider(str(p)).headlines("Tata Motors XYZ", as_of) == []

def test_gdelt_missing_file():
    assert GD.GdeltNewsProvider("/nonexistent/g.csv").headlines("x", AS_OF) == []

def test_real_delivery_file_covers_eval_universe():
    got = LS.DeliveryStore().latest("RELIANCE.NS", AS_OF)
    assert got and got["date"] < "2024-06-10" and got["delivery_pct"] > 0

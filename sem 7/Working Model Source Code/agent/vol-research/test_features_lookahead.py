"""No-lookahead tests for vol-research features (same pattern as the
agent-service exhaustion lookahead test): append/perturb bars AFTER the
forecast bar and assert every feature at that bar is bit-identical.

Run: python test_features_lookahead.py  (or pytest test_features_lookahead.py)
"""
import math
import pandas as pd

import features as F


def _synth(n=600, seed=7) -> pd.DataFrame:
    import random
    rng = random.Random(seed)
    px, out = [100.0], []
    for _ in range(n):
        px.append(px[-1] * math.exp(rng.gauss(0.0004, 0.012)))
    closes = px[1:]
    return pd.DataFrame({"Close": closes},
                        index=pd.date_range("2018-01-01", periods=n, freq="B"))


def _feats(df, i):
    rv = F.realized_vol20(df["Close"])
    return {
        "rv": rv.iloc[i],
        "med": F.trailing_median252(rv).iloc[i],
        "pct": F.vol_percentile_rank(rv, i),
        "vix": F.vix_level(df["Close"], i),
        "slope": F.vix_5d_slope(df["Close"], i),
        "freq": F.recent_extreme_move_freq(df["Close"], i),
        "reg": F.vix_regime_bucket(df["Close"], i),
    }


def test_no_lookahead_append():
    df = _synth()
    i = 400
    base = _feats(df, i)
    # append 60 future bars with a violent regime shift (must not leak back)
    extra = pd.DataFrame({"Close": [df["Close"].iloc[-1] * (1.10) ** k for k in range(1, 61)]},
                         index=pd.date_range(df.index[-1] + pd.Timedelta(days=1), periods=60, freq="B"))
    df2 = pd.concat([df, extra])
    assert _feats(df2, i) == base, "appended future bars changed features at i"


def test_no_lookahead_perturb_future():
    df = _synth()
    i = 400
    base = _feats(df, i)
    df2 = df.copy()
    df2.iloc[i + 1:, df2.columns.get_loc("Close")] *= 1.25  # shock everything after i
    assert _feats(df2, i) == base, "perturbed future bars changed features at i"


def test_percentile_strictly_prior_and_ties():
    s = pd.Series([0.20] * 300)  # flat history
    s.iloc[299] = 0.20
    assert F.vol_percentile_rank(s, 299) == 0.0, "flat stretch must rank 0 (strict-<)"


def test_short_history_defaults():
    s = pd.Series([0.15] * 30)
    assert F.vol_percentile_rank(s, 29) == 50.0
    assert F.vix_regime_bucket(s, 29) == "CALM"
    c = pd.Series([100.0] * 30)
    assert F._flag_at(c, 29) == (False, False)


def test_known_exhaustion_flag():
    # engineered -12% 5-day drop must raise flush under the fallback threshold
    c = pd.Series([100.0] * 40 + [100, 97, 94, 91, 88])
    f, b = F._flag_at(c, 44)
    assert f is True and b is False, f"expected flush, got {(f, b)}"


if __name__ == "__main__":
    test_no_lookahead_append()
    test_no_lookahead_perturb_future()
    test_percentile_strictly_prior_and_ties()
    test_short_history_defaults()
    test_known_exhaustion_flag()
    print("all lookahead tests passed")

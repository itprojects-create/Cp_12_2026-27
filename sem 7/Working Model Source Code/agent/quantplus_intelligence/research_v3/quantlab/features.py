"""W3 PIT feature engine: extends the W2 PitPanel with volume/liquidity and a
preregistered cross-sectional feature vector.

Inherited guarantees (W2 lab.data):
- every lookup is decision-gated on ``available_at <= decision_ts``;
- alias/rename closure merges bar history per INSTRUMENT (old tickers resolve
  to the same security without inventing a dated action);
- lookback windows that contain an archive session-gap or an action-shaped
  raw-price discontinuity (close/prev_close outside [0.65, 1.54]) ABSTAIN —
  typed None, disclosed, never guessed through.

Feature vector (preregistered; every feature abstains individually on its own
window problems; no imputation, no out-of-cutoff reads):

  ret_5 / ret_20 / ret_60 / ret_120   session momentum (close-to-close)
  prox_252                            proximity to 252-session available high
  vol_20                              std of 20 daily returns (21 bars)
  trend_consistency_20                fraction of positive daily returns
  volume_ratio_20                     visible volume / trailing 20-session mean
  liquidity_20                        median visible value_paise over trailing 20
  drawdown_60                         1 - close / max(close over 60)
  overnight_gap                       visible open / prev_close - 1
  rel_mom_60                          ret_60 minus NIFTY50_TRI over same span

Sector-relative features: UNAVAILABLE — no source-verified, as-of historical
sector map exists; they are never emitted (documented blocker, not a zero).
Short-term reversal is read off ret_5 (preregistered rank baseline negates it).
"""
from __future__ import annotations

import sqlite3

from quantplus_intelligence.research_v3.lab.data import PitPanel, GAP_LO, GAP_HI
from quantplus_intelligence.research_v3.lab.spec import fingerprint
from quantplus_intelligence.research_v3.quantlab.contracts import (
    RETROSPECTIVE, FeatureSnapshot)

FEATURE_NAMES = ("ret_5", "ret_20", "ret_60", "ret_120", "prox_252", "vol_20",
                 "trend_consistency_20", "volume_ratio_20", "liquidity_20",
                 "drawdown_60", "overnight_gap", "rel_mom_60")
# sector-relative features are intentionally absent (no verified map)


def _median(xs: list[float]) -> float:
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def _std(xs: list[float]) -> float:
    n = len(xs)
    if n < 2:
        return 0.0
    m = sum(xs) / n
    return (sum((x - m) ** 2 for x in xs) / n) ** 0.5


def _volume_bisect(vrows: list[tuple], visible_session: str) -> int:
    """Index one past the last volume row with session <= visible_session."""
    lo, hi = 0, len(vrows)
    while lo < hi:
        mid = (lo + hi) // 2
        if vrows[mid][0] <= visible_session:
            lo = mid + 1
        else:
            hi = mid
    return lo


class FeaturePanel(PitPanel):
    """PitPanel + volume/value series + the W3 feature vector."""

    def __init__(self, conn: sqlite3.Connection, universe_id: str = "nifty50"):
        super().__init__(conn, universe_id)
        self.volumes: dict[str, list[tuple]] = {}
        for sym in self.series:
            closure = sorted(self.alias_map[sym])
            marks = ",".join("?" * len(closure))
            rows = conn.execute(
                f"SELECT session, volume, value_paise FROM daily_bars "
                f"WHERE symbol IN ({marks}) AND series='EQ' ORDER BY session",
                closure).fetchall()
            seen, dedup = set(), []
            for r in rows:
                if r[0] not in seen:
                    seen.add(r[0])
                    dedup.append(r)
            self.volumes[sym] = dedup
        # official TRI (single benchmark truth; same basis W2 benchmark checks use)
        self.tri = {s: v for s, v in conn.execute(
            "SELECT session, tri_value FROM benchmark_bars "
            "WHERE index_code='NIFTY50_TRI' ORDER BY session")}
        # membership spell provenance per symbol (strict vs weak disclosure)
        self.spells: dict[str, list[tuple]] = {}
        for sym, vf, vt, _src, strict in conn.execute(
            "SELECT symbol, valid_from, valid_to, source, strict "
            "FROM membership_spells WHERE universe_id=?", (self.universe_id,)):
            self.spells.setdefault(sym, []).append(
                (vf, vt, bool(strict)))

    # --- window helpers ---------------------------------------------------------
    def _contiguous_window(self, sym: str, i: int, n: int) -> list[tuple] | None:
        """The n bars ending at index i-1 (inclusive), or None when the span is
        not covered by n consecutive observed sessions or contains a
        discontinuity ratio (identical rule to the W2 signal gates)."""
        rows = self.series.get(sym, ())
        if i < n:
            return None
        win = rows[i - n:i]
        j = self.pos[win[0][0]]
        if len(self.sessions[j:self.pos[win[-1][0]] + 1]) != n:
            return None
        for _s, _o, c, p, _a in win:
            if p and (c / p < GAP_LO or c / p > GAP_HI):
                return None
        return win

    def _contiguous_volume_window(self, sym: str, i: int, n: int):
        """n volume rows ending at index i-1, session-consecutive only."""
        vrows = self.volumes.get(sym, ())
        if i < n:
            return None
        win = vrows[i - n:i]
        j = self.pos[win[0][0]]
        if len(self.sessions[j:self.pos[win[-1][0]] + 1]) != n:
            return None
        return win

    def _momentum_ix(self, sym: str, i: int, lookback: int) -> float | None:
        """Close-to-close return over the last `lookback` bars ending at the
        visible index i-1 (lookback + 1 bars; same gating as W2 momentum)."""
        win = self._contiguous_window(sym, i, lookback + 1)
        if win is None:
            return None
        c0, c1 = win[0][2], win[-1][2]
        if c0 <= 0:
            return None
        return c1 / c0 - 1

    # --- snapshot ----------------------------------------------------------------
    def snapshot(self, symbol: str, decision_ts: str,
                 canonical_name: str = "") -> FeatureSnapshot:
        """Build one FeatureSnapshot strictly from bars available at cutoff."""
        sym = self._resolve(symbol)
        if sym is None:
            raise KeyError(f"instrument unknown to panel: {symbol}")
        i = self._bisect_available(sym, decision_ts)
        rows = self.series.get(sym, ())
        feats: dict[str, float] = {}
        abstained: dict[str, str] = {}
        missing: list[str] = []
        decision_session, visible_at = "", ""

        def abstain(name: str, reason: str) -> None:
            # data ABSENT (vs. present-but-corrupted) -> explicit missingness mask
            if ("insufficient" in reason or "unavailable" in reason
                    or "no bar" in reason):
                missing.append(name)
            abstained[name] = reason

        vis = rows[i - 1] if i else None
        if vis is not None:
            decision_session, visible_at = vis[0], vis[4]
        else:
            for n in FEATURE_NAMES:
                abstain(n, "no bar available at cutoff")

        if vis is not None:
            for name, lb in (("ret_5", 5), ("ret_20", 20), ("ret_60", 60),
                             ("ret_120", 120)):
                v = self._momentum_ix(sym, i, lb)
                if v is None:
                    abstain(name, "lookback gap or action discontinuity")
                else:
                    feats[name] = v

            v = self.near_52w_high(sym, decision_ts, 252)
            if v is None:
                abstain("prox_252", "lookback gap or action discontinuity")
            else:
                feats["prox_252"] = v

            # volatility / trend consistency over 20 daily returns (21 bars)
            win21 = self._contiguous_window(sym, i, 21)
            if win21 is None:
                abstain("vol_20", "lookback gap or action discontinuity")
                abstain("trend_consistency_20",
                        "lookback gap or action discontinuity")
            else:
                rets = [c / p - 1 for _s, _o, c, p, _a in win21[1:] if p]
                feats["vol_20"] = _std(rets)
                feats["trend_consistency_20"] = sum(r > 0 for r in rets) / len(rets)

            # volume-based features (visible bar must carry a usable volume)
            vrows = self.volumes.get(sym, ())
            v_i = _volume_bisect(vrows, decision_session)
            if v_i == 0 or not vrows[v_i - 1][1]:
                abstain("volume_ratio_20", "visible volume unavailable")
                abstain("liquidity_20", "visible volume unavailable")
            else:
                vwin = self._contiguous_volume_window(sym, v_i, 21)
                if vwin is None:
                    abstain("volume_ratio_20", "lookback gap or action discontinuity")
                    abstain("liquidity_20", "lookback gap or action discontinuity")
                else:
                    visible_vol = vrows[v_i - 1][1]
                    # trailing = the 20 volume rows BEFORE the visible bar
                    trailing = [r[1] for r in vwin[:-1] if r[1] and r[1] > 0]
                    if len(trailing) < 20:
                        abstain("volume_ratio_20",
                                "trailing volume history insufficient")
                    else:
                        feats["volume_ratio_20"] = visible_vol / (sum(trailing) / len(trailing))
                    vals = [r[2] for r in vwin if r[2] and r[2] > 0]
                    if len(vals) >= 20:
                        feats["liquidity_20"] = _median(vals[-20:])
                    else:
                        abstain("liquidity_20", "trailing value history insufficient")

            # drawdown from the 60-session visible high
            win60 = self._contiguous_window(sym, i, 60)
            if win60 is None:
                abstain("drawdown_60", "lookback gap or action discontinuity")
            else:
                hi = max(r[2] for r in win60)
                if hi <= 0:
                    abstain("drawdown_60", "degenerate close in window")
                else:
                    feats["drawdown_60"] = 1 - win60[-1][2] / hi

            # overnight gap of the visible bar (raw; action-shaped => abstain)
            if vis[3] and vis[3] > 0:
                ratio = vis[1] / vis[3]
                if ratio < GAP_LO or ratio > GAP_HI:
                    abstain("overnight_gap", "action-shaped open gap")
                else:
                    feats["overnight_gap"] = ratio - 1
            else:
                abstain("overnight_gap", "prev_close unavailable")

            # index-relative momentum: TRI over the same 60-bar calendar span
            win61 = self._contiguous_window(sym, i, 61)
            if win61 is None:
                abstain("rel_mom_60", "stock leg window gap or discontinuity")
            else:
                tri = self._tri_return(win61[0][0], win61[-1][0])
                c0, c1 = win61[0][2], win61[-1][2]
                if tri is None:
                    abstain("rel_mom_60", "TRI endpoints unavailable")
                elif c0 <= 0:
                    abstain("rel_mom_60", "degenerate close in window")
                else:
                    feats["rel_mom_60"] = (c1 / c0 - 1) - tri

        return FeatureSnapshot(
            symbol=sym, canonical_name=canonical_name,
            decision_session=decision_session, decision_ts=decision_ts,
            available_at=visible_at, features=feats, missing=tuple(missing),
            abstained_features=abstained,
            reconstruction_label=RETROSPECTIVE,
            snapshot_id=fingerprint({"snapshot": {
                "symbol": sym, "decision_ts": decision_ts,
                "features": {k: round(v, 12) for k, v in sorted(feats.items())}}}))

    def _tri_return(self, start_session: str, end_session: str) -> float | None:
        a, b = self.tri.get(start_session), self.tri.get(end_session)
        if a is None or b is None or a <= 0:
            return None
        return b / a - 1

    def spell_strict(self, symbol: str, decision_date: str) -> bool | None:
        """Strict provenance of the membership spell active at ``decision_date``
        (True = press-release-grade; False = weak snapshot floor; None = no
        active spell known — disclosed, never treated as verified)."""
        for vf, vt, strict in self.spells.get(symbol, ()):
            if vf <= decision_date and (vt is None or decision_date <= vt):
                return strict
        return None

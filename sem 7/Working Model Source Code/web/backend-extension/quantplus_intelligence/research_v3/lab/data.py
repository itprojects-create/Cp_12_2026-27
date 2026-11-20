"""W2 PIT feature provider: decision-time signals with typed abstention.

Loads one alias-resolved OHLC series per historical member symbol into memory
(nifty50-scale: a few hundred symbols), and serves strictly decision-gated
features:

- every feature reads only bars with ``available_at <= decision_ts``;
- ``momentum`` and ``near_52w_high`` return ``None`` (ABSTAIN) when the
  lookback window has insufficient history OR contains an overnight price
  discontinuity (raw close/prev_close outside [0.65, 1.54]) — a corrupted
  signal is refused, never guessed through;
- the discontinuity scan is disclosure-only for holding windows (returns are
  never cleaned selectively — that would bias upward).

No imputation, no forward-fill, no survivorship: members come from as-of
spells (``warehouse.members_at``), delisted names appear inside their spells.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime

from quantplus_intelligence.research_v3 import warehouse as W

GAP_LO, GAP_HI = 0.65, 1.54


class PitPanel:
    """In-memory alias-resolved series for the universe's historical members."""

    def __init__(self, conn: sqlite3.Connection, universe_id: str = "nifty50"):
        self.conn = conn
        self.universe_id = universe_id
        self.sessions = W.sessions(conn)          # observed sessions, ascending
        self.pos = {s: i for i, s in enumerate(self.sessions)}
        self._renames = conn.execute(
            "SELECT old_symbol, new_symbol FROM symbol_renames").fetchall()
        self.series: dict[str, list[tuple]] = {}  # panel key -> alias-merged rows
        self.alias_map: dict[str, frozenset[str]] = {}
        symbols = {row[0] for row in conn.execute(
            "SELECT DISTINCT symbol FROM membership_spells WHERE universe_id=?",
            (universe_id,))}
        for sym in sorted(symbols):
            closure = self._alias_closure(sym)
            self.alias_map[sym] = frozenset(closure)
            marks = ",".join("?" * len(closure))
            rows = conn.execute(
                f"SELECT session, open_paise, close_paise, prev_close_paise, available_at "
                f"FROM daily_bars WHERE symbol IN ({marks}) AND series='EQ' ORDER BY session",
                closure).fetchall()
            # dedupe sessions across aliases (rename overlap): keep first
            seen, dedup = set(), []
            for r in rows:
                if r[0] not in seen:
                    seen.add(r[0])
                    dedup.append(r)
            self.series[sym] = dedup

    def _alias_closure(self, sym: str) -> list[str]:
        """Full rename-connected component (both directions).

        Bars follow the INSTRUMENT, not the name: an undated or dated rename
        still proves the two names are the same instrument, so the merged
        series must carry history across it. Canonical display names (which
        ``members_at`` returns post-effective-date) resolve back to the spell
        symbol owning the merged series via ``key_for``.
        """
        out, frontier = {sym}, [sym]
        while frontier:
            x = frontier.pop()
            for a, b in self._renames:
                if a == x and b not in out:
                    out.add(b)
                    frontier.append(b)
                elif b == x and a not in out:
                    out.add(a)
                    frontier.append(a)
        return sorted(out)

    def key_for(self, symbol: str):
        """Panel-series key for any spelling of the instrument (spell symbol,
        canonical display name, raw bar name); None when unknown to the panel."""
        s = (symbol or "").strip().upper()
        if s in self.series:
            return s
        for key, aliases in self.alias_map.items():
            if s in aliases:
                return key
        return None

    # --- lookups ----------------------------------------------------------------
    def _resolve(self, sym: str):
        """Internal series key for any spelling (spell symbol, canonical display
        name, raw bar name); None when the instrument is unknown to the panel."""
        return self.key_for(sym)

    def _bisect_available(self, sym: str, decision_ts: str) -> int:
        """Index one past the last bar of ``sym`` available at ``decision_ts``.

        Bars are session-ordered; ``available_at`` increases with session, so
        availability bisects on the available_at column values.
        """
        rows = self.series.get(sym, ())
        lo, hi = 0, len(rows)
        while lo < hi:
            mid = (lo + hi) // 2
            if rows[mid][4] <= decision_ts:
                lo = mid + 1
            else:
                hi = mid
        return lo

    def decision_close(self, sym: str, decision_ts: str):
        """(session, close_paise) of the latest bar available at decision."""
        sym = self._resolve(sym)
        if sym is None:
            return None
        i = self._bisect_available(sym, decision_ts)
        if i == 0:
            return None
        s, _o, c, _p, _a = self.series[sym][i - 1]
        return s, c

    def bar_on(self, sym: str, session: str):
        """(open_paise, close_paise) on an observed session, or None."""
        sym = self._resolve(sym)
        if sym is None:
            return None
        rows = self.series.get(sym, ())
        lo, hi = 0, len(rows)
        while lo < hi:
            mid = (lo + hi) // 2
            if rows[mid][0] < session:
                lo = mid + 1
            else:
                hi = mid
        if lo < len(rows) and rows[lo][0] == session:
            return rows[lo][1], rows[lo][2]
        return None

    def members_at(self, decision_date: str, mode: str = "disclosed"):
        res = W.members_at(self.conn, self.universe_id, decision_date,
                           strict=(mode == "strict"))
        return res

    # --- signals ------------------------------------------------------------------
    def _window_ok(self, sym: str, sessions: list[str]) -> bool:
        """False when any overnight ratio inside the window is a discontinuity."""
        rows = self.series.get(sym, ())
        by_session = None
        for s in sessions:
            if by_session is None:
                by_session = {r[0]: r for r in rows}
            r = by_session.get(s)
            if r and r[3] and (r[2] / r[3] < GAP_LO or r[2] / r[3] > GAP_HI):
                return False
        return True

    def momentum(self, sym: str, decision_ts: str, lookback: int, skip: int = 0,
                 min_history: int = 0) -> float | None:
        """Return over the last ``lookback`` available sessions ending ``skip``
        sessions before the decision; None = ABSTAIN (typed, disclosed upstream)."""
        sym = self._resolve(sym)
        if sym is None:
            return None
        i = self._bisect_available(sym, decision_ts)
        rows = self.series.get(sym, ())
        need = lookback + skip + 1 + min_history
        if i < need:
            return None
        end_i = i - 1 - skip          # last session in the measurement window
        start_i = i - 1 - skip - lookback
        s_end = rows[end_i][0]
        s_start = rows[start_i][0]
        j = self.pos[s_start]
        window = self.sessions[j:self.pos[s_end] + 1]
        if len(window) != lookback + 1:
            return None               # archive gap inside the lookback window
        if not self._window_ok(sym, window):
            return None               # action-shaped discontinuity: refuse, don't guess
        c_start, c_end = rows[start_i][2], rows[end_i][2]
        if c_start <= 0:
            return None
        return c_end / c_start - 1

    def near_52w_high(self, sym: str, decision_ts: str,
                      window_sessions: int = 252) -> float | None:
        """Negative relative distance to the highest available close in the
        window (0 = AT the high). None = ABSTAIN on the same rules."""
        sym = self._resolve(sym)
        if sym is None:
            return None
        i = self._bisect_available(sym, decision_ts)
        rows = self.series.get(sym, ())
        if i < window_sessions:
            return None
        win = rows[i - window_sessions:i]
        sess = [r[0] for r in win]
        j = self.pos[sess[0]]
        if len(self.sessions[j:self.pos[sess[-1]] + 1]) != window_sessions:
            return None               # gap inside the window
        if not self._window_ok(sym, sess):
            return None
        high = max(r[2] for r in win)
        close = win[-1][2]
        if high <= 0:
            return None
        return -(high - close) / high   # closer to high -> closer to 0

    # --- holding-window disclosure -------------------------------------------------
    def holding_discontinuities(self, sym: str, start_session: str,
                                end_session: str) -> list[dict]:
        sym = self._resolve(sym)
        if sym is None:
            return []
        rows = self.series.get(sym, ())
        lo, hi = 0, len(rows)
        while lo < hi:
            mid = (lo + hi) // 2
            if rows[mid][0] < start_session:
                lo = mid + 1
            else:
                hi = mid
        out = []
        for s, o, c, p, _a in rows[lo:]:
            if s > end_session:
                break
            for kind, ratio in (("close/prev_close", c / p if p else None),
                                ("open/prev_close", o / p if p else None)):
                if ratio is not None and (ratio < GAP_LO or ratio > GAP_HI):
                    out.append({"session": s, "kind": kind, "ratio": round(ratio, 4)})
        return out


# ---------------------------------------------------------------------------
# coverage tool
# ---------------------------------------------------------------------------
def list_data_coverage(conn: sqlite3.Connection, universe_id: str,
                       start: str, end: str,
                       fields: list[str] | None = None) -> dict:
    """list_data_coverage(universe, start, end, fields) — typed coverage report.

    Read-only, deterministic: what the ingested sources actually prove for the
    window (sessions, membership knowability, bar coverage, TRI, fee schedule),
    with every limitation disclosed — never a filled-in coverage claim.
    """
    want = set(fields) if fields else {"sessions", "membership", "bars", "tri", "fees"}
    out: dict = {"universe_id": universe_id, "window": [start, end]}
    if "sessions" in want:
        rows = conn.execute(
            "SELECT DISTINCT session FROM daily_bars WHERE session>=? AND session<=? "
            "ORDER BY session", (start, end)).fetchall()
        per_year: dict[str, int] = {}
        for (s,) in rows:
            per_year[s[:4]] = per_year.get(s[:4], 0) + 1
        holes = []
        for a, b in zip(rows, rows[1:]):
            da = datetime.fromisoformat(a[0][:10])
            db_ = datetime.fromisoformat(b[0][:10])
            if (db_ - da).days > 14:
                holes.append([a[0], b[0], (db_ - da).days])
        out["sessions"] = {"count": len(rows), "per_year": per_year,
                           "gaps_over_14d": holes,
                           "note": "observed sessions only; a gap means the "
                                   "archive has no bars for ANY symbol there"}
    if "membership" in want:
        spells = conn.execute(
            "SELECT symbol, valid_from, COALESCE(valid_to,'9999-12-31'), source, strict "
            "FROM membership_spells WHERE universe_id=?", (universe_id,)).fetchall()
        strict_n = weak_n = 0
        members: set[str] = set()
        for sym, vf, vt, src, is_strict in spells:
            if vf <= end and vt >= start:
                members.add(sym)
                if is_strict:
                    strict_n += 1
                else:
                    weak_n += 1
        out["membership"] = {
            "universe_rows": len(spells), "members_in_window": len(members),
            "strict_spells": strict_n, "weak_spells": weak_n,
            "note": "weak (snapshot_floor) spells are backward-walk upper bounds; "
                    "no row-level first-known timestamps exist in any source"}
    if "bars" in want:
        n = conn.execute(
            "SELECT COUNT(*), COUNT(DISTINCT symbol) FROM daily_bars "
            "WHERE session>=? AND session<=?", (start, end)).fetchone()
        out["bars"] = {"rows": n[0], "distinct_symbols": n[1],
                       "basis": "raw unadjusted official bhavcopy; verified "
                                "corporate-action coverage per adjustment_factor"}
    if "tri" in want:
        t = conn.execute(
            "SELECT COUNT(*), MIN(session), MAX(session) FROM benchmark_bars "
            "WHERE index_code='NIFTY50_TRI' AND session>=? AND session<=?",
            (start, end)).fetchone()
        out["tri"] = {"rows": t[0], "first": t[1], "last": t[2],
                      "basis": "official total-return index (dividends reinvested)"}
    if "fees" in want:
        from quantplus_intelligence.research_v3 import economics as E
        out["fees"] = {
            "schedules": [s["id"] for s in E.SCHEDULES],
            "effective_from": [s["effective_from"] for s in E.SCHEDULES],
            "note": "exact paper-book model applies only at/after its effective "
                    "date; earlier fills carry typed SCHEDULE_UNAVAILABLE"}
    out["disclosure"] = "read-only coverage report; nothing was fetched or fabricated"
    return out

"""₹10L paper portfolio: replays the FROZEN v4 rule with a real share ledger.

- Fractions come from the exact v4 pipeline (same helpers, same op order as
  app/core/trend_core_v4.py, which is untouched). A fractional shadow-equity is
  carried alongside and asserted equal to run_core_v4().eq_curve (<1e-9) —
  any divergence aborts the run, so the ledger can never silently drift from
  the audited rule. Integer-share rounding is the ONLY delta, and it is reported.
- Integer NSE shares (floor), leftover cash drag, 0.105%/side on traded value.
- Adjusted closes (total-return approx; split timing effects disclosed).
- Zero LLM tokens. --universe nifty50|broad, --capital default 1000000.
"""
from __future__ import annotations

import json
import math
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import yfinance as yf  # noqa: E402
import pandas as pd  # noqa: E402

from app.core.trend_core import UNIVERSE as NIFTY50, INDEX_TICKER  # noqa: E402
from app.core.trend_core_v4 import (  # noqa: E402
    run_core_v4, TOP_K, MOMENTUM_LOOKBACK, bench_cagr_corrected,
    _mom60, _name_stats,
)
from app.core.trend_core import classify_trend_series, name_features  # noqa: E402
from app.core.trend_core_v3 import (  # noqa: E402
    vix_regime_series, TURNOVER_MIN_DELTA, MIN_HOLD_DAYS, BLACKOUT_DAYS,
    PORT_VOL_TARGET, ELEVATED_GROSS_CAP, TIER_CAPS, SECTOR_CAP,
    GROSS_CAP, COST_PER_SIDE,
)
from app.core.overlay import veto_fraction, breadth_pct  # noqa: E402
from app.data.broker_angel import paper_log  # noqa: E402

START = "2021-01-01"
END = "2026-10-01"
REBALANCE_DAYS = 5
CHUNK = 50


def _single(ticker: str):
    df = yf.download(ticker, start=START, end=END, interval="1d",
                     auto_adjust=True, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]
    closes = [float(x) for x in df["Close"].dropna().tolist()]
    dates = [str(d.date()) for d in df["Close"].dropna().index]
    return closes, dates


def _batch(tickers: list[str]) -> dict[str, list[float]]:
    out: dict[str, list[float]] = {}
    for i in range(0, len(tickers), CHUNK):
        chunk = tickers[i:i + CHUNK]
        try:
            df = yf.download(chunk, start=START, end=END, interval="1d",
                             auto_adjust=True, progress=False, group_by="ticker")
        except Exception as e:
            print(f"WARN: chunk {i // CHUNK} failed ({e})")
            continue
        if df is None or df.empty:
            continue
        for t in chunk:
            try:
                vals = [float(x) for x in df[t]["Close"].dropna().tolist()]
                if vals:
                    out[t] = vals
            except Exception:
                continue
    return out


def _frame_lists(df) -> tuple[list[float], list[str], dict[str, list[float]]]:
    """Closes + dates + aligned OHLC dicts on the dropna(Close) index."""
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]
    sub = df.dropna(subset=["Close"])
    closes = [float(x) for x in sub["Close"].tolist()]
    dates = [str(d.date()) for d in sub.index]
    ohlc = {k: [float(x) for x in sub[k].tolist()] for k in ("Open", "High", "Low")}
    return closes, dates, ohlc


def _single_ohlc(ticker: str):
    df = yf.download(ticker, start=START, end=END, interval="1d",
                     auto_adjust=True, progress=False)
    if df is None or df.empty:
        raise RuntimeError(f"no data for {ticker}")
    return _frame_lists(df)


def _batch_ohlc(tickers: list[str]):
    closes_map, ohlc_map = {}, {}
    for i in range(0, len(tickers), CHUNK):
        chunk = tickers[i:i + CHUNK]
        try:
            df = yf.download(chunk, start=START, end=END, interval="1d",
                             auto_adjust=True, progress=False, group_by="ticker")
        except Exception as e:
            print(f"WARN: chunk {i // CHUNK} failed ({e})")
            continue
        if df is None or df.empty:
            continue
        for t in chunk:
            try:
                sub = df[t].dropna(subset=["Close"]) if len(chunk) > 1 else df.dropna(subset=["Close"])
                vals = [float(x) for x in sub["Close"].tolist()]
                if not vals:
                    continue
                closes_map[t] = vals
                ohlc_map[t] = {k: [float(x) for x in sub[k].tolist()] for k in ("Open", "High", "Low")}
            except Exception:
                continue
    return closes_map, ohlc_map


def _pad(lst: list[float], n: int) -> list[float]:
    return (lst + [lst[-1]] * n)[:n] if lst else lst


def replay_ledger(index_closes, name_closes, vix_closes, tier, sector, capital: float,
                  env=None, dates=None, record=None,
                  membership_fn=None, membership_log=None, entry_gate_fn=None):
    """Mirror of run_core_v4 with integer-share ledger. Returns ledger + shadow check.

    env (optional, NEWW_PLAN Day 1): dict with ohlc {nm: {open,high,low} aligned
    lists}, dates [...], calendar (event_calendar.json). When given, a parallel
    env track runs: event-halved targets, circuit-lock deferred fills, per-tier
    costs. Shadow + flat ledger paths are byte-identical either way.

    dates + record (optional): when record is a list, one decision dict is
    appended per rebalance — regime/trend/breadth context, qualified/selected
    counts, VIX-gate blocks, per-name veto fractions on new entries, and every
    executed trade with price/shares/cost. Read-only instrumentation: numbers
    are identical with or without it.

    membership_fn + membership_log (optional, P0): same contract as run_core_v4
    (date_iso -> {members, pit_status, membership_hash}); UNKNOWN freezes the
    rebalance. Default None = legacy static-universe behavior.
    entry_gate_fn (optional, P3): (name, bar, date_or_None) -> True to ALLOW a new
    entry (False vetoes it, shrink-only). Default None = legacy behavior.
    """
    from app.data.environment import (
        cost_per_side, estimate_band, is_locked, event_gross_multiplier,
    )
    n = len(index_closes)
    trends = classify_trend_series(index_closes)
    feats = {nm: name_features(cs) for nm, cs in name_closes.items()}
    regimes = vix_regime_series(vix_closes) if vix_closes else ["CALM"] * n

    pos = {nm: 0.0 for nm in name_closes}
    last_change = {nm: -10 ** 9 for nm in name_closes}
    shares = {nm: 0 for nm in name_closes}
    cash = capital
    shadow = 1.0  # fractional shadow equity, must match run_core_v4 exactly
    shadow_curve: list[float] = []
    ledger_curve: list[float] = []
    cost_rupees = 0.0
    cost_frac_shadow = 0.0
    daily_rets: list[float] = []
    # --- env parallel state (only alive when env is given) ---
    pos_env = {nm: 0.0 for nm in name_closes}
    last_change_env = {nm: -10 ** 9 for nm in name_closes}
    shares_env = {nm: 0 for nm in name_closes}
    cash_env = capital
    cost_env = 0.0
    env_curve: list[float] = []
    locks_hit = 0
    event_days = 0

    for t in range(n):
        # --- shadow (exact v4 recurrence) ---
        day_ret = 0.0
        for nm, cs in name_closes.items():
            if t == 0 or pos[nm] == 0.0:
                continue
            pc, cc = cs[t - 1], cs[t]
            if pc and cc and pc > 0:
                day_ret += pos[nm] * (cc / pc - 1)
        cost_today_frac = 0.0
        # P0 PIT membership (mirrors run_core_v4; UNKNOWN freezes the rebalance).
        pit_members = None
        pit_frozen = False
        pit_hash = ""
        pit_status = "STATIC"
        if (membership_fn is not None and dates is not None and t < len(dates)
                and t % REBALANCE_DAYS == 0):
            snap = membership_fn(dates[t])
            pit_hash = str(snap.get("membership_hash", ""))
            pit_status = str(snap.get("pit_status", "UNKNOWN"))
            if pit_status == "UNKNOWN":
                pit_frozen = True
            else:
                pit_members = set(snap.get("members", ()))
        if membership_log is not None and t % REBALANCE_DAYS == 0:
            membership_log.append({
                "bar": t, "date": dates[t] if dates and t < len(dates) else f"bar-{t}",
                "pit_status": pit_status, "membership_hash": pit_hash,
                "n_eligible": len(pit_members) if pit_members is not None else len(name_closes),
                "frozen": pit_frozen})
        if t % REBALANCE_DAYS == 0 and not pit_frozen:
            trend = trends[t]
            regime = regimes[t] if t < len(regimes) else "CALM"
            breadth = breadth_pct(name_closes, t)
            pre_pos = dict(pos)  # decision-audit snapshot (read-only)
            ranked = []
            stressed_blocked = []
            for nm, cs in name_closes.items():
                if pit_members is not None and nm not in pit_members:
                    continue  # not a member at this rebalance — invisible
                if trend != "UP" or t >= len(cs):
                    continue
                f = feats[nm][t]
                if not (f["mom_ok"] and f["vol_target_size"] > 0):
                    continue
                if regime == "STRESSED" and pos[nm] == 0.0:
                    stressed_blocked.append(nm)
                    continue
                if pos[nm] == 0.0 and entry_gate_fn is not None:
                    date_t = dates[t] if dates is not None and t < len(dates) else None
                    if entry_gate_fn(nm, t, date_t) is False:
                        continue  # P3 event-blackout entry veto (shrink-only)
                ranked.append((_mom60(cs, t), nm))
            ranked.sort(key=lambda x: x[0], reverse=True)
            selected = {nm for _, nm in ranked[:TOP_K]}
            targets = {}
            vetoes = {}  # new-entry veto fractions, for the decision audit
            for nm, cs in name_closes.items():
                target = 0.0
                if pit_members is not None and nm not in pit_members:
                    targets[nm] = 0.0  # exited names liquidate via target 0
                    continue
                if nm in selected:
                    f = feats[nm][t]
                    cap = TIER_CAPS.get(tier.get(nm, "nifty50"), 0.10)
                    target = min(f["vol_target_size"], cap)
                    if pos[nm] == 0.0:
                        r5, dh = _name_stats(cs, t)
                        v = veto_fraction(regime, breadth, r5, dh)
                        vetoes[nm] = v
                        target *= 1.0 - v
                targets[nm] = target
            if sector:
                by_sec: dict[str, list[str]] = {}
                for nm in targets:
                    by_sec.setdefault(sector.get(nm, "UNKNOWN"), []).append(nm)
                for names in by_sec.values():
                    gs = sum(targets[nm] for nm in names)
                    if gs > SECTOR_CAP + 1e-12:
                        s = SECTOR_CAP / gs
                        for nm in names:
                            targets[nm] *= s
            cap_now = ELEVATED_GROSS_CAP if regime == "ELEVATED" and trend == "UP" else GROSS_CAP
            gross = sum(targets.values())
            if gross > cap_now + 1e-12:
                s = cap_now / gross
                targets = {k: v * s for k, v in targets.items()}
            if len(daily_rets) >= 21:
                tail = daily_rets[-20:]
                mu = sum(tail) / len(tail)
                var = sum((r - mu) ** 2 for r in tail) / 19
                pv = math.sqrt(var * 252)
                if pv > PORT_VOL_TARGET + 1e-9 and pv > 0:
                    s = PORT_VOL_TARGET / pv
                    targets = {k: v * s for k, v in targets.items()}
            for nm, target in targets.items():
                if t - last_change[nm] < MIN_HOLD_DAYS and abs(target - pos[nm]) > 1e-12:
                    target = pos[nm]
                if abs(target - pos[nm]) <= TURNOVER_MIN_DELTA + 1e-12:
                    continue
                cost_today_frac += COST_PER_SIDE * abs(target - pos[nm])
                last_change[nm] = t
                pos[nm] = target
        shadow *= 1.0 + day_ret - cost_today_frac
        cost_frac_shadow += cost_today_frac
        shadow_curve.append(shadow)
        daily_rets.append(day_ret - cost_today_frac)

        # --- ledger (integer shares at t's close) ---
        if t % REBALANCE_DAYS == 0:
            book = cash + sum(shares[nm] * (name_closes[nm][t] if t < len(name_closes[nm]) else 0.0)
                              for nm in name_closes)
            rebal_cost = 0.0
            trades = []
            for nm, cs in name_closes.items():
                px = cs[t] if t < len(cs) and cs[t] > 0 else 0.0
                if px <= 0:
                    continue
                want_val = pos[nm] * book
                want_sh = int(want_val // px)
                d_sh = want_sh - shares[nm]
                if d_sh != 0:
                    cost_leg = COST_PER_SIDE * abs(d_sh) * px
                    cash += -d_sh * px - cost_leg
                    cost_rupees += cost_leg
                    rebal_cost += cost_leg
                    trades.append({"ticker": nm,
                                   "side": "buy" if d_sh > 0 else "sell",
                                   "shares_before": shares[nm], "shares_after": want_sh,
                                   "price": round(px, 2),
                                   "traded_value": round(abs(d_sh) * px, 2),
                                   "cost": round(cost_leg, 2),
                                   "target_pct": round(pos[nm], 4)})
                    shares[nm] = want_sh
            if record is not None:
                date_s = dates[t] if dates and t < len(dates) else f"bar-{t}"
                record.append({
                    "date": date_s, "trend": trend, "regime": regime,
                    "breadth": round(breadth, 3),
                    "n_qualified": len(ranked) + len(stressed_blocked),
                    "n_selected": len(selected),
                    "n_held": sum(1 for v in pos.values() if v > 0),
                    "stressed_blocked": sorted(stressed_blocked),
                    "vetoes": {k: round(v, 4) for k, v in sorted(vetoes.items()) if v > 0},
                    "veto_blocked": sorted(nm for nm, v in vetoes.items()
                                           if v >= 1.0 and pos.get(nm, 0.0) == 0.0),
                    "gross": round(sum(pos.values()), 4),
                    "rebalance_cost": round(rebal_cost, 2),
                    "trades": trades,
                })
        ledger_curve.append(cash + sum(
            shares[nm] * (name_closes[nm][t] if t < len(name_closes[nm]) else 0.0)
            for nm in name_closes))

        # --- env track: event-halved targets, lock-deferred fills, tiered costs ---
        if env is not None:
            ohlc, dates_e, calendar = env["ohlc"], env["dates"], env["calendar"]
            mult = 1.0
            if t % REBALANCE_DAYS == 0:
                mult = event_gross_multiplier(dates_e[t] if t < len(dates_e) else "", calendar)
                if mult < 1.0:
                    event_days += 1
                book_env = cash_env + sum(
                    shares_env[nm] * (name_closes[nm][t] if t < len(name_closes[nm]) else 0.0)
                    for nm in name_closes)
                for nm, cs in name_closes.items():
                    px = cs[t] if t < len(cs) and cs[t] > 0 else 0.0
                    if px <= 0:
                        continue
                    want = pos[nm] * mult * book_env  # shadow decision, event-scaled
                    # circuit lock: pinned bar + frozen range => no fill, carry
                    try:
                        o, h, l = (ohlc[nm][k][t] for k in ("open", "high", "low"))
                        band = estimate_band(cs[max(0, t - 20):t + 1])
                        if is_locked(o, h, l, px, band):
                            locks_hit += 1
                            continue
                    except (KeyError, IndexError, TypeError):
                        pass  # no OHLC => treat as tradable (disclosed gap)
                    want_sh = int(want // px)
                    # env turnover/min-hold on env state (dust relative to book)
                    if t - last_change_env[nm] < MIN_HOLD_DAYS and want_sh != shares_env[nm]:
                        want_sh = shares_env[nm]
                    if abs(want_sh - shares_env[nm]) * px <= TURNOVER_MIN_DELTA * book_env + 1e-9:
                        want_sh = shares_env[nm]
                    d_sh = want_sh - shares_env[nm]
                    if d_sh != 0:
                        cps = cost_per_side(tier.get(nm, "nifty50"))
                        cost_leg = cps * abs(d_sh) * px
                        cash_env += -d_sh * px - cost_leg
                        cost_env += cost_leg
                        shares_env[nm] = want_sh
                        last_change_env[nm] = t
            env_curve.append(cash_env + sum(
                shares_env[nm] * (name_closes[nm][t] if t < len(name_closes[nm]) else 0.0)
                for nm in name_closes))
    out = {"shadow_curve": shadow_curve, "ledger_curve": ledger_curve,
           "shares": shares, "cash": cash, "cost_rupees": cost_rupees,
           "cost_frac_shadow": cost_frac_shadow}
    if env is not None:
        out.update({"env_curve": env_curve, "shares_env": shares_env,
                    "cash_env": cash_env, "cost_env": cost_env,
                    "locks_hit": locks_hit, "event_days": event_days})
    return out


def main(which: str, capital: float, honest_env: bool = False,
         token_rate: float = 9.0, out_tag: str | None = None,
         pit: bool = False) -> None:
    # Output tag derives from capital (10L for the default 1,000,000) so a run at
    # a different capital never clobbers the canonical paper_10L_* artifacts.
    # --pit runs are CORRECTNESS_REISSUEs: same frozen rule, only the universe
    # source changes (static -> per-rebalance PIT, non-strict disclosed). They
    # MUST use --out-tag (e.g. 10L-PIT) so canonical artifacts are never clobbered.
    tag = out_tag or f"{int(round(capital / 100000.0))}L"
    if pit and out_tag is None:
        raise ValueError("--pit reissues require --out-tag (e.g. 10L-PIT): "
                         "canonical paper_10L_* artifacts must never be overwritten")
    membership_fn = None
    membership_log: list = []
    pit_meta: dict = {}
    if pit:
        from app.data import pit_membership as PM
        universe_id = "nifty50" if which == "nifty50" else "nifty500"
        membership_fn = lambda d: PM.membership_at(universe_id, d, strict=False)
        pit_meta = {"mode": "CORRECTNESS_REISSUE (not a new strategy)",
                    "universe_id": universe_id, "strict": False,
                    "note": "non-strict with disclosure (Amendment-1: strict degenerates)"}
    from app.data.environment import load_calendar, token_spend_rupees, total_inference_tokens
    calendar = load_calendar() if honest_env else {}
    ohlc_all: dict[str, dict[str, list[float]]] = {}
    if honest_env:
        idx, dates, _ = _single_ohlc(INDEX_TICKER)
    else:
        idx, dates = _single(INDEX_TICKER)
    n = len(idx)
    try:
        vix = _single("^INDIAVIX")[0]
        vix = (vix + [vix[-1]] * n)[:n] if len(vix) != n else vix
    except Exception:
        vix = None
    tier, sector, excluded = {}, {}, []
    if which == "broad":
        with open("data/nifty500.txt", encoding="utf-8-sig") as f:
            want = [l.strip().upper() for l in f if l.strip()]
        with open("data/nifty500_sectors.json", encoding="utf-8-sig") as f:
            secmap = json.load(f)
        if honest_env:
            got, got_ohlc = _batch_ohlc(sorted(set(want)))
        else:
            got = _batch(sorted(set(want)))
            got_ohlc = {}
        names = {}
        for t, cs in got.items():
            if not cs or len(cs) < n * 0.9:
                excluded.append(t)
                continue
            names[t] = (cs + [cs[-1]] * n)[:n] if len(cs) != n else cs
            if honest_env and t in got_ohlc:
                o = got_ohlc[t]
                m = min(len(o["Open"]), len(cs))
                ohlc_all[t] = {k: _pad(v[:m], n) for k, v in o.items()}
        for t in want:
            if t not in got and t not in excluded:
                excluded.append(t)
        tier = {t: ("nifty50" if t in NIFTY50 else "nifty500") for t in names}
        sector = {t: secmap.get(t, "UNKNOWN") for t in names}
    else:
        names = {}
        for t in NIFTY50:
            try:
                if honest_env:
                    cs, _, o = _single_ohlc(t)
                    ohlc_all[t] = {k: _pad(v, n) for k, v in o.items()}
                else:
                    cs, _ = _single(t)
            except Exception:
                excluded.append(t)
                continue
            if not cs:
                excluded.append(t)
                continue
            names[t] = (cs + [cs[-1]] * n)[:n] if len(cs) != n else cs
        tier = {t: "nifty50" for t in names}

    # Reference: frozen v4 on identical aligned inputs (same membership mode,
    # so the ledger can never silently drift from the audited rule).
    ref = run_core_v4(idx, names, vix_closes=vix, tier=tier, sector=sector,
                      dates=dates if pit else None,
                      membership_fn=membership_fn,
                      membership_log=membership_log if pit else None)
    env = {"ohlc": ohlc_all, "dates": dates, "calendar": calendar} if honest_env else None
    decisions: list = []  # per-rebalance decision audit (closes the per-trade persistence gap)
    ledger_log: list = []
    led = replay_ledger(idx, names, vix, tier, sector, capital, env=env,
                        dates=dates, record=decisions,
                        membership_fn=membership_fn,
                        membership_log=ledger_log if pit else None)
    worst = max(abs(a - b) for a, b in zip(ref.eq_curve, led["shadow_curve"]))
    assert worst < 1e-9, f"ledger diverged from frozen v4: {worst}"
    print(f"reconciliation vs frozen v4: max diff {worst:.2e} (integer rounding is the only delta)")

    curve = led["ledger_curve"]
    final = curve[-1]
    profit = final - capital
    years = n / 252.0
    cagr = (final / capital) ** (1 / years) - 1
    peak, mdd = curve[0], 0.0
    for v in curve:
        peak = max(peak, v)
        mdd = max(mdd, 1 - v / peak)
    yearly = {}
    for t in range(n):
        yr = dates[t][:4]
        y = yearly.setdefault(yr, {"s": None, "e": curve[t]})
        if y["s"] is None:
            y["s"] = curve[t - 1] if t > 0 else capital
        y["e"] = curve[t]
    out = {
        "rule": ("frozen v4 + baked veto + per-rebalance PIT membership "
                 "(CORRECTNESS_REISSUE — same rule, bias-corrected universe)"
                 if pit else "frozen v4 + baked veto (integer-share ledger)"),
        "universe": which, "capital": capital, "n_names": len(names),
        "n_excluded": len(excluded),
        "initial": round(capital, 2), "final": round(final, 2),
        "profit": round(profit, 2),
        "profit_pct": round(profit / capital * 100, 2),
        "cagr_pct": round(cagr * 100, 2),
        "max_drawdown_pct": round(mdd * 100, 2),
        "costs_rupees": round(led["cost_rupees"], 2),
        "cash_leftover": round(led["cash"], 2),
        "n_holdings_end": sum(1 for s in led["shares"].values() if s > 0),
        "yearly": {yr: {"start": round(v["s"], 2), "end": round(v["e"], 2),
                        "pnl": round(v["e"] - v["s"], 2)} for yr, v in yearly.items()},
        "top_holdings_end": sorted(
            ((nm, s, round(s * names[nm][-1], 2)) for nm, s in led["shares"].items() if s > 0),
            key=lambda x: -x[2])[:10],
        "approx_note": "adjusted closes; integer shares; split-timing effects approx",
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    path = os.path.join("data", f"paper_{tag}_{which}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    paper_log({nm: s for nm, s in led["shares"].items() if s > 0})
    dpath = os.path.join("data", f"paper_{tag}_{which}_decisions.json")
    with open(dpath, "w", encoding="utf-8") as f:
        json.dump(decisions, f, indent=1)
    n_trades = sum(len(d["trades"]) for d in decisions)
    n_buys = sum(1 for d in decisions for t in d["trades"] if t["side"] == "buy")
    audit = {
        "n_rebalances": len(decisions),
        "n_rebalances_with_trades": sum(1 for d in decisions if d["trades"]),
        "n_trades": n_trades, "n_buys": n_buys, "n_sells": n_trades - n_buys,
        "total_veto_blocks": sum(len(d["veto_blocked"]) for d in decisions),
        "total_stressed_blocks": sum(len(d["stressed_blocked"]) for d in decisions),
        "rebalance_cost_check": round(sum(d["rebalance_cost"] for d in decisions), 2),
    }
    out["decision_audit"] = audit
    out["decisions_file"] = dpath
    if pit:
        from app.data import pit_membership as PM
        frozen = sum(1 for e in ledger_log if e["frozen"])
        statuses = {}
        for e in ledger_log:
            statuses[e["pit_status"]] = statuses.get(e["pit_status"], 0) + 1
        out["pit_reissue"] = {
            **pit_meta,
            "membership_source_version": PM.PU.source_version(),
            "n_frozen_unknown": frozen,
            "pit_status_counts": statuses,
            "first_hash": ledger_log[0]["membership_hash"] if ledger_log else "",
            "last_hash": ledger_log[-1]["membership_hash"] if ledger_log else "",
        }
        lpath = os.path.join("data", f"paper_{tag}_{which}_pitlog.json")
        with open(lpath, "w", encoding="utf-8") as f:
            json.dump(ledger_log, f, indent=1)
        out["pit_log_file"] = lpath
        print("pit:", json.dumps(out["pit_reissue"], indent=2))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    print(json.dumps({k: v for k, v in out.items() if k not in ("top_holdings_end", "yearly")}, indent=2))
    print("yearly P&L (Rs.):", json.dumps({yr: v["pnl"] for yr, v in out["yearly"].items()}))
    print("report:", path)
    print("decisions:", dpath, json.dumps(audit))

    if honest_env:
        ecurve = led["env_curve"]
        efinal = ecurve[-1]
        epeak, emdd = ecurve[0], 0.0
        for v in ecurve:
            epeak = max(epeak, v)
            emdd = max(emdd, 1 - v / epeak)
        tokens = total_inference_tokens()
        spend = token_spend_rupees(tokens, token_rate)
        eout = {
            "rule": "frozen v4 decisions under honest environment (NEWW_PLAN Day 1)",
            "universe": which, "capital": capital,
            "env_final": round(efinal, 2),
            "env_profit": round(efinal - capital, 2),
            "env_cagr_pct": round(((efinal / capital) ** (1 / (n / 252.0)) - 1) * 100, 2),
            "env_max_drawdown_pct": round(emdd * 100, 2),
            "env_costs_rupees": round(led["cost_env"], 2),
            "flat_costs_rupees": round(led["cost_rupees"], 2),
            "locks_hit": led["locks_hit"],
            "event_halved_rebalances": led["event_days"],
            "inference_tokens_ledger": tokens,
            "token_rate_rs_per_1k_ASSUMED": token_rate,
            "inference_spend_rupees": round(spend, 2),
            "env_profit_net_of_inference": round(efinal - capital - spend, 2),
            "prereg": "data/prereg_day1_environment.md",
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        epath = os.path.join("data", f"paper_{tag}_{which}_env.json")
        with open(epath, "w", encoding="utf-8") as f:
            json.dump(eout, f, indent=2)
        print(json.dumps(eout, indent=2))
        print("env report:", epath)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--universe", choices=["nifty50", "broad"], default="nifty50")
    ap.add_argument("--capital", type=float, default=1000000.0)
    ap.add_argument("--honest-env", action="store_true",
                    help="NEWW_PLAN Day 1: segment costs, circuit locks, event halving, token deduction")
    ap.add_argument("--token-rate", type=float, default=9.0,
                    help="ASSUMED Rs per 1K tokens (labeled assumption, not a quote)")
    ap.add_argument("--out-tag", default=None,
                    help="override output tag (default: derived from --capital, e.g. 50L)")
    ap.add_argument("--pit", action="store_true",
                    help="CORRECTNESS_REISSUE: per-rebalance PIT membership (requires --out-tag)")
    a = ap.parse_args()
    main(a.universe, a.capital, honest_env=a.honest_env, token_rate=a.token_rate,
         out_tag=a.out_tag, pit=a.pit)

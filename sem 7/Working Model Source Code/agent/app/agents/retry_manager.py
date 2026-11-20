"""Sandboxed full-manager retry (Day 4 T4.2, prereg data/prereg_overlay_retry.md).

Isolated by construction: separate module, separate sid namespace (`cfg|retry`),
separate `retry_*` checkpoints so retry never reuses frozen decisions.
Same PIT + cost + guardrail discipline (all code guardrails still apply after
reasoning in trader_risk.run_pm).

m10 retry synthesis (full retry as requested): weight-of-evidence PLUS
- explicit base-rate (index trend + breadth prior, not just analyst tally)
- falsifier checklist (name the observation that would kill the thesis)
- 5-tier rating output mapped to Thesis direction (Buy/Overweight=>long,
  Sell/Underweight=>short, Hold/REVIEW=>flat)
"""
from __future__ import annotations

import json
from datetime import datetime

from app import schemas as S


def run_manager_retry(reports: list[S.AnalystReport], turns: list[S.DebateTurn],
                      session_id: str, breadth_prior: str = "") -> S.Thesis:
    from app.agents._util import call_json
    digest = "\n".join(f"[{r.agent} conf={r.confidence:.2f}] {r.summary}" for r in reports)
    log = "\n".join(f"{t.stance}: {t.argument} (d={t.confidence_delta:+.2f})" for t in turns)
    system = ("You are the Research Manager (retry m10). Synthesize ONE thesis by weight of evidence "
              "PLUS base-rate. Steps: (1) tally analyst confidences and bull/bear/neutral counts; "
              "abstaining analysts are NEUTRAL. (2) State the market base-rate prior: "
              f"{breadth_prior or 'index trend + breadth as given, else neutral'}. "
              "A long against a DOWN index trend needs exceptional evidence. "
              "(3) State one falsifier: the concrete observation that would kill your thesis. "
              "(4) Open with a 5-tier rating line 'Rating: Buy|Overweight|Hold|Underweight|Sell'. "
              "Buy/Overweight=>long, Sell/Underweight=>short, Hold=>flat. "
              "If genuinely ambiguous (mean conf<0.45 or evenly split) choose Hold/flat — "
              "no-edge honesty is required, never forced direction. "
              "Classify mechanism_type exactly one of MOMENTUM_CONTINUATION/MEAN_REVERSION/EVENT_DRIVEN/OTHER. "
              "Return ONLY Thesis JSON: {direction, conviction, key_evidence[], key_risks[], mechanism_type}.")
    out = call_json("research_manager", session_id, system,
                    f"analysts:\n{digest}\ndebate:\n{log}\nbase_rate:\n{breadth_prior}",
                    S.Thesis)
    return out


def run_session_retry(session_id: str, instrument: str, as_of: datetime,
                      interval: str = "1d", portfolio: dict | None = None) -> S.FinalDecision:
    """Retry session: frozen analysts/debate/devil/trader/risk/PM, only manager synthesis is m10.

    Checkpoints namespaced `retry_*` so frozen and retry sessions sharing a sid
    base never collide (sid itself is also namespaced `cfg|retry` in api/v1.py).
    """
    import concurrent.futures
    from app.agents import analysts as A, debate as D, manager as M, trader_risk as T
    from app.agents.technical import run as run_tech
    from app.agents.events_analyst import run_events
    from app.agents.graph import _load_ckpt, _save_ckpt, log_event, record_thesis
    from app.data.regime import regime_at, market_trend_at
    from app.db import sqlite_conn
    from app.log import log as qlog
    from app.config import settings as _settings

    def _loads_reports(p: str):
        return {k: S.AnalystReport(**v) for k, v in json.loads(p).items()}

    conn = sqlite_conn()
    conn.execute("UPDATE sessions SET status=? WHERE id=?", ("running", session_id))
    conn.commit()

    portfolio_block = ""
    if portfolio:
        from app.portfolio import PortfolioContext
        portfolio_block = PortfolioContext.model_validate(portfolio).render(instrument)

    hit = _load_ckpt(session_id, "retry_analysts")
    if hit is not None:
        reports = _loads_reports(hit)
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:
            fut = {
                "technical": ex.submit(run_tech, instrument, as_of, interval, session_id),
                "fundamentals": ex.submit(A.run_fundamentals, instrument, as_of, interval, session_id),
                "news": ex.submit(A.run_news, instrument, as_of, session_id),
                "macro": ex.submit(A.run_macro, instrument, as_of, interval, session_id),
                "events": ex.submit(run_events, instrument, as_of, session_id),
            }
            reports = {name: f.result() for name, f in fut.items()}
        _save_ckpt(session_id, "retry_analysts",
                   json.dumps({k: v.model_dump(mode="json") for k, v in reports.items()}))
    rep_list = [reports[k] for k in ("technical", "fundamentals", "news", "macro", "events")]

    hit = _load_ckpt(session_id, "retry_debate")
    if hit is not None:
        turns = [S.DebateTurn(**v) for v in json.loads(hit)]
    else:
        turns = D.run_debate(rep_list, session_id)
        _save_ckpt(session_id, "retry_debate", json.dumps([v.model_dump(mode="json") for v in turns]))

    hit = _load_ckpt(session_id, "retry_thesis")
    if hit is not None:
        thesis = S.Thesis.model_validate_json(hit)
    else:
        thesis = run_manager_retry(rep_list, turns, session_id,
                                   breadth_prior=f"index_trend={market_trend_at(as_of)}")
        _save_ckpt(session_id, "retry_thesis", thesis.model_dump_json())

    # Devil / version / trader / risk / PM: same frozen logic + same guardrails.
    hit = _load_ckpt(session_id, "retry_challenge")
    if hit is not None:
        challenge = S.Challenge.model_validate_json(hit)
    else:
        from app.agents.graph import _load_ckpt as _lc
        import json as _j
        exh_hit = _lc(session_id, "exhaustion")
        exh = None
        if exh_hit is not None:
            d = _j.loads(exh_hit)
            exh = S.RawExhaustionSignals(flush_flag=bool(d["flush_flag"]),
                                         blowoff_flag=bool(d["blowoff_flag"]),
                                         ret_5d_pct=float(d["ret_5d_pct"]),
                                         dist_from_20d_low_pct=float(d["dist_from_20d_low_pct"]),
                                         dist_from_20d_high_pct=float(d["dist_from_20d_high_pct"]))
        challenge = M.run_devils_advocate(thesis, rep_list, session_id, exh)
        _save_ckpt(session_id, "retry_challenge", challenge.model_dump_json())

    body = json.dumps({"session_id": session_id, "thesis": thesis.model_dump(mode="json"),
                       "challenge": challenge.model_dump(mode="json"), "retry": True})
    row = conn.execute("SELECT version FROM theses WHERE instrument=? AND body LIKE ? ORDER BY version DESC LIMIT 1",
                       (instrument, f'%"session_id": "{session_id}"%')).fetchone()
    version = row[0] if row else record_thesis(instrument, challenge.status.value, body, session_id)

    proposal = T.run_trader(instrument, thesis, challenge, as_of, session_id,
                            portfolio_block=portfolio_block)
    verdicts = T.run_risk_panel(proposal, thesis, challenge, session_id,
                                portfolio_block=portfolio_block)
    decision = T.run_pm(instrument, thesis, challenge, proposal, verdicts, version,
                        session_id, regime=regime_at(as_of), market_trend=market_trend_at(as_of),
                        direction_policy=_settings.DIRECTION_POLICY,
                        portfolio_block=portfolio_block)
    _save_ckpt(session_id, "retry_decision", decision.model_dump_json())
    conn.execute("UPDATE sessions SET status=?, decision=? WHERE id=?",
                 ("done", decision.model_dump_json(), session_id))
    conn.commit()
    log_event(session_id, "session", "portfolio_manager", "done", f"v{version}:retry")
    qlog(session_id, "session", "portfolio_manager", "done",
         action=decision.action, size=decision.size, thesis_version=version)
    return decision

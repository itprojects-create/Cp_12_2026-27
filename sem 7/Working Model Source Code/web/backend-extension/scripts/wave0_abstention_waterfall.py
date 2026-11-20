"""W0.3 — Abstention waterfall for recorded forecast cards (read-only, offline).

For every card in the V2 ledger backup this reconstructs, per
(symbol, horizon, as_of, model_version):

  1. data eligibility        — stored extras `sources` per optional feed
  2. per-voter status        — stored extras `votes` (p, abstain, reason)
  3. aggregation active count— number of voters with p != None
  4. final abstention + gate reason — card.abstain / abstain_reason

It reconciles the recorded cohort answer-rates (e.g. 12/100 at 5D, 11/100 at 20D)
without assuming anything about which batch produced them, and writes
reports/alpha_v3_1/abstention_waterfall.json. Read-only; no settlement, no backfill.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

BACKUP = Path(r"D:\Quant-Plus\reports\alpha_v3_1\backups\forecast_ledger_w0_backup.sqlite3")
REPORTS = Path(r"D:\Quant-Plus\reports\alpha_v3_1")

VOTERS = ("technical", "relative", "events", "news", "flows",
          "generalist_blind", "momentum", "reversal")


def main() -> int:
    conn = sqlite3.connect(f"file:{BACKUP}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT card_id, symbol, as_of, horizon, payload, settled_at, outcome "
            "FROM forecast_ledger ORDER BY seq").fetchall()
        extras = {cid: json.loads(payload) for cid, payload in
                  conn.execute("SELECT card_id, payload FROM forecast_extras").fetchall()}
    finally:
        conn.close()

    cards = []
    vote_failures: Counter = Counter()
    source_states: Counter = Counter()
    horizon_stats: dict[int, dict] = {}
    for card_id, symbol, as_of, horizon, payload, settled_at, outcome_raw in rows:
        card = json.loads(payload)
        if card.get("model_version") != "forecast-v2-horizon-gated":
            source_states[f"model_version:{card.get('model_version')}"] += 1
        ex = extras.get(card_id, {})
        votes = {v.get("forecaster"): v for v in ex.get("votes", [])}
        sources = ex.get("sources", {})
        for name, state in sources.items():
            source_states[f"{name}:{'available' if state == 'available' else 'unavailable'}"] += 1
        active, voted_out, abstained_out = [], [], []
        for name in VOTERS:
            v = votes.get(name)
            if v is None:
                vote_failures[f"{name}:no_vote_recorded"] += 1
                continue
            if v.get("abstain") or v.get("p") is None:
                reason = (v.get("reason") or "abstain").split(":")[0][:60]
                abstained_out.append({"voter": name, "reason": reason})
                vote_failures[f"{name}:{reason[:40]}"] += 1
            else:
                active.append(v["p"])
                voted_out.append(name)
        answerable = not card.get("abstain")
        rec = {
            "card_id": card_id, "symbol": symbol, "as_of": as_of[:10], "horizon": horizon,
            "model_version": card.get("model_version"), "abstain": card.get("abstain"),
            "abstain_reason": card.get("abstain_reason", ""),
            "p_outperform": card.get("p_outperform"),
            "recorded_at": None, "sources": sources,
            "active_voters": voted_out, "active_count": len(active),
            "abstaining_voters": abstained_out,
            "settled": settled_at is not None,
        }
        cards.append(rec)
        stats = horizon_stats.setdefault(horizon, Counter())
        stats["cards"] += 1
        stats["answerable"] += int(answerable)
        stats["abstained_cards"] += int(not answerable)
        stats["settled"] += int(settled_at is not None)
        if answerable and outcome_raw:
            stats["scored"] += 1

    # cohort reconciliation: rolling 100-card windows per horizon, newest first
    reconciliation = {}
    for horizon, stats in horizon_stats.items():
        seq = [c for c in cards if c["horizon"] == horizon]
        recent = seq[-100:]
        reconciliation[str(horizon)] = {
            "total_cards": stats["cards"], "answerable": stats["answerable"],
            "abstained": stats["abstained_cards"], "settled": stats["settled"],
            "scored": stats["scored"],
            "recent_100_answerable": sum(1 for c in recent if not c["abstain"]),
            "recent_100_n": len(recent),
        }

    water = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "forecast_ledger_w0_backup.sqlite3 (read-only)",
        "note": "Per-voter status comes from forecast_extras recorded at lock time; "
                "cards without extras cannot be decomposed further.",
        "cards_missing_extras": sum(1 for c in cards
                                    if not c["active_voters"] and not c["abstaining_voters"]),
        "source_states": dict(source_states),
        "voter_failure_reasons": dict(vote_failures),
        "horizon_reconciliation": reconciliation,
        "cards": cards,
    }
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / "abstention_waterfall.json").write_text(
        json.dumps(water, indent=2, default=str), encoding="utf-8")
    summary = {k: {kk: vv for kk, vv in v.items()} for k, v in reconciliation.items()}
    print(json.dumps({"source_states": dict(source_states),
                      "voter_failure_reasons": dict(vote_failures.most_common(12)),
                      "horizon_reconciliation": summary,
                      "cards_missing_extras": water["cards_missing_extras"]},
                     indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

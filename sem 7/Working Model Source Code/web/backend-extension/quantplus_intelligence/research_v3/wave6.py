"""Wave 6 read-only adapter: inspect the forward stream without mutating it.

Mirrors the wave5 adapter conventions: no application imports, no mutation,
no broker surface.  Every function returns plain JSON-safe dictionaries.
"""
from __future__ import annotations

from pathlib import Path

from quantplus_intelligence.research_v3.forward.ledger import ForwardLedger
from quantplus_intelligence.research_v3.forward.worker import ForwardWorker


def protocol_browse(ledger: ForwardLedger) -> list[dict]:
    """Every sealed preregistration with its content hash and seal order."""
    out = []
    for record in ledger.records():
        if record["event_type"] != "PREREGISTRATION_SEALED":
            continue
        payload = record["payload"]
        out.append({
            "seq": record["seq"],
            "stream_id": payload.get("stream_id"),
            "experiment_id": payload.get("experiment_id"),
            "preregistered_at_utc": payload.get("preregistered_at_utc"),
            "preregistered_at_ist": payload.get("preregistered_at_ist"),
            "strategy_family": payload.get("strategy_family"),
            "strategy_spec_hash": payload.get("strategy_spec_hash"),
            "model_version": payload.get("model_version"),
            "broker_plan": payload.get("broker_plan"),
            "operator_approval": payload.get("operator_approval"),
            "event_hash": record["record_hash"],
        })
    return out


def stream_status(ledger: ForwardLedger, stream_id: str) -> dict:
    counts: dict[str, int] = {}
    first_signal_seq: int | None = None
    seal_seq: int | None = None
    for record in ledger.records():
        if record["payload"].get("stream_id") != stream_id:
            continue
        counts[record["event_type"]] = counts.get(record["event_type"], 0) + 1
        if record["event_type"] == "PREREGISTRATION_SEALED" and seal_seq is None:
            seal_seq = record["seq"]
        elif seal_seq is not None and first_signal_seq is None:
            first_signal_seq = record["seq"]
    ok, reason = ledger.verify_chain()
    return {
        "stream_id": stream_id,
        "sealed_seq": seal_seq,
        "first_post_seal_seq": first_signal_seq,
        "sealed_before_first_signal": (
            seal_seq is not None and first_signal_seq is not None
            and seal_seq < first_signal_seq) or
            (seal_seq is not None and first_signal_seq is None),
        "event_counts": counts,
        "chain_intact": ok,
        "chain_reason": reason,
        "head_hash": ledger.head(),
    }


def book_valuation_summary(ledger: ForwardLedger, stream_id: str) -> dict:
    """Last observed marks and cash-flow totals straight from ledger evidence."""
    marks = [e["payload"] for e in ledger.stream_records(stream_id, "VALUATION_MARK")]
    flows = [e["payload"] for e in ledger.stream_records(stream_id, "CASH_FLOW")]
    fills = [e["payload"] for e in ledger.stream_records(stream_id, "FILL_EVENT")]
    fees = [e["payload"] for e in ledger.stream_records(stream_id, "FEE_EVENT")]
    return {
        "stream_id": stream_id,
        "n_valuation_marks": len(marks),
        "n_cash_flows": len(flows),
        "n_fill_events": len(fills),
        "n_fee_events": len(fees),
        "fees_paid_paise": sum(f["total_paise"] for f in fees),
        "cash_flows_net_paise": sum(f["amount_paise"] for f in flows),
        "latest_marks": {m["symbol"]: {"mark_paise": m["mark_paise"],
                                       "session": m.get("session_date"),
                                       "source": m["mark_source"]}
                         for m in marks if m["status"] == "MARK_OBSERVED"},
    }


def worker_summary(worker: ForwardWorker) -> dict:
    return worker.status()


def health_endpoint(ledger: ForwardLedger, worker: ForwardWorker | None,
                    *, now_utc: str) -> dict:
    """JSON-safe `/health` payload for the later-approved local service.

    This function is read-only. Merely calling it does not claim durable hosting
    or notification delivery.
    """
    chain_ok, chain_reason = ledger.verify_chain()
    watchdog = (worker.watchdog(now_utc) if worker else
                {"status": "WORKER_NOT_RUNNING", "healthy": False})
    readiness = (worker.delivery_readiness() if worker else {
        "worker_durable": False, "worker_label": "WORKER_NOT_DURABLE",
        "webhook": {"status": "WEBHOOK_NOT_CONFIGURED", "delivered": False}})
    return {
        "service": "quantplus-v3.1-forward",
        "status": "healthy" if chain_ok else "degraded",
        "ledger": {"chain_intact": chain_ok, "reason": chain_reason,
                   "head_hash": ledger.head()},
        "worker": watchdog,
        "readiness": readiness,
        "live_broker_surface": False,
        "authority": "RESEARCH_ONLY_PAPER_ONLY",
    }

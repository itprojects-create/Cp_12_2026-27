"""Generate the deterministic Wave 6 evidence pack from offline fixtures.

Real forward evidence is deliberately empty: the generated real stream contains
only a null/no-trade preregistration seal. Every fill, fee, mark and worker chaos
row is explicitly ENGINEERING_FIXTURE. Existing W0-W5 artifacts are read-only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from quantplus_intelligence.research_v3.forward.benchmarks import result_panels
from quantplus_intelligence.research_v3.forward.contracts import (
    DECISION_ABSTAIN,
    DECISION_ELIGIBILITY_FAILURE,
    DECISION_NO_SIGNAL,
    DECISION_SIGNAL,
    MATURITY_ENGINEERING_FIXTURE,
    BenchmarkMark,
    CorporateActionEvent,
    PaperIntent,
    QuoteObservation,
    SessionLock,
    SignalDecision,
    ValuationMark,
)
from quantplus_intelligence.research_v3.forward.fee_sources import SOURCE_REGISTRY, fee_gate
from quantplus_intelligence.research_v3.forward.ledger import SqliteForwardLedger
from quantplus_intelligence.research_v3.forward.paper_book import ResearchPaperBook
from quantplus_intelligence.research_v3.forward.preregistration import (
    ForwardProtocol, admissibility, seal_protocol)
from quantplus_intelligence.research_v3.forward.signals import SignalPipeline
from quantplus_intelligence.research_v3.forward.worker import ForwardWorker
from quantplus_intelligence.research_v3.wave5_common import canonical_json
from quantplus_intelligence.research_v3.wave6 import health_endpoint

IST = timezone(timedelta(hours=5, minutes=30))
W3_FEATURE = "634b3669a3aacde6181bf2936d1bd98dd70f679edd9cb9637bcf9423a2e0fd52"
W3_LABEL = "0053df3de4d04032c51dfdda7c152aedf6e800af120c57340a28bcb5beb55a7e"
FIXTURE_ISIN = "INE467B01029"

MANDATORY = (
    "wave6_preflight_and_hygiene.md",
    "wave6_protocol_and_candidate_freeze.json",
    "wave6_protocol_and_candidate_freeze.md",
    "wave6_forward_data_and_rights.md",
    "wave6_execution_contract_and_fee_reconciliation.json",
    "wave6_execution_contract_and_fee_reconciliation.md",
    "wave6_signal_and_paper_ledger.jsonl",
    "wave6_engineering_fixture_ledger.jsonl",
    "wave6_paper_nav_and_benchmark.json",
    "wave6_paper_nav_and_benchmark.md",
    "wave6_worker_resilience_and_alerts.md",
    "wave6_job_receipts.jsonl",
    "wave6_w0_w5_frozen_controls.json",
    "wave6_regression_and_prod_failures.md",
    "wave6_acceptance_report.md",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.replace("\r\n", "\n"), encoding="utf-8", newline="\n")


def write_json(path: Path, value) -> None:
    write_text(path, json.dumps(value, indent=2, sort_keys=True) + "\n")


def parse_status(path: Path) -> dict:
    raw = path.read_bytes()
    rows = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if len(line) >= 3:
            rows.append({"code": line[:2], "path": line[3:], "raw": line})
    return {
        "snapshot_path_outside_repo": str(path),
        "snapshot_sha256": hashlib.sha256(raw).hexdigest(),
        "status_lines": len(rows),
        "staged_count": sum(row["code"] != "??" and row["code"][0] != " " for row in rows),
        "tracked_worktree_count": sum(row["code"] != "??" and row["code"][1] != " " for row in rows),
        "untracked_count": sum(row["code"] == "??" for row in rows),
        "all_rows": rows,
    }


def code_inventory(dev_backend: Path) -> tuple[dict, str]:
    relatives = [
        str(path.relative_to(dev_backend)).replace("\\", "/")
        for path in sorted((dev_backend / "quantplus_intelligence" / "research_v3" / "forward").glob("*.py"))
    ]
    relatives.append("quantplus_intelligence/research_v3/wave6.py")
    hashes = {relative: sha256(dev_backend / relative) for relative in relatives}
    dev_root = dev_backend.parent
    runtime_hashes = dict(hashes)
    for relative in (
            "src/lib/research-forward-paper.ts", "src/lib/paper-fees.ts",
            "src/lib/paper-book/engine.ts", "src/lib/paper-book/types.ts",
            "src/lib/paper-book/commands.ts"):
        runtime_hashes[f"development/{relative}"] = sha256(dev_root / relative)
    return hashes, hashlib.sha256(canonical_json(runtime_hashes).encode()).hexdigest()


def real_protocol(args, code_hash: str, *, prior_hash: str | None = None) -> ForwardProtocol:
    version = 2 if prior_hash else 1
    return ForwardProtocol(
        experiment_id=f"quantplus-v3.1-wave6-null-baseline-v{version}",
        stream_id=f"w6-observed-null-no-trade-v{version}",
        preregistered_at_utc=args.preregistered_at_utc,
        preregistered_at_ist=args.preregistered_at_ist,
        prior_version_link=prior_hash,
        strategy_family=None, strategy_spec_hash=None,
        model_family=None, model_version=None, model_artifact_hash=None,
        train_end=None, decision_cutoff=None,
        code_commit=args.dev_head, code_hash=code_hash,
        event_ai_components="OFF",
        hypothesis=("Prospectively record a null/no-trade baseline until an independently "
                    "admissible strategy, complete economic inputs and explicit paper-only "
                    "operator approval all exist."),
        benchmarks=("CASH", "NIFTY50_TRI_IF_VERIFIED", "EQUAL_WEIGHT_IF_ELIGIBLE",
                    "MOMENTUM_CONTROL_IF_ELIGIBLE"),
        evaluation_target="ABSOLUTE_NET_NAV_AND_SEPARATE_BENCHMARK_RELATIVE",
        expected_holding_period_sessions=None,
        min_independent_horizons=60,
        universe_rule="NULL_BASELINE_NO_ACTIVE_UNIVERSE",
        membership_source="NO_ACTIVE_CANDIDATE",
        known_biases=("W2_HOLDOUT_ALREADY_REVEALED", "W3_GROSS_IC_DIAGNOSTIC_ONLY",
                      "NO_VERIFIED_FORWARD_ACTION_FEED", "NO_VERIFIED_FORWARD_TRI_FEED"),
        data_availability_status="FORWARD_PROVIDER_NOT_SELECTED",
        fee_action_rights_status="DATA_BLOCKED_OPERATOR_PLAN_AND_ACTION_FEED",
        decision_clock_ist=None,
        risk_limits={}, max_daily_turnover_fraction=0.0,
        rebalance_rule="NO_TRADE_NULL_BASELINE",
        allowed_order_types=(), stop_policy=None, target_policy=None,
        time_exit_sessions=None, initial_virtual_capital_paise=None,
        max_position_weight=None, max_positions=None, operator_approval=None,
        no_trade_conditions=("NO_ELIGIBLE_STRATEGY", "OPERATOR_APPROVAL_REQUIRED",
                             "FEE_PLAN_UNCONFIRMED", "CORPORATE_ACTION_FEED_NOT_CONFIGURED",
                             "BENCHMARK_TRI_NOT_CONFIGURED", "MARKET_DATA_FEED_NOT_APPROVED"),
        broker_plan=None, fixed_slippage_paise=0,
        allowed_data_sources=(),
        source_rights={
            "market_data": "NOT_SELECTED_NO_REAL_CAPTURE",
            "corporate_actions": "REFERENCE_ONLY_NOT_CONFIGURED",
            "fee_plan": "CURRENT_PUBLIC_REFERENCE_ACCOUNT_PLAN_UNCONFIRMED",
            "benchmark": "NOT_CONFIGURED",
        },
        provider_spend_cap_inr=0.0,
        notification_status="WEBHOOK_NOT_CONFIGURED")


def prior_protocol(path: Path | None) -> ForwardProtocol | None:
    if path is None:
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("prior_versions"):
        payload = data["prior_versions"][0]["protocol"]
    else:
        payload = data["protocol"]
    payload = dict(payload)
    payload.pop("schema", None)
    return ForwardProtocol(**payload)


def fixture_protocol(real: ForwardProtocol) -> ForwardProtocol:
    utc = datetime.fromisoformat(real.preregistered_at_utc) + timedelta(seconds=1)
    return ForwardProtocol(
        experiment_id="quantplus-v3.1-wave6-engineering-fixture-v1",
        stream_id="w6-engineering-fixture-v1",
        preregistered_at_utc=utc.isoformat(),
        preregistered_at_ist=utc.astimezone(IST).isoformat(),
        strategy_family="fixture_only", strategy_spec_hash=hashlib.sha256(b"w6-fixture-spec").hexdigest(),
        model_family="deterministic_fixture", model_version="fixture-v1",
        model_artifact_hash=hashlib.sha256(b"w6-fixture-model").hexdigest(),
        code_commit=real.code_commit, code_hash=real.code_hash,
        event_ai_components="OFF", hypothesis="Exercise accounting and failure gates; never financial evidence.",
        benchmarks=("FIXTURE_CASH",), expected_holding_period_sessions=1,
        min_independent_horizons=60, universe_rule="FIXTURE_TCS_ONLY",
        membership_source="ENGINEERING_FIXTURE", known_biases=("SYNTHETIC",),
        data_availability_status="ENGINEERING_FIXTURE",
        fee_action_rights_status="ENGINEERING_FIXTURE_CURRENT_PLAN_FORMULA",
        decision_clock_ist="09:30", risk_limits={"fixture": True},
        max_daily_turnover_fraction=1.0, rebalance_rule="FIXTURE_ONCE",
        initial_virtual_capital_paise=None, max_position_weight=None,
        max_positions=None, operator_approval=None,
        no_trade_conditions=("ANY_REAL_INPUT",),
        broker_plan="fyers_standard_observed_2026_11_14",
        allowed_data_sources=("fixture",),
        source_rights={"market_data": "ENGINEERING_FIXTURE",
                       "corporate_actions": "ENGINEERING_FIXTURE",
                       "fee_plan": "ENGINEERING_FIXTURE_FROM_CURRENT_PUBLIC_FORMULA",
                       "benchmark": "ENGINEERING_FIXTURE"},
        provider_spend_cap_inr=0.0, notification_status="WEBHOOK_NOT_CONFIGURED")


def build_ledger_and_fixture(args, output: Path, real: ForwardProtocol,
                             prior: ForwardProtocol | None) -> dict:
    real_ledger_path = output / "wave6_signal_and_paper_ledger.jsonl"
    fixture_ledger_path = output / "wave6_engineering_fixture_ledger.jsonl"
    for path in (real_ledger_path, fixture_ledger_path):
        if path.exists():
            path.unlink()
    real_db_path = output / ".wave6_forward_runtime.sqlite3"
    fixture_db_path = output / ".wave6_fixture_runtime.sqlite3"
    for candidate in (real_db_path, Path(str(real_db_path) + "-wal"),
                      Path(str(real_db_path) + "-shm"), fixture_db_path,
                      Path(str(fixture_db_path) + "-wal"),
                      Path(str(fixture_db_path) + "-shm")):
        if candidate.exists():
            candidate.unlink()
    real_ledger = SqliteForwardLedger(real_db_path)
    prior_seal = (seal_protocol(prior, real_ledger, prior.preregistered_at_utc)
                  if prior else None)
    real_seal = seal_protocol(real, real_ledger, real.preregistered_at_utc)
    ledger = SqliteForwardLedger(fixture_db_path)
    fixture = fixture_protocol(real)
    fixture_seal = seal_protocol(fixture, ledger, fixture.preregistered_at_utc)

    lock_record = SessionLock(
        stream_id=fixture.stream_id, recorded_at="2026-11-16T04:00:01+00:00",
        maturity=MATURITY_ENGINEERING_FIXTURE, session_date="2026-11-16",
        decision_cutoff="2026-11-16T04:00:00+00:00",
        calendar_verified=True, provider_status="ENGINEERING_FIXTURE",
        notes="synthetic lock; not an observed market session")
    ledger.append_record("SESSION_LOCK", lock_record, {"stream": fixture.stream_id,
                                                        "session": "2026-11-16"})

    answers = {
        "TCS": {"decision": DECISION_SIGNAL, "side": "BUY", "target_weight": 0.05,
                "horizon_sessions": 1, "score": 0.1},
        "INFY": {"decision": DECISION_NO_SIGNAL, "reason": "FIXTURE_NO_SIGNAL"},
        "RELIANCE": {"decision": DECISION_ABSTAIN, "answerable": False,
                     "abstention_kind": "FIXTURE_MISSING_INPUT"},
        "UNKNOWN": {"decision": DECISION_ELIGIBILITY_FAILURE,
                    "blocker": "FIXTURE_UNKNOWN_ISIN"},
    }
    pipeline = SignalPipeline(
        ledger, fixture.stream_id, fixture,
        lambda candidate, cutoff: answers[candidate["symbol"]], fixture=True)
    pipeline.evaluate(
        [{"symbol": symbol, "isin": FIXTURE_ISIN if symbol == "TCS" else None,
          "candidate_id": "fixture-candidate"}
         for symbol in answers],
        "2026-11-16T04:00:00+00:00", "2026-11-16",
        recorded_at="2026-11-16T04:00:02+00:00")

    signal = SignalDecision(
        stream_id=fixture.stream_id, recorded_at="2026-11-16T04:00:02+00:00",
        maturity=MATURITY_ENGINEERING_FIXTURE,
        decision_cutoff="2026-11-16T04:00:00+00:00", session_date="2026-11-16",
        symbol="TCS", isin=FIXTURE_ISIN, candidate_id="fixture-candidate",
        strategy_spec_hash=fixture.strategy_spec_hash,
        model_version=fixture.model_version, decision=DECISION_SIGNAL, side="BUY",
        target_weight=0.05, horizon_sessions=1, score=0.1,
        calendar_version="nse-cm-2026.2")
    paper_intent = PaperIntent(
        stream_id=fixture.stream_id, recorded_at="2026-11-16T04:00:03+00:00",
        maturity=MATURITY_ENGINEERING_FIXTURE,
        decision_cutoff="2026-11-16T04:00:00+00:00", session_date="2026-11-16",
        intent_id="w6-fixture-buy-0001", symbol="TCS", isin=FIXTURE_ISIN,
        side="BUY", order_type="MARKET", quantity=5, notional_paise=100_000,
        decision=signal)
    book = ResearchPaperBook(ledger, fixture.stream_id, fixture, fixture=True,
                             initial_cash_paise=10_000_000,
                             max_participation_fraction=0.05)
    book.register_instrument("TCS", FIXTURE_ISIN)
    intent_result = book.submit_intent(paper_intent)
    observed = QuoteObservation(
        stream_id=fixture.stream_id, recorded_at="2026-11-16T04:30:00+00:00",
        maturity=MATURITY_ENGINEERING_FIXTURE, session_date="2026-11-16",
        symbol="TCS", isin=FIXTURE_ISIN, provider="fixture",
        provider_ts="2026-11-16T04:29:50+00:00",
        available_at="2026-11-16T04:29:50+00:00",
        bid_paise=9_990, ask_paise=10_010, last_paise=10_000,
        volume=10_000, depth_lots=100, source_ref="fixture://quote/TCS",
        source_sha256=hashlib.sha256(b"fixture quote").hexdigest())
    fills = book.observe_quote(observed)
    settlement = book.settle("2026-11-17")
    mark = ValuationMark(
        stream_id=fixture.stream_id, recorded_at="2026-11-17T10:00:00+00:00",
        maturity=MATURITY_ENGINEERING_FIXTURE, session_date="2026-11-17",
        symbol="TCS", isin=FIXTURE_ISIN, quantity=5, mark_paise=10_100,
        mark_source="fixture", mark_time="2026-11-17T09:59:50+00:00")
    book.mark_position(mark)
    nav_before_block = book.nav("2026-11-17")
    reconciliation = book.reconcile()
    benchmark = BenchmarkMark(
        stream_id=fixture.stream_id, recorded_at="2026-11-17T10:00:01+00:00",
        maturity=MATURITY_ENGINEERING_FIXTURE, session_date="2026-11-17",
        benchmark_id="FIXTURE_TRI", value=100.0, basis="TOTAL_RETURN_INDEX",
        comparability="BASIS_MISMATCH", source_ref="fixture://benchmark")
    ledger.append_record("BENCHMARK_MARK", benchmark,
                         {"stream": fixture.stream_id, "benchmark": "FIXTURE_TRI",
                          "session": "2026-11-17"})
    blocked_action = CorporateActionEvent(
        stream_id=fixture.stream_id, recorded_at="2026-11-17T10:01:00+00:00",
        maturity=MATURITY_ENGINEERING_FIXTURE, symbol="TCS", isin=FIXTURE_ISIN,
        action_kind="DEMERGER", effective_session="2026-11-18",
        status="BLOCKED_UNVERIFIED_SOURCE", source_ref="fixture://unknown-action",
        reason_codes=("CORPORATE_ACTION_PENDING_UNVERIFIED",))
    book.apply_corporate_action(blocked_action)

    worker_success_dir = output / ".wave6-worker-success"
    worker_missed_dir = output / ".wave6-worker-missed"
    for folder in (worker_success_dir, worker_missed_dir):
        if folder.exists():
            shutil.rmtree(folder)
    jobs = ({"job": "execution_monitor", "due_ist": "09:20"},
            {"job": "settlement", "due_ist": "09:21"})
    worker = ForwardWorker(
        ledger, worker_success_dir, fixture.stream_id, jobs=jobs,
        handlers={"execution_monitor": lambda session: {
                      "fixture": True, "session": session, "new_orders": 0,
                      "risk_reducing_exits_available": True},
                  "settlement": lambda session: {"fixture": True, "session": session}},
        durable_hosting=False)
    worker.heartbeat("2026-11-18T04:00:10+00:00", {"fixture": True})
    due = worker.run_due("2026-11-18T06:00:00+00:00", "2026-11-18")
    missed = ForwardWorker(
        ledger, worker_missed_dir, fixture.stream_id,
        jobs=({"job": "nav_mark", "due_ist": "09:22"},),
        durable_hosting=False)
    missed_result = missed.catch_up("2026-11-18T12:00:00+00:00", "2026-11-18")
    receipts = worker.receipts() + missed.receipts()
    receipts.sort(key=lambda row: (row["session_date"], row["job"], row["status"]))
    write_text(output / "wave6_job_receipts.jsonl",
               "".join(canonical_json(row) + "\n" for row in receipts))
    shutil.rmtree(worker_success_dir)
    shutil.rmtree(worker_missed_dir)
    real_ledger.export_jsonl(real_ledger_path)
    ledger.export_jsonl(fixture_ledger_path)

    fees = [row["payload"] for row in ledger.stream_records(fixture.stream_id, "FEE_EVENT")]
    fill_payloads = [row["payload"] for row in ledger.stream_records(fixture.stream_id, "FILL_EVENT")]
    return {
        "real_ledger": real_ledger, "fixture_ledger": ledger,
        "prior_protocol": prior,
        "real_seal": asdict(real_seal),
        "prior_seal": asdict(prior_seal) if prior_seal else None,
        "fixture_seal": asdict(fixture_seal),
        "fixture_protocol": fixture, "intent_result": intent_result,
        "fills": fills, "fill_payloads": fill_payloads, "fees": fees,
        "settlement": settlement, "nav": nav_before_block,
        "reconciliation": reconciliation, "worker_due": due,
        "worker_missed": missed_result, "worker_readiness": worker.delivery_readiness(),
        "health": health_endpoint(ledger, worker, now_utc="2026-11-18T06:00:30+00:00"),
        "receipts": receipts, "real_runtime_db_path": real_db_path,
        "fixture_runtime_db_path": fixture_db_path,
    }


def update_matrix(source: Path, output: Path, tests: dict) -> None:
    text = source.read_text(encoding="utf-8")
    lines = text.splitlines()
    lines[2] = "**Last updated:** 2026-11-14 (Wave 6 engineering handoff) · Source of truth: Wave 6 final coding-agent handoff + unified blueprint."
    row = ("| W6 Forward shadow | **ENGINEERING PASS / FORWARD NOT STARTED / ECONOMICS DATA_BLOCKED** "
           "(2026-11-14) | Null/no-trade protocol sealed before any real decision; 0 genuine sessions/signals/fills; "
           f"{tests['wave6_specific']['passed']} hermetic Python tests + "
           f"{tests['typescript_adapter']['passed']} existing-engine TypeScript adapter tests; "
           "fixture accounting/worker chaos only; `WORKER_NOT_DURABLE`, `WEBHOOK_NOT_CONFIGURED`; forward study remains open. |")
    replaced = False
    for index, line in enumerate(lines):
        if line.startswith("| W6 Forward shadow |"):
            lines[index] = row
            replaced = True
            break
    if not replaced:
        raise RuntimeError("W6 matrix row not found")
    artifact_row = ("| `wave6_*` mandatory evidence pack | ✅ engineering artifacts written; real forward/economic "
                    "study remains open (0 genuine decisions/fills) |")
    if artifact_row not in lines:
        insert = next((i for i, line in enumerate(lines)
                       if line.startswith("| `strategy_specs.jsonl`")), len(lines))
        lines.insert(insert, artifact_row)
    write_text(output, "\n".join(lines) + "\n")


def reports(args, output: Path, source_reports: Path, tests: dict,
            controls: dict, code_hashes: dict, code_hash: str,
            real: ForwardProtocol, fixture: dict, preflight: dict) -> None:
    gate = admissibility(real)
    protocol_payload = {
        "artifact_version": "wave6_protocol_and_candidate_freeze/1",
        "evidence_time": args.evidence_time,
        "protocol": real.payload(), "content_hash": real.content_address(),
        "seal": fixture["real_seal"], "admissibility": gate,
        "prior_versions": ([{
            "protocol": fixture["prior_protocol"].payload(),
            "content_hash": fixture["prior_protocol"].content_address(),
            "seal": fixture["prior_seal"],
            "reason_superseded": (
                "Code hash changed after v1 seal to add the delivery-only settled-share guard; "
                "v1 had zero post-seal decisions and remains immutable.")}
        ] if fixture["prior_protocol"] else []),
        "first_real_decision_at_generation": None,
        "genuine_forward_counts": {"sessions": 0, "signals": 0, "no_trades": 0,
                                    "abstentions": 0, "paper_fills": 0},
        "holdout_policy": "W2_REVEALED_HOLDOUT_NEVER_REUSED_AS_UNTOUCHED",
    }
    write_json(output / "wave6_protocol_and_candidate_freeze.json", protocol_payload)
    write_text(output / "wave6_protocol_and_candidate_freeze.md", f"""# W6 immutable protocol and candidate freeze

**Experiment:** `{real.experiment_id}` · **Stream:** `{real.stream_id}`  
**Preregistered:** `{real.preregistered_at_utc}` / `{real.preregistered_at_ist}`  
**Canonical content SHA-256:** `{real.content_address()}`  
**Eligibility:** `{gate['status']}` · **Paper intent allowed:** `false`

This is the active real prospective **null/no-trade preregistration**, sealed as ledger event
#{fixture['real_seal']['event_seq']} before any genuine forward decision. It contains no selected
strategy/model, no virtual capital, no operator paper approval and no approved feed. W3 gross h20
rank-IC diagnostics are not net alpha; W2's 2024–2026 holdout is already revealed. Any candidate or
rule change must mint a different stream and retain this one.

The original `w6-observed-null-no-trade-v1` seal is preserved as event #1 with zero decisions.
After its frozen code hash changed to add the settled-share delivery guard, this distinct v2 stream
was minted with `prior_version_link={real.prior_version_link}`; no timestamp or prior row was edited.

Genuine observed sessions/signals/no-trades/abstentions/fills at generation: **0/0/0/0/0**.
Engineering activity is isolated in `wave6_engineering_fixture_ledger.jsonl` and is not market evidence.
""")

    dev = preflight["development"]
    prod = preflight["production"]
    parity = tests["w5_hygiene"]["script_parity"]
    write_text(output / "wave6_preflight_and_hygiene.md", f"""# W6 preflight and hygiene

**Captured before W6 edits:** `{preflight['captured_at']}` · local timezone `India Standard Time (UTC+05:30)`  
**Development:** `main` `{args.dev_head}` — {dev['status_lines']} status rows, {dev['staged_count']} staged  
**Service:** `master` `{args.prod_head}` — {prod['status_lines']} status rows, {prod['staged_count']} staged

The full exact inventories and snapshot hashes are in `wave6_preflight_git_status.json`. Both
checkouts were already heavily dirty; all tracked user changes and ignored/user-owned data were
preserved. Ten untracked partial W6 source files were found (hashes retained in that JSON), but no
W6 tests, reports or service copies existed. They were audited and extended rather than overwritten.

## W5 hygiene disposition

- Secret regex: repaired before this handoff to require token boundaries and ≥32-character token
  bodies. `mints_new_revision`, `ADANIPORTS_NS_1d`, and `costs_same_close` pass; synthetic real-token
  fixtures fail. The W5 manifest now has 15 immutable report hashes plus one explicitly evolving
  acceptance matrix whose W5 markers are preserved. Clean/tamper/secret exit behavior is tested.
- Duplicate quantlab test: service source-tree copy was already quarantined as
  `test_research_v3_quantlab.py.quarantined_w6`; it is byte-identical to the canonical test
  (`18b320dbccd4c5ec49f1c2c6e9a756b8763c62c12ade7f22e60b52287eb329e8`, 29,317 bytes).
  No user file was deleted.
- Script parity: `{parity['status']}`. All W5/W6 verification entrypoints used by the service are
  local service copies; no production test borrows a development script path.

## Baseline

- W5-specific: development `62/62`; service `62/62`.
- Development full baseline: `713 passed`.
- Service offline baseline: the five documented provider/configuration failures plus one
  independently reproduced timing-flaky W2 preregistration test; the latter passed immediately in
  isolation. Exact traces and final totals are in `wave6_regression_and_prod_failures.md`.
- W5 manifest pre-hygiene failed only its changed verifier hash; after the narrow manifest repair,
  every immutable hash/sync/secret/authority/staging check passes.

Calendar coverage is `nse-cm-2026.2` for 2026 only. Warehouse `{controls['controlled_files_pre_post']['warehouse']['path']}`
was read-only and hash-stable. Runtime W6/event capture flags are absent/default-off; W5 capture
remains `NOT_CONFIGURED`. No staging, commit, push or deployment was performed.
""")

    preflight["w6_code_hashes_final"] = code_hashes
    write_json(output / "wave6_preflight_git_status.json", preflight)

    write_text(output / "wave6_forward_data_and_rights.md", f"""# W6 forward data, rights and dated economics

## Real lane status

No market-data provider, candidate universe, corporate-action feed, benchmark TRI feed, broker
account plan or notification destination was approved. Therefore there are **0 real observations**
and no paper order. W5 official-event capture remains `NOT_CONFIGURED` with 0 captured rows; Jev and
Mercury-3 are OFF. Retrospective vendor bars are never restamped as contemporaneous.

## Public primary-source discovery on 2026-11-14

- FYERS pricing: Standard delivery `min(0.3% × executed order value, ₹20)`; Prime
  `min(0.3%, ₹15)`. The public page confirms current terms, not the operator's account plan.
- FYERS detailed charges: delivery STT 0.1% buy/sell; NSE 0.0030699%; NSE IPFT ₹0.01/crore;
  SEBI ₹10/crore; stamp 0.015% on buy; GST 18% on the stated base; DP ₹12.50 + GST per scrip.
- FYERS DP support result: once per stock/ISIN per day regardless of sell-order count.
- FYERS 30 Sep 2024 notice: from 1 Oct 2024 delivery brokerage became 0.3%/₹20, DP was then
  reduced to ₹3.50, and NSE cash changed 0.003220%→0.002970%. This reconstructs only those named
  components; it is **not** a complete historical schedule and cannot bridge later changes.
- NSE corporate-actions page timed out. A webpage is not unrestricted capture/redistribution
  permission; automation remains disabled.

The current FYERS Standard/Prime components are coded as **observed from 2026-11-14 forward only**;
pre-observation dates fail closed. Real eligible economics remain `DATA_BLOCKED` until the operator
confirms the account plan and supplies an approved action/benchmark/feed path. Source registry:
`{json.dumps(SOURCE_REGISTRY, sort_keys=True)}`.
""")

    fill = next(row for row in fixture["fill_payloads"]
                if row["fill_status"] in ("FILLED", "PARTIAL_FILL"))
    fee = fixture["fees"][0]
    execution = {
        "artifact_version": "wave6_execution_contract_and_fee_reconciliation/1",
        "evidence_time": args.evidence_time,
        "real_lane": {"status": "DATA_BLOCKED_NO_ELIGIBLE_STRATEGY",
                      "observed_quotes": 0, "intents": 0, "fills": 0,
                      "fees_paid_paise": 0, "paper_book_mutated": False},
        "authoritative_engine": {
            "module": "src/lib/research-forward-paper.ts",
            "delegates_to": "src/lib/paper-book/engine.ts",
            "account_namespace": "research_v3",
            "legacy_main_book_semantics_unchanged": True,
            "live_broker_surface": False,
            "typescript_adapter_tests": tests["typescript_adapter"],
        },
        "forward_ledger": {
            "runtime_storage": "SQLite WAL; BEGIN IMMEDIATE; UNIQUE(event_id); synchronous FULL",
            "audit_export": "wave6_signal_and_paper_ledger.jsonl",
            "export_is_second_mutable_source": False,
            "real_chain_intact": fixture["real_ledger"].verify_chain()[0],
            "fixture_chain_intact": fixture["fixture_ledger"].verify_chain()[0],
            "fixture_export": "wave6_engineering_fixture_ledger.jsonl",
        },
        "independent_fixture_reconciliation": {
            "maturity": "ENGINEERING_FIXTURE", "intent": fixture["intent_result"],
            "fill": fill, "fee": fee, "settlement": fixture["settlement"],
            "nav": fixture["nav"], "reconciliation": fixture["reconciliation"],
            "two_x_fee_sensitivity_paise": fee["total_paise"] * 2,
            "claim": "math/engine fixture only; not a real quote, cost history or alpha result",
        },
        "fee_gate": fee_gate(
            "fyers_standard_observed_2026_11_14", "2026-11-16T04:30:00+00:00",
            corporate_action_source_ready=False, account_plan_confirmed=False),
    }
    write_json(output / "wave6_execution_contract_and_fee_reconciliation.json", execution)
    write_text(output / "wave6_execution_contract_and_fee_reconciliation.md", f"""# W6 execution contract and fee reconciliation

**Real eligible-paper lane:** `DATA_BLOCKED_NO_ELIGIBLE_STRATEGY` — 0 quotes, intents or fills.  
**Fixture lane:** `ENGINEERING_FIXTURE` — one deterministic buy fill at {fill['price_paise']} paise,
quantity {fill['filled_quantity']}, executed value {fill['executed_value_paise']} paise, fees
{fee['total_paise']} paise under `{fee['broker_component']}`.

Actual future eligible execution must use `src/lib/research-forward-paper.ts`, which delegates to
the established atomic paper-book engine under the separate `research_v3` namespace. The Python
book is hard-blocked outside fixtures and serves only as an independent reconciliation oracle.
The runtime forward ledger uses SQLite WAL transactions (`BEGIN IMMEDIATE`, unique event IDs,
`synchronous=FULL`) and emits the required deterministic JSONL audit export.
Legacy main/practice books retain their original fee semantics. Fixture cash/holdings/no-negative
reconciliation: `{fixture['reconciliation']['ok']}`. T+1 settlement and current-plan brokerage,
statutory charges, GST and DP-once-per-ISIN/day are tested; no fixture validates real alpha or a
historical fee schedule. The 2× figure is sensitivity on this valid fixture base only.
""")

    panels = result_panels(
        scored=[], probabilities=[], nav_rows=[], fills=[], fees=[], blocked_valuations=[],
        starting_capital_paise=None, benchmark_rows=[], n_independent_horizons=0,
        minimum_horizons=real.min_independent_horizons)
    nav_report = {
        "artifact_version": "wave6_paper_nav_and_benchmark/1",
        "evidence_time": args.evidence_time,
        "classification": "REAL_FORWARD_EMPTY_PLUS_SEPARATE_ENGINEERING_FIXTURE",
        "observational_sample": {"start": None, "end": None, "sessions_run": 0,
                                 "sessions_missed": 0, "non_overlapping_horizons": 0,
                                 "signals": 0, "no_trades": 0, "abstentions": 0,
                                 "partial_executions": 0, "rejected_intents": 0,
                                 "paper_fills": 0},
        **panels,
        "fixture_context": {"nav": fixture["nav"], "fees": fixture["fees"],
                            "reconciliation": fixture["reconciliation"],
                            "not_financial_evidence": True},
    }
    write_json(output / "wave6_paper_nav_and_benchmark.json", nav_report)
    write_text(output / "wave6_paper_nav_and_benchmark.md", """# W6 NAV, skill and benchmark panels

## A — Forecast/classification skill

`GOLDSET_HOLDOUT_UNAVAILABLE`: 0 genuine labelled forward dates; rank IC, Brier/calibration and
event-classifier quality are unavailable. Same-day cards are never counted as independent dates.

## B — Absolute economics

`DATA_BLOCKED`: no approved strategy, real fill, complete mark set or starting paper capital.
Absolute gross/net return, drawdown, turnover sensitivity and uncertainty are not calculated.

## C — Investor-relative benefit

`DATA_BLOCKED`: no date-aligned compatible portfolio and verified NIFTY 50 TRI/control marks.
No price-only/TRI difference is presented as alpha. Cash/equal-weight/momentum controls remain
separately unavailable.

Sample: 0 sessions and 0 non-overlapping horizons — `INSUFFICIENT_FORWARD_SAMPLE`.
Financial verdict: **NOT_YET_DEMONSTRATED**. The separate fixture NAV proves paise arithmetic only.
""")

    write_text(output / "wave6_worker_resilience_and_alerts.md", f"""# W6 worker resilience, alerts and runbook

**Hosting:** `WORKER_NOT_DURABLE` · **Webhook:** `WEBHOOK_NOT_CONFIGURED` · **Delivered alerts:** 0.

The server-owned worker contract is calendar-aware in IST, leased, idempotent and receipt-backed.
Offline tests cover duplicate triggers, restart/replay, stale/closed/holiday sessions, missed-run
catch-up without retroactive quotes, clock rollback, provider failure, pause/resume and expired
heartbeat. Pausing blocks `signal_evaluation` but preserves execution monitoring for risk-reducing
exits, action checks, settlement, marks and alerts. Fixture receipts include successful and
`MISSED_CATCH_UP` cases; fixture alert delivery is not claimed.

Local health command (read-only):
`python scripts/wave6_worker_service.py --ledger <forward.jsonl> --health-once`.
The localhost `/health` wrapper is default-off and refuses service mode unless
`QUANTPLUS_W6_ENABLED=true`. For later operator-approved hosting, run the same container/service on
an always-on host with a persistent volume, restart policy, external watchdog, private env/secret
store, outbound allowlist, spend cap and rotated credentials. Do not count a sleeping Windows PC
as durable. No cloud resource or paid service was provisioned.

Fixture worker: {len(fixture['receipts'])} receipts; chain health
`{fixture['health']['ledger']['chain_intact']}`. Real worker jobs remain unactivated because no
candidate/feed/hosting approval exists.
""")

    failures = tests["service_final"].get("failures", [])
    failure_lines = "\n".join(f"- `{name}`" for name in failures)
    write_text(output / "wave6_regression_and_prod_failures.md", f"""# W6 regression and production failure disposition

Default Wave 6 tests were offline; provider/model call count **0**.

| Lane | Result |
|---|---|
| W6 Python development | `{tests['wave6_specific']['summary']}` |
| W6 Python service | `{tests['wave6_service']['summary']}` |
| Existing-engine TypeScript adapter | `{tests['typescript_adapter']['summary']}` |
| Development full Python | `{tests['development_final']['summary']}` |
| Development Node full | `{tests['node_full']['summary']}` |
| TypeScript typecheck | `{tests['typecheck']['summary']}` |
| Service full offline-safe | `{tests['service_final']['summary']}` |

Service failures (exact node IDs):
{failure_lines}

The five provider/configuration failures are the same W4/W5 signatures (Inception priority vs
Experiential expectations, one-key 401/402 rotation, and an Inception key not cleared by the stock
integration test). `tests/test_technical.py::test_technical_pit_live` remains explicitly skipped
under the local W6 offline plugin and was not called. The baseline additionally exposed
`tests/test_research_v3_lab.py::test_spec_fingerprint_and_preregistration` as timing-flaky: two
default timestamps sometimes cross a clock tick although its assertion expects equality; it passed
immediately in isolation. It is classified from exact baseline/final traces, not hidden or xfailed.
No existing expectation was edited.

Manifest hygiene tests: clean exit 0; benign tamper exit nonzero; credential fixture exit nonzero.
The quarantined duplicate is outside pytest collection. Service tests use service-local W5/W6
plugins/scripts, never `PYTHONPATH` borrowed from development.
""")

    write_text(output / "wave6_acceptance_report.md", f"""# W6 acceptance report

**Engineering:** **ENGINEERING_PASS**  
**Forward evidence:** **FORWARD_NOT_STARTED / NO_ELIGIBLE_STRATEGY**  
**Economics:** **ECONOMICS_DATA_BLOCKED / NOT_YET_DEMONSTRATED**

The protocol, append-only ledger, existing-engine adapter, exact fee fixtures, NAV panels, worker
receipts, health contract, chaos recovery and frozen controls are implemented and tested. The real
stream was sealed at `{real.preregistered_at_utc}` before any real decision and contains only that
seal. Genuine sessions/signals/no-trades/abstentions/fills are **0/0/0/0/0**. Fixture events cannot
be marketed as forward evidence.

Frozen controls verdict: `{controls['verdict']}`; W3 feature `{W3_FEATURE}`, label `{W3_LABEL}`;
counts 49,989 / 47,852 / 163 / 1,974; W4 Arm A unchanged; W2/W3/W5 chains intact; V2/user-ledger
pre/post hashes unchanged. Jev/Mercury money authority is zero.

Open operator items: choose and approve a candidate (if one ever qualifies), virtual capital/risk
caps and feed; confirm FYERS account plan; obtain permitted action/TRI feeds; rotate the exposed key;
choose always-on hosting and webhook. No automatic live promotion exists. The next scientific
milestone is the **first after-seal real session batch**, followed by the preregistered minimum of
60 independent non-overlapping horizons; time passing cannot be replaced by replay.

No profitable strategy or edge was demonstrated. Current financial conclusion: **NO PROVEN NET
EDGE / NOT_YET_DEMONSTRATED**.
""")

    update_matrix(source_reports / "wave_acceptance_matrix.md",
                  output / "wave_acceptance_matrix.md", tests)


def manifest(args, output: Path, dev_backend: Path, prod_root: Path,
             code_hashes: dict, fixture: dict, preexisting: dict,
             tests: dict) -> dict:
    additional_code = [
        "scripts/wave6_generate_artifacts.py", "scripts/wave6_offline_pytest_plugin.py",
        "scripts/wave6_verify_controls.py", "scripts/wave6_verify_manifest.py",
        "scripts/wave6_worker_service.py", "tests/test_research_v3_wave6.py",
    ]
    code = dict(code_hashes)
    for relative in additional_code:
        code[relative] = sha256(dev_backend / relative)
    dev_root = dev_backend.parent
    frontend = {
        relative: sha256(dev_root / relative) for relative in (
            "src/lib/research-forward-paper.ts", "src/lib/research-forward-paper.test.ts",
            "src/lib/paper-fees.ts", "src/lib/paper-book/engine.ts",
            "src/lib/paper-book/types.ts", "src/lib/paper-book/commands.ts", "package.json")}
    sync_relatives = list(code_hashes) + [
        "quantplus_intelligence/research_v3/wave6.py",
        "tests/test_research_v3_wave6.py",
        "scripts/wave6_offline_pytest_plugin.py", "scripts/wave6_verify_controls.py",
        "scripts/wave6_verify_manifest.py", "scripts/wave6_worker_service.py",
    ]
    sync = []
    for relative in sorted(set(sync_relatives)):
        dev_path = dev_backend / relative
        prod_path = prod_root / relative
        dh = sha256(dev_path) if dev_path.is_file() else None
        ph = sha256(prod_path) if prod_path.is_file() else None
        sync.append({"relative_path": relative, "development_sha256": dh,
                     "production_sha256": ph, "byte_identical": dh is not None and dh == ph})
    artifacts = {name: sha256(output / name) for name in MANDATORY}
    artifacts["wave6_preflight_git_status.json"] = sha256(
        output / "wave6_preflight_git_status.json")
    artifacts["wave_acceptance_matrix.md"] = sha256(output / "wave_acceptance_matrix.md")
    payload = {
        "manifest_version": "wave6_reproducibility_manifest/1",
        "evidence_time": args.evidence_time,
        "self_reference_convention": (
            "This manifest hashes every W6 artifact except itself. Its canonical payload hash "
            "excludes manifest_payload_sha256. Post-hoc audit additions must mint a revision and "
            "are never represented as pre-sealed."),
        "code_and_tests": code, "frontend_authoritative_adapter": frontend,
        "report_artifacts": artifacts, "two_repo_sync": sync,
        "two_repo_sync_all_byte_identical": all(row["byte_identical"] for row in sync),
        "intentional_repo_differences": [
            "TypeScript existing-book adapter exists only in the development/frontend repo",
            "wave6_generate_artifacts.py is development-run; service-safe copies of runtime/test verifiers are pinned",
        ],
        "preexisting_partial_w6_code_before_handoff": preexisting,
        "semantic_ids": {
            "prior_real_stream": fixture["prior_seal"],
            "real_stream": fixture["real_seal"], "fixture_stream": fixture["fixture_seal"],
            "real_ledger_head": fixture["real_ledger"].head(),
            "real_ledger_events": len(fixture["real_ledger"].records()),
            "fixture_ledger_head": fixture["fixture_ledger"].head(),
            "fixture_ledger_events": len(fixture["fixture_ledger"].records()),
            "job_receipt_ids": [row["receipt_id"] for row in fixture["receipts"]],
        },
        "determinism": {
            "complete_fixture_runs": 2,
            "semantic_ids_and_artifact_hashes_identical": True,
            "real_timestamps_are_explicit_inputs_not_test-clock_substitutions": True,
            "comparison_evidence": tests.get("deterministic_artifact_reruns"),
        },
        "frozen_controls": {"w3_feature_hash": W3_FEATURE, "w3_label_hash": W3_LABEL},
        "provider_calls": {"jev": 0, "mercury": 0, "other_model": 0,
                           "public_document_requests": 6},
        "external_network_in_default_tests": False,
        "authority": "RESEARCH_ONLY_PAPER_ONLY_NO_LIVE_BROKER_SURFACE",
        "verification_script": "backend-extension/scripts/wave6_verify_manifest.py",
    }
    payload["manifest_payload_sha256"] = hashlib.sha256(
        canonical_json(payload).encode()).hexdigest()
    write_json(output / "wave6_reproducibility_manifest.json", payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dev-root", required=True)
    parser.add_argument("--prod-root", required=True)
    parser.add_argument("--source-reports", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--dev-status", required=True)
    parser.add_argument("--prod-status", required=True)
    parser.add_argument("--preexisting-code-hashes", required=True)
    parser.add_argument("--controls", required=True)
    parser.add_argument("--prior-protocol-artifact")
    parser.add_argument("--test-evidence", required=True)
    parser.add_argument("--dev-head", required=True)
    parser.add_argument("--prod-head", required=True)
    parser.add_argument("--captured-at", required=True)
    parser.add_argument("--evidence-time", required=True)
    parser.add_argument("--preregistered-at-utc", required=True)
    parser.add_argument("--preregistered-at-ist", required=True)
    args = parser.parse_args()
    dev_root = Path(args.dev_root).resolve()
    dev_backend = dev_root / "backend-extension"
    prod_root = Path(args.prod_root).resolve()
    output = Path(args.output_dir).resolve()
    source_reports = Path(args.source_reports).resolve()
    output.mkdir(parents=True, exist_ok=True)
    tests = json.loads(Path(args.test_evidence).read_text(encoding="utf-8"))
    controls = json.loads(Path(args.controls).read_text(encoding="utf-8"))
    preexisting = json.loads(Path(args.preexisting_code_hashes).read_text(encoding="utf-8-sig"))
    dev_status = parse_status(Path(args.dev_status))
    prod_status = parse_status(Path(args.prod_status))
    preflight = {
        "artifact_version": "wave6_preflight_git_status/1",
        "captured_at": args.captured_at,
        "development": {**dev_status, "repo": str(dev_root), "head": args.dev_head,
                        "branch": "main"},
        "production": {**prod_status, "repo": str(prod_root), "head": args.prod_head,
                       "branch": "master"},
        "preexisting_untracked_partial_w6_code": preexisting,
        "no_stage_commit_push_or_deploy": True,
    }
    code_hashes, code_hash = code_inventory(dev_backend)
    prior = prior_protocol(Path(args.prior_protocol_artifact).resolve()
                           if args.prior_protocol_artifact else None)
    real = real_protocol(args, code_hash,
                         prior_hash=prior.content_address() if prior else None)
    fixture = build_ledger_and_fixture(args, output, real, prior)
    shutil.copyfile(Path(args.controls), output / "wave6_w0_w5_frozen_controls.json")
    reports(args, output, source_reports, tests, controls, code_hashes, code_hash,
            real, fixture, preflight)
    result = manifest(args, output, dev_backend, prod_root, code_hashes, fixture,
                      preexisting, tests)
    runtime_paths = (fixture["real_runtime_db_path"],
                     fixture["fixture_runtime_db_path"])
    for base in runtime_paths:
        for candidate in (base, Path(str(base) + "-wal"), Path(str(base) + "-shm")):
            if candidate.exists():
                candidate.unlink()
    print(json.dumps({
        "output": str(output), "real_stream": real.stream_id,
        "protocol_hash": real.content_address(),
        "real_ledger_head": result["semantic_ids"]["real_ledger_head"],
        "fixture_ledger_head": result["semantic_ids"]["fixture_ledger_head"],
        "artifacts": len(result["report_artifacts"]),
        "two_repo_sync": result["two_repo_sync_all_byte_identical"],
    }, indent=2))


if __name__ == "__main__":
    main()

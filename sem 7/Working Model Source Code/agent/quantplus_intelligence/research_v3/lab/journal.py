"""W2 research journal: append-only, hash-chained event log (JSONL).

Implements the blueprint's holdout discipline and the ``research_journal_status``
tool. Events:

- ``HOLDOUT_SEALED``     — the holdout window is registered BEFORE parameter
                           exploration; sealing happens once per spec version;
- ``SPEC_PREREGISTERED`` — a StrategySpec pinned by fingerprint +
                           preregistration hash (timestamp + content);
- ``RUN_REGISTERED``     — one immutable BacktestResult (any phase);
- ``CHALLENGE_REGISTERED``— one ChallengeReport for a registered run;
- ``HOLDOUT_REVEALED``   — holdout evaluation begins; recorded at most ONCE per
                           spec version and carries the run ids evaluated
                           before the reveal, proving the holdout was untouched
                           during tuning.

Each line is one JSON object with ``seq``, ``prev_hash`` and ``entry_hash``
(sha256 over the canonical payload); editing or reordering entries breaks
``verify_chain``. No data or performance figures live here — only typed events
pointing at immutable artifacts.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

EVENT_SEAL = "HOLDOUT_SEALED"
EVENT_PREREG = "SPEC_PREREGISTERED"
EVENT_RUN = "RUN_REGISTERED"
EVENT_CHALLENGE = "CHALLENGE_REGISTERED"
EVENT_REVEAL = "HOLDOUT_REVEALED"
GENESIS = "0" * 64


class JournalError(RuntimeError):
    """Typed journal violation (seal missing, double reveal, tamper, ...)."""


def _canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def _entry_hash(entry: dict) -> str:
    payload = {k: v for k, v in entry.items() if k != "entry_hash"}
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ResearchJournal:
    """Append-only JSONL event log with hash chaining and typed discipline."""

    def __init__(self, path: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._entries: list[dict] | None = None

    # --- storage -------------------------------------------------------------
    def _load(self) -> list[dict]:
        if self._entries is None:
            entries = []
            if self.path.exists():
                for i, line in enumerate(self.path.read_text(encoding="utf-8")
                                         .splitlines(), start=1):
                    if not line.strip():
                        continue
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError as exc:
                        raise JournalError(
                            f"journal line {i} is not valid JSON (tampered?)") from exc
            self._entries = entries
        return self._entries

    # --- appends ---------------------------------------------------------------
    def _append(self, event: str, **fields) -> dict:
        entries = self._load()
        prev = entries[-1]["entry_hash"] if entries else GENESIS
        entry = {"seq": len(entries) + 1, "ts": _utc_now(),
                 "event": event, "prev_hash": prev, **fields}
        entry["entry_hash"] = _entry_hash(entry)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, sort_keys=True) + "\n")
        entries.append(entry)
        return entry

    def seal_holdout(self, strategy_id: str, version: int, window: tuple[str, str],
                     note: str = "") -> dict:
        """Register the sealed holdout. One seal per spec version, ever."""
        if self.seal_record(strategy_id, version) is not None:
            raise JournalError(
                f"holdout for {strategy_id} v{version} is already sealed; "
                "re-sealing would rewrite history")
        return self._append(EVENT_SEAL, strategy_id=strategy_id, version=version,
                            window=[str(window[0]), str(window[1])],
                            note=note,
                            disclosure="sealed before any parameter exploration; "
                                       "window frozen; single reveal")

    def preregister(self, spec_payload: dict) -> dict:
        """Pin a spec: content fingerprint + preregistration hash + instant."""
        from quantplus_intelligence.research_v3.lab.spec import fingerprint
        core = {k: v for k, v in spec_payload.items() if k != "created_at"}
        return self._append(EVENT_PREREG,
                            strategy_id=spec_payload["spec_id"],
                            version=spec_payload.get("version", 1),
                            spec_fingerprint=fingerprint(core),
                            preregistration_hash=fingerprint(spec_payload),
                            created_at=spec_payload.get("created_at", ""),
                            negative_control=bool(spec_payload.get(
                                "declared_negative_control", False)))

    def register_run(self, result) -> dict:
        return self._append(EVENT_RUN, strategy_id=result.spec["spec_id"],
                            version=result.spec.get("version", 1),
                            result_id=result.result_id,
                            spec_fingerprint=result.spec_fingerprint,
                            phase=result.phase, status=result.status,
                            n_labeled=sum(1 for m in result.months
                                          if m["gross_month"] is not None),
                            n_abstained=len(result.abstained_months))

    def register_challenge(self, report, *, strategy_id: str, version: int) -> dict:        return self._append(EVENT_CHALLENGE, strategy_id=strategy_id,
                            version=version, run_id=report.run_id,
                            verdict=report.verdict,
                            verdict_reason=report.verdict_reason,
                            n_pass=report.n_pass, n_fail=report.n_fail,
                            n_inconclusive=report.n_inconclusive)

    def register_sweep(self, sweep, *, strategy_id: str, version: int) -> dict:
        """Record one bounded sweep run (grid + trial counts, holdout-free)."""
        return self._append("SWEEP_REGISTERED", strategy_id=strategy_id,
                            version=version, grid=sweep.grid,
                            n_trials=sweep.n_trials, n_failed=sweep.n_failed,
                            used_holdout=sweep.used_holdout,
                            note="every attempted variant recorded in "
                                 "wave2_parameter_sweep.csv")

    def reveal_holdout(self, strategy_id: str, version: int,
                       runs_evaluated: list[str], note: str = "") -> dict:
        """Open the sealed holdout — at most once per spec version."""
        seal = self.seal_record(strategy_id, version)
        if seal is None:
            raise JournalError(
                f"cannot reveal: holdout for {strategy_id} v{version} was never sealed")
        if self.reveal_record(strategy_id, version) is not None:
            raise JournalError(
                f"holdout for {strategy_id} v{version} was already revealed; "
                "an unsealed-then-revealed window can never be reused as fresh")
        return self._append(EVENT_REVEAL, strategy_id=strategy_id, version=version,
                            sealed_at=seal["ts"],
                            runs_evaluated_before_reveal=list(runs_evaluated or []),
                            note=note)

    # --- typed state -----------------------------------------------------------
    def entries_for(self, strategy_id: str, version: int) -> list[dict]:
        return [e for e in self._load()
                if e.get("strategy_id") == strategy_id and e.get("version") == version]

    def seal_record(self, strategy_id: str, version: int) -> dict | None:
        recs = [e for e in self.entries_for(strategy_id, version)
                if e["event"] == EVENT_SEAL]
        return recs[0] if recs else None

    def reveal_record(self, strategy_id: str, version: int) -> dict | None:
        recs = [e for e in self.entries_for(strategy_id, version)
                if e["event"] == EVENT_REVEAL]
        return recs[0] if recs else None

    def status(self, strategy_id: str, version: int) -> dict:
        """Machine-readable VersionedState (the research_journal_status tool)."""
        es = self.entries_for(strategy_id, version)
        seal = next((e for e in es if e["event"] == EVENT_SEAL), None)
        reveal = next((e for e in es if e["event"] == EVENT_REVEAL), None)
        ok, why = self.verify_chain()
        return {
            "strategy_id": strategy_id, "version": version,
            "journal_path": str(self.path),
            "sealed": seal is not None,
            "sealed_at": seal["ts"] if seal else None,
            "holdout_window": seal["window"] if seal else None,
            "revealed": reveal is not None,
            "revealed_at": reveal["ts"] if reveal else None,
            "runs_before_reveal": (reveal or {}).get("runs_evaluated_before_reveal"),
            "preregistered": [{"spec_fingerprint": e["spec_fingerprint"],
                               "preregistration_hash": e["preregistration_hash"],
                               "negative_control": e.get("negative_control", False),
                               "at": e["ts"]}
                              for e in es if e["event"] == EVENT_PREREG],
            "runs": [{"result_id": e["result_id"], "phase": e["phase"],
                      "status": e["status"], "at": e["ts"]}
                     for e in es if e["event"] == EVENT_RUN],
            "challenges": [{"run_id": e["run_id"], "verdict": e["verdict"]}
                           for e in es if e["event"] == EVENT_CHALLENGE],
            "n_events": len(es),
            "chain_intact": ok,
            "chain_reason": why,
        }

    # --- integrity -------------------------------------------------------------
    def verify_chain(self) -> tuple[bool, str]:
        entries = self._load()
        prev = GENESIS
        for e in entries:
            if e.get("prev_hash") != prev:
                return False, f"seq {e.get('seq')}: prev_hash mismatch"
            if e.get("entry_hash") != _entry_hash(e):
                return False, f"seq {e.get('seq')}: entry_hash mismatch"
            prev = e["entry_hash"]
        return True, "chain intact"


def research_journal_status(journal: str | ResearchJournal, strategy_id: str,
                            version: int) -> dict:
    """Module-level ``research_journal_status(strategy_id, version)`` tool."""
    j = journal if isinstance(journal, ResearchJournal) else ResearchJournal(journal)
    return j.status(strategy_id, version)


def require_sealed(journal: ResearchJournal, strategy_id: str, version: int) -> dict:
    """Gate helper: a run set may only proceed against a registered seal."""
    seal = journal.seal_record(strategy_id, version)
    if seal is None:
        raise JournalError(
            f"{strategy_id} v{version}: holdout not sealed — seal before any runs")
    return seal

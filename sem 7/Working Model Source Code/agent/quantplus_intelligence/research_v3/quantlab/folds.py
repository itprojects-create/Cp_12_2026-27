"""W3 walk-forward folds: session-ordered, purged, embargoed. Never random.

Discipline (blueprint §9.2 + handoff §5):
- folds split by EXCHANGE SESSION, not by rows; cross-sectional names on one
  date are one group (correlated observations);
- purge: a training sample is dropped when its label window reaches into the
  validation span (exit_session >= val_start - embargo_sessions), so no
  training label overlaps a validation start;
- embargo: a fixed 10-session information gap in addition to the purge;
- the revealed W2 holdout is QUARANTINED: any span intersecting it is refused
  (W3 never selects on data the previous wave opened).
"""
from __future__ import annotations

from quantplus_intelligence.research_v3.quantlab.contracts import TrainFold

REVEALED_W2_HOLDOUT = ("2024-06-21", "2026-09-17")
EMBARGO_SESSIONS = 10


def _intersects_holdout(a: str, b: str) -> bool:
    lo, hi = REVEALED_W2_HOLDOUT
    return not (b < lo or a > hi)


def purge_ok(label_exit_session: str | None, val_start_session: str,
             embargo_sessions: int = EMBARGO_SESSIONS) -> bool:
    """True when a train row's label end is safely before the val window."""
    if label_exit_session is None:
        return False
    sessions = _index()
    if label_exit_session not in sessions:
        # sessions outside the known calendar cannot be ordered safely:
        # fail closed
        return False
    if val_start_session not in sessions:
        return False
    return sessions[label_exit_session] < sessions[val_start_session] - embargo_sessions


def _index() -> dict[str, int]:
    return _SESSION_INDEX


_SESSION_INDEX: dict[str, int] = {}


def set_session_index(sessions: list[str]) -> None:
    """Install the observed-session calendar (ascending) for purge checks."""
    _SESSION_INDEX.clear()
    for i, s in enumerate(sessions):
        _SESSION_INDEX[s] = i


def make_folds(sessions: list[str], train_start: str, val_start: str,
               val_end: str, n_folds: int, *,
               embargo_sessions: int = EMBARGO_SESSIONS) -> list[TrainFold]:
    """Expanding-window walk-forward folds inside [train_start, val_end].

    Fold k trains on everything before its validation start and validates on
    the next slice; the validation slices tile [val_start, val_end] evenly.
    Refuses spans that touch the quarantined revealed W2 holdout.
    """
    if _intersects_holdout(train_start, val_end):
        raise ValueError(
            "requested span intersects the quarantined revealed W2 holdout "
            f"{REVEALED_W2_HOLDOUT}: W3 must not train, validate or select on it")
    sess = [s for s in sessions if train_start <= s <= val_end]
    if len(sess) < n_folds * 2:
        raise ValueError("not enough sessions for the requested fold count")
    val_sess = [s for s in sess if s >= val_start]
    step = max(1, len(val_sess) // n_folds)
    folds: list[TrainFold] = []
    for k in range(n_folds):
        lo = k * step
        hi = (k + 1) * step if k + 1 < n_folds else len(val_sess)
        chunk = val_sess[lo:hi]
        if not chunk:
            continue
        folds.append(TrainFold(
            fold_id=f"wf{k + 1}",
            train_sessions=(train_start, chunk[0]),
            val_sessions=(chunk[0], chunk[-1]),
            embargo_sessions=embargo_sessions))
    if not folds:
        raise ValueError("no validation sessions in the requested span")
    return folds

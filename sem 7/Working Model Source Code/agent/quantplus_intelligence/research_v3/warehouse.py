"""Point-in-time NSE research warehouse (W1.1) — the V3.1 research-plane data store.

Reads ONLY immutable source archives (never edited in place) into an
append-only SQLite database with explicit provenance on every row:

- ``nse_eod_bhavcopy_2015_2026_full.csv.gz``  — official NSE EOD records
  (D:\\Model\\NEW DATA\\, assembled 2026-09-18 per MANIFEST.md; see
  ``historical_nse_data_coverage_and_rights.md`` for coverage and gaps).
- ``nse_index_membership_history.csv`` + ``nse_symbol_renames.json`` — vendored
  point-in-time membership (CC BY 4.0; Jha, A. 2026, github.com/aditya-jha/
  nse-historical-membership). Attribution is carried on every membership row.
- ``nifty50_tri_history.csv`` — official NSE Nifty 50 *total return* index.

The runtime app's own providers (``app/data/`` in the agent service) stay
untouched; this module is the separate research-plane store per the V3.1
blueprint §5/§14 and reuses their *disclosed semantics* (e.g. the daily-bar
completion rule of ``yfinance_provider``: a daily bar becomes available the
next local day plus the vendor delay).

Five clocks are enforced on every bar (blueprint §5.1):

======================  ===========================================
clock                   meaning
======================  ===========================================
economic period         trading session date
published_at            when the exchange/vendor published the record
first_seen_at           when OUR archive first captured the bytes
available_at            earliest time a strategy may act on the bar
decision time           caller-supplied PIT join key
======================  ===========================================

Every join in this module filters ``available_at <= decision``; data that was
not available at the decision time is returned as an explicit typed miss
(``status="NOT_AVAILABLE_AT_CUTOFF"``), never silently dropped and never
backfilled with later data.

Backtests over pre-archive history are RETROSPECTIVE reconstructions of
contemporaneously-published official records — the warehouse stamps that
distinction on sources and reports must carry it forward. No bar is ever
invented, adjusted, or backfilled here; unknown corporate actions abstain
(``adjustment_factor`` returns ``UNKNOWN``).
"""
from __future__ import annotations

import csv
import gzip
import hashlib
import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

# ---------------------------------------------------------------------------
# Configuration (env-overridable; defaults point at the audited local archives)
# ---------------------------------------------------------------------------

IST = timezone(timedelta(hours=5, minutes=30))
DAILY_BAR_DELAY_MIN = 15  # matches agent-service yfinance_provider guard

BHAVCOPY_PATH = os.environ.get("QP_BHAVCOPY_PATH") or r"D:\Model\NEW DATA\nse_eod_bhavcopy_2015_2026_full.csv.gz"
MEMBERSHIP_PATH = os.environ.get("QP_PIT_MEMBERSHIP_PATH") or r"D:\Model\data\reference\nse_index_membership_history.csv"
RENAMES_PATH = os.environ.get("QP_PIT_RENAMES_PATH") or r"D:\Model\data\reference\nse_symbol_renames.json"
NIFTY50_TRI_PATH = os.environ.get("QP_NIFTY50_TRI_PATH") or r"D:\Model\NEW DATA\nifty50_tri_history.csv"
YF_CACHE_DIR = os.environ.get("QP_YF_CACHE_DIR") or r"D:\QP\agent-service\data\yf_cache"

# Default warehouse file: <package>/../../data/research_v3/warehouse.sqlite3
# (i.e. backend-extension/data/research_v3/ in the dev repo), overridable for
# tests which always pass their own tmp path.
PKG_ROOT = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB = os.environ.get("QP_RESEARCH_V3_DB") or os.path.join(
    PKG_ROOT, os.pardir, os.pardir, os.pardir, "data", "research_v3", "warehouse.sqlite3")

# Archive provenance (recorded in pit_source_integrity.json; MANIFEST.md date)
BHAVCOPY_ARCHIVE_BUILT_ON = "2026-09-18"  # MANIFEST.md: India market data extraction

ATTRIBUTION_MEMBERSHIP = (
    "Membership: Jha, A. (2026). NSE Historical Membership (Point-in-Time). "
    "github.com/aditya-jha/nse-historical-membership. Derived from public NSE "
    "Indices Limited press releases and NSE Exchange circulars. CC BY 4.0."
)
STRICT_SOURCES = frozenset({"press_release", "merger", "amendment"})
UNIVERSE_INDEX_IDS = {"nifty50": "217", "nifty500": "221"}
_INDEX_ID_TO_UNIVERSE = {v: k for k, v in UNIVERSE_INDEX_IDS.items()}
OPEN_ENDED = "9999-12-31"

SOURCE_CLASS_BHAVCOPY = "OFFICIAL_EXCHANGE_RECORD"       # contemporaneously published, archived later
SOURCE_CLASS_YF = "VENDOR_RECONSTRUCTION"               # adjusted vendor series; disclosed basis
RETROSPECTIVE_NOTE = (
    "Any simulated decision on pre-archive history is a RETROSPECTIVE "
    "reconstruction, not a contemporaneous prediction; reports must label it so."
)

# ---------------------------------------------------------------------------
# Typed result records
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Bar:
    session: str          # YYYY-MM-DD (economic period)
    symbol: str
    series: str
    isin: str
    open_paise: int
    high_paise: int
    low_paise: int
    close_paise: int
    prev_close_paise: int | None
    volume: int
    value_paise: int
    trades: int
    source_id: str
    published_at: str     # session date: official EOD publication instant (date)
    first_seen_at: str    # archive capture date
    available_at: str     # ISO instant: session + 1 local day + vendor delay
    adjustment_basis: str
    source_class: str


@dataclass(frozen=True)
class MembershipSpell:
    universe_id: str
    index_id: str
    symbol: str
    valid_from: str
    valid_to: str | None
    source: str
    strict: bool
    source_class: str = "PRESS_RELEASE_RECONSTRUCTION"


@dataclass(frozen=True)
class PitResult:
    """Typed PIT join outcome: hits + explicit status, never a silent empty."""
    status: str  # OK | NOT_AVAILABLE_AT_CUTOFF | UNKNOWN_SYMBOL | PARTIAL | UNKNOWN
    rows: tuple
    meta: dict


# ---------------------------------------------------------------------------
# Connection + schema (append-only; INSERT OR IGNORE everywhere)
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS ingestion_runs (
  run_id TEXT PRIMARY KEY, source_id TEXT NOT NULL, source_path TEXT NOT NULL,
  source_sha256 TEXT NOT NULL, rows_ingested INTEGER NOT NULL,
  rows_ignored_duplicates INTEGER NOT NULL DEFAULT 0,
  ingested_at TEXT NOT NULL, provenance_class TEXT NOT NULL, note TEXT
);
CREATE TABLE IF NOT EXISTS instruments (
  symbol TEXT NOT NULL, isin TEXT NOT NULL, series_codes TEXT NOT NULL,
  first_session TEXT NOT NULL, last_session TEXT NOT NULL, source_id TEXT NOT NULL,
  PRIMARY KEY (symbol, isin)
);
CREATE TABLE IF NOT EXISTS daily_bars (
  session TEXT NOT NULL, symbol TEXT NOT NULL, series TEXT NOT NULL, isin TEXT NOT NULL,
  open_paise INTEGER NOT NULL, high_paise INTEGER NOT NULL, low_paise INTEGER NOT NULL,
  close_paise INTEGER NOT NULL, prev_close_paise INTEGER,
  volume INTEGER NOT NULL, value_paise INTEGER NOT NULL, trades INTEGER NOT NULL,
  source_id TEXT NOT NULL, first_seen_at TEXT NOT NULL, available_at TEXT NOT NULL,
  adjustment_basis TEXT NOT NULL, source_class TEXT NOT NULL,
  PRIMARY KEY (session, symbol, series)
);
CREATE INDEX IF NOT EXISTS idx_bars_symbol_avail
  ON daily_bars(symbol, series, available_at, session);
CREATE TABLE IF NOT EXISTS membership_spells (
  index_id TEXT NOT NULL, universe_id TEXT NOT NULL, symbol TEXT NOT NULL,
  valid_from TEXT NOT NULL, valid_to TEXT, source TEXT NOT NULL, strict INTEGER NOT NULL,
  source_hash TEXT NOT NULL, attribution TEXT NOT NULL,
  PRIMARY KEY (index_id, symbol, valid_from, source)
);
CREATE TABLE IF NOT EXISTS symbol_renames (
  old_symbol TEXT NOT NULL, new_symbol TEXT NOT NULL, effective_date TEXT NOT NULL,
  source TEXT NOT NULL, PRIMARY KEY (old_symbol, new_symbol, effective_date)
);
CREATE TABLE IF NOT EXISTS benchmark_bars (
  index_code TEXT NOT NULL, session TEXT NOT NULL, tri_value REAL NOT NULL,
  source_id TEXT NOT NULL, first_seen_at TEXT NOT NULL, adjustment_basis TEXT NOT NULL,
  PRIMARY KEY (index_code, session)
);
CREATE TABLE IF NOT EXISTS corporate_actions (
  symbol TEXT NOT NULL, kind TEXT NOT NULL, effective_date TEXT NOT NULL,
  factor REAL NOT NULL, old_symbol TEXT, new_symbol TEXT, source TEXT NOT NULL,
  verified INTEGER NOT NULL, PRIMARY KEY (symbol, kind, effective_date)
);
CREATE TABLE IF NOT EXISTS fee_schedules (
  schedule_id TEXT NOT NULL, effective_from TEXT NOT NULL, kind TEXT NOT NULL,
  spec_json TEXT NOT NULL, source TEXT NOT NULL,
  PRIMARY KEY (schedule_id, effective_from, kind)
);
CREATE TABLE IF NOT EXISTS feature_snapshots (
  snapshot_id TEXT PRIMARY KEY, symbol TEXT NOT NULL, horizon TEXT NOT NULL,
  decision_ts TEXT NOT NULL, feature_set_version TEXT NOT NULL, data_version TEXT NOT NULL,
  missingness_json TEXT NOT NULL, asof_join_json TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS target_labels (
  label_id TEXT PRIMARY KEY, symbol TEXT NOT NULL, horizon_sessions INTEGER NOT NULL,
  decision_ts TEXT NOT NULL, entry_session TEXT, entry_ref_price_paise INTEGER,
  exit_session TEXT, exit_ref_price_paise INTEGER,
  entry_execution_policy TEXT NOT NULL, exit_execution_policy TEXT NOT NULL,
  return_basis TEXT NOT NULL, adjustment_treatment TEXT NOT NULL,
  fee_schedule_id TEXT, matures_at TEXT, status TEXT NOT NULL, created_at TEXT NOT NULL
);
"""


def connect(db_path: str | None = None) -> sqlite3.Connection:
    path = os.path.abspath(db_path or DEFAULT_DB)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(_SCHEMA)
    conn.commit()
    return conn


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _record_run(conn: sqlite3.Connection, source_id: str, source_path: str,
                rows_ingested: int, rows_ignored: int, provenance_class: str,
                note: str = "") -> dict:
    sha = _sha256(source_path)
    cur = conn.execute(
        "INSERT OR IGNORE INTO ingestion_runs VALUES (?,?,?,?,?,?,?,?,?)",
        (f"{source_id}:{sha[:16]}", source_id, source_path, sha, rows_ingested,
         rows_ignored, datetime.now(timezone.utc).isoformat(), provenance_class, note))
    conn.commit()
    row = conn.execute("SELECT run_id FROM ingestion_runs WHERE source_sha256=?", (sha,)).fetchone()
    return {"run_id": row[0], "source_sha256": sha, "rows_ingested": rows_ingested,
            "rows_ignored_duplicates": rows_ignored,
            "duplicate_ingestion_skipped": bool(cur.rowcount == 0)}


# ---------------------------------------------------------------------------
# Ingestion (append-only, idempotent, source-hashed)
# ---------------------------------------------------------------------------


def _paise(value: str) -> int:
    """Official bhavcopy prices/values are rupees with <=2 decimals -> exact paise.

    Parsed as Decimal (float multiplication of large values loses ULPs).
    """
    v = __import__("decimal").Decimal(value)
    scaled = v * 100
    if scaled != scaled.to_integral_value():
        raise ValueError(f"price {value!r} is not representable in exact paise")
    return int(scaled)


def _is_iso_date(value: str) -> bool:
    """True only for a real calendar date in strict ``YYYY-MM-DD`` form.

    Source renames carry placeholders like ``2026-01-XX`` (month known, day
    unknown) — those are NOT dates and must fail closed wherever a date gates
    behaviour (display naming, verified corporate actions).
    """
    try:
        datetime.strptime(value, "%Y-%m-%d")
        return len(value) == 10
    except (ValueError, TypeError):
        return False


def ingest_bhavcopy(conn: sqlite3.Connection, path: str | None = None,
                    batch_size: int = 200_000) -> dict:
    """Ingest the official NSE EOD archive. Idempotent per source hash.

    ``available_at`` = session + 1 local calendar day + 15 min (IST) — the same
    conservative completion rule the runtime uses for daily bars: the decision
    can act no earlier than the day after the session, so no same-session
    leakage is possible even if the file actually published earlier that evening.
    """
    path = path or BHAVCOPY_PATH
    if not os.path.exists(path):
        raise FileNotFoundError(f"bhavcopy archive missing: {path} — no synthetic bars")
    opened = gzip.open(path, "rt", encoding="utf-8", newline="")
    reader = csv.DictReader(opened)
    required = {"date", "symbol", "series", "open", "high", "low", "close",
                "prevclose", "volume", "value", "trades", "isin"}
    if not required.issubset(reader.fieldnames or ()):
        raise ValueError(f"unexpected bhavcopy schema: {reader.fieldnames}")
    first_seen = BHAVCOPY_ARCHIVE_BUILT_ON
    adjustment = "unadjusted official bhavcopy prices (raw exchange record)"
    now = datetime.now(timezone.utc).isoformat()
    instruments: dict[tuple[str, str], list[str]] = {}
    batch: list[tuple] = []
    rows = dups = 0

    def _flush():
        nonlocal dups
        before = conn.execute("SELECT COUNT(*) FROM daily_bars").fetchone()[0]
        conn.executemany(
            "INSERT OR IGNORE INTO daily_bars VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", batch)
        conn.commit()
        after = conn.execute("SELECT COUNT(*) FROM daily_bars").fetchone()[0]
        dups += len(batch) - (after - before)
        batch.clear()

    for row in reader:
        session = row["date"][:10]
        symbol = row["symbol"].strip().upper()
        series = row["series"].strip().upper()
        isin = row["isin"].strip()
        available = (datetime.fromisoformat(session).replace(tzinfo=IST)
                     + timedelta(days=1, minutes=DAILY_BAR_DELAY_MIN)).isoformat()
        batch.append((
            session, symbol, series, isin,
            _paise(row["open"]), _paise(row["high"]), _paise(row["low"]),
            _paise(row["close"]),
            _paise(row["prevclose"]) if row["prevclose"] else None,
            int(row["volume"] or 0), _paise(row["value"] or 0), int(row["trades"] or 0),
            "nse_eod_bhavcopy_2015_2026_full", first_seen, available,
            adjustment, SOURCE_CLASS_BHAVCOPY))
        rows += 1
        instruments.setdefault((symbol, isin), [])
        instruments[(symbol, isin)].append((session, series))
        if len(batch) >= batch_size:
            _flush()
    if batch:
        _flush()
    opened.close()
    for (symbol, isin), spans in instruments.items():
        sessions = sorted(s for s, _ in spans)
        conn.execute(
            "INSERT OR IGNORE INTO instruments VALUES (?,?,?,?,?,?)",
            (symbol, isin, ",".join(sorted({s for _, s in spans})),
             sessions[0], sessions[-1], "nse_eod_bhavcopy_2015_2026_full"))
    conn.commit()
    meta = _record_run(conn, "nse_eod_bhavcopy_2015_2026_full", path, rows, dups,
                       SOURCE_CLASS_BHAVCOPY, RETROSPECTIVE_NOTE)
    meta["first_seen_at_of_archive"] = first_seen
    return meta


def ingest_membership(conn: sqlite3.Connection, path: str | None = None,
                      renames_path: str | None = None) -> dict:
    """Ingest the vendored PIT membership history + rename chain. Idempotent."""
    path = path or MEMBERSHIP_PATH
    renames_path = renames_path or RENAMES_PATH
    if not os.path.exists(path):
        raise FileNotFoundError(f"membership history missing: {path} — no silent universe")
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    n = 0
    for i, r in enumerate(rows):
        sym = (r.get("symbol") or "").strip().upper()
        idx = (r.get("index_id") or "").strip()
        frm = (r.get("valid_from") or "")[:10]
        to = (r.get("valid_to") or "")[:10] or None
        src = (r.get("source") or "").strip()
        if not sym or len(frm) != 10 or (to is not None and len(to) != 10):
            continue  # malformed rows are excluded, counted in meta below
        conn.execute(
            "INSERT OR IGNORE INTO membership_spells VALUES (?,?,?,?,?,?,?,?,?)",
            (idx, _INDEX_ID_TO_UNIVERSE.get(idx, idx), sym, frm, to, src,
             1 if src in STRICT_SOURCES else 0,
             hashlib.sha256(json.dumps(r, sort_keys=True).encode()).hexdigest()[:16],
             ATTRIBUTION_MEMBERSHIP))
        n += 1
    if os.path.exists(renames_path):
        with open(renames_path, encoding="utf-8-sig") as f:
            doc = json.load(f)
        entries = [e for e in (doc.get("renames", []) if isinstance(doc, dict) else [])
                   if isinstance(e, dict) and e.get("old") and e.get("new")]
        # Re-derive this block from the immutable source on every run: drop the
        # rows earlier builds wrote under the pre-fix gates (undated /
        # placeholder effective dates must not persist as verified actions).
        # Scoped: symbol_renames is single-source; corporate_actions rows from
        # any other source are untouched.
        conn.execute("DELETE FROM symbol_renames")
        conn.execute(
            "DELETE FROM corporate_actions WHERE source='nse_symbol_renames.json'")
        n_renames = n_undated = n_bad_date = 0
        for e in entries:
            eff = (e.get("effective_date") or "")
            conn.execute(
                "INSERT OR IGNORE INTO symbol_renames VALUES (?,?,?,?)",
                (e["old"].upper(), e["new"].upper(), eff, "nse_symbol_renames.json"))
            n_renames += 1
            if eff and not _is_iso_date(eff):
                n_bad_date += 1  # e.g. '2026-01-XX': month known, day unknown
            elif not eff:
                n_undated += 1   # rename real, date unverified in the source
            # A rename is a corporate action (symbol_change) with factor 1 ONLY
            # when its effective date is a verified calendar date.
            if _is_iso_date(eff):
                conn.execute(
                    "INSERT OR IGNORE INTO corporate_actions VALUES (?,?,?,?,?,?,?,?)",
                    (e["new"].upper(), "symbol_change", eff, 1.0,
                     e["old"].upper(), e["new"].upper(), "nse_symbol_renames.json", 1))
        rename_meta = {"renames_ingested": n_renames,
                       "renames_undated": n_undated,
                       "renames_invalid_date_strings": n_bad_date}
    else:
        rename_meta = {}
    conn.commit()
    meta = _record_run(conn, "nse_index_membership_history", path, n, 0,
                       "PRESS_RELEASE_RECONSTRUCTION", ATTRIBUTION_MEMBERSHIP)
    meta.update(rename_meta)
    malformed = len(rows) - n
    if malformed:
        meta["malformed_rows_excluded"] = malformed
    return meta


def ingest_nifty50_tri(conn: sqlite3.Connection, path: str | None = None) -> dict:
    """Ingest the official Nifty 50 total-return history (``dd Mon yyyy`` rows)."""
    path = path or NIFTY50_TRI_PATH
    if not os.path.exists(path):
        raise FileNotFoundError(f"TRI history missing: {path} — no synthetic benchmark")
    pts: list[tuple[str, float]] = []
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not {"date", "index_name", "total_returns_index"}.issubset(reader.fieldnames or ()):
            raise ValueError(f"unexpected TRI schema: {reader.fieldnames}")
        for r in reader:
            try:
                d = datetime.strptime(r["date"].strip(), "%d %b %Y").strftime("%Y-%m-%d")
                pts.append((d, float(r["total_returns_index"])))
            except (ValueError, KeyError):
                raise ValueError(f"unparseable TRI row: {r}") from None
    pts.sort(key=lambda p: p[0])
    dedup: dict[str, float] = {}
    for d, v in pts:
        dedup[d] = v  # ascending order: keep LAST row per date (tri_benchmark semantics)
    n = dups = 0
    for d, v in dedup.items():
        cur = conn.execute("INSERT OR IGNORE INTO benchmark_bars VALUES (?,?,?,?,?,?)",
                           ("NIFTY50_TRI", d, v, "nifty50_tri_history", "2026-09-18",
                            "official NSE total-return index (dividends reinvested)"))
        n += 1
        if cur.rowcount == 0:
            dups += 1
    conn.commit()
    meta = _record_run(conn, "nifty50_tri_history", path, n, dups + (len(pts) - len(dedup)),
                       "OFFICIAL_EXCHANGE_RECORD", "T+1 join semantics; price index kept separate; "
                       "duplicate dates keep the last row")
    return meta


def ingest_fee_schedules(conn: sqlite3.Connection) -> dict:
    """Mirror the tested charge schedules into the warehouse (fee_schedule entity)."""
    from . import economics
    n = 0
    for s in economics.SCHEDULES:
        conn.execute("INSERT OR IGNORE INTO fee_schedules VALUES (?,?,?,?,?)",
                     (s["id"], s["effective_from"], "statutory_exchange",
                      json.dumps({k: v for k, v in s.items() if k != "id"}, sort_keys=True),
                      "src/lib/paper-fees.ts mirror (integer paise)"))
        n += 1
    for broker, comps in economics.BROKER_COMPONENTS.items():
        for c in comps:
            conn.execute("INSERT OR IGNORE INTO fee_schedules VALUES (?,?,?,?,?)",
                         (c["id"], c["effective_from"], f"broker_component:{broker}",
                          json.dumps(c, sort_keys=True),
                          "research_v3.economics BROKER_COMPONENTS mirror"))
            n += 1
    conn.commit()
    return {"rows": n, "note": "fee truth stays in economics.py; warehouse records the schedule"}


# ---------------------------------------------------------------------------
# PIT joins (hard available_at <= decision rule)
# ---------------------------------------------------------------------------


def alias_symbols_at(conn: sqlite3.Connection, symbol: str, date_iso: str = "") -> list[str]:
    """Raw symbols whose canonical form is ``symbol`` (instrument identity lookup).

    Bars follow the INSTRUMENT, not the name: a rename changes the trading
    symbol, not the company, so a canonical-symbol query always includes its
    pre-rename raw names. (Membership display semantics, in contrast, gate the
    name by the rename's effective date — see ``canonical_symbol``.) The ISIN
    carried on every bar is the hard identity; alias-by-rename is the
    fallback while ISIN-keyed joins land with the W2 strategy panel.
    """
    target = symbol.strip().upper()
    out = [target]
    for old, new, _eff in conn.execute(
            "SELECT old_symbol, new_symbol, effective_date FROM symbol_renames "
            "ORDER BY effective_date"):
        # identity needs no date: a rename (dated or not) proves the two names
        # are the same instrument. No-op rows (old == new, e.g. MFSL->MFSL in
        # the source) are skipped so the alias set has no duplicates.
        if new == target and old != target and old not in out:
            out.append(old)
    return out


def bars_asof(conn: sqlite3.Connection, symbol: str, decision_ts: str,
              *, series: str = "EQ", end_session: str | None = None,
              limit: int = 5000) -> PitResult:
    """Bars usable at ``decision_ts`` (strictly ``available_at <= decision_ts``),
    joined across the instrument's alias set (bars follow the instrument
    through renames — see ``alias_symbols_at``).

    Returns a typed miss when nothing was available — never a fabricated bar
    and never a later bar pulled back in time.
    """
    symbol = symbol.strip().upper()
    if len(decision_ts) < 10:
        raise ValueError("decision_ts must be ISO with at least a date")
    aliases = alias_symbols_at(conn, symbol, decision_ts)
    marks = ",".join("?" * len(aliases))
    sql = [f"SELECT session, open_paise, high_paise, low_paise, close_paise, "
           f"prev_close_paise, volume, value_paise, trades, available_at, isin, series "
           f"FROM daily_bars WHERE symbol IN ({marks}) AND available_at<=?"]
    args: list = [*aliases, decision_ts]
    if series:
        sql.append("AND series=?")
        args.append(series)
    if end_session:
        sql.append("AND session<=?")
        args.append(end_session)
    sql.append("ORDER BY session DESC LIMIT ?")
    args.append(limit)
    rows = conn.execute(" ".join(sql), args).fetchall()
    rows = tuple(reversed(rows))  # ascending by session
    if not rows:
        known = conn.execute(
            f"SELECT COUNT(*) FROM daily_bars WHERE symbol IN ({marks}) AND series=?",
            (*aliases, series)).fetchone()[0]
        status = "UNKNOWN_SYMBOL" if not known else "NOT_AVAILABLE_AT_CUTOFF"
        return PitResult(status, (), {"symbol": symbol, "decision_ts": decision_ts,
                                      "aliases": aliases, "bars_known_at_source": known})
    return PitResult("OK", rows, {"symbol": symbol, "decision_ts": decision_ts,
                                  "aliases": aliases, "n": len(rows)})


def sessions(conn: sqlite3.Connection) -> list[str]:
    """Distinct ingested sessions (derived calendar: what the archive proves)."""
    return [r[0] for r in conn.execute(
        "SELECT DISTINCT session FROM daily_bars ORDER BY session")]


def next_session_after(conn: sqlite3.Connection, session: str) -> str | None:
    """Next *observed* session strictly after the given one, or None at the edge."""
    row = conn.execute(
        "SELECT MIN(session) FROM daily_bars WHERE session>?", (session,)).fetchone()
    return row[0] if row and row[0] else None


def canonical_symbol(conn: sqlite3.Connection, symbol: str, date_iso: str) -> str:
    """Date-aware rename for display naming: old -> new once a *verified*
    effective date has passed.

    Fail-closed on dates: renames whose ``effective_date`` is undated or a
    placeholder (e.g. ``2026-01-XX``) NEVER change the displayed name — an
    unverified date cannot justify retroactively renaming history. They still
    join instrument identity via ``alias_symbols_at``, where the date is
    irrelevant.
    """
    sym = symbol.strip().upper()
    for old, new, eff in conn.execute(
            "SELECT old_symbol, new_symbol, effective_date FROM symbol_renames "
            "ORDER BY effective_date"):
        if sym == old and _is_iso_date(eff) and eff <= date_iso[:10]:
            sym = new
    return sym


def members_at(conn: sqlite3.Connection, universe_id: str, decision_date: str,
               *, strict: bool = False) -> PitResult:
    """As-of membership: spells effective AND knowable by ``decision_date``.

    ``strict=True`` keeps only press_release/merger/amendment rows (thin
    coverage pre-2018); default discloses weaker rows (``snapshot_floor`` =
    backward-walk from current snapshots, an upper bound on membership).
    Every call carries the attribution string. UNKNOWN when the universe has
    no coverage at/before the date — the caller must abstain, never guess.
    """
    d = decision_date[:10]
    rows = conn.execute(
        "SELECT symbol, valid_from, valid_to, source, strict FROM membership_spells "
        "WHERE universe_id=?", (universe_id,)).fetchall()
    if not rows:
        return PitResult("UNKNOWN", (), {"universe_id": universe_id,
                                         "reason": "no membership history for this universe"})
    earliest = min(r[1] for r in rows)
    if d < earliest:
        return PitResult("UNKNOWN", (), {"universe_id": universe_id,
                                         "reason": f"history starts {earliest}",
                                         "attribution": ATTRIBUTION_MEMBERSHIP})
    members: set[str] = set()
    weak = 0
    for symbol, frm, to, source, is_strict in rows:
        if strict and not is_strict:
            continue
        if frm <= d and (to is None or d <= to):
            members.add(canonical_symbol(conn, symbol, d))
            if not is_strict:
                weak += 1
    status = "UNKNOWN" if not members else ("VERIFIED" if weak == 0 else "PARTIAL")
    return PitResult(status, tuple(sorted(members)),
                     {"universe_id": universe_id, "decision_date": d,
                      "weak_rows_included": weak, "strict": strict,
                      "attribution": ATTRIBUTION_MEMBERSHIP,
                      "limitation": "snapshot_floor spells are backward-walk upper bounds "
                                    "until the first dated press-release row; disclosed, "
                                    "never treated as exchange-official spells"})


def panel_asof(conn: sqlite3.Connection, universe_id: str, decision_date: str,
               *, strict: bool = False, require_bars: bool = True,
               series: str = "EQ") -> PitResult:
    """Members at ``decision_date`` cross-joined with bars available then.

    ``require_bars`` drops names with no bar available at the cutoff and
    reports them explicitly (documented exclusion — never a silent drop and
    never a survivorship-prone current-members substitution).
    """
    mem = members_at(conn, universe_id, decision_date, strict=strict)
    if mem.status == "UNKNOWN":
        return mem
    out, excluded = [], []
    for symbol in mem.rows:
        if not require_bars:
            out.append({"symbol": symbol, "bars": None})
            continue
        res = bars_asof(conn, symbol, f"{decision_date}T23:59:59+05:30", series=series)
        if res.status != "OK":
            excluded.append({"symbol": symbol, "reason": res.status})
        else:
            last = res.rows[-1]
            out.append({"symbol": symbol, "close_paise": last[4],
                        "last_available_session": last[0]})
    meta = dict(mem.meta)
    meta["n_excluded_no_bars"] = len(excluded)
    meta["excluded_no_bars"] = excluded[:50]
    return PitResult(mem.status, tuple(out), meta)


# ---------------------------------------------------------------------------
# Benchmark (official TRI; price index kept separate)
# ---------------------------------------------------------------------------


def benchmark_total_return(conn: sqlite3.Connection, index_code: str,
                           start_iso: str, end_iso: str) -> dict:
    """Official TRI total return over [start, end] with T+1 joins both ends.

    Fails loudly when the window is uncovered — never a synthetic benchmark.
    """
    pts = conn.execute("SELECT session, tri_value FROM benchmark_bars WHERE index_code=? "
                       "ORDER BY session", (index_code,)).fetchall()
    if not pts:
        raise ValueError(f"benchmark {index_code!r} not ingested — ingest first, never synthesise")

    def at_or_before(d: str) -> tuple[str, float]:
        best = None
        for s, v in pts:
            if s <= d[:10]:
                best = (s, v)
            else:
                break
        if best is None:
            raise ValueError(f"TRI uncovered before {d}")
        return best

    s0, v0 = at_or_before(start_iso)
    s1, v1 = at_or_before(end_iso)
    total = v1 / v0 - 1
    years = (datetime.fromisoformat(end_iso[:10]) - datetime.fromisoformat(start_iso[:10])).days / 365.25
    return {"index": index_code, "start_session": s0, "end_session": s1,
            "tri_start": v0, "tri_end": v1,
            "total_return": total,  # full precision; rounding is presentation-only
            "cagr": (1 + total) ** (1 / years) - 1 if years > 0 and total > -1 else None,
            "basis": "total-return (dividends reinvested); price index is a separate series"}


# ---------------------------------------------------------------------------
# Corporate actions (UNKNOWN abstains; never imputed)
# ---------------------------------------------------------------------------


def adjustment_factor(conn: sqlite3.Connection, symbol: str, date_iso: str) -> tuple[float, str]:
    """Cumulative *verified* adjustment factor for ``date_iso``.

    Unknown periods abstain with ``(1.0, "UNKNOWN")`` — never an invented
    adjustment (mirrors the runtime's corporate_actions contract).
    """
    sym = canonical_symbol(conn, symbol, date_iso)
    rows = conn.execute(
        "SELECT factor, verified FROM corporate_actions WHERE symbol=? AND effective_date<=?",
        (sym, date_iso[:10])).fetchall()
    any_rows = conn.execute("SELECT COUNT(*) FROM corporate_actions WHERE symbol=?",
                            (sym,)).fetchone()[0]
    if not any_rows:
        return 1.0, "UNKNOWN"
    factor = 1.0
    for f, verified in rows:
        if verified:
            factor *= float(f)
    return factor, "VERIFIED"


# ---------------------------------------------------------------------------
# Coverage report (feeds historical_nse_data_coverage_and_rights.md)
# ---------------------------------------------------------------------------


def coverage_report(conn: sqlite3.Connection) -> dict:
    """Deterministic coverage/status of every ingested source + known gaps."""
    per_year: dict[str, int] = {}
    for (d,) in conn.execute("SELECT DISTINCT session FROM daily_bars ORDER BY session"):
        per_year[d[:4]] = per_year.get(d[:4], 0) + 1
    n_symbols = conn.execute("SELECT COUNT(DISTINCT symbol) FROM daily_bars").fetchone()[0]
    series_counts = dict(conn.execute(
        "SELECT series, COUNT(*) FROM daily_bars GROUP BY series ORDER BY COUNT(*) DESC"))
    runs = [dict(zip(("run_id", "source_id", "source_sha256", "rows_ingested", "ingested_at"),
                     r)) for r in conn.execute(
        "SELECT run_id, source_id, source_sha256, rows_ingested, ingested_at FROM ingestion_runs")]
    tri = conn.execute("SELECT COUNT(*), MIN(session), MAX(session) FROM benchmark_bars "
                       "WHERE index_code='NIFTY50_TRI'").fetchone()
    mem = conn.execute("SELECT COUNT(*), MIN(valid_from) FROM membership_spells").fetchone()
    # Named real-archive gap (2026-09-18 partial run): only meaningful when the
    # real bhavcopy source was actually ingested — synthetic fixtures are N/A.
    real_ingested = bool(conn.execute(
        "SELECT 1 FROM ingestion_runs WHERE source_id='nse_eod_bhavcopy_2015_2026_full' "
        "AND source_path=?", (BHAVCOPY_PATH,)).fetchone())
    gap_2024 = conn.execute(
        "SELECT COUNT(DISTINCT session) FROM daily_bars WHERE session>='2024-01-01' "
        "AND session<='2024-06-20'").fetchone()[0]
    if not real_ingested:
        gap_2024_state = "NOT_APPLICABLE (real bhavcopy source not ingested in this warehouse)"
    elif gap_2024 == 0:
        gap_2024_state = "MISSING_SPAN"
    else:
        gap_2024_state = "PRESENT"
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sessions_total": per_year and sum(per_year.values()),
        "sessions_per_year": per_year,
        "distinct_symbols": n_symbols,
        "rows_by_series": series_counts,
        "ingestion_runs": runs,
        "benchmark_nifty50_tri": {"rows": tri[0], "first": tri[1], "last": tri[2]},
        "membership_spells": {"rows": mem[0], "first_valid_from": mem[1],
                              "attribution": ATTRIBUTION_MEMBERSHIP},
        "known_gaps": {
            "2024-01-01_to_2024-06-20": {
                "sessions_ingested": gap_2024, "state": gap_2024_state,
                "cause": "2026-09-18 archive run was partial for H1 2024 "
                         "(archive/nse_eod_bhavcopy_103day_partial_2024-06-21_2024-11-18.csv.gz)"},
            "2026-09-18_onward": {
                "status": "MISSING_SPAN",
                "cause": "bhavcopy archive ends 2026-09-17; newer sessions live in "
                         "yf_cache vendor snapshots (VENDOR_RECONSTRUCTION) until a "
                         "newer official archive is ingested"},
        },
        "rights": {
            "bhavcopy": "official NSE EOD records, personal-research use per MANIFEST.md",
            "membership": "CC BY 4.0 (attribution carried on every row)",
            "tri": "official NSE Indices history via niftyindices.com",
            "yf_cache": "Yahoo Finance vendor snapshots; labelled VENDOR_RECONSTRUCTION, "
                        "fallback only",
        },
    }


def instrument_lifecycle(conn: sqlite3.Connection, symbol: str) -> dict:
    """Listing/delisting evidence from the official archive (no invention)."""
    sym = symbol.strip().upper()
    rows = conn.execute(
        "SELECT first_session, last_session, series_codes, isin FROM instruments "
        "WHERE symbol=? ", (sym,)).fetchall()
    if not rows:
        raise ValueError(f"unknown instrument {sym!r} in warehouse")
    first = min(r[0] for r in rows)
    last = max(r[1] for r in rows)
    return {"symbol": sym, "first_session": first, "last_session": last,
            "series_codes": sorted({s for r in rows for s in r[2].split(",")}),
            "isins": sorted({r[3] for r in rows}),
            "evidence": "first/last sessions observed in the ingested official archive; "
                        "archive end dates are capture limits, NOT delisting proof"}

"""V3.1 forward-only research stream (Wave 6).

Modules:
- contracts:       typed immutable records with explicit evidence surfaces
- ledger:          append-only hash-chained JSONL, exactly-once, crash recovery
- preregistration: sealed ForwardProtocol before first signal; admissibility gate
- fee_sources:     date-versioned broker plan components (verified 2026-11-14)
- paper_book:      research-namespace integer-paise paper account
- signals:         every-candidate decision pipeline (no selective logging)
- benchmarks:      panels A/B/C with honest labels
- worker:          calendar-aware jobs, receipts, missed-run alerts

The runtime application, the user's V2 paper book and broker surfaces are
never imported here; no module in this package can place a real order.
"""
from .contracts import (  # noqa: F401
    ForwardRecord,
    QuoteObservation,
    SignalDecision,
    PaperIntent,
    FillEvent,
    FeeEvent,
    CashFlow,
    CorporateActionEvent,
    ValuationMark,
    BenchmarkMark,
    RiskEvent,
    SessionLock,
    NoSignalRecord,
    AbstentionRecord,
    EligibilityFailureRecord,
    ReportSnapshot,
    PreflightRecord,
    JobReceiptRecord,
    OutcomeObservation,
)
from .ledger import (ForwardLedger, SqliteForwardLedger, LedgerIntegrityError,
                     GENESIS, LEDGER_SCHEMA)  # noqa: F401
from .paper_book import ResearchPaperBook, BookError  # noqa: F401
from .signals import SignalPipeline  # noqa: F401
from .benchmarks import default_verdict, result_panels  # noqa: F401
from .worker import ForwardWorker, ClockSkewError  # noqa: F401
from .preregistration import (  # noqa: F401
    ForwardProtocol,
    OperatorApproval,
    StreamSeal,
    seal_protocol,
    admissibility,
    require_paper_authorization,
    mint_new_stream,
)
